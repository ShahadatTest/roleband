"""OpenAI company detail add-on over the Ashby source contract."""

from collections.abc import Mapping

from tracker.connectors.detail.ashby import (
    AshbyDetailConnector,
    _formatted_salary,
    _source_disclosed_comp_from_salary,
)
from tracker.connectors.detail.base import (
    DetailParseResult,
    pay_section,
    pay_unread,
    promote_section,
)


def _has_equity(compensation: Mapping) -> bool:
    tier_summary = compensation.get("compensationTierSummary")
    if isinstance(tier_summary, str) and "equity" in tier_summary.lower():
        return True
    for component in compensation.get("summaryComponents") or []:
        if not isinstance(component, Mapping):
            continue
        comp_type = str(component.get("compensationType") or "").lower()
        summary = str(component.get("summary") or "")
        if "equity" in comp_type or "equity" in summary.lower():
            return True
    return False


def _openai_compensation_text(compensation: Mapping) -> str | None:
    salary = _formatted_salary(compensation, label="Base salary range")
    if not salary:
        return None
    lines = [salary]
    if _has_equity(compensation):
        lines.append("Equity: Offers equity.")
    return "\n".join(lines)


class OpenAIDetailConnector(AshbyDetailConnector):
    source = "openai"

    def parse_payload(
        self, payload: object, raw_html: str | None = None
    ) -> DetailParseResult:
        if not isinstance(payload, Mapping):
            return super().parse_payload(payload, raw_html)

        description = payload.get("descriptionHtml")
        result = self.parse_html(description if isinstance(description, str) else raw_html)
        compensation = payload.get("compensation")
        if isinstance(compensation, Mapping):
            pay_text = _openai_compensation_text(compensation)
            if pay_text:
                pay = pay_section(pay_text)
                sections = promote_section(result.sections, pay) if pay else result.sections
                return DetailParseResult(
                    sections,
                    source_disclosed_comp=_source_disclosed_comp_from_salary(compensation, pay_text),
                )

        display = payload.get("shouldDisplayCompensationOnJobPostings")
        if display is True:
            return pay_unread(
                result.sections, "OpenAI compensation display flag set but salary object missing"
            )
        return result
