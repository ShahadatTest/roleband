"""A build/database mismatch is OUR fault, and must be diagnosable.

A checkout older than the database it writes to can meet a binding whose
adapter that build does not carry (a company seeded with `adapter="lever"`, run
by a build with no Lever connector). Neither half below is the source's doing:

1. A bare `KeyError` from `build_adapter` would be recorded as a source error
   -> `FAILED` -> `ANOMALY`, marching a blameless binding toward quarantine
   once per run.
2. Which build ran is read from the run's own record, never inferred from
   incidental signatures.
"""

from __future__ import annotations

import pytest

from tests.factories import scope_filter
from tracker.connectors import UnknownAdapterError, build_adapter
from tracker.connectors.recipes.outcome import (
    RESETS_ABSENCE,
    SourceOutcome,
    classify_source_outcome,
)
from tracker.enrich.comp import CompResolver
from tracker.platform.ratelimit import RateLimiterPool
from tracker.platform.version import MAX_LEN, code_version
from tracker.workflows.collection import collect_source

# --- an unbuildable connector is a deployment fault ------------------------- #


def test_build_adapter_names_the_company_and_what_this_build_carries():
    with pytest.raises(UnknownAdapterError) as excinfo:
        build_adapter("spotify", "lever-v2")

    message = str(excinfo.value)
    assert "spotify" in message
    assert "lever-v2" in message
    # The available list is the actionable half: it says whether the row is a
    # typo or the checkout is stale.
    assert "greenhouse" in message
    assert excinfo.value.adapter_name == "lever-v2"


@pytest.mark.asyncio
async def test_an_unbuildable_connector_is_unattempted_not_a_source_failure():
    collection = await collect_source(
        "spotify",
        {"adapter": "lever-v2"},
        scope_filter(bands=set(), roles=set(), tracks=set(), locations=set(), domains=set()),
        CompResolver(),
        max_list=None,
        hydrate=False,
        limiter_pool=RateLimiterPool(),
    )

    stats = {**collection.stats, "list_complete": collection.list_complete}
    assert stats["unattempted"] is True
    assert stats["scanned"] == 0
    # Recorded for the operator, and it keeps closure suppressed...
    assert any("lever-v2" in err for err in stats["errors"])
    assert collection.list_complete is False
    # ...but `unattempted` is read before `errors`, so it does not masquerade
    # as the source having failed.
    assert classify_source_outcome(stats) is SourceOutcome.UNATTEMPTED


def test_a_missing_connector_never_counts_against_the_source():
    """A stale checkout without the connector asked the source nothing.

    Recorded as `failed`, it would reset every posting's absence count.
    `unattempted` neither counts a miss nor resets one.
    """
    assert SourceOutcome.FAILED in RESETS_ABSENCE  # what a bare KeyError would record
    assert SourceOutcome.UNATTEMPTED not in RESETS_ABSENCE  # what a missing connector records


# --- the run can name the build that produced it ---------------------------- #


def test_code_version_identifies_this_checkout_and_fits_the_column():
    version = code_version()
    assert version is not None, "the repo is a git checkout, so this must resolve"
    assert len(version) <= MAX_LEN
    # A bare sha does not say what ran when the tree has uncommitted edits, and
    # the branch is what a human recognizes.
    assert "(" in version or "-dirty" in version or version.isalnum()


def test_code_version_never_raises_when_git_is_unavailable(monkeypatch):
    """A deployment need not be a git checkout, and a scrape must never fail
    because it could not name itself."""
    import tracker.platform.version as version_module

    monkeypatch.setattr(version_module, "_git", lambda *args: None)
    version_module.code_version.cache_clear()
    try:
        assert version_module.code_version() is None
    finally:
        version_module.code_version.cache_clear()


def test_code_version_is_computed_once_per_process():
    calls: list[tuple] = []
    import tracker.platform.version as version_module

    real = version_module._git
    version_module.code_version.cache_clear()
    version_module._git = lambda *args: (calls.append(args), real(*args))[1]
    try:
        first, second = version_module.code_version(), version_module.code_version()
        assert first == second
        # Three git invocations for the first call, none for the second.
        assert len(calls) <= 3
    finally:
        version_module._git = real
        version_module.code_version.cache_clear()


def test_scrape_run_carries_the_column_so_the_question_is_a_lookup():
    from tracker.db.models import ScrapeRun

    column = ScrapeRun.__table__.c.code_version
    assert column.nullable is True  # an older row is honestly NULL
    assert column.type.length == MAX_LEN
