"""Best fit shows the roles at a level we place first.

The Board holds roles whose level we cannot place (the posting
states none, or a level in the company's own terms we have not mapped) beside
roles whose level we place on the shared levels. Best fit, the Board's
default order, puts the placed group first and orders each group by its own
ranking; `placed_total` tells the Board where the second group starts. A
column sort, and a typed search, keep their own order.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy.dialects import postgresql

from tracker.db.models import Job
from tracker.search.best_match import intent_ranked_stmt

T0 = datetime(2026, 10, 2, tzinfo=UTC)

#: (title, basis, band, days before T0): first_seen puts the unplaced rows newest.
ROWS = [
    ("Senior Manager, Data Science", "unmapped", "staff", 0),
    ("Manager, Data Science", "none", "mid", 1),
    ("Principal Data Scientist", "generic", "principal", 5),
    ("Director, Data Science", "generic", "director_plus", 6),
    ("Staff Data Scientist (legacy row)", None, "principal", 7),  # NULL basis reads as stated
]
PLACED = ["Principal Data Scientist", "Director, Data Science", "Staff Data Scientist (legacy row)"]
UNPLACED = ["Senior Manager, Data Science", "Manager, Data Science"]


@pytest_asyncio.fixture
async def board(db_session):
    for i, (title, basis, band, days) in enumerate(ROWS):
        seen = T0 - timedelta(days=days)
        db_session.add(Job(
            company="acme", req_id=f"r{i}", dedupe_key=f"acme:r{i}", title=title,
            url=f"https://careers.example.test/acme/{i}", locations=["London, UK"],
            location_groups=["uk"], domains=[], workplace_type="onsite", level_band=band,
            level_confidence="confirmed", level_basis=basis, family="data_science",
            track="management", comp_currency="USD", status="open", in_scope=True,
            first_seen=seen, last_seen=seen, description_sections=[],
        ))
    await db_session.commit()


async def _titles(api_client, query: str) -> tuple[list[str], dict]:
    body = (await api_client.get(f"/api/jobs?{query}")).json()
    return [item["title"] for item in body["items"]], body


@pytest.mark.asyncio
async def test_best_fit_puts_the_placed_group_first_and_says_where_it_ends(api_client, board):
    # No intent signal yet: each group keeps the default order (newest first).
    titles, body = await _titles(api_client, "sort=relevance")
    assert titles == PLACED + UNPLACED
    assert (body["total"], body["placed_total"]) == (5, 3)


@pytest.mark.asyncio
async def test_the_boundary_is_an_index_of_the_whole_list_not_the_page(api_client, board):
    titles, body = await _titles(api_client, "sort=relevance&limit=2&offset=2")
    assert titles == [PLACED[2], UNPLACED[0]]
    assert body["placed_total"] == 3  # the second group starts at item 3 of 5


@pytest.mark.asyncio
async def test_a_column_sort_keeps_its_own_order_and_draws_no_boundary(api_client, board):
    titles, body = await _titles(api_client, "sort=first_seen&order=desc")
    assert titles == [title for title, *_ in ROWS]
    assert "placed_total" not in body


@pytest.mark.asyncio
async def test_a_board_holding_one_group_says_so(api_client, board):
    # The Level filter narrowed to "Level not placed": no placed group at all.
    titles, body = await _titles(api_client, "sort=relevance&level_band=unstated")
    assert titles == UNPLACED
    assert body["placed_total"] == 0


def test_the_intent_ranking_orders_each_group_by_intent():
    sql = str(intent_ranked_stmt({"status": "open"}, [0.1, 0.2], limit=50, offset=0)
              .compile(dialect=postgresql.dialect()))
    order_by = sql.split("ORDER BY", 1)[1]
    # The group key first, then cosine: intent never lifts an unplaced row
    # above a placed one, and still orders both groups.
    assert order_by.index("jobs.level_basis") < order_by.index("intent_distance")
    assert "intent_distance ASC NULLS LAST, jobs.id DESC" in order_by


# --- "Level not placed" by the years a role requires ---------------------------- #

#: (title, basis, band, days before T0, required years). Newest first by first_seen,
#: so the years order is visible against the default order.
#: The unplaced rows stating years ask for 10, 6, 6 and 3: the typical (median)
#: posting asks for 6, where a posting stating none lands.
YEARS_ROWS = [
    ("Engineering Manager, Payments", "unmapped", "staff", 0, None),
    ("Engineering Manager, Search", "none", "mid", 1, 6.0),
    ("Manager, Platform", "none", "mid", 2, None),
    ("Head of Infrastructure", "unmapped", "staff", 3, 10.0),
    ("Staff Engineer, Ads", "generic", "staff", 4, 15.0),  # placed: years never move it
    ("Principal Engineer, Ads", "generic", "principal", 5, None),
    ("Manager, Mobile", "none", "mid", 6, 3.0),
    ("Engineering Manager, Data", "unmapped", "staff", 7, 6.0),
]


@pytest_asyncio.fixture
async def years_board(db_session):
    for i, (title, basis, band, days, years) in enumerate(YEARS_ROWS):
        seen = T0 - timedelta(days=days)
        db_session.add(Job(
            company="acme", req_id=f"y{i}", dedupe_key=f"acme:y{i}", title=title,
            url=f"https://careers.example.test/acme/y{i}", locations=["London, UK"],
            location_groups=["uk"], domains=[], workplace_type="onsite", level_band=band,
            level_confidence="confirmed", level_basis=basis, family="software_engineering",
            track="management", comp_currency="USD", status="open", in_scope=True,
            first_seen=seen, last_seen=seen, description_sections=[], required_years=years,
        ))
    await db_session.commit()


@pytest.mark.asyncio
async def test_level_not_placed_orders_by_years_and_an_unstated_number_lands_with_the_typical(api_client, years_board):
    titles, body = await _titles(api_client, "sort=relevance")
    assert titles == [
        # Placed, in their own order: the 15 years do not lift "Staff Engineer".
        "Staff Engineer, Ads", "Principal Engineer, Ads",
        # Not placed: most years first. A posting stating none is not low: it
        # lands with the typical posting (6 years), mixed with those asking for
        # 6 in the default order (newest first), above the one asking for 3.
        "Head of Infrastructure",
        "Engineering Manager, Payments", "Engineering Manager, Search",
        "Manager, Platform", "Engineering Manager, Data",
        "Manager, Mobile",
    ]
    assert body["placed_total"] == 2


@pytest.mark.asyncio
async def test_a_column_sort_never_orders_by_years(api_client, years_board):
    titles, _ = await _titles(api_client, "sort=first_seen&order=desc")
    assert titles == [title for title, *_ in YEARS_ROWS]


def test_the_intent_ranking_orders_level_not_placed_by_years_before_intent():
    sql = str(intent_ranked_stmt({"status": "open"}, [0.1, 0.2], limit=50, offset=0)
              .compile(dialect=postgresql.dialect()))
    order_by = sql.split("ORDER BY", 1)[1]
    assert order_by.index("jobs.level_basis") < order_by.index("jobs.required_years") < order_by.index("intent_distance")
    # An unstated number reads the typical one: the median over unplaced rows.
    assert "coalesce(jobs.required_years, (SELECT percentile_cont" in order_by
    assert "END DESC NULLS LAST, intent_distance" in order_by
