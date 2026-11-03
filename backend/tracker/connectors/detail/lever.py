"""Lever detail parser: structured `lists` sections plus the closing block.

Lever hands us the posting already decomposed, so this connector does not have
to infer structure from headings the way the shared HTML parser does:

    description  -> intro prose
    lists[]      -> {text: "Who You Are", content: "<li>..</li>"} per section
    additional   -> the closing block

`additional` is where Lever tenants put the pay-transparency sentence, never
`description`. That makes it an isolated block in the Greenhouse `.content-pay-transparency` sense, which is
what licenses calling `source_disclosed_comp_from_text` on it. The block is only
labelled pay-and-benefits when a range is actually present; otherwise it is the
EEO/benefits boilerplate it usually is, and mislabelling it would poison the
disclosure metrics.
"""

from __future__ import annotations

from collections.abc import Mapping

from tracker.connectors.detail.base import (
    PAY_RANGE_RE,
    DetailParseResult,
    HtmlDetailConnector,
    clean_section,
    pay_section,
    section_key,
    with_pay_block,
)
from tracker.schema import JobDescriptionSection


class LeverDetailConnector(HtmlDetailConnector):
    source = "lever"
    pay_from_text = True

    def parse_payload(
        self, payload: object, raw_html: str | None = None
    ) -> DetailParseResult:
        if not isinstance(payload, Mapping):
            return self.html_failover(raw_html, "Lever detail payload is not an object")

        description = payload.get("description")
        html = description if isinstance(description, str) else raw_html
        sections: list[JobDescriptionSection] = list(self.parse_html(html).sections)

        raw_lists = payload.get("lists")
        if raw_lists is not None and not isinstance(raw_lists, list):
            return DetailParseResult(
                sections,
                mode="failover",
                reason="Lever 'lists' is present but not an array",
                complete=False,
            )
        for entry in raw_lists or []:
            if not isinstance(entry, Mapping):
                continue
            title = str(entry.get("text") or "").strip()
            content = entry.get("content")
            if not title or not content:
                continue
            section = clean_section(section_key(title), title, content)
            if section:
                sections.append(section)

        additional = payload.get("additional")
        if not isinstance(additional, str) or not additional.strip():
            return DetailParseResult(sections)

        # Label by what the block actually contains. A pay range makes it the
        # pay section (and a grounded extraction target); without one it is the
        # closing boilerplate and must not be counted as a disclosure.
        probe = pay_section(additional, "Pay and benefits")
        if probe is None:
            return DetailParseResult(sections)
        if not PAY_RANGE_RE.search(probe.content):
            closing = JobDescriptionSection(
                key="additional_information",
                title="Additional information",
                content=probe.content,
            )
            return DetailParseResult([*sections, closing])
        return with_pay_block(sections, probe)
