"""Workday detail parser — one HTML description blob, optional pay disclosure.

Workday's CXS detail returns the whole posting as a single `jobDescription` HTML
string (headings inline), so section splitting reuses the shared HTML parser. US
postings often append a pay-transparency line ("The base salary range for
this role is $X - $Y"); we promote it to a Compensation section and ground a
source-disclosed band with the shared scanner. Keyed by source ("workday") so
every Workday tenant reuses it without a per-company entry.
"""

from __future__ import annotations

from tracker.connectors.detail.base import (
    DetailParseResult,
    HtmlDetailConnector,
    with_scanned_pay,
)
from tracker.platform.util import html_to_text


class WorkdayDetailConnector(HtmlDetailConnector):
    source = "workday"
    pay_from_text = True

    def parse_payload(
        self, payload: object, raw_html: str | None = None
    ) -> DetailParseResult:
        html_body = raw_html
        if isinstance(payload, dict):
            html_body = payload.get("jobDescription") or raw_html
        if not html_body:
            # The listing's payload only points at the detail. A scan that did
            # not read it (the description is still fresh) or failed to has no
            # description, and must not report one complete: persistence would
            # overwrite the stored description and date with nothing.
            return DetailParseResult([], complete=False)
        return self._from_html(html_body)

    def parse_html(self, raw: str | None) -> DetailParseResult:
        return self._from_html(raw)

    def _from_html(self, raw_html: str | None) -> DetailParseResult:
        return with_scanned_pay(super().parse_html(raw_html).sections, html_to_text(raw_html) or "")
