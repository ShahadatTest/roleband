"""The timing report ranks what our budget threatens, from durations that happened."""

from scripts.binding_timing_report import SourceRun, summarize


def _runs(company, provider, seconds, *, outcome="ok", scanned=100, mode="reconcile"):
    return [SourceRun(company, provider, mode, outcome, s, scanned) for s in seconds]


def test_a_bounded_run_or_a_tail_past_the_budget_leads_the_report():
    rows = summarize(
        _runs("fast", "greenhouse", [2, 3, 2])
        + _runs("slow-but-fits", "workday", [900, 950, 1000])
        + _runs("tail-over", "eightfold", [1500, 1600, 1850])
        + _runs("was-bounded", "apple", [30, 31]) + _runs("was-bounded", "apple", [700], outcome="bounded"),
        {}, 1800.0,
    )
    assert [r.company for r in rows] == ["tail-over", "was-bounded", "slow-but-fits", "fast"]
    assert rows[0].at_risk and rows[0].headroom_seconds == -50.0
    assert rows[1].at_risk and rows[1].outcomes == {"bounded": 1, "ok": 2}
    assert not rows[2].at_risk, "slow is not at risk while the slowest run fits"


def test_p95_is_a_duration_that_happened_never_interpolated_below_it():
    rows = summarize(_runs("x", "p", [10] * 18 + [100]), {}, 90.0)
    assert rows[0].p95_seconds == 100 and rows[0].at_risk


def test_a_learned_budget_replaces_the_global_one_per_binding():
    rows = summarize(_runs("x", "eightfold", [200]) + _runs("y", "eightfold", [200]),
                     {("x", "eightfold"): 150.0}, 1800.0)
    by = {r.company: r for r in rows}
    assert (by["x"].budget_seconds, by["x"].budget_learned, by["x"].at_risk) == (150.0, True, True)
    assert (by["y"].budget_seconds, by["y"].budget_learned, by["y"].at_risk) == (1800.0, False, False)


def test_rate_per_posting_ignores_runs_that_scanned_nothing():
    rows = summarize(_runs("x", "p", [100], scanned=200) + _runs("x", "p", [50], scanned=0), {}, 1800.0)
    assert rows[0].seconds_per_posting_p50 == 0.5
