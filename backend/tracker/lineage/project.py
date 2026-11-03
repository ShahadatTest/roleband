"""Pure projection: effective links -> per-job lineage assignment.

Union-find over the EFFECTIVE links (the caller filters by the effective-link
predicate before passing them in), producing one LineageProjection per component
of size >= 2. Standalone jobs get no lineage. Fully DB-free so the whole graph
logic is unit-testable; ``rebuild_lineage_projection`` in detect.py is the thin
wrapper that reads links + job facts and writes the columns back.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass(frozen=True)
class LinkFact:
    job_id: int          # newer posting
    prior_job_id: int    # older posting
    relation: str        # repost | duplicate
    human: bool = False  # a person confirmed it (status `confirmed`)
    decided_at: datetime | None = None   # when the person did
    score: float | None = None           # the detector's, for a machine link


_NEVER = datetime.min.replace(tzinfo=UTC)


def _precedence(link: LinkFact) -> tuple:
    """Higher wins. A person's link before a machine's; between two of a
    person's, the later decision; between machine links, the higher score;
    then the lower prior id, so the choice is a total order on the set of
    links and never depends on the order they were read in."""
    return (
        link.human,
        link.decided_at or _NEVER,
        link.score if link.score is not None else float("-inf"),
        -link.prior_job_id,
    )


def choose_predecessors(
    links: list[LinkFact], jobs: dict[int, JobFact] | None = None
) -> dict[int, LinkFact]:
    """Each job's one projected predecessor.

    A lineage is a chain: one opening, listed again. A job with several
    effective inbound links (a person's confirmation beside a machine link, a
    twin-queue "duplicate" beside an earlier link) projects the one that
    `_precedence` ranks first; the others join nothing, so a co-predecessor
    is never made a repost of a role it is not. An edge to a job outside
    `jobs` (dangling) or to itself is no candidate. The lineage stack shows
    the same choice, so a member's shown link is the one that placed it.
    """
    chosen: dict[int, LinkFact] = {}
    for link in links:
        if link.job_id == link.prior_job_id:
            continue
        if jobs is not None and (link.job_id not in jobs or link.prior_job_id not in jobs):
            continue
        best = chosen.get(link.job_id)
        if best is None or _precedence(link) > _precedence(best):
            chosen[link.job_id] = link
    return chosen


@dataclass(frozen=True)
class JobFact:
    job_id: int
    company: str
    first_seen: datetime
    last_seen: datetime
    status: str          # open | closed


@dataclass(frozen=True)
class Member:
    job_id: int
    seq: int
    role: str            # original | repost | duplicate


@dataclass(frozen=True)
class LineageProjection:
    root_job_id: int
    company: str
    size: int
    open_members: int
    first_seen: datetime
    last_seen: datetime
    members: list[Member] = field(default_factory=list)
    oversized: bool = False


def _find(parent: dict[int, int], x: int) -> int:
    root = x
    while parent[root] != root:
        root = parent[root]
    while parent[x] != root:  # path compression
        parent[x], x = root, parent[x]
    return root


def build_projection(
    links: list[LinkFact],
    jobs: dict[int, JobFact],
    *,
    max_size: int = 6,
) -> list[LineageProjection]:
    parent: dict[int, int] = {jid: jid for jid in jobs}

    chosen = choose_predecessors(links, jobs)
    inbound: dict[int, str] = {}
    for job_id in sorted(chosen):
        link = chosen[job_id]
        inbound[job_id] = link.relation
        ra, rb = _find(parent, link.job_id), _find(parent, link.prior_job_id)
        if ra != rb:
            parent[ra] = rb

    components: dict[int, list[int]] = {}
    for jid in jobs:
        components.setdefault(_find(parent, jid), []).append(jid)

    projections: list[LineageProjection] = []
    for member_ids in components.values():
        if len(member_ids) < 2:
            continue
        ordered = sorted(member_ids, key=lambda j: (jobs[j].first_seen, j))
        members = [
            Member(
                job_id=jid,
                seq=i + 1,
                role="original" if i == 0 else inbound.get(jid, "repost"),
            )
            for i, jid in enumerate(ordered)
        ]
        facts = [jobs[j] for j in ordered]
        projections.append(
            LineageProjection(
                root_job_id=ordered[0],
                company=facts[0].company,
                size=len(ordered),
                open_members=sum(1 for f in facts if f.status == "open"),
                first_seen=min(f.first_seen for f in facts),
                last_seen=max(f.last_seen for f in facts),
                members=members,
                oversized=len(ordered) > max_size,
            )
        )
    return projections
