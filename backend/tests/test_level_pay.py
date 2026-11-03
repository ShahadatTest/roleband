"""Our per-level base pay, in shadow (`tracker.enrich.level_pay`).

Contracts:
- A filed title is read at use time by the posting reader: a title that states
  no level ("Software Engineer") or one we cannot place ("Engineering Manager")
  answers no band, with filed-only atlas-code/wage-I/flat-rung exceptions;
  a product title files under product management.
- A filed company and title are classified once, however many state and year
  cells carry them.
- The filed figure is the filings-weighted median of the latest year's cells;
  an older year never moves it.
- A posted figure takes the range most anchoring postings carry, and a rung
  code reads its band through the company's ladder.
- A company is answered only with a figure at two bands of one family.
- The bench compares the stored row the job page reads (its family and
  band), and names a ladder whose higher band pays less.
"""

from __future__ import annotations

import pytest

from scripts.bench_level_pay import agreements, coverage, inversions, job_baselines
from tracker.enrich import level_pay
from tracker.enrich.level_mapper import read_level
from tracker.enrich.level_pay import (
    FiledBase,
    LevelBase,
    PostedBase,
    filed_bases,
    posted_bases,
    weighted_median,
)
from tracker.levels.pay_grades import PayGrade
from tracker.schema import UNPLACED_BASES, LevelBand, RawJob

SWE, PM = "software_engineering", "product_management"


def _cell(title: str, year: int, n: int, p50: int, *, company: str = "google", state: str = "CA") -> dict[str, str]:
    return {"company": company, "title": title, "state": state, "year": str(year), "n": str(n), "base_p50": str(p50)}


def test_weighted_median_is_a_held_value_at_half_the_weight():
    assert weighted_median([(10, 200_000), (2, 300_000)]) == 200_000
    assert weighted_median([(1, 200_000), (9, 300_000)]) == 300_000
    # an exact tie takes the lower middle, a value some cell holds
    assert weighted_median([(1, 100), (1, 300)]) == 100
    with pytest.raises(ValueError):
        weighted_median([])


def test_a_filed_title_answers_only_where_the_reader_places_it():
    found = filed_bases([
        _cell("senior software engineer", 2026, 10, 230_000),
        _cell("staff software engineer", 2026, 4, 280_000),
        _cell("senior product manager", 2026, 3, 250_000),
        _cell("software engineer", 2026, 500, 150_000),  # states no level
        _cell("engineering manager", 2026, 50, 260_000),  # a role word we cannot place
    ])
    assert set(found) == {
        ("google", SWE, LevelBand.SENIOR), ("google", SWE, LevelBand.STAFF), ("google", PM, LevelBand.SENIOR),
    }
    assert found[("google", SWE, LevelBand.STAFF)] == FiledBase(year=2026, filings=4, titles=1, base=280_000)


def test_the_filed_figure_weights_filings_and_reads_only_the_latest_year():
    found = filed_bases([
        _cell("senior software engineer", 2026, 10, 230_000, state="CA"),
        _cell("senior software engineer", 2026, 2, 300_000, state="WA"),
        _cell("sr. software engineer", 2026, 1, 310_000, state="NY"),
        _cell("senior software engineer", 2025, 900, 100_000),  # history
    ])
    assert found[("google", SWE, LevelBand.SENIOR)] == FiledBase(year=2026, filings=13, titles=2, base=230_000)


def test_a_company_reads_its_own_vocabulary():
    found = filed_bases([_cell("software development engineer ii", 2026, 7, 175_000, company="amazon")])
    assert found == {("amazon", SWE, LevelBand.MID): FiledBase(2026, 7, 1, 175_000)}


def test_a_filed_title_can_name_an_existing_atlas_code_the_posting_reader_does_not():
    """Dropbox has no title profile: its postings read no code in a title, and
    a filed title that starts with one of its ladder codes is placed by that
    code, in the family whose ladder holds it, never for a dual title."""
    found = filed_bases([
        _cell("ic5 software engineer", 2026, 7, 250_000, company="dropbox"),
        _cell("ic5 software engineer", 2026, 3, 220_000, company="dropbox"),
        _cell("ic4 software engineer", 2026, 5, 180_000, company="dropbox"),
        _cell("ic5 and ic6 software engineer", 2026, 99, 999_000, company="dropbox"),
        _cell("ic5 product manager", 2026, 99, 999_000, company="dropbox"),
        _cell("ic5 software engineer", 2026, 99, 999_000, company="google"),
        _cell("manager software engineering", 2026, 99, 999_000, company="dropbox"),
    ])
    assert found == {
        ("dropbox", SWE, LevelBand.STAFF): FiledBase(2026, 10, 1, 250_000),
        ("dropbox", SWE, LevelBand.SENIOR): FiledBase(2026, 5, 1, 180_000),
    }
    raw = RawJob(company="dropbox", req_id="", title="ic5 software engineer", url="")
    assert read_level(raw, SWE).basis in UNPLACED_BASES


def test_a_filed_title_reads_a_printed_code_as_the_posting_does():
    """AMD prints its rung in titles, so a filing reads it through the same
    profile as a posting, a dual title at its lower rung."""
    found = filed_bases([
        _cell("pmts software development engineer", 2026, 7, 250_000, company="amd"),
        _cell("pmts and smts software development engineer", 2026, 3, 230_000, company="amd"),
        _cell("mts software development engineer", 2026, 5, 180_000, company="amd"),
    ])
    assert found == {
        ("amd", SWE, LevelBand.PRINCIPAL): FiledBase(2026, 10, 2, 250_000),
        ("amd", SWE, LevelBand.STAFF): FiledBase(2026, 5, 1, 180_000),
    }
    raw = RawJob(company="amd", req_id="", title="pmts software development engineer", url="")
    assert read_level(raw, SWE).band is LevelBand.PRINCIPAL


def _grade(lo: int, hi: int, anchors: int, *, year: int = 2026, rung: str | None = "L6",
           band: LevelBand | None = None) -> PayGrade:
    return PayGrade("google", SWE, lo, hi, year, rung, "staff software engineer", anchors, band)


def test_the_posted_figure_is_the_range_most_postings_carry():
    found = posted_bases([
        _grade(207_000, 301_000, 79),
        _grade(188_000, 274_000, 2),
        _grade(180_000, 270_000, 2),
        _grade(256_000, 279_000, 2),
        _grade(150_000, 200_000, 500, year=2025),  # history
    ])
    # unweighted, the three thin ranges would make it $188k-$274k
    assert found == {("google", SWE, LevelBand.STAFF): PostedBase(2026, 4, 207_000, 301_000, 85)}
    assert found[("google", SWE, LevelBand.STAFF)].mid == 254_000


def test_a_posted_band_row_needs_no_ladder():
    found = posted_bases([_grade(120_000, 160_000, 3, rung=None, band=LevelBand.MID)])
    assert set(found) == {("google", SWE, LevelBand.MID)}


def _base(company: str, family: str, band: LevelBand, pay: int | None, *, n: int = 3,
          posted: tuple[int, int] | None = None) -> tuple[tuple[str, str, LevelBand], LevelBase]:
    filed = FiledBase(2026, n, 1, pay) if pay is not None else None
    post = PostedBase(2026, 1, *posted) if posted else None
    return (company, family, band), LevelBase(company, family, band, filed, post)


def test_a_company_is_answered_by_two_bands_of_one_family(monkeypatch):
    shadow = dict([
        _base("ladder-co", SWE, LevelBand.SENIOR, 200_000),
        _base("ladder-co", SWE, LevelBand.STAFF, 250_000),
        _base("scattered-co", SWE, LevelBand.SENIOR, 200_000),
        _base("scattered-co", PM, LevelBand.STAFF, 250_000),
    ])
    monkeypatch.setattr(level_pay, "level_bases", lambda: shadow)
    assert level_pay.answers("ladder-co")
    assert not level_pay.answers("scattered-co")
    assert not level_pay.answers("absent-co")


def test_the_shipped_atlas_prices_google_engineering_in_band_order():
    shadow = level_pay.level_bases()
    pay = [shadow[("google", SWE, band)].filed for band in (LevelBand.SENIOR, LevelBand.STAFF, LevelBand.PRINCIPAL)]
    assert all(p is not None for p in pay)
    senior, staff, principal = (p.base for p in pay if p is not None)
    assert senior < staff < principal
    assert pay[0] is not None and pay[0].filings >= 100


def test_agreement_reads_the_stored_row_of_the_jobs_family_and_band():
    shadow = dict([
        _base("google", SWE, LevelBand.SENIOR, 230_000),
        _base("google", PM, LevelBand.SENIOR, 250_000),
        _base("google", "ml_ai_research", LevelBand.SENIOR, 240_000),  # no stored row for this family
        _base("google", SWE, LevelBand.STAFF, None, posted=(200_000, 300_000)),
        _base("unnamed-co", SWE, LevelBand.SENIOR, 100_000),
    ])
    # Keyed as readers key stored rows: by our taxonomy (`reference_pay.as_taxonomy`).
    baselines = {
        ("google", SWE, "senior"): {"base_amount": 200_000},
        ("google", PM, "senior"): {"base_amount": 250_000},
        ("google", SWE, "staff"): {"base_amount": 250_000},
        ("unnamed-co", SWE, "senior"): {"base_amount": 100_000},
    }
    found = {a.key: a for a in agreements(shadow, baselines, {"google"})}
    assert set(found) == {("google", SWE, LevelBand.SENIOR), ("google", PM, LevelBand.SENIOR),
                          ("google", SWE, LevelBand.STAFF)}
    assert found[("google", SWE, LevelBand.SENIOR)].ratio == pytest.approx(1.15)
    assert found[("google", SWE, LevelBand.STAFF)].ours == 250_000  # the posted middle, no filing


def test_inversions_name_a_higher_band_that_pays_less():
    shadow = dict([
        _base("co", SWE, LevelBand.MID, 150_000),
        _base("co", SWE, LevelBand.SENIOR, 200_000),
        _base("co", SWE, LevelBand.STAFF, 180_000),
        _base("co", PM, LevelBand.SENIOR, 300_000),  # another family is not compared
    ])
    assert inversions(shadow) == [(("co", SWE, LevelBand.SENIOR), ("co", SWE, LevelBand.STAFF))]


def test_coverage_counts_the_levels_a_company_posts_at():
    shadow = dict([_base("co", SWE, LevelBand.SENIOR, 200_000)])
    live = [("co", SWE, "senior", 40), ("co", SWE, "staff", 10), ("other", SWE, "senior", 99)]
    table = coverage(shadow, live, {"co"})
    keys, answered, postings, priced, missing = table["co"]
    assert (keys, answered, postings, priced) == (2, 1, 50, 40)
    assert dict(missing) == {"software_engineering/staff": 10}
    assert "other" not in table


def test_the_bench_uses_the_jobs_us_pay_screen_before_selecting_rungs():
    from types import SimpleNamespace

    def row(company, band, base):
        return SimpleNamespace(company_slug=company, family="software-engineer", band=band,
                               level_label=band, base_amount=base, bonus_amount=0, stock_amount=0)

    selected = job_baselines([
        row("accenture", "mid", 30_000), row("accenture", "senior", 80_000),
        row("google", "senior", 200_000),
    ])
    # Half a family's rows below the floor removes its higher rungs too.
    assert set(selected) == {("google", "software-engineer", "senior")}


# --- plain filed titles ------------------------------------------- #

def _filed(company, title, i=0, ii=0, iii=0, iv=0):
    return {"company": company, "title": title, "level_i": str(i), "level_ii": str(ii),
            "level_iii": str(iii), "level_iv": str(iv)}


def test_a_plain_title_at_a_flat_firm_reads_its_one_rung():
    # Jane Street's ladder is an entry hire plus one plain rung: "Software Engineer" is that rung.
    assert level_pay._place_filing(_filed("jane-street", "Software Engineer", ii=20, iii=6)) == (
        "software_engineering", LevelBand.MID)


def test_a_plain_title_filed_at_wage_level_i_reads_entry_anywhere():
    # A sufficiently dominant wage-level-I cell places a plain filed title at Entry.
    assert level_pay._place_filing(_filed("palantir", "Software Engineer", i=50, ii=3)) == (
        "software_engineering", LevelBand.ENTRY)


def test_wage_levels_ii_to_iv_place_nothing_outside_a_flat_firm():
    # A plain title at a firm with multiple non-entry rungs remains unplaced.
    assert level_pay._place_filing(_filed("anthropic", "Software Engineer", ii=65, iii=47, iv=78)) is None
    # Below the level I share, a mostly-entry cell does not read entry either.
    assert level_pay._place_filing(_filed("palantir", "Software Engineer", i=8, ii=2)) is None


def test_a_title_the_reader_places_keeps_its_band_whatever_the_wage_level():
    assert level_pay._place_filing(_filed("google", "Senior Software Engineer", i=10)) == (
        "software_engineering", LevelBand.SENIOR)


def test_a_filed_title_is_classified_once_however_many_cells_carry_it(monkeypatch):
    # One cell per company x title x state x year: a pair recurs, and the reader and
    # the filing-only rules both need its family.
    real = level_pay.classify_family
    calls = []
    monkeypatch.setattr(level_pay, "classify_family", lambda job: calls.append((job.company, job.title)) or real(job))
    level_pay._filed_family.cache_clear()
    level_pay._read_title.cache_clear()
    pairs = {  # placed by the reader; wage level I; a flat firm's one rung; unplaced
        ("google", "Senior Software Engineer"): {"i": 10},
        ("palantir", "Software Engineer"): {"i": 50, "ii": 3},
        ("jane-street", "Software Engineer"): {"ii": 20, "iii": 6},
        ("anthropic", "Software Engineer"): {"ii": 65, "iii": 47, "iv": 78},
    }
    rows = [
        {**_cell(title, year, 4, 150_000, company=company, state=state), **_filed(company, title, **levels)}
        for (company, title), levels in pairs.items() for state in ("CA", "NY", "WA") for year in (2024, 2025)
    ]

    found = filed_bases(rows)

    assert sorted(calls) == sorted(pairs)
    assert set(found) == {
        ("google", SWE, LevelBand.SENIOR), ("palantir", SWE, LevelBand.ENTRY), ("jane-street", SWE, LevelBand.MID),
    }
    assert all(base.year == 2025 and base.filings == 12 for base in found.values())


def test_postings_never_read_the_filing_rules():
    # The same plain title as a posting stays unplaced at a flat firm: the rule is the filings'.
    job = RawJob(company="jane-street", req_id="1", title="Software Engineer", url="")
    assert read_level(job, "software_engineering").basis in UNPLACED_BASES
