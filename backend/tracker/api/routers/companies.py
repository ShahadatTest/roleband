"""Tracked companies (built-in + user-added) and resolved Company Profiles.

What every route here answers with is declared in `api/schemas/companies.py`:
the tracked-company routes, the company-profile routes and the company card.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import and_, nullslast, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from tracker.analytics.comp_package import country_rows
from tracker.api import job_requests, scan_requests
from tracker.api.company_errors import company_error
from tracker.api.deps import OffBoardDep, SessionDep, end_read
from tracker.api.errors import ErrorCode, api_error
from tracker.api.schemas.companies import (
    BoardSearchResponse,
    CompanyCardResponse,
    CompanyClaimsResponse,
    CompanyDirectorySearchResponse,
    CompanyDirectoryStatus,
    CompanyDiscoveryResponse,
    CompanyListResponse,
    CompanyNamesResponse,
    CompanyOpenCountsResponse,
    CompanyPricesResponse,
    CompanyProfileDetailResponse,
    CompanyProfileFieldWrite,
    CompanyProfileListResponse,
    TrackedCompanyRow,
)
from tracker.api.schemas.text_class import text as text_class
from tracker.ats_detect import DetectedBoard
from tracker.board_relocate import check_address, find_moved_board
from tracker.board_resolve import board_answers, resolve_pasted_board
from tracker.comp_providers.base import OUR_PAY_COUNTRY
from tracker.company_directory import directory_company, directory_size, search_directory
from tracker.company_discovery import COMPANY_DISCOVERY, SECTORS, build_company_discovery
from tracker.company_store import (
    CONSENT_TEXT_MAX,
    CompanyError,
    add_company,
    ensure_builtins,
    get_tracked_companies,
    is_builtin,
    off_board_company_slugs,
    record_board_move,
    record_consent,
    require_consent_to_follow,
    resolve_company,
    set_enabled,
    set_visible,
    unfollowed_company_slugs,
)
from tracker.config import get_settings
from tracker.connectors import ADAPTER_REGISTRY
from tracker.db.models import (
    CompanyBenefit,
    CompanyCompLevel,
    CompanyFact,
    CompanyProfile,
    TrackedCompany,
)
from tracker.db.queries.companies import (
    display_names,
    last_read_titles,
    open_counts_by_company,
)
from tracker.db.queries.reference_pay import (
    admit_benefits,
    admit_levels,
    benefit_scope,
    level_scope,
    reference_ladder,
)
from tracker.enrich.classify import location_groups_for
from tracker.levels.atlas import load_level_base
from tracker.levels.pay import PAY_POLICIES, bonus_ratio_for, profile_offer
from tracker.notifications.coverage import generate_coverage_notifications
from tracker.platform.language_tags import LOCALE_TAG, is_locale_tag
from tracker.platform.safe_fetch import public_client
from tracker.plugin_manifest import CORE_SOURCES
from tracker.plugins.registry import COMPANY_BENEFITS, COMPANY_FACTS, PAY_LEVELS, reader_providers
from tracker.profiles import prices as price_store
from tracker.profiles import store as profile_store
from tracker.profiles.benefits_builtin import (
    dataset_benefit_notes,
    dataset_benefits,
    plugin_benefits,
)
from tracker.profiles.seed import ensure_company_profile
from tracker.schema import BoardRegion
from tracker.scope.catalog import company_count_state
from tracker.source_policy import collection_access
from tracker.taxonomy.comp_families import REFERENCE_FAMILY
from tracker.taxonomy.locations import LOCATION_GROUPS
from tracker.workflows.directory_sweep import directory_status, set_follow

router = APIRouter()


class AddCompanyPayload(BaseModel):
    catalog_slug: str | None = None
    name: str | None = Field(None, json_schema_extra=text_class("content"))
    careers_url: str | None = None


class FindBoardPayload(BaseModel):
    #: An address the person gives. Absent: search from what RoleBand knows.
    careers_url: str | None = Field(default=None, max_length=2048)


class MoveBoardPayload(BaseModel):
    """A board `POST .../board/find` answered with; verified again on write."""

    adapter: str = Field(min_length=1, max_length=64)
    board_token: str = Field(min_length=1, max_length=512)
    board_region: BoardRegion | None = None


class EnabledPayload(BaseModel):
    # Both optional so the two switches can be toggled independently.
    enabled: bool | None = None
    visible: bool | None = None




class CompanyConsent(BaseModel):
    """The user's answer to a walled company's consent dialog."""

    #: The dialog may contain pinned English within the selected language.
    locale: str = Field(default="en", pattern=LOCALE_TAG, max_length=35, json_schema_extra=text_class("code"))
    slug: str
    #: The dialog text the user confirmed, verbatim, so the record says what
    #: they agreed to rather than that they clicked something.
    text: str = Field(json_schema_extra=text_class("record"), min_length=1, max_length=CONSENT_TEXT_MAX)

    @field_validator("locale")
    @classmethod
    def valid_locale(cls, value: str) -> str:
        if not is_locale_tag(value):
            raise ValueError("invalid consent locale")
        return value


class DirectoryFollowPayload(BaseModel):
    """Follow or unfollow every other company RoleBand can scan, as one decision."""

    following: bool


class CompanySelectionPayload(BaseModel):
    #: The companies the person switched on and off, and only those. The roster
    #: changes under the screen (the wider-market scan follows companies by
    #: itself), so a write that restated the whole roster would undo those.
    follow: list[str] = []
    unfollow: list[str] = []
    #: Consents given in the dialog that produced this selection: one per walled
    #: company the dialog covered. Starting to follow a walled company without
    #: one (or a stored one) is refused.
    consents: list[CompanyConsent] = []


async def _company_locations(session: SessionDep, slug: str) -> list[dict]:
    """Open-role count per canonical city for one company, busiest first.

    Derived live from open in-scope jobs (`location_cities`, the lexical
    labels written with the job's places): offices are observed from
    postings, never declared, so the view stays current with every scrape.
    Each city carries the coarse location-group slugs its label falls into
    (the scope-filter axis) as badges, read again from the label, not from
    the job's own `location_groups`.

    `country` names the country-kind group explicitly instead of leaving the
    dashboard to guess which slug in `groups` is one. The guess ("the first
    entry that appears in the generated country table") holds only while no
    metro slug collides with a country slug, a convention rather than a
    contract, and the dashboard keeps no mirror of this taxonomy.
    `None` is a real answer, not a failure: `Wilmington, DE` resolves to no
    country because `de` is deliberately excluded from the US state tokens
    (`taxonomy.locations`), so the caller must have somewhere to put an
    unmapped city. A Canadian province code that `_CA_PROVINCE_CODES` admits
    ("Toronto, ON") resolves to Canada when the label carries no US state and
    no US signal.
    """
    rows = await session.execute(
        text(
            "SELECT city, count(*) AS n FROM"
            " (SELECT unnest(location_cities) AS city FROM jobs"
            "  WHERE company = :slug AND status = 'open' AND in_scope) t"
            " GROUP BY city ORDER BY n DESC, city"
        ),
        {"slug": slug},
    )
    out = []
    for city, n in rows.all():
        groups = location_groups_for([city])
        country = next(
            (s for s in groups if LOCATION_GROUPS.get(s, {}).get("kind") == "country"),
            None,
        )
        out.append(
            {"city": city, "open_count": n, "groups": groups, "country": country}
        )
    return out


def _company_out(row: TrackedCompany, job_count: int) -> dict:
    return {
        "slug": row.slug,
        "display": row.display,
        "adapter": row.adapter,
        "board_token": row.board_token,
        "careers_url": row.careers_url,
        "status": row.status,
        "enabled": row.enabled,
        "visible": row.visible,
        "source": row.source,
        "builtin": is_builtin(row.slug),  # blocks deletion; every company is a row
        "job_count": job_count,
        "role_catalog_status": row.role_catalog_status,
        "role_catalog_scanned_at": row.role_catalog_scanned_at,
        "role_catalog_error": row.role_catalog_error,
        "detected_family": row.detected_family if row.status == "pending" else None,
        "pending_reason": row.pending_reason if row.status == "pending" else None,
    }


@router.get("/api/companies", response_model=CompanyListResponse)
async def list_companies(session: SessionDep) -> dict:
    """Every tracked company (built-in + user-added) with its tracking + visibility
    switches. Built-ins are ordinary rows (seeded at startup) flagged `builtin` so the
    UI hides Remove.

    A pure read, for the reason `/api/companies/discovery` gives below: startup,
    the pipeline and every mutating company route already reconcile built-ins,
    and a GET must not commit (`tests/test_api_get_is_read_only.py`)."""
    counts = await open_counts_by_company(session)
    return {
        "companies": [
            _company_out(row, counts.get(row.slug, 0))
            for row in await get_tracked_companies(session)
        ]
    }


@router.get("/api/companies/directory", response_model=CompanyDirectorySearchResponse)
async def companies_directory(session: SessionDep, q: str = Query("", max_length=64)) -> dict:
    """Search every other company RoleBand can scan, by name.

    Server-side because the set is thousands of companies: the register
    asks for the few that match what the user typed, never for the list.
    """
    hits, total = search_directory(q)
    tracked = {row.slug: row for row in await get_tracked_companies(session)}
    return {
        "size": directory_size(),
        "match_count": total,
        "matches": [
            {
                "slug": hit.slug,
                "display": hit.display,
                "named_by": hit.named_by,
                "tracked": hit.slug in tracked,
                "enabled": bool(hit.slug in tracked and tracked[hit.slug].enabled),
            }
            for hit in hits
        ],
    }


@router.get("/api/companies/directory/status", response_model=CompanyDirectoryStatus)
async def companies_directory_status(session: SessionDep) -> dict:
    """The whole set as the register draws it: its size, whether it is followed,
    and how far the background scan has read it. A pure read."""
    return await directory_status(session)


@router.put("/api/companies/directory/follow", response_model=CompanyDirectoryStatus)
async def follow_companies_directory(payload: DirectoryFollowPayload, session: SessionDep) -> dict:
    """Follow every other company RoleBand can scan, or stop.

    Following starts the background scan (`workflows.directory_sweep`), which
    follows each company it finds roles at. Stopping switches off exactly the
    companies the set brought in and remembers them, so following again brings
    back the same ones; a company followed by name is never touched.
    """
    await set_follow(session, payload.following, datetime.now(UTC))
    await session.commit()
    if payload.following:
        # Read now, not at the next look up to ten minutes away.
        await job_requests.ring_directory(session, requested_by="follow")
        await session.commit()
    return await directory_status(session)


@router.get("/api/companies/discovery", response_model=CompanyDiscoveryResponse)
async def companies_discovery(session: SessionDep) -> dict:
    """Job-seeker sectors merged with the user's current tracking state.

    The Company Explorer's first paint depends on this and nothing else, so it
    is a pure read: no `ensure_builtins()` upsert+commit (startup, the pipeline,
    and every mutating company route already reconcile built-ins — a GET that
    writes can queue behind a running scrape's row locks and hold the whole
    screen blank), and no `jobs` aggregate. Open-role counts arrive separately
    via `/api/companies/open-counts`.
    """
    tracked = {row.slug: row for row in await get_tracked_companies(session)}
    return build_company_discovery(tracked=tracked)


@router.get("/api/companies/open-counts", response_model=CompanyOpenCountsResponse)
async def companies_open_counts(session: SessionDep) -> dict:
    """Open in-scope role count per company slug.

    Split out of `/api/companies/discovery` so the roster renders immediately
    and each row fills its count in place. Companies with no open in-scope role
    are absent; the caller reads a missing slug as 0.

    Beside it, per followed company, what the Profile's count leaves out and
    how many of its roles no answer can keep, by reason, so each status
    shows where the company is.
    """
    state = await company_count_state(session, await off_board_company_slugs(session))
    return {
        "counts": await open_counts_by_company(session),
        "not_counted": state.not_counted,
        "unplaced": state.unplaced,
        "unsorted": state.unsorted,
        "last_read": state.last_read,
    }


@router.get("/api/companies/names", response_model=CompanyNamesResponse)
async def companies_names(session: SessionDep) -> dict:
    """Each company's name by slug: every catalog company, and every tracked
    one, whose stored name wins. The dashboard reads it once, before its first
    render, so every screen names a company the way the company does ("PwC",
    "CrowdStrike") rather than by its slug, including the level table's
    reference companies on an install that follows none of them. The
    directory's thousands of other companies are not in it."""
    names = {slug: company.display for slug, company in COMPANY_DISCOVERY.items()}
    names.update(await display_names(session))
    return {"names": names}


@router.put("/api/companies/selection", response_model=CompanyDiscoveryResponse)
async def update_company_selection(
    payload: CompanySelectionPayload,
    session: SessionDep,
) -> dict:
    """Atomically follow and unfollow the companies the person switched.

    A company the change does not name keeps its state. Missing discovery
    companies are registered first. Sources without an implemented adapter
    remain ``pending`` and therefore cannot be scraped yet; the selection
    records intent without overstating connector readiness. Unfollowed rows are
    paused rather than deleted, preserving their history.
    """
    await ensure_builtins(session)
    rows = await get_tracked_companies(session)
    tracked = {row.slug: row for row in rows}
    desired = set(payload.follow)
    dropped = set(payload.unfollow)
    if both := desired & dropped:
        raise api_error(400, ErrorCode.INVALID_INPUT,
                        f"followed and unfollowed at once: {', '.join(sorted(both))}")
    unknown = {
        slug for slug in desired - set(COMPANY_DISCOVERY) - set(tracked)
        if directory_company(slug) is None
    }
    if unknown:
        raise api_error(400, ErrorCode.INVALID_INPUT, f"unknown companies: {', '.join(sorted(unknown))}")

    # Validate every new entry before mutating the roster so a parked source
    # cannot leave a partially applied selection.
    fields_to_add: list[dict] = []
    for slug in sorted(desired - set(tracked)):
        try:
            fields_to_add.append(resolve_company(catalog_slug=slug))
        except CompanyError as exc:
            raise company_error(exc) from exc

    added: list[TrackedCompany] = []
    try:
        for fields in fields_to_add:
            row = await add_company(session, fields)
            tracked[row.slug] = row
            added.append(row)
        # Consent first, then the transitions it unlocks — all before the
        # commit, so a refused walled follow leaves nothing half-applied.
        for consent in payload.consents:
            if consent.slug not in desired or consent.slug not in tracked:
                raise CompanyError(f"consent for '{consent.slug}', which this selection does not follow")
            record_consent(tracked[consent.slug], consent.text, locale=consent.locale)
        followed_now: list[str] = []
        for slug in sorted(desired):
            row = tracked[slug]
            if not row.enabled:
                require_consent_to_follow(row)
                followed_now.append(slug)
            row.enabled = True
        for slug in dropped & set(tracked):
            tracked[slug].enabled = False
        for row in added:
            await ensure_company_profile(session, row.slug, row.display)
        await session.commit()
    except CompanyError as exc:
        await session.rollback()
        raise company_error(exc) from exc

    scrapeable = [row.slug for row in added if row.status == "active" and row.adapter]
    if scrapeable:
        await job_requests.ring_role_discovery(session, scrapeable, max_list=150, requested_by="add_company")
        await session.commit()
    await _start_first_scans(session, [*added, *(tracked[slug] for slug in followed_now if slug in tracked)])

    tracked = {row.slug: row for row in await get_tracked_companies(session)}
    return build_company_discovery(tracked=tracked)


async def _start_first_scans(session, followed: list[TrackedCompany]) -> None:
    """Ask for a scan now for companies the user just followed.

    A company never scanned is due at once and joins one drain run;
    without this it waits for the next 600s tick. The dispatcher decides what
    is collectable (a user-directed source still waits for the user's Sync),
    so this only moves WHEN it looks. A request, so it joins one already
    queued and waits for a scan in flight, whose tick or the next picks the
    companies up. Commits.
    """
    if any(row.status == "active" and row.adapter for row in followed):
        await scan_requests.ring(session, requested_by=scan_requests.FIRST_SCAN)
        await session.commit()


@router.post("/api/companies", status_code=201, response_model=TrackedCompanyRow)
async def create_company(payload: AddCompanyPayload, session: SessionDep) -> dict:
    """Add a company from the catalog, or by careers URL (auto-detect ATS).

    URLs that aren't a board `detect_ats` collects are stored `pending`
    — visible in Settings but skipped by the pipeline until an adapter exists.
    """
    try:
        fields = resolve_company(
            name=payload.name,
            careers_url=payload.careers_url,
            catalog_slug=payload.catalog_slug,
        )
        # A URL no pattern names may still be a board its page names.
        fields = await resolve_pasted_board(fields)
        row = await add_company(session, fields)
        await session.commit()
        # A tracked company must be a /company profile from the moment it exists.
        await ensure_company_profile(session, row.slug, row.display)
        await session.commit()
    except CompanyError as exc:
        raise company_error(exc) from exc
    await _start_first_scans(session, [row])
    if row.status == "active" and row.adapter:
        # Best-effort bootstrap, skipped when a discovery is already queued or
        # running. Safe to skip: the row is created
        # `role_catalog_status="pending"` and the next pipeline run refreshes
        # the catalog as it scans — the same reason discovery may abandon its
        # remaining companies when it yields the lock to a scrape.
        await job_requests.ring_role_discovery(session, [row.slug], max_list=150, requested_by="add_company")
        await session.commit()
    return _company_out(row, 0)


@router.patch("/api/companies/{slug}", response_model=TrackedCompanyRow)
async def update_company(slug: str, payload: EnabledPayload, session: SessionDep) -> dict:
    """Toggle a company's tracking (`enabled`) and/or visibility (`visible`).

    Both fields are optional and applied independently. Built-in and user-added
    companies are identical rows here — one code path, no special case.
    """
    if payload.enabled is None and payload.visible is None:
        raise api_error(400, ErrorCode.INVALID_INPUT, "provide 'enabled' and/or 'visible'")

    # A built-in may not have been seeded yet on a brand-new DB (e.g. before the
    # first startup ran); ensure its row exists so the toggle always has a target.
    if is_builtin(slug):
        await ensure_builtins(session)

    try:
        if payload.enabled is not None:
            row = await set_enabled(session, slug, payload.enabled)
        if payload.visible is not None:
            row = await set_visible(session, slug, payload.visible)
        await session.commit()
        if payload.enabled is False:
            # An unfollowed company costs nobody coverage: its Coverage row
            # goes now, not at the next scan (the notice's own
            # "stop following" answer).
            await generate_coverage_notifications(session)
            await session.commit()
    except CompanyError as exc:
        raise company_error(exc) from exc
    counts = await open_counts_by_company(session)
    return _company_out(row, counts.get(slug, 0))


@router.post("/api/companies/{slug}/board/find", response_model=BoardSearchResponse)
async def find_company_board(slug: str, payload: FindBoardPayload, session: SessionDep) -> dict:
    """Where a company's careers page moved, verified, or null.

    With `careers_url`: the board behind the address the person gave. Without:
    the company's own careers page, then its name on the families keyed by a
    name, a guess counting only if its roles overlap what RoleBand last read
    there (`board_relocate`). Reads only; `PUT .../board` writes the move.
    """
    row = await session.get(TrackedCompany, slug)
    if row is None:
        raise api_error(404, ErrorCode.COMPANY_NOT_FOUND, f"'{slug}' is not a tracked company", slug=slug)
    known = await last_read_titles(session, slug)
    await end_read(session)
    async with public_client(user_agent=get_settings().scraper_user_agent) as client:
        if payload.careers_url:
            found = await check_address(
                payload.careers_url.strip(), slug=slug, adapter=row.adapter,
                board_token=row.board_token, known=known, client=client,
            )
        else:
            found = await find_moved_board(
                slug=slug, display=row.display or slug, adapter=row.adapter,
                board_token=row.board_token, careers_url=row.careers_url, known=known, client=client,
            )
    return {"candidate": asdict(found) if found is not None else None}


@router.put("/api/companies/{slug}/board", response_model=TrackedCompanyRow)
async def move_company_board(slug: str, payload: MoveBoardPayload, session: SessionDep) -> dict:
    """Point a company at the careers page it moved to.

    The board is verified again here, never trusted from the request: it must
    be one policy lets RoleBand read and it must answer on its family's own
    route (`board_answers`). The move retires the old binding and withholds
    closure from the new one (`company_store.record_board_move`); the
    company's Coverage notice is reconciled away and its first scan starts.
    """
    if payload.adapter not in ADAPTER_REGISTRY:
        raise api_error(400, ErrorCode.INVALID_INPUT, f"unknown adapter {payload.adapter!r}")
    if collection_access(payload.adapter, company=slug).denied:
        raise api_error(409, ErrorCode.CAREERS_PAGE_REFUSED, "RoleBand may not read that careers page")
    board = DetectedBoard(payload.adapter, payload.board_token, payload.board_region)
    async with public_client(user_agent=get_settings().scraper_user_agent) as client:
        if not await board_answers(board, client):
            raise api_error(409, ErrorCode.CAREERS_PAGE_UNREACHABLE, "That careers page isn't answering")
    try:
        await record_board_move(
            session, slug, adapter=payload.adapter, board_token=payload.board_token,
            board_region=payload.board_region.value if payload.board_region else None,
        )
        await session.commit()
    except CompanyError as exc:
        raise company_error(exc) from exc
    await generate_coverage_notifications(session)
    await session.commit()
    row = await session.get(TrackedCompany, slug)
    assert row is not None
    await _start_first_scans(session, [row])
    counts = await open_counts_by_company(session)
    return _company_out(row, counts.get(slug, 0))


# --- Company Profiles -------------------------------------------------------
# Values are RESOLVED from multi-source claims (profiles/resolve.py), so every
# field ships with its provenance: which source won, how fresh it is, and which
# other sources disagree. The UI renders that, rather than pretending we have a
# single authoritative feed.


def _field_meta(profile: CompanyProfile, field: str) -> dict:
    return (profile.field_meta or {}).get(field) or {}


def _profile_field(profile: CompanyProfile, field: str) -> dict:
    """A value plus everything the UI needs to say how much to trust it."""
    meta = _field_meta(profile, field)
    return {
        "value": getattr(profile, field, None),
        # The source is a code the dashboard names; the stored
        # English label stays in `field_meta` and never reaches the wire.
        "source": meta.get("source"),
        "observed_at": meta.get("observed_at"),
        "freshness": meta.get("freshness"),
        "is_manual": meta.get("is_manual", False),
        "conflicts": [
            {k: v for k, v in conflict.items() if k != "source_label"} for conflict in meta.get("conflicts", [])
        ],
    }


def _plugin_field(resolved: dict | None) -> dict:
    """A field the selected plugin answers, as `_profile_field` shapes ours: its
    value resolved now from its own claims, or empty where it has not read the
    company (never ours in its place)."""
    resolved = resolved or {}
    return {
        "value": resolved.get("value"),
        "source": resolved.get("source"),
        "observed_at": resolved.get("observed_at"),
        "freshness": resolved.get("freshness"),
        "is_manual": False,
        "conflicts": [
            {k: v for k, v in conflict.items() if k != "source_label"} for conflict in resolved.get("conflicts", [])
        ],
    }


PROFILE_SUMMARY_FIELDS = ("is_public", "ticker", "equity_vehicle", "headcount")
#: The slots a company profile is built from; their plugins are what it credits.
PROFILE_SLOTS = (PAY_LEVELS, COMPANY_FACTS, COMPANY_BENEFITS)


@router.get("/api/company-profiles", response_model=CompanyProfileListResponse)
async def company_profiles_list(session: SessionDep, hidden: OffBoardDep) -> dict:
    """All company profiles + their data-health badge (the triage list)."""
    profiles_stmt = select(CompanyProfile).order_by(CompanyProfile.slug)
    if hidden:
        profiles_stmt = profiles_stmt.where(CompanyProfile.slug.notin_(hidden))
    profiles = (await session.execute(profiles_stmt)).scalars().all()

    # "Levels imported" counts the reference ladder only, so the figure keeps
    # meaning one rung each rather than growing with every family harvested.
    providers = await reader_providers(session)
    counts: dict[str, int] = {}
    for rung in admit_levels(
        providers,
        (
            await session.execute(
                select(
                    CompanyCompLevel.company_slug, CompanyCompLevel.family, CompanyCompLevel.provider,
                    CompanyCompLevel.level_label, CompanyCompLevel.aliases, CompanyCompLevel.band,
                    CompanyCompLevel.band_source, CompanyCompLevel.country,
                ).where(reference_ladder(), *level_scope(providers))
            )
        ).all(),
        keep=lambda r: r.band is not None and r.country == OUR_PAY_COUNTRY,
    ):
        counts[rung.company_slug] = counts.get(rung.company_slug, 0) + 1

    # Latest cached quote per public company, so the left rail can show a price
    # inline without a round-trip. Absent for privates (and publics not yet fetched).
    prices = await price_store.latest_price_map(session)

    # Company size from the source answering it: the selected
    # plugin's, resolved from its claims, or ours from the profile column.
    facts_plugin = providers.source_for(COMPANY_FACTS)
    plugin_values = await profile_store.plugin_fields(session, providers) if facts_plugin else {}

    items = []
    for p in profiles:
        switched = profile_store.PLUGIN_FIELDS if facts_plugin else frozenset()
        theirs = plugin_values.get(p.slug, {})
        conflicts = [
            f for f in (p.field_meta or {})
            if f not in switched and (p.field_meta[f] or {}).get("conflicts")
        ] + [f for f in sorted(switched) if (theirs.get(f) or {}).get("conflicts")]
        price = prices.get(p.slug)
        items.append(
            {
                "slug": p.slug,
                "display_name": p.display_name,
                "logo_url": p.logo_url,
                "brand_color": p.brand_color,
                "is_public": p.is_public,
                "ticker": p.ticker,
                "equity_vehicle": p.equity_vehicle,
                "headcount": (theirs.get("headcount") or {}).get("value") if facts_plugin else p.headcount,
                "data_health": p.data_health,
                "conflict_fields": conflicts,
                "mapped_levels": counts.get(p.slug, 0),
                "sectors": list(catalog.sectors) if (catalog := COMPANY_DISCOVERY.get(p.slug)) else [],
                "in_dataset": p.slug in PAY_POLICIES,
                "price": price["price"] if price else None,
                "change_pct": price["change_pct"] if price else None,
                "currency": price["currency"] if price else None,
                "price_as_of": price["as_of"] if price else None,
            }
        )
    return {
        "items": items,
        "sectors": [sector.slug for sector in SECTORS],
        "attribution": providers.attribution(PROFILE_SLOTS),
    }


async def _board_count(session: AsyncSession, slug: str, hidden: list[str]) -> int:
    """The company's open roles as the Board counts them: none when it is off
    the Board (hidden, or not followed), so a "View N open roles"
    link never promises rows its Board will not show."""
    if slug in hidden:
        return 0
    return (await open_counts_by_company(session)).get(slug, 0)


def _level_base_row(slug: str, row: dict[str, str]) -> dict:
    """One `level_base.csv` row as the profile shows it, with the company's
    bonus target where its policy states one (never a guessed 0), its stock
    where the dataset holds it, and a total only when all three are known."""
    def num(name: str) -> int | None:
        return int(row[name]) if row[name] else None

    base = int(row["base_usd"])
    ratio = bonus_ratio_for(slug, row["band"])
    stock = num("stock_usd")
    return {
        "band": row["band"], "base_usd": base,
        "bonus_ratio": None if ratio is None else round(ratio, 4),
        "bonus_usd": None if ratio is None else round(base * ratio), "below_lower": False,
        "stock_usd": stock,
        "total_usd": None if ratio is None or stock is None else base + round(base * ratio) + stock,
    }


@router.get("/api/company-profiles/{slug}", response_model=CompanyProfileDetailResponse)
async def company_profile(slug: str, session: SessionDep, hidden: OffBoardDep) -> dict:
    """One company: resolved identity w/ provenance, comp baseline, benefits."""
    profile = await session.get(CompanyProfile, slug)
    if profile is None:
        raise api_error(404, ErrorCode.COMPANY_PROFILE_NOT_FOUND, "company profile not found")

    # The baseline table is one row per band, read off the reference ladder; the
    # per-family ladders feed the job package, not this panel. It is US pay, as
    # every figure of ours is: a plugin's rungs for another country price only
    # postings there.
    providers = await reader_providers(session)
    levels = admit_levels(providers, (
        await session.execute(
            select(CompanyCompLevel)
            .where(
                CompanyCompLevel.company_slug == slug,
                reference_ladder(),
                *level_scope(providers),
            )
            # Label then id break tc ties, so equal medians never swap places
            # between two reads of the same data.
            .order_by(
                nullslast(CompanyCompLevel.tc_median.desc()),
                CompanyCompLevel.level_label,
                CompanyCompLevel.id,
            )
        )
    ).scalars().all())
    # The rows the estimate reads for a US posting, by the same screen: a
    # worldwide mix or a rung stated for another country is not shown as US pay.
    levels = country_rows(levels, OUR_PAY_COUNTRY)

    benefits = admit_benefits(providers, (
        await session.execute(
            select(CompanyBenefit)
            .where(CompanyBenefit.company_slug == slug, *benefit_scope(providers))
            .order_by(
                CompanyBenefit.category,
                nullslast(CompanyBenefit.value_usd.desc()),
                CompanyBenefit.name,
            )
        )
    ).scalars().all())

    # One source answers: the selected plugin's rows, none for a
    # company it has not read, or our dataset when no plugin is selected.
    # Our per-level base, the reference family, only while no pay
    # plugin is selected: one source answers the section.
    level_base = [] if providers.source_for(PAY_LEVELS) else [
        _level_base_row(slug, row) for row in load_level_base().get((slug, REFERENCE_FAMILY), ())]
    # A level paying less base than the one under it is shown, and said: the
    # figures carry their counts, there is no floor.
    for lower, row in zip(level_base, level_base[1:], strict=False):
        row["below_lower"] = row["base_usd"] < lower["base_usd"]

    benefits_plugin = providers.source_for(COMPANY_BENEFITS)
    benefit_groups = plugin_benefits(benefits) if benefits_plugin else dataset_benefits(slug)
    benefit_notes = [] if benefits_plugin else dataset_benefit_notes(slug)

    # Open-role count for the "View N open roles" jump to the board.
    open_roles = await _board_count(session, slug, hidden)
    unfollowed = slug in await unfollowed_company_slugs(session)

    # Offices & where the open roles are, observed from live postings.
    locations = await _company_locations(session, slug)
    hq = (profile.hq_city or "").strip().lower()
    for loc in locations:
        loc["is_hq"] = bool(hq) and loc["city"].lower().startswith(hq)

    # The choices we offer the user when a field needs review: every source's
    # latest claim, most-trusted first. Suggesting beats making them retype.
    candidates = await profile_store.candidates_for(session, slug)
    # One source per field: ours, except company size while a plugin
    # is selected for facts, which shows the plugin's or nothing.
    facts_plugin = providers.source_for(COMPANY_FACTS)
    plugin_values = (await profile_store.plugin_fields(session, providers, [slug])).get(slug, {})

    fields = {}
    for f in (
        "is_public",
        "ticker",
        "headcount",
        "hq_city",
        "website",
        "equity_vehicle",
        "vesting_schedule",
    ):
        if facts_plugin and f in profile_store.PLUGIN_FIELDS:
            entry = _plugin_field(plugin_values.get(f))
            entry["answered_by"] = facts_plugin
            entry["editable"] = False  # a pin would be ours: refused while the plugin answers
        else:
            entry = _profile_field(profile, f)
            entry["answered_by"] = None
            entry["editable"] = True
        entry["candidates"] = candidates.get(f, [])
        fields[f] = entry

    return {
        "slug": profile.slug,
        "display_name": profile.display_name,
        "logo_url": profile.logo_url,
        "brand_color": profile.brand_color,
        "data_health": profile.data_health,
        "needs_review": _needs_review(profile, fields),
        # Every identity field carries its own provenance + conflicts.
        "fields": fields,
        "comp_levels": [
            {
                "level_label": r.level_label,
                "band": r.band,
                "currency": r.currency,
                "tc_median": r.tc_median,
                "base_amount": r.base_amount,
                "stock_amount": r.stock_amount,
                "bonus_amount": r.bonus_amount,
                "base_pct": r.base_pct,
                "stock_pct": r.stock_pct,
                "bonus_pct": r.bonus_pct,
                "source": r.provider,  # the publisher of the row
                "source_url": r.source_url,
            }
            for r in levels
        ],
        "level_base": level_base,
        # Perks are never summed into a total: overlapping perks and
        # unknown values make any sum a claim nobody measured.
        "benefits": benefit_groups,
        "benefit_notes": benefit_notes,
        "offer_policy": profile_offer(slug),
        "comp_notes": profile.comp_notes,
        "open_roles": open_roles,
        "unfollowed": unfollowed,
        "locations": locations,
        # Credited only where its data shows: not on a company it has not read.
        "attribution": providers.attribution(PROFILE_SLOTS, slug),
        # Sources the dashboard has no name for (a plugin's, or the ones it
        # adopts) are named by the plugin; ours it names from its catalog.
        "source_names": dict(providers.fact_labels),
        "sources": {
            "pay": providers.answering(PAY_LEVELS, slug),
            "benefits": providers.answering(COMPANY_BENEFITS, slug),
            "company_size": providers.answering(COMPANY_FACTS, slug),
        },
    }


def _needs_review(profile: CompanyProfile, fields: dict) -> list[dict]:
    """The manual-enrichment worklist for one company.

    A field needs review when sources disagree (`conflict`), when the winning claim
    has aged past its TTL (`stale`), or when nothing asserts it at all (`missing`).
    Each item carries a `suggestion` — our best guess at the right answer — so the
    workflow is "confirm or correct", not "go find it yourself".
    """
    required = set(profile_store.REQUIRED_FIELDS)
    out: list[dict] = []
    for name, f in fields.items():
        if f["is_manual"]:
            continue  # a human already settled this one
        if not f["editable"]:
            continue  # a plugin answers it: nothing of ours to confirm or correct
        if f["conflicts"]:
            reason = "conflict"
        elif f["freshness"] == "stale":
            reason = "stale"
        elif f["value"] is None and name in required:
            # Only REQUIRED fields count as missing. Optional ones (vesting_schedule)
            # are absent for almost every company and would flood the worklist with
            # noise nobody intends to fill in.
            reason = "missing"
        else:
            continue
        # Suggest the highest-trust candidate that actually asserts a value.
        suggestion = next(
            (c for c in f["candidates"] if c["value"] is not None), None
        )
        out.append(
            {
                "field": name,
                "reason": reason,
                "current": f["value"],
                "suggestion": suggestion,
                "candidates": f["candidates"],
            }
        )
    order = {"conflict": 0, "stale": 1, "missing": 2}
    out.sort(key=lambda i: order.get(i["reason"], 9))
    return out


class ProfileFieldUpdate(BaseModel):
    field: str
    value: object | None = None


@router.patch("/api/company-profiles/{slug}", response_model=CompanyProfileFieldWrite)
async def company_profile_set_manual(
    slug: str, body: ProfileFieldUpdate, session: SessionDep
) -> dict:
    """Pin a human value for one field. Outranks every source, now and on refresh."""
    if body.field not in profile_store.PROFILE_FIELDS:
        raise api_error(400, ErrorCode.INVALID_INPUT, f"unknown field: {body.field}")
    if await session.get(CompanyProfile, slug) is None:
        raise api_error(404, ErrorCode.COMPANY_PROFILE_NOT_FOUND, "company profile not found")
    try:
        health = await profile_store.set_manual(session, slug, body.field, body.value)
    except profile_store.AnsweredByPlugin as refused:
        raise api_error(409, ErrorCode.FIELD_ANSWERED_BY_PLUGIN, str(refused)) from None
    return {"slug": slug, "field": body.field, "health": health}


@router.delete(
    "/api/company-profiles/{slug}/manual/{field}", response_model=CompanyProfileFieldWrite
)
async def company_profile_clear_manual(
    slug: str, field: str, session: SessionDep
) -> dict:
    """Un-pin a field and fall back to source resolution."""
    if field not in profile_store.PROFILE_FIELDS:
        raise api_error(400, ErrorCode.INVALID_INPUT, f"unknown field: {field}")
    if await session.get(CompanyProfile, slug) is None:
        raise api_error(404, ErrorCode.COMPANY_PROFILE_NOT_FOUND, "company profile not found")
    health = await profile_store.clear_manual(session, slug, field)
    return {"slug": slug, "field": field, "health": health}


@router.get("/api/company-profiles/{slug}/claims", response_model=CompanyClaimsResponse)
async def company_claims(slug: str, session: SessionDep) -> dict:
    """Raw evidence: every claim every source has made. The audit trail behind a
    conflict badge — "what did we believe, when, and on whose word?"."""
    providers = await reader_providers(session)
    # The claims of the source answering each field: ours, except
    # company size while a plugin is selected for facts.
    plugin = providers.source_for(COMPANY_FACTS)
    ours = CompanyFact.source.in_(sorted(CORE_SOURCES))
    if plugin is not None:
        switched = CompanyFact.field.in_(sorted(profile_store.PLUGIN_FIELDS))
        shown = or_(and_(~switched, ours),
                    and_(switched, providers.where(COMPANY_FACTS, CompanyFact.source, CompanyFact.company_slug)))
    else:
        shown = ours
    rows = (
        await session.execute(
            select(CompanyFact)
            .where(CompanyFact.company_slug == slug, shown)
            .order_by(CompanyFact.field, CompanyFact.observed_at.desc())
        )
    ).scalars().all()
    return {
        "slug": slug,
        "claims": [
            {
                "field": r.field,
                "value": (r.value or {}).get("v"),
                "source": r.source,
                "rank": providers.rank_of(r.source),
                "observed_at": r.observed_at,
            }
            for r in rows
        ],
    }


# Price-history ranges the profile sparkline offers, mapped to a lookback window.
_PRICE_RANGES = {"1m": 31, "3m": 93, "6m": 186, "1y": 366}


@router.get("/api/company-profiles/{slug}/prices", response_model=CompanyPricesResponse)
async def company_prices(
    slug: str, session: SessionDep, range: str = Query("3m")
) -> dict:
    """Daily OHLC bars for one company's sparkline. Empty (not 404) when a company
    simply has no prices — a private company is a valid, price-less profile. The
    credit names the source of the bars shown, and `feed_configured` says whether
    a price key is set, so an empty chart can say what to do."""
    if await session.get(CompanyProfile, slug) is None:
        raise api_error(404, ErrorCode.COMPANY_PROFILE_NOT_FOUND, "company profile not found")
    days = _PRICE_RANGES.get(range, _PRICE_RANGES["3m"])
    since = datetime.now(UTC).date() - timedelta(days=days)
    bars = await price_store.price_history(session, slug, since)
    quote = (await price_store.latest_price_map(session, [slug])).get(slug)
    return {
        "slug": slug,
        "range": range if range in _PRICE_RANGES else "3m",
        "currency": (quote or {}).get("currency", "USD"),
        "latest": quote,
        "bars": bars,
        "attribution": await price_store.shown_attribution(session, slug) if bars else None,
        "feed_configured": (await price_store.api_key(session, get_settings()))[0] is not None,
    }


@router.get("/api/companies/{slug}/card", response_model=CompanyCardResponse)
async def company_card(slug: str, session: SessionDep, hidden: OffBoardDep) -> dict:
    """Compact hover-card payload for a company chip on a job row: identity, latest
    price, and open-role count. Falls back to the raw slug when no profile exists so
    the card still renders (and still deep-links to the board)."""
    profile = await session.get(CompanyProfile, slug)
    open_roles = await _board_count(session, slug, hidden)
    price = (await price_store.latest_price_map(session, [slug])).get(slug)
    top_cities = [loc["city"] for loc in (await _company_locations(session, slug))[:3]]
    return {
        "slug": slug,
        "display_name": profile.display_name if profile else slug.replace("-", " ").title(),
        "logo_url": profile.logo_url if profile else None,
        "brand_color": profile.brand_color if profile else None,
        "ticker": profile.ticker if profile else None,
        "is_public": bool(profile.is_public) if profile else False,
        "has_profile": profile is not None,
        "open_roles": open_roles,
        "unfollowed": slug in await unfollowed_company_slugs(session),
        "top_cities": top_cities,
        "price": price["price"] if price else None,
        "change_pct": price["change_pct"] if price else None,
        "currency": price["currency"] if price else None,
        "price_as_of": price["as_of"] if price else None,
    }
