"""The governing scope catalog: every axis a user can choose, with its inventory.

The aggregation is one named read with a session and a hidden-company list as
its only inputs. It is read-only: saves live with the endpoints that parse them.

What it joins: the five saved axes (`settings_store`), tracked companies and
their catalog status (`company_store`), per-adapter location coverage declared
by the connector manifests, the reference companies' level ladders (the
in-code decoder, `levels.ladder.walk_guide`), open-job location counts, and the
role-catalog inventory. Counts are pre-gate on purpose: this is where the gate
is chosen, so a disabled option must still show what it would include. The
`hidden` companies are the only exclusion.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import NamedTuple

from sqlalchemy import Text, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from tracker.company_store import get_tracked_companies
from tracker.config import get_settings
from tracker.connectors.listing import adapter_location_gaps
from tracker.db.models import Job, RoleCatalog, TrackedCompany
from tracker.levels import LEVELS, UNSTATED_LEVEL, all_band_slugs
from tracker.levels.ladder import stage_decoder
from tracker.schema import band_slug
from tracker.scope.inventory_joint import InventoryCounts, InventoryEntry, inventory_counts
from tracker.settings_store import (
    ENABLED_BANDS_KEY,
    ENABLED_LOCATIONS_KEY,
    ENABLED_ROLES_KEY,
    ENABLED_TRACKS_KEY,
    get_enabled_domains,
    read_opt_in_axes,
)
from tracker.taxonomy.categories import CATEGORY_GROUPS
from tracker.taxonomy.cities import CITY_PREFIX
from tracker.taxonomy.countries import BY_SLUG
from tracker.taxonomy.domains import DOMAIN_GROUPS
from tracker.taxonomy.locations import LOCATION_GROUPS, canonical_location_slugs, location_node
from tracker.taxonomy.role_answers import dump_answers
from tracker.taxonomy.role_catalog import UNCLASSIFIED_KEY
from tracker.taxonomy.roles import ROLE_GROUPS
from tracker.taxonomy.tracks import TRACKS, allowed_bands_for

# The companies the level decoder names. Many more have a reviewed ladder, and
# every one of those still bands its own postings; the decoder is a reference
# a person reads at a glance, so it stays the few ladders most people know.
DECODER_COMPANIES: tuple[str, ...] = (
    "google", "meta", "apple", "amazon", "netflix", "openai", "anthropic",
)


def uncounted_companies(
    entries: Iterable[RoleCatalog | CatalogEntry | InventoryEntry | CatalogPresence], followed: Iterable[str]
) -> dict[str, str]:
    """Followed companies the Profile's count leaves out, and why.

    `missing`: no catalog yet (never scanned, or its catalog is pending).
    `stale`: a catalog row written before the joint (`scope_cells`) existed,
    whose postings the joint cannot place; it clears on that company's next
    complete scan. One rule for the Profile's count and the Companies screen.
    `entries` are the rows the count reads (followed, not hidden, not pending).
    """
    catalogued: set[str] = set()
    stale: set[str] = set()
    for entry in entries:
        catalogued.add(entry.company)
        if (entry.band_counts or entry.count) and not entry.scope_cells:
            stale.add(entry.company)
    out = {slug: "missing" for slug in followed if slug not in catalogued}
    out.update({slug: "stale" for slug in stale})
    return out


def _tally_now(counts: dict | None) -> dict:
    """A stored band-keyed tally with each legacy band folded into its heir.
    A catalog row is rewritten by its company's next scan, and
    until then a "junior" key is the Entry rung: dropped, its roles would
    vanish from every count for a day."""
    out: dict = {}
    for band, count in (counts or {}).items():
        key = band_slug(band) if isinstance(band, str) else band
        if isinstance(count, int) and isinstance(out.get(key, 0), int):
            out[key] = out.get(key, 0) + count
        else:
            out.setdefault(key, count)
    return out


def _joint_now(joint: dict | None) -> dict:
    """`_tally_now` for a band x track tally."""
    out: dict = {}
    for band, tracks in (joint or {}).items():
        key = band_slug(band) if isinstance(band, str) else band
        if not isinstance(tracks, dict):
            out.setdefault(key, tracks)
            continue
        merged = out.setdefault(key, {})
        if isinstance(merged, dict):
            for track, count in tracks.items():
                if isinstance(count, int) and isinstance(merged.get(track, 0), int):
                    merged[track] = merged.get(track, 0) + count
    return out


class CatalogPresence(NamedTuple):
    """The part of a catalog row `uncounted_companies` reads: `scope_cells`
    says only whether the row has any, so the cells themselves stay unread."""

    company: str
    count: int
    band_counts: dict
    scope_cells: bool


def _is_counted(company: str, states: dict[str, TrackedCompany]) -> bool:
    """A catalog row the Profile's counts read: a followed company's, never a
    pending catalog. Hidden companies are left out by the query."""
    state = states.get(company)
    return state is not None and state.enabled and state.role_catalog_status != "pending"


class CatalogEntry(NamedTuple):
    """A counted catalog row with every column a count reads. Its example
    titles stay unread: no answer sends them."""

    role_group: str
    company: str
    count: int
    band_counts: dict
    band_track_counts: dict
    scope_cells: list
    domain_counts: dict
    domain_examples: dict


#: A `CatalogEntry`'s JSON columns, read as text and decoded in a worker
#: thread: decoding every row's cells is most of a catalog read, and on the
#: event loop it would hold every other request back.
_ENTRY_JSON = (
    RoleCatalog.band_counts,
    RoleCatalog.band_track_counts,
    RoleCatalog.scope_cells,
    RoleCatalog.domain_counts,
    RoleCatalog.domain_examples,
)


def _decoded(rows: list[tuple]) -> list[CatalogEntry]:
    return [
        CatalogEntry(
            role_group, company, count, json.loads(bands), json.loads(joint), json.loads(cells),
            json.loads(domains), json.loads(domain_examples),
        )
        for role_group, company, count, bands, joint, cells, domains, domain_examples in rows
    ]


async def counted_entries(
    session: AsyncSession, hidden: list[str], tracked: Iterable[TrackedCompany]
) -> list[CatalogEntry]:
    """The catalog rows every count on the Profile reads: followed companies
    only, never hidden ones, never a pending catalog. `tracked` is the
    caller's `get_tracked_companies` read."""
    states = {row.slug: row for row in tracked}
    stmt = select(
        RoleCatalog.role_group, RoleCatalog.company, RoleCatalog.count, *(column.cast(Text) for column in _ENTRY_JSON)
    )
    if hidden:
        stmt = stmt.where(RoleCatalog.company.notin_(hidden))
    rows = [tuple(row) for row in (await session.execute(stmt)).all() if _is_counted(row[1], states)]
    return await asyncio.to_thread(_decoded, rows)


async def counted_presence(
    session: AsyncSession, hidden: list[str], tracked: Iterable[TrackedCompany]
) -> list[CatalogPresence]:
    """`counted_entries` without the counts, for a reader that asks only which
    companies are catalogued and which catalogs predate the joint. `tracked`
    is the caller's `get_tracked_companies` read."""
    states = {row.slug: row for row in tracked}
    has_cells = func.coalesce(func.jsonb_array_length(RoleCatalog.scope_cells), 0) > 0
    stmt = select(RoleCatalog.company, RoleCatalog.count, RoleCatalog.band_counts, has_cells)
    if hidden:
        stmt = stmt.where(RoleCatalog.company.notin_(hidden))
    return [
        CatalogPresence(*row) for row in (await session.execute(stmt)).all() if _is_counted(row[0], states)
    ]


class CountState(NamedTuple):
    """What `company_count_state` answers."""

    not_counted: dict[str, str]
    unplaced: dict[str, int]
    unsorted: dict[str, int]
    #: When each company not counted as `stale` was last read; the inventory
    #: source only. Empty for the catalog.
    last_read: dict[str, datetime]


async def company_count_state(session: AsyncSession, hidden: list[str]) -> CountState:
    """Per followed company, what the Profile's count leaves out and why, and
    how many of its postings no answer can keep, by reason.
    One rule for the Profile and the Companies screen, from whichever source
    the counts come from."""
    tracked = await get_tracked_companies(session)
    if get_settings().scope_counts_source == "inventory":
        counts = await inventory_counts(session, tracked, hidden)
        return CountState(counts.not_counted(), counts.unplaced, counts.unsorted, counts.last_read)
    followed = [row for row in tracked if row.enabled]
    entries = await counted_presence(session, hidden, tracked)
    catalogued = {entry.company for entry in entries}
    return CountState(
        uncounted_companies(entries, (row.slug for row in followed)),
        {
            row.slug: row.role_catalog_unplaced
            for row in followed
            if row.slug in catalogued and (row.role_catalog_unplaced or 0) > 0
        },
        {
            row.slug: row.role_catalog_unsorted
            for row in followed
            if row.slug in catalogued and (row.role_catalog_unsorted or 0) > 0
        },
        {},
    )


class _Followed(NamedTuple):
    """A followed company's catalog state, as the counts read it."""

    slug: str
    status: str | None
    scanned: bool
    places: tuple[str, ...] | None
    unplaced: int | None


@dataclass(frozen=True)
class _CatalogCounts:
    """What a catalog read derives from its counted rows: the slow part of the
    read. One instance answers many reads, so nothing may change it."""

    #: Per role group: `total`, `band_counts`, `band_track_counts` and
    #: `joint_complete`. A group no counted row names is absent.
    groups: dict[str, dict]
    stage_counts: dict[str, int]
    unstated_count: int
    joint_counts_ready: bool
    #: Per track, from the rows' joints; empty unless `joint_counts_ready`.
    track_counts: dict[str, int]
    domain_counts: dict[str, int]
    domain_examples: dict[str, list[str]]
    #: The interned joint, without `cities`, which the read adds.
    scope_cells: dict


def _count_entries(
    entries: Sequence[CatalogEntry | InventoryEntry],
    followed: Sequence[_Followed],
    named_cities: frozenset[str],
    inventory: InventoryCounts | None,
) -> _CatalogCounts:
    """Every count the catalog derives from its rows. Pure, so it runs in a
    worker thread. `named_cities` are the only cities the joint keeps."""
    valid_bands = set(all_band_slugs())
    valid_tracks = {track.slug for track in TRACKS}

    def clean_joint(entry: CatalogEntry | InventoryEntry, *, unstated: bool = False) -> dict[str, dict[str, int]]:
        """Band x track counts; `unstated` also keeps the postings that state
        no level, for the readers that count postings rather than levels."""
        output: dict[str, dict[str, int]] = {}
        keep = valid_bands | {UNSTATED_LEVEL} if unstated else valid_bands
        for band, raw_tracks in _joint_now(entry.band_track_counts).items():
            if band not in keep or not isinstance(raw_tracks, dict):
                continue
            counts = {
                track: int(count)
                for track, count in raw_tracks.items()
                if track in valid_tracks and isinstance(count, int) and count > 0
            }
            if counts:
                output[band] = counts
        return output

    # Per-stage inventory totals for the career stage control. Counts are
    # pre-gate (whole market slice per stage).
    stage_counts: dict[str, int] = {}
    # Postings that state no level: counted apart, never as Mid.
    unstated_count = 0
    for entry in entries:
        for band, count in _tally_now(entry.band_counts).items():
            if band in valid_bands and isinstance(count, int) and count > 0:
                stage_counts[band] = stage_counts.get(band, 0) + count
            elif band == UNSTATED_LEVEL and isinstance(count, int) and count > 0:
                unstated_count += count

    # Only a company the user FOLLOWS, and only once it has been scanned, can
    # hold the joint counts back. An unfollowed company's capped catalog is not
    # the user's market, and a followed one nobody has scanned yet (some
    # sources are scanned only by a sync the user starts) has no rows to be
    # incomplete about; its card says so.
    # From the inventory, every entry carries its joint by construction.
    joint_counts_ready = inventory is not None or (all(
        not (entry.band_counts or entry.count) or bool(clean_joint(entry, unstated=True))
        for entry in entries
    ) and all(company.status == "ready" for company in followed if company.scanned))
    track_counts: dict[str, int] = {}
    if joint_counts_ready:
        track_counts = {track: 0 for track in valid_tracks}
        for entry in entries:
            for counts in clean_joint(entry, unstated=True).values():
                for track, count in counts.items():
                    track_counts[track] += count

    by_group: dict[str, list[CatalogEntry | InventoryEntry]] = {}
    for entry in entries:
        by_group.setdefault(entry.role_group, []).append(entry)
    groups: dict[str, dict] = {}
    for slug, group_entries in by_group.items():
        total_bands: dict[str, int] = {}
        total_joint: dict[str, dict[str, int]] = {}
        # Every company here can be priced by band and track: it has a joint,
        # or no posting at a counted level. The impact estimate is the
        # group's joint, so one company without it makes the estimate partial.
        joint_complete = True
        for entry in group_entries:
            bands = {
                band: int(count)
                for band, count in _tally_now(entry.band_counts).items()
                if band in valid_bands and isinstance(count, int) and count > 0
            }
            for band, count in bands.items():
                total_bands[band] = total_bands.get(band, 0) + count
            joint = clean_joint(entry)
            if not joint and bands:
                joint_complete = False
            for band, counts in joint.items():
                tracks = total_joint.setdefault(band, {})
                for track, count in counts.items():
                    tracks[track] = tracks.get(track, 0) + count
        groups[slug] = {
            "total": sum(total_bands.values()),
            "band_counts": {band: total_bands[band] for band in all_band_slugs() if band in total_bands},
            "band_track_counts": {band: total_joint[band] for band in all_band_slugs() if band in total_joint},
            "joint_complete": joint_complete,
        }

    # Domain-axis inventory: counts + employer-verbatim category evidence,
    # aggregated across visible companies' catalog rows. "unclassified" is a
    # first-class bucket — the fail-open volume must stay visible.
    domain_counts: dict[str, int] = {}
    domain_examples: dict[str, list[str]] = {}
    for entry in entries:
        for slug, count in (entry.domain_counts or {}).items():
            if isinstance(count, int) and count > 0:
                domain_counts[slug] = domain_counts.get(slug, 0) + count
        for slug, examples in (entry.domain_examples or {}).items():
            if not isinstance(examples, list):
                continue
            bucket = domain_examples.setdefault(slug, [])
            for example in examples:
                if isinstance(example, str) and example not in bucket and len(bucket) < 6:
                    bucket.append(example)

    # --- The scope joint, interned for the wire ----------------- #
    # Rows store slugs so each is readable alone; the payload ships five small
    # dictionaries and six-integer cells, so the payload stays small and the
    # dictionaries are the only place a slug appears more than once.
    #
    # `ready` deliberately does NOT ask whether every tracked company has been
    # scanned, unlike `joint_counts_ready` above. That gate is all-or-nothing,
    # so onboarding a single company switches the whole screen into its
    # band-only fallback until the next full sweep reaches every board.
    # Coverage is a different question from staleness, and
    # `missing_companies` answers it without blanking the counts we do have.
    cell_roles: dict[str, int] = {}
    cell_bands: dict[str, int] = {}
    cell_tracks: dict[str, int] = {}
    cell_locations: dict[tuple[str, ...], int] = {}
    cell_domains: dict[tuple[str, ...], int] = {}

    def intern(table: dict, key) -> int:
        if key not in table:
            table[key] = len(table)
        return table[key]

    merged_cells: dict[tuple[int, int, int, int, int], int] = {}
    followed_slugs = {company.slug for company in followed}
    uncounted = (
        inventory.not_counted() if inventory is not None
        else uncounted_companies(entries, followed_slugs)
    )
    stale_companies = {slug for slug, why in uncounted.items() if why == "stale"}
    for entry in entries:
        if (entry.band_counts or entry.count) and not entry.scope_cells:
            # A row written before this column existed, or by an older build.
            # It has postings we cannot place, so the joint would silently
            # under-count. A PARTIAL joint is a wrong number, not a smaller
            # one, so the screen falls back to the marginals and says which
            # question they answer. Named rather than reduced to a boolean:
            # this clears on that company's next COMPLETE scan, so a company
            # that stops scanning cleanly would otherwise hold the whole
            # screen back with nothing to point at.
            continue
        for cell in entry.scope_cells or []:
            if not isinstance(cell, dict):
                continue
            band, track = cell.get("band"), cell.get("track")
            band = band_slug(band) if isinstance(band, str) else band
            count = cell.get("count")
            locations = cell.get("locations")
            domains = cell.get("domains")
            # UNSTATED_LEVEL is a cell's level when the posting states none;
            # the browser gate passes it by the switch, never by a band.
            if (band not in valid_bands and band != UNSTATED_LEVEL) or track not in valid_tracks:
                continue
            if not isinstance(count, int) or count <= 0:
                continue
            if not isinstance(locations, list) or not isinstance(domains, list):
                continue
            # Cells record every city a posting names; only the tracked ones
            # travel, or the joint grows a location set per city in the world
            # that has roles.
            locations = [
                slug for slug in locations
                if not str(slug).startswith(CITY_PREFIX) or slug in named_cities
            ]
            key = (
                intern(cell_roles, entry.role_group),
                intern(cell_bands, band),
                intern(cell_tracks, track),
                intern(cell_locations, tuple(locations)),
                intern(cell_domains, tuple(domains)),
            )
            merged_cells[key] = merged_cells.get(key, 0) + count

    catalogued = inventory.counted if inventory is not None else {entry.company for entry in entries}
    scope_cells = {
        # A stale company's cells are left out above, so the joint of every
        # other company is exact. It never holds the whole screen back: it is
        # named in `stale_companies` and the screen says which company is not
        # counted yet.
        "ready": bool(merged_cells),
        "companies": sorted(catalogued - stale_companies),
        # Followed companies only: this answers "which of my companies are not
        # counted", and an unfollowed tracked row is not the user's market.
        "missing_companies": sorted(slug for slug, why in uncounted.items() if why == "missing"),
        "stale_companies": sorted(stale_companies),
        # Counted from a partial read only (inventory source).
        "partial_companies": sorted(slug for slug, why in uncounted.items() if why == "partial"),
        "roles": list(cell_roles),
        "bands": list(cell_bands),
        "tracks": list(cell_tracks),
        "location_sets": [list(key) for key in cell_locations],
        "domain_sets": [list(key) for key in cell_domains],
        "cells": [
            [role, band, track, location, domain, count]
            for (role, band, track, location, domain), count in sorted(merged_cells.items())
        ],
        "scanned_places": {
            company.slug: list(company.places)
            for company in followed
            if company.slug in catalogued and company.places is not None
        },
        "unplaced": sum(inventory.unplaced.values()) if inventory is not None else sum(
            company.unplaced or 0 for company in followed if company.slug in catalogued
        ),
    }
    return _CatalogCounts(
        groups, stage_counts, unstated_count, joint_counts_ready, track_counts,
        domain_counts, domain_examples, scope_cells,
    )


#: Moves with any write to `role_catalog`: replacing a company's catalog
#: deletes its rows and inserts new ones (the count, the newest id), and an
#: update in place gives a row a new `xmin`.
_CATALOG_VERSION = text("SELECT count(*), max(id), sum(xmin::text::bigint) FROM role_catalog")

_reused: tuple[tuple, _CatalogCounts] | None = None


def forget_catalog_counts() -> None:
    global _reused
    _reused = None


async def _catalog_counts(
    session: AsyncSession,
    hidden: list[str],
    tracked: Sequence[TrackedCompany],
    named_cities: frozenset[str],
    inventory: InventoryCounts | None,
) -> _CatalogCounts:
    """The counts from the rows. From the catalog they are reused within one
    process while the rows and everything they are read with are unchanged,
    so a read between two scans' catalog writes loads no row."""
    global _reused
    followed = [
        _Followed(
            row.slug,
            row.role_catalog_status,
            row.role_catalog_scanned_at is not None,
            None if row.role_catalog_places is None else tuple(row.role_catalog_places),
            row.role_catalog_unplaced,
        )
        for row in tracked
        if row.enabled
    ]
    if inventory is not None:
        return await asyncio.to_thread(_count_entries, inventory.entries, followed, named_cities, inventory)
    version = tuple((await session.execute(_CATALOG_VERSION)).one())
    key = (version, tuple(followed), tuple(sorted(hidden)), named_cities)
    reused = _reused
    if reused is not None and reused[0] == key:
        return reused[1]
    entries = await counted_entries(session, hidden, tracked)
    counts = await asyncio.to_thread(_count_entries, entries, followed, named_cities, None)
    _reused = (key, counts)
    return counts


async def build_scope_catalog(
    session: AsyncSession, hidden: list[str], extra_cities: Iterable[str] = ()
) -> dict:
    """The catalog. `extra_cities` are cities a person is answering with and
    has not saved: the stored cells keep every
    city a posting names, so naming one here prices it at once instead of
    after the save. Anything that is not a known city is ignored."""
    # The four opt-in axes in one read: what is on, and what each has gained
    # since the user last saved it.
    read = await read_opt_in_axes(session)
    axes = read.axes
    enabled_roles, new_roles = axes[ENABLED_ROLES_KEY].enabled, axes[ENABLED_ROLES_KEY].new
    enabled_bands, new_bands = axes[ENABLED_BANDS_KEY].enabled, axes[ENABLED_BANDS_KEY].new
    enabled_tracks, new_tracks = axes[ENABLED_TRACKS_KEY].enabled, axes[ENABLED_TRACKS_KEY].new
    enabled_locations, new_locations = (
        axes[ENABLED_LOCATIONS_KEY].enabled, axes[ENABLED_LOCATIONS_KEY].new,
    )
    enabled_domains = await get_enabled_domains(session)
    excluded_domains = read.excluded
    role_answers = read.answers
    excepted_places = read.excepted_places
    # The cities a person named, included or excepted: the ones
    # the tree lists and the cells keep.
    named_locations = set(enabled_locations) | excepted_places | {
        slug for slug in canonical_location_slugs(extra_cities) if slug.startswith(CITY_PREFIX)
    }
    tracked = await get_tracked_companies(session)
    # Counts from the postings a save promotes, when the switch
    # (`scope_counts_source`) says so. Every line below reads its entries as it reads
    # `role_catalog` rows.
    inventory: InventoryCounts | None = (
        await inventory_counts(session, tracked, hidden)
        if get_settings().scope_counts_source == "inventory"
        else None
    )

    # Known-job counts per location group (facets-style unnest over the stored
    # matches). Deliberately not gated on in_scope: the user is configuring that
    # gate here, so disabled groups must still show what they would include.
    loc_sql = "SELECT lg, count(*) FROM jobs, unnest(location_groups) lg WHERE status='open'"
    loc_params: dict = {}
    if hidden:
        loc_sql += " AND company <> ALL(:hidden)"
        loc_params["hidden"] = hidden
    loc_sql += " GROUP BY lg"
    location_counts = (
        # The same rows as the joint, not every open job.
        dict(inventory.location_counts) if inventory is not None else {
            str(slug): int(count)
            for slug, count in (await session.execute(text(loc_sql), loc_params)).all()
        }
    )
    # Which tracked companies cannot be asked about each region. Derived from the
    # connector manifests, not from observed counts: a region nobody queries and
    # a region with no roles both come back empty, so only the declaration can
    # tell them apart.
    # Resolved once per distinct ADAPTER, not once per company: coverage is a
    # property of the connector, many companies share one adapter, and the
    # screen reads it on every draw of the tree.
    # Cities the user tracks are placed like any group: listed after
    # the taxonomy, with the coverage their country or metro has.
    tracked_cities = [
        slug for slug in canonical_location_slugs(named_locations) if slug.startswith(CITY_PREFIX)
    ]
    location_nodes: list[tuple[str, dict]] = [
        *LOCATION_GROUPS.items(),
        *((slug, node) for slug in tracked_cities if (node := location_node(slug)) is not None),
    ]
    gaps_by_adapter: dict[str, list[str]] = {}
    uncovered_by: dict[str, list[str]] = {}
    for row in tracked:
        adapter = getattr(row, "adapter", None)
        if not adapter or not getattr(row, "enabled", True):
            continue
        if adapter not in gaps_by_adapter:
            gaps_by_adapter[adapter] = adapter_location_gaps(adapter, [slug for slug, _ in location_nodes])
        for slug in gaps_by_adapter[adapter]:
            uncovered_by.setdefault(slug, []).append(row.slug)
    for slugs in uncovered_by.values():
        slugs.sort()

    # Every count on the screen is over the companies the user FOLLOWS: the
    # walk's 100% is the roles the radar can actually show, so a number never
    # includes a company switched off in Settings, even one whose old catalog
    # is still stored.
    counts = await _catalog_counts(
        session,
        hidden,
        tracked,
        frozenset(slug for slug in named_locations if str(slug).startswith(CITY_PREFIX)),
        inventory,
    )
    if counts.joint_counts_ready:
        track_counts = counts.track_counts
    else:
        # Joint counts are not ready until the inventory refresh writes them:
        # use current open jobs for the toggle labels and mark impact math
        # unavailable.
        track_count_stmt = select(Job.track, func.count()).where(Job.status == "open")
        if hidden:
            track_count_stmt = track_count_stmt.where(Job.company.notin_(hidden))
        track_counts = {
            str(track): int(count)
            for track, count in (
                await session.execute(track_count_stmt.group_by(Job.track))
            ).all()
        }
    # The corporate-level decoder is the reviewed guide ladders of the
    # reference companies, whatever the person follows. Per-level pay rows
    # (company_comp_level) feed comp and never this table.
    guides = stage_decoder()
    decoder = {company: guides[company] for company in DECODER_COMPANIES if company in guides}

    role_by_slug = {group.slug: group for group in ROLE_GROUPS}

    def group_out(slug: str) -> dict:
        group = role_by_slug[slug]
        tallies = counts.groups.get(slug)
        return {
            "slug": group.slug,
            "default_enabled": group.default_enabled,
            "selected": group.slug in enabled_roles,
            "new": group.slug in new_roles,
            "enabled": group.slug in enabled_roles,
            **(tallies or {"total": 0, "band_counts": {}, "band_track_counts": {}, "joint_complete": True}),
        }

    return {
        "scope_cells": {**counts.scope_cells, "cities": tracked_cities},
        "settings": {
            "enabled_role_groups": [g.slug for g in ROLE_GROUPS if g.slug in enabled_roles],
            "enabled_seniority_bands": [lvl.slug for lvl in LEVELS if lvl.slug in enabled_bands],
            "enabled_role_tracks": [t.slug for t in TRACKS if t.slug in enabled_tracks],
            "enabled_location_groups": canonical_location_slugs(enabled_locations),
            "enabled_domain_groups": [
                g.slug for g in DOMAIN_GROUPS if g.slug in enabled_domains
            ],
            "excluded_domain_groups": [
                g.slug for g in DOMAIN_GROUPS if g.slug in excluded_domains
            ],
            "role_answers": dump_answers(role_answers),
            "excluded_location_groups": canonical_location_slugs(excepted_places),
            "include_unstated_level": read.include_unstated_level,
        },
        "domains": [
            {
                "slug": group.slug,
                "selected": group.slug in enabled_domains,
                # Pre-gate inventory (rows can carry several worlds, so counts
                # overlap across domains — they answer "what would turning this
                # off remove", not "how do these sum").
                "count": counts.domain_counts.get(group.slug, 0),
                # The employer's own category text the classifier read — the
                # most self-explanatory evidence the UI can show.
                "examples": counts.domain_examples.get(group.slug, []),
                "kind": group.kind,
            }
            for group in DOMAIN_GROUPS
        ],
        "unclassified_domain_count": counts.domain_counts.get(UNCLASSIFIED_KEY, 0),
        "locations": [
            {
                "slug": slug,
                "display": group["display"],
                "default_enabled": bool(group.get("enabled")),
                "selected": slug in enabled_locations,
                "new": slug in new_locations,
                "count": location_counts.get(slug, 0),
                # Nested axis: the client renders a parent -> child tree.
                # `kind` = "metro"|"country"|"region"; `parent` = the group this
                # nests under (metro->country, country->region), or None if top-level.
                "kind": group.get("kind", "country"),
                "parent": group.get("parent"),
                # Tracked companies whose source cannot be ASKED about this
                # region. Empty for whole-board sources, which return
                # every region in one response. Non-empty means selecting this
                # group yields nothing from those companies — and an unasked
                # region looks exactly like one with no open roles, so the count
                # beside it can never reveal the difference.
                "uncovered_by": uncovered_by.get(slug, []),
                # Shown before "show all" inside its region. Display-only (it
                # never affects what a posting matches); it exists because
                # every country of a region in one list is not a list anyone reads.
                # Metros and regions are always prominent; countries carry the
                # flag from the country table.
                "prominent": (
                    group.get("kind") != "country"
                    or getattr(BY_SLUG.get(slug), "prominent", False)
                ),
            }
            for slug, group in location_nodes
        ],
        "levels": [
            {
                "slug": level.slug,
                "order": level.order,
                "default_enabled": level.default_enabled,
                "selected": level.slug in enabled_bands,
                "new": level.slug in new_bands,
                # Pre-gate market inventory at this stage (all position types).
                "count": counts.stage_counts.get(level.slug, 0),
                # Per-company grade decode for this stage. Each value is a cell:
                # {"company_wide": "L5"} or {"per_track": {"technical": "ICT4"}}.
                # The client resolves it against the selected tracks, falling
                # non-technical roles back to the seniority word. A reference,
                # so every reference company shows whether followed or not.
                "decoder": {
                    company: labels[level.slug]
                    for company, labels in decoder.items()
                    if level.slug in labels
                },
            }
            for level in LEVELS
        ],
        "tracks": [
            {
                "slug": track.slug,
                "order": track.order,
                "default_enabled": track.default_enabled,
                "selected": track.slug in enabled_tracks,
                "new": track.slug in new_tracks,
                "count": track_counts.get(track.slug, 0),
                # Seniority tiers this function realistically occupies; the wizard
                # disables the rest (union across selected tracks).
                "allowed_bands": allowed_bands_for(track.slug),
            }
            for track in TRACKS
        ],
        "joint_counts_ready": counts.joint_counts_ready,
        "unstated_level_count": counts.unstated_count,
        "categories": [
            {
                "slug": category.slug,
                "groups": [group_out(slug) for slug in category.role_groups],
            }
            for category in CATEGORY_GROUPS
        ],
        "companies": [
            {
                "slug": row.slug,
                "display": row.display,
                "enabled": bool(row.enabled),
                "role_catalog_status": row.role_catalog_status,
                "role_catalog_scanned_at": row.role_catalog_scanned_at,
                "role_catalog_error": row.role_catalog_error,
            }
            for row in tracked
        ],
    }
