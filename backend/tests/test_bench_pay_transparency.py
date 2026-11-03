"""Pay-transparency benchmark arithmetic: pure classification, no network.

The fetching lives in the script; what is worth pinning is the arithmetic that
turns a response into a verdict, because the whole measurement is an argument
and a miscounted cell would make it the wrong one.
"""

from __future__ import annotations

import pytest

from scripts.bench_pay_transparency import (
    AGREE,
    BOTH,
    DIFFER,
    NEITHER,
    SOURCE_SILENT,
    STRUCTURED_ONLY,
    TEXT_ONLY,
    classify_coverage,
    classify_value,
    greenhouse_tenants,
)

_TIER = {"min_cents": 24000000, "max_cents": 31500000, "currency_type": "USD",
         "title": "Annual Salary:"}
_BODY = "<p>The annual compensation range for this role is $240,000 - $315,000.</p>"


@pytest.mark.parametrize("ranges,content,expected", [
    ([_TIER], _BODY, BOTH),
    ([_TIER], "<p>Compensation is competitive.</p>", STRUCTURED_ONLY),
    ([], _BODY, TEXT_ONLY),
    (None, _BODY, TEXT_ONLY),
    ([], "<p>Nothing about pay.</p>", NEITHER),
    (None, None, NEITHER),
])
def test_the_coverage_cells_separate_a_gain_from_a_reshape(ranges, content, expected):
    """`both` is not a disclosure gained.

    The listing already hands us `content` for free, so a posting stating its
    pay in prose is reachable today at zero extra requests. Counting it as a
    gain is how the benchmark would argue for a request it does not need —
    only `structured_only` is out of reach of every current code path.
    """
    assert classify_coverage(ranges, content) == expected


@pytest.mark.parametrize("content", [
    "salary range: 240,000 USD to 315,000 USD",
    "The range is €95,000 - €130,000",
    "£85,000-£110,000 depending on experience",
])
def test_an_amount_is_recognised_without_a_dollar_sign(content):
    """Deliberately loose, and loose in the safe direction: a false positive
    here moves a posting out of `structured_only` and makes the flag look LESS
    useful, so the measurement cannot flatter the change it is evaluating."""
    assert classify_coverage([_TIER], content) == BOTH


@pytest.mark.parametrize("content", [
    "Requisition 4461444008 for our 2026 cohort",   # a bare id is not money
    "Over 5,000 employees across 30 countries",     # a bare count is not money
    "Position ID: P78090",
    # DoorDash bodies carry this paragraph and no pay; it is the false positive
    # that adjacency exists to prevent.
    "We began using Covey Scout for Inbound from August 21, 2023, through December 21, 2023",
])
def test_a_number_that_is_not_money_does_not_count_as_a_disclosure(content):
    assert classify_coverage([_TIER], content) == STRUCTURED_ONLY


@pytest.mark.parametrize("content", [
    # A matcher that reads only `$€£` and
    # four ISO codes counts all three as disclosures reachable ONLY through the
    # flag: the benchmark would measure US pay transparency and report it as a
    # global gain, in the direction that flatters the change under evaluation.
    "₹9,424,500—₹9,424,500 INR",
    "₹6,612,600—₹6,612,600 INR",
    "503,500 د.إ—530,000 د.إ",
])
def test_a_body_stating_pay_in_a_currency_we_did_not_list_is_still_a_disclosure(content):
    assert classify_coverage([_TIER], content) == BOTH


def test_an_agreeing_band_is_the_same_whole_dollars_the_source_states():
    assert classify_value((240_000, 315_000), [_TIER]) == AGREE


@pytest.mark.parametrize("stored", [
    (240_000, 316_000),   # top edge moved
    (241_000, 315_000),   # bottom edge moved
    (None, 315_000),      # we hold only half a band
    (240_000, None),
])
def test_a_band_that_is_not_the_source_range_is_a_disagreement(stored):
    """The arm that can find a DEFECT rather than an increment: a stored band
    that is not the employer's own number is wrong on the dashboard today."""
    assert classify_value(stored, [_TIER]) == DIFFER


def test_a_source_that_states_no_range_is_not_a_disagreement():
    """Silence is not a contradiction. Folding it into `differ` would report
    our own coverage as employer disagreement and inflate the case for extra requests."""
    assert classify_value((240_000, 315_000), []) == SOURCE_SILENT
    assert classify_value((240_000, 315_000), None) == SOURCE_SILENT


def test_only_the_first_tier_is_compared_and_tiers_are_never_merged():
    """Never combine tiers into an invented min/max offer. A stored
    band spanning two tiers is a disagreement, not a match — the alternative is
    a benchmark that blesses a span no employer stated."""
    second = {"min_cents": 40000000, "max_cents": 52000000, "currency_type": "USD"}

    assert classify_value((240_000, 520_000), [_TIER, second]) == DIFFER
    assert classify_value((240_000, 315_000), [_TIER, second]) == AGREE


def test_the_measured_population_includes_the_tenant_we_actually_collect():
    """A catalog-only population misses enabled companies with no catalog row,
    even though their figures are shown on the dashboard."""
    tenants = greenhouse_tenants()

    assert tenants["anthropic"] == "anthropic"
    assert "stripe" in tenants and "datadog" in tenants


# -- how employers actually spell an amount ------------------------ #


@pytest.mark.parametrize("content", [
    # Hourly bands must count as prose disclosures too; otherwise the
    # measurement exaggerates what additional requests could recover.
    "Base Pay: $15.65 - $20.00 per hour, plus equity",
    "The pay for this role is USD 24.50 per hour.",
    # The ordinary abbreviated annual band.
    "The salary range for this role is $120K - $180K.",
    "Compensation: $1.2M total over four years",
    "Base salary of 95k USD",
])
def test_pay_stated_hourly_or_abbreviated_is_a_text_disclosure(content):
    """`structured_only` means "a disclosure NO current code path can reach",
    and it is the cell the headline is drawn from.

    Reading only comma-grouped and 4+-digit runs misses every hourly rate (never
    four digits, never comma-grouped) and every `$120K`, and counts those
    postings as prose stating no pay at all. That is biased in the direction
    that flatters the change being evaluated, the same failure as a currency
    list that is too narrow.
    """
    assert classify_coverage([_TIER], content) == BOTH


@pytest.mark.parametrize("content", [
    "Requisition 4461444008 for our 2026 cohort",
    "Position ID: P78090",
    "We began using Covey Scout for Inbound from August 21, 2023",
    # The loosening must not start reading version numbers or ratios as pay.
    "Experience with Kubernetes 1.25 and Python 3.12 required",
    "A 4.01 GPA is not a salary",
])
def test_loosening_the_amount_forms_did_not_loosen_adjacency(content):
    """Adjacency to a currency symbol or ISO code is what keeps a requisition
    id, a headcount or a version string from reading as pay. The new forms are
    additional AMOUNTS, not a new way to match without a currency."""
    assert classify_coverage([_TIER], content) == STRUCTURED_ONLY
