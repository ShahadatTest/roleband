"""One rule for every writer of a posting's stated band (`db/pay_band.py`).

Three sources state a band and a fourth corrects one. Precedence, clearing,
the place key and the stamp have to mean the same whichever wrote the row, or
a reader cannot tell which answer it has. A test per clause.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from tracker.db.pay_band import (
    CONNECTOR_READER_VERSION,
    apply_band,
    may_write,
    pay_place_key,
)

NOW = "2026-10-15T00:00:00Z"
BAND = {
    "disclosed_base_min": 150_000,
    "disclosed_base_max": 200_000,
    "disclosed_currency": "USD",
    "disclosed_pay_basis": "base",
    "disclosed_pay_period": "year",
    "disclosed_snippet": "$150,000 - $200,000",
    "disclosed_confidence": "high",
    "disclosed_bonus_pct": None,
}


def _job(**over):
    fields = {
        "disclosed_base_min": None, "disclosed_base_max": None, "disclosed_currency": None,
        "disclosed_pay_basis": None, "disclosed_pay_period": None, "disclosed_snippet": None,
        "disclosed_confidence": None, "disclosed_bonus_pct": None, "disclosed_source": None,
        "structured_at": None, "structured_prompt_version": None, "disclosed_place_key": None,
        "locations": ["New York, NY"],
    }
    return SimpleNamespace(**{**fields, **over})


# --- precedence


@pytest.mark.parametrize(
    ("owner", "writer", "allowed"),
    [
        (None, "text", True),          # nothing stored: anyone may write
        ("text", "text", True),        # a source restates its own
        ("page", "text", True),        # the posting's words beat its page
        ("page", "connector", True),   # a structured field beats both
        ("connector", "text", False),  # prose never buries a published field
        ("text", "page", False),       # a page read only fills a gap
        ("connector", "page", False),
    ],
)
def test_a_weaker_source_never_overwrites_a_stronger_one(owner, writer, allowed):
    assert may_write(owner, writer) is allowed


def test_a_refused_write_changes_nothing_and_reports_nothing():
    job = _job(**BAND, disclosed_source="connector", structured_at="earlier")
    assert apply_band(job, {**BAND, "disclosed_base_min": 1}, source="text",
                      version="text/1", now=NOW, place_key="nyc") is None
    assert job.disclosed_base_min == 150_000
    assert (job.disclosed_source, job.structured_at) == ("connector", "earlier")


# --- clearing


def test_a_source_that_states_no_pay_clears_the_band_it_owns():
    job = _job(**BAND, disclosed_source="text")
    change = apply_band(job, None, source="text", version="text/2", now=NOW, place_key="nyc")
    assert change is not None and change.moved
    assert (job.disclosed_base_min, job.disclosed_source) == (None, None)
    assert job.structured_at == NOW, "a clear is this reader's answer, and is stamped"


def test_a_source_cannot_clear_a_band_it_does_not_own():
    job = _job(**BAND, disclosed_source="connector")
    assert apply_band(job, None, source="text", version="text/2",
                      now=NOW, place_key="nyc") is None
    assert job.disclosed_base_min == 150_000


def test_a_stronger_source_cannot_clear_a_weaker_one_s_band_either():
    """Text that states no pay says nothing about the page: the page's band
    is the page's to withdraw."""
    job = _job(**BAND, disclosed_source="page", structured_at="earlier")
    assert apply_band(job, None, source="text", version="text/2",
                      now=NOW, place_key="nyc") is None
    assert (job.disclosed_base_min, job.disclosed_source) == (150_000, "page")
    assert job.structured_at == "earlier"


# --- the place key and the stamp


def test_every_write_records_the_place_and_the_reader():
    job = _job()
    apply_band(job, BAND, source="connector", version=CONNECTOR_READER_VERSION,
               now=NOW, place_key=pay_place_key(["New York, NY"]))
    assert job.disclosed_place_key == pay_place_key(["New York, NY"])
    assert job.structured_prompt_version == CONNECTOR_READER_VERSION
    assert job.structured_at == NOW


def test_the_connector_does_not_stamp_the_text_parser_s_version():
    """The stale gate reasons about the reader named in the stamp. A
    structured field read by no text parser must not carry its version."""
    from tracker.pay_disclosure import PAY_PARSER_VERSION

    assert CONNECTOR_READER_VERSION != PAY_PARSER_VERSION
    job = _job()
    apply_band(job, BAND, source="connector", version=CONNECTOR_READER_VERSION,
               now=NOW, place_key="nyc")
    assert job.structured_prompt_version == CONNECTOR_READER_VERSION


def test_the_place_key_ignores_a_respelling_of_the_same_city():
    assert pay_place_key(["New York, NY"]) == pay_place_key(["new york, ny"])
    assert pay_place_key([]) == ""


# --- what the caller records


def test_a_first_reading_is_not_a_move():
    job = _job()
    change = apply_band(job, BAND, source="text", version="text/1", now=NOW, place_key="nyc")
    assert change is not None and change.moved and not change.had_band


def test_a_restatement_of_the_same_figures_is_not_a_move():
    job = _job(**BAND, disclosed_source="text")
    change = apply_band(job, {**BAND, "disclosed_snippet": "reworded"}, source="text",
                        version="text/2", now=NOW, place_key="nyc")
    assert change is not None and not change.moved, "only the bounds are the pay"


def test_a_band_that_moves_reports_both_ends_for_the_feed():
    job = _job(**BAND, disclosed_source="text")
    change = apply_band(job, {**BAND, "disclosed_base_max": 220_000}, source="text",
                        version="text/2", now=NOW, place_key="nyc")
    assert change is not None and change.moved and change.had_band
    assert change.event_detail() == {
        "from": {"min": 150_000, "max": 200_000, "currency": "USD", "period": "year"},
        "to": {"min": 150_000, "max": 220_000, "currency": "USD", "period": "year"},
    }
