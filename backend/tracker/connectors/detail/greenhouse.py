"""Greenhouse detail parser with pay-transparency block awareness."""

from __future__ import annotations

import html

from selectolax.lexbor import LexborHTMLParser as HTMLParser

from tracker.connectors.detail.base import (
    DetailParseResult,
    HtmlDetailConnector,
    pay_section,
    pay_unread,
    promote_section,
    source_disclosed_comp_from_text,
)
from tracker.platform.util import html_to_text


class GreenhouseDetailConnector(HtmlDetailConnector):
    source = "greenhouse"
    pay_from_text = True

    def parse_html(self, raw: str | None) -> DetailParseResult:
        if not raw:
            return DetailParseResult([])
        decoded = html.unescape(raw)
        result = super().parse_html(decoded)
        node = HTMLParser(decoded).css_first(".content-pay-transparency")
        if node is None:
            if "content-pay-transparency" in decoded:
                return pay_unread(
                    result.sections, "Greenhouse pay-transparency block schema changed"
                )
            return result
        pay_text = html_to_text(node.html)
        pay = pay_section(pay_text)
        if not pay:
            return pay_unread(result.sections, "Greenhouse pay-transparency block was empty")
        return DetailParseResult(
            promote_section(result.sections, pay),
            source_disclosed_comp=source_disclosed_comp_from_text(
                pay.content, html_to_text(decoded) or pay.content
            ),
        )
