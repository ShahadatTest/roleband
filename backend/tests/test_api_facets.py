"""Facet company list is sourced from the tracked_company rows, not static config.

A user-added company that is scraped and whose jobs appear must get a checkbox
too. Built-ins and user-added companies are rows in one table, so the filter
lists every visible one uniformly, named and ordered by its display name.
"""

import pytest

from tests.factories import make_company
from tracker.api.routers.jobs import _visible_company_options

pytestmark = pytest.mark.asyncio


async def test_visible_companies_appear_with_display_names(db_session):
    db_session.add_all([make_company("stripe", "Stripe"), make_company("google", "Google")])
    await db_session.flush()

    options = await _visible_company_options(db_session)

    assert list(options.items()) == [("google", {"display": "Google"}), ("stripe", {"display": "Stripe"})]


async def test_hidden_company_is_absent_from_the_filter(db_session):
    db_session.add_all([make_company("google", "Google"), make_company("stripe", "Stripe", visible=False)])
    await db_session.flush()

    options = await _visible_company_options(db_session)

    assert "stripe" not in options
    assert "google" in options
