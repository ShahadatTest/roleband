"""Family ladders and pay grades.

A company's title words mean different rungs in different families: Google's
"II" is L3 for an engineer, L4 for a program manager and L5 for a product
manager, and its "Senior" is L5 for an engineer and L6 for a product manager.
Rules are keyed by (company, family), the family is classified first, and the
company row is the fallback. Where a title names no rung, Google's posted
base range does: its ranges are per grade (`levels.pay_grades`).
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

import pytest

from tests.factories import SENIOR_PM_SCOPE, Allowed, NoComp, PayingSource
from tracker.enrich import level_mapper
from tracker.enrich.classify import classify_family
from tracker.enrich.enricher import annotate, reread_level
from tracker.enrich.level_mapper import _level_text, read_level
from tracker.levels.ladder import band_for, reading_ladder
from tracker.levels.pay import bonus_ratio_for, level_label, pay_label, seed_range
from tracker.levels.pay_grades import PAY_GRADES, PayGrade, grade_for_pay
from tracker.levels.titles import match_title
from tracker.platform.ratelimit import RateLimiterPool
from tracker.schema import LevelBand, LevelBasis, RawJob, SourceDisclosedComp
from tracker.taxonomy.title_parse import head_with_seniority
from tracker.workflows import collection as collection_module
from tracker.workflows.collection import collect_source

E, M, S = LevelBand.ENTRY, LevelBand.MID, LevelBand.SENIOR
ST, P, D = LevelBand.STAFF, LevelBand.PRINCIPAL, LevelBand.DIRECTOR_PLUS
_POSTED = datetime(2026, 6, 1, tzinfo=UTC)


def _job(title: str, company: str = "google", *, pay: tuple[int, int] | None = None,
         currency: str = "USD", posted: datetime = _POSTED) -> RawJob:
    stated = None
    if pay is not None:
        stated = SourceDisclosedComp(
            base_min=pay[0], base_max=pay[1], currency=currency, pay_basis="base", pay_period="year",
        )
    return RawJob(company=company, req_id=title, title=title, url="", source_disclosed_comp=stated,
                  posted_at=posted)


def _read(title: str, company: str = "google", **kwargs):
    job = _job(title, company, **kwargs)
    return read_level(job, classify_family(job))


# --- rules keyed by (company, family) -------------------------------------- #


@pytest.mark.parametrize(("title", "band"), [
    # The same numeral, three rungs: the family picks the ladder.
    ("Software Engineer III, Infrastructure", M),  # L4
    ("Program Manager II, Supply Chain", M),  # L4
    ("Product Manager II, Maps", S),  # L5
    ("Program Manager I, Big Data", E),  # L3
    ("Technical Program Manager I, Fiber", E),  # L3
    ("Technical Program Manager II, Cloud", M),  # L4
    ("Technical Program Manager III, Ads", S),  # L5
    ("Product Manager I, Search", M),  # L4
    # Senior Software Engineering Manager posts Senior Staff's range: L7.
    ("Senior Software Engineering Manager, Search", P),
    ("Software Engineering Manager II, Pixel", ST),  # L6
    # L8 is titled Principal Engineer: principal, not the row's director+.
    ("Principal Engineer, Cloud", P),
    ("Group Outbound Product Manager, Launch", P),  # L7
])
def test_a_family_reads_its_own_words(title, band):
    reading = _read(title)
    assert (reading.band, reading.basis) == (band, LevelBasis.COMPANY), title


@pytest.mark.parametrize("title", [
    "Software Engineer Manager II, Full Stack",
    "Software Engineer Manager II, Embedded Systems/Firmware",
])
def test_googles_engineer_manager_reads_the_manager_ladder(title):
    """Filed as an engineer, "Software Engineer Manager II" would read no
    rung (the engineer ladder has no manager II) and stay "level not
    stated"; it is the manager ladder's II, as "Software Engineering Manager
    II" is."""
    reading = _read(title)
    assert (reading.band, reading.basis) == (ST, LevelBasis.COMPANY), title
    assert reading == _read(title.replace("Engineer Manager", "Engineering Manager"))


def test_a_team_named_communications_leaves_an_engineer_on_the_engineer_ladder():
    """Filed as marketing, "Software Engineer III" would read no rung."""
    reading = _read("Software Engineer III, Infra, Core Communications")
    assert (reading.band, reading.basis) == (M, LevelBasis.COMPANY)


def test_the_family_decides_and_the_company_row_is_the_fallback():
    # Without a family the row's words read the title: "II" names nothing
    # there, and Senior Software Engineering Manager is the generic staff.
    assert read_level(_job("Program Manager II, Supply Chain"), None).basis is not LevelBasis.COMPANY
    assert read_level(_job("Senior Software Engineering Manager, Search"), None).band is ST
    # A family with no ladder of its own reads the row: "Staff" is L6 anywhere.
    reading = read_level(_job("Staff UX Designer"), "design_ux")
    assert (reading.band, reading.basis) == (ST, LevelBasis.COMPANY)


@pytest.mark.parametrize(("title", "family", "band"), [
    # A numeral after another word is not the family's rung: "Leadership TPM
    # II" posts Senior's range, and a Software Engineer Manager is no L3.
    ("Leadership Technical Program Manager II, Cloud", "technical_program_management", S),
    ("Software Engineer Manager II, Pixel", "software_engineering", M),
    # Senior anywhere in a product/program head is Senior, not the numeral.
    ("Cloud AI Senior Technical Program Manager I", "technical_program_management", S),
    # Senior Staff is the row's L7, not the product ladder's Senior.
    ("Senior Staff Technical Program Manager", "technical_program_management", P),
    # A director stays a director whatever the family's Senior means.
    ("Senior Director, Product Management", "product_management", D),
])
def test_family_rules_do_not_overreach(title, family, band):
    assert read_level(_job(title), family).band is band, title


def test_senior_staff_is_read_as_the_rows_l7_not_the_familys_senior():
    # The generic word lands it principal either way; the company's own L7 must
    # be what decided it, or a pay-grade anchor would read it as L6.
    reading = read_level(_job("Senior Staff Technical Program Manager"), "technical_program_management")
    assert (reading.band, reading.basis) == (P, LevelBasis.COMPANY)
    match = match_title("google", "senior staff technical program manager", "technical_program_management")
    assert match is not None and match.rule.rung == "L7"


def test_a_numeral_after_another_word_is_never_the_entry_rung():
    # Read on the engineer ladder, an unanchored numeral rule would take
    # "Software Engineer Manager II" as Software Engineer II (L3). The family is
    # passed, not classified: the title is filed as a manager,
    # and the guard on the engineer ladder's anchoring must not depend on that.
    reading = read_level(_job("Software Engineer Manager II, Pixel"), "software_engineering")
    assert reading.band is not E
    assert reading.basis is not LevelBasis.COMPANY


def test_other_companies_keep_their_rules():
    # Amazon's numerals are company-wide (L4/L5/L6) and family-blind.
    assert _read("Program Manager II", "amazon").band is M
    assert _read("Solutions Architect III", "amazon").band is S
    assert _read("Software Engineer III, Infrastructure", "acme").basis is not LevelBasis.COMPANY


def test_pay_still_reads_the_company_row():
    # Family ladders change how a title is read, never what a band pays: a
    # Google director+ posting is most often a Director (L8 on the row), not the
    # IC ladder's Distinguished Engineer (L9), which has no seed.
    assert level_label("google", D) == pay_label("google", D) == "L8"
    assert seed_range("google", D) == (960_000, 1_200_000, 1_440_000)
    assert level_label("google", P) == "L7"
    assert bonus_ratio_for("google", ST) == pytest.approx(0.225)


def test_deepmind_reads_googles_family_ladders():
    reading = _read("Senior Software Engineering Manager, Gemini", "google-deepmind")
    assert (reading.band, reading.basis) == (P, LevelBasis.COMPANY)


# --- the posted range, only where the title names no rung ------------------ #


@pytest.mark.parametrize(("title", "pay", "band"), [
    ("Product Manager, Google Analytics", (138_000, 197_000), M),  # L4
    ("Product Manager, Google Analytics", (163_000, 236_000), S),  # L5
    ("Product Manager, Google Chat", (240_000, 333_000), P),  # L7
    ("Engineering Manager, NIC Pipeline", (262_000, 365_000), P),  # L7
    ("Engineering Manager, NIC Pipeline", (207_000, 301_000), ST),  # L6
    ("Program Manager, Maintenance Planning", (108_000, 153_000), E),  # L3
])
def test_a_bare_title_reads_its_posted_range(title, pay, band):
    reading = _read(title, pay=pay)
    assert (reading.band, reading.basis) == (band, LevelBasis.PAY_GRADE), title


def test_a_rung_word_outranks_the_range():
    # A rung titled Senior is senior whatever it pays. Senior Product
    # Manager at Product Manager I's range is still Senior.
    reading = _read("Senior Product Manager, Ads", pay=(138_000, 197_000))
    assert (reading.band, reading.basis) == (S, LevelBasis.COMPANY)
    # A director word too.
    assert _read("Director, Product Management", pay=(240_000, 333_000)).band is D


@pytest.mark.parametrize(("change", "why"), [
    ({"posted": datetime(2027, 3, 1, tzinfo=UTC)}, "a later year's range is unmeasured"),
    ({"currency": "EUR"}, "the measured ranges are US base"),
    ({"pay": (139_000, 197_000)}, "only the exact range is a grade"),
    ({"company": "amazon"}, "another company's range is not Google's grade"),
])
def test_the_range_reads_only_where_it_was_measured(change, why, monkeypatch):
    if "posted" in change:
        # A later year's posting is read in that year: a date ahead of the
        # clock is not a posting date at all (`plausible_posted`).
        monkeypatch.setattr(level_mapper, "_now", lambda: change["posted"])
    args = {"pay": (138_000, 197_000), "company": "google", **change}
    company = args.pop("company")
    reading = _read("Product Manager, Google Analytics", company, **args)
    assert reading.basis is not LevelBasis.PAY_GRADE, why
    assert reading.band is S  # the generic, unconfirmed Product Manager


def test_reread_moves_only_when_the_range_names_a_rung():
    job = _job("Product Manager, Google Analytics")
    listed = annotate(job)
    assert reread_level(job, listed) is listed  # nothing new to read
    job.source_disclosed_comp = SourceDisclosedComp(
        base_min=138_000, base_max=197_000, currency="USD", pay_basis="base", pay_period="year",
    )
    detailed = reread_level(job, listed)
    assert (detailed.band, detailed.basis) == (M, LevelBasis.PAY_GRADE)
    assert detailed.family == listed.family and detailed.track == listed.track


# --- the table: every range anchored by a title that states its rung ------- #


def _anchor_problems(grades: tuple[PayGrade, ...]) -> list[str]:
    """A row whose anchor title, read by its family's own rules, does not
    state the row's rung."""
    problems = []
    for grade in grades:
        head = _level_text(head_with_seniority(grade.anchor))
        match = match_title(grade.company, head, grade.family)
        if match is None or match.ladder is None or match.rule.rung != grade.rung:
            problems.append(f"{grade.family} {grade.base_min}-{grade.base_max}: {grade.anchor!r}")
    return problems


def test_every_range_is_anchored_by_a_title_that_states_its_rung():
    assert PAY_GRADES
    assert _anchor_problems(PAY_GRADES) == []


def test_an_unanchored_range_is_refused():
    # Planted control: Product Manager I's range claimed for L5.
    planted = replace(PAY_GRADES[0], rung="L9")
    assert _anchor_problems((planted,)) != []
    pm = next(g for g in PAY_GRADES if g.anchor == "product manager i")
    assert _anchor_problems((replace(pm, rung="L5"),)) != []


def test_every_range_names_a_rung_its_family_reads_and_has_two_anchors():
    for grade in PAY_GRADES:
        assert grade.anchors >= 2, grade
        assert band_for(grade.company, grade.rung, reading_ladder(grade.company, grade.family)) is not None
    keys = [(g.company, g.family, g.base_min, g.base_max, g.year) for g in PAY_GRADES]
    assert len(keys) == len(set(keys))


def test_a_child_company_reads_its_parents_ranges():
    assert grade_for_pay("google-deepmind", "product_management", 138_000, 197_000, 2026) is not None
    assert grade_for_pay("acme", "product_management", 138_000, 197_000, 2026) is None
    assert grade_for_pay("google", None, 138_000, 197_000, 2026) is None


# --- the pipeline: the detail read can move a level out of scope ----------- #


@pytest.mark.asyncio
async def test_a_range_that_names_a_lower_rung_takes_the_posting_out_of_scope(monkeypatch):
    # Google is walled until the user consents; the gate is not under test.
    monkeypatch.setattr(collection_module, "collection_access", lambda *a, **kw: Allowed())
    # Both pass on the title (generic senior); after the detail read one posts
    # Product Manager I's range (L4, mid) and one Product Manager II's (L5).
    source = PayingSource({"pm-1": (138_000, 197_000), "pm-2": (163_000, 236_000)})
    collection = await collect_source(
        "google", {"adapter": "google"}, SENIOR_PM_SCOPE, NoComp(),
        max_list=None, hydrate=True, limiter_pool=RateLimiterPool(),
        adapter_factory=lambda *a, **kw: source,
    )
    kept = {job.raw.req_id: job for job in collection.enriched}
    assert set(kept) == {"pm-2"}
    assert kept["pm-2"].level_basis is LevelBasis.PAY_GRADE
    assert collection.scope_by_key[RawJob("google", "pm-1", "", "").dedupe_key()] is False
    assert collection.stats["kept"] == 1


@pytest.mark.asyncio
async def test_the_inventory_records_the_level_the_page_decided_not_the_title_s_guess(monkeypatch):
    """Promotion admits from the inventory on its stored level. Written before
    the detail read, a posting the page put out of scope kept the title's
    in-scope guess there, and the next promotion could admit what the scan
    rejected. Fail-first: pm-1's row held the title's senior band."""
    from tracker.config import get_settings

    monkeypatch.setattr(collection_module, "collection_access", lambda *a, **kw: Allowed())
    monkeypatch.setattr(get_settings(), "inventory_enabled", True)
    source = PayingSource({"pm-1": (138_000, 197_000), "pm-2": (163_000, 236_000)})
    collection = await collect_source(
        "google", {"adapter": "google"}, SENIOR_PM_SCOPE, NoComp(),
        max_list=None, hydrate=True, limiter_pool=RateLimiterPool(),
        adapter_factory=lambda *a, **kw: source,
    )
    title_guess = annotate(RawJob("google", "pm-1", "Product Manager, Google Analytics", ""))
    rows = {row.req_id: row for row in collection.inventory.values()}
    assert collection.scope_by_key[RawJob("google", "pm-1", "", "").dedupe_key()] is False
    assert (rows["pm-1"].level_band, rows["pm-1"].level_basis) == (M.value, LevelBasis.PAY_GRADE.value)
    assert rows["pm-1"].level_band != title_guess.band.value, "the control: the page moved it"
    kept = next(job for job in collection.enriched if job.raw.req_id == "pm-2")
    assert (rows["pm-2"].level_band, rows["pm-2"].level_basis) == (kept.level_band.value, kept.level_basis.value)
