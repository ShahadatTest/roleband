"""Title normalization and head extraction.

Shared foundation for every per-company reading of a posting title. Two jobs, and
deliberately no more: clean the string, and find the segment that names the role.

Why the head matters: a title is positional — `[seniority] [ROLE HEAD], [qualifier],
…, [ORG PATH]`, and the org path is *not* evidence about the role. The first
segment almost always carries the role noun; the last rarely does. Anything that
reads the whole string lets an org name decide a role's level or family.

Two sharp edges:

- The first segment is sometimes only a seniority word (`Principal, Technical
  Program Manager , Amazon Customer Service`), so the role
  continues into the next segment.
- Some employers write **org first**: apple's `User Experience - Quality
  Engineering Manager` and `Machine Learning - Engineering Program Manager` put
  the department ahead of the role. Taking the first segment there reads a
  department as the job.

So `title_head` prefers the first segment that actually names a role — carries a
role noun or a known abbreviation — and only falls back to position when no
segment does.
"""

from __future__ import annotations

import re

# Separators observed across the roster. Company profiles narrow this; the union
# is the safe default for a company we have not measured.
_SEPARATORS = re.compile(r",|\s-\s|\s–\s|\s—\s|\s\|\s")

# Trailing noise that is never part of the role: requisition ids and the language
# markers some sources append ("(Korean, English)").
_REQ_CODE = re.compile(r"\s*[-–—]?\s*\b[A-Z]{2,}\d[A-Z0-9.\-]*\s*$")
# Never a rung: "Business Development (Director)" states the level the way
# "(Korean)" states a language, and must not be stripped as one.
_LANG_PAREN = re.compile(
    r"\s*\((?!(?:Director|Senior|Sr|Principal|Staff|Lead|Manager|Head|VP|Vice)\b)"
    r"(?:[A-Z][a-z]+)(?:,\s*[A-Z][a-z]+)*\)\s*$"
)

# Words that qualify a role without naming one. A segment made only of these is
# not the head.
_SENIORITY_ONLY = frozenset(
    {
        "sr", "sr.", "senior", "principal", "staff", "lead", "distinguished",
        "fellow", "associate", "junior", "jr", "jr.", "group", "global",
        "worldwide", "ww", "partner", "technical", "deputy", "first", "new",
        "manager", "managing", "director", "head", "chief", "vp", "svp", "evp",
        "and", "of", "the", "&", "-",
    }
)


# Words that name a role. Substring-matched, so "architect" covers
# "architecture" — deliberate, because a segment mentioning architecture at all
# is a plausible role name; position is what disambiguates it, not vocabulary.
_ROLE_NOUNS = (
    "engineer", "manager", "management", "scientist", "science", "architect",
    "analyst", "designer", "developer", "researcher", "director", "counsel",
    "recruiter", "writer", "consultant", "specialist", "administrator",
    "president", "officer", "advocate", "attorney", "paralegal", "technician",
    "producer", "strategist",
)
# Abbreviated roles that carry no role noun.
_ROLE_ABBREV = frozenset({"tpm", "tpgm", "sde", "sa", "pm", "mts", "swe", "tlm", "em", "dri"})


def names_a_role(segment: str) -> bool:
    """Whether this text carries a role noun or a known role abbreviation.

    Public: `search/policy` uses it to decide if a QUERY names a role at all —
    the taxonomy's `classify_role` answers "which family", but returns None for
    perfectly role-shaped text it has no family for ("Staff Engineer",
    "Analyst"), and that gap must not decide whether a role claim was made.
    """
    low = segment.lower()
    if any(noun in low for noun in _ROLE_NOUNS):
        return True
    return any(w.strip(".") in _ROLE_ABBREV for w in re.split(r"[\s/(),.]+", low) if w)


def normalize(title: str) -> str:
    """Collapse whitespace and strip trailing req codes / language markers.

    Cheap, deterministic, and safe on every source: it only removes text that is
    provably not part of the role name. Leaves case alone — callers lower as
    needed, and display wants the original casing.
    """
    text = title.replace(" ", " ")
    text = _LANG_PAREN.sub("", text)
    text = _REQ_CODE.sub("", text)
    text = re.sub(r"\s+", " ", text)
    # Tidy the punctuation damage sources leave behind (" ,", ", ,", trailing ",").
    text = re.sub(r"\s+,", ",", text)
    text = re.sub(r"(,\s*)+,", ", ", text)
    return text.strip().strip(",").strip()


def segments(title: str, separators: re.Pattern[str] | None = None) -> list[str]:
    """Ordered, non-empty segments of a normalized title."""
    pattern = separators or _SEPARATORS
    return [p.strip() for p in pattern.split(normalize(title)) if p.strip()]


def title_head(title: str, separators: re.Pattern[str] | None = None) -> str:
    """The segment naming the role, skipping segments that are only seniority.

    `Principal, Technical Program Manager , Amazon Customer Service`
    -> `Technical Program Manager`. Falls back to the first segment when every
    segment is seniority-only, so the result is never empty for a non-empty title.
    """
    parts = segments(title, separators)
    if not parts:
        return ""
    candidates = [
        part
        for part in parts
        if any(w not in _SENIORITY_ONLY for w in re.split(r"[\s/()]+", part.lower()) if w)
    ]
    if not candidates:
        return parts[0]
    for part in candidates:
        if names_a_role(part):
            return part
    return candidates[0]


def org_path(title: str, separators: re.Pattern[str] | None = None) -> str:
    """Everything that is not the role head — the org/product the role sits in.

    Not evidence about the role's level or family (that is the whole point of
    `title_head`), but it is the strongest available signal about the *domain*
    the work belongs to, and for employers who publish no category field it is
    the only one.
    """
    parts = segments(title, separators)
    head = title_head(title, separators)
    return " ".join(part for part in parts if part != head)


def head_with_seniority(title: str, separators: re.Pattern[str] | None = None) -> str:
    """Head plus any seniority-only segments that preceded it.

    Level rules need the seniority words that `title_head` skipped: for
    `Principal, Technical Program Manager` the rung evidence is "Principal" and
    the role evidence is "Technical Program Manager". Callers matching level
    vocabulary want both, and nothing from the org path.
    """
    parts = segments(title, separators)
    if not parts:
        return ""
    head = title_head(title, separators)
    # Seniority-only segments join the head from ANY position: meta writes
    # `Product Management, Director` with the rung after the role, apple writes
    # `AIML - Director, Data Science` with it in the middle. An org path is never
    # seniority-only, so `Sr. Program Manager, Principal Investigator Team`
    # still contributes nothing from its tail.
    prefix = [
        part
        for part in parts
        if part != head
        and (words := [w for w in re.split(r"[\s/()]+", part.lower()) if w])
        and all(w in _SENIORITY_ONLY for w in words)
    ]
    return " ".join([*prefix, head])
