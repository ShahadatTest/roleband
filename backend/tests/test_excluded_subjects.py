""""Not interested in X" is a veto: a role tagged X leaves, whatever else it is about.

The worlds axis keeps a role when ANY of its subjects is on, so it cannot say
"not interested": a role tagged advertising and AI would stay on the radar of
someone not interested in advertising. The excluded list is its own
setting, and every gate reads it: ingest (`passes_filters`), the saved-scope
recompute (`job_scope_expr`), and the save endpoints that write it.

Real Postgres for the SQL half, because NULL domains are the trap: an overlap
with NULL is NULL, and a NOT over it would write NULL into `in_scope`.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from tracker.db.models import Job
from tracker.db.repo import apply_saved_scope_to_jobs
from tracker.enrich.enricher import Annotation, ScopeFilter, passes_filters
from tracker.schema import LevelBand, LevelConfidence, RoleTrack
from tracker.taxonomy.domains import all_slugs

#: `PUT /api/settings` starts the directory scan when the set is followed.
pytestmark = pytest.mark.usefixtures("no_escape")

T0 = datetime(2026, 9, 26, 12, 0, tzinfo=UTC)
AXES = {
    "enabled_role_groups": ["software_engineering"],
    "enabled_seniority_bands": ["staff"],
    "enabled_role_tracks": ["technical"],
    "enabled_location_groups": ["uk"],
    "enabled_domain_groups": all_slugs(),
}

#: posting -> (domains, kept when advertising is excluded)
POSTINGS = {
    "untagged_null": (None, True),
    "untagged_empty": ([], True),
    "ai_only": (["ai_ml"], True),
    "ai_and_advertising": (["ai_ml", "advertising"], False),
    "advertising_only": (["advertising"], False),
}


def _scope(**over) -> ScopeFilter:
    fields = {
        "enabled_bands": frozenset({"staff"}),
        "enabled_roles": frozenset({"software_engineering"}),
        "enabled_tracks": frozenset({"technical"}),
        "enabled_locations": frozenset({"uk"}),
        "enabled_domains": frozenset(all_slugs()),
    }
    fields.update(over)
    return ScopeFilter(**fields)


def _annotation(domains: list[str]) -> Annotation:
    return Annotation(
        band=LevelBand.STAFF, confidence=LevelConfidence.CONFIRMED, family="software_engineering",
        location_groups=["uk"], track=RoleTrack.TECHNICAL, domains=domains,
    )


def _job(key: str, domains: list[str] | None) -> Job:
    return Job(
        company="acme", req_id=key, dedupe_key=f"acme:{key}", title=f"Staff Software Engineer, {key}",
        url=f"https://careers.example.test/acme/{key}", locations=["London, UK"],
        location_groups=["uk"], domains=domains, workplace_type="onsite", level_band="staff",
        level_confidence="confirmed", family="software_engineering", track="technical",
        comp_currency="USD", status="open", in_scope=True, first_seen=T0, last_seen=T0,
        description_sections=[],
    )


@pytest.mark.parametrize(("key", "domains", "kept"), [
    (key, domains or [], kept) for key, (domains, kept) in POSTINGS.items()
])
def test_ingest_drops_a_role_tagged_with_an_excluded_subject_whatever_else_it_is_about(
    key, domains, kept
):
    assert passes_filters(_annotation(domains), _scope(excluded_domains=frozenset({"advertising"}))) is kept
    # Without the veto every one of them passes: the worlds axis is all on.
    assert passes_filters(_annotation(domains), _scope()) is True


def test_the_veto_wins_over_an_interest_in_another_of_the_roles_subjects():
    scope = _scope(enabled_domains=frozenset({"ai_ml"}), excluded_domains=frozenset({"advertising"}))
    assert passes_filters(_annotation(["ai_ml", "advertising"]), scope) is False
    assert passes_filters(_annotation(["ai_ml"]), scope) is True


@pytest.mark.asyncio
async def test_the_saved_scope_recompute_applies_the_veto_and_never_writes_null(db_session):
    db_session.add_all(_job(key, domains) for key, (domains, _) in POSTINGS.items())
    await db_session.commit()

    changed = await apply_saved_scope_to_jobs(
        db_session, *AXES.values(), excluded_domains=["advertising"], answers=None, excluded_locations=[], include_unstated_level=False
    )
    await db_session.commit()

    in_scope = dict((await db_session.execute(select(Job.req_id, Job.in_scope))).all())
    assert in_scope == {key: kept for key, (_, kept) in POSTINGS.items()}
    assert changed == 2
    # And row for row, the SQL gate agrees with the ingest gate.
    scope = _scope(excluded_domains=frozenset({"advertising"}))
    for key, (domains, _) in POSTINGS.items():
        assert in_scope[key] is passes_filters(_annotation(domains or []), scope), key


@pytest.mark.asyncio
async def test_settings_save_the_excluded_list_echo_it_and_keep_it_when_a_save_omits_it(
    api_client, db_session
):
    db_session.add_all(_job(key, domains) for key, (domains, _) in POSTINGS.items())
    await db_session.commit()

    saved = await api_client.put("/api/settings", json={**AXES, "excluded_domain_groups": ["advertising", "nope"]})
    assert saved.status_code == 200, saved.text
    # Unknown slugs are dropped, the rest listed in taxonomy order.
    assert saved.json()["excluded_domain_groups"] == ["advertising"]
    assert saved.json()["in_scope_changed"] == 2
    assert (await api_client.get("/api/settings")).json()["excluded_domain_groups"] == ["advertising"]

    # A client that does not send the field leaves the veto where it was.
    again = await api_client.put("/api/settings", json=AXES)
    assert again.json()["excluded_domain_groups"] == ["advertising"]
    assert again.json()["in_scope_changed"] == 0

    # An empty list lifts it, and the roles come back.
    lifted = await api_client.put("/api/settings", json={**AXES, "excluded_domain_groups": []})
    assert lifted.json()["excluded_domain_groups"] == []
    assert lifted.json()["in_scope_changed"] == 2


@pytest.mark.asyncio
async def test_a_save_with_levels_writes_the_excluded_list_too(api_client, db_session):
    db_session.add_all(_job(key, domains) for key, (domains, _) in POSTINGS.items())
    await db_session.commit()

    saved = await api_client.put("/api/settings", json={
        "enabled_role_groups": ["software_engineering"], "enabled_seniority_bands": [],
        "enabled_role_tracks": ["technical"], "enabled_location_groups": ["uk"],
        "experience_stage": "staff", "target_stage": "staff",
        "excluded_domain_groups": ["advertising"],
    })
    assert saved.status_code == 200, saved.text
    assert saved.json()["excluded_domain_groups"] == ["advertising"]
    in_scope = dict((await db_session.execute(select(Job.req_id, Job.in_scope))).all())
    assert in_scope == {key: kept for key, (_, kept) in POSTINGS.items()}
