"""What two postings may be to each other: one rule for every writer.

The verdict commands, the manual twin link and the detector all ask the
same three questions, so no writer can join two companies, orient equal
first-seen times by argument order, or write over a pair a person decided:

- one company: a lineage, a twin and a place set are each one company's;
- orientation: the earlier posting by `(first_seen, id)` is the prior, the
  projection's own order (`project.build_projection`), so the edge and the
  roles it projects cannot disagree;
- a person's word stands: a twin-queue "Related roles" (twin confirmed) or
  "Different" (twin rejected as different) says the pair is not one opening,
  and a lineage or twin row a person decided is never rewritten by a writer
  that is not a verdict (the verdict commands, with their Undo, are the only
  way to change a decision).
"""

from __future__ import annotations

from typing import Protocol

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from tracker.db.models import JobTwinLink

#: SQL over a twin link aliased `t`: a person said the pair is NOT one opening.
#: A twin rejected as "duplicate" is the opposite (the person confirmed a
#: lineage), so it is not here.
TWIN_SAYS_NOT_ONE_OPENING_SQL = (
    "(t.status = 'confirmed' "
    "OR (t.status = 'rejected' AND t.evidence->>'review_outcome' = 'different'))"
)


class Posting(Protocol):
    id: int
    first_seen: object
    company: str


class PairRefused(ValueError):
    """The pair cannot take the relation asked of it. `status` is the HTTP
    status a route answers: 400 for a shape no posting pair can have, 409 for
    a pair a person already decided otherwise."""

    def __init__(self, status: int, detail: str) -> None:
        super().__init__(detail)
        self.status = status
        self.detail = detail


def prior_and_later(a: Posting, b: Posting) -> tuple[Posting, Posting]:
    """(prior, later) by `(first_seen, id)`: ties fall to the id, never to
    which posting a caller named first."""
    return (a, b) if (a.first_seen, a.id) <= (b.first_seen, b.id) else (b, a)


def require_one_company(a: Posting, b: Posting, relation: str) -> None:
    if a.id == b.id:
        raise PairRefused(400, "cannot link a job to itself")
    if a.company != b.company:
        raise PairRefused(400, f"a {relation} links postings of one company")


async def human_twin_row(session: AsyncSession, a_id: int, b_id: int) -> JobTwinLink | None:
    """The pair's twin row when a person decided it (any orientation)."""
    return (
        await session.scalars(
            select(JobTwinLink).where(
                or_(
                    (JobTwinLink.job_a_id == a_id) & (JobTwinLink.job_b_id == b_id),
                    (JobTwinLink.job_a_id == b_id) & (JobTwinLink.job_b_id == a_id),
                ),
                JobTwinLink.status != "pending",
            )
        )
    ).first()
