"""Where a company's careers page went.

A company can leave one ATS for another or rename its board, and the old
address then answers 404. The finder guesses
the new board from the company's name, and a guess counts only when its roles
overlap what RoleBand last read there: a wrong-but-live board is the quiet
failure. Every network answer is a `MockTransport`; nothing leaves the test.
"""

from __future__ import annotations

import asyncio
import time

import httpx
import pytest

from tracker import board_relocate
from tracker.board_relocate import (
    check_address,
    find_moved_board,
    shared_titles,
    token_guesses,
)
from tracker.config import get_settings

ASHBY = "https://api.ashbyhq.com/posting-api/job-board/"
GREENHOUSE = "https://boards-api.greenhouse.io/v1/boards/"

#: Stored titles distinguish the matching board from a namesake.
HIGHTOUCH_SEEN = [
    "Solutions Engineering Manager", "Product Marketing Manager, Competitive Intelligence",
    "Senior Technical Recruiter", "Software Engineer, Distributed Systems",
    "Full Stack Product Engineer", "Backend Engineer, Platform",
]


def _jobs(*titles: str) -> httpx.Response:
    return httpx.Response(200, json={"apiVersion": "1", "jobs": [{"id": t, "title": t} for t in titles]})


def _client(routes: dict[str, httpx.Response], seen: list[str]) -> httpx.AsyncClient:
    def handle(request: httpx.Request) -> httpx.Response:
        url = str(request.url).split("?")[0]
        seen.append(url)
        return routes.get(url, httpx.Response(404, json={"error": "not found"}))

    return httpx.AsyncClient(transport=httpx.MockTransport(handle))


@pytest.fixture(autouse=True)
def unpaced(monkeypatch):
    """The finder paces each family as its scans are; these cases are about
    what it finds, so they skip the wait. The pacing has its own case below."""
    monkeypatch.setattr(board_relocate, "_probe_delay", lambda family: 0.0, raising=False)


# --- pure ------------------------------------------------------------------- #


def test_guesses_reach_the_addresses_companies_moved_to():
    assert "hex" in token_guesses("hex-technologies", "Hex Technologies", "hextechnologies")
    hightouch = token_guesses("hightouch", "Hightouch", "hightouch")
    assert hightouch[0] == "hightouch" and "hightouch-inc" in hightouch


def test_guesses_are_only_ever_board_shaped_names():
    for guess in token_guesses("acme", "Acme & Sons (EU) Ltd.", None):
        assert guess == guess.casefold() and " " not in guess and "&" not in guess


@pytest.mark.parametrize(("known", "found", "shared"), [
    # Hex on Ashby: every role RoleBand read on Greenhouse.
    (["A", "B", "C"], ["a", "b", "c", "D"], 3),
    # A namesake board shares only one stored title, below the overlap threshold.
    (HIGHTOUCH_SEEN, ["Backend Engineer, Platform"], 0),
    # Under half of the smaller side is someone else's board.
    (["A", "B", "C", "D", "E", "F"], ["A", "B", "X", "Y", "Z", "W"], 0),
    # A one-role company that moved its one role.
    (["Founding Engineer"], ["founding  engineer"], 1),
    ([], ["A"], 0),
])
def test_a_board_is_the_company_s_only_when_its_roles_overlap(known, found, shared):
    assert shared_titles(known, found) == shared


# --- find_moved_board ------------------------------------------------------- #


@pytest.mark.asyncio
async def test_the_moved_board_is_the_one_listing_the_roles_roleband_saw():
    seen: list[str] = []
    routes = {
        # The decoy: live, Hightouch-named, one role in common.
        f"{ASHBY}hightouch": _jobs("Backend Engineer, Platform"),
        f"{ASHBY}hightouch-inc": _jobs(*HIGHTOUCH_SEEN, "Account Executive"),
    }
    async with _client(routes, seen) as client:
        found = await find_moved_board(
            slug="hightouch", display="Hightouch", adapter="greenhouse", board_token="hightouch",
            careers_url=None, known=HIGHTOUCH_SEEN, client=client,
        )

    assert found is not None
    assert (found.adapter, found.board_token, found.found_by) == ("ashby", "hightouch-inc", "name")
    assert (found.roles, found.shared) == (7, 6)
    assert f"{GREENHOUSE}hightouch/jobs" not in seen, "the board that is gone is not asked again"


@pytest.mark.asyncio
async def test_a_live_board_of_the_same_name_with_other_roles_is_not_suggested():
    seen: list[str] = []
    routes = {f"{ASHBY}hightouch": _jobs("Barista", "Shift Lead", "Store Manager")}
    async with _client(routes, seen) as client:
        found = await find_moved_board(
            slug="hightouch", display="Hightouch", adapter="greenhouse", board_token="hightouch",
            careers_url=None, known=HIGHTOUCH_SEEN, client=client,
        )
    assert found is None
    assert f"{ASHBY}hightouch" in seen, "it was asked, and refused on the evidence"


@pytest.mark.asyncio
async def test_with_nothing_read_before_no_guess_is_asked_at_all():
    """No titles means no way to tell the company's board from a namesake's."""
    seen: list[str] = []
    async with _client({f"{ASHBY}hightouch-inc": _jobs("Anything")}, seen) as client:
        found = await find_moved_board(
            slug="hightouch", display="Hightouch", adapter="greenhouse", board_token="hightouch",
            careers_url=None, known=[], client=client,
        )
    assert found is None and seen == []


@pytest.mark.asyncio
async def test_a_provider_the_operator_denied_is_never_asked(monkeypatch):
    monkeypatch.setattr(get_settings(), "sync_policy_denied_providers", frozenset({"ashby"}))
    seen: list[str] = []
    async with _client({f"{ASHBY}hightouch-inc": _jobs(*HIGHTOUCH_SEEN)}, seen) as client:
        found = await find_moved_board(
            slug="hightouch", display="Hightouch", adapter="greenhouse", board_token="hightouch",
            careers_url=None, known=HIGHTOUCH_SEEN, client=client,
        )
    assert found is None
    assert not any(url.startswith(ASHBY) for url in seen)


@pytest.mark.asyncio
async def test_the_company_s_own_page_needs_no_overlap():
    """A stored careers page is the company's word: its board is suggested even
    with no titles to compare."""
    seen: list[str] = []
    async with _client({f"{ASHBY}hex": _jobs("Staff Engineer")}, seen) as client:
        found = await find_moved_board(
            slug="hex-technologies", display="Hex Technologies", adapter="greenhouse",
            board_token="hextechnologies", careers_url="https://jobs.ashbyhq.com/hex",
            known=[], client=client,
        )
    assert found is not None
    assert (found.adapter, found.board_token, found.found_by, found.roles) == ("ashby", "hex", "page", 1)


@pytest.mark.asyncio
async def test_guesses_reach_each_provider_one_at_a_time_on_its_pace(monkeypatch):
    """A search for a gone board sends each provider its guesses one by one, at
    the pace its scans keep, and the providers side by side: four at once to
    one provider is the burst that draws a 429, which reads as "no board"."""
    pace = 0.05
    monkeypatch.setattr(board_relocate, "_probe_delay", lambda family: pace)
    starts: dict[str, list[float]] = {}
    in_flight: dict[str, int] = {}
    most: dict[str, int] = {}

    async def handle(request: httpx.Request) -> httpx.Response:
        host = request.url.host
        starts.setdefault(host, []).append(time.monotonic())
        in_flight[host] = in_flight.get(host, 0) + 1
        most[host] = max(most.get(host, 0), in_flight[host])
        await asyncio.sleep(0.01)
        in_flight[host] -= 1
        return httpx.Response(404, json={"error": "not found"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        found = await find_moved_board(
            slug="hightouch", display="Hightouch", adapter="greenhouse", board_token="hightouch",
            careers_url=None, known=HIGHTOUCH_SEEN, client=client,
        )

    assert found is None
    assert len(starts) >= 2 and all(len(times) >= 2 for times in starts.values())
    assert set(most.values()) == {1}, f"a provider was asked twice at once: {most}"
    for host, times in starts.items():
        gaps = [later - earlier for earlier, later in zip(times, times[1:], strict=False)]
        # These are send times, not the pacer's slots: one send dispatched late on a
        # loaded runner shortens the gap after it. Unpaced sends land 0.01 s apart.
        assert min(gaps) >= pace * 0.5, (host, gaps)
    first = sorted(times[0] for times in starts.values())
    assert first[-1] - first[0] < pace, "the providers are read side by side, not one after another"


# --- check_address ---------------------------------------------------------- #


@pytest.mark.asyncio
async def test_an_address_the_person_gives_is_verified_and_counted():
    """Amigo renamed its board to `concurrence`; no name guess reaches that."""
    seen: list[str] = []
    routes = {f"{ASHBY}concurrence": _jobs("Head of Engineering [NYC or SF]", "Sales Engineer [NYC]")}
    async with _client(routes, seen) as client:
        found = await check_address(
            "https://jobs.ashbyhq.com/concurrence", slug="amigo", adapter="ashby", board_token="amigo",
            known=["Head of Engineering [NYC or SF]"], client=client,
        )
        same = await check_address(
            "https://jobs.ashbyhq.com/amigo", slug="amigo", adapter="ashby", board_token="amigo",
            known=[], client=client,
        )
        dead = await check_address(
            "https://jobs.ashbyhq.com/nobody-here", slug="amigo", adapter="ashby", board_token="amigo",
            known=[], client=client,
        )
    assert found is not None
    assert (found.board_token, found.found_by, found.roles, found.shared) == ("concurrence", "address", 2, 1)
    assert same is None, "the address it already reads is no move"
    assert dead is None, "an address that does not answer is never suggested"
