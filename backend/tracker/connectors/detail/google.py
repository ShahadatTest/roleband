"""Google detail parser for careers sections flattened by SSR hydration."""

from __future__ import annotations

import html
import re

from tracker.connectors.detail.base import (
    PAY_RANGE_RE,
    DetailParseResult,
    HtmlDetailConnector,
    clean_section,
    pay_section,
    pay_unread,
    promote_section,
    section_key,
    source_disclosed_comp_from_text,
)
from tracker.platform.util import html_to_text
from tracker.schema import JobDescriptionSection

_HEADINGS = (
    "About the job",
    "Minimum qualifications",
    "Preferred qualifications",
    "Responsibilities",
)
_HEADINGS_RE = re.compile(
    "(" + "|".join(re.escape(heading) for heading in _HEADINGS) + r"):?",
    re.IGNORECASE,
)
# Google's own markup runs the team blurb straight into its pay boilerplate
# ("...collective effort.Individual pay is determined by..."), with no tag or
# space between. Left joined, the pay carve grows back to the previous
# sentence boundary and takes the blurb's last sentence into Pay & Benefits.
# Anchored on the boilerplate opener only: a general "space after a period
# before a capital" rule would split "Node.js"-style names and abbreviations.
_PAY_SEAM_RE = re.compile(r"(?<=[.!?])(?=Individual pay is determined\b)")


class GoogleDetailConnector(HtmlDetailConnector):
    source = "google"
    pay_from_text = True

    def parse_html(self, raw: str | None) -> DetailParseResult:
        if not raw:
            return DetailParseResult([])
        decoded = html.unescape(raw)
        generic = super().parse_html(decoded)
        text = _PAY_SEAM_RE.sub("\n\n", html_to_text(decoded) or "")
        matches = list(_HEADINGS_RE.finditer(text))
        if matches:
            sections: list[JobDescriptionSection] = []
            preamble = text[: matches[0].start()].strip()
            if preamble:
                section = clean_section("job_description", "Job description", preamble)
                if section:
                    sections.append(section)
            for index, match in enumerate(matches):
                title = next(
                    heading for heading in _HEADINGS if heading.lower() == match.group(1).lower()
                )
                end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
                section = clean_section(section_key(title), title, text[match.end() : end])
                if section:
                    sections.append(section)
        else:
            sections = generic.sections

        pay_section = self._pay_section(sections)
        source_comp = None
        if pay_section:
            sections = promote_section(sections, pay_section)
            source_comp = source_disclosed_comp_from_text(pay_section.content, text)
        if not matches and len(generic.sections) <= 1:
            return DetailParseResult(
                sections,
                mode="failover",
                reason="Google known section headings missing",
            )
        if PAY_RANGE_RE.search(text) and not pay_section:
            return pay_unread(sections, "Google compensation text could not be isolated")
        return DetailParseResult(sections, source_disclosed_comp=source_comp)

    def _pay_section(
        self, sections: list[JobDescriptionSection]
    ) -> JobDescriptionSection | None:
        for section in sections:
            match = PAY_RANGE_RE.search(section.content)
            if not match:
                continue
            lowered = section.content.lower()
            starts = [
                lowered.rfind("individual pay", 0, match.start()),
                lowered.rfind("base salary range", 0, match.start()),
                lowered.rfind("salary range", 0, match.start()),
            ]
            start = max(starts)
            if start < 0:
                start = max(0, match.start() - 160)
            content = section.content[start:].strip()
            return pay_section(content, "Pay & Benefits")
        return None
