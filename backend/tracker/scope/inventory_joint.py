"""The scope screens' counts from the posting inventory.

`role_catalog` holds a per-company tally written by the scan that read it;
`posting_inventory` holds the postings themselves, the rows a scope
save promotes onto the Board. Counting from the inventory makes "N
roles fit" and "N roles are on your Board" two readings of one set of rows.

One tally, one shaping: every live row goes through `add_to_catalog`, the
function the scan tallies with, and the result through
`catalog_store.catalog_rows`, the shape the stored catalog has. So
`scope/catalog.py` reads these entries exactly as it reads `role_catalog`
rows, and the joint, the marginals and the city strip are unchanged.

Which rows count:

- not gone, at a followed, active, visible company;
- not matching a learned exclusion (applied here, in SQL: the joint cannot
  carry a team or department, so it is applied before the joint exists and
  the browser's counts are exact rather than an upper bound);
- at a company with no complete read yet (`partial`), only rows seen within
  `scope_partial_window_days`: a capped read only ever adds rows, and without
  a complete read nothing marks one gone.

A complete read is the evidence `run_persistence.scan_may_close` acted on,
read back from the append-only `scrape_source_runs`: a reconcile,
uncapped, with a complete listing, no errors, and an inventory write that
succeeded. Discovery probes and counts are capped and never qualify.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy import Boolean, and_, cast, func, not_, select
from sqlalchemy.ext.asyncio import AsyncSession

from tracker.config import get_settings
from tracker.db.inventory_store import fresh_since, read_recently
from tracker.db.models import PostingInventory, ScrapeSourceRun
from tracker.db.queries.companies import is_followed_row
from tracker.db.queries.scope import load_scope_exclusions, scope_exclusion_expr
from tracker.schema import LevelBand, LevelBasis, RawJob, RoleTrack, parse_band
from tracker.scope.catalog_store import catalog_rows
from tracker.taxonomy.role_catalog import CatalogTallies, add_to_catalog, catalog_drop_reason

_BANDS = frozenset(band.value for band in LevelBand)
_TRACKS = frozenset(track.value for track in RoleTrack)
_BASES = frozenset(basis.value for basis in LevelBasis)


@dataclass
class _Stored:
    """A row's stored classification, read as the tally reads an annotation."""

    band: LevelBand
    track: RoleTrack
    family: str | None
    location_groups: list[str]
    domains: list[str]
    basis: LevelBasis | None = None


@dataclass(frozen=True)
class InventoryEntry:
    """One company's tally for one role group: the `RoleCatalog` attributes
    `scope/catalog.py` reads, built from inventory rows."""

    company: str
    role_group: str
    count: int
    band_counts: dict
    band_track_counts: dict
    scope_cells: list
    examples: list
    domain_counts: dict
    domain_examples: dict


@dataclass
class InventoryCounts:
    entries: list[InventoryEntry] = field(default_factory=list)
    #: Counted companies (a complete read, or rows from a partial one).
    counted: set[str] = field(default_factory=set)
    #: Counted companies with no complete read yet.
    partial: set[str] = field(default_factory=set)
    #: Followed companies never read: no complete read and no rows.
    missing: set[str] = field(default_factory=set)
    #: Followed companies read before, but not within the freshness window:
    #: their rows stopped counting, so they are named rather than silently shrunk.
    stale: set[str] = field(default_factory=set)
    #: When each `stale` company was last read: its last complete read or the
    #: last time a scan listed any of its rows, whichever is later.
    last_read: dict[str, datetime] = field(default_factory=dict)
    #: Live rows `add_to_catalog` could not count, per company, by reason.
    unplaced: dict[str, int] = field(default_factory=dict)
    unsorted: dict[str, int] = field(default_factory=dict)
    #: Counted rows per location group, every group a row names.
    location_counts: dict[str, int] = field(default_factory=dict)

    def not_counted(self) -> dict[str, str]:
        """What the Profile's count leaves out, one rule for the Profile and the
        Companies screen."""
        return {
            **{slug: "missing" for slug in sorted(self.missing)},
            **{slug: "partial" for slug in sorted(self.partial)},
            **{slug: "stale" for slug in sorted(self.stale)},
        }


async def complete_reads(session: AsyncSession, companies: Iterable[str]) -> dict[str, datetime]:
    """The last complete read per company: when a sync last listed its whole
    board and wrote what it read to the inventory."""
    slugs = sorted(set(companies))
    if not slugs:
        return {}
    run = ScrapeSourceRun
    stmt = (
        select(run.company_slug, func.max(run.finished_at))
        .where(
            run.company_slug.in_(slugs),
            run.scan_mode == "reconcile",
            run.list_complete.is_(True),
            func.jsonb_array_length(run.errors) == 0,
            func.coalesce(cast(run.stats["capped"].astext, Boolean), False).is_(False),
            run.stats.has_key("inventory_rows"),
        )
        .group_by(run.company_slug)
    )
    return {slug: at for slug, at in (await session.execute(stmt)).all()}


async def last_reads(
    session: AsyncSession, companies: Iterable[str], complete: dict[str, datetime],
) -> dict[str, datetime]:
    """When each company was last read: the later of its last complete read
    and the last time any read listed one of its rows. Absent: never read."""
    slugs = sorted(set(companies))
    if not slugs:
        return {}
    listed: dict[str, datetime] = {
        company: at
        for company, at in (await session.execute(
            select(PostingInventory.company, func.max(PostingInventory.last_seen_at))
            .where(PostingInventory.company.in_(slugs))
            .group_by(PostingInventory.company)
        )).all()
    }
    out: dict[str, datetime] = {}
    for slug in slugs:
        times = [at for at in (complete.get(slug), listed.get(slug)) if at is not None]
        if times:
            out[slug] = max(times)
    return out


async def inventory_counts(
    session: AsyncSession, tracked: Iterable, hidden: Iterable[str], *,
    now: datetime | None = None, apply_exclusions: bool = True,
) -> InventoryCounts:
    """The catalog entries and per-company state the scope screens read,
    from the posting inventory. `tracked` are `tracked_company` rows.
    `apply_exclusions=False` is for the bench, which compares with the stored
    catalog, a tally that never applied them."""
    now = now or datetime.now(UTC)
    hidden_set = set(hidden)
    followed = sorted(
        row.slug for row in tracked
        if is_followed_row(row) and row.slug not in hidden_set
    )
    complete = await complete_reads(session, followed)
    window_start = now - timedelta(days=get_settings().scope_partial_window_days)

    stmt = select(
        PostingInventory.company, PostingInventory.title, PostingInventory.department,
        PostingInventory.team, PostingInventory.family, PostingInventory.level_band,
        PostingInventory.level_basis, PostingInventory.track, PostingInventory.location_groups, PostingInventory.domains,
        PostingInventory.last_seen_at,
    ).where(
        PostingInventory.company.in_(followed),
        PostingInventory.gone_at.is_(None),
        # What promotion admits, so the count is what a save adds.
        read_recently(now),
    )
    exclusions = await load_scope_exclusions(session) if apply_exclusions else frozenset()
    if exclusions:
        stmt = stmt.where(not_(scope_exclusion_expr(exclusions, model=PostingInventory)))
    unread = [slug for slug in followed if slug not in complete]
    if unread:
        stmt = stmt.where(
            ~and_(PostingInventory.company.in_(unread), PostingInventory.last_seen_at < window_start)
        )
    stmt = stmt.order_by(PostingInventory.id)

    tallies: dict[str, CatalogTallies] = {}
    counts = InventoryCounts()
    unplaced: Counter[str] = Counter()
    unsorted: Counter[str] = Counter()
    places: Counter[str] = Counter()
    with_rows: set[str] = set()
    for row in (await session.execute(stmt)).all():
        with_rows.add(row.company)
        if row.level_band not in _BANDS or row.track not in _TRACKS:
            # Classified by an older taxonomy the next run's reclassify pass
            # rewrites. One such row must not blank the screen,
            # as `catalog.clean_joint` skips an unknown band.
            continue
        stored = _Stored(
            band=parse_band(row.level_band), track=RoleTrack(row.track), family=row.family,
            location_groups=list(row.location_groups or []), domains=list(row.domains or []),
            basis=LevelBasis(row.level_basis) if row.level_basis in _BASES else None,
        )
        raw = RawJob(
            company=row.company, req_id="", title=row.title, url="",
            department=row.department, team=row.team,
        )
        if add_to_catalog(tallies.setdefault(row.company, {}), raw, stored):
            places.update(set(stored.location_groups))
        elif catalog_drop_reason(stored) == "unsorted":
            unsorted[row.company] += 1
        else:
            unplaced[row.company] += 1

    for company, company_tallies in tallies.items():
        counts.entries.extend(InventoryEntry(company=company, **row) for row in catalog_rows(company_tallies))
    # A company read before but not within the window counts nothing now, so
    # it is named with when it was last read, not left to read as a smaller
    # count.
    read_at = await last_reads(session, followed, complete)
    cutoff = fresh_since(now)
    counts.stale = {
        slug for slug, at in read_at.items() if slug not in with_rows and at < cutoff
    }
    counts.last_read = {slug: read_at[slug] for slug in sorted(counts.stale)}
    counts.counted = (set(complete) - counts.stale) | with_rows
    counts.partial = with_rows - set(complete)
    counts.missing = set(followed) - counts.counted - counts.stale
    counts.unplaced = dict(unplaced)
    counts.unsorted = dict(unsorted)
    counts.location_counts = dict(places)
    return counts
