"""Provider-neutral structured job-detail parsing.

Transport adapters fetch source payloads. Detail connectors turn those payloads
into ordered, display-safe sections. A connector may use a strict source schema
first and a lossy failover parser second; failover must be surfaced as drift.
"""

from __future__ import annotations

import html
import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass

from tracker.platform.util import html_to_text
from tracker.schema import JobDescriptionSection, SourceDisclosedComp

#: The key of the section that holds a posting's pay statement. Readers find
#: pay by it: the model pay pass reads this section in place of the whole text
#: (`intelligence_runtime.disclosed_comp.pay_input_text`), and the dashboard
#: styles it (`.jd-section-pay_and_benefits`). A connector names its pay
#: section with `pay_section`, never with a key of its own.
PAY_SECTION_KEY = "pay_and_benefits"

_HEADING_RE = re.compile(r"<h([1-6])\b[^>]*>(.*?)</h\1\s*>", re.IGNORECASE | re.DOTALL)
_MARKER = "__ROLEBAND_SECTION__"
_KEY_RE = re.compile(r"[^a-z0-9]+")
# section_key is a descriptive identifier stored in ``String(64)`` columns
# (``job_skill_evidence.section_key`` / ``job_skill.section_key``). A long source
# heading slugifies past 64 chars and would overflow the column, failing the
# whole persist. Clamp at the producer; the key has no unique constraint, so
# truncating a rare long heading is harmless.
_MAX_KEY_LEN = 64
# Separators must stay in step with `intelligence.schema._EXPLICIT_BAND_RE`,
# which is what actually parses the bounds. This one only *gates* whether a
# block is treated as a pay disclosure, so a stricter gate silently discards
# bands the extractor could read, such as en and em dash ranges ("$184,049–262,928").
PAY_RANGE_RE = re.compile(
    r"(?:[$£€]\s*\d[\d,]*(?:\.\d+)?\s*[kKmM]?\s*"
    r"(?:[-–—]|to\b|and\b)\s*[$£€]?\s*\d[\d,]*(?:\.\d+)?\s*[kKmM]?"
    r"|\d[\d,]*(?:\.\d+)?\s*[kKmM]?\s*(?:[-–—]|to\b|and\b)\s*"
    r"\d[\d,]*(?:\.\d+)?\s*[kKmM]?\s+(?:USD|GBP|EUR|CAD|AUD|SGD)\b)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class DetailParseResult:
    sections: list[JobDescriptionSection]
    mode: str = "primary"  # primary | failover
    reason: str | None = None
    complete: bool = True
    source_disclosed_comp: SourceDisclosedComp | None = None


def section_key(title: str) -> str:
    key = _KEY_RE.sub("_", title.lower()).strip("_") or "job_description"
    key = PAY_SECTION_KEY if key == "pay_benefits" else key
    # Trim to the column width, then drop any underscore left dangling by the cut.
    return key[:_MAX_KEY_LEN].rstrip("_") if len(key) > _MAX_KEY_LEN else key


def clean_section(key: str, title: str, content: object) -> JobDescriptionSection | None:
    text = html_to_text(str(content)) if content is not None else None
    if not text:
        return None
    return JobDescriptionSection(key=key, title=title.strip(), content=text)


def pay_section(content: object, title: str = "Compensation") -> JobDescriptionSection | None:
    """The posting's pay statement as its own section, under `PAY_SECTION_KEY`."""
    return clean_section(PAY_SECTION_KEY, title, content)


def sections_to_text(sections: list[JobDescriptionSection]) -> str | None:
    parts = [f"{section.title}\n{section.content}" for section in sections if section.content]
    return "\n\n".join(parts).strip() or None


def sections_to_html(sections: list[JobDescriptionSection]) -> str | None:
    """Build safe storage HTML; the dashboard still renders section text as text."""
    parts = []
    for section in sections:
        title = html.escape(section.title)
        content = html.escape(section.content).replace("\n", "<br>")
        parts.append(f"<section><h2>{title}</h2><p>{content}</p></section>")
    return "\n".join(parts) or None


def source_disclosed_comp_from_text(
    pay_text: str | None,
    full_text: str | None = None,
) -> SourceDisclosedComp | None:
    """Promote a connector-isolated pay range into a persisted source fact.

    The local model remains fallback for unstructured/ambiguous text. Connectors
    call this only after they have isolated the source's own pay section.
    """
    if not pay_text:
        return None
    from tracker.pay_disclosure import extract_grounded_band

    dc = extract_grounded_band(pay_text, full_text or pay_text)
    if not dc.disclosed:
        return None
    return SourceDisclosedComp(
        base_min=dc.base_min,
        base_max=dc.base_max,
        currency=dc.currency or "USD",
        pay_basis=dc.pay_basis.value,
        pay_period=dc.pay_period.value,
        source_snippet=dc.source_snippet,
        confidence=dc.confidence,
        bonus_pct=dc.bonus_pct,
    )


# A promoted pay quote is a padded slice of the source, not a sentence: the scanner
# keeps `_QUOTE_PAD` characters either side of the numbers, so it routinely starts and
# ends mid-word. Cutting exactly that slice out of the body would sever the sentence at
# both ends ("The typical bas|e pay range for this role ... is USD $155,800 - $277,200|"
# leaves "base" in one section and the band in another), and since `description_text`
# is rebuilt from the sections, the intact sentence would exist nowhere and `pay_basis`
# could not be read from it.
#
# So each edge of the carve moves out to the nearest sentence boundary. Only that far:
# growing to the whole paragraph empties body sections that have no blank line into
# Compensation, because such a section is one "paragraph".
_PART_SEP = "\n\n"
_SENTENCE_END_RE = re.compile(r"[.!?;:]\s|\n")
# ...and not even that far when the nearest boundary is a screen away: a run-on block
# is not one sentence, so the exact quote is carved.
_CARVE_PAD_MAX = 300
_BLANK_RUN_RE = re.compile(r"\n{3,}")


def _find_part(text: str, part: str) -> tuple[int, int] | None:
    """Where `part` sits in `text`, or None.

    The scanner's quote (`pay_disclosure.find_pay_span`) folds every run of
    whitespace into one space, while a section keeps the line breaks the source
    put inside its pay statement ("is:\n\n$186,000.00 - $317,000.00 a year"). An
    exact match alone would miss that statement and leave it in the body as
    well as in the new section, so a miss is retried with any whitespace run
    matching any other."""
    start = text.find(part)
    if start != -1:
        return start, start + len(part)
    words = part.split()
    if not words:
        return None
    match = re.search(r"\s+".join(map(re.escape, words)), text)
    return (match.start(), match.end()) if match else None


def _carve_bounds(text: str, start: int, end: int) -> tuple[int, int]:
    """Grow `[start, end)` to the sentence containing it, or leave the edge alone.

    A quote that opens on the previous sentence's full stop (". Pay range ...")
    starts after it: the stop belongs to the body."""
    left = start
    for match in _SENTENCE_END_RE.finditer(text, max(0, start - _CARVE_PAD_MAX), start + 2):
        left = match.end()
    right = end
    limit = min(len(text), end + _CARVE_PAD_MAX)
    match = _SENTENCE_END_RE.search(text, end, limit)
    if match is not None:
        right = match.end()
    elif limit == len(text) and text[end:].strip("\n .") == "":
        right = len(text)
    return left, right


def promote_section(
    sections: list[JobDescriptionSection], promoted: JobDescriptionSection
) -> list[JobDescriptionSection]:
    """Move source text into its own section without duplicating it.

    What moves is the whole block the quote sits in, so neither the body nor the new
    section is left holding half a sentence. The promoted section therefore carries the
    text as the source wrote it, which is what `pay_basis` derivation reads.
    """
    result = list(sections)
    insert_at = len(result)
    for index, section in enumerate(result):
        remaining = section.content
        pieces: list[str] = []
        carved = False
        for part in promoted.content.split(_PART_SEP):
            if not part:
                continue
            found = _find_part(remaining, part)
            if found is None:
                # A promoted block can span two source fields (a declaration in
                # one and the market line in another), and only the first
                # section that matches is carved. A part that is not in THIS one is
                # kept exactly as the connector wrote it — dropping it would lose
                # the half of the pay statement the carve never reached.
                pieces.append(part)
                continue
            lo, hi = _carve_bounds(remaining, *found)
            pieces.append(remaining[lo:hi].strip())
            remaining = remaining[:lo] + remaining[hi:]
            carved = True
        if not carved:
            continue
        promoted = JobDescriptionSection(
            promoted.key, promoted.title, _PART_SEP.join(p for p in pieces if p)
        )
        remaining = _BLANK_RUN_RE.sub(_PART_SEP, remaining).strip()
        insert_at = index + 1
        if remaining:
            result[index] = JobDescriptionSection(section.key, section.title, remaining)
        else:
            result.pop(index)
            insert_at = index
        break
    if not any(s.key == promoted.key and s.content == promoted.content for s in result):
        result.insert(insert_at, promoted)
    return result


#: Reads a posting's full text for its pay statement: the section to carve out
#: of the body, and the band it states. Either may be None.
PayReader = Callable[[str], tuple[JobDescriptionSection | None, SourceDisclosedComp | None]]


def scan_pay(full_text: str) -> tuple[JobDescriptionSection | None, SourceDisclosedComp | None]:
    """The band the shared scanner finds in a posting's full text, with its
    quote as the pay section. For a source that prints pay in its prose
    without isolating it."""
    comp = source_disclosed_comp_from_text(full_text, full_text)
    if comp is None or not comp.source_snippet:
        return None, None
    return pay_section(comp.source_snippet), comp


def with_scanned_pay(
    sections: list[JobDescriptionSection], full_text: str, read: PayReader = scan_pay
) -> DetailParseResult:
    """`sections` with the pay statement `read` finds in `full_text` carved
    into its own section, and the band it states."""
    pay, comp = read(full_text)
    if pay is not None:
        sections = promote_section(sections, pay)
    return DetailParseResult(sections, source_disclosed_comp=comp)


def with_pay_block(
    sections: list[JobDescriptionSection], block: JobDescriptionSection
) -> DetailParseResult:
    """`sections` closed by the pay block the source isolates itself, and the
    band that block states. Only an isolated block licenses reading a band from
    text this way; the rest of the posting grounds it."""
    sections = [*sections, block]
    return DetailParseResult(
        sections,
        source_disclosed_comp=source_disclosed_comp_from_text(
            block.content, sections_to_text(sections) or block.content
        ),
    )


def pay_unread(sections: list[JobDescriptionSection], reason: str) -> DetailParseResult:
    """A read that holds the posting's whole text but could not isolate the pay
    the source says it prints.

    Complete, because the text is: it is stored and stamped fresh, so the
    posting is not fetched again on every scan, and an employer's later edit
    still lands. A read marked incomplete keeps the held text and its old
    stamp, which turns one unrecognised pay block into a refetch every scan
    that never stores anything. Failover, so `pay_looked` stays False and no
    stored band is cleared; the text pass reads the band from the stored text.
    A read that recovered no text is never complete."""
    return DetailParseResult(sections, mode="failover", reason=reason, complete=bool(sections))


def parse_row(
    row: Mapping[str, object],
    fields: Iterable[tuple[str, str, str]],
    *,
    pay_field: str,
    pay_title: str,
) -> DetailParseResult:
    """A listing row already split into fields: one section per
    `(field, key, title)` that holds text, in table order, then the row's
    isolated pay field as the pay section. A row with no text is not a
    complete read."""
    sections: list[JobDescriptionSection] = []
    for field, key, title in fields:
        value = row.get(field)
        if isinstance(value, str) and value.strip():
            section = clean_section(key, title, value)
            if section:
                sections.append(section)
    pay = row.get(pay_field)
    block = pay_section(pay, pay_title) if isinstance(pay, str) and pay.strip() else None
    if block is None:
        return DetailParseResult(sections, complete=bool(sections))
    return with_pay_block(sections, block)


class HtmlDetailConnector:
    """Baseline add-on for sources whose detail is already HTML/plain text."""

    source = "html"
    #: This connector finds pay by scanning the posting's own text where the
    #: source prints it (`source_disclosed_comp_from_text`). So a primary,
    #: complete read with text that found none says the posting states none,
    #: and the band it wrote may be cleared. A connector that reads a
    #: structured salary field leaves this False: an absent field is not a
    #: withdrawn band.
    pay_from_text = False

    def parse_payload(
        self, payload: object, raw_html: str | None = None
    ) -> DetailParseResult:
        return self.parse_html(raw_html)

    def html_failover(self, raw_html: str | None, reason: str) -> DetailParseResult:
        """The payload is not the shape this connector reads: the HTML the
        posting already holds, read by this connector's HTML parser and
        surfaced as failover. As complete as that read, and never complete
        when it found no text: an empty read does not show the posting has
        none."""
        result = self.parse_html(raw_html)
        return DetailParseResult(
            result.sections,
            mode="failover",
            reason=reason,
            complete=result.complete and bool(result.sections),
        )

    def parse_html(self, raw: str | None) -> DetailParseResult:
        if not raw:
            return DetailParseResult([])

        decoded = html.unescape(raw)

        def mark_heading(match: re.Match[str]) -> str:
            title = html_to_text(match.group(2)) or "Job description"
            return f"\n\n{_MARKER}{title}\n\n"

        marked = _HEADING_RE.sub(mark_heading, decoded)
        text = html_to_text(marked)
        if not text:
            return DetailParseResult([])
        if _MARKER not in text:
            section = clean_section("job_description", "Job description", text)
            return DetailParseResult([section] if section else [])

        sections: list[JobDescriptionSection] = []
        preamble, *chunks = text.split(_MARKER)
        if preamble.strip():
            section = clean_section("job_description", "Job description", preamble)
            if section:
                sections.append(section)
        for chunk in chunks:
            title, separator, content = chunk.partition("\n")
            if not separator:
                continue
            section = clean_section(section_key(title), title, content)
            if section:
                sections.append(section)
        return DetailParseResult(sections)
