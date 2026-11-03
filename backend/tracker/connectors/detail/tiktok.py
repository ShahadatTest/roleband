"""TikTok detail parser: the listing row is already decomposed.

The search API's row carries `description` (the role) and `requirement`
(qualifications) as plain text. The band is not in the row: `job_post_info`'s
salary fields are null, and the posting page states it
under "Compensation Description". The listing adapter's hydrate isolates that
block into `pay`, and only `pay` licenses `source_disclosed_comp_from_text`.
"""

from __future__ import annotations

from collections.abc import Mapping

from tracker.connectors.detail.base import DetailParseResult, HtmlDetailConnector, parse_row

_SECTIONS = (
    ("description", "responsibilities", "Responsibilities"),
    ("requirement", "qualifications", "Qualifications"),
)


class TikTokDetailConnector(HtmlDetailConnector):
    source = "tiktok"
    pay_from_text = True

    def parse_payload(self, payload: object, raw_html: str | None = None) -> DetailParseResult:
        if not isinstance(payload, Mapping):
            return self.html_failover(raw_html, "TikTok listing row is not an object")
        return parse_row(payload, _SECTIONS, pay_field="pay", pay_title="Compensation")
