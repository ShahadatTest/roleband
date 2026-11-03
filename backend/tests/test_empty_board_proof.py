"""Which families can prove a board empty, and which cannot.

An empty board is a scan with no postings only when the board itself says so:
the response envelope is present and its declared total is 0 or its posting
array is present and empty, on a family whose unknown tenant does NOT answer
that way. Everything else that ends with zero rows is a zero the adapter cannot
explain, and the collector records it as the pathology it may be.

Each family gets its proof and the negative controls that look like it: a body
missing the array, a non-200, an unknown tenant's answer. A proof that also
fired on those would hide a broken source behind "lists no roles".
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from tracker.config import get_settings
from tracker.connectors import build_adapter
from tracker.platform.ratelimit import RateLimiter
from tracker.source_review import SOURCE_REVIEWS

pytestmark = pytest.mark.asyncio

#: A real SmartRecruiters board with no openings, as the site serves it.
SR_NO_OPENINGS = (
    Path(__file__).parent / "fixtures" / "listings" / "smartrecruiters" / "empty_board.html"
).read_text()


@pytest.fixture(autouse=True)
def _no_pacing(monkeypatch):
    monkeypatch.setattr(get_settings(), "scraper_min_delay_seconds", 0)
    monkeypatch.setattr(get_settings(), "scraper_max_retries", 0)


def _adapter(company: str, family: str, token: str, answer):
    """`answer(request) -> httpx.Response`: the whole board, offline."""
    adapter = build_adapter(company, family, board_token=token)
    # A walled family is read here as a consenting user's would be.
    adapter.collection_consent = SOURCE_REVIEWS[family].wall_fingerprint
    adapter._client = httpx.AsyncClient(transport=httpx.MockTransport(answer))
    adapter._limiter = RateLimiter(0)
    return adapter


def _json(body, status: int = 200):
    return lambda _request: httpx.Response(status, json=body)


def _html(body: str, status: int = 200):
    return lambda _request: httpx.Response(status, text=body)


def _turbo(root: object) -> list:
    """`root` as a turbo-stream table: index 0 the root, every value an index,
    an object's keys written `_N` for the string at index N, -7 null."""
    table: list = []

    def put(value: object) -> int:
        if value is None:
            return -7
        at = len(table)
        table.append(None)
        if isinstance(value, dict):
            entry = {}
            for key, item in value.items():
                table.append(key)
                name = f"_{len(table) - 1}"
                entry[name] = put(item)
            table[at] = entry
        elif isinstance(value, list):
            table[at] = [put(item) for item in value]
        else:
            table[at] = value
        return at

    put(root)
    return table


def _shopify_page(rows: list, key: str = "jobPostingsWithJobs") -> str:
    """Shopify's careers page streaming `rows` as its posting list, in the `key` shape."""
    root = {"loaderData": {"($locale)/careers": {key: rows, "atsLocations": []}}}
    stream = json.dumps(json.dumps(_turbo(root)))
    return f"<script>window.__reactRouterContext.streamController.enqueue({stream});</script>"


def _sr_index(pages: int, groups: str = "") -> str:
    return (
        '<html><head><meta property="og:title" content="Careers at Acme"></head>'
        f'<body><div class="js-openings-load" data-groups-pages="{pages}">{groups}</div></body></html>'
    )


async def _read(adapter) -> list:
    async with adapter._client:
        return [job async for job in adapter.fetch()]


def _proven(adapter) -> bool:
    drift = adapter.drift
    return drift.empty_proven and not drift.listing_invalidated and not drift.listing_complete


def _pathology(adapter) -> bool:
    """Not proven; and once the collector settles the zero, invalidated."""
    adapter.drift.settle_listing(scanned=0)
    return not adapter.drift.empty_proven and adapter.drift.listing_invalidated


# --------------------------------------------------------------------------- #
# Families that can prove it
# --------------------------------------------------------------------------- #

PROVEN = [
    ("greenhouse", "acme", {"jobs": [], "meta": {"total": 0}}),
    ("ashby", "acme", {"apiVersion": "1", "jobs": []}),
    # Only the tenant's drafts: the public board lists nothing.
    ("ashby", "acme", {"apiVersion": "1", "jobs": [{"id": "d1", "title": "Draft", "isListed": False}]}),
    ("workable", "acme", {"name": "Acme", "description": "", "jobs": []}),
    ("lever", "acme", []),
    ("jibe", "www.github.careers", {"jobs": [], "totalCount": 0}),
    ("eightfold", "paypal.eightfold.ai|paypal.com|pcsx", {"data": {"count": 0, "positions": []}}),
    ("oracle", "edel.fa.us2.oraclecloud.com|CX_2001",
     {"items": [{"TotalJobsCount": 0, "requisitionList": []}]}),
]


#: Proofs read from a page, not a JSON body.
PROVEN_PAGES = [
    # Shopify streams its list decoded and empty. One company, no tenant.
    ("shopify", "shopify", _shopify_page([])),
    # Only unlisted postings, as Ashby's drafts: the public board lists nothing.
    ("shopify", "shopify", _shopify_page([{"jobPosting": {"id": "d1", "title": "Draft", "isListed": False}}])),
    # The summary shape's list, decoded and empty.
    ("shopify", "shopify", _shopify_page([], key="roles")),
    # A published SmartRecruiters board declaring no group page; an unknown
    # token is not a board index at all (`board_is_published`).
    ("smartrecruiters", "acme", _sr_index(0)),
    # The page a live board with no openings serves: its notice in place of
    # the group list, and no page count at all.
    ("smartrecruiters", "Dailymotion", SR_NO_OPENINGS),
]


@pytest.mark.parametrize(("family", "token", "page"), PROVEN_PAGES, ids=[
    "shopify", "shopify-unlisted-only", "shopify-roles", "smartrecruiters-board", "smartrecruiters-no-openings-notice",
])
async def test_a_page_that_says_it_lists_nothing_is_proven_empty(family, token, page):
    adapter = _adapter(token, family, token, _html(page))
    assert await _read(adapter) == []
    assert _proven(adapter), adapter.drift.alerts
    assert adapter.drift.alerts == []


@pytest.mark.parametrize(("family", "token", "body"), PROVEN, ids=[
    "greenhouse", "ashby", "ashby-drafts-only", "workable", "lever", "jibe", "eightfold", "oracle",
])
async def test_a_board_that_says_it_lists_nothing_is_proven_empty(family, token, body):
    adapter = _adapter("acme", family, token, _json(body))
    assert await _read(adapter) == []
    assert _proven(adapter), adapter.drift.alerts
    # A log line, not an alert: an alert on a zero-row run marks a catalog failed.
    assert adapter.drift.alerts == []


async def test_a_sitemap_naming_no_posting_is_proven_empty():
    empty = '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"></urlset>'
    adapter = _adapter("arm", "radancy", "careers.arm.com", lambda _r: httpx.Response(200, text=empty))
    assert await _read(adapter) == []
    assert _proven(adapter)


# --------------------------------------------------------------------------- #
# What looks like it and is not
# --------------------------------------------------------------------------- #

NOT_PROVEN = [
    ("greenhouse", "acme", _json({"meta": {"total": 0}})),
    ("greenhouse", "acme", _json({"status": 404, "error": "Job not found"}, status=404)),
    # A body that is not an object holds no `jobs` array either.
    ("greenhouse", "acme", _json([])),
    # Counting `jobs.item` would read a body with no `jobs` key as an empty
    # board, and the attention report would take that as positive evidence.
    ("ashby", "acme", _json({"apiVersion": "1"})),
    ("ashby", "acme", _json({"success": False}, status=404)),
    ("workable", "acme", _json({"name": "Acme"})),
    ("lever", "acme", _json({"ok": False, "error": "Document not found"}, status=404)),
    ("lever", "acme", _json({"postings": []})),
    # A total of 0 the page never stated is not one.
    ("jibe", "www.github.careers", _json({"jobs": []})),
    ("eightfold", "paypal.eightfold.ai|paypal.com|pcsx", _json({"data": {"count": 0}})),
    ("eightfold", "paypal.eightfold.ai|paypal.com|pcsx",
     lambda _r: httpx.Response(404, text="<!DOCTYPE html><html></html>")),
    ("oracle", "edel.fa.us2.oraclecloud.com|CX_2001", _json({"items": []})),
    # An unknown company answers exactly this, so the
    # SmartRecruiters API can never tell an empty board from a wrong token.
    ("smartrecruiters_api", "Wise", _json({"offset": 0, "limit": 100, "totalFound": 0, "content": []})),
]


NOT_PROVEN_PAGES = [
    # A stream without the list is a changed page, not an empty board.
    ("shopify", "shopify", _html(_shopify_page([]).replace("jobPostingsWithJobs", "somethingElse"))),
    # Rows the adapter could not read are not an empty board either.
    ("shopify", "shopify", _html(_shopify_page([{"notAPosting": True}]))),
    ("shopify", "shopify", _html(_shopify_page([{"notARole": True}], key="roles"))),
    ("shopify", "shopify", _html("<html>Service unavailable</html>", status=503)),
    # Declares a group page and serves none: postings we never saw.
    ("smartrecruiters", "acme", _html(_sr_index(1))),
    # Not a board index: an unknown token's answer.
    ("smartrecruiters", "acme", _html("<html><title>SmartRecruiters</title></html>")),
    # The notice is the board's word only on a page that answered.
    ("smartrecruiters", "Dailymotion", _html(SR_NO_OPENINGS, status=503)),
    # The notice text without the board's own notice element is not one.
    ("smartrecruiters", "Dailymotion", _html(SR_NO_OPENINGS.replace('id="st-noOpeningsFound"', ""))),
    # SuccessFactors stays a failure on zero rows: no tenant's
    # zero-result search page has been seen, and the adapter reads several
    # hosts and sites, where a wrong site path may answer an empty search. A
    # total of 0 is therefore not yet evidence; a fixture of a real empty
    # page is what would make it one.
    ("successfactors", "careers.ey.com|ey",
     _html('<html><body><span class="paginationLabel">Results 0 - 0 of 0</span></body></html>')),
]


@pytest.mark.parametrize(("family", "token", "answer"), NOT_PROVEN_PAGES, ids=[
    "shopify-no-list", "shopify-unreadable-rows", "shopify-unreadable-roles", "shopify-503", "smartrecruiters-missing-page",
    "smartrecruiters-not-a-board", "smartrecruiters-notice-503", "smartrecruiters-notice-unmarked",
    "successfactors-zero-total",
])
async def test_a_page_whose_zero_is_unexplained_is_never_proof(family, token, answer):
    company = "ey" if family == "successfactors" else token
    adapter = _adapter(company, family, token, answer)
    assert await _read(adapter) == []
    assert _pathology(adapter), adapter.drift.alerts


@pytest.mark.parametrize(("family", "token", "answer"), NOT_PROVEN, ids=[
    "greenhouse-no-array", "greenhouse-404", "greenhouse-not-an-object", "ashby-no-array", "ashby-404",
    "workable-no-array", "lever-404", "lever-not-an-array", "jibe-no-total", "eightfold-no-positions",
    "eightfold-unknown-domain", "oracle-no-result", "smartrecruiters-api-wrong-token-shape",
])
async def test_a_zero_the_board_did_not_explain_is_never_proof(family, token, answer):
    adapter = _adapter("acme", family, token, answer)
    assert await _read(adapter) == []
    assert _pathology(adapter), adapter.drift.alerts


async def test_a_sitemap_of_another_organization_is_not_an_empty_board():
    other = (
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        "<url><loc>https://careers.arm.com/about</loc></url></urlset>"
    )
    adapter = _adapter("arm", "radancy", "careers.arm.com", lambda _r: httpx.Response(200, text=other))
    assert await _read(adapter) == []
    assert _pathology(adapter)


async def test_a_proof_contradicted_by_rows_is_withdrawn():
    """Defensive: an adapter that claimed empty and then listed rows is wrong
    about one of them, so neither can stand as evidence."""
    adapter = build_adapter("acme", "greenhouse", board_token="acme")
    adapter.drift.board_empty("claimed empty")
    adapter.drift.settle_listing(scanned=3)
    assert not adapter.drift.empty_proven
    assert adapter.drift.listing_invalidated
