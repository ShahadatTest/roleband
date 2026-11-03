"""The posting-reality verdict.

Each case is a plausible way to get it wrong:

1. **One criterion is never enough.** Long listing alone would flag a third of
   the radar (Amazon's and Apple's long boards).
2. **No stronger claim than `possible` exists**, however much converges.
3. **Age counts from the earliest stated date**: an employer date older than our
   first sighting extends it; one moved later cannot shorten it. A posting in an
   effective lineage counts from the ROLE's start.
4. **One relisting is not scored twice.** A repost's own new date and a date
   moved at a reopen are part of the relisting, not a separate re-dating.
5. **A closed posting carries no verdict.**
6. **Listings are counted the way the writer counts.** `db/repo.py` bumps
   `repost_count` only together with a `reopened` event, so the fixtures carry
   both or neither; one return is two listings, never the three-listing sign.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from tracker.analytics.posting_reality import (
    CRITERIA,
    LONG_OPEN,
    REDATED,
    ListingEvidence,
    PostingFacts,
    classify,
    criteria_met,
    earliest_posted,
    listing_age,
    listing_start,
    role_age,
    role_start,
    standing_since,
)

NOW = datetime(2026, 9, 27, 12, 0, tzinfo=UTC)


def facts(*, returns: int = 0, **over) -> PostingFacts:
    """`returns` is how often the posting came back after closing: the writer's
    `repost_count`, and a `reopened` event each time."""
    base = dict(
        status="open", posted_at=NOW - timedelta(days=10), first_seen=NOW - timedelta(days=10),
        role_since=None, lineage_size=None, repost_count=returns, reopened=returns > 0,
    )
    base.update(over)
    # The writer's shape: read once, the current date is the first.
    base.setdefault("first_posted_at", base["posted_at"])
    return PostingFacts(**base)


def test_a_fresh_single_posting_meets_nothing():
    # No age of its own: the row's `listed_days` is the one a person reads.
    assert classify(facts(), NOW) == {"level": "none", "met": [], "criteria_total": 3, "listings": 1}


def test_long_listing_alone_is_not_enough():
    verdict = classify(facts(posted_at=NOW - timedelta(days=200), first_seen=NOW - timedelta(days=60)), NOW)
    assert verdict["met"] == ["long_open"] and verdict["level"] == "none"


def test_age_counts_from_the_earliest_stated_date():
    # Employer says 120 days; we first saw it 60 days ago (our history is short).
    older_employer = facts(posted_at=NOW - timedelta(days=120), first_seen=NOW - timedelta(days=60))
    assert standing_since(older_employer) == NOW - timedelta(days=120)
    # The employer moved its date to last week; we have watched it for 100 days.
    moved_later = facts(posted_at=NOW - timedelta(days=7), first_seen=NOW - timedelta(days=100))
    assert standing_since(moved_later) == NOW - timedelta(days=100), "a later date cannot shorten the listing"
    # Re-dated after we first read it: the FIRST date the employer gave still counts.
    re_dated = facts(first_posted_at=NOW - timedelta(days=120), posted_at=NOW - timedelta(days=7),
                     first_seen=NOW - timedelta(days=60))
    assert standing_since(re_dated) == NOW - timedelta(days=120)
    assert "long_open" in criteria_met(re_dated, NOW)
    # A repost whose role started before the posting itself did: role age.
    repost = facts(first_seen=NOW - timedelta(days=5), posted_at=NOW - timedelta(days=5),
                   role_since=NOW - timedelta(days=95), lineage_size=2)
    assert "long_open" in criteria_met(repost, NOW)
    assert "long_open" not in criteria_met(facts(first_seen=NOW - timedelta(days=5),
                                                 posted_at=NOW - timedelta(days=5)), NOW)


def test_the_long_open_edge_is_inclusive():
    assert "long_open" in criteria_met(facts(posted_at=NOW - LONG_OPEN, first_seen=NOW - LONG_OPEN), NOW)
    just_under = NOW - LONG_OPEN + timedelta(minutes=1)
    assert "long_open" not in criteria_met(facts(posted_at=just_under, first_seen=just_under), NOW)


def test_relisted_is_three_listings_counted_the_way_the_writer_counts():
    assert "relisted" in criteria_met(facts(lineage_size=3), NOW)
    assert "relisted" in criteria_met(facts(returns=2), NOW)
    # A repost that then came back once: its predecessor, it, it again.
    repost_returned = facts(lineage_size=2, returns=1)
    assert classify(repost_returned, NOW)["listings"] == 3
    assert "relisted" in criteria_met(repost_returned, NOW)
    # Two listings are ordinary, under a new requisition or the same one.
    assert "relisted" not in criteria_met(facts(lineage_size=2), NOW), "one repost is ordinary"
    one_return = facts(returns=1)
    assert classify(one_return, NOW)["listings"] == 2
    assert "relisted" not in criteria_met(one_return, NOW), "one return is two listings, not three"


def test_redated_is_measured_against_this_postings_own_first_sighting():
    # Watched for 40 days; the employer's date is now 20 days after we first saw it.
    redated = facts(first_seen=NOW - timedelta(days=40), posted_at=NOW - timedelta(days=20))
    assert "redated" in criteria_met(redated, NOW)
    # A repost: its own date equals its own first sighting, while the LINEAGE is
    # much older. That is the relisting, not a re-dating.
    repost = facts(first_seen=NOW - timedelta(days=5), posted_at=NOW - timedelta(days=5),
                   role_since=NOW - timedelta(days=60), lineage_size=3)
    assert criteria_met(repost, NOW) == ["relisted"]
    # A date moved at a reopen belongs to the relisting too.
    reopened = facts(first_seen=NOW - timedelta(days=40), posted_at=NOW - timedelta(days=20), returns=1)
    assert "redated" not in criteria_met(reopened, NOW)


def test_the_redated_edge_and_a_missing_employer_date():
    at_edge = facts(first_seen=NOW - timedelta(days=30), posted_at=NOW - timedelta(days=30) + REDATED)
    assert "redated" in criteria_met(at_edge, NOW)
    assert "redated" not in criteria_met(facts(posted_at=None), NOW)


def test_two_criteria_make_possible_and_three_still_only_possible():
    two = facts(posted_at=NOW - timedelta(days=150), first_seen=NOW - timedelta(days=60), returns=2)
    assert classify(two, NOW)["level"] == "possible"
    three = facts(first_seen=NOW - timedelta(days=120), posted_at=NOW - timedelta(days=20),
                  role_since=NOW - timedelta(days=130), lineage_size=4)
    verdict = classify(three, NOW)
    assert verdict["met"] == list(CRITERIA)
    assert verdict["level"] == "possible", "structural evidence never claims more"


def test_a_closed_posting_carries_no_verdict():
    assert classify(facts(status="closed", returns=5, posted_at=NOW - timedelta(days=300)), NOW) is None


def test_the_denominator_is_the_criteria_list():
    assert classify(facts(), NOW)["criteria_total"] == len(CRITERIA) == 3


# --------------------------------------------------------------------------- #
# The listing-age rule itself
# --------------------------------------------------------------------------- #


def _member(first_posted_days: int | None, first_seen_days: int, *, status: str = "open",
            closed_days: int | None = None) -> ListingEvidence:
    return ListingEvidence(
        first_posted_at=NOW - timedelta(days=first_posted_days) if first_posted_days is not None else None,
        first_seen=NOW - timedelta(days=first_seen_days),
        status=status,
        closed_at=NOW - timedelta(days=closed_days) if closed_days is not None else None,
    )


def test_the_headline_starts_at_the_earlier_of_the_first_date_and_our_sighting():
    assert listing_start(NOW - timedelta(days=90), NOW - timedelta(days=30)) == (
        NOW - timedelta(days=90), "employer",
    )
    # Later than our sighting: never the start.
    assert listing_start(NOW - timedelta(days=10), NOW - timedelta(days=30)) == (
        NOW - timedelta(days=30), "sighting",
    )
    assert listing_start(None, NOW - timedelta(days=30)) == (NOW - timedelta(days=30), "sighting")


def test_a_reopened_posting_counts_straight_through_to_now():
    """Closed for a while and back under the same requisition: the company never
    stopped trying, so the age runs from the first start, not the return."""
    since, days, basis = listing_age(
        None, NOW - timedelta(days=80), status="open", closed_at=None, now=NOW
    )
    assert (since, days, basis) == (NOW - timedelta(days=80), 80, "sighting")


def test_role_age_is_the_earliest_member_start_by_the_same_rule():
    members = [
        _member(None, 20),  # this posting, sighted 20 days ago
        _member(150, 100, status="closed", closed_days=40),  # employer-dated 150 days ago
        _member(10, 60, status="closed", closed_days=25),  # its later date is not its start
    ]
    assert role_start(members) == NOW - timedelta(days=150)
    assert role_age(members, now=NOW) == (NOW - timedelta(days=150), 150, 3)


def test_a_posting_alone_has_no_role_age():
    assert role_start([_member(30, 10)]) is None
    assert role_age([], now=NOW) is None


def test_a_role_with_every_posting_closed_stops_at_the_last_closing():
    members = [
        _member(None, 100, status="closed", closed_days=70),
        _member(None, 50, status="closed", closed_days=10),
    ]
    assert role_age(members, now=NOW) == (NOW - timedelta(days=100), 90, 2)


def test_the_first_posted_date_is_never_raised_and_ignores_implausible_dates():
    stored = NOW - timedelta(days=100)
    # A later date leaves the stored one.
    assert earliest_posted(stored, NOW - timedelta(days=5), read_at=NOW) == stored
    # An earlier one lowers it, from either field the source states.
    assert earliest_posted(stored, None, NOW - timedelta(days=130), read_at=NOW) == NOW - timedelta(days=130)
    # An epoch zero and a date a year ahead are parse accidents, not publish dates.
    epoch = datetime(1970, 1, 1, tzinfo=UTC)
    assert earliest_posted(stored, epoch, NOW + timedelta(days=365), read_at=NOW) == stored
    assert earliest_posted(None, epoch, read_at=NOW) is None
    # Tomorrow is a board a timezone ahead, still plausible.
    assert earliest_posted(None, NOW + timedelta(hours=20), read_at=NOW) == NOW + timedelta(hours=20)


# --------------------------------------------------------------------------- #
# Served on job detail, from facts the route already loads
# --------------------------------------------------------------------------- #

import pytest  # noqa: E402

from tests.company_contract_seed import company_job  # noqa: E402
from tracker.db.models import JobLifecycleEvent  # noqa: E402


@pytest.mark.asyncio
async def test_job_detail_serves_the_verdict_and_names_what_fired(api_client, db_session):
    now = datetime.now(UTC)
    # In the writer's shape (`db/repo.py`): each return after closing is one
    # `reopened` event and one more `repost_count`.
    standing = company_job("acme", "standing", first_seen=now - timedelta(days=60), last_seen=now,
                    posted_at=now - timedelta(days=150), repost_count=2)
    returned = company_job("acme", "returned", first_seen=now - timedelta(days=40), last_seen=now,
                    posted_at=now - timedelta(days=20), repost_count=1)
    closed = company_job("acme", "closed", status="closed", first_seen=now - timedelta(days=200),
                  last_seen=now - timedelta(days=1), posted_at=now - timedelta(days=300), repost_count=4)
    db_session.add_all([standing, returned, closed])
    await db_session.flush()
    for job, days_ago in ((standing, (50, 30)), (returned, (20,)), (closed, (150, 120, 90, 60))):
        db_session.add_all(
            JobLifecycleEvent(job_id=job.id, event_type="reopened", detail={},
                              created_at=now - timedelta(days=d))
            for d in days_ago
        )
    await db_session.commit()

    row = (await api_client.get(f"/api/jobs/{standing.id}")).json()
    body = row["posting_reality"]
    assert (body["level"], body["met"], body["criteria_total"], body["listings"]) == (
        "possible", ["long_open", "relisted"], 3, 3,
    )
    assert row["listed_days"] == 150, "from the employer's date, older than our first sighting"
    assert not {"listed_since", "listed_days"} & set(body), "the row's own age, not a second copy"

    # One return: two listings, not the three-listing sign. The date it moved
    # at the reopen is part of that return, not a re-dating either.
    back = (await api_client.get(f"/api/jobs/{returned.id}")).json()["posting_reality"]
    assert (back["level"], back["met"], back["listings"]) == ("none", [], 2)

    assert (await api_client.get(f"/api/jobs/{closed.id}")).json()["posting_reality"] is None


@pytest.mark.asyncio
async def test_every_board_row_carries_the_verdict_job_detail_serves(api_client, db_session):
    """The Board's sign is Job detail's verdict, not a second rule.

    `role-new` is 30 days old on its own, but its role was first listed 120
    days ago and three times: long open and relisted by the lineage alone,
    which the list must read in batch exactly as the detail route reads it.
    `relisted` reaches three listings through its own returns; `fresh` meets
    nothing; a closed posting carries no verdict on either surface."""
    from tracker.db.models import JobLineage

    now = datetime.now(UTC)
    ago = lambda d: now - timedelta(days=d)  # noqa: E731
    rows = {
        "role-old": company_job("acme", "role-old", status="closed", first_seen=ago(120), last_seen=ago(80),
                         closed_at=ago(80)),
        "role-mid": company_job("acme", "role-mid", status="closed", first_seen=ago(70), last_seen=ago(40),
                         closed_at=ago(40)),
        "role-new": company_job("acme", "role-new", first_seen=ago(30), last_seen=now),
        "relisted": company_job("acme", "relisted", first_seen=ago(100), last_seen=now, repost_count=2),
        "fresh": company_job("acme", "fresh", first_seen=ago(5), last_seen=now),
    }
    db_session.add_all(rows.values())
    await db_session.flush()
    lineage = JobLineage(company="acme", root_job_id=rows["role-old"].id, size=3, open_members=1,
                         first_seen=ago(120), last_seen=now)
    db_session.add(lineage)
    await db_session.flush()
    for seq, key in enumerate(("role-old", "role-mid", "role-new"), start=1):
        rows[key].lineage_id, rows[key].lineage_seq = lineage.id, seq
        rows[key].lineage_role = "original" if seq == 1 else "repost"
    db_session.add_all(
        JobLifecycleEvent(job_id=rows["relisted"].id, event_type="reopened", detail={}, created_at=ago(d))
        for d in (60, 30)
    )
    await db_session.commit()

    board = (await api_client.get("/api/jobs?company=acme&status=&limit=50")).json()["items"]
    served = {row["req_id"]: row["posting_reality"] for row in board}

    for key in rows:
        detail = (await api_client.get(f"/api/jobs/{rows[key].id}")).json()["posting_reality"]
        assert served[key] == detail, key
    assert (served["role-new"]["level"], served["role-new"]["met"]) == ("possible", ["long_open", "relisted"])
    assert (served["relisted"]["level"], served["relisted"]["listings"]) == ("possible", 3)
    assert served["fresh"]["level"] == "none"
    assert served["role-old"] is None and served["role-mid"] is None
