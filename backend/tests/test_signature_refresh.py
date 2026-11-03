from dataclasses import replace

import pytest

from tracker.analytics.level_evaluation import GroupInput
from tracker.analytics.signature_refresh import (
    assignment,
    independent_groups,
    measure,
    signature_key,
)

_BODY = (
    "Design distributed payment processing services and maintain resilient transactional storage. "
    "Own incident response procedures and collaborate with product engineers on reliable deployments. "
    "Develop monitoring tools for production workloads and implement system capacity planning. "
    "Review technical designs and improve operational documentation across the engineering organization. "
    "We support flexible working arrangements and offer comprehensive health insurance."
)
_OTHER = (
    "Build compilers for numerical computing using vectorized instruction sets on custom processors. "
    "Investigate algorithmic performance with benchmarks and develop optimization passes for graph execution. "
    "Partner with hardware architects to analyze memory layouts and instruction scheduling. "
    "Publish engineering specifications documenting correctness properties of floating point computations. "
    "Our benefits include vacation leave and professional development programs for all employees."
)


def posting(job_id=1, **updates):
    return {
        "id": job_id, "req_id": str(job_id), "company": "acme", "family": "software_engineering",
        "track": "technical", "title": "Senior Software Engineer, Payments", "raw_level": None,
        "description_text": _BODY, "level_year": 2026, "location_groups": ["united_states"],
        "disclosed_base_min": 150000, "disclosed_base_max": 230000, "disclosed_currency": "USD",
        "disclosed_pay_basis": "base", "disclosed_pay_period": "year",
        "disclosed_confidence": "high", "disclosed_source": "connector",
    } | updates


def pair():
    return [posting(), posting(2, title="Senior Software Engineer, Compilers", description_text=_OTHER)]


def accepted(rows):
    return [s for s in measure(rows)["signatures"] if s["eligible"]]


@pytest.mark.parametrize("updates", [
    {"disclosed_pay_basis": "total"}, {"disclosed_pay_basis": "ote"},
    {"disclosed_base_min": 180, "disclosed_base_max": 220, "disclosed_pay_period": "hour"},
    {"disclosed_base_min": 300000}, {"disclosed_base_max": None},
    {"disclosed_currency": "CAD"}, {"location_groups": ["united_states", "canada"]},
    {"disclosed_confidence": "low"}, {"disclosed_source": "model"},
    {"track": "management"}, {"family": "sales_business_development"},
    {"req_id": ""}, {"description_text": ""},
])
def test_ineligible_anchor_cannot_complete_a_signature(updates):
    a, b = pair()
    assert len(accepted([a, b])) == 1
    assert accepted([a, b | updates]) == []


def test_labels_are_reread_without_stored_pay_or_model_guesses():
    a, b = pair()
    false = b | {"title": "Software Engineer", "level_band": "senior", "level_basis": "pay_grade",
                 "independent_band": "senior", "independent_confidence": "confirmed"}
    assert accepted([a, false]) == []
    assert accepted([a, false | {"title": b["title"]}])[0]["band"] == "senior"


@pytest.mark.parametrize("title", ["Senior / Staff Software Engineer", "Full Stack Staff & Software Engineer",
                                  "Staff+ Research Engineer"])
def test_multilevel_titles_cannot_manufacture_a_unique_band(title):
    a, b = pair()
    assert accepted([a, b | {"title": title}]) == []


@pytest.mark.parametrize("variant", range(50))
def test_reposts_mirrors_and_near_templates_do_not_increase_support(variant):
    a = posting()
    b = posting(2, title="Senior Software Engineer, Payments Platform",
                description_text=_BODY.replace("resilient", f"resilient version{variant}"))
    if variant % 3 == 0:
        b["req_id"] = a["req_id"]
    elif variant % 3 == 1:
        a["place_set_id"] = b["place_set_id"] = 7
    assert accepted([a, b]) == []
    assert accepted([a, b, *[b | {"id": n + 3} for n in range(10)]]) == []


def test_same_title_different_requisitions_still_count_once():
    a, b = pair()
    assert accepted([a, b | {"title": a["title"]}]) == []


def test_independent_openings_count_once_with_provenance_and_no_conflict():
    a, b = pair()
    signature = accepted([a, b, a | {"id": 3}])[0]
    assert signature["support"] == signature["units"] == 2
    assert {anchor["tier"] for anchor in signature["anchors"]} == {"C"}
    assert accepted([a, b | {"title": "Staff Software Engineer, Compilers"}]) == []


def test_disagreeing_mirrors_are_quarantined_rather_than_majority_washed():
    a, b = pair()
    conflicting = a | {"id": 3, "title": "Staff Software Engineer, Payments"}
    assert accepted([a, b, conflicting]) == []


def test_near_template_linking_is_deterministic_and_employer_scoped():
    a = GroupInput(1, "acme", "1", "Senior Software Engineer", _BODY)
    b = replace(a, job_id=2, req_id="2", title="Software Engineer", description=_BODY.replace("resilient", "durable"))
    c = replace(b, job_id=3, company="other")
    groups, links = independent_groups([a, b, c])
    assert groups[1] == groups[2] != groups[3]
    assert links and links[0].similarity >= .85
    assert independent_groups([c, b, a]) == (groups, links)


def test_common_benefits_do_not_merge_different_roles_or_short_texts():
    a = GroupInput(1, "acme", "1", "Software Engineer", _BODY)
    b = replace(a, job_id=2, req_id="2", description=_OTHER)
    c = replace(a, job_id=3, req_id="3", title="Financial Analyst")
    groups, _ = independent_groups([a, b, c])
    assert len(set(groups.values())) == 3
    short = [replace(a, job_id=n, req_id=str(n), description="Benefits and salary") for n in (4, 5)]
    assert len(set(independent_groups(short)[0].values())) == 2


def test_protected_employer_grade_and_director_title_survive_conflicting_transfer():
    a, b = pair()
    for target in [posting(3, company="microsoft", title="Software Engineer", raw_level="IC6"),
                   posting(3, title="Director, Software Engineering")]:
        report = measure([a, b, target])
        signature = accepted([a, b])[0] | {"key": list(signature_key(target))}
        band, reason = assignment(target, signature, report["groups"])
        assert band is None
        assert reason in {"protected employer-stated grade", "title already names a band"}


def test_assignment_requires_disjoint_context_and_keeps_existing_information():
    a, b = pair()
    target = posting(3, title="Software Engineer, Storage", description_text=_OTHER + " additional words")
    report = measure([a, b, target])
    signature = accepted([a, b])[0]
    groups = {1: "a", 2: "b", 3: "target"}
    assert assignment(target, signature, groups)[0] == "senior"
    assert assignment(target | {"level_year": 2027}, signature, groups)[0] is None
    shared = report["groups"] | {3: signature["anchors"][0]["group"]}
    assert assignment(target, signature, shared)[0] is None
    assert target["disclosed_base_min"] == 150000


def test_an_unverified_captured_grade_cannot_manufacture_a_label():
    a = posting(company="microsoft", title="Software Engineer", raw_level="IC5")
    b = posting(2, company="microsoft", title="Software Engineer, Compilers", description_text=_OTHER,
                independent_raw_level="IC5", level_band="principal", level_basis="model")
    assert accepted([a, b]) == []
    assert accepted([a, b | {"raw_level": "IC5"}])[0]["band"] == "principal"


def test_runtime_keeps_stated_grade_when_exact_salary_says_principal():
    from datetime import UTC, datetime

    from tracker.enrich.level_mapper import read_level
    from tracker.schema import LevelBand, LevelBasis, RawJob, SourceDisclosedComp

    raw = RawJob(company="microsoft", req_id="independent-opening", title="Product Manager", url="",
                 posted_at=datetime(2026, 6, 1, tzinfo=UTC),
                 source_disclosed_comp=SourceDisclosedComp(base_min=142800, base_max=274800,
                                                          currency="USD", pay_basis="base", pay_period="year"))
    assert read_level(raw, "product_management").band is LevelBand.PRINCIPAL
    raw.raw_level = "IC3"
    reading = read_level(raw, "product_management")
    assert reading.band is LevelBand.MID
    assert reading.basis is LevelBasis.STATED


def test_review_covers_removed_originals_and_never_promotes_mechanical_acceptance():
    from scripts.refresh_level_signatures import review_proposals

    a, b = pair()
    target = posting(3, title="Software Engineer, Storage", description_text=_OTHER + " unique context")
    removed = posting(4, title="Director, Software Engineering", track="management")
    rows = [a, b, target, removed]
    originals = [{"id": 3, "predicted_band": "senior"}, {"id": 4, "predicted_band": "senior"}]
    report = review_proposals(rows, [target, removed], originals, measure(rows))
    assert report["reviewed_original_count"] == 2
    assert report["reconciliation"] == {"unchanged": 1, "removal": 1}
    assert report["promotion_allowed"] is False
    assert report["companies"]["acme"]["ceiling_passes"] is False
    assert report["reviews"][0]["decision"] == "source-review-required"
    with pytest.raises(ValueError, match="absent from frozen cohort"):
        review_proposals(rows, [target], originals, measure(rows))


def test_offline_cli_preserves_frozen_inputs_and_refuses_overwrite(tmp_path, capsys):
    import hashlib
    import json

    from scripts.refresh_level_signatures import main

    a, b = pair()
    target = posting(3, title="Software Engineer, Storage", description_text=_OTHER + " unique context")
    snapshot, cohort, original, output = [tmp_path / name for name in ("snapshot.json", "cohort.json", "original.json", "out.json")]
    snapshot.write_text(json.dumps({"jobs": [a, b, target]}))
    cohort.write_text(json.dumps({"targets": [target]}))
    original.write_text(json.dumps({"proposals": [{"id": 3, "predicted_band": "senior"}]}))
    before = [hashlib.sha256(path.read_bytes()).hexdigest() for path in (snapshot, cohort, original)]
    args = ["--snapshot", str(snapshot), "--cohort", str(cohort), "--original", str(original), "--out", str(output)]
    assert main(args) == 0
    assert json.loads(output.read_text())["proposal_review"]["reviewed_original_count"] == 1
    with pytest.raises(FileExistsError):
        main(args)
    assert before == [hashlib.sha256(path.read_bytes()).hexdigest() for path in (snapshot, cohort, original)]


def test_runtime_context_is_rebuilt_without_rewriting_frozen_classifications():
    from scripts.refresh_level_signatures import project_context

    frozen = posting(title="Senior Electrical Engineer", family="software_engineering")
    projected = project_context([frozen])[0]
    assert projected["family"] == "hardware_engineering"
    assert projected["captured_family"] == frozen["family"] == "software_engineering"
    assert projected["track"] == "technical"


def test_grouping_keys_ignore_description_pay_and_grade_values():
    from tracker.analytics.signature_refresh import _shingles

    assert _shingles(_BODY + " Pay $150k - $230k. Grade: 4; level 5; IC6.") == _shingles(
        _BODY + " Pay $700k - $900k. Grade: 9; level 8; IC3.")


def test_missing_capture_rejects_original_proposal_instead_of_losing_the_review():
    from scripts.refresh_level_signatures import review_proposals

    rows = pair()
    target = posting(3, title="Software Engineer, Storage")
    original = [{"id": 3, "predicted_band": "senior"}]
    report = review_proposals(rows, [target], original, measure(rows))
    assert report["reviewed_original_count"] == 1
    assert report["reviews"][0]["decision"] == "reject"
    assert report["reviews"][0]["reason"] == "frozen target differs from captured source evidence"


@pytest.mark.parametrize(("left", "right"), [
    ("Senior Mechanical Engineer, Water Projects", "Electrical Engineer, Water Projects"),
    ("Senior Backend Engineer - Access Control", "Senior Frontend Engineer - Access Control"),
    ("Android Software Engineer, Consumer Engineering", "Senior iOS Software Engineer, Consumer Engineering"),
])
def test_shared_boilerplate_cannot_merge_distinct_role_specialties(left, right):
    a = GroupInput(1, "acme", "one", left, _BODY)
    b = GroupInput(2, "acme", "two", right, _BODY.replace("resilient", "durable"))
    groups, links = independent_groups([a, b])
    assert groups[1] != groups[2]
    assert links == []


def test_generic_title_cannot_bridge_incompatible_specialties_transitively():
    inputs = [GroupInput(1, "acme", "one", "Software Engineer", _BODY),
              GroupInput(2, "acme", "two", "Android Software Engineer", _BODY),
              GroupInput(3, "acme", "three", "iOS Software Engineer", _BODY)]
    groups, _ = independent_groups(inputs)
    assert groups[2] != groups[3]
    assert groups[1] == groups[2]
