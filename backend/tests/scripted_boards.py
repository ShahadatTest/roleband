"""Scripted Google and Amazon listing boards: the real adapters over a mock
transport that serves recorded-shape pages and records what was asked."""

from __future__ import annotations

import httpx

from tracker.connectors.listing.base import RateLimiter
from tracker.connectors.listing.google import GoogleAdapter
from tracker.source_review import SOURCE_REVIEWS

#: One Google results card, as the board renders it.
CARD = (
    '<li><a aria-label="Learn more about {title}" '
    'href="jobs/results/{req_id}-role">{title}</a></li>'
)


def results_page(*, first: int, last: int, total: int, ids: range) -> str:
    """A Google results page of engineer cards `ids`, with its "Showing" line."""
    cards = "".join(CARD.format(title=f"Engineer {i}", req_id=100000 + i) for i in ids)
    return (
        "<html><body><main><ul>"
        + cards
        + "</ul>"
        + f'<span aria-live="polite">Showing {first} to {last} of {total} rows</span>'
        + "</main></body></html>"
    )


def google_board(pages: dict[str, str], requests: list[str]) -> GoogleAdapter:
    """A consented Google adapter that serves `pages` by page number and
    records each page it asks for in `requests`."""
    def handler(request: httpx.Request) -> httpx.Response:
        page = request.url.params.get("page")
        requests.append(page)
        return httpx.Response(200, text=pages.get(page, "<html><body></body></html>"))

    adapter = GoogleAdapter("google")
    # Walled: a consenting user, so the paging logic is what is tested.
    adapter.collection_consent = SOURCE_REVIEWS["google"].wall_fingerprint
    adapter._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter._limiter = RateLimiter(0.0)
    return adapter


def amazon_board(pages: dict, requests: list) -> object:
    """An Amazon adapter that serves `pages` by offset and records each offset
    it asks for in `requests`; past the last page it serves no jobs."""
    from tracker.connectors.listing.amazon import AmazonAdapter

    def handler(request: httpx.Request) -> httpx.Response:
        offset = request.url.params.get("offset")
        requests.append(offset)
        return httpx.Response(200, json=pages.get(offset, {"hits": pages["0"]["hits"], "jobs": []}))

    adapter = AmazonAdapter("amazon")
    adapter._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter._limiter = RateLimiter(0.0)
    return adapter


def amazon_hit(n: int) -> dict:
    """One Amazon search hit."""
    return {"id_icims": f"a{n}", "title": f"SDE {n}", "job_path": f"/en/jobs/{n}/sde"}
