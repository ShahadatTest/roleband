"""A company-store refusal answers with one code, whichever route meets it.

`company_store` and `db.reconciliation` raise a `CompanyError` whose class says
what kind of refusal it is; `tracker.api.company_errors` gives each class its
status and code. The dashboard says the code (`error-<code>`), so a route that
picked its own would tell the person the wrong thing: a walled company switched
on without its consent would read "That company is already in RoleBand."

1. **The table**: every refusal class the store defines has its answer, pinned
   here as the dashboard reads it.
2. **Every route, every refusal**: each route that calls the store is made to
   meet each refusal class and must answer with that class's row.
3. **Real refusals, no stand-ins**: the same refusal reached through the real
   store on different routes answers alike.
"""

from __future__ import annotations

import inspect
from types import ModuleType

import httpx
import pytest

from tests.api_errors import said
from tracker import company_store
from tracker.api.company_errors import COMPANY_REFUSALS, company_error
from tracker.api.routers import companies as companies_router
from tracker.api.routers import recipes as recipes_router
from tracker.company_store import (
    CompanyConflict,
    CompanyError,
    CompanyNotFound,
    ConsentRequired,
    RecipeConflict,
    RecipeNotFound,
)
from tracker.db import reconciliation
from tracker.db.models import TrackedCompany

# Every route here may start a scan or reach a careers page once its guard
# passes, so none of them may.
pytestmark = pytest.mark.usefixtures("no_escape")

#: What each refusal means to the person reading it.
ANSWERS: dict[type[CompanyError], tuple[int, str]] = {
    CompanyError: (400, "company-refused"),
    CompanyNotFound: (404, "company-not-found"),
    CompanyConflict: (409, "company-conflict"),
    ConsentRequired: (409, "consent-required"),
    RecipeNotFound: (404, "recipe-not-found"),
    RecipeConflict: (409, "recipe-conflict"),
}

PROBE = "probe-co"
#: A catalog company no install tracks until it is followed.
CATALOG_ONLY = "stripe"


def _answer(response: httpx.Response) -> tuple[int, str]:
    body = response.json()
    said(body)
    return response.status_code, body["detail"]["code"]


# --------------------------------------------------------------------------- #
# 1. The table
# --------------------------------------------------------------------------- #


def test_every_refusal_the_store_defines_has_its_answer():
    defined = {
        value for value in vars(company_store).values()
        if isinstance(value, type) and issubclass(value, CompanyError)
    }
    assert defined == set(ANSWERS), "a new refusal class needs its answer decided here"
    assert {cls: (status, code.value) for cls, (status, code) in COMPANY_REFUSALS.items()} == ANSWERS


def test_a_refusal_with_no_row_of_its_own_answers_as_its_nearest_parent():
    class Unlisted(RecipeConflict):
        pass

    error = company_error(Unlisted("probe"))
    assert (error.status_code, error.detail["code"]) == (409, "recipe-conflict")


# --------------------------------------------------------------------------- #
# 2. Every route, every refusal
# --------------------------------------------------------------------------- #

_REBIND = f"/api/companies/{PROBE}/recipe-rebind"

#: (method, path, body, module the route looks the store call up in, its name)
ROUTES: dict[str, tuple[str, str, dict | None, ModuleType, str]] = {
    "follow_a_new_company": (
        "PUT", "/api/companies/selection", {"follow": [CATALOG_ONLY]}, companies_router, "resolve_company"),
    "follow_a_tracked_company": (
        "PUT", "/api/companies/selection", {"follow": [PROBE]}, companies_router, "require_consent_to_follow"),
    "add": ("POST", "/api/companies", {"catalog_slug": CATALOG_ONLY}, companies_router, "resolve_company"),
    "switch": ("PATCH", f"/api/companies/{PROBE}", {"enabled": True}, companies_router, "set_enabled"),
    "move_board": (
        "PUT", f"/api/companies/{PROBE}/board", {"adapter": "greenhouse", "board_token": "probe"},
        companies_router, "record_board_move"),
    "bind_recipe": ("POST", f"/api/companies/{PROBE}/recipe", {"recipe": "probe-recipe"}, recipes_router, "bind_recipe"),
    "propose_rebind": ("POST", _REBIND, {"recipe": "probe-recipe"}, reconciliation, "recipe_revision"),
    "read_rebind": ("GET", f"{_REBIND}/1", None, reconciliation, "detail"),
    "review_rebind": (
        "POST", f"{_REBIND}/1/decisions", {"decision": "new", "source_key": "k", "reason": "A separate posting"},
        reconciliation, "review"),
    "activate_rebind": ("POST", f"{_REBIND}/1/activate", None, reconciliation, "activate"),
    "roll_back_rebind": ("POST", f"{_REBIND}/1/rollback", {"reason": "Restore the adapter"}, reconciliation, "rollback"),
}


def _refusing(original, refusal: CompanyError):
    if inspect.iscoroutinefunction(original):
        async def refuse_async(*_args, **_kwargs):
            raise refusal
        return refuse_async

    def refuse(*_args, **_kwargs):
        raise refusal
    return refuse


@pytest.fixture
def board_answers(monkeypatch):
    """The move route re-checks the board live: here it answers, and nothing leaves."""
    async def answers(_board, _client) -> bool:
        return True

    monkeypatch.setattr(companies_router, "board_answers", answers)
    monkeypatch.setattr(
        companies_router, "public_client",
        lambda **_: httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(404))),
    )


async def _seed_probe(db_session, **over) -> None:
    fields = {
        "slug": PROBE, "display": "Probe Co", "adapter": "greenhouse", "board_token": "probe",
        "status": "active", "enabled": False, "visible": True, "source": "catalog",
    }
    db_session.add(TrackedCompany(**{**fields, **over}))
    await db_session.commit()


@pytest.mark.asyncio
@pytest.mark.parametrize("refusal", list(ANSWERS), ids=lambda cls: cls.__name__)
@pytest.mark.parametrize("route", list(ROUTES))
async def test_each_route_answers_a_refusal_with_its_one_code(
    api_client, db_session, monkeypatch, board_answers, route, refusal
):
    method, path, body, module, name = ROUTES[route]
    await _seed_probe(db_session)
    monkeypatch.setattr(module, name, _refusing(getattr(module, name), refusal(f"{name} refused")))

    response = await api_client.request(method, path, json=body)

    assert _answer(response) == ANSWERS[refusal], response.text


# --------------------------------------------------------------------------- #
# 3. Real refusals, no stand-ins
# --------------------------------------------------------------------------- #

WALLED = "google"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("PATCH", f"/api/companies/{WALLED}", {"enabled": True}),
        ("PUT", "/api/companies/selection", {"follow": [WALLED]}),
    ],
    ids=["switch", "selection"],
)
async def test_a_walled_company_without_consent_is_refused_alike_on_both_follow_routes(
    api_client, db_session, method, path, body
):
    """An install that followed a walled company before consent existed and then
    unfollowed it: following it again from either control asks for the dialog."""
    db_session.add(TrackedCompany(
        slug=WALLED, display="Google", adapter="google", board_token=None, status="active",
        enabled=False, visible=True, source="builtin", consent_fingerprint=None,
    ))
    await db_session.commit()

    response = await api_client.request(method, path, json=body)

    assert _answer(response) == (409, "consent-required"), response.text
    row = await db_session.get(TrackedCompany, WALLED)
    await db_session.refresh(row)
    assert row.enabled is False and row.consented_at is None, "a refusal applies nothing"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("PATCH", "/api/companies/nobody", {"visible": False}),
        ("PUT", "/api/companies/nobody/board", {"adapter": "greenhouse", "board_token": "nobody"}),
        ("POST", "/api/companies/nobody/recipe", {"recipe": "probe-recipe"}),
        ("POST", "/api/companies/nobody/recipe-rebind/1/activate", None),
    ],
    ids=["switch", "move_board", "bind_recipe", "activate_rebind"],
)
async def test_an_untracked_company_is_not_found_on_every_route(api_client, board_answers, method, path, body):
    response = await api_client.request(method, path, json=body)
    assert _answer(response) == (404, "company-not-found"), response.text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path", [f"/api/companies/{PROBE}/recipe", f"/api/companies/{PROBE}/recipe-rebind"],
    ids=["bind_recipe", "propose_rebind"],
)
async def test_a_recipe_that_does_not_exist_is_not_found_on_both_recipe_routes(api_client, db_session, path):
    await _seed_probe(db_session, enabled=True)
    response = await api_client.post(path, json={"recipe": "no-such-recipe"})
    assert _answer(response) == (404, "recipe-not-found"), response.text
