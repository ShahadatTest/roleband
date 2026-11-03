"""Do the generated country terms actually FILTER?

Manifests are generated for all 196 countries from one rule per source
(`country_manifest`). That is only safe because each source's location filter
**fails closed**: a term it does not recognise returns nothing, so a wrong entry
under-collects rather than silently returning the whole board.

That property is the entire safety argument, and it is a claim about a live
system. `city[]` on amazon.jobs is the counter-example — it is silently ignored,
so a nonsense value returns all 10,000 results, and a manifest built on it would
re-collect the whole board once per country while reporting perfect coverage.

So this probes three things per source:

  control-nonsense  a term that cannot exist  -> MUST return ~nothing
  control-broad     a known-large country     -> must return a lot
  sample            a few real countries      -> whatever they have

and classifies each source:

  filters       nonsense returned far less than the broad control. Safe.
  IGNORES       nonsense returned about as much as broad. The manifest is a
                lie for this source and must be reverted to hand-written terms.
  unreachable   the probe could not reach the source at all (network, block).

Run:  .venv/bin/python -m scripts.check_location_coverage [--sample N]

Live network. Not part of pytest — the same rule as `scripts.check_catalog_tokens`
and `scripts.smoke_adapters`: live confidence is a script, not a test.
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from tracker.connectors.listing.accenture import (
    BOARD,
    FIND_JOBS,
    OWN_SEARCH_QUERIES,
    AccentureAdapter,
    board_country_facets,
    search_form,
)
from tracker.connectors.listing.amazon import _SEARCH_URL as AMAZON_URL
from tracker.connectors.listing.amazon import AmazonAdapter
from tracker.connectors.listing.apple import _SEARCH_URL as APPLE_URL
from tracker.connectors.listing.apple import AppleAdapter, search_body
from tracker.connectors.listing.apple_places import APPLE_COUNTRY_CODES
from tracker.connectors.listing.google import GoogleAdapter
from tracker.connectors.listing.microsoft import _DOMAIN as MS_DOMAIN
from tracker.connectors.listing.microsoft import _SEARCH_URL as MS_URL
from tracker.connectors.listing.microsoft import MicrosoftAdapter
from tracker.platform.ratelimit import RateLimiter
from tracker.taxonomy.countries import BY_SLUG

#: A term no source can resolve. If this returns roughly what a real country
#: returns, the filter is being ignored.
_NONSENSE = "Zzqqxnotaplace"
#: Real countries to spot-check. Broad first — it doubles as the control.
_SAMPLE = ("united_states", "india", "uae", "japan", "australia", "brazil")


async def _google_count(term: str) -> int | None:
    import re

    adapter = GoogleAdapter("google")
    adapter._limiter = RateLimiter(1.0)
    async with adapter:
        resp = await adapter.get(
            "https://www.google.com/about/careers/applications/jobs/results",
            params=[("page", "1"), ("sort_by", "date"), ("location", term)],
        )
        if resp.status_code != 200:
            return None
        match = re.search(r"of\s+([\d,]+)\s+rows", resp.text)
        return int(match.group(1).replace(",", "")) if match else 0


async def _amazon_count(term: str) -> int | None:
    """Amazon takes an ISO alpha-3 code, so the nonsense control is a bad CODE."""
    adapter = AmazonAdapter("amazon")
    adapter._limiter = RateLimiter(1.0)
    async with adapter:
        resp = await adapter.get(
            AMAZON_URL,
            params=[("result_limit", "10"), ("offset", "0"), ("normalized_country_code[]", term)],
        )
        if resp.status_code != 200:
            return None
        return int((resp.json() or {}).get("hits") or 0)


async def _microsoft_count(term: str) -> int | None:
    adapter = MicrosoftAdapter("microsoft")
    adapter._limiter = RateLimiter(1.0)
    async with adapter:
        resp = await adapter.get(
            MS_URL,
            params={
                "domain": MS_DOMAIN,
                "query": "",
                "location": term,
                "start": "0",
                "sort_by": "timestamp",
            },
        )
        if resp.status_code != 200:
            return None
        return int(((resp.json() or {}).get("data") or {}).get("count") or 0)


async def _apple_count(term: str) -> int | None:
    """Apple takes its own country code; a false zero is retried, as the adapter does."""
    adapter = AppleAdapter("apple")
    adapter._limiter = RateLimiter(1.0)
    body = search_body([f"postLocation-{term}"])
    async with adapter:
        if not await adapter._ensure_csrf():
            return None
        total = 0
        for _ in range(6):
            resp = await adapter.post(APPLE_URL, json=body, headers={"X-Apple-CSRF-Token": adapter._csrf or ""})
            try:
                total = int(((resp.json() or {}).get("res") or {}).get("totalRecords") or 0)
            except ValueError:
                continue
            if total:
                break
        return total


async def _accenture_board(adapter: AccentureAdapter, facets: dict) -> int | None:
    resp = await adapter.post(BOARD.cxs + "/jobs", json={"appliedFacets": facets, "limit": 1, "offset": 0, "searchText": ""})
    return resp.json().get("total") if resp.status_code == 200 else None


async def _accenture_board_count(term: str) -> int | None:
    """The board takes a facet id, so the nonsense control is a bad id.

    The board refuses an id it does not know with a 400 rather than answering
    zero: the filter is applied, so the refusal counts as no roles. A board that
    refused every id would read zero for the broad control too, and stays
    unreachable.
    """
    adapter = AccentureAdapter("accenture")
    adapter._limiter = RateLimiter(1.0)
    async with adapter:
        resp = await adapter.post(
            BOARD.cxs + "/jobs",
            json={"appliedFacets": {"locationCountry": [term]}, "limit": 1, "offset": 0, "searchText": ""},
        )
        if resp.status_code == 400:
            return 0
        return resp.json().get("total") if resp.status_code == 200 else None


_BOARD_IDS: dict[str, str] = {}


def _board_id(slug: str) -> str:
    return _BOARD_IDS.get(slug, "")


async def _accenture_recipes() -> list[tuple[str, int | None, int | None]]:
    """Each own-search country's total beside the board's exact count for it.

    A wrong recipe answers 0 like a country with no roles; the board is the
    referee. Fills `_BOARD_IDS` for the board probe.
    """
    adapter = AccentureAdapter("accenture")
    adapter._limiter = RateLimiter(1.0)
    rows: list[tuple[str, int | None, int | None]] = []
    async with adapter:
        resp = await adapter.post(BOARD.cxs + "/jobs", json={"appliedFacets": {}, "limit": 1, "offset": 0, "searchText": ""})
        ids, unknown = board_country_facets(resp.json() if resp.status_code == 200 else None)
        _BOARD_IDS.update(ids)
        if unknown:
            print(f"    !! the board names countries we cannot place: {', '.join(sorted(unknown))}")
        for slug, (query, *_) in OWN_SEARCH_QUERIES.items():
            form = search_form(query.country, query.site, 0, size=1, language=query.language)
            answer = await adapter.post(FIND_JOBS, data=form)
            own = (answer.json().get("totalHits") or {}).get("total") if answer.status_code == 200 else None
            board = await _accenture_board(adapter, {"locationCountry": [ids[slug]]}) if slug in ids else 0
            rows.append((slug, own, board))
    return rows


_SOURCES = {
    "google": (_google_count, lambda slug: BY_SLUG[slug].display, _NONSENSE),
    "microsoft": (_microsoft_count, lambda slug: BY_SLUG[slug].display, _NONSENSE),
    # Amazon's term is a code, so its nonsense control must also be a code shape.
    "amazon": (_amazon_count, lambda slug: BY_SLUG[slug].alpha3.upper(), "ZZQ"),
    # Apple's own codes (`scripts.build_apple_places`), never ISO ones.
    "apple": (_apple_count, lambda slug: APPLE_COUNTRY_CODES.get(slug, ""), "ZZQ"),
    "accenture-board": (_accenture_board_count, _board_id, "0" * 32),
}


async def probe(name: str, sample: int) -> dict:
    counter, term_for, nonsense = _SOURCES[name]
    out: dict = {"source": name, "countries": {}}
    try:
        out["nonsense"] = await counter(nonsense)
    except Exception as exc:  # noqa: BLE001 - a probe reports, never raises
        out["verdict"] = "unreachable"
        out["error"] = str(exc)[:120]
        return out

    for slug in _SAMPLE[:sample]:
        try:
            out["countries"][slug] = await counter(term_for(slug))
        except Exception as exc:  # noqa: BLE001
            out["countries"][slug] = f"ERR {str(exc)[:60]}"

    broad = out["countries"].get("united_states")
    nonsense_n = out["nonsense"]
    if nonsense_n is None or not isinstance(broad, int) or broad <= 0:
        out["verdict"] = "unreachable"
    elif nonsense_n >= broad * 0.5:
        # The filter did not narrow: a term that cannot exist returned about
        # what the largest real country returns.
        out["verdict"] = "IGNORES"
    else:
        out["verdict"] = "filters"
    return out


def _render(results: list[dict]) -> int:
    bad = 0
    for r in results:
        verdict = r["verdict"]
        print(f"\n=== {r['source']}: {verdict}")
        print(f"    nonsense control -> {r.get('nonsense')}")
        for slug, count in r["countries"].items():
            print(f"    {slug:16} -> {count}")
        if verdict == "IGNORES":
            bad += 1
            print(
                "    !! This source's filter does NOT narrow. Its generated manifest\n"
                "       would re-collect the whole board once per tracked country.\n"
                "       Revert it to hand-written, probed terms."
            )
        elif verdict == "unreachable":
            print("    (could not measure — network, block, or shape change)")
    print()
    return 1 if bad else 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--sample", type=int, default=len(_SAMPLE), help="countries to spot-check")
    ap.add_argument("--source", action="append", choices=sorted(_SOURCES))
    args = ap.parse_args()

    names = args.source or sorted(_SOURCES)

    async def run() -> tuple[list[dict], list]:
        recipes = await _accenture_recipes() if "accenture-board" in names else []
        return [await probe(name, args.sample) for name in names], recipes

    results, recipes = asyncio.run(run())
    status = _render(results)
    if recipes:
        print("=== accenture own search against the board, per recipe country")
        for slug, own, board in recipes:
            # The own search runs a few percent below the board's exact count
            # (the board also counts a posting's second places); far below
            # means the recipe broke.
            flag = "  !! recipe broken?" if isinstance(board, int) and board and (own or 0) < board * 0.7 else ""
            print(f"    {slug:16} own {own}  board {board}{flag}")
            status = status or (1 if flag else 0)
    return status


if __name__ == "__main__":
    sys.exit(main())
