"""Atlassian detail parser: the listing row is already decomposed.

Each row of `www.atlassian.com/endpoint/careers/listings` carries its sections
as separate fields:

    overview          -> "Working at Atlassian" prose
    responsibilities  -> the role
    qualifications    -> requirements
    compensation      -> the pay-philosophy paragraph (never a number)
    payRanges         -> the ranges, per country or US pay zone

`payRanges` is the isolated pay block that licenses
`source_disclosed_comp_from_text` (the Greenhouse `.content-pay-transparency`
rule): a row that states a band carries it here ("In Canada ... base pay
range for new hires is: CA$94,500 - CA$123,375"), and `compensation` states no
figure, so it is kept as prose and never read for a band. `payRanges` is
therefore the posting's pay section (`PAY_SECTION_KEY`), the one the model pay
pass reads.
"""

from __future__ import annotations

from collections.abc import Mapping

from tracker.connectors.detail.base import DetailParseResult, HtmlDetailConnector, parse_row

#: (payload key, section key, title), in the order the careers page renders.
_SECTIONS = (
    ("overview", "about_company", "Working at Atlassian"),
    ("responsibilities", "responsibilities", "Responsibilities"),
    ("qualifications", "qualifications", "Qualifications"),
    ("compensation", "compensation", "Compensation"),
)


class AtlassianDetailConnector(HtmlDetailConnector):
    source = "atlassian"
    pay_from_text = True

    def parse_payload(self, payload: object, raw_html: str | None = None) -> DetailParseResult:
        if not isinstance(payload, Mapping):
            return self.html_failover(raw_html, "Atlassian listing row is not an object")
        return parse_row(payload, _SECTIONS, pay_field="payRanges", pay_title="Pay ranges")
