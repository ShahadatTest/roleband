"""Eightfold's job HTML, read the same way for every tenant."""

from __future__ import annotations

import html
import re

from tracker.connectors.detail.base import (
    PAY_RANGE_RE,
    DetailParseResult,
    HtmlDetailConnector,
    scan_pay,
    with_scanned_pay,
)
from tracker.platform.util import html_to_text
from tracker.schema import JobDescriptionSection, SourceDisclosedComp

_BOLD_HEADING_RE = re.compile(
    r"<p\b[^>]*>\s*(?:<(?:b|strong)\b[^>]*>\s*)+"
    r"(?P<title>[^<]{1,120}?)(?:\s*</(?:b|strong)>)+\s*</p\s*>",
    re.IGNORECASE | re.DOTALL,
)


def one_band(full_text: str) -> tuple[JobDescriptionSection | None, SourceDisclosedComp | None]:
    """The shared scanner's band, only when the posting prints one range.

    A tenant that prints one range per place (PayPal names a city before each)
    is left to the text pass, which picks the band for the posting's place;
    this reader knows no place and would take the first range."""
    if len({match.group(0) for match in PAY_RANGE_RE.finditer(full_text)}) > 1:
        return None, None
    return scan_pay(full_text)


class EightfoldDetailConnector(HtmlDetailConnector):
    """Each tenant words its own pay statement, so pay is found by the shared
    scanner, never by one employer's phrasing. A company whose own wording is
    worth checking gets a subclass in `DETAIL_CONNECTORS` (`netflix.py`)."""

    source = "eightfold"
    pay_from_text = True

    def parse_payload(
        self, payload: object, raw_html: str | None = None
    ) -> DetailParseResult:
        if isinstance(payload, dict):
            # v2 says `job_description`; PCSX (paypal, qualcomm) `jobDescription`.
            description = payload.get("job_description") or payload.get("jobDescription")
            if isinstance(description, str):
                return self.parse_html(description)
        return self.html_failover(raw_html, "Eightfold detail payload missing job_description")

    def parse_html(self, raw: str | None) -> DetailParseResult:
        if not raw:
            return DetailParseResult([])
        decoded = html.unescape(raw)
        marked = _BOLD_HEADING_RE.sub(
            lambda match: f"<h2>{match.group('title').strip()}</h2>", decoded
        )
        sections = super().parse_html(marked).sections
        return self.read_pay(decoded, sections, html_to_text(decoded) or "")

    def read_pay(
        self, decoded: str, sections: list[JobDescriptionSection], full_text: str
    ) -> DetailParseResult:
        return with_scanned_pay(sections, full_text, one_band)

    @staticmethod
    def has_bold_headings(decoded: str) -> bool:
        return bool(_BOLD_HEADING_RE.search(decoded))
