"""Netflix's Eightfold template: bold-paragraph headings and one pay paragraph."""

from __future__ import annotations

import re

from tracker.connectors.detail.base import (
    PAY_RANGE_RE,
    DetailParseResult,
    pay_section,
    pay_unread,
    promote_section,
    source_disclosed_comp_from_text,
)
from tracker.connectors.detail.eightfold import EightfoldDetailConnector
from tracker.platform.util import html_to_text
from tracker.schema import JobDescriptionSection

_PARAGRAPH_RE = re.compile(r"<p\b[^>]*>.*?</p\s*>", re.IGNORECASE | re.DOTALL)


class NetflixDetailConnector(EightfoldDetailConnector):
    """Reads pay from the paragraph Netflix's own wording opens, and notes
    drift when the posting prints a range outside it: for this one employer,
    that means the template moved. Other tenants never reach these rules."""

    def read_pay(
        self, decoded: str, sections: list[JobDescriptionSection], full_text: str
    ) -> DetailParseResult:
        had_headings = self.has_bold_headings(decoded) or len(sections) > 1
        paragraphs = [html_to_text(block) for block in _PARAGRAPH_RE.findall(decoded)]
        paragraphs = [paragraph for paragraph in paragraphs if paragraph]
        pay_parts: list[str] = []
        for index, paragraph in enumerate(paragraphs):
            lowered = paragraph.lower()
            if not PAY_RANGE_RE.search(paragraph):
                continue
            if "compensation structure" not in lowered and "range for this role" not in lowered:
                continue
            pay_parts.append(paragraph)
            if index + 1 < len(paragraphs) and "benefit" in paragraphs[index + 1].lower():
                pay_parts.append(paragraphs[index + 1])
            break
        if not pay_parts:
            lowered = full_text.lower()
            start = lowered.find("generally, our compensation structure")
            if start >= 0 and PAY_RANGE_RE.search(full_text[start:]):
                boundaries = [
                    lowered.find("netflix is a unique culture", start),
                    lowered.find("inclusion is a netflix value", start),
                ]
                end = min((boundary for boundary in boundaries if boundary >= 0), default=len(full_text))
                pay_parts.append(full_text[start:end].strip())

        source_comp = None
        if pay_parts:
            pay = pay_section("\n\n".join(pay_parts), "Compensation & Benefits")
            if pay:
                sections = promote_section(sections, pay)
                source_comp = source_disclosed_comp_from_text(pay.content, full_text)

        if not had_headings and not pay_parts:
            return DetailParseResult(
                sections,
                mode="failover",
                reason="Netflix bold paragraph headings missing",
            )
        if PAY_RANGE_RE.search(full_text) and not pay_parts:
            return pay_unread(sections, "Netflix compensation paragraph schema changed")
        return DetailParseResult(sections, source_disclosed_comp=source_comp)
