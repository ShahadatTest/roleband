"""Opened-position state is durable and serialized on every job surface."""

import asyncio
from datetime import UTC, datetime

import pytest
from fastapi import HTTPException

from tracker.api.routers.jobs import mark_job_viewed
from tracker.api.serializers.jobs import serialize_job
from tracker.db.models import Job


def _job(**overrides) -> Job:
    values = dict(
        id=7,
        company="openai",
        req_id="req-7",
        dedupe_key="openai:req-7",
        title="Staff Engineer",
        url="https://example.test/7",
        locations=["San Francisco, CA"],
        location_groups=["silicon_valley"],
        workplace_type="hybrid",
        level_band="staff",
        level_confidence="confirmed",
        family="software_engineering",
        track="technical",
        status="open",
        in_scope=True,
        first_seen=datetime(2026, 7, 15, tzinfo=UTC),
        last_seen=datetime(2026, 7, 15, tzinfo=UTC),
        viewed_at=None,
    )
    values.update(overrides)
    return Job(**values)


class Session:
    def __init__(self, job: Job | None):
        self.job = job
        self.commits = 0

    async def get(self, model, job_id):
        assert model is Job
        assert job_id == 7
        return self.job

    async def commit(self):
        self.commits += 1


def test_job_serialization_exposes_view_timestamp_on_list_rows():
    viewed_at = datetime(2026, 7, 15, 18, 30, tzinfo=UTC)
    assert serialize_job(_job(viewed_at=viewed_at))["viewed_at"] == viewed_at


def test_mark_viewed_is_idempotent_and_preserves_first_open_time():
    first = datetime(2026, 7, 15, 18, 30, tzinfo=UTC)
    session = Session(_job(viewed_at=first))

    response = asyncio.run(mark_job_viewed(7, session))

    assert response == {"job_id": 7, "viewed_at": first}
    assert session.job.viewed_at == first
    assert session.commits == 0


def test_mark_viewed_persists_first_open_time():
    session = Session(_job())

    response = asyncio.run(mark_job_viewed(7, session))

    assert response["job_id"] == 7
    assert response["viewed_at"] is not None
    assert session.job.viewed_at == response["viewed_at"]
    assert session.commits == 1


def test_mark_viewed_rejects_unknown_job():
    with pytest.raises(HTTPException) as exc:
        asyncio.run(mark_job_viewed(7, Session(None)))
    assert exc.value.status_code == 404
