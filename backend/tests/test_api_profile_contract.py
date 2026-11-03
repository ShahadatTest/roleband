"""The pay floor and pursuit routes' response contract.

`tracker/api/schemas/profile.py` declares what `/api/profile/pay-floor`,
`/api/pursuits` and `PUT /api/jobs/{job_id}/pursuit` send. These tests hold it
over real HTTP against `tests/profile_contract_seed.py`:

1. **Shapes and vocabularies**: built shapes forbid unknown keys; stages are the
   ones the writer owns.
2. **An empty profile**: each read answers its empty shape.
3. **Pursuits**: highest priority first with the opportunity each tracks, narrowed
   by stage and limit; a write answers the row without its opportunity.
4. **Drift**: a builder that adds or mistypes a key fails the response.

`no_escape` guards every seeded test.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import get_args

import pytest
import pytest_asyncio
from fastapi.exceptions import ResponseValidationError
from pydantic import BaseModel

from tests.api_errors import said
from tests.profile_contract_seed import SeededProfile, seed_profile
from tracker.agents import pursuits as pursuit_writer
from tracker.api.routers import profile as router
from tracker.api.schemas import profile as contract
from tracker.api.schemas.jobs import JobPursuit, PursuitStage
from tracker.db.models import Pursuit


@pytest_asyncio.fixture
async def seeded(api_client, db_session, no_escape) -> SeededProfile:
    return await seed_profile(db_session)


def _fields(model) -> list[str]:
    return list(model.model_fields)


async def _get(api_client, path: str, status: int = 200) -> dict:
    response = await api_client.get(path)
    assert response.status_code == status, response.text
    return response.json()


async def _send(api_client, method: str, path: str, body: dict | None = None, status: int = 200) -> dict:
    response = await api_client.request(method, path, json=body)
    assert response.status_code == status, response.text
    return response.json()


# --------------------------------------------------------------------------- #
# 1-2. Shapes, vocabularies and an empty profile
# --------------------------------------------------------------------------- #


def test_built_shapes_forbid_unknown_keys():
    built = [
        model for model in vars(contract).values()
        if isinstance(model, type) and issubclass(model, BaseModel) and model.__module__ == contract.__name__
    ]
    assert len(built) >= 6
    assert [m.__name__ for m in built if m.model_config.get("extra") != "forbid"] == []


def test_stages_are_the_ones_the_writer_owns():
    [check] = [c for c in Pursuit.__table__.constraints if c.name == "ck_pursuit_stage"]
    admitted = set(re.findall(r"'([^']+)'", str(check.sqltext)))
    assert set(get_args(PursuitStage)) == set(get_args(pursuit_writer.PursuitStage)) == admitted


@pytest.mark.asyncio
async def test_an_empty_profile_answers_each_read_with_nothing_in_it(api_client, no_escape):
    assert await _get(api_client, "/api/pursuits") == {"pursuits": []}
    assert await _get(api_client, "/api/profile/pay-floor") == {"pay_floor": None}


# --------------------------------------------------------------------------- #
# 3. Pursuits
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_pursuits_list_highest_priority_first_with_the_opportunity_each_tracks(api_client, seeded):
    j, p = seeded.jobs, seeded.pursuits
    body = await _get(api_client, "/api/pursuits")
    assert list(body) == _fields(contract.PursuitListResponse)
    assert all(list(item) == _fields(contract.PursuitListItem) for item in body["pursuits"])
    assert _fields(contract.PursuitListItem) == [*_fields(JobPursuit), "opportunity"]
    assert body["pursuits"][0] == {
        "id": p["applied"], "job_id": j["applied"], "stage": "applied", "priority": 1,
        "notes": "Referred by a former colleague.", "next_action": "Prepare the product sense interview",
        "next_action_due": "2026-07-23T15:00:00Z", "created_at": "2026-07-14T15:00:00Z",
        "updated_at": "2026-07-19T15:00:00Z",
        "opportunity": {"title": "Staff Product Manager, Cloud AI", "company": "google", "status": "open",
                        "url": "https://careers.example.test/google-applied"},
    }
    # Equal priority: the most recently updated first. A closed role is still tracked.
    assert [(i["id"], i["opportunity"]["status"]) for i in body["pursuits"][1:]] == [
        (p["interviewing"], "open"), (p["rejected"], "closed"),
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("stage=applied", ["applied"]),
        ("stage=offer", []),
        ("limit=1", ["applied"]),
        ("stage=interviewing&limit=5", ["interviewing"]),
    ],
    ids=["one_stage", "empty_stage", "limit", "stage_and_limit"],
)
async def test_pursuits_narrow_by_stage_and_limit(api_client, seeded, query, expected):
    body = await _get(api_client, f"/api/pursuits?{query}")
    assert [item["id"] for item in body["pursuits"]] == [seeded.pursuits[key] for key in expected]


@pytest.mark.asyncio
async def test_an_unknown_stage_is_refused(api_client, seeded):
    await _get(api_client, "/api/pursuits?stage=promoted", status=422)


@pytest.mark.asyncio
async def test_a_pursuit_write_answers_the_row_without_its_opportunity(api_client, seeded):
    j, p = seeded.jobs, seeded.pursuits
    created = await _send(api_client, "PUT", f"/api/jobs/{j['saved']}/pursuit", {
        "stage": "researching", "priority": 2, "next_action_due": "2026-07-25T09:00:00Z",
    })
    assert list(created) == _fields(contract.PursuitWriteResponse)
    row = created["pursuit"]
    assert list(row) == _fields(JobPursuit)
    assert {k: row[k] for k in ("job_id", "stage", "priority", "notes", "next_action", "next_action_due")} == {
        "job_id": j["saved"], "stage": "researching", "priority": 2, "notes": None, "next_action": None,
        "next_action_due": "2026-07-25T09:00:00Z",
    }
    assert datetime.fromisoformat(row["created_at"]).tzinfo is not None

    updated = (await _send(api_client, "PUT", f"/api/jobs/{j['applied']}/pursuit",
                           {"notes": None, "stage": "interviewing"}))["pursuit"]
    assert (updated["id"], updated["stage"], updated["notes"], updated["next_action"], updated["created_at"]) == (
        p["applied"], "interviewing", None, "Prepare the product sense interview", "2026-07-14T15:00:00Z",
    )
    listed = (await _get(api_client, "/api/pursuits"))["pursuits"]
    assert [item["id"] for item in listed] == [p["applied"], row["id"], p["interviewing"], p["rejected"]]
    assert {k: v for k, v in listed[1].items() if k != "opportunity"} == row

    assert said(await _send(api_client, "PUT", "/api/jobs/999999/pursuit", {"stage": "saved"}, status=404)) == {
        "detail": "opportunity not found",
    }


# --------------------------------------------------------------------------- #
# 4. Drift
# --------------------------------------------------------------------------- #


def _pursuits_adding(real):
    async def drifted(*args, **kwargs):
        return [{**item, "unmodelled": True} for item in await real(*args, **kwargs)]

    return drifted


def _stage_outside_the_vocabulary(real):
    return lambda pursuit, job=None: {**real(pursuit, job), "stage": "promoted"}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("name", "drift", "method", "path", "body"),
    [
        ("list_pursuits", _pursuits_adding, "GET", "/api/pursuits", None),
        ("public_pursuit", _stage_outside_the_vocabulary, "PUT", "/api/jobs/{saved}/pursuit", {"stage": "saved"}),
    ],
    ids=["pursuit_key_added", "stage_unknown"],
)
async def test_a_builder_that_drifts_fails_the_response(api_client, seeded, monkeypatch, name, drift, method, path,
                                                       body):
    monkeypatch.setattr(router, name, drift(getattr(router, name)))
    with pytest.raises(ResponseValidationError):
        await api_client.request(method, path.format(**seeded.jobs), json=body)
