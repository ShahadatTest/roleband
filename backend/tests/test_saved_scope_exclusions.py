"""A saved-scope recompute excludes exactly what ingest excludes, missing fields included.

`db/repo.py::scope_exclusion_expr` is the SQL half of `enricher.rule_excluded`.
A rule names a company's verbatim team or department, and a posting whose field
is missing has nothing to match, so ingest keeps it. Compared as
`lower(trim(NULL))`, which is NULL, such a posting would make the whole scope
expression NULL wherever the scope otherwise included it, and the recompute
would write NULL into `jobs.in_scope`, a NOT NULL column: the save, and every
later scope save, rule change and suggestion accept, would fail with a 500.

Real Postgres, because three-valued logic is the defect: a compiled-SQL string
check cannot see what NULL does to it.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from tracker.db.models import CompanyScopeRule, Job, TrackedCompany
from tracker.db.queries.scope import load_scope_exclusions
from tracker.db.repo import apply_saved_scope_to_jobs
from tracker.enrich.enricher import rule_excluded
from tracker.schema import RawJob
from tracker.scope.projection import recompute_saved_scope
from tracker.settings_store import (
    set_enabled_bands,
    set_enabled_domains,
    set_enabled_locations,
    set_enabled_roles,
    set_enabled_tracks,
)

#: `PUT /api/settings` starts the directory scan when the set is followed.
pytestmark = pytest.mark.usefixtures("no_escape")

T0 = datetime(2026, 7, 1, 12, 0, tzinfo=UTC)
AXES = {
    "enabled_role_groups": ["software_engineering"],
    "enabled_seniority_bands": ["staff"],
    "enabled_role_tracks": ["technical"],
    "enabled_location_groups": ["uk"],
    "enabled_domain_groups": ["ai_ml"],
}

#: posting -> (company, team, department, excluded by the rules below)
POSTINGS = {
    "team_matches": ("acme", "Ads Sales", None, True),
    "team_matches_loosely": ("acme", "  ads sales ", None, True),
    "team_missing": ("acme", None, None, False),
    "team_blank": ("acme", "", "Platform", False),
    "team_longer_name": ("acme", "Ads Sales Ops", None, False),
    "department_matches": ("acme", None, "Operations", True),
    "department_missing": ("acme", "Search", None, False),
    "other_company": ("globex", "Ads Sales", "Operations", False),
}


def _job(key: str, company: str = "acme", **over) -> Job:
    row = {
        "company": company,
        "req_id": key,
        "dedupe_key": f"{company}:{key}",
        "title": f"Staff Software Engineer, {key}",
        "url": f"https://careers.example.test/{company}/{key}",
        "locations": ["London, UK"],
        "location_groups": ["uk"],
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
        "team": None,
        "department": None,
    }
    row.update(over)
    return Job(**row)


@pytest.mark.asyncio
async def test_a_recompute_excludes_exactly_what_ingest_excludes(db_session):
    db_session.add_all(
        _job(key, company, team=team, department=department)
        for key, (company, team, department, _) in POSTINGS.items()
    )
    # Out of scope on its own axes: a missing team must not bring it back in.
    db_session.add(_job("out_of_scope", level_band="junior"))
    db_session.add_all([
        CompanyScopeRule(company="acme", kind="team", value="Ads Sales", created_at=T0),
        CompanyScopeRule(company="acme", kind="department", value="Operations", created_at=T0),
    ])
    await db_session.commit()

    changed = await apply_saved_scope_to_jobs(db_session, *AXES.values(), excluded_domains=[], answers=None, excluded_locations=[], include_unstated_level=False)
    await db_session.commit()

    rows = (await db_session.execute(
        select(Job.req_id, Job.company, Job.team, Job.department, Job.in_scope)
    )).all()
    assert {row.req_id: row.in_scope for row in rows} == {
        **{key: not excluded for key, (*_, excluded) in POSTINGS.items()},
        "out_of_scope": False,
    }
    assert changed == sum(excluded for *_, excluded in POSTINGS.values()) + 1

    # And row for row, the two gates agree.
    exclusions = await load_scope_exclusions(db_session)
    for row in rows:
        if row.req_id == "out_of_scope":
            continue
        posting = RawJob(
            company=row.company, req_id=row.req_id, title="x", url="u", locations=[],
            team=row.team, department=row.department,
        )
        assert row.in_scope is not rule_excluded(posting, exclusions), row.req_id


@pytest.mark.asyncio
async def test_a_rule_for_a_company_with_unlabelled_postings_saves_and_scope_still_saves(
    api_client, db_session
):
    """The failure, over HTTP: a scope that includes a posting with no
    team, then a team rule for its company."""
    db_session.add(TrackedCompany(
        slug="acme", display="Acme", adapter="greenhouse", status="active", enabled=True,
        visible=True, source="catalog", role_catalog_status="ready",
    ))
    db_session.add_all([_job("unlabelled"), _job("ads", team="Ads Sales")])
    await db_session.commit()
    assert (await api_client.put("/api/settings", json=AXES)).status_code == 200

    created = await api_client.post(
        "/api/scope/rules", json={"company": "acme", "kind": "team", "value": "Ads Sales"}
    )
    assert created.status_code == 200, created.text
    assert created.json()["in_scope_changed"] == 1

    saved = await api_client.put("/api/settings", json=AXES)
    assert saved.status_code == 200, saved.text
    in_scope = dict((await db_session.execute(select(Job.req_id, Job.in_scope))).all())
    assert in_scope == {"unlabelled": True, "ads": False}


@pytest.mark.asyncio
async def test_the_projection_rule_changes_and_suggestion_accept_share_holds_the_same_line(db_session):
    """`scope.projection.recompute_saved_scope` reads the saved axes and the
    rules itself; rule create and delete and suggestion accept all go through
    it, so it is asserted by name rather than by one of its callers."""
    for setter, key in [
        (set_enabled_roles, "enabled_role_groups"), (set_enabled_bands, "enabled_seniority_bands"),
        (set_enabled_tracks, "enabled_role_tracks"), (set_enabled_locations, "enabled_location_groups"),
        (set_enabled_domains, "enabled_domain_groups"),
    ]:
        await setter(db_session, AXES[key])
    db_session.add_all([
        _job("unlabelled"), _job("ads", team="Ads Sales"), _job("ops", department="Operations"),
        CompanyScopeRule(company="acme", kind="team", value="Ads Sales", created_at=T0),
        CompanyScopeRule(company="acme", kind="department", value="Operations", created_at=T0),
    ])
    await db_session.commit()

    assert await recompute_saved_scope(db_session) == 2
    await db_session.commit()

    in_scope = dict((await db_session.execute(select(Job.req_id, Job.in_scope))).all())
    assert in_scope == {"unlabelled": True, "ads": False, "ops": False}
