"""Targeted retry: re-attempt only the sources a run failed on.

Three properties, each of which is a distinct way to make things worse if wrong:
eligibility must come off the outcome vocabulary (not a second opinion about what
"failed" means), attempts must be bounded so a permanently broken source cannot
storm, and the run must be `targeted` so its success never claims the untouched
companies are fresh.

Runs without a DB: fake runs and a stubbed `run_pipeline`.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from tracker.connectors.recipes.outcome import RETRYABLE, SourceOutcome
from tracker.health import RunScope
from tracker.workflows import retry_sources


def stats(**overrides) -> dict:
    base = {
        "scanned": 0,
        "kept": 0,
        "errors": [],
        "capped": False,
        "bounded": False,
        "suspended": False,
        "list_complete": False,
    }
    base.update(overrides)
    return base


OK = stats(scanned=500, list_complete=True)
CAPPED = stats(scanned=151, capped=True)
BOUNDED = stats(scanned=1880, bounded=True)
DEGRADED = stats(scanned=400, errors=["HTTPError: 500"])
FAILED = stats(errors=["TimeoutError: collection timed out"])
SUSPENDED = stats(scanned=920, errors=["ReadError (no detail)"], suspended=True)


def _run(run_id: int, per_source: dict, *, scope=RunScope.FULL, status="partial"):
    return SimpleNamespace(id=run_id, per_source=per_source, scope=scope, status=status)


class TestEligibility:
    def test_candidates_are_exactly_the_retryable_outcomes(self):
        per_source = {
            "apple": OK,
            "netflix": CAPPED,
            "meta": BOUNDED,
            "google": DEGRADED,
            "nvidia": FAILED,
        }
        assert retry_sources.retry_candidates(per_source) == ["google", "meta", "nvidia"]

    def test_a_finished_source_is_never_retried(self):
        assert retry_sources.retry_candidates({"apple": OK}) == []

    def test_an_operator_cap_is_never_retried(self):
        """`--max-list` is an instruction. Retrying it would quietly do the work
        the operator asked us not to do."""
        assert retry_sources.retry_candidates({"netflix": CAPPED}) == []

    def test_a_source_we_cut_at_our_ceiling_is_the_ideal_candidate(self):
        """`bounded` means it was still producing when we stopped it — the one
        case where a retry is almost certain to make progress."""
        assert retry_sources.retry_candidates({"meta": BOUNDED}) == ["meta"]
        assert SourceOutcome.BOUNDED in RETRYABLE

    def test_a_source_our_host_slept_through_is_worth_another_pass(self):
        """`suspended` is our laptop, not the source: nothing about the board
        changed, the machine is awake now, and the listing is still incomplete.
        The contrast is `truncated`, which is deterministic and would page into
        the same ceiling again."""
        assert retry_sources.retry_candidates({"microsoft": SUSPENDED}) == ["microsoft"]
        assert SourceOutcome.SUSPENDED in RETRYABLE

    def test_a_board_gone_from_its_address_is_not_retried(self):
        """Its root answered 404: the answer a retry gets too. The
        control is the same failed read without the flag, which still is."""
        gone = stats(listing_invalidated=True, board_missing=True)
        down = stats(listing_invalidated=True)
        assert retry_sources.retry_candidates({"amigo": gone, "hex": down}) == ["hex"]

    def test_eligibility_is_read_off_the_vocabulary_not_restated(self):
        """Guards against drift: if a new SourceOutcome member appears, this
        module must not silently keep its own stale opinion of "failed"."""
        assert RETRYABLE == {
            SourceOutcome.BOUNDED,
            SourceOutcome.SUSPENDED,
            SourceOutcome.DEGRADED,
            SourceOutcome.FAILED,
            SourceOutcome.UNATTEMPTED,
        }

    def test_an_empty_or_missing_per_source_is_not_an_error(self):
        assert retry_sources.retry_candidates({}) == []
        assert retry_sources.retry_candidates(None) == []


class TestReferenceRun:
    def test_a_targeted_run_is_never_the_reference(self):
        runs = [_run(9, {"meta": OK}, scope=RunScope.TARGETED), _run(8, {"meta": FAILED})]
        assert retry_sources.reference_run(runs).id == 8

    def test_a_full_run_that_observed_nothing_is_not_evidence(self):
        """A `full` run that died before collecting anything is not the
        reference: treating it as one reports every source as having no outcome
        while the real evidence sits one run below it."""
        runs = [_run(39, {}, status="error"), _run(38, {"meta": FAILED})]
        assert retry_sources.reference_run(runs).id == 38

    def test_no_full_run_at_all_is_reported_as_none(self):
        assert retry_sources.reference_run([_run(2, {"meta": FAILED}, scope=RunScope.TARGETED)]) is None


class TestAttemptBudget:
    def test_attempts_count_only_targeted_runs_since_the_last_full_one(self):
        """A fresh full attempt resets the cycle: it is a new question about the
        source, not a continuation of the previous round of retries."""
        runs = [
            _run(5, {"meta": FAILED}, scope=RunScope.TARGETED),
            _run(4, {"meta": FAILED}, scope=RunScope.TARGETED),
            _run(3, {"meta": FAILED}, scope=RunScope.FULL),  # cycle boundary
            _run(2, {"meta": FAILED}, scope=RunScope.TARGETED),
        ]
        assert retry_sources._attempts_so_far(runs, "meta") == 2

    def test_a_source_absent_from_a_targeted_run_did_not_consume_an_attempt(self):
        runs = [
            _run(5, {"google": FAILED}, scope=RunScope.TARGETED),
            _run(4, {"meta": FAILED}, scope=RunScope.TARGETED),
        ]
        assert retry_sources._attempts_so_far(runs, "meta") == 1

    def test_no_targeted_runs_yet_means_no_attempts(self):
        assert retry_sources._attempts_so_far([_run(3, {"meta": FAILED})], "meta") == 0


class TestPlan:
    @pytest.mark.asyncio
    async def test_plan_names_the_eligible_sources_from_the_newest_full_run(
        self, monkeypatch
    ):
        runs = [
            # A newer *targeted* run must not become the reference: it only ever
            # covered a subset, so it cannot say which sources still need work.
            _run(9, {"meta": OK}, scope=RunScope.TARGETED, status="ok"),
            _run(8, {"apple": OK, "meta": BOUNDED, "google": DEGRADED}),
        ]
        _fake_runs(monkeypatch, runs)

        plan = await retry_sources.plan_retry()
        assert plan["run_id"] == 8
        assert plan["companies"] == ["google", "meta"]

    @pytest.mark.asyncio
    async def test_a_source_over_its_attempt_budget_is_dropped_and_reported(
        self, monkeypatch
    ):
        """Dropped, and *named* — a silent cap reads as "nothing to retry"."""
        runs = [
            _run(7, {"meta": FAILED}, scope=RunScope.TARGETED),
            _run(6, {"meta": FAILED}, scope=RunScope.TARGETED),
            _run(5, {"meta": FAILED, "google": DEGRADED}),
        ]
        _fake_runs(monkeypatch, runs)

        plan = await retry_sources.plan_retry(max_attempts=2)
        assert plan["companies"] == ["google"]
        assert plan["skipped_attempts_exhausted"] == {"meta": 2}
        assert "meta" in plan["eligible"]  # eligible, just out of attempts

    @pytest.mark.asyncio
    async def test_no_full_run_to_retry_from_is_reported_not_crashed(self, monkeypatch):
        _fake_runs(monkeypatch, [_run(2, {"meta": FAILED}, scope=RunScope.TARGETED)])
        plan = await retry_sources.plan_retry()
        assert plan["companies"] == []
        assert "no full run" in plan["reason"]

    @pytest.mark.asyncio
    async def test_a_clean_full_run_leaves_nothing_to_do(self, monkeypatch):
        _fake_runs(monkeypatch, [_run(3, {"apple": OK, "netflix": CAPPED}, status="ok")])
        plan = await retry_sources.plan_retry()
        assert plan["companies"] == []


class TestRun:
    @pytest.mark.asyncio
    async def test_the_retry_run_is_targeted_so_it_cannot_fake_freshness(
        self, monkeypatch
    ):
        """The load-bearing one. A successful 2-of-9 retry marked `full` would
        advance `last_success_at` and switch off the catch-up for the other 7."""
        _fake_runs(monkeypatch, [_run(8, {"meta": BOUNDED, "google": DEGRADED})])
        calls: list[dict] = []

        async def fake_pipeline(**kwargs):
            calls.append(kwargs)
            return {"status": "ok"}

        monkeypatch.setattr(retry_sources, "run_pipeline", fake_pipeline)
        monkeypatch.setattr(retry_sources, "run_lock", _noop_lock)

        result = await retry_sources.run()
        assert result["ran"] is True
        assert calls == [{"companies": ["google", "meta"], "run_scope": RunScope.TARGETED}]

    @pytest.mark.asyncio
    async def test_dry_run_reports_the_plan_and_starts_nothing(self, monkeypatch):
        _fake_runs(monkeypatch, [_run(8, {"meta": BOUNDED})])

        async def explode(**_kwargs):
            raise AssertionError("dry run must not start a pipeline")

        monkeypatch.setattr(retry_sources, "run_pipeline", explode)
        result = await retry_sources.run(dry_run=True)
        assert result["ran"] is False
        assert result["companies"] == ["meta"]

    @pytest.mark.asyncio
    async def test_nothing_eligible_starts_no_pipeline(self, monkeypatch):
        _fake_runs(monkeypatch, [_run(8, {"apple": OK}, status="ok")])

        async def explode(**_kwargs):
            raise AssertionError("must not start a pipeline with no candidates")

        monkeypatch.setattr(retry_sources, "run_pipeline", explode)
        assert (await retry_sources.run())["ran"] is False

    @pytest.mark.asyncio
    async def test_a_retry_skips_rather_than_waits_when_a_run_holds_the_lock(
        self, monkeypatch
    ):
        """A retry is the lowest-priority work in the system: blocking would let
        it delay the scheduled scrape whose failures it exists to fix."""
        _fake_runs(monkeypatch, [_run(8, {"meta": BOUNDED})])

        async def explode(**_kwargs):
            raise AssertionError("must not run while another run holds the lock")

        monkeypatch.setattr(retry_sources, "run_pipeline", explode)
        monkeypatch.setattr(retry_sources, "run_lock", _busy_lock)

        result = await retry_sources.run()
        assert result["ran"] is False
        assert result["reason"] == "run in progress"


# --- fakes ------------------------------------------------------------------ #


class _Scalars:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _Session:
    def __init__(self, rows):
        self._rows = rows

    async def scalars(self, *_a, **_k):
        return _Scalars(self._rows)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        return None


def _fake_runs(monkeypatch, runs):
    """Swap the run-log query for a fixed list, newest first."""
    monkeypatch.setattr(retry_sources, "session_scope", lambda: _Session(runs))


class _noop_lock:  # noqa: N801 - stands in for a context manager
    def __init__(self, *_a, **_k):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False


class _busy_lock:  # noqa: N801
    def __init__(self, *_a, **_k):
        pass

    def __enter__(self):
        raise retry_sources.AlreadyRunning("held")

    def __exit__(self, *_exc):
        return False
