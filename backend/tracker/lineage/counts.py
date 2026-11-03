"""Shared lineage-aware predicates for the counting/metric call sites.

One definition of "is this a NEW job vs a repost successor" and one definition of
the effective age clock, so demand, velocity, /api/stats, the board filter, and the
serializer all agree. A job is "new" when it is standalone or the original of its
lineage; it is a repost/duplicate when it is a later member. Aging accrues across
the lineage via coalesce(lineage_first_seen, first_seen).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from sqlalchemy import and_, exists, or_, tuple_
from sqlalchemy.orm import aliased

from tracker.db.models import Job, JobPlaceSetMember

# SQL fragment for the effective first_seen, assuming the jobs table alias is `j`.
EFFECTIVE_FIRST_SEEN_SQL = "coalesce(j.lineage_first_seen, j.first_seen)"


_SELF_MEMBER = aliased(JobPlaceSetMember)
_PEER_MEMBER = aliased(JobPlaceSetMember)
_PEER = aliased(Job)


def place_set_outranked(*, eligible: Callable[[Any], list] | None = None):
    """ORM clause: another member of this posting's place set comes first.

    A place set is one role, so every count and the Board show it
    once, through its first member: the earliest `first_seen` (then id) among
    the members in the same status and scope as this one that pass
    `eligible`. A posting this is true for is a set's later member; one in no
    set is never outranked. The peer must share status and scope because the
    rebuild only runs between scans: a member that just closed, or one at a
    place out of scope, never hides the open, in-scope row the person can see.

    `eligible(peer)` returns the conditions a peer must meet to represent the
    set: the request's posting-level filters, built by the same function that
    filters the row (`db/queries/jobs.py::posting_conds`), so a filter selects
    the member that passes it instead of hiding the role behind an earlier
    member that fails it. None: every member is eligible, the
    unfiltered Board and every count.
    """
    peer = [
        _SELF_MEMBER.job_id == Job.id,
        _SELF_MEMBER.status == "auto",
        _PEER_MEMBER.set_id == _SELF_MEMBER.set_id,
        _PEER_MEMBER.status == "auto",
        _PEER_MEMBER.job_id != Job.id,
        _PEER.id == _PEER_MEMBER.job_id,
        _PEER.status == Job.status,
        _PEER.in_scope.is_not_distinct_from(Job.in_scope),
        tuple_(_PEER.first_seen, _PEER.id) < tuple_(Job.first_seen, Job.id),
    ]
    if eligible is not None:
        peer.extend(eligible(_PEER))
    return exists().where(and_(*peer))


def place_set_member_in(job_ids):
    """ORM clause: this posting, or another member of its place set, is in
    `job_ids` (a select of ids). Not for me on any member hides the role
    (a role-level rule, evaluated per set), so a place
    filter cannot bring it back through a sibling."""
    return or_(
        Job.id.in_(job_ids),
        exists().where(
            _SELF_MEMBER.job_id == Job.id,
            _SELF_MEMBER.status == "auto",
            _PEER_MEMBER.set_id == _SELF_MEMBER.set_id,
            _PEER_MEMBER.status == "auto",
            _PEER_MEMBER.job_id.in_(job_ids),
        ),
    )


def is_new_job_clause():
    """ORM clause: the job counts as a genuinely new opening."""
    return or_(Job.lineage_role.is_(None), Job.lineage_role == "original")


def is_repost_job_clause():
    """ORM clause: the job is a later member of a lineage (repost or duplicate)."""
    return Job.lineage_role.in_(("repost", "duplicate"))


def event_bucket(
    event_type: str,
    lineage_role: str | None,
    *,
    later_in_place_set: bool = False,
    new_listing: bool = False,
) -> str | None:
    """Route a lifecycle event to a demand counter, lineage-aware.

    A role's creation (`opened` by a scan, `added` by a scope change) is new
    demand only when the role is listed recently by the Board's rule
    (`new_listing`): a first read's find or a posting listed long before we
    stored it is not. On a repost/duplicate successor it is NOT new demand:
    it moves to the reposted bucket, which also collects `reopened`
    (same-req_id re-listing). A place set's later member is neither: the
    role is listed once, in several places, so its opening and re-listing
    are the first member's.
    """
    if later_in_place_set and event_type in ("opened", "added", "reopened"):
        return None
    if event_type in ("opened", "added"):
        if lineage_role in ("repost", "duplicate"):
            return "reposted_count"
        return "new_count" if new_listing else None
    if event_type == "closed":
        return "closed_count"
    if event_type == "reopened":
        return "reposted_count"
    return None
