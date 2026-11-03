"""Regenerate `tracker/taxonomy/countries.py` from the pinned upstream dataset.

Dev-only. The generated table is committed and reviewed in diff; nothing at
runtime fetches or parses the dataset, so RoleBand takes no dependency on it. The
pin lives in `tracker.vendored` (`country-table`), which is what makes
"has upstream moved?" decidable — the same contract `scripts.check_vendored_upstream`
enforces for the extract sanitizer.

Hand-authoring ~195 countries with ISO codes and centroids invites drift: a
hand-copied mirror silently falls behind. Generating means the country data has
one source and a checkable provenance.

Run:  .venv/bin/python -m scripts.gen_country_table [--check]

`--check` regenerates into memory and diffs against the committed file, exiting
non-zero on drift. That is the CI-safe form.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import unicodedata
from pathlib import Path

import httpx

from tracker.vendored import by_name

_OUT = Path(__file__).resolve().parents[1] / "tracker" / "taxonomy" / "countries.py"
#: The dashboard mirror. Generated from the same rows so the two cannot drift.
_TS_OUT = (
    Path(__file__).resolve().parents[2] / "dashboard" / "src" / "locations.gen.ts"
)
#: Unions in a module of their own: only the Profile's lazy chunk reads them,
#: and inside `locations.gen.ts` they would ride in the app shell.
_TS_UNIONS_OUT = _TS_OUT.with_name("unions.gen.ts")

# --------------------------------------------------------------------------- #
# Region assignment.
#
# Upstream ships UN M49 `region`/`subregion`. Those are geographic; ours are the
# groupings a job seeker actually reasons about, so a few deliberately diverge:
# Mexico is Latin America rather than "North America", Cyprus is Europe rather
# than "Western Asia", and the six GCC states get their own group nested under
# the Middle East because "Gulf" is how those roles are advertised.
# --------------------------------------------------------------------------- #

_SUBREGION_TO_GROUP = {
    "North America": "north_america",
    "Central America": "latin_america",
    "South America": "latin_america",
    "Caribbean": "latin_america",
    "Northern Europe": "europe",
    "Western Europe": "europe",
    "Southern Europe": "europe",
    "Eastern Europe": "europe",
    "Central Europe": "europe",
    "Southeast Europe": "europe",
    "Western Asia": "middle_east",
    "Central Asia": "central_asia",
    "Southern Asia": "south_asia",
    "Eastern Asia": "east_asia",
    "South-Eastern Asia": "southeast_asia",
    "Northern Africa": "africa",
    "Western Africa": "africa",
    "Middle Africa": "africa",
    "Eastern Africa": "africa",
    "Southern Africa": "africa",
    "Australia and New Zealand": "oceania",
    "Melanesia": "oceania",
    "Micronesia": "oceania",
    "Polynesia": "oceania",
}

#: GCC states — advertised as "the Gulf", so they get a group of their own.
_GULF = {"ARE", "SAU", "QAT", "KWT", "BHR", "OMN"}

#: Region overrides where the geographic answer is not the job-market one.
_REGION_OVERRIDE = {
    "MEX": "latin_america",  # upstream files it under Northern America
    "CYP": "europe",         # EU member, upstream files it under Western Asia
    "TUR": "middle_east",
    "RUS": "europe",
}

#: Non-UN-members that are nonetheless real hiring markets.
_EXTRA = {"TWN", "HKG", "MAC"}

#: Slug overrides. Only where the generated slug would break an EXISTING slug
#: (a renamed slug is silently dropped from a user's saved scope by
#: `settings_store._get_enabled_slugs`) or would be absurdly long.
_SLUG_OVERRIDE = {
    "GBR": "uk",                       # pre-existing slug; must not move
    "ARE": "uae",                      # united_arab_emirates is unusable in UI
    "USA": "united_states",            # pre-existing (matches natural slug)
    "VAT": "vatican",
    "COD": "dr_congo",
    "COG": "congo_republic",
    "PRK": "north_korea",
    "KOR": "south_korea",
    "LAO": "laos",
    "SYR": "syria",
    "BRN": "brunei",
    "CPV": "cape_verde",
    "TLS": "timor_leste",
    "MMR": "myanmar",
    "CIV": "ivory_coast",
    "SWZ": "eswatini",
    "CZE": "czechia",
}

#: Countries a global tech employer plausibly posts in. Display-only: it decides
#: what Settings shows before "show all", never what a posting can match.
_PROMINENT = {
    # North America
    "USA", "CAN", "MEX",
    # Europe
    "GBR", "IRL", "DEU", "FRA", "NLD", "CHE", "ESP", "ITA", "POL", "SWE", "NOR",
    "DNK", "FIN", "PRT", "AUT", "BEL", "CZE", "ROU", "HUN", "GRC", "EST", "LTU",
    "LVA", "HRV", "BGR", "SRB", "UKR", "LUX",
    # Middle East + Gulf
    "ISR", "ARE", "SAU", "QAT", "KWT", "BHR", "OMN", "TUR", "JOR", "EGY",
    # South Asia
    "IND", "PAK", "BGD", "LKA",
    # East Asia
    "JPN", "CHN", "KOR", "TWN", "HKG",
    # Southeast Asia
    "SGP", "MYS", "IDN", "THA", "VNM", "PHL",
    # Oceania
    "AUS", "NZL",
    # Latin America
    "BRA", "ARG", "CHL", "COL", "PER", "URY", "CRI",
    # Africa
    "ZAF", "NGA", "KEN", "MAR", "GHA", "TUN",
}


def _slug(name: str) -> str:
    """`United States` -> `united_states`. ASCII-folded, punctuation dropped."""
    folded = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    return re.sub(r"_+", "_", re.sub(r"[^a-z0-9]+", "_", folded.lower())).strip("_")


#: Bare names boards state that upstream lists for no country. Each is a
#: measured board string, and each is unambiguous where jobs are posted.
#: "Korea": a board's bare name for the country; no employer posts in
#: North Korea, and ISO's own name for KOR is "Korea, Republic of".
_EXTRA_ALIASES: dict[str, tuple[str, ...]] = {"KOR": ("korea",)}


def _aliases(row: dict, slug: str) -> list[str]:
    """Match tokens for this country, EXCLUDING its alpha-2 code.

    Alpha-2 is admitted separately and only when it does not collide with a US
    state abbreviation — see `taxonomy.locations`. Upstream's `altSpellings`
    leads with the alpha-2, so it is filtered here rather than trusted.
    """
    out: list[str] = []
    names = row.get("name") or {}
    for candidate in (
        names.get("common"),
        names.get("official"),
        *(row.get("altSpellings") or []),
    ):
        if not isinstance(candidate, str):
            continue
        low = unicodedata.normalize("NFKD", candidate).encode("ascii", "ignore").decode()
        low = low.strip().lower()
        # Two-letter tokens are alpha-2 codes or noise; both are handled by the
        # collision rule, never by the free-text alias list.
        if len(low) < 3 or low in out:
            continue
        out.append(low)
    if slug.replace("_", " ") not in out:
        out.append(slug.replace("_", " "))
    out.extend(extra for extra in _EXTRA_ALIASES.get(row["cca3"], ()) if extra not in out)
    return out


def _region_for(row: dict) -> str | None:
    code = row["cca3"]
    if code in _GULF:
        return "gulf"
    if code in _REGION_OVERRIDE:
        return _REGION_OVERRIDE[code]
    return _SUBREGION_TO_GROUP.get(row.get("subregion") or "")


def _cldr_display(alpha2: str, names: dict[str, str], fallback: str) -> str:
    """The CLDR English name for a territory: what iOS, Android,
    Chrome and ICU display. The standard form, except where it carries a
    qualifier in brackets or "SAR China" and CLDR offers a short form: Hong
    Kong, Macao and Myanmar read as people say them."""
    code = alpha2.upper()
    standard = names.get(code)
    if not standard:
        return fallback
    short = names.get(f"{code}-alt-short")
    if short and ("(" in standard or "SAR China" in standard):
        return short
    return standard


def _fold(text: str) -> str:
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().strip().lower()


def build_rows(data: list[dict], cldr: dict[str, str] | None = None) -> list[dict]:
    cldr = cldr or {}
    rows = []
    for row in data:
        code = row["cca3"]
        if not (row.get("unMember") or code in _EXTRA):
            continue
        region = _region_for(row)
        if region is None:
            # LOUD, never skipped. Silently dropping an unmapped subregion
            # (`Northern America` vs `North America`) would quietly delete the
            # United States and Canada from the table, the exact class of
            # invisible omission this whole taxonomy exists to end. An
            # unmapped subregion is a mapping bug; say so.
            raise SystemExit(
                f"{code} ({row.get('subregion')!r}) has no region mapping — "
                "add it to _SUBREGION_TO_GROUP or _REGION_OVERRIDE"
            )
        common = (row.get("name") or {}).get("common") or code
        slug = _SLUG_OVERRIDE.get(code, _slug(common))
        lat, lng = (row.get("latlng") or [0, 0])[:2]
        alpha2 = (row.get("cca2") or "").lower()
        aliases = _aliases(row, slug)
        # Every CLDR form is also a match token, so "Türkiye", "Côte d'Ivoire"
        # and "Congo (DRC)" resolve as well as the names they replaced.
        for key in (alpha2.upper(), f"{alpha2.upper()}-alt-short", f"{alpha2.upper()}-alt-variant"):
            name = cldr.get(key)
            folded = _fold(name) if name else ""
            if len(folded) >= 3 and folded not in aliases:
                aliases.append(folded)
        rows.append(
            {
                "slug": slug,
                "display": _cldr_display(alpha2, cldr, common),
                # What a source's own search box is sent (google, microsoft,
                # workday): the name the manifests were measured with. A display
                # rename must not silently change what we ask a board for.
                "query_name": common,
                "alpha2": alpha2,
                "alpha3": code.lower(),
                "region": region,
                # (lon, lat) — map order, the inverse of upstream's latlng.
                "centroid": (round(float(lng), 2), round(float(lat), 2)),
                "aliases": aliases,
                "prominent": code in _PROMINENT,
            }
        )
    rows.sort(key=lambda r: r["slug"])
    dupes = {r["slug"] for r in rows if sum(1 for o in rows if o["slug"] == r["slug"]) > 1}
    if dupes:
        raise SystemExit(f"duplicate slugs generated: {sorted(dupes)}")
    return rows


_HEADER = '''"""ISO 3166-1 countries with region, centroid and match vocabulary.

GENERATED by `scripts/gen_country_table.py` — do not edit by hand.

Derived from mledoze/countries, licensed ODbL-1.0; pinned in `tracker.vendored`
as `country-table`. Display names are Unicode CLDR English (licence
Unicode-3.0; `cldr-territory-names`), the names the world's software shows; the
European Union's members are CLDR's grouping (`cldr-territory-containment`).
Region assignment is RoleBand's own and deliberately diverges from UN M49 where
the job market does.

`aliases` deliberately excludes alpha-2 codes: `taxonomy.locations` admits those
separately and only where they do not collide with a US state abbreviation, so
`IN` never reads as India inside "Indianapolis, IN, USA".
"""

from __future__ import annotations

from typing import NamedTuple


class Country(NamedTuple):
    slug: str
    #: CLDR English name.
    display: str
    alpha2: str
    alpha3: str
    region: str
    #: (lon, lat) — map order.
    centroid: tuple[float, float]
    #: Free-text match tokens, never alpha-2.
    aliases: tuple[str, ...]
    #: Shown in Settings before "show all"; display-only, never matching.
    prominent: bool
    #: The name a source's search box is sent (see `country_manifest`).
    query_name: str


class Union(NamedTuple):
    """A political union, as CLDR groups its members."""

    slug: str
    display: str
    members: tuple[str, ...]


COUNTRIES: tuple[Country, ...] = (
'''

_FOOTER = ''')


BY_SLUG: dict[str, Country] = {c.slug: c for c in COUNTRIES}

UNIONS: tuple[Union, ...] = (
{unions}
)
'''


def build_unions(rows: list[dict], cldr: dict[str, str], containment: dict) -> list[dict]:
    """Political unions with CLDR's membership, mapped onto our slugs."""
    by_alpha2 = {r["alpha2"].upper(): r["slug"] for r in rows}
    unions = []
    for code, slug in (("EU", "european_union"),):
        members = containment.get(code, {}).get("_contains", [])
        unions.append({
            "slug": slug,
            "display": cldr.get(code, code),
            "members": sorted(by_alpha2[m] for m in members if m in by_alpha2),
        })
    return unions


def render(rows: list[dict], unions: list[dict]) -> str:
    body = []
    for r in rows:
        aliases = ", ".join(repr(a) for a in r["aliases"])
        body.append(
            f"    Country({r['slug']!r}, {r['display']!r}, {r['alpha2']!r}, "
            f"{r['alpha3']!r}, {r['region']!r}, {r['centroid']!r}, "
            f"({aliases}{',' if len(r['aliases']) == 1 else ''}), {r['prominent']!r}, "
            f"{r['query_name']!r}),"
        )
    union_rows = "\n".join(
        f"    Union({u['slug']!r}, {u['display']!r}, ({', '.join(repr(m) for m in u['members'])},)),"
        for u in unions
    )
    return _HEADER + "\n".join(body) + "\n" + _FOOTER.replace("{unions}", union_rows)


_TS_HEADER = """// Location display names and centroids, GENERATED by
// backend/scripts/gen_country_table.py — do not edit by hand.
//
// The dashboard takes the backend taxonomy's places from this file, never from a
// hand-maintained copy: a copy falls behind the taxonomy silently, and a place
// it lacks renders to users as a raw slug.
//
// Derived from mledoze/countries (ODbL-1.0); display names are Unicode CLDR
// English (Unicode-3.0), the names the world's software shows. See
// backend/tracker/vendored.py.

/** slug -> display name, for every country. */
export const COUNTRY_LABEL: Record<string, string> = {
"""

_TS_MID = """};

/** slug -> [lon, lat] centroid, for map placement. */
export const COUNTRY_CENTROID: Record<string, [number, number]> = {
"""

_TS_MID2 = """};

/** slug -> ISO 3166-1 alpha-2, lowercase. Feeds `flagEmoji` in format.ts: the
    two regional-indicator codepoints ARE the flag, so the flags cost no image
    assets and no icon dependency. Never use these for matching — the backend
    admits alpha-2 codes only where they do not collide with a US state abbrev
    (`IN` inside "Indianapolis, IN"), and that rule lives there, not here. */
export const COUNTRY_ALPHA2: Record<string, string> = {
"""


_TS_UNIONS = """// Political unions, GENERATED by backend/scripts/gen_country_table.py. Do not
// edit by hand. Membership is Unicode CLDR's grouping (Unicode-3.0), as our
// country slugs. See backend/tracker/vendored.py.

/** A union is not a place in the tree: choosing one chooses its members, and
    a set of members that is exactly a union reads back as its name. */
export const UNIONS: Record<string, { display: string; members: string[] }> = {
"""


def render_ts(rows: list[dict], unions: list[dict]) -> str:
    labels = "".join(f"  {r['slug']}: {json.dumps(r['display'])},\n" for r in rows)
    centroids = "".join(
        f"  {r['slug']}: [{r['centroid'][0]}, {r['centroid'][1]}],\n" for r in rows
    )
    alpha2 = "".join(f"  {r['slug']}: {json.dumps(r['alpha2'])},\n" for r in rows)
    return _TS_HEADER + labels + _TS_MID + centroids + _TS_MID2 + alpha2 + "};\n"


def render_ts_unions(unions: list[dict]) -> str:
    union_rows = "".join(
        f"  {u['slug']}: {{ display: {json.dumps(u['display'])}, members: {json.dumps(u['members'])} }},\n"
        for u in unions
    )
    return _TS_UNIONS + union_rows + "};\n"


def _pinned(name: str) -> bytes:
    """Fetch a pinned upstream blob and refuse it if the hash moved."""
    artifact = by_name(name)
    raw = httpx.get(artifact.raw_url, timeout=60.0, follow_redirects=True).content
    digest = hashlib.sha256(raw).hexdigest()
    if digest != artifact.sha256:
        raise SystemExit(f"{name}: upstream hash {digest} != pinned {artifact.sha256}")
    return raw


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true", help="diff against the committed file")
    args = ap.parse_args()

    artifact = by_name("country-table")
    raw = httpx.get(artifact.raw_url, timeout=60.0, follow_redirects=True).content
    digest = hashlib.sha256(raw).hexdigest()
    if digest != artifact.sha256:
        print(
            f"upstream blob hash {digest} != pinned {artifact.sha256}\n"
            "Upstream moved. Review the diff, then update tracker/vendored.py.",
            file=sys.stderr,
        )
        return 2

    cldr = json.loads(_pinned("cldr-territory-names"))["main"]["en"]["localeDisplayNames"]["territories"]
    containment = json.loads(_pinned("cldr-territory-containment"))["supplemental"]["territoryContainment"]
    rows = build_rows(json.loads(raw), cldr)
    unions = build_unions(rows, cldr, containment)
    rendered = render(rows, unions)
    ts = render_ts(rows, unions)
    ts_unions = render_ts_unions(unions)
    if args.check:
        stale = [
            path
            for path, want in ((_OUT, rendered), (_TS_OUT, ts), (_TS_UNIONS_OUT, ts_unions))
            if (path.read_text() if path.exists() else "") != want
        ]
        if stale:
            print(f"stale, re-run without --check: {stale}", file=sys.stderr)
            return 1
        print("generated files are current")
        return 0

    _OUT.write_text(rendered)
    _TS_OUT.write_text(ts)
    _TS_UNIONS_OUT.write_text(ts_unions)
    print(f"wrote {_OUT} and {_TS_OUT} ({len(rows)} countries)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
