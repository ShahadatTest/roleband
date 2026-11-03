import copy
import hashlib

import pytest

from tracker.analytics.level_study_sources import compile_sources, source_fingerprint


def row(**updates):
    return {"id": 1, "company": "waymo", "req_id": "r1", "title": "Machine Learning Engineer",
            "description_text": "Own the model training platform across teams.", "raw_level": "5/6",
            "family": "ml_ai_research", "track": "technical", "location_groups": ["united_states"],
            "disclosed_base_min": 150000, "disclosed_base_max": 250000,
            "disclosed_currency": "USD", "disclosed_pay_basis": "base", "disclosed_pay_period": "year",
            "disclosed_confidence": "high", "disclosed_source": "connector", "level_year": 2026,
            "level_band": "senior", "level_confidence": "confirmed", "independent_band": "senior"} | updates


def span(text, **extra):
    return {"start": 0, "end": len(text), "quote": text} | extra


def fixture():
    source = row()
    documents = {}
    mappings = []
    for code, band in (("5", "senior"), ("6", "staff")):
        text = f"The employer's engineering grade {code} maps to {band}."
        digest = hashlib.sha256(text.encode()).hexdigest()
        documents[digest] = text
        mappings.append({"company": "waymo", "code": code, "band": band, "status": "approve",
                         "basis": "employer_ladder",
                         "method": "human", "reviewer": "Mapping reviewer", "reason": "Reviewed employer ladder evidence.",
                         "allowed_families": ["ml_ai_research"], "allowed_tracks": ["technical"],
                         "document_sha256": digest, "evidence": span(text)})
    decision = {"id": 1, "source_sha256": source_fingerprint(source), "status": "approve",
                "method": "human", "reviewer": "Source reviewer", "reason": "Reviewed source and role.",
                "role": {"family": "ml_ai_research", "track": "technical"},
                "role_evidence": span(source["description_text"], field="description_text"),
                "grade_evidence": {"kind": "structured_field", "field": "Job Level", "value": "5/6"},
                "permissible_bands": ["senior", "staff"]}
    group_reviews = [{"group": "g1", "members": [1], "source_sha256": {"1": source_fingerprint(source)},
                      "status": "approve", "method": "human", "reviewer": "Group reviewer", "reason": "Verified group members."}]
    return {"rows": [source], "reviews": [decision], "mappings": mappings, "documents": documents,
            "groups": {1: "g1"}, "group_reviews": group_reviews, "multi_level": "preserve"}


def test_multi_level_source_keeps_complete_code_and_band_sets():
    result = compile_sources(**fixture())
    target = result["targets"][0]
    assert target["codes"] == ["5", "6"] and target["bands"] == ["senior", "staff"]
    assert not target["primary_single_band"] and "band" not in target
    assert result["counts"]["admitted"] == 1
    assert result["authority"] == "reviewed source targets only; no study or promotion gate implied"


def test_lower_band_reader_output_cannot_replace_a_permissible_set():
    data = fixture()
    data["reviews"][0]["permissible_bands"] = ["senior"]
    with pytest.raises(ValueError, match="permissible"):
        compile_sources(**data)


def test_explicit_exclusion_policy_retains_multi_level_exclusion_in_denominator():
    data = fixture()
    data["multi_level"] = "exclude"
    result = compile_sources(**data)
    assert not result["targets"]
    assert result["decisions"][0]["reason"] == "multi-level source excluded by policy"
    assert result["counts"]["reviewed"] == 1


@pytest.mark.parametrize("field", ["level_band", "level_confidence", "independent_band"])
def test_stored_classifier_outputs_cannot_supply_or_change_truth(field):
    data = fixture()
    data["rows"][0][field] = "director_plus"
    assert compile_sources(**data)["targets"][0]["bands"] == ["senior", "staff"]


def test_pending_source_mapping_and_group_reviews_are_never_approval():
    for field in ("reviews", "mappings", "group_reviews"):
        data = fixture()
        for r in data[field]:
            r["status"] = "pending"
        assert not compile_sources(**data)["targets"]


def test_changed_source_or_group_membership_invalidates_the_review():
    data = fixture()
    data["rows"][0]["description_text"] += " Manage a team."
    with pytest.raises(ValueError, match="fingerprint"):
        compile_sources(**data)
    data = fixture()
    data["rows"].append(row(id=2, req_id="r2"))
    data["groups"][2] = "g1"
    with pytest.raises(ValueError, match="membership"):
        compile_sources(**data)


@pytest.mark.parametrize("change", ["mapping_quote", "mapping_method", "role_quote", "wrong_field", "wrong_value"])
def test_forged_source_or_mapping_evidence_is_rejected(change):
    data = fixture()
    if change == "mapping_quote":
        data["mappings"][0]["evidence"]["quote"] = "Unseen employer assertion"
    if change == "mapping_method":
        data["mappings"][0]["method"] = "model"
    if change == "role_quote":
        data["reviews"][0]["role_evidence"]["quote"] = "Manage 20 engineers."
    if change == "wrong_field":
        data["reviews"][0]["grade_evidence"]["field"] = "Guessed Grade"
    if change == "wrong_value":
        data["reviews"][0]["grade_evidence"]["value"] = "5"
    with pytest.raises(ValueError):
        compile_sources(**data)


def test_product_track_does_not_admit_a_director_title():
    data = fixture()
    data["rows"][0] |= {"title": "Director of Product, Ecosystem", "family": "product_management", "track": "product_program"}
    data["reviews"][0]["source_sha256"] = source_fingerprint(data["rows"][0])
    data["reviews"][0]["role"] = {"family": "product_management", "track": "product_program"}
    result = compile_sources(**data)
    assert not result["targets"] and result["decisions"][0]["reason"] == "role outside initial study scope"


def test_a_missing_mapping_never_silently_drops_one_of_the_codes():
    data = fixture()
    data["mappings"].pop()
    result = compile_sources(**data)
    assert not result["targets"] and result["decisions"][0]["reason"] == "unreviewed mapping"


def test_duplicate_source_decisions_are_rejected():
    data = fixture()
    data["reviews"].append(copy.deepcopy(data["reviews"][0]))
    with pytest.raises(ValueError, match="duplicate"):
        compile_sources(**data)


def configured_source(source, bands):
    data = fixture()
    data["rows"] = [source]
    review = data["reviews"][0]
    review["source_sha256"] = source_fingerprint(source)
    review["role"] = {"family": source["family"], "track": source["track"]}
    review["role_evidence"] = span(source["description_text"], field="description_text")
    review["permissible_bands"] = list(dict.fromkeys(bands.values()))
    data["group_reviews"][0]["source_sha256"] = {"1": source_fingerprint(source)}
    template = data["mappings"][0]
    data["mappings"] = []
    data["documents"] = {}
    for code, band in bands.items():
        text = f"Employer ladder: {code.removeprefix('title:')} corresponds to {band}."
        digest = hashlib.sha256(text.encode()).hexdigest()
        data["documents"][digest] = text
        data["mappings"].append(template | {"company": source["company"], "code": code, "band": band,
                                         "document_sha256": digest, "evidence": span(text),
                                         "allowed_families": [source["family"]]})
    return data


def test_description_routes_keep_native_alternatives_even_when_both_map_to_one_band():
    text = ("Own the storage platform.\nSoftware Engineering IC5 - The typical base pay range is USD $140,000.\n"
            "Software Engineering IC6 - The typical base pay range is USD $165,000.")
    data = configured_source(row(company="microsoft", raw_level=None, description_text=text, family="software_engineering"),
                             {"IC5": "principal", "IC6": "principal"})
    data["reviews"][0]["grade_evidence"] = {"kind": "description_grade", "spans": [span(text, field="description_text")]}
    target = compile_sources(**data)["targets"][0]
    assert target["codes"] == ["IC5", "IC6"] and target["bands"] == ["principal"]
    assert target["primary_single_band"]
    first = text[:text.index("\nSoftware Engineering IC6")]
    data["reviews"][0]["grade_evidence"]["spans"] = [span(first, field="description_text")]
    with pytest.raises(ValueError, match="omits"):
        compile_sources(**data)


def test_company_vocabulary_requires_independent_document_review():
    source = row(company="google", raw_level=None, title="Senior Software Engineer", family="software_engineering")
    data = configured_source(source, {"title:senior software engineer": "senior"})
    data["reviews"][0]["grade_evidence"] = span(source["title"], kind="company_vocabulary", field="title", phrase=source["title"])
    with pytest.raises(ValueError, match="basis"):
        compile_sources(**data)
    data["mappings"][0]["basis"] = "independently_reviewed_vocabulary"
    target = compile_sources(**data)["targets"][0]
    assert target["tier"] == "B" and target["bands"] == ["senior"]


@pytest.mark.parametrize("basis", ["salary", "model_prediction", "generic_title", None])
def test_pay_derived_or_model_mapping_is_not_primary_truth(basis):
    data = fixture()
    data["mappings"][0]["basis"] = basis
    with pytest.raises(ValueError, match="basis"):
        compile_sources(**data)


def test_group_review_cannot_merge_incompatible_role_families():
    data = fixture()
    second = row(id=2, family="hardware_engineering")
    data["rows"].append(second)
    data["groups"][2] = "g1"
    data["group_reviews"][0]["members"] = [1, 2]
    data["group_reviews"][0]["source_sha256"]["2"] = source_fingerprint(second)
    assert compile_sources(**data)["decisions"][0]["reason"] == "source group has incompatible frozen roles"


def test_approved_mapping_is_limited_to_its_reviewed_role_scope():
    data = fixture()
    data["mappings"][0]["allowed_tracks"] = ["management"]
    assert compile_sources(**data)["decisions"][0]["reason"] == "mapping outside reviewed role scope"


def test_commands_prepare_pending_evidence_and_compile_only_explicit_reviews(tmp_path):
    import json

    from scripts.review_level_sources import main

    data = fixture()
    files = {}
    for name, content in {"snapshot": {"jobs": data["rows"]}, "groups": {"groups": data["groups"]}, "ids": [1],
                          "reviews": data["reviews"], "mappings": data["mappings"], "documents": data["documents"],
                          "group-reviews": data["group_reviews"]}.items():
        files[name] = tmp_path / f"{name}.json"
        files[name].write_text(json.dumps(content))
    output = tmp_path / "prepared.json"
    base = ["--snapshot", str(files["snapshot"]), "--groups", str(files["groups"])]
    assert main(["prepare", *base, "--ids", str(files["ids"]), "--out", str(output)]) == 0
    packet = json.loads(output.read_text())
    assert packet["reviews"][0]["status"] == "pending"
    assert packet["source_packets"][0]["permissible_bands"] is None
    assert "level_band" not in packet["source_packets"][0]["source"]
    assert packet["source_packets"][0]["source"]["raw_level"] == "5/6"
    compiled = tmp_path / "compiled.json"
    flags = [value for key in ("reviews", "mappings", "documents", "group-reviews") for value in ("--" + key, str(files[key]))]
    args = ["compile", *base, *flags, "--multi-level", "preserve", "--out", str(compiled)]
    assert main(args) == 0
    result = json.loads(compiled.read_text())
    assert result["targets"][0]["bands"] == ["senior", "staff"]
    assert result["inputs"]["reviews"]["sha256"] and result["snapshot_sha256"]
    with pytest.raises(FileExistsError):
        main(args)
    files["reviews"].write_text(json.dumps(packet["reviews"]))
    pending = tmp_path / "pending.json"
    assert main(args[:-1] + [str(pending)]) == 0
    assert not json.loads(pending.read_text())["targets"]
