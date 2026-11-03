"""Normalize free-form posting location strings into canonical city labels.

Sources phrase the same office a dozen ways — "Mountain View, CA, USA",
"United States, California, Mountain View", "Mountain View, California, USA" —
and multi-office postings join them with "|". `normalize_cities` collapses all
of that into stable display labels ("Mountain View, CA", "London, UK",
"Remote (US)") that `jobs.location_cities` stores and the per-company offices
view aggregates. Purely lexical; unknown-but-parseable strings degrade to a
tidied "City, Region" rather than disappearing. Country-only and
"Multiple Locations" strings yield nothing (they are not an office).

Coarse location *groups* (silicon_valley/uk/singapore, the scope-filter axis)
are a separate concept: `LOCATION_GROUPS` below (`tracker.config` re-exports
it).
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from types import MappingProxyType

from tracker.taxonomy.cities import (
    CITY_PREFIX,
    City,
    city_by_slug,
    city_country,
    city_for_place,
    fold,
    place_segments,
)
from tracker.taxonomy.countries import COUNTRIES

# Tokens that mean "a country", lowercased. Matched against whole comma parts.
_US = {"us", "usa", "united states", "united states of america"}
_UK = {"uk", "gb", "gbr", "united kingdom", "england", "scotland", "wales", "northern ireland"}
_COUNTRY_REGION: dict[str, str | None] = {
    # country token -> region label to keep when no sub-region is present
    **dict.fromkeys(_US, None),
    **dict.fromkeys(_UK, "UK"),
    "canada": "Canada",
    "can": "Canada",
    "ireland": "Ireland",
    "irl": "Ireland",
    "singapore": None,  # city-state; the city carries the name
    "sg": None,
    "sgp": None,
    "germany": "Germany",
    "deutschland": "Germany",
    "france": "France",
    "italy": "Italy",
    "spain": "Spain",
    "poland": "Poland",
    "pl": "Poland",
    "switzerland": "Switzerland",
    "netherlands": "Netherlands",
    "japan": "Japan",
    "china": "China",
    "india": "India",
    "australia": "Australia",
}

_STATE_ABBREV: dict[str, str] = {
    "alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR",
    "california": "CA", "colorado": "CO", "connecticut": "CT", "delaware": "DE",
    "florida": "FL", "georgia": "GA", "hawaii": "HI", "idaho": "ID",
    "illinois": "IL", "indiana": "IN", "iowa": "IA", "kansas": "KS",
    "kentucky": "KY", "louisiana": "LA", "maine": "ME", "maryland": "MD",
    "massachusetts": "MA", "michigan": "MI", "minnesota": "MN", "mississippi": "MS",
    "missouri": "MO", "montana": "MT", "nebraska": "NE", "nevada": "NV",
    "new hampshire": "NH", "new jersey": "NJ", "new mexico": "NM", "new york": "NY",
    "north carolina": "NC", "north dakota": "ND", "ohio": "OH", "oklahoma": "OK",
    "oregon": "OR", "pennsylvania": "PA", "rhode island": "RI", "south carolina": "SC",
    "south dakota": "SD", "tennessee": "TN", "texas": "TX", "utah": "UT",
    "vermont": "VT", "virginia": "VA", "washington": "WA", "west virginia": "WV",
    "wisconsin": "WI", "wyoming": "WY", "district of columbia": "DC",
}

# City-token spelling fixes applied before assembly.
_CITY_ALIASES: dict[str, str] = {
    "new york city": "New York",
    "sf": "San Francisco",
    "nyc": "New York",
    "washington d.c.": "Washington",
    "frankfurt am main": "Frankfurt",
    "milano": "Milan",
    "san josé": "San Jose",
}

# Whole-string aliases for shapes the parser can't derive.
_FULL_ALIASES: dict[str, str] = {
    "san francisco bay area": "San Francisco, CA",
    "singapore": "Singapore",
    "singapore, singapore, singapore": "Singapore",
}

# Bare city names that appear with no region at all.
_DEFAULT_REGION: dict[str, str] = {
    "cupertino": "CA",
    "sunnyvale": "CA",
    "san francisco": "CA",
    "mountain view": "CA",
    "seattle": "WA",
    "new york": "NY",
    "washington": "DC",
    "london": "UK",
    "dublin": "Ireland",
    "austin": "TX",
}

# Coarse country grouping for the scope-filter axis (LOCATION_GROUPS below).
# Whole-token country signals mapped to location-group slugs, reusing the same
# vocabulary as normalize_cities. Multiword names ("united kingdom") match the
# lowercased piece; short codes match comma-parts/words so "Busan" never reads as
# "usa". The DE/Delaware collision (ISO Germany vs Delaware abbrev) is resolved in
# Germany's favor — spelled-out "Delaware" still classifies US; the bare "DE"
# abbrev does not (a mis-US-tag of Frankfurt is the worse error, since
# united_states ships enabled and germany does not).
_US_STATE_NAMES: frozenset[str] = frozenset(_STATE_ABBREV)
_US_STATE_ABBREVS: frozenset[str] = frozenset(v.lower() for v in _STATE_ABBREV.values())
#: The same codes as a board prints them; an adapter reading a bare two-letter
#: field asks whether it could be a state before it reads it as a country.
US_STATE_CODES: frozenset[str] = frozenset(_STATE_ABBREV.values())
#: A state's lowercase name -> its code ("pennsylvania" -> "PA"), for a source
#: that spells the state out.
US_STATE_BY_NAME: Mapping[str, str] = MappingProxyType(_STATE_ABBREV)

#: Extra hand-curated tokens the ISO table cannot supply: constituent countries,
#: endonyms and the like. Merged over the generated vocabulary.
_EXTRA_COUNTRY_TOKENS: dict[str, str] = {
    "england": "uk", "scotland": "uk", "wales": "uk", "northern ireland": "uk",
    "deutschland": "germany",
    # The inverted form some boards print ("Seoul, Korea, South"), sometimes
    # beside a wrong `country_code`.
    "korea, south": "south_korea",
    # An Australian state holding a UK nation's name: "Sydney, New South Wales,
    # Australia" would read as Australia AND the UK. Named here, the longer
    # token shadows "wales" (`_unshadowed`).
    "new south wales": "australia",
}


def _build_country_tokens() -> tuple[dict[str, str], frozenset[str]]:
    """Country match tokens, and the subset needing a non-US context.

    Three rules, each earning its place:

    1. **Alpha-3 and full names are always admitted.** Three-letter codes cannot
       collide with two-letter state abbreviations.
    2. **Alpha-2 only when it does not collide with a US state abbreviation.**
       Computed, not curated (`ca`=Canada/California, `in`=India/Indiana,
       `il`=Israel/Illinois, `la`=Laos/Louisiana...): admitting any one of them
       would mis-tag a US posting as foreign, and a rule cannot be forgotten
       for the next country added.
    3. **A name that is also a US state name needs a non-US signal.** Georgia is
       the only case in ISO 3166 — the country and the state share a name, so
       "Atlanta, Georgia, USA" must not tag the country. Nor must "Georgia -
       Atlanta": with no country named, a place beside it that is not Georgian
       makes it the state (`_names_a_place_outside`).
    """
    tokens: dict[str, str] = {}
    for country in COUNTRIES:
        for alias in country.aliases:
            tokens.setdefault(alias, country.slug)
        if country.alpha3:
            tokens.setdefault(country.alpha3, country.slug)
        if country.alpha2 and country.alpha2 not in _US_STATE_ABBREVS:
            tokens.setdefault(country.alpha2, country.slug)
    tokens.update(_EXTRA_COUNTRY_TOKENS)
    ambiguous = frozenset(tok for tok in tokens if tok in _US_STATE_NAMES)
    return tokens, ambiguous


_FOREIGN_COUNTRY_TOKENS, _STATE_NAME_COLLISIONS = _build_country_tokens()

#: `de` stays excluded from the US side: spelled-out "Delaware" still classifies
#: US, the bare abbrev does not. Mis-tagging Frankfurt as US is the worse
#: error.
_US_STATE_TOKENS: frozenset[str] = frozenset(
    (_US_STATE_NAMES | _US_STATE_ABBREVS) - {"de"}
)


#: Canada by its provinces. Boards write a Canadian place the way they
#: write an American one ("Toronto, ON", "Calgary, AB", "Vancouver, BC"), and
#: with no country field such a place would match no group at all: collected
#: and shown to nobody. Read only where the place carries no US state and no
#: US signal, because "Ontario, CA" is a city in California.
_CA_PROVINCE_NAMES: frozenset[str] = frozenset({
    "ontario", "quebec", "british columbia", "alberta", "manitoba", "saskatchewan",
    "nova scotia", "new brunswick", "newfoundland and labrador", "prince edward island",
    "yukon", "northwest territories", "nunavut",
})
#: Two-letter codes, only as a whole comma field ("on" is an English word).
#: NL, PE and SK are left out: they are the Netherlands, Peru and Slovakia.
_CA_PROVINCE_CODES: frozenset[str] = frozenset({
    "on", "qc", "bc", "ab", "mb", "ns", "nb", "yt", "nt", "nu",
})


def countries_for(locations: list[str]) -> set[str]:
    """Country-level location-group slugs a posting's raw locations fall into.

    A US posting names a US country token or a US state and carries no explicit
    foreign country token in the same piece; foreign postings map by country
    name/code. Multi-country strings ("SF | London") return every match. Purely
    lexical, mirroring normalize_cities so grouping stays consistent with display.
    """
    out: set[str] = set()
    for raw in locations:
        for piece in _SPLIT_RE.split(raw or ""):
            # Accents folded: every alias is ASCII, so unfolded "Türkiye" and
            # "Curaçao" would match nothing.
            low = fold(piece)
            if not low:
                continue
            parts = {p.strip() for p in low.split(",") if p.strip()}
            words = {w for w in re.split(r"[^a-z0-9]+", low) if w}
            # Words the board wrote in capitals: how a country CODE looks when
            # it is one ("Remote - USA", "Berlin DEU"). See the code rule below.
            shouted = {w.lower() for w in re.split(r"[^A-Za-z0-9]+", piece) if len(w) > 1 and w.isupper()}
            us_signal = "united states" in low or bool({"us", "usa"} & words)
            state_tokens = (parts | words) & _US_STATE_TOKENS
            hits: dict[str, list[str]] = {}
            for tok, slug in _FOREIGN_COUNTRY_TOKENS.items():
                # A token standing as its own comma field is a named country;
                # one found only inside a larger field is a word that happens to
                # look like one. The two are treated differently below.
                named = (" " in tok and tok in low) or tok in parts
                if not (named or tok in words):
                    continue
                # A code of three letters or fewer, found only as a WORD, is a
                # code only when written as one — in capitals. Lowercase it is
                # English: "and" is Andorra's alpha-3 and "St." São Tomé's
                # alpha-2, so "London and Remote" would read as Andorra ONLY
                # (the country it named suppresses London's UK fallback) and
                # "New York and San Francisco" as Andorra and nowhere in the US.
                # A code in its own comma field is still a code.
                if not named and len(tok) <= 3 and tok not in shouted:
                    continue
                # A token that is also a US state name only counts as foreign
                # when the piece carries no US signal. Georgia is the one case
                # in ISO 3166, and without this "Atlanta, Georgia, USA" tags the
                # country AND the US — `out |= foreign` is unconditional.
                if tok in _STATE_NAME_COLLISIONS and (us_signal or _names_a_place_outside(piece, tok, slug)):
                    continue
                # A country found only INSIDE a field loses to a US state named
                # in another one. These aliases are native country names and
                # several are ordinary English place words: the country table
                # gives Iceland `island`, so "Staten Island, NY" and "Rhode
                # Island, RI" would read as Iceland, and "West Jordan, UT" as
                # Jordan. Worse than a stray badge: a non-empty `foreign`
                # suppresses the `united_states` branch below, so a New York
                # borough would land in Europe and nowhere in the US, invisible
                # to anyone tracking the States.
                # Scoped tightly on both sides: "Reykjavik, Iceland" and
                # "Madrid, MD, ES" name their country in its own field and are
                # untouched, and the state must be a DIFFERENT token than the
                # country or "Tbilisi, Georgia" would read as US.
                if not named and state_tokens - {tok}:
                    continue
                hits.setdefault(slug, []).append(tok)
            foreign = _unshadowed(hits, low)
            if not foreign and not us_signal and not state_tokens and (
                parts & _CA_PROVINCE_CODES
                or any(name in parts or (" " in name and name in low) for name in _CA_PROVINCE_NAMES)
            ):
                foreign.add("canada")
            out |= foreign
            if us_signal or (not foreign and (parts | words) & _US_STATE_TOKENS):
                out.add("united_states")
    return out


_SPLIT_RE = re.compile(r"\s*[|;/]\s*")


def _names_a_place_outside(piece: str, token: str, country: str) -> bool:
    """True when `piece` names a place besides `token` that is not in `country`.

    Georgia without a US signal: "Georgia - Remote" and "Tbilisi, Georgia" are
    the country, but some boards write "State - City" with no country, so
    "Georgia - Atlanta" is the state. A segment that is a country, a state, a
    region or "remote" (`CITY_RESERVED_SEGMENTS`) names nothing here; any other
    segment must be a city of the country, or the token is the state.
    """
    for segment in place_segments(piece):
        if segment == token or segment in CITY_RESERVED_SEGMENTS:
            continue
        if city_for_place(segment, {country}) is None:
            return True
    return False


def _spans(token: str, text: str) -> list[tuple[int, int]]:
    return [(m.start(), m.end()) for m in re.finditer(re.escape(token), text)]


def _unshadowed(hits: dict[str, list[str]], low: str) -> set[str]:
    """Countries named in their own right, not only inside another's name.

    One country's name inside another's is not a second country: "North Korea"
    holds "korea" (South Korea's alias), "Equatorial Guinea" and
    "Papua New Guinea" hold "guinea", "South Sudan" holds "sudan". A country is
    kept when at least one occurrence of one of its tokens lies outside every
    occurrence of a longer token matched for a DIFFERENT country.
    """
    kept: set[str] = set()
    for slug, tokens in hits.items():
        others = [
            span for other, toks in hits.items() if other != slug
            for tok in toks for span in _spans(tok, low)
        ]
        for tok in tokens:
            spans = _spans(tok, low) or [(-1, -1)]
            if any(not any(a <= s and e <= b and (b - a) > (e - s) for a, b in others) for s, e in spans):
                kept.add(slug)
                break
    return kept


def location_pieces(locations: list[str]) -> list[str]:
    """Each place a posting names, lowercased: its strings split on `|`, `;`
    and `/` exactly as `countries_for` splits them."""
    return [
        low
        for raw in locations
        for piece in _SPLIT_RE.split(raw or "")
        if (low := fold(piece))
    ]
_UK_REGIONS = {"england", "scotland", "wales", "northern ireland", "cambridgeshire", "london"}
_PROVINCE_ABBREV = {"british columbia": "BC", "ontario": "ON", "quebec": "QC", "alberta": "AB"}
# Sub-national regions better displayed as their country ("Frankfurt, Germany",
# not "Frankfurt, Hessen"/"Frankfurt, HE" as a separate office).
_REGION_TO_COUNTRY = {"hessen": "Germany", "he": "Germany", "lombardy": "Italy", "milano": "Italy"}


def _canon_region(token: str) -> str | None:
    low = token.lower()
    if low in _STATE_ABBREV:
        return _STATE_ABBREV[low]
    if low in _UK_REGIONS:
        return "UK"
    if low in _PROVINCE_ABBREV:
        return _PROVINCE_ABBREV[low]
    if low in _REGION_TO_COUNTRY:
        return _REGION_TO_COUNTRY[low]
    if len(token) == 1:
        return None  # "Dublin, D" style noise
    if len(token) == 2:
        return token.upper()
    return token.title() if token.islower() or token.isupper() else token


def _canon_one(raw: str) -> str | None:
    text = raw.strip()
    if not text:
        return None
    low = text.lower()
    if low in _FULL_ALIASES:
        return _FULL_ALIASES[low]
    if low.startswith("singapore"):
        return "Singapore"  # "Singapore-Suntec Tower" and friends
    if "remote" in low:
        return _remote_label(text, low)

    parts = [p.strip() for p in text.split(",") if p.strip()]
    if not parts:
        return None
    # Country-first order: flip to city-first.
    if parts[0].lower() in _COUNTRY_REGION:
        parts = list(reversed(parts))

    # Peel country tokens, remembering the fallback region they imply.
    country_region: str | None = None
    core = []
    for p in parts:
        pl = p.lower()
        if pl in _COUNTRY_REGION:
            country_region = country_region or _COUNTRY_REGION[pl]
        elif pl != "multiple locations":
            core.append(p)
    if not core:
        # Country-only ("US") or all-"Multiple Locations": not an office.
        return "Singapore" if low.rstrip(".") in {"singapore"} else None

    city = _CITY_ALIASES.get(core[0].lower(), core[0])
    region = None
    if len(core) > 1 and core[1].lower() != city.lower():
        region = _canon_region(core[1])
    if region is None:
        region = country_region or _DEFAULT_REGION.get(city.lower())
    return f"{city}, {region}" if region else city


_REGION_CODES: dict[str, str] = {**_STATE_ABBREV, **_PROVINCE_ABBREV}
_CODE_TO_REGION: dict[str, str] = {code.lower(): name for name, code in _REGION_CODES.items()}


def region_aliases(label: str) -> frozenset[str]:
    """The other spelling of each US state or Canadian province a place label
    names, as lower-case words: "New York, New York, USA" -> {"ny"}, "Denver,
    CO" -> {"colorado"}. A posting's text may spell its place either way
    ("USA, NY, New York - 194,700.00 ...")."""
    low = label.lower()
    out: set[str] = set()
    for name, code in _REGION_CODES.items():
        if re.search(rf"\b{re.escape(name)}\b", low):
            out.add(code.lower())
    for token in re.findall(r"[a-z]+", low):
        if token in _CODE_TO_REGION:
            out.update(_CODE_TO_REGION[token].split())
    return frozenset(out)


#: A remote place's country as a city label writes it ("London, UK"), where
#: that differs from the country group's display name.
_REMOTE_COUNTRY_LABEL = {"uk": "UK"}


def _remote_label(text: str, low: str) -> str:
    """"Remote", with the one country the place names: "Remote (US)",
    "Remote (Germany)". Without the country every remote place outside the
    US is one place: one office row, one pay location, one place in a
    comparison. Several countries, or a region ("EMEA"), stay bare."""
    if any(t in re.split(r"[\s,()-]+", low) for t in ("us", "usa")):
        return "Remote (US)"
    # The US only by its own name above: `countries_for` also reads a US state
    # code, and "or" in "Germany or France" is Oregon's.
    countries = countries_for([text]) - {"united_states"}
    if len(countries) != 1:
        return "Remote"
    (slug,) = countries
    return f"Remote ({_REMOTE_COUNTRY_LABEL.get(slug) or LOCATION_GROUPS[slug]['display']})"


def normalize_cities(locations: list[str]) -> list[str]:
    """Canonical city labels for a posting's raw location strings, deduped in order."""
    out: list[str] = []
    for raw in locations:
        for piece in _SPLIT_RE.split(raw or ""):
            city = _canon_one(piece)
            if city and city not in out:
                out.append(city)
    return out


# Location groups: a nested scope axis. Each group has a `kind` and an optional
# `parent`, forming a tree — metros nest under a country, countries nest under a
# region (Europe). `kind="metro"` matches by substring; `kind="country"` matches
# by parsed country/state (`countries_for` above) with a city-substring
# fallback (bare "London"); `kind="region"` never matches directly — it is implied
# whenever one of its child countries matches. A matched child implies its whole
# ancestor chain, so a Munich posting -> [germany, europe] and a Bay Area one ->
# [silicon_valley, united_states]. `location_groups_for` orders the most specific
# (deepest) group first, so `location_groups[0]` (the comp/primary axis) stays the
# fine leaf. Which groups are *tracked* is a user setting (settings store);
# `enabled` is only the shipped default. Nesting a group costs no extra scrape.
_METROS: dict[str, dict] = {
    # --- US metros (substring-matched; nest under united_states) ---
    "silicon_valley": {
        "display": "Silicon Valley",
        "enabled": True,
        "kind": "metro",
        "parent": "united_states",
        "substrings": [
            "mountain view",
            "sunnyvale",
            "san francisco",
            # Bare "santa clara" also covers a "Santa Clara Valley" bucket, and
            # it has to be bare: a board writing "US, CA, Santa Clara" is hit by
            # no "santa clara, ca".
            "santa clara",
            "cupertino",
            "san jose",
            "palo alto",
            "menlo park",
            "sf bay",
            "bay area",
            "los gatos",  # Netflix HQ
            # Bay Area city names with no namesake a posting would carry: bare.
            "redwood city",  # Electronic Arts HQ
            "san bruno",  # YouTube HQ
            "foster city",
            "milpitas",
            # Names shared with places elsewhere (San Carlos and San Mateo in the
            # Philippines and Mexico, Belmont MA/NC, Fremont NE/OH/MI): only with
            # California beside them, in either order, like dc_metro's
            # "arlington, va" ("Fremont, CA, USA" and "US, CA, Fremont").
            *(
                pattern
                for city in ("san carlos", "san mateo", "belmont", "fremont")
                for pattern in (f"{city}, ca", f"{city}, california", f"ca, {city}", f"california, {city}")
            ),
        ],
    },
    "pacific_northwest": {
        "display": "Pacific Northwest",
        "enabled": True,
        "kind": "metro",
        "parent": "united_states",
        "substrings": ["seattle", "redmond", "bellevue", "kirkland"],
    },
    "new_york": {
        "display": "New York",
        "enabled": True,
        "kind": "metro",
        "parent": "united_states",
        "substrings": ["new york", "jersey city", "brooklyn", "manhattan"],
    },
    "austin": {
        "display": "Austin",
        "enabled": True,
        "kind": "metro",
        "parent": "united_states",
        "substrings": ["austin"],
    },
    "dc_metro": {
        "display": "Washington, DC",
        "enabled": True,
        "kind": "metro",
        "parent": "united_states",
        # DC-metro cities; avoid bare "washington"/"arlington" (WA state / Arlington TX).
        "substrings": [
            "washington, dc",
            "washington, d.c",
            ", dc",
            "arlington, va",
            "arlington, virginia",
            "herndon",
            "reston",
            "mclean",
            "tysons",
        ],
    },
    # London is a metro under uk exactly as silicon_valley sits under
    # united_states. It exists because several sources can only *ask* about
    # London, and a coverage manifest must be able to say so. Without the finer
    # slug those adapters would have to claim `uk` and silently under-collect
    # Manchester/Edinburgh.
    "london": {
        "display": "London",
        "enabled": False,
        "kind": "metro",
        "parent": "uk",
        "substrings": ["london"],
    },
}

#: City substrings that let a bare city name resolve to its country without any
#: country token present ("London" alone -> uk). Hand-curated and deliberately
#: tiny: this is a *fallback* for the handful of cities that appear unqualified
#: in real postings, not a world city gazetteer. Generated countries get none.
_COUNTRY_CITY_FALLBACKS: dict[str, list[str]] = {
    # `abingdon`: an Oxfordshire campus a board lists as "Abingdon - 141 Park
    # Drive" with no country; "Abingdon, VA" names its state.
    "uk": ["london", "united kingdom", ", uk", " uk", "england", "abingdon"],
    "singapore": ["singapore"],
    # Boards that publish ONE free-text place and no country at all
    # ("Stockholm", "Milan", "Vienna"). Locations fail CLOSED, so a posting no
    # group matches is invisible to everyone.
    # Only names seen in real postings, and safe because a place that names
    # a country decides where its city is: "Milan, MI" and
    # "Amsterdam, NY" are the US, not Italy or the Netherlands.
    "sweden": ["stockholm"],
    "italy": ["milan"],
    "poland": ["warsaw"],
    "austria": ["vienna"],
    "germany": ["munich"],
    "finland": ["helsinki"],
    "netherlands": ["amsterdam"],
    "france": ["paris"],
    "greece": ["athens"],
    "australia": ["sydney"],
    "united_states": ["columbus", "salt lake city", "portland"],
}

#: Regions, in umbrella order. `kind="region"` never matches directly — a region
#: is implied only when one of its member countries matches, so adding regions
#: can never change what a posting matches. All ship disabled: enabling one
#: tracks a whole continent, while its members stay independently trackable.
#:
#: Each region names the UN M49 area it corresponds to, the standard
#: CLDR and every analytics product group countries by. The display is the name
#: people and job boards use; the M49 English name is a search alias, so
#: "Northern America" or "Eastern Asia" finds the region. Membership follows
#: M49 except where the job market does not (the country table's overrides:
#: Mexico in Latin America, Cyprus in Europe). The Middle East and the Gulf are
#: not M49 areas: the Middle East is M49 Western Asia (145) less Cyprus, and the
#: Gulf is the six states of the Gulf Cooperation Council.
REGIONS: dict[str, dict] = {
    "north_america": {"display": "North America", "m49": "021", "aliases": ("northern america",)},
    "latin_america": {"display": "Latin America", "m49": "419",
                      "aliases": ("latin america and the caribbean", "latam")},
    "europe": {"display": "Europe", "m49": "150", "aliases": ()},
    "middle_east": {"display": "Middle East", "m49": None, "aliases": ("western asia", "mena")},
    # The GCC is how these roles are advertised, so it is a group rather than a
    # slice of the Middle East the user has to assemble by hand.
    "gulf": {"display": "Gulf (GCC)", "parent": "middle_east", "m49": None,
             "aliases": ("gulf cooperation council", "gcc", "gulf states")},
    "africa": {"display": "Africa", "m49": "002", "aliases": ()},
    "central_asia": {"display": "Central Asia", "m49": "143", "aliases": ()},
    "south_asia": {"display": "South Asia", "m49": "034", "aliases": ("southern asia",)},
    "east_asia": {"display": "East Asia", "m49": "030", "aliases": ("eastern asia",)},
    "southeast_asia": {"display": "Southeast Asia", "m49": "035", "aliases": ("south-eastern asia",)},
    "oceania": {"display": "Oceania", "m49": "009", "aliases": ()},
}

#: Groups shipped enabled. Everything else is opt-in from Settings — which is
#: what keeps the adapter coverage contract satisfiable: a source only has to
#: declare a query for regions we ship tracked.
_DEFAULT_ENABLED = frozenset(
    {
        "silicon_valley", "pacific_northwest", "new_york", "austin", "dc_metro",
        "united_states", "uk", "singapore",
    }
)


def _build_location_groups() -> dict[str, dict]:
    """Metros, then countries, then regions — leaves before umbrellas.

    Declaration order is load-bearing in three places (`location_groups_for`'s
    tiebreak, `settings_store._set_enabled_slugs` canonicalization, and the
    scope-catalog payload order), so it is produced here rather than left to
    chance.
    """
    groups: dict[str, dict] = dict(_METROS)
    for country in COUNTRIES:
        entry: dict = {
            "display": country.display,
            "enabled": country.slug in _DEFAULT_ENABLED,
            "kind": "country",
            "parent": country.region,
        }
        fallbacks = _COUNTRY_CITY_FALLBACKS.get(country.slug)
        if fallbacks:
            entry["substrings"] = fallbacks
        groups[country.slug] = entry
    for slug, region in REGIONS.items():
        entry = {"display": region["display"], "enabled": False, "kind": "region"}
        if region.get("parent"):
            entry["parent"] = region["parent"]
        groups[slug] = entry
    return groups


LOCATION_GROUPS: dict[str, dict] = _build_location_groups()


#: A place that names only a region: "Americas" counts as its regions AND
#: every country in them, so someone tracking the United States sees a
#: remote-Americas role, rather than a region-only place matching nothing and
#: the posting being shown to nobody. "Global", "worldwide" and "anywhere"
#: name no region and stay unplaced. A value is region slugs, or country
#: slugs where the region is a pair of countries (ANZ).
_REGION_PLACES: dict[str, tuple[str, ...]] = {
    "americas": ("north_america", "latin_america"),
    "the americas": ("north_america", "latin_america"),
    "emea": ("europe", "middle_east", "africa"),
    "apac": ("east_asia", "southeast_asia", "south_asia", "oceania"),
    "asia pacific": ("east_asia", "southeast_asia", "south_asia", "oceania"),
    "asia-pacific": ("east_asia", "southeast_asia", "south_asia", "oceania"),
    "asia": ("central_asia", "south_asia", "east_asia", "southeast_asia"),
    "anz": ("australia", "new_zealand"),
    **{fold(r["display"]): (slug,) for slug, r in REGIONS.items()},
    **{alias: (slug,) for slug, r in REGIONS.items() for alias in r.get("aliases", ())},
    "latin america": ("latin_america",),
    "gulf": ("gulf",),
}
#: Words a board puts around a region that name no place ("Remote - EMEA").
_REGION_NOISE = re.compile(r"\b(?:remote|hybrid|on-?site|region|only|based)\b|[()\-–:]")


def region_places(piece: str) -> tuple[str, ...]:
    """The groups a place names when it names only a region, else ().

    The whole place, less remote/hybrid wording, must be the region ("EMEA",
    "Remote - Americas", "Europe (Remote)"); a region beside a city or country
    ("London, Europe") names that place, which the caller matches instead."""
    low = " ".join(_REGION_NOISE.sub(" ", fold(piece)).split()).strip(" ,")
    fields = [f.strip() for f in low.split(",") if f.strip()]
    if not fields:
        return ()
    found: list[str] = []
    for field in fields:
        slugs = _REGION_PLACES.get(field)
        if slugs is None:
            return ()
        found.extend(s for s in slugs if s not in found)
    return tuple(found)


def region_countries(slug: str) -> list[str]:
    """Every country group under a region (a Gulf state is in the Middle East)."""
    return [
        country for country, group in LOCATION_GROUPS.items()
        if group.get("kind") == "country" and slug in location_group_ancestors(country)
    ]


def enabled_location_groups() -> dict[str, dict]:
    return {k: v for k, v in LOCATION_GROUPS.items() if v.get("enabled")}


# Locations are a user-configurable scope axis (like roles/bands/tracks): the
# taxonomy lives here, the `enabled` flags are only the shipped defaults, and the
# tracked set lives in the settings store (`enabled_location_groups` key).
def all_location_group_slugs() -> list[str]:
    return list(LOCATION_GROUPS.keys())


def default_enabled_location_groups() -> list[str]:
    return [k for k, v in LOCATION_GROUPS.items() if v.get("enabled")]


def search_vocabulary_slugs() -> list[str]:
    """Location slugs worth offering an LLM as a closed enum.

    Every metro and region, plus the countries flagged `prominent`. Not every
    country: the enum is inlined into every structured-query prompt, and the long tail
    costs tokens on every call to name markets a natural-language query will
    essentially never mention.

    Nothing is lost by the omission. `search/parse.py` matches every display
    name deterministically before the model is consulted, so "roles in nepal"
    still resolves, through the parser rather than the enum.
    """
    prominent = {c.slug for c in COUNTRIES if c.prominent}
    return [
        slug
        for slug, group in LOCATION_GROUPS.items()
        if group["kind"] in {"metro", "region"}
        or slug in prominent
        or group.get("enabled")
    ]


def location_group_ancestors(slug: str) -> list[str]:
    """The parent chain above `slug`, nearest first. Empty for a top-level group.

    City-aware: a city's chain is its metro (when it is one of a metro's named
    cities) or its country, then on up the taxonomy. That is what lets a
    `sweden` query cover a tracked Stockholm, and the scope gate and coverage
    manifests need nothing else to know about cities."""
    chain: list[str] = []
    cur = (location_node(slug) or {}).get("parent")
    while cur and cur not in chain:
        chain.append(cur)
        cur = LOCATION_GROUPS.get(cur, {}).get("parent")
    return chain


# --------------------------------------------------------------------------- #
# Cities. The taxonomy above is the fixed tree of metros, countries
# and regions; a city from the GeoNames gazetteer (`taxonomy.cities`) hangs off
# it as a leaf, `city_<geonameid>`, created on demand rather than listed here.
# --------------------------------------------------------------------------- #

#: Segments of a place string that are never a city, whatever GeoNames has by
#: that name: every country, region and US state (except New York and
#: Washington, which are cities first in a posting), and the words boards put
#: where a city would be.
CITY_RESERVED_SEGMENTS: frozenset[str] = frozenset(
    {
        *(fold(c.display) for c in COUNTRIES),
        *(alias for c in COUNTRIES for alias in c.aliases),
        *(fold(r["display"]) for r in REGIONS.values()),
        *(alias for r in REGIONS.values() for alias in r.get("aliases", ())),
        *(_US_STATE_NAMES - {"new york", "washington"}),
        *_US_STATE_ABBREVS,
        "remote", "hybrid", "anywhere", "worldwide", "global", "emea", "apac", "latam",
        "americas", "multiple locations", "various locations", "home based", "field based",
    }
)


def metro_of_city(city: City) -> str | None:
    """The metro a city belongs to: one of the metro's named cities, in the
    metro's own country ("San Jose" in the US is Silicon Valley; San José in
    Costa Rica is not). A name qualified by its state in the metro's list
    ("san mateo, ca") matches on that pair."""
    country = city_country(city)
    if country is None:
        return None
    names = {fold(city.name), city.asciiname.lower(), *(fold(a) for a in city.alternates)}
    pairs = {f"{name}, {city.admin1.lower()}" for name in names}
    for slug, metro in _METROS.items():
        if metro["parent"] != country.slug:
            continue
        subs = set(metro.get("substrings", ()))
        if names & subs or pairs & subs:
            return slug
    return None


def location_node(slug: str) -> dict | None:
    """The taxonomy entry for `slug`, or the entry a city would have."""
    group = LOCATION_GROUPS.get(slug)
    if group is not None:
        return group
    city = city_by_slug(slug)
    if city is None:
        return None
    country = city_country(city)
    if country is None:
        return None
    return {
        "display": city.name,
        "enabled": False,
        "kind": "city",
        "parent": metro_of_city(city) or country.slug,
    }


def is_location_slug(slug: str) -> bool:
    return location_node(slug) is not None


def canonical_location_slugs(slugs: Iterable[str]) -> list[str]:
    """Valid slugs in canonical order: the taxonomy's order, then cities by
    GeoNames id. Unknown slugs are dropped."""
    wanted = {slug for slug in slugs if isinstance(slug, str)}
    ordered = [slug for slug in LOCATION_GROUPS if slug in wanted]
    cities = sorted(
        (slug for slug in wanted if slug.startswith(CITY_PREFIX) and is_location_slug(slug)),
        key=lambda slug: int(slug[len(CITY_PREFIX):]),
    )
    return ordered + cities


def tracked_city_nodes(tracked: Iterable[str]) -> list[tuple[str, dict]]:
    """The tracked GeoNames cities as (slug, node), canonical order.

    What the board's location filter offers after the taxonomy groups."""
    nodes = []
    for slug in canonical_location_slugs(tracked):
        node = None if slug in LOCATION_GROUPS else location_node(slug)
        if node is not None:
            nodes.append((slug, node))
    return nodes


def location_names(tracked: Iterable[str] = ()) -> list[tuple[str, str]]:
    """Every name a person may give a location, as (slug, name), in precedence
    order: a name that two slugs share belongs to the first.

    The names the taxonomy already holds, nothing new: each group's display
    name, then the tracked cities the board's filter offers, then the aliases
    people type for a country or region ("USA", "Korea", "LATAM"), then the
    places that define a group ("Seattle" and "Bay Area" are where
    pacific_northwest and silicon_valley are; "Portland" is the United States),
    the same terms `search/parse.py` tags a query with. A tracked city outranks
    the metro that contains it, so "Seattle" is the city when it is tracked and
    the Pacific Northwest when it is not. Alpha-2 codes stay out, as they do
    from the country aliases: "CA" is Canada to the table and California to a
    person.
    """
    names: list[tuple[str, str]] = [
        (slug, str(group["display"])) for slug, group in LOCATION_GROUPS.items()
    ]
    names.extend((slug, str(node["display"])) for slug, node in tracked_city_nodes(tracked))
    by_slug = {country.slug: country for country in COUNTRIES}
    for slug in LOCATION_GROUPS:
        country = by_slug.get(slug)
        if country is not None:
            names.extend((slug, alias) for alias in country.aliases)
    for slug, region in REGIONS.items():
        names.extend((slug, alias) for alias in region.get("aliases", ()))
    for slug, group in LOCATION_GROUPS.items():
        names.extend((slug, place) for place in group.get("substrings", ()))
    return names


def state_codes(piece: str) -> set[str]:
    """US state abbreviations a place names ("portland, or, usa" -> {"OR"})."""
    low = fold(piece)
    parts = {p.strip() for p in low.split(",") if p.strip()}
    words = {w for w in re.split(r"[^a-z0-9]+", low) if w}
    codes = {_STATE_ABBREV[name] for name in parts & _US_STATE_NAMES}
    codes |= {tok.upper() for tok in (parts | words) & _US_STATE_ABBREVS}
    return codes


def city_for_piece(piece: str, countries: set[str]) -> City | None:
    """The gazetteer city one place names (see `cities.city_for_place`)."""
    return city_for_place(
        piece, countries, state_codes(piece), CITY_RESERVED_SEGMENTS, _CITY_WEAK_SEGMENTS,
    )


#: State names that are also a city a posting means (see `city_for_place`).
_CITY_WEAK_SEGMENTS: frozenset[str] = frozenset({"new york", "washington"})


def location_group_children(slug: str) -> list[str]:
    """Direct children of a group."""
    return [s for s, g in LOCATION_GROUPS.items() if g.get("parent") == slug]


def _covers(group: str, have: frozenset[str]) -> bool:
    """Is `group` covered by a manifest declaring `have`?

    Two ways, and the asymmetry between them is the whole rule:

    * DOWN — the group itself or an ancestor is declared. Asking about
      `united_states` returns New York roles.
    * UP, **regions only** — every child country is declared. Asking about all
      of Europe's countries does cover Europe, because a European posting is
      always in some European country; a region has no postings of its own.

    Up-coverage stops at regions deliberately. A country is NOT covered by
    declaring its metros: `uk` has roles in Manchester that a `london` query
    never returns, which would be an over-claim. Regions have
    no such remainder.
    """
    if {group, *location_group_ancestors(group)} & have:
        return True
    if LOCATION_GROUPS.get(group, {}).get("kind") != "region":
        return False
    children = location_group_children(group)
    return bool(children) and all(_covers(child, have) for child in children)


def uncovered_groups(declared: Iterable[str], wanted: Iterable[str]) -> set[str]:
    """Which `wanted` groups a manifest of `declared` groups does not cover.

    Walks UP from each wanted group instead of testing every declared group
    against it: O(wanted x depth) rather than O(wanted x declared). Manifests
    can declare every country, and the scope-catalog screen does this for every
    adapter on every read.
    """
    have = frozenset(declared)
    return {group for group in wanted if not _covers(group, have)}


def location_group_covers(declared: str, wanted: str) -> bool:
    """Does asking a source about `declared` also return everything in `wanted`?

    Coverage flows DOWN the tree only. A `united_states` query returns New York
    postings, so declaring the country covers the metro. The reverse is false
    and is the whole reason this function exists: a source that can only ask
    about `london` does NOT cover `uk` — Manchester and Edinburgh postings are
    never in the response, and nothing about an empty result says so.
    """
    return declared == wanted or declared in location_group_ancestors(wanted)


_COUNTRY_CODES: Mapping[str, str] = MappingProxyType({c.slug: c.alpha2.upper() for c in COUNTRIES if c.alpha2})


def country_code(slug: str) -> str | None:
    """The ISO 3166-1 alpha-2 code of the country a location group lies in: a
    country itself, or a metro or city through its parent chain. None for a
    region, which spans countries."""
    for group in (slug, *location_group_ancestors(slug)):
        if (LOCATION_GROUPS.get(group) or {}).get("kind") == "country" or group in _COUNTRY_CODES:
            return _COUNTRY_CODES.get(group)
    return None


def pay_country(location_groups: Iterable[str] | None) -> str | None:
    """The one country a posting's pay is for: the country every place it names
    lies in. None when it names places in several countries, or none: pay is
    stated per country, and a figure for one country is never shown for a
    posting that may be in another."""
    codes = {code for code in (country_code(g) for g in location_groups or ()) if code}
    return next(iter(codes)) if len(codes) == 1 else None
