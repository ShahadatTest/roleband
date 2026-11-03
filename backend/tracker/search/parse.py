"""Natural-language query parsing for the smart search box.

`parse_query("staff ml engineer at google remote over 500k", companies=...)`
yields structured filters: company=[google], level_band=[staff], family=[ml_ai_research],
workplace_type=[remote], comp_min=500000 — plus the semantic *remainder* (the text
left after removing recognized structured spans), which drives the lexical + vector
halves of hybrid search.

Design rules:
- Reuse the app's existing taxonomy (role groups, level bands, location groups).
  No new dictionaries here. The companies a query may name are passed in by
  the caller (`companies`, slug -> the names a person types for it), so this
  module reads no roster and stays pure.
- Be conservative. Compensation needs an explicit money cue ($ / k / m / a comp
  word) so "top 5" or "400 roles" never become a comp filter. Untracked names
  (e.g. "Meta") stay in the remainder rather than forcing a wrong filter: a
  name outside `companies` is never a company.
- Never lose the query: if every token was consumed by structured extraction, the
  remainder falls back to the full text so the semantic search still has signal.

Pure and dependency-free (regex + taxonomy). Fully unit-testable without a DB.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

from tracker.schema import LevelBand, WorkplaceType
from tracker.taxonomy.countries import BY_SLUG
from tracker.taxonomy.locations import LOCATION_GROUPS
from tracker.taxonomy.roles import family_named, get_group


def _bounded_needles() -> dict[str, tuple[str, ...]]:
    """Whole-word search terms per location group: display name + aliases.

    Aliases matter because people type codes and short forms — "UAE", "USA",
    "Korea" — none of which are the display name. Alpha-2 is absent by
    construction: the country table strips it from `aliases`, so "IN" cannot
    tag India inside "IN-person".

    Longest first, so a longer name is consumed before a shorter one nested
    inside it and the remainder loses the whole phrase rather than half of it.
    """
    out: dict[str, tuple[str, ...]] = {}
    for slug, meta in LOCATION_GROUPS.items():
        needles = {str(meta.get("display", "")).lower()}
        country = BY_SLUG.get(slug)
        if country is not None:
            needles.update(country.aliases)
        out[slug] = tuple(sorted(filter(None, needles), key=len, reverse=True))
    return out


_BOUNDED_NEEDLES = _bounded_needles()

_Span = tuple[int, int]


@dataclass(frozen=True)
class ParsedQuery:
    """Structured filters extracted from a free-text query + semantic remainder."""

    company: list[str] = field(default_factory=list)
    level_band: list[str] = field(default_factory=list)
    family: list[str] = field(default_factory=list)
    workplace_type: list[str] = field(default_factory=list)
    location_group: list[str] = field(default_factory=list)
    comp_min: int | None = None
    comp_max: int | None = None
    remainder: str = ""

    def structured(self) -> dict:
        """Return only the non-empty structured filters (for merge into params)."""
        out: dict = {}
        if self.company:
            out["company"] = self.company
        if self.level_band:
            out["level_band"] = self.level_band
        if self.family:
            out["family"] = self.family
        if self.workplace_type:
            out["workplace_type"] = self.workplace_type
        if self.location_group:
            out["location_group"] = self.location_group
        if self.comp_min is not None:
            out["comp_min"] = self.comp_min
        if self.comp_max is not None:
            out["comp_max"] = self.comp_max
        return out

    def as_echo(self) -> dict:
        """Full structured echo (including remainder) for the API `parsed` field."""
        return {
            "company": self.company,
            "level_band": self.level_band,
            "family": self.family,
            "workplace_type": self.workplace_type,
            "location_group": self.location_group,
            "comp_min": self.comp_min,
            "comp_max": self.comp_max,
            "remainder": self.remainder,
        }


# --- level-band synonyms (word-boundary matched) --------------------------- #
# Ordered longest-first so "vice president" is tried before a bare token.
# Public: `search.policy` strips these tokens before comparing role heads, and a
# second copy of the level vocabulary is exactly what would drift.
LEVEL_SYNONYMS: tuple[tuple[str, LevelBand], ...] = (
    ("vice president", LevelBand.DIRECTOR_PLUS),
    ("distinguished", LevelBand.DIRECTOR_PLUS),
    ("entry level", LevelBand.ENTRY),
    ("entry-level", LevelBand.ENTRY),
    ("mid-level", LevelBand.MID),
    ("mid level", LevelBand.MID),
    ("principal", LevelBand.PRINCIPAL),
    ("new grad", LevelBand.ENTRY),
    ("director", LevelBand.DIRECTOR_PLUS),
    ("fellow", LevelBand.DIRECTOR_PLUS),
    ("internship", LevelBand.INTERN),
    ("junior", LevelBand.ENTRY),
    ("senior", LevelBand.SENIOR),
    ("intern", LevelBand.INTERN),
    ("staff", LevelBand.STAFF),
    ("vp", LevelBand.DIRECTOR_PLUS),
    ("sr", LevelBand.SENIOR),
)

# --- workplace-type keywords ----------------------------------------------- #
_WORKPLACE_KEYWORDS: tuple[tuple[str, WorkplaceType], ...] = (
    ("in office", WorkplaceType.ONSITE),
    ("in-office", WorkplaceType.ONSITE),
    ("on site", WorkplaceType.ONSITE),
    ("on-site", WorkplaceType.ONSITE),
    ("onsite", WorkplaceType.ONSITE),
    ("remote", WorkplaceType.REMOTE),
    ("hybrid", WorkplaceType.HYBRID),
)

# A money cue is required before a bare number becomes a comp bound.
_MONEY_CUE = re.compile(r"[$]|\b\d[\d,\.]*\s*[km]\b|\b(?:comp|pay|salary|tc)\b", re.I)

_NUM = r"\$?\s*(\d[\d,\.]*)\s*([km])?"
_RANGE_RE = re.compile(rf"{_NUM}\s*(?:-|–|to)\s*{_NUM}", re.I)
_MIN_RE = re.compile(
    rf"(?:over|above|more than|at\s+least|greater than|min(?:imum)?|from|>=?)\s*{_NUM}", re.I
)
_MAX_RE = re.compile(
    rf"(?:under|below|less than|up to|at\s+most|max(?:imum)?|<=?)\s*{_NUM}", re.I
)
_PLUS_RE = re.compile(rf"{_NUM}\s*\+", re.I)


def _to_dollars(num: str, suffix: str | None) -> int | None:
    """Parse a number + optional k/m suffix into whole dollars.

    Returns None for values too small to be a plausible comp bound without a
    magnitude suffix (guards against "$500" or a stray "5" becoming a filter).
    """
    try:
        val = float(num.replace(",", ""))
    except ValueError:
        return None
    if suffix == "k":
        val *= 1_000
    elif suffix == "m":
        val *= 1_000_000
    elif val < 10_000:
        # No magnitude suffix and implausibly small for total comp — ignore.
        return None
    return int(val)


def _extract_comp(text: str, spans: list[_Span]) -> tuple[int | None, int | None]:
    """Extract (comp_min, comp_max). Requires an explicit money cue in the text."""
    if not _MONEY_CUE.search(text):
        return None, None

    comp_min: int | None = None
    comp_max: int | None = None

    m = _RANGE_RE.search(text)
    if m:
        lo = _to_dollars(m.group(1), m.group(2) or m.group(4))
        hi = _to_dollars(m.group(3), m.group(4))
        if lo is not None and hi is not None:
            comp_min, comp_max = min(lo, hi), max(lo, hi)
            spans.append((m.start(), m.end()))
            return comp_min, comp_max

    for regex, is_min in ((_MIN_RE, True), (_PLUS_RE, True), (_MAX_RE, False)):
        m = regex.search(text)
        if not m:
            continue
        val = _to_dollars(m.group(1), m.group(2))
        if val is None:
            continue
        if is_min and comp_min is None:
            comp_min = val
        elif not is_min and comp_max is None:
            comp_max = val
        spans.append((m.start(), m.end()))

    return comp_min, comp_max


def _find_all(text: str, needle: str) -> list[_Span]:
    """All non-overlapping spans of a literal needle (word-boundary where alnum)."""
    esc = re.escape(needle)
    # Word-boundary only makes sense when the needle starts/ends with a word char.
    left = r"\b" if needle[:1].isalnum() else ""
    right = r"\b" if needle[-1:].isalnum() else ""
    return [(m.start(), m.end()) for m in re.finditer(f"{left}{esc}{right}", text)]


def _company_spans(low: str, companies: Mapping[str, Iterable[str]]) -> tuple[list[str], list[_Span]]:
    """The companies `low` names, in `companies` order, and the spans naming them.

    Longest name first across every company, and a span already taken is not
    read again: "google deepmind" names Google DeepMind, not Google as well."""
    needles = sorted(
        ((name.lower(), slug) for slug, names in companies.items() for name in names if name),
        key=lambda pair: len(pair[0]), reverse=True,
    )
    taken: list[_Span] = []
    named: set[str] = set()
    for needle, slug in needles:
        for start, end in _find_all(low, needle):
            if any(start < other_end and other_start < end for other_start, other_end in taken):
                continue
            taken.append((start, end))
            named.add(slug)
    return [slug for slug in companies if slug in named], taken


def companies_mentioned(
    raw: str, companies: Mapping[str, Iterable[str]]
) -> dict[str, tuple[str, ...]]:
    """The entries of `companies` with a name `raw` holds as `parse_query`
    matches one (whole words, any case): every company the query could name,
    whichever of them a longer name then claims."""
    low = (raw or "").strip().lower()
    return {
        slug: tuple(names)
        for slug, names in companies.items()
        if any(name and _find_all(low, name.lower()) for name in names)
    }


def parse_query(raw: str, *, companies: Mapping[str, Iterable[str]]) -> ParsedQuery:
    """Parse free text into structured filters + a semantic remainder.

    `companies` is every company a query may name, slug -> the names a person
    types for it (lowercase or not); an empty mapping names none."""
    text = (raw or "").strip()
    if not text:
        return ParsedQuery(remainder="")

    low = text.lower()
    spans: list[_Span] = []

    # --- companies --------------------------------------------------------- #
    companies_named, company_spans = _company_spans(low, companies)
    spans.extend(company_spans)

    # --- role family ------------------------------------------------------ #
    # A posting gets exactly one family, by the taxonomy's own precedence
    # (`roles.family_named`): a sales, support or documentation engineer
    # before software engineering's catch-all `engineer`. The query is read by
    # the same rule, so the filter matches how postings are filed; the chosen
    # family's own keywords leave the remainder.
    families: list[str] = []
    family = family_named(text)
    group = get_group(family) if family else None
    if group is not None:
        spans.extend(span for kw in group.keywords for span in _find_all(low, kw))
        families.append(group.slug)

    # --- level bands ------------------------------------------------------- #
    bands: list[str] = []
    for token, band in LEVEL_SYNONYMS:
        found = _find_all(low, token)
        if found:
            spans.extend(found)
            if band.value not in bands:
                bands.append(band.value)

    # --- workplace type ---------------------------------------------------- #
    workplaces: list[str] = []
    for token, wp in _WORKPLACE_KEYWORDS:
        found = _find_all(low, token)
        if found:
            spans.extend(found)
            if wp.value not in workplaces:
                workplaces.append(wp.value)

    # --- location groups --------------------------------------------------- #
    locations: list[str] = []
    # All groups, not just tracked ones: the tracked set is a runtime DB setting,
    # and downstream `in_scope` filtering already applies it to results.
    #
    # Display names match on a WORD BOUNDARY. The curated `substrings` are
    # deliberately partial (", uk", " uk") and keep matching loosely, but a
    # display name is a whole word, and every country's is in this loop.
    # Unbounded, "china" tags a china shop, "chad" tags Chad, "jordan" tags
    # every Jordan, and "georgia" tags an Atlanta search.
    for slug, meta in LOCATION_GROUPS.items():
        hit = False
        for needle in filter(None, meta.get("substrings", [])):
            idx = low.find(needle)
            while idx != -1:
                spans.append((idx, idx + len(needle)))
                hit = True
                idx = low.find(needle, idx + len(needle))
        # Display name AND the country's own aliases, so people can type what
        # they actually type: "UAE" rather than "United Arab Emirates", "USA",
        # "Korea". All bounded.
        for needle in _BOUNDED_NEEDLES.get(slug, ()):
            for match in re.finditer(rf"\b{re.escape(needle)}\b", low):
                spans.append(match.span())
                hit = True
        if hit:
            locations.append(slug)

    # --- compensation ------------------------------------------------------ #
    comp_min, comp_max = _extract_comp(low, spans)

    remainder = _remainder(text, spans)
    return ParsedQuery(
        company=companies_named,
        level_band=bands,
        family=families,
        workplace_type=workplaces,
        location_group=locations,
        comp_min=comp_min,
        comp_max=comp_max,
        remainder=remainder,
    )


def _remainder(text: str, spans: list[_Span]) -> str:
    """Text with all matched spans blanked out, whitespace collapsed.

    Also drops now-orphaned connective tokens (at / in / with / and) so the
    remainder reads as clean search terms. Falls back to the full text when
    everything was consumed, keeping semantic signal for fully-structured queries.
    """
    if not spans:
        return text
    keep = [True] * len(text)
    for start, end in spans:
        for i in range(max(0, start), min(len(text), end)):
            keep[i] = False
    kept = "".join(c if keep[i] else " " for i, c in enumerate(text))
    tokens = [t for t in kept.split() if t.lower() not in _STOPWORDS]
    remainder = " ".join(tokens).strip()
    return remainder or text


_STOPWORDS = {"at", "in", "on", "with", "and", "the", "a", "an", "of", "for", "to", "roles", "role", "jobs", "job", "positions", "position"}
