"""Fit search thresholds on the frozen eval fixture, with a held-out split.

Split the fixture by query, fit on one half, verify unchanged on the other, then
swap: a threshold failing either direction is not calibrated. This script runs
that procedure, so the numbers in
`tracker/search/policy.py::SearchThresholds` can be re-derived rather than
believed.

    .venv/bin/python -m scripts.calibrate_search_thresholds

Read-only: encodes the frozen fixture text through the production embed seams and
computes pg_trgm similarity on the live server inside a transaction it rolls back.

What is being fit, and against which constraint:

- `semantic_*_min` — the ADMISSION floor. The binding constraint: a
  no-answer control must produce ZERO semantic-only admission. So the floor is
  driven by the highest cosine any posting reaches for a query whose answer is
  "nothing", not by how well relevant rows score.
- `trgm_close_min` — the misspelling route into `close`, fit on the typo cohort.
- `semantic_close_min` — the paraphrase route into `close`. Reported, but this
  script will refuse to emit a value when the classes overlap.

The split is deterministic (sorted query keys, alternating) so a re-run
reproduces it exactly; `Math.random`-style sampling would make the held-out
claim unverifiable.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from sqlalchemy import text

from tracker.company_discovery import company_names
from tracker.config import get_settings
from tracker.db.session import session_scope
from tracker.search.parse import parse_query
from tracker.semantic.embed import embed_query, embed_texts

FIXTURE = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "search_retrieval_eval.json"

RELEVANT = {"exact", "close", "related"}


# One dot product for both eval scripts: the calibrated numbers must come from
# the same arithmetic the eval verifies, or a drift between two private copies
# certifies thresholds the eval can never reproduce.
from scripts.eval_search_retrieval import _dot as _cos  # noqa: E402


def _split(keys: list[str]) -> tuple[list[str], list[str]]:
    """Deterministic halves: sort, then alternate. Reproducible across runs."""
    ordered = sorted(keys)
    return ordered[0::2], ordered[1::2]


def _fit_floor(no_answer_max: list[float]) -> float | None:
    """Smallest floor that admits nothing for any no-answer query in this half.

    Rounded UP to the next 0.01 so the fitted value is not sitting exactly on an
    observed score, which would make it a memorised data point rather than a
    threshold.
    """
    if not no_answer_max:
        return None
    import math

    return math.ceil(max(no_answer_max) * 100 + 1) / 100


async def main() -> None:
    fixture = json.loads(FIXTURE.read_text())
    postings = fixture["postings"]
    queries = {q["key"]: q for q in fixture["queries"]}
    cls_of = {(lab["query"], lab["posting"]): lab["class"] for lab in fixture["labels"]}

    settings = get_settings()
    doc_vecs = dict(
        zip((p["key"] for p in postings), embed_texts([p["doc_text"] for p in postings]), strict=True)
    )
    qvecs: dict[str, list[float]] = {}
    for key, q in queries.items():
        parsed = parse_query(q["text"], companies=company_names())
        qvecs[key] = (await embed_query(parsed.remainder or q["text"])) or []

    # cosine[(query, posting)]
    cosine = {
        (qk, p["key"]): _cos(qv, doc_vecs[p["key"]])
        for qk, qv in qvecs.items() if qv
        for p in postings
    }

    def klass(qk: str, pk: str) -> str:
        return cls_of.get((qk, pk), "irrelevant")

    no_answer = [k for k, q in queries.items() if q["cohort"] == "no_answer"]
    half_a, half_b = _split(no_answer)

    print("=== semantic admission floor: fit on one half, hold on the other ===")
    print(f"  half A (fit): {half_a}\n  half B (fit): {half_b}\n")
    results = {}
    for name, fit, hold in (("A->B", half_a, half_b), ("B->A", half_b, half_a)):
        floor = _fit_floor([max(cosine[(qk, p["key"])] for p in postings) for qk in fit])
        worst_hold = max(max(cosine[(qk, p["key"])] for p in postings) for qk in hold)
        holds = floor is not None and worst_hold < floor
        results[name] = (floor, worst_hold, holds)
        print(f"  {name}: fitted floor={floor}  worst held-out no-answer cosine={worst_hold:.4f}  "
              f"-> {'HOLDS' if holds else 'FAILS'}")

    floors = [r[0] for r in results.values() if r[0] is not None]
    if not floors or not all(r[2] for r in results.values()):
        print("\n  NOT CALIBRATED: a floor fitted on one half did not hold on the other.")
        chosen = None
    else:
        chosen = max(floors)
        print(f"\n  calibrated floor = max(both directions) = {chosen}")

    # --- what the floor costs, per cohort ---------------------------------- #
    if chosen is not None:
        print("\n=== retained relevant rows at that floor (semantic source only) ===")
        by_cohort: dict[str, list[int]] = {}
        for qk, q in queries.items():
            if not qvecs.get(qk):
                continue
            rel = [p["key"] for p in postings if klass(qk, p["key"]) in RELEVANT]
            if not rel:
                continue
            kept = sum(1 for pk in rel if cosine[(qk, pk)] >= chosen)
            by_cohort.setdefault(q["cohort"], []).extend([kept, len(rel)])
        for cohort, pairs in sorted(by_cohort.items()):
            kept = sum(pairs[0::2])
            total = sum(pairs[1::2])
            print(f"  {cohort:17s} {kept:4d}/{total:<4d} relevant rows clear the floor "
                  f"({100 * kept / total:.0f}%)")

    # --- semantic_close_min: only if the classes actually separate ---------- #
    print("\n=== semantic_close_min (paraphrase route into `close`) ===")
    overlaps = []
    for qk, q in queries.items():
        if q["cohort"] != "semantic_intent" or not qvecs.get(qk):
            continue
        close = [cosine[(qk, p["key"])] for p in postings if klass(qk, p["key"]) == "close"]
        irrel = [cosine[(qk, p["key"])] for p in postings if klass(qk, p["key"]) == "irrelevant"]
        if close and irrel and min(close) <= max(irrel):
            overlaps.append((qk, min(close), max(irrel)))
    if overlaps:
        print(f"  REFUSING to emit a value: {len(overlaps)} of 8 semantic-intent queries have an")
        print("  irrelevant row scoring at or above their lowest close target.")
        for qk, lo, hi in overlaps:
            print(f"    {qk:34s} close_min={lo:.4f} <= irrelevant_max={hi:.4f}")
        print("  Any threshold separating them for one query admits noise for another.")
    else:
        print("  classes separate; a value can be fit")

    # --- trgm_close_min, computed by the server's pg_trgm --------------------- #
    print("\n=== trgm_close_min (misspelling route into `close`) ===")
    # PER QUERY, never pooled: trigram similarity scales with the query string,
    # so pooling "anthropc" (a 9-char company match) with a three-word misspelled
    # title compares numbers that were never on the same scale.
    async with session_scope() as session:
        per_query_sims: dict[str, dict[str, list[float]]] = {}
        for qk, q in queries.items():
            if q["cohort"] != "typo_fragment":
                continue
            for p in postings:
                cls = klass(qk, p["key"])
                sim = await session.scalar(
                    text("select greatest(similarity(:t, :q), similarity(:c, :q))"),
                    {"t": p["title"], "q": q["text"], "c": p["company"]},
                )
                per_query_sims.setdefault(qk, {}).setdefault(cls, []).append(float(sim or 0.0))
        await session.rollback()

    separable, inverted = [], []
    for qk, by_cls in sorted(per_query_sims.items()):
        close = by_cls.get("close") or []
        lower = (by_cls.get("related") or []) + (by_cls.get("irrelevant") or [])
        if not close or not lower:
            continue
        gap = min(close) - max(lower)
        (separable if gap > 0 else inverted).append((qk, min(close), max(lower), gap))
    for qk, lo, hi, gap in separable:
        print(f"  SEPARATES {qk:32s} close_min={lo:.4f} > below_max={hi:.4f} (gap {gap:+.4f})")
    for qk, lo, hi, gap in inverted:
        print(f"  OVERLAPS  {qk:32s} close_min={lo:.4f} <= below_max={hi:.4f} (gap {gap:+.4f})")
    if separable and not inverted:
        bound = min(lo for _, lo, _, _ in separable)
        print(f"  every typo query separates; the binding value is {bound:.4f}")
    else:
        print(f"  NOT CALIBRATED: {len(inverted)} of {len(separable) + len(inverted)} typo queries "
              "rank a non-close row at or above their weakest close row.")

    print(f"\nmodel={settings.embedding_model} dim={settings.embedding_dim}")


if __name__ == "__main__":
    asyncio.run(main())
