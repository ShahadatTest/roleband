"""Per-employer title profiles: how one company names its own ladder.

The asset behind "a filter the user can rely on". A company's title vocabulary is
an employer fact, not a connector fact: many companies share one generic ATS
adapter, and employers migrate ATS, so profiles are keyed by the company
**slug**, the identity already used by `tracked_company.slug`,
`jobs.company`, `CompanyBlueprint`, `SourceBinding`, and `levels.COMPANIES`.

Scope of this module: **title -> ladder rung**. The rung itself, and its band,
live once in `levels.companies`; a rule names a rung by any of its
spellings and `ladder.band_for` answers the band.

Design rules:

- A rule may only emit a rung that exists in the company's ladder (its own or
  its parent's). The `title_profile` blueprint check enforces this, so a typo
  fails by name rather than silently mapping to nothing.
- Rules match against the title **head** (plus preceding seniority words), never
  the org path: `Sr. Program Manager, Principal Investigator Team` must not read
  as Principal.
- Rules are ordered, most specific first ("senior principal" before "principal").
- `calibrated=False` is an honest declaration that a company's ladder vocabulary
  has not been measured yet. Such a profile changes nothing: the generic mapper
  keeps its answer. A guess would be worse than an absence, because a wrong band
  silently moves a posting in or out of the user's board.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from tracker.levels.atlas import load_rung_titles, phrase_words
from tracker.levels.ladder import band_for, ladder_for, ladders_of, lineage, reading_ladder
from tracker.levels.model import Ladder, RungTitle
from tracker.schema import LEVEL_BAND_ORDER


@dataclass(frozen=True)
class RungRule:
    """One title-vocabulary rule: this pattern means this rung, at this company."""

    rung: str  # a spelling of a rung in levels.companies (own or parent ladder)
    pattern: str  # regex, matched case-insensitively against the title head
    note: str = ""
    # True when the matched word IS the rung's own name ("Principal", "Staff",
    # "II"): the company's reading of that word outranks the generic one, so
    # the rule may override a generic or early-stage verdict (never a VP,
    # Director or Head of). False for a seniority prefix ("Sr." is L6 at
    # Amazon): "Sr. Manager" and "Senior Engineering Manager" carry a manager
    # rung the prefix rule does not know, so it only fills the ambiguous middle.
    names_rung: bool = False

    def matches(self, head: str) -> bool:
        return re.search(self.pattern, head, re.I) is not None


@dataclass(frozen=True)
class TitleProfile:
    slug: str
    # Ordered, first match wins. A company with a parent (`CompanyLevels.parent`,
    # google-deepmind -> google) reads its own rules first, then the parent's.
    # These name rungs of the company row and apply to every family.
    rung_rules: tuple[RungRule, ...] = field(default_factory=tuple)
    # {ladder family: rules}: a family's own words, read before
    # `rung_rules` for a posting whose family reads that ladder, naming rungs
    # of that ladder. Google's "Senior" is L5 for an engineer and L6 for a
    # product manager; "II" is L3, L4 or L5 by family.
    family_rules: dict[str, tuple[RungRule, ...]] = field(default_factory=dict)
    # Company-internal vocabulary the shared domain keywords cannot know:
    # {domain_slug: (term, ...)}. "SSD Ops Integration" is Amazon's Sub Same Day
    # delivery org, and no general lexicon will ever contain it.
    domain_terms: dict[str, tuple[str, ...]] = field(default_factory=dict)
    # A professional-services firm's rank: read anywhere in
    # the TITLE, not the head, because the firm writes it as its own segment
    # ("Cyber - Enterprise Security Architect - Manager - Consulting"), and it
    # outranks the generic words, Director included. Ordered most specific
    # first; see `rank_for_title`.
    ranks: tuple[RungRule, ...] = field(default_factory=tuple)
    # True = the vocabulary is measured: the coverage gate holds the company to
    # a floor over its stored titles. False with rung or family rules is refused
    # (blueprint check); `ranks` may be declared unmeasured where the firm has no
    # inventory to measure (PwC, collected only on the user's Sync).
    calibrated: bool = False
    note: str = ""
    # Title phrases that are NOT a rung at this company, masked before any
    # level vocabulary reads the title. A negative statement, so it
    # applies whether or not the profile is calibrated: iCapital's "Vice
    # President" is a mid-career banking title, not the executive the generic
    # tier reads.
    not_rung: tuple[str, ...] = ()


# Roman-numeral rungs, longest first so III never matches as II or I.
def _roman(rung_iii: str, rung_ii: str, rung_i: str) -> tuple[RungRule, ...]:
    return (
        RungRule(rung_iii, r"\bIII\b", "roman-numeral rung", names_rung=True),
        RungRule(rung_ii, r"\bII\b", "roman-numeral rung", names_rung=True),
        RungRule(rung_i, r"\bI\b", "roman-numeral rung", names_rung=True),
    )


def _role_numeral(role: str, *rungs: tuple[str, str]) -> tuple[RungRule, ...]:
    """A numeral that follows the family's own role noun ("Program Manager
    II"), never one after another word: Google's "Leadership Technical Program
    Manager II" posts Senior's range, and "Software Engineer Manager II" is a
    manager, not Software Engineer II. `rungs` pairs (numeral, rung), longest
    numeral first."""
    return tuple(
        RungRule(rung, rf"^(?!.*\bleadership\b).*\b{role}\s+{numeral}\b",
                 "roman-numeral rung", names_rung=True)
        for numeral, rung in rungs
    )


#: A rung word that, beside a numeral, decides the title itself: Elastic's
#: "Principal Software Engineer I" is a Principal, Rocket Lab's "Senior
#: Engineer II" a Senior, never the numeral's lower rung.
_RUNG_WORD = (r"\b(?:senior|sr|staff|principal|distinguished|fellow|lead|chief|junior|associate"
              r"|intern|manager|director|head)\b")


def _engineer_numeral(*rungs: tuple[str, str]) -> tuple[RungRule, ...]:
    """A numbered engineering rung: the numeral right after
    "Engineer", in a head no other rung word joins. `rungs` pairs (numeral,
    rung), longest numeral first; "I" never matches inside "II"."""
    return tuple(
        RungRule(rung, rf"^(?!.*{_RUNG_WORD}).*\bengineer\s+{numeral}\b", "numbered engineering rung",
                 names_rung=True)
        for numeral, rung in rungs
    )


# Google's product and program ladders read "Senior" anywhere in the head
# ("Cloud AI Senior Technical Program Manager I" is Senior, not I).
# "Senior Staff" and "Staff" fall through to the company row (L7, L6).
_GOOGLE_SENIOR_L6 = RungRule(
    "L6", r"\b(sr\.?|senior)\b(?!\s+staff\b)", "Senior is L6 in this family",
)


# Firm ranks. A role word that only looks like a rank is excluded
# where the corpus has one: an agency's Art or Creative Director, a "Partner
# Programs" team, a "Partner Manager".
_SR = r"(?:senior|sr\.?)"
_ASSOC = r"assoc(?:iate|\.)?"
_PARTNER = (r"(?<!business )(?<!channel )(?<!alliance )(?<!technology )\bpartner\b"
            r"(?!\s+(?:programs?|manager|engineer|specialist|success|marketing|development|alliances?|solutions?)\b)")
_DIRECTOR = r"(?<!art )(?<!creative )(?<!managing )(?<!principal )\bdirector\b"
# "Associate Vice President" is a senior title of its own, never the
# Associate rank (EY India).
_ASSOCIATE = r"\bassociate\b(?!\s+vice[\s-]+president)"


def _rank(rung: str, pattern: str) -> RungRule:
    return RungRule(rung, pattern, "firm rank", names_rung=True)


def _big4_top(partner: str, *, associate_director: str | None) -> tuple[RungRule, ...]:
    """Partner, Managing Director, (Associate) Director: the Big 4 top ranks."""
    return (
        _rank(partner, r"\bmanaging director\b"),
        _rank(partner, _PARTNER),
        *((_rank(associate_director, rf"\b{_ASSOC}\s+director\b"),) if associate_director else ()),
        _rank("Director", _DIRECTOR),
        _rank("Senior Manager", rf"\b{_SR}\s+manager\b"),
    )


PROFILES: dict[str, TitleProfile] = {
    # Amazon runs one company-wide L-ladder and names rungs in the title itself:
    # "Sr." is L6 and "Principal" is L7 across functions, not just SDE.
    "amazon": TitleProfile(
        "amazon",
        calibrated=True,
        note="Company-wide L4-L12; SDE labels are the ladder's own vocabulary.",
        # Distinguished (L10), Senior Principal (L8) and Principal (L7) are
        # atlas phrase rows (`rung_titles.csv`). These remain:
        # a leading "Sr." reads only where the generic verdict is SENIOR or
        # none, and a numeral only after a role word, neither a phrase row.
        rung_rules=(
            RungRule("L6", r"^\s*(sr\.?|senior)\b", "Amazon 'Sr.' is L6"),
            *_roman("L6", "L5", "L4"),
        ),
        domain_terms={
            # Delivery-network org names that read as nothing to a general lexicon.
            "logistics_fulfillment": (
                "amazon flex", "sub same day", "ssd ", "amxl", "middle mile",
                "delivery service partner", "dsp ", "amazon logistics", "ats ",
            ),
            "public_sector": ("kuiper", "amazon leo"),
            "media_entertainment": ("prime video", "twitch", "audible"),
            "retail_commerce": ("selling partner", "fba", "amazon fresh", "instock"),
        },
    ),
    # Google's ladder is numeric and the title carries the word, not the number.
    # Google also uses I/II/III in some Cloud titles at rungs we have not
    # measured: deliberately unmapped rather than guessed.
    # Family rules measured from Google's posted base ranges (the anchoring
    # titles are in `pay_grades.py`). Sales, data-centre
    # technician and customer-engineer numerals have no posted range in the
    # corpus and stay unmapped.
    "google": TitleProfile(
        "google",
        calibrated=True,
        note="Company row L3-L10; family words for IC, EM, PM, TPM, PgM.",
        rung_rules=(
            RungRule("L8", r"\b(vp|vice president|senior director)\b", names_rung=True),
            RungRule("L7", r"\b(sr\.?|senior)\s+staff\b", names_rung=True),
            RungRule("L6", r"\bstaff\b", names_rung=True),
            RungRule("L5", r"^\s*(sr\.?|senior)\b"),
        ),
        family_rules={
            "software_engineering": (
                RungRule("L8", r"\bprincipal\b", "titled Principal Engineer", names_rung=True),
                RungRule("L7", r"\b(sr\.?|senior)\s+staff\b", names_rung=True),
                RungRule("L6", r"\bstaff\b", names_rung=True),
                RungRule("L5", r"^\s*(sr\.?|senior)\b"),
                *_role_numeral("engineer", ("III", "L4"), ("II", "L3")),
            ),
            "engineering_management": (
                RungRule("L7", r"\b(sr\.?|senior)\b.*\bmanager\b",
                         "Senior Software Engineering Manager posts Senior Staff's range",
                         names_rung=True),
                *_role_numeral("manager", ("II", "L6")),
            ),
            "product_management": (
                RungRule("L8", r"\bprincipal\b", names_rung=True),
                RungRule("L7", r"\bgroup\b", names_rung=True),
                _GOOGLE_SENIOR_L6,
                *_role_numeral("product manager", ("II", "L5"), ("I", "L4")),
            ),
            "technical_program_management": (
                RungRule("L7", r"\b(sr\.?|senior)\b.*\bII\b", names_rung=True),
                _GOOGLE_SENIOR_L6,
                *_role_numeral(
                    "technical program manager", ("III", "L5"), ("II", "L4"), ("I", "L3"),
                ),
            ),
            "program_management": (
                _GOOGLE_SENIOR_L6,
                *_role_numeral("program manager", ("III", "L5"), ("II", "L4"), ("I", "L3")),
            ),
        },
    ),
    "google-deepmind": TitleProfile("google-deepmind", calibrated=True),
    # Apple's ICT ladder is not spoken in titles: "Senior" is a weak ICT4 signal
    # and the existing mapper deliberately flags it unconfirmed. Nothing to add
    # until the vocabulary is measured.
    "apple": TitleProfile("apple", note="ICT ladder absent from titles; bare 'Senior' is weak."),
    # Microsoft titles do carry "Principal"/"Partner", and the generic mapper
    # already reads them; its printed IC/M codes band a posting first.
    "microsoft": TitleProfile("microsoft", note="Generic words read its titles; printed codes outrank them."),
    "netflix": TitleProfile("netflix", note="Some titles carry (L5)/(L6); not yet mapped."),
    "nvidia": TitleProfile("nvidia", note="IC ladder absent from titles."),
    "openai": TitleProfile("openai", note="L-ladder absent from titles."),
    "anthropic": TitleProfile("anthropic", note="Named ladder overlaps generic vocabulary."),
    "spotify": TitleProfile("spotify", note="Named ladder; too few postings to measure."),
    # Numbered engineering rungs, each the employer's
    # own: MongoDB's "Software Engineer 2" is its new-grad rung ("up to 18
    # months"), 3 the next; Elastic and Rocket Lab number I and II below
    # Senior (Zipline does too, but posts no numbered title yet: no rule).
    # Every other word reads generically.
    "mongodb": TitleProfile(
        "mongodb", calibrated=True, note="Numbered engineering rungs 2 and 3 below Senior.",
        rung_rules=_engineer_numeral(("3", "Software Engineer 3"), ("2", "Software Engineer 2")),
    ),
    "elastic": TitleProfile(
        "elastic", calibrated=True, note="Software Engineer I and II below Senior; Principal I/II read Principal.",
        rung_rules=_engineer_numeral(("II", "Software Engineer II"), ("I", "Software Engineer I")),
    ),
    "rocket-lab": TitleProfile(
        "rocket-lab", calibrated=True, note="US Engineer I and II below Senior I and II.",
        rung_rules=_engineer_numeral(("II", "Engineer II"), ("I", "Engineer I")),
    ),
    # CrowdStrike prints Engineer II and III below Sr.: both mid, each posting
    # a range below Sr.'s.
    "crowdstrike": TitleProfile(
        "crowdstrike", calibrated=True, note="Engineer I, II, III below Sr.; II and III both mid.",
        rung_rules=_engineer_numeral(("III", "Engineer III"), ("II", "Engineer II"), ("I", "Engineer I")),
    ),
    # Snap prints its level in the title's last segment ("Software Engineer,
    # ML Infrastructure, Level 4"), so it is read over the whole title, as a
    # firm's rank is, and outranks the title's words like a printed code:
    # Level 3 < 4 < 5 (6+ years) < 6 Staff < 7 Principal.
    "snap": TitleProfile(
        "snap", calibrated=True, note="Prints 'Level N' (3-7) in the title.",
        ranks=tuple(
            RungRule(f"L{n}", rf"\blevel[\s-]*{n}\b", "printed level", names_rung=True) for n in (7, 6, 5, 4, 3)
        ),
    ),
    # Applied Materials prints its company-wide E-grade in the title ("Process and Technology
    # Engineer - (E3)"), read over the whole title like a printed code. Its "(M1)"-"(M6)"
    # manager codes are not read: no employer source lines them up with the E grades.
    "applied-materials": TitleProfile(
        "applied-materials", calibrated=True, note="Prints its E-grade, (E1)-(E5), in the title.",
        ranks=tuple(
            RungRule(f"E{n}", rf"\(\s*E{n}\s*\)", "printed grade", names_rung=True) for n in (5, 4, 3, 2, 1)
        ),
    ),
    # Salesforce prints its MTS rung in the title, as a code or spelled out ("Senior (SMTS)
    # Endpoint Security Software Engineer", "Lead Member of Technical Staff"): AMTS < MTS < SMTS
    # < LMTS < PMTS. A code inside a longer one is part of it.
    "salesforce": TitleProfile(
        "salesforce", calibrated=True, note="Prints its MTS rung (AMTS..PMTS) in the title.",
        ranks=(
            RungRule("PMTS", r"\bPMTS\b|\bprincipal member of technical staff\b", "printed rung", names_rung=True),
            RungRule("LMTS", r"\bLMTS\b|\blead member of technical staff\b", "printed rung", names_rung=True),
            RungRule("SMTS", r"\bSMTS\b|\bsenior member of technical staff\b", "printed rung", names_rung=True),
            RungRule("AMTS", r"\bAMTS\b|\bassociate member of technical staff\b", "printed rung", names_rung=True),
            RungRule("MTS", r"\bMTS\b|\bmember of technical staff\b", "printed rung", names_rung=True),
        ),
    ),
    # AMD prints its technical-staff rung and its Fellow tiers in the title ("PMTS - DFT
    # Architect", "Sr. Fellow - Software Architect", "GPU Kernel Development Engineer -
    # Fellow"): MTS < SMTS < PMTS < Fellow < Senior Fellow < Corporate Fellow. A code inside
    # a longer one is part of it, so the longer codes come first.
    "amd": TitleProfile(
        "amd", calibrated=True, note="Prints its MTS rung (MTS..PMTS) and Fellow tier in the title.",
        ranks=(
            RungRule("Corporate Fellow", r"\bcorporate fellow\b", "printed rung", names_rung=True),
            RungRule("Senior Fellow", r"\b(?:senior|sr\.?) fellow\b", "printed rung", names_rung=True),
            RungRule("Fellow", r"\bfellow\b", "printed rung", names_rung=True),
            RungRule("PMTS", r"\bPMTS\b|\bprincipal member of technical staff\b", "printed rung", names_rung=True),
            RungRule("SMTS", r"\bSMTS\b|\bsenior member of technical staff\b", "printed rung", names_rung=True),
            RungRule("MTS", r"\bMTS\b|\bmember of technical staff\b", "printed rung", names_rung=True),
        ),
    ),
    # Wise prints its IC rung in brackets in the title ("Senior Software Engineer (IC3 -
    # Backend)", "Senior Product Analyst (IC2)"), and it outranks the title's own words.
    "wise": TitleProfile(
        "wise", calibrated=True, note="Prints its IC rung, (IC1)-(IC6), in the title.",
        ranks=tuple(
            RungRule(f"IC{n}", rf"\(\s*IC\s?{n}\b", "printed rung", names_rung=True) for n in (6, 5, 4, 3, 2, 1)
        ),
    ),
    # Pinterest titles its new-grad rung "University Grad" and numbers I and II
    # below Sr.
    "pinterest": TitleProfile(
        "pinterest", calibrated=True, note="University Grad, Software Engineer I and II below Sr.",
        rung_rules=(
            RungRule("University Grad", r"\buniversity grad\b", "new-grad rung", names_rung=True),
            *_engineer_numeral(("II", "Software Engineer II"), ("I", "Software Engineer I")),
        ),
    ),
    # Twitch posts Amazon's bands under its own board: Software
    # Engineer I (entry) < SDE II < SDE III (senior, as Amazon's L6).
    "twitch": TitleProfile(
        "twitch", calibrated=True, note="Amazon's SDE ladder: I entry, II mid, III senior.",
        rung_rules=_engineer_numeral(("III", "SDE III"), ("II", "SDE II"), ("I", "Software Engineer I")),
    ),
    # Adobe's number is the rung, one US range per number: 3 mid,
    # 4 senior ("Software Engineer 4 (P40)"), 5 staff. "Senior" alone spans
    # three bands there, so a rung word beside the number still decides.
    "adobe": TitleProfile(
        "adobe", calibrated=True, note="Numbered SDE rungs 3, 4, 5.",
        rung_rules=_engineer_numeral(("5", "SDE 5"), ("4", "SDE 4"), ("3", "SDE 3")),
    ),
    # Booking numbers its ladder from I: I entry, II mid.
    "booking": TitleProfile(
        "booking", calibrated=True, note="Software Engineer I and II below Senior.",
        rung_rules=_engineer_numeral(("II", "Software Engineer II"), ("I", "Software Engineer I")),
    ),
    # EA posts Software Engineer III on the Senior range: III is
    # senior there, as II is mid and I entry.
    "electronic-arts": TitleProfile(
        "electronic-arts", calibrated=True, note="Software Engineer I, II, III; III paid as Senior.",
        rung_rules=_engineer_numeral(
            ("III", "Software Engineer III"), ("II", "Software Engineer II"), ("I", "Software Engineer I"),
        ),
    ),
    # A banking ladder: its own "Job Listing Level" field publishes
    # Analyst < Associate < AVP < VP < SVP < Managing Director, so a "Vice
    # President" here is mid-career, not the executive the generic tier reads.
    # Masked, they state no level
    # until the ladder is calibrated; Managing Director stays a director.
    "icapital": TitleProfile(
        "icapital",
        note="Banking title ladder; VP and AVP are not director rungs.",
        not_rung=(r"\b(?:assistant|senior|executive)?\s*vice[\s-]+president\b", r"\b[ae]?vp\b", r"\bsvp\b"),
    ),
    # Professional-services firms: read by rank.
    "ey": TitleProfile("ey", calibrated=True, note="Firm rank, often its own title segment.", ranks=(
        *_big4_top("Partner", associate_director="Associate Director"),
        _rank("Assistant Director", r"\bassistant\s+director\b"),
        _rank("Assistant Manager", r"\bassistant\s+manager\b"),
        _rank("Associate Manager", rf"\b{_ASSOC}\s+manager\b"),
        _rank("Manager", r"\bmanager\b"),
        # "Senior Consultant" is one rank, so "Consultant / Senior Consultant"
        # reads as two ranks offered, not three words.
        _rank("Senior", rf"\b{_SR}(?:\s+(?:consultant|associate|analyst))?(?=\s|$|\d|-|,|\))"),
        # EY UK's Senior-equivalent rank.
        _rank("Senior", r"\bsupervising\s+associate\b"),
        _rank("Associate Consultant", r"\bassociate\s+consultant\b"),
        _rank("Staff", rf"\b(?:staff|consultant|analyst)\b|{_ASSOCIATE}"),
    )),
    "kpmg": TitleProfile("kpmg", calibrated=True, note="Firm rank leads the title.", ranks=(
        _rank("Associate Managing Director", rf"\b{_ASSOC}\s+managing director\b"),
        *_big4_top("Partner", associate_director="Associate Director"),
        _rank("Manager", r"\bmanager\b"),
        _rank("Senior Associate", rf"\b{_SR}\s+associate\b"),
        _rank("Associate", rf"\banalyst\b|{_ASSOCIATE}"),
    )),
    "deloitte": TitleProfile("deloitte", calibrated=True, note="Firm rank, appended or its own segment.", ranks=(
        *_big4_top("Partner", associate_director="Associate Director"),
        _rank("Manager", r"\bmanager\b"),
        _rank("Senior Consultant", rf"\b{_SR}\s+consultant\b"),
        _rank("Senior Consultant", rf"\b{_SR}(?=\s|$|,|-)"),
        _rank("Consultant", r"\bconsultant\b"),
        # Not "Associate": Deloitte US ranks no one Associate, and its titles
        # use the word for the role ("Associate Solution Architect").
        _rank("Analyst", r"\banalyst\b"),
    )),
    # Not calibrated: PwC is collected only on the user's Sync, so no
    # inventory title exists for the coverage gate to measure its ranks on.
    "pwc": TitleProfile("pwc", note="Firm rank appended to the title; unmeasured.", ranks=(
        *_big4_top("Partner", associate_director=None),
        _rank("Manager", r"\bmanager\b"),
        _rank("Senior Associate", rf"\b{_SR}\s+associate\b"),
        _rank("Associate", _ASSOCIATE),
    )),
    "accenture": TitleProfile("accenture", calibrated=True, note="Career level named in the title.", ranks=(
        _rank("Principal Director", r"\bprincipal\s+director\b"),
        _rank("Managing Director", r"\bmanaging director\b"),
        _rank("Associate Director", rf"\b{_ASSOC}\s+director\b"),
        _rank("Senior Manager", rf"\b{_SR}\s+manager\b"),
        _rank("Associate Manager", rf"\b{_ASSOC}\s+manager\b"),
        _rank("Manager", r"\bmanager\b"),
        # "Senior Project Cost Analyst": the rank's words need not touch.
        _rank("Senior Analyst", rf"\b{_SR}\s+(?:[\w&/-]+\s+){{0,3}}analyst\b"),
        _rank("Consultant", r"\bconsultant\b"),
        _rank("Analyst", r"\banalyst\b"),
    )),
}

_GENERIC = TitleProfile("__generic__")


def profile_for(company: str) -> TitleProfile:
    """The profile governing this company, or a no-op generic profile."""
    return PROFILES.get(company, _GENERIC)


def rung_rules_for(company: str) -> tuple[RungRule, ...]:
    """Own rules, then the parent company's (own rules win by position)."""
    return tuple(rule for slug in lineage(company) for rule in profile_for(slug).rung_rules)


def family_rules_for(company: str, ladder_family: str) -> tuple[RungRule, ...]:
    """A family ladder's own rules, own company first, then the parent's."""
    return tuple(
        rule for slug in lineage(company)
        for rule in profile_for(slug).family_rules.get(ladder_family, ())
    )


@dataclass(frozen=True)
class TitleMatch:
    """A rule that matched, and the ladder whose rung it names (None = the
    company row)."""

    rule: RungRule
    ladder: Ladder | None


def domain_terms_for(company: str) -> dict[str, tuple[str, ...]]:
    """Company-internal domain vocabulary, merged with the parent company's."""
    merged: dict[str, tuple[str, ...]] = {}
    for slug in lineage(company):
        for domain, terms in profile_for(slug).domain_terms.items():
            merged[domain] = merged.get(domain, ()) + terms
    return merged


def company_domains(company: str, text: str) -> list[str]:
    """Every domain this company's own internal vocabulary names, in
    declaration order. Multi-label for the same reason as
    `taxonomy.domains.match_domains`: recording all worlds is what lets the
    scope gate keep a posting when ANY of them is enabled."""
    if not text:
        return []
    hay = f" {text.lower()} "
    return [
        slug
        for slug, terms in domain_terms_for(company).items()
        if any(term in hay for term in terms)
    ]


# --- rung phrases (atlas `rung_titles.csv`) ------------------------ #


def phrase_index(rows: tuple[RungTitle, ...]) -> dict[str, tuple[RungTitle, ...]]:
    """Phrases by company, longest first: the most specific phrase wins
    ("senior engineering manager" before "engineering manager")."""
    out: dict[str, list[RungTitle]] = {}
    for row in sorted(rows, key=lambda r: (-len(r.phrase), r.phrase)):
        out.setdefault(row.company, []).append(row)
    return {company: tuple(rows) for company, rows in out.items()}


#: The atlas's rung phrases, indexed once.
RUNG_PHRASES = phrase_index(load_rung_titles())


def phrase_meets(words: str, row: RungTitle) -> bool:
    """Whether a title's words (`atlas.phrase_words`) meet a phrase row."""
    if row.match == "exact":
        return words == row.phrase
    if row.match == "prefix":
        return words == row.phrase or words.startswith(row.phrase + " ")
    return f" {row.phrase} " in f" {words} "


@dataclass(frozen=True)
class PhraseMatch:
    row: RungTitle
    ladder: Ladder


def match_rung_phrase(company: str, head: str, family: str | None = None) -> PhraseMatch | None:
    """The phrase row a title head meets, or None: the posting's family ladder
    first (when this taxonomy family reads one), then the company's row; the
    company's own rows first, then its parent's. The row is what the regex
    rules read every family by (`ladder.ladder_for`): the `company` ladder, or
    a company-wide engineering ladder (Amazon's L-ladder grades every
    function, so its phrases read a supply-chain title too). `head` is the
    head plus its leading seniority words, as `read_level` reads it, never the
    org path."""
    words = phrase_words(head)
    if not words:
        return None
    family_ladder = reading_ladder(company, family)
    wanted = [family_ladder.family] if family_ladder is not None else []
    row_ladder = ladder_for(company)
    if row_ladder is not None and row_ladder.company_wide and row_ladder.family not in wanted:
        wanted.append(row_ladder.family)
    for slug in lineage(company):
        rows = RUNG_PHRASES.get(slug, ())
        for ladder_family in wanted:
            for row in rows:
                if row.family == ladder_family and phrase_meets(words, row):
                    ladder = next(lad for lad in ladders_of(slug) if lad.family == row.family)
                    return PhraseMatch(row, ladder)
    return None


def not_rung_pattern(company: str) -> re.Pattern[str] | None:
    """One pattern over the `not_rung` phrases of this company and its
    parents, or None when none is declared."""
    phrases = [phrase for slug in lineage(company) if (p := PROFILES.get(slug)) for phrase in p.not_rung]
    return re.compile("|".join(f"(?:{phrase})" for phrase in phrases), re.I) if phrases else None


def match_title(company: str, title: str, family: str | None = None) -> TitleMatch | None:
    """The first rule that matches: the family ladder's own rules (when this
    taxonomy family reads one), then the company row's. None when the
    company's vocabulary is silent.

    `title` must already be reduced to the head (+ preceding seniority) by the
    caller — see `taxonomy.title_parse.head_with_seniority`. Passing a full title
    would let an org path decide a level.
    """
    ladder = reading_ladder(company, family)
    if ladder is not None:
        for rule in family_rules_for(company, ladder.family):
            if rule.matches(title):
                return TitleMatch(rule, ladder)
    for rule in rung_rules_for(company):
        if rule.matches(title):
            return TitleMatch(rule, None)
    return None


_DUAL_GAP = re.compile(r"^\s*(?:/|&|\+|\bor\b|\band\b)\s*$", re.I)


def rank_for_title(company: str, title: str) -> RungRule | None:
    """The firm rank this title states, or None.

    Read over the whole title: a firm writes its rank as its own segment. The
    first rule in order wins, except that two ranks joined by "/" or "or"
    ("Manager/Senior Manager") are a dual-level req and read the lower, as a
    printed dual rung does (`taxonomy.stated_level.lowest_stated_rung`).
    """
    ranks = profile_for(company).ranks
    if not ranks or not title:
        return None
    found = [(m.start(), m.end(), rule) for rule in ranks for m in re.finditer(rule.pattern, title, re.I)]
    if not found:
        return None
    # A match inside a longer one is part of it ("manager" in "Senior Manager").
    spans = sorted(
        (f for f in found if not any(o[0] <= f[0] and f[1] <= o[1] and o[:2] != f[:2] for o in found)),
        key=lambda f: f[0],
    )
    for (_, end, left), (start, _, right) in zip(spans, spans[1:], strict=False):
        if left is not right and _DUAL_GAP.match(title[end:start]):
            pair = [left, right]
            return min(pair, key=lambda r: _rank_order(company, r))
    return next(rule for rule in ranks if any(f[2] is rule for f in spans))


def _rank_order(company: str, rule: RungRule) -> int:
    band = band_for(company, rule.rung)
    return LEVEL_BAND_ORDER[band.value] if band is not None else len(LEVEL_BAND_ORDER)


def rung_for_title(company: str, title: str, family: str | None = None) -> str | None:
    """The company's own ladder rung for this title (see `match_title`)."""
    match = match_title(company, title, family)
    return match.rule.rung if match is not None else None

