"""Score the live search retrieval code against the frozen eval fixture.

Ranking/admission eval, not a unit test.
It recomputes every score from the FROZEN posting text through the SAME
production seams the app uses — `embed_texts` for documents, `embed_query` for
the parsed query remainder — so nothing is blessed from a prior run and the
benchmark cannot drift as the live corpus changes.

Three checks, all read-only:

0. Query plan contract: the fuzzy predicate must still probe a trigram
   index on the REAL table; a bare `similarity() >= x` seq-scans silently.
1. Parity/retrieval pass. Load the frozen posting fields + freshly-encoded
   vectors into a transaction-local ``CREATE TEMP TABLE jobs`` that SHADOWS the
   real table (temp schema precedes public in search_path), build
   ``search_vector`` with the imported production expression
   (``repo.SEARCH_VECTOR_SQL``), then run the ACTUAL production builders
   (``search.retrieval``: ``match_total``/``candidate_pool``/``fused_candidates``)
   against it and roll back. Real PostgreSQL FTS + pg_trgm + pgvector semantics,
   not a Python re-implementation.
2. Calibration context. For each query, cosine of every labelled posting by
   authored class, plus live corpus cosine percentiles (public.jobs).

    .venv/bin/python -m scripts.eval_search_retrieval
    .venv/bin/python -m scripts.eval_search_retrieval --save out.json

The recorded comparison point lives at
``tests/fixtures/search_retrieval_eval_baseline.json``.
``semantic_only_admitted_total`` and ``no_answer_admitted`` are structurally
zero under textual-only membership, and kept so a regression that readmits
dense membership is loud: a benchmark that cannot fail measures nothing.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
from pathlib import Path

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    ARRAY,
    BigInteger,
    Column,
    Integer,
    MetaData,
    Table,
    Text,
    func,
    literal,
    select,
    text,
)

from tracker.company_discovery import company_names
from tracker.config import get_settings
from tracker.db.models import Job
from tracker.db.queries.jobs import structured_conds
from tracker.db.repo import SEARCH_VECTOR_SQL
from tracker.db.session import get_session_factory
from tracker.search.best_match import exact_title_ids, ranked_conds
from tracker.search.parse import parse_query
from tracker.search.policy import fold_query, identity_probe, resolve_query_kind
from tracker.search.retrieval import (
    candidate_pool,
    fused_candidates,
    fuzzy_predicate,
    identifier_matches,
    match_total,
)
from tracker.semantic import provision
from tracker.semantic.embed import embed_query, embed_texts
from tracker.semantic.manifest import spec_for

FIXTURE = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "search_retrieval_eval.json"

RELEVANT = {"exact", "close", "related"}
_GAIN = {"exact": 3.0, "close": 2.0, "related": 1.0, "irrelevant": 0.0}
_FLOOR_GRID = [0.30, 0.35, 0.40, 0.45, 0.50, 0.55]
_EID_BASE = 9_000_000  # synthetic ids, clear of any real job_feedback/favorite id


def _dot(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=True))


def _dcg(gains: list[float]) -> float:
    from math import log2

    return sum(g / log2(i + 2) for i, g in enumerate(gains))


def _ndcg_at(order_classes: list[str], k: int) -> float:
    gains = [_GAIN[c] for c in order_classes[:k]]
    ideal = sorted(order_classes, key=lambda c: _GAIN[c], reverse=True)
    idcg = _dcg([_GAIN[c] for c in ideal[:k]])
    return _dcg(gains) / idcg if idcg else 0.0


def _temp_jobs_ddl(dim: int) -> str:
    return f"""
        CREATE TEMP TABLE jobs (
            id integer PRIMARY KEY,
            company text NOT NULL,
            req_id text,
            title text,
            url text,
            department text,
            team text,
            description_text text,
            family text,
            track text,
            level_band text,
            level_confidence text DEFAULT 'confirmed',
            workplace_type text DEFAULT 'unknown',
            status text DEFAULT 'open',
            in_scope boolean DEFAULT true,
            domains text[],
            location_groups text[] DEFAULT '{{}}',
            comp_median bigint,
            search_vector tsvector,
            embedding vector({dim})
        )
    """


def _jobs_table(dim: int) -> Table:
    """Core table (fresh MetaData) named `jobs` for typed inserts into the temp table."""
    md = MetaData()
    return Table(
        "jobs",
        md,
        Column("id", Integer, primary_key=True),
        Column("company", Text),
        Column("req_id", Text),
        Column("title", Text),
        Column("url", Text),
        Column("department", Text),
        Column("team", Text),
        Column("description_text", Text),
        Column("family", Text),
        Column("track", Text),
        Column("level_band", Text),
        Column("domains", ARRAY(Text)),
        Column("comp_median", BigInteger),
        Column("embedding", Vector(dim)),
    )


async def _retrieve(session, query_text: str, qvec: list[float] | None) -> dict:
    """Run the production relevance path and return the full admitted ranking.

    Mirrors `relevance_search`'s parse -> merge -> count -> pool -> fuse, but
    with empty explicit params (eval has no UI filters) and no pagination limit,
    so metrics see the whole admitted set. Uses the imported production builders
    — this measures the live code, not a copy of it.
    """
    query_text = fold_query(query_text)  # as `relevance_search` receives it
    # Every named company: the shadow substrate shows them all, as the Board
    # shows the ones a user follows (`best_match.board_company_names`).
    parsed = parse_query(query_text, companies=company_names())
    merged = parsed.structured()  # explicit params are empty in the eval
    remainder = parsed.remainder or query_text

    # Direct identity resolution, exactly as `relevance_search` runs it,
    # including the request's DEFAULT filters (`status="open"`), so the mirror
    # carries the same conds the app sends, not a strictly weaker set.
    # Identifier reads bypass standing visibility (as `ids` reads do); the
    # title probe browses. The shadow substrate is all-visible anyway: the
    # harness measures retrieval with visibility held constant, never the
    # user's current scope config (many frozen rows sit outside any one
    # scope; carrying that in would benchmark a setting).
    request_params = {"status": "open"}
    probe = identity_probe(query_text)
    ident_ids = (
        await identifier_matches(
            session, probe, structured_conds(request_params, browse_visibility=False)
        )
        if probe.is_identifier()
        else []
    )
    title_ids = (
        []
        if ident_ids
        else await exact_title_ids(session, probe.title_key, request_params, query_text)
    )
    kind = resolve_query_kind(
        has_identifier_match=bool(ident_ids), has_exact_title_match=bool(title_ids)
    )
    direct_ids = ident_ids or title_ids

    conds = ranked_conds(merged, remainder)
    matched_total = await match_total(session, conds, remainder)
    pool = candidate_pool(matched_total)
    fused, via_names = fused_candidates(conds, remainder, qvec, pool)
    ranked_total = int(await session.scalar(select(func.count()).select_from(fused)) or 0)

    via_cols = [fused.c[f"via_{n}"] for n in via_names]
    stmt = select(fused.c.id, fused.c.rrf, *via_cols).order_by(
        fused.c.rrf.desc(), fused.c.id.desc()
    )
    rows = (await session.execute(stmt)).all()
    ranked = [
        (int(r[0]), float(r[1]), {via_names[i] for i in range(len(via_names)) if r[2 + i]})
        for r in rows
    ]
    return {
        "ranked": ranked,
        "matched_total": int(matched_total),
        "ranked_total": ranked_total,
        "pool": pool,
        "ranking_truncated": matched_total > pool,
        "parsed": parsed.as_echo(),
        "query_kind": kind,
        "direct_ids": direct_ids,
    }


async def run(fixture: dict, save: Path | None) -> dict:
    settings = get_settings()
    dim = settings.embedding_dim
    postings = fixture["postings"]
    queries = fixture["queries"]
    labels = fixture["labels"]

    # label lookup + per-query relevant totals (pool = every posting).
    cls_of: dict[tuple[str, str], str] = {(lab["query"], lab["posting"]): lab["class"] for lab in labels}
    rel_total: dict[str, int] = {}
    for q in queries:
        rel_total[q["key"]] = sum(
            1 for p in postings if cls_of.get((q["key"], p["key"]), "irrelevant") in RELEVANT
        )

    # --- tier provenance (never silently certify only this machine's tier) ---- #
    spec = spec_for(settings.embedding_model)
    tier = provision.resolve_tier()
    tiers_defined = list(spec.tiers)
    tiers_not_measured = [t for t in tiers_defined if t != tier]

    # --- encode through production seams -------------------------------------- #
    doc_vecs = dict(
        zip((p["key"] for p in postings), embed_texts([p["doc_text"] for p in postings]), strict=True)
    )
    query_vecs: dict[str, list[float]] = {}
    if settings.search_semantic_enabled:
        for q in queries:
            parsed = parse_query(q["text"], companies=company_names())
            remainder = parsed.remainder or q["text"]
            query_vecs[q["key"]] = (await embed_query(remainder)) or []

    factory = get_session_factory()

    # --- query plan contract: the trigram source must keep its index --------- #
    # Runs against the REAL jobs table (the temp shadow has no indexes), with
    # seq scans disabled so the planner shows whether the predicate is
    # index-answerable at all: `%` probes gin_trgm_ops; a bare `similarity()>=x`
    # cannot use it and would silently seq-scan as the corpus grows.
    async with factory() as session:
        pred_sql = str(
            fuzzy_predicate("netflx").compile(
                dialect=session.bind.dialect, compile_kwargs={"literal_binds": True}
            )
        )
        await session.execute(text("SET LOCAL enable_seqscan = off"))
        plan_rows = (
            await session.execute(
                text(f"EXPLAIN (COSTS OFF) SELECT id FROM jobs WHERE {pred_sql}")
            )
        ).scalars().all()
        plan = "\n".join(plan_rows)
        if "ix_jobs_title_trgm" not in plan and "ix_jobs_company_trgm" not in plan:
            raise SystemExit(
                "PLAN CONTRACT FAILED: the fuzzy predicate no longer probes a trigram "
                f"index — the explicit floor has replaced `%` instead of joining it.\n{plan}"
            )
        await session.rollback()

    # --- pass 2 first: live corpus percentiles (real table, no shadow) -------- #
    corpus_ctx: dict[str, dict] = {}
    async with factory() as session:
        for q in queries:
            qvec = query_vecs.get(q["key"]) or None
            if not qvec:
                corpus_ctx[q["key"]] = {"note": "no query vector"}
                continue
            qv = literal(qvec, Vector(dim))
            cos = (1 - Job.embedding.cosine_distance(qv)).label("cos")
            vals = (
                await session.execute(
                    select(cos).where(Job.embedding.isnot(None)).order_by(cos.desc()).limit(300)
                )
            ).scalars().all()
            vals = [float(v) for v in vals]
            ranks = {r: (round(vals[r - 1], 4) if len(vals) >= r else None) for r in (1, 2, 10, 25, 50, 100, 200)}
            counts = {f">={f}": sum(1 for v in vals if v >= f) for f in _FLOOR_GRID}
            corpus_ctx[q["key"]] = {"cosine_at_rank": ranks, "corpus_count_ge": counts}
        await session.rollback()

    # --- pass 1: parity retrieval over the shadow temp table ------------------ #
    eid_of = {p["key"]: _EID_BASE + i for i, p in enumerate(postings)}
    key_of = {v: k for k, v in eid_of.items()}

    per_query: dict[str, dict] = {}
    async with factory() as session:
        await session.execute(text(_temp_jobs_ddl(dim)))
        jobs_t = _jobs_table(dim)
        await session.execute(
            jobs_t.insert(),
            [
                {
                    "id": eid_of[p["key"]],
                    "company": p["company"],
                    "req_id": p["req_id"],
                    "title": p["title"],
                    "url": p["url"],
                    "department": p.get("department"),
                    "team": p.get("team"),
                    "description_text": p["doc_text"].split("\n", 1)[-1],
                    "family": p["family"],
                    "track": p["track"],
                    "level_band": p["level_band"],
                    "domains": list(p["domains"]),
                    "comp_median": None,
                    "embedding": doc_vecs[p["key"]],
                }
                for p in postings
            ],
        )
        # Document-side search_vector: THE production expression, imported from
        # its single writer so shadow ranking and live ranking cannot diverge.
        await session.execute(text(f"UPDATE jobs SET search_vector = {SEARCH_VECTOR_SQL}"))

        for q in queries:
            qkey = q["key"]
            qvec = query_vecs.get(qkey) or None
            res = await _retrieve(session, q["text"], qvec)
            ranked = res["ranked"]
            direct_keys = [key_of[eid] for eid in res["direct_ids"] if eid in key_of]

            # Assembled response order: the direct section is whole
            # and sorts above every related row; an identifier response carries
            # ONLY its identity rows.
            fused_keys = [key_of[eid] for eid, _, _ in ranked]
            if res["query_kind"] == "identifier":
                order_keys = direct_keys
            elif res["query_kind"] == "exact_title":
                order_keys = direct_keys + [k for k in fused_keys if k not in set(direct_keys)]
            else:
                order_keys = fused_keys
            order_cls = [cls_of.get((qkey, k), "irrelevant") for k in order_keys]
            via_of = {key_of[eid]: via for eid, _, via in ranked}

            # Identity gate inputs: direct resolution vs authored truth.
            labelled_exact = sorted(
                p["key"] for p in postings if cls_of.get((qkey, p["key"])) == "exact"
            )
            direct_ok = sorted(direct_keys) == labelled_exact
            false_exacts = sorted(set(direct_keys) - set(labelled_exact))

            # exact target rank (1-based) in the assembled order.
            exact_keys = labelled_exact
            exact_rank = None
            for idx, k in enumerate(order_keys, 1):
                if k in exact_keys:
                    exact_rank = idx
                    break
            # semantic-only admissions: rows admitted through semantic rank alone.
            semantic_only = sorted(
                k for k in order_keys if via_of.get(k) == {"semantic"}
            )
            semantic_only_irrelevant = [k for k in semantic_only if cls_of.get((qkey, k)) == "irrelevant"]

            top10 = order_cls[:10]
            top25 = order_cls[:25]
            prec_at_10 = (sum(1 for c in top10 if c in RELEVANT) / min(10, len(top10))) if top10 else 0.0
            rt = rel_total[qkey]
            recall_at_25 = (sum(1 for c in top25 if c in RELEVANT) / rt) if rt else None

            # calibration: cos(query, posting) from frozen encodings, by class.
            by_class_cos: dict[str, list[float]] = {}
            if qvec:
                for p in postings:
                    c = cls_of.get((qkey, p["key"]), "irrelevant")
                    by_class_cos.setdefault(c, []).append(_dot(qvec, doc_vecs[p["key"]]))
            cos_stats = {
                c: {
                    "n": len(v),
                    "min": round(min(v), 4),
                    "median": round(statistics.median(v), 4),
                    "max": round(max(v), 4),
                }
                for c, v in sorted(by_class_cos.items())
                if v
            }

            admitted_classes: dict[str, int] = {}
            for c in order_cls:
                admitted_classes[c] = admitted_classes.get(c, 0) + 1

            per_query[qkey] = {
                "cohort": q["cohort"],
                "kind": q["kind"],
                "resolved_kind": res["query_kind"],
                "direct_keys": direct_keys,
                "direct_ok": direct_ok,
                "false_exacts": false_exacts,
                "matched_total": res["matched_total"],
                "admitted_total": res["ranked_total"],
                "pool": res["pool"],
                "ranking_truncated": res["ranking_truncated"],
                "exact_rank": exact_rank,
                "precision_at_10": round(prec_at_10, 4),
                "recall_at_25": round(recall_at_25, 4) if recall_at_25 is not None else None,
                "ndcg_at_10": round(_ndcg_at(order_cls, 10), 4),
                "relevant_total": rt,
                "admitted_by_class": admitted_classes,
                "semantic_only_admitted": len(semantic_only),
                "semantic_only_irrelevant_admitted": len(semantic_only_irrelevant),
                "cosine_by_class": cos_stats,
                "corpus": corpus_ctx.get(qkey, {}),
                "parsed_remainder": res["parsed"]["remainder"],
            }
        await session.rollback()

    # --- aggregates + semantic-only admission summary ------------------------- #
    exact_ranks = [v["exact_rank"] for v in per_query.values() if v["exact_rank"] is not None]
    identifier_q = [k for k, v in per_query.items() if v["kind"] == "identifier"]
    exact_q = [k for k, v in per_query.items() if v["kind"] == "exact_title"]
    no_answer_q = [k for k, v in per_query.items() if v["cohort"] == "no_answer"]

    result = {
        "fixture_version": fixture["version"],
        "policy": "s3-direct-resolution+textual-membership",
        "embedding_model": settings.embedding_model,
        "embedding_dim": dim,
        "tier_measured": tier,
        "tiers_defined": tiers_defined,
        "tiers_not_measured": tiers_not_measured,
        "macro_ndcg_at_10": round(
            sum(v["ndcg_at_10"] for v in per_query.values()) / len(per_query), 4
        ),
        "macro_precision_at_10": round(
            sum(v["precision_at_10"] for v in per_query.values()) / len(per_query), 4
        ),
        "exact_targets_found": len(exact_ranks),
        "exact_targets_total": len(identifier_q) + len(exact_q),
        "exact_all_rank_1": all(
            per_query[k]["exact_rank"] == 1 for k in identifier_q + exact_q
        ),
        # Hard identity gates: direct resolution equals authored identity truth on
        # every query (an authored-exploratory query resolving a direct id is a
        # kind mismatch; a resolved id outside the labelled exact set is a false
        # exact). Both must be empty.
        "identity_gate_violations": sorted(
            k for k, v in per_query.items()
            if not v["direct_ok"] or v["kind"] != v["resolved_kind"]
        ),
        "false_exact_total": sum(len(v["false_exacts"]) for v in per_query.values()),
        # Rows admitted through semantic rank alone: structurally zero while
        # membership is textual-only, kept so a regression is loud.
        "semantic_only_admitted_total": sum(
            v["semantic_only_admitted"] for v in per_query.values()
        ),
        "no_answer_admitted": {
            k: per_query[k]["admitted_total"] for k in no_answer_q
        },
        "per_query": per_query,
    }

    print(json.dumps(result, indent=2))
    if tiers_not_measured:
        print(
            f"\nNOTE: measured tier={tier!r}; tiers NOT measured this run: "
            f"{tiers_not_measured}: retrieval is not certified for them."
        )
    if save:
        save.write_text(json.dumps(result, indent=2) + "\n")
        print(f"saved -> {save}")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--save", type=Path, default=None, help="write the result JSON here")
    args = parser.parse_args()
    fixture = json.loads(FIXTURE.read_text())
    asyncio.run(run(fixture, args.save))


if __name__ == "__main__":
    main()
