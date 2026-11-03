"""List-only role/seniority inventory refresh.

Pipeline full scans own authoritative snapshots. This CLI is the capped bootstrap
used after company creation and an optional manual refresh:

    python -m tracker.discover_roles --company acme --max-list 150
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import time
from collections.abc import Sequence
from datetime import UTC, datetime

from tracker.company_store import (
    ensure_builtins,
    ensure_catalog_connectors,
    ensure_source_bindings,
    get_active_targets,
)
from tracker.config import get_settings
from tracker.connectors import BreakerPool, RateLimiterPool, build_adapter
from tracker.db.binding import get_active_binding
from tracker.db.inventory_store import write_inventory
from tracker.db.session import session_scope
from tracker.enrich.enricher import annotate
from tracker.enrich.inventory import InventoryRow, inventory_row
from tracker.platform.clock import BOUNDED, STALLED, SourceClock, bound_fired
from tracker.platform.locks import release_dedicated_advisory_lock, take_dedicated_advisory_lock
from tracker.platform.paths import PACING_DIR
from tracker.platform.ratelimit import enable_shared_pacing
from tracker.platform.util import describe_exception
from tracker.profiles.seed import ensure_company_profiles
from tracker.scope.catalog_store import persist_company_catalog, scanned_places
from tracker.settings_store import get_enabled_locations
from tracker.source_policy import CollectionPolicyDenied, collection_access
from tracker.taxonomy.locations import canonical_location_slugs
from tracker.taxonomy.role_catalog import (
    CatalogTallies,
    add_to_catalog,
    catalog_collection_error,
    catalog_drop_reason,
)
from tracker.workflows.collection_types import empty_stats, judge_listing

logger = logging.getLogger(__name__)

# The main scrape already refreshes the role catalog, so discovery is the lower
# priority. Between companies it drops the shared run lock for this long, letting
# a waiting scrape (which wait-retries; see pipeline._RUN_LOCK_*) take over; if a
# scrape grabs it, discovery stops (the scrape refreshes the catalog itself).
_YIELD_WINDOW_SECONDS = 1.0


async def discover(
    companies: list[str] | None = None,
    max_list: int | None = 600,
    locations: list[str] | None = None,
) -> dict:
    """Refresh the role catalog. A source that lists only the places it is
    asked for is asked for the saved places, as the scrape asks it, plus
    `locations`: places a person is answering with and has not saved, so
    "Count now" can count them. Passed no places, such a source would read
    the shipped defaults, whatever was saved."""
    settings = get_settings()
    key = settings.advisory_lock_key
    per_company: dict[str, dict] = {}
    pool = RateLimiterPool()
    # Same bulkheads as the scrape. Discovery needs them MORE, not
    # less: it holds the shared run lock for the whole of one company's scan and
    # only yields *between* companies, so a single slow source here does not
    # just stall discovery: it blocks every scrape for as long as it hangs.
    breaker_pool = BreakerPool()

    async with session_scope() as session:
        # On a connection of its own, as the pipeline holds it: this session
        # commits between companies, and a commit can hand it another
        # connection, where an unlock would release nothing.
        lock = await take_dedicated_advisory_lock(session.bind, key)
        if lock is None:
            return {"status": "deferred", "reason": "pipeline lock held"}
        try:
            await ensure_builtins(session)
            await ensure_catalog_connectors(session)
            # Same reconciliation as the scrape: discovery also seeds company
            # rows, so it must not be able to leave one binding-less.
            await ensure_source_bindings(session)
            await ensure_company_profiles(session)
            targets = await get_active_targets(session)
            places = frozenset(await get_enabled_locations(session)) | frozenset(
                canonical_location_slugs(locations or [])
            )
            if companies:
                requested = set(companies)
                targets = {slug: cfg for slug, cfg in targets.items() if slug in requested}

            for index, (company, cfg) in enumerate(targets.items()):
                if index > 0:
                    # Yield to a higher-priority scrape between companies: commit
                    # this company's catalog, drop the lock briefly, and stop if a
                    # scrape took it (remaining companies are not lost work: the
                    # scrape refreshes the catalog as it scans).
                    await session.commit()
                    await release_dedicated_advisory_lock(lock, key)
                    lock = None
                    await asyncio.sleep(_YIELD_WINDOW_SECONDS)
                    lock = await take_dedicated_advisory_lock(session.bind, key)
                    if lock is None:
                        logger.info(
                            "yielding role discovery to a scrape after %d companies",
                            len(per_company),
                        )
                        return {
                            "status": "yielded",
                            "reason": "scrape took priority",
                            "companies": per_company,
                        }
                scanned = 0
                unplaced = 0
                unsorted = 0
                seen: set[str] = set()
                tallies: CatalogTallies = {}
                # Every posting this read saw, for the posting inventory:
                # what the scope screens count from.
                inventory: dict[str, InventoryRow] = {}
                error: str | None = None
                capped = False
                bounded = False
                try:
                    collection_access(
                        cfg["adapter"], company=company, settings=settings, consent=cfg.get("consent"),
                    ).require()
                except CollectionPolicyDenied as exc:
                    per_company[company] = {
                        "scanned": 0, "groups": 0, "status": "unattempted",
                        "policy_reason": exc.access.reason,
                        "policy_provider": exc.access.provider_key,
                    }
                    logger.info("role discovery skipped for %s: %s", company, exc)
                    continue
                # Same two bounds as the pipeline, via the same helper, so
                # changing one workflow cannot silently leave the other behind.
                deadline = SourceClock(
                    stall_seconds=settings.scraper_source_stall_seconds,
                    hard_deadline=time.monotonic() + settings.scraper_source_budget_seconds,
                )
                adapter = build_adapter(
                    company,
                    cfg["adapter"],
                    cfg.get("board_token"),
                    board_region=cfg.get("board_region"),
                    limiter_pool=pool,
                    breaker_pool=breaker_pool,
                    deadline=deadline,
                    location_groups=places,
                    consent=cfg.get("consent"),
                )
                try:
                    async with adapter:
                        async for raw in adapter.fetch():
                            # Cooperative bound exit, before the cap check: the
                            # tallies gathered so far are kept and the lock is
                            # released to whoever is waiting for it.
                            fired = bound_fired(deadline)
                            if fired == STALLED:
                                error = (
                                    f"SourceStalled: {company} made no progress "
                                    "within its stall window"
                                )
                                break
                            if fired == BOUNDED:
                                # Our ceiling, not a source fault: recorded as a
                                # partial catalogue, not an error.
                                bounded = True
                                break
                            deadline.progress()
                            scanned += 1
                            if max_list is not None and scanned > max_list:
                                capped = True
                                break
                            # NB: must not shadow the advisory-lock `key`:
                            # unlock/relock after the first company reads it.
                            dedupe = raw.dedupe_key()
                            if dedupe in seen:
                                continue
                            seen.add(dedupe)
                            ann = annotate(raw)
                            if settings.inventory_enabled:
                                inventory[dedupe] = inventory_row(raw, ann)
                            if not add_to_catalog(tallies, raw, ann):
                                if catalog_drop_reason(ann) == "unsorted":
                                    unsorted += 1
                                else:
                                    unplaced += 1
                except CollectionPolicyDenied as exc:
                    per_company[company] = {
                        "scanned": 0, "groups": 0, "status": "unattempted",
                        "policy_reason": exc.access.reason,
                        "policy_provider": exc.access.provider_key,
                    }
                    logger.info("role discovery skipped for %s: %s", company, exc)
                    continue
                except Exception as exc:  # noqa: BLE001 - preserve prior catalog on source failure
                    logger.exception("role discovery failed for %s", company)
                    error = describe_exception(exc)

                # The collector's judgement (`judge_listing`): a read cut by a
                # cap or our bound, truncated by a page ceiling, or missing a
                # page or a row is partial, and a partial read never replaces
                # a ready catalog. Its zero-row rule runs here too: an
                # unexplained zero is not a catalog of no roles.
                stats = empty_stats()
                stats["scanned"] = scanned
                if error is not None:
                    stats["errors"].append(error)
                complete = judge_listing(stats, adapter, cut=capped or bounded)
                if error is None:
                    error = catalog_collection_error(
                        errors=[],
                        scanned=scanned,
                        drift_alerts=list(adapter.drift.alerts),
                    )

                state = await persist_company_catalog(
                    session,
                    company,
                    tallies,
                    complete=complete and error is None,
                    error=error,
                    places=scanned_places(adapter),
                    unplaced=unplaced,
                    unsorted=unsorted,
                )
                await _write_count_inventory(
                    session, company, inventory, seen | adapter.drift.present_only,
                )
                per_company[company] = {
                    "scanned": min(scanned, max_list) if max_list is not None else scanned,
                    "groups": len(tallies),
                    "status": state,
                }
                logger.info("%s: %s", company, per_company[company])
            return {"status": "ok", "companies": per_company}
        finally:
            if lock is not None:
                await release_dedicated_advisory_lock(lock, key)


async def _write_count_inventory(
    session, company: str, rows: dict[str, InventoryRow], seen_keys: set[str],
) -> None:
    """Keep the postings a count read in the posting inventory, so the scope
    screens count them before a sync reads them.

    Never authoritative, whatever the read looked like: a count is always
    capped, and a budget-bounded read judged complete here would mark live
    postings gone. Only a sync marks gone. No run: the rows name none until a
    sync reads them. In a SAVEPOINT: a failure costs the catalog write nothing.
    """
    settings = get_settings()
    if not settings.inventory_enabled or not (rows or seen_keys):
        return
    await session.flush()
    binding = await get_active_binding(session, company)
    try:
        async with session.begin_nested():
            await write_inventory(
                session, run_id=None, company=company,
                binding_id=binding.id if binding is not None else None, rows=rows,
                seen_keys=seen_keys, authoritative=False, now=datetime.now(UTC),
                touch_hours=settings.inventory_touch_hours,
            )
    except Exception:  # noqa: BLE001 - the inventory never fails a count
        logger.warning("inventory write failed for %s", company, exc_info=True)


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Discover role/seniority inventory")
    parser.add_argument("--company", nargs="*")
    parser.add_argument("--max-list", type=int, default=600)
    parser.add_argument("--location", nargs="*", help="places to ask for beyond the saved ones")
    parser.add_argument("-v", "--verbose", action="store_true")
    return parser.parse_args(argv)


async def _main() -> None:
    enable_shared_pacing(PACING_DIR)
    args = _parse_args()
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING)
    summary = await discover(companies=args.company, max_list=args.max_list, locations=args.location)
    import json

    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    asyncio.run(_main())
