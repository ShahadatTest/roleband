"""Ashby detail parser: description HTML plus structured compensation."""

from __future__ import annotations

from collections.abc import Mapping

from tracker.connectors.detail.base import (
    DetailParseResult,
    HtmlDetailConnector,
    pay_section,
    pay_unread,
    promote_section,
)
from tracker.pay_period import PayPeriod, decide_period, size_classes
from tracker.schema import SourceDisclosedComp

#: The interval units a posting may state, and the ones we show.
_UNITS = ("YEAR", "MONTH", "WEEK", "DAY", "HOUR")
_SHOWN = {"YEAR": PayPeriod.year, "MONTH": PayPeriod.month, "HOUR": PayPeriod.hour}


def _interval(raw: object) -> tuple[int, str] | None:
    """Ashby's `interval` ("1 YEAR", "2 WEEK") as (count, unit), or None when
    it states none ("NONE", empty, or a shape we cannot read)."""
    words = str(raw or "").upper().split()
    if len(words) == 1:
        words = ["1", *words]
    if len(words) != 2 or not words[0].isdigit():
        return None
    unit = words[1].removesuffix("S")
    return (int(words[0]), unit) if unit in _UNITS else None


def _stated_period(raw: object) -> PayPeriod | None:
    """The period the board's interval states: the unit we show, `unclear` for
    one we do not (a day, a week, a count other than one), None for none.

    Only a missing interval lets the size decide alone. A stated interval
    is never treated as "no word": "1 DAY" at $600-800 or "2 WEEK" at
    $5,000-6,000 reads `unclear`, never a period guessed from the size.
    """
    interval = _interval(raw)
    if interval is None:
        return None if str(raw or "").strip().upper() in ("", "NONE") else PayPeriod.unclear
    count, unit = interval
    return _SHOWN.get(unit, PayPeriod.unclear) if count == 1 else PayPeriod.unclear


def _salary_component(compensation: Mapping) -> Mapping | None:
    components = compensation.get("summaryComponents")
    return next(
        (
            component
            for component in components or []
            if isinstance(component, Mapping)
            and str(component.get("compensationType") or "").lower() == "salary"
        ),
        None,
    )


def _formatted_salary(compensation: Mapping, *, label: str | None = None) -> str | None:
    summary = compensation.get("scrapeableCompensationSalarySummary")
    salary = _salary_component(compensation)
    if not isinstance(summary, str) or not summary.strip():
        if not isinstance(salary, Mapping):
            return None
        low, high = salary.get("minValue"), salary.get("maxValue")
        if not isinstance(low, (int, float)) or not isinstance(high, (int, float)):
            return None
        summary = f"${low:,.0f} - ${high:,.0f}"

    suffix: list[str] = []
    if isinstance(salary, Mapping):
        currency = salary.get("currencyCode")
        if isinstance(currency, str) and currency and currency not in summary:
            suffix.append(currency)
        # The unit the board states, so the stored quote says why a day rate
        # reads "could not tell": "per day", "per 2 weeks".
        interval = _interval(salary.get("interval"))
        if interval is not None:
            count, unit = interval
            suffix.extend(["per", unit.lower()] if count == 1 else ["per", str(count), f"{unit.lower()}s"])
    text = " ".join([summary.strip(), *suffix]).strip()
    return f"{label}: {text}" if label else text


def _source_disclosed_comp_from_salary(
    compensation: Mapping, pay_text: str
) -> SourceDisclosedComp | None:
    salary = _salary_component(compensation)
    if not isinstance(salary, Mapping):
        return None
    low, high = salary.get("minValue"), salary.get("maxValue")
    if not isinstance(low, (int, float)) and not isinstance(high, (int, float)):
        return None
    currency = salary.get("currencyCode")
    currency = currency if isinstance(currency, str) and currency else "USD"
    # The board's own interval is a word next to the amount; a structured pay
    # field is pay by definition, so its size alone may decide when it states
    # no interval. "1 YEAR" on $45 reads `unclear`; "NONE" on
    # $180,000 reads `year`; "1 DAY" on $600 reads `unclear`, never `hour`.
    decided = decide_period(
        size_classes(low if isinstance(low, (int, float)) else None,
                     high if isinstance(high, (int, float)) else None, currency),
        _stated_period(salary.get("interval")),
        structured=True,
    )
    if decided is None:
        return None
    pay_period = decided.value
    return SourceDisclosedComp(
        base_min=int(low) if isinstance(low, (int, float)) else None,
        base_max=int(high) if isinstance(high, (int, float)) else None,
        currency=currency,
        pay_basis="base",
        pay_period=pay_period,
        source_snippet=pay_text[:240],
        confidence="high",
    )


class AshbyDetailConnector(HtmlDetailConnector):
    source = "ashby"

    def parse_payload(
        self, payload: object, raw_html: str | None = None
    ) -> DetailParseResult:
        if not isinstance(payload, Mapping):
            return self.html_failover(raw_html, "Ashby detail payload is not an object")

        description = payload.get("descriptionHtml")
        html = description if isinstance(description, str) else raw_html
        result = self.parse_html(html)
        compensation = payload.get("compensation")
        display = payload.get("shouldDisplayCompensationOnJobPostings")
        expects_pay = display is True
        pay_text = _formatted_salary(compensation) if isinstance(compensation, Mapping) else None
        if pay_text:
            pay = pay_section(pay_text)
            sections = promote_section(result.sections, pay) if pay else result.sections
            return DetailParseResult(
                sections,
                source_disclosed_comp=_source_disclosed_comp_from_salary(compensation, pay_text),
            )
        if expects_pay:
            return pay_unread(
                result.sections, "Ashby compensation display flag set but salary object missing"
            )
        return result
