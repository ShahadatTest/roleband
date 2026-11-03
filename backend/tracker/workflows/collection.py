"""Source collection: fetch, filter, hydrate and enrich, holding no DB session.

`collect_sources` runs distinct backends concurrently and each backend's
companies serially, and bounds every company independently; its docstring names the three bounds and what each one
firing means. Nothing bounds the run as a whole: a slow network makes it longer,
never smaller. `collect_source` records why a source stopped and keeps the pages
already fetched. Nothing here writes: persistence receives the
`SourceCollection`s this returns.
"""

from __future__ import annotations

import asyncio
import functools
import logging
import time
from collections import deque
from collections.abc import Awaitable, Callable, Mapping
from typing import TYPE_CHECKING

from tracker.config import get_settings
from tracker.connectors import (
    BaseAdapter,
    BreakerPool,
    RateLimiterPool,
    UnknownAdapterError,
    build_adapter,
    structure_job_detail,
)
from tracker.connectors.recipes.outcome import classify_source_outcome
from tracker.enrich.comp import EstimateSet
from tracker.enrich.enricher import (
    ScopeFilter,
    annotate,
    build_enriched,
    passes_filters,
    passes_filters_but_level,
    reread_level,
    rule_excluded,
)
from tracker.enrich.inventory import InventoryRow, inventory_row
from tracker.enrich.level_mapper import LevelReading, level_awaits_read
from tracker.platform.breaker import CircuitOpenError
from tracker.platform.clock import (
    BOUNDED,
    STALLED,
    SourceClock,
    SuspensionMonitor,
    bound_fired,
)
from tracker.platform.http import RetryDeadlineExceeded
from tracker.platform.transport_tally import tally_transport
from tracker.platform.util import describe_exception
from tracker.provider_pacing import HostScope, pacing_for
from tracker.schema import EnrichedJob, RawJob
from tracker.scope.catalog_store import scanned_places
from tracker.source_policy import CollectionPolicyDenied, collection_access
from tracker.taxonomy.role_catalog import CatalogTallies, add_to_catalog, catalog_drop_reason
from tracker.workflows import outage
from tracker.workflows.collection_types import (
    AskedCompany,
    RunLookups,
    ScanMode,
    SourceCollection,
    SourceCost,
    SourceLookups,
    SourceStats,
    deferred_collection,
    empty_stats,
    failed_collection,
    judge_listing,
)

if TYPE_CHECKING:
    from tracker.company_store import ScanTarget

logger = logging.getLogger(__name__)

# How long past its cooperative deadline a source gets to unwind before the
# backstop cancels it (losing what it had not yet streamed), and how long a
# cancelled source then gets to close before its lane moves on without it.
_SOURCE_BUDGET_GRACE_SECONDS = 15.0


def _tallied[**P](
    collect: Callable[P, Awaitable[SourceCollection]],
) -> Callable[P, Awaitable[SourceCollection]]:
    """The collection with what its reads cost in its stats (`platform.transport_tally`)."""

    @functools.wraps(collect)
    async def tallied(*args: P.args, **kwargs: P.kwargs) -> SourceCollection:
        with tally_transport() as tally:
            collection = await collect(*args, **kwargs)
        collection.stats.update(tally.stats())  # type: ignore[typeddict-item]
        return collection

    return tallied


@_tallied
async def collect_source(
    company: str,
    cfg: ScanTarget,
    scope: ScopeFilter,
    resolver: EstimateSet,
    *,
    max_list: int | None,
    hydrate: bool,
    limiter_pool: RateLimiterPool,
    breaker_pool: BreakerPool | None = None,
    deadline: float | SourceClock | None = None,
    adapter_factory: Callable[..., BaseAdapter] = build_adapter,
    scan_mode: ScanMode = ScanMode.RECONCILE,
    lookups: SourceLookups | None = None,
    on_row: Callable[[EnrichedJob], None] | None = None,
) -> SourceCollection:
    """Fetch, filter, hydrate, and enrich one source without touching the DB.

    ``deadline`` is handed to the adapter's transport rather than enforced by
    cancelling this coroutine: past it the retry loops raise instead of sleeping,
    so the ``except`` below records the source while **keeping the pages already
    fetched**. Cancelling would discard them (see ``asyncio.wait_for``'s
    return-value semantics).

    A `SourceClock` additionally distinguishes *why* the source stopped. Silence
    (`stalled`) is the source's own pathology and reaches binding health; our own
    ceiling (`exhausted`) does not, because a threshold we picked is not evidence
    about the source. A bare float is a single bound.

    ``on_row`` receives each kept row the moment it is built, so the
    run's one writer can store it while the listing is still being read. An
    in-memory hand-off: no await, no DB, never allowed to fail the collection.
    The row stays in the returned collection either way.

    ``lookups`` is what the run read about this company before collecting
    (`SourceLookups`; none when omitted). Its ``held_dates`` are put on each
    `RawJob` before its level is read, so a posting that states no date reads
    its pay grade for the year relevel does (`level_mapper.level_date`). They
    also name the held postings whose out-of-scope read is kept in
    `held_reads`; None keeps every out-of-scope read, for the caller to match.
    """
    if lookups is None:
        lookups = SourceLookups()
    started = time.monotonic()
    # Watches for the host going down underneath this source. Started next to
    # `started` because it measures the same span: the two clocks agree until
    # something suspends the process, and their disagreement is that suspension.
    suspension = SuspensionMonitor(
        threshold_seconds=get_settings().scraper_host_suspension_seconds
    )
    stats = empty_stats()
    # Detail requests this source may spend. A probe runs up to 4x/day, so an
    # unbounded per-job fetch inside one would multiply with the cadence; a
    # reconcile is the authoritative pass and is bounded by the listing itself.
    detail_budget = (
        get_settings().scraper_discovery_detail_budget
        if scan_mode is ScanMode.DISCOVERY
        else None
    )
    detail_fetches = 0
    enriched_jobs = []
    seen_keys: set[str] = set()
    scope_by_key: dict[str, bool] = {}
    catalog: CatalogTallies = {}
    catalog_unplaced = 0
    catalog_unsorted = 0
    inventory: dict[str, InventoryRow] = {}
    held_reads: dict[str, InventoryRow] = {}
    keep_inventory = get_settings().inventory_enabled
    adapter: BaseAdapter | None = None
    route: str | None = None
    cap_fired = False
    stalled = False
    bounded = False

    async def read_detail(raw: RawJob) -> bool:
        """One detail read of `raw` within this source's budget; False when
        the budget is spent and the read was deferred."""
        nonlocal detail_fetches
        assert adapter is not None
        if detail_budget is not None and detail_fetches >= detail_budget:
            # A probe stays a probe. A kept row still persists (blank) and the
            # backfill pass drains it; counted, because a cap nobody can see
            # reads as complete coverage.
            stats["detail_deferred"] += 1
            return False
        detail_fetches += 1
        try:
            await adapter.hydrate(raw)
        except (CircuitOpenError, RetryDeadlineExceeded):
            # The source's, not the posting's: the handlers below
            # record a refusing source as blocked and a bound as ours.
            raise
        except Exception as exc:  # noqa: BLE001 - detail is best effort
            adapter.drift.note("hydrate error", error=describe_exception(exc), req=raw.req_id)
        return True

    def structure_detail(raw: RawJob) -> None:
        """Structure what a detail read left on `raw` (or the listing carried),
        then drop the payload."""
        assert adapter is not None
        structure_job_detail(raw, adapter.drift, payload=raw.detail_payload, source=cfg["adapter"])
        raw.detail_payload = None

    async def retain(raw, *, network: bool) -> None:
        nonlocal catalog_unplaced, catalog_unsorted
        key = raw.dedupe_key()
        if key in seen_keys:
            return
        seen_keys.add(key)
        held = (lookups.held_dates or {}).get(key)
        if held is not None:
            raw.held_first_posted_at, raw.held_first_seen = held
        ann = annotate(raw)

        def note_inventory() -> None:
            # Every posting read, with the level the scan decided on: written
            # before the scope check and again after any re-read, or promotion
            # would decide on the title's guess the page overruled.
            if keep_inventory:
                inventory[key] = inventory_row(raw, ann)

        note_inventory()
        if not add_to_catalog(catalog, raw, ann):
            # Why it was dropped, counted apart.
            if catalog_drop_reason(ann) == "unsorted":
                catalog_unsorted += 1
            else:
                catalog_unplaced += 1
        excluded = rule_excluded(raw, scope.company_exclusions)
        in_scope = passes_filters(ann, scope) and not excluded
        # Read before deciding: a posting
        # that fails the scope only on a level we GUESSED from its title (none
        # stated, "Product Manager", "Engineering Manager") is read in full
        # first, within the same detail budget, and decided on what it states
        # (its range, a printed rung). Only where a read can state one
        # (`level_awaits_read`): elsewhere the page would change nothing. A
        # row we already hold is re-read from its stored text by
        # `levels_backfill`, never fetched again here.
        read_for_level = False
        if (
            not in_scope and not excluded and network and hydrate
            and key not in lookups.fresh_description_keys
            and not (scan_mode is ScanMode.DISCOVERY and key in lookups.existing_open_keys)
            and level_awaits_read(raw, LevelReading(ann.band, ann.confidence, ann.basis), ann.family)
            and passes_filters_but_level(ann, scope)
        ):
            read_for_level = await read_detail(raw)
            if read_for_level:
                structure_detail(raw)
                ann = reread_level(raw, ann)
                note_inventory()
                in_scope = passes_filters(ann, scope)
        scope_by_key[key] = in_scope
        if not in_scope:
            if held is not None or lookups.held_dates is None:
                held_reads[key] = inventory_row(raw, ann)
            return
        stats["kept"] += 1
        # Frontier filter before detail/comp/enrichment. A discovery
        # probe still scans and records listing coverage, but existing
        # open roles trigger no detail or secondary-provider requests
        # and cannot create canonical-field churn.
        if scan_mode is ScanMode.DISCOVERY and key in lookups.existing_open_keys:
            return
        if not read_for_level:
            # Hydration follows the JOB's need, not the run's mode: a
            # run-level flag cannot express "this row has no text", and
            # would withhold the description from exactly the rows
            # discovery persists (the new ones) while reconcile re-fetches
            # descriptions it already holds. Structured whether or not it
            # was read: a listing can carry the description.
            if network and hydrate and key not in lookups.fresh_description_keys:
                await read_detail(raw)
            structure_detail(raw)
        # The detail read can state the posting's base range, which names the
        # rung a bare title did not. The scope decision above read the
        # title alone, so a moved level is decided again: a row the range puts
        # outside the scope is recorded out of scope, never stored as kept.
        reread = reread_level(raw, ann)
        if reread is not ann:
            ann = reread
            note_inventory()
            if not passes_filters(ann, scope):
                scope_by_key[key] = False
                stats["kept"] -= 1
                if held is not None or lookups.held_dates is None:
                    held_reads[key] = inventory_row(raw, ann)
                return
        enriched = await build_enriched(raw, ann, resolver if network else None)
        enriched_jobs.append(enriched)
        if on_row is not None:
            try:
                on_row(enriched)
            except Exception:  # noqa: BLE001 - the row is still in the collection
                logger.debug("row hand-off failed for %s", company, exc_info=True)
        if network and isinstance(deadline, SourceClock):
            # A comp lookup is OUR wait: every lane queues on the provider's one
            # cache-miss lock. A deliberate wait is followed by progress (the
            # clock's rule), or a queue of misses reads as this source's silence
            # and a healthy board is recorded stalled.
            deadline.progress()

    try:
        # Gate the requested provider before adapter construction. This also
        # protects alternate factories and the direct daily/discovery paths.
        collection_access(cfg["adapter"], company=company, consent=cfg.get("consent")).require()
        adapter = adapter_factory(
            company,
            cfg["adapter"],
            cfg.get("board_token"),
            # Keyword, not positional: an injected factory in the tests declares
            # `(company, adapter, board_token=None, **kwargs)`, so a fourth
            # positional argument breaks every stand-in rather than the code.
            board_region=cfg.get("board_region"),
            limiter_pool=limiter_pool,
            breaker_pool=breaker_pool,
            deadline=deadline,
            page_budgets=lookups.page_budgets,
            discovery=scan_mode is ScanMode.DISCOVERY,
            location_groups=scope.enabled_locations,
            # The frontier: rows we already hold open. A discovery probe pages
            # until it reaches them, so how deep it reads follows how much the
            # board moved rather than a constant. Empty/absent outside discovery,
            # where stopping early would forfeit the closure authority that only
            # a complete reconcile listing carries.
            known_keys=(
                lookups.existing_open_keys if scan_mode is ScanMode.DISCOVERY else None
            ),
            # A recipe binding's pinned, compiled revision; passed only
            # when present so every stand-in factory keeps its signature.
            **({"recipe_plan": cfg["recipe_plan"]} if cfg.get("recipe_plan") is not None else {}),
            # The adapter re-checks policy on entry and on every request; it
            # must see the same consent the gate above did, or a consented
            # walled company is refused one layer down.
            consent=cfg.get("consent"),
        )
        # Places already read for this company's open postings: an
        # adapter that places a posting only from its detail page reuses them.
        adapter.known_places = lookups.known_places
        # A place read only from a posting's detail page is spent only on a
        # posting the rest of the scope admits. One that fails the
        # role gate is dropped below whatever its place, so reading it first
        # would spend a detail request on every listed posting.
        adapter.place_gate = lambda raw: passes_filters(
            annotate(raw), scope, read_place=False
        ) and not rule_excluded(raw, scope.company_exclusions)
        # Regions the user tracks that this source was never asked about. Recorded
        # BEFORE the scan, because a question we do not send leaves no trace in
        # the response: no error, no drift, no anomaly, and an empty region reads
        # exactly like a region with no open roles.
        #
        # `getattr`, as for `truncated` and `query_observations`: collection
        # accepts duck-typed adapters. The default can never fire for a real
        # source: `BaseAdapter` defines the method and
        # `tests/contracts/test_location_coverage.py` calls it for every entry in
        # ADAPTER_REGISTRY.
        stats["uncovered_locations"] = list(
            getattr(adapter, "location_gaps", list)() or []
        )
        async with adapter:
            async for raw in adapter.fetch():
                # Cooperative bound exit, checked per item so a source that is
                # slow *without* being HTTP-bound (paging a huge board, a
                # non-transport stall) is bounded too, and so the items already
                # collected survive. A cancel here would throw them away.
                fired = bound_fired(deadline)
                if fired == STALLED:
                    stalled = True
                    break
                if fired == BOUNDED:
                    bounded = True
                    break
                # An item in hand is progress: a board of out-of-scope roles
                # still proves the source is working, so liveness must count
                # what was scanned, never what was kept.
                if isinstance(deadline, SourceClock):
                    deadline.progress()
                stats["scanned"] += 1
                if max_list is not None and stats["scanned"] > max_list:
                    cap_fired = True
                    break
                await retain(raw, network=True)
    except CollectionPolicyDenied as exc:
        logger.info("collection skipped for %s: %s", company, exc)
        stats["unattempted"] = True
        stats["policy_reason"] = exc.access.reason
        stats["policy_provider"] = exc.access.provider_key
        # A route-family adapter that found the board on another route.
        # Carried out for the pipeline to record; this function
        # touches no database.
        route = getattr(exc, "route", None)
    except RetryDeadlineExceeded:
        # A bound stopped us, not a fault. This exception exists for exactly that
        # signal, so it must not be recorded as an error: that would classify a
        # ceiling-exhausted source as `degraded` and score a health anomaly. A
        # slowly paced listing can reach the ceiling inside the transport, which
        # raises here before the per-item check can label it.
        #
        # Which bound decides the attribution: silence is the source's, the
        # ceiling is ours.
        if bound_fired(deadline) == STALLED:
            stalled = True
        else:
            bounded = True
    except UnknownAdapterError as exc:
        # A company whose connector this build does not carry. That is a fact
        # about the DEPLOYMENT, not about the source, so it must not count against
        # it: `unattempted` neither counts a miss nor resets one. The error
        # is still recorded so the run reports it and closure stays suppressed;
        # `classify_source_outcome` reads `unattempted` before `errors`.
        logger.error("adapter for %s cannot be built: %s", company, exc)
        stats["errors"].append(describe_exception(exc))
        stats["unattempted"] = True
    except CircuitOpenError as exc:
        # The breaker refused further sends. `blocked` (a WAF-style uniform
        # refusal) is recorded as its own flag so the outcome derivation can
        # name it: "the source is refusing us" and "the source errored" need
        # different operator responses. A plain congestion-open stays an
        # ordinary error and classifies degraded/failed.
        logger.error("adapter %s stopped by its circuit breaker: %s", company, exc)
        stats["errors"].append(describe_exception(exc))
        stats["blocked"] = exc.blocked
    except Exception as exc:  # noqa: BLE001 - one source must not kill the run
        logger.exception("adapter %s failed", company)
        stats["errors"].append(describe_exception(exc))

    if adapter is not None and not stats["unattempted"]:
        for raw in getattr(adapter, "drain_completed", lambda: ())():
            if raw.dedupe_key() in seen_keys:
                continue
            if max_list is not None and stats["scanned"] >= max_list:
                cap_fired = True
                break
            stats["scanned"] += 1
            try:
                await retain(raw, network=False)
            except Exception as exc:  # noqa: BLE001 - retain source isolation
                stats["errors"].append(describe_exception(exc))
                break
    listing_complete = await _record_scan_end(
        stats,
        adapter,
        company=company,
        started=started,
        suspension=suspension,
        stalled=stalled,
        bounded=bounded,
        cap_fired=cap_fired,
        max_list=max_list,
    )
    drift = list(adapter.drift.alerts) if adapter is not None else []
    if adapter is not None:
        # Rows that named a requisition without being buildable into a posting.
        # `seen_keys` is read by exactly one thing, `close_missing`, and its
        # question is "was this key present in the listing?", which a stub
        # answers as well as a full row. Merged here rather than at the yield
        # site because the adapter never produces a `RawJob` for them: there is
        # nothing to enrich, persist or filter, only a job that must not be
        # closed by an absence that was never real.
        seen_keys |= adapter.drift.present_only
    return SourceCollection(
        company,
        enriched_jobs,
        seen_keys,
        stats,
        drift,
        scope_by_key,
        catalog,
        listing_complete,
        route=route,
        catalog_unplaced=catalog_unplaced,
        catalog_unsorted=catalog_unsorted,
        catalog_places=scanned_places(adapter),
        inventory=inventory,
        held_reads=held_reads,
    )


async def _record_scan_end(
    stats: SourceStats,
    adapter: BaseAdapter | None,
    *,
    company: str,
    started: float,
    suspension: SuspensionMonitor,
    stalled: bool,
    bounded: bool,
    cap_fired: bool,
    max_list: int | None,
) -> bool:
    """Record in `stats` how a scan that has ended went, and answer whether its
    listing is complete.

    `stalled`, `bounded` and `cap_fired` are how its loop stopped; `started` is
    the monotonic time it began, which `suspension` measured beside it.
    """
    if stalled:
        # An error, not a bound we chose: the source went silent on its own.
        # That is what makes it `degraded` rather than `bounded`, and therefore
        # a health signal.
        stats["errors"].append(
            f"SourceStalled: {company} made no progress within its stall window"
        )
    stats["duration_seconds"] = round(time.monotonic() - started, 1)
    # Recorded before the flags below because it explains them: a suspension is
    # what *produced* the transport errors already in `stats["errors"]`, and the
    # outcome derivation needs both to tell our sleeping laptop from a sick
    # source. `duration_seconds` above is monotonic and so excludes the gap:
    # it stays an honest measure of work done, which is why the gap has to be
    # carried separately rather than inferred from it.
    stats["suspended"] = suspension.suspended()
    stats["suspended_seconds"] = round(suspension.suspended_seconds(), 1)
    # A dropped connection lands as transport errors too, with no clock gap to
    # give it away. A read that failed while no job site accepts a connection is
    # our outage: recorded as ours (`suspended`), it scores no anomaly against a
    # binding (three in a row quarantine one) and no backoff against a provider.
    # Asked only of a read that already failed: a network that
    # filters job sites answers like none at all, and must never stop a read.
    if (
        stats["errors"]
        and not (stats["unattempted"] or stats["suspended"] or stats["blocked"])
        and not await outage.network_up()
    ):
        stats["offline"] = True
    # Only a listing that ran to its natural end is judged by its row count, and
    # only one can authorize closure: a bound, a cap, an error or a suspension
    # already explains a short one. `bounded`, `truncated` and `suspended` sit
    # beside a fired cap: the listing was cut mid-flight, so it is not
    # authoritative evidence that unseen jobs closed, even where it records no
    # error and no health anomaly. `suspended` counts even when the adapter
    # reported a complete listing: a gap we cannot see inside is not a listing
    # we can close jobs against, and one night of suppressed closure is the
    # cheap side of that trade. The directory read does not pass it (it only
    # counts, `judge_listing`).
    listing_complete = judge_listing(
        stats, adapter, cut=bounded or stalled or cap_fired or stats["suspended"]
    )
    # Recorded so the outcome derivation stays a pure function of the stats dict.
    # `capped`, `bounded`, `truncated` and `suspended` (above) are the four
    # reasons a run is *ours* rather than evidence about the source: none may
    # advance binding health.
    # Only the last is unchosen: our hardware rather than our thresholds.
    #
    # `capped` records that an operator cap was IN FORCE, not that it fired.
    # A board that finishes under `--max-list` enumerates completely,
    # and the listing below still says so, but the run is a test the operator
    # bounded: recorded `ok`, it would advance binding health and grant a
    # withheld binding closure authority. Whether the cap fired is `cap_fired`, which
    # only the listing's completeness needs.
    stats["capped"] = max_list is not None
    stats["bounded"] = bounded
    # Per-query pagination observations for the tuning pass. Recorded as
    # plain dicts, like every other stat here, so the derivation stays pure over
    # a mapping.
    stats["queries"] = (
        [
            {
                "query_key": o.query_key,
                "pages_used": o.pages_used,
                "items": o.items,
                "stop_reason": o.stop_reason.value,
                "ceiling": o.ceiling,
                "declared_total": o.declared_total,
                "page_size": o.page_size,
            }
            # `getattr`, as `judge_listing` reads `truncated`: adapters are
            # duck-typed here (test fakes, recipe bridges), and one that never
            # paged simply teaches the tuner nothing.
            for o in getattr(adapter, "query_observations", ())
        ]
        if adapter is not None
        else []
    )
    return listing_complete


def _host_of(cfg: ScanTarget) -> str:
    """The host a tenant token names (`host|site`, `host|domain|pcsx`), or the
    token itself; two companies on one host must never run side by side."""
    token = str(cfg.get("board_token") or "")
    return token.split("|", 1)[0].strip().lower() or token


class _Slots:
    """A semaphore whose waiters can be moved to the front: a lane holding a
    company a person asked for takes the next free slot. Waiters are served in
    the order they asked otherwise, so lanes start in lane order."""

    def __init__(self, size: int) -> None:
        self._free = size
        self._waiters: deque[tuple[str, asyncio.Future[None]]] = deque()

    async def acquire(self, lane: str, *, urgent: bool = False) -> None:
        if self._free > 0 and not self._waiters:
            self._free -= 1
            return
        entry = (lane, asyncio.get_running_loop().create_future())
        if urgent:
            self._waiters.appendleft(entry)
        else:
            self._waiters.append(entry)
        try:
            await entry[1]
        except asyncio.CancelledError:
            if entry[1].done() and not entry[1].cancelled():
                self.release()
            elif entry in self._waiters:
                self._waiters.remove(entry)
            raise

    def release(self) -> None:
        while self._waiters:
            _lane, waiter = self._waiters.popleft()
            if not waiter.done():
                waiter.set_result(None)
                return
        self._free += 1

    def hurry(self, lane: str) -> None:
        """Serve this lane's waiter next, if it is waiting."""
        entry = next((entry for entry in self._waiters if entry[0] == lane), None)
        if entry is not None:
            self._waiters.remove(entry)
            self._waiters.appendleft(entry)


#: Scan time assumed for a company with no measured cost: a paged board of a
#: few hundred postings. Order only, so a wrong guess delays, never loses.
_UNKNOWN_SECONDS = 60.0


def collector_lanes(
    targets: Mapping[str, ScanTarget],
    costs: Mapping[str, SourceCost] | None = None,
    *,
    slots: int | None = None,
) -> dict[str, list[tuple[str, ScanTarget]]]:
    """Collector streams: one per shared-host backend, several per tenant-hosted one.

    A SHARED backend (one service for many companies) is one service behind
    one pacer, so its companies drain serially down one stream; running them
    side by side would only queue on the same pacer. A PER_TENANT backend
    serves each tenant from the tenant's own host with its own pacer, so up to
    `max_boards_in_flight` of its companies run at once without raising any
    host's request rate. Companies on the SAME host always share a lane (one
    shared host can carry several tenants).

    **Order is the first sync's speed**. The returned order is the
    order lanes take the run's `slots`, and with measured ``costs``:

    * tenant hosts are spread by scan TIME, not by count, so a 30-minute board
      runs alone rather than beside the tenants queued behind it;
    * a lane longer than an even share of the run (total work / slots) starts
      first, longest first: it sets when the run can end, and started last it
      ends the run late;
    * the rest start by postings found per second, and a shared lane's
      companies run in that order too, so most of a user's jobs land in the
      first minutes; inside a lane, companies with nothing measured run
      before all of them.

    Without costs (a new install) every lane keeps target order.
    """
    known = costs or {}

    def seconds(company: str) -> float:
        cost = known.get(company)
        return cost.seconds if cost is not None and cost.seconds > 0 else _UNKNOWN_SECONDS

    def found(company: str) -> int:
        cost = known.get(company)
        return cost.kept if cost is not None else 0

    def rate(queue: list[tuple[str, ScanTarget]]) -> float:
        return sum(found(c) for c, _ in queue) / max(1.0, sum(seconds(c) for c, _ in queue))

    lanes: dict[str, list[tuple[str, ScanTarget]]] = {}
    by_backend: dict[str, list[tuple[str, ScanTarget]]] = {}
    for company, cfg in targets.items():
        by_backend.setdefault(cfg["adapter"], []).append((company, cfg))
    for backend, queue in by_backend.items():
        policy = pacing_for(backend)
        width = min(max(1, policy.max_boards_in_flight), len(queue))
        if policy.host_scope is not HostScope.PER_TENANT or width == 1:
            lanes[backend] = queue
            continue
        hosts: dict[str, list[tuple[str, ScanTarget]]] = {}
        for company, cfg in queue:
            hosts.setdefault(_host_of(cfg), []).append((company, cfg))
        # Longest host groups first, each to the currently least loaded lane:
        # by scan time when it is known, which reduces to count when it is not.
        streams: list[list[tuple[str, ScanTarget]]] = [[] for _ in range(min(width, len(hosts)))]
        load = [0.0] * len(streams)
        for group in sorted(
            hosts.values(), key=lambda g: (sum(seconds(c) for c, _ in g), len(g)), reverse=True
        ):
            index = min(range(len(streams)), key=lambda i: (load[i], len(streams[i])))
            streams[index].extend(group)
            load[index] += sum(seconds(c) for c, _ in group)
        for index, stream in enumerate(streams):
            lanes[backend if index == 0 else f"{backend}#{index}"] = stream
    if not known:
        return lanes
    for queue in lanes.values():
        # A company with nothing measured goes first, in target order: it is
        # one its person just followed, or one never read through.
        queue.sort(key=lambda item: (item[0] in known, -found(item[0]) / max(1.0, seconds(item[0]))))
    work = {name: sum(seconds(c) for c, _ in queue) for name, queue in lanes.items()}
    share = sum(work.values()) / max(1, slots or len(lanes))
    long = sorted((n for n in lanes if work[n] > share), key=lambda n: -work[n])
    rest = sorted((n for n in lanes if work[n] <= share), key=lambda n: -rate(lanes[n]))
    return {name: lanes[name] for name in [*long, *rest]}


async def collect_sources(
    targets: dict[str, ScanTarget],
    scope: ScopeFilter,
    resolver: EstimateSet,
    *,
    max_list: int | None,
    hydrate: bool,
    max_concurrent_sources: int,
    source_budget_seconds: float | None = None,
    source_stall_seconds: float | None = None,
    adapter_factory: Callable[..., BaseAdapter] = build_adapter,
    on_source_start: Callable[[str], None] | None = None,
    on_source_done: Callable[[str, int, str, int], None] | None = None,
    scan_mode: ScanMode = ScanMode.RECONCILE,
    lookups: RunLookups | None = None,
    on_row: Callable[[str, EnrichedJob], None] | None = None,
    on_collected: Callable[[str, SourceCollection], None] | None = None,
    asked: asyncio.Queue[AskedCompany] | None = None,
) -> dict[str, SourceCollection]:
    """Collect distinct backends concurrently; queue companies per backend.

    ``on_source_start(company)`` fires when a company actually begins collecting,
    and ``on_source_done(company, detected, outcome, scanned)`` when it finishes,
    giving the caller live progress during a phase that writes nothing. Both are
    plain in-memory callbacks: no awaits, no DB, and never allowed to fail the
    collection (a broken progress hook must not cost a scrape).

    The pair is deliberate. A company sitting in ``targets`` is not yet working:
    the semaphore admits at most ``max_concurrent_sources`` *backends*, and each
    holds its slot while draining its own companies serially. Only the start hook
    can tell in-flight from queued, and without it a caller can do no better than
    "everything not finished is running", which is wrong by the width of the
    queue.

    Bulkheading. Each *company* is bounded independently, so a source that fails
    slowly cannot hold the run. Three bounds, and which one fires
    is itself the diagnosis:

    * ``source_stall_seconds``: sliding; a source that goes silent this long is
      **stalled**, its own pathology, and it reaches binding health;
    * ``source_budget_seconds`` (the setting when not given), tightened by a
      learned budget: absolute; a source still producing when this
      expires is **bounded**, our threshold talking, and health is untouched.
      Catches the pathological slow trickle a stall window never can;
    * a backstop per company for a source that ignores both; discards that
      company's in-flight partial data, which is the accepted trade for a hard
      cap. A source that then cannot even close is left behind, so its lane
      goes on.

    There is no bound on the run as a whole. Every company is either read or
    has a reason it was not (its lane lost the network first), however long
    the run takes: a run bound would cut the companies at the end of a slow
    person's queue and blame them for our threshold.

    The first two are enforced cooperatively through one `SourceClock`, so the
    pages already fetched always survive. That split exists because one fixed
    budget cannot tell a slow healthy source from a stuck one: it either cuts
    healthy sources every run and blames them for our threshold, or never
    bounds the stuck ones.

    Cancelling this coroutine cancels and awaits every collector before the
    cancellation propagates, so no adapter outlives the run that opened it.

    ``on_row(company, row)`` and ``on_collected(company, collection)`` stream
    the run to its writer: each kept row as it is read, then each
    company as it finishes. Same contract as the progress hooks: in-memory,
    never fatal. A company whose lane crashed is not announced; it is in the
    returned mapping only, and the caller finishes it from there.

    ``asked`` carries the companies a person asks for while the run reads. One
    the run has not started yet moves to the front of its lane; one outside
    the run joins it at the front of the lane for its host, or in a lane of its
    own that takes the next free slot. One the run already started or read is
    left alone: its request stays queued for the next tick.

    ``lookups`` is what the run read before collecting (`RunLookups`): each
    company is collected with its own share of it, a learned time budget can
    only tighten that company's ceiling, and the measured costs order the lanes.
    """

    def _start(company: str) -> None:
        if on_source_start is None:
            return
        try:
            on_source_start(company)
        except Exception:  # noqa: BLE001 - progress is display-only, never fatal
            logger.debug("progress start hook failed for %s", company, exc_info=True)

    def _report(company: str, collection: SourceCollection) -> None:
        if on_source_done is None:
            return
        try:
            # Classified here from the same inputs the persist loop uses, so the
            # live view and the recorded `per_source` row can never disagree
            # about how a source went. `list_complete` lives on the collection,
            # not in stats, and the classifier reads it.
            outcome = classify_source_outcome(
                {**collection.stats, "list_complete": collection.list_complete}
            )
            on_source_done(
                company,
                len(collection.enriched),
                outcome.value,
                int(collection.stats.get("scanned") or 0),
            )
        except Exception:  # noqa: BLE001 - progress is display-only, never fatal
            logger.debug("progress hook failed for %s", company, exc_info=True)

    def _collected(company: str, collection: SourceCollection) -> None:
        _report(company, collection)
        if on_collected is None:
            return
        try:
            on_collected(company, collection)
        except Exception:  # noqa: BLE001 - the caller also finishes from the return
            logger.debug("collected hook failed for %s", company, exc_info=True)
    if not targets:
        return {}
    if lookups is None:
        lookups = RunLookups()
    limiter_pool = RateLimiterPool()
    # Run-scoped, like the pacer it keys alongside: the next run always
    # re-probes a source that pushed back during this one.
    breaker_pool = BreakerPool()
    ceiling = float(
        source_budget_seconds
        if source_budget_seconds is not None
        else get_settings().scraper_source_budget_seconds
    )
    slots = _Slots(max_concurrent_sources)
    # Tasks are created, and so admitted to the slots, in lane order.
    backend_queues = {
        name: deque(queue)
        for name, queue in collector_lanes(targets, lookups.costs, slots=max_concurrent_sources).items()
    }
    #: Each lane's backend and the hosts it has held, for the lane an asked company joins.
    lane_hosts = {
        name: (queue[0][1]["adapter"], {_host_of(cfg) for _, cfg in queue})
        for name, queue in backend_queues.items()
    }
    #: Every company each lane took, asked ones included: a lane that crashes
    #: answers for all of them.
    lane_members = {name: [company for company, _ in queue] for name, queue in backend_queues.items()}
    #: Lanes opened for an asked company: they take the next free slot.
    urgent: set[str] = set()
    asked_lookups: dict[str, SourceLookups] = {}
    #: Companies whose collection started, or that the run already holds.
    began: set[str] = set()
    #: Collections that ignored their cancellation past the grace: still running,
    #: no longer waited for.
    abandoned: set[asyncio.Task[SourceCollection]] = set()

    async def collect_backend(lane: str) -> dict[str, SourceCollection]:
        queue = backend_queues[lane]
        completed: dict[str, SourceCollection] = {}
        offline = False
        await slots.acquire(lane, urgent=lane in urgent)
        try:
            while queue:
                company, cfg = queue.popleft()
                began.add(company)
                if offline:
                    # This lane's last read failed while no job site accepted a
                    # connection. Its companies share its host, so each would
                    # fail the same way: deferred, retried at the next tick.
                    # Other lanes judge for themselves: a network
                    # that filters job sites must not stop a careers page that
                    # still answers.
                    completed[company] = deferred_collection(company)
                    _collected(company, completed[company])
                    continue
                now = time.monotonic()
                company_lookups = asked_lookups.pop(company, None) or lookups.for_company(company)
                # A binding's learned budget replaces the global one for this
                # source, but can only ever be *tighter*: it was clamped to
                # the global ceiling when written, and `min` here means a row
                # edited by hand still cannot buy a source more time than the
                # operator allowed.
                budget = ceiling
                learned = company_lookups.source_budget
                if learned is not None:
                    budget = min(budget, learned)
                # The clock is built *inside* the semaphore, so time spent
                # queueing for a slot never counts against the source.
                clock = SourceClock(
                    # No stall window configured => liveness is the ceiling
                    # alone, a single fixed budget.
                    stall_seconds=(
                        source_stall_seconds if source_stall_seconds is not None else budget
                    ),
                    hard_deadline=now + budget,
                )
                # The backstop must fire strictly *after* the cooperative
                # deadline, or it wins the race and the partial data it exists
                # to protect is discarded on every bound exhaustion instead of
                # none. It is measured from the *ceiling*, not the stall window:
                # a source sliding its stall bound forward is working, and a
                # backstop tied to the shorter bound would cancel it mid-work.
                # The grace is capped at the budget so the hard bound is never
                # more than twice what was asked for (and keeps sub-second
                # budgets in tests from waiting out a fixed 15s grace).
                grace = min(_SOURCE_BUDGET_GRACE_SECONDS, budget)
                backstop = budget + grace
                _start(company)
                work = asyncio.create_task(
                    collect_source(
                        company,
                        cfg,
                        scope,
                        resolver,
                        max_list=max_list,
                        hydrate=hydrate,
                        limiter_pool=limiter_pool,
                        breaker_pool=breaker_pool,
                        deadline=clock,
                        adapter_factory=adapter_factory,
                        scan_mode=scan_mode,
                        lookups=company_lookups,
                        on_row=(
                            functools.partial(on_row, company)
                            if on_row is not None
                            else None
                        ),
                    ),
                    name=f"source:{company}",
                )
                try:
                    # Backstop only. The deadline above is what normally stops
                    # the source, cooperatively and with its data; this fires
                    # only if the transport deadline failed to bite, and it
                    # loses what the company had not yet streamed.
                    await asyncio.wait({work}, timeout=backstop)
                    if not work.done():
                        work.cancel()
                        await asyncio.wait({work}, timeout=grace)
                except asyncio.CancelledError:
                    # The caller cancelled the run: the source goes with it.
                    work.cancel()
                    await asyncio.wait({work}, timeout=grace)
                    raise
                if work.done() and not work.cancelled():
                    completed[company] = work.result()
                    offline = bool(completed[company].stats.get("offline"))
                else:
                    # The cooperative bounds were ignored: the source was stuck
                    # inside a single un-interruptible await. That is a genuine
                    # pathology (unlike hitting our ceiling while producing), so
                    # it stays an error and does reach binding health. One that
                    # will not even close is no longer waited for: with no run
                    # bound behind it, waiting would hold this lane for good.
                    if not work.done():
                        abandoned.add(work)
                        work.add_done_callback(abandoned.discard)
                        logger.warning("%s did not close after its backstop; its lane goes on", company)
                    completed[company] = failed_collection(
                        company,
                        f"SourceUnresponsive: {company} ignored its deadline and hit "
                        f"the {backstop:.0f}s backstop",
                    )
                _collected(company, completed[company])
        finally:
            # Nothing here awaits: between the empty queue and this lane's end
            # there is no moment an asked company could be added and lost.
            slots.release()
        return completed

    tasks = {
        lane: asyncio.create_task(collect_backend(lane), name=f"collect:{lane}")
        for lane in backend_queues
    }

    def lane_for(cfg: ScanTarget) -> str:
        """The lane an asked company belongs in: the one holding its host, any
        lane of a backend whose companies share one, else its backend's own."""
        backend, host = cfg["adapter"], _host_of(cfg)
        per_tenant = pacing_for(backend).host_scope is HostScope.PER_TENANT
        for name, (lane_backend, hosts) in lane_hosts.items():
            if lane_backend == backend and (not per_tenant or host in hosts):
                return name
        return backend

    async def admit(queue: asyncio.Queue[AskedCompany]) -> None:
        while True:
            item = await queue.get()
            company = item.company
            if company in began:
                continue
            asked_lookups[company] = item.lookups
            waiting = next((name for name, lane in backend_queues.items()
                            if any(queued == company for queued, _ in lane)), None)
            if waiting is not None:
                lane_queue = backend_queues[waiting]
                entry = next(entry for entry in lane_queue if entry[0] == company)
                lane_queue.remove(entry)
                lane_queue.appendleft(entry)
                slots.hurry(waiting)
                continue
            if company in targets:
                continue
            name = lane_for(item.target)
            if name in tasks and not tasks[name].done():
                backend_queues[name].appendleft((company, item.target))
                lane_hosts[name][1].add(_host_of(item.target))
                lane_members[name].append(company)
                slots.hurry(name)
                continue
            if name in tasks:
                name = f"{name}+{company}"
            backend_queues[name] = deque([(company, item.target)])
            lane_hosts[name] = (item.target["adapter"], {_host_of(item.target)})
            lane_members[name] = [company]
            urgent.add(name)
            tasks[name] = asyncio.create_task(collect_backend(name), name=f"collect:{name}")

    admitter = asyncio.create_task(admit(asked), name="collect:asked") if asked is not None else None
    try:
        # A lane opened for an asked company joins the wait on the next turn.
        while running := [task for task in tasks.values() if not task.done()]:
            await asyncio.wait(running, return_when=asyncio.FIRST_COMPLETED)
    except asyncio.CancelledError:
        # The caller cancelled the run. Cancelling this coroutine interrupts only
        # the wait above, never the tasks it was waiting on: a hung source would
        # keep its `collect:<backend>` task running and its adapter open for as
        # long as the process lived. Each collector is cancelled and
        # awaited, so every `async with adapter` has exited before the
        # cancellation reaches the run. Their partial results are dropped with
        # it: a cancelled run records nothing.
        for task in tasks.values():
            task.cancel()
        await asyncio.gather(*tasks.values(), return_exceptions=True)
        raise
    finally:
        if admitter is not None:
            admitter.cancel()
            await asyncio.gather(admitter, return_exceptions=True)

    collections: dict[str, SourceCollection] = {}
    for lane, task in tasks.items():
        try:
            collections.update(task.result())
        except Exception as exc:  # defensive: collect_source contains source errors
            for company in lane_members[lane]:
                collections[company] = failed_collection(
                    company, describe_exception(exc)
                )
    return collections
