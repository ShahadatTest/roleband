"""POST_PASSES table contract.

Pins the load-bearing properties of the post-persist pass table: order,
capped-scan exclusions, settings gates, and the fatal/non-fatal failure
policy of the executing loop.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from tracker.workflows.collection_types import ScanMode
from tracker.workflows.post_passes import (
    POST_PASSES,
    PostPass,
    PostPassContext,
    _pass_demand_metrics,
    _record_derivation,
    run_post_passes,
    run_scheduled_pass,
)


class _PoisonError(Exception):
    """Stand-in for SQLAlchemy's PendingRollbackError."""


class FakeSession:
    """Models the one behavior the loop's rollback turns on: a failed flush
    poisons the session, and every later operation raises until ``rollback()``
    clears it.

    This is the state a caught non-fatal pass leaves the shared session in, and
    the next fatal pass dies on it. A bare object() cannot express that; this can, deterministically.
    """

    def __init__(self):
        self.poisoned = False
        self.commits = 0
        self.rollbacks = 0
        self.calls: list[str] = []

    async def flush(self):
        self.calls.append("flush")
        if self.poisoned:
            raise _PoisonError("session is in a pending-rollback state")

    async def commit(self):
        self.calls.append("commit")
        if self.poisoned:
            raise _PoisonError("session is in a pending-rollback state")
        self.commits += 1

    async def rollback(self):
        self.calls.append("rollback")
        self.poisoned = False
        self.rollbacks += 1

    async def execute(self, *_args, **_kwargs):
        self.calls.append("execute")
        if self.poisoned:
            raise _PoisonError("session is in a pending-rollback state")

    async def fail_flush(self):
        """Simulate a flush that overflows a column: poison, then raise."""
        self.poisoned = True
        raise _PoisonError("value too long for type character varying(64)")


def _settings(**overrides):
    base = {
        "intelligence_extract_in_pipeline": True,  # on by default
        "intelligence_max_per_run": 50,
        "lineage_enabled": True,
        "lineage_max_per_run": 500,
        "twin_enabled": True,
        "twin_max_per_run": 500,
        "tiingo_api_key": None,  # no environment key: the prices pass skips itself
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _ctx(*, max_list=None, settings=None, session=None, touched_ids=None):
    return PostPassContext(
        session=session if session is not None else FakeSession(),
        touched_ids=[1] if touched_ids is None else list(touched_ids),
        per_source={"google": {"errors": []}, "meta": {"errors": ["boom"]}},
        settings=settings or _settings(),
        max_list=max_list,
    )


def test_table_order_is_load_bearing():
    names = [p.name for p in POST_PASSES]
    # fingerprint before embeddings/disclosed_comp (they gate on it); lineage
    # after embeddings and before demand_metrics; twins after lineage; clusters
    # and similarity after embeddings+twins (they read whole-corpus vectors);
    # prices last (external fetch, no downstream pass depends on it); tuning
    # after it because it reads only `per_source` — nothing downstream consumes
    # its bounds until the NEXT run reads them back before collection.
    #
    # description_backfill is FIRST and extends `touched_ids`: every text-reading
    # pass below it (fingerprint, skills, embeddings, disclosed_comp) must see a
    # row it just filled, or that description sits unindexed and unenriched until
    # the row happens to be touched again.
    assert names == [
        "description_backfill",
        # domains_backfill anywhere before demand rollups is fine (pure CPU
        # over stored fields, nothing downstream reads it yet); it sits right
        # after description_backfill so the axis debt drains earliest.
        "domains_backfill",
        # roles_backfill: the same pure derivation for family and track.
        "roles_backfill",
        # levels_backfill: and for the level, after roles because it reads the
        # stored family.
        "levels_backfill",
        # places_backfill: and for location groups and cities.
        "places_backfill",
        # inventory_promotion after all three, so inventory rows are filed as
        # `jobs` rows are before promotion reads them, and before
        # search_vectors, so every derivation below covers what it admits.
        "inventory_promotion",
        # inventory_retention anywhere is correct (it deletes only inventory
        # rows no scan read for days, which promotion never admits); it sits by
        # promotion so the inventory's two passes read together.
        "inventory_retention",
        "search_vectors",
        "content_fingerprint",
        "skills_requirements",
        "embeddings",
        "disclosed_comp",
        # pay_periods after disclosed_comp: a band that pass just wrote is on
        # the current rule already, so it is never a candidate.
        "pay_periods",
        # reference before comp_metrics: today's pay statistics must read the
        # re-estimated values.
        "reference",
        # posting_pages after disclosed_comp: its queue is "the text stated no
        # pay", which only disclosed_comp has decided.
        "posting_pages",
        # relevance_review after domains_backfill (so "unclassified" is real
        # debt, not not-yet-derived) and after embeddings/disclosed_comp only
        # by convention — it reads no other pass's output and writes only its
        # own advisory table.
        "relevance_review",
        # profile_inference after relevance_review: both are advisory readers
        # of user signals + stored rows; it writes only profile_suggestions.
        "profile_inference",
        # place_sets right before lineage: the detector's same-set gate reads
        # this run's sets, and a set withdraws the queue's proposals between
        # its members. After places_backfill, whose cities it
        # compares.
        "place_sets",
        "lineage",
        "twins",
        "clusters",
        "similarity",
        "demand_metrics",
        "skill_demand",
        "comp_metrics",
        "disclosure_metrics",
        "prices",
        "tuning",
    ]


def test_capped_scan_excludes_lineage_twins_and_tuning():
    # clusters/similarity read the whole open corpus, so they are correct on a
    # capped run and must NOT be excluded — only closure-coupled passes are.
    #
    # `tuning` joins them for a different reason: a `--max-list` scan
    # stopped where the operator said, so its page counts measure the cap and
    # not the board. Learning from one would ratchet every bound down toward the
    # cap, and the next full run would truncate against bounds a capped run set.
    #
    # `inventory_retention` for a third: an operator's capped smoke,
    # often from a worktree against the shared database, never deletes.
    #
    # `posting_pages` for a fourth: it spends one request per owed
    # posting, and a capped smoke is a check of collection, not a reader of forms.
    full_scrape_only = {p.name for p in POST_PASSES if not p.capped_ok}
    assert full_scrape_only == {
        "lineage", "twins", "tuning", "inventory_retention", "posting_pages"
    }


def test_discovery_runs_only_incremental_touched_job_passes():
    discovery = {p.name for p in POST_PASSES if p.discovery_ok}
    assert discovery == {
        # A probe is what creates the description debt, so it must also be able
        # to drain it.
        "description_backfill",
        # Pure derivation over stored fields; a probe's new rows deserve
        # domains the same as a scrape's.
        "domains_backfill",
        "roles_backfill",
        "levels_backfill",
        "places_backfill",
        # A probe's run holds the lock too, so it admits what a save left
        # pending.
        "inventory_promotion",
        "search_vectors",
        "content_fingerprint",
        "skills_requirements",
        "embeddings",
        "disclosed_comp",
        # A probe's run holds the lock and may follow a reference switch: the
        # stored estimates move with it.
        "reference",
        # Standing-debt drain like the backfills: a discovery probe's new rows
        # are exactly the unclassified volume the advisory exists to review.
        "relevance_review",
        # Reads only persisted user signals; suggestion freshness should not
        # wait for the next full scrape.
        "profile_inference",
    }


def test_settings_gates():
    s = _settings()
    by_name = {p.name: p for p in POST_PASSES}
    # disclosed_comp is on by default, off only when explicitly disabled.
    assert by_name["disclosed_comp"].enabled(s) is True
    assert by_name["disclosed_comp"].enabled(_settings(intelligence_extract_in_pipeline=False)) is False
    # prices is always enabled: its key may live in Settings, which no Settings
    # object can see, so the pass itself skips without one.
    assert by_name["prices"].enabled(s) is True
    assert by_name["lineage"].enabled(_settings(lineage_enabled=False)) is False
    assert by_name["twins"].enabled(_settings(twin_enabled=False)) is False
    # Everything else runs unconditionally.
    for name in ("search_vectors", "content_fingerprint", "skills_requirements",
                 "embeddings", "clusters", "similarity", "demand_metrics",
                 "skill_demand", "comp_metrics", "disclosure_metrics"):
        assert by_name[name].enabled(s) is True


def test_the_prices_pass_keeps_its_own_schedule_and_no_pipeline_run_includes_it():
    """A saved key waited for a scan to end; prices are the supervisor's job now."""
    by_name = {p.name: p for p in POST_PASSES}
    assert by_name["prices"].scheduled is True
    assert [p.name for p in POST_PASSES if p.scheduled] == ["prices"]


def test_a_pipeline_run_skips_the_scheduled_pass(monkeypatch):
    import tracker.workflows.post_passes as pp

    ran: list[str] = []

    async def refresh(session, settings):
        ran.append("prices")
        return {}

    async def nothing(*_a, **_k):
        return None

    monkeypatch.setattr(pp, "run_refresh", refresh)
    monkeypatch.setattr(pp, "_record_derivation", nothing)
    monkeypatch.setattr(
        pp, "POST_PASSES", tuple(p for p in POST_PASSES if p.name == "prices")
    )
    ctx = _ctx()
    asyncio.run(pp.run_post_passes(ctx))
    assert ran == []


def test_the_scheduled_runner_runs_the_pass_and_records_it(monkeypatch):
    import tracker.workflows.post_passes as pp

    recorded: list[tuple[str, bool, dict]] = []

    async def refresh(session, settings):
        return {"priced": 2, "next_at": "2026-10-20T06:00:00+00:00"}

    async def record(session, name, *, ok, detail):
        recorded.append((name, ok, detail))

    monkeypatch.setattr(pp, "run_refresh", refresh)
    monkeypatch.setattr(pp, "_record_derivation", record)
    ctx = _ctx()
    detail = asyncio.run(pp.run_scheduled_pass("prices", ctx.session, ctx.settings))
    assert detail["priced"] == 2
    assert recorded == [("prices", True, detail)]

    async def busy(session, settings):
        return {"skipped": "busy"}

    monkeypatch.setattr(pp, "run_refresh", busy)
    asyncio.run(pp.run_scheduled_pass("prices", ctx.session, ctx.settings))
    assert len(recorded) == 1, "a run that found the lock held writes no row"


def test_fatal_flags_match_pre_table_behavior():
    fatal = {p.name for p in POST_PASSES if p.fatal}
    assert fatal == {
        "search_vectors",
        "content_fingerprint",
        "embeddings",
        "demand_metrics",
        "skill_demand",
        "comp_metrics",
        # Same class as its rollup siblings: a silently-missing daily slice is a
        # permanent hole in a longitudinal series, so the run fails loudly.
        "disclosure_metrics",
    }


def test_clean_companies_excludes_errored_sources():
    assert _ctx().clean_companies == {"google"}


def _mute_derivation(monkeypatch):
    """No-op the per-pass state recorder so commit/rollback assertions below
    measure only the pass loop's own boundaries, not derivation bookkeeping
    (which has its own tests). run_post_passes looks it up as a module global."""
    async def _noop(session, name, *, ok, detail):
        return None

    monkeypatch.setattr("tracker.workflows.post_passes._record_derivation", _noop)


@pytest.mark.asyncio
async def test_loop_skips_capped_and_disabled_and_survives_nonfatal_failure(monkeypatch):
    _mute_derivation(monkeypatch)
    ran: list[str] = []

    def make(name, **kw):
        async def _run(ctx):
            ran.append(name)
            if name == "flaky":
                raise RuntimeError("transient")
        return PostPass(name, _run, **kw)

    table = (
        make("always"),
        make("flaky"),  # non-fatal: logged, loop continues
        make("capped_only_full", capped_ok=False),
        make("disabled", enabled=lambda s: False),
        make("last"),
    )
    monkeypatch.setattr("tracker.workflows.post_passes.POST_PASSES", table)

    session = FakeSession()
    await run_post_passes(_ctx(max_list=150, session=session))
    assert ran == ["always", "flaky", "last"]
    # The failed pass is rolled back; the successful ones are each committed.
    assert session.rollbacks == 1
    assert session.commits == 2  # "always" and "last"


@pytest.mark.asyncio
async def test_loop_skips_global_passes_during_discovery(monkeypatch):
    _mute_derivation(monkeypatch)
    ran: list[str] = []

    def make(name, *, discovery_ok=False):
        async def _run(ctx):
            ran.append(name)

        return PostPass(name, _run, discovery_ok=discovery_ok)

    monkeypatch.setattr(
        "tracker.workflows.post_passes.POST_PASSES",
        (make("incremental", discovery_ok=True), make("global")),
    )
    ctx = _ctx(max_list=150)
    ctx.scan_mode = ScanMode.DISCOVERY
    await run_post_passes(ctx)
    assert ran == ["incremental"]


@pytest.mark.asyncio
async def test_nonfatal_failure_does_not_poison_a_later_fatal_pass(monkeypatch):
    """The exact crash: a non-fatal pass that fails its flush must not leave the
    shared session pending-rollback for the next (fatal) pass.

    Fail-first: without the rollback in the loop, the fatal "embeddings" pass
    flushes a poisoned session and raises _PoisonError out of run_post_passes.
    """
    ran: list[str] = []

    def touch(name, **kw):
        async def _run(ctx):
            ran.append(name)
            await ctx.session.flush()
        return PostPass(name, _run, **kw)

    def truncate(name):
        async def _run(ctx):
            ran.append(name)
            await ctx.session.fail_flush()  # overflow → poison → raise
        return PostPass(name, _run)  # non-fatal

    table = (
        touch("search_vectors", fatal=True),
        touch("content_fingerprint", fatal=True),
        truncate("skills_requirements"),  # non-fatal, poisons the session
        touch("embeddings", fatal=True),  # must run on a clean session
    )
    monkeypatch.setattr("tracker.workflows.post_passes.POST_PASSES", table)

    session = FakeSession()
    await run_post_passes(_ctx(session=session))  # must not raise

    assert ran == ["search_vectors", "content_fingerprint", "skills_requirements", "embeddings"]
    assert session.rollbacks == 1  # recovered exactly once, after the failure
    assert session.poisoned is False


@pytest.mark.asyncio
async def test_each_pass_is_committed_so_earlier_work_survives(monkeypatch):
    """Every pass gets a committed boundary, so a later failure can never
    discard an earlier pass's work (fatal passes here do not self-commit)."""
    def touch(name, **kw):
        async def _run(ctx):
            await ctx.session.flush()
        return PostPass(name, _run, **kw)

    _mute_derivation(monkeypatch)
    table = (touch("a", fatal=True), touch("b"), touch("c", fatal=True))
    monkeypatch.setattr("tracker.workflows.post_passes.POST_PASSES", table)

    session = FakeSession()
    await run_post_passes(_ctx(session=session))
    assert session.commits == 3  # one per pass, not a single trailing commit
    assert session.rollbacks == 0


@pytest.mark.asyncio
async def test_loop_propagates_fatal_failure(monkeypatch):
    async def _boom(ctx):
        raise RuntimeError("fatal pass broke")

    async def _never(ctx):
        raise AssertionError("must not run after a fatal failure")

    table = (PostPass("boom", _boom, fatal=True), PostPass("after", _never))
    monkeypatch.setattr("tracker.workflows.post_passes.POST_PASSES", table)

    _mute_derivation(monkeypatch)
    with pytest.raises(RuntimeError, match="fatal pass broke"):
        await run_post_passes(_ctx())


@pytest.mark.asyncio
async def test_fatal_failure_records_derivation_error_before_propagating(monkeypatch):
    """A fatal pass failure aborts the run, but its derivation row must flip to
    error first — otherwise `last_status` keeps reporting the previous run's
    "ok" for as long as the pass keeps failing, hiding exactly the kind of
    silent rot the freshness row exists to surface."""
    recorded: list[tuple[str, bool]] = []

    async def _capture(session, name, *, ok, detail):
        recorded.append((name, ok))

    monkeypatch.setattr("tracker.workflows.post_passes._record_derivation", _capture)

    async def _boom(ctx):
        raise RuntimeError("fatal pass broke")

    table = (PostPass("boom", _boom, fatal=True),)
    monkeypatch.setattr("tracker.workflows.post_passes.POST_PASSES", table)

    session = FakeSession()
    with pytest.raises(RuntimeError, match="fatal pass broke"):
        await run_post_passes(_ctx(session=session))
    assert recorded == [("boom", False)]
    assert session.rollbacks == 1  # session cleaned before the recorder runs


@pytest.mark.asyncio
async def test_loop_records_derivation_state_only_for_passes_that_ran(monkeypatch):
    """Every executed pass upserts its freshness row (ok/error); a pass
    skipped for being capped-excluded or disabled records nothing, so a capped
    run can't refresh an 'ok' it never earned. This is what makes a
    registered-but-never-run pass visible as stale instead of silently empty."""
    recorded: list[tuple[str, bool]] = []

    async def _capture(session, name, *, ok, detail):
        recorded.append((name, ok))

    monkeypatch.setattr("tracker.workflows.post_passes._record_derivation", _capture)

    def make(name, **kw):
        async def _run(ctx):
            if name == "boom":
                raise RuntimeError("transient")
        return PostPass(name, _run, **kw)

    table = (
        make("ok_pass"),
        make("boom"),  # non-fatal failure → recorded ok=False
        make("capped_only", capped_ok=False),  # skipped on capped run
        make("disabled", enabled=lambda s: False),  # skipped
        make("ok_last"),
    )
    monkeypatch.setattr("tracker.workflows.post_passes.POST_PASSES", table)

    await run_post_passes(_ctx(max_list=150, session=FakeSession()))
    assert recorded == [("ok_pass", True), ("boom", False), ("ok_last", True)]


@pytest.mark.asyncio
async def test_record_derivation_is_best_effort(monkeypatch):
    """A failure to write the state row must never break the run — the pass
    result is already committed before this call."""
    class _ExecFails(FakeSession):
        async def execute(self, *_a, **_k):
            raise RuntimeError("state table gone")

    session = _ExecFails()
    # Must not raise, and must clean up after itself.
    await _record_derivation(session, "clusters", ok=True, detail={})
    assert session.rollbacks == 1
    assert session.commits == 0


def _capture_details(monkeypatch) -> list[dict]:
    recorded: list[dict] = []

    async def _capture(session, name, *, ok, detail):
        recorded.append(detail)

    monkeypatch.setattr("tracker.workflows.post_passes._record_derivation", _capture)
    return recorded


@pytest.mark.asyncio
async def test_a_skipped_pass_records_what_kind_of_failure_it_was(monkeypatch, caplog):
    """`str(KeyError("title"))` is `'title'`: the derivation row would name a
    key without saying one was missing. The stored detail leads with the
    exception's type, and the warning carries the traceback, since nothing
    else keeps it once the run moves on."""
    recorded = _capture_details(monkeypatch)

    async def _missing_key(ctx):
        raise KeyError("title")

    monkeypatch.setattr(
        "tracker.workflows.post_passes.POST_PASSES", (PostPass("flaky", _missing_key),)
    )
    with caplog.at_level(logging.WARNING, logger="tracker.workflows.post_passes"):
        await run_post_passes(_ctx(session=FakeSession()))

    (detail,) = recorded
    assert detail["error"].startswith("KeyError:") and "title" in detail["error"]
    (warning,) = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert warning.exc_info is not None and warning.exc_info[0] is KeyError


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["fatal", "scheduled"])
async def test_a_failure_that_stops_its_caller_records_its_type_even_without_a_message(
    monkeypatch, kind
):
    """A timeout carries no message, so its plain string is empty and the row
    would say the pass failed and nothing else."""
    recorded = _capture_details(monkeypatch)

    async def _silent(ctx):
        raise TimeoutError()

    monkeypatch.setattr(
        "tracker.workflows.post_passes.POST_PASSES",
        (PostPass("silent", _silent, fatal=kind == "fatal", scheduled=kind == "scheduled"),),
    )
    with pytest.raises(TimeoutError):
        if kind == "fatal":
            await run_post_passes(_ctx())
        else:
            await run_scheduled_pass("silent", FakeSession(), _settings())

    (detail,) = recorded
    assert detail["error"].startswith("TimeoutError")


@pytest.mark.asyncio
async def test_demand_slices_result_is_captured(monkeypatch):
    async def fake_demand(session, **_kwargs):
        return 7

    monkeypatch.setattr("tracker.workflows.post_passes.compute_demand_metrics", fake_demand)
    ctx = _ctx()
    by_name = {p.name: p for p in POST_PASSES}
    await by_name["demand_metrics"].run(ctx)
    assert ctx.results["demand_slices"] == 7


# --------------------------------------------------------------------------- #
# The post-pass phase never runs behind an `if not timed_out:` gate in
# `run_pipeline`. Such a gate throws away the demand rollup — and every other
# pass — for every healthy source whenever one source runs long, which is the
# coupling bulkheading exists to remove.
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_post_passes_run_over_the_healthy_sources_when_one_timed_out(monkeypatch):
    """A timed-out neighbour must not cancel the rollup for everyone else.

    Scoping is per-pass and already correct: lineage/twins see only
    `clean_companies`, while the demand rollup is global and must still run.
    """
    async def fake_demand(session, **_kwargs):
        return 12

    monkeypatch.setattr("tracker.workflows.post_passes.compute_demand_metrics", fake_demand)

    scoped: list[set[str]] = []

    async def _scoped_pass(ctx):
        scoped.append(ctx.clean_companies)

    table = (
        PostPass("lineage", _scoped_pass, capped_ok=False),
        PostPass("demand_metrics", _pass_demand_metrics, fatal=True),
    )
    monkeypatch.setattr("tracker.workflows.post_passes.POST_PASSES", table)

    ctx = PostPassContext(
        session=FakeSession(),
        touched_ids=[1, 2],
        per_source={
            "google": {"errors": []},
            "apple": {"errors": []},
            "meta": {"errors": ["TimeoutError: collection timed out"]},
        },
        settings=_settings(),
        max_list=None,
    )
    await run_post_passes(ctx)

    assert ctx.results["demand_slices"] == 12  # the rollup was NOT discarded
    assert scoped == [{"google", "apple"}]  # and it excluded only the bad source


@pytest.mark.asyncio
async def test_reclassify_domains_repairs_stale_rows_and_moves_them_on_the_radar(db_session):
    """A lexicon change must reach rows the scraper will not rewrite, and the
    radar must follow.

    `stale_logistics` is stored as unclassified (so fail-open keeps it on the
    radar), the current lexicon reads
    its hyphenated team slug as logistics, and the user tracks only AI — so it
    must LEAVE the radar. Without the `in_scope` recompute it stays.
    """
    from sqlalchemy import select

    from tracker.db.models import Job
    from tracker.settings_store import (
        set_enabled_bands,
        set_enabled_domains,
        set_enabled_locations,
        set_enabled_roles,
        set_enabled_tracks,
    )
    from tracker.workflows.post_passes import reclassify_domains

    t0 = datetime(2026, 9, 1, tzinfo=UTC)

    def job(key, title, *, team=None, domains=(), in_scope=True):
        return Job(
            company="amazon", req_id=key, dedupe_key=f"amazon:{key}", title=title,
            url=f"https://example.test/{key}", team=team, department=None,
            locations=["London, UK"], location_groups=["uk"],
            domains=None if domains is None else list(domains),
            workplace_type="onsite", level_band="staff", level_confidence="confirmed",
            family="software_engineering", track="technical", comp_currency="USD",
            status="open", in_scope=in_scope, first_seen=t0, last_seen=t0,
            description_sections=[],
        )

    db_session.add_all([
        job("stale_logistics", "Staff Software Engineer", team="team-last-mile"),
        job("stale_ai", "Staff Software Engineer, Alexa AI"),
        job("never_classified", "Staff Software Engineer", domains=None),
        job("current", "Staff Machine Learning Engineer", domains=["ai_ml"]),
    ])
    await set_enabled_roles(db_session, ["software_engineering"])
    await set_enabled_bands(db_session, ["staff"])
    await set_enabled_tracks(db_session, ["technical"])
    await set_enabled_locations(db_session, ["uk"])
    await set_enabled_domains(db_session, ["ai_ml"])
    await db_session.commit()

    result = await reclassify_domains(db_session)
    await db_session.commit()

    rows = {
        r.req_id: (r.domains, r.in_scope)
        for r in (await db_session.execute(select(Job.req_id, Job.domains, Job.in_scope))).all()
    }
    assert rows == {
        "stale_logistics": (["logistics_fulfillment"], False),  # off the radar now
        "stale_ai": (["ai_ml"], True),
        "never_classified": ([], True),  # honestly unknown still shows
        "current": (["ai_ml"], True),
    }
    assert result == {"reclassified": 3, "in_scope_changed": 1}

    # Caught up: a second run is a scan that writes nothing.
    assert await reclassify_domains(db_session) == {"reclassified": 0, "in_scope_changed": 0}


@pytest.mark.asyncio
async def test_reclassify_roles_moves_ic_managers_off_leadership_and_the_radar(db_session):
    """A classifier change must reach stored rows, and the radar must follow.
    The user tracks leadership only: the Customer Success Manager
    stored as management must LEAVE the radar, the people manager must stay,
    and a second run writes nothing."""
    from sqlalchemy import select

    from tracker.db.models import Job
    from tracker.settings_store import (
        set_enabled_bands,
        set_enabled_domains,
        set_enabled_locations,
        set_enabled_roles,
        set_enabled_tracks,
    )
    from tracker.workflows.post_passes import reclassify_roles

    t0 = datetime(2026, 9, 1, tzinfo=UTC)

    def job(key, title):
        return Job(
            company="amazon", req_id=key, dedupe_key=f"amazon:{key}", title=title,
            url=f"https://example.test/{key}", team=None, department=None,
            locations=["London, UK"], location_groups=["uk"], domains=[],
            workplace_type="onsite", level_band="staff", level_confidence="confirmed",
            family="customer_success", track="management", comp_currency="USD",
            status="open", in_scope=True, first_seen=t0, last_seen=t0,
            description_sections=[],
        )

    db_session.add_all([
        job("ic", "Senior Customer Success Manager"),
        job("lead", "Senior Manager, Customer Success"),
    ])
    await set_enabled_roles(db_session, ["customer_success"])
    await set_enabled_bands(db_session, ["staff"])
    await set_enabled_tracks(db_session, ["management"])
    await set_enabled_locations(db_session, ["uk"])
    await set_enabled_domains(db_session, [])
    await db_session.commit()

    result = await reclassify_roles(db_session)
    await db_session.commit()

    rows = {
        r.req_id: (r.family, r.track, r.in_scope)
        for r in (await db_session.execute(select(Job.req_id, Job.family, Job.track, Job.in_scope))).all()
    }
    assert rows == {
        "ic": ("customer_success", "business_customer", False),
        "lead": ("customer_success", "management", True),
    }
    assert result == {"reclassified": 1, "in_scope_changed": 1}
    assert await reclassify_roles(db_session) == {"reclassified": 0, "in_scope_changed": 0}


@pytest.mark.asyncio
async def test_the_description_backfill_paces_its_requests_per_host(db_session, monkeypatch):
    """A drain of one company's blank rows goes out at the host's pace.

    Each posting builds its own adapter. With no shared pool each adapter would
    get a private pacer whose first wait is immediate, sending the drain's
    requests back to back to a host the collection has just finished pacing.
    """
    import time

    from tracker.config import get_settings
    from tracker.connectors.listing.base import BaseAdapter
    from tracker.db.models import Job
    from tracker.workflows import post_passes
    from tracker.workflows.post_passes import backfill_missing_descriptions

    delay = 0.25
    monkeypatch.setattr(get_settings(), "scraper_min_delay_seconds", delay)
    sent: list[float] = []

    class Board(BaseAdapter):
        name = "eightfold"

        async def fetch(self):  # pragma: no cover - the drain only hydrates
            yield None

        async def hydrate(self, raw):
            await self._limiter.wait()
            sent.append(time.monotonic())
            raw.description_html = "<p>Lead the platform team.</p>"

    monkeypatch.setattr(post_passes, "build_adapter", lambda company, _adapter, token=None, **kw: Board(company, token, **kw))

    async def targets(_session):
        return {"acme": {"adapter": "eightfold", "board_token": "acme"}}

    monkeypatch.setattr(post_passes, "get_active_targets", targets)
    t0 = datetime(2026, 9, 1, tzinfo=UTC)
    db_session.add_all([
        Job(
            company="acme", req_id=f"r{i}", dedupe_key=f"acme:r{i}", title="Staff Software Engineer",
            url=f"https://example.test/r{i}", locations=["London, UK"], location_groups=["uk"],
            workplace_type="onsite", level_band="staff", level_confidence="confirmed",
            family="software_engineering", track="technical", comp_currency="USD",
            status="open", in_scope=True, first_seen=t0, last_seen=t0, description_sections=[],
        )
        for i in range(3)
    ])
    await db_session.commit()

    filled = await backfill_missing_descriptions(db_session, limit=10)

    assert len(filled) == 3 and len(sent) == 3
    gaps = [later - earlier for earlier, later in zip(sent, sent[1:], strict=False)]
    assert all(gap >= delay * 0.9 for gap in gaps), gaps


def _blank(company: str, req_id: str, first_seen: datetime):
    from tracker.db.models import Job

    return Job(
        company=company, req_id=req_id, dedupe_key=f"{company}:{req_id}",
        title="Staff Product Manager", url=f"https://careers.example.test/{company}/{req_id}",
        locations=["London, UK"], location_groups=["uk"], workplace_type="onsite",
        level_band="staff", level_confidence="confirmed", family="product_management",
        track="technical", comp_currency="USD", status="open", in_scope=True,
        first_seen=first_seen, last_seen=first_seen, description_sections=[],
    )


@pytest.fixture
def backfill_board(monkeypatch):
    """Every adapter the drain builds, as the companies it asked and the
    consent each was handed; each answers with text."""
    from tracker.connectors.listing.base import BaseAdapter
    from tracker.workflows import post_passes

    asked: list[tuple[str, str | None]] = []

    class Board(BaseAdapter):
        name = "eightfold"

        async def fetch(self):  # pragma: no cover - the drain only hydrates
            yield None

        async def hydrate(self, raw):
            asked.append((self.company, self.collection_consent))
            raw.description_html = "<p>Lead the platform team.</p>"

    monkeypatch.setattr(
        post_passes, "build_adapter", lambda company, _adapter, token=None, **kw: Board(company, token, **kw)
    )
    return asked


@pytest.mark.asyncio
async def test_the_description_backfill_holds_no_transaction_across_a_request(db_session, monkeypatch):
    """Each posting is a paced request. A transaction left open across them
    holds one snapshot for the whole drain, so every request goes out with
    none open, and each fill commits on its own. A row another writer gave
    text while its request was out keeps that text and is not counted.
    Fail-first: the drain fetched inside the transaction that read its queue."""
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from tracker.connectors.listing.base import BaseAdapter
    from tracker.db.models import Job, TrackedCompany
    from tracker.workflows import post_passes
    from tracker.workflows.post_passes import backfill_missing_descriptions

    open_at_request: list[bool] = []
    other = async_sessionmaker(db_session.bind, expire_on_commit=False, class_=AsyncSession)

    class Board(BaseAdapter):
        name = "eightfold"

        async def fetch(self):  # pragma: no cover - the drain only hydrates
            yield None

        async def hydrate(self, raw):
            open_at_request.append(db_session.in_transaction())
            if raw.req_id == "raced":
                async with other() as writer:
                    row = await writer.scalar(select(Job).where(Job.req_id == "raced"))
                    row.description_text = "Filled by the scan."
                    await writer.commit()
            raw.description_html = "<p>Lead the platform team.</p>"

    monkeypatch.setattr(
        post_passes, "build_adapter", lambda company, _adapter, token=None, **kw: Board(company, token, **kw)
    )
    db_session.add(TrackedCompany(slug="efco", display="Efco", adapter="eightfold", board_token="efco",
                                  status="active", enabled=True))
    t0 = datetime(2026, 9, 1, tzinfo=UTC)
    db_session.add_all([_blank("efco", "raced", t0), _blank("efco", "quiet", t0.replace(day=2))])
    await db_session.commit()

    filled = await backfill_missing_descriptions(db_session, limit=25)

    assert open_at_request == [False, False]
    assert not db_session.in_transaction(), "each fill commits; nothing is left for the caller"
    texts = dict((await db_session.execute(select(Job.req_id, Job.description_text))).all())
    assert texts["raced"] == "Filled by the scan."
    assert texts["quiet"].endswith("Lead the platform team.")
    assert [j.req_id for j in [await db_session.get(Job, i) for i in filled]] == ["quiet"]


@pytest.mark.asyncio
async def test_the_description_backfill_counts_only_rows_it_can_fill(db_session, backfill_board):
    """Blank rows the drain cannot fill must not hold its slots. Workday's
    `hydrate` needs the listing's payload, which a stored posting does not
    carry, so oldest-first Workday blanks would take every slot each run and
    the blanks behind them (SuccessFactors, KPMG) would never be reached.
    Unfollowed and inline companies are blanks the drain cannot ask either."""
    from tracker.db.models import TrackedCompany
    from tracker.workflows.post_passes import backfill_missing_descriptions

    def company(slug: str, adapter: str, **over) -> TrackedCompany:
        return TrackedCompany(**{
            "slug": slug, "display": slug.title(), "adapter": adapter, "board_token": slug,
            "status": "active", "enabled": True, **over,
        })

    old = datetime(2026, 7, 23, tzinfo=UTC)
    db_session.add_all([
        company("wdco", "workday", board_token="wdco.wd1.myworkdayjobs.com|External"),
        company("efco", "eightfold"),
        company("gone", "eightfold", enabled=False),  # the user does not follow it
        company("ghco", "greenhouse"),  # text arrives inline: nothing to fetch
    ])
    db_session.add_all([_blank("wdco", f"wd{i}", old.replace(hour=i % 24, minute=i)) for i in range(30)])
    db_session.add_all([
        _blank("gone", "g1", old.replace(day=1)),
        _blank("ghco", "h1", old.replace(day=2)),
        _blank("efco", "e1", datetime(2026, 9, 28, tzinfo=UTC)),
    ])
    await db_session.commit()

    filled = await backfill_missing_descriptions(db_session, limit=25)

    assert backfill_board == [("efco", None)]
    assert len(filled) == 1


@pytest.mark.asyncio
async def test_a_board_row_whose_level_is_not_stated_is_read_first(db_session, backfill_board):
    """Its text is what can name its level, so a row the
    person sees unplaced goes ahead of older debt. Not ahead of nothing: an
    unplaced row off the Board waits its turn, oldest first."""
    from tracker.db.models import TrackedCompany
    from tracker.workflows.post_passes import backfill_missing_descriptions

    db_session.add(TrackedCompany(slug="efco", display="Efco", adapter="eightfold", board_token="efco",
                                  status="active", enabled=True))
    old = datetime(2026, 7, 23, tzinfo=UTC)
    oldest = _blank("efco", "stated", old)  # level stated: ordinary debt
    off_board = _blank("efco", "off", old.replace(day=24))
    off_board.level_basis, off_board.in_scope = "none", False
    unplaced = _blank("efco", "unplaced", datetime(2026, 9, 28, tzinfo=UTC))
    unplaced.level_basis = "none"
    db_session.add_all([oldest, off_board, unplaced])
    await db_session.commit()

    first = await backfill_missing_descriptions(db_session, limit=1)
    second = await backfill_missing_descriptions(db_session, limit=1)

    assert first == [unplaced.id]
    assert second == [oldest.id]


@pytest.mark.asyncio
async def test_the_description_backfill_asks_a_walled_company_only_with_consent(db_session, backfill_board):
    """Google is walled by robots. A followed Google company is
    asked only with the user's consent, and the adapter is handed that
    consent: it re-checks the policy on entry and refused every such row."""
    from tracker.db.models import TrackedCompany
    from tracker.source_review import SOURCE_REVIEWS
    from tracker.workflows.post_passes import backfill_missing_descriptions

    consent = SOURCE_REVIEWS["google"].wall_fingerprint
    db_session.add_all([
        TrackedCompany(slug="walled", display="Walled", adapter="google", status="active", enabled=True),
        TrackedCompany(
            slug="consented", display="Consented", adapter="google", status="active", enabled=True,
            consent_fingerprint=consent,
        ),
    ])
    t0 = datetime(2026, 9, 1, tzinfo=UTC)
    db_session.add_all([_blank("walled", "w1", t0), _blank("consented", "c1", t0.replace(day=2))])
    await db_session.commit()

    await backfill_missing_descriptions(db_session, limit=25)

    assert backfill_board == [("consented", consent)]


@pytest.mark.asyncio
async def test_the_description_backfill_reads_a_posting_through_the_real_adapter(db_session, monkeypatch):
    """A posting rebuilt from storage must not take `RawJob`'s default
    `description_complete=True`: SuccessFactors' and Avature's `hydrate`
    return at once for a posting whose text is complete, so its blank would be
    selected every run and never filled. The row has no text, so the rebuilt
    posting says so."""
    from pathlib import Path

    import httpx

    from tracker.config import get_settings
    from tracker.db.models import Job, TrackedCompany
    from tracker.workflows.post_passes import backfill_missing_descriptions

    detail = (Path(__file__).parent / "fixtures/listings/successfactors/detail_1431618233.html").read_text()
    asked: list[str] = []

    def handle(request: httpx.Request) -> httpx.Response:
        asked.append(request.url.path)
        return httpx.Response(200, text=detail)

    monkeypatch.setattr(
        "tracker.connectors.listing.base.make_tier_client",
        lambda *a, **k: httpx.AsyncClient(transport=httpx.MockTransport(handle)),
    )
    monkeypatch.setattr(get_settings(), "scraper_min_delay_seconds", 0)
    db_session.add(TrackedCompany(slug="ey", display="EY", adapter="successfactors",
                                  board_token="careers.ey.com|ey", status="active", enabled=True))
    row = _blank("ey", "1431618233", datetime(2026, 9, 28, tzinfo=UTC))
    row.url = "https://careers.ey.com/ey/job/Rochester-Manager-NY-14604/1431618233/"
    db_session.add(row)
    await db_session.commit()

    filled = await backfill_missing_descriptions(db_session, limit=25)

    assert asked == ["/ey/job/Rochester-Manager-NY-14604/1431618233/"]
    assert filled == [row.id]
    stored = await db_session.get(Job, row.id)
    assert stored.description_text and "EY" in stored.description_text


def test_the_only_user_directed_source_the_description_backfill_asks_waits_for_the_user():
    """The drain runs after every run, scheduled ones included, and a
    user-directed source is collected only when the user starts it.
    Workday reads its text from the posting, and the drain asks a company
    RoleBand does not scan automatically only in a run that scanned it
    (`scanned_automatically`). Enumerated: the day another user-directed source
    declares `text_from_posting`, this fails and asks for that decision; and
    the gate must refuse every one of them."""
    from tracker.connectors import ADAPTER_REGISTRY
    from tracker.source_policy import scanned_automatically
    from tracker.source_review import SOURCE_REVIEWS

    asked = [name for name, cls in ADAPTER_REGISTRY.items() if cls.text_from_posting]
    assert asked, "the control: some adapter reads text from the posting alone"
    directed = [name for name in asked if SOURCE_REVIEWS[name].user_directed]
    assert directed == ["workday"]
    assert not any(scanned_automatically(name, "acme", None) for name in directed)


@pytest.mark.asyncio
async def test_reclassify_places_repairs_stale_place_lists_and_moves_them_on_the_radar(db_session):
    """A location-taxonomy change must reach stored rows. The
    New York row was stored without its region, so a "North America" radar
    missed it; the London, Kentucky row was once read as the UK. Both are
    re-derived from the stored `locations`, the radar follows, and a second
    run writes nothing."""
    from sqlalchemy import select

    from tracker.db.models import Job
    from tracker.settings_store import (
        set_enabled_bands,
        set_enabled_domains,
        set_enabled_locations,
        set_enabled_roles,
        set_enabled_tracks,
    )
    from tracker.workflows.post_passes import reclassify_places

    t0 = datetime(2026, 9, 1, tzinfo=UTC)

    def job(key, places, groups, cities):
        return Job(
            company="amazon", req_id=key, dedupe_key=f"amazon:{key}", title="Staff Software Engineer",
            url=f"https://example.test/{key}", team=None, department=None,
            locations=places, location_groups=groups, location_cities=cities, domains=[],
            workplace_type="onsite", level_band="staff", level_confidence="confirmed",
            family="software_engineering", track="technical", comp_currency="USD",
            status="open", in_scope=False, first_seen=t0, last_seen=t0, description_sections=[],
        )

    db_session.add_all([
        job("nyc", ["New York, NY"], ["new_york", "united_states"], []),
        job("kentucky", ["London, Kentucky, USA"], ["uk", "europe"], []),
    ])
    await set_enabled_roles(db_session, ["software_engineering"])
    await set_enabled_bands(db_session, ["staff"])
    await set_enabled_tracks(db_session, ["technical"])
    await set_enabled_locations(db_session, ["north_america"])
    await set_enabled_domains(db_session, [])
    await db_session.commit()

    result = await reclassify_places(db_session)
    await db_session.commit()

    rows = {
        r.req_id: (set(r.location_groups), r.in_scope)
        for r in (await db_session.execute(select(Job.req_id, Job.location_groups, Job.in_scope))).all()
    }
    assert {"new_york", "united_states", "north_america"} <= rows["nyc"][0]
    assert rows["kentucky"][0] >= {"united_states", "north_america"}
    assert not rows["kentucky"][0] & {"uk", "europe"}
    assert rows["nyc"][1] is True and rows["kentucky"][1] is True
    assert result == {"reclassified": 2, "in_scope_changed": 2}
    assert await reclassify_places(db_session) == {"reclassified": 0, "in_scope_changed": 0}


@pytest.mark.asyncio
async def test_a_workday_blank_is_filled_only_by_a_run_that_scanned_its_company(db_session, monkeypatch, no_escape):
    """Workday's hydrate needs its listing payload, which it rebuilds from the
    posting url, so the drain can fill a blank description back. But Workday
    is scanned only when the user asks and this drain runs after every run: a
    scheduled run never reaches it, a run that scanned NVIDIA (a sync the user
    started) fills its blanks."""
    import httpx
    from sqlalchemy import select

    from tracker.connectors.listing import base
    from tracker.connectors.listing.base import RateLimiter
    from tracker.connectors.listing.workday import WorkdayAdapter
    from tracker.db.models import Job
    from tracker.workflows import post_passes
    from tracker.workflows.post_passes import backfill_missing_descriptions

    external = "/job/US-CA-Santa-Clara/Senior-Research-Manager--World-Model-Evaluation_JR2019461"
    requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request.url.path)
        return httpx.Response(200, json={"jobPostingInfo": {
            "jobDescription": "<p>Lead evaluation of world models.</p>", "startDate": "2026-08-17"}})

    def build(company, _adapter, token=None, **_kw):
        adapter = WorkdayAdapter(company, token)
        adapter._limiter = RateLimiter(0.0)
        return adapter

    # `async with adapter` builds its client from the policy's tier: the mock
    # goes in there, and `no_escape` refuses any request that would not.
    monkeypatch.setattr(base, "make_tier_client",
                        lambda *_a, **_kw: httpx.AsyncClient(transport=httpx.MockTransport(handler)))

    async def targets(_session):
        return {"nvidia": {"adapter": "workday", "board_token": None}}

    monkeypatch.setattr(post_passes, "build_adapter", build)
    monkeypatch.setattr(post_passes, "get_active_targets", targets)
    blank = _blank("nvidia", "JR2019461", datetime(2026, 7, 23, tzinfo=UTC))
    blank.url = "https://nvidia.wd5.myworkdayjobs.com/NVIDIAExternalCareerSite" + external
    db_session.add(blank)
    await db_session.commit()

    assert await backfill_missing_descriptions(db_session, limit=10) == []
    assert requests == [], "a scheduled run sends Workday nothing"

    filled = await backfill_missing_descriptions(db_session, limit=10, collected={"nvidia"})
    await db_session.commit()

    assert filled == [blank.id]
    assert requests == ["/wday/cxs/nvidia/NVIDIAExternalCareerSite" + external]
    text = await db_session.scalar(select(Job.description_text).where(Job.id == blank.id))
    assert "world models" in text


# --- the embed pass: off the loop, committed per chunk, bounded per run -----
#
# The pipeline's liveness heartbeat is a task on the same event loop the passes
# run on, and `reconcile_stale_runs` declares a run dead after
# `stale_run_heartbeat_seconds` of silence. Encoding a corpus takes far longer
# than that, so these hold the three properties that keep a run alive and make
# its work survive: the encode yields, each chunk is durable on its own, and the
# pass hands the rest of a backlog to the next run.


class _RecordingHeartbeat:
    """Stands in for `pipeline.session_scope` and counts the beats that land.

    The real ticker is driven, not a stub of it: what is under test is whether
    the event loop is free enough for that task to run at all.
    """

    def __init__(self):
        self.count = 0

    @asynccontextmanager
    async def scope(self):
        heart = self

        class _Session:
            async def execute(self, *_args, **_kwargs):
                heart.count += 1
                return SimpleNamespace(rowcount=1)

        yield _Session()


def _embeddable(n: int) -> list:
    from tracker.db.models import Job

    seen = datetime(2026, 10, 1, tzinfo=UTC)
    return [
        Job(
            company="acme", req_id=f"e{i}", dedupe_key=f"acme:e{i}", title=f"Staff Engineer {i}",
            url=f"https://careers.example.test/e{i}", level_band="staff", status="open",
            in_scope=True, first_seen=seen, last_seen=seen,
            description_text=f"Own the platform {i}.",
        )
        for i in range(n)
    ]


@pytest.fixture
def embedder(monkeypatch):
    """A fake encoder, and the chunk size cut down so a handful of rows is
    several chunks.

    `slow(seconds)` makes a chunk cost that much and, while it does, proves the
    event loop is still running: the encoder asks the loop to set a flag and
    waits for it. An encode on the loop cannot be answered by the loop, so that
    wait times out and the encoder fails where the blocking happens.
    """
    from tracker.config import get_settings
    from tracker.semantic import embed as embed_mod
    from tracker.semantic import provision
    from tracker.workflows import post_passes

    dim = get_settings().embedding_dim
    chunks: list[int] = []
    delay = 0.0
    loop: asyncio.AbstractEventLoop | None = None

    def encode(texts: list[str]) -> list[list[float]]:
        chunks.append(len(texts))
        if delay:
            answered = threading.Event()
            assert loop is not None
            loop.call_soon_threadsafe(answered.set)
            time.sleep(delay)  # blocking on purpose: a real encode is CPU-bound
            assert answered.wait(timeout=5.0), "the event loop was blocked by the encode"
        return [[0.1] * dim for _ in texts]

    monkeypatch.setattr(embed_mod, "embed_texts", encode)
    monkeypatch.setattr(provision, "resolve_tier", lambda: "fp32")
    monkeypatch.setattr(post_passes, "EMBED_COMMIT_BATCH", 2)

    def configure(seconds: float) -> None:
        nonlocal delay, loop
        delay = seconds
        loop = asyncio.get_running_loop()

    return SimpleNamespace(chunks=chunks, slow=configure)


async def _reconcile_nothing(monkeypatch):
    """The tier reconcile is a no-op here: it needs app_settings this schema
    has no rows for, and it is not what these tests are about."""
    from tracker.workflows import post_passes

    async def noop(_session):
        return "fp32"

    monkeypatch.setattr(post_passes, "reconcile_tier", noop)


@pytest.mark.asyncio
async def test_the_embed_pass_leaves_the_event_loop_free(db_session, monkeypatch, embedder):
    """Fail-first: with `embed_texts` awaited inline the ticker below never
    beats, which is exactly how a run goes silent and is reconciled away."""
    from sqlalchemy import func, select

    from tracker.db.models import Job
    from tracker.workflows import pipeline
    from tracker.workflows.post_passes import _pass_embeddings

    await _reconcile_nothing(monkeypatch)
    jobs = _embeddable(6)
    db_session.add_all(jobs)
    await db_session.commit()
    embedder.slow(0.1)  # three chunks of two, 0.3s of encoding in all

    beats = _RecordingHeartbeat()
    monkeypatch.setattr(pipeline, "session_scope", beats.scope)
    ticker = pipeline._heartbeat_task(run_id=1, interval_seconds=0.01)
    before = beats.count
    try:
        result = await _pass_embeddings(
            _ctx(
                session=db_session,
                touched_ids=[j.id for j in jobs],
                settings=_settings(embedding_budget_seconds=60.0),
            )
        )
    finally:
        ticker.cancel()

    assert result == {"embedded": 6, "deferred": 0}
    # The encoder's own gate already failed the run if the loop stalled; this
    # is the consequence that matters to the reconciler. A loop free for 0.3s
    # of encoding beats about thirty times at this interval, against the
    # handful an inline encode leaves at the pass's own await points.
    assert beats.count - before >= 10, "the heartbeat went quiet while the corpus was encoded"
    embedded = await db_session.scalar(
        select(func.count()).select_from(Job).where(Job.embedded_at.isnot(None))
    )
    assert embedded == 6


@pytest.mark.asyncio
async def test_a_chunk_that_committed_survives_the_chunk_that_failed(
    db_session, monkeypatch, embedder
):
    """A killed embedder keeps the chunks it finished. One transaction over the
    queue would hand back every vector it had written, which is what makes a
    backlog unable to drain across runs."""
    from sqlalchemy import func, select

    from tracker.db.models import Job
    from tracker.semantic import embed as embed_mod
    from tracker.workflows.post_passes import _pass_embeddings

    await _reconcile_nothing(monkeypatch)
    jobs = _embeddable(6)
    db_session.add_all(jobs)
    await db_session.commit()

    real = embed_mod.embed_texts

    def die_on_the_third(texts: list[str]) -> list[list[float]]:
        if len(embedder.chunks) >= 2:
            raise RuntimeError("encoder died")
        return real(texts)

    monkeypatch.setattr(embed_mod, "embed_texts", die_on_the_third)

    with pytest.raises(RuntimeError):
        await _pass_embeddings(
            _ctx(
                session=db_session,
                touched_ids=[j.id for j in jobs],
                settings=_settings(embedding_budget_seconds=60.0),
            )
        )
    await db_session.rollback()

    embedded = await db_session.scalar(
        select(func.count()).select_from(Job).where(Job.embedded_at.isnot(None))
    )
    assert embedded == 4, "the two chunks that committed before the failure are gone"


@pytest.mark.asyncio
async def test_the_budget_defers_the_rest_of_the_queue_to_the_next_run(
    db_session, monkeypatch, embedder
):
    """A run older than `stale_run_minutes` is reconciled to `error` however
    well it beats, so a backlog larger than one run's budget is handed on. The
    cut is by id, and a spent budget still embeds one chunk: a budget too small
    for any chunk must never stall the corpus."""
    from sqlalchemy import select

    from tracker.db.models import Job
    from tracker.workflows.post_passes import _pass_embeddings

    await _reconcile_nothing(monkeypatch)
    jobs = _embeddable(6)
    db_session.add_all(jobs)
    await db_session.commit()
    ids = sorted(j.id for j in jobs)
    ctx = _ctx(
        session=db_session, touched_ids=ids, settings=_settings(embedding_budget_seconds=0.0)
    )

    assert await _pass_embeddings(ctx) == {"embedded": 2, "deferred": 4}
    done = sorted(
        (await db_session.scalars(select(Job.id).where(Job.embedded_at.isnot(None)))).all()
    )
    assert done == ids[:2], "the budget cuts the queue in id order"

    assert await _pass_embeddings(ctx) == {"embedded": 2, "deferred": 2}
    assert embedder.chunks == [2, 2], "no row is encoded twice"
    done = sorted(
        (await db_session.scalars(select(Job.id).where(Job.embedded_at.isnot(None)))).all()
    )
    assert done == ids[:4]
