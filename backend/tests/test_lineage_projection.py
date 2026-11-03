"""Union-find projection: chains get seq/role, rejected edges split, cycles are safe."""

from __future__ import annotations

import itertools
from datetime import UTC, datetime, timedelta

import pytest

from tracker.lineage.project import JobFact, LinkFact, build_projection, choose_predecessors

BASE = datetime(2026, 1, 1, tzinfo=UTC)


def job(jid: int, days: int, status: str = "closed") -> JobFact:
    return JobFact(
        job_id=jid,
        company="acme",
        first_seen=BASE + timedelta(days=days),
        last_seen=BASE + timedelta(days=days + 5),
        status=status,
    )


def test_chain_gets_ordered_seq_and_roles():
    jobs = {1: job(1, 0), 2: job(2, 10), 3: job(3, 20, status="open")}
    links = [LinkFact(2, 1, "repost"), LinkFact(3, 2, "repost")]

    (proj,) = build_projection(links, jobs)

    assert proj.root_job_id == 1
    assert proj.size == 3
    assert proj.open_members == 1
    assert proj.first_seen == jobs[1].first_seen
    assert [(m.seq, m.job_id, m.role) for m in proj.members] == [
        (1, 1, "original"),
        (2, 2, "repost"),
        (3, 3, "repost"),
    ]


def test_role_reflects_link_relation():
    jobs = {1: job(1, 0, status="open"), 2: job(2, 5)}
    (proj,) = build_projection([LinkFact(2, 1, "duplicate")], jobs)
    assert proj.members[1].role == "duplicate"


def test_rejected_edge_absent_splits_the_chain():
    # Caller passes only EFFECTIVE links; a rejected 3->2 link simply isn't here.
    jobs = {1: job(1, 0), 2: job(2, 10), 3: job(3, 20)}
    links = [LinkFact(2, 1, "repost")]  # 3 is now standalone

    projs = build_projection(links, jobs)

    assert len(projs) == 1
    assert projs[0].size == 2
    assert 3 not in {m.job_id for m in projs[0].members}


def test_lone_job_yields_no_lineage():
    assert build_projection([], {1: job(1, 0)}) == []


def test_two_independent_chains_stay_separate():
    jobs = {1: job(1, 0), 2: job(2, 5), 10: job(10, 0), 11: job(11, 5)}
    links = [LinkFact(2, 1, "repost"), LinkFact(11, 10, "repost")]

    projs = sorted(build_projection(links, jobs), key=lambda p: p.root_job_id)

    assert [p.root_job_id for p in projs] == [1, 10]
    assert all(p.size == 2 for p in projs)


def test_cycle_and_dangling_edges_do_not_crash():
    jobs = {1: job(1, 0), 2: job(2, 5)}
    links = [LinkFact(2, 1, "repost"), LinkFact(1, 2, "repost"), LinkFact(2, 999, "repost")]

    (proj,) = build_projection(links, jobs)

    assert proj.size == 2
    assert proj.members[0].role == "original"


def test_oversized_component_flagged_but_still_projected():
    jobs = {i: job(i, i) for i in range(1, 6)}  # 5 members
    links = [LinkFact(i + 1, i, "repost") for i in range(1, 5)]

    (proj,) = build_projection(links, jobs, max_size=3)

    assert proj.size == 5
    assert proj.oversized is True


# --- one predecessor per job, whatever the row order --------------

H0 = datetime(2026, 10, 1, tzinfo=UTC)


def _roles(projections) -> dict[int, tuple[int, str]]:
    return {m.job_id: (p.root_job_id, m.role) for p in projections for m in p.members}


@pytest.mark.parametrize(
    "links",
    [
        # A fan-in: job 3 confirmed a duplicate of 1 by a person, and a
        # machine repost of 2.
        [
            LinkFact(3, 1, "duplicate", human=True, decided_at=H0),
            LinkFact(3, 2, "repost", score=0.97),
        ],
        # A diamond of machine links only.
        [
            LinkFact(3, 1, "duplicate", score=0.96),
            LinkFact(3, 2, "repost", score=0.98),
            LinkFact(4, 3, "repost", score=0.97),
            LinkFact(4, 2, "duplicate", score=0.96),
        ],
        # Two human links on one job: the later decision stands.
        [
            LinkFact(3, 1, "duplicate", human=True, decided_at=H0),
            LinkFact(3, 2, "repost", human=True, decided_at=H0 + timedelta(hours=1)),
        ],
    ],
    ids=["human_and_machine", "machine_diamond", "two_human"],
)
def test_every_order_of_the_same_links_projects_the_same(links):
    """Choosing a predecessor must not depend on inbound edge order."""
    jobs = {i: job(i, i) for i in range(1, 5)}
    projections = {
        tuple(sorted(_roles(build_projection(list(order), jobs)).items()))
        for order in itertools.permutations(links)
    }
    assert len(projections) == 1


def test_a_person_outranks_the_machine_and_a_second_predecessor_joins_nothing():
    """A machine `repost` never beats the human `duplicate`, even when it comes
    last, and the co-predecessor 2, linked to nothing but job 3's unchosen edge,
    is not projected a `repost` of 1 (which would take it out of new demand,
    on 1's age clock)."""
    jobs = {1: job(1, 0), 2: job(2, 1), 3: job(3, 2)}
    links = [
        LinkFact(3, 1, "duplicate", human=True, decided_at=H0),
        LinkFact(3, 2, "repost", score=0.99),
    ]
    roles = _roles(build_projection(links, jobs))
    assert roles == {1: (1, "original"), 3: (1, "duplicate")}
    assert 2 not in roles


def test_choose_predecessors_skips_a_dangling_edge_before_choosing():
    jobs = {1: job(1, 0), 2: job(2, 5)}
    chosen = choose_predecessors(
        [LinkFact(2, 999, "repost", human=True, decided_at=H0), LinkFact(2, 1, "repost")], jobs
    )
    assert chosen[2].prior_job_id == 1
