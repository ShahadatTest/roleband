"""A bundle is immutable code and resources, with all runtime state outside it."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def bundle(tmp_path):
    resources = tmp_path / "RoleBand Test.app" / "Contents" / "Resources"
    engine = resources / "engine"
    shutil.copytree(ROOT / "backend" / "tracker", engine / "tracker", ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copytree(ROOT / "backend" / "alembic", engine / "alembic", ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copy(ROOT / "backend" / "alembic.ini", engine)
    bootstrap = ROOT / "backend" / "packaged.py"
    if bootstrap.exists():
        shutil.copy(bootstrap, engine)
    (engine / "release.json").write_text(json.dumps({"version": "1.2.3"}))
    (engine / ".env").write_text("ROLEBAND_API_PORT=63452\nROLEBAND_NO_USAGE_STATS=1\n")
    wheels = resources / "plugin-wheels"
    wheels.mkdir()
    for name in ("roleband_plugin_sdk", "roleband_robots"):
        (wheels / f"{name}-0.1.0-py3-none-any.whl").write_bytes(b"wheel command fixture")
    dashboard = resources / "dashboard"
    dashboard.mkdir()
    (dashboard / "index.html").write_text("<html>packaged dashboard</html>")
    shutil.copy(ROOT / "dashboard" / "csp-policy.json", dashboard)
    shutil.copy(ROOT / "CHANGELOG.md", resources)
    for path in resources.rglob("*"):
        path.chmod(0o555 if path.is_dir() else 0o444)
    resources.chmod(0o555)
    try:
        yield resources
    finally:
        resources.chmod(0o755)
        for path in resources.rglob("*"):
            path.chmod(0o755 if path.is_dir() else 0o644)


def probe(resources: Path, tmp_path: Path, script: str) -> subprocess.CompletedProcess:
    home = tmp_path / "user home"
    home.mkdir(exist_ok=True)
    env = {key: value for key, value in os.environ.items() if not key.startswith("ROLEBAND_")}
    env.update({
        "HOME": str(home), "PYTHONPATH": str(resources / "engine"),
        "ROLEBAND_PACKAGED": "1", "ROLEBAND_PGDATA": str(tmp_path / "db"),
        "ROLEBAND_DATABASE_URL": "", "PYTHONDONTWRITEBYTECODE": "1",
        "ROLEBAND_SECRET_KEY_FILE": str(home / ".roleband" / "secret.key"),
    })
    return subprocess.run(
        [sys.executable, "-B", "-c", script], cwd=resources / "engine", env=env,
        capture_output=True, text=True, timeout=180,
    )


def test_read_only_bundle_keeps_runtime_files_outside_code(bundle, tmp_path):
    result = probe(bundle, tmp_path, """
from pathlib import Path
from tracker.platform.paths import DATA_DIR, PACING_DIR, DASHBOARD_DIST
from tracker.platform.locks import run_lock
from tracker.platform.secrets import seal, unseal, key_path
from tracker.semantic.provision import models_dir
from tracker.supervisor import logs, maintenance
from tracker.workflows.watchdog import STATE_FILE, ALERTS_LOG, BACKUPS_DIR
with run_lock(DATA_DIR / 'daily.lock'):
    pass
expected = Path.home() / '.roleband'
assert DATA_DIR == expected, DATA_DIR
assert PACING_DIR == expected / 'pacing'
assert models_dir() == expected / 'models'
assert STATE_FILE == expected / 'watchdog_state.json'
assert ALERTS_LOG == expected / 'alerts.log'
assert BACKUPS_DIR == expected / 'backups'
assert DASHBOARD_DIST.joinpath('index.html').read_text() == '<html>packaged dashboard</html>'
fd = logs.open_append(DATA_DIR / 'logs' / 'probe.log')
import os
os.write(fd, b'bundle probe')
os.close(fd)
maintenance.request(DATA_DIR, by='probe', drain=True)
assert unseal(seal('scratch-secret')) == 'scratch-secret'
assert key_path() == expected / 'secret.key'
""")
    assert result.returncode == 0, result.stderr
    assert not (bundle / "data").exists()


def test_packaged_version_comes_from_build_metadata_without_git(bundle, tmp_path):
    result = probe(bundle, tmp_path, """
import sys
def guard(event, args):
    if event == 'subprocess.Popen':
        raise AssertionError('packaged version must not invoke git')
sys.addaudithook(guard)
import tracker
from tracker.platform.version import code_version
assert tracker.__version__ == '1.2.3', tracker.__version__
assert code_version() == '1.2.3', code_version()
""")
    assert result.returncode == 0, result.stderr


def test_packaged_supervisor_uses_no_checkout_tools(bundle, tmp_path):
    result = probe(bundle, tmp_path, """
import asyncio
import sys
from types import SimpleNamespace
from tracker.platform.paths import REPO_ROOT, DATA_DIR
from tracker.supervisor import activation, gate
from tracker.supervisor.registry import JOBS
def guard(event, args):
    if event == 'subprocess.Popen':
        raise AssertionError(f'checkout tool invoked: {args[1]}')
sys.addaudithook(guard)
watcher = activation.Watcher(SimpleNamespace(repo_root=REPO_ROOT, data_dir=DATA_DIR))
assert asyncio.run(watcher.look(0)).action == activation.NOTHING
assert gate.read(REPO_ROOT).proven
gate.clear_residue(REPO_ROOT, sys.executable)
assert not {'preflight', 'dashboard_build'} & {job.name for job in JOBS}
backup = next(job for job in JOBS if job.name == 'backup')
assert backup.command == ('{python}', '-m', 'tracker.supervisor.entries', 'backup')
""")
    assert result.returncode == 0, result.stderr


def test_packaged_children_run_from_read_only_engine(bundle, tmp_path):
    result = probe(bundle, tmp_path, """
import asyncio
import os
import socket
import subprocess
import sys
import time
import httpx
from alembic import command
from alembic.config import Config
from tracker.platform.paths import REPO_ROOT, BACKEND_DIR, DATA_DIR
from tracker.platform.embedded_db import stop_server
from tracker.config import get_settings
from tracker.supervisor import runner
from tracker.supervisor.api import ApiService
from tracker.supervisor.registry import JOBS, JobSpec, OnRequest
from tracker.supervisor.plan import ALEMBIC_INI, code_heads
from tracker.supervisor.child import read_result
from tracker.db import job_store
from tracker.db.session import get_session_factory, get_engine
assert ALEMBIC_INI == BACKEND_DIR / 'alembic.ini'
assert code_heads()
job = JobSpec('probe', ('{python}', '-c',
    'from pathlib import Path; import tracker; '
    'assert Path.cwd().name == "engine"; assert tracker.__version__ == "1.2.3"'), OnRequest())
launched = runner.launch(job, 901, repo_root=REPO_ROOT, data_dir=DATA_DIR)
assert launched.process.wait(timeout=10) == 0
assert read_result(runner.result_path(DATA_DIR, 901))['exit_code'] == 0
config = Config(str(ALEMBIC_INI))
config.set_main_option('script_location', str(BACKEND_DIR / 'alembic'))
api = None
supervisor = None
try:
    command.upgrade(config, 'head')
    backup = next(job for job in JOBS if job.name == 'backup')
    backed_up = runner.launch(backup, 902, repo_root=REPO_ROOT, data_dir=DATA_DIR)
    assert backed_up.process.wait(timeout=15) == 0, backed_up.log_path.read_text()
    assert list((DATA_DIR / 'backups').glob('*.dump'))
    with socket.socket() as available:
        available.bind(('127.0.0.1', 0))
        port = available.getsockname()[1]
    api = ApiService(repo_root=REPO_ROOT, data_dir=DATA_DIR, host='127.0.0.1', port=port)
    async def exercise():
        deadline = time.monotonic() + 25
        async with httpx.AsyncClient(trust_env=False, timeout=5) as client:
            while time.monotonic() < deadline:
                await api.tend(time.monotonic())
                if api.state == 'running':
                    break
                await asyncio.sleep(0.05)
            assert api.state == 'running', api.log.read_text()
            root = await client.get(f'http://127.0.0.1:{port}/')
            assert root.status_code == 200 and 'packaged dashboard' in root.text
            assert 'script-src' in root.headers['content-security-policy']
            health = await client.get(f'http://127.0.0.1:{port}/api/status')
            assert health.status_code == 200, health.text
            assert health.json()['launcher']['version'] == '1.2.3'
    asyncio.run(exercise())
    asyncio.run(api.stop(grace_seconds=5))
    api = None
    async def seed_recent_runs():
        async with get_session_factory()() as session:
            for job in JOBS:
                run = await job_store.open_run(session, job.name, job.name, trigger='schedule')
                await job_store.finish_run(session, run.id, state=job_store.EXITED, exit_code=0, result={'kind': 'ran'})
            await session.commit()
        await get_engine().dispose()
    asyncio.run(seed_recent_runs())
    env = {**os.environ, 'ROLEBAND_API_PORT': str(port)}
    supervisor = subprocess.Popen(
        [sys.executable, '-I', str(BACKEND_DIR / 'packaged.py'), 'supervisor', 'run', '--dry-run-network'],
        cwd=DATA_DIR, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    async def verify_supervisor():
        # The supervisor starts its own API from cold source (-B, no bytecode), which
        # on a loaded CI runner takes several times the local seconds.
        deadline = time.monotonic() + 60
        async with httpx.AsyncClient(trust_env=False, timeout=3) as client:
            while time.monotonic() < deadline:
                assert supervisor.poll() is None, (DATA_DIR / 'logs' / 'supervisor.log').read_text()
                try:
                    status = await client.get(f'http://127.0.0.1:{port}/api/status')
                    if status.status_code == 200 and status.json()['supervisor']['state'] == 'running':
                        assert status.json()['supervisor']['reason'] is None
                        return
                except httpx.HTTPError:
                    pass
                await asyncio.sleep(0.05)
        raise AssertionError((DATA_DIR / 'logs' / 'supervisor.log').read_text())
    asyncio.run(verify_supervisor())
finally:
    if supervisor is not None:
        supervisor.terminate()
        try:
            supervisor.wait(timeout=15)
        except subprocess.TimeoutExpired:
            supervisor.kill()
            supervisor.wait(timeout=5)
    if api is not None:
        asyncio.run(api.stop(grace_seconds=5))
    stop_server(get_settings().embedded_pgdata())
""")
    assert result.returncode == 0, result.stderr + result.stdout
    assert not (bundle / "data").exists()


def test_packaged_configuration_and_integration_commands_need_no_checkout(bundle, tmp_path):
    result = probe(bundle, tmp_path, """
import sys
from pathlib import Path
from tracker.config import get_settings
from tracker.platform.paths import REPO_ROOT, BACKEND_DIR
from tracker.plugins.install import constraints_file, pip_steps
from tracker.plugins import install
from tracker.plugins.runtime import _python
from tracker.api.routers.intelligence import _agent_connection_state
from tracker.agents.config import AgentAccessConfig
from tracker.usage_stats.kill import blocked_by
assert get_settings().api_port == 8010
assert blocked_by(environ={}) is None
assert constraints_file().parent == BACKEND_DIR / 'constraints'
steps = pip_steps(Path('/scratch/venv/bin/python'), Path('/scratch/plugin'))
assert any(str(REPO_ROOT / 'plugin-wheels') in arg for step in steps for arg in step)
assert not any('/sdk/python' in arg or '/robots/python' in arg for step in steps for arg in step)
assert _python() == sys.executable
agent = _agent_connection_state(AgentAccessConfig())
assert agent['command'] == sys.executable
assert agent['cwd'] == str(BACKEND_DIR)
assert agent['args'] == ['-I', str(BACKEND_DIR / 'packaged.py'), 'mcp.server']
install.REPO_ROOT = Path.home() / 'missing-resources'
try:
    pip_steps(Path('/scratch/python'), Path('/scratch/plugin'))
except install.InstallRefused:
    pass
else:
    raise AssertionError('missing wheels must not fall back to building inside the app')
""")
    assert result.returncode == 0, result.stderr


def test_isolated_packaged_entrypoint_uses_built_version(bundle, tmp_path):
    result = probe(bundle, tmp_path, """
import os
import subprocess
import sys
from pathlib import Path
bootstrap = Path.cwd() / 'packaged.py'
env = {key: value for key, value in os.environ.items() if key != 'ROLEBAND_PACKAGED'}
version = subprocess.run([sys.executable, '-I', str(bootstrap), '--version'],
    env=env, cwd=Path.home(), capture_output=True, text=True)
assert version.returncode == 0, version.stderr
assert version.stdout.strip() == '1.2.3', version.stdout
help = subprocess.run([sys.executable, '-I', str(bootstrap), 'supervisor', '--help'],
    env=env, cwd=Path.home(), capture_output=True, text=True)
assert help.returncode == 0 and 'maintenance' in help.stdout, help.stderr
""")
    assert result.returncode == 0, result.stderr


def test_packaged_children_ignore_the_persons_own_python_packages(tmp_path):
    # The API, jobs and plugins start without -I, so only the environment the
    # entry point leaves behind keeps the person's user site out of them. A venv
    # disables the user site by itself, so the child runs the base interpreter.
    home = tmp_path / "user home"
    home.mkdir()
    base = getattr(sys, "_base_executable", sys.executable)
    env = {key: value for key, value in os.environ.items() if not key.startswith(("ROLEBAND_", "PYTHON"))}
    env["HOME"] = str(home)
    user_site = subprocess.run([base, "-c", "import site; print(site.getusersitepackages())"],
                               env=env, capture_output=True, text=True, check=True).stdout.strip()
    Path(user_site).mkdir(parents=True)
    Path(user_site, "user_site_probe.py").write_text("")
    reachable = subprocess.run([base, "-c", "import user_site_probe"], env=env, capture_output=True)
    assert reachable.returncode == 0, "the fixture must be importable without the entry point"
    script = f"""
import runpy, subprocess, sys
sys.argv = ['packaged.py', '--version']
runpy.run_path({str(ROOT / "backend" / "packaged.py")!r}, run_name='__main__')
child = subprocess.run([{base!r}, '-c', 'import user_site_probe'], capture_output=True)
sys.exit(0 if child.returncode != 0 else 3)
"""
    result = subprocess.run([sys.executable, "-c", script], env=env, cwd=home, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr or "a child of the packaged engine imported from the user site"


def test_packaged_engine_opens_only_a_cluster_the_app_made(bundle, tmp_path):
    result = probe(bundle, tmp_path, """
import json
from pathlib import Path
from tracker.config import get_settings
from tracker.platform import embedded_db
settings = get_settings()
pgdata = settings.embedded_pgdata()
record = pgdata.parent / 'db.owner.json'
started = []
def start(path, **_):
    assert json.loads(record.read_text()) == {'owner': 'app'}, 'the claim must exist before initdb'
    started.append(path)
embedded_db.ensure_server = start
settings.ensure_embedded_server()
settings.ensure_embedded_server()
assert started == [pgdata, pgdata]
(pgdata / 'PG_VERSION').parent.mkdir(parents=True, exist_ok=True)
(pgdata / 'PG_VERSION').write_text('17')
settings.ensure_embedded_server()
for other in ('{"owner": "source"}', 'not json', '[]'):
    record.write_text(other)
    try:
        settings.ensure_embedded_server()
    except embedded_db.ClusterOwnedElsewhere:
        pass
    else:
        raise AssertionError(f'opened a cluster recorded as {other}')
assert len(started) == 3
""")
    assert result.returncode == 0, result.stderr


def test_packaged_engine_leaves_a_source_installs_cluster_alone(bundle, tmp_path):
    result = probe(bundle, tmp_path, """
from tracker.config import get_settings
from tracker.platform import embedded_db
settings = get_settings()
pgdata = settings.embedded_pgdata()
pgdata.mkdir(parents=True)
(pgdata / 'PG_VERSION').write_text('17')
def start(*_, **__):
    raise AssertionError('started a source install cluster')
embedded_db.ensure_server = start
try:
    settings.ensure_embedded_server()
except embedded_db.ClusterOwnedElsewhere as refused:
    assert str(pgdata) in str(refused)
else:
    raise AssertionError('opened a source install cluster')
assert not (pgdata.parent / 'db.owner.json').exists()
""")
    assert result.returncode == 0, result.stderr


def test_a_source_install_claims_nothing(monkeypatch, tmp_path):
    from tracker.config import get_settings
    from tracker.platform import embedded_db

    pgdata = tmp_path / "db"
    pgdata.mkdir()
    (pgdata / "PG_VERSION").write_text("17")
    settings = get_settings().model_copy(update={"db_pgdata": str(pgdata)})
    started = []
    monkeypatch.setattr(embedded_db, "ensure_server", lambda path, **_: started.append(path))
    settings.ensure_embedded_server()
    assert started == [pgdata]
    assert not embedded_db.owner_record(pgdata).exists()
