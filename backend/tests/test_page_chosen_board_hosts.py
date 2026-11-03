"""A board whose host a careers page chose sends no request anywhere else.

Jibe and Avature tenants are known by the host their careers page is served
from (`ats_detect.detect_page`), so a company added by pasting a URL gets
whatever host that page lives on, and every later scan reads it. Each request
such a scan makes, redirect hops and posting links included, stays on that
host: a hostile page cannot point recurring requests at this computer or the
network it sits on.

The test clients follow redirects as the production client does, so a hop the
adapter did not check would be sent.
"""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlsplit

import httpx
import pytest

from tracker.connectors import build_adapter
from tracker.platform.ratelimit import RateLimiter
from tracker.platform.safe_fetch import BlockedDestination

FIX = Path(__file__).parent / "fixtures/listings"
JIBE_PAGE = json.loads((FIX / "jibe/page1.json").read_text())
AVATURE_PAGE = json.loads((FIX / "avature/page1.json").read_text())["html"]
AVATURE_DETAIL = (FIX / "avature/detail_216202.html").read_text()
LOOPBACK = "http://127.0.0.1:8010"
PASTED = "careers.pasted.example"


def _adapter(adapter_name: str, token: str, handle):
    asked: list[str] = []

    def record(request: httpx.Request) -> httpx.Response:
        asked.append(str(request.url))
        return handle(request)

    adapter = build_adapter("pasted-company", adapter_name, board_token=token)
    adapter._client = httpx.AsyncClient(transport=httpx.MockTransport(record), follow_redirects=True)
    adapter._limiter = RateLimiter(0)
    return adapter, asked


def _hosts(asked: list[str]) -> set[str | None]:
    return {urlsplit(url).hostname for url in asked}


@pytest.mark.asyncio
async def test_a_jibe_board_never_follows_a_redirect_off_its_host():
    def handle(request):
        if request.url.host == PASTED:
            return httpx.Response(302, headers={"location": f"{LOOPBACK}/api/status"})
        return httpx.Response(200, json={**JIBE_PAGE, "jobs": []})

    adapter, asked = _adapter("jibe", PASTED, handle)
    with pytest.raises(BlockedDestination):
        [job async for job in adapter.fetch()]
    assert _hosts(asked) == {PASTED}


@pytest.mark.asyncio
async def test_a_jibe_board_still_follows_a_redirect_on_its_own_host():
    def handle(request):
        if request.url.path == "/api/jobs":
            return httpx.Response(302, headers={"location": f"https://{PASTED}/api/v2/jobs?page=1&limit=100"})
        return httpx.Response(200, json={**JIBE_PAGE, "jobs": [], "totalCount": 0})

    adapter, asked = _adapter("jibe", PASTED, handle)
    assert [job async for job in adapter.fetch()] == []
    assert len(asked) == 2 and _hosts(asked) == {PASTED}


@pytest.mark.asyncio
@pytest.mark.parametrize("route", ["avature", "avature_tls"])
async def test_an_avature_posting_link_off_the_tenant_host_is_never_read(route, monkeypatch):
    if route == "avature_tls":
        # The walled route runs only for a consented user; the consent is
        # granted here so the posting-link check, not the policy, is what refuses.
        from tracker.connectors.listing import base
        from tracker.source_policy import collection_access
        from tracker.source_review import SOURCE_REVIEWS

        consented = collection_access(
            "avature_tls", company="pasted-company", consent=SOURCE_REVIEWS["avature_tls"].wall_fingerprint,
        )
        monkeypatch.setattr(base.BaseAdapter, "access", property(lambda self: consented))
    off_host = AVATURE_PAGE.replace("https://jobs.ea.com/en_US/careers/JobDetail/", f"{LOOPBACK}/en_US/careers/JobDetail/")

    def handle(request):
        if "/JobDetail/" in request.url.path:
            return httpx.Response(200, text=AVATURE_DETAIL)
        page = off_host if request.url.params.get("jobOffset") in (None, "0") else "<html></html>"
        return httpx.Response(200, text=page)

    adapter, asked = _adapter(route, "jobs.ea.com|en_US/careers", handle)
    jobs = [job async for job in adapter.fetch()]
    assert jobs and all(job.url.startswith(LOOPBACK) for job in jobs)
    await adapter.hydrate(jobs[0])
    assert not jobs[0].description_complete
    assert _hosts(asked) == {"jobs.ea.com"}
