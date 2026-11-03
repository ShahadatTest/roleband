"""Shared harnesses for the listing-connector contract suite.

Transport injection (the one mechanism this suite uses): adapters build their
real httpx client inside ``__aenter__`` via ``tracker.platform.http.make_client``.
The contract suite never enters that context manager; each harness assigns
``adapter._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))``
directly and zeroes the pacer (``adapter._limiter = RateLimiter(0.0)``) — the
same convention as the per-adapter tests in ``tests/test_adapter_*.py``. Meta is
the one exception: it runs on curl_cffi, so its harness injects a fake
``AsyncSession`` that dispatches to the same handler.

Fixture convention (``tests/fixtures/listings/<adapter>/``):
- ``page1.json`` — first listing response body; ``page2.json`` — next page,
  where the board's declared total leaves room for one. An adapter held to its
  declared total (``close_listing``) needs a fixture whose rows ADD UP to that
  total: apple, amazon, microsoft and workday keep one page whose total is its
  row count, because an invented total larger than the rows is a
  shortfall, not a fixture.
- JSON-API adapters store the raw response payload — an envelope object for most
  boards, a bare array for lever (which is what its API returns).
- google stores ``{"html": ...}`` (its listing is SSR HTML).
- meta stores ``{"sitemap": ..., "pages": {url: html}}`` (its listing is a
  sitemap crawl over per-job pages).

Modes (``build_harness(name, mode)``):
- ``normal``  — fixture pages served in order, then an empty page.
- ``repeat``  — page1 served for every listing request; pagination must still
  terminate (request cap enforced in the handler).
- ``broken``  — structurally mangled payload; fetch must degrade to drift.
- ``flaky429`` — first request answers 429 with ``Retry-After: 0``, then
  normal; the shared retry must recover.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import httpx

from tracker.connectors import build_adapter
from tracker.connectors.listing.base import BaseAdapter, RateLimiter
from tracker.source_review import SOURCE_REVIEWS

FIXTURES_ROOT = Path(__file__).resolve().parents[1] / "fixtures" / "listings"

#: Hard ceiling per fetch(); a terminating adapter stays far below it, a
#: pagination loop that never ends trips the assertion inside the handler.
REQUEST_CAP = 5000

#: Structurally mangled body used by ``broken`` mode for JSON sources.
MANGLED = {"unexpected": ["structure"]}

MODE_NORMAL = "normal"
MODE_REPEAT = "repeat"
MODE_BROKEN = "broken"
MODE_FLAKY_429 = "flaky429"

_EMPTY_HTML = "<html><body><main></main></body></html>"


def fixture_dir(adapter_name: str) -> Path:
    return FIXTURES_ROOT / adapter_name


def load_fixture(adapter_name: str, filename: str) -> dict | list:
    # `list` because a fixture stores the source's raw payload, and some boards
    # (Lever) answer a bare array rather than an envelope object.
    return json.loads((fixture_dir(adapter_name) / filename).read_text())


class RequestCounter:
    def __init__(self) -> None:
        self.count = 0


def _wrap_handler(
    adapter_name: str,
    route: Callable[[httpx.Request], httpx.Response],
    broken_route: Callable[[httpx.Request], httpx.Response],
    mode: str,
    counter: RequestCounter,
) -> Callable[[httpx.Request], httpx.Response]:
    def handler(request: httpx.Request) -> httpx.Response:
        counter.count += 1
        assert counter.count <= REQUEST_CAP, (
            f"{adapter_name}: exceeded {REQUEST_CAP} requests — pagination did not terminate"
        )
        if mode == MODE_FLAKY_429 and counter.count == 1:
            return httpx.Response(429, headers={"Retry-After": "0"})
        if mode == MODE_BROKEN:
            return broken_route(request)
        return route(request)

    return handler


def _wire_httpx(
    adapter: BaseAdapter,
    route: Callable[[httpx.Request], httpx.Response],
    broken_route: Callable[[httpx.Request], httpx.Response],
    mode: str,
) -> BaseAdapter:
    counter = RequestCounter()
    handler = _wrap_handler(adapter.name, route, broken_route, mode, counter)
    adapter._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter._limiter = RateLimiter(0.0)
    adapter.contract_requests = counter
    return adapter


def _json_broken(_request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json=MANGLED)


# --------------------------------------------------------------------------- #
# Per-adapter harness builders. Each returns a fetch-ready adapter whose
# transport serves the adapter's fixture files.
# --------------------------------------------------------------------------- #


def _greenhouse(mode: str) -> BaseAdapter:
    page1 = load_fixture("greenhouse", "page1.json")

    def route(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=page1)

    return _wire_httpx(build_adapter("anthropic", "greenhouse"), route, _json_broken, mode)


def _lever(mode: str) -> BaseAdapter:
    # Lever answers a bare JSON array and declares no total, so a page shorter
    # than the requested `limit` is the end of the board. The fixture is such a
    # page, which is why every mode terminates on the first request.
    page1 = load_fixture("lever", "page1.json")

    def route(request: httpx.Request) -> httpx.Response:
        if mode == MODE_REPEAT:
            return httpx.Response(200, json=page1)
        skip = request.url.params.get("skip")
        return httpx.Response(200, json=page1 if skip == "0" else [])

    return _wire_httpx(build_adapter("spotify", "lever"), route, _json_broken, mode)


def _ashby(mode: str) -> BaseAdapter:
    page1 = load_fixture("ashby", "page1.json")

    def route(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=page1)

    return _wire_httpx(build_adapter("openai", "ashby"), route, _json_broken, mode)


def _eightfold(mode: str) -> BaseAdapter:
    page1 = load_fixture("eightfold", "page1.json")
    page2 = load_fixture("eightfold", "page2.json")
    empty = {"count": page1["count"], "positions": []}

    def route(request: httpx.Request) -> httpx.Response:
        if mode == MODE_REPEAT:
            return httpx.Response(200, json=page1)
        start = request.url.params.get("start")
        body = {"0": page1, "10": page2}.get(start, empty)
        return httpx.Response(200, json=body)

    return _wire_httpx(build_adapter("netflix", "eightfold"), route, _json_broken, mode)


def _apple(mode: str) -> BaseAdapter:
    page1 = load_fixture("apple", "page1.json")
    empty = {"res": {"totalRecords": page1["res"]["totalRecords"], "searchResults": []}}

    def csrf(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"x-apple-csrf-token": "contract-token"})

    def route(request: httpx.Request) -> httpx.Response:
        if request.url.path.lower().endswith("csrftoken"):
            return csrf(request)
        if mode == MODE_REPEAT:
            return httpx.Response(200, json=page1)
        page = json.loads(request.content).get("page")
        body = {1: page1}.get(page, empty)
        return httpx.Response(200, json=body)

    def broken_route(request: httpx.Request) -> httpx.Response:
        # The CSRF handshake still succeeds so the mangled SEARCH payload (not a
        # missing token) is what the drift detector must catch.
        if request.url.path.lower().endswith("csrftoken"):
            return csrf(request)
        return httpx.Response(200, json=MANGLED)

    return _wire_httpx(build_adapter("apple", "apple"), route, broken_route, mode)


def _google(mode: str) -> BaseAdapter:
    page1 = load_fixture("google", "page1.json")["html"]
    page2 = load_fixture("google", "page2.json")["html"]

    def route(request: httpx.Request) -> httpx.Response:
        if mode == MODE_REPEAT:
            return httpx.Response(200, text=page1)
        page = request.url.params.get("page")
        return httpx.Response(200, text={"1": page1, "2": page2}.get(page, _EMPTY_HTML))

    def broken_route(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=_EMPTY_HTML)

    adapter = build_adapter("google", "google")
    # Google is walled (robots disallows the paginated listing): it is
    # collected only with the user's consent. The contract suite tests parsing,
    # so it stands in a consenting user rather than weakening the gate.
    adapter.collection_consent = SOURCE_REVIEWS["google"].wall_fingerprint
    return _wire_httpx(adapter, route, broken_route, mode)


def _amazon(mode: str) -> BaseAdapter:
    page1 = load_fixture("amazon", "page1.json")
    empty = {"hits": page1["hits"], "jobs": []}

    def route(request: httpx.Request) -> httpx.Response:
        if mode == MODE_REPEAT:
            return httpx.Response(200, json=page1)
        offset = request.url.params.get("offset")
        return httpx.Response(200, json={"0": page1}.get(offset, empty))

    return _wire_httpx(build_adapter("amazon", "amazon"), route, _json_broken, mode)


def _workday(mode: str) -> BaseAdapter:
    page1 = load_fixture("workday", "page1.json")
    empty = {"total": page1["total"], "jobPostings": []}
    # A row that lists "2 Locations" is placed from its detail answer before
    # scope reads it; the fixture carries that real NVIDIA shape.
    detail = load_fixture("workday", "detail_JR2020600.json")

    def route(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            if request.url.path.endswith("_JR2020600"):
                return httpx.Response(200, json=detail)
            return httpx.Response(404)
        if mode == MODE_REPEAT:
            return httpx.Response(200, json=page1)
        offset = json.loads(request.content).get("offset")
        return httpx.Response(200, json={0: page1}.get(offset, empty))

    # Walled, like the SmartRecruiters
    # API route: the harness consents so the contract exercises the
    # adapter rather than the gate.
    adapter = build_adapter("nvidia", "workday")
    adapter.collection_consent = SOURCE_REVIEWS["workday"].wall_fingerprint
    return _wire_httpx(adapter, route, _json_broken, mode)


def _microsoft(mode: str) -> BaseAdapter:
    page1 = load_fixture("microsoft", "page1.json")
    empty = {"status": 200, "data": {"count": page1["data"]["count"], "positions": []}}

    def route(request: httpx.Request) -> httpx.Response:
        if mode == MODE_REPEAT:
            return httpx.Response(200, json=page1)
        start = request.url.params.get("start")
        return httpx.Response(200, json={"0": page1}.get(start, empty))

    return _wire_httpx(build_adapter("microsoft", "microsoft"), route, _json_broken, mode)


class _CurlSessionStub:
    """curl_cffi AsyncSession stand-in dispatching to an httpx-style handler."""

    def __init__(self, handler: Callable[[httpx.Request], httpx.Response]) -> None:
        self._handler = handler

    async def request(self, method: str, url: str, **_kwargs) -> httpx.Response:
        return self._handler(httpx.Request(method, str(url)))

    async def close(self) -> None:
        return None


def _smartrecruiters(mode: str) -> BaseAdapter:
    # The board route: an index page declaring two group pages, a
    # second group page, an empty third, and one more-page completing the
    # Amsterdam group (9 shown + 10 = the 19 it states). Trimmed from Roland
    # Berger's board. MODE_REPEAT serves the index for every
    # listing request, which the page ceiling must end.
    root = fixture_dir("smartrecruiters")
    index = load_fixture("smartrecruiters", "page1.json")["html"]
    groups = (root / "groups_page1.html").read_text()
    more = (root / "more_amsterdam_page1.html").read_text()

    def route(request: httpx.Request) -> httpx.Response:
        path, page = request.url.path, request.url.params.get("page")
        if mode == MODE_REPEAT:
            return httpx.Response(200, text=more if path.endswith("/api/more") else index)
        if path.endswith("/api/groups"):
            return httpx.Response(200, text=groups if page == "1" else "")
        if path.endswith("/api/more"):
            return httpx.Response(200, text=more if page == "1" else "")
        return httpx.Response(200, text=index)

    return _wire_httpx(
        build_adapter("roland-berger", "smartrecruiters", board_token="RolandBerger"),
        route, _json_broken, mode,
    )


def _smartrecruiters_api(mode: str) -> BaseAdapter:
    # The walled API route. Its fixtures follow SmartRecruiters'
    # DOCUMENTED Posting API shape rather than a capture: the route is robots-
    # walled, and nothing is collected from it without a user's consent. The
    # board root redirects off SmartRecruiters (as Wise's does), so the adapter
    # stays on the API; the harness client follows redirects like the real one.
    page1 = load_fixture("smartrecruiters_api", "page1.json")

    def route(request: httpx.Request) -> httpx.Response:
        if request.url.host == "careers.smartrecruiters.com":
            return httpx.Response(301, headers={"Location": "https://wise.jobs/"})
        if request.url.host == "wise.jobs":
            return httpx.Response(200, text="<html><body>Wise careers</body></html>")
        if mode == MODE_REPEAT:
            return httpx.Response(200, json=page1)
        offset = request.url.params.get("offset")
        return httpx.Response(200, json=page1 if offset == "0" else {**page1, "content": []})

    adapter = build_adapter("wise", "smartrecruiters_api", board_token="Wise")
    adapter.collection_consent = SOURCE_REVIEWS["smartrecruiters_api"].wall_fingerprint
    wired = _wire_httpx(adapter, route, _json_broken, mode)
    wired._client = httpx.AsyncClient(transport=wired._client._transport, follow_redirects=True)
    return wired


def _atlassian(mode: str) -> BaseAdapter:
    # One GET returns the whole board, so every mode ends on the
    # first request. Real rows, including one verbatim repeat,
    # which the adapter must deduplicate without an alert.
    page1 = load_fixture("atlassian", "page1.json")

    def route(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=page1)

    return _wire_httpx(build_adapter("atlassian", "atlassian"), route, _json_broken, mode)


def _oracle(mode: str) -> BaseAdapter:
    # Oracle Cloud HCM: a real 4-row Fortinet page whose counts were
    # rewritten to make it a whole board; offset 0 serves it, later offsets an
    # empty list. The detail route serves one real requisition.
    page1 = load_fixture("oracle", "page1.json")
    detail = load_fixture("oracle", "detail_23073.json")
    empty = {"items": [{**page1["items"][0], "requisitionList": []}]}

    def route(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("recruitingCEJobRequisitionDetails"):
            return httpx.Response(200, json=detail)
        if mode == MODE_REPEAT or "offset=0," in request.url.params.get("finder", ""):
            return httpx.Response(200, json=page1)
        return httpx.Response(200, json=empty)

    return _wire_httpx(
        build_adapter("fortinet", "oracle", board_token="edel.fa.us2.oraclecloud.com|CX_2001"),
        route, _json_broken, mode,
    )


def _kpmg(mode: str) -> BaseAdapter:
    # KPMG US's own search: a real page 1 whose stated count was
    # rewritten to its 12 cards, so it is the whole board; later pages empty.
    page1 = load_fixture("kpmg", "page1.json")["html"]

    def route(request: httpx.Request) -> httpx.Response:
        if mode == MODE_REPEAT or request.url.params.get("spage") == "1":
            return httpx.Response(200, text=page1)
        return httpx.Response(200, text=_EMPTY_HTML)

    return _wire_httpx(build_adapter("kpmg", "kpmg"), route, _json_broken, mode)


def _accenture(mode: str) -> BaseAdapter:
    # Accenture's own search API: five real US rows, `totalHits`
    # rewritten to 5 so each country query is a whole board; later offsets empty.
    # Every planned country query gets the same rows; the shared `seen` set
    # collapses them, which is the cross-query rule under test.
    page1 = load_fixture("accenture", "page1.json")
    empty = {**page1, "data": []}

    def route(request: httpx.Request) -> httpx.Response:
        form = dict(httpx.QueryParams(request.content.decode()))
        if mode == MODE_REPEAT or form.get("startIndex") == "0":
            return httpx.Response(200, json=page1)
        return httpx.Response(200, json=empty)

    return _wire_httpx(build_adapter("accenture", "accenture"), route, _json_broken, mode)


def _tiktok(mode: str) -> BaseAdapter:
    # TikTok's search API: five real rows (San Jose, Singapore,
    # London, Sydney, Seoul), `data.count` rewritten to 5; later offsets empty.
    # The API refuses a request without its `website-path` header, as live.
    page1 = load_fixture("tiktok", "page1.json")
    empty = {**page1, "data": {"job_post_list": [], "count": page1["data"]["count"]}}

    def route(request: httpx.Request) -> httpx.Response:
        if request.headers.get("website-path") != "tiktok":
            return httpx.Response(400, json={"code": 1, "message": "invalid request"})
        body = json.loads(request.content)
        if mode == MODE_REPEAT or body.get("offset") == 0:
            return httpx.Response(200, json=page1)
        return httpx.Response(200, json=empty)

    return _wire_httpx(build_adapter("tiktok", "tiktok"), route, _json_broken, mode)


def _successfactors(mode: str) -> BaseAdapter:
    # EY's SuccessFactors career site: a real page 1 of 25 rows, its
    # stated total (8551) rewritten to 25; later offsets answer no rows.
    page1 = load_fixture("successfactors", "page1.json")["html"].replace("of <b>8551", "of <b>25")

    def route(request: httpx.Request) -> httpx.Response:
        if mode == MODE_REPEAT or request.url.params.get("startrow") == "0":
            return httpx.Response(200, text=page1)
        return httpx.Response(200, text=_EMPTY_HTML)

    adapter = build_adapter("ey", "successfactors", board_token="careers.ey.com|ey")
    # A "+N more" row would read its posting page; the contract is the listing.
    adapter.place_gate = lambda _job: False
    return _wire_httpx(adapter, route, _json_broken, mode)


def _shopify(mode: str) -> BaseAdapter:
    # Shopify's careers page as it streams its `roles` list, reduced to that
    # list; every mode is the one response, the page being the list.
    page = load_fixture("shopify", "roles.json")["html"]

    def route(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=page)

    return _wire_httpx(build_adapter("shopify", "shopify"), route, _json_broken, mode)


def _avature(mode: str) -> BaseAdapter:
    # Avature: a real EA page 1 whose stated total was rewritten to
    # its 20 cards; later offsets answer an empty page.
    page1 = load_fixture("avature", "page1.json")["html"]

    def route(request: httpx.Request) -> httpx.Response:
        if mode == MODE_REPEAT or request.url.params.get("jobOffset") == "0":
            return httpx.Response(200, text=page1)
        return httpx.Response(200, text=_EMPTY_HTML)

    return _wire_httpx(
        build_adapter("electronic-arts", "avature", board_token="jobs.ea.com|en_US/careers"),
        route, _json_broken, mode,
    )


def _avature_tls(mode: str) -> BaseAdapter:
    # TSMC's real page 1, stated total rewritten to its 10 cards;
    # the walled route, so the harness carries the register's consent.
    page1 = load_fixture("avature_tls", "page1.json")["html"]

    def route(request: httpx.Request) -> httpx.Response:
        if mode == MODE_REPEAT or request.url.params.get("jobOffset") == "0":
            return httpx.Response(200, text=page1)
        return httpx.Response(200, text=_EMPTY_HTML)

    adapter = build_adapter("tsmc", "avature_tls", board_token="careers.tsmc.com|en_US/careers")
    adapter.collection_consent = SOURCE_REVIEWS["avature_tls"].wall_fingerprint
    return _wire_httpx(adapter, route, _json_broken, mode)


def _deel(mode: str) -> BaseAdapter:
    # Deel: the real Klarna sitemap cut to 4 postings, every posting
    # page answering one real Klarna posting. MODE_REPEAT cannot loop — the
    # sitemap is fetched once and names a fixed set of URLs.
    sitemap = load_fixture("deel", "page1.json")["html"]
    posting = (fixture_dir("deel") / "job_5d3636f8.html").read_text()
    # A second real shape: most of this board's postings state a BARE CITY
    # ("Stockholm"), not a country. Serving only the country-qualified page
    # would let a bare-city posting classify into no location group, and be
    # shown to nobody, with every test green.
    bare_city = (fixture_dir("deel") / "job_87bd8299.html").read_text()

    def route(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("sitemap.xml"):
            return httpx.Response(200, text=sitemap)
        if "87bd8299" in request.url.path:
            return httpx.Response(200, text=bare_city)
        return httpx.Response(200, text=posting)

    return _wire_httpx(build_adapter("klarna", "deel", board_token="klarna"), route, _json_broken, mode)


def _radancy(mode: str) -> BaseAdapter:
    # Radancy TalentBrew: the real Arm sitemap cut to 4 postings,
    # every posting page answering one real Arm posting. MODE_REPEAT cannot
    # loop — the sitemap is fetched once and names a fixed set of URLs.
    sitemap = load_fixture("radancy", "page1.json")["html"]
    posting = (fixture_dir("radancy") / "job_100980904800.html").read_text()

    def route(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("sitemap.xml"):
            return httpx.Response(200, text=sitemap)
        return httpx.Response(200, text=posting)

    return _wire_httpx(
        build_adapter("arm", "radancy", board_token="careers.arm.com"), route, _json_broken, mode,
    )


def _jibe(mode: str) -> BaseAdapter:
    # Jibe: five real GitHub rows whose totalCount was rewritten to
    # make them a whole board; page 1 serves it, later pages an empty list with
    # the same total, as the live route does.
    page1 = load_fixture("jibe", "page1.json")

    def route(request: httpx.Request) -> httpx.Response:
        if mode == MODE_REPEAT or request.url.params.get("page") == "1":
            return httpx.Response(200, json=page1)
        return httpx.Response(200, json={**page1, "jobs": []})

    return _wire_httpx(build_adapter("github", "jibe", board_token="www.github.careers"), route, _json_broken, mode)


def _workable(mode: str) -> BaseAdapter:
    # One GET returns the whole board, so every mode terminates on the first
    # request and MODE_REPEAT cannot loop: there is no page parameter to vary.
    page1 = load_fixture("workable", "page1.json")

    def route(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=page1)

    return _wire_httpx(build_adapter("hugging-face", "workable"), route, _json_broken, mode)


def _meta(mode: str) -> BaseAdapter:
    bundle = load_fixture("meta", "page1.json")
    sitemap_url = "https://www.metacareers.com/jobsearch/sitemap.xml"

    def route(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url == sitemap_url:
            return httpx.Response(200, text=bundle["sitemap"])
        page = bundle["pages"].get(url)
        return httpx.Response(200, text=page) if page else httpx.Response(404, text="")

    def broken_route(request: httpx.Request) -> httpx.Response:
        # Sitemap answers 200 but carries no job_details URLs (schema drift).
        return httpx.Response(200, text="<?xml version=\"1.0\"?><urlset></urlset>")

    adapter = build_adapter("meta", "meta")
    # Fixture replay exercises source behavior under an explicit local allow;
    # it must not disable the process-wide default policy for denial tests.
    adapter.settings = adapter.settings.model_copy(update={"sync_policy_denied_providers": frozenset()})
    counter = RequestCounter()
    handler = _wrap_handler(adapter.name, route, broken_route, mode, counter)
    adapter._session = _CurlSessionStub(handler)
    adapter._limiter = RateLimiter(0.0)
    adapter.contract_requests = counter
    return adapter


#: adapter-registry name -> harness builder. A registry entry missing here (or
#: missing its fixtures directory) fails test_listing_connectors by name.
HARNESSES: dict[str, Callable[[str], BaseAdapter]] = {
    "greenhouse": _greenhouse,
    "lever": _lever,
    "ashby": _ashby,
    "eightfold": _eightfold,
    "apple": _apple,
    "google": _google,
    "amazon": _amazon,
    "workday": _workday,
    "meta": _meta,
    "microsoft": _microsoft,
    "workable": _workable,
    "smartrecruiters": _smartrecruiters,
    "smartrecruiters_api": _smartrecruiters_api,
    "atlassian": _atlassian,
    "oracle": _oracle,
    "kpmg": _kpmg,
    "accenture": _accenture,
    "avature": _avature,
    "jibe": _jibe,
    "radancy": _radancy,
    "deel": _deel,
    "avature_tls": _avature_tls,
    "tiktok": _tiktok,
    "successfactors": _successfactors,
    "shopify": _shopify,
}


def build_harness(adapter_name: str, mode: str) -> BaseAdapter:
    return HARNESSES[adapter_name](mode)


async def run_fetch(adapter: BaseAdapter) -> list:
    """Collect fetch() output, then release the injected transport."""
    try:
        return [job async for job in adapter.fetch()]
    finally:
        client = getattr(adapter, "_client", None)
        if isinstance(client, httpx.AsyncClient):
            await client.aclose()
            adapter._client = None
        session = getattr(adapter, "_session", None)
        if isinstance(session, _CurlSessionStub):
            await session.close()
