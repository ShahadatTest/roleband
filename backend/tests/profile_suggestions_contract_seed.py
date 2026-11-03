"""Realistic rows for the profile suggestion contract.

Every timestamp is fixed, so two runs of the same request return the same bytes.
Each `basis` is built by the real inference (`suggest_worlds`), never restated:
a key the writer adds reaches these rows, and with them the contract's exact-key
checks: the writer is the only witness to the stored shape.

| row | what it exercises |
|---|---|
| `narrow` | pending `world_off:advertising`: two wrong-world passes and one other, no sector, no intent |
| `widen` | pending `world_on:media_entertainment`: a save, a pursuit, a followed sector, the intent line |
| `early` | pending `world_on:payments_fintech`, from a pursuit and a background entry, created first |
| `accepted` | `world_off:ai_ml`, already accepted: never listed, and a second verdict is refused |
| `dismissed` | `world_on:security_privacy`, already dismissed: the same, naming its own status |

The list orders by `created_at` and then `id`: `early` comes first, and `narrow`
and `widen` share a timestamp so their order is the id tie-break.

Six open roles give an accept something to move. Under `PERSONA` the two
advertising roles, the ai_ml role and the unclassified one are in scope; the
media_entertainment and payments_fintech roles are not, because `PERSONA`
enables every world except those two.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from tracker.db.models import Job, ProfileSuggestion, TrackedCompany
from tracker.taxonomy.domains import all_slugs, get_group
from tracker.user_profile.inference import WorldSignals, WorldSuggestion, suggest_worlds

T0 = datetime(2026, 7, 1, 12, 0, tzinfo=UTC)

#: Worlds the persona leaves out, so a `world_on` for them is a real widening.
EXCLUDED_WORLDS = ("media_entertainment", "payments_fintech")

#: A persona as the current writer stores it, without an intent line: saving one
#: would embed it, and no test here needs the model.
PERSONA = {
    "experience_stage": "staff",
    "target_stage": "principal",
    "crafts": ["technical"],
    "disciplines": ["software_engineering"],
    "locations": ["uk"],
    "domains": [slug for slug in all_slugs() if slug not in EXCLUDED_WORLDS],
}


def settings_body(persona: dict) -> dict:
    """The one save path's body for a persona-shaped fixture."""
    return {
        "enabled_role_groups": persona["disciplines"], "enabled_seniority_bands": [],
        "enabled_role_tracks": persona["crafts"], "enabled_location_groups": persona["locations"],
        "enabled_domain_groups": persona["domains"],
        "experience_stage": persona["experience_stage"], "target_stage": persona["target_stage"],
    }


@dataclass(frozen=True)
class SeededSuggestions:
    narrow: int
    widen: int
    early: int
    accepted: int
    dismissed: int


def _intent_naming(world: str) -> str:
    group = get_group(world)
    assert group is not None, world
    return f"Staff roles in {sorted(group.keywords)[0].strip()}"


def _raised(kind: str, world: str, signals: WorldSignals) -> WorldSuggestion:
    """The suggestion inference raises for these signals: the writer's own basis."""
    enabled = frozenset(all_slugs()) - {world} if kind == "world_on" else frozenset(all_slugs())
    raised = [s for s in suggest_worlds(signals, enabled) if (s.kind, s.world) == (kind, world)]
    assert raised, f"these signals no longer raise {kind}:{world}; the seed needs new ones"
    return raised[0]


def _row(suggestion: WorldSuggestion, *, created_at: datetime, status: str = "pending") -> ProfileSuggestion:
    return ProfileSuggestion(
        kind=suggestion.kind,
        dedupe_key=suggestion.dedupe_key,
        payload={"world": suggestion.world},
        basis=suggestion.basis,
        status=status,
        created_at=created_at,
        resolved_at=None if status == "pending" else T0,
    )


def _job(key: str, domains: list[str]) -> Job:
    return Job(
        company="acme",
        req_id=key,
        dedupe_key=f"acme:{key}",
        title=f"Staff Software Engineer, {key}",
        url=f"https://careers.example.test/acme/{key}",
        locations=["London, UK"],
        location_groups=["uk"],
        domains=domains,
        workplace_type="onsite",
        level_band="staff",
        level_confidence="confirmed",
        family="software_engineering",
        track="technical",
        comp_currency="USD",
        status="open",
        in_scope=False,
        first_seen=T0,
        last_seen=T0,
        description_sections=[],
    )


async def seed_profile_suggestions(session: AsyncSession) -> SeededSuggestions:
    widen = _raised("world_on", "media_entertainment", WorldSignals(
        favorited={"media_entertainment": 1},
        pursued={"media_entertainment": 1},
        tracked_sectors=("gaming",),
        intent_statement=_intent_naming("media_entertainment"),
    ))
    assert widen.basis["sectors"] == ["gaming"] and widen.basis["intent_matched"] is True, widen.basis

    rows = {
        "narrow": _row(_raised("world_off", "advertising", WorldSignals(
            dismissed_wrong_domain={"advertising": 2}, dismissed_other={"advertising": 1},
        )), created_at=T0 + timedelta(hours=1)),
        "widen": _row(widen, created_at=T0 + timedelta(hours=1)),
        "early": _row(_raised("world_on", "payments_fintech", WorldSignals(
            pursued={"payments_fintech": 1}, background={"payments_fintech": 1},
        )), created_at=T0),
        "accepted": _row(_raised("world_off", "ai_ml", WorldSignals(
            dismissed_wrong_domain={"ai_ml": 3},
        )), created_at=T0 - timedelta(days=1), status="accepted"),
        "dismissed": _row(_raised("world_on", "security_privacy", WorldSignals(
            favorited={"security_privacy": 2},
        )), created_at=T0 - timedelta(days=1), status="dismissed"),
    }

    session.add(TrackedCompany(
        slug="acme", display="Acme", adapter="greenhouse", board_token="acme",
        careers_url="https://careers.example.test/acme", status="active", enabled=True,
        visible=True, source="catalog", role_catalog_status="ready",
        role_catalog_scanned_at=T0, role_catalog_error=None, created_at=T0,
    ))
    session.add_all([
        _job("ads-1", ["advertising"]),
        _job("ads-2", ["advertising"]),
        _job("ai-1", ["ai_ml"]),
        _job("unclassified-1", []),
        _job("media-1", ["media_entertainment"]),
        _job("pay-1", ["payments_fintech"]),
    ])
    # One flush per suggestion, so ids follow the table above.
    for row in rows.values():
        session.add(row)
        await session.flush()
    await session.commit()
    return SeededSuggestions(**{name: row.id for name, row in rows.items()})
