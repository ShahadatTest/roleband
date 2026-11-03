"""The shapes one source collection travels in.

`ScanMode` is how much authority a collection carries; `RunLookups` is what the
run read before collecting; `SourceCollection` is what collection hands
persistence; `SourceStats` is the per-source record both fill in and the run
stores; `judge_listing` is how a read that ended fills in its listing facts.
No outcome vocabulary lives here: a source's outcome is always
`connectors.recipes.outcome.classify_source_outcome` over these stats.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING, NotRequired, TypedDict

from tracker.enrich.inventory import InventoryRow
from tracker.schema import EnrichedJob
from tracker.taxonomy.role_catalog import CatalogTallies

if TYPE_CHECKING:
    from tracker.company_store import ScanTarget


class ScanMode(StrEnum):
    """Authority of one source collection.

    Discovery is deliberately non-authoritative even if a connector happens to
    enumerate its whole board before the item cap. Only reconciliation may
    close by absence or advance binding health.
    """

    DISCOVERY = "discovery"
    RECONCILE = "reconcile"
    REPAIR = "repair"
    SHADOW = "shadow"


class SourceStats(TypedDict):
    """One source's record, stored as built: `scrape_runs.per_source[company]`
    and `scrape_source_runs.stats` (JSONB), read back by health, retry, tuning
    and the sync diagnostics.

    A plain dict at runtime, so nothing stands between what is typed here and
    what is stored. Keys arrive in three stages; the later ones are
    `NotRequired` because a collection that never reached a stage never set
    them. `tests/test_pipeline_lifecycle.py` pins the stored key set and value
    types per outcome: adding, renaming or retyping a key is a stored-data
    change, never a refactor.
    """

    # At scan open (`empty_stats`, whose comments say which bounds are ours).
    scanned: int
    kept: int
    new: int
    closed: int
    errors: list[str]
    capped: bool
    bounded: bool
    truncated: bool
    blocked: bool
    suspended: bool
    suspended_seconds: float
    unattempted: bool
    uncovered_locations: list[str]
    detail_deferred: int
    # When the scan ends (`collection.collect_source`).
    duration_seconds: NotRequired[float]
    records_dropped: NotRequired[int]
    listing_invalidated: NotRequired[bool]
    #: The board proved it lists nothing (`SchemaDriftDetector.board_empty`).
    empty_proven: NotRequired[bool]
    #: The board root answered 404/410 (`SchemaDriftDetector.board_missing`).
    board_missing: NotRequired[bool]
    queries: NotRequired[list[dict]]
    #: What the reads cost (`platform.transport_tally`): completed requests,
    #: retries, response bytes, each None when no read reached a shared
    #: transport; and the latest moment a `Retry-After` named, ISO 8601.
    requests: NotRequired[int | None]
    retries: NotRequired[int | None]
    bytes_received: NotRequired[int | None]
    retry_after_until: NotRequired[str | None]
    policy_reason: NotRequired[str]
    policy_provider: NotRequired[str]
    #: Why a company was never started (`deferred_collection`): its lane lost
    #: the network. Ours, like `unattempted` it rides on.
    deferred_reason: NotRequired[str]
    #: No job site accepted a connection when this source failed, or when its
    #: lane reached it: our outage, never the source's (`outage`).
    offline: NotRequired[bool]
    # While persisting (`run_persistence.persist_source`).
    #: Inventory rows written or touched, and marked gone; an
    #: inventory write that failed records why and costs the source nothing else.
    inventory_rows: NotRequired[int]
    inventory_gone: NotRequired[int]
    inventory_error: NotRequired[str]
    closure_scope: NotRequired[str]
    closure_eligible: NotRequired[bool]
    drift: NotRequired[list[dict]]
    list_complete: NotRequired[bool]
    outcome: NotRequired[str]
    binding_activation: NotRequired[str]
    #: Whether this run granted its withheld binding closure authority; set
    #: with `binding_activation`.
    binding_activated: NotRequired[bool]


def empty_stats() -> SourceStats:
    return {
        "scanned": 0,
        "kept": 0,
        "new": 0,
        "closed": 0,
        "errors": [],
        # The three bounds *we* impose (operator cap, time ceiling, page
        # ceiling), kept alongside each other so the outcome derivation stays a
        # pure read of this dict.
        "capped": False,
        "bounded": False,
        "truncated": False,
        # The one flag here that is the SOURCE's doing, not ours: the breaker
        # identified a uniform WAF-style refusal.
        "blocked": False,
        # Ours as well, though not chosen: the host was suspended mid-scan and
        # killed its own sockets. Health-inert like the three above.
        "suspended": False,
        "suspended_seconds": 0.0,
        # Ours again, and the strongest of the lot: no connector in this build
        # could serve the company, so nothing was ever asked of the source.
        # The only flag that stops health transitioning at all.
        "unattempted": False,
        # Tracked location groups this source has no query for. Ours, and unlike
        # every flag above it is not about how the scan *went*: it names the
        # questions the scan never asked. Health-inert by design: the source
        # answered everything it was asked, so punishing the binding would be
        # blaming it for our manifest. It reaches the user instead.
        "uncovered_locations": [],
        # Kept rows whose description the discovery detail budget deferred. Also
        # ours, also health-inert; the backfill pass drains them. Counted so a
        # cap can never read as complete coverage.
        "detail_deferred": 0,
    }


def judge_listing(stats: SourceStats, adapter: object | None, *, cut: bool) -> bool:
    """Judge a listing read that has ended: write the listing facts the outcome
    derivation reads into `stats`, and answer whether the listing is complete.

    One judgement for the collector (`collection.collect_source`) and the
    directory read (`directory_sweep.check_company`). `cut`: something other
    than the board's own
    end stopped the read or voids it as a whole listing: a bound of ours, a
    stall, an operator cap, and, for the collector alone, a host suspension
    (a gap it cannot see inside is no listing to close against; the directory
    only counts).

    Only a read that reached its natural end with no error and nothing left
    unattempted is judged by its row count (`settle_listing`, the zero-row
    rule), and only such a read can be complete: not truncated by a
    page ceiling, and complete by the adapter's own account (lost pages and
    lost rows). `adapter` is duck-typed (test fakes, recipe
    bridges): one with no drift recorder is judged by the rest.
    """
    drift = getattr(adapter, "drift", None)
    ended = adapter is not None and not (stats["errors"] or stats["unattempted"] or cut)
    if ended and drift is not None:
        drift.settle_listing(scanned=stats["scanned"])
    stats["truncated"] = bool(getattr(adapter, "truncated", False))
    stats["records_dropped"] = drift.records_dropped if drift is not None else 0
    stats["listing_invalidated"] = bool(drift is not None and drift.listing_invalidated)
    # The adapter's positive proof that the board lists nothing.
    stats["empty_proven"] = bool(drift is not None and drift.empty_proven)
    # The board's own address said there is no such board.
    stats["board_missing"] = bool(drift is not None and getattr(drift, "board_gone", False))
    return ended and not stats["truncated"] and (drift is None or drift.listing_complete)


@dataclass(frozen=True)
class SourceCost:
    """What one company's last complete scan cost and found.

    ``seconds`` is its learned scan time, ``kept`` the open in-scope postings it
    holds. Only the ORDER of work reads these; no bound does.
    """

    seconds: float
    kept: int


@dataclass(frozen=True)
class SourceLookups:
    """What the run read about one company before collecting it
    (`RunLookups.for_company`).

    ``fresh_description_keys``: rows whose stored description is recent enough
    not to fetch again. ``known_places``: places held for its open postings, by
    req_id. ``held_dates``: every held posting's (first_posted_at, first_seen)
    by dedupe key; None when the run loaded none. ``page_budgets`` and
    ``source_budget``: its learned per-query page ceilings and time budget,
    None where the adapter's own constant and the run's ceiling stand.
    ``existing_open_keys``: the discovery frontier, the keys it holds open.
    """

    fresh_description_keys: frozenset[str] = frozenset()
    known_places: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    held_dates: Mapping[str, tuple[datetime | None, datetime]] | None = None
    page_budgets: Mapping[str, int] | None = None
    source_budget: float | None = None
    existing_open_keys: frozenset[str] = frozenset()


@dataclass(frozen=True)
class AskedCompany:
    """A company a person asked for while a run reads (Scan now): it joins the
    run at the front of its lane, with what the run read about it."""

    company: str
    target: ScanTarget
    lookups: SourceLookups


@dataclass(frozen=True)
class RunLookups:
    """What a run reads from the database before collecting, by company.

    Read once per run (`pipeline.run_pipeline`), so the hot path never queries
    per job; each company is collected with its own share (`for_company`).
    The loaders: `repo.load_fresh_description_keys`, `repo.load_known_places`,
    `repo.load_held_dates`, `repo.load_open_keys` (discovery only) and
    `tuning_pass.load_page_budgets`, `load_source_budgets`, `load_source_costs`.
    ``costs`` orders the run's lanes (`collection.collector_lanes`).
    """

    fresh_description_keys: frozenset[str] = frozenset()
    known_places: Mapping[str, Mapping[str, tuple[str, ...]]] = field(default_factory=dict)
    held_dates: Mapping[str, Mapping[str, tuple[datetime | None, datetime]]] | None = None
    page_budgets: Mapping[str, Mapping[str, int]] = field(default_factory=dict)
    source_budgets: Mapping[str, float] = field(default_factory=dict)
    existing_open_keys: Mapping[str, frozenset[str]] = field(default_factory=dict)
    costs: Mapping[str, SourceCost] = field(default_factory=dict)

    def for_company(self, slug: str) -> SourceLookups:
        return SourceLookups(
            fresh_description_keys=self.fresh_description_keys,
            known_places=self.known_places.get(slug, {}),
            # `{}` for a company with no held rows, so its scan keeps no
            # `held_reads`; None only when the run loaded none.
            held_dates=None if self.held_dates is None else self.held_dates.get(slug, {}),
            page_budgets=self.page_budgets.get(slug),
            source_budget=self.source_budgets.get(slug),
            existing_open_keys=self.existing_open_keys.get(slug, frozenset()),
        )


@dataclass
class SourceCollection:
    """Network/enrichment output for one source; DB writes stay in the pipeline."""

    company: str
    enriched: list[EnrichedJob]
    seen_keys: set[str]
    stats: SourceStats
    drift: list[dict]
    scope_by_key: dict[str, bool] = field(default_factory=dict)
    catalog: CatalogTallies = field(default_factory=dict)
    list_complete: bool = False
    #: The adapter this company's board moved to, when a route-family adapter
    #: detected the move; the pipeline records it on the company.
    route: str | None = None
    #: What the catalog could not count or was not asked: postings
    #: with no recognised place, postings with a place but no family (counted
    #: apart), and the location groups a source that lists
    #: only asked-for places was queried for (None: the whole board).
    catalog_unplaced: int = 0
    catalog_unsorted: int = 0
    catalog_places: list[str] | None = None
    #: Every row the scan read, in scope or not, by dedupe key.
    inventory: dict[str, InventoryRow] = field(default_factory=dict)
    #: What the scan read for each HELD posting it judged out of scope, by
    #: dedupe key: the inventory's allowlist, kept whether or not
    #: the inventory is on. Such a posting is not written, so without this its
    #: stored places, title and team stay the last in-scope read's, and the writer's
    #: re-projection would admit it again from them (`repo.refresh_held_reads`).
    held_reads: dict[str, InventoryRow] = field(default_factory=dict)


OFFLINE_ERROR = "NetworkUnreachable: no job site accepted a connection"


def deferred_collection(company: str) -> SourceCollection:
    """A company its lane never started: the lane's last read failed while no
    job site accepted a connection.

    `unattempted`, so health and provider pressure stay untouched and the next
    tick reads it. Recorded as a failure it would put the whole provider
    into backoff for an outage on our side.
    """
    stats = empty_stats()
    stats["unattempted"] = True
    stats["errors"].append(OFFLINE_ERROR)
    stats["offline"] = True
    stats["deferred_reason"] = "no job site accepted a connection before this company started"
    return SourceCollection(company, [], set(), stats, [])


def failed_collection(company: str, error: str) -> SourceCollection:
    """A source that produced nothing, with the reason recorded.

    Used for the bounds enforced *outside* ``collect_source`` (the per-source
    backstop and a crashed lane), where the collection itself is lost. Rows
    the source streamed before the cut are already written, and the run's
    writer counts them as kept.
    """
    stats = empty_stats()
    stats["errors"].append(error)
    return SourceCollection(company, [], set(), stats, [])
