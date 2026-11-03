"""SQL-compile contracts for `search/retrieval.py`.

Pure: statements are compiled to PostgreSQL SQL and inspected, never executed —
the shapes these tests pin are exactly the ones that fail silently at runtime
(a predicate that drops its index, a source that quietly regains membership
power). The live halves — plan shape via EXPLAIN, metric gates — run in
`scripts.eval_search_retrieval` against the real server.

Written to fail for the plausible broken implementations:
- semantic CTE reads the whole table again -> dense membership is back;
- explicit floor replaces `%` instead of joining it -> Seq Scan at scale;
- a structured filter applied to one source but not the other;
- `setweight` dropped from the vector build -> flat ranking returns.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.dialects import postgresql

from tracker.db.models import Job
from tracker.db.repo import SEARCH_VECTOR_SQL
from tracker.search.policy import DEFAULT_THRESHOLDS
from tracker.search.retrieval import (
    candidate_pool,
    fused_candidates,
    fuzzy_predicate,
    textual_match,
)


def _sql(clause) -> str:
    return str(
        clause.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})
    )


def _fused_sql(conds: list, qvec: list[float] | None) -> str:
    fused, _ = fused_candidates(conds, "example query", qvec, pool=200)
    # Bound vector params cannot literal-bind; structure is what these tests
    # read, so placeholders are fine.
    return str(select(fused).compile(dialect=postgresql.dialect()))


QVEC = [0.1] * 768


# --------------------------------------------------------------------------- #
# Fuzzy source: index probe AND explicit floor
# --------------------------------------------------------------------------- #


def test_fuzzy_predicate_keeps_the_index_probe_and_the_explicit_floor() -> None:
    sql = _sql(fuzzy_predicate("netflx"))
    # `%` probes gin_trgm_ops; without it the planner seq-scans.
    assert "%" in sql
    # The explicit floor is what removes the session GUC from the match set.
    assert "similarity(" in sql
    assert f">= {DEFAULT_THRESHOLDS.trgm_min}" in sql


def test_textual_match_carries_the_same_explicit_floor() -> None:
    compiled = textual_match("netflx").compile(dialect=postgresql.dialect())
    sql = str(compiled)
    assert "websearch_to_tsquery" in sql
    assert "similarity(" in sql and ">=" in sql
    assert DEFAULT_THRESHOLDS.trgm_min in compiled.params.values(), (
        "the honest-total predicate must bind the same floor as the fuzzy source, "
        "or `matched` counts a different set than retrieval admits"
    )


# --------------------------------------------------------------------------- #
# Semantic reorders, never admits
# --------------------------------------------------------------------------- #


def test_semantic_ranking_reads_only_the_textual_union() -> None:
    """The guard for THE core invariant, written to actually fail.

    Splitting on `"vec AS"` and searching the remainder for the substring
    `"textual"` — which the OUTER query always contains — or counting SELECTs in
    a fragment truncated at the first paren inside `row_number()` are
    tautologies: reverting the vec CTE to an unbounded embedding scan keeps them
    green. This asserts the binding predicate itself.
    """
    sql = _fused_sql([], QVEC)
    # The cosine ranking exists...
    assert "<=>" in sql
    # ...and the vec CTE's WHERE binds its id set to the textual union. This
    # exact predicate is what disappears if someone reverts to a free scan.
    assert "jobs.id IN (SELECT textual.id" in sql, (
        "semantic CTE no longer bounded by the textual union — dense membership is back"
    )
    # The embedding filter may only ever appear ALONGSIDE that bound, never as
    # the sole membership condition.
    vec_start = sql.index("vec AS")
    vec_body = sql[vec_start : sql.index("SELECT fused", vec_start)]
    assert "jobs.id IN (SELECT textual.id" in vec_body
    assert "embedding IS NOT NULL" in vec_body


def test_no_query_vector_means_no_semantic_sql_at_all() -> None:
    sql = _fused_sql([], None)
    assert "<=>" not in sql
    assert "vec AS" not in sql  # no CTE named vec ("search_vector" contains "vec")


def test_via_names_carry_membership_sources_only() -> None:
    _, via = fused_candidates([], "example", QVEC, pool=200)
    assert via == ["keyword", "fuzzy"]
    assert "semantic" not in via
    sql = _fused_sql([], QVEC)
    assert "via_keyword" in sql and "via_fuzzy" in sql
    assert "via_semantic" not in sql, (
        "a via badge is a membership claim; the reordering vector may not make one"
    )


def test_semantic_rank_still_contributes_to_the_fused_score() -> None:
    # Reorder-only must not degrade into ignored-entirely: the vec CTE's rank
    # (its only non-join column) must feed the fused score.
    with_vec = _fused_sql([], QVEC)
    without = _fused_sql([], None)
    assert "vec.rnk" in with_vec
    assert "vec.rnk" not in without


# --------------------------------------------------------------------------- #
# Identical structured filters in every membership source
# --------------------------------------------------------------------------- #


def test_structured_conditions_appear_in_every_textual_source() -> None:
    fused, _ = fused_candidates([Job.workplace_type.in_(["remote"])], "example", None, pool=200)
    sql = str(select(fused).compile(dialect=postgresql.dialect()))
    hits = sql.count("workplace_type IN")
    assert hits == 2, f"expected the filter in both lex and trgm CTEs, found {hits}"


# --------------------------------------------------------------------------- #
# Direct identity lookups — equality, never similarity
# --------------------------------------------------------------------------- #


def test_req_id_lookup_is_equality_never_fuzzy(monkeypatch) -> None:
    """Identifier equality never fuzzy-matches a different req.

    Captures the statement the req branch executes and asserts it compares
    `req_id =` with no trigram/similarity/tsquery anywhere.
    """
    import asyncio

    from tracker.search.policy import identity_probe
    from tracker.search.retrieval import identifier_matches

    captured: list[str] = []

    class _Session:
        async def scalars(self, stmt):
            captured.append(str(stmt.compile(dialect=postgresql.dialect())))

            class _R:
                def all(self):
                    return []

            return _R()

        async def execute(self, stmt):  # pragma: no cover - url branch unused here
            raise AssertionError("bare req_id probe must not run the URL branch")

    probe = identity_probe("10428842")
    asyncio.run(identifier_matches(_Session(), probe, [Job.status == "open"]))
    (sql,) = captured
    assert "req_id =" in sql
    assert "%" not in sql.replace("%(", "(")  # no trigram operator
    assert "similarity" not in sql and "websearch" not in sql
    # Explicit request filters constrain the lookup.
    assert "jobs.status =" in sql


def test_url_lookup_fetches_only_explicitly_filtered_urls(monkeypatch) -> None:
    import asyncio

    from tracker.search.policy import identity_probe
    from tracker.search.retrieval import identifier_matches

    captured: list[str] = []

    class _Session:
        async def execute(self, stmt):
            captured.append(str(stmt.compile(dialect=postgresql.dialect())))

            class _R:
                def all(self):
                    return []

            return _R()

        async def scalars(self, stmt):
            captured.append(str(stmt.compile(dialect=postgresql.dialect())))

            class _R:
                def all(self):
                    return []

            return _R()

    probe = identity_probe("https://example.com/jobs/123?utm_source=x")
    asyncio.run(identifier_matches(_Session(), probe, [Job.status == "open"]))
    url_sql = captured[0]
    assert "jobs.url" in url_sql and "IS NOT NULL" in url_sql
    assert "jobs.status =" in url_sql
    assert "similarity" not in url_sql  # identity is Python-key equality, not fuzz


def test_exact_title_lookup_carries_explicit_filters_and_no_fuzz() -> None:
    import asyncio

    from tracker.search.retrieval import exact_title_matches

    captured: list[str] = []

    class _Session:
        async def execute(self, stmt):
            captured.append(str(stmt.compile(dialect=postgresql.dialect())))

            class _R:
                def all(self):
                    return []

            return _R()

    asyncio.run(
        exact_title_matches(_Session(), "product manager", [Job.status == "open"], "Product Manager")
    )
    (sql,) = captured
    assert "jobs.title" in sql and "jobs.status =" in sql
    # The trigram `%` probe is a PREFILTER (equal keys imply similarity ~1.0);
    # equality itself stays in Python via exact_title_key — so no similarity()
    # threshold and no tsquery may appear here.
    assert "jobs.title %" in sql
    assert "similarity" not in sql and "websearch" not in sql


def test_identifier_lookup_bypasses_standing_visibility_but_keeps_request_filters() -> None:
    """Like `ids`, a pasted URL/req_id is a specific-row read.

    Scope, hidden companies, and the dismissed exclusion must not hide it (a
    row the user explicitly names stays resolvable after a scope change), but
    request filters — the Open/Closed toggle included — still apply.
    """
    from tracker.db.queries.jobs import structured_conds

    params = {"status": "open", "hidden": ["acme"]}
    browse = " AND ".join(
        str(c.compile(dialect=postgresql.dialect())) for c in structured_conds(params)
    )
    direct = " AND ".join(
        str(c.compile(dialect=postgresql.dialect()))
        for c in structured_conds(params, browse_visibility=False)
    )
    # Browse keeps all three standing gates...
    assert "in_scope" in browse and "NOT IN" in browse
    # ...direct resolution drops exactly those...
    assert "in_scope" not in direct
    assert "NOT IN" not in direct  # dismissed exclusion + hidden companies
    # ...and keeps the explicit request filter.
    assert "jobs.status =" in direct


def test_empty_title_key_probes_nothing() -> None:
    import asyncio

    from tracker.search.retrieval import exact_title_matches

    class _Session:
        async def execute(self, stmt):  # pragma: no cover
            raise AssertionError("empty key must not touch the database")

    assert asyncio.run(exact_title_matches(_Session(), "", [], "")) == []


# --------------------------------------------------------------------------- #
# Weighted document vector
# --------------------------------------------------------------------------- #


def test_search_vector_build_is_weighted_title_first() -> None:
    assert SEARCH_VECTOR_SQL.count("setweight") == 3
    for field, weight in (("title", "'A'"), ("team", "'B'"), ("description_text", "'C'")):
        assert field in SEARCH_VECTOR_SQL and weight in SEARCH_VECTOR_SQL
    # Title must outrank category text must outrank body: order of tiers is the
    # measured fix, not a style choice.
    assert SEARCH_VECTOR_SQL.index("'A'") < SEARCH_VECTOR_SQL.index("'B'") < SEARCH_VECTOR_SQL.index("'C'")
    assert SEARCH_VECTOR_SQL.index("title") < SEARCH_VECTOR_SQL.index("department")


# --------------------------------------------------------------------------- #
# Pool bounds work, not membership
# --------------------------------------------------------------------------- #


def test_candidate_pool_grows_to_the_match_set_up_to_the_ceiling() -> None:
    from tracker.config import get_settings

    s = get_settings()
    base, ceiling = s.search_candidate_pool, max(s.search_candidate_pool, s.search_candidate_pool_max)
    assert candidate_pool(0) == base
    assert candidate_pool(base + 50) == base + 50
    assert candidate_pool(ceiling + 1000) == ceiling
