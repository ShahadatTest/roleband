"""Board-token discovery from Common Crawl.

The script's live half reads a public index and is run by hand; what is tested
here is the judgment around it. Two failures matter:

* **a token that is not a board** — a vendor file, another host's record from a
  straddling index block, a name that only resembles a company. Each would put
  a guess in front of a curator dressed as a finding.
* **a partial read reported as whole.** The index can answer 200 with half a
  page; a reader that trusts the status returns a candidate list
  missing everything after `f` and exits 0.
"""

from __future__ import annotations

import json
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from scripts.check_catalog_tokens import LIVE
from scripts.discover_board_tokens import (
    COLLINFO_URL,
    EXCLUDED_BOARDS,
    IndexReader,
    Snapshot,
    build_directory,
    classify,
    discover,
    known_boards,
    parse_page,
    tally,
    token_of,
)
from tracker.company_discovery import DiscoveryCompany

# --- reading a captured URL -------------------------------------------------


@pytest.mark.parametrize(
    ("url", "host", "expected"),
    [
        ("https://job-boards.greenhouse.io/stripe/jobs/123", "job-boards.greenhouse.io",
         ("greenhouse", "stripe", None)),
        ("https://boards.greenhouse.io/embed/job_board?for=acme", "boards.greenhouse.io",
         ("greenhouse", "acme", None)),
        ("https://jobs.ashbyhq.com/mistral.ai/5f2c", "jobs.ashbyhq.com",
         ("ashby", "mistral.ai", None)),
        ("https://jobs.eu.lever.co/spotify/abc", "jobs.eu.lever.co", ("lever", "spotify", "eu")),
        ("https://jobs.lever.co/Arcade/1c84/apply?utm_source=x", "jobs.lever.co",
         ("lever", "Arcade", "global")),
    ],
)
def test_a_board_url_yields_its_family_token_and_region(url, host, expected):
    assert token_of(url, host) == expected


@pytest.mark.parametrize(
    ("url", "host"),
    [
        # A vendor file on the host, which Ashby's dotted-name pattern admits.
        ("http://jobs.ashbyhq.com/robots.txt", "jobs.ashbyhq.com"),
        ("https://jobs.ashbyhq.com/sitemap.xml", "jobs.ashbyhq.com"),
        # Wrapper segments are never tenants.
        ("https://boards.greenhouse.io/embed/job_app?token=1", "boards.greenhouse.io"),
        ("https://job-boards.greenhouse.io/v1/boards", "job-boards.greenhouse.io"),
        # A record from the neighbouring block of a straddling index page: on
        # its own host it is a real board, but not the host this query read.
        ("https://jobs.lever.co/acme/1", "jobs.ashbyhq.com"),
        ("https://evil-boards.greenhouse.io/acme", "boards.greenhouse.io"),
        ("https://boards.greenhouse.io.attacker.example/acme", "boards.greenhouse.io"),
        # A posting deep link names the posting, not the account.
        ("https://apply.workable.com/j/ABC123", "apply.workable.com"),
        ("not a url", "jobs.ashbyhq.com"),
    ],
)
def test_what_is_not_a_board_on_the_queried_host_yields_nothing(url, host):
    assert token_of(url, host) is None


def test_one_board_seen_under_two_hosts_and_two_spellings_is_one_candidate():
    boards: dict = {}
    tally([{"url": "https://boards.greenhouse.io/Stripe", "timestamp": "20260801000000"}],
          "boards.greenhouse.io", "CC-A", boards)
    tally([{"url": "https://job-boards.greenhouse.io/stripe/jobs/1", "timestamp": "20260910000000"},
           {"url": "https://job-boards.greenhouse.io/stripe/jobs/2", "timestamp": "20260905000000"}],
          "job-boards.greenhouse.io", "CC-B", boards)
    (candidate,) = boards.values()
    assert candidate.token == "stripe"  # the spelling seen most often
    assert candidate.captures == 3
    assert candidate.snapshots == {"CC-A", "CC-B"}
    assert candidate.last_seen == "20260910000000"


def test_the_same_name_on_two_lever_deployments_is_two_boards():
    boards: dict = {}
    tally([{"url": "https://jobs.lever.co/acme"}], "jobs.lever.co", "s", boards)
    tally([{"url": "https://jobs.eu.lever.co/acme"}], "jobs.eu.lever.co", "s", boards)
    assert sorted(c.region for c in boards.values()) == ["eu", "global"]


# --- what a curator is shown ------------------------------------------------

_COMPANIES = {
    "citadel": DiscoveryCompany("citadel", "Citadel", "https://example.test"),
    "citadel-securities": DiscoveryCompany(
        "citadel-securities", "Citadel Securities", "https://example.test"),
    "figure": DiscoveryCompany("figure", "Figure", "https://example.test", aliases=("Figure AI",)),
    "stripe": DiscoveryCompany("stripe", "Stripe", "https://example.test"),
    "tsmc": DiscoveryCompany("tsmc", "TSMC", "https://example.test"),
    "anduril": DiscoveryCompany("anduril", "Anduril", "https://example.test"),
    "ey": DiscoveryCompany("ey", "EY", "https://example.test"),
}
_STATES = {"citadel": "planned", "citadel-securities": "planned", "figure": "planned",
           "stripe": "ready", "tsmc": "parked", "anduril": "planned", "ey": "planned"}


def _classify(*urls_by_host: tuple[str, str], known: set | None = None):
    boards: dict = {}
    for host, url in urls_by_host:
        tally([{"url": url}], host, "s", boards)
    return classify(boards.values(), _COMPANIES, known or set(), _STATES.__getitem__)


def _companies(rows: list[dict]) -> set[tuple[str, str]]:
    return {(row["company"], row["token"]) for row in rows}


def test_a_token_that_is_a_planned_companys_name_is_matched_to_it_alone():
    found = _classify(("boards.greenhouse.io", "https://boards.greenhouse.io/citadel"))
    assert _companies(found.matched) == {("citadel", "citadel")}
    assert found.possible == [] and found.unmatched == []


@pytest.mark.parametrize(
    ("token", "companies"),
    [
        # The case the tier exists for, measured: Anduril's Greenhouse board.
        ("andurilindustries", {"anduril"}),
        # ...and the case it cannot tell from it: Figure Lending is not Figure.
        ("figurelending", {"figure"}),
        ("citadelsecurities-careers", {"citadel", "citadel-securities"}),
    ],
)
def test_a_token_that_starts_with_a_name_is_possible_never_matched(token, companies):
    found = _classify(("jobs.ashbyhq.com", f"https://jobs.ashbyhq.com/{token}"))
    assert found.matched == []
    assert _companies(found.possible) == {(slug, token) for slug in companies}
    assert found.unmatched == []


@pytest.mark.parametrize(
    "token",
    [
        "eyewear",  # `ey` is too short a name to be a prefix of anything
        "thecitadelgroup",  # a name inside a token is not a name leading it
        "tsmc",  # a parked company: its hold is policy, not a missing token
        "tsmcarizona",
        "stripe",  # ready: we hold a token already, this is not the gap
        "brandnew",
    ],
)
def test_a_token_naming_no_planned_company_is_unmatched(token):
    found = _classify(("jobs.ashbyhq.com", f"https://jobs.ashbyhq.com/{token}"))
    assert found.matched == [] and found.possible == []
    assert [row["token"] for row in found.unmatched] == [token]


def test_a_curated_alias_matches_and_so_does_a_legal_form():
    found = _classify(("jobs.ashbyhq.com", "https://jobs.ashbyhq.com/FigureAI"),
                      ("jobs.lever.co", "https://jobs.lever.co/citadel-securities-llc"))
    assert _companies(found.matched) == {
        ("figure", "FigureAI"), ("citadel-securities", "citadel-securities-llc")}
    # An exact match is not ALSO offered as a possible one for a shorter name.
    assert found.possible == []


def test_a_board_we_already_hold_is_never_offered_whatever_its_case():
    found = _classify(
        ("boards.greenhouse.io", "https://boards.greenhouse.io/Citadel"),
        ("boards.greenhouse.io", "https://boards.greenhouse.io/AndurilIndustries"),
        ("jobs.ashbyhq.com", "https://jobs.ashbyhq.com/brandnew"),
        known={("greenhouse", "citadel"), ("greenhouse", "andurilindustries")},
    )
    assert found.matched == [] and found.possible == []
    assert [row["token"] for row in found.unmatched] == ["brandnew"]


def test_known_boards_include_built_ins_by_their_effective_token():
    known = known_boards()
    # `anthropic` stores no token; its adapter resolves the slug.
    assert ("greenhouse", "anthropic") in known
    assert ("greenhouse", "stripe") in known


# --- reading the index ------------------------------------------------------

_PAGE = "".join(json.dumps({"url": f"https://jobs.ashbyhq.com/{name}", "timestamp": "2026"}) + "\n"
                for name in ("alpha", "bravo", "zulu"))


@pytest.mark.parametrize(
    "body",
    [
        _PAGE[: len(_PAGE) // 2],  # cut mid-record
        _PAGE.rstrip("\n"),  # cut before the final newline
        "",  # a 200 with nothing in it
        "\n",  # ...or with nothing but the line ending
        "<html><body>504 Gateway Time-out</body></html>\n",
        '{"message": "No Captures found"}\n',  # a JSON line that is not a record
    ],
)
def test_a_body_that_is_not_a_whole_page_is_rejected(body):
    assert parse_page(body) is None


def test_a_whole_page_is_every_record():
    assert [row["url"].rsplit("/", 1)[1] for row in parse_page(_PAGE) or []] == [
        "alpha", "bravo", "zulu"]


def _index(pages: dict[int, list[httpx.Response]], count: httpx.Response | None = None):
    """A CDX endpoint whose page N answers `pages[N]` in turn, then its last."""
    seen: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        query = parse_qs(urlparse(str(request.url)).query)
        if "showNumPages" in query:
            return count or httpx.Response(200, json={"pages": len(pages)})
        page = int(query["page"][0])
        seen.append(page)
        answers = pages[page]
        return answers.pop(0) if len(answers) > 1 else answers[0]

    return handler, seen


async def _read(handler, retries: int = 2) -> tuple[list[dict], list[dict]]:
    lost: list[dict] = []
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        reader = IndexReader(client, delay=0, retries=retries)
        rows = await reader.records(Snapshot("CC-X", "https://index.test/CC-X-index"),
                                    "jobs.ashbyhq.com", lost)
    return rows, lost


@pytest.mark.asyncio
async def test_a_half_page_is_read_again_until_it_is_whole():
    handler, seen = _index({0: [httpx.Response(200, text=_PAGE[:40]),
                                httpx.Response(200, text=_PAGE)]})
    rows, lost = await _read(handler)
    assert len(rows) == 3 and lost == []
    assert seen == [0, 0]


@pytest.mark.asyncio
async def test_a_page_that_never_arrives_whole_is_recorded_lost_not_empty():
    handler, _ = _index({0: [httpx.Response(200, text=_PAGE)],
                         1: [httpx.Response(200, text=_PAGE[:40])]})
    rows, lost = await _read(handler)
    assert len(rows) == 3  # what WAS read is kept
    assert lost == [{"snapshot": "CC-X", "host": "jobs.ashbyhq.com", "page": 1}]


@pytest.mark.asyncio
async def test_an_overloaded_index_is_retried_then_recorded_lost():
    handler, seen = _index({0: [httpx.Response(503)]})
    rows, lost = await _read(handler, retries=2)
    assert rows == [] and len(lost) == 1
    assert seen == [0, 0, 0]


@pytest.mark.asyncio
async def test_a_host_with_no_captures_is_complete_and_empty():
    handler, seen = _index({}, count=httpx.Response(404, json={"message": "No Captures found"}))
    rows, lost = await _read(handler)
    assert rows == [] and lost == [] and seen == []


@pytest.mark.asyncio
async def test_an_unreadable_page_count_is_lost_not_zero_pages():
    handler, _ = _index({}, count=httpx.Response(200, text="<html>oops</html>"))
    rows, lost = await _read(handler)
    assert rows == [] and lost == [{"snapshot": "CC-X", "host": "jobs.ashbyhq.com", "page": None}]


@pytest.mark.asyncio
async def test_discovery_reads_every_page_of_the_latest_snapshots_only():
    collections = [{"id": f"CC-{n}", "cdx-api": f"https://index.test/CC-{n}-index"}
                   for n in (3, 2, 1)]
    requested: list[tuple[str, int]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == COLLINFO_URL:
            return httpx.Response(200, json=collections)
        query = parse_qs(request.url.query.decode())
        snapshot = request.url.path.split("/")[1].removesuffix("-index")
        if "showNumPages" in query:
            return httpx.Response(200, json={"pages": 2})
        page = int(query["page"][0])
        requested.append((snapshot, page))
        name = f"{snapshot.lower()}-p{page}"
        return httpx.Response(200, text=json.dumps({"url": f"https://jobs.ashbyhq.com/{name}",
                                                    "timestamp": "2026"}) + "\n")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        candidates, snapshots, lost = await discover(client, ["jobs.ashbyhq.com"], 2,
                                                     delay=0, retries=0)
    assert [s.id for s in snapshots] == ["CC-3", "CC-2"]
    assert sorted(requested) == [("CC-2", 0), ("CC-2", 1), ("CC-3", 0), ("CC-3", 1)]
    assert sorted(c.token for c in candidates) == ["cc-2-p0", "cc-2-p1", "cc-3-p0", "cc-3-p1"]
    assert lost == []


# --- the directory: reviewed exclusions ---------------------------


def _candidate(token: str, captures: int) -> dict:
    return {"adapter": "greenhouse", "token": token, "region": None, "captures": captures}


def _live(name: str | None) -> dict:
    return {"state": LIVE, "count": 3, **({"declared": name} if name else {})}


def test_a_reviewed_board_that_is_not_a_company_never_takes_a_row_or_a_slug():
    """Two referral boards both name themselves "Referrals Only". Excluded,
    neither is a row, and neither holds the slug the name would make."""
    rows = [_candidate("thoughtworksreferral", 90), _candidate("MonzoReferrals", 80),
            _candidate("referralsonly", 10)]
    results = [_live("Referrals Only"), _live("Referrals Only"), _live("Referrals Only")]

    kept, held = build_directory(rows, results, set(), companies={})

    assert [(r["slug"], r["board_token"]) for r in kept] == [("referrals-only", "referralsonly")]
    assert held["excluded"] == 2


def test_a_board_of_the_same_name_not_reviewed_is_still_a_row():
    """The control: the exclusion is the reviewed address, never the name."""
    kept, held = build_directory(
        [_candidate("acmereferral", 90)], [_live("Referrals Only")], set(), companies={})
    assert [r["slug"] for r in kept] == ["referrals-only"] and not held


def test_every_exclusion_states_its_reason_and_the_built_directory_holds_none():
    from tracker.company_directory import directory

    for (adapter, token), reason in EXCLUDED_BOARDS.items():
        assert token == token.casefold(), (adapter, token)
        assert len(reason.split()) >= 5, (adapter, token)
    present = {(r.adapter, r.board_token.casefold()) for r in directory().values()}
    assert not present & set(EXCLUDED_BOARDS)


def test_a_company_whose_name_looks_like_a_placeholder_is_not_excluded():
    """The control: "Demo S.A." (Workable `demo-s-dot-a`) reads like a demo
    account and is a pharmaceutical company with public roles. A name is never the reason; a reviewed board is."""
    from tracker.company_directory import directory

    assert ("workable", "demo-s-dot-a") not in EXCLUDED_BOARDS
    assert any(r.board_token == "demo-s-dot-a" for r in directory().values())

