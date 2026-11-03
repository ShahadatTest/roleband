"""The lineage and twin surfaces' response contract.

`tracker/api/schemas/lineage.py` declares what the eleven lineage and twin routes
send. These tests hold it to its sources:

1. **The builders and vocabularies**: `build_member_diff`, `compare_descriptions`
   and the model client's `_metrics` write exactly the keys their models name;
   the literals are the verdict constants and the profile's provider field.
2. **The routes over real HTTP** against seeded Postgres rows
   (`tests/lineage_contract_seed.py`) with the clock and the local model pinned:
   each shape's exact keys, the stack and twin component a posting belongs to,
   each review lens, every verdict read back through the surface it changes,
   the manual writes, each refused request leaving every relationship exactly
   as it was, and the model's advice leaving the human verdict untouched.
3. **Drift in both directions**: a key or a value a serializer produces without
   its model fails the response instead of reaching a client.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import timedelta
from types import SimpleNamespace
from typing import get_args

import pytest
from fastapi.exceptions import ResponseValidationError
from pydantic import ValidationError
from sqlalchemy import CheckConstraint, event, func, select

from tests.factories import make_company
from tests.lineage_contract_seed import (
    ASSESSMENT,
    MODEL_ID,
    NOW,
    USAGE,
    pin_lineage_environment,
    seed_lineage_contract,
)
from tracker.api.routers import lineage as lineage_router
from tracker.api.schemas import jobs as job_contract
from tracker.api.schemas import lineage as contract
from tracker.api.schemas.local_models import LocalModelMetrics, LocalModelProvider
from tracker.db.models import Job, JobFeedback, JobLineage, JobLineageLink, JobTwinLink
from tracker.intelligence.duplicate_review import PROMPT_VERSION, DuplicateAssessment
from tracker.lineage import review as verdicts
from tracker.lineage.content_diff import compare_descriptions
from tracker.lineage.diff import build_member_diff
from tracker.local_llm.client import _metrics
from tracker.local_llm.models import LocalLLMProfileInput


def _fields(model) -> list[str]:
    """A model's wire keys in declaration order, by alias."""
    return [field.alias or name for name, field in model.model_fields.items()]


def _iso(value) -> str:
    return value.isoformat().replace("+00:00", "Z")


# --------------------------------------------------------------------------- #
# 1. Builders and vocabularies
# --------------------------------------------------------------------------- #


def test_the_verdict_statuses_are_the_verdicts_both_kinds_share():
    # A verdict both queues accept sets that status. The one only a queue accepts
    # (`twin`, `duplicate`) moves the pair to the other kind and leaves this
    # proposal `rejected`, which the route tests read back.
    shared = set(get_args(lineage_router.LineageVerdict)) & set(get_args(lineage_router.TwinVerdict))
    assert set(get_args(contract.VerdictStatus)) == shared


def test_the_provider_literal_is_the_profile_vocabulary():
    assert get_args(LocalModelProvider) == get_args(LocalLLMProfileInput.model_fields["provider"].annotation)


def test_the_assessment_body_is_the_validated_assessment():
    body = {name: field.annotation for name, field in contract.DuplicateAssessmentBody.model_fields.items()}
    assert body == {name: field.annotation for name, field in DuplicateAssessment.model_fields.items()}


@pytest.mark.parametrize(
    ("table", "fields"),
    [
        (JobLineageLink, [(contract.DuplicateProposal, n) for n in ("relation", "method", "confidence", "status", "decision")]),
        (JobTwinLink, [(contract.TwinProposal, n) for n in ("method", "confidence", "status", "decision")]),
    ],
    ids=["duplicate", "twin"],
)
def test_no_constraint_bounds_the_link_strings_the_models_leave_open(table, fields):
    checks = [c for c in table.__table__.constraints if isinstance(c, CheckConstraint)]
    assert all("job_a_id < job_b_id" in str(c.sqltext) for c in checks), (
        f"a CHECK constraint now bounds a {table.__tablename__} string: type the field as its Literal"
    )
    for model, name in fields:
        assert model.model_fields[name].annotation in (str, str | None), f"{model.__name__}.{name}"


def _posting(**over) -> SimpleNamespace:
    row = {
        "title": "Staff Product Manager", "level_band": "staff", "disclosed_base_min": None,
        "disclosed_base_max": None, "disclosed_currency": None, "disclosed_pay_basis": None,
        "locations": ["Mountain View, CA, USA"], "comp_median": 600_000, "comp_currency": "USD",
    }
    row.update(over)
    return SimpleNamespace(**row)


def test_the_diff_model_names_every_field_the_builder_can_write():
    moved = _posting(
        title="Staff Product Manager, Inference", level_band="principal", disclosed_base_min=250_000,
        disclosed_currency="USD", disclosed_pay_basis="base", locations=["London, UK"], comp_median=640_000,
    )
    diff = build_member_diff(_posting(), moved)
    assert list(diff) == _fields(contract.PostingDiff)
    assert contract.PostingDiff.model_validate(diff).model_dump(by_alias=True, exclude_unset=True) == diff
    assert contract.PostingDiff.model_validate({}).model_dump(by_alias=True, exclude_unset=True) == {}


@pytest.mark.parametrize(
    "left",
    [[{"key": "responsibilities", "title": "Responsibilities", "content": "Own the roadmap."}], []],
    ids=["comparable", "one_side_empty"],
)
def test_description_evidence_is_exactly_its_model(left):
    right = [{"key": "responsibilities", "title": "Responsibilities", "content": "Own enterprise adoption."}]
    evidence = compare_descriptions(left, None, right, None).evidence()
    assert list(evidence) == _fields(contract.DescriptionDiff)
    assert contract.DescriptionDiff.model_validate(evidence).model_dump() == evidence


def test_the_metrics_model_names_every_key_the_client_writes():
    metrics = _metrics({"usage": USAGE, "choices": [{"finish_reason": "stop"}]}, wall_time_ms=9412, context_window=32768)
    assert list(metrics) == _fields(LocalModelMetrics)


def test_a_standalone_posting_carrying_a_stack_key_is_neither_branch():
    with pytest.raises(ValidationError):
        contract.JobLineageResponse.model_validate({"lineage_id": None, "size": 1, "members": [], "company": "google"})


# --------------------------------------------------------------------------- #
# 2. The routes over HTTP
# --------------------------------------------------------------------------- #


@pytest.fixture
def pinned(monkeypatch, no_escape) -> None:
    pin_lineage_environment(monkeypatch)


async def _json(api_client, method: str, path: str, expected: int = 200, **kwargs) -> dict:
    response = await api_client.request(method, path, **kwargs)
    assert response.status_code == expected, response.text
    return response.json()


async def _lineage_count(db_session) -> int:
    return await db_session.scalar(select(func.count()).select_from(JobLineage))


async def _relationships(db_session) -> tuple:
    """Everything a verdict, a manual write or a model call could change."""
    duplicate_links = sorted((await db_session.execute(select(
        JobLineageLink.id, JobLineageLink.job_id, JobLineageLink.prior_job_id, JobLineageLink.relation,
        JobLineageLink.method, JobLineageLink.status, JobLineageLink.reviewed_at, JobLineageLink.evidence,
    ))).all())
    twin_links = sorted((await db_session.execute(select(
        JobTwinLink.id, JobTwinLink.job_a_id, JobTwinLink.job_b_id, JobTwinLink.method, JobTwinLink.status,
        JobTwinLink.reviewed_at, JobTwinLink.evidence,
    ))).all())
    projection = sorted((await db_session.execute(select(Job.id, Job.lineage_id, Job.lineage_seq, Job.lineage_role))).all())
    lineages = sorted((await db_session.execute(select(JobLineage.root_job_id, JobLineage.size, JobLineage.open_members))).all())
    return duplicate_links, twin_links, projection, lineages


def _assert_posting(job: dict) -> None:
    assert list(job) == _fields(job_contract.JobDetailRow)


@pytest.mark.asyncio
async def test_a_stack_answers_every_posting_of_the_role_oldest_first(api_client, db_session, pinned):
    seeded = await seed_lineage_contract(db_session)
    body = await _json(api_client, "GET", f"/api/jobs/{seeded.repost}/lineage")
    assert list(body) == _fields(contract.LineageStack)
    members = body.pop("members")
    assert body == {
        "lineage_id": body["lineage_id"], "root_job_id": seeded.original, "company": "google", "size": 3,
        "open_members": 2, "first_seen": _iso(NOW - timedelta(days=90)), "last_seen": _iso(NOW - timedelta(days=1)),
    }
    assert [(m["seq"], m["role"], m["job"]["id"]) for m in members] == [
        (1, "original", seeded.original), (2, "repost", seeded.repost), (3, "duplicate", seeded.duplicate),
    ]
    for member in members:
        assert list(member) == _fields(contract.LineageMember)
        _assert_posting(member["job"])
        assert member["job"]["lineage_id"] == body["lineage_id"]

    original, repost, duplicate = members
    assert (original["link"], original["diff_vs_prev"]) == (None, None)
    assert list(repost["link"]) == _fields(contract.DuplicateProposal)
    assert (repost["link"]["id"], repost["link"]["confidence"], repost["link"]["decision"]) == (
        seeded.repost_link, "auto", None,
    )
    assert repost["diff_vs_prev"] == {
        "title": {"from": "Senior Product Manager, Inference", "to": "Staff Product Manager, Inference"},
        "level_band": {"from": "senior", "to": "staff"},
        "disclosed_band": {"from": None, "to": [250_000, 360_000], "currency": "USD"},
        "pay_basis": {"from": None, "to": "base"},
        "locations": {"added": ["London, UK"], "removed": ["Seattle, WA, USA"]},
        "comp_median": {"from": 410_000, "to": 640_000, "currency": "USD"},
    }
    assert duplicate["diff_vs_prev"] == {}, "an effective link between matching postings names no change"
    assert (duplicate["link"]["status"], duplicate["link"]["decision"], duplicate["link"]["decision_changes"]) == (
        "confirmed", "duplicate", 1,
    )
    for member_id in (seeded.original, seeded.duplicate):
        assert await _json(api_client, "GET", f"/api/jobs/{member_id}/lineage") == {**body, "members": members}


@pytest.mark.asyncio
@pytest.mark.parametrize("posting", ["solo", "rejected"], ids=["no_link", "only_a_rejected_link"])
async def test_a_posting_in_no_lineage_answers_three_keys(api_client, db_session, pinned, posting):
    seeded = await seed_lineage_contract(db_session)
    body = await _json(api_client, "GET", f"/api/jobs/{getattr(seeded, posting)}/lineage")
    assert body == {"lineage_id": None, "size": 1, "members": []}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("query", "expected", "total"),
    [
        ("", ["pending_link"], 1),
        ("?confidence=", ["repost_link", "pending_link"], 2),
        # The Duplicates screen's "Matched automatically" lens, and
        # the weakest-first order it reads them in.
        ("?confidence=auto", ["repost_link"], 1),
        ("?confidence=&order=weakest", ["pending_link", "repost_link"], 2),
        # Decided: the newest verdict first, whatever its score.
        ("?status=reviewed", ["rejected_link", "duplicate_link"], 2),
        ("?status=confirmed", ["duplicate_link"], 1),
        ("?status=reviewed&limit=1&offset=1", ["duplicate_link"], 2),
        ("?status=confirmed&offset=50", [], 1),
    ],
    ids=["pending_suspected", "any_confidence", "auto_only", "weakest_first", "reviewed", "confirmed", "second_page",
         "past_the_end"],
)
async def test_the_duplicate_queue_serves_each_lens_in_its_order(api_client, db_session, pinned, query, expected, total):
    seeded = await seed_lineage_contract(db_session)
    body = await _json(api_client, "GET", f"/api/lineage/review{query}")
    assert list(body) == _fields(contract.DuplicateReviewList)
    assert [item["link"]["id"] for item in body["items"]] == [getattr(seeded, key) for key in expected]
    assert body["total"] == total, "the total counts the lens, not the page"
    for item in body["items"]:
        assert list(item) == _fields(contract.DuplicateReviewItem)
        assert list(item["link"]) == _fields(contract.DuplicateProposal)
        _assert_posting(item["job"])
        _assert_posting(item["prior"])
        assert (item["job"]["id"], item["prior"]["id"]) == (item["link"]["job_id"], item["link"]["prior_job_id"])


@pytest.mark.asyncio
async def test_decided_lists_a_verdict_on_a_pair_matched_automatically_newest_first(api_client, db_session, pinned):
    # A verdict keeps the link's confidence: a pair decided from "Matched
    # automatically" stays `auto`, and the Decided list asks for any.
    seeded = await seed_lineage_contract(db_session)
    for model, link_id in ((JobLineageLink, seeded.repost_link), (JobTwinLink, seeded.twin_pending)):
        link = await db_session.get(model, link_id)
        link.confidence, link.status, link.reviewed_at = "auto", "rejected", NOW - timedelta(hours=1)
    await db_session.commit()

    decided = await _json(api_client, "GET", "/api/lineage/review?status=reviewed&confidence=")
    # Newest first, not by score: 0.97 an hour ago, 0.88 two days ago, 0.99 three days ago.
    assert [item["link"]["id"] for item in decided["items"]] == [
        seeded.repost_link, seeded.rejected_link, seeded.duplicate_link,
    ]
    assert decided["total"] == 3
    twins = await _json(api_client, "GET", "/api/twins/review?status=reviewed&confidence=")
    assert [item["link"]["id"] for item in twins["items"]] == [
        seeded.twin_pending, seeded.twin_manual, seeded.twin_reviewed,
    ]
    # The default lens is the queue's: it never lists the auto verdict.
    assert seeded.repost_link not in [
        item["link"]["id"] for item in (await _json(api_client, "GET", "/api/lineage/review?status=reviewed"))["items"]
    ]


@contextmanager
def _statements(engine) -> Iterator[list[str]]:
    seen: list[str] = []

    def record(_conn, _cursor, statement, _parameters, _context, _executemany):
        seen.append(statement)

    event.listen(engine.sync_engine, "before_cursor_execute", record)
    try:
        yield seen
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", record)


#: What `detail=true` adds to a posting, and the columns it reads them from.
_DETAIL_ONLY = [key for key in _fields(job_contract.JobDetailRow) if key not in _fields(job_contract.JobRow)]
_DESCRIPTION_COLUMNS = ("jobs.description_text", "jobs.description_html", "jobs.description_sections")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("route", "summary_list", "summary_item"),
    [
        ("/api/lineage/review", contract.DuplicateReviewSummaryList, contract.DuplicateReviewSummaryItem),
        ("/api/twins/review", contract.TwinReviewSummaryList, contract.TwinReviewSummaryItem),
    ],
    ids=["duplicates", "twins"],
)
async def test_the_decided_summary_lists_the_same_pairs_without_reading_a_description(
    api_client, db_session, pinned, monkeypatch, route, summary_list, summary_item
):
    # The Decided list reads a long page of each kind. The summary form sends
    # each posting as a list row, so no description is read from the database,
    # sent, or compared with its pair's.
    await seed_lineage_contract(db_session)
    compared: list[tuple] = []
    compare = lineage_router.compare_descriptions

    def counting(*args):
        compared.append(args)
        return compare(*args)

    monkeypatch.setattr(lineage_router, "compare_descriptions", counting)
    decided = f"{route}?status=reviewed&confidence="

    with _statements(db_session.bind) as full_reads:
        full_response = await api_client.get(decided)
    assert full_response.status_code == 200, full_response.text
    full, full_compared = full_response.json(), len(compared)
    with _statements(db_session.bind) as summary_reads:
        summary_response = await api_client.get(f"{decided}&detail=false")
    assert summary_response.status_code == 200, summary_response.text
    summary = summary_response.json()

    # The same pairs, in the same order, with the same verdicts and totals.
    assert len(summary["items"]) == len(full["items"]) >= 2
    assert summary["total"] == full["total"]
    assert [(item["link"], item["diff"]) for item in summary["items"]] == [
        (item["link"], item["diff"]) for item in full["items"]
    ]
    # Each posting is the full read's row without what detail adds.
    assert list(summary) == _fields(summary_list)
    for brief, whole in zip(summary["items"], full["items"], strict=True):
        assert list(brief) == _fields(summary_item)
        for side in ("job", "prior"):
            assert list(brief[side]) == _fields(job_contract.JobRow)
            assert brief[side] == {key: value for key, value in whole[side].items() if key not in _DETAIL_ONLY}

    # Negative control: the full read reads, sends and (for twins) compares the descriptions.
    full_jobs = [sql for sql in full_reads if "FROM jobs" in sql]
    assert full_jobs and all(column in full_jobs[-1] for column in _DESCRIPTION_COLUMNS)
    assert "Own the inference platform roadmap" in full_response.text
    assert full_compared == (len(full["items"]) if route == "/api/twins/review" else 0)

    summary_jobs = [sql for sql in summary_reads if "FROM jobs" in sql]
    assert summary_jobs
    assert not any(column in sql for sql in summary_jobs for column in _DESCRIPTION_COLUMNS)
    assert "Own the inference platform roadmap" not in summary_response.text
    assert len(compared) == full_compared, "the summary form compares no descriptions"
    assert len(summary_response.content) < len(full_response.content)


@pytest.mark.asyncio
async def test_a_queued_duplicate_pairs_the_newer_posting_with_what_moved(api_client, db_session, pinned):
    seeded = await seed_lineage_contract(db_session)
    (item,) = (await _json(api_client, "GET", "/api/lineage/review"))["items"]
    assert (item["job"]["id"], item["prior"]["id"]) == (seeded.pending_newer, seeded.pending_prior)
    assert item["link"]["reasons"] == ["same department and team", "description cosine 0.93"]
    assert item["diff"] == {
        "title": {"from": "Staff Product Manager, Payments", "to": "Staff Product Manager, Payments Platform"},
    }


@pytest.mark.asyncio
async def test_the_twin_queue_serves_the_stored_evidence_and_the_pair_as_it_stands(api_client, db_session, pinned):
    seeded = await seed_lineage_contract(db_session)
    body = await _json(api_client, "GET", "/api/twins/review")
    assert list(body) == _fields(contract.TwinReviewList)
    assert body["total"] == 1
    (item,) = body["items"]
    assert list(item) == _fields(contract.TwinReviewItem)
    link = item["link"]
    assert list(link) == _fields(contract.TwinProposal)
    assert (link["id"], link["job_id"], link["prior_job_id"], link["relation"], link["gap_days"]) == (
        seeded.twin_pending, seeded.twin_right, seeded.twin_left, "twin", None,
    )
    assert (item["job"]["id"], item["prior"]["id"]) == (seeded.twin_right, seeded.twin_left)

    stored = (await db_session.get(JobTwinLink, seeded.twin_pending)).evidence["description_diff"]
    assert link["description_diff"] == stored
    assert list(link["description_diff"]) == list(stored), "served in the order the database returns it"
    left, right = await db_session.get(Job, seeded.twin_left), await db_session.get(Job, seeded.twin_right)
    assert item["description_diff"] == compare_descriptions(
        left.description_sections, left.description_text, right.description_sections, right.description_text,
    ).evidence()
    assert list(item["description_diff"]) == _fields(contract.DescriptionDiff)


@pytest.mark.asyncio
async def test_reviewed_twins_carry_their_decision_and_no_stored_evidence(api_client, db_session, pinned):
    seeded = await seed_lineage_contract(db_session)
    body = await _json(api_client, "GET", "/api/twins/review?status=reviewed")
    assert [item["link"]["id"] for item in body["items"]] == [seeded.twin_manual, seeded.twin_reviewed]
    for item in body["items"]:
        assert (item["link"]["decision"], item["link"]["description_diff"], item["link"]["score"]) == ("twin", None, None)


# The queue asks only about pairs the user can act on, one posting of
# which is on the Board. Each case moves BOTH postings of the queued duplicate
# and of the queued twin, or only one (a positive control: one posting still on
# the Board keeps the pair).
_OFF_BOARD = {
    "both_closed": (("pending_prior", "pending_newer", "twin_left", "twin_right"), "closed"),
    "both_out_of_scope": (("pending_prior", "pending_newer", "twin_left", "twin_right"), "out_of_scope"),
    "both_not_for_me": (("pending_prior", "pending_newer", "twin_left", "twin_right"), "not_for_me"),
    "company_unfollowed": ((), "unfollowed"),
    "company_hidden": ((), "hidden"),
    "one_closed": (("pending_prior", "twin_left"), "closed"),
    "one_out_of_scope": (("pending_newer", "twin_right"), "out_of_scope"),
    "one_not_for_me": (("pending_prior", "twin_right"), "not_for_me"),
}


async def _take_off_board(db_session, seeded, case: str) -> None:
    keys, how = _OFF_BOARD[case]
    if how == "unfollowed":
        db_session.add(make_company("google", "Google", enabled=False))
    elif how == "hidden":
        db_session.add(make_company("google", "Google", visible=False))
    for key in keys:
        job = await db_session.get(Job, getattr(seeded, key))
        if how == "closed":
            job.status, job.closed_at = "closed", NOW - timedelta(days=1)
        elif how == "out_of_scope":
            job.in_scope = False
        else:
            db_session.add(JobFeedback(job_id=job.id, verdict="dismissed"))
    await db_session.commit()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("case", "listed"),
    [(case, case.startswith("one_")) for case in _OFF_BOARD],
    ids=list(_OFF_BOARD),
)
async def test_the_queue_asks_only_about_pairs_with_a_posting_on_the_board(
    api_client, db_session, pinned, case, listed
):
    seeded = await seed_lineage_contract(db_session)
    await _take_off_board(db_session, seeded, case)

    duplicates = await _json(api_client, "GET", "/api/lineage/review")
    twins = await _json(api_client, "GET", "/api/twins/review")
    assert [item["link"]["id"] for item in duplicates["items"]] == ([seeded.pending_link] if listed else [])
    assert [item["link"]["id"] for item in twins["items"]] == ([seeded.twin_pending] if listed else [])
    assert (duplicates["total"], twins["total"]) == ((1, 1) if listed else (0, 0))

    # Nothing is withdrawn: the pairs stay pending, listed on request.
    every = await _json(api_client, "GET", "/api/lineage/review?on_board=false")
    every_twin = await _json(api_client, "GET", "/api/twins/review?on_board=false")
    assert [item["link"]["id"] for item in every["items"]] == [seeded.pending_link]
    assert [item["link"]["id"] for item in every_twin["items"]] == [seeded.twin_pending]

    # The nav badge counts the queue it opens.
    stats = await _json(api_client, "GET", "/api/stats")
    assert stats["review_pending"] == duplicates["total"] + twins["total"]


@pytest.mark.asyncio
async def test_a_decided_pair_stays_in_decided_whatever_its_postings_show_now(api_client, db_session, pinned):
    seeded = await seed_lineage_contract(db_session)
    await db_session.execute(
        Job.__table__.update().values(status="closed", in_scope=False, closed_at=NOW - timedelta(days=1))
    )
    await db_session.commit()
    decided = await _json(api_client, "GET", "/api/lineage/review?status=reviewed")
    assert [item["link"]["id"] for item in decided["items"]] == [seeded.rejected_link, seeded.duplicate_link]
    decided_twins = await _json(api_client, "GET", "/api/twins/review?status=reviewed")
    assert [item["link"]["id"] for item in decided_twins["items"]] == [seeded.twin_manual, seeded.twin_reviewed]
    # The automatically matched lens is a pending lens: it follows the Board too.
    assert (await _json(api_client, "GET", "/api/lineage/review?confidence=auto"))["total"] == 0
    assert (await _json(api_client, "GET", "/api/lineage/review?confidence=auto&on_board=false"))["total"] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("start", "component", "direct", "direct_link"),
    [
        ("twin_left", ["twin_hub", "twin_spoke"], "twin_hub", "twin_reviewed"),
        ("twin_spoke", ["twin_left", "twin_hub"], "twin_hub", "twin_manual"),
        ("solo", [], None, None),
    ],
    ids=["hub_reached_directly", "left_reached_through_the_hub", "no_twins"],
)
async def test_a_posting_answers_its_confirmed_twin_component(
    api_client, db_session, pinned, start, component, direct, direct_link
):
    seeded = await seed_lineage_contract(db_session)
    start_id = getattr(seeded, start)
    body = await _json(api_client, "GET", f"/api/jobs/{start_id}/twins")
    assert list(body) == _fields(contract.JobTwinsResponse)
    others = sorted(getattr(seeded, key) for key in component)
    assert (body["job_id"], body["size"], body["direct_count"]) == (start_id, 1 + len(others), int(direct is not None))
    assert [member["job"]["id"] for member in body["members"]] == [start_id, *others]
    direct_id = getattr(seeded, direct) if direct else None
    for member in body["members"]:
        assert list(member) == _fields(contract.TwinMember)
        _assert_posting(member["job"])
        is_direct = member["job"]["id"] == direct_id
        assert member["direct"] is is_direct
        assert (member["link"]["id"] if member["link"] else None) == (getattr(seeded, direct_link) if is_direct else None)


async def _twin_link_rows(api_client, db_session, path: str) -> tuple[dict, int]:
    """The body of `path`, and how many twin-link rows its statements returned."""
    from sqlalchemy import event

    rows = 0

    def record(_conn, cursor, statement, _parameters, _context, _executemany):
        nonlocal rows
        if "FROM job_twin_link" in statement:
            rows += max(cursor.rowcount, 0)

    engine = db_session.bind.sync_engine
    event.listen(engine, "after_cursor_execute", record)
    try:
        body = await _json(api_client, "GET", path)
    finally:
        event.remove(engine, "after_cursor_execute", record)
    return body, rows


@pytest.mark.asyncio
async def test_a_postings_twins_read_its_component_however_large_the_twin_table(api_client, db_session, pinned):
    """Job detail asks for its twins on every open, so the read follows the
    posting's own component: twin pairs elsewhere change neither the answer nor
    how many link rows it reads."""
    from tests.lineage_contract_seed import _job as lineage_job
    from tracker.lineage.twins import DETECTOR_VERSION as TWIN_DETECTOR_VERSION

    seeded = await seed_lineage_contract(db_session)
    path = f"/api/jobs/{seeded.twin_left}/twins"
    before, read_before = await _twin_link_rows(api_client, db_session, path)

    elsewhere = [lineage_job(f"elsewhere_{i}", days_ago=9, title=f"Staff Product Manager, Area {i}") for i in range(40)]
    db_session.add_all(elsewhere)
    await db_session.flush()
    for left, right in zip(elsewhere[::2], elsewhere[1::2], strict=True):
        a, b = sorted((left.id, right.id))
        db_session.add(JobTwinLink(
            job_a_id=a, job_b_id=b, method="manual", score=None, title_similarity=None, confidence="suspected",
            status="confirmed", reviewed_at=NOW, detector_version=TWIN_DETECTOR_VERSION,
        ))
    await db_session.commit()
    after, read_after = await _twin_link_rows(api_client, db_session, path)

    assert after == before
    assert before["size"] == 3 and read_before > 0
    assert read_after == read_before, "the twins read grew with pairs outside the posting's component"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("verdict", "status", "decision", "stack", "lineages"),
    [
        ("confirmed", "confirmed", "duplicate", ["pending_prior", "pending_newer"], 2),
        ("rejected", "rejected", "different", None, 1),
        ("twin", "rejected", "twin", None, 1),
    ],
)
async def test_a_duplicate_verdict_is_read_back_through_what_it_changed(
    api_client, db_session, pinned, verdict, status, decision, stack, lineages
):
    seeded = await seed_lineage_contract(db_session)
    body = await _json(api_client, "POST", f"/api/lineage/links/{seeded.pending_link}/review", json={"verdict": verdict})
    assert list(body) == _fields(contract.DuplicateVerdictResult)
    twin_link_id = body.pop("twin_link_id")
    assert body == {"id": seeded.pending_link, "status": status, "reviewed_at": _iso(NOW), "lineages": lineages, "decision": decision, "kept": []}
    assert await _lineage_count(db_session) == lineages

    lineage = await _json(api_client, "GET", f"/api/jobs/{seeded.pending_newer}/lineage")
    members = [m["job"]["id"] for m in lineage["members"]]
    assert members == ([getattr(seeded, key) for key in stack] if stack else [])
    twins = await _json(api_client, "GET", f"/api/jobs/{seeded.pending_newer}/twins")
    if verdict == "twin":
        assert twins["members"][1]["link"]["id"] == twin_link_id
        assert (twins["members"][1]["job"]["id"], twins["members"][1]["direct"]) == (seeded.pending_prior, True)
    else:
        assert (twin_link_id, twins["size"]) == (None, 1)


@pytest.mark.asyncio
async def test_withdrawing_a_duplicate_verdict_returns_the_pair_to_the_queue(api_client, db_session, pinned):
    seeded = await seed_lineage_contract(db_session)
    body = await _json(api_client, "POST", f"/api/lineage/links/{seeded.duplicate_link}/review", json={"verdict": "pending"})
    assert body == {
        "id": seeded.duplicate_link, "status": "pending", "reviewed_at": None, "lineages": 1,
        "decision": None, "twin_link_id": None, "kept": [],
    }
    stack = await _json(api_client, "GET", f"/api/jobs/{seeded.repost}/lineage")
    assert [m["job"]["id"] for m in stack["members"]] == [seeded.original, seeded.repost]
    queue = await _json(api_client, "GET", "/api/lineage/review")
    assert [(i["link"]["id"], i["link"]["decision"], i["link"]["decision_changes"]) for i in queue["items"]] == [
        (seeded.duplicate_link, None, 2), (seeded.pending_link, None, 0),
    ]


@pytest.mark.asyncio
async def test_changing_a_verdict_replaces_the_one_before_it(api_client, db_session, pinned):
    seeded = await seed_lineage_contract(db_session)
    body = await _json(api_client, "POST", f"/api/lineage/links/{seeded.rejected_link}/review", json={"verdict": "confirmed"})
    assert body == {
        "id": seeded.rejected_link, "status": "confirmed", "reviewed_at": _iso(NOW), "lineages": 1,
        "decision": "duplicate", "twin_link_id": None, "kept": [],
    }
    stack = await _json(api_client, "GET", f"/api/jobs/{seeded.rejected}/lineage")
    assert [m["job"]["id"] for m in stack["members"]] == [seeded.original, seeded.repost, seeded.duplicate, seeded.rejected]
    assert stack["members"][-1]["link"]["decision_changes"] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("verdict", "status", "decision"),
    [("confirmed", "confirmed", "twin"), ("rejected", "rejected", "different"), ("duplicate", "rejected", "duplicate")],
)
async def test_a_twin_verdict_is_read_back_through_what_it_changed(api_client, db_session, pinned, verdict, status, decision):
    seeded = await seed_lineage_contract(db_session)
    body = await _json(api_client, "POST", f"/api/twins/links/{seeded.twin_pending}/review", json={"verdict": verdict})
    assert list(body) == _fields(contract.TwinVerdictResult)
    lineages = 2 if verdict == "duplicate" else 1
    assert body == {"id": seeded.twin_pending, "status": status, "decision": decision, "reviewed_at": _iso(NOW), "lineages": lineages, "kept": []}

    twins = await _json(api_client, "GET", f"/api/jobs/{seeded.twin_right}/twins")
    lineage = await _json(api_client, "GET", f"/api/jobs/{seeded.twin_right}/lineage")
    if verdict == "confirmed":
        assert (twins["size"], twins["direct_count"]) == (4, 1)
        assert lineage["lineage_id"] is None
    elif verdict == "rejected":
        assert (twins["size"], lineage["lineage_id"]) == (1, None)
    else:
        assert twins["size"] == 1
        assert [m["job"]["id"] for m in lineage["members"]] == [seeded.twin_left, seeded.twin_right]


@pytest.mark.asyncio
async def test_withdrawing_a_twin_verdict_breaks_the_component_it_joined(api_client, db_session, pinned):
    seeded = await seed_lineage_contract(db_session)
    body = await _json(api_client, "POST", f"/api/twins/links/{seeded.twin_reviewed}/review", json={"verdict": "pending"})
    assert body == {"id": seeded.twin_reviewed, "status": "pending", "decision": None, "reviewed_at": None, "lineages": 1, "kept": []}
    assert (await _json(api_client, "GET", f"/api/jobs/{seeded.twin_left}/twins"))["size"] == 1
    assert (await _json(api_client, "GET", f"/api/jobs/{seeded.twin_hub}/twins"))["size"] == 2


@pytest.mark.asyncio
async def test_a_manual_twin_is_confirmed_and_read_back(api_client, db_session, pinned):
    seeded = await seed_lineage_contract(db_session)
    body = await _json(
        api_client, "POST", "/api/twins/links", expected=201,
        json={"job_id": seeded.solo, "twin_job_id": seeded.pending_prior},
    )
    assert list(body) == _fields(contract.TwinLinkCreated)
    assert body == {"id": body["id"], "status": "confirmed", "decision": "twin"}
    twins = await _json(api_client, "GET", f"/api/jobs/{seeded.solo}/twins")
    (_, partner) = twins["members"]
    assert (partner["job"]["id"], partner["direct"], partner["link"]["id"], partner["link"]["method"]) == (
        seeded.pending_prior, True, body["id"], "manual",
    )


@pytest.mark.asyncio
async def test_rejecting_a_link_keeps_it_as_a_negative_label(api_client, db_session, pinned):
    seeded = await seed_lineage_contract(db_session)
    body = await _json(api_client, "DELETE", f"/api/lineage/links/{seeded.repost_link}")
    assert list(body) == _fields(contract.LineageLinkRejected)
    assert body == {"id": seeded.repost_link, "status": "rejected", "lineages": 1}
    assert (await _json(api_client, "GET", f"/api/jobs/{seeded.original}/lineage"))["lineage_id"] is None
    stack = await _json(api_client, "GET", f"/api/jobs/{seeded.repost}/lineage")
    assert [m["job"]["id"] for m in stack["members"]] == [seeded.repost, seeded.duplicate]
    link = await db_session.get(JobLineageLink, seeded.repost_link)
    await db_session.refresh(link)
    assert (link.status, link.reviewed_at) == ("rejected", NOW)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("path", "link_key"),
    [("lineage", "pending_link"), ("twins", "twin_pending")],
    ids=["duplicate", "twin"],
)
async def test_the_models_advice_is_served_and_the_human_verdict_is_untouched(api_client, db_session, pinned, path, link_key):
    seeded = await seed_lineage_contract(db_session)
    before = await _relationships(db_session)
    body = await _json(api_client, "POST", f"/api/{path}/links/{getattr(seeded, link_key)}/analyze")
    assert list(body) == _fields(contract.RelationshipAssessment)
    assert list(body["metrics"]) == _fields(LocalModelMetrics)
    assert body == {
        "profile_id": seeded.profile_id, "provider": "omlx", "model": MODEL_ID, "prompt_version": PROMPT_VERSION,
        "assessment": ASSESSMENT,
        "metrics": {
            "wall_time_ms": 9412, "total_time_ms": 9400, "time_to_first_token_ms": 610, "prompt_eval_ms": 1200,
            "generation_ms": 8200, "prompt_tokens": 1830, "completion_tokens": 212, "total_tokens": 2042,
            "cached_prompt_tokens": 512, "prompt_tokens_per_second": 1525.0, "generation_tokens_per_second": 25.9,
            "finish_reason": "stop", "context_window": 32768,
        },
    }
    assert await _relationships(db_session) == before, "advice changed a relationship"


@pytest.mark.asyncio
async def test_token_counts_and_rates_arrive_as_the_server_sent_them(api_client, db_session, monkeypatch, no_escape):
    seeded = await seed_lineage_contract(db_session)
    pin_lineage_environment(monkeypatch, usage={**USAGE, "prompt_tokens": 1830.0, "prompt_tokens_per_second": 1525})
    response = await api_client.post(f"/api/lineage/links/{seeded.pending_link}/analyze")
    assert response.status_code == 200, response.text
    assert '"prompt_tokens":1830.0,' in response.text
    assert '"prompt_tokens_per_second":1525,' in response.text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method", "path", "payload", "status"),
    [
        ("GET", "/api/jobs/999999/lineage", None, 404),
        ("GET", "/api/jobs/999999/twins", None, 404),
        ("GET", "/api/lineage/review?status=everything", None, 400),
        ("GET", "/api/twins/review?status=everything", None, 400),
        ("GET", "/api/lineage/review?limit=201", None, 422),
        ("GET", "/api/lineage/review?order=newest", None, 422),
        ("POST", "/api/lineage/links/{pending_link}/review", {"verdict": "maybe"}, 422),
        ("POST", "/api/lineage/links/999999/review", {"verdict": "confirmed"}, 404),
        ("POST", "/api/twins/links/{twin_pending}/review", {"verdict": "twin"}, 422),
        ("POST", "/api/twins/links/999999/review", {"verdict": "confirmed"}, 404),
        ("POST", "/api/twins/links", {"job_id": "{solo}", "twin_job_id": "{solo}"}, 400),
        ("POST", "/api/twins/links", {"job_id": "{solo}", "twin_job_id": "{other_company}"}, 400),
        ("POST", "/api/twins/links", {"job_id": "{original}", "twin_job_id": "{repost}"}, 409),
        ("POST", "/api/twins/links", {"job_id": "{solo}", "twin_job_id": 999999}, 404),
        ("DELETE", "/api/lineage/links/999999", None, 404),
        ("POST", "/api/lineage/links/999999/analyze", None, 404),
        ("POST", "/api/twins/links/999999/analyze", None, 404),
    ],
    ids=[
        "lineage_unknown_job", "twins_unknown_job", "duplicate_lens_unknown", "twin_lens_unknown", "page_over_200", "order_unknown",
        "duplicate_verdict_unknown", "duplicate_link_unknown", "twin_verdict_of_the_other_kind", "twin_link_unknown",
        "twin_to_itself", "twin_across_companies", "twin_inside_one_lineage", "twin_unknown_job",
        "reject_unknown_link",
        "advise_unknown_duplicate", "advise_unknown_twin",
    ],
)
async def test_a_refused_request_changes_no_relationship(api_client, db_session, pinned, method, path, payload, status):
    seeded = await seed_lineage_contract(db_session)
    ids = vars(seeded)
    if isinstance(payload, dict):
        # `"{solo}"` names a seeded row; any other value is sent as written.
        payload = {key: ids[v[1:-1]] if isinstance(v, str) and v.startswith("{") else v for key, v in payload.items()}
    before = await _relationships(db_session)
    response = await api_client.request(method, path.format(**ids), json=payload)
    assert response.status_code == status, response.text
    assert await _relationships(db_session) == before


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("local_model", "reply", "status"),
    [(False, None, 409), (True, "not json at all", 502)],
    ids=["local_models_off", "invalid_assessment"],
)
async def test_advice_that_cannot_be_given_changes_no_relationship(
    api_client, db_session, monkeypatch, no_escape, local_model, reply, status
):
    seeded = await seed_lineage_contract(db_session, local_model=local_model)
    pin_lineage_environment(monkeypatch, model_reply=reply)
    before = await _relationships(db_session)
    response = await api_client.post(f"/api/lineage/links/{seeded.pending_link}/analyze")
    assert response.status_code == status, response.text
    assert await _relationships(db_session) == before


# --------------------------------------------------------------------------- #
# 3. Drift
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_a_proposal_key_the_model_does_not_name_fails_the_queue(api_client, db_session, pinned, monkeypatch):
    await seed_lineage_contract(db_session)
    real = lineage_router._serialize_link
    monkeypatch.setattr(lineage_router, "_serialize_link", lambda link: {**real(link), "detector_version": "v9"})
    with pytest.raises(ResponseValidationError):
        await api_client.get("/api/lineage/review")


@pytest.mark.asyncio
async def test_a_twin_proposal_missing_its_stored_evidence_fails_the_queue(api_client, db_session, pinned, monkeypatch):
    await seed_lineage_contract(db_session)
    real = lineage_router._serialize_twin_link

    def without_evidence(link):
        row = real(link)
        row.pop("description_diff")
        return row

    monkeypatch.setattr(lineage_router, "_serialize_twin_link", without_evidence)
    with pytest.raises(ResponseValidationError):
        await api_client.get("/api/twins/review")


@pytest.mark.asyncio
async def test_a_diff_key_the_model_does_not_name_fails_the_stack(api_client, db_session, pinned, monkeypatch):
    seeded = await seed_lineage_contract(db_session)
    real = lineage_router.build_member_diff
    monkeypatch.setattr(
        lineage_router, "build_member_diff", lambda prev, cur: {**real(prev, cur), "team": {"from": "A", "to": "B"}},
    )
    with pytest.raises(ResponseValidationError):
        await api_client.get(f"/api/jobs/{seeded.repost}/lineage")


@pytest.mark.asyncio
async def test_a_posting_key_the_model_does_not_name_fails_the_twins(api_client, db_session, pinned, monkeypatch):
    seeded = await seed_lineage_contract(db_session)
    real = lineage_router.serialize_job
    monkeypatch.setattr(lineage_router, "serialize_job", lambda job, **kw: {**real(job, **kw), "salary": 1})
    with pytest.raises(ResponseValidationError):
        await api_client.get(f"/api/jobs/{seeded.twin_left}/twins")


@pytest.mark.asyncio
async def test_a_metric_the_model_does_not_name_fails_the_advice(api_client, db_session, pinned, monkeypatch):
    seeded = await seed_lineage_contract(db_session)
    real = lineage_router.assess_duplicate

    async def with_cost(*args, **kwargs):
        result = await real(*args, **kwargs)
        return {**result, "metrics": {**result["metrics"], "cost_usd": 0.0}}

    monkeypatch.setattr(lineage_router, "assess_duplicate", with_cost)
    with pytest.raises(ResponseValidationError):
        await api_client.post(f"/api/lineage/links/{seeded.pending_link}/analyze")


@pytest.mark.asyncio
async def test_a_rebuild_that_counts_nothing_fails_the_verdict(api_client, db_session, pinned, monkeypatch):
    seeded = await seed_lineage_contract(db_session)

    async def uncounted(_session):
        return None

    monkeypatch.setattr(lineage_router, "rebuild_lineage_projection", uncounted)
    with pytest.raises(ResponseValidationError):
        await api_client.post(f"/api/lineage/links/{seeded.pending_link}/review", json={"verdict": "confirmed"})


@pytest.mark.asyncio
async def test_a_verdict_status_outside_the_vocabulary_fails_the_verdict(api_client, db_session, pinned, monkeypatch):
    seeded = await seed_lineage_contract(db_session)

    async def withdrawn(_session, link):
        link.status = "withdrawn"
        return dict(link.evidence or {}), []

    monkeypatch.setattr(verdicts, "_withdraw_verdict", withdrawn)
    with pytest.raises(ResponseValidationError):
        await api_client.post(f"/api/twins/links/{seeded.twin_reviewed}/review", json={"verdict": "pending"})
