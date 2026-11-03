"""Coverage notifications: a followed company not scanned in full lately.

What must hold, each a plausible way to get it wrong:

1. **The copy reports outcomes in the user's words** (`docs/copy.md`
   rule 6): when the company last had a full scan and what that costs
   (new roles may be missing), never binding / source / quarantine / sync.
2. **Only what a person loses.** An unfollowed company never rings; neither
   does a Workday company, scanned when its user asks, nor one
   followed yesterday that no scan has reached yet. A followed company rings
   after 3 days without a full scan; `lossy` counts as one; an empty careers
   page rings at once.
3. **One notice for an outage.** Five or more stale companies that are half or
   more of the automatically scanned ones ring once, not once each, and the
   per-company rows go; an empty board still rings on its own.
4. **Reconciled, not appended.** One row per company however many passes run;
   the row ages in place without losing its read or dismissed state; a full
   scan (or an unfollow) retracts it; other categories are never touched.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from tracker.config import Settings
from tracker.db.models import (
    Notification,
    ScrapeRun,
    ScrapeSourceRun,
    SourceBinding,
    TrackedCompany,
)
from tracker.db.queries.binding_attention import CAUSES, OUTAGE_MIN
from tracker.notifications import coverage
from tracker.notifications.coverage import (
    classify_coverage,
    classify_coverage_outage,
    generate_coverage_notifications,
    rings,
)

NOW = datetime(2026, 10, 2, 12, 0, tzinfo=UTC)
#: The shipped default (`Settings.coverage_stale_after_days`).
STALE_AFTER = timedelta(days=Settings.model_fields["coverage_stale_after_days"].default)

#: Words `docs/copy.md` keeps out of user copy, plus the internal health words.
BANNED = (
    "binding", "source", "sync", "scrape", "connector", "adapter", "quarantin", "suspect",
    "anomal", "drift", "inventory", "catalog", "endpoint", "board", "check",
)


@pytest.fixture(autouse=True)
def _utc_reader(monkeypatch):
    """The copy below is written for a reader in UTC; the day printed is the
    reader's own (`coverage._local_zone`), so it is pinned."""
    monkeypatch.setattr(coverage, "_local_zone", lambda: UTC)


def _item(**over) -> dict:
    item = {
        "company": "stripe", "display": "Stripe", "automatic": True, "stale": True,
        "cause": "unreachable", "days_since_full_scan": 4.4,
        "last_full_scan_at": datetime(2026, 9, 28, 3, 0, tzinfo=UTC), "held_open": 3,
        "empty_since": None, "days_empty": None, "cause_message": "ReadError: ",
    }
    item.update(over)
    return item


# --------------------------------------------------------------------------- #
# 1. The copy
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("over", "title", "body"),
    [
        (
            {},
            "Couldn't scan Stripe · 4 days",
            "Its careers page isn't answering. It hasn't had a full scan since 28 Sep, so new "
            "roles from Stripe may be missing. This clears on its next full scan.",
        ),
        (
            {"cause": "partial", "days_since_full_scan": 3.0},
            "Couldn't scan Stripe · 3 days",
            "Scans read only part of its careers page. It hasn't had a full scan since 28 Sep, "
            "so new roles from Stripe may be missing. This clears on its next full scan.",
        ),
        (
            # Never read in full: no date to name.
            {"cause": "unknown", "last_full_scan_at": None},
            "Waiting to scan Stripe",
            "No scan has reached its careers page. It hasn't had a full scan yet, so new roles "
            "from Stripe may be missing. This clears on its next full scan.",
        ),
        (
            # An empty careers page was read in full: nothing is missing. What
            # it may mean is a move (Vercel); what it costs is the
            # roles it held.
            {"cause": "empty_listing", "held_open": 1, "days_empty": 2.2},
            "Stripe lists no roles · 2 days",
            "Its careers page answered with an empty list. If Stripe is still hiring, its roles "
            "may have moved to a new careers page. 1 role stays as last seen until it lists "
            "roles again.",
        ),
        (
            {"cause": "empty_listing", "held_open": 0, "days_empty": 0.3},
            "Stripe lists no roles",
            "Its careers page answered with an empty list. If Stripe is still hiring, its roles "
            "may have moved to a new careers page.",
        ),
        (
            # 1.4 days is one day, not "1 days".
            {"days_since_full_scan": 1.4},
            "Couldn't scan Stripe · 1 day",
            "Its careers page isn't answering. It hasn't had a full scan since 28 Sep, so new "
            "roles from Stripe may be missing. This clears on its next full scan.",
        ),
    ],
    ids=["unreachable", "partial", "never-scanned", "empty-singular", "empty-fresh", "one-day"],
)
def test_the_copy_names_the_loss_and_what_ends_it(over, title, body):
    notif = classify_coverage(_item(**over))
    assert (notif.title, notif.body) == (title, body)
    assert (notif.category, notif.priority) == ("coverage", "normal"), "operational, not an interrupt"


def test_the_day_named_is_the_readers_own(monkeypatch):
    """A scan ending on the 27th in California can be dated the 28th in UTC.
    The notification must use the reader's local date, not the UTC date."""
    from zoneinfo import ZoneInfo

    monkeypatch.setattr(coverage, "_local_zone", lambda: ZoneInfo("America/Los_Angeles"))
    assert "since 27 Sep" in classify_coverage(_item()).body
    monkeypatch.setattr(coverage, "_local_zone", lambda: ZoneInfo("Asia/Tokyo"))
    assert "since 28 Sep" in classify_coverage(_item()).body


@pytest.mark.parametrize("cause", ["unreachable", "unreadable", "partial", "board_missing"])
def test_a_first_failed_scan_does_not_present_the_bindings_age_as_a_scan_gap(cause):
    notif = classify_coverage(_item(cause=cause, last_full_scan_at=None, days_since_full_scan=81.4))
    assert "81" not in notif.title
    assert notif.meta["say"]["title"]["p"]["days"] == 0


def test_companies_waiting_for_their_first_scan_are_not_an_eighty_day_failure():
    items = [_item(company=f"company-{i}", cause="unknown", last_full_scan_at=None,
                   days_since_full_scan=81.4) for i in range(5)]
    notif = classify_coverage_outage(items)
    assert notif.title == "Waiting to scan 5 companies"
    assert "81" not in notif.body


def test_a_new_company_in_an_outage_does_not_acquire_another_companys_scan_gap():
    notif = classify_coverage_outage([
        _item(last_full_scan_at=None, days_since_full_scan=81.4),
        _item(company="other", days_since_full_scan=4.4),
    ])
    assert notif.title == "Couldn't scan 2 companies"


def test_the_outage_copy_counts_the_companies_and_names_the_newest_full_scan():
    items = [
        _item(company=c, days_since_full_scan=d, last_full_scan_at=NOW - timedelta(days=d))
        for c, d in (("a", 4.0), ("b", 3.2), ("c", 6.0), ("d", 3.6), ("e", 5.1))
    ]
    notif = classify_coverage_outage(items)
    assert notif.title == "Couldn't scan 5 companies · 3 days"
    assert notif.body == (
        "None of them has had a full scan since 29 Sep, so new roles may be missing. "
        "This clears as scans get through."
    )
    assert notif.meta["companies"] == ["a", "b", "c", "d", "e"]


@pytest.mark.parametrize("cause", CAUSES)
def test_no_copy_uses_a_word_the_user_does_not_have(cause):
    """Every cause the report can serve, read from its own vocabulary rather
    than restated here; and the outage notice."""
    for notif in (classify_coverage(_item(cause=cause)), classify_coverage_outage([_item()] * 5)):
        text = f"{notif.title} {notif.body}".lower()
        assert [w for w in BANNED if w in text] == [], text


def test_a_cause_the_copy_does_not_know_fails_loudly():
    with pytest.raises(ValueError, match="flooded"):
        classify_coverage(_item(cause="flooded"))


def test_it_rings_only_for_what_a_person_loses():
    assert rings(_item())
    assert not rings(_item(stale=False)), "scanned in full within 3 days"
    assert not rings(_item(automatic=False)), "Workday: scanned when its user asks"
    assert rings(_item(stale=False, empty_since=NOW)), "an empty page rings at once"
    assert not rings(_item(), outage=True), "one outage notice instead"
    assert rings(_item(empty_since=NOW), outage=True), "an empty board is not our outage"
    assert not rings(_item(automatic=False, empty_since=NOW))


# --------------------------------------------------------------------------- #
# 2. Reconciliation, on seeded Postgres rows
# --------------------------------------------------------------------------- #

MADE = NOW - timedelta(days=60)


async def _company(session, slug: str, *, adapter: str = "greenhouse", enabled: bool = True,
                   binding_id: int, made: datetime = MADE) -> None:
    session.add(TrackedCompany(slug=slug, display=slug.title(), adapter=adapter, status="active",
                               enabled=enabled, visible=True, source="catalog"))
    await session.flush()
    session.add(SourceBinding(id=binding_id, company_slug=slug, connector_kind="adapter",
                              connector_id=adapter, status="stable", closure_capability="authoritative",
                              created_at=made))
    await session.flush()


_RUN_IDS = iter(range(1, 10_000))


async def _scan(session, binding_id: int, slug: str, outcome: str, ago: timedelta, *,
                errors: list | None = None, scanned: int = 10) -> None:
    run_id = next(_RUN_IDS)
    session.add(ScrapeRun(id=run_id, started_at=NOW - ago, status="ok"))
    await session.flush()
    session.add(ScrapeSourceRun(
        run_id=run_id, binding_id=binding_id, company_slug=slug, provider_key=slug,
        scan_mode="reconcile", outcome=outcome, started_at=NOW - ago, finished_at=NOW - ago,
        scanned=scanned, errors=errors or [], drift=[],
    ))
    await session.flush()


async def _seed(session) -> None:
    global _RUN_IDS
    _RUN_IDS = iter(range(1, 10_000))
    # Stalled: last full scan 4 days ago, a failed one since.
    await _company(session, "stalled", binding_id=21)
    await _scan(session, 21, "stalled", "ok", timedelta(days=4))
    await _scan(session, 21, "stalled", "failed", timedelta(hours=2), errors=["ReadError: "], scanned=0)
    # Fresh, and fresh by a lossy read: scanned in full within 3 days.
    await _company(session, "fresh", binding_id=22)
    await _scan(session, 22, "fresh", "ok", timedelta(hours=2))
    await _company(session, "lossyco", binding_id=23)
    await _scan(session, 23, "lossyco", "ok", timedelta(days=9))
    await _scan(session, 23, "lossyco", "lossy", timedelta(hours=5))
    # Unfollowed and stale: nobody's loss.
    await _company(session, "dirco", enabled=False, binding_id=24)
    await _scan(session, 24, "dirco", "ok", timedelta(days=30))
    # Workday, stale: scanned when its user asks.
    await _company(session, "wdco", adapter="workday", binding_id=25)
    await _scan(session, 25, "wdco", "ok", timedelta(days=5))
    # Followed yesterday, no scan yet.
    await _company(session, "newco", binding_id=26, made=NOW - timedelta(days=1))
    # Its careers page answered with an empty list a day ago.
    await _company(session, "emptyco", adapter="ashby", binding_id=27)
    await _scan(session, 27, "emptyco", "ok", timedelta(days=2), scanned=88)
    await _scan(session, 27, "emptyco", "empty", timedelta(days=1), scanned=0)
    # Another category's row under the SAME source key as stalled's coverage
    # row, which reconciliation must never touch.
    session.add(Notification(created_at=NOW, priority="high", category="pursuit_due", title="Follow up",
                             source_type="binding", source_id=21, meta={}))
    await session.commit()


async def _coverage_rows(session) -> list[Notification]:
    session.expire_all()
    return list((await session.scalars(
        select(Notification).where(Notification.category == "coverage").order_by(Notification.source_id)
    )).all())


@pytest.mark.asyncio
async def test_one_row_per_company_that_ages_in_place_and_leaves_on_a_full_scan(db_session):
    await _seed(db_session)

    assert await generate_coverage_notifications(db_session, now=NOW) == 2
    await db_session.commit()
    rows = await _coverage_rows(db_session)
    assert [(r.source_type, r.source_id, r.title) for r in rows] == [
        ("binding", 21, "Couldn't scan Stalled · 4 days"),
        ("binding", 27, "Emptyco lists no roles · 1 day"),
    ], "fresh, lossy-fresh, unfollowed, Workday and followed-yesterday companies do not ring"
    first = rows[0]
    assert first.meta["cause"] == "unreachable" and first.meta["cause_message"] == "ReadError: "
    read_stamp = NOW + timedelta(minutes=5)
    first.read_at = read_stamp
    first.dismissed_at = read_stamp
    await db_session.commit()

    # A day later: the same row, refreshed, still read and dismissed, not re-rung.
    later = NOW + timedelta(days=1)
    await generate_coverage_notifications(db_session, now=later)
    await db_session.commit()
    rows = await _coverage_rows(db_session)
    assert rows[0].id == first.id
    assert rows[0].title == "Couldn't scan Stalled · 5 days"
    assert (rows[0].created_at, rows[0].read_at, rows[0].dismissed_at) == (NOW, read_stamp, read_stamp)

    # A full scan: the row goes.
    await _scan(db_session, 21, "stalled", "ok", timedelta(hours=-20))
    await db_session.commit()
    await generate_coverage_notifications(db_session, now=later)
    await db_session.commit()
    assert [r.source_id for r in await _coverage_rows(db_session)] == [27]
    others = (await db_session.scalars(select(Notification).where(Notification.category == "pursuit_due"))).all()
    assert len(others) == 1, "another category sharing source_id 21 is untouched"


@pytest.mark.asyncio
async def test_stale_starts_at_three_days_without_a_full_scan(db_session):
    await _seed(db_session)
    just_before = NOW - timedelta(days=4) + STALE_AFTER - timedelta(minutes=1)
    await generate_coverage_notifications(db_session, now=just_before)
    await db_session.commit()
    assert [r.source_id for r in await _coverage_rows(db_session)] == [27]


@pytest.mark.asyncio
async def test_the_notice_reads_the_stale_bound_from_config(db_session, monkeypatch):
    """`coverage_stale_after_days` owns the number the notice
    uses; at 6 days the stalled company of the seed is not yet stale."""
    from tracker.config import get_settings

    await _seed(db_session)
    monkeypatch.setattr(get_settings(), "coverage_stale_after_days", 6.0)
    await generate_coverage_notifications(db_session, now=NOW)
    await db_session.commit()
    # Only the empty board rings; stalled (21, four days unscanned) is not yet stale.
    assert [r.source_id for r in await _coverage_rows(db_session)] == [27]


@pytest.mark.asyncio
async def test_unfollowing_retracts_the_row(db_session):
    await _seed(db_session)
    await generate_coverage_notifications(db_session, now=NOW)
    await db_session.commit()
    company = await db_session.get(TrackedCompany, "stalled")
    company.enabled = False
    await db_session.commit()
    await generate_coverage_notifications(db_session, now=NOW)
    await db_session.commit()
    assert [r.source_id for r in await _coverage_rows(db_session)] == [27]


@pytest.mark.asyncio
async def test_an_outage_rings_once_and_its_companies_leave_when_scans_get_through(db_session):
    await _seed(db_session)
    # Our scheduler down a week: every automatically scanned company is stale.
    week = NOW + timedelta(days=7)
    await generate_coverage_notifications(db_session, now=week)
    await db_session.commit()
    rows = await _coverage_rows(db_session)
    # stalled, fresh, lossyco and newco are stale: four, under OUTAGE_MIN.
    assert OUTAGE_MIN == 5
    assert [r.source_id for r in rows] == [21, 22, 23, 26, 27]

    await _company(db_session, "fifthco", binding_id=28)
    await _scan(db_session, 28, "fifthco", "ok", timedelta(days=6))
    await db_session.commit()
    await generate_coverage_notifications(db_session, now=week)
    await db_session.commit()
    rows = await _coverage_rows(db_session)
    assert [(r.source_type, r.source_id) for r in rows] == [("outage", 0), ("binding", 27)]
    outage = rows[0]
    assert outage.title == "Couldn't scan 5 companies"
    assert outage.meta["companies"] == ["fifthco", "fresh", "lossyco", "newco", "stalled"]

    # Scans get through for all but one: the outage ends, the one left rings alone.
    for binding_id, slug in ((22, "fresh"), (23, "lossyco"), (26, "newco"), (28, "fifthco")):
        await _scan(db_session, binding_id, slug, "ok", timedelta(days=-7))
    await db_session.commit()
    await generate_coverage_notifications(db_session, now=week)
    await db_session.commit()
    assert [(r.source_type, r.source_id) for r in await _coverage_rows(db_session)] == [
        ("binding", 21), ("binding", 27),
    ]
