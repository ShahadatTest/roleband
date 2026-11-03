"""Posting text -> classified evidence units with stable offsets.

Every unit is an exact substring of one stored section's content (or the title),
carrying `[start_offset, end_offset)` that round-trips: content[start:end] == text.
That substring guarantee is what the grounding validator enforces downstream —
evidence quotes are never paraphrased.

Classification is heading prior + sentence-level override: the section heading
sets the default aspect, but pay/legal/application cues inside a unit override it
(Amazon publishes comp inside `preferred_qualifications`; the override catches it).

A section is not always one block. Microsoft prints "Required
Qualifications:" and "Preferred Qualifications:" inside one `qualifications`
section, and many boards store a whole posting as one `job_description`: a line
that is wholly a block heading opens that block until the next one.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from tracker.skills.years import stated_years

# Aspects: where in the posting's rhetoric the unit lives.
ASPECTS = (
    "minimum", "preferred", "responsibility", "team", "company",
    "benefit", "legal", "application", "other",
)

# --- Block headings, read whole ------------------------------------------------
# Matched against the WHOLE normalized line (or section title): "Requirements
# gathering with stakeholders" and "Python a plus" begin with heading words and
# are requirements, never headings. Apostrophes normalize to a space, so a
# section key ("what_we_re_looking_for") reads like its title. The phrases are
# the headings stored postings print.
_NOUN = (
    r"(?:qualifications?|requirements?|skills|experience|competencies|attributes|knowledge|abilities"
    r"|education(?: and training)?|(?:academic )?credentials)"
)
_QUAL = rf"{_NOUN}(?: and {_NOUN})?(?: for (?:the role|this role|success))?"
_YOU_LL = r"you(?: ll| will)?"
_BLOCK_HEADINGS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("preferred", re.compile(
        rf"(?:additional (?:(?:/|or|and) )?)?(?:preferred|desired|desirable|bonus|suggested)(?: {_QUAL})?"
        rf"|preferred (?:/|or|and) additional(?: {_QUAL})?"
        r"|nice to haves?|great to haves?|bonus points?(?: if(?: you have)?| for)?"
        r"|bonus (?:skills|points) to stand out|bonus if you have(?: the following)?"
        r"|ways to stand out(?: from the crowd)?|what (?:would|will) make(?:s)? you stand out"
        r"|(?:it s )?a plus if you have|it s a plus|pluses|we prefer|even better if you have"
    )),
    ("minimum", re.compile(
        rf"(?:additional )?(?:minimum|basic|required|essential|key|core|your)(?: ?/ ?(?:minimum|required))? {_QUAL}"
        rf"|(?:[a-z]+ ){{0,2}}requirements?(?: for the role)?|required|qualifications|{_NOUN} and {_NOUN}"
        r"|must haves?|job requirements other and additional"
        rf"|(?:here s )?what (?:{_YOU_LL}|we) need(?: to see| to succeed)?(?: from you)?"
        r"|(?:here s )?(?:what|who) we(?: re| are) looking for(?: in you)?|(?:[a-z]+ ){1,3}we(?: re| are) looking for"
        r"|what we look for|to be successful(?: in this role)?(?: you (?:have|need|will have))?"
        rf"|who you are|about you|you have|what you (?:must )?have|what {_YOU_LL} bring(?: to the team)?"
    )),
    ("responsibility", re.compile(
        r"(?:key |main |core |primary |additional |essential )?(?:job )?responsibilities"
        r"|duties(?: and responsibilities)?"
        rf"|what {_YOU_LL} (?:do|be doing|own|work on|be working on)"
        r"|(?:about )?the (?:role|job|position|opportunity)|about this (?:role|job|position)"
        r"|(?:role|position|job|general) (?:overview|summary)|in this role(?: you(?: ll| will)?)?"
        r"|you will|your (?:role|impact|mission)|day to day|a day in the life"
    )),
    ("team", re.compile(
        r"(?:about|meet) (?:the|our) team|the team|our team|team overview"
        r"|(?:our |the )?(?:tech(?:nical)? (?:stack|environment)|tech stack|stack)"
    )),
    ("benefit", re.compile(
        r"(?:our |your )?benefits(?: and perks| package)?|perks(?: and benefits)?"
        r"|compensation(?: and benefits)?|total rewards|what we offer(?: you)?|salary and benefits"
        r"|(?:annual |base )?salary(?: range)?|(?:expected |local |the )?pay range(?: transparency)?"
        r"|pay transparency|pay range and other compensation and benefits"
    )),
    ("legal", re.compile(
        r"equal (?:employment )?opportunity(?: employer)?(?: statement)?|eeo(?: statement)?"
        r"|(?:reasonable )?accommodations?|export control(?: requirements?)?|compliance"
        r"|state specific notices|fair chance(?: ordinances)?|other employment statements"
    )),
    ("application", re.compile(
        r"how to apply|(?:application|interview|hiring|recruiting) process"
        r"|application (?:window|deadline)(?: notice)?"
    )),
    ("company", re.compile(
        r"about us|who we are|our (?:mission|story|company|values|culture)|company (?:overview|description)"
        r"|how we(?: re| are) different|come work with us|why [a-z0-9][a-z0-9 .]{0,24}|about [a-z0-9][a-z0-9 .]{0,24}"
        r"|life at [a-z0-9][a-z0-9 .]{0,24}"
        # Amazon's company paragraphs, printed after its requirements.
        r"|diverse experiences|inclusive team culture|work / life balance|mentorship and career growth"
    )),
    ("other", re.compile(
        r"additional (?:information|info)|locations?|logistics|summary|overview|(?:job )?description"
        r"|additional job elements|(?:other )?job details|other"
    )),
)
_BULLET_LEAD = re.compile(r"^[\s\-*•·–—]+")
_TAIL_PUNCT = re.compile(r"[\s:?!.\-–—]+$")
_PARENTHETICAL = re.compile(r"\s*\([^)]*\)\s*$")  # "Nice to have (not required)"
# "Preferred Qualifications: 3+ years of ..." or "Minimum education: Bachelor's
# degree": a heading glued to the one line it labels.
_INLINE_HEADING = re.compile(r"^[\s\-*•·]*(?P<label>[^:\n]{2,40}):\s*\S")
# "Additional or preferred qualificationsMaster's Degree ...": a source that
# loses the newline after a heading, which still opens the block that follows.
_GLUED_HEADING = re.compile(
    r"^[\s\-*•·]*(?P<label>[A-Za-z][A-Za-z /]{4,48}?(?:qualifications?|requirements?))(?=[A-Z])"
)
_WORD_HYPHEN = re.compile(r"(?<=[a-z])-(?=[a-z])")
_COMPOUND_SPLIT = re.compile(r" (?:—|–|-|/|\||and) ")
_QUALIFICATION_ASPECTS = ("minimum", "preferred")


def _normalize_heading(text: str) -> str:
    text = _BULLET_LEAD.sub("", text.lower())
    text = text.replace("’", " ").replace("'", " ").replace("_", " ").replace("&", " and ")
    text = _WORD_HYPHEN.sub(" ", text).replace("/", " / ").replace("*", "").replace(":", " ")
    text = _PARENTHETICAL.sub("", _TAIL_PUNCT.sub("", text))
    return " ".join(text.split())


def _whole_heading(line: str) -> str | None:
    for aspect, pattern in _BLOCK_HEADINGS:
        if pattern.fullmatch(line):
            return aspect
    return None


def block_heading(text: str) -> str | None:
    """The aspect a line opens when the whole line is a block heading, else None.

    A compound (PayPal's "What You'll Bring" and "Minimum Qualifications"
    joined by a dash, "Additional Responsibilities & Preferred Qualifications")
    is a heading when every part is one; the qualification part names the block
    that follows."""
    if len(text) > 80:
        return None
    line = _normalize_heading(text)
    if not line:
        return None
    whole = _whole_heading(line)
    if whole is not None:
        return whole
    parts = [_whole_heading(part) for part in _COMPOUND_SPLIT.split(line)]
    if len(parts) < 2 or None in parts:
        return None
    return next((aspect for aspect in parts if aspect in _QUALIFICATION_ASPECTS), parts[0])


def _inline_heading(text: str) -> str | None:
    """A minimum or preferred heading glued to the line it labels."""
    match = _INLINE_HEADING.match(text)
    if match is None:
        return None
    aspect = block_heading(match.group("label"))
    return aspect if aspect in _QUALIFICATION_ASPECTS else None


def _glued_heading(text: str) -> str | None:
    """A minimum or preferred heading run into its block's first line."""
    match = _GLUED_HEADING.match(text)
    if match is None:
        return None
    aspect = block_heading(match.group("label"))
    return aspect if aspect in _QUALIFICATION_ASPECTS else None


# --- Section-heading priors (matched against key + title, lowercased) ----------
# Fuzzy fallback for a heading `block_heading` does not read whole. Preferred is
# tried first: "Preferred Qualifications" also contains "qualifications".
_HEADING_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("preferred", re.compile(r"preferred|nice to have|bonus point|desirable|great to have|plus\b")),
    ("minimum", re.compile(r"minimum|basic qualification|requirements|must have|what you need|what we need|qualifications")),
    ("responsibility", re.compile(r"responsibilit|what you.?ll do|what you will do|the role\b|your (?:role|impact)|day.to.day|about the (?:role|job|position)|duties")),
    ("team", re.compile(r"about the team|the team\b|our team|team overview")),
    ("benefit", re.compile(r"benefit|compensation|salary|\bpay\b|perks|total rewards|what we offer")),
    ("legal", re.compile(r"equal opportunity|eeo|accommodation|affirmative|non.?discrimination|export control")),
    ("application", re.compile(r"how to apply|application process|interview process|hiring process|recruiting")),
    ("company", re.compile(r"about (?:us|the company)|who we are|our (?:company|mission|story)|company overview")),
)

# --- Unit-level overrides (heading is a prior, not authority) -------------------
_BENEFIT_UNIT = re.compile(
    r"\$\s?\d{1,3},\d{3}|salary range|base (?:salary|pay)|sign[\s-]?on|401\(?k"
    r"|health (?:insurance|benefits)|medical, dental|paid time off|\bpto\b"
    r"|compensation (?:range|package|will be)|bonus target|restricted stock|rsus?\b"
    r"|total compensation",
    re.IGNORECASE,
)
_LEGAL_UNIT = re.compile(
    r"equal (?:employment )?opportunity|without regard to|protected veteran"
    r"|reasonable accommodation|e-?verify|affirmative action",
    re.IGNORECASE,
)
_APPLICATION_UNIT = re.compile(
    r"recruiting partner|to apply\b|application deadline|background check"
    r"|contact (?:your|the) recruiter",
    re.IGNORECASE,
)

# --- Actor cues -----------------------------------------------------------------
_CANDIDATE_CUE = re.compile(
    r"\byou (?:have|are|bring|possess|hold)\b|your (?:experience|background)"
    r"|ideal candidate|candidates? (?:should|must|will have)"
    r"|experience (?:with|in|building|leading)|proficien|familiarity|fluen"
    r"|track record|demonstrated|knowledge of|ability to|degree in|\d+\+?\s*years",
    re.IGNORECASE,
)
_TEAM_CUE = re.compile(
    r"\b(?:the|our) team (?:uses|works|is|owns|builds)|we use\b|our (?:stack|codebase)",
    re.IGNORECASE,
)
_COMPANY_CUE = re.compile(
    r"\b(?:our|the) (?:company|organization|org)\b|we(?:'re| are) (?:a|the|one of)\b"
    r"|our (?:products?|platform|customers|mission)\b",
    re.IGNORECASE,
)

# --- Negation: a mentioned concept explicitly NOT required ----------------------
_NEGATION = re.compile(
    r"not required|not a requirement|is not necessary|not necessary"
    r"|need not|no prior .{0,40}?(?:required|necessary|needed)"
    r"|nice but (?:not necessary|unnecessary)|without (?:needing|requiring)"
    r"|not expected to",
    re.IGNORECASE,
)

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?;])\s+")


def affirmed_text(text: str) -> str:
    """`text` without its sentences that negate a requirement. A negation
    reaches its own sentence: "Minimum of 5 years of experience as a TPM.
    Consulting experience is a plus but not required" still requires 5 years."""
    return " ".join(sent for sent in _SENTENCE_SPLIT.split(text) if not _NEGATION.search(sent))


@dataclass(frozen=True)
class EvidenceUnit:
    section_key: str | None  # None => job title pseudo-section
    section_title: str | None
    unit_index: int
    text: str
    start_offset: int  # within the section's stored content (or the title string)
    end_offset: int
    aspect: str
    actor: str  # candidate|role|team|company|other
    modality: str  # required|preferred|used_in_role|context
    negated: bool


def _heading_aspect(key: str | None, title: str | None) -> str:
    """Aspect prior from the section heading. Key rules win over fuzzy title text."""
    if key == "minimum_qualifications":
        return "minimum"
    if key == "preferred_qualifications":
        return "preferred"
    for text in (title, key):
        whole = block_heading(text) if text else None
        if whole is not None:
            return whole
    haystack = f"{key or ''} {title or ''}".lower().replace("_", " ")
    for aspect, pattern in _HEADING_RULES:
        if pattern.search(haystack):
            return aspect
    return "other"


def _unit_aspect(text: str, heading_aspect: str) -> str:
    """Sentence-level exclusion cues override the heading prior."""
    if _BENEFIT_UNIT.search(text):
        return "benefit"
    if _LEGAL_UNIT.search(text):
        return "legal"
    application_text = text
    if heading_aspect in _QUALIFICATION_ASPECTS and stated_years(text, requirement_line=True):
        application_text = re.sub(
            r"\(exceptional new grads[^)]{0,160}\bwelcome to apply\)", "", text, flags=re.I,
        )
    if _APPLICATION_UNIT.search(application_text):
        return "application"
    return heading_aspect


def _unit_actor(text: str, aspect: str) -> str:
    """Subject of the unit: who the statement is about."""
    if aspect in ("benefit", "legal", "application", "company"):
        return "company"
    if _TEAM_CUE.search(text) and not _CANDIDATE_CUE.search(text):
        return "team"
    if _COMPANY_CUE.search(text) and not _CANDIDATE_CUE.search(text):
        return "company"
    if aspect in ("minimum", "preferred"):
        return "candidate"
    if aspect == "responsibility":
        return "role"
    if _CANDIDATE_CUE.search(text):
        return "candidate"
    if aspect == "team":
        return "team"
    return "other"


def _unit_modality(aspect: str, negated: bool) -> str:
    if negated:
        return "context"  # explicitly not a requirement
    if aspect == "minimum":
        return "required"
    if aspect == "preferred":
        return "preferred"
    if aspect == "responsibility":
        return "used_in_role"
    return "context"


def _split_units(content: str) -> list[tuple[int, int]]:
    """Offsets of units within `content`: one per line; long prose lines split
    into sentences. Offsets index the ORIGINAL string (no normalization)."""
    spans: list[tuple[int, int]] = []
    pos = 0
    for line in content.split("\n"):
        start = pos
        pos += len(line) + 1  # +1 for the split newline
        stripped = line.strip()
        if not stripped:
            continue
        lead = len(line) - len(line.lstrip())
        line_start = start + lead
        line_end = line_start + len(stripped)
        # Bullets stay whole; prose paragraphs split into sentences.
        if len(stripped) > 220 and _SENTENCE_SPLIT.search(stripped):
            cursor = line_start
            for sent in _SENTENCE_SPLIT.split(stripped):
                sent = sent.strip()
                if not sent:
                    continue
                found = content.find(sent, cursor, line_end)
                if found == -1:  # defensive; should not happen
                    continue
                spans.append((found, found + len(sent)))
                cursor = found + len(sent)
        else:
            spans.append((line_start, line_end))
    return spans


def segment_job(
    title: str | None,
    sections: list[dict] | None,
) -> list[EvidenceUnit]:
    """Segment a stored posting into classified evidence units.

    `sections` is the `jobs.description_sections` JSONB payload
    ([{key,title,content}, ...]). The job title becomes one pseudo-unit with
    section_key=None so a concept named in the title still gets grounded,
    low-weight evidence.
    """
    units: list[EvidenceUnit] = []

    if title and title.strip():
        t = title.strip()
        units.append(
            EvidenceUnit(
                section_key=None,
                section_title=None,
                unit_index=0,
                text=t,
                start_offset=title.find(t),
                end_offset=title.find(t) + len(t),
                aspect="other",
                actor="role",
                modality="context",
                negated=False,
            )
        )

    for section in sections or []:
        key = section.get("key")
        sec_title = section.get("title")
        content = section.get("content") or ""
        if not content.strip():
            continue
        heading = _heading_aspect(key, sec_title)
        for idx, (start, end) in enumerate(_split_units(content)):
            text = content[start:end]
            heading = block_heading(text) or _glued_heading(text) or heading
            negated = bool(_NEGATION.search(text))
            # A label glued to its line ("Minimum education: Bachelor's") names
            # that line only: the next line may be "Visa sponsorship: ...".
            aspect = _unit_aspect(text, _inline_heading(text) or heading)
            units.append(
                EvidenceUnit(
                    section_key=key,
                    section_title=sec_title,
                    unit_index=idx,
                    text=text,
                    start_offset=start,
                    end_offset=end,
                    aspect=aspect,
                    actor=_unit_actor(text, aspect),
                    modality=_unit_modality(aspect, negated),
                    negated=negated,
                )
            )
    return units
