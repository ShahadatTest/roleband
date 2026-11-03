"""The ladder rung the employer PRINTS in the posting, before we guess one.

`jobs.level_band` and `jobs.family` are the KEY that selects one
`company_comp_level` row, and every comp figure RoleBand shows is read off that
row. Otherwise both halves of that key are inferred from the title. Two
employers do not make us guess:

**Microsoft** states its own discipline and rung in the compensation sentence:
``Product Management IC5 - The typical base pay range for this role across the
U.S. is USD $155,800 - $277,200 per year``. A stored posting without that
sentence states no rung; absence there is not a parse failure.

**Nvidia** states a band PER LEVEL: ``the base salary range is 200,000 USD -
322,000 USD for Level 5, and 240,000 USD - 379,500 USD for Level 4``.

A req can be open at TWO adjacent rungs, and that is a fact about the req rather
than a parse ambiguity: some Microsoft postings state two ("Senior and
Principal Product Manager", "Principal + Senior Product Manager"), and Nvidia's
per-level form always does. So the stated rung is a SET, rendered ascending and
"/"-joined ("IC4/IC5"), and `jobs.raw_level` keeps it whole. Collapsing it to one
rung here would throw away the only evidence that the req is dual-level.

This module only READS what is printed. Turning a rung into a `LevelBand` is a
per-company claim about a ladder and lives in `levels.companies` (`printed`), which is
where every other rung vocabulary already lives.
"""

from __future__ import annotations

import re

# Microsoft: "<Discipline> IC5 - The typical base pay range ...". The discipline
# prefix is not needed for the rung, but requiring it is what keeps the pattern
# from matching prose: the sentence is the only place this shape occurs.
_MICROSOFT_RUNG_RE = re.compile(
    r"[A-Z][A-Za-z &/]+?\s+(M|IC)(\d)\s*-\s*The typical base pay",
)

# Nvidia: "... is 200,000 USD - 322,000 USD for Level 5, and ... for Level 4".
# Anchored on the pay clause, never on a bare "Level 5" — that phrase appears in
# prose ("Level 3 support") and a level we invent is worse than none.
_NVIDIA_LEVEL_RE = re.compile(
    r"[\d,]+\s*USD\s*-\s*[\d,]+\s*USD\s+for\s+Level\s*(\d+)",
    re.IGNORECASE,
)


def _microsoft_rungs(text: str) -> list[str]:
    # Sorted by track then number so "IC4/IC5" is stable regardless of the order
    # the two blocks appear in — Microsoft prints them either way round.
    return sorted({f"{track.upper()}{num}" for track, num in _MICROSOFT_RUNG_RE.findall(text)})


def _nvidia_rungs(text: str) -> list[str]:
    return [f"Level {n}" for n in sorted({int(m) for m in _NVIDIA_LEVEL_RE.findall(text)})]


# company slug -> the reader for that employer's printed rung. Absence is the
# common case and the honest one: most employers print no rung at all, and
# their rare regex-shaped hits are prose ("the CPUs in the M1/M2 Mac", "direct L5/L6 PMs"), which is why this
# is a per-company table rather than one pattern applied to everyone.
_READERS = {
    "microsoft": _microsoft_rungs,
    "nvidia": _nvidia_rungs,
}

#: Employers whose postings can print a rung: the only rows worth reading a
#: description for when `raw_level` is empty (`workflows.relevel`).
PRINTING_COMPANIES = frozenset(_READERS)


def stated_rungs(company: str, text: str | None) -> list[str]:
    """Every ladder rung this posting's text states, ascending. Empty = none stated."""
    reader = _READERS.get(company)
    if reader is None or not text:
        return []
    return reader(text)


def stated_level(company: str, text: str | None) -> str | None:
    """`jobs.raw_level` for this posting: the stated rung(s), or None.

    Two rungs render as "IC4/IC5" — one string, both facts kept.
    """
    rungs = stated_rungs(company, text)
    return "/".join(rungs) or None


def lowest_stated_rung(raw_level: str | None) -> str | None:
    """The rung a dual-level req is banded at: the LOWER one.

    Not a preference — the only choice that keeps the two stored numbers
    consistent. `jobs.disclosed_base_*` already holds the LOWER rung's band (the
    disclosure pass takes the lower of the two blocks), so banding at the higher rung would pair a
    high level with a low band and manufacture a `stated_below_measured` flag out
    of our own bookkeeping.
    """
    if not raw_level:
        return None
    return raw_level.split("/")[0] or None
