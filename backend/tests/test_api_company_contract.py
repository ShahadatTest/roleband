"""The tracked-company routes' response contract.

`tracker/api/schemas/companies.py` declares what these routes send. These tests
hold it to its sources:

1. **The vocabulary**: a discovery company's `connector_state` against the labels
   the discovery catalog defines.
2. **The routes over real HTTP** against seeded Postgres rows
   (`tests/company_contract_seed.py`): each shape's exact keys, what the values
   mean, the selection's draft applied and answered with the re-read roster,
   rejected input leaving the roster exactly as it was, and removal keeping a
   company's history.
3. **Drift in both directions**: a key a serializer adds or drops without its
   model fails the response instead of vanishing from, or defaulting in, it.

No test may start a scan: `no_escape` refuses a real spawn, and the route's
spawn is replaced by a recorder so each test can say which companies were sent.
"""

from __future__ import annotations

from typing import get_args

import httpx
import pytest
import pytest_asyncio
from fastapi.exceptions import ResponseValidationError
from sqlalchemy import func, select

from tests.api_errors import said
from tests.company_contract_seed import seed_company_contract
from tracker import board_resolve, company_discovery
from tracker.api.routers import companies as companies_router
from tracker.api.schemas import companies as contract
from tracker.company_discovery import COMPANY_DISCOVERY
from tracker.db.models import (
    Job,
    TrackedCompany,
)

# Every test here reaches code that starts or signals a process on this
# machine, so none of them may.
pytestmark = pytest.mark.usefixtures("no_escape")

# --------------------------------------------------------------------------- #
# 1. Vocabulary
# --------------------------------------------------------------------------- #


def test_connector_state_is_the_set_the_discovery_catalog_labels():
    assert set(get_args(contract.ConnectorState)) == set(company_discovery.CONNECTOR_STATES)
    # Every parked company's reason is one the dashboard can say.
    assert set(company_discovery._PARKED.values()) <= set(get_args(contract.ParkedReason))
    assert set(company_discovery._PARKED_WHY) == set(get_args(contract.ParkedReason))


# --------------------------------------------------------------------------- #
# 2. The routes over HTTP
# --------------------------------------------------------------------------- #


class Spawned(list):
    """Role-discovery spawns, plus `dispatched`: how often a follow started the
    sync dispatcher for first scans."""

    dispatched = 0


@pytest_asyncio.fixture
async def spawned(db_session, monkeypatch, no_escape) -> Spawned:
    calls = Spawned()

    async def record(_session, slugs, *, max_list, requested_by):
        calls.append([*slugs, f"max_list={max_list}"])
        return True

    monkeypatch.setattr(companies_router.job_requests, "ring_role_discovery", record)
    real_ring = companies_router.scan_requests.ring

    async def ring(session, *, requested_by):
        calls.dispatched += 1
        await real_ring(session, requested_by=requested_by)

    monkeypatch.setattr(companies_router.scan_requests, "ring", ring)
    await seed_company_contract(db_session)
    return calls


def _fields(model) -> set[str]:
    return set(model.model_fields)


async def _roster(api_client) -> dict[str, dict]:
    return {row["slug"]: row for row in (await api_client.get("/api/companies")).json()["companies"]}


@pytest.mark.asyncio
async def test_the_roster_sends_every_key_and_counts_only_open_in_scope_roles(api_client, spawned):
    body = (await api_client.get("/api/companies")).json()
    assert set(body) == {"companies"}
    assert all(set(row) == _fields(contract.TrackedCompanyRow) for row in body["companies"])

    rows = {row["slug"]: row for row in body["companies"]}
    assert {slug: row["job_count"] for slug, row in rows.items()} == {
        "google": 2, "stripe": 1, "mckinsey-company": 0, "acme-labs": 0, "hidden-co": 1,
    }
    assert rows["google"]["builtin"] is True and rows["stripe"]["builtin"] is False
    assert rows["stripe"]["role_catalog_scanned_at"] == "2026-07-01T12:00:00Z"
    assert rows["mckinsey-company"]["role_catalog_scanned_at"] is None
    assert rows["acme-labs"]["role_catalog_error"] == "HTTPError: 503 on page 2"

    counts = (await api_client.get("/api/companies/open-counts")).json()
    assert counts["counts"] == {"google": 2, "stripe": 1, "hidden-co": 1}, "a company with none is absent"
    assert set(counts) == _fields(contract.CompanyOpenCountsResponse)


@pytest.mark.asyncio
async def test_names_answer_every_tracked_and_catalog_company_as_it_names_itself(
    api_client, spawned, db_session,
):
    """Without this the dashboard prints `pwc`, `fortinet`, `palo-alto-networks`:
    its own name table knows only a few companies. This is the rest, read once before
    it renders. A name is not a posting, so hidden, unfollowed, pending and
    URL-added companies are all named, and so is every catalog company, followed
    or not: the level table names them on a fresh install. A stored name wins;
    the directory's thousands are not in it."""
    stripe = await db_session.get(TrackedCompany, "stripe")
    stripe.display = "Stripe, Inc."
    await db_session.commit()

    body = (await api_client.get("/api/companies/names")).json()
    assert set(body) == _fields(contract.CompanyNamesResponse)
    names = body["names"]
    assert {slug: names[slug] for slug in ("google", "stripe", "mckinsey-company", "acme-labs", "hidden-co")} == {
        "google": "Google",
        "stripe": "Stripe, Inc.",
        "mckinsey-company": "McKinsey & Company",
        "acme-labs": "Acme Labs",
        "hidden-co": "Hidden Co",
    }
    assert await db_session.get(TrackedCompany, "coinbase") is None
    assert names["coinbase"] == "Coinbase"
    assert names["1password"] == "1Password"
    assert set(names) == set(COMPANY_DISCOVERY) | {"acme-labs", "hidden-co"}


@pytest.mark.asyncio
async def test_discovery_merges_the_catalog_with_the_roster(api_client, spawned):
    body = (await api_client.get("/api/companies/discovery")).json()
    assert set(body) == _fields(contract.CompanyDiscoveryResponse)
    assert all(set(sector) == _fields(contract.DiscoverySector) for sector in body["sectors"])
    assert all(set(company) == _fields(contract.DiscoveryCompany) for company in body["companies"])

    companies = {company["slug"]: company for company in body["companies"]}
    assert companies["google"]["connector_state"] == "live" and companies["google"]["builtin"] is True
    assert companies["stripe"]["connector_state"] == "ready"
    # `mckinsey-company` runs a bespoke careers site on no ATS we could add, so
    # it stays `planned`.
    planned = companies["mckinsey-company"]
    assert (planned["connector_state"], planned["status"]) == ("planned", "pending")
    deepmind = companies["google-deepmind"]
    assert {key: deepmind[key] for key in ("connector_state", "tracked", "enabled", "visible", "status")} == {
        "connector_state": "family", "tracked": False, "enabled": False, "visible": True, "status": None,
    }
    tesla = companies["tesla"]
    assert (tesla["connector_state"], tesla["selectable"]) == ("parked", False)
    assert tesla["parked_reason"] == "bot_protected"
    # A URL-added company outside the catalog keeps its place, with no sector.
    assert (companies["acme-labs"]["sectors"], companies["acme-labs"]["connector_state"]) == ([], "active")
    assert companies["hidden-co"]["visible"] is False

    for sector in body["sectors"]:
        members = [c for c in body["companies"] if sector["slug"] in c["sectors"]]
        assert sector["company_count"] == len(members), sector["slug"]
        assert sector["ready_count"] == sum(
            c["connector_state"] in {"live", "ready", "family", "active"} for c in members
        )
        assert sector["selected_count"] == sum(c["enabled"] for c in members)


@pytest.mark.asyncio
async def test_a_selection_applies_the_draft_and_answers_with_the_reread_roster(
    api_client, db_session, spawned
):
    followed_before = {slug for slug, row in (await _roster(api_client)).items() if row["enabled"]}
    applied = await api_client.put(
        "/api/companies/selection", json={"follow": ["google", "stripe", "mckinsey-company", "google-deepmind"]}
    )
    assert applied.status_code == 200, applied.text
    body = applied.json()
    assert body == (await api_client.get("/api/companies/discovery")).json()
    enabled = {c["slug"] for c in body["companies"] if c["enabled"]}
    assert {"google", "stripe", "mckinsey-company", "google-deepmind"} <= enabled
    assert followed_before <= enabled and "hidden-co" not in enabled, "a company not named keeps its state"
    assert spawned == [["google-deepmind", "max_list=150"]], "only a newly added, scannable company is scanned"
    assert spawned.dispatched == 1, "following companies starts their first scans once, now"

    rows_before = await db_session.scalar(select(func.count()).select_from(Job))
    followed = [c["slug"] for c in body["companies"] if c["enabled"]]
    emptied = (await api_client.put("/api/companies/selection", json={"unfollow": followed})).json()
    assert not any(company["enabled"] for company in emptied["companies"])
    assert spawned.dispatched == 1, "unfollowing starts nothing"
    roster = await _roster(api_client)
    assert {"acme-labs", "hidden-co", "mckinsey-company", "google-deepmind"} <= set(roster), "paused, never deleted"
    assert await db_session.scalar(select(func.count()).select_from(Job)) == rows_before


@pytest.mark.asyncio
async def test_a_change_leaves_every_company_it_does_not_name_as_it_is(api_client, db_session, spawned):
    """The roster changes under the screen: the wider-market scan follows
    companies by itself. A company followed after the screen loaded stays
    followed when the person switches another one."""
    loaded = await _roster(api_client)
    assert loaded["hidden-co"]["enabled"] is False and loaded["stripe"]["enabled"] is True
    (await db_session.get(TrackedCompany, "hidden-co")).enabled = True  # followed meanwhile
    await db_session.commit()

    body = (await api_client.put("/api/companies/selection", json={"unfollow": ["stripe"]})).json()

    enabled = {c["slug"]: c["enabled"] for c in body["companies"]}
    assert enabled["stripe"] is False
    assert enabled["hidden-co"] is True, "followed since the screen loaded, and not named"
    assert enabled["google"] is loaded["google"]["enabled"]


@pytest.mark.asyncio
async def test_a_company_cannot_be_followed_and_unfollowed_at_once(api_client, spawned):
    before = await _roster(api_client)
    response = await api_client.put("/api/companies/selection", json={"follow": ["stripe"], "unfollow": ["stripe"]})
    assert response.status_code == 400
    assert said(response.json()) == {"detail": "followed and unfollowed at once: stripe"}
    assert await _roster(api_client) == before


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("slugs", "detail"),
    [
        (["nope"], "unknown companies: nope"),
        (["stripe", "tesla"], "'tesla' is not currently available: Careers source is currently bot-protected"),
    ],
    ids=["unknown", "parked"],
)
async def test_a_rejected_selection_leaves_the_roster_exactly_as_it_was(api_client, spawned, slugs, detail):
    """The selection seeds the built-ins before it validates, so this holds only
    because a request that raises is never committed."""
    before = await _roster(api_client)

    response = await api_client.put("/api/companies/selection", json={"follow": slugs})

    assert response.status_code == 400
    assert said(response.json()) == {"detail": detail}
    assert await _roster(api_client) == before
    assert spawned == [] and spawned.dispatched == 0


@pytest.mark.asyncio
async def test_adding_a_company_answers_201_with_its_row(api_client, spawned):
    catalog = await api_client.post("/api/companies", json={"catalog_slug": "databricks"})
    assert catalog.status_code == 201, catalog.text
    row = catalog.json()
    assert set(row) == _fields(contract.TrackedCompanyRow)
    assert (row["source"], row["status"], row["job_count"], row["role_catalog_status"]) == (
        "catalog", "active", 0, "pending",
    )

    board = (await api_client.post(
        "/api/companies", json={"name": "Globex", "careers_url": "https://job-boards.greenhouse.io/globex"}
    )).json()
    assert (board["slug"], board["source"], board["adapter"], board["board_token"]) == (
        "globex", "url", "greenhouse", "globex",
    )
    pending = (await api_client.post(
        "/api/companies", json={"name": "Initech", "careers_url": "https://careers.initech.example/jobs"}
    )).json()
    assert (pending["status"], pending["adapter"]) == ("pending", None)

    assert spawned == [["databricks", "max_list=150"], ["globex", "max_list=150"]], "a pending source is not scanned"
    # Each followed board starts its first scan now, not at the next tick; a
    # pending source has nothing to scan.
    assert spawned.dispatched == 2
    assert {"databricks", "globex", "initech"} <= set(await _roster(api_client))


@pytest.mark.asyncio
async def test_toggles_apply_independently(api_client, spawned):
    disabled = (await api_client.patch("/api/companies/stripe", json={"enabled": False})).json()
    assert set(disabled) == _fields(contract.TrackedCompanyRow)
    assert (disabled["enabled"], disabled["visible"], disabled["job_count"]) == (False, True, 1)
    hidden = (await api_client.patch("/api/companies/stripe", json={"visible": False})).json()
    assert (hidden["enabled"], hidden["visible"]) == (False, False)

    # A built-in missing from a fresh database is seeded so the toggle has a target.
    amazon = await api_client.patch("/api/companies/amazon", json={"visible": False})
    assert amazon.status_code == 200, amazon.text
    assert (amazon.json()["source"], amazon.json()["visible"]) == ("builtin", False)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method", "path", "body", "status", "detail"),
    [
        ("POST", "/api/companies", {"catalog_slug": "google"}, 409, "'google' is a built-in company and is always tracked"),
        ("POST", "/api/companies", {"catalog_slug": "stripe"}, 409, "'stripe' is already tracked"),
        ("POST", "/api/companies", {"catalog_slug": "tesla"}, 400,
         "'tesla' is not currently available: Careers source is currently bot-protected"),
        ("POST", "/api/companies", {}, 400, "provide a catalog company, or a name and careers URL"),
        ("PATCH", "/api/companies/stripe", {}, 400, "provide 'enabled' and/or 'visible'"),
        ("PATCH", "/api/companies/nobody", {"enabled": True}, 404, "'nobody' is not a tracked company"),
    ],
)
async def test_errors_keep_their_status_and_detail(api_client, spawned, method, path, body, status, detail):
    before = await _roster(api_client)
    response = await api_client.request(method, path, json=body)
    assert response.status_code == status
    assert said(response.json()) == {"detail": detail}
    assert await _roster(api_client) == before
    assert spawned == []


# --------------------------------------------------------------------------- #
# 3. Drift
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("target", "path", "drift"),
    [
        ("_company_out", "/api/companies", lambda row: {**row, "surprise": 1}),
        ("_company_out", "/api/companies", lambda row: {k: v for k, v in row.items() if k != "job_count"}),
        ("build_company_discovery", "/api/companies/discovery", lambda body: {**body, "surprise": []}),
        ("build_company_discovery", "/api/companies/discovery",
         lambda body: {k: v for k, v in body.items() if k != "sectors"}),
    ],
    ids=["row_adds_a_key", "row_drops_a_key", "discovery_adds_a_key", "discovery_drops_a_key"],
)
async def test_serializer_drift_fails_the_response_instead_of_reshaping_it(
    api_client, spawned, monkeypatch, target, path, drift
):
    real = getattr(companies_router, target)
    monkeypatch.setattr(companies_router, target, lambda *a, **kw: drift(real(*a, **kw)))

    with pytest.raises(ResponseValidationError):
        await api_client.get(path)


@pytest.mark.asyncio
async def test_the_register_row_says_the_family_and_reason_of_a_pending_company(api_client, db_session, monkeypatch):
    """A pasted careers page that names Jibe, whose board does not answer:
    the row stays pending and says so, naming the family."""
    page = httpx.Response(200, text="<html><script>jibeapply</script></html>", headers={"content-type": "text/html"})
    routes = {"https://jobs.acme.example/": page}
    transport = httpx.MockTransport(lambda request: routes.get(str(request.url), httpx.Response(404)))
    monkeypatch.setattr(board_resolve, "public_client", lambda **_kw: httpx.AsyncClient(transport=transport))

    async def no_first_scans(_session, _rows):
        return None

    monkeypatch.setattr(companies_router, "_start_first_scans", no_first_scans)
    response = await api_client.post(
        "/api/companies", json={"name": "Acme", "careers_url": "https://jobs.acme.example/"})
    assert response.status_code in (200, 201), response.text
    row = next(r for r in (await api_client.get("/api/companies")).json()["companies"] if r["slug"] == "acme")
    assert (row["status"], row["detected_family"], row["pending_reason"]) == ("pending", "jibe", "board_silent")
