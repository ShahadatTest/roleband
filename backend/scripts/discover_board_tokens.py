"""Board tokens Common Crawl has seen, as catalog candidates.

A catalog row needs a board token, and a one-off lookup per company does not
scale. This script reads Common Crawl's public URL index for the
hosts where a multi-tenant family serves its boards, slices the token out of
every captured URL, and hands curators three lists:

* **matched** — a token whose name IS a company we recommend but cannot collect
  yet (`connector_state == "planned"`). The actionable list.
* **possible** — a token that STARTS with such a company's name
  (`andurilindustries`). As often somebody else (`uberfreight`); a person
  decides, helped by the name the board declares under `--verify`.
* **unmatched** — every other token not already catalogued, by how often it was
  captured. The inventory new catalog entries are chosen from.

Keyless and offline in the sense that matters: no employer site and no ATS is
touched unless `--verify` is passed, and then only through
`check_catalog_tokens.check_probe`, which consults collection policy first.

**A token here is a claim, not a board.** Common Crawl records what somebody
LINKED, including boards that closed years ago, test tenants and typos. Nothing
in this output may enter `CATALOG` until `check_catalog_tokens` (or `--verify`,
the same probe) has found the board live AND, where the family states its name,
confirmed it belongs to the company. `matched` is name equality only
(`identity_matches`, legal forms stripped): `figure` is not Figure AI, and the
list is allowed to be short for exactly that reason.

**The URL is read by `ats_detect.detect_ats`, never restated here.** It is the
same parser a pasted careers URL goes through, so the `v1` API segment, the
`embed/job_board?for=` form, Lever's regional hosts and Ashby's dotted names are
decided once. Records outside the queried host are dropped: a CDX page is a set
of index BLOCKS, and a block straddling the prefix carries its neighbours.

**An unread page is not an empty page.** The index answers 404 for a host with
no captures (a real, complete answer) and 502/503 under load (no answer at all).
A page that still fails after its retries is recorded under `lost` and the run
exits 3, so a short candidate list is never mistaken for a complete one.

    0  every page of every snapshot was read
    3  INCOMPLETE — at least one page could not be read; the lists are partial

Usage (from `backend/`):

    .venv/bin/python -m scripts.discover_board_tokens
    .venv/bin/python -m scripts.discover_board_tokens --snapshots 1 --host jobs.ashbyhq.com
    .venv/bin/python -m scripts.discover_board_tokens --verify --out /tmp/tokens.json
    .venv/bin/python -m scripts.discover_board_tokens --from /tmp/tokens.json --directory

`--directory` probes every candidate that is not already ours and writes
`tracker/company_directory.json`: the live boards, named, most-linked first.
`--from` reuses a saved report instead of reading the index again.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from collections import Counter
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

import httpx

from scripts.check_catalog_tokens import (
    EMPTY,
    LIVE,
    MISMATCH,
    Probe,
    _identity_key,
    build_probes,
    check_all,
    identity_matches,
)
from tracker.ats_detect import detect_ats
from tracker.company_catalog import CATALOG
from tracker.company_directory import DIRECTORY_PATH
from tracker.company_discovery import COMPANY_DISCOVERY, DiscoveryCompany, connector_state
from tracker.company_store import slugify
from tracker.config import COMPANIES, get_settings

COLLINFO_URL = "https://index.commoncrawl.org/collinfo.json"

#: Where each family serves boards by PATH, so a host prefix query returns every
#: tenant. `{token}.greenhouse.io` is deliberately absent: querying `*.greenhouse
#: .io` returns the vendor's own `www`, `app`, `support` and `api` hosts, each of
#: which `detect_ats` would read as a tenant.
HOSTS: tuple[str, ...] = (
    "boards.greenhouse.io",
    "job-boards.greenhouse.io",
    "jobs.ashbyhq.com",
    "jobs.lever.co",
    "jobs.eu.lever.co",
    "apply.workable.com",
    "jobs.smartrecruiters.com",
)

#: A path's first segment that is a file on the vendor's host, not a tenant.
#: Only Ashby's name pattern admits a dot, so this is where `robots.txt` would
#: otherwise become a company.
_ARTEFACT_SUFFIXES = (".txt", ".xml", ".ico", ".js", ".css", ".png", ".svg", ".json", ".html")

#: Statuses that mean "not now". Anything else non-200 other than the 404 the
#: index uses for "no captures" is a definitive refusal and is not retried.
_TRANSIENT = frozenset({408, 429, 500, 502, 503, 504})


@dataclass(frozen=True)
class Snapshot:
    id: str
    cdx_api: str


@dataclass
class Candidate:
    """One board, as Common Crawl saw it across the snapshots read."""

    adapter: str
    region: str | None
    spellings: Counter[str] = field(default_factory=Counter)
    captures: int = 0
    snapshots: set[str] = field(default_factory=set)
    last_seen: str = ""

    @property
    def token(self) -> str:
        """The spelling seen most often; ties go to the lexically first.

        Case is preserved because a token is opaque (`ats_detect`): Ashby and
        SmartRecruiters names are case-sensitive, and choosing a spelling here
        is only a proposal the probe then answers.
        """
        return min(self.spellings.items(), key=lambda item: (-item[1], item[0]))[0]

    def as_dict(self) -> dict:
        return {
            "adapter": self.adapter,
            "token": self.token,
            "region": self.region,
            "captures": self.captures,
            "snapshots": sorted(self.snapshots),
            "last_seen": self.last_seen,
        }


def _key(adapter: str, token: str, region: str | None) -> tuple[str, str, str]:
    return adapter, token.casefold(), region or ""


def token_of(url: str, host: str) -> tuple[str, str, str | None] | None:
    """`(adapter, token, region)` for a captured URL on `host`, else None."""
    try:
        seen_host = (urlparse(url).hostname or "").lower()
    except ValueError:
        return None
    if seen_host != host:
        return None
    board = detect_ats(url)
    if board is None:
        return None
    if board.board_token.lower().endswith(_ARTEFACT_SUFFIXES):
        return None
    region = board.region.value if board.region is not None else None
    return board.adapter, board.board_token, region


def tally(
    records: Iterable[Mapping[str, str]],
    host: str,
    snapshot: str,
    into: dict[tuple[str, str, str], Candidate],
) -> None:
    """Fold CDX records into `into`, one Candidate per board."""
    for record in records:
        found = token_of(record.get("url", ""), host)
        if found is None:
            continue
        adapter, token, region = found
        candidate = into.setdefault(_key(adapter, token, region), Candidate(adapter, region))
        candidate.spellings[token] += 1
        candidate.captures += 1
        candidate.snapshots.add(snapshot)
        candidate.last_seen = max(candidate.last_seen, record.get("timestamp", ""))


def known_boards() -> set[tuple[str, str]]:
    """`(adapter, casefolded token)` for every board we already collect or offer.

    Built by `check_catalog_tokens.build_probes`, so a built-in with no stored
    token counts under the EFFECTIVE token its adapter resolves (`anthropic` ->
    greenhouse `anthropic`), exactly as the monthly check probes it. Region is
    left out on purpose: a token we hold on one deployment is shown as known on
    both, which can hide a second board but never offers one we already have.
    """
    builtins = [(slug, entry.get("adapter"), entry.get("board_token"))
                for slug, entry in COMPANIES.items()]
    return {(p.adapter, p.token.casefold()) for p in build_probes(CATALOG, builtins)}


def _names(company: DiscoveryCompany) -> tuple[str, ...]:
    return (company.display, company.slug, *company.aliases)


#: A name key shorter than this is not a prefix worth reading: `ey`, `amd` and
#: `pwc` start thousands of unrelated tokens.
_MIN_PREFIX = 4


def _starts_with_name(token: str, company: DiscoveryCompany) -> bool:
    key = _identity_key(token)
    return any(key.startswith(name) for name in map(_identity_key, _names(company))
               if len(name) >= _MIN_PREFIX)


@dataclass(frozen=True)
class Classified:
    #: The token IS the company's name: the actionable list.
    matched: list[dict]
    #: The token STARTS with the company's name. Kept apart because it is right
    #: and wrong in equal measure: `andurilindustries` (Anduril) and
    #: `sonyinteractiveentertainmentglobal`
    #: (PlayStation) beside `uberfreight`, `baincapitalventures` and
    #: `citadel-ai`. Only the board's declared name, or a person, tells them
    #: apart; this list is what a person reads.
    possible: list[dict]
    #: Everything else not already catalogued.
    unmatched: list[dict]


def classify(
    candidates: Iterable[Candidate],
    companies: Mapping[str, DiscoveryCompany],
    known: set[tuple[str, str]],
    state=connector_state,
) -> Classified:
    """Sort candidates against the companies we recommend but cannot collect yet.

    A token matches when it IS one of the company's names once case,
    punctuation and a trailing legal form are set aside — the same equality
    `check_catalog_tokens` holds a board's declared name to. A token that only
    starts with a name is `possible`, never `matched`: `figure` in
    `figurelending` belongs to somebody else often enough that a curator must
    decide it, not this script.
    """
    planned = [c for slug, c in sorted(companies.items()) if state(slug) == "planned"]
    matched: list[dict] = []
    possible: list[dict] = []
    unmatched: list[dict] = []
    for candidate in candidates:
        if (candidate.adapter, candidate.token.casefold()) in known:
            continue
        hits = [c.slug for c in planned if identity_matches(candidate.token, _names(c))]
        near = [c.slug for c in planned if _starts_with_name(candidate.token, c)]
        if hits:
            matched.extend({"company": slug, **candidate.as_dict()} for slug in hits)
        elif near:
            possible.extend({"company": slug, **candidate.as_dict()} for slug in near)
        else:
            unmatched.append(candidate.as_dict())
    for rows in (matched, possible):
        rows.sort(key=lambda row: (row["company"], -row["captures"], row["token"]))
    unmatched.sort(key=lambda row: (-row["captures"], row["adapter"], row["token"]))
    return Classified(matched, possible, unmatched)


class IndexReader:
    """Paced, retried reads of the Common Crawl index. The only network code here.

    Sequential by design: the index is a shared public service that answers 503
    when pushed, and a curator script has no deadline worth that.
    """

    def __init__(self, client: httpx.AsyncClient, delay: float, retries: int) -> None:
        self._client = client
        self._delay = delay
        self._retries = retries
        self._requested = False

    async def _get(
        self, url: str, params: dict | None = None,
        complete: Callable[[httpx.Response], bool] = lambda _: True,
    ) -> httpx.Response | None:
        """The response, or None when the index never answered usefully.

        A 200 that `complete` rejects is retried like a 503: it is the same
        overloaded service, answering in a way that merely looks successful.
        """
        for attempt in range(self._retries + 1):
            if self._requested:
                await asyncio.sleep(self._delay * (2 ** attempt))
            self._requested = True
            try:
                response = await self._client.get(url, params=params)
            except httpx.HTTPError:
                continue
            if response.status_code in _TRANSIENT:
                retry_after = response.headers.get("Retry-After", "")
                if retry_after.isdigit():
                    await asyncio.sleep(min(int(retry_after), 120))
                continue
            if response.status_code == 200 and not complete(response):
                continue
            return response
        return None

    async def snapshots(self, count: int) -> list[Snapshot]:
        response = await self._get(COLLINFO_URL)
        if response is None or response.status_code != 200:
            raise RuntimeError("Common Crawl collection list unavailable")
        # collinfo.json lists collections newest first.
        return [Snapshot(row["id"], row["cdx-api"]) for row in response.json()[:count]]

    async def records(
        self, snapshot: Snapshot, host: str, lost: list[dict]
    ) -> list[dict[str, str]]:
        """Every record the index holds under `host/`, and each page it could not read."""
        query = {"url": f"{host}/*", "output": "json"}
        count = await self._get(snapshot.cdx_api, {**query, "showNumPages": "true"})
        if count is not None and count.status_code == 404:
            return []  # the index's own "No Captures found": complete, and empty
        pages = _page_count(count) if count is not None and count.status_code == 200 else None
        if pages is None:
            lost.append({"snapshot": snapshot.id, "host": host, "page": None})
            return []
        rows: list[dict[str, str]] = []
        for page in range(pages):
            params = {**query, "fl": "url,timestamp", "page": str(page)}
            response = await self._get(snapshot.cdx_api, params,
                                       lambda r: parse_page(r.text) is not None)
            parsed = parse_page(response.text) if response is not None else None
            if response is None or response.status_code != 200 or parsed is None:
                lost.append({"snapshot": snapshot.id, "host": host, "page": page})
                continue
            rows.extend(parsed)
        return rows


def _page_count(response: httpx.Response) -> int | None:
    try:
        pages = response.json().get("pages")
    except (ValueError, AttributeError):
        return None
    return pages if isinstance(pages, int) and pages >= 0 else None


def parse_page(body: str) -> list[dict[str, str]] | None:
    """A CDX page's records, or None when the body is not a whole page.

    Under load the index can answer **200 with half a page** (a page that
    stops mid-alphabet, the next page empty) and nothing in the status says
    so. What does say so is the
    shape: a whole page is one or more JSON records, each on its own line, and
    the body ends with a newline. A cut body ends mid-record or empty. Cut
    exactly on a line boundary it is indistinguishable, which is why a page is
    also retried, not only checked.
    """
    if not body.endswith("\n"):
        return None
    rows: list[dict[str, str]] = []
    for line in body.splitlines():
        try:
            record = json.loads(line)
        except ValueError:
            return None
        if not isinstance(record, dict) or not isinstance(record.get("url"), str):
            return None
        rows.append(record)
    return rows


async def discover(
    client: httpx.AsyncClient, hosts: Iterable[str], snapshot_count: int,
    delay: float, retries: int,
) -> tuple[list[Candidate], list[Snapshot], list[dict]]:
    reader = IndexReader(client, delay, retries)
    snapshots = await reader.snapshots(snapshot_count)
    boards: dict[tuple[str, str, str], Candidate] = {}
    lost: list[dict] = []
    for snapshot in snapshots:
        for host in hosts:
            records = await reader.records(snapshot, host, lost)
            tally(records, host, snapshot.id, boards)
            print(f"{snapshot.id} {host}: {len(records)} records", file=sys.stderr)
    return list(boards.values()), snapshots, lost


async def verify(rows: list[dict], delay: float) -> None:
    """Probe each board as the monthly check would, recording the verdict in place.

    For a `possible` row the identity verdict is expected to be `mismatch`
    (`Anduril Industries` is not `Anduril` by equality); what the curator needs
    from it is `declared`, the name the board gives itself.
    """
    probes = [
        Probe(row["company"], row["adapter"], row["token"], "discovered",
              display=COMPANY_DISCOVERY[row["company"]].display, region=row["region"])
        for row in rows
    ]
    results = await check_all(delay, probes)
    for row, result in zip(rows, results, strict=True):
        row["verified"] = {k: result[k] for k in ("state", "identity", "declared", "count",
                                                  "detail") if k in result}


def display_from_token(token: str) -> str:
    """A readable name from a board address, for a family that states none.

    A token carrying capitals is the tenant's own spelling (`Crusoe`,
    `ClickUp`) and is kept; a lowercase one is split and capitalised
    (`base-power` -> "Base Power"). Either way the row is `named_by="address"`.
    """
    if any(ch.isupper() for ch in token):
        return re.sub(r"[-_]+", " ", token).strip()
    words = [w for w in re.split(r"[-_.]+", token) if w]
    return " ".join(w[:1].upper() + w[1:] for w in words) or token


#: Boards that are not a company, reviewed one at a time, with why.
#: Excluded here, never by editing the generated file, so the monthly rebuild
#: cannot add them back. Keyed by board address `(adapter, token)`, the token
#: case-folded. Deliberately not a pattern: "Rocket Referrals" is a company and
#: "Coupang Internal" is not, and only a person reading the board can tell.
EXCLUDED_BOARDS: Mapping[tuple[str, str], str] = {
    ("greenhouse", "monzoreferrals"): (
        "Monzo's referral board, named 'Referrals Only'; Monzo is its own row (monzo). "
        "Flagged by the 2026-10-01 token audit"
    ),
    ("greenhouse", "thoughtworksreferral"): (
        "Thoughtworks' referral board, also named 'Referrals Only'; its slug, made from "
        "that name, confirmed it to the token check"
    ),
    # Each board read live and its roles compared with the company's main
    # board by Greenhouse `internal_job_id`.
    # Employee, alumni or referral copies of a main board: the same roles
    # twice, under a name that is not a company, behind a link an outsider
    # cannot apply through.
    ("greenhouse", "referralsuseonly"): (
        "Elastic's referral board ('Referral Board', 'roles that are not externally posted'); "
        "101 of 109 roles are on Elastic's own board (catalog: elastic)"
    ),
    ("greenhouse", "coupanginternal"): (
        "Coupang's internal board ('exclusively for internal employees'); 438 of 466 roles "
        "are on Coupang's own board (coupang)"
    ),
    ("greenhouse", "internaljobsatlush"): (
        "Lush's internal job board; 80 of 96 roles are on Lush's own board (lush)"
    ),
    ("greenhouse", "connectedcannabisco"): (
        "Connected's internal transfer board; all 18 roles are on its careers board "
        "(connectedcannabis)"
    ),
    ("greenhouse", "ssreferrals"): (
        "Sprout Social's employee referral board ('do not share this link outside our "
        "organization'); 20 of 31 roles are on Sprout's own board (sproutsocial)"
    ),
    ("greenhouse", "4lu44n1n37w012k"): (
        "HelloFresh's alumni job board; 10 of 11 roles are on HelloFresh's own board (hellofresh)"
    ),
    ("greenhouse", "vitalfarmsinternalcrew"): (
        "Vital Farms' board for current crew members; 8 of 10 roles are on its own board "
        "(vitalfarms)"
    ),
    ("greenhouse", "misfitsinternaljobs"): (
        "Misfits Market's internal job board; 9 of 16 roles are on its own board (misfitsmarket)"
    ),
    ("greenhouse", "bwreferrals"): (
        "Bridgewater's referral board; its roles are referral only, one also on Bridgewater's "
        "own board (bridgewater89)"
    ),
    ("greenhouse", "bridgewaterassociatescampusrecruitingreferral"): (
        "Bridgewater's campus referral board; its one role is on Bridgewater's own board "
        "(bridgewater89)"
    ),
    # Boards that list nothing, a test account, and forms that are not roles.
    ("greenhouse", "remotereferralboardinternaluseonly"): (
        "Remote's internal referral board; lists no roles"
    ),
    ("greenhouse", "2uinlinepromotions"): (
        "2U's internal in-line promotions board; lists no roles"
    ),
    ("greenhouse", "headoutreferrals"): "Headout's referral board; lists no roles",
    ("greenhouse", "ezcatertalentcommunity"): (
        "ezCater's talent community sign-up; lists no roles"
    ),
    ("workable", "contactually"): "A Workable account named 'test' that lists no roles",
    ("greenhouse", "auldwhitetalentcommunity"): (
        "Auld & White's talent community: two 'General Application' forms, no role; the "
        "company's roles are on auldwhiteconstructors"
    ),
    ("greenhouse", "wooreferral"): (
        "WOO's referral intake: one 'External Referrals' form, no role"
    ),
    ("greenhouse", "axontalentcommunity"): (
        "Axon's AfroTech 2026 event board, named 'Join Our Talent Community': three event "
        "roles under a name that is not a company; Axon is its own row (axon)"
    ),
}


def excluded(adapter: str, token: str) -> str | None:
    """Why this board is not a directory company, or None."""
    return EXCLUDED_BOARDS.get((adapter, token.casefold()))


def reserved_slugs() -> set[str]:
    return set(COMPANY_DISCOVERY) | set(CATALOG) | set(COMPANIES)


def build_directory(
    rows: list[dict], results: list[dict], reserved: set[str],
    companies: Mapping[str, DiscoveryCompany] = COMPANY_DISCOVERY,
) -> tuple[list[dict], Counter[str]]:
    """Directory rows for probed candidates, most-captured first, and why the rest left.

    `results[i]` is the probe of `rows[i]`. Kept: a board that answered live,
    empty or named (a named board reports `mismatch` here because the probe
    has no company to compare it with). Held back, counted in the second
    value: a board that is dead or could not be judged, and one whose name IS
    a company we recommend — that is a curator's decision (`classify`'s
    `matched`), never a second row beside the recommended one. A reviewed
    exclusion (`EXCLUDED_BOARDS`) never takes a row or a slug.
    """
    taken = set(reserved)
    kept: list[dict] = []
    held: Counter[str] = Counter()
    pairs = sorted(zip(rows, results, strict=True),
                   key=lambda p: (-p[0]["captures"], p[0]["adapter"], p[0]["token"]))
    for row, result in pairs:
        if excluded(row["adapter"], row["token"]):
            held["excluded"] += 1
            continue
        if result["state"] not in (LIVE, EMPTY, MISMATCH):
            held[result["state"]] += 1
            continue
        declared = (result.get("declared") or "").strip()
        display = declared or display_from_token(row["token"])
        if any(identity_matches(display, _names(c)) for c in companies.values()):
            held["a recommended company"] += 1
            continue
        base = slugify(display) or slugify(row["token"]) or row["adapter"]
        slug, n = base, 1
        while slug in taken:
            slug = f"{base}-{row['adapter']}" + (f"-{n}" if n > 1 else "")
            n += 1
        taken.add(slug)
        kept.append({"slug": slug, "display": display,
                     "named_by": "board" if declared else "address",
                     "adapter": row["adapter"], "board_token": row["token"],
                     "board_region": row["region"]})
    return kept, held


async def probe_directory(rows: list[dict], delay: float) -> list[dict]:
    """Probe every row, one paced lane per family, side by side."""
    lanes: dict[str, list[int]] = {}
    for index, row in enumerate(rows):
        lanes.setdefault(row["adapter"], []).append(index)

    async def lane(indexes: list[int]) -> list[tuple[int, dict]]:
        probes = [Probe(f"directory:{rows[i]['token']}", rows[i]["adapter"], rows[i]["token"],
                        "directory", region=rows[i]["region"]) for i in indexes]
        return list(zip(indexes, await check_all(delay, probes), strict=True))

    results: list[dict] = [{}] * len(rows)
    for pairs in await asyncio.gather(*(lane(ix) for ix in lanes.values())):
        for index, result in pairs:
            results[index] = result
    return results


def write_directory(path: Path, companies: list[dict], snapshots: list[str]) -> None:
    """One company per line, so a monthly rebuild reviews as a readable diff."""
    lines = ",\n".join("  " + json.dumps(c, ensure_ascii=False, sort_keys=True) for c in companies)
    head = json.dumps({"built": datetime.now(UTC).date().isoformat(), "snapshots": snapshots})
    path.write_text(head[:-1] + ',\n "companies": [\n' + lines + "\n ]}\n")


def _render(report: dict) -> None:
    print(f"snapshots: {', '.join(report['snapshots'])}")
    for tier, title in (("matched", "MATCHED to a planned company"),
                        ("possible", "POSSIBLE: starts with a planned company's name")):
        print(f"\n=== {title} ({len(report[tier])}) ===")
        for row in report[tier]:
            verified = row.get("verified")
            note = f"  -> {verified['state']}" if verified else ""
            if verified and verified.get("declared"):
                note += f" declares {verified['declared']!r}"
            print(f"  {row['company']:<24} {row['adapter']:<16} {row['token']:<36} "
                  f"{row['captures']:>6} captures{note}")
    top = report["unmatched"][:40]
    print(f"\n=== NEW, unmatched ({len(report['unmatched'])}; top {len(top)} by captures) ===")
    for row in top:
        region = f" ({row['region']})" if row["region"] else ""
        print(f"  {row['adapter']:<16} {row['token'] + region:<34} {row['captures']:>6} captures")
    if report["lost"]:
        print(f"\nINCOMPLETE: {len(report['lost'])} index page(s) unread — the lists are partial")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--snapshots", type=int, default=3,
                        help="latest Common Crawl snapshots to read (default 3)")
    parser.add_argument("--host", action="append", choices=HOSTS,
                        help="restrict to one board host (repeatable)")
    parser.add_argument("--delay", type=float, default=1.5, help="seconds between index requests")
    parser.add_argument("--retries", type=int, default=4, help="retries per index request")
    parser.add_argument("--verify", action="store_true",
                        help="probe matched and possible boards (live + identity) via check_catalog_tokens")
    parser.add_argument("--json", action="store_true", help="print the report as JSON")
    parser.add_argument("--out", help="also write the full JSON report to this path")
    parser.add_argument("--from", dest="source", help="reuse a saved --out report instead of the index")
    parser.add_argument("--directory", nargs="?", const=str(DIRECTORY_PATH),
                        help="probe every new board and write the company directory")
    args = parser.parse_args()

    if args.directory:
        return _directory(args)

    async def run() -> dict:
        headers = {"user-agent": get_settings().scraper_user_agent}
        async with httpx.AsyncClient(timeout=120, headers=headers,
                                     follow_redirects=True) as client:
            candidates, snapshots, lost = await discover(
                client, args.host or HOSTS, args.snapshots, args.delay, args.retries)
        found = classify(candidates, COMPANY_DISCOVERY, known_boards())
        if args.verify:
            await verify(found.matched + found.possible, args.delay)
        return {"snapshots": [s.id for s in snapshots], "hosts": list(args.host or HOSTS),
                "matched": found.matched, "possible": found.possible,
                "unmatched": found.unmatched, "lost": lost}

    report = asyncio.run(run())
    if args.out:
        with open(args.out, "w") as handle:
            json.dump(report, handle, indent=2)
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        _render(report)
    return 3 if report["lost"] else 0


def _directory(args: argparse.Namespace) -> int:
    if args.source:
        with open(args.source) as handle:
            report = json.load(handle)
    else:
        async def scan() -> dict:
            headers = {"user-agent": get_settings().scraper_user_agent}
            async with httpx.AsyncClient(timeout=120, headers=headers,
                                         follow_redirects=True) as client:
                candidates, snapshots, lost = await discover(
                    client, args.host or HOSTS, args.snapshots, args.delay, args.retries)
            found = classify(candidates, COMPANY_DISCOVERY, known_boards())
            return {"snapshots": [s.id for s in snapshots], "possible": found.possible,
                    "unmatched": found.unmatched, "lost": lost}
        report = asyncio.run(scan())
    # `matched` rows name a recommended company: a curator's call, never a row.
    rows = report.get("possible", []) + report["unmatched"]
    seen: set[tuple[str, str, str]] = set()
    unique = []
    for row in rows:
        key = _key(row["adapter"], row["token"], row["region"])
        if key not in seen:
            seen.add(key)
            unique.append(row)
    print(f"probing {len(unique)} boards", file=sys.stderr)
    results = asyncio.run(probe_directory(unique, args.delay))
    companies, held = build_directory(unique, results, reserved_slugs())
    write_directory(Path(args.directory), companies, report.get("snapshots", []))
    print(f"wrote {len(companies)} companies to {args.directory}; held back: {dict(held)}")
    return 3 if report.get("lost") or held.get("unknown") else 0


if __name__ == "__main__":
    sys.exit(main())
