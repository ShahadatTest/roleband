"""Two descriptions whose every difference is explained. Pure.

`place_text` joins two texts that differ only by where the role is. Employers
also vary what COMES with a place, in whole passages: the local benefits
block, a pay disclosure one posting has and the other lacks, the legal notice
a state or country requires, a line naming the office, the company intro a
brand rewrote. A pair whose every changed passage is one of those, with at
most `MAX_OTHER_WORDS` other words changed, is one role.

`differs_by_explained_passages` compares the two texts passage by passage
(`content_diff`, the twin detector's own split), classifies each passage only
one side has, and lets through:

- `boilerplate`: the passage recurs in at least `BOILERPLATE_MIN` of the
  company's postings, so it is the company's, not this role's (benefits,
  legal, intro blocks). Counted from data, no word list.
- `pay`: a pay statement (a pay word or currency with a figure, or a pay word).
- `legal`: an equal-opportunity, background-check, citizenship, visa, privacy
  or local-ordinance notice.
- `benefits`: insurance, retirement, leave, holidays, perks.
- `location`: a short passage (at most `LOCATION_MAX_WORDS`) naming a place
  of either posting.

Whatever is left (the passages that say what the job is) may differ by at most
`MAX_OTHER_WORDS` words, or only by place (`place_text`). Anything more is a
question for a person: the title, team, scope or requirements moved.

Three guards keep a different opening out, whatever its size: a figure in
the leftover change ("3+ years" against "8+ years"); a seniority word in it
("Senior", "Staff", "II"); and a pay figure that moves while the postings name
the same places (one city, a different band: a different level). A pay
disclosure only one side has, or pay that moves with the place, stays
explained. A single swapped ordinary word ("analysts" against "engineers") is
NOT caught: it reads exactly like swaps within one role ("enterprises" against
"client facing environment"), so no word rule separates them.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from difflib import SequenceMatcher

from tracker.lineage.content_diff import Passage, compare_descriptions, passage_key
from tracker.lineage.place_text import (
    GENERIC_PLACE_WORDS,
    differs_only_by_place,
    place_words,
    words,
)

#: The most leftover words one role's two postings differ by; a related
#: role changes more.
MAX_OTHER_WORDS = 20
#: A passage in this many of the company's postings is the company's.
BOILERPLATE_MIN = 3
LOCATION_MAX_WORDS = 30

_PAY = re.compile(
    r"(salary|compensation|\bpay\b|base pay|\bote\b|bonus|equity|\brsus?\b|stock|annual|per year"
    r"|per hour|hourly|\$|€|£|\b(usd|eur|gbp|cad|aud|chf|sek|nok|dkk|pln|inr|sgd|jpy)\b|\d+k\b)",
    re.I,
)
_LEGAL = re.compile(
    r"(equal opportunity|\beeo|discriminat|accommodat|criminal|background check|fair chance"
    r"|e-verify|citizen|clearance|\bvisa\b|right to work|privacy|recruitment fraud|scam|pursuant"
    r"|ordinance|county applicants|protected veteran|disabilit|affirmative action|export control"
    r"|\bitar\b|gdpr|data protection|consent)",
    re.I,
)
_BENEFITS = re.compile(
    r"(benefit|insurance|medical|dental|vision|401\(?k|pension|rrsp|vacation|holiday|paid time off"
    r"|\bpto\b|parental|maternity|paternity|\bleave\b|wellness|gym|stipend|perks|days off"
    r"|retirement|life assurance|cycle to work)",
    re.I,
)

#: Words that change the level of the job (`normalize_title` keeps them in
#: titles for the same reason).
SENIORITY_WORDS = frozenset(
    {"senior", "sr", "staff", "principal", "lead", "head", "director", "vp", "chief", "junior",
     "jr", "associate", "intern", "ii", "iii", "iv", "distinguished", "executive", "entry"}
)

#: Why a passage only one side has does not make the texts two.
EXPLAINED = ("boilerplate", "pay", "legal", "benefits", "location")


def passage_class(
    passage: Passage,
    places: Iterable[str],
    recurrence: Callable[[str], int],
    min_recurrence: int = BOILERPLATE_MIN,
) -> str:
    """What a passage only one posting has is: one of `EXPLAINED`, or
    `substantive`. `recurrence(key)` is how many of the company's postings
    hold the passage (`content_diff.passage_key`)."""
    text = passage.text
    if recurrence(passage_key(passage)[1]) >= min_recurrence:
        return "boilerplate"
    if _PAY.search(text) and re.search(r"\d", text):
        return "pay"
    if _LEGAL.search(text):
        return "legal"
    if _BENEFITS.search(text):
        return "benefits"
    if _PAY.search(text):
        return "pay"
    found = words(text)
    near = place_words(places) | GENERIC_PLACE_WORDS
    if len(found) <= LOCATION_MAX_WORDS and any(w in near for w in found):
        return "location"
    return "substantive"


def differs_by_explained_passages(
    left_sections: list[dict] | None,
    left_text: str | None,
    left_places: Iterable[str],
    right_sections: list[dict] | None,
    right_text: str | None,
    right_places: Iterable[str],
    recurrence: Callable[[str], int],
    min_recurrence: int = BOILERPLATE_MIN,
) -> bool:
    """True when every passage only one side has is explained, and what is
    left differs by at most `MAX_OTHER_WORDS` words or only by place."""
    left_places, right_places = list(left_places), list(right_places)
    diff = compare_descriptions(
        left_sections, left_text, right_sections, right_text, snippet_limit=10_000
    )
    if not diff.comparable:
        return False
    places = [*left_places, *right_places]
    left_classes = [(p, passage_class(p, places, recurrence, min_recurrence)) for p in diff.left_only]
    right_classes = [(p, passage_class(p, places, recurrence, min_recurrence)) for p in diff.right_only]

    def stated_pay(classes: list) -> bool:
        return any(c == "pay" and re.search(r"\d", p.text) for p, c in classes)

    same_places = {x.strip().casefold() for x in left_places} == {
        x.strip().casefold() for x in right_places
    }
    # Pay figures on both sides at the same places: a different band, not a place.
    pay_is_role = same_places and stated_pay(left_classes) and stated_pay(right_classes)
    held = {"substantive", "pay"} if pay_is_role else {"substantive"}
    left_rest = [p.text for p, c in left_classes if c in held]
    right_rest = [p.text for p, c in right_classes if c in held]
    if not left_rest and not right_rest:
        return True
    left_joined, right_joined = " ".join(left_rest), " ".join(right_rest)
    if differs_only_by_place(left_joined, left_places, right_joined, right_places):
        return True
    a, b = words(left_joined), words(right_joined)
    changed_words: list[str] = []
    for tag, i1, i2, j1, j2 in SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if tag != "equal":
            changed_words += a[i1:i2] + b[j1:j2]
    if any(w.isdigit() or w in SENIORITY_WORDS for w in changed_words):
        return False
    changed = sum(
        max(i2 - i1, j2 - j1)
        for tag, i1, i2, j1, j2 in SequenceMatcher(None, a, b, autojunk=False).get_opcodes()
        if tag != "equal"
    )
    return changed <= MAX_OTHER_WORDS


_YEARS = re.compile(r"(\d+)\s*\+?\s*(?:years|yrs)", re.I)


def years_asked(text: str | None) -> frozenset[int]:
    """The years-of-experience figures a text asks for ("7+ years" -> 7)."""
    return frozenset(int(n) for n in _YEARS.findall(text or ""))


def requirements_conflict(left: str | None, right: str | None) -> bool:
    """Two texts whose headline experience asks differ: each asks for years
    and the most it asks is not the same ("Sr. Operations Manager" at 7+
    against 5+ years of management). The highest figure, not the whole set:
    some employers' templates add optional bullets with smaller figures to the
    same role. A text that asks for none says nothing either way."""
    a, b = years_asked(left), years_asked(right)
    return bool(a) and bool(b) and max(a) != max(b)

