"""Resolve a pasted careers URL by fetching its page.

`ats_detect.detect_ats` names a board from its URL alone. Three families serve
each tenant from the tenant's own host (Jibe, Radancy TalentBrew, Avature on a
company domain), so their URL carries no marker and only the page can say what
it is. This module is the one place RoleBand fetches a URL a user typed:

1. the page, through `platform.safe_fetch` — public addresses only, every
   redirect re-checked, connections pinned to the vetted address;
2. `ats_detect.detect_page` reads the family from the page's marker; the token
   comes from the URL the page was served at, never from page text;
3. collection policy is asked first (`source_policy.collection_access`): a
   denied or walled source is not probed and the company stays pending;
4. the candidate is VERIFIED on the family's own board route
   (`BoardProbe`, the same declaration `check_catalog_tokens` uses): it must
   answer 200 with a posting count the family can read. A page is
   attacker-influenced, so a marker alone activates nothing, and a board the
   adapter could not claim complete (Deloitte's Avature portal states no total)
   stays pending rather than failing its first scan.

Anything that does not end in a verified board returns None: the caller keeps
the company `pending`, exactly as an unrecognised URL leaves it.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Literal

import httpx

from tracker.ats_detect import DetectedBoard, detect_page
from tracker.config import get_settings
from tracker.connectors import ADAPTER_REGISTRY
from tracker.platform.safe_fetch import BlockedDestination, fetch_public, public_client
from tracker.source_policy import collection_access

logger = logging.getLogger(__name__)

#: The page is read under `safe_fetch`'s 2 MB default: markers sit in its head.
#: A board answer must be read WHOLE to be counted, and a family's own route
#: runs large: a Jibe page of 100 postings can pass 2 MB, and an answer cut
#: mid-JSON reads as no board at all.
PROBE_MAX_BYTES = 16_000_000

__all__ = ["PROBE_MAX_BYTES", "PageReading", "board_answers", "detect_by_page", "read_page", "resolve_pasted_board"]

#: Why a page that names a known family still left its company pending.
PendingReason = Literal["policy_refused", "board_silent"]


@dataclass(frozen=True)
class PageReading:
    """What a careers page said: the verified board, or the family its marker
    named and why that did not become a board. A page naming no family is
    `PageReading(None, None, None)`."""

    board: DetectedBoard | None
    family: str | None
    reason: PendingReason | None


async def detect_by_page(
    url: str, *, slug: str, client: httpx.AsyncClient
) -> DetectedBoard | None:
    """The verified board behind a careers page, or None (`read_page`'s board)."""
    return (await read_page(url, slug=slug, client=client)).board


async def read_page(url: str, *, slug: str, client: httpx.AsyncClient) -> PageReading:
    """The verified board behind a careers page, or the family its marker
    named and why it stayed pending.

    Best effort, and never the reason an add fails: whatever goes wrong — a
    refused destination, a dead site, a page nobody can parse — the company
    stays pending, naming the family only when the page named one.
    """
    try:
        return await _detect(url, slug=slug, client=client)
    except Exception as exc:  # noqa: BLE001 - see docstring
        logger.info("page detection: %s left pending: %s: %s", url, type(exc).__name__, exc)
        return PageReading(None, None, None)


async def _detect(url: str, *, slug: str, client: httpx.AsyncClient) -> PageReading:
    try:
        page = await fetch_public(client, url)
    except (BlockedDestination, httpx.HTTPError) as exc:
        logger.info("page detection: %s not fetched: %s", url, exc)
        return PageReading(None, None, None)
    if page.status != 200:
        return PageReading(None, None, None)
    board = detect_page(page.final_url, page.text)
    if board is None:
        return PageReading(None, None, None)
    if collection_access(board.adapter, company=slug).denied:
        return PageReading(None, board.adapter, "policy_refused")
    if not await board_answers(board, client):
        return PageReading(None, board.adapter, "board_silent")
    return PageReading(board, board.adapter, None)


async def board_answers(board: DetectedBoard, client: httpx.AsyncClient) -> bool:
    """Whether the board answers on its family's own route with a posting count
    the family can read. Shared with `board_relocate`, which verifies a moved
    board the same way before a person may point a company at it."""
    cls = ADAPTER_REGISTRY.get(board.adapter)
    probe = getattr(cls, "board_probe", None)
    if probe is None:
        return False
    if probe.sitemap is not None:
        return (await probe.sitemap(board.board_token).probe(client)).inventory.complete
    body = dict(probe.probe_body) if probe.probe_body is not None else None
    try:
        answer = await fetch_public(
            client, probe.url_for(board.board_token), method=probe.method,
            max_bytes=PROBE_MAX_BYTES,
            json=body if probe.probe_encoding == "json" else None,
            data=body if probe.probe_encoding == "form" else None,
            headers=dict(probe.probe_headers) if probe.probe_headers else None,
        )
    except (BlockedDestination, httpx.HTTPError, ValueError):
        return False
    if answer.status != 200 or answer.truncated:
        return False
    if probe.read_count is not None:
        return probe.read_count(answer.text) is not None
    try:
        payload = json.loads(answer.text)
    except ValueError:
        return False
    return isinstance(payload, (dict, list))


async def resolve_pasted_board(fields: dict) -> dict:
    """Upgrade a `pending` URL company whose page names a verified board.

    `fields` is `company_store.resolve_company`'s answer; anything but a
    pending URL add is returned unchanged.
    """
    if fields.get("status") != "pending" or fields.get("source") != "url" or not fields.get("careers_url"):
        return fields
    async with public_client(user_agent=get_settings().scraper_user_agent) as client:
        reading = await read_page(fields["careers_url"], slug=fields["slug"], client=client)
    board = reading.board
    if board is None:
        # Still pending; the family the page named, if any, and why it waits.
        return {**fields, "detected_family": reading.family, "pending_reason": reading.reason}
    return {
        **fields,
        "adapter": board.adapter,
        "board_token": board.board_token,
        "board_region": board.region.value if board.region else None,
        "status": "active",
    }
