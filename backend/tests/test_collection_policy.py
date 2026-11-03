"""A configured denial reaches every supported collection/transport entry."""

from unittest.mock import AsyncMock, Mock

import httpx
import pytest

from tests.test_recipe_adapter import RECIPE
from tracker.config import COMPANIES, get_settings
from tracker.connectors import ADAPTER_REGISTRY, build_adapter
from tracker.connectors.listing.recipe_adapter import RecipeAdapter
from tracker.connectors.recipes import compile_recipe, run_plan
from tracker.connectors.runtime.context import RuntimeContext
from tracker.connectors.runtime.httpx_transport import HttpxTransport
from tracker.connectors.sdk import FetchRequest
from tracker.platform.drift import SchemaDriftDetector
from tracker.platform.ratelimit import RateLimiter
from tracker.source_policy import CollectionPolicyDenied, collection_access, scanned_automatically

#: A denied provider and a company that declares it. Synthetic by design.
DENIED_ATS = "denied-ats"
DENIED_CO = "denied-co"


@pytest.fixture
def deny(monkeypatch):
    """Configure a denial, and register the synthetic company that carries it.

    No real provider is denied. The denial machinery has to keep working when
    no tracked company is denied, which is exactly when a regression in it
    would go unnoticed, so these tests supply their own denied company instead
    of borrowing one.
    """
    monkeypatch.setitem(COMPANIES, DENIED_CO, {"adapter": DENIED_ATS})

    def configure(*providers):
        monkeypatch.setattr(get_settings(), "sync_policy_denied_providers", frozenset(providers))
        monkeypatch.setattr(get_settings(), "scraper_max_retries", 0)
        monkeypatch.setattr(get_settings(), "scraper_min_delay_seconds", 0)
    return configure


@pytest.mark.parametrize("denied", [False, True])
def test_automatic_coverage_honors_current_operator_policy(deny, denied):
    deny(*(["greenhouse"] if denied else []))
    assert scanned_automatically("greenhouse", "coverage-fixture", None) is not denied


@pytest.mark.parametrize(
    "provider,company,denied",
    [
        (DENIED_ATS, None, True),
        (DENIED_ATS, DENIED_CO, True),
        # A recipe runs SOME company's board. Naming the executor `recipe`
        # cannot shed the denial its declared provider carries.
        ("recipe", DENIED_CO, True),
        ("recipe", "stripe", False),
        ("greenhouse", "stripe", False),
        ("greenhouse", DENIED_CO, True),  # a denied company keeps its denial
    ],
)
def test_the_reporting_gate_and_the_executor_read_one_decision(provider, company, denied, deny):
    """Scheduler/ops report with `.denied`; collection refuses with `.require()`.

    Both must use the same resolver: direct set membership cannot see a
    company's declared provider.
    """
    deny(DENIED_ATS)
    access = collection_access(provider, company=company)

    assert access.denied is denied
    if denied:
        with pytest.raises(CollectionPolicyDenied) as raised:
            access.require()
        assert raised.value.access.provider_key == DENIED_ATS
    else:
        access.require()


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", sorted(ADAPTER_REGISTRY))
@pytest.mark.parametrize("entry", ["context", "direct_fetch"])
async def test_denied_adapter_never_reaches_http_or_curl(provider, entry, deny):
    deny(provider)
    # A built-in tenant when the family has one, else any slug: the denial is
    # keyed on the PROVIDER, and a family whose only tenant is a catalog row
    # (workable) must be covered by this gate exactly like the rest.
    # A bare `next(...)` raises StopIteration for such a family, inside a
    # coroutine, so it surfaces as "coroutine raised StopIteration" rather than
    # as the missing-company fact it is.
    company = next(
        (slug for slug, cfg in COMPANIES.items() if cfg["adapter"] == provider),
        "policy-test-co",
    )
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(403, request=request)

    adapter = build_adapter(company, provider)
    adapter._limiter = RateLimiter(0)
    curl = AsyncMock()
    curl.request.return_value = httpx.Response(403)
    adapter._session = curl
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        adapter._client = client
        with pytest.raises(PermissionError, match="policy"):
            if entry == "context":
                async with adapter:
                    pass
            else:
                _ = [job async for job in adapter.fetch()]
    assert requests == []
    curl.request.assert_not_awaited()
    assert adapter.drift.alerts == []


@pytest.mark.asyncio
@pytest.mark.parametrize("entry", ["buffered", "stream", "context", "context_stream"])
async def test_denied_transport_cannot_send_or_retry(entry, deny):
    deny("review-provider")
    client_provider = AsyncMock()
    # A synchronous supplier must never be reached by a denied transport.
    supplier = Mock(return_value=client_provider)
    request = FetchRequest(url="https://careers.example.test/jobs")
    transport = HttpxTransport(supplier, log_name="review-provider")
    with pytest.raises(PermissionError, match="policy"):
        if entry == "buffered":
            await transport.send(request)
        elif entry == "stream":
            async with transport.open_stream(request):
                pass
        else:
            # Context gate must hold even over a separately constructed transport.
            context = RuntimeContext(
                transport=HttpxTransport(supplier), connector_name="review-provider",
                drift=SchemaDriftDetector("review"),
            )
            if entry == "context":
                await context.fetch(request)
            else:
                async with context.stream(request):
                    pass
    supplier.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("company,provider", [(DENIED_CO, DENIED_ATS), ("demo", "recipe")])
@pytest.mark.parametrize("entry", ["adapter", "runner"])
async def test_recipe_cannot_bypass_static_provider_denial(company, provider, entry, deny):
    deny(provider)
    plan = compile_recipe(RECIPE)
    requests = AsyncMock()
    with pytest.raises(PermissionError, match="policy"):
        if entry == "adapter":
            adapter = RecipeAdapter(company, plan)
            async with adapter:
                _ = [job async for job in adapter.fetch()]
        else:
            await run_plan(plan, requests, company)
    requests.fetch.assert_not_awaited()


@pytest.mark.asyncio
async def test_allowed_board_still_returns_postings(deny):
    deny(DENIED_ATS)
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(200, json={"jobs": [{
            "id": 123, "title": "Staff Engineer", "absolute_url": "https://example.test/123",
        }]})

    adapter = build_adapter("fixture", "greenhouse", "fixture")
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        adapter._client = client
        jobs = [job async for job in adapter.fetch()]
    assert [job.req_id for job in jobs] == ["123"]
    assert len(requests) == 1
    assert adapter.drift.listing_complete


@pytest.mark.asyncio
async def test_smoke_reports_local_denial_without_creating_transport(deny, monkeypatch, capsys):
    """`run_one` consults the policy before it builds anything, so a denied
    company costs no adapter and no transport at all."""
    from scripts import smoke_adapters

    deny(DENIED_ATS)
    build = Mock(side_effect=AssertionError("denied smoke built an adapter"))
    monkeypatch.setattr(smoke_adapters, "build_adapter", build)

    async def no_consent(_company):
        return None  # Refuse a configured-database read; no consent is needed for denial.

    monkeypatch.setattr(smoke_adapters, "_stored_consent", no_consent)
    await smoke_adapters.run_one(DENIED_CO, 5)
    assert "policy" in capsys.readouterr().out.lower()
    build.assert_not_called()
