"""A throwaway embedded cluster at the schema baseline, for upgrade rehearsals.

`tests/conftest.py` exposes `baseline_database`, so a test takes the cluster by
fixture name and never imports it from another test module. Each case that takes
it builds a real cluster through several subprocesses, so the fixture skips
locally unless ROLEBAND_REHEARSE_UPGRADE=1. CI always runs it: the
ROLEBAND_REQUIRE_INTEGRATION=1 its workflow sets opens the same gate.
"""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

from tests import skip_policy
from tests.embedded_utils import destroy
from tracker.platform.embedded_db import run_psql

_BACKEND = Path(__file__).resolve().parents[1]
BASELINE_REVISION = "c5e1a9d3f7b2"
REHEARSAL_FLAG = "ROLEBAND_REHEARSE_UPGRADE"


def rehearsal_enabled() -> bool:
    """CI always rehearses; a local run only when asked to."""

    return skip_policy.enforced() or os.environ.get(REHEARSAL_FLAG) == "1"


def require_own_pgdata(reported: str, expected: Path) -> None:
    """Refuse unless the server reports the data directory this test created.

    Compared CANONICALLY, because the two spellings genuinely differ: on macOS
    `tmp_path` is under `/tmp`, a symlink to `/private/tmp`, and Postgres reports
    the resolved path. A string comparison fails on every macOS run, and the
    obvious "fix" is to drop the check, which is how a test ends up migrating
    whatever server it happened to reach.
    """

    if Path(reported).resolve() != Path(expected).resolve():
        raise AssertionError(
            f"refusing to migrate: the server reports data_directory {reported!r}, but this test "
            f"created {str(expected)!r}. Nothing has been migrated or seeded. A rehearsal that "
            "reached another cluster would be running against the live database."
        )


def _env(pgdata: Path) -> dict[str, str]:
    """The ONE environment every subprocess gets.

    `ROLEBAND_DATABASE_URL` is emptied rather than left alone: it takes precedence
    over embedded mode, so a developer's `.env` pointing at an external server
    would otherwise send `alembic upgrade` there.
    """

    return {
        **os.environ,
        "ROLEBAND_PGDATA": str(pgdata),
        "ROLEBAND_DATABASE_URL": "",
        "PYTHONDONTWRITEBYTECODE": "1",
    }


def _run(args: list[str], env: dict[str, str]) -> subprocess.CompletedProcess:
    return subprocess.run(args, cwd=_BACKEND, env=env, capture_output=True, text=True)


def _python(*args: str) -> list[str]:
    return [sys.executable, *args]


def _resolved_pgdata(env: dict[str, str]) -> str:
    """What the app's own configuration would choose, asked before anything exists."""

    probe = _run(
        _python(
            "-c", "from tracker.config import get_settings; print(get_settings().embedded_pgdata())"
        ),
        env,
    )
    assert probe.returncode == 0, (probe.stderr or "")[-2000:]
    return probe.stdout.strip()


def _connection(env: dict[str, str]) -> tuple[str, Path]:
    """The DSN and client binaries, resolved the way every script resolves them.

    The socket directory is NOT the pgdata: upstream relocates it to a hashed
    runtime path when the pgdata path exceeds the ~104-character unix-socket cap,
    which a `tmp_path` reliably does. Asking `scripts.db_uri` is the only correct
    way to find it, and doing so here is also what proves that script still works.
    """

    dsn = _run(_python("-m", "scripts.db_uri", "dsn"), env)
    assert dsn.returncode == 0, (dsn.stderr or "")[-2000:]
    bin_dir = _run(_python("-m", "scripts.db_uri", "bin-dir"), env)
    assert bin_dir.returncode == 0, (bin_dir.stderr or "")[-2000:]
    return dsn.stdout.strip(), Path(bin_dir.stdout.strip())


def run_alembic(env: dict[str, str], *args: str) -> subprocess.CompletedProcess:
    return _run(_python("-m", "alembic", *args), env)


@pytest.fixture
def baseline_database(tmp_path) -> Iterator[tuple[dict[str, str], str, Path]]:
    """A throwaway cluster at BASELINE_REVISION, as `(env, dsn, bin_dir)`, destroyed afterwards.

    The gate sits here rather than on each test, so no case can build a cluster
    without the opt-in.
    """

    if not rehearsal_enabled():
        pytest.skip(f"set {REHEARSAL_FLAG}=1 to run the upgrade rehearsal locally")
    pgdata = tmp_path / "rehearsal"
    env = _env(pgdata)
    assert Path(_resolved_pgdata(env)).resolve() == pgdata.resolve()
    try:
        result = run_alembic(env, "upgrade", BASELINE_REVISION)
        assert result.returncode == 0, (result.stderr + result.stdout)[-2000:]
        dsn, bin_dir = _connection(env)
        require_own_pgdata(run_psql(dsn, bin_dir, "show data_directory"), pgdata)
        yield env, dsn, bin_dir
    finally:
        destroy(pgdata)
