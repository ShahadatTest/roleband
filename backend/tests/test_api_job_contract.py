"""The job browse routes' response contract: models, vocabularies and the wire.

`tracker/api/schemas/jobs.py` declares what the job routes send. These tests hold
that declaration to three sources of truth, because a model that agrees only
with itself proves nothing:

1. **The vocabularies** each Literal mirrors — module constants and database
   CHECK constraints — read from their source, so a new constant fails by name.
2. **The builders**: `build_job_package` and the offer-policy description,
   driven through every branch without a database.
3. **The routes over real HTTP** against seeded Postgres rows, one per
   serializer branch (`tests/job_contract_seed.py`), including the proof that a
   key a serializer adds or drops without the model fails loudly rather than
   vanishing from, or silently defaulting in, the response.
"""

from __future__ import annotations

import re
from typing import get_args

import pytest
import pytest_asyncio
from fastapi.exceptions import ResponseValidationError
from sqlalchemy import CheckConstraint

from tests.api_errors import said
from tests.factories import T0
from tests.job_contract_seed import SECTION, SeededJobs, seed_job_contract
from tracker.analytics import comp_package as cp
from tracker.analytics import posting_reality
from tracker.api.routers import jobs as jobs_router
from tracker.api.schemas import jobs as contract
from tracker.config import get_settings
from tracker.db.models import Job, JobRelevanceReview, Pursuit
from tracker.db.queries import listing_history
from tracker.levels import model as pay_vocabulary
from tracker.levels import pay as op
from tracker.search import policy as search_policy

# --------------------------------------------------------------------------- #
# 1. Vocabularies
# --------------------------------------------------------------------------- #


def _constants(module, prefix: str, *, excluding: tuple[str, ...] = ()) -> set[str]:
    return {
        value
        for name, value in vars(module).items()
        if name.startswith(prefix) and isinstance(value, str) and name not in excluding
    }


def _check_values(model, column: str) -> set[str]:
    """The values a table's `<column> IN (...)` CHECK constraint allows."""
    (check,) = [
        c
        for c in model.__table__.constraints
        if isinstance(c, CheckConstraint) and re.match(rf"\s*{column}\s+IN\b", str(c.sqltext))
    ]
    return set(re.findall(r"'([a-z_]+)'", str(check.sqltext)))


@pytest.mark.parametrize(
    ("literal", "source"),
    [
        (contract.CompProvenance, lambda: _constants(cp, "PROV_")),
        (contract.CompSplitSource, lambda: _constants(cp, "SPLIT_")),
        (contract.CompEquityBasis, lambda: _constants(cp, "EQUITY_")),
        (contract.CompNoSplitReason, lambda: _constants(cp, "NO_SPLIT_")),
        (contract.CompReconciliationVerdict, lambda: _constants(cp, "VERDICT_")),
        (contract.CompMarketVerdict, lambda: _constants(cp, "MARKET_")),
        # `describe` turns the unverified sentinels into null, so they never reach the wire.
        (contract.OfferBonusRule, lambda: _constants(pay_vocabulary, "BONUS_", excluding=("BONUS_UNVERIFIED",))),
        (contract.OfferEquityRule, lambda: _constants(pay_vocabulary, "EQUITY_", excluding=("EQUITY_UNVERIFIED",))),
        (contract.PursuitStage, lambda: _check_values(Pursuit, "stage")),
        (contract.ReviewRelevance, lambda: _check_values(JobRelevanceReview, "relevance")),
        (contract.QueryKind, lambda: set(get_args(search_policy.QueryKind))),
        (contract.MatchClass, lambda: {m.value for m in search_policy.MatchClass}),
        (contract.ListingBasis, lambda: set(get_args(posting_reality.Basis))),
        (contract.ListingEventKind, lambda: set(listing_history._KIND_ORDER)),
    ],
    ids=lambda value: getattr(value, "__name__", None) or "",
)
def test_each_vocabulary_matches_the_source_it_mirrors(literal, source):
    assert set(get_args(literal)) == source()


def test_the_vocabulary_reader_sees_a_constant_it_was_not_told_about():
    """The control: `_constants` must find names by prefix, not by a list."""

    class Module:
        PROV_STATED = "stated"
        PROV_ESTIMATED = "estimated"
        PROV_INVENTED = "invented"

    assert _constants(Module, "PROV_") == {"stated", "estimated", "invented"}


# --------------------------------------------------------------------------- #
# 2. Builders
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("company", [*sorted(op.PAY_POLICIES), "a-company-with-no-policy"])
def test_every_offer_policy_fits_the_contract(company):
    contract.OfferPolicy.model_validate(op.describe(company))


_BAND = {"disclosed": True, "currency": "USD", "pay_basis": "base", "pay_period": "year",
         "snippet": "$230,000-$330,000", "confidence": "high", "base_min": 230_000, "base_max": 330_000}


@pytest.mark.parametrize(
    "disclosed",
    [
        None,
        {"disclosed": False},
        _BAND | {"bonus_pct": None},
        _BAND | {"bonus_pct": 0.15},
        _BAND | {"base_min": None, "bonus_pct": None},
        _BAND | {"currency": "CAD", "bonus_pct": None},
        _BAND | {"pay_period": "hour", "base_min": 60, "base_max": 85, "bonus_pct": None},
        _BAND | {"pay_basis": "total", "bonus_pct": None},
        _BAND | {"pay_basis": "unclear", "bonus_pct": None},
    ],
    ids=["unchecked", "none_stated", "base", "base+bonus", "one_sided", "cad", "hourly", "total", "unclear"],
)
@pytest.mark.parametrize("company", ["google", "netflix", "acme"])
@pytest.mark.parametrize("band", ["staff", None])
@pytest.mark.parametrize("median", [640_000, None])
def test_every_comp_package_branch_fits_the_contract(disclosed, company, band, median):
    package = cp.build_job_package(
        company=company, band=band, family="product_management",
        comp_low=None if median is None else 520_000, comp_median=median,
        comp_high=None if median is None else 760_000,
        comp_provenance=None if median is None else "Google L6 estimated median",
        disclosed=disclosed,
    )
    validated = contract.JobCompPackage.model_validate(package)
    # Nothing was dropped or reshaped on the way through: the JSON dump is the dict.
    assert validated.model_dump(mode="json") == package


def test_a_built_shape_refuses_a_key_it_does_not_declare():
    """The rule that turns serializer drift into a failure instead of lost output."""
    with pytest.raises(ValueError, match="extra"):
        contract.FavoriteResponse.model_validate({"job_id": 1, "is_favorite": True, "surprise": 1})


def test_a_stored_shape_keeps_a_key_an_older_writer_left():
    source = {"provider": "x", "median": 1, "low": None, "high": 2, "currency": "USD",
              "source": "s", "legacy_field": "kept"}
    assert contract.CompSource.model_validate(source).model_dump(mode="json") == source


def test_an_integral_amount_is_not_reemitted_as_a_float():
    dumped = contract.CompSource.model_validate(
        {"provider": "x", "median": 735_000, "low": 1.5, "high": None, "currency": "USD", "source": "s"}
    ).model_dump_json()
    assert '"median":735000,' in dumped and '"low":1.5,' in dumped


# --------------------------------------------------------------------------- #
# 3. The routes over HTTP
# --------------------------------------------------------------------------- #

# Every list row also carries the standing-posting verdict; the
# ranked paths' keys are the only extras.
_ROW_KEYS = set(contract.JobRow.model_fields) | {"posting_reality"}
_RANK_KEYS = {"relevance", "why_world", "matched_via", "match_class"}
_ENVELOPE = {"total", "limit", "offset", "items"}
_SEARCH_ENVELOPE = _ENVELOPE | {
    "matched", "ranking_truncated", "related_items", "related_total", "query_kind", "parsed"
}


@pytest_asyncio.fixture
async def seeded(db_session, monkeypatch) -> SeededJobs:
    async def no_query_vector(_text):
        return None  # no model weights in tests: the lexical half ranks alone

    monkeypatch.setattr(jobs_router, "embed_query", no_query_vector)
    return await seed_job_contract(db_session)


def _row_extras(body: dict) -> set[str]:
    rows = body["items"] + body.get("related_items", [])
    for row in rows:
        assert _ROW_KEYS <= set(row), f"row {row.get('id')} lost {_ROW_KEYS - set(row)}"
    return set().union(*(set(row) - _ROW_KEYS for row in rows)) if rows else set()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("query", "envelope", "extras"),
    [
        ("", _ENVELOPE, set()),
        ("?limit=2&offset=1", _ENVELOPE, set()),
        ("?favorites_only=true", _ENVELOPE, set()),
        ("?dismissed_only=true", _ENVELOPE, set()),
        ("?status=closed", _ENVELOPE, set()),
        ("?sort=relevance&q=product%20manager", _SEARCH_ENVELOPE, {"relevance", "matched_via", "match_class"}),
        ("?sort=relevance&q=Platform%20Strategy%20Lead%2C%20Cloud&include_related=true",
         _SEARCH_ENVELOPE, {"relevance", "matched_via", "match_class"}),
        ("?sort=relevance&q=https%3A%2F%2Fcareers.example.test%2Fband",
         _SEARCH_ENVELOPE, {"relevance", "matched_via", "match_class"}),
    ],
    ids=["default", "paged", "saved", "not_for_me", "closed", "exploratory", "exact_title", "identifier"],
)
async def test_each_list_shape_sends_exactly_its_own_keys(api_client, seeded, query, envelope, extras):
    """`exclude_unset` is what keeps search-only keys off a plain list. Without
    it every default row would gain `relevance: null`, and this fails."""
    response = await api_client.get(f"/api/jobs{query}")

    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == envelope
    assert _row_extras(body) == (extras if body["items"] else set())


@pytest.mark.asyncio
async def test_an_intent_ranked_list_adds_ranked_by_and_the_why(api_client, seeded, monkeypatch):
    async def no_statement(_session):
        return None

    async def intent_vector(_session, _stored):
        return [0.01] * get_settings().embedding_dim

    monkeypatch.setattr(jobs_router, "get_intent_embedding", no_statement)
    monkeypatch.setattr(jobs_router, "build_intent_vector", intent_vector)

    body = (await api_client.get("/api/jobs?sort=relevance")).json()

    # Best fit also says where the roles whose level we cannot place begin
    #: an index of the whole list, at most its total.
    assert set(body) == _ENVELOPE | {"ranked_by", "placed_total"} and body["ranked_by"] == "intent"
    assert 0 <= body["placed_total"] <= body["total"]
    assert _row_extras(body) == {"relevance", "why_world"}
    # No seeded row has an embedding, so every row is unranked — null, never absent.
    assert all(row["relevance"] is None for row in body["items"])


@pytest.mark.asyncio
async def test_search_sections_carry_their_meaning(api_client, seeded):
    exact = (await api_client.get(
        "/api/jobs?sort=relevance&q=Platform%20Strategy%20Lead%2C%20Cloud&include_related=true"
    )).json()
    assert exact["query_kind"] == "exact_title"
    assert [row["id"] for row in exact["items"]] == [seeded.none_stated]
    assert exact["items"][0]["match_class"] == "exact" and exact["items"][0]["matched_via"][0] == "exact"
    assert [row["id"] for row in exact["related_items"]] == [seeded.hourly]
    assert exact["related_total"] == 1

    identifier = (await api_client.get(
        "/api/jobs?sort=relevance&q=https%3A%2F%2Fcareers.example.test%2Fband"
    )).json()
    assert identifier["query_kind"] == "identifier"
    assert [row["id"] for row in identifier["items"]] == [seeded.band]
    assert identifier["related_items"] == [] and identifier["items"][0]["relevance"] is None
    assert set(identifier["parsed"]) == set(contract.ParsedQueryEcho.model_fields)


@pytest.mark.asyncio
async def test_every_detail_branch_sends_every_detail_key(api_client, seeded):
    for name, job_id in seeded.items():
        response = await api_client.get(f"/api/jobs/{job_id}")
        assert response.status_code == 200, (name, response.text)
        assert set(response.json()) == set(contract.JobDetailResponse.model_fields), name


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "places,currency",
    [(["london"], "GBP"), (["new_york", "canada"], "USD")],
    ids=["london", "new_york_or_canada"],
)
async def test_a_stated_base_outside_us_pay_is_left_whole_and_says_why(api_client, db_session, seeded, places, currency):
    # No plugin answers pay. Our split is measured on US pay, so a band for a
    # posting in another country, or in several, stays whole, and the reason
    # names our data, never a plugin. The offer policy is the company's and stays.
    job = await db_session.get(Job, seeded.band)
    job.location_groups, job.disclosed_currency = places, currency
    await db_session.commit()

    package = (await api_client.get(f"/api/jobs/{seeded.band}")).json()["comp_package"]
    assert package["state"] == "band" and package["stated"] == {"low": 230_000, "high": 330_000}
    assert package["no_split_reason"] == "not_us_pay"
    assert package["components"] == [] and package["total"] is None and package["split_source"] is None
    assert package["policy"]["verified"] is True


@pytest.mark.asyncio
async def test_detail_branches_mean_what_they_say(api_client, seeded):
    async def detail(job_id):
        return (await api_client.get(f"/api/jobs/{job_id}")).json()

    band = await detail(seeded.band)
    package = band["comp_package"]
    assert package["state"] == "band" and package["stated"] == {"low": 230_000, "high": 330_000}
    assert [c["kind"] for c in package["components"]] == ["base", "bonus", "equity"]
    assert package["components"][0]["provenance"] == "stated"
    assert package["total"]["low"] == sum(c["low"] for c in package["components"])
    assert package["policy"]["verified"] is True
    assert band["disclosed_comp"]["checked_at"] == "2026-07-01T12:00:00Z"
    assert band["is_favorite"] is True and band["pursuit"]["stage"] == "applied"
    assert band["relevance_review"]["relevance"] == "relevant"
    assert band["comp_sources"][0]["median"] == 640_000
    assert [e["event_type"] for e in band["lifecycle"]] == ["opened", "changed"]
    (skill,) = band["requirements"]["skills"]
    (evidence,) = skill["evidence"]
    assert SECTION[evidence["start_offset"]:evidence["end_offset"]] == evidence["quote"]
    assert band["lineage_size"] == 2

    repost = await detail(seeded.repost)
    assert repost["lineage_days_open"] == repost["days_open"] + 30

    plain = await detail(seeded.plain)
    assert plain["disclosed_comp"] is None and plain["comp_package"]["state"] == "unchecked"
    assert plain["comp_package"]["policy"]["verified"] is False
    assert plain["domains"] == [] and plain["requirements"]["state"] == "unavailable"

    hourly = await detail(seeded.hourly)
    assert hourly["comp_package"]["no_split_reason"] == "hourly"
    assert hourly["comp_package"]["components"] == []

    total = await detail(seeded.total)
    assert total["comp_package"]["no_split_reason"] == "employee_election"
    assert total["comp_package"]["total"] == {"low": 500_000, "high": 900_000, "provenance": "stated"}

    estimated = await detail(seeded.none_stated)
    assert estimated["disclosed_comp"]["disclosed"] is False
    assert estimated["comp_package"]["state"] == "none_stated"
    assert {c["provenance"] for c in estimated["comp_package"]["components"]} == {"estimated"}

    dismissed = await detail(seeded.dismissed)
    assert dismissed["is_dismissed"] is True and dismissed["feedback_reason"] == "wrong_level"


@pytest.mark.asyncio
async def test_writes_answer_with_their_contract(api_client, seeded):
    viewed = await api_client.post(f"/api/jobs/{seeded.band}/view")
    assert viewed.json() == {"job_id": seeded.band, "viewed_at": T0.isoformat().replace("+00:00", "Z")}

    assert (await api_client.put(f"/api/jobs/{seeded.plain}/favorite")).json() == {
        "job_id": seeded.plain, "is_favorite": True,
    }
    assert (await api_client.delete(f"/api/jobs/{seeded.plain}/favorite")).json() == {
        "job_id": seeded.plain, "is_favorite": False,
    }
    dismissed = await api_client.put(
        f"/api/jobs/{seeded.plain}/feedback", json={"verdict": "dismissed", "reason": "wrong_role"}
    )
    assert dismissed.json() == {
        "job_id": seeded.plain, "is_dismissed": True, "reason": "wrong_role",
        "company": "acme", "department": None, "team": None,
    }
    assert (await api_client.delete(f"/api/jobs/{seeded.plain}/feedback")).json() == {
        "job_id": seeded.plain, "is_dismissed": False,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method", "path", "body", "status", "detail"),
    [
        ("GET", "/api/jobs/999999", None, 404, "job not found"),
        ("POST", "/api/jobs/999999/view", None, 404, "job not found"),
        ("PUT", "/api/jobs/999999/favorite", None, 404, "job not found"),
        ("PUT", "/api/jobs/999999/feedback", {"verdict": "dismissed"}, 404, "job not found"),
        ("PUT", "/api/jobs/1/feedback", {"verdict": "dismissed", "reason": "nope"}, 422, "unknown reason: 'nope'"),
    ],
)
async def test_errors_keep_their_status_and_detail(api_client, seeded, method, path, body, status, detail):
    response = await api_client.request(method, path, json=body)
    assert response.status_code == status
    assert said(response.json()) == {"detail": detail}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "drift",
    [
        lambda row: {**row, "surprise": 1},
        lambda row: {k: v for k, v in row.items() if k != "twin_count"},
    ],
    ids=["serializer_adds_a_key", "serializer_drops_a_key"],
)
async def test_serializer_drift_fails_the_response_instead_of_reshaping_it(
    api_client, seeded, monkeypatch, drift
):
    """Both directions a serializer and its model can part: an added key would
    otherwise be filtered out unseen, a dropped one would otherwise be missing
    from the wire. Either way the route must fail, loudly and here."""
    real = jobs_router.serialize_job
    monkeypatch.setattr(jobs_router, "serialize_job", lambda *a, **kw: drift(real(*a, **kw)))

    with pytest.raises(ResponseValidationError):
        await api_client.get("/api/jobs")
