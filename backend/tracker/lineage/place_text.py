"""Two descriptions that differ only by where the role is. Pure.

A place set needs one text, compared exactly after folding case and
whitespace. Some employers write the place into the text: Brex's "based in
San Francisco" against "based in New York City", Amazon's pay line per place
("USA, NY, New York - 194,700.00 - 263,400.00 USD annually" against "USA, CO,
Denver - 177,000.00 - ..."). Those postings are one role at two places, and
the exact hash called them two.

`differs_only_by_place` compares the word sequences and accepts every
difference that is one of:

1. punctuation, bullets, case or spacing (the words are equal);
2. a run of place words: the words of either posting's own place labels, the
   other spelling of a state or province they name ("NY" for New York), and a
   few generic ones ("city", "county");
3. a run of numbers within `PAY_REACH` words after a place-word run, or
   figures after the place words inside one run: the pay stated for that
   place.

Anything else is a different text. A pay figure that moves with no place
beside it is the controlling case: Apple prints one pay line per posting, and
a different figure at the same place is a different level, not a place. So is
a moved "3+ years" or "8+ years". Words of a work arrangement ("remote",
"hybrid") are never place words: an arrangement is a difference the user
needs to see, not noise.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from difflib import SequenceMatcher

from tracker.taxonomy.locations import region_aliases

#: How far after a place-word run a number run may sit and still be that
#: place's pay: "co, denver - 177,000.00 - 240,000.00 usd" puts the first
#: figure one word after the place and the second four.
PAY_REACH = 8

_WORD = re.compile(r"[a-z0-9]+")

#: Words that name a kind of place, never one place.
GENERIC_PLACE_WORDS = frozenset(
    {"city", "county", "state", "metro", "area", "greater", "region", "province", "district"}
)

#: How a role is worked. Never stripped as place words, though boards put
#: them in place labels ("Germany (Remote)").
_ARRANGEMENT_WORDS = frozenset(
    {"remote", "hybrid", "onsite", "on", "site", "office", "in", "distributed", "anywhere", "or", "and"}
)


def words(text: str | None) -> list[str]:
    return _WORD.findall((text or "").lower())


def place_words(labels: Iterable[str]) -> frozenset[str]:
    """The words of the place labels and the other spelling of any state or
    province they name ("New York" -> "ny"), less arrangement words."""
    found: set[str] = set()
    for label in labels:
        found.update(words(label))
        found.update(region_aliases(label))
    return frozenset(found - _ARRANGEMENT_WORDS)


def _figures_follow_a_place(run: list[str], allowed: frozenset[str]) -> bool:
    """Every figure in the run comes after a place word: the pay of that
    place, never a figure the place merely sits beside ("3 years in London")."""
    seen_place = False
    for w in run:
        if w.isdigit() and not seen_place:
            return False
        seen_place = seen_place or w in allowed
    return True


def differs_only_by_place(
    left: str | None,
    left_places: Iterable[str],
    right: str | None,
    right_places: Iterable[str],
) -> bool:
    """True when the two texts are one text but for where the role is."""
    a, b = words(left), words(right)
    if not a or not b:
        return False
    if a == b:
        return True
    allowed = place_words([*left_places, *right_places]) | GENERIC_PLACE_WORDS
    # Necessary and cheap: a word only one side has must be a place word or a
    # figure, or some changed run holds a word that is neither.
    if any(not (w in allowed or w.isdigit()) for w in set(a) ^ set(b)):
        return False
    last_place_end: int | None = None
    for tag, i1, i2, j1, j2 in SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if tag == "equal":
            continue
        changed = a[i1:i2] + b[j1:j2]
        if all(w in allowed for w in changed):
            last_place_end = i2
        elif all(w in allowed or w.isdigit() for w in changed) and all(
            _figures_follow_a_place(side, allowed) for side in (a[i1:i2], b[j1:j2])
        ):
            # A place and the pay stated for it, in one run: "ny new york
            # 194 700" against "co denver 177 000".
            last_place_end = i2
        elif all(w.isdigit() for w in changed):
            if last_place_end is None or i1 - last_place_end > PAY_REACH:
                return False
        else:
            return False
    return last_place_end is not None
