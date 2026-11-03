"""Quote-grounded responsibility facts for offline level experiments."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Literal

from tracker.skills.segment import block_heading, segment_job
from tracker.skills.years import stated_experience_field, stated_years

CONTEXT_VERSION = "1.4.0"
FEATURES = ("required_years", "preferred_years", "unspecified_years", "autonomy",
            "ownership_breadth", "architecture", "people_management", "organizational_impact")
_EXCLUDED_ASPECTS = frozenset({"company", "team", "benefit", "legal", "application"})


@dataclass(frozen=True)
class SourceSpan:
    source: Literal["description_text", "description_sections"]
    section_index: int | None
    start: int
    end: int
    quote: str


@dataclass(frozen=True)
class FeatureEvidence:
    feature: str
    value: str | tuple[int, ...]
    modality: str
    alternatives: bool
    span: SourceSpan
    context: SourceSpan | None = None


@dataclass(frozen=True)
class ExperienceRoute:
    availability: SourceSpan
    heading: SourceSpan
    years: tuple[int, ...] | None
    statement: SourceSpan | None
    alternatives: Literal[True] = True


@dataclass(frozen=True)
class ContextProfile:
    source_hash: str
    version: str
    features: dict[str, tuple[FeatureEvidence, ...] | None]
    experience_routes: tuple[ExperienceRoute, ...] = ()

    @property
    def missing(self) -> tuple[str, ...]:
        return tuple(key for key, entries in self.features.items() if entries is None)


@dataclass(frozen=True)
class _Source:
    source: Literal["description_text", "description_sections"]
    index: int | None
    key: str
    title: str
    content: str


def _sources(description: str | None, sections: list[dict] | None) -> list[_Source]:
    result = []
    for index, section in enumerate(sections or []):
        content = section.get("content")
        if isinstance(content, str) and content.strip():
            result.append(_Source("description_sections", index, str(section.get("key") or ""),
                                  str(section.get("title") or ""), content))
    if not result and description:
        result.append(_Source("description_text", None, "job_description", "Job description", description))
    return result


def _source_hash(sources: list[_Source]) -> str:
    content = [(s.source, s.index, s.key, s.title, s.content) for s in sources]
    return hashlib.sha256(json.dumps(content, ensure_ascii=False).encode()).hexdigest()


_AVAILABILITY = re.compile(r"This role is open at (?P<labels>[^.\n]{1,180}\bor\b[^.\n]{1,80}) level\.", re.I)


def _experience_routes(source: _Source) -> tuple[tuple[ExperienceRoute, ...], list[tuple[int, int]]]:
    routes: list[ExperienceRoute] = []
    intervals: list[tuple[int, int]] = []
    lines: list[SourceSpan] = []
    offset = 0
    for raw_line in source.content.splitlines(keepends=True):
        quote = raw_line.strip()
        if quote:
            start = offset + len(raw_line) - len(raw_line.lstrip())
            lines.append(SourceSpan(source.source, source.index, start, start + len(quote), quote))
        offset += len(raw_line)
    units = segment_job(None, [{"key": source.key, "title": source.title, "content": source.content}])
    for index, line in enumerate(lines):
        availability = _AVAILABILITY.match(line.quote)
        if availability is None:
            continue
        unit = next((u for u in units if u.start_offset <= line.start < u.end_offset), None)
        if unit is None or unit.aspect in _EXCLUDED_ASPECTS:
            continue
        anchor = SourceSpan(source.source, source.index, line.start,
                            line.start + availability.end(), availability.group())
        group: list[ExperienceRoute] = []
        end = len(source.content)
        for position in range(index + 1, len(lines)):
            heading = lines[position]
            if block_heading(heading.quote) is not None or _AVAILABILITY.match(heading.quote):
                end = heading.start
                break
            if (not heading.quote.endswith(":") or len(heading.quote.split()) > 6
                    or ":" in heading.quote[:-1]):
                continue
            label = heading.quote[:-1].strip()
            if not label or re.search(r"(?<!\w)" + re.escape(label) + r"(?!\w)", availability["labels"], re.I) is None:
                continue
            statement = lines[position + 1] if position + 1 < len(lines) else None
            years = stated_experience_field(statement.quote) if statement else []
            group.append(ExperienceRoute(anchor, heading, tuple(years) if years else None,
                                         statement if years else None))
        if len(group) >= 2:
            routes.extend(group)
            intervals.append((group[0].heading.start, end))
    return tuple(routes), intervals


_PREFERRED = re.compile(r"\bpreferred\b|nice to have|a plus\b|bonus (?:if|points)", re.I)
_REQUIRED = re.compile(r"\brequired\b|\bmust have\b|\bat least\b|\bminimum\b", re.I)
_NEGATED = re.compile(r"\b(?:not required|not necessary|not expected|will not|you['’]ll not|do not|won.t|not responsible)\b"
                      r"|\bno (?:direct reports|people management)\b", re.I)
_NONROLE = re.compile(r"^(?:(?:our|the) (?:team|company|organization)|we\b|[A-Z][\w-]+ (?:is|has|provides)\b)", re.I)
_ROLE = re.compile(r"^(?:you (?:will|must|are responsible|own|architect|make scoping)|you['’]ll|own\b|lead\b|drive\b|design\b|"
                   r"develop\b|build\b|set\b|manage\b|hire\b|work\b|operate\b|be responsible\b|"
                   r"responsible for\b|provide\b|define\b|shape\b|take ownership\b|guide\b|establish\b|architect\b|close\b)", re.I)
_SENTENCES = re.compile(r"(?<=[.!?])\s+(?=[A-Z])|;\s*")
_TIMELINE = re.compile(r"^(?:month|week|day)\s+\d+\s*[-:–—]\s*(?=you will\b)", re.I)
_OWN_HEADING = re.compile(r"what you(?:['’]ll| will) own\s*:?$", re.I)
_SKILL_SUBJECT = r"(?P<subject>(?:[\w-]+\s+){1,5}(?:experience|expertise|knowledge|skills?|certification))"
_OTHER_PREFERENCE = re.compile(
    r"(?:\s[-–—]\s+|,\s+)" + _SKILL_SUBJECT +
    r"\s+(?:(?:is|are|would be)\s+)?(?:a plus|preferred)\b", re.I,
)
_SEPARATE_NEGATION = re.compile(
    r"\s[-–—]\s+(?=" + _SKILL_SUBJECT + r"\s+(?:is\s+)?not (?:required|necessary)\b)", re.I,
)
_DIRECT_ROLE = re.compile(r"^you (?:will\b|own\b|architect\b|are responsible\b|make scoping\b)|^you['’]ll\b", re.I)
_DECISION_DUTY = re.compile(r"^you make scoping\b.{0,80}\b(?:calls|decisions)\b", re.I)
_ADOPTION_OBJECT = re.compile(r"\b(?:product|platform|feature)\s+(?:activation|adoption|usage)\b", re.I)
_OUTCOME = r"(?:strateg(?:y|ies)|standards?|initiatives?|programs?|polic(?:y|ies)|outcomes?|roadmaps?|architecture)\b"
_ORG_SCOPE = r"(?:\b(?:organization|company|org)[- ]wide\b|\bacross (?:the |our )?organization\b)"
_OUTCOME_MODIFIER = r"(?!(?:collaboration|meetings?|partner|collaborate|attend)\b)[\w-]+"

_SCOPE_RULES: dict[str, tuple[tuple[str, re.Pattern[str]], ...]] = {
    "autonomy": (("independent", re.compile(
        r"\bindependently\b|\bminimal supervision\b|\blimited guidance\b|\bwith autonomy\b"
        r"|\bhave (?:the )?autonomy to\b|\bwithout waiting for sign[- ]off\b", re.I,
    )),),
    "ownership_breadth": (
        ("cross_team", re.compile(r"\b(?:own|lead|drive|define|shape)\b.{0,180}(?:across (?:multiple )?teams|cross.functional|cross.team)", re.I)),
        ("component_or_service", re.compile(
            r"\b(?:own|take ownership of|you(?:['’]ll| will)? have (?:significant |full |direct )?ownership (?:of|over))\b"
            r"(?:(?!\b(?:own|shape|drive|lead|build|design|develop|that|which)\b"
            r"|(?<![-\w])(?:from|to)(?![-\w])|[,.!?;]).){0,90}"
            r"\b(?:services?|systems?|components?|platforms?|products?|features?|subassembl(?:y|ies))\b", re.I,
        )),
    ),
    "architecture": (("stated", re.compile(
        r"\b(?:own|lead|design|define|defining|determining|drive|shape|set|develop|guide|establish)\s+"
        r"(?:[\w-]+\s+){0,6}architectur(?:e\b(?!\s+(?:discussions?|analys[ie]s)\b)"
        r"|al\s+(?:decisions?|designs?|patterns?|standards?|roadmaps?)\b)"
        r"|\bclose\s+(?:open\s+)?architectural\s+decisions?\b"
        r"|(?:^architect\b|\byou (?:will )?architect\b|\byou['’]ll architect\b)\s+"
        r"[^,.!?;]{0,90}\b(?:systems?|infrastructure|platforms?|parts?|solutions?|integrations?|pipelines?)\b", re.I,
    )),),
    "people_management": (("stated", re.compile(
        r"\bmanage\s+(?:(?:a|the|your)\s+)?team\s+of\b|\bdirect reports\b|"
        r"\b(?:conduct|own|lead)\b.{0,50}\bperformance reviews\b", re.I)),),
    "organizational_impact": (("organization", re.compile(
        r"\b(?:own|lead|drive|define|set|shape|deliver)\s+"
        rf"(?:(?:(?:the|our)\s+)?{_ORG_SCOPE}\s+(?:{_OUTCOME_MODIFIER}\s+){{0,4}}{_OUTCOME}"
        rf"|(?:{_OUTCOME_MODIFIER}\s+){{0,4}}{_OUTCOME}\s+{_ORG_SCOPE})", re.I,
    )),),
}


def _role_clause(text: str, aspect: str) -> bool:
    role_text = _TIMELINE.sub("", text)
    timeline = role_text != text
    if aspect in {"responsibility", "other"} and ":" in role_text:
        _, suffix = role_text.split(":", 1)
        if (aspect == "responsibility" and _ROLE.match(suffix.lstrip())
                or aspect == "other" and _DIRECT_ROLE.match(suffix.lstrip())):
            role_text = suffix.lstrip()
    if (_NONROLE.search(text) or _NEGATED.search(text)
            or re.match(r"you(?:['’]ll| will)? have (?:experience|expertise|the ability)\b", role_text, re.I)):
        return False
    if aspect == "responsibility" and re.match(r"partnering on determining\b", role_text, re.I):
        return True
    if (_DECISION_DUTY.match(role_text)
            and re.search(r"\bwithout waiting for sign[- ]off\b", role_text, re.I)):
        return True
    if aspect == "responsibility" or timeline:
        return bool(_ROLE.search(role_text))
    return aspect == "other" and bool(_DIRECT_ROLE.match(role_text))


def _scope_supported(feature: str, value: str, pattern: re.Pattern[str], text: str) -> bool:
    for match in pattern.finditer(text):
        if re.search(r"\b(?:who|that|which|they)\s+$", text[:match.start()], re.I):
            continue
        tail = re.match(r"\s+\w+", text[match.end():])
        owned = match.group() + (tail.group() if tail else "")
        if feature == "ownership_breadth" and value == "component_or_service" and _ADOPTION_OBJECT.search(owned):
            continue
        return True
    return False


def _ownership_heading(source: _Source, before: int) -> SourceSpan | None:
    heading = None
    offset = 0
    for line in source.content[:before].splitlines(keepends=True):
        stripped = line.strip()
        if block_heading(stripped) is not None:
            left = offset + len(line) - len(line.lstrip())
            heading = (SourceSpan(source.source, source.index, left, left + len(stripped), stripped)
                       if _OWN_HEADING.fullmatch(stripped) else None)
        offset += len(line)
    return heading


def _nominal_architecture(text: str) -> bool:
    return (not _NONROLE.search(text)
            and not re.search(r"\b(?:experience|knowledge|familiarity|expertise|ability|understanding)\b", text, re.I)
            and bool(re.match(r"^(?:[\w-]+\s+){0,3}architecture\b", text, re.I)))


def _fragments(text: str) -> list[tuple[int, int]]:
    if re.search(r"\bor\b", text, re.I) and re.search(r"bachelor|master|doctor|ph\.?d", text, re.I):
        return [(0, len(text))]
    result = []
    cursor = 0
    boundaries = sorted([*_SENTENCES.finditer(text), *_SEPARATE_NEGATION.finditer(text)], key=lambda m: m.start())
    for match in boundaries:
        if match.re is _SEPARATE_NEGATION and not _independent_skill(match):
            continue
        prefix = text[:match.start()]
        if not match.group(0).startswith(";") and prefix.count("(") > prefix.count(")"):
            continue
        if re.search(r"\b(?:sr|jr|dr|e\.g|i\.e)\.$", text[:match.start()], re.I):
            continue
        result.append((cursor, match.start()))
        cursor = match.end()
    result.append((cursor, len(text)))
    trimmed = []
    for start, end in result:
        chunk = text[start:end]
        left = len(chunk) - len(chunk.lstrip(" \t\r•*-"))
        right = len(chunk.rstrip())
        if left < right:
            trimmed.append((start + left, start + right))
    return trimmed


def _independent_skill(match: re.Match[str]) -> bool:
    prefix, suffix = match.string[:match.start()], match.string[match.end():]
    if not stated_years(prefix, requirement_line=True) or stated_years(suffix, requirement_line=True):
        return False
    generic = {"of", "in", "and", "or", "with", "the", "a", "an", "experience", "expertise", "knowledge",
               "skill", "skills", "certification", "professional", "relevant", "industry", "work", "working"}
    def words(text: str) -> set[str]:
        return set(re.findall(r"\b[a-z][a-z-]*\b", text.lower())) - generic
    subject = words(match.group("subject"))
    domain = words(re.split(r"\b(?:years?|yrs?)\b", prefix, flags=re.I)[-1])
    return bool(subject and domain and not subject & words(prefix))


def _negated_years(text: str) -> bool:
    optional = re.sub(r"\bpreferred but not required\b", "preferred", text, flags=re.I)
    return bool(_NEGATED.search(optional))


def _year_feature(text: str, aspect: str) -> tuple[str, str]:
    modality_text = re.sub(
        r"\([^)]*\)",
        lambda match: match.group(0) if stated_years(match.group(0), requirement_line=True) else "",
        text,
    )
    unrelated = _OTHER_PREFERENCE.search(modality_text)
    if unrelated and _independent_skill(unrelated):
        modality_text = modality_text[:unrelated.start()]
    if re.match(r"typically\b", modality_text, re.I):
        return "unspecified_years", "unspecified"
    if _PREFERRED.search(modality_text) or aspect == "preferred":
        return "preferred_years", "preferred"
    if aspect == "minimum" or _REQUIRED.search(text):
        return "required_years", "required"
    return "unspecified_years", "unspecified"


def _alternative_routes(text: str, years: tuple[int, ...]) -> bool:
    return bool(
        re.search(r"\bor\s+(?:(?:a|an|the)\s+)?(?:bachelor|master|doctor|ph\.?d|equivalent)", text, re.I)
        or re.search(r"\bexceptional new grads\b[^)]{0,160}\bwelcome to apply\b", text, re.I)
        or len(years) > 1 and re.search(
            r"alternatively|/\s*\d+\+?\s*years?|\bor\s+(?:at least\s+)?\d+\+?\s*years?", text, re.I,
        )
    )


def extract_context(description: str | None, *, sections: list[dict] | None = None) -> ContextProfile:
    """Keep direct source statements; missing evidence never becomes a scope guess."""
    sources = _sources(description, sections)
    evidence: dict[str, list[FeatureEvidence]] = {key: [] for key in FEATURES}
    routes: list[ExperienceRoute] = []
    for source in sources:
        source_routes, intervals = _experience_routes(source)
        routes.extend(source_routes)
        units = segment_job(None, [{"key": source.key, "title": source.title, "content": source.content}])
        for unit in units:
            if unit.aspect in _EXCLUDED_ASPECTS:
                continue
            for left, right in _fragments(unit.text):
                text = unit.text[left:right]
                if _negated_years(text):
                    continue
                span = SourceSpan(source.source, source.index, unit.start_offset + left,
                                  unit.start_offset + right, text)
                if any(start <= span.start < end for start, end in intervals):
                    continue
                if _NONROLE.search(text):
                    continue
                years = stated_years(text, requirement_line=unit.aspect in {"minimum", "preferred"})
                if years:
                    feature, modality = _year_feature(text, unit.aspect)
                    alternatives = _alternative_routes(text, tuple(years))
                    evidence[feature].append(FeatureEvidence(feature, tuple(years), modality, alternatives, span))
                if not _role_clause(text, unit.aspect):
                    heading = _ownership_heading(source, span.start)
                    if unit.aspect == "responsibility" and heading and _nominal_architecture(text):
                        evidence["architecture"].append(FeatureEvidence(
                            "architecture", "stated", "responsibility", False, span, heading,
                        ))
                    continue
                for feature, rules in _SCOPE_RULES.items():
                    for value, pattern in rules:
                        if _scope_supported(feature, value, pattern, text):
                            evidence[feature].append(FeatureEvidence(feature, value, "responsibility", False, span))
                            break
    profile = ContextProfile(_source_hash(sources), CONTEXT_VERSION,
                             {key: tuple(entries) if entries else None for key, entries in evidence.items()}, tuple(routes))
    validate_context(profile, description, sections=sections)
    return profile


def validate_context(profile: ContextProfile, description: str | None, *, sections: list[dict] | None = None) -> None:
    """Reject evidence replayed against a different source or altered quote offsets."""
    sources = _sources(description, sections)
    if (profile.source_hash != _source_hash(sources) or set(profile.features) != set(FEATURES)
            or profile.version != CONTEXT_VERSION):
        raise ValueError("source fingerprint or feature schema mismatch")
    lookup = {(s.source, s.index): s for s in sources}
    routed = {(s.source, s.index): _experience_routes(s) for s in sources}
    if profile.experience_routes != tuple(route for routes, _ in routed.values() for route in routes):
        raise ValueError("experience route does not ground in source")
    units = {(s.source, s.index): segment_job(None, [{"key": s.key, "title": s.title, "content": s.content}])
             for s in sources}
    for key, entries in profile.features.items():
        for entry in entries or ():
            span = entry.span
            source = lookup.get((span.source, span.section_index))
            if any(start <= span.start < end for start, end in routed.get((span.source, span.section_index), ((), []))[1]):
                raise ValueError("route-specific evidence cannot become a universal feature")
            content = source.content if source else None
            if (content is None or not 0 <= span.start < span.end <= len(content)
                    or content[span.start:span.end] != span.quote or entry.feature != key):
                raise ValueError("evidence does not ground in source")
            unit = next((u for u in units[(span.source, span.section_index)]
                         if u.start_offset <= span.start < span.end <= u.end_offset), None)
            if unit is None or unit.aspect in _EXCLUDED_ASPECTS or _negated_years(span.quote):
                raise ValueError("evidence does not ground in a source unit")
            if not any(span.start == unit.start_offset + left and span.end == unit.start_offset + right
                       for left, right in _fragments(unit.text)):
                raise ValueError("evidence omits part of its source clause")
            if key.endswith("years"):
                feature, modality = _year_feature(span.quote, unit.aspect)
                if key != feature or entry.modality != modality or _NONROLE.search(span.quote):
                    raise ValueError("years modality does not ground in source")
                years = tuple(stated_years(span.quote, requirement_line=key != "unspecified_years"))
                if (entry.value != years or entry.alternatives != _alternative_routes(span.quote, years)
                        or entry.context is not None):
                    raise ValueError("years do not ground in source")
            elif entry.context is not None:
                if (key != "architecture" or entry.value != "stated" or entry.modality != "responsibility"
                        or entry.alternatives or unit.aspect != "responsibility" or source is None
                        or not _nominal_architecture(span.quote)
                        or _ownership_heading(source, span.start) != entry.context):
                    raise ValueError("scope context does not ground in source")
            elif (not _role_clause(span.quote, unit.aspect) or entry.modality != "responsibility"
                  or entry.alternatives
                  or not any(entry.value == value and _scope_supported(key, value, pattern, span.quote)
                             for value, pattern in _SCOPE_RULES[key])):
                raise ValueError("scope does not ground in source")
