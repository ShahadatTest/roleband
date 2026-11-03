"""Are the board tokens we actually scrape still live?

`company_catalog.CATALOG` promises that enabling an entry is "one-click,
immediately-scrapeable"; this script checks that promise against the boards.

A wrong token is not a soft failure. A dead board answers 404, so the listing is
invalidated, `scanned` is 0, and the run classifies `failed` -> `ANOMALY`. Three
of those quarantine the binding, and quarantine suppresses closure with no exit
a user can reach.

**The catalog is not the roster.** Deleting a rotted catalog entry leaves an
already-seeded `tracked_companies` row pointing at the same dead board, so
checking `CATALOG` alone would silently *narrow* what gets checked. The probe
set is the union: every catalog entry, plus every distinct token in use by a
tracked company. A token being scraped tonight is the stronger claim, and it is
checked whether or not the catalog still lists it.

**A missing `board_token` is not the absence of a token.** `TenantMap.resolve`
falls back to the adapter's module map and then to the company slug, so a row
with no stored token can still scrape an *effective* token in a multi-tenant
URL (`.../boards/anthropic/jobs`) that rots exactly like a catalog token. What
decides is whether the adapter DECLARES a `BoardProbe`; the probe set resolves
the token the adapter would really use.

Board roots are not restated here either. Each adapter declares its own
(`BaseAdapter.board_probe`), so this script cannot verify a route the adapter
stopped fetching.

Buckets, which mean genuinely different things:

* **live** — 200 with at least one posting. The promise holds.
* **empty** — 200 and a well-formed but empty board. The
  token is CORRECT; the company simply is not hiring. Never "fix" one of these,
  or a real token gets replaced with a guess.
* **mismatch** — 200, a readable board, and it belongs to somebody else. The
  quiet failure, and the reason identity is checked separately from coverage:
  a wrong company with HTTP 200 is still wrong. A dead token is loud;
  a live board under the wrong tenant collects their postings under our slug.
  Only Greenhouse can answer this: its board root states
  `{"name": ...}`, while Ashby answers `{jobs, apiVersion}` and Lever a bare
  array. For those two the identity is reported `unstated` — not verified.
* **self-named** (an identity, beside a live or empty state) — a directory
  company: every name we hold for it was read from this board or its
  address, so a match confirms nothing and a different spelling proves nothing.
  Only a board-named row that now declares another name is `mismatch`.
  Whether a directory board is a company at all ("Referrals Only")
  is a human's call, recorded in `discover_board_tokens.EXCLUDED_BOARDS`.
* **dead** — a definitive non-200 (404, 410, 401/403 ...), or a body we cannot
  read. The entry is a liability.
* **denied** — collection policy refuses the provider. No request is
  made. Our own decision, so it is never evidence about a token and never fails
  the run. Reported rather than raised, unlike `smoke_adapters`: a raise here
  would abort the monthly pass at the first denied provider and hide every
  other token's state.
* **uncheckable** — an adapter that declares no board probe (`google-deepmind`
  rides the `google` adapter with a `DeepMind` token). Structural and
  permanent, so it is reported but never fails the run.
* **unknown** — the check could not finish: a network error, or a host that
  throttled or was briefly unavailable (429/502/503/504/408, with any
  `Retry-After` in the detail). Says nothing about the token, so it is never
  `dead`; it makes the run inconclusive (exit 3), not wrong (exit 1). A healthy
  board answering 429 reported DEAD is exactly how a correct token gets
  replaced with a guess.

Deliberately a script and not a test: tests never fetch live sources
(`docs/testing.md`), and a hiring freeze at one company must never fail the
build. Run it by hand on the same monthly cadence as `check_vendored_upstream`,
and whenever adding an entry.

    0  every token live or legitimately empty
    1  WRONG — a token is dead, or resolves to another company's board
    3  UNKNOWN — could not complete the check (network/DB); not a failure

Usage (from `backend/`):

    .venv/bin/python -m scripts.check_catalog_tokens
    .venv/bin/python -m scripts.check_catalog_tokens --json
    .venv/bin/python -m scripts.check_catalog_tokens --no-db   # catalog only
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

import httpx

from tracker.company_catalog import CATALOG
from tracker.company_directory import DirectoryCompany, directory_company
from tracker.company_discovery import COMPANY_DISCOVERY
from tracker.config import get_settings
from tracker.connectors import ADAPTER_REGISTRY, BoardProbe
from tracker.connectors.extract.sitemap import SitemapProbe
from tracker.platform.safe_fetch import public_transport
from tracker.source_policy import collection_access


def board_probe_for(adapter: str | None) -> BoardProbe | None:
    """The adapter's own declaration of its board root, or None.

    Read off the registry rather than restated here: a hand-copied table could
    keep probing an endpoint the adapter stopped fetching, and a declaration on
    the class cannot drift from the class.
    """
    cls = ADAPTER_REGISTRY.get(adapter or "")
    return getattr(cls, "board_probe", None) if cls is not None else None


LIVE, EMPTY, DEAD, UNKNOWN, UNCHECKABLE = "live", "empty", "dead", "unknown", "uncheckable"
#: Statuses that say "not now", never "no such board": throttling (429), a
#: gateway or upstream blip (502/504), maintenance (503), a slow request (408).
#: They report UNKNOWN. Everything else non-200 is a definitive answer.
TRANSIENT_STATUSES = frozenset({408, 429, 502, 503, 504})
#: 200, a readable board, and it belongs to somebody else. A dead token costs
#: anomalies and is loud; this one is quiet and collects another company's
#: postings under our slug, which is why it fails the run like DEAD.
MISMATCH = "mismatch"
#: Collection policy refuses this provider. No request is made.
DENIED = "denied"

#: What the identity route settled. `unstated` is not a pass and not a failure:
#: Ashby and Lever name no tenant, so this check cannot speak for them.
CONFIRMED, UNSTATED = "confirmed", "unstated"
#: A directory company: every name we hold for it was read from this
#: board, or spelled out from its address, so comparing them confirms nothing
#: and a mismatch proves nothing. Not a pass, not a failure.
SELF_NAMED = "self-named"

#: Where a probe came from. `tracked` is the load-bearing one: that token is on
#: tonight's roster, so its rot is already costing jobs.
CATALOG_ONLY, TRACKED_ONLY, BOTH = "catalog", "tracked", "catalog+tracked"

#: Trailing words that state a legal form rather than an identity. Dropped from
#: BOTH sides before comparison, on word boundaries, so "Wiz, Inc." and "Wiz"
#: are one name and "Wisconsin" is never a suffix of anything.
#:
#: Stripped, then compared for EQUALITY, never substring containment: a
#: substring test cannot tell a legal form from a line of business, and the
#: difference is the whole check. Greenhouse `figure` is **Figure Lending**, an
#: unrelated company, and containment would let "Figure Lending" confirm
#: `figure`, the wrong-company hit this module exists to catch.
#: `Citadel Securities` vs `Citadel` is the same shape, and both are separate
#: companies in `COMPANY_DISCOVERY`. Equality keeps "Gusto, Inc." vs `gusto`
#: and rejects both of those.
_LEGAL_FORMS = frozenset(
    {
        "ab", "ag", "as", "bv", "co", "company", "corp", "corporation", "gmbh",
        "inc", "incorporated", "kk", "limited", "llc", "llp", "lp", "ltd", "nv",
        "oy", "plc", "pte", "pty", "sa", "sas", "spa", "srl",
    }
)


def _normalize(name: str | None) -> str:
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


def _identity_key(name: str | None) -> str:
    """A company name reduced to the part that identifies it.

    Word split first, because `_normalize` destroys the boundaries a legal form
    has to be recognised on: once "Wiz, Inc." is `wizinc` there is no way back.
    A name that is *only* a legal form keeps its normalized self rather than
    reducing to nothing, so a hypothetical company called "Co" still compares.
    """
    words = [w for w in re.split(r"[^a-z0-9]+", (name or "").lower()) if w]
    while len(words) > 1 and words[-1] in _LEGAL_FORMS:
        words.pop()
    return "".join(words) or _normalize(name)


def identity_matches(declared: str | None, candidates: Iterable[str]) -> bool:
    """Does a board's self-declared name belong to this company?

    Equality of `_identity_key`, which is normalized equality once a trailing
    legal form is off both sides. Kept pure and separate from the request so the
    wrong-company case is testable without a network — the whole point of the
    check is a response that looks perfectly healthy.

    Deliberately not fuzzy. A board that names a company we have another name
    for is `UNSTATED`'s problem to record, not this function's to guess at: the
    way to admit "IMC" for `imc-trading` is to curate the alias, which is a name
    WE assert, rather than to widen the comparison until the board can assert it
    for us.
    """
    board = _identity_key(declared)
    if not board:
        return False
    return any(_identity_key(candidate) == board for candidate in candidates if candidate)


@dataclass(frozen=True)
class Probe:
    slug: str
    adapter: str
    token: str
    origin: str
    #: Company display name when we have one, for the identity comparison.
    display: str | None = None
    #: Regional deployment for a multi-region family, else None. Load-bearing:
    #: probing an EU tenant against the global host answers the
    #: same 404 a dead token does, so a healthy board would be reported DEAD
    #: and its correct token "fixed" with a guess.
    region: str | None = None

    @property
    def identity_candidates(self) -> tuple[str, ...]:
        """OUR names for this company — never the token.

        The token is the thing under test. A board reached via token `stripe`
        declares "Stripe", so admitting the token as a candidate would make
        every mismatch confirm itself and the check would be decorative (its
        negative control). The slug, one of our names, already settles a live
        board (`scaleai` vs "Scale AI" included), so dropping the token costs
        nothing real.

        The curated aliases join it on the same principle, and only
        on that principle: `COMPANY_DISCOVERY` aliases are names a human wrote
        down for the company, so they cannot confirm a token the way the token
        itself would. They are load-bearing for a tenant whose board is named
        after the trading entity rather than the product — Greenhouse `imc`
        declares "IMC" where our display is "IMC Trading", and `IMC` is already
        an alias because seekers search for it.
        """
        company = COMPANY_DISCOVERY.get(self.slug)
        aliases = company.aliases if company is not None else ()
        return tuple(x for x in (self.display, self.slug, *aliases) if x)


def build_probes(
    catalog: Mapping[str, Mapping[str, str]],
    tracked: Iterable[tuple] = (),
) -> list[Probe]:
    """The union of catalog entries and tokens actually in use, deduplicated.

    `tracked` is `(slug, adapter, board_token[, board_region])` rows straight off
    `tracked_companies` — plain tuples, so the merge rule is testable without a
    database. A row whose adapter *and* token match its catalog entry is the
    same probe (origin `catalog+tracked`), not a second request; a row that
    disagrees with the catalog, or has no catalog entry at all, is its own probe.

    **The company is part of the key.** Deduplicating by `(adapter, token,
    region)` alone would deduplicate the company *assertions* along with the
    requests: a tracked `acme -> greenhouse/stripe` would collapse into the
    catalog's `stripe` entry, and the surviving probe would ask Stripe's board
    whether it is Stripe's and confirm. A readable board belonging to the wrong
    company would escape whenever the wrong token is one we already know, and a
    second tracked row sharing a token would go unprobed, its own policy check
    unevaluated. Requests are still made once per board; `_ResponseCache` does that where it
    belongs, without discarding anybody's claim to it.
    """
    probes: dict[tuple[str, str, str, str], Probe] = {}
    for slug, entry in sorted(catalog.items()):
        adapter, token = entry["adapter"], entry["board_token"]
        probes[(adapter, token, "", slug)] = Probe(
            slug, adapter, token, CATALOG_ONLY, display=entry.get("display")
        )

    for row in sorted(tracked, key=lambda row: row[0]):
        # 3-tuples stay valid: a company with no region is every single-host
        # family plus every Lever row with no region stored.
        slug, adapter, token = row[:3]
        region = row[3] if len(row) > 3 else None
        # Skipping keys off DECLARED TENANCY, not off a missing stored token:
        # `TenantMap.resolve` falls back to the module map and then to the
        # slug, so a row with no stored token still scrapes an *effective*
        # token in a multi-tenant URL that rots exactly like a catalog token.
        # A source that really does hard-code its listing URL declares no
        # probe and is skipped.
        probe = board_probe_for(adapter)
        if adapter is None or probe is None:
            continue
        effective = probe.tenants.resolve(slug, token or None)
        if not effective:
            continue
        # Region is part of the identity: the same site name on two Lever
        # deployments is two different boards, so they are two probes.
        key = (adapter, effective, region or "", slug)
        existing = probes.get(key)
        if existing is None:
            probes[key] = Probe(slug, adapter, effective, TRACKED_ONLY, region=region)
        elif existing.origin == CATALOG_ONLY:
            # Same company AND same mapping — the catalog offer and the live row
            # agree, so this is one claim recorded twice, not two claims.
            probes[key] = Probe(
                existing.slug, adapter, effective, BOTH,
                display=existing.display, region=region,
            )

    return sorted(probes.values(), key=lambda p: (p.slug, p.token))


def _posting_count(payload: object) -> int | None:
    """Postings in a board payload, or None if it is not a board payload at all.

    A **bare list is a board**: Lever's postings feed answers a
    top-level array with no envelope at all. Requiring a dict here would report
    a healthy Lever board DEAD ("no jobs/postings array"), and a false dead is
    how a correct token gets replaced with a guess.
    """
    if isinstance(payload, list):
        return len(payload)
    if not isinstance(payload, dict):
        return None
    # Eightfold's PCSX API wraps the board in `data`; Accenture's
    # findjobs answers `data` as the posting array itself.
    if isinstance(payload.get("data"), list):
        return len(payload["data"])
    if isinstance(payload.get("data"), dict):
        payload = payload["data"]
    # SmartRecruiters' Posting API pages its board in `content`.
    for key in ("jobs", "postings", "positions", "content"):
        value = payload.get(key)
        if isinstance(value, list):
            return len(value)
    return None


class _DedupTransport(httpx.AsyncBaseTransport):
    """One real GET per URL, however many companies claim that board.

    The REQUEST is the thing worth deduplicating — two companies mapped to one
    board are still one board, and a maintenance script should not double the
    load on a public API just to say so twice. What must never be deduplicated
    is the company *assertion*; see `build_probes`.
    Keying on the URL is exactly keying on `(adapter, token, region)`, because
    that is all the URL is built from.

    It lives at the transport rather than around `check_probe` so the checking
    code stays written against a plain client: whether a board has already been
    read is a fact about the network, not a branch every caller should carry.
    A fresh `Response` is built per call from the stored bytes — handing the
    same instance back twice would share one already-consumed stream.

    `aread()` returns DECODED bytes, so the framing headers that described the
    wire form do not describe the body and must not be replayed: keeping
    `content-encoding: gzip` beside an already-gunzipped body makes httpx
    decompress it a second time, which is a `DecodingError` on every board that
    answers gzip and invisible against a mock (no mock sets the header).
    """

    #: Describe the wire form, not the bytes we stored. See the class docstring.
    _REFRAMED = ("content-encoding", "content-length", "transfer-encoding")

    def __init__(self, inner: httpx.AsyncBaseTransport) -> None:
        self._inner = inner
        self.seen: dict[str, tuple[int, bytes, httpx.Headers]] = {}

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url not in self.seen:
            response = await self._inner.handle_async_request(request)
            await response.aread()
            headers = httpx.Headers(
                [(k, v) for k, v in response.headers.multi_items()
                 if k.lower() not in self._REFRAMED]
            )
            self.seen[url] = (response.status_code, response.content, headers)
        status, content, headers = self.seen[url]
        return httpx.Response(status, content=content, headers=headers)

    async def aclose(self) -> None:
        await self._inner.aclose()


def _sitemap_verdict(result: SitemapProbe) -> dict:
    """A sitemap board's state, from the same bounded walk collection makes.

    The root decides dead vs unknown exactly as a JSON board's route does: a
    definitive status or a body that is no sitemap is dead; no response or a
    transient status judges nothing. A readable root whose children were not
    all read is unknown, never dead and never a count.
    """
    inventory, status = result.inventory, result.root_status
    if not inventory.recognized:
        if status is None or status in TRANSIENT_STATUSES:
            why = inventory.failures[0] if inventory.failures else "no response"
            shown = why if status is None else f"HTTP {status}"
            return {"state": UNKNOWN, "detail": f"sitemap root unread ({shown}), token not judged"}
        if status != 200:
            return {"state": DEAD, "detail": f"HTTP {status}"}
        return {"state": DEAD, "detail": "root is not a sitemap"}
    if not inventory.complete:
        why = "; ".join(inventory.failures[:3]) or "our sitemap ceiling fired"
        return {"state": UNKNOWN, "detail": f"sitemap inventory partly read: {why}"}
    count = len(inventory.urls)
    return {"state": LIVE if count else EMPTY, "count": count, "identity": UNSTATED,
            "detail": f"sitemap inventory: {count} postings"}


async def check_probe(client: httpx.AsyncClient, probe: Probe) -> dict:
    base = {"slug": probe.slug, "adapter": probe.adapter, "token": probe.token,
            "origin": probe.origin}
    board = board_probe_for(probe.adapter)
    if board is None:
        # An adapter with no declared board root. Permanent and structural, so
        # it is reported without failing the run — conflating it with a network
        # blip would make the exit code mean nothing.
        return {**base, "state": UNCHECKABLE,
                "detail": f"adapter {probe.adapter!r} declares no board probe"}

    # Collection policy first, and before any socket. This script builds its
    # own httpx client, so the transport-level gates never see its requests; it
    # consults the deny list itself. A denied provider is `unattempted`, not a
    # failure.
    access = collection_access(probe.adapter, company=probe.slug)
    if access.denied:
        return {**base, "state": DENIED, "detail": access.reason or "collection policy"}

    if board.sitemap is not None:
        return {**base, **_sitemap_verdict(await board.sitemap(probe.token).probe(client))}

    body = dict(board.probe_body) if board.probe_body is not None else None
    try:
        response = await client.request(
            board.method,
            board.url_for(probe.token, probe.region),
            json=body if board.probe_encoding == "json" else None,
            data=body if board.probe_encoding == "form" else None,
            headers=dict(board.probe_headers) if board.probe_headers else None,
        )
    except httpx.HTTPError as exc:
        return {**base, "state": UNKNOWN, "detail": f"{type(exc).__name__}: {exc}"}

    result = base
    if response.status_code in TRANSIENT_STATUSES:
        retry_after = response.headers.get("Retry-After")
        detail = f"HTTP {response.status_code}: host throttled or unavailable, token not judged"
        if retry_after:
            detail += f" (Retry-After: {retry_after})"
        return {**result, "state": UNKNOWN, "detail": detail}
    if response.status_code != 200:
        return {**result, "state": DEAD, "detail": f"HTTP {response.status_code}"}
    floor = (board.uncounted_rows(probe.token, response.text)
             if board.uncounted_rows is not None else None)
    if floor is not None:
        # A tenant declared to state no total: the page's rows are
        # a floor, reported below as "serves roles", never a board size.
        count = floor
    elif board.read_count is not None:
        # An HTML board: the family reads its own page.
        count = board.read_count(response.text)
    else:
        try:
            payload = response.json()
        except ValueError:
            return {**result, "state": DEAD, "detail": "non-JSON body"}
        count = _posting_count(payload)
    if count is None:
        # 200 with a body that is not a board. A redirect to a marketing page
        # lands here, and it is dead: the adapter would parse nothing.
        return {**result, "state": DEAD, "detail": "no jobs/postings array"}

    # The board is readable. Whose is it? Schema/identity verification is a
    # separate question from coverage, and only Greenhouse answers it.
    identity = await _check_identity(client, probe, board)
    result = {**result, "identity": identity["identity"]}
    if identity["identity"] == MISMATCH:
        return {**result, "state": MISMATCH, "count": count, "detail": identity["detail"],
                "declared": identity["declared"]}
    if identity["identity"] == UNKNOWN:
        return {**result, "state": UNKNOWN, "detail": identity["detail"]}
    if identity.get("declared"):
        result["declared"] = identity["declared"]

    if count == 0:
        return {**result, "state": EMPTY, "count": 0, "detail": "board exists, no open roles"}
    if not board.counts_whole_board or floor is not None:
        # The probe asked for one posting. Say what was established -- the board
        # serves roles -- rather than printing a size nobody measured.
        return {**result, "state": LIVE, "count": count, "capped": True,
                "detail": f"board serves roles (probe read {count})"}
    return {**result, "state": LIVE, "count": count}


async def _check_identity(
    client: httpx.AsyncClient, probe: Probe, board: BoardProbe
) -> dict:
    """Does this readable board declare itself to be this company's?

    Only reached for a board that already answered, so a dead token costs no
    second request. `unstated` when the family names no tenant: Ashby answers
    `{jobs, apiVersion}` and Lever a bare array, and reporting either as
    verified would be the check claiming something it never established.

    The board's declared name is cached with the board; the COMPARISON is not.
    That split is the point: one fetch, and one verdict per
    company claiming it, so a second company on the same token is judged rather
    than dropped.
    """
    if board.identity_url is None:
        return {"identity": UNSTATED, "detail": "family declares no board name"}
    try:
        response = await client.get(board.identity_url.format(token=probe.token))
    except httpx.HTTPError as exc:
        return {"identity": UNKNOWN, "detail": f"identity: {type(exc).__name__}: {exc}"}
    if response.status_code != 200:
        return {"identity": UNKNOWN, "detail": f"identity: HTTP {response.status_code}"}
    try:
        declared = (
            board.read_identity(response.text)
            if board.read_identity is not None
            else response.json().get(board.identity_key)
        )
    except (ValueError, AttributeError):
        return {"identity": UNKNOWN, "detail": "identity: unreadable body"}
    if not isinstance(declared, str) or not declared.strip():
        return {"identity": UNSTATED, "detail": "board stated no name"}
    listed = _directory_row(probe.slug)
    if listed is not None:
        return _self_named(declared, listed)
    if identity_matches(declared, probe.identity_candidates):
        return {"identity": CONFIRMED, "declared": declared}
    return {
        "identity": MISMATCH,
        "declared": declared,
        "detail": f"board declares {declared!r}, not {probe.slug!r}",
    }


def _directory_row(slug: str) -> DirectoryCompany | None:
    """The directory row a probe's company is, or None for one of ours.

    The builder reserves every curated, catalog and built-in slug, so a slug
    is never both; checked anyway, so a later catalog entry is judged by our
    names even before the monthly rebuild drops its directory twin."""
    if slug in COMPANY_DISCOVERY or slug in CATALOG:
        return None
    return directory_company(slug)


def _self_named(declared: str, listed: DirectoryCompany) -> dict:
    """A directory company's board against the only names we hold for it.

    They came from this board (`named_by="board"`) or its address, so a match
    confirms nothing: `self-named`, never `confirmed`. Comparing the slug
    instead is wrong both ways: a slug made from the board's name "confirms"
    it (`referrals-only`), and one that took a `-<adapter>` suffix because the
    plain slug was taken reads WRONG COMPANY (`current-greenhouse`, named
    "Current").

    One comparison is still evidence: a board that named itself at build time
    and now declares a different name is not the board the directory read, the
    quiet failure this check exists for.
    """
    if listed.named_by == "board" and not identity_matches(declared, (listed.display,)):
        return {
            "identity": MISMATCH,
            "declared": declared,
            "detail": f"board now declares {declared!r}; the directory read {listed.display!r}",
        }
    return {"identity": SELF_NAMED, "declared": declared}


async def tracked_tokens() -> list[tuple]:
    """`(slug, adapter, board_token, board_region)` for every tracked company.

    Imported lazily: `--no-db` must stay usable on a machine with no Postgres.
    """
    from sqlalchemy import select

    from tracker.db.models import TrackedCompany
    from tracker.db.session import session_scope

    async with session_scope() as session:
        rows = (await session.execute(select(TrackedCompany))).scalars().all()
        return [(row.slug, row.adapter, row.board_token, row.board_region) for row in rows]


async def check_all(delay: float, probes: list[Probe]) -> list[dict]:
    settings = get_settings()
    headers = {"accept": "application/json", "user-agent": settings.scraper_user_agent}
    results: list[dict] = []
    transport = _DedupTransport(public_transport())
    async with httpx.AsyncClient(
        timeout=30, follow_redirects=True, headers=headers, transport=transport
    ) as client:
        fetched = False
        for probe in probes:
            board = board_probe_for(probe.adapter)
            # Pace before a real request, never before a cache hit. A second
            # company claiming an already-read board issues no traffic, so
            # sleeping for it would only slow the monthly pass down for no
            # politeness gain.
            due = board is not None and (
                board.url_for(probe.token, probe.region) not in transport.seen
            )
            if fetched and due:
                # Paced like a scrape: this is the same public API the adapters
                # use, and a burst from a maintenance script is still a burst.
                await asyncio.sleep(delay)
            fetched = fetched or due
            results.append(await check_probe(client, probe))
    return results


def _render(results: list[dict]) -> None:
    for state, title in ((MISMATCH, "WRONG COMPANY"), (DEAD, "DEAD"), (UNKNOWN, "UNKNOWN"),
                         (DENIED, "DENIED (policy)"), (UNCHECKABLE, "UNCHECKABLE"),
                         (EMPTY, "EMPTY (token OK)"), (LIVE, "LIVE")):
        rows = [r for r in results if r["state"] == state]
        if not rows:
            continue
        print(f"\n=== {title} ({len(rows)}) ===")
        for row in rows:
            suffix = row.get("detail") or f"{row.get('count')} postings"
            origin = row.get("origin", CATALOG_ONLY)
            # A dead token on tonight's roster is already costing jobs; one that
            # is only offered in the catalog has merely never been taken up.
            identity = row.get("identity")
            note = f" [identity {identity}]" if identity in (MISMATCH, UNSTATED, SELF_NAMED) else ""
            print(f"  {row['slug']:<14} {row['adapter']:<11} {row['token']:<22} "
                  f"{origin:<15} {suffix}{note}")


def exit_code(results: Iterable[dict], db_error: str | None = None) -> int:
    """0 usable / 1 wrong / 3 unverifiable — the whole point of the check.

    `mismatch` fails alongside `dead` and is the worse of the two: a dead token
    is loud (404 -> anomaly -> quarantine), while a live board belonging to
    another company is silent and collects their postings under our slug.

    `uncheckable` deliberately does not fail: it is a permanent structural fact
    about an adapter, so failing on it would leave the check red forever and
    train everyone to ignore it. `denied` does not fail either — collection
    policy refusing a provider is our own decision, never evidence about a
    token. A `db_error` does fail, because a catalog-only pass has
    not checked the tokens that are actually being scraped.
    """
    states = [r["state"] for r in results]
    if DEAD in states or MISMATCH in states:
        return 1
    return 3 if (UNKNOWN in states or db_error) else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.add_argument("--delay", type=float, default=1.0, help="seconds between probes")
    parser.add_argument("--no-db", action="store_true",
                        help="probe the catalog only, skipping tokens in use")
    args = parser.parse_args()

    tracked: list[tuple[str, str | None, str | None]] = []
    db_error: str | None = None
    if not args.no_db:
        try:
            tracked = asyncio.run(tracked_tokens())
        except Exception as exc:  # noqa: BLE001 - any DB failure is the same answer here
            # Falling through to a catalog-only pass would print a clean report
            # while silently skipping the population that actually gets scraped,
            # the failure this check exists to catch. Say so, and never exit 0
            # on it.
            db_error = f"{type(exc).__name__}: {exc}"

    probes = build_probes(CATALOG, tracked)
    results = asyncio.run(check_all(args.delay, probes))
    dead = [r for r in results if r["state"] == DEAD]
    mismatch = [r for r in results if r["state"] == MISMATCH]
    unknown = [r for r in results if r["state"] == UNKNOWN]
    uncheckable = [r for r in results if r["state"] == UNCHECKABLE]
    denied = [r for r in results if r["state"] == DENIED]
    in_use = [r for r in results if r.get("origin") in (TRACKED_ONLY, BOTH)]
    confirmed = [r for r in results if r.get("identity") == CONFIRMED]

    if args.json:
        print(json.dumps({"results": results, "dead": len(dead), "mismatch": len(mismatch),
                          "unknown": len(unknown), "uncheckable": len(uncheckable),
                          "denied": len(denied), "in_use": len(in_use),
                          "identity_confirmed": len(confirmed), "db_error": db_error}, indent=2))
    else:
        _render(results)
        usable = len(results) - len(dead) - len(mismatch) - len(unknown) - len(uncheckable)
        print(f"\n{len(results)} probes ({len(in_use)} in use by a tracked company): "
              f"{usable} usable, {len(mismatch)} wrong company, {len(dead)} dead, "
              f"{len(uncheckable)} uncheckable, {len(denied)} denied, {len(unknown)} unknown")
        self_named = sum(r.get("identity") == SELF_NAMED for r in results)
        print(f"board identity confirmed for {len(confirmed)}; {self_named} named by their own "
              f"board (directory companies, nothing to compare); the rest state no name")
        if db_error:
            print(f"\ncould not read tracked companies: {db_error}\n"
                  f"catalog-only pass — tokens in use were NOT checked")

    return exit_code(results, db_error)


if __name__ == "__main__":
    sys.exit(main())
