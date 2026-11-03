"""Map a posting to a coarse `LevelBand` + confidence.

Three tiers, in order of authority:

0. **The rung the employer PRINTED on this posting** (`jobs.raw_level`, read by
   `taxonomy.stated_level` and banded by `levels.ladder`). Microsoft states
   "Product Management IC5" in its compensation sentence; there is nothing to
   infer, so nothing below may overturn it. Few employers print a rung, so
   this tier is silent for most postings.
1. **The company's own ladder vocabulary** (`levels.titles` ->
   `levels.companies`). Amazon says "Sr." means L6 and "II" means
   L5; that is the employer's own statement about its ladder and it outranks
   any generic reading. Keyed by (company, family): the posting's family is
   classified first, and a family with a ladder of its own reads its own
   words first (Google's "Senior" is L5 for an engineer, L6 for a product
   manager), then the company row's.
1b. **The posted base range** (`levels.pay_grades`), only when the title
   names no rung: Google's ranges are per grade, so the range a "Product
   Manager" posting states names its grade. A rung word in the title always
   wins (a rung titled Senior is senior).
2. **Generic title vocabulary** (`levels.vocabulary`), tiered so clear
   people-manager and staff+ titles are confirmed while ambiguous IC/PM titles
   ("Product Manager", "Member of Technical Staff") stay SENIOR/unconfirmed:
   included, and flagged.

The profile may only refine the **ambiguous middle** — a generic verdict of
SENIOR, or no verdict at all. It can never overturn an explicit director/
principal/staff signal, because "Sr. Director" is a director whatever the ladder
calls the "Sr." rung. Companies whose ladder is absent from their titles
(apple's ICT, meta's E-ladder) declare `calibrated=False` and are left alone.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import NamedTuple

from tracker.analytics.posting_reality import earliest_posted
from tracker.levels.ladder import (
    band_for,
    band_for_stated_rung,
    prints_rungs_in_text,
    reading_ladder,
    senior_unconfirmed,
)
from tracker.levels.pay_grades import grade_for_pay, has_measured_ranges
from tracker.levels.titles import (
    TitleMatch,
    match_rung_phrase,
    match_title,
    not_rung_pattern,
    rank_for_title,
)
from tracker.levels.vocabulary import (
    AMBIGUOUS_IC,
    AMBIGUOUS_MGMT,
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
from tracker.schema import UNPLACED_BASES, LevelBand, LevelBasis, LevelConfidence, RawJob
from tracker.taxonomy.stated_level import lowest_stated_rung
from tracker.taxonomy.title_parse import head_with_seniority, segments, title_head


def _early_stage_text(title: str) -> str:
    """The whole title, lowered, with the joins some boards leave in a word
    split: "INTERN_NVE Design" and "Strategy ManagerGraduate" carry the marker
    glued to its neighbour, where a word boundary cannot see it."""
    spaced = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", title).replace("_", " ")
    return f" {spaced.lower().strip()} "


#: Only a numeral standing alone after the role: a duration, a count, a
#: version or a time is no rung. "(6-Month Contract)", "7+ years",
#: "24/7", "5-star", "SAP BI 4.0", "S/4 HANA", "5-11 pm" name no rung.
#: "3/4" stays a dual rung; its lower one is the one read.
_TRAILING_NUM_RE = re.compile(
    r"(?<![.+])(?<!\d\d/)(?<![a-z]/)\b([4-9])\b"
    r"(?![.,]\d|\+|%|\s*[-–]?\s*(?:\d|months?\b|mois\b|monate?\b|weeks?\b|days?\b|jours?\b|years?\b|yrs?\b"
    r"|ans\b|jahre?\b|hours?\b|hrs?\b|std\b|star\b|ploeg|pm\b|am\b))"
)


# Text inside the title head that names something OTHER than this role's rung.
# Masked out before ANY level vocabulary runs, because both tiers walk into it
# otherwise: "Chief of Staff" contains the generic `STAFF` keyword AND matches
# google's own profile rule `\bstaff\b -> L6`, so guarding one tier would just
# move the wrong answer to the other.
#
# The reporting clause is the same rule applied to a different word: a role
# reporting "to the VP of Applied Science" is not a VP, exactly as an org path is
# not evidence about a level (`head_with_seniority` exists for that case, but it
# splits on separators and this clause carries none).
_RUNG_FALSE_FRIEND_RE = re.compile(r"\bchief of staff\b|\bto the\b.*$", re.IGNORECASE)


def _not_rung_masked(text: str, company: str | None) -> str:
    """`text` with the company's own not-a-rung phrases removed (iCapital's
    "Vice President")."""
    pattern = not_rung_pattern(company) if company else None
    return pattern.sub(" ", text) if pattern is not None else text


def _level_text(head: str, company: str | None = None) -> str:
    """The head with false-friend phrases removed, padded for substring matching."""
    return f" {_RUNG_FALSE_FRIEND_RE.sub(' ', _not_rung_masked(head, company)).strip().lower()} "


# A director rung in a segment the head skipped. The head is the
# segment naming the role, joined only by segments that are nothing but
# seniority words, so a rung sharing its segment with a product or org is not
# in it: Cadence "Application Engineer, RTL2GDS Sr Director", OKX "Deputy
# General Counsel, Head of Americas Legal", Asana "VP/GM, Product Management".
# Only the rung phrase joins, never the segment's other words: an org path is
# still no evidence about a level. A segment OPENING with the rung, or ENDING
# with Director, states it. Not a VP rank closing the title: that is how a bank
# appends its corporate rank (iCapital, BTIG: "..., Vice President"), a
# mid-level title; a tech VP leads with it.
_SEGMENT_RUNG_START_RE = re.compile(
    r"^(?:(?:sr\.?|senior|executive|managing|group|global|regional)\s+)?"
    r"(?:head of|vice president|vp|svp|evp|director)\b(?!['’]s\b)",  # not "Director's Office"
    re.IGNORECASE,
)
_SEGMENT_DIRECTOR_END_RE = re.compile(
    r"\b(?:(?:sr\.?|senior|executive|managing|associate|group|global)\s+)?director\s*$", re.IGNORECASE
)
_BRACKETED_RE = re.compile(r"\([^)]*(?:\)|$)")
# "Office of the Director", "Assistant to the Director": the director is
# someone else.
_OF_THE_RE = re.compile(r"(?:\bof(?: the)?|\bto(?: the)?|'s)\s*$", re.IGNORECASE)
_VP_RANK_RE = re.compile(
    r"^(?:(?:senior|sr\.?|executive|assistant|associate)\s+)?(?:vice president|vp|svp|evp|avp)\b", re.IGNORECASE
)


def _segment_rungs(title: str, company: str | None) -> list[str]:
    """The director rungs the title's other segments open or close with.

    Not where the company states a bank rank its profile says is no rung
    (iCapital "Global Head of Payroll - Vice President"): the rank
    the company states decides, and a "Head of" beside it does not overrule
    it. Not inside parentheses: Render's "Executive Business Partner (CEO, VP
    of Finance, VP of People)" names the people the role supports."""
    pattern = not_rung_pattern(company) if company else None
    if pattern is not None and pattern.search(title):
        return []
    unbracketed = _BRACKETED_RE.sub(" ", title)
    parts = segments(unbracketed)
    head = title_head(unbracketed)
    found = []
    for index, part in enumerate(parts):
        if part == head:
            continue
        text = _RUNG_FALSE_FRIEND_RE.sub(" ", _not_rung_masked(part, company)).strip()
        opening = _SEGMENT_RUNG_START_RE.match(text)
        if opening is not None and not (index == len(parts) - 1 and _VP_RANK_RE.match(text)):
            found.append(opening.group(0))
            continue
        closing = _SEGMENT_DIRECTOR_END_RE.search(text)
        if closing is not None and not _OF_THE_RE.search(text[: closing.start()]):
            found.append(closing.group(0))
    return found


def _title_level_text(title: str, company: str | None) -> str:
    """What every level rule reads: the head with its seniority words, and any
    director rung another segment states (`_segment_rungs`) when the head names
    no rung of its own. A rung in the head stands: Shield AI's "Senior Staff
    Engineer, Test Director" is a Senior Staff Engineer whose role is directing
    tests, and Databricks' "Principal AI Research Scientist, Research Director"
    a Principal."""
    head = head_with_seniority(title)
    text = _level_text(head, company)
    if rung_word_band(text) is not None or names_director(text):
        return text
    return _level_text(" ".join([*_segment_rungs(title, company), head]), company)


class LevelReading(NamedTuple):
    band: LevelBand
    confidence: LevelConfidence
    basis: LevelBasis


def map_level(job: RawJob, family: str | None = None) -> tuple[LevelBand, LevelConfidence]:
    """Band and confidence; `read_level` also says what decided them."""
    reading = read_level(job, family)
    return reading.band, reading.confidence


def _company(job: RawJob, band: LevelBand) -> LevelReading:
    return LevelReading(*_weak_senior(job, band, LevelConfidence.CONFIRMED), LevelBasis.COMPANY)


def read_level(job: RawJob, family: str | None = None) -> LevelReading:
    """`family` is the posting's taxonomy family (`classify.classify_family`):
    it picks the ladder whose words read the title. None reads the company
    row only, which is the reading for a company without family ladders."""
    # Seniority vocabulary reads only the head + its leading seniority words. An
    # org path is not evidence about a level: `Sr. Program Manager, Principal
    # Investigator Team` is a Sr. Program Manager, not a Principal. The head is
    # never empty: `_level_text` pads it.
    head = _title_level_text(job.title, job.company)

    # The employer's printed rung outranks every reading of the title, including
    # the early-stage markers below: a posting Microsoft labels IC5 is IC5 even
    # if its title mentions a graduate programme. `lowest_stated_rung` is what
    # bands a dual-level req; see its docstring for why the lower one.
    #
    # One exception: a rung below director never
    # pulls a director title down. Microsoft prints M5/M6/IC5/IC6 on "Director,
    # Silicon Design" and "Group Creative Director"; the title's Director, VP or
    # Chief officer stands and the printed code is not read.
    stated = band_for_stated_rung(job.company, lowest_stated_rung(job.raw_level))
    if stated is not None and not (
        stated is not LevelBand.DIRECTOR_PLUS and names_director(head)
    ):
        return LevelReading(stated, LevelConfidence.CONFIRMED, LevelBasis.STATED)
    match = match_title(job.company, head, family) if head.strip() else None
    # A company rule whose word IS the rung's name ("Principal", "Staff", "II")
    # outranks every generic reading below a director: Amazon's "Solutions
    # Architect II" is its L5, not the principal the generic word "architect"
    # suggests. A seniority-prefix rule ("Sr." is L6) does not get this reach,
    # and no rule outranks an early-stage marker: "Applied Scientist II Intern"
    # is an intern and "IT Support Associate II" sits on the associate ladder,
    # not on SDE II.
    named = _match_band(job, match) if match is not None and match.rule.names_rung else None

    # Early-stage markers read the WHOLE title on purpose: "University Graduate"
    # and "Intern" are legitimately qualifier segments ("Software Engineer III,
    # University Graduate"), and missing one would band a new-grad role as senior.
    early = _early_stage_text(job.title)
    if INTERN_RE.search(early):
        return LevelReading(LevelBand.INTERN, LevelConfidence.CONFIRMED, LevelBasis.GENERIC)
    if ENTRY_RE.search(early):
        return LevelReading(LevelBand.ENTRY, LevelConfidence.CONFIRMED, LevelBasis.GENERIC)

    # A professional-services firm's rank: read
    # anywhere in the title, because the firm writes it as its own segment, and
    # the firm's statement of the rung, like a printed code. It outranks every
    # generic word below, "Associate" and Director included: EY's "Staff" is its
    # entry rung, its "Senior" the second rung, and its Director sits at
    # principal by years and posted pay. An intern stays an intern (above).
    # Over the same masked text as every other tier: "Chief of Staff" is an
    # org role, not EY's Staff rank.
    rank = rank_for_title(job.company, _RUNG_FALSE_FRIEND_RE.sub(" ", _not_rung_masked(job.title, job.company)))
    ranked = band_for(job.company, rank.rung) if rank is not None else None
    if ranked is not None:
        return _company(job, ranked)

    # A phrase the company uses for one of its rungs (atlas `rung_titles.csv`):
    # a reviewed row of the company's own words ("senior manager"
    # is Apple's M2), so it names the rung outright, ahead of "Associate",
    # the regex rules and a range. It may confirm a director title, never pull
    # one down. An intern stays an intern (above).
    phrase = match_rung_phrase(job.company, head, family) if head.strip() else None
    phrased = band_for(job.company, phrase.row.code, phrase.ladder) if phrase is not None else None
    if phrased is not None and (phrased is LevelBand.DIRECTOR_PLUS or not names_director(head)):
        return LevelReading(phrased, LevelConfidence.CONFIRMED, LevelBasis.COMPANY)

    # "Associate" is an entry marker only when nothing stronger names the rung:
    # "Associate Director" is a director, "Associate Principal" a principal and
    # "Senior Associate" senior. The stronger word must be a rung word in the
    # head, never a role word ("Associate Product Manager" stays entry).
    if junior_marked(early):
        stronger = rung_word_band(head)
        if stronger is None:
            return LevelReading(LevelBand.ENTRY, LevelConfidence.CONFIRMED, LevelBasis.GENERIC)
        return LevelReading(*_weak_senior(job, stronger, LevelConfidence.CONFIRMED), LevelBasis.GENERIC)

    band, confidence = _classify_title(head)

    # The employer's own ladder wins the ambiguous middle (a generic SENIOR, or
    # no verdict), and a rule naming the rung wins everything below a director.
    # Never a director verdict: "Sr. Director" is a director whatever the ladder
    # calls the "Sr." rung.
    if band is not LevelBand.DIRECTOR_PLUS and named is not None:
        return _company(job, named)
    # A title naming no rung ("Product Manager", "Engineering Manager", a
    # "Manager, X" prefix rule) is read by its posted range where the company
    # pays that range at a measured rung. A rung word never is: "Senior
    # Product Manager" is senior whatever it pays.
    if rung_word_band(head) is None:
        graded = _pay_grade_band(job, family)
        if graded is not None:
            return LevelReading(*_weak_senior(job, graded, LevelConfidence.CONFIRMED), LevelBasis.PAY_GRADE)
    if band is None or band is LevelBand.SENIOR:
        ladder_band = _match_band(job, match)
        if ladder_band is not None:
            return _company(job, ladder_band)

    if band is None:
        # No seniority marker at all. Mid is kept for sorting and pay lookups
        # only: basis NONE tells the scope gate the posting states no level,
        # so it never passes a level axis by this default.
        return LevelReading(LevelBand.MID, LevelConfidence.UNCONFIRMED, LevelBasis.NONE)

    # A generic band that no rung word in the title names is our guess from a
    # role word ("Engineering Manager", "Lead", "Senior Manager" read staff):
    # the title states a level in the company's own terms that we cannot place.
    # The band stays for sorting; the gate never reads it.
    if band not in (LevelBand.INTERN, LevelBand.ENTRY) and rung_word_band(head) is not band:
        return LevelReading(*_weak_senior(job, band, confidence), LevelBasis.UNMAPPED)
    return LevelReading(*_weak_senior(job, band, confidence), LevelBasis.GENERIC)


def _match_band(job: RawJob, match: TitleMatch | None) -> LevelBand | None:
    """Band of the rung a matched rule names, on the rule's own ladder (a
    family rule) or the company row, or None when no rule matched.

    The rule is matched against the SAME head the generic tier read: head plus
    leading seniority words, false friends masked. A separately derived head
    would let a company rule see "Chief of Staff" after the generic tier had
    declined to.
    """
    if match is None:
        return None
    return band_for(job.company, match.rule.rung, match.ladder)


def _now() -> datetime:
    return datetime.now(UTC)


def level_date(job: RawJob) -> datetime:
    """The date a posting's pay grade is read for (ranges are revised yearly):
    the earliest date the employer gave, else our first sight of the row, else
    now for a posting first seen in this read.

    One rule for the scan, relevel and the bench. The scan reads
    the held row's dates off the `RawJob` (collection puts them there) and
    relevel the stored columns, so both reach what `first_posted_at` will hold
    after the write: `earliest_posted` over the same dates. Otherwise a posting
    with no date would read `now` at scan time and its first sight in relevel,
    and from the first day of a year whose ranges are not measured the two
    would disagree on every row.
    """
    now = _now()
    facts = job.source_facts
    first = earliest_posted(
        job.held_first_posted_at,
        job.posted_at,
        facts.first_published_at if facts is not None else None,
        read_at=now,
    )
    return first or job.held_first_seen or now


def _pay_grade_band(job: RawJob, family: str | None) -> LevelBand | None:
    """Band of the rung this posting's base range is paid at, or None.

    Only a stated annual US base range is read: the measured ranges are US
    base. The year is the posting's own (`level_date`)."""
    pay = job.source_disclosed_comp
    if (
        pay is None or not pay.base_min or not pay.base_max
        or (pay.currency or "").upper() != "USD"
        or pay.pay_period != "year" or pay.pay_basis != "base"
    ):
        return None
    year = level_date(job).year
    grade = grade_for_pay(job.company, family, pay.base_min, pay.base_max, year)
    if grade is None:
        return None
    if grade.rung is None:  # a band-level row: the company has no ladder
        return grade.band
    return band_for(job.company, grade.rung, reading_ladder(job.company, family))


def is_level_guess(title: str, reading: LevelReading, company: str | None = None) -> bool:
    """True when the band is our guess, not the posting's statement: nothing
    stated, or a generic band no rung word in the title names ("Product
    Manager" and MTS read senior, "Engineering Manager", "Lead", "Architect"
    and "Senior Manager" read staff or principal). A rung word naming the band
    is a statement even where the reading is unconfirmed ("Senior Product
    Manager" is senior), and an early-stage marker states the stage."""
    if reading.basis in UNPLACED_BASES:
        return True
    # A stored GENERIC row is judged by its title.
    if reading.basis is not LevelBasis.GENERIC or reading.band in (LevelBand.INTERN, LevelBand.ENTRY):
        return False
    head = _title_level_text(title, company)
    return rung_word_band(head) is not reading.band


_DUAL_SPLIT = re.compile(r"\s*(?:/|\band\b|\bor\b|&|\+)\s*")
_DUAL_CODES = re.compile(
    r"\b(?:I{1,3}|IV|V|VI|VII|(?:IC|L|E)\d+)\s*(?:/|\band\b|\bor\b|&)\s*"
    r"(?:I{1,3}|IV|V|VI|VII|(?:IC|L|E)\d+|senior|sr\.?|staff|principal)\b", re.I,
)


def title_states_band(title: str, reading: LevelReading, printed: str | None = None,
                      company: str | None = None) -> bool:
    """A confirmed, independently stated band suitable for posted-pay evidence.

    Shared with the exact-range mapping bench. Role words, a
    pay-derived reading, dual-level titles and a title overriding a printed
    rung cannot anchor a pay figure. A mapped printed rung can.
    """
    if reading.confidence is not LevelConfidence.CONFIRMED:
        return False
    if reading.basis is LevelBasis.STATED:
        return True
    if printed:
        return False
    head = _level_text(head_with_seniority(title), company)
    if _DUAL_CODES.search(head):
        return False
    parts = _DUAL_SPLIT.split(head)
    named = {rung_word_band(f" {part} ") for part in parts} - {None}
    if (reading.basis is LevelBasis.GENERIC and reading.band is LevelBand.ENTRY
            and len(parts) > 1 and any(ENTRY_RE.search(part) or junior_marked(part) for part in parts)):
        named.add(LevelBand.ENTRY)
    if len(named) > 1:
        return False
    if reading.basis is LevelBasis.COMPANY:
        return True
    if reading.basis is LevelBasis.GENERIC and reading.band is LevelBand.ENTRY:
        early = _early_stage_text(title)
        return bool(ENTRY_RE.search(early) or junior_marked(early))
    return reading.basis is LevelBasis.GENERIC and rung_word_band(head) is reading.band


def full_read_can_state(job: RawJob, family: str | None) -> bool:
    """True when reading the posting in full could state its level: the
    company prints rungs we band and none is held yet, or the title leaves the
    decision to a stated range (no rung word, no early-stage marker, no
    company rule naming the rung, the same precedence as `read_level`) and
    the company's ranges for this family and year are measured. Anywhere
    else a read changes nothing a level is read from.

    A printed rung is read the way `read_level` reads it: below director it
    never pulls a director title down, so a director title at a
    company that prints rungs is no reason to read.

    This restates `read_level`'s order by hand; a change to either is checked
    against the other by `tests/test_bench_read_agreement.py` and
    `scripts.bench_level_bands read-agreement`."""
    head = _title_level_text(job.title, job.company)
    if job.raw_level is None and prints_rungs_in_text(job.company) and not names_director(head):
        return True
    early = _early_stage_text(job.title)
    if rung_word_band(head) is not None or INTERN_RE.search(early) or ENTRY_RE.search(early) or junior_marked(early):
        return False
    # A firm rank decides before any range: a read changes nothing.
    if rank_for_title(job.company, job.title) is not None:
        return False
    # A company phrase names the rung before any range.
    if head.strip() and match_rung_phrase(job.company, head, family) is not None:
        return False
    match = match_title(job.company, head, family) if head.strip() else None
    if match is not None and match.rule.names_rung:
        return False
    year = level_date(job).year
    return has_measured_ranges(job.company, family, year)


def level_awaits_read(job: RawJob, reading: LevelReading, family: str | None) -> bool:
    """The level is our guess and a full read could replace it with what the
    posting states: collection reads such a posting before
    the scope decides on the guess."""
    return is_level_guess(job.title, reading, job.company) and full_read_can_state(job, family)


def _weak_senior(
    job: RawJob, band: LevelBand, confidence: LevelConfidence
) -> tuple[LevelBand, LevelConfidence]:
    """A bare SENIOR where the company's titles do not speak its ladder is a
    weak signal (Apple's ≈ICT4): the atlas says which companies
    (`companies.senior_unconfirmed`)."""
    if band is LevelBand.SENIOR and senior_unconfirmed(job.company):
        return band, LevelConfidence.UNCONFIRMED
    return band, confidence


def _classify_title(title: str) -> tuple[LevelBand | None, LevelConfidence]:
    if names_director(title):
        return LevelBand.DIRECTOR_PLUS, LevelConfidence.CONFIRMED
    if has_word(title, PRINCIPAL):
        return LevelBand.PRINCIPAL, LevelConfidence.CONFIRMED
    # Check ambiguous IC (MTS) before STAFF: "member of technical staff" contains
    # the "staff" substring but is not a staff-level signal.
    if has_word(title, AMBIGUOUS_IC):
        return LevelBand.SENIOR, LevelConfidence.UNCONFIRMED
    if has_word(title, STAFF) and not has_word(title, NOT_STAFF):
        return LevelBand.STAFF, LevelConfidence.CONFIRMED
    if has_word(title, MGMT_L6):
        return LevelBand.STAFF, LevelConfidence.CONFIRMED
    # An explicit Senior rung also qualifies an IC product/program manager.
    # Bare PM role words remain guesses; employer weak-senior guards run later.
    if has_word(title, SENIOR):
        return LevelBand.SENIOR, LevelConfidence.CONFIRMED
    if has_word(title, AMBIGUOUS_MGMT):
        return LevelBand.SENIOR, LevelConfidence.UNCONFIRMED
    # Netflix-style trailing seniority number ("Software Engineer 5").
    m = _TRAILING_NUM_RE.search(title)
    if m:
        return LevelBand.SENIOR, LevelConfidence.CONFIRMED
    return None, LevelConfidence.CONFIRMED
