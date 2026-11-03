"""The "not for me" primitive: endpoint behavior.

Dismissal is a VIEW filter — it must never touch `in_scope`, which is a
projection of the saved scope axes and gets recomputed wholesale on scope
saves. The exclusion-rule endpoints DO recompute, because a rule is part of
what `in_scope` projects.
"""

from __future__ import annotations

import asyncio

import pytest
from fastapi import HTTPException

from tracker.api.routers.jobs import FeedbackPayload, clear_feedback, set_feedback
from tracker.db.models import Job, JobFeedback


class _Session:
    def __init__(self, job: Job | None):
        self._job = job
        self.feedback: JobFeedback | None = None
        self.deleted: list[object] = []
        self.commits = 0

    async def get(self, model, key):
        assert model is Job
        return self._job

    async def scalar(self, stmt):
        return self.feedback

    def add(self, row):
        self.feedback = row

    async def delete(self, row):
        self.deleted.append(row)
        self.feedback = None

    async def commit(self):
        self.commits += 1


def _job() -> Job:
    return Job(
        id=7, company="amazon", req_id="r", dedupe_key="k",
        title="Sr. Operations Manager", url="u",
        department="Fulfillment & Operations Management", team="AMZL",
        level_band="senior", in_scope=True,
    )


def test_dismiss_upserts_and_offers_the_employer_vocabulary():
    session = _Session(_job())
    result = asyncio.run(
        set_feedback(7, FeedbackPayload(verdict="dismissed", reason="wrong_domain"), session)
    )
    assert session.feedback is not None and session.feedback.reason == "wrong_domain"
    assert session.commits == 1
    # The response carries the verbatim fields so the UI can OFFER a rule
    # without another read — offering, never writing, is this endpoint's job.
    assert result["company"] == "amazon"
    assert result["department"] == "Fulfillment & Operations Management"
    assert result["team"] == "AMZL"
    # A dismissal never touches scope.
    assert session._job.in_scope is True

    # Second verdict upserts (reason can be revised, no duplicate row), and it
    # is a NEW mark: the Not-for-me lens orders by it, newest first.
    session.feedback.created_at = None
    asyncio.run(set_feedback(7, FeedbackPayload(verdict="dismissed", reason="other"), session))
    assert session.feedback.reason == "other"
    assert session.feedback.created_at is not None

    # Undo removes the row and reports the state.
    undone = asyncio.run(clear_feedback(7, session))
    assert undone == {"job_id": 7, "is_dismissed": False}
    assert session.feedback is None and len(session.deleted) == 1


def test_dismiss_validates_job_and_reason():
    with pytest.raises(HTTPException) as missing:
        asyncio.run(set_feedback(9, FeedbackPayload(verdict="dismissed"), _Session(None)))
    assert missing.value.status_code == 404

    with pytest.raises(HTTPException) as bad_reason:
        asyncio.run(
            set_feedback(7, FeedbackPayload(verdict="dismissed", reason="vibes"), _Session(_job()))
        )
    assert bad_reason.value.status_code == 422
