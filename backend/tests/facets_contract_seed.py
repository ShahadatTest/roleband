"""Realistic rows and a pinned clock for the similar-postings and facets contract.

`/api/jobs/{job_id}/similar` reads the precomputed `job_similarity` table while it can
answer in full with neighbours that are still open, in scope and visible, and whose stored
score is still the cosine of their vectors; otherwise a live nearest-neighbour query
answers. Every embedded row here sits at exactly its stored score from `cloud`. `/api/facets` counts open, in-scope, visible roles per filter value and
offers visible tracked companies, the role taxonomy, tracked locations that have roles, and
worlds that have roles. `pin_jobs_clock` fixes `datetime.now` in the jobs router AND in the
shared serializer, so `days_open` is stable.

| rows | what they exercise |
|---|---|
| companies | Google, OpenAI and Anthropic; `paused-co`, disabled but still offered; `hidden-co`, which `hide_company` hides |
| `cloud` | the posting asked about, with neighbours in both scopes |
| `closed`, `maps`, `lonely` | same-company neighbours; `closed` closed after the table was built, `maps` is saved, `lonely` has no vector |
| `gpt`, `vault`, `claude` | cross-company neighbours; `vault` at the hidden company, `gpt` dismissed |
| `lonely` | also a posting with no neighbours of its own and no embedding |
| `out` | an out-of-scope role: counted nowhere |
| locations | tracked: Silicon Valley, the United States, New York and the UK (no role names it); London has a role but is not tracked |
| worlds | ai_ml, logistics and security; `gpt` names none and `lonely` predates the axis (NULL) |
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from tests.factories import make_company, make_job
from tracker.config import get_settings
from tracker.db.models import AppSetting, Favorite, Job, JobFeedback, JobSimilarity
from tracker.settings_store import ENABLED_LOCATIONS_KEY
from tracker.taxonomy.locations import LOCATION_GROUPS

NOW = datetime(2026, 7, 20, 15, 0, tzinfo=UTC)
TRACKED_LOCATIONS = ["silicon_valley", "united_states", "new_york", "uk"]


class _Clock(datetime):
    @classmethod
    def now(cls, tz=None):
        return NOW if tz is not None else NOW.replace(tzinfo=None)


def pin_jobs_clock(monkeypatch) -> None:
    """`datetime.now` answers `NOW` everywhere a job surface reads it.

    Both modules: the router stamps `viewed_at` and a feedback row, and the
    serializer computes `days_open`, a separate module with its own clock
    read. Pinning only the router leaves `days_open` measured against the
    real day.
    """
    import tracker.api.routers.jobs as router
    import tracker.api.serializers.jobs as serializer

    monkeypatch.setattr(router, "datetime", _Clock)
    monkeypatch.setattr(serializer, "datetime", _Clock)


@dataclass(frozen=True)
class SeededBoard:
    jobs: dict[str, int]


#: Each embedded posting's cosine to `cloud`, the score its `job_similarity`
#: row states: a unit vector with that component on `cloud`'s axis and the
#: rest on an axis of its own.
SCORES = {"closed": 0.8123, "maps": 0.74012, "gpt": 0.8812, "vault": 0.8655, "claude": 0.61234}


def _vector(key: str) -> list[float]:
    vec = [0.0] * get_settings().embedding_dim
    if key == "cloud":
        vec[0] = 1.0
        return vec
    score = SCORES[key]
    vec[0] = score
    vec[1 + list(SCORES).index(key)] = (1 - score * score) ** 0.5
    return vec


def _role(key: str, company: str, **over) -> Job:
    return make_job(key, company=company, dedupe_key=f"{company}:{key}", url=f"https://careers.example.test/{company}/{key}",
                first_seen=NOW - timedelta(days=10), last_seen=NOW, **over)


BAY = {"location_groups": ["silicon_valley", "united_states"]}


async def seed_board(session: AsyncSession) -> SeededBoard:
    assert all(slug in LOCATION_GROUPS for slug in [*TRACKED_LOCATIONS, "london"])
    session.add_all([
        make_company("google", "Google"),
        make_company("openai", "OpenAI"),
        make_company("anthropic", "Anthropic"),
        make_company("paused-co", "Paused Co", enabled=False),
        make_company("hidden-co", "Hidden Co", source="url"),
        AppSetting(key=ENABLED_LOCATIONS_KEY, value={"slugs": TRACKED_LOCATIONS}),
    ])
    jobs = {
        "cloud": _role("cloud", "google", workplace_type="hybrid", **BAY),
        "closed": _role("closed", "google", status="closed", closed_at=NOW - timedelta(days=1), **BAY),
        "maps": _role("maps", "google", locations=["New York, NY, USA"], location_groups=["new_york", "united_states"],
                      domains=["logistics_fulfillment"], level_band="senior", level_confidence="unconfirmed",
                      family="engineering_management", track="management"),
        "lonely": _role("lonely", "google", domains=None, **BAY),
        "gpt": _role("gpt", "openai", domains=[], family=None, track="technical", workplace_type="remote", **BAY),
        "vault": _role("vault", "hidden-co", domains=["security_privacy"], family="program_management", **BAY),
        "claude": _role("claude", "anthropic", locations=["London, UK"], location_groups=["london"],
                        level_band="principal"),
        "out": _role("out", "openai", in_scope=False, **BAY),
    }
    for key in ("cloud", *SCORES):
        jobs[key].embedding = _vector(key)
    session.add_all(jobs.values())
    await session.flush()
    j = {key: row.id for key, row in jobs.items()}

    def neighbour(scope: str, other: str, rank: int, score: float) -> JobSimilarity:
        return JobSimilarity(job_id=j["cloud"], neighbor_job_id=j[other], scope=scope, rank=rank, score=score)

    session.add_all([
        neighbour("within", "closed", 1, 0.8123), neighbour("within", "maps", 2, 0.74012),
        neighbour("within", "lonely", 3, 0.6),
        neighbour("cross", "gpt", 1, 0.8812), neighbour("cross", "vault", 2, 0.8655),
        neighbour("cross", "claude", 3, 0.61234),
        Favorite(job_id=j["maps"], created_at=NOW - timedelta(days=2)),
        JobFeedback(job_id=j["gpt"], verdict="dismissed", reason="wrong_domain", created_at=NOW - timedelta(days=1)),
    ])
    await session.commit()
    return SeededBoard(jobs=j)
