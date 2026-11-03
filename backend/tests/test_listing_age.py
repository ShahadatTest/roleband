"""How long a posting has been listed: one rule, served and sorted.

"Days open: 62" beside "Listed for 164 days" can both be true: `days_open`
counts from OUR first sighting, which our history caps, and the
standing-posting check counts from the earliest date either side states. A
person reads one age, so every row carries `listed_days` from
`posting_reality.listing_start`, and the Board's Age sort orders by the same
rule in SQL. `days_open` stays our own clock.

The rule reads the posting's own evidence: the earlier of the employer's FIRST
published date (`first_posted_at`, never raised) and our first sighting of
this posting. The lineage does not move the headline, and each row says whose
date it starts from (`listed_basis`).
"""

from datetime import UTC, datetime, timedelta

import pytest

from tests.factories import make_job
from tracker.api.serializers.jobs import serialize_job

NOW = datetime.now(UTC)


def _ago(days: int) -> datetime:
    # An hour of slack so a whole-day count cannot land on a boundary.
    return NOW - timedelta(days=days, hours=1)


def _served(**over) -> dict:
    return serialize_job(make_job("age", **over))


def test_an_older_employer_date_is_the_listing_age_and_our_clock_stays_ours():
    row = _served(posted_at=_ago(164), first_seen=_ago(62))

    assert row["listed_days"] == 164
    assert row["listed_since"] == _ago(164)
    assert row["days_open"] == 62


def test_an_employer_date_moved_later_cannot_shorten_the_age():
    # A re-dated posting: the employer's date is newer than our first sighting.
    assert _served(posted_at=_ago(3), first_seen=_ago(40))["listed_days"] == 40


def test_a_repost_keeps_its_own_headline_age():
    """The headline is the posting's own evidence.
    A repost under a new requisition is 5 days old however old its lineage is;
    the lineage speaks through Job detail's role age instead."""
    row = _served(posted_at=_ago(5), first_seen=_ago(5), lineage_first_seen=_ago(118))
    assert (row["listed_days"], row["listed_basis"]) == (5, "sighting")


def test_the_basis_names_whose_date_the_age_starts_from():
    assert _served(posted_at=_ago(164), first_seen=_ago(62))["listed_basis"] == "employer"
    assert _served(posted_at=None, first_seen=_ago(21))["listed_basis"] == "sighting"
    # An employer date later than our sighting is never the start.
    assert _served(posted_at=_ago(3), first_seen=_ago(40))["listed_basis"] == "sighting"


def test_a_re_dated_posting_keeps_the_employer_s_first_date():
    """The employer moved its date from 120 days ago to last week. `posted_at`
    says last week; the age still runs from the first date they gave."""
    row = _served(first_posted_at=_ago(120), posted_at=_ago(7), first_seen=_ago(60))
    assert (row["listed_days"], row["listed_basis"]) == (120, "employer")
    assert row["posted_at"] == _ago(7), "the current date is still served as the employer's"


def test_without_an_employer_date_the_age_is_our_sighting():
    assert _served(posted_at=None, first_seen=_ago(21))["listed_days"] == 21


def test_a_closed_posting_stops_counting_when_it_closed():
    row = _served(
        posted_at=_ago(100), first_seen=_ago(50), status="closed", closed_at=_ago(30)
    )
    assert row["listed_days"] == 70


@pytest.mark.asyncio
async def test_the_age_sort_orders_by_the_age_each_row_shows(api_client, db_session):
    """A sort on our sighting clock would rank the posting the employer dated
    164 days ago BELOW one we have merely watched for 100."""
    db_session.add_all([
        make_job("employer-dated", posted_at=_ago(164), first_seen=_ago(62)),
        make_job("watched-long", posted_at=None, first_seen=_ago(100)),
        make_job("fresh", posted_at=_ago(10), first_seen=_ago(5)),
    ])
    await db_session.commit()

    response = await api_client.get("/api/jobs?sort=days_open&order=desc")

    assert response.status_code == 200, response.text
    items = response.json()["items"]
    assert [row["req_id"] for row in items] == ["employer-dated", "watched-long", "fresh"]
    assert [row["listed_days"] for row in items] == [164, 100, 10]

    asc = (await api_client.get("/api/jobs?sort=days_open&order=asc")).json()["items"]
    assert [row["req_id"] for row in asc] == ["fresh", "watched-long", "employer-dated"]


@pytest.mark.asyncio
async def test_the_age_sort_reads_the_first_date_not_the_current_one(api_client, db_session):
    """A posting re-dated to last week sorts by the date it was first given,
    as its row shows; sorting by `posted_at` put it among the newest."""
    db_session.add_all([
        make_job("re-dated", first_posted_at=_ago(150), posted_at=_ago(7), first_seen=_ago(60)),
        make_job("steady", posted_at=_ago(90), first_seen=_ago(60)),
    ])
    await db_session.commit()

    items = (await api_client.get("/api/jobs?sort=days_open&order=desc")).json()["items"]

    assert [(row["req_id"], row["listed_days"]) for row in items] == [("re-dated", 150), ("steady", 90)]


@pytest.mark.asyncio
async def test_posted_within_reads_the_age_each_row_shows(api_client, db_session):
    """"Posted within 7 days" must not match a posting when EITHER date is
    recent, or one the employer dated 90 days ago but re-dated last week, or
    one we first saw last week, shows under it beside "Listed for 90 days"."""
    db_session.add_all([
        make_job("re-dated", first_posted_at=_ago(90), posted_at=_ago(3), first_seen=_ago(40)),
        make_job("new-to-us", posted_at=_ago(60), first_seen=_ago(2)),
        make_job("really-new", posted_at=_ago(4), first_seen=_ago(3)),
        make_job("undated-new", posted_at=None, first_seen=_ago(5)),
        make_job("undated-old", posted_at=None, first_seen=_ago(20)),
    ])
    await db_session.commit()

    items = (await api_client.get("/api/jobs?posted_within_days=7&sort=days_open&order=desc")).json()["items"]

    assert [(row["req_id"], row["listed_days"]) for row in items] == [("undated-new", 5), ("really-new", 4)]
    assert all(row["listed_days"] <= 7 for row in items)

    month = (await api_client.get("/api/jobs?posted_within_days=30")).json()["items"]
    assert {row["req_id"] for row in month} == {"really-new", "undated-new", "undated-old"}


@pytest.mark.asyncio
async def test_the_closed_board_sorts_by_how_long_each_posting_was_listed(api_client, db_session):
    """A closed row's age stops at its closing. Sorted by the start alone, the
    posting listed for 10 days two hundred days ago outranked one listed for
    49 days until yesterday."""
    db_session.add_all([
        make_job("short-long-ago", posted_at=_ago(200), first_seen=_ago(200), status="closed",
             closed_at=_ago(190)),
        make_job("long-recent", posted_at=_ago(50), first_seen=_ago(50), status="closed", closed_at=_ago(1)),
        make_job("still-open", posted_at=_ago(30), first_seen=_ago(30)),
    ])
    await db_session.commit()

    desc = (await api_client.get("/api/jobs?status=closed&sort=days_open&order=desc")).json()["items"]

    assert [row["req_id"] for row in desc] == ["long-recent", "short-long-ago"]
    assert [row["listed_days"] for row in desc] == [49, 10]

    asc = (await api_client.get("/api/jobs?status=closed&sort=days_open&order=asc")).json()["items"]
    assert [row["req_id"] for row in asc] == ["short-long-ago", "long-recent"]

    # Open rows are still counted to now.
    both = (await api_client.get("/api/jobs?status=&sort=days_open&order=desc")).json()["items"]
    assert [row["req_id"] for row in both] == ["long-recent", "still-open", "short-long-ago"]
