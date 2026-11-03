"""Lineage review API lenses: pending work versus immutable decision history."""

import pytest
from fastapi import HTTPException

from tracker.api.routers.lineage import _review_statuses


def test_reviewed_lens_returns_both_human_decision_statuses():
    assert _review_statuses("reviewed") == ("confirmed", "rejected")


def test_pending_lens_stays_separate_from_history():
    assert _review_statuses("pending") == ("pending",)


def test_unknown_review_lens_is_rejected():
    with pytest.raises(HTTPException, match="status must be"):
        _review_statuses("everything")
