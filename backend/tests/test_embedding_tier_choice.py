"""Embedding tiers represent the same model in slightly different spaces.
    A tier switch must not leave a corpus spanning those spaces: the choice
    reaches the checkout's decision file, work is owed only when the tier
    changes, and a switch cannot start over a running embedder.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from tracker.db.models import AppSetting
from tracker.semantic import matching, provision, tier_store
from tracker.semantic.manifest import TIER_FP32, TIER_INT8

# Every test here reaches code that starts or signals a process on this
# machine, so none of them may.
pytestmark = pytest.mark.usefixtures("no_escape")


class _Session:
    """app_settings-backed fake: get() serves stored rows, execute() records upserts.

    `statements` keeps every statement in order, and `commits` marks where each
    commit fell among them — the tier switch's correctness is an *ordering*
    claim (the corpus invalidation must land in the same committed transaction
    as the choice, before anything is spawned), which a set of rows cannot show.
    """

    def __init__(self, rows: dict[str, dict] | None = None):
        self.rows = dict(rows or {})
        self.committed = False
        self.statements: list[str] = []

    async def get(self, model, key):
        assert model is AppSetting
        value = self.rows.get(key)
        return AppSetting(key=key, value=value) if value is not None else None

    async def execute(self, stmt, params=None):
        text = str(stmt).strip()
        self.statements.append(text)
        if "app_settings" in text.lower():
            compiled = stmt.compile()
            self.rows[compiled.params["key"]] = compiled.params["value"]

    async def commit(self):
        self.statements.append("COMMIT")
        self.committed = True



def _stop_answers(answer):
    """A re-embed stop that answers as the supervisor's would, without one."""

    async def stop(_session, **_kwargs):
        return answer

    return stop

@pytest.fixture
def tmp_models(tmp_path, monkeypatch):
    monkeypatch.setattr(provision, "DATA_DIR", tmp_path)
    return tmp_path / "models"


# --- the shared choice -------------------------------------------------------

def test_tier_choice_round_trips_and_clears(tmp_models):
    session = _Session()
    assert asyncio.run(tier_store.get_tier_choice(session)) is None

    asyncio.run(tier_store.set_tier_choice(session, TIER_FP32))
    assert asyncio.run(tier_store.get_tier_choice(session)) == TIER_FP32

    asyncio.run(tier_store.set_tier_choice(session, None))
    assert asyncio.run(tier_store.get_tier_choice(session)) is None


def test_a_retired_tier_reads_as_auto_not_as_an_error(tmp_models):
    """A manifest that stops offering a tier must degrade to auto-detection.
    Raising instead would mean the machine cannot embed at all — a stored
    preference is never worth more than a working encoder."""
    session = _Session({tier_store.TIER_KEY: {"tier": "fp16"}})
    assert asyncio.run(tier_store.get_tier_choice(session)) is None


def test_reconcile_pushes_a_user_choice_into_this_checkout(tmp_models, monkeypatch):
    """The cross-checkout guard. The decision file is per-checkout, the vectors
    it produces are per-user and shared, so a choice made elsewhere must land
    here before this checkout embeds anything."""
    monkeypatch.setattr(provision, "detect_total_ram_bytes", lambda: 8 * 2**30)
    session = _Session({tier_store.TIER_KEY: {"tier": TIER_FP32}})

    assert asyncio.run(tier_store.reconcile_tier(session)) == TIER_FP32
    # And it is on disk, because that file is all the sync encoder ever reads.
    assert provision.resolve_tier() == TIER_FP32
    assert provision.read_decision()["chosen_by"] == "user"


def test_reconcile_without_a_choice_never_re_decides(tmp_models, monkeypatch):
    """No user choice = leave the file alone. Re-deriving here would re-decide
    the tier on every startup, and a re-decision means a re-download and a
    corpus embedded across two spaces."""
    monkeypatch.setattr(provision, "detect_total_ram_bytes", lambda: 32 * 2**30)
    assert provision.resolve_tier() == TIER_FP32

    monkeypatch.setattr(provision, "detect_total_ram_bytes", lambda: 8 * 2**30)
    session = _Session()
    assert asyncio.run(tier_store.reconcile_tier(session)) == TIER_FP32


# --- the switch endpoint -----------------------------------------------------

@pytest.fixture
def switch(monkeypatch):
    """The endpoint with its side effects observable and none of them real."""
    from tracker.api.routers import intelligence as router

    spawned: list[bool] = []
    resets: list[bool] = []
    running = {"value": False}
    spawn_ok = {"value": True}

    async def fake_spawn(_session, *, requested_by):
        spawned.append(True)
        return spawn_ok["value"]

    async def fake_in_progress(session):
        return running["value"]

    monkeypatch.setattr("tracker.api.job_requests.ring_reembed", fake_spawn)
    monkeypatch.setattr(router, "_reembed_in_progress", fake_in_progress)
    monkeypatch.setattr("tracker.semantic.embed.reset_model", lambda: resets.append(True))

    async def fake_state(session):
        return {"matching": {"tier": provision.resolve_tier()}}

    monkeypatch.setattr(router, "_intelligence_state", fake_state)
    return SimpleNamespace(
        router=router, spawned=spawned, resets=resets, running=running, spawn_ok=spawn_ok
    )


def _put(router, session, tier):
    return asyncio.run(
        router.put_matching_tier_ep(router.MatchingTierPayload(tier=tier), session)
    )


def _stop(router, session):
    return asyncio.run(router.stop_matching_switch(session))


def test_switching_tier_records_applies_and_re_embeds(tmp_models, monkeypatch, switch):
    router, spawned, resets = switch.router, switch.spawned, switch.resets
    monkeypatch.setattr(provision, "detect_total_ram_bytes", lambda: 8 * 2**30)
    assert provision.resolve_tier() == TIER_INT8
    session = _Session()

    _put(router, session, TIER_FP32)

    assert session.rows[tier_store.TIER_KEY] == {"tier": TIER_FP32}
    assert session.committed  # the choice is durable BEFORE the job starts
    assert provision.resolve_tier() == TIER_FP32
    assert resets == [True]  # the live encoder cannot keep serving the old graph
    assert spawned == [True]


def test_reselecting_the_active_tier_costs_nothing(tmp_models, monkeypatch, switch):
    """A no-op must not re-embed an unchanged space."""
    router, spawned, resets = switch.router, switch.spawned, switch.resets
    monkeypatch.setattr(provision, "detect_total_ram_bytes", lambda: 8 * 2**30)
    session = _Session({tier_store.TIER_KEY: {"tier": TIER_INT8}})
    provision.set_tier(TIER_INT8)

    _put(router, session, TIER_INT8)

    assert spawned == []
    assert resets == []


def test_pinning_what_auto_already_chose_records_but_does_not_re_embed(
    tmp_models, monkeypatch, switch
):
    """Pinning is a real change of *decision* — it stops a future RAM
    re-detection moving the tier — but the space does not move, so the corpus
    stays valid and no re-embed is owed."""
    router, spawned = switch.router, switch.spawned
    monkeypatch.setattr(provision, "detect_total_ram_bytes", lambda: 8 * 2**30)
    assert provision.resolve_tier() == TIER_INT8
    session = _Session()

    _put(router, session, TIER_INT8)

    assert session.rows[tier_store.TIER_KEY] == {"tier": TIER_INT8}
    assert provision.read_decision()["chosen_by"] == "user"
    assert spawned == []


def test_restoring_auto_re_embeds_when_the_hardware_disagrees(
    tmp_models, monkeypatch, switch
):
    router, spawned = switch.router, switch.spawned
    monkeypatch.setattr(provision, "detect_total_ram_bytes", lambda: 8 * 2**30)
    provision.set_tier(TIER_FP32)
    session = _Session({tier_store.TIER_KEY: {"tier": TIER_FP32}})

    _put(router, session, None)

    assert session.rows[tier_store.TIER_KEY] == {}
    assert provision.resolve_tier() == TIER_INT8
    assert spawned == [True]


def test_a_switch_is_refused_while_one_is_running(tmp_models, monkeypatch, switch):
    """Two concurrent embedders would fight over the same rows. 409, not a
    second job — and crucially the choice must NOT be recorded either, or the
    file and the corpus would disagree with no job left to reconcile them."""
    from fastapi import HTTPException

    router, spawned, running = switch.router, switch.spawned, switch.running
    monkeypatch.setattr(provision, "detect_total_ram_bytes", lambda: 8 * 2**30)
    running["value"] = True
    session = _Session()

    with pytest.raises(HTTPException) as excinfo:
        _put(router, session, TIER_FP32)

    assert excinfo.value.status_code == 409
    assert tier_store.TIER_KEY not in session.rows
    assert spawned == []


def test_stop_restores_auto_even_after_the_new_tier_is_the_corpus_majority(
    tmp_models, monkeypatch, switch
):
    """Progress is not history: at 51% the majority names the NEW tier.

    Querying the corpus majority to decide where "go back" means would let a
    late cancel stop the process but keep the tier the user cancelled. The
    active artifact has exactly one counterpart; that
    invariant is the origin record at every progress point.
    """
    router = switch.router
    switch.running["value"] = True
    monkeypatch.setattr(provision, "detect_total_ram_bytes", lambda: 8 * 2**30)
    monkeypatch.setattr("tracker.api.job_requests.stop_reembed", _stop_answers(("stopped", 123)))

    class NoCorpusRead(_Session):
        async def scalar(self, _stmt):
            raise AssertionError("stop must not infer switch origin from corpus progress")

    # Auto originally chose int8; the user switched to fp32. Whether 1% or 99%
    # of rows now say fp32 must not change the restoration target.
    provision.set_tier(TIER_FP32)
    session = NoCorpusRead({tier_store.TIER_KEY: {"tier": TIER_FP32}})

    result = _stop(router, session)

    assert result["stopped"] is True
    assert session.rows[tier_store.TIER_KEY] == {}
    assert provision.resolve_tier() == TIER_INT8


def test_stop_restores_a_pinned_previous_tier_when_auto_would_not(
    tmp_models, monkeypatch, switch
):
    router = switch.router
    switch.running["value"] = True
    monkeypatch.setattr(provision, "detect_total_ram_bytes", lambda: 8 * 2**30)
    monkeypatch.setattr("tracker.api.job_requests.stop_reembed", _stop_answers(("stopped", 123)))

    # The machine would auto-select int8, so a switch back to fp32 must restore
    # the explicit pin rather than clear the choice to auto.
    provision.set_tier(TIER_INT8)
    session = _Session({tier_store.TIER_KEY: {"tier": TIER_INT8}})

    _stop(router, session)

    assert session.rows[tier_store.TIER_KEY] == {"tier": TIER_FP32}
    assert provision.resolve_tier() == TIER_FP32


def test_failed_stop_never_moves_the_choice_under_a_live_encoder(
    tmp_models, monkeypatch, switch
):
    from fastapi import HTTPException

    router = switch.router
    switch.running["value"] = True
    monkeypatch.setattr(provision, "detect_total_ram_bytes", lambda: 8 * 2**30)
    monkeypatch.setattr("tracker.api.job_requests.stop_reembed", _stop_answers(("error", 123)))
    provision.set_tier(TIER_FP32)
    session = _Session({tier_store.TIER_KEY: {"tier": TIER_FP32}})

    with pytest.raises(HTTPException) as excinfo:
        _stop(router, session)

    assert excinfo.value.status_code == 503
    assert session.rows[tier_store.TIER_KEY] == {"tier": TIER_FP32}
    assert provision.resolve_tier() == TIER_FP32


def test_unmanaged_embedder_is_not_reinterpreted_as_a_stopped_switch(
    tmp_models, monkeypatch, switch
):
    from fastapi import HTTPException

    router = switch.router
    switch.running["value"] = True
    monkeypatch.setattr(provision, "detect_total_ram_bytes", lambda: 8 * 2**30)
    monkeypatch.setattr("tracker.api.job_requests.stop_reembed", _stop_answers(("not_running", None)))
    provision.set_tier(TIER_FP32)
    session = _Session({tier_store.TIER_KEY: {"tier": TIER_FP32}})

    with pytest.raises(HTTPException) as excinfo:
        _stop(router, session)

    assert excinfo.value.status_code == 409
    assert session.rows[tier_store.TIER_KEY] == {"tier": TIER_FP32}
    assert provision.resolve_tier() == TIER_FP32


def test_the_corpus_is_invalidated_before_the_download_is_attempted(monkeypatch):
    """Ordering is the whole guarantee. If a download that fails came AFTER the
    invalidation was skipped, the corpus would stay marked embedded at the old
    tier while the machine runs the new one — and nothing would repair it,
    because the incremental trigger does not fire on a tier change."""
    from contextlib import asynccontextmanager

    from tracker.semantic import backfill

    events: list[str] = []

    class _Recorder:
        async def execute(self, stmt, params=None):
            # Lock bookkeeping is not the subject; only corpus writes are.
            if "embedded_at" in str(stmt):
                events.append(str(stmt).strip())

        async def scalar(self, stmt, params=None):
            return True  # the re-embed lock is free

        async def scalars(self, stmt):  # pragma: no cover - never reached here
            raise AssertionError("provisioning must fail before the corpus is read")

    @asynccontextmanager
    async def fake_scope():
        yield _Recorder()

    async def failing_provision():
        events.append("provision")
        raise RuntimeError("mirror unreachable")

    monkeypatch.setattr(backfill, "session_scope", fake_scope)
    monkeypatch.setattr(backfill, "_provision_current_tier", failing_provision)

    with pytest.raises(RuntimeError, match="mirror unreachable"):
        asyncio.run(backfill.run(open_only=False, refresh=True, provision_first=True))

    assert events == ["UPDATE jobs SET embedded_at = NULL", "provision"]


def test_the_switch_records_the_choice_and_touches_no_job_rows(
    tmp_models, monkeypatch, switch
):
    """The switch writes a CHOICE, and nothing else.

    It never blanks `embedded_at` across the whole table: `jobs.embedded_tier`
    is a property each row already carries, so a corpus owing work is marked
    without stamping every row, which is what makes stopping a switch cost only
    the rows already converted instead of all of them.

    If the spawned job never starts, every row still disagrees with the active
    tier, so the ordinary pass picks the work up with no bulk write. See
    `test_a_failed_spawn_still_leaves_the_corpus_self_healing`.
    """
    router, spawned = switch.router, switch.spawned
    monkeypatch.setattr(provision, "detect_total_ram_bytes", lambda: 8 * 2**30)
    assert provision.resolve_tier() == TIER_INT8
    session = _Session()

    _put(router, session, TIER_FP32)

    # The choice is committed before anything is spawned...
    assert any(
        "app_settings" in s.lower()
        for s in session.statements[: session.statements.index("COMMIT")]
    )
    assert spawned == [True]
    # ...and not one job row is rewritten to say so.
    assert not any("UPDATE jobs" in s for s in session.statements)
    assert not any("embedded_at" in s for s in session.statements)


def test_a_no_op_switch_never_invalidates_the_corpus(tmp_models, monkeypatch, switch):
    """Pinning the tier auto already chose changes the decision, not the space."""
    router = switch.router
    monkeypatch.setattr(provision, "detect_total_ram_bytes", lambda: 8 * 2**30)
    session = _Session()

    _put(router, session, TIER_INT8)

    assert not any("embedded_at" in s for s in session.statements)


def test_a_failed_spawn_still_leaves_the_corpus_self_healing(
    tmp_models, monkeypatch, switch
):
    """Silently returning success would show a settled screen while nothing ran.

    Recovery needs no bulk write: the choice is committed and the active tier
    has moved, so every already-embedded row disagrees with it and the ordinary
    pass converts them. The failure is still REPORTED (a 503, not a cheerful
    200) because "it will finish later" and "it is
    finishing now" are different things to a user watching the screen.
    """
    from fastapi import HTTPException

    router = switch.router
    switch.spawn_ok["value"] = False
    monkeypatch.setattr(provision, "detect_total_ram_bytes", lambda: 8 * 2**30)
    session = _Session()

    with pytest.raises(HTTPException) as excinfo:
        _put(router, session, TIER_FP32)

    assert excinfo.value.status_code == 503
    assert session.committed
    # The tier moved, which is exactly what makes the corpus self-healing.
    assert provision.resolve_tier() == TIER_FP32
    assert not any("UPDATE jobs" in s for s in session.statements)


def test_chosen_by_follows_the_database_not_the_local_file(tmp_models, monkeypatch):
    """The database is authoritative for `chosen_by`. A stale decision file
    must not report a user pin after another checkout restores auto, or the
    screen offers an automatic-choice action that can only be a no-op."""
    from tracker.api.routers import intelligence as router

    monkeypatch.setattr(provision, "detect_total_ram_bytes", lambda: 8 * 2**30)
    provision.set_tier(TIER_FP32)  # this checkout's file now says chosen_by=user
    assert provision.read_decision()["chosen_by"] == "user"

    async def no_reembed(session):
        return False

    monkeypatch.setattr(router, "_reembed_in_progress", no_reembed)

    class _CountingSession(_Session):
        async def execute(self, stmt, params=None):
            if "count" in str(stmt).lower():
                return SimpleNamespace(one=lambda: (0, 0, 0))
            return await super().execute(stmt, params)

        async def scalar(self, _stmt):
            # The stale-row count. Zero: this test is about which
            # source `chosen_by` reads from, not about corpus state.
            return 0

    # DB carries no choice (another checkout cleared it).
    state = asyncio.run(
        matching.matching_state(_CountingSession(), reembed_running=False)
    )
    assert state["chosen_by"] == "auto"


def test_a_second_embedder_is_refused_by_the_lock_not_by_a_pid_file(monkeypatch):
    """`_job_running` only validates a PID the API itself recorded, so a
    hand-run `python -m tracker.semantic.backfill` (the command the module
    documents) is invisible to it, and the API would start a second embedder
    over the same rows while reporting "not re-embedding". The guard is the
    advisory lock the backfill holds, which every embedder takes."""
    from contextlib import asynccontextmanager

    from tracker.semantic import backfill

    held = {"value": True}  # someone else already holds it

    class _Locked:
        async def scalar(self, stmt, params=None):
            return not held["value"]

        async def execute(self, stmt, params=None):
            return None

    @asynccontextmanager
    async def fake_scope():
        yield _Locked()

    monkeypatch.setattr(backfill, "session_scope", fake_scope)

    with pytest.raises(backfill.AlreadyEmbedding):
        asyncio.run(backfill.run(open_only=False, refresh=True))

    # And the probe the API uses reports it, with no PID file anywhere.
    assert asyncio.run(backfill.is_running(_Locked())) is True
    held["value"] = False
    assert asyncio.run(backfill.is_running(_Locked())) is False


def test_embedding_commits_in_batches_so_progress_moves_and_survives_a_kill(monkeypatch):
    """A full re-embed is not ONE transaction over the whole corpus: that would
    make nothing durable until the last row, so a kill late in the run would
    discard all of it and the Settings progress count would sit at zero for the
    entire run before jumping to the total."""
    from tracker.semantic import backfill

    commits: list[int] = []
    seen: list[int] = []

    class _Batch:
        async def commit(self):
            commits.append(len(seen))

    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def fake_scope():
        s = _Batch()
        yield s
        await s.commit()

    async def fake_embed_jobs(session, ids):
        seen.extend(ids)
        return len(ids)

    monkeypatch.setattr(backfill, "session_scope", fake_scope)
    monkeypatch.setattr(backfill, "embed_jobs", fake_embed_jobs)

    total = asyncio.run(backfill._embed_in_batches(list(range(450))))

    assert total == 450
    assert seen == list(range(450))  # every row, once, in order
    # Durable in pieces: three commits at 200 / 400 / 450, not one at the end.
    assert commits == [200, 400, 450]


def test_an_unpinned_tier_is_refused_at_the_edge():
    """422 from the payload, never a KeyError inside spec.tiers after commit."""
    from pydantic import ValidationError

    from tracker.api.routers.intelligence import MatchingTierPayload

    with pytest.raises(ValidationError):
        MatchingTierPayload(tier="fp16")
