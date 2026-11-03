"""Pure-logic tests for notification classification.

The contract: the per-role channel
speaks ONLY about roles the user tracks, comp alerts come from the posted band
and never from the cohort lookup, and discovery is a ranked daily digest rather
than one interrupt per posting.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

import pytest

from tests.factories import STAFF_EM_SCOPE, NoComp
from tracker.config import get_settings
from tracker.connectors import RateLimiterPool
from tracker.connectors.recipes.outcome import (
    SourceOutcome,
    classify_source_outcome,
    run_status_for,
)
from tracker.db.models import ScrapeRun
from tracker.notifications import (
    DigestMatch,
    classify_daily_digest,
    classify_event,
    classify_pursuit_due,
    classify_sync_result,
    classify_sync_started,
    fit_label,
)
from tracker.workflows.collection import collect_source
from tracker.workflows.collection_types import deferred_collection, empty_stats


@dataclass
class JobStub:
    company: str = "openai"
    title: str = "Research Manager"
    comp_median: int | None = None
    total_days_open: int = 0
    drift_alerts: list = field(default_factory=list)


def band(low: int | None, high: int | None) -> dict:
    return {"min": low, "max": high}


# --------------------------------------------------------------------------
# The tracked gate. If it regresses, the feed refills with untracked rows.
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "event_type,detail",
    [
        ("opened", {}),
        ("reopened", {}),
        ("closed", {}),
        ("changed", {"title": {"from": "a", "to": "b"}}),
        ("changed", {"disclosed_base": {"from": band(200_000, 240_000), "to": band(300_000, 340_000)}}),
    ],
)
def test_untracked_role_never_produces_a_notification(event_type, detail):
    assert classify_event(event_type, detail, JobStub(), False) is None


def test_untracked_high_comp_role_is_still_silent():
    """An untracked role's cohort median never fires a notification.

    It would write high-priority rows for roles the user has not asked to
    follow. Comp is a ranking input for the digest, never a reason to interrupt.
    """
    job = JobStub(comp_median=1_500_000)
    assert classify_event("opened", {}, job, False) is None


def test_tracked_closed_is_high_priority():
    notif = classify_event("closed", {}, JobStub(), True)
    assert notif is not None
    assert notif.category == "closed"
    assert notif.priority == "high"
    assert "closed" in notif.title.lower()
    assert notif.meta["tracked"] is True


def test_tracked_repost_successor_reads_as_a_repost():
    notif = classify_event("opened", {}, JobStub(), True, lineage_role="repost")
    assert notif is not None
    assert notif.category == "repost"
    assert notif.priority == "high"
    assert "reposted" in notif.title


def test_tracked_reopened_is_a_repost():
    notif = classify_event("reopened", {}, JobStub(), True)
    assert notif is not None
    assert notif.category == "repost"


# --------------------------------------------------------------------------
# Comp: posted band only. `comp_median` is a cohort lookup and must never fire.
# --------------------------------------------------------------------------


def test_comp_median_change_alone_fires_no_comp_notification():
    """The single most important guard in this file.

    `comp_median` is a company+level+family lookup, so one refresh moves every
    row in the cohort together: firing on it would write hundreds of identical
    "Comp down at Apple" rows in the same second for a trivial move, and let
    comp own the feed and most of its high-priority rows.
    """
    detail = {"comp_median": {"from": 306_217, "to": 306_143}}
    notif = classify_event("changed", detail, JobStub(), True)
    assert notif is not None
    assert notif.category not in ("comp_up", "comp_down")


def test_posted_band_increase_is_comp_up():
    detail = {"disclosed_base": {"from": band(200_000, 240_000), "to": band(230_000, 270_000)}}
    notif = classify_event("changed", detail, JobStub(), True)
    assert notif is not None
    assert notif.category == "comp_up"
    assert notif.priority == "high"
    assert "$200k-$240k -> $230k-$270k" in notif.body


def test_posted_band_decrease_is_comp_down_and_not_high_priority():
    detail = {"disclosed_base": {"from": band(300_000, 340_000), "to": band(250_000, 290_000)}}
    notif = classify_event("changed", detail, JobStub(), True)
    assert notif is not None
    assert notif.category == "comp_down"
    assert notif.priority == "normal"


def test_unchanged_band_midpoint_is_not_a_comp_event():
    """A band that widens symmetrically has not moved. Direction needs a delta."""
    detail = {"disclosed_base": {"from": band(200_000, 300_000), "to": band(150_000, 350_000)}}
    notif = classify_event("changed", detail, JobStub(), True)
    assert notif is not None
    assert notif.category not in ("comp_up", "comp_down")


def test_a_band_that_loses_a_bound_is_not_a_comp_move():
    """A noise class of comp moves, on a smaller population.

    `_band_midpoint` averages whatever bounds are present, so a source that drops
    `max` for one scrape moves the midpoint by half the band -- $250k becomes
    $200k, which reads as a $50k pay cut -- and moves it back when the field
    returns. On a tracked role that is an alternating comp_down/comp_up pair
    every scrape, driven by a source flapping a FIELD rather than by any change
    in pay.

    Direction needs like for like. A band that discloses different bounds than
    the one before it is a disclosure change, not a comp change, and the event
    falls through to the generic `changed` row that says so.
    """
    lost = {"disclosed_base": {"from": band(200_000, 300_000), "to": {"min": 200_000, "max": None}}}
    notif = classify_event("changed", lost, JobStub(), True)
    assert notif is not None
    assert notif.category not in ("comp_up", "comp_down"), (
        "a dropped bound was read as a pay cut"
    )

    regained = {"disclosed_base": {"from": {"min": 200_000, "max": None}, "to": band(200_000, 300_000)}}
    notif = classify_event("changed", regained, JobStub(), True)
    assert notif is not None
    assert notif.category not in ("comp_up", "comp_down"), (
        "the bound coming back was read as a raise -- this is the other half of "
        "the alternating pair"
    )


def test_a_one_bound_band_still_moves_when_that_bound_moves():
    """The narrowing must not swallow a real move.

    Some sources only ever post a floor. Comparing a min-only band with another
    min-only band is like for like, and a rise in the only number disclosed is a
    real rise.
    """
    detail = {
        "disclosed_base": {"from": {"min": 200_000}, "to": {"min": 240_000}},
    }
    notif = classify_event("changed", detail, JobStub(), True)
    assert notif is not None
    assert notif.category == "comp_up"


def _stated(low, high, currency, period):
    return {"min": low, "max": high, "currency": currency, "period": period}


@pytest.mark.parametrize(
    "before,after,shown",
    [
        (_stated(80_000, 95_000, "GBP", "year"), _stated(85_000, 100_000, "GBP", "year"),
         "80k-95k GBP -> 85k-100k GBP"),
        (_stated(45, 60, "USD", "hour"), _stated(50, 65, "USD", "hour"), "$45-$60 an hour -> $50-$65 an hour"),
        (_stated(9_000, 9_000, "EUR", "month"), _stated(9_500, 9_500, "EUR", "month"),
         "9,000 EUR a month -> 9,500 EUR a month"),
        # A detail written without its currency and period reads as dollars, and
        # names no period its size alone cannot confirm.
        (band(45, 60), band(50, 65), "$45-$60 -> $50-$65"),
    ],
    ids=["pounds", "hourly", "monthly", "older_detail"],
)
def test_a_band_reads_in_its_own_currency_and_period(before, after, shown):
    notif = classify_event("changed", {"disclosed_base": {"from": before, "to": after}}, JobStub(), True)
    assert notif is not None
    assert notif.category == "comp_up"
    assert shown in notif.body


@pytest.mark.parametrize(
    "after",
    [_stated(120_000, 140_000, "GBP", "year"), _stated(70, 90, "USD", "hour")],
    ids=["another_currency", "another_period"],
)
def test_a_band_restated_in_other_terms_is_neither_a_raise_nor_a_cut(after):
    # Both midpoints are lower, so comparing the raw figures would ring a pay cut.
    before = _stated(150_000, 170_000, "USD", "year")
    notif = classify_event("changed", {"disclosed_base": {"from": before, "to": after}}, JobStub(), True)
    assert notif is not None
    assert notif.category not in ("comp_up", "comp_down")


def test_long_open_update_is_now_reachable():
    """Almost every `changed` event carries a `comp_median` delta, so a comp
    branch that preempts it would keep the long-open update from ever firing."""
    detail = {"comp_median": {"from": 100, "to": 200}, "title": {"from": "a", "to": "b"}}
    notif = classify_event("changed", detail, JobStub(total_days_open=60), True, long_open_days=45)
    assert notif is not None
    assert notif.category == "long_open_update"


def test_a_long_open_update_names_no_second_clock():
    """`total_days_open` counts from our first sighting, and a person reads one
    age per posting, from the earlier of the employer's date and ours:
    "open 60 days" beside Job detail's "Listed for 164 days" would contradict
    that rule. The sign is named, Job detail states
    the figure, and copy carries no em dash."""
    detail = {"title": {"from": "a", "to": "b"}}
    notif = classify_event("changed", detail, JobStub(total_days_open=60), True, long_open_days=45)
    assert notif is not None and notif.category == "long_open_update"

    assert notif.title.endswith(" updated a role you saved, listed for a long time")
    assert notif.body == "Research Manager"
    assert "60" not in notif.title and "open" not in notif.title.lower().split()
    assert "\u2014" not in notif.title, "no em dash in copy"


# --------------------------------------------------------------------------
# Digest
# --------------------------------------------------------------------------


def test_digest_is_none_when_nothing_opened():
    assert classify_daily_digest("2026-09-04", []) is None


def test_digest_counts_all_and_leads_with_best_fit():
    matches = [
        DigestMatch(1, "google", "Staff PM, Ads", fit=0.71),
        DigestMatch(2, "apple", "TPM, Silicon", fit=0.55),
        DigestMatch(3, "netflix", "EM, Streaming", fit=0.31),
    ]
    notif = classify_daily_digest("2026-09-04", matches)
    assert notif is not None
    assert notif.category == "daily_digest"
    assert notif.title == "3 new roles for you today"
    assert "Strong fit: Staff PM, Ads at Google" in notif.body
    assert "and 2 more" in notif.body
    assert notif.meta["count"] == 3
    assert notif.meta["companies"] == ["apple", "google", "netflix"]
    assert [t["job_id"] for t in notif.meta["top"]] == [1, 2, 3]


def test_digest_top_is_capped_but_count_stays_exact():
    """Hundreds of roles can open on one day. The digest names a few and
    counts them all; a capped COUNT would misreport the day."""
    matches = [DigestMatch(i, "google", f"Role {i}", fit=1 - i / 100) for i in range(40)]
    notif = classify_daily_digest("2026-09-04", matches, top_n=5)
    assert notif is not None
    assert notif.meta["count"] == 40
    assert len(notif.meta["top"]) == 5
    assert "and 39 more" in notif.body


def test_digest_without_intent_signal_still_ships():
    """Fresh install: no statement, no feedback, so no ranking. The day's roles
    must still arrive rather than being withheld until the user trains it."""
    notif = classify_daily_digest("2026-09-04", [DigestMatch(1, "google", "Staff PM")])
    assert notif is not None
    assert notif.title == "1 new role for you today"
    assert notif.meta["ranked"] is False
    assert notif.body == "Staff PM at Google"


def test_singular_plural_reads_correctly():
    one = classify_daily_digest("2026-09-04", [DigestMatch(1, "google", "A")])
    assert one is not None and one.title == "1 new role for you today"


@pytest.mark.parametrize(
    "fit,expected",
    [(0.75, "Strong"), (0.60, "Strong"), (0.59, "Good"), (0.42, "Fair"), (0.10, "Weak"), (None, None)],
)
def test_fit_bands_match_the_intelligence_screen(fit, expected):
    assert fit_label(fit) == expected


def test_the_digest_word_follows_the_edges_the_screen_draws(monkeypatch):
    """One set of edges: move one in `search/fit.py` and the digest moves with it."""
    from tracker.search import fit as fit_scale

    monkeypatch.setattr(fit_scale, "FIT_BAND_EDGES", (("strong", "Strong", 0.70), ("good", "Good", 0.40),
                                                      ("some", "Fair", 0.30)))
    assert [fit_label(score) for score in (0.70, 0.65, 0.40, 0.35, 0.29)] == [
        "Strong", "Good", "Good", "Fair", "Weak",
    ]


# --------------------------------------------------------------------------
# Pursuit follow-ups
# --------------------------------------------------------------------------


def test_pursuit_due_names_the_action_and_the_debt():
    notif = classify_pursuit_due("google", "Staff PM, Ads", "interviewing", "Email the recruiter", 3)
    assert notif.category == "pursuit_due"
    assert notif.priority == "high"
    assert "3d overdue" in notif.title
    assert "Google" in notif.title
    assert "Email the recruiter" in notif.body
    assert "interviewing" in notif.body


def test_pursuit_due_today_does_not_claim_to_be_overdue():
    notif = classify_pursuit_due("apple", "TPM", "applied", "Follow up", 0)
    assert "due today" in notif.title
    assert "overdue" not in notif.title


def test_pursuit_without_a_named_action_still_notifies():
    notif = classify_pursuit_due("apple", "TPM", "applied", None, 1)
    assert "No next action set" in notif.body


# --------------------------------------------------------------------------
# Run outcomes
# --------------------------------------------------------------------------


def test_sync_started_names_companies_as_followed_and_no_server_clock():
    """The companies by the names the person follows them under, not slugs,
    and no time in the server's zone: the feed dates the row in the reader's."""
    run = ScrapeRun(id=42, started_at=datetime(2026, 7, 14, 1, 25, tzinfo=UTC))
    names = {"apple": "Apple", "google": "Google", "meta": "Meta", "netflix": "Netflix", "stripe": "Stripe"}
    notif = classify_sync_started(run, ["apple", "google", "meta", "netflix", "stripe", "uber"], names=names)

    assert notif.category == "sync_started"
    assert notif.meta["sync_state"] == "running"
    assert notif.meta["source_count"] == 6
    assert notif.meta["started_at"] == "2026-07-14T01:25:00+00:00", "the time stays data, for the feed"
    assert notif.body == "Scanning 6 companies: Apple, Google, Meta, Netflix and 2 more."
    assert "UTC" not in notif.body and "01:25" not in notif.body
    one = classify_sync_started(run, ["stripe"], names=names)
    assert one.body == "Scanning 1 company: Stripe."
    # A company the register does not name falls back to its label, never a gap.
    assert "Uber" in classify_sync_started(run, ["uber"]).body
    assert classify_sync_started(run, []).body == "Scanning every company you follow."


def test_clean_run_produces_no_notification():
    """A clean sync is recorded in run history, not announced as an interrupt."""
    run = ScrapeRun(
        status="ok",
        started_at=datetime(2026, 7, 14, 1, 25, tzinfo=UTC),
        finished_at=datetime(2026, 7, 14, 1, 27, 5, tzinfo=UTC),
        jobs_seen=12,
        jobs_new=3,
        jobs_closed=1,
        per_source={"google": {"kept": 12, "new": 3, "closed": 1, "errors": []}},
        drift_alerts=[],
    )
    assert classify_sync_result(run) is None


def _fortinet_run(status: str, per_source: dict, drift: list[dict]) -> ScrapeRun:
    return ScrapeRun(
        status=status,
        started_at=datetime(2026, 10, 4, 1, 50, tzinfo=UTC),
        finished_at=datetime(2026, 10, 4, 1, 51, tzinfo=UTC),
        jobs_seen=2, jobs_new=0, jobs_closed=0,
        per_source=per_source,
        drift_alerts=drift,
    )


#: Stored per-source stats, as `collection_types` records them.
_OK = {"scanned": 5, "kept": 5, "new": 0, "closed": 0, "errors": [], "list_complete": True}
#: One row of 976 unread: `lossy`.
_LOSSY = {"scanned": 975, "kept": 2, "new": 0, "closed": 0, "errors": [], "list_complete": False,
          "records_dropped": 1, "listing_invalidated": False}
#: A page lost mid-walk: `degraded`, a real problem.
_DEGRADED = {"scanned": 400, "kept": 2, "new": 0, "closed": 0, "errors": [], "list_complete": False,
             "listing_invalidated": True}
#: The board root answered 404 (`board_missing`).
_GONE = {"scanned": 0, "kept": 0, "new": 0, "closed": 0, "errors": [], "list_complete": False,
         "listing_invalidated": True, "board_missing": True}
#: The same read answering 503: a failure, not a moved board.
_DOWN = {"scanned": 0, "kept": 0, "new": 0, "closed": 0, "errors": [], "list_complete": False,
         "listing_invalidated": True}


def test_a_lossy_read_is_a_successful_refresh_and_says_nothing():
    """A lossy full read is a successful refresh. A countable missing row
    must not turn it into a failed-scan notification."""
    drift = [{"source": "oracle:fortinet", "message": "fewer unique postings than TotalJobsCount",
              "missing": 1, "declared": 976}]
    assert classify_sync_result(_fortinet_run("partial", {"fortinet": _LOSSY}, drift)) is None

    # The control: a lost PAGE is an unknown share of the board, still a problem.
    notif = classify_sync_result(_fortinet_run("partial", {"fortinet": _DEGRADED}, drift))
    assert notif is not None and notif.category == "sync_warning"


def test_a_note_on_a_clean_read_is_not_a_problem():
    """A complete listing's diagnostic note belongs in the run log, not a
    problem notification. The same note on an incomplete read remains visible."""
    drift = [{"source": "ashby:legora", "message": "job detail connector entered failover mode"}]
    assert classify_sync_result(_fortinet_run("ok", {"legora": _OK}, drift)) is None

    # The control: the same note on a read that lost a page is named.
    notif = classify_sync_result(_fortinet_run("partial", {"legora": _DEGRADED}, drift))
    assert notif is not None
    assert notif.meta["diagnostics"]["drift"][0]["message"] == "job detail connector entered failover mode"


def test_problems_are_named_by_company_never_by_provider():
    """The alert is `{adapter}:{company}`; the body read "Problems at: Oracle"."""
    drift = [{"source": "oracle:fortinet", "message": "non-200 search", "status": 500}]
    notif = classify_sync_result(
        _fortinet_run("partial", {"fortinet": _DEGRADED, "legora": _OK}, drift),
        names={"fortinet": "Fortinet"},
    )
    assert notif is not None and notif.category == "sync_warning"
    assert "Problems at: Fortinet." in notif.body
    assert "Oracle" not in notif.body


def test_a_board_gone_from_its_address_rings_no_scan_notification():
    """A moved careers page is reported by Coverage once, not repeated as a
    failed-scan notification with internal run notes on every retry."""
    drift = [{"source": "ashby:amigo", "message": "non-200 job board", "status": 404, "board_missing": True}]
    run = _fortinet_run("error", {"amigo": _GONE}, drift)
    run.notes = "amigo=failed; 12526 demand slices"
    assert classify_sync_result(run) is None

    # Beside a real problem, only the real problem is named.
    mixed = classify_sync_result(
        _fortinet_run("partial", {"amigo": _GONE, "fortinet": _DEGRADED, "legora": _OK}, drift),
        names={"amigo": "Amigo", "fortinet": "Fortinet"},
    )
    assert mixed is not None and "Problems at: Fortinet." in mixed.body
    assert "Amigo" not in mixed.body

    # The control: the same read answering 503 is a failed scan, named by
    # company and never by the run's notes.
    down = _fortinet_run("error", {"amigo": _DOWN}, [{**drift[0], "status": 503, "board_missing": False}])
    down.notes = "amigo=failed; 12526 demand slices"
    failed = classify_sync_result(down, names={"amigo": "Amigo"})
    assert failed is not None and failed.category == "sync_failed"
    assert "Problems at: Amigo." in failed.body
    assert "demand slices" not in failed.body


def test_a_board_coverage_tells_is_never_named_even_with_errors_recorded():
    """One set of told sources for every part of the result: a moved board that
    also recorded an error is named neither as a problem nor in the failure's
    detail, which quotes each named company's own error."""
    gone = {**_GONE, "errors": ["non-200 job board: 404"]}
    down = {**_DOWN, "errors": ["connect timeout"]}
    notif = classify_sync_result(
        _fortinet_run("error", {"amigo": gone, "fortinet": down}, []),
        names={"amigo": "Amigo", "fortinet": "Fortinet"},
    )
    assert notif is not None and notif.category == "sync_failed"
    assert "Fortinet: connect timeout" in notif.body
    assert "Amigo" not in notif.body and "404" not in notif.body
    assert notif.meta["error_sources"] == ["fortinet"]
    assert list(notif.meta["source_errors"]) == ["fortinet"]


def test_a_slept_through_sync_says_the_machine_slept():
    """A sync that slept must not read "Affected source: microsoft" over a
    transport error microsoft never caused, with a diagnostics panel showing
    the bare string "ReadError:". The sources still get named — the
    listing really is incomplete, but the body has to say whose fault it is.
    """
    run = ScrapeRun(
        status="partial",
        started_at=datetime(2026, 9, 7, 8, 32, 48, tzinfo=UTC),
        finished_at=datetime(2026, 9, 7, 8, 54, 2, tzinfo=UTC),
        jobs_seen=42,
        jobs_new=0,
        jobs_closed=0,
        per_source={
            "microsoft": {
                "scanned": 920,
                "kept": 42,
                "new": 0,
                "closed": 0,
                "errors": ["ReadError (no detail)"],
                "suspended": True,
                "suspended_seconds": 987.0,
            }
        },
        drift_alerts=[],
    )
    notif = classify_sync_result(run)

    assert notif is not None
    assert notif.category == "sync_warning"
    assert notif.priority == "normal"
    assert "asleep for 16m 27s" in notif.body
    assert "Microsoft" in notif.body
    assert notif.meta["suspended_sources"] == {"microsoft": 987.0}
    # An empty exception message must not leave a trailing bare colon.
    assert "ReadError:" not in notif.body


def test_an_ordinary_warning_does_not_claim_the_machine_slept():
    """Negative control: without the flag the sentence must be absent, or every
    warning would blame a sleep that did not happen."""
    run = ScrapeRun(
        status="partial",
        started_at=datetime(2026, 9, 7, 8, 32, 48, tzinfo=UTC),
        finished_at=datetime(2026, 9, 7, 8, 54, 2, tzinfo=UTC),
        jobs_seen=42,
        jobs_new=0,
        jobs_closed=0,
        per_source={
            "microsoft": {"scanned": 920, "kept": 42, "errors": ["HTTPError: 500"]},
        },
        drift_alerts=[],
    )
    notif = classify_sync_result(run)

    assert notif is not None
    assert "asleep" not in notif.body
    assert notif.meta["suspended_sources"] == {}


def test_sync_failed_notification_reports_affected_source_and_error_detail():
    run = ScrapeRun(
        status="error",
        started_at=datetime(2026, 7, 14, 1, 25, tzinfo=UTC),
        finished_at=datetime(2026, 7, 14, 1, 25, 12, tzinfo=UTC),
        jobs_seen=0,
        jobs_new=0,
        jobs_closed=0,
        per_source={"google": {"kept": 0, "new": 0, "closed": 0, "errors": ["TimeoutError"]}},
        drift_alerts=[],
    )
    notif = classify_sync_result(run)

    assert notif is not None
    assert notif.priority == "high"
    assert notif.category == "sync_failed"
    assert notif.meta["sync_state"] == "failed"
    assert notif.meta["error_sources"] == ["google"]
    assert notif.meta["source_errors"] == {"google": ["TimeoutError"]}
    assert "Problems at: Google: TimeoutError" in notif.body


def test_problems_name_each_company_as_the_user_tracks_it():
    """"Problems at:" names each company by display name, never by slug
    ("google-deepmind"), as the sentence after it does."""
    broken = _recorded({**empty_stats(), "errors": ["HTTPError: 500"]})
    names = {"google-deepmind": "Google DeepMind", "meta": "Meta Platforms"}
    warned = classify_sync_result(
        _partial_run({"google-deepmind": broken, "meta": _UNREACHED, "apple": _OK}), names=names
    )
    assert warned is not None
    assert "Problems at: Google DeepMind." in warned.body
    assert "google-deepmind" not in warned.body

    failed = classify_sync_result(_partial_run({"google-deepmind": broken}), names=names)
    assert failed is not None and failed.category == "sync_failed"
    assert "Problems at: Google DeepMind: HTTPError: 500." in failed.body


def test_degraded_run_writes_one_row_not_two():
    """A partial run writes `sync_warning` once, never a second `scraper_health`
    row from the same ScrapeRun and the same source list. The diagnostics
    payload hangs off the sync notification itself."""
    run = ScrapeRun(
        status="error",
        started_at=datetime(2026, 7, 14, 1, 25, tzinfo=UTC),
        finished_at=datetime(2026, 7, 14, 1, 26, tzinfo=UTC),
        per_source={"google": {"errors": ["boom"]}},
        drift_alerts=[{"source": "google", "message": "selector changed"}],
    )
    notif = classify_sync_result(run)
    assert notif is not None
    assert notif.category == "sync_failed"
    assert notif.meta["diagnostics"]["errors"][0]["error"] == "boom"


# --------------------------------------------------------------------------- #
# What the run did not reach is named, never called a problem
# --------------------------------------------------------------------------- #


def _recorded(stats: dict, *, list_complete: bool = False) -> dict:
    """A per-source record as `run_persistence` stores it: the collected stats
    plus the listing verdict and the outcome derived from both."""
    record = {**stats, "list_complete": list_complete}
    record["outcome"] = classify_source_outcome(record).value
    return record


def _partial_run(per_source: dict) -> ScrapeRun:
    """A finished run whose status is the projection of its sources,
    never a hand-picked word."""
    return ScrapeRun(
        status=run_status_for(SourceOutcome(stats["outcome"]) for stats in per_source.values()),
        started_at=datetime(2026, 9, 27, 8, 0, tzinfo=UTC),
        finished_at=datetime(2026, 9, 27, 8, 40, tzinfo=UTC),
        jobs_seen=120, jobs_new=4, jobs_closed=0,
        per_source=per_source, drift_alerts=[],
    )


_OK = _recorded({**empty_stats(), "scanned": 300, "kept": 40}, list_complete=True)
#: A company a run never started for a reason of ours other than the network:
#: `unattempted` and `deferred_reason` without `offline`, with an error marker.
_UNREACHED = _recorded({
    **empty_stats(), "unattempted": True, "errors": ["TimeoutError: collection timed out"],
    "deferred_reason": "run deadline reached before this company started",
})
#: A real google row: a page ceiling, no errors.
_TRUNCATED = _recorded({**empty_stats(), "scanned": 99, "kept": 1, "truncated": True})
_BOUNDED = _recorded({**empty_stats(), "scanned": 300, "kept": 40, "bounded": True})
#: A read that failed while no job site accepted a connection, and a
#: company its lane then left for the next tick.
_CUT_OFFLINE = _recorded({**empty_stats(), "scanned": 12, "offline": True,
                          "errors": ["ConnectError: [Errno 8] nodename nor servname provided"]})
_DEFERRED_OFFLINE = _recorded(deferred_collection("beta").stats)


async def _collected(company: str, adapter: str) -> dict:
    """What `collect_source` records for a company it never asked."""
    collection = await collect_source(
        company, {"adapter": adapter}, STAFF_EM_SCOPE, NoComp(), max_list=None, hydrate=False,
        limiter_pool=RateLimiterPool(),
    )
    return _recorded(collection.stats, list_complete=collection.list_complete)


def test_the_fixtures_are_what_the_pipeline_records():
    assert _UNREACHED["outcome"] == "unattempted"
    assert (_TRUNCATED["outcome"], _BOUNDED["outcome"], _OK["outcome"]) == ("truncated", "bounded", "ok")


def test_a_run_that_only_ran_out_of_time_names_who_it_missed_at_low_priority():
    """The case this rule exists for: a deferred company carries the
    run-timeout marker in `errors`, so read naively it is also an error
    source, and the run reads "Scan finished with problems" naming it twice."""
    notif = classify_sync_result(_partial_run({"apple": _OK, "meta": _UNREACHED, "stripe": _UNREACHED}))

    assert notif is not None
    assert (notif.priority, notif.category, notif.title) == (
        "low", "sync_unfinished", "Scan ran out of time before 2 companies",
    )
    assert "Not reached before the scan ran out of time: Meta, Stripe." in notif.body
    assert "They are still due, so the next scan picks them up." in notif.body
    assert "problems" not in notif.body.lower(), "nothing went wrong at any company"
    assert notif.meta["sync_state"] == "partial"
    assert notif.meta["unreached_sources"] == ["meta", "stripe"]
    assert notif.meta["error_sources"] == [] and notif.meta["source_errors"] == {}, (
        "the run deadline is ours, not an error at meta or stripe"
    )


def test_one_company_not_reached_is_it_not_they():
    notif = classify_sync_result(_partial_run({"apple": _OK, "stripe": _UNREACHED}))

    assert notif is not None
    assert notif.title == "Scan ran out of time before 1 company"
    assert "It is still due, so the next scan picks it up." in notif.body
    assert "They are" not in notif.body


def test_a_deadline_that_came_before_every_company_is_not_a_failure():
    """Every company deferred projects to `error` (nothing usable), yet nothing
    failed anywhere: it is the same low notice, never "Couldn't scan"."""
    notif = classify_sync_result(_partial_run({"meta": _UNREACHED, "stripe": _UNREACHED}))

    assert notif is not None
    assert (notif.priority, notif.category, notif.title) == (
        "low", "sync_unfinished", "Scan ran out of time before 2 companies",
    )


def test_names_are_the_ones_the_user_knows():
    notif = classify_sync_result(
        _partial_run({"apple": _OK, "piedpiper": _UNREACHED}), names={"piedpiper": "Pied Piper"},
    )

    assert notif is not None
    assert "Not reached before the scan ran out of time: Pied Piper." in notif.body
    assert "piedpiper" not in notif.body


def test_a_listing_our_own_time_limit_cut_short_is_ours_not_the_companys():
    notif = classify_sync_result(_partial_run({"apple": _OK, "micron": _BOUNDED}))

    assert notif is not None
    assert (notif.category, notif.title) == ("sync_unfinished", "Scan covered 1 company only in part")
    assert "Stopped at the scan's time limit: Micron." in notif.body
    assert "complete read" not in notif.body, "no promise of a read that may never come"
    assert notif.meta["cut_short_sources"] == ["micron"]


def test_a_run_our_connection_cut_names_its_companies_at_low_priority():
    """A dropped connection while awake must not score every company read in
    that tick as a failure ("Scan finished with problems" naming each) when
    nothing went wrong at any of them."""
    notif = classify_sync_result(
        _partial_run({"apple": _OK, "acme": _CUT_OFFLINE, "beta": _DEFERRED_OFFLINE}),
    )

    assert _CUT_OFFLINE["outcome"] == "suspended" and _DEFERRED_OFFLINE["outcome"] == "unattempted"
    assert notif is not None
    assert (notif.priority, notif.category, notif.title) == (
        "low", "sync_unfinished", "Scan lost its internet connection at 2 companies",
    )
    assert "This machine had no internet connection while scanning: Acme, Beta." in notif.body
    assert "they are still due, so the next scan picks them up." in notif.body
    assert "problems" not in notif.body.lower() and "ran out of time" not in notif.body
    assert notif.meta["offline_sources"] == ["acme", "beta"]
    assert notif.meta["error_sources"] == [] and notif.meta["source_errors"] == {}


def test_the_same_failure_while_the_network_answered_is_the_companys():
    failed = _recorded({**empty_stats(), "scanned": 12,
                        "errors": ["ConnectError: [Errno 8] nodename nor servname provided"]})
    notif = classify_sync_result(_partial_run({"apple": _OK, "acme": failed}))

    assert notif is not None
    assert notif.title == "Scan finished with problems" and "Acme" in notif.body
    assert "internet connection" not in notif.body


def test_an_outage_is_counted_beside_the_runs_own_limits():
    two = {"meta": _UNREACHED, "stripe": _UNREACHED}
    notif = classify_sync_result(_partial_run({**two, "acme": _CUT_OFFLINE, "micron": _BOUNDED}))

    assert notif is not None
    assert notif.title == (
        "Scan ran out of time before 2 companies, lost its internet connection at 1 company"
        " and covered 1 only in part"
    )
    assert "it is still due, so the next scan picks it up." in notif.body


def test_a_page_ceiling_alone_says_nothing_every_run():
    """A page ceiling is deterministic (outcome.py leaves `truncated` out of
    RETRYABLE): google past its ceiling would read "only in part" on every run,
    forever, promising a complete read that never comes."""
    assert classify_sync_result(_partial_run({"apple": _OK, "google": _TRUNCATED})) is None


def test_each_group_is_counted_as_what_it_is():
    """3 not reached and 1 cut by a page ceiling must not read "Scan read 4
    companies only in part", since 3 were not read at all."""
    three = {"meta": _UNREACHED, "stripe": _UNREACHED, "uber": _UNREACHED}
    notif = classify_sync_result(_partial_run({**three, "google": _TRUNCATED}))
    assert notif is not None
    assert notif.title == "Scan ran out of time before 3 companies"
    assert "Google" not in notif.body and "only in part" not in notif.body

    notif = classify_sync_result(_partial_run({**three, "micron": _BOUNDED}))
    assert notif is not None
    assert notif.title == "Scan ran out of time before 3 companies and covered 1 only in part"
    assert "Not reached before the scan ran out of time: Meta, Stripe, Uber." in notif.body
    assert "Stopped at the scan's time limit: Micron." in notif.body


@pytest.mark.asyncio
async def test_a_policy_refusal_is_not_a_timeout_and_says_nothing(monkeypatch):
    """A provider refusal is a standing decision shown in the schedule as
    policy_denied, not a new run-timeout warning on every pass."""
    monkeypatch.setattr(get_settings(), "sync_policy_denied_providers", frozenset({"workday"}))
    refused = await _collected("nvidia", "workday")
    assert refused["outcome"] == "unattempted" and refused["policy_reason"], "the shape collection records"

    assert classify_sync_result(_partial_run({"apple": _OK, "nvidia": refused})) is None

    broken = _recorded({**empty_stats(), "errors": ["HTTPError: 500"]})
    notif = classify_sync_result(_partial_run({"apple": broken, "nvidia": refused, "google": _OK}))
    assert notif is not None
    assert "Problems at: Apple." in notif.body
    assert "nvidia" not in notif.body.lower() and "ran out of time" not in notif.body


@pytest.mark.asyncio
async def test_a_connector_this_build_lacks_stays_a_problem():
    """`unattempted` too, and health-inert, but it recorded an error and it is
    a fault of the deployment: never "not reached before the scan ran out of time"."""
    ghost = await _collected("ghostco", "notinthisbuild")
    assert ghost["outcome"] == "unattempted" and ghost["errors"], "the shape collection records"

    notif = classify_sync_result(_partial_run({"apple": _OK, "ghostco": ghost}))
    assert notif is not None
    assert (notif.category, notif.title) == ("sync_warning", "Scan finished with problems")
    assert "Problems at: Ghostco." in notif.body
    assert "ran out of time" not in notif.body


def test_a_real_problem_keeps_its_warning_and_also_names_who_was_not_reached():
    broken = _recorded({**empty_stats(), "errors": ["HTTPError: 500"]})
    notif = classify_sync_result(_partial_run({"apple": broken, "meta": _UNREACHED, "google": _OK}))

    assert notif is not None
    assert (notif.priority, notif.category, notif.title) == ("normal", "sync_warning", "Scan finished with problems")
    assert "Problems at: Apple." in notif.body, "meta is not a problem, only not reached"
    assert "Not reached before the scan ran out of time: Meta." in notif.body
    assert notif.meta["error_sources"] == ["apple"]


def test_a_clean_run_still_says_nothing():
    run = _partial_run({"apple": _OK})
    assert run.status == "ok"
    assert classify_sync_result(run) is None


# --------------------------------------------------------------------------- #
# A company is named as the user follows it, in every row
# --------------------------------------------------------------------------- #


def _register_display(slug: str) -> str | None:
    """The name `tracked_company.display` holds for a slug once it is
    followed: a built-in is seeded from `config.COMPANIES`, anything else is
    written by `company_store.resolve_company`."""
    from tracker.company_store import CompanyError, resolve_company
    from tracker.config import COMPANIES

    if slug in COMPANIES:
        return COMPANIES[slug]["display"]
    try:
        return resolve_company(catalog_slug=slug)["display"]
    except CompanyError:
        return None


def test_every_known_company_is_named_as_the_register_names_it():
    """Never "Jane-Street", "Doordash" or "Drw": a short map with a
    `slug.title()` fallback misnames catalog companies."""
    from tracker.company_catalog import CATALOG
    from tracker.company_discovery import COMPANY_DISCOVERY
    from tracker.config import COMPANIES
    from tracker.notifications.render import _company_label

    wrong = {}
    for slug in sorted({*CATALOG, *COMPANY_DISCOVERY, *COMPANIES}):
        expected = _register_display(slug)
        if expected is not None and _company_label(slug) != expected:
            wrong[slug] = (_company_label(slug), expected)
    assert not wrong


@pytest.mark.parametrize(
    ("slug", "expected"),
    [("jane-street", "Jane Street"), ("doordash", "DoorDash"), ("drw", "DRW"),
     ("google-deepmind", "Google DeepMind"), ("scaleai", "Scale AI"), ("nvidia", "Nvidia")],
)
def test_a_catalog_company_is_never_its_slug(slug, expected):
    from tracker.notifications.render import _company_label

    assert _company_label(slug) == expected


def test_an_unknown_slug_never_shows_a_hyphen():
    from tracker.notifications.render import _company_label

    assert _company_label("acme-robotics-labs") == "Acme Robotics Labs"


def test_a_saved_role_names_its_company_as_the_user_follows_it():
    jane = JobStub(company="jane-street", title="Head of Product")
    assert classify_event("closed", {}, jane, True).title == "Jane Street closed a role you saved"
    door = JobStub(company="doordash")
    assert classify_event("reopened", {}, door, True).title == "DoorDash reposted a role you saved"

    # The register's own name wins over any fallback: a company added by its
    # careers link is named only there.
    acme = JobStub(company="acme-labs")
    names = {"acme-labs": "ACME Labs"}
    assert classify_event("closed", {}, acme, True, names=names).title == "ACME Labs closed a role you saved"
    raised = classify_event(
        "changed", {"disclosed_base": {"from": band(200_000, 240_000), "to": band(260_000, 300_000)}},
        acme, True, names=names,
    )
    assert raised.title == "ACME Labs raised the posted range on a role you saved"
    elsewhere = classify_event("closed", {}, acme, True, names=names, listed_elsewhere=[(7, "Austin")])
    assert elsewhere.title == "ACME Labs still lists a role you saved in another place"


def test_the_digest_lead_and_a_reminder_name_the_company_as_followed():
    digest = classify_daily_digest(
        "2026-10-08",
        [DigestMatch(1, "jane-street", "Head of Trading Tech", fit=0.7), DigestMatch(2, "acme-labs", "PM")],
        names={"acme-labs": "ACME Labs"},
    )
    assert digest.body.startswith("Strong fit: Head of Trading Tech at Jane Street")

    led_by_acme = classify_daily_digest(
        "2026-10-08", [DigestMatch(2, "acme-labs", "PM", fit=0.7)], names={"acme-labs": "ACME Labs"}
    )
    assert led_by_acme.body == "Strong fit: PM at ACME Labs"

    reminder = classify_pursuit_due("jane-street", "Head of Product", "applied", "Email Sam", 2)
    assert reminder.title == "Follow up with Jane Street · 2d overdue"
    named = classify_pursuit_due(
        "acme-labs", "PM", "applied", "Email Sam", 0, names={"acme-labs": "ACME Labs"}
    )
    assert named.title == "Follow up with ACME Labs · due today"


# --------------------------------------------------------------------------- #
# A scan the person stopped is their own act, never a failure
# --------------------------------------------------------------------------- #


def _stopped_run(per_source: dict) -> ScrapeRun:
    """What `POST /api/sync/cancel` records: the status `cancelled_run_status`
    projects from the companies already saved, and the stop note."""
    from tracker.connectors.recipes.outcome import STOPPED_BY_USER_NOTE, cancelled_run_status

    return ScrapeRun(
        status=cancelled_run_status(SourceOutcome(stats["outcome"]) for stats in per_source.values()),
        started_at=datetime(2026, 10, 8, 9, 0, tzinfo=UTC),
        finished_at=datetime(2026, 10, 8, 9, 2, tzinfo=UTC),
        jobs_seen=sum(int(s.get("kept") or 0) for s in per_source.values()), jobs_new=0, jobs_closed=0,
        per_source=per_source, drift_alerts=[], notes=STOPPED_BY_USER_NOTE,
    )


def test_a_scan_stopped_before_any_company_is_not_a_failure():
    run = _stopped_run({})
    assert run.status == "error", "the record stays what the cancel route writes"

    notif = classify_sync_result(run)
    assert notif is not None
    assert (notif.category, notif.priority, notif.title) == ("sync_unfinished", "low", "Scan stopped")
    assert notif.body == "You stopped it before it scanned any company."
    assert notif.meta["sync_state"] == "partial" and notif.meta["stopped_by_user"] is True
    assert "diagnostics" not in notif.meta


def test_a_scan_stopped_after_some_companies_says_what_it_found_is_saved():
    run = _stopped_run({"apple": _OK, "google": _OK})
    assert run.status == "partial"

    notif = classify_sync_result(run, names={"apple": "Apple", "google": "Google"})
    assert notif is not None
    assert (notif.category, notif.priority, notif.title) == ("sync_unfinished", "low", "Scan stopped")
    assert notif.body.startswith("You stopped it after it scanned 2 companies. What it found is saved.")
    assert "Problems" not in notif.body


def test_a_scan_stopped_after_a_company_failed_names_the_problem_but_not_a_failed_scan():
    broken = _recorded({**empty_stats(), "errors": ["HTTPError: 500"]})
    run = _stopped_run({"jane-street": broken})
    assert run.status == "error"

    notif = classify_sync_result(run)
    assert notif is not None
    assert (notif.category, notif.priority, notif.title) == ("sync_warning", "normal", "Scan stopped")
    assert notif.body.startswith("You stopped it after it scanned 1 company. Problems at: Jane Street.")
    assert "What was read is saved" not in notif.body, "nothing usable was read"


def test_a_genuine_failure_is_still_a_failed_scan():
    """The stop is told apart by the run's own note, never by an empty record:
    a run that died before collecting anything still fails out loud."""
    died = ScrapeRun(
        status="error", started_at=datetime(2026, 10, 8, 9, 0, tzinfo=UTC),
        finished_at=datetime(2026, 10, 8, 9, 0, 3, tzinfo=UTC), jobs_seen=0, jobs_new=0, jobs_closed=0,
        per_source={}, drift_alerts=[], notes="pipeline exception: OperationalError: connection refused",
    )
    notif = classify_sync_result(died)
    assert notif is not None
    assert (notif.category, notif.priority, notif.title) == (
        "sync_failed", "high", "Couldn't scan, nothing was updated",
    )
