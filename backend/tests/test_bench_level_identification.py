import json
from types import SimpleNamespace

import pytest
from sqlalchemy import select
from sqlalchemy.engine import make_url

from scripts import bench_level_identification as bench
from tracker.db.models import Job


def sample(**updates):
    return {
        "id": 1, "company": "microsoft", "req_id": "source-1", "title": "Software Engineer",
        "description_text": "Build distributed storage and reliable orchestration services for payments across multiple regions.",
        "family": "software_engineering", "track": "technical", "level_year": 2026,
        "raw_level": "IC5", "level_band": "mid", "level_basis": "none",
        "level_confidence": "unconfirmed", "status": "open", "location_groups": ["united_states"],
        "disclosed_base_min": 150000, "disclosed_base_max": 230000,
        "disclosed_currency": "USD", "disclosed_pay_basis": "base", "disclosed_pay_period": "year",
        "disclosed_confidence": "high", "disclosed_source": "connector",
    } | updates


def test_private_artifacts_are_atomic_immutable_and_not_written_to_a_checkout(tmp_path):
    path = tmp_path / "notes" / "artifact.json"
    bench.write_artifact(path, {"value": 1})
    with pytest.raises(FileExistsError):
        bench.write_artifact(path, {"value": 2})
    assert json.loads(path.read_text()) == {"value": 1}
    assert not list(path.parent.glob(".level-artifact-*"))
    repo = tmp_path / "checkout"
    repo.mkdir()
    (repo / ".git").write_text("gitdir: /another/repository")
    with pytest.raises(ValueError, match="outside a repository"):
        bench.write_artifact(repo / "audit.json", {})
    assert not (repo / "audit.json").exists()


def test_capture_requires_explicit_live_opt_in_and_preserves_url_components(monkeypatch):
    live = "postgresql+asyncpg://reader:secret@localhost/roleband?host=/tmp/socket"
    monkeypatch.setattr(bench, "get_settings", lambda: SimpleNamespace(database_url=live))
    with pytest.raises(ValueError, match="allow-live"):
        bench.database_url("roleband", allow_live=False)
    actual = make_url(bench.database_url("roleband_scratch", allow_live=False))
    assert actual.database == "roleband_scratch"
    assert actual.username == "reader" and actual.password == "secret"
    assert actual.query["host"] == "/tmp/socket"


def test_a_frozen_cohort_counts_reachability_without_counting_repeated_titles():
    rows = [sample(id=1, title="Payments Engineer"), sample(id=2, title="  Payments  Engineer "),
            sample(id=3, raw_level=None, title="Software Engineer", has_embedding=True)]
    target = next(row for row in bench.frozen_cohort(rows)["targets"] if row["id"] == 3)
    assert target["anchor_titles"] == 1
    assert not target["reachable"]
    assert target["displayed_band"] is None
    rows.append(sample(id=4, title="Storage Engineer"))
    target = next(row for row in bench.frozen_cohort(rows)["targets"] if row["id"] == 3)
    assert target["anchor_titles"] == 2 and target["reachable"]


def test_label_provenance_counts_units_not_scraper_sightings():
    result = bench.provenance([sample(), sample(id=2), sample(id=3, raw_level=None)])
    assert result["anchor_rows"] == 2
    assert result["anchor_units"] == 1
    assert result["tiers"]["A"]["units"] == 1


def test_missing_year_does_not_silently_create_a_cross_vintage_cohort():
    row = sample()
    del row["level_year"]
    with pytest.raises(ValueError, match="evidence year"):
        bench.frozen_cohort([row])


def test_a_snapshot_without_context_cannot_claim_template_isolation():
    row = sample()
    del row["description_text"]
    with pytest.raises(ValueError, match="captured descriptions"):
        bench.grouped_snapshot([row])


def test_the_command_uses_a_frozen_file_and_masks_its_whole_range(tmp_path):
    snapshot, output = tmp_path / "snapshot.json", tmp_path / "masked.json"
    rows = [sample(), sample(id=2, title="Storage Engineer"),
            sample(id=3, disclosed_base_max=260000), sample(id=4, disclosed_base_max=None)]
    snapshot.write_text(json.dumps({"jobs": rows}))
    assert bench.main(["mask", str(snapshot), "--target", "1", "--mode", "M3", "--out", str(output)]) == 0
    result = json.loads(output.read_text())
    assert result["excluded_label_ids"] == [1, 2]
    assert result["training_ids"] == [3, 4]
    assert all("raw_level" not in row for row in result["masked_inputs"])
    assert result["source_sha256"]
    with pytest.raises(FileExistsError):
        bench.main(["mask", str(snapshot), "--target", "1", "--mode", "M3", "--out", str(output)])


def test_a_duplicate_job_id_cannot_enter_a_frozen_benchmark(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text(json.dumps({"jobs": [sample(), sample()]}))
    with pytest.raises(ValueError, match="duplicate job ids"):
        bench.load_snapshot(path)


def lane(result, name, rule="exact", family="same_company", field="predicted"):
    return result["lanes"][name][family][rule][field]


def test_an_anchor_in_the_targets_own_group_cannot_support_it():
    separate = [sample(id=1, req_id="r1", title="Senior Software Engineer", raw_level=None),
                sample(id=2, req_id="r2", title="Senior Platform Engineer", raw_level=None),
                sample(id=3, req_id="r3", title="Senior Storage Engineer", raw_level=None)]
    result = bench.benchmark(separate)
    assert lane(result, "title_identity") == 3 and lane(result, "grouped") == 3
    assert lane(result, "grouped", field="correct") == 3
    one_requisition = [row | {"req_id": "r1"} for row in separate]
    result = bench.benchmark(one_requisition)
    assert lane(result, "title_identity") == 3
    assert lane(result, "grouped") == 0


def test_sealing_a_signature_withholds_a_printed_grade_but_keeps_a_stated_title():
    silent_titles = [sample(id=1, req_id="r1", title="Software Engineer"),
                     sample(id=2, req_id="r2", title="Storage Engineer"),
                     sample(id=3, req_id="r3", title="Reliability Engineer")]
    result = bench.benchmark(silent_titles)
    assert result["tiers"] == {"A": 3}
    assert lane(result, "grouped") == 3 and lane(result, "grouped", field="correct") == 3
    assert lane(result, "grouped_m3") == 0

    stated_titles = [silent_titles[0],
                     sample(id=2, req_id="r2", title="Senior Storage Engineer"),
                     sample(id=3, req_id="r3", title="Senior Reliability Engineer")]
    result = bench.benchmark(stated_titles)
    assert lane(result, "grouped") == 3
    assert lane(result, "grouped_m3") == 1
    assert lane(result, "grouped_m3_hard") == 0


def test_the_cross_employer_lane_never_reads_the_target_employer():
    rows = [sample(id=1, req_id="r1", company="microsoft", title="Senior Software Engineer", raw_level=None),
            sample(id=2, req_id="r2", company="microsoft", title="Senior Platform Engineer", raw_level=None),
            sample(id=3, req_id="r3", company="microsoft", title="Senior Storage Engineer", raw_level=None),
            sample(id=4, req_id="r4", company="acme", title="Staff Software Engineer", raw_level=None),
            sample(id=5, req_id="r5", company="globex", title="Staff Platform Engineer", raw_level=None)]
    result = bench.benchmark(rows)
    assert lane(result, "grouped", field="correct") == 3
    assert lane(result, "grouped", family="cross_employer") == 3
    assert lane(result, "grouped", family="cross_employer", field="correct") == 0


def test_the_constant_band_baseline_reports_the_label_base_rate():
    rows = [sample(id=index, req_id=f"r{index}", title=title, raw_level=None) for index, title in
            enumerate(("Senior Software Engineer", "Senior Platform Engineer",
                       "Senior Storage Engineer", "Staff Search Engineer"), start=1)]
    result = bench.benchmark(rows)
    assert result["constant_band"]["band"] == "senior"
    assert result["constant_band"]["share"] == 0.75
    assert result["title_only"]["per_tier"]["C"]["agreement"] == 1.0


@pytest.mark.asyncio
async def test_capture_reads_the_real_scratch_database_without_rewriting_it(db_session, monkeypatch):
    url = db_session.bind.url
    assert make_url(url).database.startswith("roleband_test_")
    monkeypatch.setattr(bench, "get_settings", lambda: SimpleNamespace(database_url=url.render_as_string(hide_password=False)))
    db_session.add(Job(company="microsoft", req_id="source-1", dedupe_key="microsoft:source-1", title="Software Engineer",
                       url="https://example.test/jobs/source-1", level_band="senior", raw_level="IC5",
                       locations=["Seattle, WA"], location_groups=["united_states"],
                       family="software_engineering", description_text=sample()["description_text"],
                       disclosed_base_min=150000, disclosed_base_max=230000, disclosed_currency="USD",
                       disclosed_pay_basis="base", disclosed_pay_period="year", disclosed_source="connector",
                       disclosed_confidence="high"))
    await db_session.commit()
    captured = await bench.capture(make_url(url).database, allow_live=True)
    assert captured["metadata"]["read_only"] == "on"
    assert captured["metadata"]["database"] == make_url(url).database
    assert len(captured["jobs"]) == 1
    assert captured["jobs"][0]["raw_level"] == "IC5"
    stored = (await db_session.execute(select(Job))).scalar_one()
    assert stored.raw_level == "IC5" and stored.level_band == "senior"
