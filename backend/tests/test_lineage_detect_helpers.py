"""Pure helpers inside the DB-facing detector: band comparison, gap, candidate choice."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from tests.factories import make_job
from tests.job_contract_seed import _stated
from tracker.config import get_settings
from tracker.db.models import Job
from tracker.lineage import detect as lineage_detect
from tracker.lineage.detect import (
    ScoredCandidate,
    _choose,
    _gap_days,
    _is_concurrent,
    band_relation,
)
from tracker.lineage.score import Candidate, Verdict

BASE = datetime(2026, 1, 1, tzinfo=UTC)


def test_band_relation_overlap_disjoint_period_currency():
    # overlapping annual USD ranges
    assert band_relation(240_000, 334_000, "USD", "year", 250_000, 350_000, "USD", "year") == "overlap"
    # non-overlapping -> disjoint (counter-evidence)
    assert band_relation(100_000, 150_000, "USD", "year", 300_000, 400_000, "USD", "year") == "disjoint"
    # hourly vs annual -> hard gate
    assert band_relation(50, 80, "USD", "hour", 200_000, 300_000, "USD", "year") == "period_mismatch"
    # different currency -> neutral, never penalize
    assert band_relation(240_000, 334_000, "USD", "year", 220_000, 300_000, "EUR", "year") == "unknown"
    # either side missing -> unknown
    assert band_relation(None, None, None, None, 240_000, 334_000, "USD", "year") == "unknown"


def test_is_concurrent_detects_overlapping_lifetimes():
    job_first = BASE + timedelta(days=100)
    # prior still open -> concurrent
    assert _is_concurrent(job_first, None) is True
    # prior closed AFTER this posting appeared -> lifetimes overlapped -> concurrent
    assert _is_concurrent(job_first, BASE + timedelta(days=101)) is True
    # prior closed BEFORE this posting appeared -> a true repost
    assert _is_concurrent(job_first, BASE + timedelta(days=90)) is False


def test_gap_days_uses_closed_at_for_repost_and_first_seen_for_duplicate():
    job_first = BASE + timedelta(days=100)
    # repost (not concurrent): prior closed 12 days before this posting appeared
    assert _gap_days(job_first, False, BASE + timedelta(days=88), BASE) == 12
    # duplicate (concurrent): gap measured from the prior's first_seen
    assert _gap_days(job_first, True, None, BASE + timedelta(days=95)) == 5


def _sc(decision: str, cosine: float, prior_id: int) -> ScoredCandidate:
    cand = Candidate(
        job_id=9, prior_job_id=prior_id, cosine=cosine, title_display_equal=True, title_equal=False,
        title_jaccard=0.8, title_grade_compatible=True, concurrent=False, gap_days=10, location_overlap=True,
        both_locations_empty=False, location_jaccard=1.0, same_family=True, same_level_band=True,
        prior_lineage_size=1, has_descriptions=True, band_relation="unknown",
    )
    return ScoredCandidate(cand, Verdict(decision, "repost", cosine, "embedding"), f"t{prior_id}", None)


def test_choose_prefers_single_best_auto():
    chosen = _choose([_sc("auto", 0.94, 1), _sc("auto", 0.97, 2), _sc("suspected", 0.99, 3)])
    assert [s.candidate.prior_job_id for s in chosen] == [2]


def test_choose_keeps_only_the_best_suspected_predecessor():
    chosen = _choose(
        [_sc("suspected", 0.90, 1), _sc("suspected", 0.88, 2),
         _sc("suspected", 0.87, 3), _sc("suspected", 0.86, 4), _sc("reject", 0.5, 5)]
    )
    assert [s.candidate.prior_job_id for s in chosen] == [1]


def test_choose_returns_nothing_when_all_reject():
    assert _choose([_sc("reject", 0.4, 1)]) == []


def test_redetection_clears_only_pending_machine_links(monkeypatch):
    """A v2 pass must be able to withdraw an obsolete pending proposal."""
    job = Job(id=9)

    class Selected:
        """The selection's rows: the job and its current input key."""

        def all(self):
            return [type("Row", (), {"Job": job, "input_key": "key"})()]

    class Session:
        def __init__(self):
            self.statements = []
            self.commits = 0

        async def scalars(self, _stmt):
            return type("Scalars", (), {"all": lambda self: []})()

        async def execute(self, stmt, *_args, **_kwargs):
            self.statements.append(stmt)
            return Selected()

        async def commit(self):
            self.commits += 1

    async def no_candidates(_session, make_job, *, k, place_sets=None):
        return []

    monkeypatch.setattr(lineage_detect, "fetch_candidates", no_candidates)
    session = Session()
    summary = asyncio.run(lineage_detect.detect_lineage(session, [job.id]))

    assert summary["links_written"] == 0
    assert session.commits == 1
    sql = [str(stmt) for stmt in session.statements]
    delete = next(i for i, s in enumerate(sql) if "job_lineage_link.status =" in s)
    # The relationship lock comes before the write.
    assert any("pg_advisory_xact_lock" in s for s in sql[:delete])


def test_any_two_known_periods_that_differ_are_a_mismatch():
    # A monthly posting and its yearly repost are ~12x apart: "disjoint", the
    # wrong reason, while month was not counted as a period.
    assert band_relation(10_000, 12_000, "USD", "month", 120_000, 144_000, "USD", "year") == "period_mismatch"
    # "Could not tell" is no period: never evidence either way.
    assert band_relation(240_000, 334_000, "USD", "unclear", 250_000, 350_000, "USD", "year") == "overlap"


@pytest.mark.asyncio
async def test_candidates_compare_the_served_period_never_the_stored_one(db_session):
    """Netflix's $600,000 salary, stored as hourly, and its
    yearly repost: the stored labels differ, the served ones do not (a stored
    period its amount cannot be is served `unclear`)."""
    vector = [1.0] + [0.0] * (get_settings().embedding_dim - 1)

    def posting(key: str, period: str, first_seen: datetime) -> Job:
        return make_job(
            key, company="netflix", title="Staff Product Manager", embedding=vector,
            description_text="Own the roadmap.", first_seen=first_seen, last_seen=first_seen,
            **_stated(disclosed_base_min=600_000, disclosed_base_max=1_066_000, disclosed_pay_period=period),
        )

    prior = posting("prior", "hour", BASE)
    newer = posting("newer", "year", BASE + timedelta(days=30))
    db_session.add_all([prior, newer])
    await db_session.commit()

    (scored,) = await lineage_detect.fetch_candidates(db_session, newer, k=5)
    assert scored.candidate.prior_job_id == prior.id
    assert scored.candidate.band_relation == "overlap"
