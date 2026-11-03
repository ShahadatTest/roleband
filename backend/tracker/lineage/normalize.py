"""Title normalization for repost lineage matching.

Two grades:

- ``normalize_title`` — display-grade. Unicode/dash/whitespace/case normalized,
  with req-id noise, bracket noise ("(Remote)"), and a trailing location suffix
  removed. KEEPS level words so the cleaned title stays human-readable.
- ``title_key`` — match-grade. Everything ``normalize_title`` does PLUS level-token
  removal and punctuation stripping, because ``level_band`` is an independent gate:
  "Staff Software Engineer II" and "Software Engineer" key-equal when both are
  ``level_band=staff``.

Location stripping uses THE JOB'S OWN locations, never a gazetteer — far more
precise, and it reuses data we already have. ``title_key`` is NOT token-sorted:
the ordered key is what ``titles_equal`` compares, so "EM, Data Platform" and
"EM, Payments" never collapse. The unordered token set feeds ``title_jaccard``
only — a review-tier signal that never auto-links.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from tracker.platform.util import normalize_text

_WS = re.compile(r"\s+")

# Requisition-id noise, run on the already-lowercased normalized title.
_REQ_ID_RES: tuple[re.Pattern[str], ...] = (
    re.compile(r"\s*[(\[]?\br-?\d{3,}[)\]]?", re.I),            # R-4831, R4831, (R-4831)
    re.compile(r"\s*[(\[]?#\s?\d{3,}[)\]]?"),                    # #12345, (#12345)
    re.compile(
        r"\s*[(\[]?\b(?:job\s*id|req(?:uisition)?(?:\s*id)?|posting(?:\s*id)?)"
        r"\s*[:#-]?\s*\d{3,}[)\]]?",
        re.I,
    ),                                                           # req 88213, job id: 44
    re.compile(r"\s*[-|]\s*\d{4,}\s*$"),                         # trailing "- 12345"
    re.compile(r"\s*\b\d{6,}\b"),                                # bare long id
)

# Parenthetical / bracketed noise a repost commonly toggles.
_BRACKET_NOISE_RE = re.compile(
    r"\s*[(\[]\s*(?:"
    r"remote(?:[- ][a-z.]+)?|hybrid|onsite|on-site|"
    r"us|usa|u\.s\.?|uk|emea|apac|new|"
    r"[fmwdхe](?:\s*/\s*[fmwdхe]){1,3}|all\s+genders|"
    r"contract(?:or)?|fixed[- ]term|temporary|intern(?:ship)?|maternity\s+cover"
    r")\s*[)\]]",
    re.I,
)

# Seniority words + ladder codes + trailing roman numerals. Stripped ONLY in title_key.
_LEVEL_TOKEN_RE = re.compile(
    r"\b(?:"
    r"sr|snr|senior|staff|principal|prin|lead|distinguished|fellow|"
    r"l\d{1,2}|ict\d|ic\d|e\d|t\d|p\d|m\d|"
    r"levels?\s*\d+|grade\s*\d+|"
    r"i{1,3}|iv|vi{0,3}|ix"
    r")\b",
    re.I,
)

# Keep a separate ladder signal even though ``title_key`` removes it. The coarse
# ``level_band`` taxonomy is intentionally broad (for example, several provider
# grades map to ``senior``), so title equality must not erase a meaningful grade
# difference such as "Engineer I" versus "Engineer III".
_GRADE_RE = re.compile(
    r"\b(?:[litpem]\d{1,2}|i{1,3}|iv|v|vi{0,3}|ix)\b",
    re.I,
)

_SEG_SPLIT = re.compile(r"\s*(?:[-|@·/]|,)\s*")
_PUNCT_RE = re.compile(r"[^\w\s]")

# Location words the source appends but that aren't in a job's `locations` list.
_GENERIC_LOCS = frozenset(
    {
        "remote", "hybrid", "onsite", "on-site", "us", "usa", "u.s.", "u.s",
        "uk", "emea", "apac", "united states", "united kingdom", "worldwide",
        "multiple locations", "various",
    }
)


def strip_req_ids(title: str) -> str:
    for pat in _REQ_ID_RES:
        title = pat.sub(" ", title)
    return _WS.sub(" ", title).strip()


def strip_bracket_noise(title: str) -> str:
    return _WS.sub(" ", _BRACKET_NOISE_RE.sub(" ", title)).strip()


def _location_alts(locations: Sequence[str]) -> set[str]:
    alts = set(_GENERIC_LOCS)
    for loc in locations or ():
        norm = normalize_text(loc)
        if not norm:
            continue
        alts.add(norm)
        for part in re.split(r"[,/|]", norm):
            part = part.strip()
            if part:
                alts.add(part)
    return alts


def strip_location_suffix(title: str, locations: Sequence[str]) -> str:
    """Drop trailing comma/dash/pipe-separated segments that are locations.

    Only a job's own locations (plus a small generic set) count, so a role facet
    like "Data Platform" is never mistaken for a place.
    """
    alts = _location_alts(locations)
    segments = [s.strip() for s in _SEG_SPLIT.split(title)]
    while len(segments) > 1 and segments[-1].lower() in alts:
        segments.pop()
    return ", ".join(s for s in segments if s).strip()


def normalize_title(title: str | None, locations: Sequence[str] = ()) -> str:
    """Display-grade: cleaned but still readable (level words kept)."""
    t = normalize_text(title)
    t = strip_req_ids(t)
    t = strip_bracket_noise(t)
    t = strip_location_suffix(t, locations)
    return t.strip(" ,-|@·/").strip()


def title_key(title: str | None, locations: Sequence[str] = ()) -> str:
    """Match-grade: level tokens and punctuation removed, ordered (not sorted)."""
    t = normalize_title(title, locations)
    t = _LEVEL_TOKEN_RE.sub(" ", t)
    t = _PUNCT_RE.sub(" ", t)
    return _WS.sub(" ", t).strip()


def title_grade(title: str | None, locations: Sequence[str] = ()) -> str | None:
    """Provider ladder token from a normalized title, if one is explicit.

    Missing grade is neutral; two different explicit grades are counter-evidence.
    The last token is the title suffix in ordinary provider naming conventions.
    """
    matches = _GRADE_RE.findall(normalize_title(title, locations))
    return matches[-1].lower() if matches else None


def title_tokens(key: str) -> frozenset[str]:
    return frozenset(key.split())


def title_jaccard(a_key: str, b_key: str) -> float:
    a, b = title_tokens(a_key), title_tokens(b_key)
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def titles_equal(a_key: str, b_key: str) -> bool:
    return bool(a_key) and a_key == b_key
