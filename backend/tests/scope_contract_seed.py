"""Realistic rows for the scope, settings and profile contract.

Every timestamp is fixed, so two runs of the same request return the same bytes.
The rows cover each branch `build_scope_catalog` and the settings router can take:

| row | what it exercises |
|---|---|
| `google` | builtin, catalog `ready`, a `company_wide` decoder ladder, joint band x track counts |
| `apple` | builtin, catalog `ready`, a `per_track` decoder ladder |
| `acme` | catalog-sourced greenhouse board, catalog `partial`, no joint counts (so joint impact is off) |
| `pending_co` | `pending`, never scanned: its catalog rows are skipped and its timestamp is null |
| `hidden_co` | not visible: its catalog row and open job are excluded from every count |

Nothing is stored for the five scope axes or the persona, so a test starts from
the defaults and sets what it needs through the API or `store_persona`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from tracker.db.models import AppSetting, CompanyScopeRule, Job, RoleCatalog, TrackedCompany
from tracker.settings_store import INTENT_EMBEDDING_KEY, PERSONA_PROFILE_KEY
from tracker.taxonomy.role_catalog import UNCLASSIFIED_KEY

T0 = datetime(2026, 7, 1, 12, 0, tzinfo=UTC)

#: A persona as the current writer stores it: every key present.
CURRENT_PERSONA = {
    "experience_stage": "staff",
    "target_stage": "principal",
    "crafts": ["technical"],
    "disciplines": ["software_engineering"],
    "locations": ["silicon_valley", "uk"],
    "domains": ["ai_ml"],
    "intent_statement": "Platform leadership in applied AI",
}

#: A persona saved before the worlds axis and the intent line existed.
LEGACY_PERSONA = {
    key: CURRENT_PERSONA[key]
    for key in ("experience_stage", "target_stage", "crafts", "disciplines", "locations")
}


@dataclass(frozen=True)
class SeededScope:
    rule_id: int


def _company(slug: str, display: str, **over) -> TrackedCompany:
    row = {
        "slug": slug,
        "display": display,
        "adapter": "greenhouse",
        "board_token": None,
        "careers_url": None,
        "status": "active",
        "enabled": True,
        "visible": True,
        "source": "catalog",
        "role_catalog_status": "ready",
        "role_catalog_scanned_at": T0,
        "role_catalog_error": None,
        "created_at": T0,
    }
    row.update(over)
    return TrackedCompany(**row)


def _job(company: str, key: str, **over) -> Job:
    row = {
        "company": company,
        "req_id": key,
        "dedupe_key": f"{company}:{key}",
        "title": f"Staff Software Engineer, {key}",
        "url": f"https://careers.example.test/{company}/{key}",
        "locations": ["Mountain View, CA, USA"],
        "location_groups": ["silicon_valley", "united_states"],
        "domains": ["ai_ml"],
        "workplace_type": "onsite",
        "level_band": "staff",
        "level_confidence": "confirmed",
        "family": "software_engineering",
        "track": "technical",
        "comp_currency": "USD",
        "status": "open",
        "in_scope": True,
        "first_seen": T0,
        "last_seen": T0,
        "description_sections": [],
    }
    row.update(over)
    return Job(**row)


async def seed_scope_contract(session: AsyncSession) -> SeededScope:
    session.add_all([
        _company("google", "Google", adapter="google", source="builtin"),
        _company("apple", "Apple", adapter="apple", source="builtin"),
        _company(
            "acme", "Acme", board_token="acme", careers_url="https://acme.example.test/careers",
            role_catalog_status="partial",
        ),
        _company(
            "pending_co", "Pending Co", adapter=None, status="pending", source="url",
            role_catalog_status="pending", role_catalog_scanned_at=None,
        ),
        _company("hidden_co", "Hidden Co", visible=False),
    ])
    session.add_all([
        RoleCatalog(
            role_group="software_engineering", company="google", count=3,
            band_counts={"staff": 2, "senior": 1},
            band_track_counts={"staff": {"technical": 2}, "senior": {"technical": 1}},
            examples=["Staff Software Engineer", "Senior Software Engineer"],
            domain_counts={"ai_ml": 2, UNCLASSIFIED_KEY: 1},
            domain_examples={"ai_ml": ["Applied AI"]},
            updated_at=T0,
        ),
        RoleCatalog(
            role_group="software_engineering", company="apple", count=1,
            band_counts={"principal": 1},
            band_track_counts={"principal": {"technical": 1}},
            examples=["Principal Engineer"],
            domain_counts={"ai_ml": 1},
            domain_examples={"ai_ml": ["Machine Learning Platform"]},
            updated_at=T0,
        ),
        # A legacy row: counts, but no joint band x track breakdown.
        RoleCatalog(
            role_group="product_management", company="acme", count=2,
            band_counts={"principal": 2}, band_track_counts={},
            examples=["Principal Product Manager"],
            domain_counts={"logistics_fulfillment": 2},
            domain_examples={"logistics_fulfillment": ["Fulfillment & Operations Management"]},
            updated_at=T0,
        ),
        RoleCatalog(
            role_group="software_engineering", company="pending_co", count=5,
            band_counts={"staff": 5}, examples=["Never counted"], updated_at=T0,
        ),
        RoleCatalog(
            role_group="software_engineering", company="hidden_co", count=7,
            band_counts={"staff": 7}, examples=["Never shown"], updated_at=T0,
        ),
    ])
    session.add_all([
        _job("google", "sv"),
        _job("google", "london", locations=["London, UK"], location_groups=["uk"]),
        _job("acme", "ops", title="Principal Product Manager, Ops", family="product_management",
             track="product_program", level_band="principal", department="Operations",
             locations=["London, UK"], location_groups=["uk"], domains=["logistics_fulfillment"]),
        _job("hidden_co", "never", location_groups=["uk"]),
        _job("google", "closed", status="closed", closed_at=T0),
    ])
    rule = CompanyScopeRule(company="acme", kind="department", value="Operations", created_at=T0)
    session.add(rule)
    await session.commit()
    return SeededScope(rule_id=rule.id)


async def store_persona(session: AsyncSession, profile: dict | None) -> None:
    """Write the persona row directly, as an older version of the app left it."""
    existing = await session.get(AppSetting, PERSONA_PROFILE_KEY)
    if profile is None:
        if existing is not None:
            await session.delete(existing)
    elif existing is None:
        session.add(AppSetting(key=PERSONA_PROFILE_KEY, value=profile))
    else:
        existing.value = profile
    await session.commit()


async def store_intent_record(session: AsyncSession, statement: str) -> None:
    """The standing intent vector a profile-less (fine-tune only) install keeps.

    Replaces any record a save through the API already wrote.
    """
    value = {"statement": statement, "model": "test-model", "tier": "base", "vector": [0.1, 0.2]}
    existing = await session.get(AppSetting, INTENT_EMBEDDING_KEY)
    if existing is None:
        session.add(AppSetting(key=INTENT_EMBEDDING_KEY, value=value))
    else:
        existing.value = value
    await session.commit()
