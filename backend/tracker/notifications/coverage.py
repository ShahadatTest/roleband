"""A followed company RoleBand has not scanned in full for days.

`/api/status.bindings_attention` reports every followed company without a
recent full scan; this rings for the ones a person loses something to:

- **Scanned automatically.** A user-directed company is scanned when its
  user asks, so days without a scan are not a loss; its row says when it was
  last scanned instead. A walled company without consent is not scanned at all,
  and neither is one on a source operator policy denies
  (`source_policy.scanned_automatically`).
- **Stale or empty.** No full scan for `coverage_stale_after_days`, or a
  careers page that answered with an empty list, which rings at once: a
  moved page is lost coverage from the first day. So does
  a careers page gone from its address: the company moved it, and
  waiting until it is stale only delays the one thing that fixes it, which is the
  person pointing RoleBand at the new page or unfollowing.
- **One notice for an outage.** When enough followed companies are stale at
  once (`binding_attention.is_outage`), the cause is ours, not theirs: one
  notice names how many, instead of one per company. Empty boards still ring
  on their own. Most of one provider's boards gone at once are the
  provider's answer more likely than that many companies moving
  (`missing_burst`): they ring only once stale, with the outage notice.

Reconciled, not appended, exactly like `pursuit_due.py`: each pass rewrites the
set of open `coverage` rows to match the report. A company scanned in full
again, unfollowed, or covered by an outage notice loses its row in the same
transaction that would otherwise re-assert it, and a lasting problem refreshes
its row in place ("· 4 days" becomes "· 5 days") without ringing again, since
`created_at` and `read_at` are not refreshable.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, tzinfo

from sqlalchemy import and_, delete, not_, or_
from sqlalchemy.ext.asyncio import AsyncSession

from tracker.config import get_settings
from tracker.db.models import Notification
from tracker.db.queries.binding_attention import (
    CAUSE_BOARD_MISSING,
    CAUSE_EMPTY_LISTING,
    CAUSE_PARTIAL,
    CAUSE_UNKNOWN,
    CAUSE_UNREACHABLE,
    CAUSE_UNREADABLE,
    attention_item,
    followed_bindings,
    is_outage,
    missing_burst,
)
from tracker.notifications import say as S
from tracker.notifications.channels import deliver
from tracker.notifications.events import ClassifiedNotif, _said
from tracker.platform.local_zone import local_zone
from tracker.source_policy import scanned_automatically

SOURCE_TYPE = "binding"


#: The outage notice's identity: one row, whatever the companies in it.
OUTAGE_SOURCE_TYPE = "outage"


OUTAGE_SOURCE_ID = 0


CATEGORY = "coverage"


#: Per cause: what went wrong, said as what happened to the careers page.
#: Keyed on the report's own constants (`db/queries/binding_attention.py`), so
#: a cause this table does not word fails in `classify_coverage`, loudly.
_COVERAGE_WHAT_KEY: dict[str, str] = {
    CAUSE_UNREACHABLE: "notif-coverage-unreachable",
    CAUSE_UNREADABLE: "notif-coverage-unreadable",
    CAUSE_PARTIAL: "notif-coverage-partial",
    CAUSE_UNKNOWN: "notif-coverage-unknown",
    CAUSE_EMPTY_LISTING: "notif-coverage-empty-listing",
    CAUSE_BOARD_MISSING: "notif-coverage-board-missing",
}


def _day_say(dt: datetime) -> dict:
    """`_day` as a date the dashboard writes ("28 Sep"), on the reader's calendar."""
    return S.day(dt.astimezone(_local_zone()).date())


def _local_zone() -> tzinfo:
    """The reader's zone: the machine's, as the digest reads it."""
    return local_zone()


def classify_coverage(item: dict) -> ClassifiedNotif:
    """A company you follow that RoleBand has not scanned in full lately.

    Reports the outcome, never the machinery (`docs/copy.md` rule 6): no
    binding, source, health or sync. What the user loses is named:
    new roles from the company may be missing. `item` is one
    `binding_attention` report item.

    The one source of these words: Settings > Companies shows the same title
    and body on the company's row (`/api/sync/targets` `coverage`).
    """
    company = item["display"]
    cause = item["cause"]
    if cause not in _COVERAGE_WHAT_KEY:
        raise ValueError(f"no Coverage copy for cause {cause!r}")
    held = item["held_open"]
    scan_days = item["days_since_full_scan"] if item.get("last_full_scan_at") is not None else None
    if cause == CAUSE_EMPTY_LISTING:
        # Read in full, so nothing is missing; what an empty page may mean is
        # that the company moved its roles elsewhere. Its postings cannot
        # close on an empty list.
        title_say = S.say("notif-coverage-empty-title", company=company, days=S.days(item.get("days_empty")))
        body_say = [S.say("notif-coverage-empty-moved", company=company)]
        if held:
            body_say.append(S.say("notif-coverage-held-until-listed", held=held))
        days = item.get("days_empty")
    elif cause == CAUSE_BOARD_MISSING:
        # The company moved its page. Nothing clears this on its own, so it
        # says what does: the person finds the
        # new page or stops following. Its postings close only once RoleBand
        # reads the new page in full.
        days = scan_days
        title_say = S.say("notif-coverage-gone-title", company=company, days=S.days(days))
        body_say = [S.say("notif-coverage-gone-moved", company=company)]
        if held:
            body_say.append(S.say("notif-coverage-held-until-then", held=held))
    else:
        days = scan_days
        last = item.get("last_full_scan_at")
        title_say = (
            S.say("notif-coverage-waiting-title", company=company)
            if cause == CAUSE_UNKNOWN
            else S.say("notif-coverage-scan-title", company=company, days=S.days(days))
        )
        body_say = [
            S.say("notif-coverage-not-scanned-since", day=_day_say(last), company=company)
            if last is not None
            else S.say("notif-coverage-not-scanned", company=company)
        ]
    return ClassifiedNotif(
        priority="normal",
        category="coverage",
        meta={
            "company": item["company"],
            "display": company,
            "cause": cause,
            "held_open": held,
            "days": days,
            "cause_message": item["cause_message"],
            "say": _said(title_say, S.say(_COVERAGE_WHAT_KEY[cause]), *body_say),
        },
    )


def classify_coverage_outage(items: list[dict]) -> ClassifiedNotif:
    """Many followed companies without a full scan at once.

    The cause is ours, not each company's: such a gap is the scheduler not
    running. One notice says how many and since when, in place of one per
    company; the companies are in `meta` for the operator view.
    """
    days = min(
        (i["days_since_full_scan"] or 0.0) if i.get("last_full_scan_at") is not None else 0.0
        for i in items
    ) if items else 0.0
    dated = [i["last_full_scan_at"] for i in items if i.get("last_full_scan_at") is not None]
    count = len(items)
    waiting = bool(items) and all(i["cause"] == CAUSE_UNKNOWN for i in items)
    return ClassifiedNotif(
        priority="normal",
        category="coverage",
        meta={
            "outage": True,
            "companies": sorted(i["company"] for i in items),
            "days": days,
            "say": _said(
                S.say("notif-coverage-waiting-outage", count=count)
                if waiting else S.say("notif-coverage-outage", count=count, days=S.days(days)),
                S.say("notif-coverage-outage-since", day=_day_say(max(dated)))
                if dated
                else S.say("notif-coverage-outage-body"),
            ),
        },
    )


def rings(item: dict, *, outage: bool = False, burst: bool = False) -> bool:
    """Whether one report item rings on its own. See the module docstring."""
    if not item["automatic"]:
        return False
    if item["empty_since"] is not None:
        return True
    if item["cause"] == CAUSE_BOARD_MISSING and not burst:
        return True
    return bool(item["stale"]) and not outage


async def coverage_report(session: AsyncSession, now: datetime) -> tuple[list[dict], bool]:
    """Every followed company's report item (with its `binding_id`), and whether
    the stale ones are an outage. The bell and Settings > Companies read this
    one answer."""
    rows = await followed_bindings(session, automatic=scanned_automatically)
    stale_after = timedelta(days=get_settings().coverage_stale_after_days)
    items = [
        {**attention_item(row, now, stale_after=stale_after), "binding_id": row.binding_id}
        for row in rows
    ]
    return items, is_outage(items, sum(1 for r in rows if r.automatic))


def _ids(items: list[dict]) -> list[int]:
    return [item["binding_id"] for item in items]


async def generate_coverage_notifications(session: AsyncSession, *, now: datetime | None = None) -> int:
    """Reconcile `coverage` rows against the followed companies that ring now."""
    now = now or datetime.now(UTC)
    items, outage = await coverage_report(session, now)
    burst = missing_burst(items)
    ringing = [item for item in items if rings(item, outage=outage, burst=burst)]
    # The outage notice names the stale companies that do not ring on their own.
    alone = {item["binding_id"] for item in ringing}
    stale = [i for i in items if i["automatic"] and i["stale"] and i["binding_id"] not in alone]

    # Retract first: a company scanned again since the last pass must lose its
    # row in the same transaction that would otherwise re-assert it.
    keep = [
        and_(Notification.source_type == SOURCE_TYPE, Notification.source_id.in_(_ids(ringing)))
    ] if ringing else []
    if outage:
        keep.append(Notification.source_type == OUTAGE_SOURCE_TYPE)
    stale_rows = delete(Notification).where(
        Notification.category == CATEGORY,
        Notification.source_type.in_((SOURCE_TYPE, OUTAGE_SOURCE_TYPE)),
    )
    if keep:
        stale_rows = stale_rows.where(not_(or_(*keep)))
    await session.execute(stale_rows)

    deliveries = [(SOURCE_TYPE, item["binding_id"], classify_coverage(item)) for item in sorted(
        ringing, key=lambda i: i["binding_id"]
    )]
    if outage:
        deliveries.append((OUTAGE_SOURCE_TYPE, OUTAGE_SOURCE_ID, classify_coverage_outage(stale)))
    for source_type, source_id, classified in deliveries:
        await deliver(
            session,
            {
                "created_at": now,
                "priority": classified.priority,
                "category": classified.category,
                "title": classified.title,
                "body": classified.body,
                "job_id": None,
                "run_id": None,
                "source_type": source_type,
                "source_id": source_id,
                "meta": classified.meta or {},
            },
            refresh=("title", "body", "meta", "priority"),
        )
    return len(deliveries)
