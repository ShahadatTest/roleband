"""The level atlas files are the leveling model.

`tracker/levels/atlas/` holds every company's ladders, rungs, printed codes,
offer policy and measured pay ranges as CSV with a generated Frictionless
descriptor. Four contracts:

- **The files are the model, exactly.** Loaded and written back they are
  byte-identical, so nothing the app reads exists only in code or only in a
  file.
- **The descriptor is generated, never edited.** It equals what `TABLES`
  states, so the shape is declared once.
- **A file that breaks its shape is refused by name**, never half-loaded.
- **No vendor name or URL** in any file.
"""

from __future__ import annotations

import re
import shutil

import pytest

from tests import vendor_names
from tracker.enrich.inventory import CLASSIFIER_SOURCES
from tracker.levels import atlas
from tracker.levels.atlas import TABLES, AtlasError


@pytest.fixture(scope="module")
def current_texts():
    # Once per module: `title_pay` alone is tens of thousands of validated rows.
    return atlas.current_texts()


@pytest.mark.parametrize("table", TABLES, ids=lambda t: t.name)
def test_the_files_are_the_model_byte_for_byte(table, current_texts):
    assert current_texts[table.name] == table.path.read_text(encoding="utf-8")


def test_the_descriptor_is_generated_from_the_tables():
    assert atlas.DESCRIPTOR.read_text(encoding="utf-8") == atlas.descriptor_text()


def test_the_descriptor_states_the_licence_and_what_is_derived():
    import json

    package = json.loads(atlas.DESCRIPTOR.read_text(encoding="utf-8"))
    assert [entry["name"] for entry in package["licenses"]] == ["CC-BY-4.0"]
    resources = {r["name"]: r for r in package["resources"]}
    assert "Department of Labor" in resources["title_pay"]["sources"][0]["title"]
    # Only a derived file names a source; a curated one is ours.
    assert "sources" not in resources["companies"]
    names = [r["name"] for r in atlas.descriptor()["resources"]]
    assert names == [t.name for t in TABLES]
    assert sorted(p.stem for p in atlas.ATLAS_DIR.glob("*.csv")) == sorted(names)


# --- a broken file is refused, naming the file and row -------------------- #


@pytest.fixture
def scratch_atlas(tmp_path, monkeypatch):
    """A copy of the atlas the test may break; the module reads the copy."""
    copy = tmp_path / "atlas"
    shutil.copytree(atlas.ATLAS_DIR, copy)
    monkeypatch.setattr(atlas, "ATLAS_DIR", copy)
    return copy


def _edit(path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    assert old in text, old
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def test_the_scratch_copy_loads_as_the_real_one(scratch_atlas):
    """The control for the rejections below: an untouched copy loads to the
    model the app runs."""
    from tracker.levels.companies import COMPANIES
    from tracker.levels.pay import PAY_POLICIES

    assert atlas.load_companies() == COMPANIES
    assert atlas.load_pay_policies() == PAY_POLICIES


@pytest.mark.parametrize(("file", "old", "new", "says"), [
    ("rungs.csv", "google,company,L5,senior,", "google,company,L5,seniorish,", "rungs.csv:"),
    ("rungs.csv", "google,company,L5,senior,,,false,", "google,company,L5,senior,,,maybe,", "not true/false"),
    ("rungs.csv", "google,company,L3,entry,", "google,company,L4,entry,", "duplicate key"),
    ("ladders.csv", "figma,software_engineering", "figmo,software_engineering", "unknown company"),
    ("printed.csv", "accenture,Manager,senior", "accenture,Manager,", "required"),
    ("company_facts.csv", "google,vesting,", "google,vestng,", "not in"),
    ("company_facts.csv", "google,verified,", "google,sources,", "not in"),
    # Every row says when its evidence was read.
    ("rungs.csv", "google,company,L5,senior,,,false,408000,15,20,2026-10-02,",
     "google,company,L5,senior,,,false,408000,15,20,,", "rungs.csv:4 as_of: required"),
    ("ladders.csv", "okta,software_engineering,true,false,technical,,,2026-10-09,",
     "okta,software_engineering,true,false,technical,,,last week,", "is not a date"),
    ("ladders.csv", "meta,software_engineering,true,false,technical,,true,",
     "meta,software_engineering,true,false,technical,,flat,", "'flat' is not true/false"),
    ("companies.csv", "cadence,,,,2026-10-09,", "cadence,,,,,", "companies.csv:34 as_of: required"),
    ("company_facts.csv", "google,vesting,38/32/20/10,estimated,2026-10-09", "google,vesting,38/32/20/10,estimated,", "as_of: required"),
    # Every fact says who states it; the entry's own rows say nobody.
    ("company_facts.csv", "google,vesting,38/32/20/10,estimated,", "google,vesting,38/32/20/10,,", "company_facts.csv:4 stated_by: required"),
    ("company_facts.csv", "google,vesting,38/32/20/10,estimated,", "google,vesting,38/32/20/10,rumoured,", "not in"),
    ("company_facts.csv", "google,verified,2026-10-09,,", "google,verified,2026-10-09,employer,", "describes the entry"),
    # `unknown` is searched-and-not-found: nobody states it, and only a fact can be searched.
    ("company_facts.csv", "jane-street,vesting,unknown,,", "jane-street,vesting,unknown,estimated,", "nobody states an unknown fact"),
    ("company_facts.csv", "google,verified,2026-10-09,,", "google,verified,unknown,,", "verified cannot be unknown"),
    ("company_facts.csv", "coinbase,grant_term,one_year,", "coinbase,grant_term,two_year,", "grant_term 'two_year' not in"),
    ("company_facts.csv", "google,bonus_rule,pct_of_base,", "google,bonus_rule,percent_of_base,",
     "bonus_rule 'percent_of_base' not in"),
    ("company_facts.csv", "amazon,equity_rule,tc_target_minus_base,", "amazon,equity_rule,tc_target,",
     "equity_rule 'tc_target' not in"),
])
def test_a_broken_file_is_refused_by_name(scratch_atlas, file, old, new, says):
    _edit(scratch_atlas / file, old, new)
    with pytest.raises(AtlasError, match=re.escape(says)):
        atlas.load_companies()
        atlas.load_pay_policies()


def test_a_file_saved_by_a_spreadsheet_with_a_byte_order_mark_loads(scratch_atlas):
    """Excel's "CSV UTF-8" save starts the file with a BOM; read as plain
    utf-8 the first column would be named "\ufeffslug" and the API would fail to
    start."""
    from tracker.levels.companies import COMPANIES

    for path in scratch_atlas.glob("*.csv"):
        path.write_bytes(b"\xef\xbb\xbf" + path.read_bytes())
    assert atlas.load_companies() == COMPANIES


def test_a_short_row_is_refused_as_missing_cells(scratch_atlas):
    """A row missing its last cells read as `None not in [...]`, naming no
    cause."""
    rungs = scratch_atlas / "rungs.csv"
    lines = rungs.read_text(encoding="utf-8").splitlines(keepends=True)
    (at,) = [i for i, line in enumerate(lines) if line.startswith("google,company,L5,senior,")]
    lines[at] = "google,company,L5,senior\n"
    rungs.write_text("".join(lines), encoding="utf-8")
    with pytest.raises(AtlasError, match=r"rungs\.csv:\d+: \d+ cells, the header has \d+"):
        atlas.load_companies()


def test_a_rung_without_its_ladder_is_refused(scratch_atlas):
    _edit(scratch_atlas / "rungs.csv", "google,product_management,L4,", "google,sales,L4,")
    with pytest.raises(AtlasError, match="no ladder"):
        atlas.load_companies()


def test_a_reordered_column_is_refused(scratch_atlas):
    _edit(scratch_atlas / "printed.csv", "company,code,band", "code,company,band")
    with pytest.raises(AtlasError, match="columns"):
        atlas.load_companies()


# --- what the files may not say -------------------------------------------- #

#: Vendor names and URL shapes. Planted below, so a scanner that stopped
#: seeing would fail.
_VENDOR = re.compile(
    "|".join((vendor_names.CONTENT.pattern, vendor_names.IDENTIFIER.pattern, *vendor_names.OTHERS, r"https?://", r"www\.")),
    re.I,
)


def test_no_atlas_file_names_a_vendor_or_a_url():
    hits = [
        (path.name, m.group(0))
        for path in sorted(atlas.ATLAS_DIR.iterdir())
        for m in _VENDOR.finditer(path.read_text(encoding="utf-8"))
    ]
    assert hits == []


@pytest.mark.parametrize(
    "planted", [vendor_names.planted("content"), "see https://example.test", vendor_names.planted("identifier")]
)
def test_the_vendor_scan_sees_a_planted_name(planted):
    assert _VENDOR.search(planted)


# --- re-leveling ----------------------------------------------------------- #


def test_an_edit_to_a_ladder_file_re_levels_the_inventory():
    """The inventory re-annotates when `classifier_fingerprint` moves; the
    ladder files are part of it, the pay tables are not (no pay there)."""
    for name in ("companies", "ladders", "rungs", "printed", "rung_titles"):
        assert f"levels/atlas/{name}.csv" in CLASSIFIER_SOURCES
    for name in ("company_facts", "pay_grades", "pay_bands", "title_pay", "posted_pay", "estimated_pay"):
        assert f"levels/atlas/{name}.csv" not in CLASSIFIER_SOURCES


def test_a_hand_written_estimated_pay_row_is_read_and_priced(scratch_atlas):
    """The file is filled by hand in its current header: a row at a rung the
    atlas places prices that band, base and equity; a row at a rung it does not
    place is read and then dropped."""
    from scripts.build_level_base import row as level_base_row
    from tracker.enrich.estimated_pay import estimated_bases
    from tracker.enrich.level_pay import level_bases
    from tracker.schema import LevelBand

    atlas.ESTIMATED_PAY.path.write_text(
        "company,family,rung,base_usd,equity_usd,cash_bonus_usd\n"
        "anthropic,software_engineering,Staff Software Engineer,300000,200000,\n"
        "anthropic,software_engineering,Lead Software Engineer,250000,,\n",
        encoding="utf-8")
    rows = atlas.read_rows(atlas.ESTIMATED_PAY)
    assert [r["rung"] for r in rows] == ["Staff Software Engineer", "Lead Software Engineer"]
    key = ("anthropic", "software_engineering", LevelBand.STAFF)
    found = estimated_bases(rows)
    assert list(found) == [key]
    assert (found[key].base, found[key].equity, found[key].cash_bonus) == (300000, 200000, None)
    level_bases.cache_clear()
    try:
        priced = level_bases()[key]
        assert priced.estimated == found[key]
        assert level_base_row(priced)["stock_usd"] == 200000
    finally:
        level_bases.cache_clear()


def test_estimated_pay_has_one_canonical_dataset_name():
    names = {resource["name"] for resource in atlas.descriptor()["resources"]}
    assert "estimated_pay" in names
    assert atlas.ESTIMATED_PAY.path.name == "estimated_pay.csv"
    facts = atlas.read_rows(atlas.FACTS)
    assert {row["stated_by"] for row in facts} == {"employer", "estimated", ""}
    assert "verified" in {row["fact"] for row in facts}
    assert "sources" not in {row["fact"] for row in facts}
