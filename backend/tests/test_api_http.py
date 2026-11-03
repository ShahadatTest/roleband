"""Business HTTP contracts: request parsing, JSON and committed Postgres state."""

from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import event, func, select

from tracker.db.models import Favorite, Job, Pursuit, PursuitEvent

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def jobs(db_session):
    now = datetime.now(UTC)
    rows = []
    for index, (company, status, in_scope) in enumerate([
        ("google", "open", True), ("amazon", "open", True),
        ("google", "closed", True), ("google", "open", False),
    ]):
        row = Job(
            company=company, req_id=str(index), dedupe_key=f"{company}:{index}",
            title=f"Staff Product Manager {index}", url=f"https://example.test/jobs/{index}",
            level_band="staff", family="product_management", track="product_program",
            locations=["San Francisco, CA, USA"], location_groups=["silicon_valley"],
            status=status, in_scope=in_scope,
            first_seen=now - timedelta(days=index + 1), last_seen=now,
        )
        db_session.add(row)
        rows.append(row)
    await db_session.commit()
    return rows


async def test_jobs_defaults_and_explicit_all_status_are_different_http_contracts(api_client, jobs):
    response = await api_client.get("/api/jobs")
    assert response.status_code == 200
    body = response.json()
    assert (body["total"], body["limit"], body["offset"]) == (2, 50, 0)
    assert [row["id"] for row in body["items"]] == [jobs[0].id, jobs[1].id]
    first = body["items"][0]
    assert first["title"] == jobs[0].title
    assert first["is_favorite"] is False
    assert first["comp_median"] is None
    assert datetime.fromisoformat(first["first_seen"]) == jobs[0].first_seen

    response = await api_client.get("/api/jobs", params={
        "status": "", "sort": "first_seen", "order": "asc", "limit": 2, "offset": 1,
    })
    assert response.status_code == 200
    body = response.json()
    assert (body["total"], body["limit"], body["offset"]) == (3, 2, 1)
    assert [row["id"] for row in body["items"]] == [jobs[1].id, jobs[0].id]
    all_rows = (await api_client.get("/api/jobs?status=")).json()["items"]
    assert {row["id"] for row in all_rows} == {job.id for job in jobs[:3]}
    assert next(row for row in all_rows if row["id"] == jobs[2].id)["status"] == "closed"


async def test_repeated_company_query_values_are_not_lost(api_client, jobs):
    single = await api_client.get("/api/jobs?company=google")
    assert single.status_code == 200
    assert [row["id"] for row in single.json()["items"]] == [jobs[0].id]
    both = await api_client.get("/api/jobs?company=google&company=amazon")
    assert both.status_code == 200
    assert {row["id"] for row in both.json()["items"]} == {jobs[0].id, jobs[1].id}


@pytest.mark.parametrize("query", ["viewed=", "viewed=anything", "limit=501", "ids=not-an-id"])
async def test_invalid_jobs_query_is_rejected_at_the_http_boundary(api_client, query):
    response = await api_client.get(f"/api/jobs?{query}")
    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"][0] == "query"


@pytest.mark.parametrize(
    ("query", "newest_first"),
    [("sort=date_added", True), ("sort=date_added&order=ASC", False), ("order=sideways", True)],
)
async def test_a_sort_or_direction_the_list_does_not_know_reads_as_the_default(
    api_client, jobs, query, newest_first
):
    # An old link keeps listing rows: a retired key orders by the default
    # column, `asc` in any case is ascending, and any other direction is
    # descending, as `resolve_ordering` reads them.
    response = await api_client.get(f"/api/jobs?{query}")
    assert response.status_code == 200
    newest, older = jobs[0].id, jobs[1].id
    expected = [newest, older] if newest_first else [older, newest]
    assert [row["id"] for row in response.json()["items"]] == expected


async def test_favorites_commit_idempotently_and_delete_is_visible_next_request(api_client, jobs, db_session):
    path = f"/api/jobs/{jobs[0].id}/favorite"
    for _ in range(2):
        response = await api_client.put(path)
        assert response.status_code == 200
        assert response.json() == {"job_id": jobs[0].id, "is_favorite": True}
    saved = (await api_client.get("/api/jobs?favorites_only=true")).json()
    assert saved["total"] == 1
    assert saved["items"][0]["id"] == jobs[0].id
    assert saved["items"][0]["is_favorite"] is True
    assert await db_session.scalar(select(func.count()).select_from(Favorite)) == 1

    assert (await api_client.delete(path)).json() == {"job_id": jobs[0].id, "is_favorite": False}
    assert (await api_client.get("/api/jobs?favorites_only=true")).json()["total"] == 0
    assert await db_session.scalar(select(func.count()).select_from(Favorite)) == 0


async def test_pursuit_write_serializes_and_commits_current_state_favorite_and_history(api_client, jobs, db_session):
    due = "2026-09-12T09:30:00+00:00"
    response = await api_client.put(f"/api/jobs/{jobs[0].id}/pursuit", json={
        "stage": "applied", "priority": 2, "notes": "Referral sent",
        "next_action": "Follow up", "next_action_due": due,
    })
    assert response.status_code == 200
    pursuit = response.json()["pursuit"]
    assert pursuit["job_id"] == jobs[0].id
    assert pursuit["stage"] == "applied"
    assert pursuit["priority"] == 2
    assert datetime.fromisoformat(pursuit["next_action_due"]) == datetime.fromisoformat(due)
    assert datetime.fromisoformat(pursuit["created_at"]).tzinfo is not None
    read = await api_client.get("/api/pursuits?stage=applied")
    assert read.status_code == 200
    stored = read.json()["pursuits"]
    assert len(stored) == 1
    assert {key: stored[0][key] for key in pursuit} == pursuit
    assert stored[0]["opportunity"]["title"] == jobs[0].title
    assert (await api_client.get("/api/jobs?favorites_only=true")).json()["total"] == 1
    history = (await db_session.scalars(select(PursuitEvent))).all()
    assert [(row.actor, row.event_type, row.to_stage) for row in history] == [("user", "created", "applied")]

    updated = await api_client.put(f"/api/jobs/{jobs[0].id}/pursuit", json={
        "stage": "interviewing", "next_action_due": None,
    })
    assert updated.status_code == 200
    current = updated.json()["pursuit"]
    assert current["stage"] == "interviewing"
    assert current["next_action_due"] is None
    assert (current["notes"], current["priority"]) == ("Referral sent", 2)
    assert datetime.fromisoformat(current["updated_at"]) >= datetime.fromisoformat(pursuit["updated_at"])
    assert (await api_client.get("/api/pursuits?stage=applied")).json()["pursuits"] == []
    history = (await db_session.scalars(select(PursuitEvent).order_by(PursuitEvent.id))).all()
    assert [(row.from_stage, row.to_stage) for row in history] == [(None, "applied"), ("applied", "interviewing")]
    assert await db_session.scalar(select(func.count()).select_from(Favorite)) == 1


async def test_the_two_save_paths_meet_on_one_favorite_row(api_client, jobs, db_session):
    """`favorites.job_id` is UNIQUE, so "insert unless one exists" is not tidiness
    — a second insert is an IntegrityError and a 500. Two independent writers
    reach this table (the star on a row, and a pursuit write, which saves the job
    on the way past), so the rule has to hold in BOTH orders.
    """
    job_id = jobs[0].id

    starred = await api_client.put(f"/api/jobs/{job_id}/favorite", json=None)
    assert starred.status_code == 200
    # The pursuit write saves the job as it goes; the row is already there.
    pursued = await api_client.put(f"/api/jobs/{job_id}/pursuit", json={"stage": "applied"})
    assert pursued.status_code == 200
    assert await db_session.scalar(select(func.count()).select_from(Favorite)) == 1

    # And the other way round: the star on a job a pursuit already saved.
    other = jobs[1].id
    assert (await api_client.put(f"/api/jobs/{other}/pursuit", json={"stage": "saved"})).status_code == 200
    assert (await api_client.put(f"/api/jobs/{other}/favorite", json=None)).status_code == 200
    assert await db_session.scalar(select(func.count()).select_from(Favorite)) == 2
    assert (await api_client.get("/api/jobs?favorites_only=true")).json()["total"] == 2


@pytest.mark.parametrize("payload", [
    {"stage": "invented"}, {"priority": 0}, {"next_action_due": "tomorrow-ish"},
    # An EXPLICIT null on a NOT NULL column. Absent means "leave it alone" and
    # is the ordinary case; `null` asks for a value the table cannot hold, and
    # must be refused before the flush, not answered with a 500.
    {"stage": None}, {"priority": None}, {"stage": None, "notes": "typed anyway"},
])
async def test_invalid_pursuit_body_creates_no_partial_state(api_client, jobs, db_session, payload):
    response = await api_client.put(f"/api/jobs/{jobs[0].id}/pursuit", json=payload)
    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"][0] == "body"
    for model in (Pursuit, Favorite, PursuitEvent):
        assert await db_session.scalar(select(func.count()).select_from(model)) == 0


async def test_an_explicit_null_still_clears_the_nullable_pursuit_fields(api_client, jobs, db_session):
    """The other half of the explicit-null rule, and the reason the guard names two fields
    rather than rejecting every null. `notes`, `next_action` and
    `next_action_due` ARE nullable, so `null` there is a legitimate "clear
    this" — the only way the route offers to take a follow-up back off."""
    path = f"/api/jobs/{jobs[0].id}/pursuit"
    assert (await api_client.put(path, json={
        "stage": "applied", "notes": "phone screen booked", "next_action": "send thanks",
        "next_action_due": "2026-09-20T09:00:00+00:00",
    })).status_code == 200

    cleared = await api_client.put(path, json={
        "notes": None, "next_action": None, "next_action_due": None,
    })
    assert cleared.status_code == 200
    pursuit = cleared.json()["pursuit"]
    assert (pursuit["notes"], pursuit["next_action"], pursuit["next_action_due"]) == (None, None, None)
    # The NOT NULL pair is untouched by a write that names neither.
    assert (pursuit["stage"], pursuit["priority"]) == ("applied", 3)


@pytest.mark.parametrize("endpoint,payload", [("favorite", None), ("pursuit", {"stage": "saved"})])
async def test_unknown_job_write_returns_404(api_client, db_session, endpoint, payload):
    response = await api_client.put(f"/api/jobs/999999/{endpoint}", json=payload)
    assert response.status_code == 404
    for model in (Pursuit, Favorite, PursuitEvent):
        assert await db_session.scalar(select(func.count()).select_from(model)) == 0


async def test_failed_history_insert_rolls_back_the_pursuit_update(api_client, jobs, db_session):
    path = f"/api/jobs/{jobs[0].id}/pursuit"
    assert (await api_client.put(path, json={"stage": "applied", "notes": "Original"})).status_code == 200

    def fail_history_insert(_mapper, _connection, _target):
        raise RuntimeError("history store unavailable")

    # Inject a storage failure after the real unit of work has begun flushing.
    # The handler and session teardown still own the transaction/rollback.
    event.listen(PursuitEvent, "before_insert", fail_history_insert)
    try:
        with pytest.raises(RuntimeError, match="history store unavailable"):
            await api_client.put(path, json={"stage": "offer", "notes": "Must roll back"})
    finally:
        event.remove(PursuitEvent, "before_insert", fail_history_insert)

    stored = (await api_client.get("/api/pursuits")).json()["pursuits"]
    assert len(stored) == 1
    assert (stored[0]["stage"], stored[0]["notes"]) == ("applied", "Original")
    assert await db_session.scalar(select(func.count()).select_from(PursuitEvent)) == 1
