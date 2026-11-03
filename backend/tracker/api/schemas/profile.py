"""Response contracts for the pay floor and pursuit routes.

`GET`, `PUT` and `DELETE /api/profile/pay-floor`, `GET /api/pursuits` and
`PUT /api/jobs/{job_id}/pursuit`. A pursuit is `JobPursuit`, the row job detail
sends; the list adds the opportunity it tracks.
"""

from __future__ import annotations

from pydantic import Field

from tracker.api.schemas.base import Built
from tracker.api.schemas.jobs import JobPursuit
from tracker.api.schemas.text_class import text

# --- pay floor ------------------------------------------------------------ #


class PayFloor(Built):
    """The lowest yearly base pay the user would consider."""

    amount: int
    currency: str


class PayFloorResponse(Built):
    """`GET/PUT/DELETE /api/profile/pay-floor`: null when unset."""

    pay_floor: PayFloor | None


# --- pursuits -------------------------------------------------------------- #


class PursuitOpportunity(Built):
    title: str = Field(json_schema_extra=text("content"))
    company: str
    status: str
    url: str


class PursuitListItem(JobPursuit):
    """A pursuit with the opportunity it tracks."""

    opportunity: PursuitOpportunity


class PursuitListResponse(Built):
    """`GET /api/pursuits`: highest priority first, then most recently updated."""

    pursuits: list[PursuitListItem]


class PursuitWriteResponse(Built):
    """`PUT /api/jobs/{job_id}/pursuit`: the pursuit as written, without its opportunity."""

    pursuit: JobPursuit
