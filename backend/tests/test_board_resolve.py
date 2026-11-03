"""A pasted careers page names its board; the board must answer.

`detect_page` is pure: which family a page's markers name, with the token taken
from the URL it was served at. `detect_by_page` adds the fetch and the
verification. Every network answer here is a `MockTransport` serving the real
fixture bodies, so verification runs each family's own count reader.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from tracker import board_resolve
from tracker.ats_detect import DetectedBoard, detect_page
from tracker.board_resolve import detect_by_page, resolve_pasted_board

FIXTURES = Path(__file__).parent / "fixtures/listings"
JIBE = (FIXTURES / "jibe/page1.json").read_text()
AVATURE = json.loads((FIXTURES / "avature/page1.json").read_text())["html"]
RADANCY = json.loads((FIXTURES / "radancy/page1.json").read_text())["html"]
SR_NO_OPENINGS = (FIXTURES / "smartrecruiters/empty_board.html").read_text()


# --- detect_page: pure ------------------------------------------------------ #


@pytest.mark.parametrize("url,html,expected", [
    ("https://www.github.careers/careers-home/jobs", "<script src=x.jibeapply.com>", ("jibe", "www.github.careers")),
    ("https://careers.arm.com/search-jobs", "cdn.TalentBrew.com", ("radancy", "careers.arm.com")),
    # TalentBrew that applies through Avature names both; the page is TalentBrew.
    ("https://careers.synopsys.com/search-jobs", "talentbrew ... avature", ("radancy", "careers.synopsys.com")),
    ("https://jobs.ea.com/en_US/careers/SearchJobs", "/portalpacks/", ("avature", "jobs.ea.com|en_US/careers")),
    ("https://apply.deloitte.com/en_US/careers/SearchJobs/?q=x", "portalpacks", ("avature", "apply.deloitte.com|en_US/careers")),
])
def test_a_page_marker_names_the_family_and_the_url_names_the_tenant(url, html, expected):
    assert detect_page(url, html) == DetectedBoard(*expected)


def test_the_token_never_comes_from_page_text():
    html = "jibeapply <a href='https://www.victim.example/'>www.victim.example</a>"
    assert detect_page("https://jobs.acme.example/", html).board_token == "jobs.acme.example"


@pytest.mark.parametrize("url,html", [
    ("https://www.anthropic.com/careers", "<html>no vendor here</html>"),
    ("http://www.github.careers/", "jibeapply"),                   # never over plain http
    ("https://paypal.eightfold.ai/careers", "talentbrew"),         # a vendor's own host
    ("https://jobs.ea.com/", "portalpacks"),                       # Avature, but no portal in the URL
    ("https://boards.greenhouse.io/stripe", "jibeapply"),           # URL-detectable: the URL decides
])
def test_a_page_that_names_no_board_we_can_place(url, html):
    assert detect_page(url, html) is None


# --- detect_by_page: fetch, policy, verification ---------------------------- #


def _client(routes: dict[str, httpx.Response], seen: list[str]) -> httpx.AsyncClient:
    def handle(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        seen.append(url)
        # Longest prefix wins: a page URL is often a prefix of its board route.
        matches = [prefix for prefix in routes if url.startswith(prefix)]
        return routes[max(matches, key=len)] if matches else httpx.Response(404)

    return httpx.AsyncClient(transport=httpx.MockTransport(handle))


def _page(marker: str) -> httpx.Response:
    return httpx.Response(200, text=f"<html><script>{marker}</script></html>",
                          headers={"content-type": "text/html"})


@pytest.mark.asyncio
async def test_a_jibe_page_whose_board_answers_is_detected():
    seen: list[str] = []
    routes = {
        "https://jobs.acme.example/careers": _page("jibeapply"),
        "https://jobs.acme.example/api/jobs": httpx.Response(200, text=JIBE),
    }
    async with _client(routes, seen) as client:
        board = await detect_by_page("https://jobs.acme.example/careers", slug="acme", client=client)

    assert board == DetectedBoard("jibe", "jobs.acme.example")
    assert seen[1].startswith("https://jobs.acme.example/api/jobs")


@pytest.mark.asyncio
@pytest.mark.parametrize(("body", "answers"), [
    (SR_NO_OPENINGS, True),
    ("<html><head><title>SmartRecruiters Job Search</title></head></html>", False),
], ids=["no-openings", "not-a-board"])
async def test_a_smartrecruiters_board_with_no_openings_still_answers(body, answers):
    """A live board listing nothing is a board to verify a company against; the
    page an unknown token lands on is not."""
    routes = {"https://careers.smartrecruiters.com/Dailymotion": httpx.Response(200, text=body)}
    async with _client(routes, []) as client:
        board = DetectedBoard("smartrecruiters", "Dailymotion")
        assert await board_resolve.board_answers(board, client) is answers


@pytest.mark.asyncio
async def test_a_redirected_page_names_the_host_that_served_it():
    seen: list[str] = []
    routes = {
        "https://acme.example/careers": httpx.Response(302, headers={"location": "https://careers.acme.example/search-jobs"}),
        "https://careers.acme.example/search-jobs": _page("talentbrew"),
        "https://careers.acme.example/sitemap.xml": httpx.Response(
            200, text=RADANCY.replace("careers.arm.com", "careers.acme.example")),
    }
    async with _client(routes, seen) as client:
        board = await detect_by_page("https://acme.example/careers", slug="acme", client=client)
    assert board == DetectedBoard("radancy", "careers.acme.example")


@pytest.mark.asyncio
async def test_an_avature_portal_that_states_its_total_is_detected():
    seen: list[str] = []
    routes = {
        "https://jobs.acme.example/en_US/careers": _page("portalpacks"),
        "https://jobs.acme.example/en_US/careers/SearchJobs/": httpx.Response(200, text=AVATURE),
    }
    async with _client(routes, seen) as client:
        board = await detect_by_page("https://jobs.acme.example/en_US/careers", slug="acme", client=client)
    assert board == DetectedBoard("avature", "jobs.acme.example|en_US/careers")


@pytest.mark.asyncio
async def test_a_board_that_does_not_answer_its_route_is_not_detected():
    """A marker is page content; only the board route is evidence. Deloitte's
    portal is Avature but states no total, so the adapter could not claim it
    complete — it must stay pending rather than fail its first scan."""
    seen: list[str] = []
    routes = {
        "https://apply.acme.example/en_US/careers": _page("portalpacks"),
        "https://apply.acme.example/en_US/careers/SearchJobs/": httpx.Response(
            200, text="<html>10 cards and no stated total</html>"),
    }
    async with _client(routes, seen) as client:
        assert await detect_by_page("https://apply.acme.example/en_US/careers", slug="acme", client=client) is None

    dead: list[str] = []
    async with _client({"https://jobs.acme.example/": _page("jibeapply")}, dead) as client:
        assert await detect_by_page("https://jobs.acme.example/", slug="acme", client=client) is None
    assert len(dead) == 2  # the page, then the probe that 404ed


@pytest.mark.asyncio
async def test_a_source_policy_refuses_before_the_board_is_probed(monkeypatch):
    from tracker.source_policy import CollectionAccess

    monkeypatch.setattr(
        board_resolve, "collection_access",
        lambda provider, company=None: CollectionAccess(provider, "denied for the test"),
    )
    seen: list[str] = []
    routes = {"https://jobs.acme.example/": _page("jibeapply")}
    async with _client(routes, seen) as client:
        assert await detect_by_page("https://jobs.acme.example/", slug="acme", client=client) is None
    assert seen == ["https://jobs.acme.example/"]


@pytest.mark.asyncio
async def test_any_failure_leaves_the_company_pending_and_never_raises():
    def explode(_request):
        raise RuntimeError("something nobody planned for")

    async with httpx.AsyncClient(transport=httpx.MockTransport(explode)) as client:
        assert await detect_by_page("https://jobs.acme.example/", slug="acme", client=client) is None


@pytest.mark.asyncio
async def test_only_a_pending_url_add_is_ever_fetched(monkeypatch):
    def refuse(**_kwargs):
        raise AssertionError("fetched a company that was not a pending URL add")

    monkeypatch.setattr(board_resolve, "public_client", refuse)
    active = {"status": "active", "source": "url", "careers_url": "https://jobs.ashbyhq.com/acme", "slug": "acme"}
    catalog = {"status": "pending", "source": "catalog", "careers_url": "https://x.example/", "slug": "x"}
    assert await resolve_pasted_board(active) is active
    assert await resolve_pasted_board(catalog) is catalog


@pytest.mark.asyncio
async def test_a_detected_board_upgrades_the_pending_add(monkeypatch):
    routes = {
        "https://jobs.acme.example/careers": _page("jibeapply"),
        "https://jobs.acme.example/api/jobs": httpx.Response(200, text=JIBE),
    }
    monkeypatch.setattr(board_resolve, "public_client", lambda **_kw: _client(routes, []))
    fields = {"slug": "acme", "display": "Acme", "adapter": None, "board_token": None,
              "board_region": None, "careers_url": "https://jobs.acme.example/careers",
              "status": "pending", "source": "url"}

    upgraded = await resolve_pasted_board(fields)
    assert (upgraded["status"], upgraded["adapter"], upgraded["board_token"]) == (
        "active", "jibe", "jobs.acme.example",
    )
    assert fields["status"] == "pending"  # the caller's dict is not mutated


@pytest.mark.asyncio
async def test_a_board_answer_cut_by_the_byte_cap_is_not_a_board(monkeypatch):
    """A real Jibe answer can exceed the page cap and be cut mid-JSON; it must
    not read as no board at all. A cut answer is never counted as evidence."""
    routes = {
        "https://jobs.acme.example/careers": _page("jibeapply"),
        "https://jobs.acme.example/api/jobs": httpx.Response(200, text=JIBE),
    }
    monkeypatch.setattr(board_resolve, "PROBE_MAX_BYTES", len(JIBE) // 2)
    async with _client(routes, []) as client:
        assert await detect_by_page("https://jobs.acme.example/careers", slug="acme", client=client) is None


# --- a pending add names the family its page named, and why ----------------- #


def _pending(url: str) -> dict:
    return {"slug": "acme", "display": "Acme", "adapter": None, "board_token": None, "board_region": None,
            "careers_url": url, "status": "pending", "source": "url"}


@pytest.mark.asyncio
async def test_a_board_that_does_not_answer_leaves_its_family_named(monkeypatch):
    routes = {"https://jobs.acme.example/": _page("jibeapply")}
    monkeypatch.setattr(board_resolve, "public_client", lambda **_kw: _client(routes, []))
    kept = await resolve_pasted_board(_pending("https://jobs.acme.example/"))
    assert (kept["status"], kept["detected_family"], kept["pending_reason"]) == ("pending", "jibe", "board_silent")


@pytest.mark.asyncio
async def test_a_refused_source_leaves_its_family_named(monkeypatch):
    from tracker.source_policy import CollectionAccess

    monkeypatch.setattr(board_resolve, "collection_access",
                        lambda provider, company=None: CollectionAccess(provider, "denied for the test"))
    routes = {"https://jobs.acme.example/": _page("jibeapply")}
    monkeypatch.setattr(board_resolve, "public_client", lambda **_kw: _client(routes, []))
    kept = await resolve_pasted_board(_pending("https://jobs.acme.example/"))
    assert (kept["detected_family"], kept["pending_reason"]) == ("jibe", "policy_refused")


@pytest.mark.asyncio
async def test_an_unrecognised_page_names_no_family(monkeypatch):
    routes = {"https://jobs.acme.example/": _page("nothing anyone knows")}
    monkeypatch.setattr(board_resolve, "public_client", lambda **_kw: _client(routes, []))
    kept = await resolve_pasted_board(_pending("https://jobs.acme.example/"))
    assert (kept["status"], kept["detected_family"], kept["pending_reason"]) == ("pending", None, None)

