"""Settings > Plugins over HTTP, and the reference set on /api/status.

Contracts: approval is of the install AS SHOWN (a changed fingerprint is
refused); enabling selects the target at once and starts a re-estimate, with
readers switching when it applies the set; disable stops only a live runner; Refresh now
starts one detached run, never in a maintenance wake, never twice; Remove data
needs the typed id and a disabled plugin and keeps append-only history; the
route table does not change with what is installed. No test spawns: the
runtime's spawner and the machine reading are fakes.
"""

from __future__ import annotations

import os
import signal
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from tests.plugin_seed import cover
from tracker.config import get_settings
from tracker.db.models import (
    CompanyBenefit,
    CompanyCompLevel,
    CompanyProfile,
    ExternalCompObservation,
    Job,
    PluginInstall,
    PluginRun,
    TrackedCompany,
)
from tracker.platform.power import Power
from tracker.plugins import runtime
from tracker.plugins.reestimate import reestimate
from tracker.plugins.registry import COMPANY_BENEFITS, PAY_LEVELS, PAY_OBSERVATIONS
from tracker.taxonomy.comp_families import REFERENCE_FAMILY

pytestmark = [pytest.mark.asyncio, pytest.mark.usefixtures("no_escape")]

AT = datetime(2026, 10, 1, tzinfo=UTC)
MANIFEST = {
    "plugin": {"id": "tpl", "name": "Template plugin", "version": "0.1.0", "entry": "tpl.main:plugin",
               "repository": "https://github.com/example/tpl", "licence": "MIT", "attribution": "Example data"},
    "provides": [{"slot": PAY_LEVELS}, {"slot": COMPANY_BENEFITS}, {"slot": PAY_OBSERVATIONS}],
    "network": {"hosts": ["data.example.com"], "identity": "identified"},
    "jobs": [{"name": "refresh", "schedule": "weekly", "budget_seconds": 600, "needs": ["followed_companies"]},
             {"name": "import", "schedule": "manual", "budget_seconds": 60}],
}


def _plugins(monkeypatch, value: str | None) -> None:
    """Set `ROLEBAND_PLUGINS` (None: unset) and drop the cached settings."""
    if value is None:
        monkeypatch.delenv("ROLEBAND_PLUGINS", raising=False)
    else:
        monkeypatch.setenv("ROLEBAND_PLUGINS", value)
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def plugins_shown(monkeypatch):
    _plugins(monkeypatch, "true")
    yield
    get_settings.cache_clear()


@pytest.fixture
def spawned(monkeypatch):
    """Every run the routes ask the supervisor for, as the command it would
    start: the registry's, then the request's arguments. The request is still
    written."""
    from tracker.supervisor.registry import job as registry_job

    calls: list[list[str]] = []
    real_ring = runtime._ring

    async def ring(session, name, *, argument, requested_by, args):
        calls.append([*registry_job(name).command, *args.get("argv", [])])
        await real_ring(session, name, argument=argument, requested_by=requested_by, args=args)

    monkeypatch.setattr(runtime, "_ring", ring)
    return calls


@pytest.fixture
def awake(monkeypatch):
    from tracker.api.routers import plugins as router

    monkeypatch.setattr(router, "read_power", lambda: Power(dark_wake=False, on_battery=True))


async def _install(db, *, approved=False, enabled=False, fingerprint="fp-now") -> None:
    db.add(PluginInstall(
        plugin_id="tpl", name="Template plugin", version="0.1.0", source_dir="/x/src", manifest_sha="m",
        code_sha="c", manifest=MANIFEST, fingerprint=fingerprint,
        approved_fingerprint=fingerprint if approved else None, enabled=enabled,
    ))
    await db.commit()


async def _pay(db, *, clean: bool) -> None:
    db.add(CompanyProfile(slug="acme", display_name="Acme"))
    await db.flush()
    db.add_all([
        CompanyCompLevel(company_slug="acme", family=REFERENCE_FAMILY, level_label="L5", band="senior",
                         tc_median=300_000, base_amount=200_000, provider="manual",
                         fetched_at=AT),
        # As a plugin sends it: no band; read at senior from its words.
        CompanyCompLevel(company_slug="acme", family=REFERENCE_FAMILY, level_label="Senior Engineer", band=None,
                         tc_median=999_000, base_amount=600_000, provider="tpl", country="US", fetched_at=AT),
        CompanyBenefit(company_slug="acme", name="Free yacht", category="Perks", provider="tpl"),
        Job(company="acme", req_id="1", dedupe_key="acme:1", title="Senior Software Engineer",
            url="https://example.com/1", level_band="senior", family=None, location_groups=["silicon_valley"]),
    ])
    if clean:
        cover(db, "tpl", (PAY_LEVELS, COMPANY_BENEFITS), ("acme",))
    await db.commit()


# --------------------------------------------------------------------------- #
# Reads
# --------------------------------------------------------------------------- #


async def test_with_nothing_installed_the_list_is_empty_and_the_core_answers(api_client):
    body = (await api_client.get("/api/plugins")).json()
    assert body["plugins"] == []
    assert body["reference"]["applied_fp"] is None and body["reference"]["last_change"] is None
    caps = {c["slot"]: c for c in body["capabilities"]}
    assert caps[PAY_LEVELS] == {"slot": PAY_LEVELS, "providers": [], "builtin": True}
    assert caps[COMPANY_BENEFITS]["builtin"] is True
    assert caps[PAY_OBSERVATIONS]["builtin"] is False


async def test_an_unknown_plugin_is_a_coded_404(api_client):
    response = await api_client.get("/api/plugins/nope")
    assert response.status_code == 404 and response.json()["detail"]["code"] == "plugin-not-found"


async def test_the_detail_lists_runs_newest_first_and_what_approval_shows(api_client, db_session):
    await _install(db_session, approved=True, enabled=True)
    db_session.add_all([
        PluginRun(plugin_id="tpl", job="refresh", trigger="cli", fingerprint="fp-now", outcome="error",
                  message="the plugin exited without an end message"),
        PluginRun(plugin_id="tpl", job="refresh", trigger="schedule", fingerprint="fp-now", outcome="clean",
                  published={PAY_LEVELS: 4}),
    ])
    await db_session.commit()
    body = (await api_client.get("/api/plugins/tpl")).json()
    assert [r["outcome"] for r in body["runs"]] == ["clean", "error"]
    assert body["runs"][0]["published"] == {PAY_LEVELS: 4}
    assert body["approval"]["hosts"] == ["data.example.com"] and body["approval"]["identity"] == "identified"
    # An adoption is part of what is approved: it is shown, even when empty.
    assert "legacy_sources" not in body["approval"] and body["approval"]["fact_rank"] is None
    assert body["fingerprint"] == "fp-now" and body["state"] == "enabled"
    assert body["last_run"]["outcome"] == "clean" and body["last_clean_at"] is not None


async def test_the_view_says_what_coverage_is_out_of_and_how_long_the_rest_takes(api_client, db_session):
    """A plugin answers app-wide from the moment it is on, so the page
    says how many followed companies it has read and how long the rest takes, at
    the pace its own runs kept: 10 units in 600s, then 10 more in 600s."""
    await _install(db_session, approved=True, enabled=True)
    db_session.add_all([
        TrackedCompany(slug=slug, display=slug.title(), adapter="greenhouse", enabled=slug != "gone",
                       source="catalog", status="active")
        for slug in ("acme", "beta", "gamma", "gone")
    ])
    db_session.add_all([
        PluginRun(plugin_id="tpl", job="refresh", trigger="schedule", fingerprint="fp-now", outcome="stopped",
                  started_at=AT, ended_at=AT + timedelta(seconds=600), progress_done=10, progress_total=1_180),
        PluginRun(plugin_id="tpl", job="refresh", trigger="schedule", fingerprint="fp-now", outcome="stopped",
                  started_at=AT + timedelta(hours=1), ended_at=AT + timedelta(hours=1, seconds=600),
                  progress_done=20, progress_total=1_180),
    ])
    await db_session.commit()
    [view] = (await api_client.get("/api/plugins")).json()["plugins"]
    assert view["companies"] == 3
    assert view["reading_left"]["units"] == 1_160
    assert view["reading_left"]["seconds_per_unit"] == pytest.approx(60.0)
    # 1,160 at 60s is 69,600s of reading, more than one 600s budget can hold:
    # 116 runs, 115 waits between them.
    assert view["reading_left"]["seconds"] == pytest.approx(69_600 + 115 * 1_800)


async def test_a_plugin_with_no_pass_under_way_has_nothing_left_to_say(api_client, db_session):
    await _install(db_session, approved=True, enabled=True)
    [view] = (await api_client.get("/api/plugins")).json()["plugins"]
    assert view["reading_left"] is None and view["companies"] == 0


# --------------------------------------------------------------------------- #
# Approve, enable, disable
# --------------------------------------------------------------------------- #


async def test_approval_is_of_the_install_as_shown(api_client, db_session, spawned):
    await _install(db_session)
    assert (await api_client.get("/api/plugins")).json()["plugins"][0]["state"] == "needs_approval"

    stale = await api_client.post("/api/plugins/tpl/approve", json={"fingerprint": "fp-before-update"})
    assert stale.status_code == 409 and stale.json()["detail"]["code"] == "plugin-approval-stale"

    ok = await api_client.post("/api/plugins/tpl/approve", json={"fingerprint": "fp-now"})
    assert ok.status_code == 200
    assert ok.json()["plugin"]["state"] == "disabled" and ok.json()["plugin"]["approved_at"] is not None
    row = await db_session.get(PluginInstall, "tpl", populate_existing=True)
    assert row.approved_fingerprint == "fp-now"
    assert row.approved_text["hosts"] == ["data.example.com"]


async def test_enabling_selects_the_plugin_at_once_even_before_its_first_run(api_client, db_session, spawned):
    """Enabling selects the declared slots and starts a detached re-estimate,
    even when the plugin has not read any company."""
    await _install(db_session, approved=True)
    await _pay(db_session, clean=False)
    await reestimate(db_session)
    body = (await api_client.post("/api/plugins/tpl/enable")).json()
    assert body["plugin"]["state"] == "enabled"
    assert body["plugin"]["active_slots"] == [COMPANY_BENEFITS, PAY_LEVELS, PAY_OBSERVATIONS]
    assert body["reestimate_started"] is True
    assert [argv[1:] for argv in spawned] == [["-m", "tracker.plugins.reestimate_cli", "--wait", "600"]]


async def test_re_enabling_after_a_clean_run_moves_estimates_without_a_fetch(api_client, db_session, spawned):
    await _install(db_session, approved=True)
    await _pay(db_session, clean=True)
    await reestimate(db_session)  # applied: core only (the plugin is disabled)
    body = (await api_client.post("/api/plugins/tpl/enable")).json()
    assert body["plugin"]["active_slots"] == [COMPANY_BENEFITS, PAY_LEVELS, PAY_OBSERVATIONS]
    assert body["reestimate_started"] is True
    assert [argv[1:] for argv in spawned] == [["-m", "tracker.plugins.reestimate_cli", "--wait", "600"]]  # no plugin run


async def test_disable_stops_only_a_live_runner_and_moves_estimates_back(api_client, db_session, spawned,
                                                                          monkeypatch):
    await _install(db_session, approved=True, enabled=True)
    await _pay(db_session, clean=True)
    await reestimate(db_session)
    db_session.add_all([
        PluginRun(plugin_id="tpl", job="refresh", trigger="schedule", fingerprint="fp-now", outcome="running",
                  pid=4242),
        PluginRun(plugin_id="tpl", job="refresh", trigger="schedule", fingerprint="fp-now", outcome="running",
                  pid=4343),
    ])
    await db_session.commit()
    sent = []
    monkeypatch.setattr(runtime, "_command", lambda pid: "python -m scripts.plugin run tpl" if pid == 4242 else "")
    monkeypatch.setattr(runtime.os, "kill", lambda pid, sig: sent.append((pid, sig)))
    body = (await api_client.post("/api/plugins/tpl/disable")).json()
    assert body["plugin"]["state"] == "disabled" and body["stopped"] == [4242]
    assert sent == [(4242, signal.SIGTERM)]
    assert body["reestimate_started"] is True


# --------------------------------------------------------------------------- #
# Refresh now
# --------------------------------------------------------------------------- #


async def test_refresh_now_starts_the_weekly_job_detached_as_manual(api_client, db_session, spawned, awake):
    await _install(db_session, approved=True, enabled=True)
    body = (await api_client.post("/api/plugins/tpl/refresh", json={})).json()
    assert body == {"started": True, "job": "refresh", "waiting": None}
    assert spawned[0][1:] == ["-m", "tracker.plugins.cli", "run", "tpl", "refresh", "--trigger", "manual"]


async def test_refresh_now_runs_a_named_manual_job_and_refuses_an_unknown_one(api_client, db_session, spawned,
                                                                              awake):
    await _install(db_session, approved=True, enabled=True)
    assert (await api_client.post("/api/plugins/tpl/refresh", json={"job": "import"})).json()["job"] == "import"
    bad = await api_client.post("/api/plugins/tpl/refresh", json={"job": "steal"})
    assert bad.status_code == 400


@pytest.mark.parametrize("state", ["needs_approval", "disabled"])
async def test_refresh_now_refuses_a_plugin_that_may_not_run(api_client, db_session, spawned, awake, state):
    await _install(db_session, approved=state != "needs_approval", enabled=state != "disabled")
    response = await api_client.post("/api/plugins/tpl/refresh", json={})
    assert response.status_code == 409 and response.json()["detail"]["code"] == "plugin-not-runnable"
    assert spawned == []


async def test_refresh_now_never_starts_a_second_run(api_client, db_session, spawned, awake, monkeypatch):
    await _install(db_session, approved=True, enabled=True)
    db_session.add(PluginRun(plugin_id="tpl", job="refresh", trigger="schedule", fingerprint="fp-now",
                             outcome="running", pid=777))
    await db_session.commit()
    monkeypatch.setattr(runtime, "_command", lambda pid: "python -m scripts.plugin run tpl refresh")
    response = await api_client.post("/api/plugins/tpl/refresh", json={})
    assert response.status_code == 409 and response.json()["detail"]["code"] == "plugin-running"
    assert spawned == []


async def test_refresh_now_waits_out_a_maintenance_wake(api_client, db_session, spawned, monkeypatch):
    from tracker.api.routers import plugins as router

    monkeypatch.setattr(router, "read_power", lambda: Power(dark_wake=True, on_battery=False))
    await _install(db_session, approved=True, enabled=True)
    body = (await api_client.post("/api/plugins/tpl/refresh", json={})).json()
    assert body["started"] is False and body["waiting"] and spawned == []


# --------------------------------------------------------------------------- #
# Pause, Start, schedule, uninstall
# --------------------------------------------------------------------------- #


async def test_pause_stops_a_live_runner_holds_the_schedule_and_moves_no_estimate(
    api_client, db_session, spawned, monkeypatch
):
    await _install(db_session, approved=True, enabled=True)
    await _pay(db_session, clean=True)
    await reestimate(db_session)
    db_session.add(PluginRun(plugin_id="tpl", job="refresh", trigger="schedule", fingerprint="fp-now",
                             outcome="running", pid=4242))
    await db_session.commit()
    sent = []
    monkeypatch.setattr(runtime, "_command", lambda pid: "python -m scripts.plugin run tpl")
    monkeypatch.setattr(runtime.os, "kill", lambda pid, sig: sent.append((pid, sig)))
    body = (await api_client.post("/api/plugins/tpl/pause")).json()
    view = body["plugin"]
    assert (view["state"], view["paused"], view["next_update_at"]) == ("enabled", True, None)
    assert view["active_slots"] == [COMPANY_BENEFITS, PAY_LEVELS, PAY_OBSERVATIONS], "a paused plugin still answers"
    assert body["stopped"] == [4242] and sent == [(4242, signal.SIGTERM)]
    assert body["reestimate_started"] is False and spawned == []
    assert await runtime.start_due(db_session, trigger="schedule") == [] and spawned == []


async def test_resume_releases_the_pause_and_starts_nothing(api_client, db_session, spawned):
    await _install(db_session, approved=True, enabled=True)
    await api_client.post("/api/plugins/tpl/pause")
    body = (await api_client.post("/api/plugins/tpl/resume")).json()
    assert body["plugin"]["paused"] is False and body["plugin"]["paused_at"] is None
    assert spawned == []


async def test_start_releases_a_pause_and_runs_now(api_client, db_session, spawned, awake):
    await _install(db_session, approved=True, enabled=True)
    await api_client.post("/api/plugins/tpl/pause")
    assert (await api_client.post("/api/plugins/tpl/refresh", json={})).json()["started"] is True
    assert (await api_client.get("/api/plugins/tpl")).json()["paused"] is False


async def test_the_user_s_schedule_is_what_every_job_runs_on_and_null_returns_the_plugin_s(
    api_client, db_session, spawned
):
    await _install(db_session, approved=True, enabled=True)
    db_session.add(PluginRun(plugin_id="tpl", job="refresh", trigger="schedule", fingerprint="fp-now",
                             outcome="clean", started_at=AT, ended_at=AT))
    await db_session.commit()
    view = (await api_client.put("/api/plugins/tpl/schedule", json={"schedule": "daily"})).json()["plugin"]
    assert view["schedule"] == "daily" and view["schedules"] == ["manual", "daily", "weekly", "monthly"]
    assert [(j["name"], j["schedule"], j["manifest_schedule"]) for j in view["jobs"]] == [
        ("refresh", "daily", "weekly"), ("import", "daily", "manual")]
    assert view["next_update_at"] == "2026-10-02T00:00:00Z"
    manual = (await api_client.put("/api/plugins/tpl/schedule", json={"schedule": "manual"})).json()["plugin"]
    assert manual["next_update_at"] is None
    back = (await api_client.put("/api/plugins/tpl/schedule", json={"schedule": None})).json()["plugin"]
    assert back["schedule"] is None and [j["schedule"] for j in back["jobs"]] == ["weekly", "manual"]
    assert back["next_update_at"] == "2026-10-08T00:00:00Z"
    bad = await api_client.put("/api/plugins/tpl/schedule", json={"schedule": "hourly"})
    assert bad.status_code == 422


async def test_uninstall_forgets_the_code_keeps_its_data_and_hides_its_rows(
    api_client, db_session, spawned, tmp_path
):
    home = tmp_path / "tpl"
    (home / "src").mkdir(parents=True)
    (home / "venv").mkdir()
    (home / "data").mkdir()
    (home / "data" / "state.json").write_text("{}")
    await _install(db_session, approved=True, enabled=True)
    await db_session.execute(
        PluginInstall.__table__.update().values(source_dir=str(home / "src"))
    )
    await db_session.commit()
    await _pay(db_session, clean=True)
    body = (await api_client.delete("/api/plugins/tpl")).json()
    assert body["plugin"]["state"] == "removed" and body["plugin"]["active_slots"] == []
    assert not (home / "src").exists() and not (home / "venv").exists()
    assert (home / "data" / "state.json").exists(), "its data directory is the user's to keep"
    assert await db_session.scalar(select(func.count()).select_from(CompanyCompLevel)
                                   .where(CompanyCompLevel.provider == "tpl")) == 1, "rows stay until Remove data"
    again = await api_client.post("/api/plugins/tpl/enable")
    assert again.status_code == 409 and again.json()["detail"]["code"] == "plugin-not-runnable"


# --------------------------------------------------------------------------- #
# Remove data
# --------------------------------------------------------------------------- #


async def test_remove_data_needs_the_typed_id_and_a_disabled_plugin(api_client, db_session, spawned):
    await _install(db_session, approved=True, enabled=True)
    await _pay(db_session, clean=True)
    wrong = await api_client.post("/api/plugins/tpl/remove-data", json={"confirm": "yes"})
    assert wrong.status_code == 400 and wrong.json()["detail"]["code"] == "plugin-confirm-mismatch"
    enabled = await api_client.post("/api/plugins/tpl/remove-data", json={"confirm": "tpl"})
    assert enabled.status_code == 409 and enabled.json()["detail"]["code"] == "plugin-still-enabled"
    assert await db_session.scalar(select(func.count()).select_from(CompanyCompLevel)
                                   .where(CompanyCompLevel.provider == "tpl")) == 1


async def test_remove_data_deletes_the_plugin_rows_and_keeps_history(api_client, db_session, spawned):
    """Its rows and the estimates computed from them go; ours, stored beside
    them, and the append-only history stay."""
    from sqlalchemy import update

    from tracker.db.models import JobCompEstimate

    await _install(db_session, approved=True, enabled=True)
    await _pay(db_session, clean=True)
    db_session.add_all([
        ExternalCompObservation(company_slug="acme", provider="tpl", dedup_key="k1", source_level="L5",
                                total_amount=500_000, base_amount=250_000, equity_amount=200_000, bonus_amount=50_000,
                                currency="USD", country="US",
                                snapshot_date=AT.date()),
    ])
    await db_session.commit()
    await reestimate(db_session)  # the plugin's estimate and ours, side by side
    await db_session.execute(update(PluginInstall).values(enabled=False))
    await db_session.commit()
    await reestimate(db_session)  # the estimates stop reading it
    estimates = select(JobCompEstimate.source, JobCompEstimate.comp_median).order_by(JobCompEstimate.source)
    assert (await db_session.execute(estimates)).all() == [("roleband", 300_000), ("tpl", 999_000)]

    # What RoleBand derived and kept for it: a chart series from its
    # estimates, its resume cursor, a number it reported. Ours stays.
    from tracker.db.models import CompSnapshot, PluginReport, PluginState

    db_session.add_all([
        CompSnapshot(metric_date=AT, company="acme", comp_values=[999_000], source="tpl"),
        CompSnapshot(metric_date=AT, company="acme", comp_values=[300_000], source="roleband"),
        PluginState(plugin_id="tpl", key="resume.refresh", value="acme"),
        PluginReport(plugin_id="tpl", key="absent", value=3, label="companies the site does not list"),
    ])
    await db_session.commit()

    body = (await api_client.post("/api/plugins/tpl/remove-data", json={"confirm": "tpl"})).json()
    assert body["deleted"] == {"company_comp_level": 1, "company_benefit": 1, "job_comp_estimate": 1,
                               "comp_snapshot": 1, "plugin_state": 1, "plugin_report": 1, "plugin_coverage": 2}
    assert set((await db_session.execute(select(CompSnapshot.source))).scalars().all()) == {"roleband"}
    left = {
        "core": await db_session.scalar(select(func.count()).select_from(CompanyCompLevel)
                                        .where(CompanyCompLevel.provider == "manual")),
        "observations": await db_session.scalar(select(func.count()).select_from(ExternalCompObservation)),
    }
    assert left == {"core": 1, "observations": 1}
    assert (await db_session.execute(estimates)).all() == [("roleband", 300_000)]


async def test_remove_data_waits_until_the_estimates_no_longer_read_the_plugin(api_client, db_session, spawned):
    """Disabled, but the re-estimate the disable started has not landed: the
    stored estimates still come from its rows, so they stay until it does."""
    await _install(db_session, approved=True, enabled=True)
    await _pay(db_session, clean=True)
    await reestimate(db_session)  # the applied set now reads tpl
    await api_client.post("/api/plugins/tpl/disable")
    moving = await api_client.post("/api/plugins/tpl/remove-data", json={"confirm": "tpl"})
    assert moving.status_code == 409 and moving.json()["detail"]["code"] == "plugin-estimates-moving"
    assert await db_session.scalar(select(func.count()).select_from(CompanyCompLevel)
                                   .where(CompanyCompLevel.provider == "tpl")) == 1
    await reestimate(db_session)  # the disable's re-estimate lands
    done = await api_client.post("/api/plugins/tpl/remove-data", json={"confirm": "tpl"})
    assert done.status_code == 200 and done.json()["deleted"]["company_comp_level"] == 1


async def test_a_lapsed_approval_reads_as_still_on_and_turns_off_without_approving(api_client, db_session, spawned):
    """An update lapses the approval but not the user's switch: the list says the
    plugin is on, and disable works without approving it first."""
    await _install(db_session, approved=True, enabled=True)
    row = await db_session.get(PluginInstall, "tpl")
    row.fingerprint = "fp-updated"
    await db_session.commit()
    view = (await api_client.get("/api/plugins")).json()["plugins"][0]
    assert (view["state"], view["enabled"]) == ("needs_approval", True)
    off = (await api_client.post("/api/plugins/tpl/disable")).json()["plugin"]
    assert (off["state"], off["enabled"]) == ("needs_approval", False)


async def test_the_user_s_order_between_plugins_is_what_the_registry_reads(db_session):
    """Two plugins declare one slot: the user's order (`lifecycle.set_order`)
    decides which ONE answers (never both), an id that does not
    provide the slot is refused, and an empty order returns to the id order."""
    from tracker.plugins import lifecycle
    from tracker.plugins.registry import load_providers

    for pid in ("aaa", "zzz"):
        db_session.add(PluginInstall(plugin_id=pid, name=pid, version="1.0.0", source_dir="/x", manifest_sha="m",
                                     code_sha="c", manifest={"provides": [{"slot": PAY_LEVELS}]}, fingerprint="f",
                                     approved_fingerprint="f", enabled=True))
    await db_session.flush()
    for pid in ("aaa", "zzz"):
        cover(db_session, pid, (PAY_LEVELS,), ("acme",))
    await db_session.commit()
    assert (await load_providers(db_session)).active[PAY_LEVELS] == ("aaa",)
    await lifecycle.set_order(db_session, PAY_LEVELS, ["zzz", "aaa"])
    assert (await load_providers(db_session)).active[PAY_LEVELS] == ("zzz",)
    with pytest.raises(lifecycle.Refused, match="not an installed plugin providing"):
        await lifecycle.set_order(db_session, PAY_LEVELS, ["nobody"])
    await lifecycle.set_order(db_session, PAY_LEVELS, [])
    assert (await load_providers(db_session)).active[PAY_LEVELS] == ("aaa",)


# --------------------------------------------------------------------------- #
# /api/status and the route table
# --------------------------------------------------------------------------- #


async def test_status_carries_the_reference_set_and_running_plugins(api_client, db_session):
    await _install(db_session, approved=True, enabled=True)
    await _pay(db_session, clean=True)
    result = await reestimate(db_session)
    db_session.add(PluginRun(plugin_id="tpl", job="refresh", trigger="sync", fingerprint="fp-now",
                             outcome="running"))
    await db_session.commit()
    body = (await api_client.get("/api/status")).json()
    assert body["reference"]["applied_fp"] == result.target_fp
    assert body["reference"]["last_change_id"] == result.change_id
    assert body["reference"]["last_change"]["gained"] == 1 and body["reference"]["pending_jobs"] == 0
    assert body["plugins_running"] == 1
    caps = {c["slot"]: (c["providers"], c["builtin"]) for c in body["capabilities"]}
    # One source per slot: the plugin answers its slots, ours the rest, never both.
    assert caps[PAY_LEVELS] == (["tpl"], False)
    assert caps["company.facts"] == ([], True)


async def test_installing_a_plugin_leaves_the_api_shape_unchanged(api_client, db_session):
    from tracker.api.app import app

    app.openapi_schema = None
    before = app.openapi()
    await _install(db_session, approved=True, enabled=True)
    await api_client.get("/api/plugins")
    app.openapi_schema = None
    assert app.openapi() == before


async def test_comp_trends_marks_each_reference_switch_in_its_window(api_client, db_session):
    from datetime import timedelta

    from tracker.db.models import ReferenceChange

    now = datetime.now(UTC)
    db_session.add_all([
        ReferenceChange(at=now - timedelta(days=200), to_fp="old", moved_report={"jobs": 9, "moved": 9}),
        ReferenceChange(at=now - timedelta(days=3), to_fp="new", moved_report={"jobs": 5, "moved": 2,
                                                                             "companies": {"acme": 2}}),
        # Code that answers the same: a change of fingerprint, no step in any series.
        ReferenceChange(at=now - timedelta(days=1), to_fp="same", moved_report={"jobs": 5, "moved": 0,
                                                                              "gained": 0, "lost": 0}),
    ])
    await db_session.commit()
    body = (await api_client.get("/api/statistics/comp-trends?days=90")).json()
    assert [(c["moved"], c["companies"]) for c in body["reference_changes"]] == [(2, 1)]
    every = (await api_client.get("/api/statistics/comp-trends?days=0")).json()
    assert [c["jobs"] for c in every["reference_changes"]] == [9, 5]


async def _acme_figures(api_client) -> dict[int, tuple]:
    """What the board shows for each acme job: (median, who answered)."""
    items = (await api_client.get("/api/jobs?status=open&limit=50")).json()["items"]
    return {j["id"]: (j["comp_median"], j["comp_provider"]) for j in items if j["company"] == "acme"}


def _detail_figures(body: dict) -> tuple:
    """Every pay figure a job's detail shows: headline, who answered, the
    package's estimate and the per-provider breakdown (ours 300k, plugin 999k)."""
    package = body["comp_package"]["estimate"] or {}
    return (body["comp_median"], body["comp_provider"], package.get("median"),
            sorted({s["median"] for s in body["comp_sources"] if s["median"] is not None}))


async def test_a_switch_mid_way_shows_one_source_in_the_list_and_the_detail(api_client, db_session):
    """Batches move each source's stored row, never what a reader shows.
    Until the last batch every job, in the list and in its detail, shows the
    applied set (ours here); the last batch moves them all at once."""
    await _install(db_session, approved=True, enabled=False)
    await _pay(db_session, clean=True)
    db_session.add_all([
        Job(company="acme", req_id=str(n), dedupe_key=f"acme:{n}", title="Senior Software Engineer",
            url=f"https://example.com/{n}", level_band="senior", family=None, location_groups=["silicon_valley"])
        for n in (2, 3)
    ])
    await db_session.commit()
    assert (await reestimate(db_session)).applied
    ours = await _acme_figures(api_client)
    assert len(ours) == 3 and {median for median, _ in ours.values()} == {300_000}
    first = min(ours)
    ours_detail = _detail_figures((await api_client.get(f"/api/jobs/{first}")).json())
    assert ours_detail[0] == ours_detail[2] == 300_000 and ours_detail[3] == [300_000]

    (await db_session.get(PluginInstall, "tpl")).enabled = True
    await db_session.commit()
    partial = await reestimate(db_session, batch=1, max_batches=1)
    # The first job's plugin estimate is stored, yet nothing a reader shows moved.
    assert await _acme_figures(api_client) == ours
    assert _detail_figures((await api_client.get(f"/api/jobs/{first}")).json()) == ours_detail
    assert not partial.applied and partial.reached == 1 and partial.written == 0
    reference = (await api_client.get("/api/status")).json()["reference"]
    assert reference["target_fp"] == partial.target_fp and reference["pending_jobs"] == 2

    rest = await reestimate(db_session, batch=1)
    assert rest.applied and rest.written == 3
    assert {figure for figure in (await _acme_figures(api_client)).values()} == {(999_000, "tpl")}
    body = (await api_client.get(f"/api/jobs/{first}")).json()
    assert _detail_figures(body) == (999_000, "tpl", 999_000, [999_000])
    assert (body["comp_component"], body["comp_base_median"]) == ("total", 600_000)
    assert (await api_client.get("/api/status")).json()["reference"]["pending_jobs"] == 0


def _profile_sources(body: dict) -> tuple:
    """Who the profile's pay and benefits come from, read off what it shows."""
    benefits = sorted({i["provider"] for c in body["benefits"] for i in c["items"]})
    return (body["sources"]["pay"]["plugin"], body["sources"]["benefits"]["plugin"], benefits,
            [r["tc_median"] for r in body["comp_levels"]])


async def test_the_whole_app_changes_source_at_the_one_flip(api_client, db_session, spawned):
    """Turning a plugin on records the target at once, so the status says
    estimates are updating before the spawned re-estimate starts, and no slot
    moves until that re-estimate applies the set; then pay and benefits move
    together. Off is the same in reverse. Benefits and company size never move
    at the click with pay following later while the status says nothing is
    pending."""
    await _install(db_session, approved=True, enabled=False)
    await _pay(db_session, clean=True)
    assert (await reestimate(db_session)).applied
    ours = _profile_sources((await api_client.get("/api/company-profiles/acme")).json())
    assert ours == (None, None, [], [300_000])

    response = await api_client.post("/api/plugins/tpl/enable")
    assert response.status_code == 200 and response.json()["reestimate_started"] is True
    assert _profile_sources((await api_client.get("/api/company-profiles/acme")).json()) == ours
    reference = (await api_client.get("/api/status")).json()["reference"]
    assert reference["target_fp"] is not None and reference["pending_jobs"] == 1

    assert (await reestimate(db_session)).applied
    on = (await api_client.get("/api/company-profiles/acme")).json()
    assert _profile_sources(on) == ("tpl", "tpl", ["tpl"], [999_000])
    assert on["attribution"] == "Example data"
    assert (await api_client.get("/api/status")).json()["reference"]["target_fp"] is None

    assert (await api_client.post("/api/plugins/tpl/disable")).json()["reestimate_started"] is True
    assert (await api_client.get("/api/status")).json()["reference"]["pending_jobs"] == 1
    assert _profile_sources((await api_client.get("/api/company-profiles/acme")).json()) == _profile_sources(on)
    assert (await reestimate(db_session)).applied
    assert _profile_sources((await api_client.get("/api/company-profiles/acme")).json()) == ours


async def test_a_plugin_is_credited_only_on_a_company_it_has_read(api_client, db_session):
    """A company the plugin has not read shows none of its data, so
    its profile names no plugin credit."""
    await _install(db_session, approved=True, enabled=True)
    await _pay(db_session, clean=True)
    db_session.add(CompanyProfile(slug="globex", display_name="Globex"))
    await db_session.commit()
    await reestimate(db_session)
    assert (await api_client.get("/api/company-profiles/acme")).json()["attribution"] == "Example data"
    globex = (await api_client.get("/api/company-profiles/globex")).json()
    assert globex["sources"]["pay"] == {"plugin": "tpl", "plugin_name": "Template plugin", "covered": False}
    assert globex["attribution"] is None


async def test_a_plugin_s_total_is_never_split_by_our_heuristic(api_client, db_session):
    """The plugin's acme rung states a total and a base, no grant and
    no bonus, so it measures no split. Its 999k stays whole; our heuristic and
    pay policy, which split ours, never split it."""
    await _install(db_session, approved=True, enabled=True)
    await _pay(db_session, clean=True)
    await reestimate(db_session)
    job = (await db_session.execute(select(Job))).scalar_one()
    body = (await api_client.get(f"/api/jobs/{job.id}")).json()
    package = body["comp_package"]
    assert (body["comp_median"], body["comp_provider"]) == (999_000, "tpl")
    assert (package["components"], package["total"], package["split_source"]) == ([], None, None)
    assert package["no_split_reason"] == "plugin_without_split"
    assert package["policy"] is None  # our offer policy stays off the plugin's card

    (await db_session.get(PluginInstall, "tpl")).enabled = False
    await db_session.commit()
    await reestimate(db_session)
    ours = (await api_client.get(f"/api/jobs/{job.id}")).json()["comp_package"]
    assert ours["split_source"] == "heuristic" and ours["components"] and ours["no_split_reason"] is None


async def test_the_equity_check_never_models_a_plugin_s_figure_with_our_heuristic(api_client, db_session):
    """The same on the diagnostic: acme states its base, so the check reads the
    equity its shown total implies. The plugin's rung measures no split, so
    there is no modeled share to check it against: the row is counted
    `unsplit`. When our source answers, our heuristic models its split."""
    await _install(db_session, approved=True, enabled=True)
    await _pay(db_session, clean=True)
    job = (await db_session.execute(select(Job))).scalar_one()
    job.status, job.in_scope = "open", True
    job.disclosed_base_min, job.disclosed_base_max, job.disclosed_currency = 400_000, 500_000, "USD"
    job.disclosed_pay_basis, job.disclosed_pay_period, job.disclosed_bonus_pct = "base", "year", 0.1
    job.structured_prompt_version = "disclosed_comp/v5"
    await db_session.commit()
    await reestimate(db_session)

    body = (await api_client.get("/api/statistics/equity-validation")).json()
    assert body["groups"] == []
    assert body["excluded"]["unsplit"] == 1 and body["coverage"]["used_reqs"] == 0

    (await db_session.get(PluginInstall, "tpl")).enabled = False
    await db_session.commit()
    await reestimate(db_session)
    body = (await api_client.get("/api/statistics/equity-validation")).json()
    [group] = body["groups"]
    assert (group["company"], group["comp_medians"], group["model_source"]) == ("acme", [300_000], "heuristic")
    assert body["excluded"]["unsplit"] == 0


async def test_a_job_at_a_company_the_plugin_has_not_read_says_so(api_client, db_session):
    """The job names who answers pay and whether it has read the
    company; one it has not read is "not covered", never "split not reported"
    (the plugin gave nothing to split) and never our estimate."""
    await _install(db_session, approved=True, enabled=True)
    await _pay(db_session, clean=False)
    job = (await db_session.execute(select(Job))).scalar_one()
    job.structured_at, job.disclosed_base_min, job.disclosed_base_max = AT, 230_000, 330_000
    job.disclosed_currency, job.disclosed_pay_basis, job.disclosed_pay_period = "USD", "base", "year"
    await db_session.commit()
    await reestimate(db_session)
    body = (await api_client.get(f"/api/jobs/{job.id}")).json()
    assert body["pay_source"] == {"plugin": "tpl", "plugin_name": "Template plugin", "covered": False}
    assert body["comp_median"] is None and body["comp_package"]["total"] is None
    assert body["comp_package"]["no_split_reason"] == "plugin_not_covered"
    assert body["comp_package"]["stated"] == {"low": 230_000, "high": 330_000}

    cover(db_session, "tpl", (PAY_LEVELS, COMPANY_BENEFITS), ("acme",))
    await db_session.commit()
    await reestimate(db_session)
    read = (await api_client.get(f"/api/jobs/{job.id}")).json()
    assert read["pay_source"] == {"plugin": "tpl", "plugin_name": "Template plugin", "covered": True}
    assert read["comp_package"]["no_split_reason"] == "plugin_without_split"

    (await db_session.get(PluginInstall, "tpl")).enabled = False
    await db_session.commit()
    await reestimate(db_session)
    ours = (await api_client.get(f"/api/jobs/{job.id}")).json()
    assert ours["pay_source"] == {"plugin": None, "plugin_name": None, "covered": True}


async def test_pay_coverage_names_the_plugin_answering_pay_and_the_companies_it_has_read(api_client, db_session):
    """One read every list surface takes "not covered" from, as of the
    applied set: a company read after the last switch is not in it yet."""
    assert (await api_client.get("/api/pay-coverage")).json() == {"plugin": None, "plugin_name": None,
                                                                  "companies": []}
    await _install(db_session, approved=True, enabled=True)
    await _pay(db_session, clean=True)
    db_session.add(CompanyProfile(slug="globex", display_name="Globex"))
    await db_session.commit()
    await reestimate(db_session)
    assert (await api_client.get("/api/pay-coverage")).json() == {"plugin": "tpl", "plugin_name": "Template plugin",
                                                                  "companies": ["acme"]}
    cover(db_session, "tpl", (PAY_LEVELS,), ("globex",), at=AT + timedelta(days=1))
    await db_session.commit()
    assert (await api_client.get("/api/pay-coverage")).json()["companies"] == ["acme"], "not before the next switch"
    await reestimate(db_session)
    assert (await api_client.get("/api/pay-coverage")).json()["companies"] == ["acme", "globex"]


async def test_the_detail_takes_every_pay_figure_from_the_source_it_names(api_client, db_session):
    """A switch that commits between two of the detail's reads must not pair one
    source's headline with the other's breakdown: the figures come
    from the applied source's stored row, never from the list's copy beside it."""
    await _install(db_session, approved=True, enabled=False)
    await _pay(db_session, clean=True)
    await reestimate(db_session)
    job = (await db_session.execute(select(Job))).scalar_one()
    # The list's copy as a flip committed mid-request would leave it: the plugin's.
    job.comp_median, job.comp_provider = 999_000, "tpl"
    await db_session.commit()
    median, provider, package_median, breakdown = _detail_figures(
        (await api_client.get(f"/api/jobs/{job.id}")).json())
    assert (median, package_median, breakdown) == (300_000, 300_000, [300_000])
    assert provider != "tpl"


async def test_the_switch_moves_company_size_and_never_writes_a_profile_column(api_client, db_session, spawned):
    """The profile's columns are ours: a plugin's HQ is never read, and
    its company size shows beside ours while it is on, with no fetch and nothing
    of ours rewritten."""
    from tracker.db.models import CompanyFact

    await _install(db_session, approved=True, enabled=False)
    db_session.add(CompanyProfile(slug="acme", display_name="Acme"))
    await db_session.flush()
    cover(db_session, "tpl", ("company.facts",), ("acme",))
    db_session.add_all([
        CompanyFact(company_slug="acme", field="hq_city", value={"v": "Shelbyville"}, source="tpl", observed_at=AT),
        CompanyFact(company_slug="acme", field="headcount", value={"v": 777}, source="tpl", observed_at=AT),
    ])
    await db_session.commit()
    db_session.expire_all()
    (await db_session.get(PluginInstall, "tpl")).manifest = {**MANIFEST, "provides": [
        *MANIFEST["provides"], {"slot": "company.facts", "fields": ["hq_city", "headcount"], "rank": 40}]}
    await db_session.commit()

    async def shown() -> tuple:
        fields = (await api_client.get("/api/company-profiles/acme")).json()["fields"]
        profile = await db_session.get(CompanyProfile, "acme", populate_existing=True)
        return (fields["hq_city"]["value"], fields["headcount"]["value"], fields["headcount"]["answered_by"],
                profile.hq_city, profile.headcount)

    assert await shown() == (None, None, None, None, None)
    await api_client.post("/api/plugins/tpl/enable")
    assert await shown() == (None, 777, "tpl", None, None)
    await api_client.post("/api/plugins/tpl/disable")
    assert await shown() == (None, None, None, None, None)


async def test_a_manifest_naming_legacy_rows_adopts_nothing(api_client, db_session, spawned):
    """A manifest's `legacy_sources` must not adopt rows: the plugin answers
    only from its own rows, and its view exposes no adopted slots."""
    db_session.add(PluginInstall(
        plugin_id="acme-reports", name="Acme reports", version="1.0.0", source_dir="/x/src", manifest_sha="m",
        code_sha="c", fingerprint="f", approved_fingerprint="f", enabled=True,
        manifest={"plugin": {"id": "acme-reports", "legacy_sources": ["acme.reports"]},
                  "provides": [{"slot": PAY_OBSERVATIONS}], "jobs": [{"name": "refresh", "schedule": "manual"}]},
    ))
    await db_session.commit()
    [view] = (await api_client.get("/api/plugins")).json()["plugins"]
    assert view["active_slots"] == [PAY_OBSERVATIONS] and "adopted_slots" not in view
    off = (await api_client.post("/api/plugins/acme-reports/disable")).json()["plugin"]
    assert off["active_slots"] == []


# --------------------------------------------------------------------------- #
# The sites' robots rules, and the user's consent past them
# --------------------------------------------------------------------------- #

SITE_RULES = "User-agent: *\nDisallow: /v1/ladders/globex\nDisallow: /*?page=\n"


@pytest.fixture
def sites(monkeypatch):
    """The only internet the robots read has: data.example.com's file."""
    import httpx

    from tracker.plugins import robots

    served = {"data.example.com": httpx.Response(200, text=SITE_RULES)}

    def handler(request):
        return served.get(request.url.host, httpx.Response(599))

    monkeypatch.setattr(robots, "public_client", lambda **_: httpx.AsyncClient(
        transport=httpx.MockTransport(handler), headers={"User-Agent": "RoleBand-test/1"}))
    return served


async def test_the_approval_shows_each_site_s_rules_and_records_the_choice(api_client, db_session, sites, spawned):
    from tracker.plugins.robots import robots_sha

    await _install(db_session)
    body = (await api_client.get("/api/plugins/tpl/robots")).json()
    sha = robots_sha(SITE_RULES)
    assert body == {"sites": [{"host": "data.example.com", "state": "rules", "sha256": sha,
                               "disallow": ["/v1/ladders/globex", "/*?page="]}],
                    "consent": None, "consent_at": None}

    approved = await api_client.post("/api/plugins/tpl/approve",
                                     json={"fingerprint": "fp-now", "robots": {"data.example.com": sha}})
    assert approved.status_code == 200
    assert approved.json()["plugin"]["robots_consent_at"] is not None
    assert (await api_client.get("/api/plugins/tpl/robots")).json()["consent"] == {"data.example.com": sha}

    # Approving again without it is a choice too: it follows the rules.
    await api_client.post("/api/plugins/tpl/approve", json={"fingerprint": "fp-now"})
    assert (await api_client.get("/api/plugins/tpl/robots")).json()["consent"] is None


async def test_consent_names_only_declared_sites_by_a_file_s_sha(api_client, db_session):
    await _install(db_session, approved=True)
    for robots in ({"evil.example.com": "a" * 64}, {"data.example.com": "not-a-sha"}):
        response = await api_client.put("/api/plugins/tpl/robots", json={"robots": robots})
        assert response.status_code == 400 and response.json()["detail"]["code"] == "invalid-input"
    assert (await db_session.get(PluginInstall, "tpl", populate_existing=True)).robots_consent is None


async def test_a_site_that_changed_its_rules_since_the_consent_reads_as_lapsed(api_client, db_session):
    await _install(db_session, approved=True)
    assert (await api_client.put("/api/plugins/tpl/robots", json={"robots": {"data.example.com": "a" * 64}})
            ).status_code == 200
    row = await db_session.get(PluginInstall, "tpl", populate_existing=True)
    row.robots_seen = {"data.example.com": "a" * 64}
    await db_session.commit()
    [view] = (await api_client.get("/api/plugins")).json()["plugins"]
    assert view["robots_lapsed"] == []
    row.robots_seen = {"data.example.com": "b" * 64}
    await db_session.commit()
    [view] = (await api_client.get("/api/plugins")).json()["plugins"]
    assert view["robots_lapsed"] == ["data.example.com"]
    assert (await api_client.put("/api/plugins/tpl/robots", json={"robots": None})).json()["plugin"][
        "robots_consent_at"] is None


async def test_a_site_that_refuses_its_rules_cannot_be_consented_past(api_client, db_session, sites):
    import httpx

    sites["data.example.com"] = httpx.Response(403)
    await _install(db_session)
    [site] = (await api_client.get("/api/plugins/tpl/robots")).json()["sites"]
    assert (site["state"], site["sha256"], site["disallow"]) == ("refused", None, [])



async def test_remove_data_is_refused_while_an_update_runs(api_client, db_session, spawned):
    """A run would publish into the tables being emptied."""
    await _install(db_session, approved=True, enabled=False)
    db_session.add(PluginRun(plugin_id="tpl", job="refresh", trigger="cli", fingerprint="fp-now",
                             outcome="running", pid=os.getpid()))
    await db_session.commit()
    response = await api_client.post("/api/plugins/tpl/remove-data", json={"confirm": "tpl"})
    assert response.status_code == 409 and response.json()["detail"]["code"] == "plugin-running"


async def test_the_view_says_what_remove_data_deletes_and_whether_it_may_now(api_client, db_session):
    """Remove data deletes the slots `SlotSpec.removable` names, so the
    dialog says so per plugin; and it is held while the estimates still read the
    plugin, which the view says, so the button never offers what the server refuses."""
    await _install(db_session, approved=True, enabled=True)
    await _pay(db_session, clean=True)
    await reestimate(db_session)
    [view] = (await api_client.get("/api/plugins")).json()["plugins"]
    assert view["removable_slots"] == [COMPANY_BENEFITS, PAY_LEVELS]
    assert view["estimates_read"] is True
    (await db_session.get(PluginInstall, "tpl")).enabled = False
    await db_session.commit()
    await reestimate(db_session)
    [view] = (await api_client.get("/api/plugins")).json()["plugins"]
    assert view["estimates_read"] is False


async def test_with_plugins_off_the_api_lists_none_and_hides_each_one(api_client, db_session, monkeypatch):
    await _install(db_session, approved=True, enabled=True)
    on = (await api_client.get("/api/plugins")).json()
    assert on["available"] is True and [p["id"] for p in on["plugins"]] == ["tpl"]  # control
    _plugins(monkeypatch, "false")
    off = (await api_client.get("/api/plugins")).json()
    assert off["available"] is False and off["plugins"] == []
    assert (await api_client.get("/api/plugins/tpl")).status_code == 404


async def test_plugins_are_off_unless_turned_on(api_client, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)  # no `.env` to turn them on
    _plugins(monkeypatch, None)
    assert (await api_client.get("/api/plugins")).json()["available"] is False


async def test_the_view_carries_the_plugin_s_own_words(api_client, db_session):
    manifest = {**MANIFEST, "plugin": {**MANIFEST["plugin"], "description": "Pay ladders from example.com"}}
    db_session.add(PluginInstall(
        plugin_id="tpl", name="Template plugin", version="0.1.0", source_dir="/x/src", manifest_sha="m",
        code_sha="c", manifest=manifest, fingerprint="fp", approved_fingerprint="fp", enabled=True,
    ))
    db_session.add(PluginRun(plugin_id="tpl", job="refresh", trigger="cli", fingerprint="fp", outcome="stopped",
                             summary="Read pay for 56 of 1,180 companies"))
    await db_session.commit()
    [view] = (await api_client.get("/api/plugins")).json()["plugins"]
    assert view["description"] == "Pay ladders from example.com"
    assert view["last_run"]["summary"] == "Read pay for 56 of 1,180 companies"
    detail = (await api_client.get("/api/plugins/tpl")).json()
    assert detail["runs"][0]["summary"] == "Read pay for 56 of 1,180 companies"
