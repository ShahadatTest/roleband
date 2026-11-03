"""Materialize a `company_profile` row for every tracked company.

The `/company` view lists `company_profile` rows, so a freshly added company
(built-in or user-added) needs one before anything else writes to it. This seeder
creates it: it runs wherever `ensure_builtins()` runs (API startup,
pipeline, role discovery) and after a company is added via the API.

Get-or-create only, claims through the trust substrate. Identity is ours,
always: our dataset's `company_identity.csv` is recorded
as `"roleband"` claims (rank 60), the blueprint's identity fields as
`"blueprint"` claims (rank 30), so a human pin (100) supersedes them; a
plugin's identity claims are never read, and the price feed claims none.
Never deletes, never overwrites a resolved value directly.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tracker.analytics.comp_split import parent_ticker
from tracker.blueprint import BLUEPRINT
from tracker.company_store import get_tracked_companies
from tracker.db.models import CompanyFact, CompanyProfile
from tracker.levels.identity import identity_for
from tracker.levels.model import CompanyIdentity
from tracker.levels.pay import equity_vehicle_for, profile_vesting, stated_by
from tracker.profiles import store

SOURCE = "blueprint"
#: Our dataset's identity claims (`company_identity.csv`).
DATASET_SOURCE = "roleband"


def _identity_claims(identity: CompanyIdentity) -> list[tuple[str, object]]:
    """The profile fields our identity record states: a researched cell only.

    A company the atlas says is not listed claims "no ticker": claims are
    append-only and the newest of a source wins, so this is what retracts a
    ticker the row once held (Confluent's CFLT after IBM bought it)."""
    claims: list[tuple[str, object]] = []
    for field, value in (
        ("display_name", identity.display_name),
        ("is_public", identity.listed),
        ("ticker", identity.ticker),
        ("website", identity.website),
        ("hq_city", identity.hq_city),
        ("headcount", identity.headcount),
        ("year_founded", identity.year_founded),
        ("brand_color", identity.brand_color),
    ):
        if value is not None:
            claims.append((field, value))
    if identity.listed is False and identity.ticker is None:
        claims.append(("ticker", None))
    return claims


async def ensure_company_profile(session: AsyncSession, slug: str, display: str | None) -> bool:
    """Get-or-create one profile + record blueprint identity claims.

    Returns True when anything changed (row created or a new claim recorded).
    """
    changed = False
    profile = await session.get(CompanyProfile, slug)
    if profile is None:
        profile = CompanyProfile(slug=slug, display_name=display or slug.title())
        session.add(profile)
        await session.flush()
        changed = True

    if (identity := identity_for(slug)) is not None:
        for field, value in _identity_claims(identity):
            changed = await store.record_fact(session, slug, field, value, DATASET_SOURCE) or changed

    bp = BLUEPRINT.get(slug)
    if bp is not None:
        claims: list[tuple[str, object]] = [
            ("display_name", bp.display),
            ("is_public", bp.is_public),
        ]
        if bp.is_public and bp.ticker:
            claims.append(("ticker", bp.ticker))
        if bp.brand_color:
            claims.append(("brand_color", bp.brand_color))
        for field, value in claims:
            changed = await store.record_fact(session, slug, field, value, SOURCE) or changed

    changed = await claim_pay_policy(session, profile) or changed
    if changed:
        await store.resolve_and_materialize(session, slug)
    return changed


async def claim_pay_policy(session: AsyncSession, profile: CompanyProfile) -> bool:
    """Equity mechanics no scraped field expresses, claimed by the core.

    The atlas's equity vehicle and vesting are claimed as who states them.
    Where the atlas names no vehicle, the INFERRED one (public ->
    RSUs, private -> options, a subsidiary of a listed parent -> RSUs)
    reads the RESOLVED `is_public`, never another source's page. The inferred claim is re-asserted only where
    one already exists. The resolved `is_public` is ours (the
    profile columns resolve from our sources only), so the inference never reads
    a plugin's word.

    Returns whether any claim was appended (`record_fact` skips a repeat).
    """
    slug = profile.slug
    changed = False
    if vehicle := equity_vehicle_for(slug):
        changed = await store.record_fact(
            session, slug, "equity_vehicle", vehicle, stated_by(slug, "equity_vehicle")
        ) or changed
    elif await _has_inferred_vehicle(session, slug):
        # From OUR listing only: unknown is not private, so nothing is inferred
        # from it (the claim says None) unless a listed parent decides it.
        if profile.is_public or parent_ticker(slug):
            inferred: str | None = "rsu"
        elif profile.is_public is False:
            inferred = "options"
        else:
            inferred = None
        changed = await store.record_fact(session, slug, "equity_vehicle", inferred, "heuristic") or changed
    if found := profile_vesting(slug):
        vesting, source = found
        changed = await store.record_fact(session, slug, "vesting_schedule", vesting, source) or changed
    return changed


async def _has_inferred_vehicle(session: AsyncSession, slug: str) -> bool:
    found = await session.execute(
        select(CompanyFact)
        .where(
            CompanyFact.company_slug == slug,
            CompanyFact.field == "equity_vehicle",
            CompanyFact.source == "heuristic",
        )
        .limit(1)
    )
    return found.scalar_one_or_none() is not None


async def ensure_company_profiles(session: AsyncSession) -> list[str]:
    """Profile row per tracked company; returns the slugs that changed."""
    changed: list[str] = []
    for row in await get_tracked_companies(session):
        if await ensure_company_profile(session, row.slug, row.display):
            changed.append(row.slug)
    return changed
