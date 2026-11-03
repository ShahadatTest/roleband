"""Persist source claims and materialize the resolved profile.

Bridges the pure resolver (`resolve.py`) to the DB. Ingesters never write profile
columns directly — they `record_fact()`, then `resolve_and_materialize()` decides
what the profile actually says. That indirection is what lets a new source be added
without touching any existing writer, and what makes a human correction durable.

**The profile columns are ours, always.** They are
resolved from our own sources only (`CORE_SOURCES`: the blueprint, the atlas, the
employer, filings, your pins, our inferences), never from a plugin, so turning a
plugin on or off never rewrites them. A plugin answers one field only,
`PLUGIN_FIELDS` (company size), and only while it is selected for
`company.facts`: its value is resolved from its own claims when read
(`plugin_fields`), side by side with ours, never instead of ours on disk.
Identity and the offer policy never switch.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from tracker.db.models import CompanyFact, CompanyProfile
from tracker.plugin_manifest import CORE_SOURCES
from tracker.plugins.registry import COMPANY_FACTS, Providers, reader_providers
from tracker.profiles import sources
from tracker.profiles.resolve import Claim, Resolved, company_health, resolve_all

# Identity + mechanics fields resolved from claims. Comp levels and benefits are
# their own tables (they are lists, not single-valued fields).
PROFILE_FIELDS = (
    "display_name",
    "is_public",
    "ticker",
    "headcount",
    "hq_city",
    "website",
    "year_founded",
    "equity_vehicle",
    "vesting_schedule",
    "logo_url",
    "brand_color",
)

#: The one field a plugin may answer: company size. Every other field is ours
#: only, whatever a plugin's manifest claims: identity (name, listed, ticker,
#: website, HQ, logo, colour) and the offer policy (equity vehicle, vesting).
PLUGIN_FIELDS = frozenset({"headcount"})


class AnsweredByPlugin(Exception):
    """A pin on a field a selected plugin answers: your pins are ours, and ours is
    not what that field shows while the plugin answers it."""

    def __init__(self, field: str, plugin: str) -> None:
        super().__init__(f"{field} is answered by {plugin} while it is on")
        self.field, self.plugin = field, plugin


# Fields a profile needs before we consider it usable. Absent ones become
# manual-enrichment work (`needs_review`). `headcount` is not one: the core has
# no source for it, only a plugin's `company.facts` or the user, so requiring it
# would mark every profile of a fresh install incomplete.
REQUIRED_FIELDS = (
    "is_public",
    "equity_vehicle",
)


def required_fields_for(resolved: dict) -> list[str]:
    """Required fields for this company, given what we know so far.

    `ticker` is only required of a PUBLIC company — a private one legitimately has
    none, and demanding it would flag every startup as incomplete forever.
    """
    fields = list(REQUIRED_FIELDS)
    is_public = resolved.get("is_public")
    if is_public is not None and is_public.value:
        fields.append("ticker")
    return fields


async def record_fact(
    session: AsyncSession,
    slug: str,
    field: str,
    value: object,
    source: str,
    *,
    observed_at: datetime | None = None,
    confidence: float = 1.0,
) -> bool:
    """Append one source's claim. Append-only — never updates in place.

    Skips a no-op re-assertion (same source, same field, same value as its latest
    claim) so a nightly refresh doesn't grow the table without adding information.
    Returns whether a claim was actually appended, so callers can skip
    re-resolution when nothing changed.
    """
    latest = (
        await session.execute(
            select(CompanyFact)
            .where(
                CompanyFact.company_slug == slug,
                CompanyFact.field == field,
                CompanyFact.source == source,
            )
            .order_by(CompanyFact.observed_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if latest is not None and latest.value == {"v": value}:
        return False

    session.add(
        CompanyFact(
            company_slug=slug,
            field=field,
            # Wrapped so JSONB can carry null/bool/int/str uniformly.
            value={"v": value},
            source=source,
            confidence=confidence,
            observed_at=observed_at or datetime.now(UTC),
        )
    )
    return True


def _claims(rows) -> list[Claim]:
    return [
        Claim(
            field=r.field,
            value=(r.value or {}).get("v"),
            source=r.source,
            observed_at=r.observed_at,
            confidence=r.confidence,
        )
        for r in rows
    ]


async def _our_claims(session: AsyncSession, slug: str) -> list[Claim]:
    """Every claim of OUR sources for the company. A plugin's are never among
    them, whether it is on or off."""
    rows = (
        await session.execute(
            select(CompanyFact).where(CompanyFact.company_slug == slug, CompanyFact.source.in_(sorted(CORE_SOURCES)))
        )
    ).scalars().all()
    return _claims(rows)


def _meta(r: Resolved, label_of) -> dict:
    return {
        "source": r.source,
        "source_label": label_of(r.source),
        "observed_at": r.observed_at.isoformat(),
        "freshness": r.freshness,
        "is_manual": r.is_manual,
        "conflicts": [
            {
                "source": c["source"],
                "source_label": c["source_label"],
                "value": c["value"],
                "observed_at": c["observed_at"].isoformat(),
            }
            for c in r.conflicts
        ],
    }


async def resolve_and_materialize(session: AsyncSession, slug: str, *, now: datetime | None = None) -> dict:
    """Resolve our claims for a company and write the winners onto the profile.

    Writes `field_meta` (per-field provenance + conflicts) and `data_health` (the
    company badge). Returns the health dict so callers can log/report it. Our
    sources only: a plugin's claims never reach these columns, so a caller that
    re-resolves after a plugin event finds nothing to change, and
    `profile_updated_at` moves only when something did.
    """
    now = now or datetime.now(UTC)
    profile = await session.get(CompanyProfile, slug)
    if profile is None:
        return {"status": "missing", "missing": list(REQUIRED_FIELDS)}

    resolved = resolve_all(await _our_claims(session, slug), now)
    before = ({f: getattr(profile, f, None) for f in PROFILE_FIELDS}, profile.field_meta, profile.data_health)

    meta: dict[str, dict] = {}
    for field in PROFILE_FIELDS:
        r = resolved.get(field)
        if r is None:
            # Nothing of ours claims it: clear it rather than keep a value no
            # source of ours states, whatever wrote it before.
            # The resolver is these columns' only writer, so a value without a
            # claim of ours is a leftover,
            # even where `field_meta` does not name it. Only where
            # the column permits NULL (every one but the name).
            if hasattr(profile, field):
                col = CompanyProfile.__table__.columns.get(field)
                if col is not None and col.nullable:
                    setattr(profile, field, None)
            continue
        if hasattr(profile, field):
            setattr(profile, field, r.value)
        meta[field] = _meta(r, sources.label)

    health = company_health(resolved, required_fields_for(resolved))
    profile.field_meta = meta
    profile.data_health = health["status"]
    after = ({f: getattr(profile, f, None) for f in PROFILE_FIELDS}, profile.field_meta, profile.data_health)
    if after != before:
        profile.profile_updated_at = now
    return health


async def _plugin_rows(session: AsyncSession, providers: Providers, slugs: list[str] | None):
    pid = providers.source_for(COMPANY_FACTS)
    if pid is None:
        return []
    stmt = select(CompanyFact).where(
        CompanyFact.field.in_(sorted(PLUGIN_FIELDS)),
        providers.where(COMPANY_FACTS, CompanyFact.source, CompanyFact.company_slug),
    )
    if slugs is not None:
        stmt = stmt.where(CompanyFact.company_slug.in_(slugs))
    return (await session.execute(stmt.order_by(CompanyFact.observed_at.desc()))).scalars().all()


async def plugin_fields(
    session: AsyncSession, providers: Providers, slugs: list[str] | None = None, *, now: datetime | None = None
) -> dict[str, dict[str, dict]]:
    """`{slug: {field: {value, **meta}}}` for the plugin selected for
    `company.facts`, resolved now from its own claims: only `PLUGIN_FIELDS`, only
    the companies it has read whole. Empty when ours answers."""
    now = now or datetime.now(UTC)
    by_company: dict[str, list] = {}
    for row in await _plugin_rows(session, providers, slugs):
        by_company.setdefault(row.company_slug, []).append(row)
    out: dict[str, dict[str, dict]] = {}
    for slug, rows in by_company.items():
        resolved = resolve_all(_claims(rows), now, providers.fact_ranks, providers.fact_labels)
        out[slug] = {f: {"value": r.value, **_meta(r, providers.label_of)} for f, r in resolved.items()}
    return out


async def set_manual(
    session: AsyncSession, slug: str, field: str, value: object
) -> dict:
    """Pin a human-supplied value. Outranks every source of ours, now and on every
    refresh. Refused for a field a selected plugin answers (`AnsweredByPlugin`):
    the pin would be ours, and that field is not shown from ours while it is on."""
    if field in PLUGIN_FIELDS and (pid := (await reader_providers(session)).source_for(COMPANY_FACTS)):
        raise AnsweredByPlugin(field, pid)
    await record_fact(session, slug, field, value, "manual")
    profile = await session.get(CompanyProfile, slug)
    if profile is not None:
        pinned = set(profile.manual_fields or [])
        pinned.add(field)
        profile.manual_fields = sorted(pinned)
    health = await resolve_and_materialize(session, slug)
    await session.commit()
    return health


async def clear_manual(session: AsyncSession, slug: str, field: str) -> dict:
    """Un-pin a field: drop the human claims and fall back to source resolution.

    Deletes the manual claims rather than merely un-listing the field — a lingering
    `manual` claim would keep winning (rank 100) and the "revert" would be a no-op.
    """
    await session.execute(
        delete(CompanyFact).where(
            CompanyFact.company_slug == slug,
            CompanyFact.field == field,
            CompanyFact.source == "manual",
        )
    )
    profile = await session.get(CompanyProfile, slug)
    if profile is not None:
        profile.manual_fields = sorted(set(profile.manual_fields or []) - {field})
        # The column still holds the human value. Clear it so re-resolution can
        # repopulate from whatever source now wins (or leave it genuinely empty),
        # where the column permits NULL (every identity field does).
        col = CompanyProfile.__table__.columns.get(field)
        if col is not None and col.nullable:
            setattr(profile, field, None)
    health = await resolve_and_materialize(session, slug)
    await session.commit()
    return health


async def candidates_for(session: AsyncSession, slug: str) -> dict[str, list[dict]]:
    """Per field, the latest claim from each source — the choices we offer the user.

    This is the "our job is to suggest" half of the manual workflow: when sources
    disagree we don't just flag it, we hand over every candidate value with its
    source and date so the human can pick rather than retype. Ranked most-trusted
    first, and from the ONE source answering each field: ours, or for
    `PLUGIN_FIELDS` the selected plugin's, never both (a plugin's value offered
    here would become a pin of ours).
    """
    providers = await reader_providers(session)
    plugin = providers.source_for(COMPANY_FACTS)
    rows = list(
        (
            await session.execute(
                select(CompanyFact)
                .where(CompanyFact.company_slug == slug, CompanyFact.source.in_(sorted(CORE_SOURCES)))
                .order_by(CompanyFact.observed_at.desc())
            )
        ).scalars().all()
    )
    if plugin is not None:
        rows = [r for r in rows if r.field not in PLUGIN_FIELDS] + list(
            await _plugin_rows(session, providers, [slug]))
        rows.sort(key=lambda r: r.observed_at, reverse=True)

    out: dict[str, list[dict]] = {}
    for r in rows:
        bucket = out.setdefault(r.field, [])
        if any(c["source"] == r.source for c in bucket):
            continue  # keep only each source's most recent claim
        bucket.append(
            {
                "source": r.source,
                "rank": providers.rank_of(r.source),
                "value": (r.value or {}).get("v"),
                "observed_at": r.observed_at.isoformat(),
            }
        )
    for bucket in out.values():
        bucket.sort(key=lambda c: c["rank"], reverse=True)
    return out


async def rematerialize_source(session: AsyncSession, source: str) -> list[str]:
    """Resolve again every company `source` has claimed a fact for: when a
    plugin is turned on, off or removed, its claims become read or unread, and a
    profile column it alone filled must clear at once, not at the next
    materialization. Commits nothing; returns the companies."""
    companies = sorted(
        (await session.execute(select(CompanyFact.company_slug).where(CompanyFact.source == source).distinct()))
        .scalars()
    )
    for slug in companies:
        await resolve_and_materialize(session, slug)
    return companies


async def rematerialize_sources(session: AsyncSession, sources: list[str]) -> list[str]:
    """`rematerialize_source` for several sources at once. Each company resolved once."""
    companies = sorted(
        (await session.execute(
            select(CompanyFact.company_slug).where(CompanyFact.source.in_(sources)).distinct()
        )).scalars()
    )
    for slug in companies:
        await resolve_and_materialize(session, slug)
    return companies
