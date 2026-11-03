import copy

import pytest

from tracker.analytics.level_review import (
    adjudicate,
    draw_representative,
    prepare_review,
    validate_reviews,
)


def cohort(count=650):
    return [{"id": i, "company": "apple" if i < 180 else f"company-{i % 20}",
             "title": f"Systems Engineer {i}", "description_text": "Own the storage service and its architecture across multiple teams.",
             "family": "software_engineering", "track": "technical", "location_groups": ["united_states"],
             "disclosed_base_min": 100000, "disclosed_base_max": 150000,
             "level_confidence": "unconfirmed", "candidate_output": "FORBIDDEN", "level_band": "principal",
             "neighbors": ["FORBIDDEN"], "embedding": [99]} for i in range(count)]


def prepared():
    rows = cohort()
    groups = {r["id"]: f"group-{r['id']}" for r in rows}
    nonapple = list(range(180, 650))
    apple = list(range(180))
    selections = {"high_confidence": apple[:80] + nonapple[:170],
                  "representative": apple[80:160] + nonapple[170:340],
                  "edge": apple[160:] + nonapple[340:420]}
    return prepare_review(rows, groups, selections, high_confidence_ids=set(selections["high_confidence"]),
                          seed=42, reviewers=("Alice", "Bob"))


def responses(bundle):
    return [{"case_id": a["case_id"], "reviewer": a["reviewer"], "bands": ["staff"],
             "method": "human", "not_identifiable": False, "confidence": "medium",
             "evidence": [{"field": "description_text", "start": 0, "end": 23, "quote": "Own the storage service"}],
             "reason": "Owns cross-team architecture."} for a in bundle["sealed"]["assignments"]]


def test_packets_hide_candidate_incumbent_strata_and_duplicate_identity():
    bundle = prepared()
    assert len(bundle["packets"]["Alice"]) == 600 and len(bundle["packets"]["Bob"]) == 150
    for packets in bundle["packets"].values():
        assert all(set(p) == {"case_id", "company", "title", "description_text"} for p in packets)
        assert all("FORBIDDEN" not in str(p) for p in packets)
    first = {a["job_id"]: a["case_id"] for a in bundle["sealed"]["assignments"] if a["reviewer"] == "Alice"}
    assert all(a["case_id"] != first[a["job_id"]] for a in bundle["sealed"]["assignments"] if a["reviewer"] == "Bob")
    assert prepared() == bundle


def test_representative_draw_is_reproducible_capped_and_group_disjoint():
    rows = cohort(1000)
    groups = {r["id"]: f"group-{r['id'] // 2}" for r in rows}
    selected = draw_representative(rows, groups, seed=12)
    assert len(selected) == 250 and len({groups[i] for i in selected}) == 250
    assert sum(rows[i]["company"] == "apple" for i in selected) <= 100
    assert selected == draw_representative(list(reversed(rows)), groups, seed=12)
    assert selected != draw_representative(rows, groups, seed=13)
    with pytest.raises(ValueError, match="sufficient"):
        draw_representative(rows[:10], groups, seed=12)


def test_same_group_cases_cannot_fill_the_sample():
    rows = cohort()
    with pytest.raises(ValueError, match="group"):
        prepare_review(rows, {r["id"]: "same" for r in rows},
                       {"high_confidence": list(range(250)), "representative": list(range(250, 500)), "edge": list(range(500, 600))},
                       high_confidence_ids=set(range(250)), seed=42, reviewers=("A", "B"))


def test_high_confidence_pool_and_exact_stratum_sizes_are_required():
    rows = cohort()
    groups = {r["id"]: str(r["id"]) for r in rows}
    selections = {"high_confidence": list(range(250)), "representative": list(range(250, 500)), "edge": list(range(500, 600))}
    with pytest.raises(ValueError, match="high-confidence"):
        prepare_review(rows, groups, selections, high_confidence_ids=set(), seed=42, reviewers=("A", "B"))
    with pytest.raises(ValueError, match="40%"):
        prepare_review(rows, groups, selections, high_confidence_ids=set(range(250)), seed=42, reviewers=("A", "B"))
    selections["edge"].pop()
    with pytest.raises(ValueError, match="stratum"):
        prepare_review(rows, groups, selections, high_confidence_ids=set(range(250)), seed=42, reviewers=("A", "B"))


def test_review_collection_requires_all_750_independent_grounded_responses():
    bundle = prepared()
    rows = responses(bundle)
    result = validate_reviews(bundle["sealed"], rows)
    assert result["reviewed_cases"] == 600 and result["double_reviewed"] == 150
    assert result["agreement"]["exact_set_agreement"] == 1 and result["agreement"]["kappa"] is None
    for bad in (rows[:-1], rows + [rows[0]]):
        with pytest.raises(ValueError, match="assignment"):
            validate_reviews(bundle["sealed"], bad)
    bad = copy.deepcopy(rows)
    bad[0]["evidence"][0]["quote"] = "Manage twenty engineers"
    with pytest.raises(ValueError, match="quote"):
        validate_reviews(bundle["sealed"], bad)
    bad = copy.deepcopy(rows)
    bad[0]["reviewer"] = "Bob"
    with pytest.raises(ValueError, match="reviewer"):
        validate_reviews(bundle["sealed"], bad)


def test_ambiguous_and_not_identifiable_labels_require_explicit_adjudication():
    bundle = prepared()
    rows = responses(bundle)
    rows[0] |= {"bands": ["senior", "staff"]}
    rows[1] |= {"bands": [], "not_identifiable": True, "evidence": [], "reason": "Scope is not stated."}
    assert not validate_reviews(bundle["sealed"], rows)["adjudicated"]
    finals = [{"job_id": case["job_id"], "adjudicator": "Carol", "bands": ["staff"], "not_identifiable": False,
               "method": "human", "confidence": "medium", "reason": "Reviewed source and both readings.", "evidence": rows[2]["evidence"]}
              for case in bundle["sealed"]["cases"]]
    finals[0] |= {"bands": ["senior", "staff"]}
    finals[1] |= {"bands": [], "not_identifiable": True, "evidence": []}
    sealed = adjudicate(bundle["sealed"], rows, finals)
    assert sealed["adjudicated"] and sealed["cases"] == 600
    assert sealed["labels"][0]["bands"] == ["senior", "staff"] and sealed["labels"][1]["not_identifiable"] is True
    with pytest.raises(ValueError, match="adjudication"):
        adjudicate(bundle["sealed"], rows, finals[:-1])


def test_kappa_retains_reviewer_orientation_when_responses_are_reordered():
    bundle = prepared()
    repeated = sorted(a["job_id"] for a in bundle["sealed"]["assignments"] if a["reviewer"] == "Bob")
    lookup = {a["case_id"]: a for a in bundle["sealed"]["assignments"]}
    rows = responses(bundle)
    for r in rows:
        assignment = lookup[r["case_id"]]
        if assignment["job_id"] in repeated:
            position = repeated.index(assignment["job_id"])
            r["bands"] = ["senior"] if position < (75 if r["reviewer"] == "Alice" else 50) else ["staff"]
    agreement = validate_reviews(bundle["sealed"], rows)["agreement"]
    assert agreement["exact_set_agreement"] == pytest.approx(125 / 150)
    assert agreement["kappa"] == pytest.approx(2 / 3)
    assert validate_reviews(bundle["sealed"], list(reversed(rows)))["agreement"] == agreement


@pytest.mark.parametrize("update", [
    {"method": "model"}, {"method": None}, {"bands": ["staff", "staff"]},
    {"bands": ["unconfirmed"]}, {"bands": [], "not_identifiable": False},
    {"bands": ["staff"], "not_identifiable": True}, {"evidence": []}, {"confidence": .99},
])
def test_prelabels_invalid_sets_and_unsupported_judgments_are_not_truth(update):
    bundle = prepared()
    rows = responses(bundle)
    rows[0] |= update
    with pytest.raises(ValueError):
        validate_reviews(bundle["sealed"], rows)


def test_review_key_cannot_be_rebound_to_another_source():
    bundle = prepared()
    rows = responses(bundle)
    bundle["sealed"]["cases"][0]["source"]["description_text"] = "Manage a team of twenty engineers."
    with pytest.raises(ValueError, match="fingerprint"):
        validate_reviews(bundle["sealed"], rows)


def test_same_person_cannot_fill_both_review_roles():
    rows = cohort()
    with pytest.raises(ValueError, match="distinct reviewers"):
        prepare_review(rows, {r["id"]: str(r["id"]) for r in rows}, {}, high_confidence_ids=set(),
                       seed=1, reviewers=("Alice", " alice "))


def test_command_exports_separate_packets_and_refuses_a_stale_candidate(tmp_path):
    import hashlib
    import json

    from scripts.prepare_level_review import main

    rows = cohort()
    source = tmp_path / "snapshot.json"
    source.write_text(json.dumps({"jobs": rows}))
    frozen = tmp_path / "cohort.json"
    frozen.write_text(json.dumps({"targets": rows}))
    groups = tmp_path / "groups.json"
    groups.write_text(json.dumps({"groups": {r["id"]: f"group-{r['id']}" for r in rows}}))
    bundle = prepared()
    selections = {s: [c["job_id"] for c in bundle["sealed"]["cases"] if c["stratum"] == s]
                  for s in ("representative", "high_confidence", "edge")}
    selection = tmp_path / "selection.json"
    selection.write_text(json.dumps(selections))
    candidate = tmp_path / "candidate.json"
    predictions = [{"id": r["id"], "high_confidence": r["id"] in selections["high_confidence"],
                    "band": "principal", "explanation": "CANDIDATE MUST NOT REACH REVIEWER"} for r in rows]
    candidate.write_text(json.dumps({"snapshot_sha256": "stale", "predictions": predictions}))
    out = tmp_path / "packets"
    args = ["packets", "--cohort", str(frozen), "--snapshot", str(source), "--groups", str(groups),
            "--selection", str(selection), "--candidate", str(candidate), "--reviewers", "Alice", "Bob",
            "--seed", "42", "--out-dir", str(out)]
    with pytest.raises(ValueError, match="snapshot"):
        main(args)
    assert not out.exists()
    candidate.write_text(json.dumps({"snapshot_sha256": hashlib.sha256(source.read_bytes()).hexdigest(), "predictions": predictions}))
    assert main(args) == 0
    assert len(json.loads((out / "reviewer-primary.json").read_text())["cases"]) == 600
    assert len(json.loads((out / "reviewer-secondary.json").read_text())["cases"]) == 150
    for name in ("reviewer-primary.json", "reviewer-secondary.json"):
        assert "CANDIDATE MUST NOT REACH REVIEWER" not in (out / name).read_text()
        assert "high_confidence" not in (out / name).read_text()
    with pytest.raises(FileExistsError):
        main(args)
    key = json.loads((out / "private-key.json").read_text())
    reviews = tmp_path / "responses.json"
    reviews.write_text(json.dumps(responses({"sealed": key["sealed"]})))
    collected = tmp_path / "collected.json"
    assert main(["collect", "--key", str(out / "private-key.json"), "--reviews", str(reviews), "--out", str(collected)]) == 0
    assert not json.loads(collected.read_text())["adjudicated"]


def test_partial_collection_never_claims_complete_or_adjudicated_labels():
    bundle = prepared()
    rows = responses(bundle)
    progress = validate_reviews(bundle["sealed"], rows[:1], complete=False)
    assert not progress["complete"] and not progress["adjudicated"]
    assert progress["readings"] == 1 and progress["expected_readings"] == 750
    assert progress["agreement"]["kappa"] is None
    with pytest.raises(ValueError, match="assignment"):
        adjudicate(bundle["sealed"], rows[:1], [])
    rows[0]["evidence"][0]["end"] = 1
    with pytest.raises(ValueError, match="quote"):
        validate_reviews(bundle["sealed"], rows[:1], complete=False)
