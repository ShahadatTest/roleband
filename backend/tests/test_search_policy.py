"""Behavior tests for the pure search policy (no DB, no model, no network).

Covers the search policy's backend invariants, plus a fixture-driven agreement
check that runs the real decision tree against the frozen ground truth.

These are written to fail for plausible broken implementations: an exact key
that deletes `senior`, a semantic score that overrides `family`, a
partial req id that fuzzy-matches a different one, and a `close` granted on
similarity alone.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tracker.search.policy import (
    DEFAULT_THRESHOLDS,
    SEARCH_POLICY_VERSION,
    CandidateEvidence,
    ConflictKind,
    MatchClass,
    SearchThresholds,
    classify_candidate,
    exact_title_key,
    explicit_level,
    identity_url_key,
    material_conflicts,
    posting_signature,
    query_signature,
    req_id_probe,
    resolve_query_kind,
)

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "search_retrieval_eval.json"

PV_QUERY = "Applied Science Manager, Prime Video Personalization & Discovery"


def _sig(title: str, *, family=None, track=None, level_band=None, domains=(), company=None):
    return posting_signature(
        title=title, family=family, track=track, level_band=level_band,
        domains=list(domains), company=company,
    )


def _evidence(signature, *, sources=("keyword",), title_similarity=None):
    return CandidateEvidence(
        signature=signature,
        sources=frozenset(sources),
        title_similarity=title_similarity,
    )


# --------------------------------------------------------------------------- #
# Conservative exact-title key
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "left,right",
    [
        # Case-fold and whitespace collapse are cosmetic.
        ("Applied Science Manager", "applied   science manager"),
        # Trailing whitespace / separator damage sources leave behind.
        ("Engineering Manager", "Engineering Manager,  "),
        ("Engineering Manager", "  Engineering Manager |"),
        # Non-breaking and thin spaces are spaces.
        ("Staff Engineer, Ads", "Staff Engineer, Ads"),
        # Dash codepoints fold to ASCII.
        ("Manager - Ads", "Manager — Ads"),
        ("Front-End Engineer", "Front‑End Engineer"),
    ],
)
def test_exact_key_normalizes_only_cosmetic_damage(left: str, right: str) -> None:
    assert exact_title_key(left) == exact_title_key(right)


@pytest.mark.parametrize(
    "left,right,why",
    [
        ("Senior Data Scientist", "Data Scientist", "level token is material"),
        ("Principal Engineer", "Senior Engineer", "level tokens differ"),
        ("Applied Science Manager", "Applied Scientist Manager", "one word differs"),
        ("Product Manager", "Program Manager", "one word differs"),
        ("Engineering Manager", "Engineer", "one word differs"),
        ("Engineer, Ads", "Ads Engineer", "token order is not identity"),
        ("Software Engineer", "Software Engineers", "no stemming"),
        ("Manager of Ads", "Manager Ads", "no stop-word deletion"),
        ("C++ Engineer", "C Engineer", "technical punctuation survives"),
        ("C# Engineer", "C Engineer", "technical punctuation survives"),
        ("AI/ML Engineer", "AI ML Engineer", "technical punctuation survives"),
    ],
)
def test_exact_key_never_erases_a_material_word(left: str, right: str, why: str) -> None:
    assert exact_title_key(left) != exact_title_key(right), why


def test_exact_key_is_the_search_key_not_the_lineage_key() -> None:
    """`lineage.normalize.title_key` deliberately deletes level tokens.

    Reusing it here would make `Senior X` and `X` the same identity, which is the
    false-exact this whole module exists to prevent.
    """
    from tracker.lineage.normalize import title_key as lineage_key

    assert lineage_key("Senior Data Scientist") == lineage_key("Data Scientist")
    assert exact_title_key("Senior Data Scientist") != exact_title_key("Data Scientist")


# --------------------------------------------------------------------------- #
# Identity probes
# --------------------------------------------------------------------------- #


def test_url_identity_drops_tracking_and_fragment_only() -> None:
    stored = "https://www.amazon.jobs/en/jobs/10428842/applied-science-manager"
    pasted = (
        "https://amazon.jobs/en/jobs/10428842/applied-science-manager"
        "?utm_source=linkedin&utm_campaign=x&ref=feed#job-details"
    )
    assert identity_url_key(pasted) == identity_url_key(stored)


def test_url_identity_keeps_a_provider_job_id_carried_in_the_query() -> None:
    # `gh_jid` IS the greenhouse job id. A wildcard "drop gh_*" rule would erase
    # identity rather than noise, collapsing every job on a board into one key.
    a = identity_url_key("https://boards.greenhouse.io/acme/jobs/4?gh_jid=111&gh_src=abc")
    b = identity_url_key("https://boards.greenhouse.io/acme/jobs/4?gh_jid=222&gh_src=zzz")
    assert a is not None and a != b


def test_url_identity_ignores_query_order_but_not_a_different_path() -> None:
    assert identity_url_key("https://x.co/a?b=1&a=2") == identity_url_key("https://x.co/a?a=2&b=1")
    assert identity_url_key("https://x.co/a/") != identity_url_key("https://x.co/b")


def test_non_url_text_has_no_url_key() -> None:
    assert identity_url_key("Applied Science Manager") is None
    assert identity_url_key("") is None


@pytest.mark.parametrize("text", ["10428842", "5316593008", "JR-12345", "a1b2c3"])
def test_req_id_probe_accepts_a_complete_bare_identifier(text: str) -> None:
    assert req_id_probe(text) == text


@pytest.mark.parametrize(
    "text",
    [
        "1042 8842",                 # whitespace: a phrase, not an id
        "Applied Science Manager",   # no digit
        "42",                        # too short to be an id
        "",
    ],
)
def test_req_id_probe_rejects_anything_that_is_not_a_complete_id(text: str) -> None:
    assert req_id_probe(text) is None


def test_req_id_probe_is_equality_not_prefix() -> None:
    """A truncated id must never resolve to the full one.

    The probe returns the text verbatim so the SQL side can compare for
    equality; nothing here may normalize `1042` toward `10428842`.
    """
    assert req_id_probe("1042") == "1042"
    assert req_id_probe("1042") != "10428842"


def test_query_kind_follows_resolved_evidence_not_the_shape_of_the_text() -> None:
    assert resolve_query_kind(has_identifier_match=True, has_exact_title_match=True) == "identifier"
    assert resolve_query_kind(has_identifier_match=False, has_exact_title_match=True) == "exact_title"
    # Looks like a req id, matches no row -> exploratory, not an empty identifier page.
    assert resolve_query_kind(has_identifier_match=False, has_exact_title_match=False) == "exploratory"


# --------------------------------------------------------------------------- #
# Title signature + material conflicts
# --------------------------------------------------------------------------- #


def test_mid_band_is_not_an_explicit_level() -> None:
    # `mid` is the corpus sentinel for "no seniority marker in the title". Read
    # as a level it would put every unmarked posting in conflict with every
    # `Senior` query.
    assert explicit_level("mid") is None
    assert explicit_level(None) is None
    assert explicit_level("principal") == "principal"


def test_query_signature_reads_role_head_and_org_path_separately() -> None:
    sig = query_signature(PV_QUERY)
    assert sig.head == "Applied Science Manager"
    assert sig.org == "Prime Video Personalization & Discovery"
    assert sig.family == "ml_ai_research"   # requires the taxonomy fix
    assert sig.track == "management"
    assert sig.explicit_level is None       # query names no level -> neutral
    assert {"media_entertainment", "ai_ml"} <= sig.domains


def test_query_that_names_no_role_claims_no_track() -> None:
    # "Prime Video" is a mission, not a role. Asserting a track here would put
    # the query in conflict with every IC posting on that team.
    sig = query_signature("Prime Video Personalization")
    assert sig.family is None
    assert sig.track is None
    assert sig.names_a_role is False


@pytest.mark.parametrize(
    "title,family,track,level,domains,expected",
    [
        # Product Manager on the exact team the query named: family + track flip.
        ("Principal Product Manager Tech, Prime Video Personalization & Discovery",
         "product_management", "product_program", "principal", ["media_entertainment"],
         {ConflictKind.FAMILY, ConflictKind.TRACK}),
        # Same family, IC instead of manager.
        ("Principal Applied Scientist, Prime Video Personalization & Discovery",
         "ml_ai_research", "technical", "principal", ["media_entertainment", "ai_ml"],
         {ConflictKind.TRACK}),
        # Same role shape, different mission. Both rows carry broad `ai_ml`, so
        # only the org path can tell these apart.
        ("Applied Science Manager, Amazon Robotics",
         "ml_ai_research", "management", "mid", ["ai_ml", "devices_hardware"],
         {ConflictKind.ORG_PATH}),
        # Same mission, same shape: no conflict at all.
        ("Applied Science Manager, Prime Video - Content Localization",
         "ml_ai_research", "management", "mid", ["media_entertainment", "ai_ml"],
         set()),
    ],
)
def test_material_conflicts_against_the_prime_video_query(
    title, family, track, level, domains, expected
) -> None:
    got = material_conflicts(
        query_signature(PV_QUERY),
        _sig(title, family=family, track=track, level_band=level, domains=domains, company="amazon"),
    )
    assert set(got) == expected


def test_company_name_in_an_org_path_is_not_shared_mission() -> None:
    # Every amazon org path contains "Amazon". Counting it as overlap would clear
    # the mission gate for the entire company.
    q = query_signature("Applied Science Manager, Amazon Alexa")
    c = _sig("Applied Science Manager, Amazon Robotics", family="ml_ai_research",
             track="management", level_band="mid", company="amazon")
    assert ConflictKind.ORG_PATH in material_conflicts(q, c)


def test_missing_evidence_is_neutral_never_a_conflict() -> None:
    # An unclassified row and a query that states nothing must not manufacture a
    # mismatch out of two unknowns.
    q = query_signature("Engineering Manager")
    unclassified = _sig("Some Title", family=None, track=None, level_band=None, domains=[])
    assert material_conflicts(q, unclassified) == ()


def test_explicit_level_conflicts_only_when_both_sides_state_one() -> None:
    q = query_signature("Senior Data Scientist")
    assert q.explicit_level == "senior"
    principal = _sig("Principal Data Scientist", family="data_science", track="technical",
                     level_band="principal")
    assert ConflictKind.EXPLICIT_LEVEL in material_conflicts(q, principal)
    # Candidate carries the "no marker" sentinel -> the level axis stays silent.
    unmarked = _sig("Data Scientist", family="data_science", track="technical", level_band="mid")
    assert ConflictKind.EXPLICIT_LEVEL not in material_conflicts(q, unmarked)


# --------------------------------------------------------------------------- #
# Decision tree
# --------------------------------------------------------------------------- #


def test_exact_source_wins_before_any_conflict_check() -> None:
    d = classify_candidate(
        query_signature(PV_QUERY),
        _evidence(_sig("anything at all"), sources=("exact", "keyword")),
    )
    assert d.admitted and d.match_class is MatchClass.EXACT


def test_textual_evidence_with_a_hard_conflict_is_related_never_close() -> None:
    # The Product Manager on the exact Prime Video team: the user's own words are
    # in the row, so it stays visible — but it is not the same role.
    pm = _sig("Principal Product Manager Tech, Prime Video Personalization & Discovery",
              family="product_management", track="product_program", level_band="principal",
              domains=["media_entertainment"], company="amazon")
    d = classify_candidate(query_signature(PV_QUERY), _evidence(pm, sources=("keyword", "fuzzy")))
    assert d.admitted
    assert d.match_class is MatchClass.RELATED
    assert ConflictKind.FAMILY in d.conflicts


def test_semantic_only_with_a_hard_conflict_is_rejected() -> None:
    pm = _sig("Principal Product Manager Tech, Prime Video Personalization & Discovery",
              family="product_management", track="product_program", level_band="principal",
              domains=["media_entertainment"], company="amazon")
    d = classify_candidate(query_signature(PV_QUERY), _evidence(pm, sources=("semantic",)))
    assert not d.admitted
    assert d.match_class is None


def test_a_high_semantic_score_cannot_clear_a_family_conflict() -> None:
    """The one-word rule. Same team, same body, different job.

    A cross-encoder-grade cosine is still only a score; it may support a class
    and may never establish one.
    """
    pm = _sig("Principal Product Manager Tech, Prime Video Personalization & Discovery",
              family="product_management", track="product_program", level_band="principal",
              domains=["media_entertainment"], company="amazon")
    d = classify_candidate(
        query_signature(PV_QUERY),
        CandidateEvidence(signature=pm, sources=frozenset({"semantic"}),
                          title_similarity=0.99, semantic_similarity=0.99),
    )
    assert not d.admitted


def test_no_conflict_and_agreeing_head_is_close() -> None:
    same = _sig("Applied Science Manager, Prime Video - Content Localization",
                family="ml_ai_research", track="management", level_band="mid",
                domains=["media_entertainment", "ai_ml"], company="amazon")
    d = classify_candidate(query_signature(PV_QUERY), _evidence(same))
    assert d.match_class is MatchClass.CLOSE


def test_level_words_do_not_block_close_when_the_query_is_silent() -> None:
    # "Principal Product Manager Tech" vs "Product Manager": the head gate must
    # not count `Principal` against agreement, or every levelled title would
    # drop to `related` for an unlevelled query.
    q = query_signature("Product Manager")
    c = _sig("Principal Product Manager Tech, Prime Video Personalization & Discovery",
             family="product_management", track="product_program", level_band="principal",
             domains=["media_entertainment"], company="amazon")
    assert classify_candidate(q, _evidence(c)).match_class is MatchClass.CLOSE


def test_admitted_but_disagreeing_head_is_related() -> None:
    q = query_signature("Engineering Manager")
    # No stored classification at all -> no conflict, but nothing agrees either.
    d = classify_candidate(q, _evidence(_sig("Veterinary Surgeon")))
    assert d.admitted and d.match_class is MatchClass.RELATED


# --------------------------------------------------------------------------- #
# Uncalibrated thresholds fail closed
# --------------------------------------------------------------------------- #


def test_policy_version_says_uncalibrated_and_score_close_gates_stay_none() -> None:
    """No score threshold separates the classes on this representation.

    There are no dense-admission floors. The two close-gate thresholds are
    named seams that must stay None until a new
    representation is measured — and they are not plumbed (the router passes no
    similarity scores), which their docstrings state.
    """
    assert SEARCH_POLICY_VERSION.endswith("uncalibrated")
    assert DEFAULT_THRESHOLDS.trgm_close_min is None
    assert DEFAULT_THRESHOLDS.semantic_close_min is None
    assert not hasattr(DEFAULT_THRESHOLDS, "semantic_exploratory_min"), (
        "the dense-admission floor apparatus was removed with §14; do not re-add "
        "it without a measured representation"
    )


def test_a_typo_reaches_close_only_through_a_measured_trigram_threshold() -> None:
    """Token overlap collapses on misspellings by construction.

    "enginering" shares no token with "engineering", so a typo can only reach
    `close` through a trigram score. This pins the MECHANISM in both directions:
    inert while the threshold is `None`, active once one is supplied.

    The 0.35 below is illustrative, NOT a candidate value. Over the frozen eval
    fixture's cohort no separating threshold exists: for
    this very query a non-close row scores 0.4500 against the weakest close row's
    0.3725. That is why `trgm_close_min` ships as `None` — see
    `scripts.calibrate_search_thresholds`.
    """
    q = query_signature("anthropc enginering manager")
    em = _sig("Engineering Manager, Agent Prompts & Evals", family="engineering_management",
              track="management", level_band="staff", company="anthropic")
    # similarity(title, query) as the database computes it for this pair.
    measured = _evidence(em, title_similarity=0.4043)

    assert classify_candidate(q, measured).match_class is MatchClass.RELATED

    calibrated = SearchThresholds(trgm_close_min=0.35)
    assert classify_candidate(q, measured, calibrated).match_class is MatchClass.CLOSE

    # The same threshold must still reject the IC decoy in that cohort (0.1509).
    ic = _sig("Senior Staff Software Engineer, API", family="software_engineering",
              track="technical", level_band="principal", company="anthropic")
    decoy = _evidence(ic, title_similarity=0.1509)
    assert classify_candidate(q, decoy, calibrated).match_class is MatchClass.RELATED


# --------------------------------------------------------------------------- #
# Frozen eval fixture ground truth
# --------------------------------------------------------------------------- #

#: Cohorts whose class boundary is a *measured score*, not a deterministic field.
#: Excluded from the agreement check because no measured score separates
#: them; `test_a_typo_reaches_close_only_through_a_measured_trigram_threshold`
#: pins both directions so this exclusion cannot hide a regression.
_SCORE_DEPENDENT_COHORTS = {
    # A misspelling shares no token with the word it misspells, and a paraphrase
    # shares none with the corpus's own vocabulary. Both cohorts therefore reach
    # `close` only through a MEASURED score (trigram / cosine).
    #
    # `scripts.calibrate_search_thresholds` cannot fit either score: typo and
    # semantic-intent queries rank a NON-close row at or above their weakest
    # close row, so no threshold separates them. These cohorts are therefore
    # excluded from the deterministic agreement check, not pending a number — the
    # mechanism is still pinned in both directions by
    # `test_a_typo_reaches_close_only_through_a_measured_trigram_threshold`.
    "typo_fragment",
    "semantic_intent",
}


def _classifiable(query: dict) -> bool:
    """Whether this query's labels are a claim THIS module can answer.

    Excluded: identifier queries (identity is resolved in SQL, not classified),
    and `filter_dependent` queries whose labels encode a company/location/
    workplace fact. `TitleSignature` has no company axis on purpose —
    those are structured filters applied during retrieval, so a wrong-company
    row never reaches the classifier. Asserting them here would test the wrong
    layer and would push a company axis into the policy to satisfy a test.
    """
    return query["kind"] != "identifier" and not query.get("filter_dependent")


@pytest.fixture(scope="module")
def fixture_data() -> dict:
    return json.loads(FIXTURE.read_text())


def test_policy_reproduces_the_frozen_labels_for_every_deterministic_pair(fixture_data) -> None:
    """The real decision tree against the eval fixture's hand-authored ground truth.

    Every candidate is handed *textual* support, which is the hardest setting
    for this tree: it removes the reject branch entirely, so a conflict rule
    that has gone soft shows up as a `related` row promoted to `close` rather
    than as a row quietly disappearing.
    """
    postings = {p["key"]: p for p in fixture_data["postings"]}
    queries = {q["key"]: q for q in fixture_data["queries"]}

    checked, failures = 0, []
    for label in fixture_data["labels"]:
        query = queries[label["query"]]
        if not _classifiable(query) or query["cohort"] in _SCORE_DEPENDENT_COHORTS:
            continue
        if label["class"] == "irrelevant":
            continue  # membership is the semantic floor's job, not policy's

        posting = postings[label["posting"]]
        sources = {"keyword", "fuzzy"}
        if exact_title_key(query["text"]) == exact_title_key(posting["title"]):
            sources.add("exact")

        decision = classify_candidate(
            query_signature(query["text"]),
            _evidence(
                _sig(posting["title"], family=posting["family"], track=posting["track"],
                     level_band=posting["level_band"], domains=posting["domains"],
                     company=posting["company"]),
                sources=tuple(sources),
            ),
        )
        got = decision.match_class.value if decision.match_class else "rejected"
        checked += 1
        if got != label["class"]:
            failures.append(f"{label['query']}/{label['posting']}: "
                            f"want {label['class']}, got {got} ({decision.reason})")

    assert not failures, "\n".join(failures)
    assert checked >= 20, "fixture shrank — the agreement check stopped covering the tree"


def test_must_not_class_is_never_violated_on_any_relevant_pair(fixture_data) -> None:
    """The gate a macro average cannot hide.

    One violated `must_not_class` is a failure regardless of how well every
    other pair scores. Restricted to labelled-relevant pairs: an `irrelevant`
    label forbids *admission*, which is a membership claim owned by the source
    predicates and the semantic floor — a row the user's own words hit is
    legitimately `related` here, so asserting it through this tree would
    be testing the wrong layer.
    """
    postings = {p["key"]: p for p in fixture_data["postings"]}
    queries = {q["key"]: q for q in fixture_data["queries"]}

    violations = []
    for label in fixture_data["labels"]:
        query = queries[label["query"]]
        if not _classifiable(query) or label["class"] == "irrelevant":
            continue
        if query["cohort"] in _SCORE_DEPENDENT_COHORTS:
            continue
        posting = postings[label["posting"]]
        sources = {"keyword", "fuzzy"}
        if exact_title_key(query["text"]) == exact_title_key(posting["title"]):
            sources.add("exact")

        decision = classify_candidate(
            query_signature(query["text"]),
            _evidence(
                _sig(posting["title"], family=posting["family"], track=posting["track"],
                     level_band=posting["level_band"], domains=posting["domains"],
                     company=posting["company"]),
                sources=tuple(sources),
            ),
        )
        if decision.match_class and decision.match_class.value in label.get("must_not_class", []):
            violations.append(f"{label['query']}/{label['posting']}: "
                              f"classified {decision.match_class.value}, "
                              f"forbidden {label['must_not_class']}")

    assert not violations, "\n".join(violations)


def test_no_answer_control_rejects_every_semantic_only_row_it_can_refute(fixture_data) -> None:
    """The no-answer control, split by which layer owns which half of the claim.

    Policy's half: a semantic-only candidate carrying a material conflict is
    rejected outright — `Veterinary Surgeon, Small Animal Clinic` cannot reach
    the board on cosine order alone. The residual half is rows whose stored
    fields refute nothing (a single-segment title has no org path, and a query
    naming no family asserts none); those are the semantic floor's to exclude,
    and until one is calibrated the source does not run at all
    (`test_an_unmeasured_semantic_floor_disables_the_source_it_cannot_bound`).

    What this pins in both directions: every refutable row must reject, and no
    row of a no-answer query may ever be `exact` or `close`.
    """
    postings = {p["key"]: p for p in fixture_data["postings"]}
    query_text = next(q["text"] for q in fixture_data["queries"] if q["key"] == "no_answer_vet")
    signature = query_signature(query_text)

    refutable, admitted_classes = 0, []
    for posting in postings.values():
        candidate = _sig(posting["title"], family=posting["family"], track=posting["track"],
                         level_band=posting["level_band"], domains=posting["domains"],
                         company=posting["company"])
        conflicts = material_conflicts(signature, candidate)
        decision = classify_candidate(signature, _evidence(candidate, sources=("semantic",)))

        if conflicts:
            refutable += 1
            assert not decision.admitted, (
                f"{posting['key']} carries {[c.value for c in conflicts]} and is semantic-only, "
                "so it must be rejected, not ranked"
            )
        if decision.match_class is not None:
            admitted_classes.append((posting["key"], decision.match_class))

    assert refutable >= 10, "control cohort stopped exercising the reject branch"
    assert all(cls is MatchClass.RELATED for _, cls in admitted_classes), (
        f"a no-answer query produced a close/exact row: {admitted_classes}"
    )


def test_prime_video_target_is_the_only_exact_row_in_the_fixture(fixture_data) -> None:
    """One exact row for the regression query, and zero false exacts."""
    key = exact_title_key(PV_QUERY)
    exact_rows = [p["key"] for p in fixture_data["postings"]
                  if exact_title_key(p["title"]) == key]
    assert exact_rows == ["amazon-10428842"]
