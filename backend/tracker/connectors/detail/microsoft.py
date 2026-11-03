"""Microsoft (Eightfold PCSX) detail parser.

`position_details.jobDescription` is one HTML blob whose section headers are bold
runs (`<b>Overview</b>`, `<b>Responsibilities</b>`, `<b>Qualifications</b>`)
rather than heading tags, so we promote those known headers to <h2> and reuse the
shared heading splitter. US roles disclose a base-pay range in the text ("The
typical base pay range for this role across the U.S. is USD $130,900 - $251,900
per year") -> grounded into a SourceDisclosedComp + a Compensation section.
"""

from __future__ import annotations

import re

from tracker.connectors.detail.base import (
    DetailParseResult,
    HtmlDetailConnector,
    with_scanned_pay,
)
from tracker.platform.util import html_to_text

# The bold runs Microsoft uses as top-level section headers (not inline emphasis,
# which is <strong>). Promote just these to <h2> so the shared splitter sees them.
_SECTION_HEADERS = (
    "Overview",
    "Responsibilities",
    "Qualifications",
    "Minimum Qualifications",
    "Preferred Qualifications",
)
_HEADER_RE = re.compile(
    r"<b>\s*(" + "|".join(re.escape(h) for h in _SECTION_HEADERS) + r")\s*</b>",
    re.IGNORECASE,
)


class MicrosoftDetailConnector(HtmlDetailConnector):
    source = "microsoft"
    pay_from_text = True

    def parse_html(self, raw: str | None) -> DetailParseResult:
        if not raw:
            return DetailParseResult([])
        promoted = _HEADER_RE.sub(lambda m: f"<h2>{m.group(1)}</h2>", raw)
        return with_scanned_pay(super().parse_html(promoted).sections, html_to_text(raw) or "")
