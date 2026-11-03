"""The leveling model: one rung, stated once.

A rung's facts (rung -> band, printed code -> band, band -> pay label, band ->
seed pay, band -> bonus target, the Walk guide's cells, display aliases) kept in
separate tables drift apart: a band's pay read at a rung its own ladder bands
differently. These tests hold the model's invariants, so the drift has nowhere
to come back from.
"""

from __future__ import annotations

import json
import re
from dataclasses import replace
from pathlib import Path

import pytest

from tracker.enrich.estimated_pay import estimated_band
from tracker.enrich.inventory import CLASSIFIER_SOURCES
from tracker.enrich.level_mapper import map_level
from tracker.levels.companies import COMPANIES
from tracker.levels.ladder import (
    band_for,
    band_for_stated_rung,
    duplicate_spellings,
    ladder_for,
    rung_for_band,
    stage_decoder,
    walk_guide,
)
from tracker.levels.model import Ladder, Rung
from tracker.levels.pay import bonus_ratio_for, level_label, seed_range
from tracker.levels.words import resolve_band
from tracker.schema import LevelBand, RawJob
from tracker.taxonomy.tracks import allowed_bands_for

TRACKER = Path(__file__).resolve().parents[1] / "tracker"


# --- a rung is stated once ------------------------------------------------- #


def test_no_spelling_names_two_rungs_of_one_company():
    assert [problem for record in COMPANIES.values() for problem in duplicate_spellings(record)] == []


def test_a_spelling_shared_by_two_rungs_is_refused():
    # Planted control: Amazon's "SDE III" also spelled on its L7 rung.
    amazon = COMPANIES["amazon"]
    ladder = amazon.ladders[0]
    rungs = tuple(
        replace(rung, aliases=(*rung.aliases, "SDE III")) if rung.code == "L7" else rung
        for rung in ladder.rungs
    )
    planted = replace(amazon, ladders=(replace(ladder, rungs=rungs),))
    assert duplicate_spellings(planted) == ["amazon: 'SDE III' names software_engineering/L6 and software_engineering/L7"]


def test_every_spelling_of_a_rung_answers_the_same_band():
    # One rung, three names: the page title, the L-number
    # and the guide code all reach Amazon's L6.
    assert band_for("amazon", "SDE III") is band_for("amazon", "L6") is LevelBand.SENIOR
    assert band_for("microsoft", "64") is LevelBand.SENIOR
    assert band_for_stated_rung("microsoft", "IC4") is LevelBand.SENIOR


def test_a_printed_code_is_read_whatever_its_case_or_spacing():
    # A board's field styles its value: "senior manager", "SENIOR MANAGER" and
    # "Senior  Manager" name Accenture's one rung.
    expected = band_for_stated_rung("accenture", "Senior Manager")
    assert expected is LevelBand.STAFF
    for spelling in ("senior manager", "SENIOR MANAGER", "Senior  Manager", " Senior Manager "):
        assert band_for_stated_rung("accenture", spelling) is expected, spelling
    assert band_for_stated_rung("microsoft", "ic4") is LevelBand.SENIOR
    # Control: a different code is still a different code.
    assert band_for_stated_rung("accenture", "Senior Managers") is None


def test_no_company_prints_two_codes_that_read_alike():
    """The lookup ignores case and spacing, so two printed codes of one company
    that differ only there would be one code with two bands."""
    from tracker.levels.atlas import PRINTED, read_rows
    from tracker.levels.ladder import printed_key

    seen: dict[tuple[str, str], str] = {}
    for row in read_rows(PRINTED):
        key = (row["company"], printed_key(row["code"]))
        assert key not in seen, f"{row['company']}: {row['code']!r} reads as {seen[key]!r}"
        seen[key] = row["code"]


def test_a_child_company_reads_its_parents_ladder():
    # google-deepmind shares Google's ladder, so its title rules band through
    # Google's rungs even though no band row names deepmind.
    assert band_for("google-deepmind", "L6") is LevelBand.STAFF
    assert resolve_band("google-deepmind", "L5") is LevelBand.SENIOR
    assert band_for("acme", "L6") is None


# --- the band a rung reads its pay from -------------------------------------- #


def test_a_band_without_a_rung_reads_the_nearest_rung_below():
    # Amazon and Microsoft have no Staff rung: staff reads the top senior rung,
    # derived, never pointed at by hand.
    assert rung_for_band("amazon", LevelBand.STAFF).code == "L6"
    assert level_label("amazon", LevelBand.STAFF) == "SDE III"
    assert rung_for_band("microsoft", LevelBand.STAFF).code == "64"
    assert seed_range("microsoft", LevelBand.STAFF) == (256_000, 320_000, 384_000)


def test_a_band_reads_a_rung_its_own_ladder_puts_in_that_band():
    # Negative control: Microsoft director_plus must not read at 67, which the
    # ladder bands principal.
    for slug in COMPANIES:
        for band in (LevelBand.SENIOR, LevelBand.PRINCIPAL, LevelBand.DIRECTOR_PLUS):
            rung = rung_for_band(slug, band)
            ladder = ladder_for(slug)
            if rung is None or ladder is None:
                continue
            if any(r.band is band for r in ladder.rungs):
                assert rung.band is band, f"{slug} {band.value} reads {rung.code} ({rung.band.value})"
    assert level_label("microsoft", LevelBand.DIRECTOR_PLUS) == "68"


def test_no_pay_rung_below_senior():
    # Pay reference starts at Senior (CompResolver asks for none below it), so
    # a per-band baseline below it stays the median row, not the lowest rung.
    assert level_label("microsoft", LevelBand.MID) == "mid"
    assert seed_range("google", LevelBand.MID) is None


def test_bonus_targets_live_on_rungs_and_read_through_the_band():
    assert bonus_ratio_for("google", LevelBand.STAFF) == pytest.approx(0.225)
    # Microsoft's target is one figure per level pair (63-64, 65-66); its maximum
    # is double that and is never the target. Staff reads 64.
    assert bonus_ratio_for("microsoft", LevelBand.SENIOR) == pytest.approx(0.15)
    assert bonus_ratio_for("microsoft", LevelBand.STAFF) == pytest.approx(0.15)
    assert bonus_ratio_for("microsoft", LevelBand.PRINCIPAL) == pytest.approx(0.20)
    assert bonus_ratio_for("microsoft", LevelBand.DIRECTOR_PLUS) is None
    assert bonus_ratio_for("amazon", LevelBand.SENIOR) == 0.0


# --- the Walk guide is derived, so it shows what the mapper bands ----------- #


def _assert_label_spans_band(slug: str, ladder: Ladder, band: str, label: str) -> None:
    codes = [rung.code for rung in ladder.rungs]
    first, _, last = label.partition("–")
    first = first.removesuffix("+")
    start = codes.index(first)
    end = codes.index(last) if last else (
        max(i for i, r in enumerate(ladder.rungs) if r.band.value == band)
        if label.endswith("+") else start
    )
    spanned = ladder.rungs[start:end + 1]
    assert {rung.band.value for rung in spanned} == {band}, f"{slug} {band}: {label}"
    assert sum(rung.band.value == band for rung in ladder.rungs) == len(spanned), f"{slug} {band}"


def _speaking_ladder(slug: str, track: str | None) -> Ladder:
    """The guide ladder a track's label comes from: the track's own, else the
    company-wide row."""
    guides = [ladder for ladder in COMPANIES[slug].ladders if ladder.guide]
    own = [ladder for ladder in guides if not ladder.company_wide and track in ladder.tracks]
    return own[0] if own else next(ladder for ladder in guides if ladder.company_wide)


def test_every_guide_cell_names_exactly_the_rungs_the_mapper_puts_in_its_band():
    """A person picks a band by the rung the guide shows ("senior = Amazon L6");
    the Board gates by the band the ladder gives that rung. The cell's span runs
    from its first to its last rung in ladder order, and every rung inside the
    span must carry the cell's band. A per-track label is checked against the
    ladder that speaks for that track."""
    for slug, bands in stage_decoder().items():
        for band, cell in bands.items():
            if "company_wide" in cell:
                _assert_label_spans_band(slug, _speaking_ladder(slug, None), band, cell["company_wide"])
            for track, label in cell.get("per_track", {}).items():
                _assert_label_spans_band(slug, _speaking_ladder(slug, track), band, label)


def test_googles_principal_engineer_is_principal_on_the_technical_track_only():
    # L8 is Principal Engineer on the technical track and Director on the
    # other tracks. The guide must show the same band the Board gates on.
    google = stage_decoder()["google"]
    assert google["principal"]["per_track"]["technical"] == "L7–L8"
    assert google["director_plus"]["per_track"]["technical"] == "L9–L10"
    for track in ("management", "product_program", "business_customer"):
        assert google["principal"]["per_track"][track] == "L7"
        assert google["director_plus"]["per_track"][track] == "L8–L10"
    # Where the IC ladder and the row agree, the cell stays company-wide.
    assert google["staff"] == {"company_wide": "L6"}


def test_company_wide_ladders_apply_to_every_function():
    decoder = stage_decoder()
    assert decoder["google"]["senior"] == {"company_wide": "L5"}
    assert decoder["amazon"]["mid"] == {"company_wide": "L5"}
    assert decoder["microsoft"]["principal"] == {"company_wide": "65–67"}


def test_technical_only_ladders_are_tagged_per_track():
    decoder = stage_decoder()
    assert decoder["apple"]["senior"] == {"per_track": {"technical": "ICT4"}}
    assert decoder["anthropic"]["senior"] == {"per_track": {"technical": "Senior Software Engineer"}}
    assert "company_wide" not in decoder["apple"]["senior"]


@pytest.mark.parametrize("title, band", [
    ("Staff Software Engineer, Claude Code", LevelBand.STAFF),
    ("Senior Staff Software Engineer, API", LevelBand.PRINCIPAL),
])
def test_anthropics_staff_is_staff_and_its_senior_staff_is_principal(title, band):
    code = title.split(",")[0]
    assert band_for("anthropic", code) is band
    assert walk_guide("anthropic")[band.value] == {"per_track": {"technical": code}}
    raw = RawJob(company="anthropic", req_id="", title=title, url="")
    assert map_level(raw, family="software_engineering")[0] is band


def test_anthropics_estimated_rungs_price_staff_and_principal():
    def band(rung: str) -> LevelBand | None:
        return estimated_band("anthropic", "software_engineering", rung)

    assert band("Staff Software Engineer") is LevelBand.STAFF
    assert band("Senior Staff Software Engineer") is LevelBand.PRINCIPAL
    assert "Lead Software Engineer" not in {rung.code for rung in ladder_for("anthropic").rungs}


def test_no_company_wide_cell_carries_an_engineering_only_label():
    for company, bands in stage_decoder().items():
        for band, cell in bands.items():
            wide = cell.get("company_wide")
            if wide is not None:
                for word in ("SDE", "ICT", "Engineer"):
                    assert word not in wide, f"{company}/{band} leaks an eng title: {wide}"


def test_a_company_with_no_staff_rung_has_no_staff_cell():
    assert "staff" not in walk_guide("amazon")
    assert "staff" not in walk_guide("microsoft")


def test_only_the_reviewed_companies_have_a_guide():
    # The reference companies plus the reviewed atlas ladders: a company joins
    # only by a reviewed ladder, each ordered from the employer's postings.
    assert set(stage_decoder()) == {
        "google", "apple", "amazon", "netflix", "openai", "anthropic", "nvidia", "spotify", "microsoft",
        "servicenow", "qualcomm", "zscaler", "micron", "okta", "affirm", "playstation", "cadence",
        "anduril", "fortinet", "snowflake", "arm", "tiktok", "shield-ai", "tsmc",
        "palo-alto-networks", "amd", "salesforce", "applied-materials", "intel",
        "waymo", "zoox", "zipline", "rocket-lab", "roblox", "palantir", "mongodb", "elastic",
        "asml", "synopsys", "electronic-arts", "wise",
        "jane-street", "susquehanna-international-group", "drw", "imc-trading", "optiver", "jump-trading",
        "hugging-face", "runway", "ami-labs", "lovable", "notion", "linear",
        "crowdstrike", "sentinelone", "1password", "vercel", "wiz",
        "xai", "mistral", "scaleai", "perplexity", "cohere",
        "datadog", "cloudflare", "gitlab", "grafana-labs", "doordash", "lyft", "pinterest", "snap", "instacart",
        "atlassian", "github", "docker", "hashicorp", "confluent", "twitch", "unity", "supercell", "discord",
        "valve", "riot-games", "epic-games", "take-two-interactive", "nintendo", "paypal", "block", "robinhood",
        "plaid", "brex", "ramp", "adyen", "klarna", "revolut", "tower-research-capital", "hudson-river-trading",
        "two-sigma", "xtx-markets", "citadel", "citadel-securities", "samsara", "skydio", "nuro", "aurora", "figure",
        "tesla", "boston-consulting-group", "bain-company", "roland-berger", "mckinsey-company", "oliver-wyman",
        "asana", "dropbox", "gusto", "meta", "flexport", "adobe", "shopify", "booking", "uber",
    }


def test_the_guide_is_json_serializable():
    json.dumps(stage_decoder())


def test_track_gates_match_market_reality():
    # Seven rungs: Intern below Entry / Junior; a manager is never an intern.
    ladder = ["intern", "entry", "mid", "senior", "staff", "principal", "director_plus"]
    assert allowed_bands_for("management") == ["senior", "staff", "principal", "director_plus"]
    assert allowed_bands_for("business_customer") == ladder[:-1]
    assert allowed_bands_for("technical") == ladder
    assert allowed_bands_for("product_program") == ladder
    assert allowed_bands_for("nonexistent") == ladder


# --- nothing outside tracker/levels states these facts again --------------- #

#: Retired table names. Shrink-only: a name here may never be defined again
#: anywhere under tracker/.
RETIRED_TABLES = (
    "LEVEL_BAND_SEED", "STATED_RUNG_BAND", "EQUITY_VEHICLE_SEED", "VESTING_SEED",
    "BAND_TO_LEVEL_LABEL", "SEED_MEDIAN_TC", "COMPANY_LADDERS", "_LEVEL_DISPLAY_ALIAS",
    "_SKILL_INDEX_SEED", "_BAND_ANCHORS", "OFFER_POLICIES",
)


@pytest.mark.parametrize("name", RETIRED_TABLES)
def test_a_retired_table_name_does_not_return(name):
    pattern = re.compile(rf"\b{re.escape(name)}\b")
    hits = [
        str(path.relative_to(TRACKER))
        for path in TRACKER.rglob("*.py")
        if pattern.search(path.read_text())
    ]
    assert hits == [], f"{name} reappeared in {hits}"


def test_the_retired_table_scan_can_fail(tmp_path):
    # Control: the scan finds a planted definition.
    planted = tmp_path / "planted.py"
    planted.write_text("SEED_MEDIAN_TC = {}\n")
    assert re.search(r"\bSEED_MEDIAN_TC\b", planted.read_text())


def test_every_classifier_source_exists():
    # A path that does not exist drops out of the fingerprint silently, and a
    # leveling edit then stops re-annotating stored postings.
    missing = [entry for entry in CLASSIFIER_SOURCES if not (TRACKER / entry).exists()]
    assert missing == []


def test_the_fingerprint_covers_the_ladders_and_titles_but_not_pay_policy():
    assert "levels/companies.py" in CLASSIFIER_SOURCES
    assert "levels/titles.py" in CLASSIFIER_SOURCES
    assert "levels/pay.py" not in CLASSIFIER_SOURCES
    # The inventory holds no pay, so a pay-grade row can never move a stored
    # inventory classification: re-annotating rows for one would be waste.
    assert "levels/pay_grades.py" not in CLASSIFIER_SOURCES


def test_a_ladder_rung_list_is_ordered_lowest_first():
    from tracker.schema import LEVEL_BAND_ORDER

    for slug, record in COMPANIES.items():
        for ladder in record.ladders:
            orders = [LEVEL_BAND_ORDER[rung.band.value] for rung in ladder.rungs]
            assert orders == sorted(orders), f"{slug} {ladder.family} is out of order"


def test_rung_and_ladder_records_are_frozen():
    with pytest.raises(AttributeError):
        Rung("L5", LevelBand.SENIOR).code = "L6"  # type: ignore[misc]
    with pytest.raises(AttributeError):
        Ladder("x", ()).guide = True  # type: ignore[misc]
