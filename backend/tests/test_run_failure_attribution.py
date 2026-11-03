"""A failure is attributed to the thing that failed.

A run can collect every source cleanly — `list_complete`, `closure_eligible`,
binding still `healthy` — and then fail in a post-pass (the embedding pass
raising because a checkout has no model weights). The feed must not then say

    Scan finished with problems
    Problems at: all enabled sources.
    spotify | 71 | 13 | 9 | 0 | 4s | ok

two halves of one notification, disagreeing. Nor may the run's status become
`error`: `run_status_for` defines it as "no source produced usable data", and
`health.REFRESHED_STATUSES` excludes it on precisely that reading. A derivation
failing over healthy sources would freeze `last_success_at`, leave `stale` true,
and have `should_catch_up` kick another run into the same wall every hour.

These tests hold the three claims apart, because they fail differently.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from tracker.connectors.recipes.outcome import SourceOutcome, run_status_for
from tracker.db.models import ScrapeRun
from tracker.health import REFRESHED_STATUSES, freshness, should_catch_up
from tracker.notifications.render import _affected_summary
from tracker.notifications.run_result import classify_sync_result


def _run(status: str, per_source: dict, *, notes: str | None = None) -> ScrapeRun:
    started = datetime(2026, 9, 20, 23, 21, 4, tzinfo=UTC)
    return ScrapeRun(
        started_at=started,
        finished_at=started + timedelta(seconds=5),
        status=status,
        scope="targeted",
        per_source=per_source,
        drift_alerts=[],
        notes=notes,
        jobs_seen=13,
        jobs_new=9,
        jobs_closed=0,
    )


#: A source that collected cleanly: complete, nothing wrong.
CLEAN_SOURCE = {
    "spotify": {
        "scanned": 71, "kept": 13, "new": 9, "closed": 0,
        "errors": [], "outcome": "ok", "list_complete": True,
    }
}


# --------------------------------------------------------------------------- #
# 1. The status is the sources' verdict, and nothing else writes it.
# --------------------------------------------------------------------------- #


def test_a_clean_collection_projects_to_a_refreshing_status():
    status = run_status_for([SourceOutcome.OK])
    assert status == "ok"
    assert status in REFRESHED_STATUSES


def test_error_still_means_no_source_produced_usable_data():
    # The word has to keep meaning this, or excluding it from REFRESHED_STATUSES
    # stops being justified.
    assert run_status_for([SourceOutcome.FAILED]) == "error"
    assert "error" not in REFRESHED_STATUSES


def test_a_derivation_failure_must_not_freeze_freshness():
    """The loop, stated as the arithmetic that produced it.

    A run that collected cleanly is the newest refresh. Marking it `error`
    removes it from that query, so the age is measured from the run before —
    and once that crosses the threshold the watchdog starts another run, which
    fails the same way.
    """
    now = datetime(2026, 9, 21, 12, 0, tzinfo=UTC)
    collected_at = now - timedelta(hours=1)
    stale_before = now - timedelta(hours=40)
    max_hours = 24

    # The rule: the clean collection counts, so nothing is stale.
    _, stale = freshness(collected_at, now, max_hours)
    assert stale is False
    assert should_catch_up({"stale": stale, "last_run_status": "ok"}) is False

    # What assigning `error` would produce: the run is invisible to the freshness
    # query, the age comes from the previous one, and the watchdog re-fires.
    _, stale_old = freshness(stale_before, now, max_hours)
    assert stale_old is True
    assert should_catch_up({"stale": stale_old, "last_run_status": "error"}) is True


# --------------------------------------------------------------------------- #
# 2. An empty list of culprits is not every culprit.
# --------------------------------------------------------------------------- #


def test_no_source_at_fault_does_not_read_as_every_source():
    summary = _affected_summary([], [])
    assert "all enabled sources" not in summary
    assert summary == "no single company; see the scan's notes"


def test_a_source_at_fault_is_still_named():
    """Alerts are `{adapter}:{company}` (`BaseAdapter`'s drift recorder).
    Reading the part before the colon would name the provider: "Problems at:
    Oracle" for Fortinet."""
    assert _affected_summary(["spotify"], []) == "Spotify"
    assert _affected_summary([], [{"source": "oracle:fortinet"}]) == "Fortinet"
    assert _affected_summary([], [{"source": "google:google"}]) == "Google"


def test_a_company_at_fault_is_named_as_the_user_knows_it():
    """The slug is a key, not a name: "google-deepmind" and "meta" are what the
    table stores, "Google DeepMind" and "Meta" are what the user tracks."""
    names = {"google-deepmind": "Google DeepMind", "openai": "OpenAI"}
    summary = _affected_summary(
        ["google-deepmind"], [{"source": "ashby:openai"}], lambda s: names.get(s, s)
    )
    assert summary == "Google DeepMind, OpenAI"


# --------------------------------------------------------------------------- #
# 3. The notification says which thing failed.
# --------------------------------------------------------------------------- #


def test_a_derivation_failure_names_the_derivation_not_the_sources():
    notif = classify_sync_result(
        _run("ok", CLEAN_SOURCE, notes="pipeline exception: ModelNotReady: ..."),
        failure="ModelNotReady: embedding model lightonai/DenseOn (fp32) is not provisioned yet",
    )
    assert notif is not None
    assert notif.category == "sync_warning"
    assert "derivation failed" in notif.title
    # The body must not blame sources that were fine.
    assert "all enabled sources" not in (notif.body or "")
    assert "spotify" not in (notif.body or "")
    assert "ModelNotReady" in (notif.body or "")
    assert notif.meta["failure"].startswith("ModelNotReady")


def test_a_derivation_failure_is_never_silent():
    """The status is `ok`, so the status alone cannot raise it."""
    run = _run("ok", CLEAN_SOURCE)
    assert classify_sync_result(run) is None, "a genuinely clean run is not news"
    assert classify_sync_result(run, failure="boom") is not None


def test_a_real_source_failure_still_names_the_source():
    broken = {
        "spotify": {
            "scanned": 0, "kept": 0, "new": 0, "closed": 0,
            "errors": ["HTTP 500"], "outcome": "failed",
        }
    }
    notif = classify_sync_result(_run("error", broken), failure="RuntimeError: collection died")
    assert notif is not None
    assert notif.category == "sync_failed"
    assert "Spotify" in (notif.body or "")


def test_a_source_failure_beside_a_derivation_failure_names_the_source():
    """Both went wrong: the source is the actionable one and keeps the headline."""
    mixed = {
        "spotify": {"scanned": 71, "kept": 13, "new": 9, "closed": 0,
                    "errors": [], "outcome": "ok"},
        "google": {"scanned": 0, "kept": 0, "new": 0, "closed": 0,
                   "errors": ["HTTP 429"], "outcome": "failed"},
    }
    notif = classify_sync_result(_run("partial", mixed), failure="ModelNotReady: ...")
    assert notif is not None
    assert "Google" in (notif.body or "")
    assert "derivation failed" not in notif.title
    # ...and the derivation failure is still carried, just not as the headline.
    assert notif.meta["failure"].startswith("ModelNotReady")


def test_a_clean_run_with_no_failure_stays_quiet():
    assert classify_sync_result(_run("ok", CLEAN_SOURCE)) is None


def test_a_partial_run_still_speaks_up():
    """`partial` is a successful refresh AND still worth a word — both hold.

    The word is for the source that made it partial, so the fixture carries
    one: a status the sources do not project is not a run."""
    degraded = {"scanned": 40, "kept": 2, "new": 0, "closed": 0, "errors": [],
                "list_complete": False, "listing_invalidated": True}
    run = _run("partial", {**CLEAN_SOURCE, "google": degraded})
    assert run.status in REFRESHED_STATUSES
    notif = classify_sync_result(run)
    assert notif is not None and notif.category == "sync_warning"
