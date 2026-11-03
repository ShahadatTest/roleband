"""A posting's listing history and its role age, read on demand.

The headline listing age is one number from one rule
(`analytics.posting_reality.listing_start`). This module answers the question
behind it: every dated fact about the posting, oldest first, and which other
postings count as the same role. Job detail's `role_since` and the history
route and the agent's `listing_history` tool all read it, so no surface
assembles its own.

What counts, and what does not:

- **Role age** is over the posting's lineage, and `jobs.lineage_id` is
  assigned over EFFECTIVE links only (`lineage.detect.EFFECTIVE_LINK_SQL`:
  auto and not rejected, or confirmed). A pending suspected link is listed in
  `unconfirmed` and moves no number.
- **A reopen under the same requisition counts straight through**: the headline
  runs from the first start, and the closing and the return are events.
- **A re-dating is a fact, never a start**: `redated` events carry both dates.
- **Edits collapse to one event per field, and only the employer's fields
  count** (`POSTING_FIELDS`): `changed` events also record our own estimate
  refreshes, which are not the posting's history.

One query per concern and none per member: the job, its lineage members, the
links among them, its lifecycle events, and its pending suspected links.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import case, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from tracker.analytics.posting_reality import ListingEvidence, listing_age, listing_start, role_age
from tracker.db.models import Job, JobLifecycleEvent, JobLineageLink
from tracker.lineage.detect import EFFECTIVE_LINK_SQL

#: Tie-break for events at the same instant, in the order a reader should
#: meet them: what the employer said, then what we saw, then what changed.
_KIND_ORDER = (
    "employer_published",
    "earlier_posting",
    "first_seen",
    "redated",
    "edited",
    "closed",
    "reopened",
    "later_posting",
    "last_seen",
)

#: The lifecycle events the history shows as themselves. `opened` and
#: `added` are the first sighting, which `first_seen` already states.
_PASSED_THROUGH = ("closed", "reopened")


@dataclass(frozen=True)
class Member:
    """One posting of a lineage, with what its listing start needs."""

    id: int
    req_id: str
    title: str
    first_posted_at: datetime | None
    first_seen: datetime
    status: str
    closed_at: datetime | None

    @property
    def evidence(self) -> ListingEvidence:
        return ListingEvidence(self.first_posted_at, self.first_seen, self.status, self.closed_at)


async def lineage_members(session: AsyncSession, lineage_id: int | None) -> list[Member]:
    """Every posting of a lineage, in one query. Empty for a standalone posting."""
    if lineage_id is None:
        return []
    rows = (
        await session.execute(
            select(
                Job.id, Job.req_id, Job.title, Job.first_posted_at, Job.first_seen,
                Job.status, Job.closed_at,
            ).where(Job.lineage_id == lineage_id)
        )
    ).all()
    return [Member(*row) for row in rows]


def role_of(members: Sequence[Member], now: datetime) -> dict | None:
    """`{since, days, postings}`, or None when there is no other posting."""
    age = role_age([m.evidence for m in members], now=now)
    if age is None:
        return None
    since, days, postings = age
    return {"since": since, "days": days, "postings": postings}


def _event(at: datetime, kind: str, **fields: object) -> dict:
    return {
        "at": at, "kind": kind, "from_at": None, "to_at": None, "field": None, "count": None,
        "job_id": None, "req_id": None, "title": None, "until": None, "link": None,
        **fields,
    }


#: The fields a `changed` event can name that the EMPLOYER changed: its title and
#: its stated pay. `comp_median` is our estimate, and `level_band` / `family`
#: are our reading of the title; a refresh of either is not the posting's
#: history.
POSTING_FIELDS = frozenset({"title", "disclosed_base"})


def _changed_fields(detail: dict) -> list[str]:
    """The employer's fields a `changed` event names. The writer keys the detail
    by field (`{"title": {"from", "to"}}`); a detail naming one `field` is read
    too."""
    named = detail.get("field")
    fields = [named] if isinstance(named, str) else [str(key) for key in detail]
    return [field for field in fields if field in POSTING_FIELDS]


def _parse(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


async def _member_links(session: AsyncSession, job_id: int, member_ids: list[int]) -> dict[int, str]:
    """For each other member, the machine or human state of the effective link
    that ties it in: the direct link to this posting when there is one, else
    the link through which it joined the chain."""
    rows = (
        await session.execute(
            select(JobLineageLink.job_id, JobLineageLink.prior_job_id, JobLineageLink.status)
            .where(
                text(EFFECTIVE_LINK_SQL),
                JobLineageLink.job_id.in_(member_ids),
                JobLineageLink.prior_job_id.in_(member_ids),
            )
            .order_by(JobLineageLink.id)
        )
    ).all()
    # Rank 0: linked to this posting directly. 1: the member is the newer side,
    # the link that brought it into the chain. 2: any other link touching it.
    best: dict[int, tuple[int, str]] = {}
    for newer, prior, status in rows:
        link = "confirmed" if status == "confirmed" else "auto"
        for member, other in ((newer, prior), (prior, newer)):
            if member == job_id:
                continue
            rank = 0 if other == job_id else 1 if member == newer else 2
            if member not in best or rank < best[member][0]:
                best[member] = (rank, link)
    return {member: link for member, (_rank, link) in best.items()}


async def listing_history(session: AsyncSession, job_id: int, now: datetime) -> dict | None:
    """The `ListingHistoryResponse` payload for one posting, or None if unknown."""
    job = await session.get(Job, job_id)
    if job is None:
        return None

    since, days, basis = listing_age(
        job.first_posted_at, job.first_seen, status=job.status, closed_at=job.closed_at, now=now
    )
    own_start = since
    events: list[dict] = []
    if job.first_posted_at is not None:
        events.append(_event(job.first_posted_at, "employer_published"))
    events.append(_event(job.first_seen, "first_seen"))

    lifecycle = (
        await session.execute(
            select(JobLifecycleEvent.event_type, JobLifecycleEvent.detail, JobLifecycleEvent.created_at)
            .where(JobLifecycleEvent.job_id == job_id)
            .order_by(JobLifecycleEvent.created_at, JobLifecycleEvent.id)
        )
    ).all()
    edits: dict[str, tuple[int, datetime]] = {}
    for kind, detail, at in lifecycle:
        if kind in _PASSED_THROUGH:
            events.append(_event(at, kind))
        elif kind == "redated":
            events.append(_event(
                at, "redated",
                from_at=_parse((detail or {}).get("from")), to_at=_parse((detail or {}).get("to")),
            ))
        elif kind == "changed":
            for field in _changed_fields(detail or {}):
                count, latest = edits.get(field, (0, at))
                edits[field] = (count + 1, max(latest, at))
    for field, (count, latest) in edits.items():
        events.append(_event(latest, "edited", field=field, count=count))

    members = await lineage_members(session, job.lineage_id)
    role = role_of(members, now)
    others = [m for m in members if m.id != job.id] if role is not None else []
    links = await _member_links(session, job.id, [m.id for m in members]) if others else {}
    for member in others:
        start, _basis = listing_start(member.first_posted_at, member.first_seen)
        events.append(_event(
            start, "earlier_posting" if start < own_start else "later_posting",
            job_id=member.id, req_id=member.req_id, title=member.title,
            until=member.closed_at if member.status != "open" else None,
            link=links.get(member.id, "auto"),
        ))

    if job.status == "open":
        events.append(_event(job.last_seen, "last_seen"))
    events.sort(key=lambda e: (e["at"], _KIND_ORDER.index(e["kind"])))

    return {
        "headline": {"since": since, "days": days, "basis": basis},
        "role": role,
        "events": events,
        "unconfirmed": await _unconfirmed(session, job.id, {m.id for m in members}),
    }


async def _unconfirmed(session: AsyncSession, job_id: int, counted: set[int]) -> list[dict]:
    """Pending suspected links touching this posting, either side: possibly the
    same role, not counted. A posting already counted through an effective
    path is left out, so nothing is listed both as counted and as not."""
    other_id = case(
        (JobLineageLink.job_id == job_id, JobLineageLink.prior_job_id), else_=JobLineageLink.job_id
    )
    rows = (
        await session.execute(
            select(
                JobLineageLink.id, Job.id, Job.req_id, Job.title, Job.first_posted_at, Job.first_seen,
            )
            .join(Job, Job.id == other_id)
            .where(
                or_(JobLineageLink.job_id == job_id, JobLineageLink.prior_job_id == job_id),
                JobLineageLink.confidence == "suspected",
                JobLineageLink.status == "pending",
            )
            .order_by(JobLineageLink.id)
        )
    ).all()
    return [
        {
            "link_id": link_id, "job_id": other, "req_id": req_id, "title": title,
            "listed_since": listing_start(first_posted_at, first_seen)[0],
        }
        for link_id, other, req_id, title, first_posted_at, first_seen in rows
        if other not in counted
    ]
