"""The posting inventory keeps every posting a sync reads.

`posting_inventory` is the superset of `jobs`: one slim row per posting a scan
read for a followed company, in scope or not, so a later scope widening can
admit a posting without a rescan. Invariants:

- I1 every row `retain` sees is captured, in scope or not, with its annotation;
- I8 only allowlisted listing facts reach a row: never a description, a detail
  payload or `source_facts`, where a person could ride in;
- I2 a second identical scan inside the touch window rewrites nothing;
- I3 only an authoritative listing marks rows gone;
- I4 a listed key the source could not build keeps its row alive, creates none;
- I5 a reappearance clears `gone_at`, and `first_seen_at` never moves.

The store runs on real Postgres; I6 (a failed write costs the source nothing)
and the stored stats keys live in `tests/test_pipeline_lifecycle.py`.
"""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from tests.factories import NoComp, scope_filter
from tracker.db.inventory_store import write_inventory
from tracker.db.models import PostingInventory, ScrapeRun
from tracker.enrich.enricher import annotate
from tracker.enrich.inventory import InventoryRow, inventory_row
from tracker.platform.drift import SchemaDriftDetector
from tracker.platform.ratelimit import RateLimiterPool
from tracker.schema import (
    AccessSurface,
    JobDescriptionSection,
    RawJob,
    SourceJobFacts,
    WorkplaceType,
)
from tracker.workflows.collection import collect_source

T0 = datetime(2026, 9, 28, 9, 0, tzinfo=UTC)


def _raw(req: str, title: str = "Staff Software Engineer", **extra) -> RawJob:
    return RawJob(
        company="acme", req_id=req, title=title, url=f"https://jobs.example.test/{req}",
        locations=["London, UK"], **extra,
    )


# --------------------------------------------------------------------------- #
# I8: the allowlist
# --------------------------------------------------------------------------- #

#: Every field an inventory row may carry. Adding one is a privacy decision,
#: made here on purpose rather than by growing the dataclass.
ALLOWED = {
    "dedupe_key", "req_id", "title", "url", "department", "team", "raw_level",
    "locations", "workplace_type", "posted_at", "level_band", "level_confidence",
    "level_basis", "family", "track", "location_groups", "domains",
}


def test_an_inventory_row_carries_only_allowlisted_listing_facts():
    assert {f.name for f in dataclasses.fields(InventoryRow)} == ALLOWED


def test_no_person_or_description_reaches_an_inventory_row():
    """A hiring team in the detail payload (Shopify), a recruiter in
    the description, a person in `source_facts`: none is a listing fact."""
    person = "Ada Lovelace, Hiring Manager"
    raw = _raw(
        "p1",
        description_html=f"<p>Reach out to {person}</p>",
        description_sections=[JobDescriptionSection(key="team", title="Your team", content=person)],
        detail_payload={"hiringTeam": [{"name": person}]},
        source_facts=SourceJobFacts(
            provider="greenhouse", access_surface=AccessSurface.PUBLIC_API, tenant_identity="acme",
            posting_id="p1", requisition_label=person,
        ),
        workplace_type=WorkplaceType.HYBRID,
        raw_level="L6",
    )
    row = inventory_row(raw, annotate(raw))
    assert person not in repr(row)
    assert row.workplace_type == "hybrid" and row.raw_level == "L6"


def test_a_row_keeps_the_classification_jobs_would_store():
    raw = _raw("c1")
    ann = annotate(raw)
    row = inventory_row(raw, ann)
    assert (row.level_band, row.family, row.track) == (ann.band.value, ann.family, ann.track.value)
    assert row.location_groups == tuple(ann.location_groups) and "uk" in row.location_groups
    assert row.domains == tuple(ann.domains)


def test_the_content_hash_moves_with_any_field_and_only_then():
    row = inventory_row(_raw("h1"), annotate(_raw("h1")))
    assert row.content_hash == inventory_row(_raw("h1"), annotate(_raw("h1"))).content_hash
    assert dataclasses.replace(row, title="Staff Engineer II").content_hash != row.content_hash
    assert dataclasses.replace(row, family=None).content_hash != row.content_hash
    assert dataclasses.replace(row, posted_at=T0).content_hash != row.content_hash


# --------------------------------------------------------------------------- #
# I1: capture, in scope or not
# --------------------------------------------------------------------------- #


class _Listing:
    """An inert listing: its rows, plus keys it names but cannot build."""

    def __init__(self, rows: list[RawJob], present_only: tuple[str, ...] = ()) -> None:
        self.company = "acme"
        self.drift = SchemaDriftDetector("acme")
        for key in present_only:
            self.drift.observe_present(key, "row had no title")
        self.truncated = False
        self.query_observations: list = []
        self._rows = rows

    def location_gaps(self) -> list[str]:
        return []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc) -> None:
        return None

    async def fetch(self):
        for raw in self._rows:
            yield raw

    async def hydrate(self, job: RawJob) -> None:
        return None


@pytest.mark.asyncio
async def test_every_scanned_row_is_captured_in_scope_or_not():
    kept, dropped, unsorted = _raw("in"), _raw("out", title="Staff Product Manager"), _raw("x", title="Barista")
    ann = annotate(kept)
    scope = scope_filter(
        bands={ann.band.value},
        roles={ann.family},
        tracks={ann.track.value},
        locations=ann.location_groups,
        domains=(),
    )
    listing = _Listing([kept, dropped, unsorted])
    collection = await collect_source(
        "acme", {"adapter": "greenhouse"}, scope, NoComp(), max_list=None, hydrate=False,
        limiter_pool=RateLimiterPool(), adapter_factory=lambda *a, **kw: listing,
    )
    assert collection.scope_by_key == {kept.dedupe_key(): True, dropped.dedupe_key(): False, unsorted.dedupe_key(): False}
    assert set(collection.inventory) == set(collection.scope_by_key)
    assert collection.inventory[dropped.dedupe_key()].family == annotate(dropped).family == "product_management"
    assert collection.inventory[unsorted.dedupe_key()].family is None


# --------------------------------------------------------------------------- #
# The store: I2, I3, I4, I5 on real Postgres
# --------------------------------------------------------------------------- #


async def _run(db_session) -> int:
    run = ScrapeRun(status="running")
    db_session.add(run)
    await db_session.flush()
    return run.id


def _rows(*reqs: str, title: str = "Staff Software Engineer") -> dict[str, InventoryRow]:
    out = {}
    for req in reqs:
        raw = _raw(req, title=title)
        out[raw.dedupe_key()] = inventory_row(raw, annotate(raw))
    return out


async def _write(db_session, rows, *, run_id, now, seen=None, authoritative=True, touch_hours=12.0):
    return await write_inventory(
        db_session, run_id=run_id, company="acme", binding_id=None, rows=rows,
        seen_keys=set(rows) if seen is None else seen, authoritative=authoritative,
        now=now, touch_hours=touch_hours,
    )


async def _stored(db_session) -> dict[str, PostingInventory]:
    db_session.expire_all()
    return {row.req_id: row for row in (await db_session.scalars(select(PostingInventory))).all()}


@pytest.mark.asyncio
async def test_an_unchanged_board_rewrites_nothing_inside_the_touch_window(db_session):
    run = await _run(db_session)
    first = await _write(db_session, _rows("a", "b"), run_id=run, now=T0)
    assert (first.rows, first.gone) == (2, 0)

    again = await _write(db_session, _rows("a", "b"), run_id=run, now=T0 + timedelta(hours=1))
    assert again.rows == 0
    assert {r.last_seen_at for r in (await _stored(db_session)).values()} == {T0}

    # A changed title is rewritten at once; the untouched row waits for the window.
    changed = await _write(
        db_session, {**_rows("a"), **_rows("b", title="Principal Software Engineer")},
        run_id=run, now=T0 + timedelta(hours=2),
    )
    assert changed.rows == 1
    assert (await _stored(db_session))["b"].title == "Principal Software Engineer"

    later = await _write(db_session, _rows("a"), run_id=run, now=T0 + timedelta(hours=13), authoritative=False)
    assert later.rows == 1
    assert (await _stored(db_session))["a"].last_seen_at == T0 + timedelta(hours=13)


@pytest.mark.asyncio
@pytest.mark.parametrize("authoritative", [True, False], ids=["authoritative", "capped_or_partial"])
async def test_only_an_authoritative_listing_marks_postings_gone(db_session, authoritative):
    run = await _run(db_session)
    await _write(db_session, _rows("a", "b", "c"), run_id=run, now=T0)

    result = await _write(db_session, _rows("a"), run_id=run, now=T0 + timedelta(hours=1), authoritative=authoritative)
    stored = await _stored(db_session)
    if authoritative:
        assert result.gone == 2
        assert (stored["b"].gone_at, stored["c"].gone_at) == (T0 + timedelta(hours=1),) * 2
    else:
        assert result.gone == 0
        assert all(row.gone_at is None for row in stored.values())
    assert stored["a"].gone_at is None


@pytest.mark.asyncio
async def test_a_listed_key_the_source_could_not_build_stays_alive_and_creates_nothing(db_session):
    run = await _run(db_session)
    await _write(db_session, _rows("a", "b"), run_id=run, now=T0)
    b_key = next(k for k in _rows("b"))
    ghost = _raw("never-built").dedupe_key()

    result = await _write(
        db_session, _rows("a"), run_id=run, now=T0 + timedelta(hours=20), seen={*_rows("a"), b_key, ghost},
    )
    stored = await _stored(db_session)
    assert set(stored) == {"a", "b"}, "a present-only key created a row"
    assert stored["b"].gone_at is None and result.gone == 0
    assert stored["b"].last_seen_at == T0 + timedelta(hours=20)


@pytest.mark.asyncio
async def test_a_reappearing_posting_clears_gone_and_keeps_its_first_sighting(db_session):
    run = await _run(db_session)
    await _write(db_session, _rows("a", "b"), run_id=run, now=T0)
    await _write(db_session, _rows("a"), run_id=run, now=T0 + timedelta(days=1))
    assert (await _stored(db_session))["b"].gone_at is not None

    # Inside the touch window of "a"'s last sighting, so only "b" is rewritten.
    back_at = T0 + timedelta(days=1, hours=1)
    back = await _write(db_session, _rows("a", "b"), run_id=run, now=back_at)
    stored = await _stored(db_session)
    assert back.rows == 1, "only the returning row is rewritten"
    assert stored["b"].gone_at is None
    assert stored["b"].first_seen_at == T0
    assert stored["b"].last_seen_at == back_at


@pytest.mark.asyncio
async def test_a_board_larger_than_one_batch_is_written_whole(db_session):
    run = await _run(db_session)
    rows = _rows(*(f"r{i}" for i in range(2_345)))
    assert (await _write(db_session, rows, run_id=run, now=T0)).rows == 2_345
    assert len(await _stored(db_session)) == 2_345


# --------------------------------------------------------------------------- #
# One touch rule for a built row and a listed-only row
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["built", "listed_only"])
@pytest.mark.parametrize(
    ("state", "incoming_run", "written"),
    [
        ("fresh", True, False),
        ("gone", True, True),
        ("stale", True, True),
        ("no_run", True, True),
        ("no_run", False, False),  # a count read never takes or gives a run
        ("fresh", False, False),
    ],
)
async def test_one_touch_rule_for_built_and_listed_only_rows(db_session, path, state, incoming_run, written):
    """Broken rule caught: the upsert and the listed-only UPDATE spelled the
    rule separately and could drift; both ask `_needs_touch`."""
    run = await _run(db_session)
    await _write(db_session, _rows("a"), run_id=run, now=T0)
    row = (await _stored(db_session))["a"]
    if state == "gone":
        row.gone_at = T0
    elif state == "stale":
        row.last_seen_at = T0 - timedelta(hours=24)
    elif state == "no_run":
        row.last_seen_run_id = None
    await db_session.flush()

    rows = _rows("a") if path == "built" else {}
    seen = set(_rows("a"))
    result = await _write(
        db_session, rows, run_id=run if incoming_run else None, now=T0 + timedelta(hours=1),
        seen=seen, authoritative=False,
    )
    assert (result.rows == 1) is written
