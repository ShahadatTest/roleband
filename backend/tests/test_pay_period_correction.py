"""Correcting stored pay periods the old rule got wrong.

Each text is verbatim from a real row, or the smallest edit of one. The rule
may relabel a band and repair a misread amount, never pick a different band and
never remove one.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from tests.factories import make_job
from tracker.db.models import Job
from tracker.intelligence_runtime.disclosed_comp import correct_pay_periods, corrected_band
from tracker.pay_disclosure import extract_grounded_band

NETFLIX = (
    "The range for this role is $600,000.00 - $1,066,000.00. This compensation range is "
    "determined by the market. Full-time hourly employees accrue 35 days annually for paid time off."
)
GOOGLE = "US: $163000 - $236000 (USD) + 15% bonus target + equity + benefits."
ELASTIC = "The typical starting salary range for this role is: €104.800—€165.700 EUR Additional Information"
VERCEL = (
    "San Francisco, CA pay range for this position is $382,000 - $485,000 OTE. "
    "New York pay range is $340,000 - $425,000 OTE."
)
COHERE = "Everyone receives a $500 home office stipend to set up your workspace."
# What the rule itself stores as `unclear`: the words contradict the size.
CONTRADICTION = "Base pay: $150,000 - $200,000 per month, paid in arrears."


def _read(text: str):
    band = extract_grounded_band(text, text)
    return band if band.disclosed else None


def test_the_same_amounts_read_again_take_the_new_period():
    assert corrected_band((600_000, 1_066_000, "USD", "hour"), _read(NETFLIX)) == {
        "disclosed_pay_period": "year"
    }


def test_a_stored_could_not_tell_is_never_a_candidate():
    # `unclear` is what the rule writes when the words contradict the size;
    # the read-time guard does not promote it to `year`, so it is consistent
    # as stored, and re-reading it every run could only write it again.
    assert _read(CONTRADICTION).pay_period.value == "unclear"
    assert corrected_band((150_000, 200_000, "USD", "unclear"), _read(CONTRADICTION)) is None
    assert corrected_band((163_000, 236_000, "USD", "unclear"), _read(GOOGLE)) is None


def test_a_misread_european_amount_is_repaired_with_its_period():
    change = corrected_band((104, 165, "EUR", "year"), _read(ELASTIC))
    assert change is not None
    assert (change["disclosed_base_min"], change["disclosed_base_max"]) == (104_800, 165_700)
    assert change["disclosed_pay_period"] == "year"
    assert "€104.800" in change["disclosed_snippet"]


def test_another_band_in_the_same_posting_is_never_swapped_in():
    # Stored: the New York range. A re-read picks San Francisco's first. Both are
    # yearly, so the stored row is not even a candidate; and forced through, it
    # must still not be swapped.
    assert corrected_band((340_000, 425_000, "USD", "year"), _read(VERCEL)) is None
    assert corrected_band((340_000, 425_000, "USD", "unclear"), _read(VERCEL)) is None


def test_a_salary_whose_thousands_match_a_stored_small_band_is_not_a_repair():
    """The repair is for the "€104.800" misread only: the text must write the
    stored amounts with a dot before the thousands. Here the stored band is a
    real hourly range read as yearly and the posting also states a salary
    whose thousands happen to match; swapping it in is picking another band,
    not repairing a misread."""
    both = (
        "Contract rate: $150 - $200 per hour. Converts to full time at "
        "$150,000 - $200,000 per year."
    )
    reread = _read(both)
    assert (reread.base_min, reread.base_max) == (150_000, 200_000), "the salary ranks first"
    assert corrected_band((150, 200, "USD", "year"), reread) is None


def test_nothing_found_again_removes_nothing():
    # Cohere's stipend, stored as a $500 salary: the rule reads no pay at all.
    assert _read(COHERE) is None
    assert corrected_band((500, 500, "USD", "year"), None) is None


def test_a_band_already_consistent_is_not_touched():
    assert corrected_band((150_000, 200_000, "USD", "year"), _read(GOOGLE)) is None
    assert corrected_band((59, 89, "USD", "hour"), None) is None
    # Consistent by size, though its text now reads "could not tell": this pass
    # corrects contradictions only, so a salary shown yearly is not demoted.
    worded = "Hourly rate: $150,000 - $200,000"
    assert _read(worded).pay_period.value == "unclear"
    assert corrected_band((150_000, 200_000, "USD", "year"), _read(worded)) is None


def _row(key: str, text: str, low, high, currency, period) -> Job:
    return make_job(
        key, description_text=text, structured_at=datetime(2026, 9, 1, tzinfo=UTC),
        disclosed_base_min=low, disclosed_base_max=high,
        disclosed_currency=currency, disclosed_pay_period=period, disclosed_pay_basis="unclear",
    )


@pytest.mark.asyncio
async def test_the_pass_corrects_what_it_can_and_then_writes_nothing(db_session):
    db_session.add_all([
        _row("netflix", NETFLIX, 600_000, 1_066_000, "USD", "hour"),
        _row("contradiction", CONTRADICTION, 150_000, 200_000, "USD", "unclear"),
        _row("elastic", ELASTIC, 104, 165, "EUR", "year"),
        _row("cohere", COHERE, 500, 500, "USD", "year"),
        _row("right", GOOGLE, 163_000, 236_000, "USD", "year"),
    ])
    await db_session.commit()

    first = await correct_pay_periods(db_session)
    await db_session.commit()
    # The stored contradiction is not selected: a read-time guard that
    # promoted `unclear` salaries would re-read it, and keep it, on every run.
    assert first == {"candidates": 3, "relabelled": 1, "amounts_fixed": 1, "kept": 1}

    async def stored() -> dict:
        db_session.expire_all()
        return {
            job.req_id: (job.disclosed_base_min, job.disclosed_base_max,
                         job.disclosed_pay_period, job.disclosed_snippet)
            for job in (await db_session.scalars(select(Job))).all()
        }

    rows = await stored()
    assert {key: row[:3] for key, row in rows.items()} == {
        "netflix": (600_000, 1_066_000, "year"),
        "contradiction": (150_000, 200_000, "unclear"),
        "elastic": (104_800, 165_700, "year"),
        "cohere": (500, 500, "year"),  # kept: shown as "could not tell", never removed
        "right": (163_000, 236_000, "year"),
    }

    # Caught up: the one row still selected is the one no re-read can fix,
    # and the run writes nothing.
    again = await correct_pay_periods(db_session)
    await db_session.commit()
    assert again == {"candidates": 1, "relabelled": 0, "amounts_fixed": 0, "kept": 1}
    assert await stored() == rows
