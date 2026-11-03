"""The posting inventory's only writer.

`write_inventory` keeps one company's rows current after a scan: every row the
scan read is upserted, a listed key the source could not build
(`present_only`) keeps its row alive, and only an authoritative listing marks
the rest gone. Current state, never history: `first_seen_at` is set once,
`gone_at` clears on reappearance.

A steady board costs no row churn: an upsert rewrites a row only when its
content changed, it was gone, or its last touch is older than the touch window.
Commits nothing; the caller holds the company's transaction.

Retention: `remove_unread` deletes rows no scan has read since a
cutoff, and `retention_counts` counts them with the same clause, so what
Settings says is due is what a run removes. One rule covers every case the user
means: a posting that leaves its listing stops being read, and so does every
posting of a company that is unfollowed or untracked.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence, Set
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import (
    ColumnElement,
    Integer,
    Text,
    and_,
    any_,
    delete,
    func,
    literal,
    not_,
    or_,
    select,
    update,
)
from sqlalchemy.dialects.postgresql import ARRAY, insert

from tracker.config import get_settings
from tracker.db.models import PostingInventory, TrackedCompany
from tracker.db.queries.companies import followed_company, is_followed
from tracker.enrich.enricher import annotate
from tracker.enrich.inventory import InventoryRow, classifier_fingerprint, inventory_row
from tracker.schema import RawJob, WorkplaceType
from tracker.settings_store import get_setting_dict, set_setting_dict

#: Rows per INSERT: 25 columns x 1,000 stays under asyncpg's 32,767 parameters.
_BATCH = 1000

#: Columns an upsert refreshes; `first_seen_at` is written by the insert only.
_REFRESHED = (
    "req_id", "title", "url", "department", "team", "raw_level", "locations",
    "workplace_type", "posted_at", "level_band", "level_confidence", "level_basis", "family",
    "track", "location_groups", "domains", "content_hash", "binding_id",
    "last_seen_at", "last_seen_run_id",
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class InventoryWrite:
    #: Rows inserted or rewritten, including present-only keys revived or touched.
    rows: int
    #: Rows this listing marked gone.
    gone: int


def _values(
    row: InventoryRow, *, company: str, binding_id: int | None, run_id: int | None, now: datetime
) -> dict:
    return {
        "dedupe_key": row.dedupe_key,
        "company": company,
        "req_id": row.req_id,
        "binding_id": binding_id,
        "title": row.title,
        "url": row.url,
        "department": row.department,
        "team": row.team,
        "raw_level": row.raw_level,
        "locations": list(row.locations),
        "workplace_type": row.workplace_type,
        "posted_at": row.posted_at,
        "level_band": row.level_band,
        "level_confidence": row.level_confidence,
        "level_basis": row.level_basis,
        "family": row.family,
        "track": row.track,
        "location_groups": list(row.location_groups),
        "domains": list(row.domains),
        "content_hash": row.content_hash,
        "first_seen_at": now,
        "last_seen_at": now,
        "last_seen_run_id": run_id,
        "gone_at": None,
    }


def _needs_touch(stale_before: datetime, incoming_run):
    """A stored row worth writing even when its content is unchanged: it was
    marked gone (revived), it was not touched within the window (its
    `last_seen_at` would go stale), or it names no sync while this read is one
    (a row only a count read wrote gains the first sync's run at once, or it
    stays unpromotable for a whole window). `incoming_run` is the run this
    read writes, NULL for a count read. One spelling for the full upsert and
    the listed-only UPDATE."""
    return or_(
        PostingInventory.gone_at.isnot(None),
        PostingInventory.last_seen_at < stale_before,
        and_(PostingInventory.last_seen_run_id.is_(None), incoming_run.isnot(None)),
    )


async def write_inventory(
    session,
    *,
    run_id: int | None,
    company: str,
    binding_id: int | None,
    rows: Mapping[str, InventoryRow],
    seen_keys: Set[str],
    authoritative: bool,
    now: datetime,
    touch_hours: float,
) -> InventoryWrite:
    """Upsert one company's scanned rows; mark gone only when `authoritative`.

    `seen_keys` is every key the listing named, built or not; `authoritative`
    is `run_persistence.scan_may_close` (reconcile, uncapped, complete,
    error-free). Anything less upserts what it saw and marks nothing gone.

    `run_id` is None for a read that opens no run ("Count now"). Such a read
    never takes a sync's run from a row it touches: the row keeps naming the
    last run that read it, or none if no sync has.
    """
    stale_before = now - timedelta(hours=touch_hours)
    written = 0
    items = list(rows.values())
    for start in range(0, len(items), _BATCH):
        stmt = insert(PostingInventory).values([
            _values(row, company=company, binding_id=binding_id, run_id=run_id, now=now)
            for row in items[start:start + _BATCH]
        ])
        stmt = stmt.on_conflict_do_update(
            index_elements=[PostingInventory.dedupe_key],
            set_={
                **{name: stmt.excluded[name] for name in _REFRESHED},
                "last_seen_run_id": func.coalesce(
                    stmt.excluded.last_seen_run_id, PostingInventory.last_seen_run_id
                ),
                "gone_at": None,
            },
            where=or_(
                PostingInventory.content_hash.is_distinct_from(stmt.excluded.content_hash),
                _needs_touch(stale_before, stmt.excluded.last_seen_run_id),
            ),
        ).returning(PostingInventory.id)
        written += len((await session.execute(stmt)).all())

    # Listed, but the source could not build a row: alive, never created.
    present_only = sorted(set(seen_keys) - rows.keys())
    if present_only:
        revived = await session.execute(
            update(PostingInventory)
            .where(
                PostingInventory.dedupe_key == any_(literal(present_only, ARRAY(Text))),
                _needs_touch(stale_before, literal(run_id, Integer)),
            )
            .values(
                gone_at=None, last_seen_at=now,
                last_seen_run_id=func.coalesce(literal(run_id), PostingInventory.last_seen_run_id),
            )
        )
        written += revived.rowcount or 0

    gone = 0
    if authoritative:
        marked = await session.execute(
            update(PostingInventory)
            .where(
                PostingInventory.company == company,
                PostingInventory.gone_at.is_(None),
                not_(PostingInventory.dedupe_key == any_(literal(sorted(seen_keys), ARRAY(Text)))),
            )
            .values(gone_at=now)
        )
        gone = marked.rowcount or 0
    return InventoryWrite(rows=written, gone=gone)


async def pending_inventory_classes(session) -> list[dict]:
    """Re-derive every inventory row's classification from its stored fields;
    the rows whose classification changed, written by
    `write_inventory_classes` (one transaction, the pass) or in batches
    (`scripts.backfill_classifier`).

    The `jobs` reclassify passes (roles, domains, places) bring stored rows in
    line with a taxonomy change at once; promotion must not then admit by an
    older classification than the Board shows. `annotate` reads only fields
    the inventory stores (company, title, level text, locations, department,
    team), so re-annotating IS the capture rule, not a copy of it. Writes only
    rows whose content hash moved; once caught up, a scan that writes nothing.

    A row the code cannot read (a stored value outside the current enum) is
    skipped and logged, never the pass: failing the pass whole would stop
    promotion and repeat the full re-derivation every run.
    """
    rows = (
        await session.execute(
            select(
                PostingInventory.id, PostingInventory.company, PostingInventory.req_id,
                PostingInventory.title, PostingInventory.url, PostingInventory.department,
                PostingInventory.team, PostingInventory.raw_level, PostingInventory.locations,
                PostingInventory.workplace_type, PostingInventory.posted_at,
                PostingInventory.content_hash,
            ).order_by(PostingInventory.id.asc())
        )
    ).all()
    changes = []
    unreadable: list[int] = []
    for row in rows:
        try:
            workplace = WorkplaceType(row.workplace_type)
        except ValueError:
            unreadable.append(row.id)
            continue
        raw = RawJob(
            company=row.company, req_id=row.req_id, title=row.title, url=row.url,
            locations=list(row.locations or []), department=row.department, team=row.team,
            workplace_type=workplace, posted_at=row.posted_at,
            raw_level=row.raw_level,
        )
        fresh = inventory_row(raw, annotate(raw))
        if fresh.content_hash != row.content_hash:
            changes.append({
                "id": row.id,
                "level_band": fresh.level_band,
                "level_confidence": fresh.level_confidence,
                "level_basis": fresh.level_basis,
                "family": fresh.family,
                "track": fresh.track,
                "location_groups": list(fresh.location_groups),
                "domains": list(fresh.domains),
                "content_hash": fresh.content_hash,
            })
    if unreadable:
        logger.warning(
            "inventory reclassify skipped %d rows it cannot read (ids %s)", len(unreadable), unreadable[:20],
        )
    return changes


async def write_inventory_classes(session, changes: list[dict]) -> int:
    """Write re-derived classifications (`pending_inventory_classes` rows)."""
    if changes:
        await session.execute(update(PostingInventory), changes)
    return len(changes)


async def reclassify_inventory(session) -> int:
    """Re-derive every inventory row's classification and write what changed
    (`pending_inventory_classes`); returns how many changed."""
    return await write_inventory_classes(session, await pending_inventory_classes(session))


async def mark_classified(session) -> None:
    """Record that every row is classified by the current code: the next
    `reclassify_inventory_if_changed` reads nothing until the code changes."""
    await set_setting_dict(session, CLASSIFIED_WITH_KEY, {"fingerprint": classifier_fingerprint()})


#: The classifier fingerprint the inventory was last re-derived under.
CLASSIFIED_WITH_KEY = "inventory_classified_with"


async def reclassify_inventory_if_changed(session) -> int | None:
    """`reclassify_inventory` when the classifier changed since the last one;
    None when it did not (nothing read). Rows a scan writes are classified by
    the current code, so only a classifier change can leave one stale."""
    fingerprint = classifier_fingerprint()
    stored = await get_setting_dict(session, CLASSIFIED_WITH_KEY)
    if stored is not None and stored.get("fingerprint") == fingerprint:
        return None
    changed = await reclassify_inventory(session)
    await mark_classified(session)
    return changed


# --------------------------------------------------------------------------- #
# Retention
# --------------------------------------------------------------------------- #


def at_followed_company() -> ColumnElement[bool]:
    """The row's company is followed and collectable: what promotion admits
    from, spelled once with the Board's rule
    (`db.queries.companies.followed_company`). Retention's counts apply the
    same rule as a join (`retention_counts`)."""
    return followed_company(PostingInventory.company)


def fresh_since(now: datetime | None = None) -> datetime:
    """The start of the freshness window, `inventory_promotion_fresh_hours`
    back: a read before it does not count."""
    hours = get_settings().inventory_promotion_fresh_hours
    return (now or datetime.now(UTC)) - timedelta(hours=hours)


def read_recently(now: datetime | None = None) -> ColumnElement[bool]:
    """A scan read the row within `inventory_promotion_fresh_hours`: the one
    freshness rule, which promotion admits by and the scope counts count by,
    so a count never includes a row a save would not add."""
    return PostingInventory.last_seen_at >= fresh_since(now)


def unread_since(cutoff: datetime) -> ColumnElement[bool]:
    """No scan has read the row since `cutoff`: the whole retention rule.

    `last_seen_at` moves on every read older than the touch window, so a row a
    followed company still lists is never older than touch window + one scan
    cadence. Anything older has left its listing, or its company is not being
    scanned (unfollowed, removed, or failing for the whole window)."""
    return PostingInventory.last_seen_at < cutoff


@dataclass(frozen=True)
class RetentionCounts:
    #: Every stored row.
    stored: int
    #: Rows marked gone by an authoritative listing, at a followed company.
    no_longer_listed: int
    #: Rows at a company not followed (or not tracked at all).
    stopped_following: int
    #: Per window in days: rows no scan read within it, i.e. what a run under
    #: that window removes (up to its batch bound).
    due_by_days: Mapping[int, int]


async def retention_counts(session, *, now: datetime, windows: Sequence[int]) -> RetentionCounts:
    """One read for Settings > Data retention; `due_by_days` shares
    `unread_since` with `remove_unread`, so the two cannot disagree.

    The follow split is `at_followed_company`'s rule as a join on the
    company's key, at most one match per row: inside an aggregate's FILTER
    Postgres runs that EXISTS once per stored row, which is most of the read."""
    followed = TrackedCompany.slug.isnot(None)
    columns = [
        func.count(),
        func.count().filter(and_(PostingInventory.gone_at.isnot(None), followed)),
        func.count().filter(not_(followed)),
        *(func.count().filter(unread_since(now - timedelta(days=days))) for days in windows),
    ]
    stmt = select(*columns).select_from(PostingInventory).outerjoin(
        TrackedCompany, and_(TrackedCompany.slug == PostingInventory.company, is_followed())
    )
    row = (await session.execute(stmt)).one()
    return RetentionCounts(
        stored=row[0],
        no_longer_listed=row[1],
        stopped_following=row[2],
        due_by_days={days: row[3 + i] for i, days in enumerate(windows)},
    )


async def remove_unread(session, *, cutoff: datetime, limit: int) -> int:
    """Delete up to `limit` rows no scan read since `cutoff`, oldest id first;
    returns how many. Commits nothing.

    The clause is repeated on the DELETE itself, not only in the id subquery:
    under READ COMMITTED a row a concurrent scan refreshed after the subquery
    read it is re-checked against its new version and kept."""
    ids = (
        select(PostingInventory.id)
        .where(unread_since(cutoff))
        .order_by(PostingInventory.id)
        .limit(limit)
        .scalar_subquery()
    )
    result = await session.execute(
        delete(PostingInventory)
        .where(PostingInventory.id.in_(ids), unread_since(cutoff))
        .execution_options(synchronize_session=False)
    )
    return result.rowcount or 0
