"""Reported per-level rows that cannot stand for US pay are set aside.

A non-US ladder must not supply a US baseline merely because its highest
rung clears the floor; individual outliers in a US ladder are handled separately.
"""

from __future__ import annotations

from types import SimpleNamespace

from tracker.analytics.comp_market import US_BASE_FLOOR_USD, set_aside, us_rows
from tracker.analytics.comp_package import select_baselines


def _row(company, family, band, base, label=None, stock=0, bonus=0, currency="USD"):
    return SimpleNamespace(company_slug=company, family=family, band=band, base_amount=base,
                           currency=currency,
                           level_label=label or band, stock_amount=stock, bonus_amount=bonus)


ACCENTURE = [_row("accenture", "software-engineer", b, v) for b, v in
             [("entry", 6_171), ("mid", 10_994), ("senior", 12_000), ("staff", 27_677), ("principal", 44_415),
              ("director_plus", 61_000)]]
DELOITTE = ([_row("deloitte", "software-engineer", b, v) for b, v in
             [("entry", 7_000), ("mid", 14_000), ("senior", 27_000), ("staff", 36_000)]]
            + [_row("deloitte", "data-scientist", b, v) for b, v in
               [("entry", 86_000), ("mid", 108_000), ("senior", 132_000), ("staff", 165_000)]])
GOOGLE = [_row("google", "software-engineer", b, v) for b, v in
          [("entry", 158_125), ("mid", 192_939), ("senior", 233_924), ("staff", 275_249)]]


def test_a_worldwide_mix_family_is_set_aside_whole_even_its_rungs_above_the_floor():
    # Accenture's top rung ($61K) clears the floor only because it is senior India pay.
    assert us_rows(ACCENTURE) == []
    assert len(set_aside(ACCENTURE)) == len(ACCENTURE)


def test_only_the_mixed_family_goes_when_another_family_reads_us_pay():
    kept = us_rows(DELOITTE)
    assert {r.family for r in kept} == {"data-scientist"}
    assert len(kept) == 4


def test_us_pay_is_untouched_and_one_stray_row_goes_alone():
    assert us_rows(GOOGLE) == GOOGLE
    stray = [*GOOGLE, _row("google", "software-engineer", "director_plus", 30_000)]
    assert us_rows(stray) == GOOGLE  # one row below the floor of four US rows: the row, not the family


def test_the_floor_is_inclusive_interns_are_exempt_and_unpriced_rows_stay():
    edge = [_row("x", "software-engineer", "mid", US_BASE_FLOOR_USD), _row("x", "software-engineer", "senior", 150_000)]
    assert us_rows(edge) == edge
    intern = _row("x", "software-engineer", "intern", 30_000)
    assert us_rows([*edge, intern]) == [*edge, intern]
    unpriced = _row("x", "software-engineer", "staff", None)
    assert unpriced in us_rows([*edge, unpriced])


def test_a_us_posting_never_reads_a_worldwide_mix_as_its_measured_split():
    # What the job route builds: Deloitte software engineering has no measured row,
    # so the package falls back (cross-family US data, or the heuristic) instead of India pay.
    baselines = select_baselines(us_rows(DELOITTE))
    assert ("deloitte", "software-engineer", "mid") not in baselines
    assert ("deloitte", "data-scientist", "mid") in baselines
    assert select_baselines(us_rows(ACCENTURE)) == {}


def test_the_us_base_floor_reads_dollars_only():
    """`US_BASE_FLOOR_USD` is a dollar figure. A rung in another currency is
    not US pay whatever its number, so it is set aside rather than measured
    against a floor it shares no unit with. Fail-first: the yen row is kept
    as US pay and the euro row is called "below the US floor"."""
    dollars = _row("acme", "software-engineer", "senior", 200_000)
    euros = _row("acme", "software-engineer", "senior", 40_000, currency="EUR")
    yen = _row("acme", "software-engineer", "senior", 9_000_000, currency="JPY")
    kept = us_rows([dollars, euros, yen])
    assert kept == [dollars]


def _stated(company, family, band, base, country, **kw):
    row = _row(company, family, band, base, **kw)
    row.country = row.stated_country = country
    return row


def test_a_row_that_states_its_country_is_kept_or_dropped_by_it_not_by_the_floor():
    """The floor guesses at rows that state nothing. A row that names its
    country has answered: a German rung at $150K is not US pay, and a US rung
    at $40K is, below the floor or not. Fail-first: the floor kept the German
    rung and dropped the US one."""
    german = _stated("acme", "software-engineer", "senior", 150_000, "DE")
    low_us = _stated("acme", "software-engineer", "entry", 40_000, "US")
    assert us_rows([german, low_us]) == [low_us]


def test_rows_that_state_a_country_never_make_a_company_look_like_a_worldwide_mix():
    """Three stated US rungs under the floor next to one unstated row above it:
    the unstated one is judged on its own, not set aside as part of a mix."""
    stated = [_stated("acme", "software-engineer", b, 40_000, "US") for b in ("entry", "mid", "senior")]
    unstated = _row("acme", "software-engineer", "staff", 200_000)
    assert us_rows([*stated, unstated]) == [*stated, unstated]


def test_unstated_rows_keep_the_floor_and_the_mix_rule():
    """The control: what the floor was for still holds."""
    assert us_rows(ACCENTURE) == []
    assert us_rows([_row("acme", "software-engineer", "senior", 40_000)]) == []


def test_a_banded_row_of_ours_is_read_for_the_us_but_judged_on_what_it_states():
    """`banded` reads our rows for the US when they name no country; that
    default is not a statement, so the floor still applies to them."""
    from tracker.db.queries.reference_pay import banded
    from tracker.plugins.registry import Providers

    ours = SimpleNamespace(provider="roleband", company_slug="acme", family="software-engineer", band="senior",
                           level_label="senior", base_amount=40_000, country=None, currency="USD", aliases=())
    (read,) = banded(Providers(), [ours])
    assert (read.country, read.stated_country) == ("US", None)
    assert us_rows([read]) == []
