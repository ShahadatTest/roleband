"""The run tail must record a failure even when the failure was the database.

`run_pipeline` commits its "running" marker at open, then does the whole run and
writes the terminal status at the end. Its recovery block is what turns a crash
into a recorded `error`, and it flushed on whatever session state the exception
left behind.

That is fine for an ordinary exception and wrong for the one that matters. If the
original error was a DB error, the session is in a pending-rollback state, so the
first statement in the recovery block raises `PendingRollbackError` -- which
replaces the real exception on the way out AND skips the status write, leaving the
row at `running`. `running` is the single status the reconciler cannot tell from a
live run until it goes stale, so the failure is invisible for `stale_run_minutes`
and the original cause is gone entirely.

The same module already gets this right for post-passes (`_record_derivation`
rolls back first, and says why). This is the run-level twin.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

import pytest
from sqlalchemy import select, text

from tracker.db.models import ScrapeRun
from tracker.workflows import pipeline as pipeline_module
from tracker.workflows import post_passes as post_passes_module
from tracker.workflows import run_persistence as run_persistence_module

pytestmark = pytest.mark.asyncio


async def test_a_db_error_in_the_run_tail_is_still_recorded_as_error(db_session, monkeypatch):
    @asynccontextmanager
    async def _scope():
        # The pipeline must stay inside the scratch database this test owns.
        yield db_session

    calls = {"n": 0}

    async def poison_then_fail(session, run, **kwargs):
        """A DB error, swallowed by a caller, then an unrelated failure.

        This is the real shape: something upstream catches a statement error and
        re-raises its own, so the session is already poisoned by the time the
        recovery block runs.

        Fails ONCE. The recovery block calls this same function again to write
        the failure notification, and a stub that exploded every time would be
        testing a second, different defect (a recovery path that cannot survive
        its own notification failing) instead of this one.
        """
        calls["n"] += 1
        if calls["n"] > 1:
            return 0
        try:
            await session.execute(text("SELECT * FROM a_table_that_does_not_exist"))
        except Exception:  # noqa: BLE001 - poisoning the session is the point
            pass
        raise RuntimeError("run tail exploded")

    monkeypatch.setattr(pipeline_module, "session_scope", _scope)
    monkeypatch.setattr(run_persistence_module, "generate_notifications", poison_then_fail)

    # The ORIGINAL exception must survive, never a PendingRollbackError from
    # the recovery block's own flush.
    with pytest.raises(RuntimeError, match="run tail exploded"):
        await pipeline_module.run_pipeline(companies=["__no_such_company__"], hydrate=False)

    runs = (await db_session.scalars(select(ScrapeRun))).all()
    assert len(runs) == 1, "the run marker should have been opened exactly once"
    assert runs[0].status == "error", (
        "the run was left at 'running' after a DB-error failure — the reconciler "
        "cannot distinguish that from a live run until it goes stale"
    )
    assert "run tail exploded" in (runs[0].notes or ""), (
        "the recorded note names the wrong exception, so the real cause was masked"
    )


async def test_a_fatal_post_pass_failure_is_recorded_as_itself(db_session, monkeypatch):
    """The same guarantee, for the failure a fresh install actually meets.

    `./setup.sh` does not provision the embedding model, so a fresh install's
    first scrape stops at the embeddings pass — fatal by design
    (`tracker/semantic/provision.py`), and that is what must reach the operator.
    `run_post_passes` rolls the session back before it records a fatal pass's
    failure; the rollback expires every object, so a run-level recovery block
    that then reads `run.id` does a lazy load and raises MissingGreenlet,
    replacing the real error and leaving the run `running`. Reading it before the recovery block's OWN rollback is not
    enough: this earlier rollback defeats that.
    """

    @asynccontextmanager
    async def _scope():
        yield db_session

    async def weights_missing(ctx):
        # The real pass reads the shared tier decision before it asks for the
        # model, so a transaction is open when it raises. Without a statement
        # here the loop's rollback is a no-op, nothing expires, and this test
        # would pass against the defect.
        await ctx.session.execute(text("SELECT 1"))
        raise RuntimeError("embedding model lightonai/DenseOn (int8) is not provisioned yet")

    monkeypatch.setattr(pipeline_module, "session_scope", _scope)
    monkeypatch.setattr(
        post_passes_module,
        "POST_PASSES",
        (post_passes_module.PostPass("embeddings", weights_missing, discovery_ok=True, fatal=True),),
    )

    with pytest.raises(RuntimeError, match="not provisioned yet"):
        await pipeline_module.run_pipeline(companies=["__no_such_company__"], hydrate=False)

    runs = (await db_session.scalars(select(ScrapeRun))).all()
    assert len(runs) == 1
    assert runs[0].status == "error", "left at 'running': the failure was masked on the way out"
    assert "not provisioned yet" in (runs[0].notes or "")

