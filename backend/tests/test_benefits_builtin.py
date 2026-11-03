"""Benefits come from our dataset or from one plugin, never both.

Contracts, each on the real dataset: the dataset reader answers from the dataset
alone and the plugin reader from the plugin's rows alone, so neither can shape
the other (no per-cell precedence between them); reading
a plugin never changes what the dataset reader answers after; an unknown cell is
never shown as "not offered"; a label no alias maps is kept under its own name;
every evidence record keeps the dataset's rules (a named company, a taxonomy
type, an id of its own), and nothing the runtime does writes it (every file
hash unchanged).
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from types import SimpleNamespace

import pytest

from tests.plugin_seed import cover
from tracker.company_discovery import named_companies
from tracker.db.models import CompanyBenefit, CompanyProfile, PluginInstall
from tracker.plugins.registry import COMPANY_BENEFITS
from tracker.profiles.benefits_builtin import (
    DATASET,
    OTHER,
    builtin_cells,
    dataset_benefit_notes,
    dataset_benefits,
    plugin_benefits,
    problems,
    taxonomy,
)

#: One test drives Settings > Plugins, a route that can start a process.
pytestmark = pytest.mark.usefixtures("no_escape")

#: Lyft's retirement cell holds two employer mentions, worded differently.
COMPANY, CELL = "lyft", "retirement_plan"


def _row(name, provider="tpl", value_usd=None, value_text=None, country=None):
    return SimpleNamespace(name=name, value_usd=value_usd, value_text=value_text, description=None, source=provider,
                           provider=provider, company_slug=COMPANY, country=country)


def _items(groups):
    return [item for group in groups for item in group["items"]]


def _cell(groups, kind):
    return [i for i in _items(groups) if i["benefit_type"] == kind]


def _hashes() -> dict[str, str]:
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(DATASET.iterdir()) if p.is_file()}


# --------------------------------------------------------------------------- #
# One source
# --------------------------------------------------------------------------- #


OBSERVATIONS = "observations.jsonl"


def _records() -> list[dict]:
    with (DATASET / OBSERVATIONS).open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle]


def _check(tmp_path, lines: list[str]) -> list[str]:
    """The dataset's own check, on a copy whose records are `lines`."""
    copy = tmp_path / "benefits"
    shutil.copytree(DATASET, copy, dirs_exist_ok=True)
    (copy / OBSERVATIONS).write_text("".join(f"{line}\n" for line in lines), encoding="utf-8")
    return problems(copy, set(named_companies()))


def test_every_evidence_record_keeps_the_dataset_s_rules():
    """One record per line, each naming a company the app names and a type the
    taxonomy has, with an id no other record uses. A benefit with no record is
    unknown, so nothing pads the file and nothing restates a record."""
    assert (DATASET / OBSERVATIONS).read_text(encoding="utf-8").splitlines()
    assert problems(DATASET, set(named_companies())) == []


def test_a_broken_record_is_named_by_its_line(tmp_path):
    """Negative controls for the rules above: each break is reported at its line."""
    lines = (DATASET / OBSERVATIONS).read_text(encoding="utf-8").splitlines()[:3]
    employer = json.loads(lines[0])
    # The breaks below are made on a dataset record, built from the file's first employer record.
    first = {k: v for k, v in employer.items() if k not in ("supporting_capture_count", "display_excerpt")} | {
        "kind": "dataset", "context": "company_unknown_scope",
        "scope": {k: v for k, v in employer["scope"].items() if k != "scope_title"}}

    def line(**change) -> str:
        return json.dumps({**first, **change})

    def broken(*extra: str) -> list[str]:
        return _check(tmp_path, [*lines, *extra])

    assert broken() == []
    assert broken(line(observation_id="x")) == []
    assert broken('{"company": "1password",') == [f"{OBSERVATIONS}:4: not a JSON object"]
    assert broken(lines[0]) == [f"{OBSERVATIONS}:4: duplicate key ({employer['observation_id']!r},)"]
    assert broken(line(observation_id="x", benefit_type="moon_base")) == [
        f"{OBSERVATIONS}:4: benefit_type 'moon_base' is not in taxonomy.json"]
    assert broken(line(observation_id="x", company="not-a-named-company")) == [
        f"{OBSERVATIONS}:4: company 'not-a-named-company' is not a named company"]
    assert broken(line(observation_id="x", status="listed")) == [f"{OBSERVATIONS}:4: unknown fields ['status']"]
    assert broken(line(observation_id="x", context="job_specific")) == [
        f"{OBSERVATIONS}:4: context 'job_specific' does not fit a dataset record"]
    assert broken(line(observation_id="x", supporting_capture_count=2)) == [
        f"{OBSERVATIONS}:4: supporting_capture_count is kept on employer records only"]
    assert broken(line(observation_id="x", estimated_annual_value_usd="500")) == [
        f"{OBSERVATIONS}:4 estimated_annual_value_usd: '500' is not an integer"]
    assert broken(line(observation_id="x", estimated_annual_value_usd=True)) == [
        f"{OBSERVATIONS}:4 estimated_annual_value_usd: True is not an integer"]
    assert broken(line(observation_id="x", kind="rumour")) == [f"{OBSERVATIONS}:4 kind: 'rumour' not in ['employer', 'dataset']"]
    assert broken(line(observation_id="")) == [f"{OBSERVATIONS}:4 observation_id: required"]
    without_value = {k: v for k, v in first.items() if k != "estimated_annual_value_usd"}
    assert broken(json.dumps({**without_value, "observation_id": "x"})) == [
        f"{OBSERVATIONS}:4: estimated_annual_value_usd: required, null when unknown"]
    assert broken(line(observation_id="x", scope={"country": None})) == [
        f"{OBSERVATIONS}:4: scope needs ['employee_group', 'level', 'region', 'role_family']"]


def test_a_taxonomy_label_that_names_two_types_is_refused(tmp_path):
    """`classify` keeps one type per label, so a label two types share would
    silently file a plugin's row under whichever came last."""
    copy = tmp_path / "benefits"
    shutil.copytree(DATASET, copy)
    raw = json.loads((copy / "taxonomy.json").read_text(encoding="utf-8"))
    raw["benefit_types"][1]["aliases"].append(raw["benefit_types"][0]["label"])
    (copy / "taxonomy.json").write_text(json.dumps(raw), encoding="utf-8")
    first, second = raw["benefit_types"][0]["id"], raw["benefit_types"][1]["id"]
    label = " ".join(raw["benefit_types"][0]["label"].split()).casefold()
    assert problems(copy, set(named_companies())) == [f"taxonomy.json: {label!r} names both {first!r} and {second!r}"]


def test_a_file_the_dataset_does_not_hold_is_named(tmp_path):
    copy = tmp_path / "benefits"
    shutil.copytree(DATASET, copy)
    (copy / "cells.jsonl").write_text("", encoding="utf-8")
    (copy / "taxonomy.json").unlink()
    assert problems(copy, set(named_companies())) == [
        "cells.jsonl: not a benefits dataset file", "taxonomy.json: missing"]


def test_records_group_into_one_cell_per_benefit_in_file_order():
    """The reader groups a company's records by benefit type, keeping the file's
    order, and hands each observation over without the line's own keys."""
    records = [r for r in _records() if r["company"] == COMPANY]
    cells = builtin_cells(COMPANY)
    assert [c["benefit_type"] for c in cells] == list(dict.fromkeys(r["benefit_type"] for r in records))
    cell = next(c for c in cells if c["benefit_type"] == CELL)
    assert [o["observation_id"] for o in cell["observations"]] == [
        r["observation_id"] for r in records if r["benefit_type"] == CELL]
    assert len(cell["observations"]) == 2
    assert all("company" not in o and "benefit_type" not in o for c in cells for o in c["observations"])


def test_the_dataset_alone_answers_every_listed_cell_once():
    """One row per benefit: Lyft's retirement cell holds two employer
    mentions, and both land on one row."""
    groups = dataset_benefits(COMPANY)
    listed = [c["benefit_type"] for c in builtin_cells(COMPANY)]
    assert sorted(i["benefit_type"] for i in _items(groups)) == sorted(listed)
    assert all(i["builtin"] and i["provider"] == "builtin" for i in _items(groups))
    [row] = _cell(groups, CELL)
    assert row["value_text"] == "401(k) plan with company match to help save for your future"  # the fuller wording leads
    assert [(w["text"], w["kind"]) for w in row["wordings"]] == [("401(k) plan to help save for your future", "employer")]
    assert row["mentions"] == 5  # both mentions' capture counts, 4 and 1


def test_a_record_is_reviewed_only_when_its_review_state_says_so():
    """The reviewed flag follows each record's review status, not a dataset-wide
    assumption. Reviewed and disputed records must produce different flags."""
    from tracker.profiles.benefits_builtin import _builtin_item

    obs = {"kind": "dataset", "terms": "16 weeks", "scope": {}, "estimated_annual_value_usd": None}
    assert _builtin_item(CELL, {**obs, "review_status": "reviewed"})["reviewed"] is True
    assert _builtin_item(CELL, {**obs, "review_status": "disputed"})["reviewed"] is False
    assert {i["reviewed"] for i in _items(dataset_benefits(COMPANY))} == {False}


def test_every_company_shows_each_benefit_once_and_each_wording_once():
    """A row per mention would list one benefit many times, and "* 401(k)" /
    "- 401(k)" / "4. 401(k) Plan" pass an exact-text check. Across the whole
    dataset: one row per benefit, no wording twice on a row,
    and no list marker left in front of one."""
    from tracker.profiles.benefits_builtin import _cells, _said

    for company in _cells():
        items = _items(dataset_benefits(company))
        kinds = [i["benefit_type"] for i in items]
        assert len(kinds) == len(set(kinds)), company
        for item in items:
            said = [_said(t) for t in [item["value_text"], *(w["text"] for w in item["wordings"])] if t]
            assert len(said) == len(set(said)), (company, item["benefit_type"])
            for text in filter(None, [item["value_text"], *(w["text"] for w in item["wordings"])]):
                assert text[:1] not in "*-•·", (company, text)
    amazon = _items(dataset_benefits("amazon"))
    assert len(amazon) == 13
    [plan] = [i for i in amazon if i["benefit_type"] == "retirement_plan"]
    assert _said(plan["value_text"]) == "401(k) plan"
    assert {_said(w["text"]) for w in plan["wordings"]} == {"401(k)"}


def test_a_sentence_several_benefits_share_is_said_once_as_a_note():
    """"Medical, Dental, and Vision Coverage" names three benefits and must not
    be shown under each. It is one note, counted once, and under none of them."""
    notes = dataset_benefit_notes("amazon")
    [note] = [n for n in notes if n["text"] == "Medical, Dental, and Vision Coverage"]
    assert note["benefit_types"] == ["dental_insurance", "medical_insurance", "vision_insurance"]
    items = {i["benefit_type"]: i for i in _items(dataset_benefits("amazon"))}
    for kind in note["benefit_types"]:
        shown = [items[kind]["value_text"], *(w["text"] for w in items[kind]["wordings"])]
        assert note["text"] not in shown
        assert items[kind]["mentions"] >= note["mentions"] > 0  # still counted toward the benefit
    assert len({n["text"] for n in notes}) == len(notes)


#: A heading an employer wrote above its benefits that names one country.
HEADING_COUNTRY = {
    "US": re.compile(r"\b(US|USA|U\.S\.|United States)\b"),
    "CA": re.compile(r"\bCanada\b"),
    "GB": re.compile(r"\b(UK|United Kingdom)\b"),
}


def test_a_benefit_under_a_country_heading_says_that_country():
    """A benefit the employer listed under "United States" or "What we offer you
    (Canada)" applies there, and the profile says so; left blank, it would read
    as unscoped."""
    for obs in _records():
        heading = obs["scope"].get("scope_title") or ""
        named = [code for code, pattern in HEADING_COUNTRY.items() if pattern.search(heading)]
        if len(named) == 1:
            assert obs["scope"]["country"] == named[0], (obs["company"], obs["benefit_type"], heading)
    amat = {i["benefit_type"]: i for i in _items(dataset_benefits("applied-materials"))}
    assert amat["relocation_support"]["country"] == "US"  # "Relocation assistance is given to all US interns"


def test_an_employer_mention_shows_the_sentence_that_names_the_benefit():
    """An employer mention's `terms` is the whole line it was found in (up to
    1,400 characters), which can open on pay. The record shows
    `display_excerpt`, the sentence around the match, and keeps the full
    statement as its description so the original wording stays reachable."""
    import re

    from tracker.profiles.benefits_builtin import _builtin_item

    line = ("The base salary range for this position is listed below. "
            "Starting Day 1 of employment, Acme offers EAP, Mental Health Support, 401(k) matching.")
    excerpt = "Starting Day 1 of employment, Acme offers EAP, Mental Health Support, 401(k) matching."
    item = _builtin_item("mental_health_support", {
        "kind": "employer", "terms": line, "display_excerpt": excerpt, "scope": {}, "review_status": "unreviewed",
    })
    assert (item["value_text"], item["description"]) == (excerpt, line)
    same = _builtin_item("vacation", {"kind": "employer", "terms": "Generous PTO", "display_excerpt": "Generous PTO",
                                      "scope": {}, "review_status": "unreviewed"})
    assert (same["value_text"], same["description"]) == ("Generous PTO", None)
    # A dataset record's terms are reference text (structured fields, the
    # estimate note): never its wording, never its description.
    record = _builtin_item("health_savings_account", {
        "kind": "dataset", "terms": '{"amountDollars":"500","frequency":"y"} | 500 USD/year imported estimate',
        "scope": {}, "review_status": "unreviewed", "estimated_annual_value_usd": 500})
    assert (record["value_text"], record["description"], record["value_usd"]) == (None, None, 500)

    texts = [t for i in _items(dataset_benefits("amazon"))
             for t in [i["value_text"], *(w["text"] for w in i["wordings"])] if t]
    assert not [t for t in texts if re.search(r"salary range|starting pay|USD/year imported|^\{", t, re.I)]


def _fake_cells(monkeypatch, cells):
    from tracker.profiles import benefits_builtin

    monkeypatch.setattr(benefits_builtin, "builtin_cells", lambda company: cells)


def _obs(kind, text, *, mentions=None, usd=None, reviewed=False, oid=None, country=None):
    obs = {"kind": kind, "assertion": "listed", "terms": text or "", "scope": {"country": country},
           "review_status": "reviewed" if reviewed else "unreviewed", "estimated_annual_value_usd": usd,
           "observation_id": oid or f"{kind}-{text}"}
    if text:
        obs["display_excerpt"] = text
    if kind == "employer":
        obs["supporting_capture_count"] = mentions or 1
    return obs


def test_the_row_leads_with_a_reviewed_wording_then_the_fullest(monkeypatch):
    _fake_cells(monkeypatch, [{"benefit_type": "vacation", "observations": [
        _obs("employer", "Unlimited PTO", mentions=3),
        _obs("dataset", "Twenty days a year plus the week between the holidays"),
        _obs("employer", "PTO", mentions=1, reviewed=True, oid="r"),
        _obs("dataset", None, usd=4000),
    ]}])
    [row] = _items(dataset_benefits("x"))
    assert (row["value_text"], row["reviewed"], row["kind"]) == ("PTO", True, "employer")
    assert [w["text"] for w in row["wordings"]] == [
        "Twenty days a year plus the week between the holidays", "Unlimited PTO"]
    assert (row["mentions"], row["value_usd"]) == (4, 4000)  # the estimate rides on the row it belongs to


def test_a_wording_that_only_restates_the_name_counts_but_is_not_words(monkeypatch):
    _fake_cells(monkeypatch, [{"benefit_type": "dental_insurance", "observations": [
        _obs("employer", "Dental Insurance", mentions=5), _obs("dataset", None)]}])
    [row] = _items(dataset_benefits("x"))
    assert (row["value_text"], row["wordings"], row["mentions"], row["kind"]) == (None, [], 5, "employer")


def test_a_shared_sentence_counts_its_captures_once_not_per_benefit(monkeypatch):
    said = "Medical, dental and vision"
    pair = "1x salary up to $200,000 in Life and Accidental Death insurance"
    _fake_cells(monkeypatch, [
        {"benefit_type": "medical_insurance", "observations": [_obs("employer", said, mentions=7, oid="a")]},
        {"benefit_type": "dental_insurance", "observations": [_obs("employer", said + ".", mentions=7, oid="b")]},
        {"benefit_type": "vision_insurance", "observations": [_obs("employer", said, mentions=6, oid="c")]},
        {"benefit_type": "life_insurance", "observations": [_obs("employer", pair, mentions=2, oid="d")]},
        {"benefit_type": "accident_insurance", "observations": [_obs("employer", pair, mentions=2, oid="e")]},
    ])
    assert [(n["mentions"], n["benefit_types"]) for n in dataset_benefit_notes("x")] == [
        (7, ["dental_insurance", "medical_insurance", "vision_insurance"])]
    rows = {i["benefit_type"]: i for i in _items(dataset_benefits("x"))}
    assert rows["medical_insurance"]["value_text"] is None and rows["medical_insurance"]["mentions"] == 7
    # Two benefits named together are still each one's terms: the sentence stays under both.
    assert rows["life_insurance"]["value_text"] == rows["accident_insurance"]["value_text"] == pair


def test_two_plugin_labels_for_one_benefit_are_one_row():
    groups = plugin_benefits([_row("Dental Insurance", value_text="100% covered"),
                              _row("dental  insurance", value_text="Orthodontics included up to $2,000")])
    [row] = _items(groups)
    assert row["value_text"] == "Orthodontics included up to $2,000"
    assert [w["text"] for w in row["wordings"]] == ["100% covered"]
    assert dataset_benefit_notes("a-company-the-catalog-does-not-name") == []


def test_the_plugin_reader_answers_from_the_plugin_s_rows_alone():
    """No dataset record appears beside a plugin's, not even in
    the cells the plugin does not answer."""
    label = next(name for name, kind in taxonomy().alias.items() if kind == CELL)  # an explicit alias
    groups = plugin_benefits([_row(label, value_text="25 days")])
    assert [(i["benefit_type"], i["kind"], i["provider"], i["builtin"]) for i in _items(groups)] == [
        (CELL, "provider", "tpl", False)]


def test_reading_a_plugin_never_changes_what_the_dataset_answers():
    alone = dataset_benefits(COMPANY)
    plugin_benefits([_row("Health Insurance"), _row("Free yacht")])  # on
    assert dataset_benefits(COMPANY) == alone  # off: nothing was consumed or rewritten
    assert all(i["builtin"] and i["provider"] == "builtin" for i in _items(alone))


def test_a_label_no_alias_maps_is_kept_under_its_own_name():
    groups = plugin_benefits([_row("Free yacht", value_usd=999_000), _row("Health Insurance")])
    other = next(g for g in groups if g["category"] == OTHER)
    assert [(i["name"], i["benefit_type"], i["value_usd"]) for i in other["items"]] == [("Free yacht", None, 999_000)]
    assert groups[-1]["category"] == OTHER


def test_an_unknown_cell_is_never_shown():
    listed = {c["benefit_type"] for c in builtin_cells(COMPANY)}
    shown = {i["benefit_type"] for i in _items(dataset_benefits(COMPANY))}
    assert shown == listed


def test_a_company_with_no_listed_cell_shows_nothing_from_the_dataset():
    assert dataset_benefits("a-company-the-catalog-does-not-name") == []
    assert plugin_benefits([]) == []


# --------------------------------------------------------------------------- #
# The dataset is the runtime's to read, never to write
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_the_runtime_never_writes_the_dataset(api_client, db_session, monkeypatch):
    before = _hashes()
    db_session.add(CompanyProfile(slug=COMPANY, display_name="Lyft"))
    db_session.add(PluginInstall(plugin_id="tpl", name="T", version="1", source_dir="/x", manifest_sha="m",
                                 code_sha="c", manifest={"provides": [{"slot": COMPANY_BENEFITS}]}, fingerprint="f",
                                 approved_fingerprint="f", enabled=True))
    await db_session.flush()
    cover(db_session, "tpl", (COMPANY_BENEFITS,), (COMPANY,))
    db_session.add(
        CompanyBenefit(company_slug=COMPANY, name="Health Insurance", category="Health", provider="tpl"))
    await db_session.commit()
    for _ in range(2):
        assert (await api_client.get(f"/api/company-profiles/{COMPANY}")).status_code == 200
    await api_client.post("/api/plugins/tpl/disable")
    assert (await api_client.get(f"/api/company-profiles/{COMPANY}")).status_code == 200
    assert _hashes() == before
