"""A posting with no family is out of scope, never NULL.

`family` is the one nullable column the scope gate compares bare: `family IN
(...)` is NULL for a posting whose family is unknown. Where the posting's
place is tracked, that NULL is the whole expression, and the recompute writes
it into `jobs.in_scope`, a NOT NULL column: the save fails. Where the place is
not tracked, FALSE AND NULL is FALSE, which is why only a tracked place shows
it. Ingest (`passes_filters`, `answer_admits`) keeps such a posting out, so
the stored projection must say False, on both role paths: the flat role axis
and the role answers.

Real Postgres, because three-valued logic is the defect.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from tracker.db.models import Job
from tracker.db.repo import apply_saved_scope_to_jobs
from tracker.taxonomy.role_answers import RoleAnswer

T0 = datetime(2026, 7, 1, 12, 0, tzinfo=UTC)
ROLES = ["software_engineering"]
BANDS = ["staff"]
TRACKS = ["technical"]
LOCATIONS = ["uk"]


def _job(key: str, *, family: str | None, location_groups: list[str]) -> Job:
    return Job(
        company="acme", req_id=key, dedupe_key=f"acme:{key}", title="Staff Engineer",
        url=f"https://careers.example.test/acme/{key}", locations=["London, UK"],
        location_groups=location_groups, domains=None, workplace_type="onsite", level_band="staff",
        level_confidence="confirmed", family=family, track="technical", comp_currency="USD",
        status="open", in_scope=True, first_seen=T0, last_seen=T0, description_sections=[],
    )


async def _seed(db) -> None:
    db.add_all([
        _job("known_tracked", family="software_engineering", location_groups=["uk"]),
        _job("unknown_tracked", family=None, location_groups=["uk"]),
        _job("unknown_untracked", family=None, location_groups=["germany"]),
    ])
    await db.commit()


async def _projected(db) -> dict[str, bool]:
    return dict((await db.execute(select(Job.req_id, Job.in_scope))).all())


@pytest.mark.asyncio
@pytest.mark.parametrize("answers", [
    None,
    [RoleAnswer("technical", frozenset(ROLES))],
    [RoleAnswer("technical", None)],
], ids=["role axis", "answer with families", "answer for any family"])
async def test_a_posting_with_no_family_projects_out_of_scope(db_session, answers):
    await _seed(db_session)
    await apply_saved_scope_to_jobs(
        db_session, ROLES, BANDS, TRACKS, LOCATIONS, [], excluded_domains=[], answers=answers,
        excluded_locations=[], include_unstated_level=False,
    )
    await db_session.commit()
    assert await _projected(db_session) == {
        "known_tracked": True,  # control: the gate admits a posting it knows
        "unknown_tracked": False,
        "unknown_untracked": False,
    }
