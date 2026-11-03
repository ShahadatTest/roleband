"""Reading a rung label nobody wrote a ladder entry for.

A pay source names rungs in its own words ("L4 Product Manager",
"Senior Product Manager", "Group PM"). `resolve_band` bands them: our own
dataset first (`atlas_band`: the company's ladder by the label, by the code at
its head, or by a code the company prints), then the aliases the source sends,
then the seniority words.

Our dataset (`tracker/levels/atlas/`) is the source of truth for which level a
rung is. The aliases and the words only band a label the atlas does not know
yet, and every such label is a gap to fill in the atlas, not a reading to keep.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from tracker.levels.ladder import band_for, band_for_stated_rung
from tracker.levels.vocabulary import (
    ENTRY_RE,
    INTERN_RE,
    MGMT_L6,
    NOT_STAFF,
    PRINCIPAL,
    SENIOR,
    STAFF,
    has_word,
    junior_marked,
    names_director,
    rung_word_band,
)
from tracker.schema import LevelBand

# A ladder code at the head of a label: "L4 Product Manager" -> "L4", "L6 SDM" ->
# "L6", "IC5" -> "IC5", Microsoft's bare "64" -> "64". Non-SWE families qualify the
# code with the family's title (Meta's product managers, Amazon's managers); the
# code is the rung and the qualifier is not.
_LADDER_CODE_RE = re.compile(r"^(?:(?:ICT|IC|VP|L|E|M|D|G)\d{1,2}|\d{2})(?=\s|$)", re.IGNORECASE)

# Seniority words for a rung NAMED rather than numbered ("Senior Product Manager",
# "Group PM", "Director"). A label reads the vocabulary a posting's title does
# (`levels.vocabulary`): the same words, matched whole, tried in the order
# `enrich.level_mapper` tries them (an intern or entry marker, then an Associate
# no rung word outranks, then director, principal, the staff words and the
# people-manager titles, senior). So a posting titled "Group Product Manager" and
# the "Group Product Manager" rung land in the same band: the comp lookup joins
# on exactly that. A rung label is not a posting title, and it reads differently
# in five places:
#
# - A label with no rung word is the ladder's mid rung. A bare "Product Manager"
#   or "Member of Technical Staff" is mid here, where the mapper reads it senior,
#   unconfirmed, as a guess.
# - The MTS family is a ladder whose prefix names the rung, so an abbreviation
#   reads as its spelled-out rung word: AMTS is Associate (entry), SMTS Senior,
#   LMTS Lead (staff), PMTS Principal, DMTS Distinguished. The mapper reads
#   every MTS title senior.
# - A trailing numeral is the rung's place on the ladder ("Product Manager II",
#   "Engineer 5"): I/1 is the first full-time rung (entry), II/2 the mid one,
#   III/3 and 4-9 senior. The mapper reads only 4-9 (senior) and leaves the
#   rest to the company's ladder.
# - "Partner" names a firm's top rank and "Group" a rung over managers ("Group
#   PM"); in a posting's title both more often name a role or an org (a Partner
#   Manager, the Payments Group), and the mapper reads neither.
# - "APM" is Google's Associate Product Manager rung (APM1/APM2 on its ladder),
#   and a ladder code may glue its number to VP ("VP1", "VP2"): still a VP.
_LABEL_DIRECTOR = ("partner",)
_LABEL_PRINCIPAL = ("group",)
_LABEL_ENTRY = ("apm",)
_VP_CODE_RE = re.compile(r"(?<![a-z])[a-z]?vp\d{1,2}\b")
_MTS_RE = re.compile(r"(?<![a-z])(member of technical staff|amts|smts|lmts|pmts|dmts|mts)s?(?![a-z])")
_MTS_RUNG_WORD = {
    "member of technical staff": "", "mts": "",
    "amts": "associate", "smts": "senior", "lmts": "lead", "pmts": "principal", "dmts": "distinguished",
}
_RUNG_NUMERAL_RE = re.compile(r"\b(iii|ii|i|[1-9])$")
_NUMERAL_BANDS = {"i": LevelBand.ENTRY, "1": LevelBand.ENTRY, "ii": LevelBand.MID, "2": LevelBand.MID}


def _band_from_words(label: str) -> LevelBand:
    text = _MTS_RE.sub(lambda found: f" {_MTS_RUNG_WORD[found.group(1)]} ", f" {label.strip().lower()} ")
    if INTERN_RE.search(text):
        return LevelBand.INTERN
    if ENTRY_RE.search(text):
        return LevelBand.ENTRY
    if junior_marked(text) or has_word(text, _LABEL_ENTRY):
        return rung_word_band(text) or LevelBand.ENTRY
    if names_director(text) or has_word(text, _LABEL_DIRECTOR) or _VP_CODE_RE.search(text):
        return LevelBand.DIRECTOR_PLUS
    if has_word(text, PRINCIPAL) or has_word(text, _LABEL_PRINCIPAL):
        return LevelBand.PRINCIPAL
    if (has_word(text, STAFF) and not has_word(text, NOT_STAFF)) or has_word(text, MGMT_L6):
        return LevelBand.STAFF
    if has_word(text, SENIOR):
        return LevelBand.SENIOR
    numeral = _RUNG_NUMERAL_RE.search(text.strip())
    if numeral:
        return _NUMERAL_BANDS.get(numeral.group(1), LevelBand.SENIOR)
    return LevelBand.MID


def atlas_band(company: str, level_label: str) -> LevelBand | None:
    """The level OUR dataset gives this rung label, or None when it cannot
    place it: the company's ladder by the label's own spelling, then
    by the ladder code at its head ("L4 Product Manager" is Meta's L4), then by
    a code the company prints on its postings (Dropbox's "IC4"), the table its
    postings are levelled by. Nothing an outside source says decides it."""
    label = level_label.strip()
    found = band_for(company, label)
    if found is None:
        code = _LADDER_CODE_RE.match(label)
        if code:
            found = band_for(company, code.group(0).upper())
    return found if found is not None else band_for_stated_rung(company, label)


def resolve_band(company: str, level_label: str, *, aliases: Iterable[str] = ()) -> LevelBand:
    """Band for any rung a pay source names, in order of how much we trust the path.

    1. Our dataset (`atlas_band`): the company's ladder by the page's own label, by
       the ladder code at its head ("L4 Product Manager" -> Meta "L4"), or by a code
       the company prints.
    2. The ladder lookups on each alias: a rung may arrive as "Senior Product
       Manager" while Amazon's ladder knows it as `L6`; a plugin sends the
       rung's other names as `aliases` (it pairs them, the core never does),
       and the L-number is what the ladder knows.
    3. The seniority words in the label. Never None: a rung with no recognisable
       code and no seniority word is the ladder's mid rung, which is what a bare
       "Product Manager" is at Netflix.

    Our dataset stays the source of truth (`atlas_band`); the rest only band a
    label the atlas does not know yet, and the host marks such a band as
    `words` (`company_comp_level.band_source`).
    """
    placed = atlas_band(company, level_label)
    if placed is not None:
        return placed
    for candidate in aliases:
        seeded = band_for(company, candidate)
        if seeded is not None:
            return seeded
        code = _LADDER_CODE_RE.match(candidate.strip())
        if code:
            seeded = band_for(company, code.group(0).upper())
            if seeded is not None:
                return seeded
    return _band_from_words(level_label)


#: Who decides a rung's band (`company_comp_level.band_source` on rows of ours).
ATLAS = "atlas"
#: A rung the atlas cannot place, banded from its own words and aliases.
WORDS = "words"


def rung_band(company: str, level_label: str, aliases: Iterable[str] = ()) -> tuple[str, str]:
    """(band, who decided it) for a plugin's rung, worked out when it is READ:
    the atlas when it places the label, else its
    words and aliases. A plugin's stored row keeps what the plugin sent and is
    never re-banded in place, so an atlas change moves the next read, not the row."""
    placed = atlas_band(company, level_label)
    if placed is not None:
        return placed.value, ATLAS
    return resolve_band(company, level_label, aliases=aliases).value, WORDS
