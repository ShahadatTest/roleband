"""Collected statistics fill pay gaps; never manufacture a level or policy."""

import csv
import io

import pytest

from scripts.bench_level_pay import agreements, figure
from tracker.enrich.estimated_pay import EstimatedPay, estimated_bases
from tracker.enrich.level_pay import FiledBase, LevelBase, PostedBase
from tracker.levels.atlas import estimated_pay_text
from tracker.pay_store.estimated_pay import build
from tracker.schema import LevelBand

#: A neutral capture: its own source name and family spellings, as a real one declares them.
SOURCE = "acme-pay"
FAMILIES = {"software-engineer": "software_engineering", "product-manager": "product_management",
            "software-engineering-manager": "engineering_management"}


def _build(rows, named):
    return build(rows, named, source=SOURCE, families=FAMILIES)


def _row(**changes):
    return {"company_slug": "microsoft", "family": "software-engineer", "level_label": "65",
            "base_usd": 200_000, "stock_usd": 100_000, "bonus_usd": 40_000,
            "source": SOURCE, "band": "entry", "band_source": SOURCE,
            "source_url": "https://example.test/paid", "fetched_at": "2026-09-28T00:00:00+00:00",
            **changes}


def _cells(rows):
    return _build(rows, {"microsoft", "google", "amazon", "broadcom", "palantir"}).rows


def _read(rows):
    return estimated_bases(list(csv.DictReader(io.StringIO(estimated_pay_text(_cells(rows))))))


def test_a_captured_number_fills_only_the_rung_our_atlas_names():
    key = ("microsoft", "software_engineering", LevelBand.PRINCIPAL)
    found = _read([_row()])
    assert set(found) == {key}  # Stored external band said entry; ignored.
    assert found[key] == EstimatedPay("65", 200_000, 100_000, 40_000)
    assert _read([_row(level_label="completely unknown", band="principal")]) == {}
    assert _read([_row(company_slug="broadcom", level_label="ICB 5", band="senior")]) == {}


def test_a_family_ladder_keeps_its_own_band_and_rejects_a_rung_only_another_family_has():
    pm = _row(company_slug="google", family="product-manager", level_label="L8")
    em = _row(company_slug="google", family="software-engineering-manager", level_label="L8")
    unsupported = _row(company_slug="google", family="software-engineering-manager", level_label="L5")
    found = _read([pm, em, unsupported])
    assert set(found) == {("google", "product_management", LevelBand.PRINCIPAL),
                          ("google", "engineering_management", LevelBand.DIRECTOR_PLUS)}


def test_one_whole_observation_is_selected_by_the_existing_pay_label_not_input_order():
    low = _row(level_label="65", base_usd=200_000, stock_usd=100_000, bonus_usd=40_000)
    high = _row(level_label="67", base_usd=300_000, stock_usd=500_000, bonus_usd=70_000)
    first, second = _read([high, low]), _read([low, high])
    assert first == second
    chosen = next(iter(first.values()))
    assert (chosen.rung, chosen.base, chosen.equity, chosen.cash_bonus) == ("65", 200_000, 100_000, 40_000)


def test_worldwide_family_is_excluded_even_when_its_high_rung_clears_the_floor():
    low = _row(level_label="61", base_usd=30_000)
    high = _row(level_label="65", base_usd=100_000)
    built = _build([low, high], {"microsoft"})
    assert built.rows == []
    assert built.dropped == {"worldwide or below US floor": 2}
    # A stored external intern band cannot evade the floor.
    assert _cells([_row(base_usd=30_000, band="intern")]) == []


@pytest.mark.parametrize("changes,reason", [
    ({"company_slug": "not-named"}, "company not named"),
    ({"source": "manual"}, "another source"),
    ({"family": "unknown-family"}, "no exact taxonomy family"),
    ({"level_label": ""}, "no rung label"),
    ({"base_usd": None, "tc_median": 300_000}, "no positive base component"),
    ({"base_usd": -100}, "no positive base component"),
])
def test_unusable_rows_are_counted_and_never_decomposed(changes, reason):
    built = _build([_row(**changes)], {"microsoft"})
    assert built.rows == [] and built.dropped == {reason: 1}


def test_zero_or_missing_components_stay_unknown_and_no_source_or_guessed_band_travels():
    cells = _cells([_row(stock_usd=0, bonus_usd=None)])
    assert cells[0]["equity_usd"] is None and cells[0]["cash_bonus_usd"] is None
    assert not {"band", "source", "source_url", "n", "tc_median", "fetched_on", "as_of"} & cells[0].keys()
    read = next(iter(_read([_row(stock_usd=0, bonus_usd=0)]).values()))
    assert read.equity is None and read.cash_bonus is None


def test_duplicate_capture_key_fails_loudly():
    with pytest.raises(ValueError, match="duplicate collected key"):
        _cells([_row(), _row()])


def test_estimated_sign_on_is_never_called_annual_bonus_at_a_no_bonus_company():
    found = _read([_row(company_slug="amazon", level_label="L7", bonus_usd=222_000)])
    point = next(iter(found.values()))
    assert point.cash_bonus == 222_000
    assert point.annual_bonus("amazon") == 0
    assert point.annual_bonus("no-known-policy") is None


def test_estimated_base_fills_a_gap_but_never_displaces_employer_evidence():
    point = EstimatedPay("65", 200_000, 100_000, 40_000)
    key = ("microsoft", "software_engineering", LevelBand.PRINCIPAL)
    only = LevelBase(*key, filed=None, posted=None, estimated=point)
    assert only.base == 200_000 and figure(only) == (200_000, 0)  # submission count unknown
    posted = LevelBase(*key, filed=None, posted=PostedBase(2026, 1, 150_000, 170_000), estimated=point)
    from scripts.build_level_base import row

    assert row(only)["base_usd"] == 200_000
    assert set(row(only)) == {"company", "family", "band", "base_usd", "stock_usd"}
    assert posted.base == 160_000
    assert row(posted)["base_usd"] == 160_000
    filed = LevelBase(*key, filed=FiledBase(2026, 10, 1, 145_000), posted=posted.posted, estimated=point)
    assert filed.base == 145_000
    assert row(filed)["base_usd"] == 145_000
    # Agreement with the same captured statistics proves nothing.
    baselines = {("microsoft", "software-engineer", "principal"): {"base_usd": 200_000}}
    assert agreements({key: only}, baselines, {"microsoft"}) == []
