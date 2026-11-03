"""The core's plugin host gives the fake host's answers, against the real tables.

Every run here is a real `roleband_plugin_sdk.runner` process speaking stdio
to `tracker.plugins.host`, writing to the scratch database. HTTP never leaves
the process: the client is an `httpx.MockTransport` that records each request
and answers only the URLs below.

Contracts:
- install pins what runs; approval lapses on any change, and an edit to the
  installed copy stops the plugin;
- a clean run writes provider-stamped, atlas- or words-banded rows, and makes
  the plugin active only then; an unapproved, disabled or changed plugin never
  starts;
- the host refuses an undeclared host, a robots-disallowed path and a
  non-identified identity, and the run ends `partial`, not clean;
- a spent budget ends `bounded`, a stop ends `stopped`; neither retires;
- a clean complete snapshot retires the rows it did not repeat, never deletes;
- the plugin's environment carries no address or key of ours.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from datetime import timedelta
from pathlib import Path
from unittest import mock

import httpx
import pytest
from sqlalchemy import select

from tests.plugin_web import ACME, BASE, REPO, TEMPLATE, Web, plugin_levels, seed_plugin_companies
from tracker.db.models import (
    CompanyBenefit,
    CompanyCompLevel,
    CompanyProfile,
    ExternalCompObservation,
    PluginCoverage,
    PluginInstall,
    PluginReport,
    PluginRun,
    PluginState,
    ReferenceState,
)
from tracker.db.queries.reference_pay import package_rows, pay_level_rows
from tracker.levels.words import rung_band
from tracker.platform.ratelimit import RateLimiter
from tracker.plugins import store
from tracker.plugins.host import HostConfig, NotRunnable, pacing_delay, run_job
from tracker.plugins.install import InstallRefused, approval_text, code_sha, install
from tracker.plugins.reestimate import reestimate, reference_inputs
from tracker.plugins.registry import reader_providers

#: The one process these tests start is the SDK runner, through the host's
#: `spawn` hook; everything else stays refused by `no_escape`.
#: Captured at import, before the fixture replaces them.
REAL_SPAWN = asyncio.create_subprocess_exec
REAL_POPEN = subprocess.Popen
#: A stop ends the runner the test started, and only that one.
REAL_KILL = os.kill


async def spawn_runner(*args, **kwargs):
    """The real spawner, for this one call: asyncio builds on `Popen`."""
    with mock.patch.object(subprocess, "Popen", REAL_POPEN):
        return await REAL_SPAWN(*args, **kwargs)

pytestmark = [pytest.mark.asyncio, pytest.mark.usefixtures("no_escape")]

SDK = REPO / "sdk" / "python"


async def _installed(db, tmp_path, source=TEMPLATE, *, approve=True, enable=True) -> PluginInstall:
    row, _ = await install(db, source, plugins_dir=tmp_path / "plugins", venv=False)
    if approve:
        await store.approve(db, row.plugin_id, shown=approval_text(row.manifest))
    if enable:
        await store.set_enabled(db, row.plugin_id, True)
    await db.commit()
    return row


async def _no_sleep(_seconds: float) -> None:
    return None


def _config(row: PluginInstall, web: Web, **kw) -> HostConfig:
    """Pacing is real (a `RateLimiter`), its sleep is not: `pacing_delay` is
    tested on its own, so these runs do not wait the core's 2 s per request."""
    home = Path(row.source_dir)
    kw.setdefault("stall_seconds", 30)
    return HostConfig(python=sys.executable, pythonpath=[str(SDK), str(home / "src")],
                      data_dir=home.parent / "data", client=web.client(),
                      limiter=RateLimiter(2.0, sleep=_no_sleep), spawn=spawn_runner, send_signal=REAL_KILL, **kw)


async def _run(db, row, web, **kw):
    return await run_job(db, row.plugin_id, "refresh", trigger="cli", config=_config(row, web, **kw))


# --------------------------------------------------------------------------- #
# Install and approval
# --------------------------------------------------------------------------- #


async def test_an_update_whose_environment_fails_to_build_leaves_the_installed_version(
        db_session, tmp_path, monkeypatch):
    """An update builds its copy and venv beside the installed ones and
    swaps them in only once both are ready. Deleting the installed copy and
    venv first would let a failed pip leave a plugin whose code does not match
    its approval: refused on every run, with nothing said."""
    import subprocess as sp

    from tracker.plugins import install as installer

    def built(home, *, src=None, into=None):
        target = into or home / "venv"
        target.mkdir(parents=True, exist_ok=True)
        (target / "built").write_text("v1")
        return target / "bin" / "python"

    monkeypatch.setattr(installer, "build_venv", built)
    row, _ = await install(db_session, TEMPLATE, plugins_dir=tmp_path / "plugins")
    await db_session.commit()
    home = Path(row.source_dir).parent
    before = (row.code_sha, installer.code_sha(Path(row.source_dir)))

    changed = tmp_path / "changed"
    shutil.copytree(TEMPLATE, changed)
    (changed / "src" / "roleband_plugin_template" / "extra.py").write_text("X = 1\n")

    def broken(home, *, src=None, into=None):
        raise sp.CalledProcessError(1, ["pip", "install"])

    monkeypatch.setattr(installer, "build_venv", broken)
    with pytest.raises(installer.InstallRefused, match="unchanged"):
        await install(db_session, changed, plugins_dir=tmp_path / "plugins")
    await db_session.rollback()
    row = await db_session.get(PluginInstall, row.plugin_id, populate_existing=True)
    assert (row.code_sha, installer.code_sha(Path(row.source_dir))) == before
    assert (home / "venv" / "built").read_text() == "v1"
    assert not (home / "src.new").exists() and not (home / "venv.new").exists()


async def test_a_new_plugin_may_not_take_an_id_that_already_names_stored_data(db_session, tmp_path):
    """Rows stored under a provider value with no plugin installed
    under it would read as the new plugin's own,
    and its observations would collide with theirs. Installing under such an id
    is refused; an installed plugin's own update is not."""
    await seed_plugin_companies(db_session)
    db_session.add(CompanyCompLevel(company_slug="acme", family="software_engineering", level_label="L5",
                                    tc_median=300_000, provider="oldsource"))
    await db_session.commit()
    renamed = tmp_path / "renamed"
    shutil.copytree(TEMPLATE, renamed)
    manifest = renamed / "roleband-plugin.toml"
    manifest.write_text(manifest.read_text().replace('id = "plugin-template"', 'id = "oldsource"', 1))
    with pytest.raises(InstallRefused, match="already names data"):
        await install(db_session, renamed, plugins_dir=tmp_path / "plugins", venv=False)
    assert await db_session.get(PluginInstall, "oldsource") is None

    row = await _installed(db_session, tmp_path)
    db_session.add(CompanyCompLevel(company_slug="acme", family="software_engineering", level_label="L6",
                                    tc_median=400_000, provider=row.plugin_id))
    await db_session.commit()
    again, _ = await install(db_session, TEMPLATE, plugins_dir=tmp_path / "plugins", venv=False)
    assert again.plugin_id == row.plugin_id, "its own rows never block its own update"


async def test_install_pins_the_tree_and_an_update_lapses_approval(db_session, tmp_path):
    await seed_plugin_companies(db_session)
    row = await _installed(db_session, tmp_path)
    assert row.approved_fingerprint == row.fingerprint
    assert row.code_sha == code_sha(Path(row.source_dir))

    changed = tmp_path / "changed"
    shutil.copytree(TEMPLATE, changed)
    (changed / "src" / "roleband_plugin_template" / "parse.py").write_text(
        (TEMPLATE / "src" / "roleband_plugin_template" / "parse.py").read_text() + "\n# edited\n")
    updated, lapsed = await install(db_session, changed, plugins_dir=tmp_path / "plugins", venv=False)
    await db_session.commit()
    assert lapsed and updated.approved_fingerprint != updated.fingerprint
    with pytest.raises(NotRunnable, match="changed since it was approved"):
        await _run(db_session, updated, Web())


async def test_an_update_that_lapses_approval_unreads_its_claims_at_once(db_session, tmp_path):
    """Approval lapses on any change, and with it the plugin stops answering at
    once, on the install itself, not at some later re-approval: its ladder is no
    longer read, and ours answers again."""
    from tracker.plugins import lifecycle

    await seed_plugin_companies(db_session)
    row = await _installed(db_session, tmp_path)
    assert (await _run(db_session, row, Web())).outcome == "clean"
    assert {r.company_slug for r in await pay_level_rows(db_session)} == {"acme"}

    changed = tmp_path / "changed"
    shutil.copytree(TEMPLATE, changed)
    (changed / "src" / "roleband_plugin_template" / "parse.py").write_text(
        (TEMPLATE / "src" / "roleband_plugin_template" / "parse.py").read_text() + "\n# edited\n")
    _, lapsed, _ = await lifecycle.install(db_session, changed, plugins_dir=tmp_path / "plugins", venv=False)
    assert lapsed
    assert await pay_level_rows(db_session) == [], "ours holds no stored ladder for acme"
    # Identity was never the plugin's to answer, before or after.
    assert (await db_session.get(CompanyProfile, "acme", populate_existing=True)).website is None


async def test_bytecode_saved_beside_the_installed_copy_stops_the_plugin(db_session, tmp_path):
    """Python imports a cached module whose header matches its source in place
    of the source, so bytecode that appears under the approved copy is code
    nobody approved, though every source file still hashes as approved."""
    import importlib.util
    import py_compile

    await seed_plugin_companies(db_session)
    row = await _installed(db_session, tmp_path)
    parse = Path(row.source_dir) / "src" / "roleband_plugin_template" / "parse.py"
    cached = Path(importlib.util.cache_from_source(str(parse)))
    py_compile.compile(str(parse), cfile=str(cached), doraise=True)
    assert cached.is_file()
    web = Web()
    result = await _run(db_session, row, web)
    assert result.outcome == "error" and "changed on disk" in (result.message or "")
    assert web.requests == [], "nothing of the cached copy ran"


async def test_an_edit_to_the_installed_copy_stops_the_plugin_and_says_why(db_session, tmp_path):
    """The edited copy never runs. The refused attempt is recorded, so
    the user sees why and the scheduler waits `RETRY_AFTER`; unrecorded, the
    job would be due, and spawned, on every tick."""
    from tracker.plugins.registry import install_records
    from tracker.plugins.runtime import due_jobs, run_records

    await seed_plugin_companies(db_session)
    row = await _installed(db_session, tmp_path)
    parse = Path(row.source_dir) / "src" / "roleband_plugin_template" / "parse.py"
    parse.write_text(parse.read_text() + "\nFAMILIES['Anything'] = 'software_engineering'\n")
    web = Web()
    result = await _run(db_session, row, web)
    assert result.outcome == "error" and "changed on disk" in (result.message or "")
    assert web.requests == [], "nothing of the edited copy ran"
    [run] = (await db_session.execute(select(PluginRun))).scalars().all()
    assert run.outcome == "error" and "reinstall" in (run.message or "")
    assert due_jobs(await install_records(db_session), await run_records(db_session), run.ended_at) == []


@pytest.mark.parametrize(("approve", "enable"), [(False, True), (True, False)])
async def test_a_plugin_that_is_not_approved_and_enabled_never_starts(db_session, tmp_path, approve, enable):
    await seed_plugin_companies(db_session)
    row = await _installed(db_session, tmp_path, approve=approve, enable=enable)
    web = Web()
    with pytest.raises(NotRunnable):
        await _run(db_session, row, web)
    assert web.requests == []


async def test_a_manifest_the_core_no_longer_accepts_ends_an_error_run_saying_why(db_session, tmp_path):
    """An SDK bump or a tightened core rule can refuse a manifest that was
    accepted at install. The run is recorded, `error`, with the reason: without
    a row the scheduler would see no attempt and start it again every tick."""
    from tracker.plugins.registry import install_records
    from tracker.plugins.runtime import RETRY_AFTER, due_jobs, run_records

    await seed_plugin_companies(db_session)
    row = await _installed(db_session, tmp_path)
    plugin = dict(row.manifest["plugin"], sdk=">=2,<3")
    row.manifest = {**row.manifest, "plugin": plugin}
    await db_session.commit()
    web = Web()
    result = await _run(db_session, row, web)
    # An install whose range the shipped SDK has since left.
    assert result.outcome == "error" and "does not admit the SDK this core ships" in (result.message or "")
    assert web.requests == []
    run = await db_session.get(PluginRun, result.run_id)
    assert run.outcome == "error" and run.ended_at is not None
    now = run.started_at + RETRY_AFTER / 2
    assert due_jobs(await install_records(db_session), await run_records(db_session), now) == []


async def test_install_refuses_a_manifest_whose_range_the_shipped_sdk_is_not_in(db_session, tmp_path):
    """The range is the plugin's word on which SDK it runs on; one that leaves
    out the SDK this core ships is refused, with why, and nothing is installed."""
    later = tmp_path / "later"
    shutil.copytree(TEMPLATE, later)
    manifest = later / "roleband-plugin.toml"
    text = manifest.read_text()
    assert 'sdk = ">=1,<2"' in text  # control: the template's own range
    manifest.write_text(text.replace('sdk = ">=1,<2"', 'sdk = ">=2,<3"'))
    with pytest.raises(InstallRefused, match="does not admit the SDK this core ships"):
        await install(db_session, later, plugins_dir=tmp_path / "plugins", venv=False)
    assert (await db_session.execute(select(PluginInstall.plugin_id))).scalars().all() == []


async def test_the_host_runs_the_approved_copy_ahead_of_the_venv_s(db_session, tmp_path):
    """`code_sha` hashes `<home>/src` and the host re-checks it before every run,
    so that copy must be what the runner imports: it goes on the path ahead of
    the venv's site-packages (where pip put a copy of its own at install)."""
    from tracker.plugins.host import installed_config

    await seed_plugin_companies(db_session)
    row = await _installed(db_session, tmp_path)
    config = installed_config(row)
    home = Path(row.source_dir).parent
    assert config.python == str(home / "venv" / "bin" / "python")
    assert config.pythonpath == [str(SDK), str(Path(row.source_dir) / "src")]
    assert config.data_dir == home / "data"

    dev = installed_config(row, python=sys.executable)
    dev.client, dev.spawn, dev.limiter = Web().client(), spawn_runner, RateLimiter(2.0, sleep=_no_sleep)
    result = await run_job(db_session, row.plugin_id, "refresh", trigger="cli", config=dev)
    assert result.outcome == "clean", (result.message, result.stderr)


async def test_code_a_plugin_saves_in_its_data_directory_never_runs(db_session, tmp_path):
    """The data directory is the plugin's to write, so nothing there may
    be imported. A planted SDK runner and a planted copy of the plugin package
    each leave a mark if they run; neither may, and the approved copy runs."""
    await seed_plugin_companies(db_session)
    row = await _installed(db_session, tmp_path)
    data = Path(row.source_dir).parent / "data"
    marks = data / "marks"
    for package, module in (("roleband_plugin_sdk", "runner"), ("roleband_plugin_template", "__init__")):
        (data / package).mkdir(parents=True)
        (data / package / "__init__.py").write_text("")
        (data / package / f"{module}.py").write_text(
            f"import pathlib\npathlib.Path({str(marks)!r}).mkdir(exist_ok=True)\n"
            f"pathlib.Path({str(marks)!r}, {package!r}).write_text('ran')\nraise SystemExit(0)\n")

    result = await _run(db_session, row, Web())

    assert result.outcome == "clean", (result.message, result.stderr)
    assert not marks.exists() or sorted(p.name for p in marks.iterdir()) == []


async def test_the_runner_is_isolated_and_starts_where_the_plugin_cannot_write(db_session, tmp_path):
    """Isolated mode (no current directory, user site-packages or PYTHON*
    variables on the path) and a working directory outside every plugin folder."""
    await seed_plugin_companies(db_session)
    probe = tmp_path / "probe"
    shutil.copytree(TEMPLATE, probe)
    (probe / "src" / "roleband_plugin_template" / "__init__.py").write_text(
        "import os, sys\nfrom roleband_plugin_sdk import Plugin\nplugin = Plugin()\n\n"
        "@plugin.job('refresh')\ndef refresh(ctx):\n"
        "    ctx.log(f'isolated={sys.flags.isolated} cwd={os.getcwd()} path0={sys.path[0]}')\n")
    row = await _installed(db_session, tmp_path, source=probe)
    import logging

    logged: list[str] = []

    class Grab(logging.Handler):
        def emit(self, record):
            logged.append(record.getMessage())

    handler = Grab()
    logging.getLogger("tracker.plugins.host").addHandler(handler)
    logging.getLogger("tracker.plugins.host").setLevel(logging.INFO)
    try:
        result = await _run(db_session, row, Web())
    finally:
        logging.getLogger("tracker.plugins.host").removeHandler(handler)
    assert result.outcome == "clean", (result.message, result.stderr)
    said = next(m for m in logged if "isolated=" in m)
    assert "isolated=1" in said
    cwd = said.split("cwd=", 1)[1].split(" ", 1)[0]
    home = str(Path(row.source_dir).parent)
    assert not cwd.startswith(home) and not os.access(cwd, os.W_OK)
    assert said.split("path0=", 1)[1] == str(SDK), "the SDK this core ships leads the path, never ''"


async def test_a_lock_is_what_the_venv_installs_and_a_lock_pip_cannot_read_is_refused(db_session, tmp_path,
                                                                                     monkeypatch):
    """The approval covers the lock file, so its pins (with hashes) are what the
    venv gets; a lock pip cannot install is refused rather than ignored. The
    build sees none of our environment."""
    from tracker.plugins.install import ROBOTS_DIR, SDK_DIR, build_env, pip_steps

    locked = tmp_path / "locked"
    shutil.copytree(TEMPLATE, locked)
    (locked / "requirements.lock").write_text("pydantic==2.9.2 --hash=sha256:" + "0" * 64 + "\n")
    python = tmp_path / "venv" / "bin" / "python"
    steps = pip_steps(python, locked)
    assert steps[0][-3:] == ["--require-hashes", "-r", str(locked / "requirements.lock")]
    # The matcher is named with the SDK and the plugin: it is on no index, so
    # the SDK's dependency on it is satisfied from this checkout.
    assert steps[1][-4:] == ["--no-deps", str(ROBOTS_DIR), str(SDK_DIR), str(locked)]
    assert "-c" in pip_steps(python, TEMPLATE)[0], "unlocked: the core's constraints"

    monkeypatch.setenv("ROLEBAND_DATABASE_URL", "postgresql://secret@db/roleband")
    assert "ROLEBAND_DATABASE_URL" not in build_env()

    uv = tmp_path / "uv"
    shutil.copytree(TEMPLATE, uv)
    (uv / "uv.lock").write_text("version = 1\n")
    with pytest.raises(InstallRefused, match="pip installs only a requirements.lock"):
        await install(db_session, uv, plugins_dir=tmp_path / "plugins", venv=False)


async def test_install_refuses_a_plugin_that_opens_its_own_connection(db_session, tmp_path):
    bad = tmp_path / "bad"
    shutil.copytree(TEMPLATE, bad)
    (bad / "src" / "roleband_plugin_template" / "fetch.py").write_text("import httpx\n")
    with pytest.raises(InstallRefused, match="imports httpx"):
        await install(db_session, bad, plugins_dir=tmp_path / "plugins", venv=False)


# --------------------------------------------------------------------------- #
# A clean run
# --------------------------------------------------------------------------- #


async def test_a_clean_run_writes_stamped_banded_rows_and_only_then_is_read(db_session, tmp_path):
    await seed_plugin_companies(db_session)
    row = await _installed(db_session, tmp_path)
    web = Web()
    before = await pay_level_rows(db_session)

    result = await _run(db_session, row, web)

    assert result.outcome == "clean", (result.message, result.stderr)
    assert result.published == {"pay.levels": 3, "company.facts": 1}  # headcount: the one fact a plugin answers
    levels = await plugin_levels(db_session)
    assert [(r.level_label, r.tc_median, r.bonus_amount, r.family, r.provider) for r in levels] == [
        ("E3", 180000, 10000, "software_engineering", "plugin-template"),
        ("E4", 240000, None, "software_engineering", "plugin-template"),
        ("E5", 330000, None, "software_engineering", "plugin-template"),
    ]
    # Stored as the plugin sent them; our atlas bands them when read.
    assert {(r.band, r.band_source) for r in levels} == {(None, None)}
    assert sorted(r.band for r in await pay_level_rows(db_session)) == sorted(
        rung_band("acme", r.level_label)[0] for r in levels)
    assert levels[0].base_pct == pytest.approx(150000 / 180000) and levels[1].base_pct is None
    assert web.requests[0] == "https://data.example.com/robots.txt"
    assert web.user_agents == {"RoleBand-test/1"}, "the host's identity, never the plugin's"
    run = await db_session.get(PluginRun, result.run_id)
    assert (run.outcome, run.progress_done, run.progress_total) == ("clean", 2, 2)
    profile = await db_session.get(CompanyProfile, "acme")
    await db_session.refresh(profile)
    # Identity is ours: a plugin cannot even claim it.
    assert profile.website is None and "website" not in (profile.field_meta or {})
    assert before == [], "before its first clean run the plugin's rows reach no reader"
    assert {(r.company_slug, r.level_label) for r in await pay_level_rows(db_session)} >= {("acme", "E3")}


ROBOTS_NO_GLOBEX = "User-agent: *\nDisallow: /v1/ladders/globex\n"


async def test_a_robots_disallowed_path_is_refused_and_never_fetched(db_session, tmp_path):
    await seed_plugin_companies(db_session)
    row = await _installed(db_session, tmp_path)
    web = Web(robots=ROBOTS_NO_GLOBEX)
    result = await _run(db_session, row, web)
    assert result.outcome == "partial", "the template passes over a refused company; a refusal is never clean"
    assert any("robots.txt on data.example.com disallows /v1/ladders/globex.json" in r for r in result.refusals)
    assert f"{BASE}/globex.json" not in web.requests


def _asking(urls: list[str]) -> str:
    """A probe plugin that GETs each of `urls` and logs which the host refused."""
    return (
        "from roleband_plugin_sdk import HostError, Plugin\nplugin = Plugin()\n\n"
        "@plugin.job('refresh')\ndef refresh(ctx):\n"
        f"    for url in {urls!r}:\n"
        "        try:\n            ctx.get(url)\n        except HostError:\n            pass\n"
    )


async def _probe(db_session, tmp_path, urls: list[str]) -> PluginInstall:
    probe = tmp_path / "probe"
    shutil.copytree(TEMPLATE, probe)
    (probe / "src" / "roleband_plugin_template" / "__init__.py").write_text(_asking(urls))
    return await _installed(db_session, tmp_path, source=probe)


async def test_a_robots_rule_on_the_query_string_is_honoured(db_session, tmp_path):
    """Robots rules match path AND query (`robots.path_allowed`); a host that
    checked the path alone would let `/list?page=2` through `/*?page=`."""
    await seed_plugin_companies(db_session)
    row = await _probe(db_session, tmp_path, ["https://data.example.com/list?page=2", "https://data.example.com/list"])
    web = Web(pages={"https://data.example.com/list": httpx.Response(200, text="ok")},
              robots="User-agent: *\nDisallow: /*?page=\n")
    result = await _run(db_session, row, web)
    assert "https://data.example.com/list?page=2" not in web.requests
    assert "https://data.example.com/list" in web.requests
    assert any("disallows /list?page=2" in r for r in result.refusals)


async def test_rules_written_for_roleband_by_name_are_the_ones_followed(db_session, tmp_path):
    """A group naming our agent is ours, not the `*` fallback; a host reading
    only `*` would read a site that refused RoleBand by name anyway."""
    await seed_plugin_companies(db_session)
    row = await _probe(db_session, tmp_path, ["https://data.example.com/private"])
    web = Web(robots="User-agent: *\nAllow: /\n\nUser-agent: RoleBand-test\nDisallow: /private\n")
    result = await _run(db_session, row, web)
    assert "https://data.example.com/private" not in web.requests
    assert any("disallows /private" in r for r in result.refusals)


async def test_a_plugin_the_user_allowed_reads_what_the_rules_disallow_until_they_change(db_session, tmp_path):
    """The user may allow a plugin past its sites'
    robots rules, for the files they saw; a site that changes its file is asked
    about again, and until then its disallowed pages are skipped."""
    import hashlib

    await seed_plugin_companies(db_session)
    row = await _installed(db_session, tmp_path)
    seen = hashlib.sha256(ROBOTS_NO_GLOBEX.encode()).hexdigest()
    row.robots_consent = {"data.example.com": seen}
    await db_session.commit()

    allowed = Web(robots=ROBOTS_NO_GLOBEX)
    result = await _run(db_session, row, allowed)
    assert f"{BASE}/globex.json" in allowed.requests and not result.refusals
    await db_session.refresh(row)
    assert row.robots_seen == {"data.example.com": seen}

    changed = ROBOTS_NO_GLOBEX + "Disallow: /v2/\n"
    again = Web(robots=changed)
    result = await _run(db_session, row, again)
    assert f"{BASE}/globex.json" not in again.requests
    assert any("changed its robots rules since you allowed" in r for r in result.refusals)
    await db_session.refresh(row)
    assert row.robots_seen == {"data.example.com": hashlib.sha256(changed.encode()).hexdigest()}


async def test_a_robots_file_that_redirects_is_followed_by_the_run_and_the_dialog_alike(db_session, tmp_path):
    """A site that moved its robots file answers 301. Read as the redirect's own
    body, the file states no rule, so the run and the approval dialog would both
    allow everything; followed, the target's rules hold in the run, and the
    dialog shows the very file the run read."""
    from tracker.plugins.robots import site_rules

    moved = "https://www.data.example.com/robots.txt"

    class Moved(Web):
        def handler(self, request):
            url = str(request.url)
            if url == "https://data.example.com/robots.txt":
                self.requests.append(url)
                return httpx.Response(301, headers={"location": moved}, text="Moved Permanently")
            if url == moved:
                self.requests.append(url)
                return httpx.Response(200, text=ROBOTS_NO_GLOBEX)
            return super().handler(request)

    await seed_plugin_companies(db_session)
    row = await _installed(db_session, tmp_path)
    web = Moved()
    result = await _run(db_session, row, web)
    assert web.requests[:2] == ["https://data.example.com/robots.txt", moved]
    assert f"{BASE}/globex.json" not in web.requests
    assert any("robots.txt on data.example.com disallows /v1/ladders/globex.json" in r for r in result.refusals)

    async with Moved().client() as client:
        [site] = await site_rules(["data.example.com"], client=client)
    assert (site["state"], site["disallow"]) == ("rules", ["/v1/ladders/globex"])
    await db_session.refresh(row)
    assert row.robots_seen == {"data.example.com": site["sha256"]}, "the dialog shows the file the run read"


async def test_a_refusal_holds_back_only_the_refused_company_not_the_rest_of_the_run(db_session, tmp_path):
    """`ctx.resume` passes over the refused company and reads the rest. The run
    is partial (the host counts the refusal), yet acme, read whole, is read at
    once: one company the host refused never holds back the others."""
    await seed_plugin_companies(db_session)
    row = await _installed(db_session, tmp_path)
    result = await _run(db_session, row, Web(robots=ROBOTS_NO_GLOBEX))
    assert result.outcome == "partial"
    assert [r.level_label for r in await plugin_levels(db_session)] == ["E3", "E4", "E5"]
    assert {r.company_slug for r in await pay_level_rows(db_session)} == {"acme"}
    coverage = (await db_session.execute(select(PluginCoverage.company_slug, PluginCoverage.complete_at)
                                         .where(PluginCoverage.slot == "pay.levels"))).all()
    assert [(c, at is not None) for c, at in coverage] == [("acme", True)]


async def test_a_declared_host_that_resolves_to_a_private_address_is_refused(db_session, tmp_path):
    """The public client refuses a destination that is not public (a declared
    host resolving to a LAN address, a DNS sinkhole). That is a refusal the
    plugin is told about, never the host failing."""
    from tracker.platform.safe_fetch import BlockedDestination

    await seed_plugin_companies(db_session)
    row = await _installed(db_session, tmp_path)

    class Sinkholed(Web):
        def handler(self, request):
            if str(request.url).endswith("/acme.json"):
                raise BlockedDestination("data.example.com resolved to 0.0.0.0")
            return super().handler(request)

    result = await _run(db_session, row, Sinkholed())
    assert any("not public" in r for r in result.refusals), (result.refusals, result.message)
    assert "the host failed" not in (result.message or "")


async def test_an_identity_other_than_identified_is_refused_without_consent(db_session, tmp_path):
    await seed_plugin_companies(db_session)
    stealthy = tmp_path / "stealthy"
    shutil.copytree(TEMPLATE, stealthy)
    manifest = stealthy / "roleband-plugin.toml"
    manifest.write_text(manifest.read_text().replace('identity = "identified"', 'identity = "tls_fingerprint"'))
    row = await _installed(db_session, tmp_path, source=stealthy)
    web = Web()
    result = await _run(db_session, row, web)
    assert result.outcome == "partial"
    assert any("needs the user's consent" in r for r in result.refusals)
    assert web.requests == []


async def test_a_company_read_whole_retires_what_it_dropped_even_when_the_run_is_cut(db_session, tmp_path):
    """The second run publishes acme's smaller ladder as complete, then its
    budget runs out before globex. acme was read whole, so E4 and E5 retire at
    that publish (never deleted); the run's end does not hold them."""
    await seed_plugin_companies(db_session)
    row = await _installed(db_session, tmp_path)
    assert (await _run(db_session, row, Web())).outcome == "clean"

    now = [0.0]
    smaller = json.loads(json.dumps(ACME))
    smaller["ladders"][0]["levels"] = smaller["ladders"][0]["levels"][:1]

    class SlowWeb(Web):
        def handler(self, request):
            response = super().handler(request)
            if str(request.url).endswith("/acme.json"):
                now[0] = 10_000.0  # the 600 s budget is spent once acme is read
            return response

    web = SlowWeb({f"{BASE}/acme.json": httpx.Response(200, json=smaller), f"{BASE}/globex.json": httpx.Response(404)})
    result = await _run(db_session, row, web, clock=lambda: now[0])
    assert result.outcome == "bounded"
    assert f"{BASE}/globex.json" not in web.requests
    assert result.retired == 2
    levels = {r.level_label: r.retired_at for r in await plugin_levels(db_session)}
    assert levels["E3"] is None and levels["E4"] is not None and levels["E5"] is not None


async def test_a_company_read_whole_is_read_at_once_not_after_the_pass(db_session, tmp_path):
    """The budget ends the run after acme: acme's ladder is read at once, globex,
    never read, is not covered (never ours in its place). The next run
    reads globex and it joins. Identity claims are stored and never read."""
    await seed_plugin_companies(db_session)
    row = await _installed(db_session, tmp_path)

    now = [0.0]

    class SlowWeb(Web):
        def handler(self, request):
            response = super().handler(request)
            if str(request.url).endswith("/acme.json"):
                now[0] = 10_000.0  # the budget is spent once acme is read
            return response

    first = await _run(db_session, row, SlowWeb(), clock=lambda: now[0])
    assert first.outcome == "bounded"
    assert (await db_session.get(CompanyProfile, "acme", populate_existing=True)).website is None
    assert {r.company_slug for r in await pay_level_rows(db_session)} == {"acme"}

    globex = json.loads(json.dumps(ACME))
    globex.update(company="globex", website="https://globex.example")
    web = Web({f"{BASE}/acme.json": httpx.Response(404), f"{BASE}/globex.json": httpx.Response(200, json=globex)})
    await _run(db_session, row, web)
    assert (await db_session.get(CompanyProfile, "globex", populate_existing=True)).website is None
    assert {r.company_slug for r in await pay_level_rows(db_session)} == {"acme", "globex"}


async def test_a_run_that_published_marks_where_the_estimates_go_as_it_closes(db_session, tmp_path):
    """The run's rows move the reference set; the target is recorded as the run
    closes, so the status says estimates are updating until a re-estimate
    applies them, never "settled" until the idle re-estimate. A run
    that published nothing marks nothing."""
    await seed_plugin_companies(db_session)
    row = await _installed(db_session, tmp_path)
    assert (await reestimate(db_session)).applied

    nothing = Web({f"{BASE}/acme.json": httpx.Response(404), f"{BASE}/globex.json": httpx.Response(404)})
    assert (await _run(db_session, row, nothing)).published == {}
    state = await db_session.get(ReferenceState, 1, populate_existing=True)
    assert state.target_fp is None

    result = await _run(db_session, row, Web())
    assert result.outcome == "clean" and result.published
    state = await db_session.get(ReferenceState, 1, populate_existing=True)
    current = (await reference_inputs(db_session)).fingerprint
    assert state.target_fp == current and state.applied_fp != current
    assert (await reestimate(db_session)).applied
    state = await db_session.get(ReferenceState, 1, populate_existing=True)
    assert (state.applied_fp, state.target_fp) == (current, None)


async def test_a_clean_complete_snapshot_retires_what_it_did_not_repeat(db_session, tmp_path):
    await seed_plugin_companies(db_session)
    row = await _installed(db_session, tmp_path)
    assert (await _run(db_session, row, Web())).outcome == "clean"

    smaller = json.loads(json.dumps(ACME))
    smaller["ladders"][0]["levels"] = smaller["ladders"][0]["levels"][:1]
    web = Web({f"{BASE}/acme.json": httpx.Response(200, json=smaller), f"{BASE}/globex.json": httpx.Response(404)})
    result = await _run(db_session, row, web)
    assert result.outcome == "clean" and result.retired == 2
    levels = {r.level_label: r.retired_at for r in await plugin_levels(db_session)}
    assert levels["E3"] is None and levels["E4"] is not None and levels["E5"] is not None, (
        "retired, never deleted"
    )


CHUNKED = """from roleband_plugin_sdk import Plugin
plugin = Plugin()


def rung(label):
    return {'family': 'software_engineering', 'label': label, 'tc': 200000, 'currency': 'USD', 'country': 'US',
            'as_of': '2026-09-30'}


@plugin.job('refresh')
def refresh(ctx):
    ctx.publish('pay.levels', company='acme', rows=[rung('E3'), rung('E4')], complete=False)
    ctx.publish('pay.levels', company='acme', rows=[rung('E5')], complete=True)
    ctx.publish('pay.levels', company='globex', rows=[rung('E3')], complete=False)
"""


async def test_a_snapshot_sent_in_chunks_is_read_whole_at_its_last_chunk(db_session, tmp_path):
    """acme's ladder arrives in two publishes, `complete=False` then
    `complete=True`: the last closes the snapshot over both, so acme is read,
    the rungs of both chunks stay live, and only the rung neither chunk sent
    retires. globex, sent only incomplete, is not read and retires nothing."""
    from roleband_plugin_sdk import PayLevel

    from tracker.plugins import writer

    await seed_plugin_companies(db_session)
    probe = tmp_path / "chunked"
    shutil.copytree(TEMPLATE, probe)
    (probe / "src" / "roleband_plugin_template" / "__init__.py").write_text(CHUNKED)
    row = await _installed(db_session, tmp_path, source=probe)
    stale = PayLevel.model_validate({"family": "software_engineering", "label": "E6", "tc": 400000,
                                     "currency": "USD", "country": "US", "as_of": "2026-06-30"}).model_dump()
    for company in ("acme", "globex"):
        await writer.write_batch(db_session, row.plugin_id, "pay.levels", company, [stale])
    await db_session.commit()

    result = await _run(db_session, row, Web())

    assert result.outcome == "clean", (result.message, result.stderr)
    assert result.retired == 1
    live = {(r.company_slug, r.level_label) for r in await plugin_levels(db_session) if r.retired_at is None}
    assert live == {("acme", "E3"), ("acme", "E4"), ("acme", "E5"), ("globex", "E3"), ("globex", "E6")}
    coverage = dict((await db_session.execute(
        select(PluginCoverage.company_slug, PluginCoverage.complete_at).where(PluginCoverage.slot == "pay.levels")
    )).all())
    assert coverage["acme"] is not None and coverage["globex"] is None
    assert {(r.company_slug, r.level_label) for r in await pay_level_rows(db_session)} == {
        ("acme", "E3"), ("acme", "E4"), ("acme", "E5")}


async def test_the_plugin_environment_carries_nothing_of_ours(db_session, tmp_path, monkeypatch):
    """A probe plugin logs its environment's keys; none may be ours."""
    await seed_plugin_companies(db_session)
    probe = tmp_path / "probe"
    shutil.copytree(TEMPLATE, probe)
    (probe / "src" / "roleband_plugin_template" / "__init__.py").write_text(
        "import os\nfrom roleband_plugin_sdk import Plugin\nplugin = Plugin()\n\n"
        "@plugin.job('refresh')\ndef refresh(ctx):\n    ctx.log(','.join(sorted(os.environ)))\n")
    monkeypatch.setenv("ROLEBAND_DATABASE_URL", "postgresql://secret@db/roleband")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-secret")
    row = await _installed(db_session, tmp_path, source=probe)
    logged = []
    import logging

    class Grab(logging.Handler):
        def emit(self, record):
            logged.append(record.getMessage())

    handler = Grab()
    logging.getLogger("tracker.plugins.host").addHandler(handler)
    logging.getLogger("tracker.plugins.host").setLevel(logging.INFO)
    try:
        result = await _run(db_session, row, Web())
    finally:
        logging.getLogger("tracker.plugins.host").removeHandler(handler)
    assert result.outcome == "partial" or result.outcome == "clean"
    keys = next(m for m in logged if m.startswith("plugin:plugin-template ")).split(" ", 1)[1].split(",")
    assert "ROLEBAND_DATABASE_URL" not in keys and "ANTHROPIC_API_KEY" not in keys
    assert set(keys) <= {"PATH", "HOME", "LANG", "LC_ALL", "TMPDIR",
                         "__CF_USER_TEXT_ENCODING", "LC_CTYPE"}


async def test_a_plugin_is_paced_at_its_own_delay_never_faster_than_the_core():
    from roleband_plugin_sdk.manifest import load_manifest

    manifest = load_manifest(TEMPLATE)  # declares 1.0 s
    assert pacing_delay(manifest, 2.0) == 2.0
    assert pacing_delay(manifest, 0.5) == 1.0


async def test_a_failure_on_the_host_s_side_ends_the_run_error_and_closes_it(db_session, tmp_path, monkeypatch):
    """A store that fails mid-publish is the host's failure, not the plugin's:
    the run still closes, `error`, saying why, and nothing of the failed batch
    is kept. Left open, the row would read `running` until a later tick found
    the process gone, and the reason would be lost."""
    await seed_plugin_companies(db_session)
    row = await _installed(db_session, tmp_path)

    async def failing_write(*_args, **_kwargs):
        raise RuntimeError("the store went away")

    monkeypatch.setattr("tracker.plugins.host.writer.write_batch", failing_write)
    result = await _run(db_session, row, Web())
    assert result.outcome == "error"
    assert "RuntimeError: the store went away" in (result.message or "")
    run = await db_session.get(PluginRun, result.run_id, populate_existing=True)
    assert run.outcome == "error" and run.ended_at is not None
    assert await plugin_levels(db_session) == []


async def test_a_second_host_for_a_running_plugin_stops_before_it_records_anything(db_session, tmp_path):
    """Start, Sync and the scheduler each spawn a host; the `running` row only
    appears once one has started. A second host finds the run lock held."""
    from tracker.platform.locks import run_lock
    from tracker.plugins.host import RUN_LOCK

    await seed_plugin_companies(db_session)
    row = await _installed(db_session, tmp_path)
    config = _config(row, Web())
    with run_lock(config.data_dir / RUN_LOCK), pytest.raises(NotRunnable, match="already running"):
        await run_job(db_session, row.plugin_id, "refresh", trigger="schedule", config=config)
    assert (await db_session.execute(select(PluginRun))).scalars().all() == []
    assert (await _run(db_session, row, Web())).outcome == "clean", "the lock is released with its holder"


async def test_a_stop_ends_a_busy_plugin_at_once_not_at_its_next_message(db_session, tmp_path):
    """Stop (or disable) while the plugin works between calls: the host ends the
    run `stopped` now, and ends the runner, instead of waiting for the plugin's
    next message or the stall timeout."""
    import time

    await seed_plugin_companies(db_session)
    busy = tmp_path / "busy"
    shutil.copytree(TEMPLATE, busy)
    (busy / "src" / "roleband_plugin_template" / "__init__.py").write_text(
        "import time\nfrom roleband_plugin_sdk import Plugin\nplugin = Plugin()\n\n"
        "@plugin.job('refresh')\ndef refresh(ctx):\n    time.sleep(30)\n    ctx.log('woke')\n")
    row = await _installed(db_session, tmp_path, source=busy)
    stop = asyncio.Event()
    asyncio.get_running_loop().call_later(0.5, stop.set)
    started = time.monotonic()
    result = await run_job(db_session, row.plugin_id, "refresh", trigger="cli",
                           config=_config(row, Web(), stall_seconds=20), stop=stop)
    assert result.outcome == "stopped"
    assert time.monotonic() - started < 5


async def test_a_pass_that_stops_before_its_budget_ends_clean_and_is_continued(db_session, tmp_path):
    """The host tells the plugin its budget (`start.budget_seconds`; without it
    `time_left` is None and `resume` never stops early); a job that stops at a
    unit boundary saying `more` ends clean, and the run is recorded as a pass in
    progress that the schedule continues soon."""
    from tracker.plugins.registry import install_records
    from tracker.plugins.runtime import due_jobs, run_records

    await seed_plugin_companies(db_session)
    chunked = tmp_path / "chunked"
    shutil.copytree(TEMPLATE, chunked)
    (chunked / "src" / "roleband_plugin_template" / "__init__.py").write_text(
        "from roleband_plugin_sdk import Plugin\nplugin = Plugin()\n\n"
        "@plugin.job('refresh')\ndef refresh(ctx):\n"
        "    ctx.resume('refresh', ctx.companies(), lambda c: None, key=lambda c: c.slug, margin=10_000)\n")
    row = await _installed(db_session, tmp_path, source=chunked)
    result = await _run(db_session, row, Web())
    assert (result.outcome, result.continues) == ("clean", True), (result.message, result.stderr)
    run = await db_session.get(PluginRun, result.run_id, populate_existing=True)
    assert run.continues is True
    runs = await run_records(db_session)
    later = run.ended_at + timedelta(hours=1)
    assert [d.reason for d in due_jobs(await install_records(db_session), runs, later)] == ["continues"]


async def test_a_chunk_with_a_refused_request_ends_partial_and_is_still_continued(db_session, tmp_path):
    """A refusal makes the run `partial`, and the pass it is part of goes
    on 30 minutes later, never after the 6-hour retry."""
    from tracker.plugins.registry import install_records
    from tracker.plugins.runtime import due_jobs, run_records

    await seed_plugin_companies(db_session)
    chunked = tmp_path / "chunked"
    shutil.copytree(TEMPLATE, chunked)
    (chunked / "src" / "roleband_plugin_template" / "__init__.py").write_text(
        "from roleband_plugin_sdk import HostError, Plugin\nplugin = Plugin()\n\n"
        "@plugin.job('refresh')\ndef refresh(ctx):\n"
        f"    try:\n        ctx.get({BASE + '/globex.json'!r})\n    except HostError:\n        pass\n"
        "    ctx.resume('refresh', ctx.companies(), lambda c: None, key=lambda c: c.slug, margin=10_000)\n")
    row = await _installed(db_session, tmp_path, source=chunked)
    result = await _run(db_session, row, Web(robots=ROBOTS_NO_GLOBEX))
    assert (result.outcome, result.continues) == ("partial", True), (result.message, result.stderr)
    run = await db_session.get(PluginRun, result.run_id, populate_existing=True)
    assert run.continues is True and run.refusals, "the refusal stays on the run"
    later = run.ended_at + timedelta(hours=1)
    assert [d.reason for d in due_jobs(await install_records(db_session), await run_records(db_session), later)] == [
        "continues"]


async def test_a_stop_ends_the_run_stopped_and_serves_nothing_after(db_session, tmp_path):
    await seed_plugin_companies(db_session)
    row = await _installed(db_session, tmp_path)
    stop = asyncio.Event()
    stop.set()  # a disable that lands as the run starts
    web = Web()
    result = await run_job(db_session, row.plugin_id, "refresh", trigger="cli", config=_config(row, web), stop=stop)
    assert result.outcome == "stopped" and result.retired == 0
    assert web.requests == [] and await plugin_levels(db_session) == []


async def test_an_active_plugin_s_taxonomy_keyed_ladder_reaches_the_estimate_and_the_profile(
    db_session, api_client, tmp_path
):
    """A plugin keys its rows by our taxonomy family (`software_engineering`); the
    estimate and the profile read ladders by the ladder they stand for, so the
    plugin's rows answer the same keys the core's do (`Providers.family_of`)."""
    from tracker.analytics.comp_package import pay_level_index
    from tracker.taxonomy.comp_families import REFERENCE_FAMILY

    await seed_plugin_companies(db_session)
    row = await _installed(db_session, tmp_path)
    assert (await _run(db_session, row, Web())).outcome == "clean"

    index = pay_level_index(await pay_level_rows(db_session))
    acme = {key: hit.tc_median for key, hit in index.items() if key[0] == "acme"}
    assert acme and {key[1] for key in acme} == {REFERENCE_FAMILY}
    body = (await api_client.get("/api/company-profiles/acme")).json()
    assert sorted(r["level_label"] for r in body["comp_levels"]) == ["E3", "E4", "E5"]


async def test_a_plugin_rung_the_atlas_cannot_place_is_read_on_its_words_band(db_session, tmp_path):
    """`acme` has no ladder in the atlas, so its rungs are banded from their
    words when read, and their stored rows are never re-banded."""
    await seed_plugin_companies(db_session)
    row = await _installed(db_session, tmp_path)
    assert (await _run(db_session, row, Web())).outcome == "clean"
    read = await package_rows(db_session, await reader_providers(db_session), "acme", "US")
    assert read and {r.band_source for r in read} == {"words"}
    assert {r.band_source for r in await plugin_levels(db_session)} == {None}


# --------------------------------------------------------------------------- #
# Numbers a plugin reports (ctx.report)
# --------------------------------------------------------------------------- #

REPORTER = """from roleband_plugin_sdk import HostError, Plugin
plugin = Plugin()

@plugin.job('refresh')
def refresh(ctx):
    n = (ctx.state.get('round') or 0) + 1
    ctx.state.set('round', n)
    if n == 1:
        ctx.report('absent', 900, 'followed companies the site does not list')
        ctx.report('stale', 3, 'ladders older than a year')
    elif n == 2:
        ctx.report('absent', 912, 'followed companies the site does not list')
        ctx.report('stale', None, 'ladders older than a year')
    else:
        for i in range(10):
            try:
                ctx.report(f'k{i}', i, 'numbers')
            except HostError as exc:
                ctx.log(f'refused {i}: {exc}')
"""


async def _reporter(db, tmp_path) -> PluginInstall:
    reporter = tmp_path / "reporter"
    shutil.copytree(TEMPLATE, reporter)
    (reporter / "src" / "roleband_plugin_template" / "__init__.py").write_text(REPORTER)
    return await _installed(db, tmp_path, source=reporter)


async def _report_rows(db, plugin_id="plugin-template"):
    rows = (await db.execute(select(PluginReport).where(PluginReport.plugin_id == plugin_id)
                             .order_by(PluginReport.key))).scalars().all()
    return [(r.key, r.value, r.label) for r in rows]


async def test_a_reported_number_is_kept_with_its_words_updated_and_withdrawn(db_session, tmp_path):
    from tracker.plugins.status import plugin_list

    await seed_plugin_companies(db_session)
    row = await _reporter(db_session, tmp_path)
    first = await _run(db_session, row, Web())
    assert first.outcome == "clean", first.message
    assert await _report_rows(db_session) == [
        ("absent", 900, "followed companies the site does not list"), ("stale", 3, "ladders older than a year"),
    ]
    second = await _run(db_session, row, Web())
    assert second.outcome == "clean", second.message
    assert await _report_rows(db_session) == [("absent", 912, "followed companies the site does not list")]
    (view,) = await plugin_list(db_session)
    assert [(r["key"], r["value"], r["label"]) for r in view["reports"]] == [
        ("absent", 912, "followed companies the site does not list")]
    assert view["reports"][0]["reported_at"] is not None


async def test_a_plugin_reports_at_most_eight_numbers(db_session, tmp_path):
    await seed_plugin_companies(db_session)
    row = await _reporter(db_session, tmp_path)
    await store.state_set(db_session, row.plugin_id, "round", 2)  # the next run is round 3
    await store.report_set(db_session, row.plugin_id, "absent", None, "x")
    await db_session.commit()
    await _run(db_session, row, Web())
    assert [key for key, _, _ in await _report_rows(db_session)] == [f"k{i}" for i in range(8)]


async def test_reports_go_with_the_install_and_never_with_another_plugin_s(db_session, tmp_path):
    await seed_plugin_companies(db_session)
    row = await _reporter(db_session, tmp_path)
    await _run(db_session, row, Web())
    assert len(await _report_rows(db_session)) == 2  # control: there is something to lose
    assert await _report_rows(db_session, "someone-else") == []
    await db_session.delete(await db_session.get(PluginInstall, row.plugin_id))
    await db_session.commit()
    assert await _report_rows(db_session) == []


# --------------------------------------------------------------------------- #
# A plugin's own words: its description and each run's summary
# --------------------------------------------------------------------------- #

SUMMARIZER = """from roleband_plugin_sdk import Plugin
plugin = Plugin()

@plugin.job('refresh')
def refresh(ctx):
    ctx.summary('Read pay for 1 of 2 companies')
    ctx.summary('Read pay for 2 of 2 companies')
    if ctx.state.get('fail'):
        raise RuntimeError('the site changed its page')
"""


SILENT = """from roleband_plugin_sdk import Plugin
plugin = Plugin()

@plugin.job('refresh')
def refresh(ctx):
    ctx.progress(0, 0)
"""


async def _summarizer(db, tmp_path) -> PluginInstall:
    summarizer = tmp_path / "summarizer"
    shutil.copytree(TEMPLATE, summarizer)
    (summarizer / "src" / "roleband_plugin_template" / "__init__.py").write_text(SUMMARIZER)
    manifest = summarizer / "roleband-plugin.toml"
    text = manifest.read_text()
    assert 'description = "Pay ladders and headcount from data.example.com"' in text  # the template says it
    return await _installed(db, tmp_path, source=summarizer)


async def test_a_run_keeps_the_plugin_s_latest_summary_and_the_view_its_description(db_session, tmp_path):
    from tracker.plugins.status import plugin_list

    await seed_plugin_companies(db_session)
    row = await _summarizer(db_session, tmp_path)
    result = await _run(db_session, row, Web())
    assert result.outcome == "clean", result.message
    (view,) = await plugin_list(db_session)
    assert view["description"] == "Pay ladders and headcount from data.example.com"
    assert view["last_run"]["summary"] == "Read pay for 2 of 2 companies"


async def test_a_run_that_fails_after_its_summary_still_keeps_it(db_session, tmp_path):
    from tracker.plugins.status import plugin_list

    await seed_plugin_companies(db_session)
    row = await _summarizer(db_session, tmp_path)
    await store.state_set(db_session, row.plugin_id, "fail", True)
    await db_session.commit()
    result = await _run(db_session, row, Web())
    assert result.outcome == "error"
    (view,) = await plugin_list(db_session)
    assert view["last_run"]["summary"] == "Read pay for 2 of 2 companies"
    assert "RuntimeError" in view["last_run"]["message"]


async def test_a_plugin_that_says_nothing_of_itself_has_no_description_or_summary(db_session, tmp_path):
    from tracker.plugins.status import plugin_list

    await seed_plugin_companies(db_session)
    silent = tmp_path / "silent"
    shutil.copytree(TEMPLATE, silent)
    (silent / "src" / "roleband_plugin_template" / "__init__.py").write_text(SILENT)
    manifest = silent / "roleband-plugin.toml"
    manifest.write_text("".join(line for line in manifest.read_text().splitlines(keepends=True)
                                if not line.startswith("description = ")))
    row = await _installed(db_session, tmp_path, source=silent)
    assert (await _run(db_session, row, Web())).outcome == "clean"
    (view,) = await plugin_list(db_session)
    assert view["description"] is None and view["last_run"]["summary"] is None


# --------------------------------------------------------------------------- #
# The same job under FakeHost: a plugin's own tests predict this host
# --------------------------------------------------------------------------- #

PARITY = """from roleband_plugin_sdk import HostError, Plugin
plugin = Plugin()

LEVEL = {'family': 'software_engineering', 'label': 'L5', 'as_of': '2026-09-30'}
BENEFIT = {'name': '401k', 'category': 'Financial'}


def obs(key, total):
    return {'source_level': 'L5', 'total': total, 'base': total, 'equity': 0, 'bonus': 0, 'currency': 'USD',
            'snapshot_date': '2026-09-01', 'dedup_key': key}


PUBLISHES = [
    ('pay.levels', 'acme', [
        {**LEVEL, 'tc': 300000, 'currency': 'USD', 'country': 'US'},
        {**LEVEL, 'tc': 310000, 'currency': 'USD', 'country': 'US'},
        {**LEVEL, 'tc': 150000, 'currency': 'GBP', 'country': 'GB'},
        {**LEVEL, 'tc': 280000, 'currency': 'USD'},
    ]),
    ('pay.levels', 'acme', [{**LEVEL, 'family': 'rocket_science', 'tc': 1, 'currency': 'USD'}]),
    ('pay.levels', 'initech', [{**LEVEL, 'tc': 1, 'currency': 'USD'}]),
    ('company.benefits', 'acme', [{**BENEFIT, 'value_text': '4%'}, {**BENEFIT, 'value_text': '6%'}]),
    ('company.benefits', 'globex', [{**BENEFIT, 'value_text': '3%'}]),
    ('pay.observations', 'acme', [obs('k1', 200000), obs('k1', 999999)]),
    ('pay.observations', 'globex', [obs('k1', 111111), obs('k2', 222222)]),
]


@plugin.job('refresh')
def refresh(ctx):
    for slot, company, rows in PUBLISHES:
        try:
            ctx.publish(slot, company=company, rows=rows)
        except HostError as exc:
            ctx.log(f'refused {slot} for {company}: {exc}')
    for key in ('a', 'b', 'c', 'a'):
        try:
            ctx.state.set(key, key)
        except HostError as exc:
            ctx.log(f'refused state {key}: {exc}')
    for key in ('x', 'y'):
        try:
            ctx.report(key, 1, 'numbers')
        except HostError as exc:
            ctx.log(f'refused report {key}: {exc}')
"""

PARITY_SLOTS = """[[provides]]
slot = "pay.levels"

[[provides]]
slot = "pay.observations"

[[provides]]
slot = "company.benefits"

[[jobs]]
name = "refresh"
publishes = ["pay.levels", "pay.observations", "company.benefits"]
schedule = "manual"
budget_seconds = 600
"""


async def test_the_fake_host_predicts_what_this_host_stores_refuses_and_keeps(db_session, tmp_path, monkeypatch):
    """One job, both hosts: a rung in its own currency, rows that share the
    store's key (a snapshot keeps the latest, history the first, an
    observation's key spans companies), a made-up family, an unknown company,
    and one past each cap (lowered, so the test does not write ten thousand
    keys). What each host stores, refuses and keeps must be the same, and
    must be what the store's own keys say."""
    from roleband_plugin_sdk import protocol
    from roleband_plugin_sdk.testing import FakeHost

    monkeypatch.setattr(protocol, "MAX_STATE_KEYS", 2)
    monkeypatch.setattr(protocol, "MAX_REPORTS", 1)
    await seed_plugin_companies(db_session)
    source = tmp_path / "parity"
    shutil.copytree(TEMPLATE, source)
    entry = source / "src" / "roleband_plugin_template" / "__init__.py"
    entry.write_text(PARITY)
    manifest = source / "roleband-plugin.toml"
    manifest.write_text(manifest.read_text().split("[[provides]]", 1)[0] + PARITY_SLOTS)
    row = await _installed(db_session, tmp_path, source=source)

    real = await _run(db_session, row, Web())

    loader = importlib.util.spec_from_file_location("parity_plugin", entry)
    assert loader is not None and loader.loader is not None
    module = importlib.util.module_from_spec(loader)
    loader.loader.exec_module(module)
    fake = FakeHost(source, companies={"acme": "Acme Corp", "globex": "Globex"}).run("refresh", module.plugin)

    assert (real.outcome, sorted(real.refusals)) == (fake.outcome, sorted(fake.refusals))
    assert real.outcome == "partial"
    assert [r.split(":")[0] for r in sorted(real.refusals)] == ["invalid", "invalid", "invalid", "refused"]

    companies = ("acme", "globex")
    levels = {("acme", "US", "USD", 310000), ("acme", "GB", "GBP", 150000), ("acme", None, "USD", 280000)}
    assert {(r.company_slug, r.country, r.currency, r.tc_median) for r in await plugin_levels(db_session)} == levels
    assert {(c, r.country, r.currency, r.tc) for c in companies for r in fake.rows("pay.levels", c)} == levels

    benefits = {("acme", "401k", "6%"), ("globex", "401k", "3%")}
    stored = (await db_session.execute(select(CompanyBenefit).where(CompanyBenefit.provider == row.plugin_id))).scalars()
    assert {(b.company_slug, b.name, b.value_text) for b in stored} == benefits
    assert {(c, b.name, b.value_text) for c in companies for b in fake.rows("company.benefits", c)} == benefits

    observations = {("acme", "k1", 200000), ("globex", "k2", 222222)}
    stored = (await db_session.execute(
        select(ExternalCompObservation).where(ExternalCompObservation.provider == row.plugin_id))).scalars()
    assert {(o.company_slug, o.dedup_key, o.total_amount) for o in stored} == observations
    assert {(c, o.dedup_key, o.total) for c in companies for o in fake.rows("pay.observations", c)} == observations

    kept = (await db_session.execute(select(PluginState).where(PluginState.plugin_id == row.plugin_id))).scalars()
    assert {s.key: s.value for s in kept} == fake.state == {"a": "a", "b": "b"}
    assert await _report_rows(db_session) == [(k, v, label) for k, (v, label) in fake.reports.items()] == [
        ("x", 1, "numbers")]
