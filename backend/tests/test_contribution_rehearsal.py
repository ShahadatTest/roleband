"""The offline contribution rehearsal: the worked example runs, and stays test-only.

`docs/development.md` §6.2 tells a contributor how to add a listing adapter;
`tests/example_adapter.py` is that recipe as runnable code. This file is the
part that makes the example safe to ship: a fake provider must be able to run
end to end WITHOUT being something production could ever discover or point at a
real board.

Four claims, and the last is the one worth having:

1. the example actually works: it pages, stops, yields valid `RawJob`s, and
   records every row it cannot use, so a copy of it cannot drop a live
   posting's row and still call the listing complete;
2. production cannot see it: it is absent from `ADAPTER_REGISTRY`, and it
   lives in `tests/`, which `tracker/` never imports;
3. it starts no live work: the whole file runs under `no_escape`, which
   refuses subprocesses and every network transport, so a hidden fetch fails
   here rather than on someone's machine;
4. **an incomplete registration fails BY NAME**: the thing a contributor
   actually gets wrong is registering an adapter and forgetting one of the
   artifacts that must ship with it.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from tests.contracts.artifacts import missing_artifacts
from tests.example_adapter import EXAMPLE_PAGES, PAGE_SIZE, ExampleAdapter
from tracker.connectors import ADAPTER_REGISTRY
from tracker.platform.paging import StopReason
from tracker.schema import RawJob, dedupe_key_for

# The example must not be able to act on this machine even by accident.
pytestmark = pytest.mark.usefixtures("no_escape")

_BACKEND = Path(__file__).resolve().parents[1]


async def _collect(adapter: ExampleAdapter) -> list[RawJob]:
    return [job async for job in adapter.fetch()]


# --------------------------------------------------------------------------- #
# 1. The example works
# --------------------------------------------------------------------------- #


def test_the_example_yields_valid_rawjobs_across_pages():
    adapter = ExampleAdapter("example-co")
    jobs = asyncio.run(_collect(adapter))

    assert [job.req_id for job in jobs] == ["EX-1", "EX-2", "EX-3"], (
        "the example must page: three postings across two pages, the second short"
    )
    assert all(isinstance(job, RawJob) for job in jobs)
    assert all(job.company == "example-co" for job in jobs), (
        "a RawJob carries the company slug the adapter was built for, not the source's"
    )
    assert jobs[1].locations == ["London, UK"]
    assert jobs[2].department == "Product"
    assert adapter.drift.listing_complete is True, "clean pages must leave the listing complete"
    assert adapter.drift.alerts == []


def test_the_example_stops_on_the_source_signal_rather_than_running_on():
    """A short page is the end of the board, and that is what ends the scan.

    An adapter that keeps asking until a page repeats is how a scan runs
    forever; the connector contract plants exactly that case for every real
    adapter, so the example has to model the correct shape.
    """

    assert len(EXAMPLE_PAGES[-1]) < PAGE_SIZE, "the example's last page must be short"
    adapter = ExampleAdapter("example-co")
    asyncio.run(_collect(adapter))

    [query] = adapter.query_observations
    assert query.pages_used == len(EXAMPLE_PAGES), "the scan asked past the short last page"
    assert query.stop_reason is StopReason.STOPPED
    assert adapter.truncated is False


def test_a_row_without_an_id_is_counted_as_lost():
    """A row that names no posting is a real loss, so the run closes nothing.

    Skipped rather than raised, since an exception costs the whole page, and
    never skipped silently: a listing that hid the loss would read as complete,
    and closure would treat a live posting it could not see as gone.
    """

    adapter = ExampleAdapter("example-co")

    assert adapter._to_raw_job({"id": "", "title": "No id", "absolute_url": "u"}) is None
    assert adapter.drift.records_dropped == 1
    assert adapter.drift.listing_complete is False


def test_a_row_with_only_an_id_keeps_its_posting_open():
    """The id is all closure needs, so the listing stays complete.

    Counting the row as lost instead would take closure away from every healthy
    posting on the board to protect this one.
    """

    adapter = ExampleAdapter("example-co")

    assert adapter._to_raw_job({"id": "X", "title": "", "absolute_url": "u"}) is None
    assert adapter._to_raw_job({"id": "Y", "title": "T", "absolute_url": ""}) is None
    assert adapter.drift.present_only == {
        dedupe_key_for("example-co", "X"),
        dedupe_key_for("example-co", "Y"),
    }
    assert adapter.drift.records_dropped == 0
    assert adapter.drift.listing_complete is True


# --------------------------------------------------------------------------- #
# 2-3. It is test-only, and it acts on nothing
# --------------------------------------------------------------------------- #


def test_the_example_is_invisible_to_production_discovery():
    assert "example" not in ADAPTER_REGISTRY, (
        "the example adapter is in ADAPTER_REGISTRY, which is production discovery: the "
        "scheduler would schedule it and a run would try to collect from it. It is a "
        "teaching artifact and must stay out."
    )
    assert not any(
        isinstance(value, type) and value.__module__.startswith("tests.")
        for value in ADAPTER_REGISTRY.values()
    ), "an adapter defined under tests/ is registered for production"


def test_the_example_lives_where_production_cannot_reach_it():
    """`tracker/` never imports `tests/`, and that is the containment.

    Registering it would not be enough to make it dangerous, and forgetting to
    register it is not what keeps it safe: its location is.
    """

    assert (_BACKEND / "tests" / "example_adapter.py").exists()
    assert not (_BACKEND / "tracker" / "connectors" / "listing" / "example.py").exists()

    offenders = [
        path.relative_to(_BACKEND).as_posix()
        for path in (_BACKEND / "tracker").rglob("*.py")
        if "tests.example_adapter" in path.read_text() or "from tests" in path.read_text()
    ]
    assert not offenders, f"production code imports the test tree: {offenders}"


def test_the_example_reaches_no_network():
    """Held by `no_escape`, which refuses every network transport.

    The example runs its whole scan under that refusal, so a fetch smuggled into
    it fails here, not against a real board.
    """

    jobs = asyncio.run(_collect(ExampleAdapter("example-co")))
    assert len(jobs) == 3


# --------------------------------------------------------------------------- #
# 4. An incomplete registration fails by name
# --------------------------------------------------------------------------- #


def test_an_incomplete_registration_is_reported_by_name():
    """What a contributor actually gets wrong.

    Registering the class is the easy half; the fixtures and the harness ship in
    the same change or the adapter is untested. `missing_artifacts` is the
    completeness gate's own logic, called here with a name that was never
    onboarded: the same shape as handing the route-table gate a throwaway app.
    """

    problems = missing_artifacts(["newsource"])

    assert len(problems) == 2, problems
    joined = "\n".join(problems)
    assert "newsource" in joined, "the failure must name the adapter, not just count"
    assert "tests/fixtures/listings/newsource/page1.json" in joined
    assert "HARNESSES" in joined


def test_a_complete_registration_reports_nothing():
    """The control: the gate is not simply always angry."""

    assert missing_artifacts(["greenhouse"]) == []
