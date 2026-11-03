"""Find where a company's careers page moved.

A board that answers 404 at its own address is gone, and the company is
usually still hiring somewhere else: it moved to another ATS, or renamed its
board on the same one. A scan alone can only say "Couldn't scan". This module
answers "where did it go?" so the Coverage notice can offer the new page.

Where it looks, in order:

1. **The company's own careers page**, when one is stored. The page is the
   company's word, so a verified board behind it needs no other evidence
   (`board_resolve.detect_by_page`, the pasted-URL path).
2. **The same name on the families keyed by a name**: Ashby, Greenhouse and
   Workable, whose board address is a token like `hex` or `hightouch-inc`.
   Lever is left out because its probe reads one posting (`limit=1`), too
   few to say whose board it is.

A guessed board is somebody's live board, and a wrong-but-live board is the
quiet failure: it would pass every gate a scan has. So a guess
must SHOW it is the same company: its roles must overlap the titles RoleBand
last read at the company (`shared_titles`). A guessed name can be a stale
board of the same name listing a role or two, while the company's real board
lists the roles RoleBand read before the move.

Nothing here writes. It suggests; the person confirms, and the API re-verifies
the board before `company_store.record_board_move` writes the move. Every
fetch goes through `platform.safe_fetch`, the one public-only fetch path.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

import httpx

from tracker.ats_detect import DetectedBoard, detect_ats
from tracker.board_resolve import PROBE_MAX_BYTES, board_answers, detect_by_page
from tracker.connectors import ADAPTER_REGISTRY
from tracker.platform.ratelimit import RateLimiterPool
from tracker.platform.safe_fetch import BlockedDestination, fetch_public
from tracker.source_policy import collection_access

logger = logging.getLogger(__name__)

__all__ = [
    "GUESS_FAMILIES",
    "MovedBoard",
    "board_titles",
    "check_address",
    "find_moved_board",
    "shared_titles",
    "token_guesses",
]

#: Families whose board address is a name-like token and whose probe returns
#: the whole board as JSON, so a guess can be read and compared.
GUESS_FAMILIES: tuple[str, ...] = ("ashby", "greenhouse", "workable")

#: Words a company name carries that its board address often drops:
#: "Hex Technologies" is Ashby `hex`.
_GENERIC_WORDS = frozenset({
    "inc", "llc", "ltd", "co", "corp", "corporation", "company", "technologies", "technology",
    "labs", "hq", "io", "ai", "software", "systems", "careers", "jobs", "group",
})
#: Endings tenants add to a taken name: Hightouch is Ashby `hightouch-inc`.
_SUFFIXES = ("", "-inc", "hq")
#: Board tokens are short ASCII names; anything else is no address to try.
_TOKEN = re.compile(r"[a-z0-9][a-z0-9-]{0,62}")

FoundBy = Literal["page", "name", "address"]


@dataclass(frozen=True)
class MovedBoard:
    """A board that answered, and why RoleBand thinks it is the company's."""

    adapter: str
    board_token: str
    board_region: str | None
    #: Roles the board lists now; None when its family cannot be counted here.
    roles: int | None
    #: Of those, titles RoleBand last read at the company.
    shared: int
    #: `page`: the company's careers page names it. `name`: guessed from the
    #: company's name, and its roles overlap. `address`: the person gave it.
    found_by: FoundBy


def token_guesses(slug: str, display: str, board_token: str | None) -> list[str]:
    """Board addresses a company of this name plausibly uses, most likely first."""
    bases: list[str] = []

    def add(value: str) -> None:
        value = value.strip().casefold()
        if value and value not in bases and _TOKEN.fullmatch(value):
            bases.append(value)

    words = re.findall(r"[a-z0-9]+", display.casefold())
    core = [word for word in words if word not in _GENERIC_WORDS]
    add(board_token or "")
    add(slug)
    add("".join(words))
    add("-".join(words))
    if core and core != words:
        add("".join(core))
        add("-".join(core))
    guesses: list[str] = []
    for base in bases:
        for suffix in _SUFFIXES:
            guess = f"{base}{suffix}"
            if guess not in guesses and _TOKEN.fullmatch(guess):
                guesses.append(guess)
    return guesses


def board_titles(payload: object) -> list[str] | None:
    """The role titles a family's board answer lists, or None if it lists none
    RoleBand can read. Ashby, Greenhouse and Workable answer `{"jobs": [...]}`
    with a `title` each; Lever a bare array with `text`."""
    rows = payload if isinstance(payload, list) else (
        payload.get("jobs") if isinstance(payload, dict) else None
    )
    if not isinstance(rows, list):
        return None
    titles = [str(row.get("title") or row.get("text") or "") for row in rows if isinstance(row, dict)]
    return [title for title in titles if title.strip()]


def _norm(title: str) -> str:
    return " ".join(title.casefold().split())


def shared_titles(known: Iterable[str], found: Iterable[str]) -> int:
    """How many of a board's titles RoleBand last read at the company, or 0 when
    that is too few to say it is the company's board.

    At least half the smaller set must match, and at least two titles unless
    RoleBand only ever saw one: one common title ("Software Engineer") on a
    one-role board is a coincidence, not an identity.
    """
    mine = {_norm(title) for title in known if title.strip()}
    theirs = {_norm(title) for title in found if title.strip()}
    if not mine or not theirs:
        return 0
    shared = len(mine & theirs)
    if shared < max(1, math.ceil(min(len(mine), len(theirs)) / 2)):
        return 0
    if shared < 2 and len(mine) > 1:
        return 0
    return shared


async def _read_board(board: DetectedBoard, client: httpx.AsyncClient) -> list[str] | None:
    """The titles one board lists, read on its family's own probe route."""
    probe = getattr(ADAPTER_REGISTRY.get(board.adapter), "board_probe", None)
    if probe is None or probe.method != "GET" or probe.read_count is not None or probe.sitemap is not None:
        return None
    region = board.region.value if board.region else None
    try:
        answer = await fetch_public(client, probe.url_for(board.board_token, region), max_bytes=PROBE_MAX_BYTES)
    except (BlockedDestination, httpx.HTTPError, ValueError):
        return None
    if answer.status != 200 or answer.truncated:
        return None
    try:
        return board_titles(json.loads(answer.text))
    except ValueError:
        return None


def _probe_delay(family: str) -> float:
    """Seconds between two guesses on one family, as its scans are paced."""
    return ADAPTER_REGISTRY[family].pacing_delay()


def _allowed(adapter: str, slug: str) -> bool:
    return not collection_access(adapter, company=slug).denied


async def _from_page(
    url: str, *, slug: str, current: tuple[str | None, str | None], known: list[str],
    client: httpx.AsyncClient, found_by: FoundBy,
) -> MovedBoard | None:
    """The verified board a URL names (its address or its page), unless it is
    the board the company already reads."""
    board = detect_ats(url)
    if board is not None and not (_allowed(board.adapter, slug) and await board_answers(board, client)):
        board = None
    if board is None:
        board = await detect_by_page(url, slug=slug, client=client)
    if board is None or (board.adapter, board.board_token) == current:
        return None
    titles = await _read_board(board, client)
    return MovedBoard(
        adapter=board.adapter,
        board_token=board.board_token,
        board_region=board.region.value if board.region else None,
        roles=len(titles) if titles is not None else None,
        shared=shared_titles(known, titles or []),
        found_by=found_by,
    )


async def check_address(
    url: str, *, slug: str, adapter: str | None, board_token: str | None,
    known: list[str], client: httpx.AsyncClient,
) -> MovedBoard | None:
    """The board behind an address the person gave, verified, or None.

    The person's word is the identity here, as when they add a company by its
    careers page: no title overlap is required, only a board that
    answers and that policy lets RoleBand read.
    """
    return await _from_page(
        url, slug=slug, current=(adapter, board_token), known=known, client=client, found_by="address",
    )


async def find_moved_board(
    *,
    slug: str,
    display: str,
    adapter: str | None,
    board_token: str | None,
    careers_url: str | None,
    known: list[str],
    client: httpx.AsyncClient,
) -> MovedBoard | None:
    """Where the company's careers page went, or None if RoleBand cannot tell.

    `known` is every title RoleBand last read at the company; with none, a
    guessed board cannot show it is the company's, so only the company's own
    page can answer.
    """
    current = (adapter, board_token)
    if careers_url:
        found = await _from_page(
            careers_url, slug=slug, current=current, known=known, client=client, found_by="page",
        )
        if found is not None:
            return found
    if not known:
        return None

    lanes = {
        family: [
            DetectedBoard(family, token, None)
            for token in token_guesses(slug, display, board_token)
            if (family, token) != current
        ]
        for family in GUESS_FAMILIES
        if family in ADAPTER_REGISTRY and _allowed(family, slug)
    }
    guesses = [board for boards in lanes.values() for board in boards]
    # One lane per family, side by side: within a lane the guesses go one at a
    # time on the family's own pacer, the one a scan of that family waits on,
    # so a search never sends a provider a burst while it is being paced.
    pacers = RateLimiterPool()

    async def lane(family: str, boards: list[DetectedBoard]) -> list[tuple[DetectedBoard, list[str] | None]]:
        pacer = pacers.get(family, _probe_delay(family))
        read = []
        for board in boards:
            await pacer.wait()
            read.append((board, await _read_board(board, client)))
        return read

    best: MovedBoard | None = None
    answered = await asyncio.gather(*(lane(family, boards) for family, boards in lanes.items()))
    for board, titles in (pair for lane_read in answered for pair in lane_read):
        if not titles:
            continue
        shared = shared_titles(known, titles)
        if not shared:
            continue
        candidate = MovedBoard(board.adapter, board.board_token, None, len(titles), shared, "name")
        if best is None or (candidate.shared, candidate.roles or 0) > (best.shared, best.roles or 0):
            best = candidate
    if best is None:
        logger.info("board relocation: nothing found for %s over %d guesses", slug, len(guesses))
    return best
