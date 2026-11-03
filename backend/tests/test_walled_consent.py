"""Walled companies are collected only with the user's consent.

Robots and bot walls gate on the user's consent, not on our refusal. The contracts, each asserted as an absence of requests where a
request is what would be wrong:

* A wall is read off the register row; its fingerprint names the evidence.
* `collection_access` refuses a walled company the user never consented to on
  every execution path — adapter entry, direct fetch, recipe adapter and runner,
  pipeline collection, smoke — and the user's consent unlocks exactly that.
* Consent is asked once per company: it stands when the robots file, the wall's
  kind or the fetch tier changes, and across an unfollow and a re-follow.
* Provider-level questions (no company named) answer the operator deny only.
* Following a walled company needs a consent in the request or a stored one;
  a walled company followed before consent existed stays followed and simply
  is not scanned.

Google is the real walled source (robots disallows its paginated listing), so
these tests use it; `google-deepmind` rides the same connector family.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from unittest.mock import AsyncMock, Mock

import httpx
import pytest

from tests.factories import STAFF_EM_SCOPE as _SCOPE
from tests.factories import DetailSource as _DetailSource
from tests.factories import NoComp as _NoComp
from tests.test_recipe_adapter import RECIPE
from tracker import source_review
from tracker.company_discovery import build_company_discovery, company_wall, is_curated
from tracker.company_store import CompanyError, record_consent
from tracker.config import get_settings
from tracker.connectors import RateLimiterPool, build_adapter
from tracker.connectors.listing.recipe_adapter import RecipeAdapter
from tracker.connectors.recipes import compile_recipe, run_plan
from tracker.db.models import TrackedCompany
from tracker.platform.ratelimit import RateLimiter
from tracker.source_policy import collection_access
from tracker.source_review import SOURCE_REVIEWS, FetchTier, RobotsStatus, Wall
from tracker.workflows.collection import collect_source

# The selection PUT tests reach a route that spawns role discovery for a newly
# added company; none may start a process here.
pytestmark = pytest.mark.usefixtures("no_escape")


@pytest.fixture(autouse=True)
def dispatched(monkeypatch) -> list[str]:
    """A follow asks for a first scan: recorded here as well as stored."""
    from tracker.api.routers import companies as companies_router

    starts: list[str] = []
    real_ring = companies_router.scan_requests.ring

    async def ring(session, *, requested_by):
        starts.append("dispatcher")
        await real_ring(session, requested_by=requested_by)

    monkeypatch.setattr(companies_router.scan_requests, "ring", ring)
    return starts


GOOGLE = SOURCE_REVIEWS["google"]
CONSENT = GOOGLE.wall_fingerprint


# --------------------------------------------------------------------------- #
# The register
# --------------------------------------------------------------------------- #


def test_a_wall_is_read_off_the_register_row():
    assert GOOGLE.wall is Wall.ROBOTS
    assert CONSENT == f"robots:{GOOGLE.robots.sha256}"
    greenhouse = SOURCE_REVIEWS["greenhouse"]
    assert greenhouse.wall is None and greenhouse.wall_fingerprint is None
    bot = replace(greenhouse, refuses_identified_client=True)
    assert bot.wall is Wall.BOT_WALL
    # Robots is the source's own stated request; it names the wall first.
    both = replace(GOOGLE, refuses_identified_client=True)
    assert both.wall is Wall.ROBOTS


def test_only_the_sources_own_walls_are_walls_and_walled_is_never_curated():
    walled = sorted(key for key, row in SOURCE_REVIEWS.items() if row.wall is not None)
    # `smartrecruiters_api`: its robots allows only LinkedInBot.
    # Its board route (`smartrecruiters`) serves no robots file and is not walled.
    # `workday` is NOT here: a source left to the user asks nothing of us, so there is no consent to take — it keeps
    # its companies off the curated list and out of automatic work instead.
    # `avature_tls`: TSMC's portal refuses identified clients.
    assert walled == ["avature_tls", "google", "smartrecruiters_api"]
    assert not is_curated("tsmc"), "TSMC is on the walled TLS route"
    assert SOURCE_REVIEWS["workday"].wall is None and SOURCE_REVIEWS["workday"].user_directed
    assert not is_curated("wise"), "Wise is on the walled API route"
    assert company_wall("google-deepmind") is GOOGLE, "the family shares Google's robots verdict"
    assert not is_curated("google")
    assert not is_curated("google-deepmind")
    assert not is_curated("nvidia"), "a user-directed source is never followed by default"


# --------------------------------------------------------------------------- #
# The gate
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "provider,company,consent,denied",
    [
        ("google", "google", None, True),
        ("google", "google", CONSENT, False),
        ("google", "google-deepmind", None, True),
        ("google", "google-deepmind", CONSENT, False),
        # A consent given before the robots file changed still stands.
        ("google", "google", "robots:" + "0" * 64, False),
        # An empty record is no consent.
        ("google", "google", "", True),
        # A recipe runs SOME company's board: naming the executor `recipe`
        # cannot shed the wall its company's declared provider carries,
        # whether that company is a built-in, a catalog company or one read
        # through another company's connector family.
        ("recipe", "google", None, True),
        ("recipe", "tsmc", None, True),
        ("recipe", "wise", None, True),
        ("recipe", "google-deepmind", None, True),
        # A company on another route of its own family answers to that route.
        ("smartrecruiters", "wise", None, False),
        ("avature", "tsmc", None, False),
        # Provider-level: no company named, so only the operator deny answers.
        ("google", None, None, False),
        # Unwalled sources need nothing.
        ("greenhouse", "stripe", None, False),
    ],
)
def test_walled_needs_the_users_consent(provider, company, consent, denied):
    access = collection_access(provider, company=company, consent=consent)
    assert access.denied is denied
    assert access.walled is denied


def test_an_operator_deny_outranks_any_consent(monkeypatch):
    monkeypatch.setattr(get_settings(), "sync_policy_denied_providers", frozenset({"google"}))
    access = collection_access("google", company="google", consent=CONSENT)
    assert access.denied and not access.walled


def _move_googles_robots_file(monkeypatch) -> None:
    moved = replace(GOOGLE, robots=replace(GOOGLE.robots, sha256="f" * 64))
    monkeypatch.setitem(source_review.SOURCE_REVIEWS, "google", moved)


def test_a_consent_outlives_a_changed_robots_file(monkeypatch):
    _move_googles_robots_file(monkeypatch)
    assert not collection_access("google", company="google", consent=CONSENT).denied
    assert collection_access("google", company="google").denied, "no consent is still refused"


def test_a_consent_outlives_a_wall_that_changes_kind_and_tier(monkeypatch):
    # Robots lifted, but the host now refuses an identified client and the row
    # records a stronger tier: the user already answered for this company.
    rewalled = replace(
        GOOGLE,
        robots=replace(GOOGLE.robots, status=RobotsStatus.ALLOWED),
        refuses_identified_client=True,
        fetch_tier=FetchTier.TLS_FINGERPRINT,
    )
    monkeypatch.setitem(source_review.SOURCE_REVIEWS, "google", rewalled)
    access = collection_access("google", company="google", consent=CONSENT)
    assert not access.denied
    assert access.tier is FetchTier.TLS_FINGERPRINT


def test_a_robots_file_that_now_allows_us_needs_no_consent(monkeypatch):
    lifted = replace(GOOGLE, robots=replace(GOOGLE.robots, status=RobotsStatus.ALLOWED))
    monkeypatch.setitem(source_review.SOURCE_REVIEWS, "google", lifted)
    assert not collection_access("google", company="google").denied


# --------------------------------------------------------------------------- #
# Every execution path
# --------------------------------------------------------------------------- #


def _recording_adapter(company: str, consent: str | None):
    requests: list[httpx.Request] = []

    def respond(request):
        requests.append(request)
        return httpx.Response(500, request=request)

    adapter = build_adapter(company, "google")
    adapter._limiter = RateLimiter(0)
    adapter.collection_consent = consent
    curl = AsyncMock()
    adapter._session = curl
    return adapter, requests, respond, curl


@pytest.mark.asyncio
@pytest.mark.parametrize("company", ["google", "google-deepmind"])
@pytest.mark.parametrize("entry", ["context", "direct_fetch"])
async def test_an_unconsented_walled_adapter_sends_nothing(company, entry, monkeypatch):
    monkeypatch.setattr(get_settings(), "scraper_max_retries", 0)
    adapter, requests, respond, curl = _recording_adapter(company, None)
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        adapter._client = client
        with pytest.raises(PermissionError, match="walled"):
            if entry == "context":
                async with adapter:
                    pass
            else:
                _ = [job async for job in adapter.fetch()]
    assert requests == []
    curl.request.assert_not_awaited()


@pytest.mark.asyncio
async def test_a_consented_walled_adapter_reaches_its_source(monkeypatch):
    """Positive control: without it, a gate that refused everything would pass above."""
    monkeypatch.setattr(get_settings(), "scraper_max_retries", 0)
    monkeypatch.setattr(get_settings(), "scraper_min_delay_seconds", 0)
    adapter, requests, respond, _ = _recording_adapter("google", CONSENT)
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        adapter._client = client
        try:
            _ = [job async for job in adapter.fetch()]
        except Exception:  # noqa: BLE001 - the 500 is the point: a request was made
            pass
    assert requests, "a consented walled source must be reachable"


@pytest.mark.asyncio
@pytest.mark.parametrize("consent", [CONSENT, None])
async def test_the_consent_given_to_build_adapter_is_the_one_its_gate_reads(consent, monkeypatch):
    """A caller hands the company row's consent to `build_adapter` and assigns
    nothing afterwards: consented, the walled source is asked; not, the
    adapter refuses before any request."""
    monkeypatch.setattr(get_settings(), "scraper_max_retries", 0)
    monkeypatch.setattr(get_settings(), "scraper_min_delay_seconds", 0)
    requests: list[httpx.Request] = []

    def respond(request):
        requests.append(request)
        return httpx.Response(500, request=request)

    adapter = build_adapter("google", "google", consent=consent)
    adapter._limiter = RateLimiter(0)
    adapter._session = AsyncMock()
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        adapter._client = client
        if consent is None:
            with pytest.raises(PermissionError, match="walled"):
                _ = [job async for job in adapter.fetch()]
        else:
            try:
                _ = [job async for job in adapter.fetch()]
            except Exception:  # noqa: BLE001 - the 500 is the point: a request was made
                pass
    assert adapter.collection_consent == consent
    assert bool(requests) is (consent is not None)


def test_a_recipe_built_with_a_consent_carries_it_like_any_adapter():
    """The recipe branch of `build_adapter` forwards the consent too, so a
    caller never has to know which branch built its adapter."""
    plan = compile_recipe(RECIPE)
    assert build_adapter("acme", "recipe", recipe_plan=plan, consent=CONSENT).collection_consent == CONSENT
    assert build_adapter("acme", "recipe", recipe_plan=plan).collection_consent is None


@pytest.mark.asyncio
@pytest.mark.parametrize("company", ["google", "tsmc", "google-deepmind"])
@pytest.mark.parametrize("entry", ["adapter", "runner"])
async def test_a_recipe_cannot_collect_a_walled_company(entry, company):
    plan = compile_recipe(RECIPE)
    requests = AsyncMock()
    with pytest.raises(PermissionError, match="walled"):
        if entry == "adapter":
            adapter = RecipeAdapter(company, plan)
            async with adapter:
                _ = [job async for job in adapter.fetch()]
        else:
            await run_plan(plan, requests, company)
    requests.fetch.assert_not_awaited()


async def _collect(cfg: dict, factory):
    return await collect_source(
        "google", cfg, _SCOPE, _NoComp(), max_list=None, hydrate=False,
        limiter_pool=RateLimiterPool(), adapter_factory=factory,
    )


@pytest.mark.asyncio
async def test_the_pipeline_skips_an_unconsented_walled_company_as_unattempted():
    factory = Mock(side_effect=AssertionError("built an adapter for a walled company"))
    result = await _collect({"adapter": "google"}, factory)
    factory.assert_not_called()
    assert result.stats["unattempted"] is True
    assert "walled" in result.stats["policy_reason"]


@pytest.mark.asyncio
async def test_the_pipeline_hands_the_stored_consent_to_the_adapter():
    source = _DetailSource(count=1)
    handed: list[str | None] = []

    def factory(*_args, consent=None, **_kwargs):
        handed.append(consent)
        return source

    result = await _collect({"adapter": "google", "consent": CONSENT}, factory)
    assert handed == [CONSENT], "the adapter's own gate must see the consent too"
    assert not result.stats.get("unattempted")


@pytest.mark.asyncio
async def test_smoke_skips_an_unconsented_walled_company_and_says_how_to_consent(monkeypatch, capsys):
    from scripts import smoke_adapters

    monkeypatch.setattr(smoke_adapters, "_stored_consent", AsyncMock(return_value=None))
    build = Mock(side_effect=AssertionError("smoke built an adapter for a walled company"))
    monkeypatch.setattr(smoke_adapters, "build_adapter", build)
    await smoke_adapters.run_one("google", 5)
    out = capsys.readouterr().out
    assert "walled" in out and "Followed companies" in out
    build.assert_not_called()


# --------------------------------------------------------------------------- #
# Following
# --------------------------------------------------------------------------- #


def _row(slug: str, *, enabled: bool, consent: str | None = None) -> TrackedCompany:
    return TrackedCompany(
        slug=slug, display=slug.title(), adapter="google", board_token=None, status="active",
        enabled=enabled, visible=True, source="builtin", consent_fingerprint=consent,
    )


def test_discovery_keeps_reporting_a_consent_after_the_robots_file_changes(monkeypatch):
    # `consented` is what the dashboard reads to decide whether to show the dialog.
    _move_googles_robots_file(monkeypatch)
    state = build_company_discovery(tracked={
        "google": _row("google", enabled=True, consent=CONSENT),
        "google-deepmind": _row("google-deepmind", enabled=True),
    })
    by_slug = {company["slug"]: company for company in state["companies"]}
    assert by_slug["google"]["consented"] is True
    assert by_slug["google-deepmind"]["consented"] is False


def test_discovery_reports_the_wall_and_whether_the_user_consented():
    state = build_company_discovery(tracked={
        "google": _row("google", enabled=True),
        "google-deepmind": _row("google-deepmind", enabled=True, consent=CONSENT),
    })
    by_slug = {company["slug"]: company for company in state["companies"]}
    assert (by_slug["google"]["wall"], by_slug["google"]["consented"]) == ("robots", False)
    assert (by_slug["google-deepmind"]["wall"], by_slug["google-deepmind"]["consented"]) == ("robots", True)
    assert (by_slug["apple"]["wall"], by_slug["apple"]["consented"]) == (None, False)


@pytest.mark.asyncio
async def test_following_a_walled_company_needs_its_consent(db_session, api_client, dispatched):
    db_session.add(_row("google", enabled=False))
    await db_session.commit()

    refused = await api_client.put("/api/companies/selection", json={"follow": ["google"]})
    assert refused.status_code == 409
    await db_session.refresh(row := await db_session.get(TrackedCompany, "google"))
    assert row.enabled is False and row.consented_at is None, "a refusal applies nothing"
    assert dispatched == [], "and starts no scan"

    text = "Google's careers site asks automated tools not to collect its job listings. ..."
    ok = await api_client.put("/api/companies/selection", json={
        "follow": ["google"], "consents": [{"slug": "google", "text": text}],
    })
    assert ok.status_code == 200
    google = next(c for c in ok.json()["companies"] if c["slug"] == "google")
    assert google["enabled"] and google["consented"]
    await db_session.refresh(row)
    assert row.consent_text == text and row.consent_fingerprint == CONSENT and row.consented_at
    assert row.consent_locale == "en", "a record of an agreement says which language it was made in"
    assert dispatched == ["dispatcher"], "a consented follow starts its first scan now"


def test_a_consent_records_its_language_and_refuses_one_that_is_not_a_tag():
    row = _row("google", enabled=False)
    record_consent(row, "Its careers site limits automated collection.", locale="es", now=datetime(2026, 1, 1, tzinfo=UTC))
    assert (row.consent_locale, row.consent_fingerprint) == ("es", CONSENT), "a translation covers the same wall"
    before = (row.consented_at, row.consent_text, row.consent_locale, row.consent_fingerprint)
    for invalid in ("<script>", "en-12-34"):
        with pytest.raises(CompanyError):
            record_consent(row, "Different text", locale=invalid)
        assert (row.consented_at, row.consent_text, row.consent_locale, row.consent_fingerprint) == before, "a refused consent changes nothing"


@pytest.mark.asyncio
async def test_a_walled_follow_from_before_consent_existed_survives_other_changes(db_session, api_client):
    # An install that followed Google before consent existed: followed, never consented.
    db_session.add(_row("google", enabled=True))
    await db_session.commit()
    # An unrelated change must not fail on it...
    ok = await api_client.put("/api/companies/selection", json={"follow": ["apple"]})
    assert ok.status_code == 200
    google = next(c for c in ok.json()["companies"] if c["slug"] == "google")
    # ...and it stays followed, still unconsented, so it is still not scanned.
    assert google["enabled"] and not google["consented"]


@pytest.mark.asyncio
async def test_refollowing_after_an_unfollow_never_asks_again(db_session, api_client, monkeypatch):
    agreed = datetime(2026, 1, 1, tzinfo=UTC)
    row = _row("google", enabled=True, consent=CONSENT)
    row.consented_at, row.consent_text, row.consent_locale = agreed, "As shown.", "en"
    db_session.add(row)
    await db_session.commit()
    assert (await api_client.put("/api/companies/selection", json={"unfollow": ["google"]})).status_code == 200
    # Undo, or a later follow, follows it again with no dialog.
    assert (await api_client.put("/api/companies/selection", json={"follow": ["google"]})).status_code == 200

    assert (await api_client.put("/api/companies/selection", json={"unfollow": ["google"]})).status_code == 200
    _move_googles_robots_file(monkeypatch)
    again = await api_client.put("/api/companies/selection", json={"follow": ["google"]})
    assert again.status_code == 200, "an update to the register does not ask the same question again"
    google = next(c for c in again.json()["companies"] if c["slug"] == "google")
    assert google["enabled"] and google["consented"]
    await db_session.refresh(row)
    assert (row.consented_at, row.consent_text, row.consent_fingerprint) == (agreed, "As shown.", CONSENT), (
        "the record of what was agreed is kept as it was given"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("consent", [
    {"slug": "apple", "text": "x"},          # not walled: nothing to consent to
    {"slug": "google", "text": "x"},         # not in this selection
])
async def test_a_consent_must_name_a_walled_company_this_selection_follows(consent, db_session, api_client):
    db_session.add(_row("google", enabled=False))
    await db_session.commit()
    response = await api_client.put("/api/companies/selection", json={
        "follow": ["apple"], "consents": [consent],
    })
    assert response.status_code == 400
    row = await db_session.get(TrackedCompany, "google")
    await db_session.refresh(row)
    assert row.consented_at is None


@pytest.mark.asyncio
async def test_the_single_company_switch_cannot_skip_the_dialog(db_session, api_client):
    db_session.add(_row("google", enabled=False))
    await db_session.commit()
    response = await api_client.patch("/api/companies/google", json={"enabled": True})
    assert response.status_code == 409


# --------------------------------------------------------------------------- #
# The scheduler
# --------------------------------------------------------------------------- #


def test_an_unconsented_walled_company_is_not_due_work():
    """It would be refused anyway — and left in the plan it is PERMANENTLY
    overdue, so it would take a dispatch slot from a scannable source on every
    tick, forever."""
    from tracker.config import Settings
    from tracker.workflows.collection_types import ScanMode
    from tracker.workflows.scheduler import DueWork, collectable_now

    now = datetime(2026, 9, 21, 12, 0, tzinfo=UTC)
    due = [
        DueWork(1, "google", "google", ScanMode.RECONCILE, now),
        DueWork(2, "apple", "apple", ScanMode.RECONCILE, now),
    ]
    targets = {
        "google": {"adapter": "google", "consent": None},
        "apple": {"adapter": "apple"},
    }
    assert [item.company_slug for item in collectable_now(due, targets, Settings())] == ["apple"]

    targets["google"]["consent"] = CONSENT
    assert [item.company_slug for item in collectable_now(due, targets, Settings())] == [
        "google", "apple",
    ]


def test_a_consented_company_stays_scheduled_after_its_robots_file_changes(monkeypatch):
    from tracker.config import Settings
    from tracker.workflows.collection_types import ScanMode
    from tracker.workflows.scheduler import DueWork, collectable_now

    _move_googles_robots_file(monkeypatch)
    now = datetime(2026, 9, 21, 12, 0, tzinfo=UTC)
    due = [DueWork(1, "google", "google", ScanMode.RECONCILE, now)]
    targets = {"google": {"adapter": "google", "consent": CONSENT}}
    assert [item.company_slug for item in collectable_now(due, targets, Settings())] == ["google"]


# --------------------------------------------------------------------------- #
# User-directed sources: consent says "you may", not "now"
# --------------------------------------------------------------------------- #


def _workday_due():
    from tracker.workflows.collection_types import ScanMode
    from tracker.workflows.scheduler import DueWork

    now = datetime(2026, 9, 23, 12, 0, tzinfo=UTC)
    consent = SOURCE_REVIEWS["workday"].wall_fingerprint
    due = [
        DueWork(1, "nvidia", "workday", ScanMode.RECONCILE, now),
        DueWork(2, "apple", "apple", ScanMode.RECONCILE, now),
    ]
    targets = {
        "nvidia": {"adapter": "workday", "consent": consent},
        "apple": {"adapter": "apple"},
    }
    return due, targets


def test_a_consented_user_directed_company_still_waits_for_the_user():
    """A Workday company is scanned by a sync the user
    starts, never because a deadline passed. Consent alone must not schedule
    it — that is the difference between 'you may' and 'now'."""
    from tracker.config import Settings
    from tracker.workflows.scheduler import collectable_now

    due, targets = _workday_due()
    assert [item.company_slug for item in collectable_now(due, targets, Settings())] == ["apple"]


def test_the_sync_button_is_what_collects_a_user_directed_company():
    """The manual request on the binding (what `queue_manual_reconciliation`
    writes) is the user asking, and it admits exactly that binding."""
    from tracker.config import Settings
    from tracker.workflows.scheduler import collectable_now

    due, targets = _workday_due()
    admitted = collectable_now(due, targets, Settings(), manual_binding_ids=[1])
    assert [item.company_slug for item in admitted] == ["nvidia", "apple"]


def test_a_user_directed_company_needs_no_consent_only_the_users_request():
    """The source asks nothing of us, so there is nothing to consent TO.
    What it still needs is the user's request: without one the
    scheduler leaves it alone, with one it runs."""
    from tracker.config import Settings
    from tracker.workflows.scheduler import collectable_now

    due, targets = _workday_due()
    targets["nvidia"]["consent"] = None
    assert [item.company_slug for item in collectable_now(due, targets, Settings())] == ["apple"]
    assert [item.company_slug for item in collectable_now(due, targets, Settings(), [1])] == [
        "nvidia", "apple",
    ]
    # And the gate does not refuse it: following the company was the decision.
    access = collection_access("workday", company="nvidia", settings=Settings(), consent=None)
    assert not access.walled and not access.denied


def test_only_workday_is_user_directed_and_it_is_not_a_wall():
    """The register approves COLLECTION from this source on the condition the user
    directs it. The approval is recorded (with its author), and it changes
    nothing a user has not asked for: the wall still refuses, and no tenant is
    approved by it."""
    from tracker.source_review import ReviewResult, effective_review, user_directed_source

    directed = sorted(key for key, row in SOURCE_REVIEWS.items() if row.user_directed)
    assert directed == ["workday"]
    assert user_directed_source("workday") and not user_directed_source("greenhouse")
    # Resolved through the company's declared provider, exactly as the wall is,
    # for a catalog company as for a built-in.
    assert user_directed_source("recipe", company="nvidia")
    assert user_directed_source("recipe", company="adobe")

    assert SOURCE_REVIEWS["workday"].review is ReviewResult.APPROVED
    assert SOURCE_REVIEWS["workday"].reviewer == "owner"
    assert effective_review("workday", company="nvidia") is ReviewResult.UNREVIEWED
    # The approval is not a key either: it approves no employer, and every
    # Workday company still starts off the curated list.
    assert not is_curated("nvidia") and not is_curated("salesforce")

@pytest.mark.asyncio
async def test_http_consent_records_the_exact_displayed_text_and_locale(db_session, api_client, dispatched):
    db_session.add(_row("google", enabled=False))
    await db_session.commit()
    shown = "Google · Su sitio limita la recopilación. Its careers site limits automated collection."
    response = await api_client.put("/api/companies/selection", json={
        "follow": ["google"],
        "consents": [{"slug": "google", "text": shown, "locale": "es"}],
    })
    assert response.status_code == 200
    row = await db_session.get(TrackedCompany, "google")
    await db_session.refresh(row)
    assert (row.consent_text, row.consent_locale, row.consent_fingerprint) == (shown, "es", CONSENT)
    rejected = await api_client.put("/api/companies/selection", json={
        "follow": ["google"], "consents": [{"slug":"google", "text":"different", "locale":"en-12-34"}],
    })
    assert rejected.status_code == 422
    await db_session.refresh(row)
    assert (row.consent_text, row.consent_locale) == (shown, "es")
