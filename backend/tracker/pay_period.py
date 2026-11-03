"""The pay period: one rule for every source.

An amount's SIZE says which period it can be (the three classes are about 10x
apart), and the posting's WORDS count only when they sit next to the amount.
`decide_period` is the rule, `effective_period` the read-time guard every
consumer of a stored band uses. The currency table it sizes amounts with is
`pay_numbers.USD_PER_UNIT`.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from enum import Enum

from tracker.pay_numbers import USD_PER_UNIT


class PayPeriod(str, Enum):
    year = "year"
    month = "month"
    hour = "hour"
    #: We could not tell: the posting's own word contradicts the
    #: size of its amount. Shown verbatim, never split, never counted.
    unclear = "unclear"


# What a human salary band can actually be. Prose context is too weak to
# separate pay from money-shaped noise (a budget figure can sit one sentence
# from the word "pay"), but MAGNITUDE separates them cleanly, and it
# does so without depending on how a posting happens to be worded.
# Floor is the US federal minimum wage: below it a figure is not an hourly rate,
# it is a number that happens to carry a currency symbol. Without a floor here,
# "$3-4B annual logistics spend" qualifies as an hourly band and the reject
# never fires.
_HOURLY_RANGE = (7, 1_000)


_ANNUAL_RANGE = (10_000, 5_000_000)


# --------------------------------------------------------------------------- #
# The pay period: one rule for every source.
#
# An amount's SIZE says which period it can be, because the three are about
# ten times apart: nobody earns $150,000 an hour or $45 a year. The posting's
# WORDS count only when they sit next to the amount; the rest of the pay
# paragraph is not evidence. Read anywhere, words would mark salaries hourly:
# a benefits line "Full-time hourly employees accrue 35 days", "salary or
# hourly ranges", "wage-and-hour laws".
# --------------------------------------------------------------------------- #

#: Monthly pay, in US dollars. The ceiling is senior monthly pay, which runs to
#: about USD 30,000 ("S$12,000 - S$18,000 per month", "Base pay: $9,000 -
#: $12,000 per month"); a ceiling at the yearly floor (10,000) would read all of
#: them as no pay at all.
_MONTHLY_RANGE = (1_000, 30_000)


#: Size classes in US dollars, the no-word reading first. A band must sit
#: wholly inside one; outside every class it is not pay under any reading, a
#: hard reject: `$3-4` ("a $3-4B annual logistics spend") and
#: `$250,000-$100,000,000` ("construction projects ranging from") corrupt comp
#: data the dashboard shows as fact. Hour and month do not overlap. Month and
#: year DO, from USD 10,000 to 30,000: there only a word says monthly, and an
#: amount with no word reads yearly.
_SIZE_CLASSES: tuple[tuple[PayPeriod, float, float], ...] = (
    (PayPeriod.year, _ANNUAL_RANGE[0], _ANNUAL_RANGE[1]),
    (PayPeriod.month, _MONTHLY_RANGE[0], _MONTHLY_RANGE[1]),
    (PayPeriod.hour, _HOURLY_RANGE[0], _HOURLY_RANGE[1]),
)


#: (period, floor, ceiling) in US dollars, for a reader that checks a size in SQL.
SIZE_CLASSES = _SIZE_CLASSES


def size_classes(
    low: float | None, high: float | None, currency: str | None
) -> tuple[PayPeriod, ...]:
    """Every period an amount of this size can be, the no-word reading first;
    empty if it is no pay."""
    low = low if low is not None else high
    high = high if high is not None else low
    if low is None or high is None or low <= 0 or high < low:
        return ()
    factor = USD_PER_UNIT.get((currency or "USD").upper(), 1.0)
    lo, hi = low * factor, high * factor
    return tuple(
        period for period, floor, ceiling in _SIZE_CLASSES if floor <= lo and hi <= ceiling
    )


def size_class(low: float | None, high: float | None, currency: str | None) -> PayPeriod | None:
    """The period an amount of this size reads with no word, or None if it is
    no pay. `size_classes` holds every period it can be."""
    classes = size_classes(low, high, currency)
    return classes[0] if classes else None


def _words(pattern: str) -> re.Pattern[str]:
    return re.compile(pattern, re.IGNORECASE)


#: A UNIT names the period outright ("per month", "/hr", "annually"). A general
#: word only leans ("hourly", "monthly", "salary"): "Salary: €4,500 - €5,500
#: per month" is monthly, so a unit outranks a general word, and "salary or
#: hourly ranges" (two general words) names nothing.
_PERIOD_UNITS: tuple[tuple[PayPeriod, re.Pattern[str]], ...] = (
    # `/hr` is not a substring of "hour": without it "$59.49 and $89.84/hr"
    # reads as a fifty-nine dollar salary.
    (PayPeriod.hour, _words(r"\bper\s+(?:hour|hr)\b|\ban?\s+hour\b|/\s*(?:hr|hour)\b")),
    (PayPeriod.month, _words(r"\bper\s+(?:month|mo)\b|\ba\s+month\b|/\s*(?:mo|month)\b")),
    (PayPeriod.year, _words(r"\bper\s+(?:year|annum|yr)\b|\ba\s+year\b|/\s*(?:yr|year|annum)\b|\bannually\b")),
    # A day or a week is a unit we name but never show, so it reads `unclear`:
    # it must CONTRADICT the size rather than go unread, or "$600 - $800 per
    # day" is stored as an hourly rate by its size alone. "a day" and "a week"
    # stay out: "in the office twice a week" sits beside salaries.
    (PayPeriod.unclear, _words(r"\bper\s+(?:day|week|wk)\b|/\s*(?:day|week|wk)\b")),
)
_PERIOD_LEANS: tuple[tuple[PayPeriod, re.Pattern[str]], ...] = (
    (PayPeriod.hour, _words(r"\bhourly\b|\bhour\b")),
    (PayPeriod.month, _words(r"\bmonthly\b")),
    (PayPeriod.year, _words(r"\bannual\b|\byearly\b|\bsalary\b")),
    # Only as a rate's name ("Daily rate", "day rate", "weekly pay"): bare,
    # "daily" and "weekly" are prose or how often pay is paid ("on a daily
    # basis", "Daily meals allowance", "paid weekly", "bi-weekly").
    (PayPeriod.unclear, _words(r"\b(?:daily|day|(?<!-)weekly)\s+(?:rate|pay|wage)s?\b")),
)


#: A count of hours or days is a schedule, not a pay unit: "(40 hour week)",
#: "40-hour", "37.5 hours per week", "3 days a week". Removed before the words
#: are read, or "Compensation: $150,000 - $200,000 (40 hour week)" leans hourly
#: and a salary reads `unclear`. Never after a currency sign or inside a
#: number: "$65 hour" states an amount.
_SCHEDULE_RE = _words(
    r"(?<![\d.,$£€])\d+(?:\.\d+)?\s*-?\s*(?:hours?|hrs?|days?)\b"
    r"(?:\s*(?:per\s+|an?\s+|each\s+|/\s*)?(?:work\s*)?(?:week|wk|day|month)\b)?"
)


#: How far from the amount a word still describes it: a label before it
#: ("Annual Salary: ", "Hourly Rate: ", "This role is paid hourly: ") and a
#: unit after it ("USD annually", "per hour", "/hr").
_WORD_LEAD = 40
_WORD_TRAIL = 30

#: Past the label window the lead reaches back to the start of the amount's
#: own sentence ("The hourly pay range for this role in California and New
#: York is $50 - $60": 66 characters, past the label window), capped so text
#: with no full stops cannot lend a word from a screen away. Only through the
#: same line and sentence: reaching across a line break or a sentence glued to
#: the next ("on a daily basis.Individual pay") would mark correct salaries
#: `unclear` ("Daily meals allowance", "monthly wellness" in the benefits list
#: above the band).
_SENTENCE_REACH = 160
_FAR_STOP_RE = re.compile(r"[.!?](?=\s|$|[A-Z])|\n")


def period_words(text: str) -> PayPeriod | None:
    """The one period `text` names, or None when it names none or several.
    Units first; general words only when no unit is present. A named unit we
    do not show (a day, a week) is `PayPeriod.unclear`."""
    text = _SCHEDULE_RE.sub(" ", text or "")
    for table in (_PERIOD_UNITS, _PERIOD_LEANS):
        named = {period for period, pattern in table if pattern.search(text)}
        if named:
            return named.pop() if len(named) == 1 else None
    return None


#: A sentence ends at . ! or ? followed by whitespace; the dot inside
#: "126,900.00" or "€104.800" is followed by a digit, so it is no end.
_SENTENCE_END_RE = re.compile(r"[.!?](?=\s|$)")


def attached_words(pay_text: str, start: int, end: int) -> PayPeriod | None:
    """The period the words next to the amount at `start:end` name, within the
    amount's own sentence: Cobalt's "The hourly range for this role is $84 -
    $106. A candidate's salary is..." is hourly, and the next sentence's
    "salary" must not cancel it."""
    near = max(0, start - _WORD_LEAD)
    far = pay_text[max(0, start - _SENTENCE_REACH) : near]
    stops = list(_FAR_STOP_RE.finditer(far))
    lead = (far[stops[-1].end() :] if stops else far) + pay_text[near:start]
    ends = list(_SENTENCE_END_RE.finditer(lead))
    if ends:
        lead = lead[ends[-1].end() :]
    trail = pay_text[end : end + _WORD_TRAIL]
    stop = _SENTENCE_END_RE.search(trail)
    if stop:
        trail = trail[: stop.start()]
    return period_words(lead + pay_text[start:end] + trail)


def decide_period(
    size: PayPeriod | Sequence[PayPeriod] | None,
    words: PayPeriod | None,
    *,
    structured: bool = False,
) -> PayPeriod | None:
    """The period of a band, or None when it is not pay.

    `size` is `size_classes(...)` (one period, or several where month and year
    overlap, the no-word reading first).

    | words next to it | size             | period                              |
    |------------------|------------------|-------------------------------------|
    | agree            | any              | that period                         |
    | none             | yearly           | year: a salary-sized amount is one  |
    | none             | hourly/monthly   | not pay in free text (a "$500       |
    |                  |                  | stipend"); the size in a structured |
    |                  |                  | pay field, which is pay by definition|
    | disagree         | can be yearly    | unclear: could not tell             |
    | disagree         | hourly/monthly   | not pay in free text ("$1,500 -     |
    |                  |                  | $3,000 annual learning budget"),    |
    |                  |                  | unclear in a structured field       |
    | any              | no class         | not pay                             |
    """
    sizes = (size,) if isinstance(size, PayPeriod) else tuple(size or ())
    if not sizes:
        return None
    if words in sizes:
        return words
    if words is None:
        return sizes[0] if sizes[0] is PayPeriod.year or structured else None
    # A small amount whose words disagree with its size is a stipend, a budget
    # or a day rate in prose, not pay we can show; a salary-sized one is pay
    # whose unit we could not tell.
    if not structured and PayPeriod.year not in sizes:
        return None
    return PayPeriod.unclear


def effective_period(
    stored: str | None, low: float | None, high: float | None, currency: str | None
) -> str:
    """The period a STORED band may be shown with, checked against its size.

    Read-time guard for rows written before this rule, and for sources that
    state a period without us checking it. A stored period its amount cannot
    be ("$600,000 / hr", "€104 / yr") reads `unclear`. A stored `unclear`
    stays `unclear`: under this rule it means the words next to the amount
    contradict its size ("$150,000 per month"), and promoting it to `year`
    would split contradictions into base, bonus and equity and compare them
    with the pay floor. The `pay_periods` pass relabels stored rows from their
    own text. A band stored with no period at all reads by its size. Pure:
    nothing is rewritten.
    """
    sizes = size_classes(low, high, currency)
    if stored is not None and stored in {size.value for size in sizes}:
        return stored
    if stored is None and sizes and sizes[0] is PayPeriod.year:
        return PayPeriod.year.value
    return PayPeriod.unclear.value


def not_yearly_usd(
    low: float | None, high: float | None, currency: str | None, period: str | None
) -> str | None:
    """Why a stored band cannot sit on a yearly US-dollar axis, or None when it can.

    `not_usd` for another currency: nothing is converted, and a band stored with
    no currency is a dollar band. `not_yearly` when `effective_period` reads a
    period other than `year`: hourly and monthly are never annualised. An amount
    that is no pay at any size passes here, for the caller's own plausibility
    floor to count.
    """
    if (currency or "USD").upper() != "USD":
        return "not_usd"
    if size_class(low, high, currency) is not None and effective_period(period, low, high, currency) != "year":
        return "not_yearly"
    return None
