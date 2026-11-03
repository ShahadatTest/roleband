"""The years of experience one requirement line states.

One grammar for every reader of years: the qualification extractor and the
level evidence read the same statements, so they cannot disagree about what a
line requires.

**What.** A statement is "N+ years", "N-M years" (N), "at least N years",
"minimum (of) N years", "N years minimum", "N or more years", or a bare "N
years". The marked forms need no "experience": "5+ years of owning program
strategy" is a requirement, and employers write minimums that way. A bare "N years" in prose needs its clause to say experience, so "20 years
in business" and "over 10 years of serving customers" state nothing. On a line
of the employer's requirement list (`requirement_line`) it does not:
"8 years working on integration technologies" and "or 6 years and a Master's
degree" are requirements. Never one, on any line: a window ("within
the last 3 years", "in 4 years", "up to 5 years", "after five years"), an age, a
date, a salary, a "4 year degree", "years ago" or "years of service". Numbers
may be words ("two years of experience").

**Every number, in order.** A line can state more than one: "5+ years of
software engineering, with at least 1 to 2 years of people management", or a
degree ladder ("Bachelor's AND 4+ years OR Master's AND 3+ years OR Doctorate
AND 1+ year"). The caller keeps them all; the largest is the line's headline,
the base a ladder substitutes down from.

Pure text: no section, no modality, no band. Which block a line sits in is
`segment`'s question; whether years say anything about a level is measured per
company, never assumed.
"""

from __future__ import annotations

import re

#: A requirement longer than this is not a requirement (a founding date, a tenure).
MAX_YEARS = 25

_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
    "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14,
    "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19,
    "twenty": 20, "twenty-one": 21, "twenty-two": 22, "twenty-three": 23,
    "twenty-four": 24, "twenty-five": 25,
}
# A number, never the tail of a larger one: "$120,000", "2026", "3.5" and
# a glued "experience.8 years" are told apart by what precedes the digits.
_NUM = r"(?:(?<![\d,$])(?<!\d\.)\d{1,2}|\b(?:" + "|".join(sorted(_WORDS, key=len, reverse=True)) + r"))"

_YEARS_RE = re.compile(
    rf"(?P<lead>\b(?:at\s+least|minimum(?:\s+of)?|min\.?(?:\s+of)?|over|more\s+than)\s+)?"
    rf"(?P<n>{_NUM})"
    # The legal form repeats the number in digits: "five (5) years".
    r"(?:\s*\(\d{1,2}\))?"
    rf"(?:\s*(?P<plus>\+))?(?:\s+or\s+more)?"
    # A range reads its floor: "3-5", "3 to 5", "between 3 and 5", "1 or 2".
    rf"(?:\s*(?:-|–|—|\b(?:to|and|or)\b)\s*(?P<m>{_NUM})\s*\+?)?"
    r"\s*(?:(?:full[- ]time|overall|total|combined|professional|relevant|industry|work)\s+)?"
    r"(?:years?|yrs?)\b(?:\(s\))?(?P<min>\s+minimum\b)?",
    re.IGNORECASE,
)
# What follows the word "years" when it is not a requirement.
_NOT_REQUIREMENT_RE = re.compile(
    r"^(?:\s*(?:ago|old|of\s+age|(?:or|and)\s+(?:older|above|over)|of\s+(?:customer\s+)?service|in\s+business|of\s+serving|"
    r"of\s+(?:history|operation)|young|running|of\s+(?:college|university|study|school)|"
    r"[- ]?(?:degree|college|university|bachelor)|from\s+now)\b|\s*\?)",
    re.IGNORECASE,
)
# What precedes a bare "N years" when it is a window, not a requirement.
# "for 20 years" is a window ("in business for 20 years") unless the line is
# "looking for" or "seeking" them, which is a requirement.
# A substitution note ("Master's = one year") states an exchange rate, not a bar.
_WINDOW_RE = re.compile(
    r"(?:\b(?:last|past|within|in|after|next|up\s+to|every|per|(?<!looking\s)(?<!seeking\s)for|over\s+the|less\s+than|"
    r"under|fewer\s+than|first)\s+(?:the\s+)?|=\s*)$",
    re.IGNORECASE,
)
# The clause a bare "N years" must sit in: up to a full stop, semicolon or line end.
_CLAUSE_END_RE = re.compile(r"[;\n]|\.(?!\d)")
_EXPERIENCE_RE = re.compile(r"\bexperience[sd]?\b", re.IGNORECASE)


def _number(token: str) -> int:
    return int(token) if token.isdigit() else _WORDS[token.lower()]


def stated_years(text: str, *, requirement_line: bool = False) -> list[int]:
    """Every years-of-experience statement in `text`, in the order written.

    `requirement_line`: the text is one line of the employer's minimum or
    preferred list, where a bare "N years" is a requirement without saying
    experience."""
    found = []
    for match in _YEARS_RE.finditer(text):
        tail = text[match.end():]
        if _NOT_REQUIREMENT_RE.match(tail):
            continue
        lead = (match.group("lead") or "").lower()
        if lead.startswith(("over", "more")) and not match.group("plus"):
            # "over 10 years of serving customers" is a boast, not a bar; "more
            # than 5 years of experience" still is one, by its clause below.
            marked = False
        else:
            marked = bool(
                lead or match.group("plus") or match.group("m") or match.group("min")
                or " or more" in match.group(0).lower()
            )
        if not marked:
            if _WINDOW_RE.search(text[: match.start()]):
                continue
            clause = _CLAUSE_END_RE.split(tail, maxsplit=1)[0]
            if not requirement_line and not _EXPERIENCE_RE.search(clause):
                continue
        years = _number(match.group("n"))
        if 0 < years <= MAX_YEARS:
            found.append(years)
    return found


def stated_experience_field(text: str) -> list[int]:
    """Read a standalone label/value field without assigning requirement modality."""
    field = re.fullmatch(r"years? of experience:\s*(.+?)\s*\.?", text.strip(), re.I)
    if field is None:
        return []
    normalized = field.group(1) + " years"
    if _YEARS_RE.fullmatch(normalized) is None:
        return []
    return stated_years(normalized, requirement_line=True)
