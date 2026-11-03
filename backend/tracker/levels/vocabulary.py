"""The generic seniority vocabulary: the words any company's titles use for a
rung, and how a title is matched against them.

Two readers share it. `enrich.level_mapper` reads a posting's title with it
once the employer's own statements (a printed rung, the company's ladder words)
have had their say; `levels.words` reads a pay source's rung label the atlas
cannot place. Both read these words, by this whole-word match. What each makes
of a title the words do not settle is its own, and `levels.words` says where
it differs.

Every reader here takes the lowered title padded with a space at each end.
"""

from __future__ import annotations

import functools
import re
from collections.abc import Iterable

from tracker.schema import LevelBand

# Explicit early-stage markers, checked before everything else. Two distinct
# first-class stages, not a disqualifier bucket: an internship or a
# student job is not a first full-time role, so a person starting out is not
# shown internships, and an intern marker wins over an entry one ("Graduate
# Intern" is an intern).
#
# Whole words, never substrings: "intern" sits inside Internal, Internet and
# Internals, and as a substring it would band "Staff Software Engineer, Internet
# Egress" and "Internal Audit Manager" entry CONFIRMED. The suffixes are the
# marker's own inflections, nothing wider; German boards write the stage as one
# compound word ("Werkstudent", "Praktikant/in"), so the compounds are listed.
INTERN_RE = re.compile(
    r"\b(?:interns?|internships?|students?|werkstudent(?:in|en)?|praktikant(?:in|en)?|praktikum)\b"
)
ENTRY_RE = re.compile(
    r"\b(?:apprentices?|apprenticeships?|new grads?|"
    r"early[- ]careers?|graduates?|entry[- ]level|trainees?|traineeprogramm\w*)\b"
)
#: Junior and Associate name the first full-time rung, which is Entry.
_JUNIOR_RE = re.compile(r"\b(?:juniors?|jr\b\.?|associates?)\b")
#: An "Associate" that names no first rung, masked before the rule
#: above reads the title. TikTok tags a contractor role "(Third-Party
#: Associate)". An Associate General Counsel is paid like a Senior Counsel and
#: an Associate Partner is the consulting rank: in filed pay, these are the
#: "Associate <X>" phrases that sit well above the first rung and that no rung
#: word already reads. Partner only closing the phrase: "Associate Partner
#: Operations Manager" works on a partner team, and an "Associate HR Business
#: Partner" or "Associate Corporate Counsel" is the first rung of its role, so
#: both stay entry.
_ASSOCIATE_NOT_ENTRY_RE = re.compile(
    r"\bthird[- ]?party associates?\b"
    r"|\bassociates?(?= general counsel\b)"
    r"|\bassociates?(?= partners?\b(?!\s*[a-z0-9]))"
)


def junior_marked(text: str) -> bool:
    """The text names the first rung by "Junior" or "Associate"."""
    return bool(_JUNIOR_RE.search(_ASSOCIATE_NOT_ENTRY_RE.sub(" ", text)))


# Rung words, tried high to low: the first list a title matches names its band.
DIRECTOR_PLUS = (
    "vp ",
    # The regional, group and area vice presidents boards abbreviate (RVP, GVP,
    # AVP). Not CVP: a Client Value Partner prints the same three letters.
    "rvp", "gvp", "avp",
    "vice president",
    "svp",
    "evp",
    "head of",
    "distinguished",
    "fellow",
    "director",
)

# "Chief" is a C-suite word and a senior-IC word, and the difference is the rest
# of the phrase, so it is matched as a phrase, never as a prefix. A `"chief "`
# prefix in the list above would band "Data Center Chief Engineer" (a
# facilities role paid well below a director) and "Technical Advisor & Chief of
# Staff to the VP of Applied Science" `director_plus` CONFIRMED. A chief of
# staff TO a VP is not a VP.
#
# The officer form is the discriminator: a C-suite title is "Chief <something>
# Officer". The named exceptions are the officer-equivalent titles that omit the
# word. "Chief Engineer", "Chief of Staff" and "Chief Architect" match none of
# this and fall through to the rest of the title, which is the honest reading.
_CHIEF_OFFICER_RE = re.compile(r"\bchief\b[^,]*\bofficer\b")
_CHIEF_TITLES = ("chief scientist", "chief economist", "chief of engineering")
PRINCIPAL = (
    "principal",
    "senior staff",
    "sr staff",
    "sr. staff",
    "architect",
    "group product manager",
    "gpm",
    "senior director",
)
STAFF = ("staff", "senior manager", "sr manager", "sr. manager", "lead ")
# Titles containing the substring "staff" that are not the staff RUNG. Without
# this, "Chief of Staff" would land on `STAFF`, a wrong confident band. A chief of staff is an
# org role whose rung the title does not state, so it must fall through to the
# reader's default rather than borrow a Staff Engineer's ladder.
NOT_STAFF = ("chief of staff",)
# People-manager / program-lead titles that sit at L6+ at these companies.
MGMT_L6 = (
    "engineering manager",
    "eng manager",
    "manager, engineering",
    # Comma-free twin: the head this list is matched against has already been
    # segmented, so `Manager, Engineering Program Management` arrives as
    # "manager engineering program management" and the comma form cannot fire.
    "manager engineering",
    "manager of engineering",
    "technical lead manager",
    "senior engineering manager",
)

# Ambiguous management/PM titles: they name a role, not its rung (could be < L6).
AMBIGUOUS_MGMT = (
    "product manager",
    "program manager",
    "technical program manager",
    "product management",
)
# Ambiguous senior IC titles.
# The MTS family as boards abbreviate it (Salesforce SMTS/LMTS/PMTS, Micron
# SMTS/DMTS).
AMBIGUOUS_IC = ("member of technical staff", "mts", "amts", "smts", "lmts", "pmts", "dmts")

# Clear senior (non-ambiguous) IC signal.
SENIOR = ("senior", "sr.", "sr ")

# The words above that are role words, not rung words. They band a
# title with no other signal, but they never outrank "associate": "Retail Lead
# Associate" is not a staff rung and "Associate Solution
# Architect" is not a principal one.
ROLE_NOT_RUNG = frozenset({"architect", "lead ", "senior manager", "sr manager", "sr. manager"})


@functools.lru_cache(maxsize=256)
def word_re(needle: str) -> re.Pattern[str]:
    """The needle as a whole word (a plural counts: "Directors"), never the
    head of a longer one. A needle written with a trailing space ("lead ",
    "vp ") keeps that space: "Lead/Senior" and "Coach (VP+)" do not match it."""
    if needle.endswith("."):
        tail = ""  # the dot ends the word: "Sr.Client" is a Sr. Client engineer
    else:
        tail = r"(?=\s)" if needle.endswith(" ") else r"(?![a-z])"
    return re.compile(r"(?<![a-z])" + re.escape(needle.strip()) + r"s?" + tail)


def has_word(text: str, needles: Iterable[str]) -> bool:
    """A needle is a whole word or phrase of the lowered, padded text. Read as
    a substring, "director" would band Active Directory, "staff" Staffing,
    "fellow" a Fellowship and "sr " an ASR Scientist, each CONFIRMED; and since
    a director word vetoes a printed rung, the false friend would discard the
    employer's own statement."""
    return any(word_re(n).search(text) for n in needles)


def is_chief_officer(text: str) -> bool:
    """True for a C-suite "Chief ... Officer" (or a named equivalent), not for
    "Chief Engineer" / "Chief of Staff". The comma stop in the pattern keeps the
    org path out of it: "Chief of Staff, Officer Experience" is not an officer."""
    return bool(_CHIEF_OFFICER_RE.search(text)) or has_word(text, _CHIEF_TITLES)


def names_director(text: str) -> bool:
    """The text names a director-or-above rung: the director words (VP, Head
    of, Director, Distinguished, Fellow) or a Chief officer."""
    return has_word(text, DIRECTOR_PLUS) or is_chief_officer(text)


def rung_word_band(text: str) -> LevelBand | None:
    """Band named by an explicit rung word (director, principal, staff, senior),
    or None. Role words ("lead", "architect", "engineering manager", "product
    manager") and MTS are not rung words, so they never outrank "associate"."""
    if names_director(text):
        return LevelBand.DIRECTOR_PLUS
    if has_word(text, [w for w in PRINCIPAL if w not in ROLE_NOT_RUNG]):
        return LevelBand.PRINCIPAL
    if has_word(text, AMBIGUOUS_IC):
        return None
    if has_word(text, [w for w in STAFF if w not in ROLE_NOT_RUNG]) and not has_word(text, NOT_STAFF):
        return LevelBand.STAFF
    if has_word(text, SENIOR):
        return LevelBand.SENIOR
    return None
