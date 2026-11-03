"""The ownership registry's writer, reader and lifecycle fields, held to the code.

`test_table_ownership.py` proves every table is CLAIMED. This proves the claim's
neighbours are true: that the declared writers are the writers, that a table
declaring no reader really has none, and that history is not being overwritten.

**Every check here is one-directional, and saying so is not a disclaimer — it is
the design.** `table_writers.py` resolves what it can (model classes, import
aliases, local bindings, rows loaded by `select`/`get` and then mutated) and
cannot follow a row handed back by a function: a helper that returns a row its
caller mutates makes that table scan as insert-only although it is updated
every run. A scan like that can prove a
declaration WRONG. It can never prove one complete, and a gate that claimed
otherwise would measure names, not behaviour. So:

* found writers must be a SUBSET of declared writers — an undeclared writer fails;
* `readers=()` must find no reader — a table claiming to be dead that is not fails;
* `lifecycle="append_only"` must find no update, delete or upsert;
* router writers must be exactly `ROUTER_WRITERS`, which may only shrink.

Never widen a declaration to make this pass without reading the write it names.
"""

from __future__ import annotations

import pytest

from tests.table_writers import kinds_by_table, scan_readers, scan_writers, writers_by_table
from tracker.db.ownership import LIFECYCLES, TABLE_OWNERS

#: Every (router, table) pair where an API handler writes rows itself instead of
#: calling a store. Frozen and SHRINK-ONLY: a router may stop writing, never start.
#:
#: The routers that commit but are absent here — companies, intelligence,
#: ops — delegate every write to a store and so are correctly absent; they commit a unit of work they did not
#: compose.
#:
#: `jobs.py`/`favorites` is the one to read twice: ADDING a favorite goes through
#: `agents.pursuits.ensure_favorite`, while REMOVING one still deletes
#: the row in the handler. One table, two layers, depending on the verb — which is
#: why the ratchet is keyed by (router, table) and not by router.
ROUTER_WRITERS: frozenset[tuple[str, str]] = frozenset(
    {
        ("tracker/api/routers/jobs.py", "compare_selection"),
        ("tracker/api/routers/jobs.py", "favorites"),
        ("tracker/api/routers/jobs.py", "job_feedback"),
        ("tracker/api/routers/jobs.py", "jobs"),
        ("tracker/api/routers/lineage.py", "job_lineage_link"),
        ("tracker/api/routers/notifications.py", "notifications"),
        ("tracker/api/routers/profile.py", "profile_suggestions"),
        ("tracker/api/routers/settings.py", "company_scope_rules"),
    }
)

_MUTATING = {"update", "delete", "upsert"}


def test_every_writer_the_scan_finds_is_declared():
    found = writers_by_table()
    undeclared = {
        table: sorted(modules - set(TABLE_OWNERS[table].writers))
        for table, modules in found.items()
        if modules - set(TABLE_OWNERS[table].writers)
    }
    assert not undeclared, (
        f"these modules write tables that do not name them as writers: {undeclared}. "
        "Add the module to that table's `writers` in tracker/db/ownership.py — or, if the "
        "write does not belong there, move it. Do not widen the declaration without reading it."
    )


def test_declared_writers_are_not_stale():
    """A declared writer the scan cannot corroborate is named, not failed.

    The scan under-reports by construction, so a writer it misses is expected
    rather than wrong — but a declaration naming a module that does not exist
    is always a defect, and that much can be checked.
    """

    from tests.table_writers import BACKEND

    missing = {
        table: [module for module in ownership.writers if not (BACKEND / module).exists()]
        for table, ownership in TABLE_OWNERS.items()
        if any(not (BACKEND / module).exists() for module in ownership.writers)
    }
    assert not missing, f"`writers` name modules that do not exist: {missing}"


def test_a_table_declaring_no_reader_really_has_none():
    """The `readers=()` claim is the one reader claim worth enforcing.

    Three are recorded: `scrape_source_runs` and `comp_metrics` are written
    every run and read by nothing, and `binding_reconciliation_decisions` has
    neither. If a consumer appears, this fails and the claim gets corrected —
    which is the point of writing dead data down rather than deleting it.
    """

    readers = scan_readers()
    contradicted = {
        table: sorted(readers.get(table, ()))
        for table, ownership in TABLE_OWNERS.items()
        if not ownership.readers and readers.get(table)
    }
    assert not contradicted, (
        f"these tables declare `readers=()` but are read: {contradicted}. "
        "Record the read owner instead — a table with a consumer is not dead data."
    )


def test_append_only_tables_are_never_updated_or_deleted():
    """AGENTS.md's central data rule, as far as a scan can hold it.

    This cannot prove a table IS append-only — the scan is
    blind to a row returned from a helper — but an update, delete or upsert it
    DOES find on one of these six is a true positive, and the longitudinal asset
    is what is at stake.
    """

    kinds = kinds_by_table()
    violated = {
        table: sorted(kinds.get(table, set()) & _MUTATING)
        for table, ownership in TABLE_OWNERS.items()
        if ownership.lifecycle == "append_only" and kinds.get(table, set()) & _MUTATING
    }
    assert not violated, (
        f"history is being rewritten: {violated}. Either the write is wrong, or the table "
        "is not append_only — decide which, and do not relabel it to make this pass."
    )


def test_router_writers_are_frozen_and_may_only_shrink():
    found = {
        (module, table)
        for table, hits in scan_writers().items()
        for module, _ in hits
        if module.startswith("tracker/api/routers/")
    }
    added = sorted(found - ROUTER_WRITERS)
    assert not added, (
        f"new router writers: {added}. A handler that writes rows itself is the pattern this "
        "ratchet freezes — put the write in a store the router calls, as companies, intelligence "
        "and ops already do."
    )
    removed = sorted(ROUTER_WRITERS - found)
    assert not removed, (
        f"these router writers are gone: {removed} — good. Delete them from ROUTER_WRITERS so "
        "the ratchet records the new floor; it may only shrink."
    )


def test_lifecycles_and_claims_are_from_the_vocabulary():
    bad = {
        table: ownership.lifecycle
        for table, ownership in TABLE_OWNERS.items()
        if ownership.lifecycle not in LIFECYCLES
    }
    assert not bad, f"unknown lifecycle(s): {bad}; known: {sorted(LIFECYCLES)}"


def test_an_unpopulated_table_has_no_writer_and_a_written_one_does():
    """The two halves of `unpopulated` agree with the scan.

    A table labelled unpopulated that something writes is the
    registered-but-never-run bug inverted: the schema says "no feature yet"
    while rows are arriving.
    """

    found = writers_by_table()
    writing = sorted(
        table
        for table, ownership in TABLE_OWNERS.items()
        if ownership.lifecycle == "unpopulated" and found.get(table)
    )
    assert not writing, (
        f"these tables are labelled `unpopulated` but are written: {writing}. "
        "Give them a real claim and lifecycle."
    )


# --------------------------------------------------------------------------- #
# The scan itself, held to planted code
# --------------------------------------------------------------------------- #


_PLANTED = """
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from tracker.db.models import Job, JobObservation, ScrapeRun

async def writes(session):
    session.add(JobObservation(job_id=1))
    await session.execute(delete(Job))
    alias = ScrapeRun
    await session.execute(pg_insert(alias).values(id=1).on_conflict_do_update(index_elements=["id"]))
    row = await session.get(Job, 1)
    row.status = "closed"
"""


@pytest.mark.parametrize(
    ("table", "kind"),
    [
        ("job_observations", "insert"),   # session.add(Model(...))
        ("jobs", "delete"),               # delete(Model) through a sqlalchemy import
        ("scrape_runs", "upsert"),        # pg_insert alias + on_conflict_do_update
        ("jobs", "update"),               # attribute mutation on a loaded row
    ],
)
def test_the_scan_finds_each_write_form(tmp_path, table, kind):
    """Fail-first for the scanner: each detector fires on code planted for it.

    Without this the gate could silently stop detecting a form — and a scan that
    finds nothing passes every subset check above.
    """

    (tmp_path / "tracker").mkdir()
    (tmp_path / "tracker" / "planted.py").write_text(_PLANTED)
    (tmp_path / "scripts").mkdir()
    hits = scan_writers(tmp_path)
    assert (("tracker/planted.py", kind)) in hits.get(table, set()), (
        f"the scan no longer detects {kind} on {table}; found {sorted(hits.get(table, ()))}"
    )


def test_an_undeclared_writer_is_reported(tmp_path):
    """The gate's own failure path, proven rather than assumed."""

    (tmp_path / "tracker").mkdir()
    (tmp_path / "scripts").mkdir()
    (tmp_path / "tracker" / "planted.py").write_text(
        "from tracker.db.models import JobObservation\n"
        "def w(session):\n    session.add(JobObservation(job_id=1))\n"
    )
    found = {t: {m for m, _ in hits} for t, hits in scan_writers(tmp_path).items()}
    declared = set(TABLE_OWNERS["job_observations"].writers)
    assert found["job_observations"] - declared == {"tracker/planted.py"}
