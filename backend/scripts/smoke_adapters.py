"""Smoke-test each adapter against its live endpoint.

    python -m scripts.smoke_adapters            # all adapters, 5 jobs each
    python -m scripts.smoke_adapters google 3   # one adapter, N jobs

Verifies the source is reachable, the payload parses, and required fields populate.
"""

from __future__ import annotations

import asyncio
import sys

from tracker.config import COMPANIES, get_settings
from tracker.connectors import BreakerPool, build_adapter, structure_job_detail
from tracker.connectors.detail.base import PAY_SECTION_KEY
from tracker.source_policy import CollectionPolicyDenied, collection_access


async def _stored_consent(company: str) -> str | None:
    """The user's consent for a walled company, read from its row.

    A smoke is a live request like any other: a walled company is collected
    only for a user who consented, so the script reads that consent rather than
    carrying its own. No database, or no row, means no consent.
    """
    try:
        from tracker.db.models import TrackedCompany
        from tracker.db.session import get_session_factory

        async with get_session_factory()() as session:
            row = await session.get(TrackedCompany, company)
            return row.consent_fingerprint if row is not None else None
    except Exception:  # noqa: BLE001 - an unreachable database is "no consent", never a crash
        return None


async def run_one(company: str, limit: int) -> None:
    adapter_name = COMPANIES[company]["adapter"]
    print(f"\n=== {company} ({adapter_name}) ===")
    consent = await _stored_consent(company)
    try:
        collection_access(adapter_name, company=company, consent=consent).require()
    except CollectionPolicyDenied as exc:
        hint = " (follow it with consent in Settings > Followed companies)" if exc.access.walled else ""
        print(f"  -> skipped: {exc}{hint}")
        return
    got = 0
    # Give the adapter a real breaker pool: without one `_breaker` is None and
    # the smoke run silently exercises the unbounded retry path, so the
    # one thing this script exists to observe against a throttling source,
    # the circuit opening, could never appear.
    breaker_pool = BreakerPool()
    adapter = build_adapter(company, adapter_name, breaker_pool=breaker_pool, consent=consent)
    async with adapter:
        try:
            async for job in adapter.fetch():
                got += 1
                locs = ", ".join(job.locations[:2]) or "-"
                print(f"  [{got}] {job.title[:60]!r:62} | {locs[:40]:40} | {job.req_id}")
                # Source facts are only observable live: the fixtures prove the
                # mapping, this proves the fields are still IN the response.
                facts = job.source_facts
                if facts is not None:
                    tiers = facts.compensation.tiers
                    print(
                        f"       facts: job={facts.source_job_id} req={facts.requisition_label} "
                        f"type={facts.employment_type_raw} "
                        # Both publication fields: they are different claims,
                        # and printing only the first would make Ashby (which
                        # states a LAST publication and no first) look like a
                        # board serving no date at all.
                        f"first_published={facts.first_published_at} "
                        f"last_published={facts.last_published_at} "
                        f"updated={facts.source_updated_at} "
                        f"created={facts.source_created_at} "
                        f"locations={len(facts.locations)} "
                        f"pay={facts.compensation.state.value}({len(tiers)} tiers)"
                    )
                if got >= limit:
                    break
        except Exception as exc:  # noqa: BLE001 - smoke visibility
            print(f"  !! ERROR: {type(exc).__name__}: {exc}")
        # Optionally hydrate the last job to test detail fetch.
        if got:
            try:
                await adapter.hydrate(job)
                structure_job_detail(
                    job,
                    adapter.drift,
                    payload=job.detail_payload,
                    source=adapter_name,
                )
                job.detail_payload = None
                dlen = len(job.description_html or "")
                print(f"  hydrate: description length = {dlen}")
                print(f"  sections: {[section.title for section in job.description_sections]}")
                pay = next(
                    (s for s in job.description_sections if s.key == PAY_SECTION_KEY),
                    None,
                )
                print(f"  pay section: {pay.content[:160] if pay else '-'}")
                # The rung the employer printed, when it prints one (microsoft,
                # nvidia). Blank everywhere else, which is the honest answer.
                print(f"  raw_level: {job.raw_level or '-'}")
            except Exception as exc:  # noqa: BLE001
                print(f"  hydrate ERROR: {type(exc).__name__}: {exc}")
    if adapter.drift.alerts:
        print(f"  drift alerts: {adapter.drift.alerts}")
    breaker = adapter._breaker
    if breaker is not None and breaker.failures:
        state = "OPEN" if breaker.is_open else "closed"
        threshold = get_settings().scraper_breaker_threshold
        print(f"  breaker[{breaker.scope}]: {state}, {breaker.failures}/{threshold} failures")
    print(f"  -> {got} jobs parsed")


async def main() -> int:
    """Dispatch, and REFUSE a name this script cannot smoke.

    An unrecognised argument must never fan out to every built-in: a typo, or
    a catalog slug that is not a built-in, would fire every live source instead
    of one. That is the wrong default for the one command whose entire purpose is a
    deliberate, narrow live request, which is also why it is a policy-gated
    entrypoint. Naming a company it cannot reach is a
    mistake to report, not a scope to widen.
    """
    args = sys.argv[1:]
    if args and not args[0].isdigit():
        if args[0] not in COMPANIES:
            print(
                f"unknown company {args[0]!r}: this script smokes built-ins only.\n"
                f"  available: {', '.join(sorted(COMPANIES))}\n"
                f"  a catalog-only company has no built-in config; probe its board with "
                f"`python -m scripts.check_catalog_tokens`.",
                file=sys.stderr,
            )
            return 2
        companies = [args[0]]
    else:
        companies = list(COMPANIES)
    limit = int(args[1]) if len(args) > 1 else (int(args[0]) if args and args[0].isdigit() else 5)
    for company in companies:
        await run_one(company, limit)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
