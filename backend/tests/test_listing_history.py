"""A posting's listing history and role age, over real HTTP.

`GET /api/jobs/{id}/history` answers the question behind the one age a row
shows: every dated fact, oldest first, and which other postings count as the
same role. The dashboard's History popover is written against this exact
shape, so the shape is held key for key, and each case is a way to get the
MEANING wrong:

1. **A standalone posting** has no role age and no postings beside it.
2. **A re-dated posting** keeps its first date as the start; the move is an
   event, not a start, and edits collapse to one line per field.
3. **A reopened posting** counts straight through its closed gap.
4. **A three-posting lineage**: role age from the earliest member by the same
   rule, while the headline stays each posting's own evidence; Job detail
   serves the role age and the standing-posting check reads it.
5. **A suspected, unreviewed link** is listed as not counted and moves no
   number; a rejected one is not listed at all.

Rows are written in the writer's shape (`db/repo.py`): lifecycle `changed`
details keyed by field, `redated` details `{from, to}` as ISO strings, and a
`reopened` event for each `repost_count`.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio

from tests.api_errors import said
from tests.factories import make_job
from tracker.api.schemas.jobs import ListingEvent, ListingHistoryResponse, UnconfirmedPosting
from tracker.db.models import JobLifecycleEvent, JobLineage, JobLineageLink

NOW = datetime.now(UTC)


def _ago(days: int) -> datetime:
    # An hour of slack so a whole-day count cannot land on a boundary.
    return NOW - timedelta(days=days, hours=1)


def _at(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value.replace("Z", "+00:00")) if value is not None else None


def _event(job_id: int, kind: str, at: datetime, **detail) -> JobLifecycleEvent:
    return JobLifecycleEvent(job_id=job_id, event_type=kind, detail=detail, created_at=at)


def _link(newer: int, prior: int, *, confidence: str, status: str) -> JobLineageLink:
    return JobLineageLink(
        job_id=newer, prior_job_id=prior, relation="repost", method="title+embedding", score=0.93,
        confidence=confidence, status=status, detector_version="test", evidence={},
    )


@pytest_asyncio.fixture
async def seeded(db_session) -> dict[str, int]:
    rows = {
        "standalone": make_job("standalone", first_seen=_ago(21), last_seen=_ago(0)),
        "redated": make_job(
            "redated", first_posted_at=_ago(120), posted_at=_ago(10), first_seen=_ago(60),
            last_seen=_ago(0),
        ),
        "reopened": make_job("reopened", first_seen=_ago(80), last_seen=_ago(0), repost_count=1),
        # The lineage, oldest first: A was dated by its employer before we saw it.
        "a": make_job("a", first_posted_at=_ago(200), posted_at=_ago(200), first_seen=_ago(100),
                  last_seen=_ago(90), status="closed", closed_at=_ago(90)),
        "b": make_job("b", first_seen=_ago(85), last_seen=_ago(40), status="closed", closed_at=_ago(40)),
        "c": make_job("c", first_posted_at=_ago(25), posted_at=_ago(25), first_seen=_ago(20),
                  last_seen=_ago(0)),
        "suspect": make_job("suspect", first_seen=_ago(10), last_seen=_ago(0)),
        "old_lookalike": make_job("old_lookalike", first_seen=_ago(300), last_seen=_ago(250),
                              status="closed", closed_at=_ago(250)),
        "rejected_lookalike": make_job("rejected_lookalike", first_seen=_ago(400), last_seen=_ago(380),
                                   status="closed", closed_at=_ago(380)),
    }
    db_session.add_all(rows.values())
    await db_session.flush()
    ids = {key: job.id for key, job in rows.items()}

    lineage = JobLineage(company="google", root_job_id=ids["a"], size=3, open_members=1,
                         first_seen=_ago(100), last_seen=_ago(0))
    db_session.add(lineage)
    await db_session.flush()
    for key, seq, role in (("a", 1, "original"), ("b", 2, "repost"), ("c", 3, "repost")):
        rows[key].lineage_id, rows[key].lineage_seq, rows[key].lineage_role = lineage.id, seq, role
        # What the lineage pass writes; the headline must not read it.
        rows[key].lineage_first_seen = _ago(100)

    db_session.add_all([
        _event(ids["standalone"], "opened", _ago(21)),
        _event(ids["redated"], "opened", _ago(60)),
        _event(ids["redated"], "changed", _ago(50), comp_median={"from": 500_000, "to": 510_000}),
        _event(ids["redated"], "changed", _ago(30), comp_median={"from": 510_000, "to": 520_000},
               title={"from": "Staff PM", "to": "Staff Product Manager"}),
        _event(ids["redated"], "redated", _ago(10), **{"from": _ago(120).isoformat(), "to": _ago(10).isoformat()}),
        _event(ids["reopened"], "opened", _ago(80)),
        _event(ids["reopened"], "closed", _ago(50), basis="absent_from_complete_listing"),
        _event(ids["reopened"], "reopened", _ago(30)),
        # B joined A by the machine; a person confirmed C as B's repost.
        _link(ids["b"], ids["a"], confidence="auto", status="pending"),
        _link(ids["c"], ids["b"], confidence="auto", status="confirmed"),
        # Possibly the same role, nobody has looked: listed, never counted.
        _link(ids["suspect"], ids["old_lookalike"], confidence="suspected", status="pending"),
        # Looked at and rejected: not listed at all.
        _link(ids["suspect"], ids["rejected_lookalike"], confidence="suspected", status="rejected"),
    ])
    await db_session.commit()
    return ids


async def _history(api_client, job_id: int) -> dict:
    response = await api_client.get(f"/api/jobs/{job_id}/history")
    assert response.status_code == 200, response.text
    body = response.json()
    # Every key, on every event: the client reads nulls, never absences.
    assert set(body) == set(ListingHistoryResponse.model_fields)
    for event in body["events"]:
        assert set(event) == set(ListingEvent.model_fields), event
    for other in body["unconfirmed"]:
        assert set(other) == set(UnconfirmedPosting.model_fields), other
    ats = [_at(e["at"]) for e in body["events"]]
    assert ats == sorted(ats), "oldest first"
    return body


def _kinds(body: dict) -> list[str]:
    return [e["kind"] for e in body["events"]]


@pytest.mark.asyncio
async def test_a_standalone_posting_has_its_own_age_and_nothing_beside_it(api_client, seeded):
    body = await _history(api_client, seeded["standalone"])

    assert body["headline"] == {"since": body["headline"]["since"], "days": 21, "basis": "sighting"}
    assert _at(body["headline"]["since"]) == _ago(21)
    assert body["role"] is None and body["unconfirmed"] == []
    # `opened` is the first sighting, stated once as `first_seen`.
    assert _kinds(body) == ["first_seen", "last_seen"]


@pytest.mark.asyncio
async def test_a_re_dated_posting_starts_at_its_first_date_and_records_the_move(api_client, seeded):
    body = await _history(api_client, seeded["redated"])

    assert (body["headline"]["days"], body["headline"]["basis"]) == (120, "employer")
    # Our estimate's refreshes are not the posting's history: only the title edit shows.
    assert _kinds(body) == ["employer_published", "first_seen", "edited", "redated", "last_seen"]
    (moved,) = [e for e in body["events"] if e["kind"] == "redated"]
    assert (_at(moved["from_at"]), _at(moved["to_at"])) == (_ago(120), _ago(10))
    edits = {e["field"]: (e["count"], _at(e["at"])) for e in body["events"] if e["kind"] == "edited"}
    assert edits == {"title": (1, _ago(30))}, "one line per employer field, at the latest; comp_median is ours"

    row = (await api_client.get(f"/api/jobs/{seeded['redated']}")).json()
    assert (row["listed_days"], row["listed_basis"]) == (120, "employer"), "the row reads the same rule"


@pytest.mark.asyncio
async def test_a_reopened_posting_counts_straight_through_its_gap(api_client, seeded):
    body = await _history(api_client, seeded["reopened"])

    assert body["headline"]["days"] == 80, "from the first sighting, not the return"
    assert _kinds(body) == ["first_seen", "closed", "reopened", "last_seen"]


@pytest.mark.asyncio
async def test_a_lineage_gives_role_age_from_its_earliest_posting(api_client, seeded):
    newest = await _history(api_client, seeded["c"])

    # The headline is C's own evidence: its employer dated it 25 days ago.
    assert (newest["headline"]["days"], newest["headline"]["basis"]) == (25, "employer")
    # The role is A's start by the same rule: its employer's date, before our sighting.
    assert newest["role"]["days"] == 200 and newest["role"]["postings"] == 3
    assert _at(newest["role"]["since"]) == _ago(200)
    earlier = {e["req_id"]: e for e in newest["events"] if e["kind"] == "earlier_posting"}
    assert set(earlier) == {"a", "b"} and "later_posting" not in _kinds(newest)
    assert (_at(earlier["a"]["at"]), _at(earlier["a"]["until"]), earlier["a"]["link"]) == (
        _ago(200), _ago(90), "auto",
    )
    assert (_at(earlier["b"]["at"]), earlier["b"]["link"]) == (_ago(85), "confirmed")
    assert earlier["b"]["job_id"] == seeded["b"] and earlier["b"]["title"] == "Staff Product Manager, b"
    # Closed postings are done: no `last_seen` is claimed for the open question.
    oldest = await _history(api_client, seeded["a"])
    assert "last_seen" not in _kinds(oldest)
    assert oldest["headline"]["days"] == 110, "to its closing, from its employer's date"
    assert {e["req_id"] for e in oldest["events"] if e["kind"] == "later_posting"} == {"b", "c"}
    assert oldest["role"]["days"] == 200 and oldest["role"]["postings"] == 3

    detail = (await api_client.get(f"/api/jobs/{seeded['c']}")).json()
    assert (detail["listed_days"], detail["role_days"], detail["role_postings"]) == (25, 200, 3)
    assert _at(detail["role_since"]) == _ago(200)
    # A long search is what the standing-posting check exists to catch: the
    # role's 200 days count there, though the ad itself is 25 days old.
    assert detail["posting_reality"]["met"] == ["long_open", "relisted"]


@pytest.mark.asyncio
async def test_a_suspected_link_is_listed_and_moves_no_number(api_client, seeded):
    body = await _history(api_client, seeded["suspect"])

    assert body["headline"]["days"] == 10 and body["role"] is None
    (other,) = body["unconfirmed"]
    assert (other["job_id"], other["req_id"], other["title"]) == (
        seeded["old_lookalike"], "old_lookalike", "Staff Product Manager, old_lookalike",
    )
    assert _at(other["listed_since"]) == _ago(300)
    assert isinstance(other["link_id"], int)
    assert "earlier_posting" not in _kinds(body)
    # Either side of the link sees it.
    back = await _history(api_client, seeded["old_lookalike"])
    assert [o["job_id"] for o in back["unconfirmed"]] == [seeded["suspect"]]

    detail = (await api_client.get(f"/api/jobs/{seeded['suspect']}")).json()
    assert (detail["listed_days"], detail["role_since"], detail["role_days"], detail["role_postings"]) == (
        10, None, None, None,
    )
    assert "long_open" not in detail["posting_reality"]["met"]


@pytest.mark.asyncio
async def test_an_unknown_posting_has_no_history(api_client, seeded):
    response = await api_client.get("/api/jobs/999999/history")
    assert (response.status_code, said(response.json())) == (404, {"detail": "job not found"})
