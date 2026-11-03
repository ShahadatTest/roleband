"""Amazon detail parser: three-field payload with deterministic US pay bands.

Amazon's pay transparency text may be in `description`, `basic_qualifications`,
or `preferred_qualifications`. It uses either the geographic-market form
(`$X/year ... $Y/year`) or a location-led unsigned annual USD form. Both become
source facts without waiting for local AI.
"""

from __future__ import annotations

import re

from tracker.connectors.detail.base import (
    DetailParseResult,
    HtmlDetailConnector,
    clean_section,
    pay_section,
    source_disclosed_comp_from_text,
    with_scanned_pay,
)
from tracker.platform.util import html_to_text
from tracker.schema import JobDescriptionSection, SourceDisclosedComp

# "The base pay for this position ranges from $70,000/year in our lowest geographic
# market up to $78,000/year in our highest geographic market." The two amounts are
# separated by filler, so match across it non-greedily and require the /year unit
# (hourly roles are not L6+ base salaries we want to promote as an annual band).
_BASE_PAY_RE = re.compile(
    r"base pay for this position ranges from\s*\$(?P<low>[\d,]+)(?:\.\d+)?\s*/\s*year"
    r".*?up to\s*\$(?P<high>[\d,]+)(?:\.\d+)?\s*/\s*year",
    re.IGNORECASE | re.DOTALL,
)
# Some postings declare the base-salary range, then show an unsigned decimal
# annual USD band on a location line. Declaration + annual USD are mandatory so
# unrelated numeric ranges cannot be promoted as pay.
_LISTED_SALARY_RE = re.compile(
    r"(?P<snippet>\bthe\s+base\s+salary\s+range\s+for\s+(?:this|the)\s+position\s+"
    r"is\s+listed\s+below\."
    r".{0,3000}?"
    r"(?P<market>(?:^|\n)\s*(?:USA,\s*)?[A-Z]{2},\s*[^\n-]+?\s+-\s*"
    r"\$?(?P<low>[\d,]+)(?:\.\d+)?\s*-\s*\$?(?P<high>[\d,]+)(?:\.\d+)?\s+"
    r"USD\s+annually\b))",
    re.IGNORECASE | re.DOTALL | re.MULTILINE,
)
# The full compensation paragraph, kept as the pay section body. Amazon opens it
# with the geographic-market sentence and closes near the equity/benefits tail.
_PAY_BLOCK_RE = re.compile(
    r"(?:Our compensation reflects|The base pay for this position ranges).*?"
    r"(?:total compensation company\.[^\n]*|equity[^\n]*|benefits[^\n]*)",
    re.IGNORECASE | re.DOTALL,
)

_FIELDS = (
    ("description", "job_description", "Job description"),
    ("basic_qualifications", "basic_qualifications", "Basic Qualifications"),
    ("preferred_qualifications", "preferred_qualifications", "Preferred Qualifications"),
)


class AmazonDetailConnector(HtmlDetailConnector):
    source = "amazon"
    pay_from_text = True

    def parse_payload(
        self, payload: object, raw_html: str | None = None
    ) -> DetailParseResult:
        if not isinstance(payload, dict):
            return self._from_html(raw_html)

        sections: list[JobDescriptionSection] = []
        for field, key, title in _FIELDS:
            section = clean_section(key, title, html_to_text(payload.get(field)))
            if section:
                sections.append(section)
        if not sections:
            return self._from_html(raw_html)

        # Amazon can append transparency text to any source field. Search all
        # fields in source order; promotion removes the exact matched block from
        # the section where it appeared.
        full_text = "\n\n".join(section.content for section in sections)
        return with_scanned_pay(sections, full_text, self._pay)

    def _from_html(self, raw_html: str | None) -> DetailParseResult:
        return with_scanned_pay(
            super().parse_html(raw_html).sections, html_to_text(raw_html) or "", self._pay
        )

    def _pay(
        self, full_text: str
    ) -> tuple[JobDescriptionSection | None, SourceDisclosedComp | None]:
        listed_match = _LISTED_SALARY_RE.search(full_text)
        block = listed_match or _PAY_BLOCK_RE.search(full_text)
        pay_text = block.group(0).strip() if block else None
        section = pay_section(pay_text) if pay_text else None

        match = _BASE_PAY_RE.search(full_text)
        if match is not None:
            low = int(match.group("low").replace(",", ""))
            high = int(match.group("high").replace(",", ""))
            low, high = sorted((low, high))
            source_comp: SourceDisclosedComp | None = SourceDisclosedComp(
                base_min=low,
                base_max=high,
                currency="USD",
                pay_basis="base",  # Amazon states "base pay ... ranges"
                pay_period="year",
                source_snippet=(match.group(0)[:240]),
                confidence="high",
            )
        elif listed_match is not None:
            low = int(listed_match.group("low").replace(",", ""))
            high = int(listed_match.group("high").replace(",", ""))
            low, high = sorted((low, high))
            source_comp = SourceDisclosedComp(
                base_min=low,
                base_max=high,
                currency="USD",
                pay_basis="base",
                pay_period="year",
                source_snippet=listed_match.group("market").strip()[:240],
                confidence="high",
            )
        else:
            # Fall back to the shared grounded scanner for any adjacent "$X - $Y"
            # phrasing Amazon may use elsewhere; None when no band is stated.
            source_comp = source_disclosed_comp_from_text(pay_text, full_text)
        return section, source_comp
