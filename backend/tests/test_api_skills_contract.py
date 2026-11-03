"""The skills and cluster routes' response contract.

`tracker/api/schemas/skills.py` declares what `/api/skills/top`,
`/api/skills/trends`, `/api/skills/overlap`, `/api/clusters` and
`/api/clusters/{cluster_id}` send. These tests hold it over real HTTP against
`tests/skills_contract_seed.py`:

1. **Shapes**: built shapes forbid unknown keys; a stored cluster term keeps them.
2. **An empty radar**: each list route answers its empty shape.
3. **The leaderboard** counts evidence-grounded requirements on open, in-scope,
   visible roles, never industries, deprecated concepts, context mentions or
   low-confidence extractions, and narrows by company, family and location.
4. **The trends** read the rollup inside the window, zero-filled over a shared
   axis, by named terms in order or by latest count.
5. **The overlap** ranks companies by open roles above a per-company floor.
6. **Clusters** size themselves from stored sizes, or from the visible mix once a
   company is hidden, and list members most central first.
7. **Drift**: a builder that adds, drops or mistypes a key fails the response.

`pin_skills_clock` fixes the trend window's "now"; `no_escape` guards every test.
Counts are asserted as sets wherever the route leaves a tie unordered.
"""

from __future__ import annotations

import json
from datetime import timedelta

import pytest
import pytest_asyncio
from fastapi.exceptions import ResponseValidationError
from pydantic import BaseModel
from sqlalchemy import select

from tests.api_errors import said
from tests.skills_contract_seed import (
    DAY_START,
    SeededSkills,
    hide_company,
    pin_skills_clock,
    seed_skills,
)
from tracker.api.routers import skills as router
from tracker.api.schemas import skills as contract
from tracker.api.schemas.jobs import JobRow
from tracker.db.models import Cluster


@pytest_asyncio.fixture
async def clock(monkeypatch, no_escape):
    pin_skills_clock(monkeypatch)


@pytest_asyncio.fixture
async def seeded(api_client, db_session, clock) -> SeededSkills:
    return await seed_skills(db_session)


@pytest_asyncio.fixture
async def hidden(db_session, seeded) -> SeededSkills:
    await hide_company(db_session)
    return seeded


def _fields(model) -> list[str]:
    return list(model.model_fields)


async def _get(api_client, path: str, status: int = 200) -> dict:
    response = await api_client.get(path)
    assert response.status_code == status, response.text
    return response.json()


def _day(days_before_today: int) -> str:
    return (DAY_START - timedelta(days=days_before_today)).date().isoformat()


def _counts(body: dict) -> dict[str, int]:
    """Roles per concept, skills and competencies alike (the API lists them apart)."""
    return {item["term"]: item["job_count"] for item in body["items"] + body["competencies"]}


# --------------------------------------------------------------------------- #
# 1-2. Shapes and an empty radar
# --------------------------------------------------------------------------- #


def test_built_shapes_forbid_unknown_keys_and_a_stored_term_keeps_them():
    built = [
        model for model in vars(contract).values()
        if isinstance(model, type) and issubclass(model, BaseModel) and model.__module__ == contract.__name__
        and model is not contract.ClusterTerm
    ]
    assert len(built) >= 11
    assert [m.__name__ for m in built if m.model_config.get("extra") != "forbid"] == []
    assert contract.ClusterTerm.model_config.get("extra") == "allow"


@pytest.mark.asyncio
async def test_an_empty_radar_answers_each_list_with_nothing_in_it(api_client, clock):
    assert await _get(api_client, "/api/skills/top") == {
        "items": [], "competencies": [], "roles": 0, "market_roles": 0, "narrowed": False,
    }
    assert await _get(api_client, "/api/skills/trends") == {"days": 90, "dates": [], "series": [], "set_changes": []}
    assert await _get(api_client, "/api/skills/overlap") == {"companies": [], "pairs": [], "min_jobs": 2}
    assert await _get(api_client, "/api/clusters") == {"items": [], "model_version": None}


# --------------------------------------------------------------------------- #
# 3. The leaderboard
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_the_leaderboard_counts_only_grounded_requirements_on_visible_open_roles(api_client, hidden):
    body = await _get(api_client, "/api/skills/top")
    assert list(body) == _fields(contract.TopSkillsResponse)
    assert all(list(item) == _fields(contract.TopSkill) for item in body["items"])
    # Not g4's context mention or low-confidence sql, not a closed or out-of-scope role,
    # not the hidden company, never an industry or a deprecated concept.
    assert [(i["term"], i["category"], i["job_count"]) for i in body["items"]] == [
        ("python", "language", 7),
        ("kubernetes", "platform", 4),
        ("sql", "language", 2),
    ]
    # A competency is listed apart, never ranked with the skills.
    assert [(i["term"], i["job_count"]) for i in body["competencies"]] == [("stakeholder-management", 3)]
    assert all(list(item) == _fields(contract.TopSkill) for item in body["competencies"])
    # The whole market: share of the roles naming any skill, lift 1, nothing distinctive.
    assert body["narrowed"] is False and body["roles"] == body["market_roles"] > 0
    python = body["items"][0]
    assert python["share"] == round(7 / body["roles"], 4) == python["market_share"]
    assert (python["lift"], python["distinctiveness"]) == (1.0, 0.0)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("company=google", {"python": 3, "sql": 2, "kubernetes": 1}),
        # The limit applies to each list: two skills, and the slice's one competency.
        ("company=google&company=openai&limit=2", {"python": 5, "kubernetes": 4, "stakeholder-management": 2}),
        ("family=product_management", {"python": 4, "sql": 2, "kubernetes": 1}),
        ("location_group=silicon_valley", {"python": 7, "kubernetes": 4, "stakeholder-management": 3, "sql": 2}),
        ("location_group=london", {}),
    ],
    ids=["one_company", "two_companies_limited", "family", "location", "no_location_match"],
)
async def test_the_leaderboard_narrows_by_company_family_location_and_limit(api_client, hidden, query, expected):
    assert _counts(await _get(api_client, f"/api/skills/top?{query}")) == expected


@pytest.mark.asyncio
async def test_a_narrowed_slice_leads_with_what_sets_it_apart(api_client, hidden):
    """By count, every slice would lead with the same ubiquitous concepts. A
    slice leads with the skill most characteristic of it against the rest
    of the market: OpenAI's roles carry 3 of the market's 4 Kubernetes
    requirements, while naming Python less often than the market does."""
    body = await _get(api_client, "/api/skills/top?company=openai")
    assert body["narrowed"] is True and body["roles"] < body["market_roles"]
    first, *rest = body["items"]
    assert first["term"] == "kubernetes" and first["lift"] > 1 and first["distinctiveness"] > 0
    python = next(i for i in rest if i["term"] == "python")
    assert python["distinctiveness"] < first["distinctiveness"]
    # The whole market is not narrowed: lift 1, ranked by share.
    market = await _get(api_client, "/api/skills/top")
    assert [i["term"] for i in market["items"]][0] == "python"


@pytest.mark.asyncio
async def test_a_visible_company_counts_until_it_is_hidden(api_client, db_session, seeded):
    visible = _counts(await _get(api_client, "/api/skills/top"))
    assert (visible["python"], visible["sql"]) == (9, 4)
    await hide_company(db_session)
    assert _counts(await _get(api_client, "/api/skills/top")) == {
        "python": 7, "kubernetes": 4, "stakeholder-management": 3, "sql": 2,
    }


# --------------------------------------------------------------------------- #
# 4. The trends
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_trends_are_zero_filled_over_a_shared_axis_inside_the_window(api_client, hidden):
    body = await _get(api_client, "/api/skills/trends")
    assert list(body) == _fields(contract.SkillTrendsResponse)
    assert (body["days"], body["dates"]) == (90, [_day(2), _day(1)])
    assert all(list(s) == _fields(contract.SkillTrendSeries) for s in body["series"])
    # Top by the latest count; the hidden company's slice is not in python's 5.
    # Slugs only: the dashboard names each skill.
    assert [(s["term"], s["current"], s["delta"]) for s in body["series"]] == [
        ("python", 5, 3), ("kubernetes", 3, 2), ("sql", 2, 2),
    ]
    sql = body["series"][2]["points"]
    assert [(p["date"], p["job_count"]) for p in sql] == [(_day(2), 0), (_day(1), 2)]
    # Each point is also its share of the day's skill mentions.
    assert sql[0]["share"] == 0.0 and 0 < sql[1]["share"] < 1
    assert body["series"][2]["current_share"] == sql[1]["share"]

    all_time = await _get(api_client, "/api/skills/trends?days=0")
    assert all_time["dates"] == [_day(120), _day(2), _day(1)]
    assert (all_time["series"][0]["term"], all_time["series"][0]["delta"]) == ("python", 4)


@pytest.mark.asyncio
async def test_named_terms_come_back_in_order_and_filters_narrow_the_rollup(api_client, hidden):
    named = await _get(api_client, "/api/skills/trends?term=sql&term=python")
    assert [s["term"] for s in named["series"]] == ["sql", "python"]
    assert (await _get(api_client, "/api/skills/trends?term=nope"))["series"] == []
    openai = await _get(api_client, "/api/skills/trends?company=openai")
    assert [(s["term"], s["current"]) for s in openai["series"]] == [("kubernetes", 3), ("python", 2)]
    assert [s["term"] for s in (await _get(api_client, "/api/skills/trends?limit=1"))["series"]] == ["python"]


# --------------------------------------------------------------------------- #
# 5. The overlap
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_every_read_that_counts_skills_counts_the_same_requirements(api_client, db_session, seeded):
    """The leaderboard, the daily demand rollup and a group's labels read one rule
    (`ELIGIBLE_REQUIREMENT`). g4's context mention and low-confidence sql, the
    industry and the deprecated concept count in none of them, and each reader
    finds python on the same roles."""
    from datetime import UTC, datetime

    from tracker.db.models import Job, SkillConcept, SkillDemandDaily
    from tracker.semantic.cluster import _member_skills
    from tracker.skills.analytics import compute_skill_demand

    leaderboard = _counts(await _get(api_client, "/api/skills/top?limit=50"))

    await compute_skill_demand(db_session)
    today = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    demand: dict[str, int] = {}
    for slug, count in (
        await db_session.execute(
            select(SkillConcept.slug, SkillDemandDaily.job_count)
            .join(SkillConcept, SkillConcept.id == SkillDemandDaily.concept_id)
            .where(SkillDemandDaily.metric_date == today)
        )
    ).all():
        demand[slug] = demand.get(slug, 0) + count

    open_ids = list(
        (await db_session.scalars(select(Job.id).where(Job.status == "open", Job.in_scope.is_(True)))).all()
    )
    by_job, _meta = await _member_skills(db_session, open_ids)
    labelled: dict[str, int] = {}
    for slugs in by_job.values():
        for slug in slugs:
            labelled[slug] = labelled.get(slug, 0) + 1

    for reader in (leaderboard, demand, labelled):
        assert not {"fintech", "perl"} & set(reader), reader
    assert leaderboard["python"] == demand["python"] == labelled["python"]
    assert leaderboard["sql"] == demand["sql"] == labelled["sql"]
    assert seeded.jobs["g4"] not in by_job, "a context mention and a low-confidence read are not skills"


@pytest.mark.asyncio
async def test_overlap_scores_what_companies_share_beyond_what_every_company_names(api_client, hidden):
    """Generic skills shared by every company must not inflate similarity.
    Each company is a rarity-weighted skill vector with competencies excluded;
    when Python is the only shared skill and all companies name it, pairs score 0."""
    body = await _get(api_client, "/api/skills/overlap")
    assert list(body) == _fields(contract.SkillOverlapResponse)
    # Stakeholder management is a competency: OpenAI's set is Python and Kubernetes.
    assert body["companies"] == [
        {"company": "google", "skill_count": 2, "open": 5},
        {"company": "openai", "skill_count": 2, "open": 3},
        {"company": "anthropic", "skill_count": 1, "open": 2},
    ]
    assert body["pairs"] == [
        {"a": "google", "b": "openai", "shared": 1, "union": 3, "similarity": 0.0, "top_shared": ["python"]},
        {"a": "google", "b": "anthropic", "shared": 1, "union": 2, "similarity": 0.0, "top_shared": ["python"]},
        {"a": "openai", "b": "anthropic", "shared": 1, "union": 2, "similarity": 0.0, "top_shared": ["python"]},
    ]
    assert body["min_jobs"] == 2


@pytest.mark.asyncio
async def test_a_lower_floor_widens_each_set_and_a_company_limit_drops_every_pair(api_client, hidden):
    floor_one = await _get(api_client, "/api/skills/overlap?min_jobs=1")
    pairs = {(p["a"], p["b"]): p for p in floor_one["pairs"]}
    # Google and OpenAI now also share Kubernetes, which two of the three name:
    # that is what scores, and it weighs more than Python, which all three name.
    assert pairs[("google", "openai")]["top_shared"] == ["kubernetes", "python"]
    assert pairs[("google", "openai")]["similarity"] > 0
    assert pairs[("openai", "anthropic")]["similarity"] == 0.0
    assert floor_one["min_jobs"] == 1
    assert await _get(api_client, "/api/skills/overlap?limit_companies=1") == {
        "companies": [{"company": "google", "skill_count": 2, "open": 5}], "pairs": [], "min_jobs": 2,
    }


@pytest.mark.asyncio
async def test_the_companies_compared_can_be_named(api_client, hidden):
    body = await _get(api_client, "/api/skills/overlap?company=openai&company=google&company=nope")
    assert [c["company"] for c in body["companies"]] == ["openai", "google"]
    assert [(p["a"], p["b"]) for p in body["pairs"]] == [("openai", "google")]


# --------------------------------------------------------------------------- #
# 6. Clusters
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_with_nothing_hidden_a_cluster_states_its_current_members(api_client, seeded):
    """The size is the members shown (open, in scope), never the stored count
    the last pass made: here "Python · SQL" is stored at 5 and "Other" at 1 with
    its only member closed."""
    body = await _get(api_client, "/api/clusters")
    assert list(body) == _fields(contract.ClusterListResponse)
    assert all(list(item) == _fields(contract.ClusterSummary) for item in body["items"])
    # Named by the dashboard from its terms, then its family.
    assert [([t["term"] for t in i["top_terms"]], i["family_hint"], i["size"], i["companies"]) for i in body["items"]] == [
        (["python", "sql"], "product_management", 4, {"google": 3, "hidden-co": 1}),
        (["kubernetes"], "engineering_management", 3, {"openai": 3}),
        ([], None, 1, {"hidden-co": 1}),
    ]
    assert body["model_version"] == "c-2026-07"
    # Top terms as the clustering pass stored them, in the order Postgres serves JSONB keys.
    first = body["items"][0]
    assert first["top_terms"] == [
        {"term": "python", "weight": 255.0},
        {"term": "sql", "weight": 130.5},
    ]
    # The stored English name stays in the database and never reaches the wire.
    assert list(first["top_terms"][0]) == ["term", "weight"]


@pytest.mark.asyncio
async def test_once_a_company_is_hidden_clusters_size_from_the_visible_mix(api_client, hidden):
    body = await _get(api_client, "/api/clusters")
    # Only the hidden company filled one cluster and only a closed role the other: both drop out.
    assert [(i["id"], i["size"], i["companies"]) for i in body["items"]] == [
        (hidden.clusters["c1"], 3, {"google": 3}),
        (hidden.clusters["c2"], 3, {"openai": 3}),
    ]


@pytest.mark.asyncio
async def test_a_cluster_lists_its_open_members_most_central_first(api_client, hidden):
    body = await _get(api_client, f"/api/clusters/{hidden.clusters['c1']}")
    assert list(body) == _fields(contract.ClusterDetailResponse)
    assert all(list(row) == _fields(JobRow) for row in body["items"])
    assert [(row["id"], row["is_favorite"]) for row in body["items"]] == [
        (hidden.jobs["g1"], True), (hidden.jobs["g3"], False), (hidden.jobs["g2"], False),
    ]
    assert body["size"] == 3
    empty = await _get(api_client, f"/api/clusters/{hidden.clusters['c3']}")
    assert (empty["size"], empty["items"]) == (0, [])
    assert said(await _get(api_client, "/api/clusters/999999", status=404)) == {"detail": "cluster not found"}


@pytest.mark.asyncio
async def test_with_nothing_hidden_a_cluster_answers_its_current_size(api_client, seeded):
    body = await _get(api_client, f"/api/clusters/{seeded.clusters['c1']}")
    assert (body["size"], len(body["items"]), body["items"][0]["id"]) == (4, 4, seeded.jobs["h1"])


# --------------------------------------------------------------------------- #
# 7. Drift
# --------------------------------------------------------------------------- #


def _each_skill_adding(real):
    def drifted(*args, **kwargs):
        body = real(*args, **kwargs)
        return {**body, "items": [{**item, "unmodelled": True} for item in body["items"]]}

    return drifted


def _points_without_count(real):
    def drifted(*args, **kwargs):
        axis, series = real(*args, **kwargs)
        return axis, [{**s, "points": [{"date": p["date"]} for p in s["points"]]} for s in series]

    return drifted


def _pair_without_shared(real):
    def drifted(*args, **kwargs):
        return [{k: v for k, v in p.items() if k != "shared"} for p in real(*args, **kwargs)]

    return drifted


def _serialize_adding(real):
    def drifted(*args, **kwargs):
        return {**real(*args, **kwargs), "unmodelled": True}

    return drifted


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("name", "drift", "path"),
    [
        ("rank_skills", _each_skill_adding, "/api/skills/top"),
        ("build_trend_series", _points_without_count, "/api/skills/trends"),
        ("compute_overlap", _pair_without_shared, "/api/skills/overlap"),
        ("_terms", lambda real: lambda stored: [{"weight": 1.0}], "/api/clusters"),
        ("serialize_job", _serialize_adding, "/api/clusters/{c1}"),
    ],
    ids=["top_skill_key_added", "trend_count_dropped", "pair_shared_dropped", "cluster_term_dropped", "member_key_added"],
)
async def test_a_builder_that_drifts_fails_the_response(api_client, hidden, monkeypatch, name, drift, path):
    monkeypatch.setattr(router, name, drift(getattr(router, name)))
    with pytest.raises(ResponseValidationError):
        await api_client.get(path.format(c1=hidden.clusters["c1"]))


@pytest.mark.asyncio
async def test_a_stored_term_keeps_an_unnamed_key_and_fails_without_its_term(api_client, db_session, hidden):
    cluster = (await db_session.execute(select(Cluster).where(Cluster.id == hidden.clusters["c2"]))).scalar_one()
    await db_session.refresh(cluster)
    terms = json.loads(json.dumps(cluster.top_terms))
    terms[0]["rank"] = 1
    cluster.top_terms = terms
    await db_session.commit()
    items = (await _get(api_client, "/api/clusters"))["items"]
    assert items[1]["top_terms"][0]["rank"] == 1

    cluster.top_terms = [{k: v for k, v in terms[0].items() if k != "term"}]
    await db_session.commit()
    with pytest.raises(ResponseValidationError):
        await api_client.get("/api/clusters")
