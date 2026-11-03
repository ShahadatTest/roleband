"""What would Greenhouse's `?pay_transparency=true` actually buy?

The selective Greenhouse pay-detail fetch waits on a measured benefit:
requests, disclosures gained, duration and response bytes, measured before
enabling it broadly. This is that measurement.

The flag adds exactly one key to the detail response — `pay_input_ranges`, a
list of `{min_cents, max_cents, currency_type, title, blurb}` — and costs one
request per posting on top of the single listing request that already returns
every posting's `content`.

TWO ARMS, because "gained" is two different questions and only one of them is
about coverage.

**Coverage** — how many postings gain a structured tier at all, and how many of
those already state the amount in the `content` HTML the listing hands us for
free. A posting whose pay is in the prose is already reachable by the on-device
disclosed-comp pass at zero extra requests, so it is not a disclosure gained;
it is the same disclosure, structured. Only the `structured_only` cell is a
disclosure that no current code path can reach.

**Value** — where RoleBand already stores a band for a posting, does the
employer's own structured range AGREE with it? This is the arm that can find a
defect rather than an increment: a disagreement means the number on the
dashboard is wrong today, which is a different reason to implement the fetch than
"more rows covered", and would outrank it.

NEGATIVE CONTROL, without which this measures nothing. A fraction of postings
are fetched a second time WITHOUT the flag, and `pay_input_ranges` must be
absent. If the field arrives regardless, then the cost being weighed is the
detail request and the flag is free — a materially different trade, and one the
benchmark would otherwise silently get backwards.

Deliberately a script and not a test: tests never fetch live sources
(`docs/testing.md`). The classification is pure and is tested offline
(`tests/test_bench_pay_transparency.py`); only the fetching lives here.

    0  completed
    2  refused (a tenant argument that is not a Greenhouse board)
    3  UNKNOWN — could not complete (network/DB); not a verdict

Usage (from `backend/`):

    .venv/bin/python -m scripts.bench_pay_transparency
    .venv/bin/python -m scripts.bench_pay_transparency --sample 4 --value-sample 10
    .venv/bin/python -m scripts.bench_pay_transparency --tenants anthropic --json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import re
import sys
import time

import httpx
from sqlalchemy import text

from tracker.company_catalog import CATALOG
from tracker.config import get_settings
from tracker.connectors.listing.greenhouse import BOARD_TOKENS
from tracker.db.session import session_scope
from tracker.source_policy import collection_access

_ADAPTER = "greenhouse"
_BOARD = "https://boards-api.greenhouse.io/v1/boards"

#: A currency amount stated in the posting body: an amount ADJACENT to a symbol
#: or an ISO code, in either order. This stands in for "the disclosed-comp pass
#: has something to read", not for what it parses.
#:
#: The currency list is long on purpose: reading only `$€£`/`USD|EUR|GBP|CAD`
#: would count a body stating `₹9,424,500—₹9,424,500 INR` or
#: `503,500 د.إ—530,000 د.إ` as a disclosure reachable ONLY through the flag,
#: wrong in the direction that flatters the change being evaluated. A benchmark
#: that cannot read the world's currencies measures US pay transparency and
#: reports it as a global gain.
_CURRENCY = (r"[$€£¥₹₩﷼]|د\.?إ|\b(?:USD|EUR|GBP|CAD|AUD|INR|AED|SGD|JPY|CHF|SEK|NOK"
             r"|DKK|PLN|BRL|MXN|ILS|NZD|HKD|KRW|ZAR|CNY|TWD|THB|IDR|PHP|MYR)\b")
#: How employers actually spell an amount, in the order the alternatives should
#: be tried. Reading only comma-grouped and 4+-digit runs would be biased in
#: the direction that flatters the change being evaluated, like the currency
#: list above, in a second dimension:
#:
#: * `$15.65 – $20.00 per hour`: an hourly rate never reaches four digits and
#:   carries no comma, so an hourly board would read as prose stating no pay at
#:   all, and the flag's hourly ranges (`min_cents: 1565`) are exactly those;
#: * `$120K – $180K`: the ordinary abbreviated annual band.
#:
#: A miss on either counts the posting `structured_only`, the cell that means "a
#: disclosure NO current code path can reach", which is the cell the gain is
#: drawn from. Erring toward matching is the safe direction here: a false match moves
#: a posting to `both` and shrinks the claimed gain, while a miss inflates it.
_AMOUNT = (r"\d{1,3}(?:,\d{3})+(?:\.\d+)?"      # 120,000
           r"|\d+(?:\.\d+)?\s?[KkMm]\b"          # 120K, 1.2M
           r"|\d+\.\d{2}\b"                      # 15.65
           r"|\d{4,}(?:\.\d+)?")                 # 120000
#: Adjacency is what keeps a requisition id, an employee count or a year from
#: reading as pay — the numbers that actually appear in these bodies.
_MONEY = re.compile(rf"(?:{_CURRENCY})\s?(?:{_AMOUNT})|(?:{_AMOUNT})\s?(?:{_CURRENCY})", re.I)

#: Coverage cells. Only `structured_only` is a disclosure no current code path
#: can reach; `both` is the same disclosure in a better shape.
STRUCTURED_ONLY = "structured_only"
BOTH = "both"
TEXT_ONLY = "text_only"
NEITHER = "neither"

#: Value cells, comparing a stored band against the employer's own range.
AGREE = "agree"
DIFFER = "differ"
SOURCE_SILENT = "source_silent"


def greenhouse_tenants() -> dict[str, str]:
    """Every Greenhouse tenant RoleBand can reach: catalog plus the built-in map.

    The built-in half matters because a company with no catalog row still
    scrapes an effective token, and the enabled Greenhouse tenants can be
    exactly those, so measuring the catalog alone could measure the population
    we are NOT collecting from.
    """
    tenants = {slug: entry["board_token"] for slug, entry in CATALOG.items()
               if entry["adapter"] == _ADAPTER}
    return {**tenants, **BOARD_TOKENS}


def classify_coverage(pay_ranges: list | None, content: str | None) -> str:
    """Which coverage cell one posting falls in."""
    structured = bool(pay_ranges)
    in_text = bool(content and _MONEY.search(content))
    if structured and in_text:
        return BOTH
    if structured:
        return STRUCTURED_ONLY
    return TEXT_ONLY if in_text else NEITHER


def classify_value(stored: tuple[int | None, int | None], pay_ranges: list | None) -> str:
    """Does the employer's own range agree with the band we already store?

    Compared on whole dollars against the FIRST tier only, and a multi-tier
    posting is never collapsed into an invented span. `differ` is
    therefore conservative in the direction that matters: it can under-report a
    disagreement, never invent one.
    """
    if not pay_ranges:
        return SOURCE_SILENT
    tier = pay_ranges[0]
    low = tier.get("min_cents")
    high = tier.get("max_cents")
    source = (low // 100 if isinstance(low, int) else None,
              high // 100 if isinstance(high, int) else None)
    return AGREE if source == stored else DIFFER


class Fetcher:
    """Paced GETs with per-request bytes and duration, so cost is measured."""

    def __init__(self, client: httpx.AsyncClient, delay: float) -> None:
        self._client = client
        self._delay = delay
        self._first = True
        self.requests = 0
        self.bytes = 0
        self.seconds = 0.0

    async def get(self, url: str, params: dict | None = None) -> tuple[int, bytes]:
        if not self._first:
            # The same public API the adapter uses; a burst from a bench script
            # is still a burst.
            await asyncio.sleep(self._delay)
        self._first = False
        started = time.monotonic()
        response = await self._client.get(url, params=params)
        self.seconds += time.monotonic() - started
        self.requests += 1
        self.bytes += len(response.content)
        return response.status_code, response.content


async def measure_tenant(fetch: Fetcher, slug: str, token: str, sample: int,
                         rng: random.Random, control_every: int) -> dict:
    row: dict = {"slug": slug, "token": token, "cells": dict.fromkeys(
        (STRUCTURED_ONLY, BOTH, TEXT_ONLY, NEITHER), 0)}
    status, body = await fetch.get(f"{_BOARD}/{token}/jobs", {"content": "true"})
    if status != 200:
        return {**row, "error": f"listing HTTP {status}"}
    try:
        postings = json.loads(body).get("jobs") or []
    except ValueError:
        return {**row, "error": "listing non-JSON"}
    row["board_size"] = len(postings)
    if not postings:
        return {**row, "error": "empty board"}

    picked = rng.sample(postings, min(sample, len(postings)))
    row["sampled"] = len(picked)
    controls_clean = controls_run = 0
    for index, posting in enumerate(picked):
        job_id = posting.get("id")
        status, body = await fetch.get(f"{_BOARD}/{token}/jobs/{job_id}",
                                       {"pay_transparency": "true"})
        if status != 200:
            row["cells"][NEITHER] += 1
            continue
        detail = json.loads(body)
        # The listing already carries `content`; the detail request is being
        # weighed for `pay_input_ranges` alone, so the text signal is read off
        # the free copy.
        ranges = detail.get("pay_input_ranges")
        cell = classify_coverage(ranges, posting.get("content"))
        row["cells"][cell] += 1
        for tier in ranges or []:
            # The interval is nowhere in the payload; the only thing that says
            # whether 1565 cents is hourly or annual is this tenant-authored
            # free-text label. Recorded so the hazard is measured, not asserted.
            row.setdefault("titles", []).append(
                {"title": tier.get("title"), "currency": tier.get("currency_type"),
                 "min_cents": tier.get("min_cents"), "max_cents": tier.get("max_cents")}
            )
        if control_every and index % control_every == 0:
            status, body = await fetch.get(f"{_BOARD}/{token}/jobs/{job_id}")
            if status == 200:
                controls_run += 1
                controls_clean += int("pay_input_ranges" not in json.loads(body))
    row["controls_run"] = controls_run
    row["controls_clean"] = controls_clean
    return row


async def stored_bands(limit: int, rng: random.Random) -> list[dict]:
    """Postings we already hold a band for, with the tenant token to fetch them."""
    async with session_scope() as session:
        rows = (await session.execute(text("""
            SELECT j.company, j.req_id, j.disclosed_base_min AS lo, j.disclosed_base_max AS hi
            FROM jobs j JOIN tracked_company tc ON tc.slug = j.company
            WHERE tc.adapter = :adapter AND j.status = 'open'
              AND j.disclosed_base_min IS NOT NULL
        """), {"adapter": _ADAPTER})).all()
    picked = rng.sample(list(rows), min(limit, len(rows)))
    return [{"company": r.company, "req_id": r.req_id, "stored": (r.lo, r.hi)} for r in picked]


async def measure_value(fetch: Fetcher, tenants: dict[str, str], rows: list[dict]) -> dict:
    cells = dict.fromkeys((AGREE, DIFFER, SOURCE_SILENT), 0)
    disagreements: list[dict] = []
    for row in rows:
        token = tenants.get(row["company"], row["company"])
        status, body = await fetch.get(f"{_BOARD}/{token}/jobs/{row['req_id']}",
                                       {"pay_transparency": "true"})
        if status != 200:
            continue
        ranges = json.loads(body).get("pay_input_ranges")
        cell = classify_value(row["stored"], ranges)
        cells[cell] += 1
        if cell == DIFFER:
            tier = ranges[0]
            disagreements.append({
                "company": row["company"], "req_id": row["req_id"],
                "stored": row["stored"],
                "source": (tier.get("min_cents"), tier.get("max_cents")),
                "title": tier.get("title"),
            })
    return {"cells": cells, "compared": len(rows), "disagreements": disagreements}


def render(results: list[dict], value: dict, fetch: Fetcher) -> None:
    print(f"\n{'tenant':14s} {'board':>6s} {'n':>4s} "
          f"{'struct-only':>11s} {'both':>6s} {'text-only':>9s} {'neither':>8s}")
    totals = dict.fromkeys((STRUCTURED_ONLY, BOTH, TEXT_ONLY, NEITHER), 0)
    sampled = 0
    for row in results:
        if row.get("error"):
            print(f"{row['slug']:14s} {'-':>6s} {'-':>4s}   {row['error']}")
            continue
        cells = row["cells"]
        for key, count in cells.items():
            totals[key] += count
        sampled += row["sampled"]
        print(f"{row['slug']:14s} {row['board_size']:6d} {row['sampled']:4d} "
              f"{cells[STRUCTURED_ONLY]:11d} {cells[BOTH]:6d} "
              f"{cells[TEXT_ONLY]:9d} {cells[NEITHER]:8d}")
    print(f"{'TOTAL':14s} {'':>6s} {sampled:4d} "
          f"{totals[STRUCTURED_ONLY]:11d} {totals[BOTH]:6d} "
          f"{totals[TEXT_ONLY]:9d} {totals[NEITHER]:8d}")

    controls_run = sum(r.get("controls_run", 0) for r in results)
    controls_clean = sum(r.get("controls_clean", 0) for r in results)
    print(f"\nnegative control: {controls_clean}/{controls_run} unflagged responses carried "
          f"no `pay_input_ranges`"
          + ("" if controls_clean == controls_run else "  <-- THE FLAG IS NOT WHAT ADDS IT"))

    if sampled:
        gained = totals[STRUCTURED_ONLY]
        structured = gained + totals[BOTH]
        print(f"structured tier on {structured}/{sampled} sampled postings "
              f"({structured / sampled:.0%}); of those, {gained} state no amount in "
              f"`content` — the only cell no current code path can reach "
              f"({gained / sampled:.0%} of sampled).")

    tiers = [t for r in results for t in r.get("titles", [])]
    if tiers:
        labels: dict[tuple[str, str], list[int]] = {}
        for tier in tiers:
            cents = tier.get("min_cents")
            if isinstance(cents, int):
                key = ((tier.get("title") or "").strip(), tier.get("currency_type") or "?")
                labels.setdefault(key, []).append(cents)
        hourly = sum(1 for t in tiers if isinstance(t.get("min_cents"), int)
                     and t["min_cents"] < 100_000)
        currencies = {t.get("currency_type") for t in tiers}
        print(f"\ninterval carrier: {len(tiers)} tiers, {len(labels)} distinct "
              f"(label, currency) pairs across {len(currencies)} currencies; {hourly} carry "
              f"a minor-unit amount under 100,000 (an hourly or per-period figure, not an "
              f"annual base)")
        # Grouped WITH the currency: printing an INR tier as dollars is the
        # exact conflation an implementation would make if it read the amount
        # and not the unit.
        for (label, code), amounts in sorted(labels.items(), key=lambda kv: -len(kv[1]))[:10]:
            print(f"  {len(amounts):3d}x [{code}] {label[:60]!r} "
                  f"{min(amounts) / 100:,.0f}-{max(amounts) / 100:,.0f}")

    cells = value["cells"]
    compared = sum(cells.values())
    print(f"\nvalue arm: {compared} stored bands compared — "
          f"{cells[AGREE]} agree, {cells[DIFFER]} differ, "
          f"{cells[SOURCE_SILENT]} the source states no range")
    for bad in value["disagreements"][:10]:
        print(f"  DIFFER {bad['company']}/{bad['req_id']}: stored {bad['stored']} "
              f"vs source {bad['source']} cents ({bad['title']})")

    per = fetch.seconds / fetch.requests if fetch.requests else 0
    print(f"\ncost: {fetch.requests} requests, {fetch.bytes / 1_048_576:.1f} MiB, "
          f"{fetch.seconds:.1f}s in-flight ({per * 1000:.0f} ms/request, pacing excluded)")


async def main_async(args: argparse.Namespace) -> int:
    tenants = greenhouse_tenants()
    if args.tenants:
        unknown = [t for t in args.tenants if t not in tenants]
        if unknown:
            print(f"not Greenhouse tenants: {', '.join(unknown)}", file=sys.stderr)
            print(f"valid: {', '.join(sorted(tenants))}", file=sys.stderr)
            return 2
        tenants = {slug: tenants[slug] for slug in args.tenants}

    # Collection policy first, and before any socket: this script
    # builds its own client, so no transport-level gate can see it.
    access = collection_access(_ADAPTER)
    if access.denied:
        print(f"refused by collection policy: {access.reason}", file=sys.stderr)
        return 0

    settings = get_settings()
    rng = random.Random(args.seed)
    headers = {"accept": "application/json", "user-agent": settings.scraper_user_agent}
    try:
        value_rows = await stored_bands(args.value_sample, rng)
    except Exception as exc:  # noqa: BLE001 - a DB failure is UNKNOWN, not a verdict
        print(f"could not read stored bands: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 3

    async with httpx.AsyncClient(timeout=30, follow_redirects=True, headers=headers) as client:
        fetch = Fetcher(client, settings.scraper_min_delay_seconds)
        try:
            results = [await measure_tenant(fetch, slug, token, args.sample, rng, args.control_every)
                       for slug, token in sorted(tenants.items())]
            value = await measure_value(fetch, tenants, value_rows)
        except httpx.HTTPError as exc:
            print(f"network failure: {type(exc).__name__}: {exc}", file=sys.stderr)
            return 3

    if args.json:
        print(json.dumps({"coverage": results, "value": value,
                          "cost": {"requests": fetch.requests, "bytes": fetch.bytes,
                                   "seconds": round(fetch.seconds, 2)}}, indent=2, default=str))
    else:
        render(results, value, fetch)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--tenants", nargs="*", help="limit to these company slugs")
    parser.add_argument("--sample", type=int, default=10, help="postings per tenant (default 10)")
    parser.add_argument("--value-sample", type=int, default=40,
                        help="stored bands to compare against the source (default 40)")
    parser.add_argument("--control-every", type=int, default=5,
                        help="unflagged control request every Nth posting (0 disables)")
    parser.add_argument("--seed", type=int, default=20260910, help="sampling seed")
    parser.add_argument("--json", action="store_true")
    return asyncio.run(main_async(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
