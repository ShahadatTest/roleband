"""Is this posting likely a standing one? A hedged verdict, structural only.

Some postings stay listed without a live hire behind them: evergreen
requisitions, pipelines kept warm, a role re-dated to look fresh. A candidate
deciding where to spend an application wants to know. This is the structural
half of a "ghost posting" signal, the half a single-person, local tool can
support honestly.

**Three structural criteria**, each a fact we observed, never a guess:

- `long_open`: listed for at least `LONG_OPEN` (90 days), counted by ROLE age
  when the posting has an effective lineage (the earliest listing start among
  its members), else by its own headline listing age. A long search
  is the signal this sign exists to catch, so a repost under a new requisition
  inherits its predecessors' time here, and only here: the headline stays the
  posting's own evidence. Our own clock is capped at the days we have
  watched; the employer's date, when older, is the true lower bound. A date the employer moved LATER cannot shorten it, because
  `first_posted_at` keeps the earliest date ever given.
- `relisted`: listed at least `RELISTED_LISTINGS` (3) times: each posting of
  its lineage once, plus each time this posting came back after closing (it
  was absent from a complete listing, since closure requires one, then
  returned; `repost_count`). One return is two listings, as ordinary as one
  repost under a new requisition, so it does not fire alone: "Listed 2 times"
  never shows under a sign that means three or more.
- `redated`: the employer's date moved at least `REDATED` (14 days) past OUR
  first sighting of THIS posting, while it stayed listed (no reopen). Measured
  against the posting's own `first_seen`, not the lineage's: a repost carries
  its own new date, and counting that here would score one relisting twice. A date
  that moved at a reopen is part of the relisting, so it is excluded for the
  same reason.

**The verdict**: `possible` when at least `CONVERGENCE` (2) criteria fire,
otherwise `none`. There is no stronger level: a `likely` verdict needs OUTCOME
evidence (applicants who heard nothing, from at least two people), which one
person's tool cannot collect, and structural evidence alone must never claim it.
Long listing alone is not enough: large employers keep long-running boards, and
a single criterion would call a large share of the radar stale.

A closed posting carries no verdict: it is already down, so there is nothing
left to warn about. Computed on read and never stored, because it depends on
the clock; nothing here reads the clock.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

from tracker.schema import Arrival

LONG_OPEN = timedelta(days=90)
REDATED = timedelta(days=14)
RELISTED_LISTINGS = 3
CONVERGENCE = 2

#: The criteria, in the order a reader should meet them. `criteria_total` is
#: derived from this tuple so the served "2 of 3" can never disagree with it.
CRITERIA = ("long_open", "relisted", "redated")

POSSIBLE = "possible"
NONE = "none"


#: What a listing age counts from: the employer's own date, or our sighting.
Basis = Literal["employer", "sighting"]

#: Before this, a posting date is a parse accident (an epoch zero, a two-digit
#: year), not an employer's statement.
EARLIEST_PLAUSIBLE = datetime(2000, 1, 1, tzinfo=UTC)
#: How far past the moment we read it a stated date may lie: a board a timezone
#: ahead dates a posting "tomorrow". Anything later is not a publish date.
FUTURE_SLACK = timedelta(days=1)


@dataclass(frozen=True)
class PostingFacts:
    """What the verdict reads, all stored facts about one posting.

    `posted_at` is the employer's CURRENT date (what `redated` compares);
    `first_posted_at` the earliest date they ever gave (what the age counts
    from). `role_since` is the role's start over its effective lineage, None
    for a posting with no earlier or later posting counted as the same role."""

    status: str
    posted_at: datetime | None
    first_posted_at: datetime | None
    first_seen: datetime
    role_since: datetime | None
    lineage_size: int | None
    repost_count: int
    reopened: bool
    #: Other postings of the role open at this posting's own place (a place
    #: set's `relisted` members): each is the role listed again.
    listed_here: int = 0


@dataclass(frozen=True)
class ListingEvidence:
    """One posting's own dated facts: enough to state its listing age."""

    first_posted_at: datetime | None
    first_seen: datetime
    status: str
    closed_at: datetime | None


def plausible_posted(value: datetime | None, read_at: datetime) -> datetime | None:
    """A stated posting date, or None when it cannot be one: before
    `EARLIEST_PLAUSIBLE`, or more than `FUTURE_SLACK` after the moment we read
    it. The migration `b8e41f6c2d57` freezes the same bounds in SQL."""
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    if value < EARLIEST_PLAUSIBLE or value > read_at + FUTURE_SLACK:
        return None
    return value


def earliest_posted(
    stored: datetime | None, *stated: datetime | None, read_at: datetime
) -> datetime | None:
    """`first_posted_at` after one read: the earliest of what is stored and
    every plausible date the source states now. Never raised: an employer who
    moves the date later has not unpublished the earlier one."""
    candidates = [d for d in (plausible_posted(s, read_at) for s in stated) if d is not None]
    if stored is not None:
        candidates.append(stored)
    return min(candidates) if candidates else None


def listing_start(first_posted_at: datetime | None, first_seen: datetime) -> tuple[datetime, Basis]:
    """Where a posting's headline listing age starts, and on whose evidence.

    The one listing-age rule: the earlier of
    the employer's first published date and our first sighting of THIS
    posting. An employer date later than our sighting is never the start; it
    is a re-dating, recorded as a `redated` event. The lineage does not move
    the headline; it speaks through `role_start`. Every surface reads it: the
    serializer's `listed_days`, the agent tools, the history route and the
    Board's Age sort, whose SQL twin is `db.queries.jobs._LISTED_SINCE`
    (`LEAST` skips a NULL `first_posted_at` exactly as this does).
    """
    if first_posted_at is not None and first_posted_at < first_seen:
        return first_posted_at, "employer"
    return first_seen, "sighting"


def listing_age(
    first_posted_at: datetime | None,
    first_seen: datetime,
    *,
    status: str,
    closed_at: datetime | None,
    now: datetime,
) -> tuple[datetime, int, Basis]:
    """`(listed_since, listed_days, basis)` as a person reads them: from
    `listing_start` to now, or to its closing for a closed posting.
    `db.queries.jobs._LISTED_FOR` is the sort's twin. A reopen under the same
    requisition counts straight through: the company never stopped trying."""
    since, basis = listing_start(first_posted_at, first_seen)
    until = closed_at if status != "open" and closed_at else now
    return since, max(0, (until - since).days), basis


#: A role is new while the age its row shows is at most this many whole days.
NEW_LISTING_DAYS = 2
NEW_LISTING_WINDOW = timedelta(days=NEW_LISTING_DAYS + 1)


def is_new_listing(
    first_posted_at: datetime | None,
    first_seen: datetime,
    *,
    arrival: str | None,
    status: str,
    lineage_role: str | None,
    now: datetime,
) -> bool:
    """Whether the row lights as new: an open posting, not a repost of an
    earlier one, whose `listing_start` is under `NEW_LISTING_WINDOW` old.

    A sighting dates a posting only when the company was already read
    (`schema.Arrival`): a first read's find is new on the employer's date
    alone, so an undated one never is. NULL `arrival` takes the sighting at
    its word. The SQL twin is `db.queries.jobs.new_listing_clause`, which the
    New view and every count of new roles read."""
    if status != "open" or lineage_role not in (None, "original"):
        return False
    since, basis = listing_start(first_posted_at, first_seen)
    if basis == "sighting" and arrival == Arrival.FIRST_READ:
        return False
    return now - since < NEW_LISTING_WINDOW


def role_start(members: Sequence[ListingEvidence]) -> datetime | None:
    """The role's start: the earliest listing start among the postings of its
    lineage, each by the headline rule. None for fewer than two members: a
    posting alone has no role age apart from its own.

    The caller passes EFFECTIVE members only (`jobs.lineage_id` is assigned
    over `lineage.detect.EFFECTIVE_LINK_SQL`), so a pending suspected link
    never moves this."""
    if len(members) < 2:
        return None
    return min(listing_start(m.first_posted_at, m.first_seen)[0] for m in members)


def role_age(members: Sequence[ListingEvidence], *, now: datetime) -> tuple[datetime, int, int] | None:
    """`(role_since, role_days, postings)`: from `role_start` to now while any
    member is open, else to the last member's closing."""
    since = role_start(members)
    if since is None:
        return None
    if any(m.status == "open" for m in members):
        until = now
    else:
        until = max((m.closed_at for m in members if m.closed_at is not None), default=now)
    return since, max(0, (until - since).days), len(members)


def standing_since(facts: PostingFacts) -> datetime:
    """What `long_open` counts from: the role's start when it has one, else
    the posting's own headline start."""
    if facts.role_since is not None:
        return facts.role_since
    return listing_start(facts.first_posted_at, facts.first_seen)[0]


def listings(facts: PostingFacts) -> int:
    """How many times this role has been listed, counted the way the writer
    counts: each posting of its lineage once, plus each time THIS posting came
    back after closing (`repost_count`, which `db/repo.py` increments only
    together with a `reopened` event), plus each other posting of the role
    open at this posting's place (`listed_here`: a place set's `relisted`
    members; a set's postings at OTHER places are one listing per
    place, not a relisting). A lineage member's own returns are not loaded,
    so this is a lower bound."""
    return (facts.lineage_size or 1) + facts.repost_count + facts.listed_here


def criteria_met(facts: PostingFacts, now: datetime) -> list[str]:
    met = []
    if now - standing_since(facts) >= LONG_OPEN:
        met.append("long_open")
    if listings(facts) >= RELISTED_LISTINGS:
        met.append("relisted")
    if (
        facts.posted_at is not None
        and not facts.reopened
        and facts.posted_at - facts.first_seen >= REDATED
    ):
        met.append("redated")
    return met


def classify(facts: PostingFacts, now: datetime) -> dict | None:
    """The verdict and its workings, or `None` for a closed posting."""
    if facts.status != "open":
        return None
    met = criteria_met(facts, now)
    return {
        "level": POSSIBLE if len(met) >= CONVERGENCE else NONE,
        "met": met,
        "criteria_total": len(CRITERIA),
        "listings": listings(facts),
    }
