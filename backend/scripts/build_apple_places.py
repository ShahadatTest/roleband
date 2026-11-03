"""Build Apple's country codes from Apple's own place lookup.

Apple's search filters by `postLocation-<code>`, and the code cannot be derived
from the country. An ISO alpha-3 code fails three ways: an unknown code answers
nothing (safe), `IND` names a US place rather than India (`INDC`), and `SWE`
names part of Sweden (`SWEC` is the whole country). The last one returns real
rows in the right country, so no check of the rows can catch it. Apple's lookup
is therefore the only source of a code:

    GET /api/v1/refData/postlocation?input=<name>
        -> {"res": [{"code": "SWEC", "level": 1, "name_en_US": "Sweden", ...}]}

A country's code is the `level == 1` entry whose name equals the country's
display name, search name or an alias, ignoring case. Never a prefix: "India"
also answers British Indian Ocean Territory, "Netherlands" Netherlands Antilles.
No match means no code, and the country stays a reported gap.

Each code is then searched once. Rows placed in another country reject it. A
zero is retried, because the search sometimes answers a false "0 results";
a code that answers zero every time is kept (the lookup is the authority) and
printed as unproven.

    .venv/bin/python -m scripts.build_apple_places             # report only
    .venv/bin/python -m scripts.build_apple_places --write     # rewrite the table
    .venv/bin/python -m scripts.build_apple_places --country sweden --country india
    .venv/bin/python -m scripts.build_apple_places --country serbia --write   # those rows only

Live network, one request a second. Not part of pytest, like
`scripts.check_location_coverage`. Writes
`tracker/connectors/listing/apple_places.py`.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from dataclasses import dataclass
from pathlib import Path

from tracker.connectors.listing.apple import _ORIGIN, _SEARCH_URL, AppleAdapter, search_body
from tracker.platform.ratelimit import RateLimiter
from tracker.taxonomy.countries import BY_SLUG, COUNTRIES, Country

_LOOKUP_URL = f"{_ORIGIN}/api/v1/refData/postlocation"
#: Apple's name for a country, where it is none of ours.
_APPLE_NAMES: dict[str, str] = {
    "dr_congo": "Congo (Democratic Republic)",
    "georgia": "Republic of Georgia",
    "laos": "Lao (People’s Democratic Republic)",
    "moldova": "Moldova (Republic of)",
    "north_macedonia": "Macedonia (Republic of)",
    "serbia": "Serbia (Republic of)",
    "south_korea": "Korea (Republic of)",
    "tanzania": "Tanzania (United Republic of)",
    "vatican": "Vatican City State (Holy See)",
}
#: Same budget as the adapter's soft-empty retries.
_ZERO_ATTEMPTS = 6
_TABLE = Path(__file__).resolve().parents[1] / "tracker/connectors/listing/apple_places.py"


@dataclass
class Found:
    country: Country
    code: str | None = None
    verdict: str = "no match"  # "verified", "unproven", "elsewhere", "no match", "unreadable"
    total: int = 0
    seen_in: tuple[str, ...] = ()


def _names(country: Country) -> list[str]:
    """Every name the country may go by, Apple's own first, without repeats."""
    names = [_APPLE_NAMES.get(country.slug, ""), country.display, country.query_name, *country.aliases]
    out: list[str] = []
    for name in names:
        if name and name.lower() not in {n.lower() for n in out}:
            out.append(name)
    return out


async def _answer(adapter: AppleAdapter, method: str, url: str, **kwargs: object) -> dict | None:
    """One JSON answer, retried: Apple sometimes answers 200 with a body that
    is not JSON. None when no attempt was readable."""
    for _ in range(_ZERO_ATTEMPTS):
        resp = await adapter.request(
            method, url, headers={"X-Apple-CSRF-Token": adapter._csrf or ""}, **kwargs
        )
        if resp.status_code != 200:
            continue
        try:
            body = resp.json()
        except ValueError:
            continue
        if isinstance(body, dict):
            return body
    return None


async def _lookup(adapter: AppleAdapter, text: str) -> list[dict] | None:
    """The lookup's entries for `text`; None when Apple never answered readably."""
    body = await _answer(adapter, "GET", _LOOKUP_URL, params={"input": text})
    if body is None:
        return None
    rows = body.get("res")
    return [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []


async def _search(adapter: AppleAdapter, code: str) -> tuple[int, set[str]]:
    """The code's total and the countries its first page is placed in."""
    body = search_body([f"postLocation-{code}"])
    for _ in range(_ZERO_ATTEMPTS):
        res = (await _answer(adapter, "POST", _SEARCH_URL, json=body) or {}).get("res") or {}
        total = res.get("totalRecords")
        if isinstance(total, int) and total > 0:
            places = {
                str(loc.get("countryName") or "").lower()
                for row in res.get("searchResults") or []
                for loc in row.get("locations") or []
                if isinstance(loc, dict)
            }
            return total, places
    return 0, set()


async def _find(adapter: AppleAdapter, country: Country) -> Found:
    found = Found(country)
    wanted = {name.lower() for name in _names(country)}
    for name in _names(country):
        entries = await _lookup(adapter, name)
        if entries is None:
            # Not "no match": a lookup that never answered says nothing.
            found.verdict = "unreadable"
            return found
        for entry in entries:
            label = str(entry.get("name_en_US") or entry.get("name") or "").lower()
            if str(entry.get("level")) == "1" and label in wanted and entry.get("code"):
                found.code = str(entry["code"])
                break
        if found.code:
            break
    if not found.code:
        return found
    found.total, places = await _search(adapter, found.code)
    found.seen_in = tuple(sorted(places))
    if not found.total:
        found.verdict = "unproven"
    elif places & wanted:
        found.verdict = "verified"
    else:
        found.verdict = "elsewhere"
    return found


def _shipped() -> dict[str, str]:
    """The table as shipped; empty before the first write."""
    try:
        from tracker.connectors.listing.apple_places import APPLE_COUNTRY_CODES
    except ImportError:
        return {}
    return dict(APPLE_COUNTRY_CODES)


def _render_table(codes: dict[str, str]) -> str:
    rows = sorted(codes.items())
    lines = [
        '"""Apple\'s `postLocation` code for each country, slug to code.',
        "",
        "Written by `scripts.build_apple_places` from Apple's own place lookup; edit",
        "by rerunning it. A country missing here has no code Apple's lookup names, and",
        "stays a reported coverage gap.",
        '"""',
        "",
        "APPLE_COUNTRY_CODES: dict[str, str] = {",
        *(f'    "{slug}": "{code}",' for slug, code in rows),
        "}",
        "",
    ]
    return "\n".join(lines)


async def _run(slugs: list[str]) -> list[Found]:
    adapter = AppleAdapter("apple")
    adapter._limiter = RateLimiter(1.0)
    found: list[Found] = []
    async with adapter:
        if not await adapter._ensure_csrf():
            raise SystemExit("Apple answered no CSRF token; nothing was looked up.")
        for country in [BY_SLUG[s] for s in slugs] if slugs else COUNTRIES:
            item = await _find(adapter, country)
            found.append(item)
            print(f"{country.slug:28} {item.code or '-':10} {item.verdict:10} {item.total}", flush=True)
    return found


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--write", action="store_true", help="rewrite apple_places.py; with --country, only those rows")
    ap.add_argument("--country", action="append", default=[], choices=sorted(BY_SLUG), metavar="SLUG")
    args = ap.parse_args()
    found = asyncio.run(_run(args.country))
    print()
    for verdict in ("elsewhere", "unreadable", "unproven", "no match"):
        items = [f for f in found if f.verdict == verdict]
        if items:
            print(f"{verdict} ({len(items)}):")
            for f in items:
                print(f"    {f.country.slug} {f.code or ''} {', '.join(f.seen_in)}")
    print(f"verified: {sum(f.verdict == 'verified' for f in found)} of {len(found)}")
    # What a rerun would change in the shipped table: the monthly check. With
    # --country only the named rows are read, so only they can change.
    shipped = _shipped()
    fresh = {f.country.slug: f.code for f in found if f.code and f.verdict in ("verified", "unproven")}
    read = {f.country.slug for f in found}
    table = {**{slug: code for slug, code in shipped.items() if slug not in read}, **fresh}
    for slug in sorted(set(shipped) | set(table)):
        if shipped.get(slug) != table.get(slug):
            print(f"changed: {slug} {shipped.get(slug)} -> {table.get(slug)}")
    unreadable = [f.country.slug for f in found if f.verdict == "unreadable"]
    if args.write and unreadable:
        # A table written now would drop countries Apple has codes for.
        print(f"not written: {len(unreadable)} lookups never answered; rerun")
        return 1
    if args.write:
        _TABLE.write_text(_render_table(table))
        print(f"wrote {_TABLE}")
    # Rows placed elsewhere mean the lookup and the search disagree: look by hand.
    return 1 if any(f.verdict in ("elsewhere", "unreadable") for f in found) else 0


if __name__ == "__main__":
    sys.exit(main())
