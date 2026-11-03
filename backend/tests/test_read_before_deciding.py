"""Read before deciding, and pay at every company that posts it.

A posting whose title states no level is not decided on its title alone: its
full posting often names the level (a stated range), so a posting that
fails the scope only on level is read first, and every company whose ranges
repeat reads a bare title by its range (`levels/pay_grades.PAY_BANDS`).
"""

from __future__ import annotations

import re
from dataclasses import replace
from datetime import UTC, datetime

import pytest

from tests.factories import NoComp, scope_filter
from tracker.enrich.classify import classify_family
from tracker.enrich.enricher import ScopeFilter
from tracker.enrich.level_mapper import (
    LevelReading,
    full_read_can_state,
    is_level_guess,
    read_level,
)
from tracker.levels.ladder import lineage
from tracker.levels.pay_grades import PAY_BANDS, PAY_GRADES, PayGrade, grade_for_pay
from tracker.platform.ratelimit import RateLimiterPool
from tracker.schema import LevelBand, LevelBasis, LevelConfidence, RawJob, SourceDisclosedComp
from tracker.workflows import collection as collection_module
from tracker.workflows.collection import collect_source
from tracker.workflows.collection_types import SourceLookups

_POSTED = datetime(2026, 6, 1, tzinfo=UTC)


def _job(company: str, title: str, pay: tuple[int, int] | None = None, raw_level: str | None = None) -> RawJob:
    stated = None
    if pay is not None:
        stated = SourceDisclosedComp(base_min=pay[0], base_max=pay[1], currency="USD",
                                     pay_basis="base", pay_period="year")
    return RawJob(company=company, req_id=title, title=title, url="", raw_level=raw_level,
                  source_disclosed_comp=stated, posted_at=_POSTED)


# --- band rows: every company whose ranges repeat ------------------------- #


_PRINTED = re.compile(r"^(.*) \[([^\]]+)\]$")


def _anchor_problems(rows: tuple[PayGrade, ...]) -> list[str]:
    """A row whose anchor, read without its range, does not state the row's
    band (the printed rung in brackets is read as the posting printed it)."""
    problems = []
    for row in rows:
        printed = _PRINTED.match(row.anchor)
        title, raw_level = (printed.group(1), printed.group(2)) if printed else (row.anchor, None)
        reading = read_level(_job(row.company, title, raw_level=raw_level), row.family)
        if reading.band is not row.band or reading.basis is LevelBasis.NONE:
            problems.append(f"{row.company} {row.family} {row.base_min}-{row.base_max}: {row.anchor!r}"
                            f" reads {reading.band.value}, row {row.band}")
    return problems


def test_band_rows_exist_beyond_google():
    companies = {row.company for row in PAY_BANDS}
    assert {"amazon", "microsoft", "apple"} <= companies
    assert all(row.rung is None and row.band is not None for row in PAY_BANDS)


def test_every_band_row_is_anchored_by_a_title_that_states_its_band():
    assert _anchor_problems(PAY_BANDS) == []


def test_an_unanchored_band_row_is_refused():
    # Planted control: an Amazon row claimed for a band its anchor does not state.
    row = next(r for r in PAY_BANDS if r.company == "amazon" and r.band is LevelBand.SENIOR)
    assert _anchor_problems((replace(row, band=LevelBand.DIRECTOR_PLUS),)) != []


def test_band_rows_never_restate_a_rung_table():
    ruled = {g.company for g in PAY_GRADES}
    assert not [r for r in PAY_BANDS if ruled & set(lineage(r.company))]
    keys = [(r.company, r.family, r.base_min, r.base_max, r.year) for r in (*PAY_GRADES, *PAY_BANDS)]
    assert len(keys) == len(set(keys))
    assert all(row.anchors >= 2 for row in PAY_BANDS)


def test_a_bare_title_at_a_measured_range_reads_its_band():
    row = next(r for r in PAY_BANDS if r.company == "amazon" and r.family == "program_management")
    job = _job("amazon", "Program Manager, Trade Planning", pay=(row.base_min, row.base_max))
    assert classify_family(job) == "program_management"
    reading = read_level(job, "program_management")
    assert (reading.band, reading.basis) == (row.band, LevelBasis.PAY_GRADE)
    # Controls: the same title one dollar off the range, and at another company.
    assert read_level(_job("amazon", job.title, pay=(row.base_min + 1, row.base_max)),
                      "program_management").basis is not LevelBasis.PAY_GRADE
    assert grade_for_pay("acme", "program_management", row.base_min, row.base_max, 2026) is None


# --- read before deciding --------------------------------------------------- #


class _Allowed:
    def require(self) -> None:
        return None


class _Source:
    """Bare "Software Engineer" titles at Google (no level in the title);
    the detail page states a range."""

    def __init__(self, ranges: dict[str, tuple[int, int]], title: str = "Software Engineer, Google Cloud",
                 company: str = "google") -> None:
        from tracker.platform.drift import SchemaDriftDetector

        self.company = company
        self.drift = SchemaDriftDetector(company)
        self.truncated = False
        self.query_observations: list = []
        self.hydrated: list[str] = []
        self._ranges = ranges
        self._title = title

    def location_gaps(self) -> list[str]:
        return []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc) -> None:
        return None

    async def fetch(self):
        for req in self._ranges:
            yield RawJob(company=self.company, req_id=req, title=self._title,
                         url=f"https://example.test/{req}", locations=["Mountain View, CA, USA"],
                         description_complete=False, posted_at=_POSTED)

    async def hydrate(self, job: RawJob) -> None:
        self.hydrated.append(job.req_id)
        low, high = self._ranges[job.req_id]
        job.description_html = (
            "<h3>Minimum qualifications:</h3><ul><li>Bachelor's degree.</li></ul>"
            f"<p>The US base salary range for this full-time position is ${low:,}-${high:,} "
            "+ bonus + equity + benefits.</p>"
        )
        job.description_complete = True


def _scope(*, include_unstated: bool, roles=("software_engineering",), bands=("staff",),
           tracks=("technical",)) -> ScopeFilter:
    return scope_filter(
        bands=bands,
        roles=roles,
        tracks=tracks,
        locations={"united_states"},
        domains=(),
        include_unstated_level=include_unstated,
    )


#: Google's Staff (L6) and Senior Staff (L7) engineering ranges (`PAY_GRADES`).
_L6, _L7 = (207_000, 301_000), (262_000, 365_000)


async def _collect(source: _Source, scope: ScopeFilter, monkeypatch, **kwargs):
    # Google is walled until the user consents; the gate is not under test.
    monkeypatch.setattr(collection_module, "collection_access", lambda *a, **kw: _Allowed())
    return await collect_source(
        source.company, {"adapter": "google"}, scope, NoComp(), max_list=None, hydrate=True,
        limiter_pool=RateLimiterPool(), adapter_factory=lambda *a, **kw: source, **kwargs,
    )


def _key(req: str, company: str = "google") -> str:
    return RawJob(company, req, "", "").dedupe_key()


@pytest.mark.asyncio
async def test_a_posting_failing_only_on_an_unstated_level_is_read_before_deciding(monkeypatch):
    # The switch is off: unread, both would be dropped ("Software
    # Engineer" states no level). Read, one posts Staff's range (L6) and is
    # kept for a person tracking staff; one posts Senior Staff's (L7) and stays out.
    assert read_level(_job("google", "Software Engineer, Google Cloud"), "software_engineering").basis is LevelBasis.NONE
    source = _Source({"l6": _L6, "l7": _L7})
    collection = await _collect(source, _scope(include_unstated=False), monkeypatch)

    assert source.hydrated == ["l6", "l7"]  # one read each, never two
    kept = {job.raw.req_id: job for job in collection.enriched}
    assert set(kept) == {"l6"}
    assert (kept["l6"].level_band, kept["l6"].level_basis) == (LevelBand.STAFF, LevelBasis.PAY_GRADE)
    assert collection.scope_by_key[_key("l7")] is False
    assert collection.stats["kept"] == 1


@pytest.mark.asyncio
async def test_a_posting_out_on_another_axis_is_never_read(monkeypatch):
    # Level is not the only thing it fails: reading it could not admit it.
    source = _Source({"pm": _L6})
    collection = await _collect(source, _scope(include_unstated=False, roles=("data_science",)), monkeypatch)
    assert source.hydrated == []
    assert collection.enriched == []


@pytest.mark.asyncio
async def test_a_posting_we_hold_text_for_is_not_fetched_again(monkeypatch):
    # `levels_backfill` re-reads it from the stored text instead.
    source = _Source({"pm": _L6})
    collection = await _collect(
        source, _scope(include_unstated=False), monkeypatch,
        lookups=SourceLookups(fresh_description_keys=frozenset({_key("pm")})),
    )
    assert source.hydrated == []
    assert collection.enriched == []


@pytest.mark.asyncio
async def test_with_the_switch_on_nothing_changes(monkeypatch):
    # The posting already passes on its title and is read once;
    # the range still decides it after the read.
    source = _Source({"l6": _L6, "l7": _L7})
    collection = await _collect(source, _scope(include_unstated=True), monkeypatch)
    assert source.hydrated == ["l6", "l7"]
    assert {job.raw.req_id for job in collection.enriched} == {"l6"}


# --- a guessed level is read before deciding ---------------------- #

#: Google's engineering-manager ranges: L6 (staff) and L7 (principal) (`PAY_GRADES`).
_EM_L6, _EM_L7 = (207_000, 300_000), (262_000, 364_000)
#: A person tracking principal only, the switch on, people managers.
_PRINCIPAL_MANAGERS = {"include_unstated": True, "roles": ("engineering_management",),
                       "bands": ("principal",), "tracks": ("management",)}
#: The same with the switch off: a level we cannot place is left out unless a read places it.
_PRINCIPAL_MANAGERS_ONLY_PLACED = {**_PRINCIPAL_MANAGERS, "include_unstated": False}


def _reading(company: str, title: str, raw_level: str | None = None) -> LevelReading:
    return read_level(_job(company, title, raw_level=raw_level), classify_family(_job(company, title)))


@pytest.mark.asyncio
async def test_a_level_guessed_from_a_role_word_is_read_before_deciding(monkeypatch):
    # "Engineering Manager" names no rung: the generic staff is our guess, a
    # level we cannot place. With the switch off it is left out
    # unless what it states places it, so it is read first: one posts the L7
    # range (principal) and is kept; one posts L6 and stays out.
    title = "Engineering Manager, Cloud Networking"
    assert _reading("google", title) == (LevelBand.STAFF, LevelConfidence.CONFIRMED, LevelBasis.UNMAPPED)
    source = _Source({"l6": _EM_L6, "l7": _EM_L7}, title=title)
    collection = await _collect(source, _scope(**_PRINCIPAL_MANAGERS_ONLY_PLACED), monkeypatch)

    assert source.hydrated == ["l6", "l7"]
    kept = {job.raw.req_id: job for job in collection.enriched}
    assert set(kept) == {"l7"}
    assert (kept["l7"].level_band, kept["l7"].level_basis) == (LevelBand.PRINCIPAL, LevelBasis.PAY_GRADE)
    assert collection.scope_by_key[_key("l6")] is False


@pytest.mark.asyncio
async def test_with_the_switch_on_a_guessed_level_is_admitted_and_its_range_still_decides(monkeypatch):
    # A guess never hides a posting from a person who includes levels we
    # cannot place: both are kept on the title and read once; the
    # stated range then places L6 at staff, out of a principal scope.
    title = "Engineering Manager, Cloud Networking"
    source = _Source({"l6": _EM_L6, "l7": _EM_L7}, title=title)
    collection = await _collect(source, _scope(**_PRINCIPAL_MANAGERS), monkeypatch)

    assert source.hydrated == ["l6", "l7"]
    assert {job.raw.req_id for job in collection.enriched} == {"l7"}
    assert collection.scope_by_key[_key("l6")] is False


@pytest.mark.asyncio
async def test_a_guess_no_read_could_place_is_kept_unread_with_the_switch_on(monkeypatch):
    # At a company with no measured range the page cannot place it, and the
    # person includes levels we cannot place: kept on the title, labelled.
    source = _Source({"em": _EM_L7}, title="Engineering Manager, Platform", company="acme")
    collection = await _collect(source, _scope(**_PRINCIPAL_MANAGERS), monkeypatch)
    kept = {job.raw.req_id: job for job in collection.enriched}
    assert set(kept) == {"em"}
    assert kept["em"].level_basis is LevelBasis.UNMAPPED


@pytest.mark.asyncio
async def test_a_title_that_states_its_level_is_never_read_for_it(monkeypatch):
    # "Senior Engineering Manager" is Google's own word for L7 (principal): for
    # a person tracking staff it is out on what the title states, so no read.
    title = "Senior Engineering Manager, Search"
    assert _reading("google", title).basis is LevelBasis.COMPANY
    source = _Source({"em": _EM_L6}, title=title)
    collection = await _collect(source, _scope(**{**_PRINCIPAL_MANAGERS, "bands": ("staff",)}), monkeypatch)
    assert source.hydrated == []
    assert collection.enriched == []


@pytest.mark.asyncio
async def test_a_guess_no_read_could_place_is_never_read(monkeypatch):
    # A company with no measured ranges and no printed rung: the page holds
    # nothing a level is read from, so fetching it would change nothing.
    title = "Engineering Manager, Platform"
    assert grade_for_pay("acme", "engineering_management", *_EM_L7, 2026) is None
    source = _Source({"em": _EM_L7}, title=title, company="acme")
    collection = await _collect(source, _scope(**_PRINCIPAL_MANAGERS_ONLY_PLACED), monkeypatch)
    assert source.hydrated == []
    assert collection.enriched == []


@pytest.mark.parametrize(("company", "title", "guess"), [
    ("google", "Engineering Manager, Cloud Networking", True),  # role word, read staff
    ("google", "Product Manager, Ads", True),  # unconfirmed senior, no rung word
    ("acme", "Software Engineer", True),  # nothing stated
    ("apple", "Senior Software Engineer", False),  # rung word names the band, though Apple's is unconfirmed
    ("acme", "Senior Product Manager", False),  # a rung titled Senior is senior
    ("acme", "Director, Product", False),
    ("acme", "Software Engineering Intern", False),  # the stage is stated
    ("google", "Senior Engineering Manager, Search", False),  # the company's own word
])
def test_a_guess_is_a_band_no_word_in_the_title_states(company, title, guess):
    assert is_level_guess(title, _reading(company, title)) is guess


@pytest.mark.parametrize(("company", "title", "raw_level", "can"), [
    ("google", "Product Manager, Ads", None, True),  # measured ranges for the family
    ("microsoft", "Product Manager", None, True),  # prints a rung we band
    ("acme", "Engineering Manager, Platform", None, False),  # nothing measured, prints nothing
    ("google", "Senior Product Manager, Ads", None, False),  # a rung word: no range outranks it
    ("google", "Software Engineering Intern", None, False),  # an early-stage marker outranks a range
    # Microsoft prints M5/IC6 on director titles and `read_level` never lets a
    # rung below director pull one down: reading the page cannot
    # change the level, so it is no reason to read.
    ("microsoft", "Director, Silicon Design", None, False),
    ("microsoft", "Group Creative Director", None, False),
])
def test_a_full_read_can_state_a_level_only_where_a_level_is_read_from_it(company, title, raw_level, can):
    job = _job(company, title, raw_level=raw_level)
    assert full_read_can_state(job, classify_family(job)) is can
