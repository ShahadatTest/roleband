"""`restore_db.sh` and `backup_db.sh`, run for real: what a drill proves, what it refuses.

The drill never reports "drill complete" after pg_restore fails, with `jobs`
empty, or with its row counts unreadable; `--check --into roleband` never
reaches the live database without asking; and the backup's own check reads more
than the archive's table of contents, so a dump cut off in its data is never
promoted as a good one.

Two layers:

* Decisions, with every PostgreSQL client stubbed: which database a set of
  flags names, what is refused before any database is touched, which outcome
  each restore result reaches, and that the drill and a live restore take the
  same path up to the swap. No server.
* The real thing, on a throwaway embedded cluster made for this module, never
  the shared one: the real backup script writes the archive, the real restore
  script restores it, and a dump cut off in its data, a dump with no postings
  and a dump missing a core table all fail. A restore that fails for any of
  those reasons leaves the live database as it was, because a live restore is
  verified beside it and swapped in, never written over it.

The scripts run from a copy of `deploy/` in a scratch root beside a
`backend/.venv/bin/python` that is either a stub answering `scripts.db_uri`
(decisions) or this interpreter running the real `scripts.db_uri` (real). In
the real layer the live database is whatever ROLEBAND_DATABASE_URL names on the
throwaway cluster, and HOME is the scratch root, so nothing can reach
`~/.roleband/db`.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

import pytest

from scripts.db_uri import _with_database

REPO = Path(__file__).resolve().parents[2]
DEPLOY = REPO / "deploy"
CHECK_DB = "roleband_restore_check"

#: macOS banners from `backup_db.sh`'s failure path would reach the desktop of
#: whoever runs the suite; an exported bash function shadows the binary, which
#: the script's own PATH (system dirs first) would otherwise always find.
QUIET_OSASCRIPT = {"BASH_FUNC_osascript%%": '() { echo "osascript $*" >> "$CALLS"; }'}


def _executable(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body)
    path.chmod(0o755)


def _copy_deploy(root: Path, *names: str) -> None:
    (root / "deploy").mkdir(parents=True)
    for name in names:
        shutil.copy2(DEPLOY / name, root / "deploy" / name)


@dataclass
class Run:
    rc: int
    out: str
    err: str
    calls: list[str]

    def called(self, tool: str) -> list[str]:
        return [call for call in self.calls if call.startswith(tool + " ")]

    def touched(self) -> bool:
        """Did the script do anything to a database (beyond asking whether it is
        up and whether a supervisor holds it)?"""
        return bool(self.steps("psql") or self.called("pg_restore"))

    def steps(self, tool: str) -> list[str]:
        """Calls of `tool`, without the read-only supervisor probe."""
        return [call for call in self.called(tool) if "pg_locks" not in call]


# --- decisions: every PostgreSQL client is a stub --------------------------

#: `python -m scripts.db_uri ...`, answered from the environment.
_DB_URI_STUB = """#!/bin/sh
[ "$1" = "-m" ] && [ "$2" = "scripts.db_uri" ] || { echo "unexpected: $*" >&2; exit 97; }
case "$3" in
  dsn) if [ "$4" = "--database" ]; then db="$5"; else db="$APP_DB"; fi
       echo "postgresql://postgres:@/$db?host=/stub/sock" ;;
  database) echo "$APP_DB" ;;
  bin-dir) echo "$BIN_DIR" ;;
  *) exit 2 ;;
esac
"""

#: One log line per call, arguments joined by spaces (the SQL is multi-line).
_LOG = 'printf "%s " "$(basename "$0")" "$@" | tr "\\n" " " >> "$CALLS"; echo >> "$CALLS"\n'

_PSQL_STUB = "#!/bin/sh\n" + _LOG + """case "$*" in
  *"pg_locks"*)
    # The supervisor probe: SUPERVISED_AFTER calls answer 0, then 1.
    [ -n "$PROBE_FAIL" ] && { echo 'ERROR:  permission denied' >&2; exit 1; }
    n=$(grep -c pg_locks "$CALLS")
    if [ -n "$SUPERVISED_AFTER" ] && [ "$n" -gt "$SUPERVISED_AFTER" ]; then echo 1; else echo 0; fi ;;
  *"from job_observations"*)
    if [ -n "$FACTS_FAIL" ]; then echo 'ERROR:  relation "jobs" does not exist' >&2; exit 1; fi
    echo "$FACTS" ;;
  *'RENAME TO "roleband_before_'*)
    if [ -n "$SET_ASIDE_FAIL" ]; then echo 'ERROR:  database "roleband" is being accessed by other users' >&2; exit 1; fi ;;
esac
exit 0
"""

_PG_RESTORE_STUB = "#!/bin/sh\n" + _LOG + """if [ "$RESTORE_RC" != 0 ]; then
  echo "pg_restore: error: could not read from input file: end of file" >&2
fi
exit "$RESTORE_RC"
"""


@pytest.fixture
def stubbed(tmp_path):
    root = tmp_path / "root"
    _copy_deploy(root, "restore_db.sh")
    (root / "data" / "backups").mkdir(parents=True)
    (root / "data" / "backups" / "roleband_20261003_063000.dump").write_bytes(b"stub archive")
    bin_dir = tmp_path / "bin"
    _executable(root / "backend" / ".venv" / "bin" / "python", _DB_URI_STUB)
    _executable(bin_dir / "psql", _PSQL_STUB)
    _executable(bin_dir / "pg_restore", _PG_RESTORE_STUB)
    _executable(bin_dir / "pg_isready", "#!/bin/sh\n" + _LOG)
    calls = tmp_path / "calls.log"

    def run(
        *args: str,
        app_db: str = "roleband",
        restore_rc: int = 0,
        facts: str = "rev_a 120 900",
        facts_fail: bool = False,
        stdin: str = "",
        supervised_after: int | None = None,
        env: dict[str, str] | None = None,
    ) -> Run:
        calls.write_text("")
        proc = subprocess.run(
            ["bash", str(root / "deploy" / "restore_db.sh"), *args],
            input=stdin,
            capture_output=True,
            text=True,
            timeout=60,
            env={
                "PATH": os.environ["PATH"],
                "HOME": str(tmp_path),
                "TMPDIR": str(tmp_path),
                "CALLS": str(calls),
                "BIN_DIR": str(bin_dir),
                "APP_DB": app_db,
                "RESTORE_RC": str(restore_rc),
                "FACTS": facts,
                "FACTS_FAIL": "1" if facts_fail else "",
                "SUPERVISED_AFTER": "" if supervised_after is None else str(supervised_after),
                "PROBE_FAIL": "",
                "SET_ASIDE_FAIL": "",
                **(env or {}),
            },
        )
        return Run(proc.returncode, proc.stdout, proc.stderr, calls.read_text().splitlines())

    return run


def _drops(run: Run, db: str) -> list[int]:
    """Positions, among all calls, of DROP DATABASE statements for `db`."""
    return [i for i, call in enumerate(run.calls) if f'DROP DATABASE IF EXISTS "{db}"' in call]


class TestTargets:
    """Which database a set of flags names, and what never reaches a database."""

    @pytest.mark.parametrize(
        "args",
        [
            ("--check", "--into", "roleband"),  # restored --clean over live, unprompted
            ("--into", "roleband", "--check"),
            ("--into", "roleband"),
        ],
    )
    def test_check_and_into_never_name_the_live_database(self, stubbed, args):
        run = stubbed(*args)
        assert run.rc == 2
        assert "is the live database" in run.err
        assert not run.touched()

    def test_the_live_name_is_the_one_the_app_reads(self, stubbed):
        # The app reads its database name from backend/.env; a shell's
        # ROLEBAND_POSTGRES_DB is unset or stale. Trusting it would take the app's
        # database for a scratch one, to be dropped and recreated.
        run = stubbed("--into", "roleband_prod", app_db="roleband_prod", env={"ROLEBAND_POSTGRES_DB": "roleband"})
        assert run.rc == 2
        assert "is the live database" in run.err
        assert not run.touched()

    @pytest.mark.parametrize(
        "name", ["postgres", "template1", 'drill"; DROP DATABASE roleband; --', "drill-1"]
    )
    def test_a_scratch_database_is_a_plain_name_nothing_else_needs(self, stubbed, name):
        run = stubbed("--check", "--into", name)
        assert run.rc == 2
        assert "refused" in run.err
        assert not run.touched()

    @pytest.mark.parametrize("args", [("--into",), ("--check", "--into", "")])
    def test_into_needs_a_name(self, stubbed, args):
        # An empty name never falls through to a plain --check.
        run = stubbed(*args)
        assert run.rc == 2
        assert "--into needs a database name" in run.err
        assert not run.touched()

    def test_check_restores_into_its_scratch_database_in_one_transaction(self, stubbed):
        run = stubbed("--check")
        assert run.rc == 0, run.err
        (restore,) = run.called("pg_restore")
        assert f"/{CHECK_DB}?host=" in restore
        assert "--single-transaction" in restore
        created = next(i for i, call in enumerate(run.calls) if f'CREATE DATABASE "{CHECK_DB}"' in call)
        restored = run.calls.index(restore)
        # Recreated empty before the restore, dropped after it, and nothing else.
        assert [i for i in _drops(run, CHECK_DB) if i < created]
        assert [i for i in _drops(run, CHECK_DB) if i > restored]
        assert not [call for call in run.called("psql") if '"roleband"' in call]
        assert "drill passed" in run.out

    def test_check_into_a_named_scratch_database_drills_and_drops_that_one(self, stubbed):
        run = stubbed("--check", "--into", "drill_a")
        assert run.rc == 0, run.err
        (restore,) = run.called("pg_restore")
        assert "/drill_a?host=" in restore
        assert _drops(run, "drill_a")[-1] > run.calls.index(restore)
        assert not _drops(run, CHECK_DB)

    def test_into_keeps_its_scratch_database(self, stubbed):
        run = stubbed("--into", "drill_a")
        assert run.rc == 0, run.err
        restored = run.calls.index(run.called("pg_restore")[0])
        assert not [i for i in _drops(run, "drill_a") if i > restored]
        assert "drill passed" not in run.out
        assert "drill_a verified" in run.out

    @pytest.mark.parametrize("answer", ["roleband_x\n", ""])  # a wrong name; no answer at all
    def test_a_live_restore_asks_and_anything_but_the_name_changes_nothing(self, stubbed, answer):
        run = stubbed(stdin=answer)
        assert run.rc == 1
        assert "LIVE database 'roleband'" in run.out
        assert "aborted" in run.err
        assert not run.touched()

    def test_a_confirmed_live_restore_builds_beside_live_and_swaps_it_in(self, stubbed):
        """Nothing is written into the live database. The dump lands in a
        scratch database, is verified there, and only then takes the live
        name, so a dump that fails verification costs nothing."""
        run = stubbed(stdin="roleband\n")
        assert run.rc == 0, run.err
        (restore,) = run.called("pg_restore")
        assert "/roleband_restore_" in restore and "/roleband?host=" not in restore
        assert "--single-transaction" in restore
        # The live schema is never dropped, which is what a dump older than it
        # would fail on; the scratch target is empty, so there is nothing to clean.
        assert "--clean" not in restore
        assert not _drops(run, "roleband")

        restored = run.calls.index(restore)
        renames = [i for i, call in enumerate(run.calls) if "RENAME TO" in call]
        assert renames and min(renames) > restored, "the swap happens after the restore"
        swap = " ".join(run.calls[i] for i in renames)
        assert 'ALTER DATABASE "roleband" RENAME TO "roleband_before_' in swap
        assert 'RENAME TO "roleband"' in swap

        # Closed before its backends are cleared, not after: an agent that
        # reconnects between the kill and the rename holds the rename open.
        step = run.calls[min(renames)]
        assert step.index("ALLOW_CONNECTIONS false") < step.index("pg_terminate_backend")
        assert step.index("pg_terminate_backend") < step.index("RENAME TO")

    def test_a_failed_set_aside_reopens_the_live_database(self, stubbed):
        """The live database is closed to new connections before it is renamed
        aside. If that rename fails, the database is still the live one and
        must take connections again: the message says nothing was replaced."""
        run = stubbed(stdin="roleband\n", env={"SET_ASIDE_FAIL": "1"})
        assert run.rc == 1
        assert "could not set the live database aside" in run.err
        assert "nothing replaced the live database" in run.err
        failed = next(i for i, call in enumerate(run.calls) if 'RENAME TO "roleband_before_' in call)
        reopened = [i for i, call in enumerate(run.calls)
                    if 'ALTER DATABASE "roleband" WITH ALLOW_CONNECTIONS true' in call]
        assert reopened and reopened[0] > failed, "the live database was left refusing connections"

    def test_the_drill_takes_the_live_restore_s_path(self, stubbed):
        """"Drill passed" has to mean "this dump will apply". It only does if
        the drill restores the way a live restore restores."""
        def shape(run) -> list[list[str]]:
            """Every database call up to and including the read-back, with the
            scratch name and the connection string generalised away. What
            follows it is the drill's cleanup or the live path's swap."""
            target = run.out.split("-> ", 1)[1].splitlines()[0]
            steps: list[list[str]] = []
            for call in run.calls:
                if not call.startswith(("pg_restore ", "psql ")) or "pg_locks" in call:
                    continue
                call = call.replace(target, "<target>")
                steps.append([w for w in call.split() if not w.startswith("postgresql://")])
                if "from job_observations" in call:
                    break
            return steps

        drill = stubbed("--check")
        live = stubbed(stdin="roleband\n")
        assert drill.rc == 0 and live.rc == 0
        assert shape(drill) == shape(live), "the drill and the live restore diverge before the swap"


class TestKeptCopies:
    """A live restore keeps the database it replaced (`<live>_before_<stamp>`):
    it is the only way back from a wrong dump, so no drill may reuse its name."""

    @pytest.mark.parametrize("args", [
        ("--into", "roleband_before_20261020_101010"),
        ("--check", "--into", "roleband_before_20261020_101010"),
    ])
    def test_a_kept_copy_is_never_a_scratch_target(self, stubbed, args):
        run = stubbed(*args)
        assert run.rc == 2
        assert "is a copy a live restore kept" in run.err
        assert not run.touched()


class TestSupervisor:
    """A live restore never swaps under a supervisor that is dispatching."""

    def test_a_supervisor_holding_the_live_database_refuses_before_anything(self, stubbed):
        run = stubbed(stdin="roleband\n", supervised_after=0)
        assert run.rc == 1
        assert "the supervisor is running jobs on 'roleband'" in run.err
        assert "tracker.supervisor maintenance on" in run.err
        assert not run.touched()

    def test_a_supervisor_that_starts_during_the_restore_stops_the_swap(self, stubbed):
        run = stubbed(stdin="roleband\n", supervised_after=1)
        assert run.rc == 1
        assert "the supervisor is running jobs on 'roleband'" in run.err
        assert not [call for call in run.called("psql") if "RENAME TO" in call or "pg_terminate_backend" in call]
        assert [call for call in run.steps("psql") if "roleband_restore_" in call and "DROP" in call], (
            "the verified copy goes; the live database stays as it was"
        )

    def test_a_probe_that_cannot_answer_refuses_rather_than_guess(self, stubbed):
        run = stubbed(stdin="roleband\n", env={"PROBE_FAIL": "1"})
        assert run.rc == 1
        assert "could not tell whether the supervisor is using 'roleband'" in run.err
        assert not run.touched()

    @pytest.mark.parametrize("args", [("--check",), ("--into", "drill_a")])
    def test_a_drill_does_not_care_about_the_supervisor(self, stubbed, args):
        run = stubbed(*args, supervised_after=0)
        assert run.rc == 0, run.err
        assert not [call for call in run.called("psql") if "pg_locks" in call]

    def test_the_script_names_the_supervisor_s_own_lock(self):
        from tracker.supervisor.singleton import SUPERVISOR_LOCK_KEY

        assert f"SUPERVISOR_LOCK_KEY={SUPERVISOR_LOCK_KEY}\n" in (DEPLOY / "restore_db.sh").read_text()


class TestOutcomes:
    """Success is reported only after the restored data is read back."""

    @pytest.mark.parametrize(
        ("result", "reason"),
        [
            ({"restore_rc": 1}, "pg_restore exited 1"),
            ({"facts_fail": True}, "could not read the restored data"),
            ({"facts": "- 120 900"}, "no schema revision restored"),
            ({"facts": "rev_a 0 900"}, "jobs is empty"),
            ({"facts": "rev_a 120 0"}, "job_observations is empty"),
        ],
    )
    def test_a_drill_that_restored_no_data_fails_and_leaves_nothing(self, stubbed, result, reason):
        run = stubbed("--check", **result)
        assert run.rc == 1
        assert f"FAILED: {reason}" in run.err
        assert "verified" not in run.out
        assert "drill passed" not in run.out
        assert _drops(run, CHECK_DB)[-1] == len(run.calls) - 1  # the drill's last act

    def test_the_restore_error_is_shown(self, stubbed):
        run = stubbed("--check", restore_rc=1)
        assert "could not read from input file: end of file" in run.err

    def test_a_restore_reads_back_only_what_the_app_cannot_rebuild(self, stubbed):
        # The drill proves history landed: the schema revision, postings and
        # observations. A seed table's count is no proof of anything.
        run = stubbed("--check", facts="rev_a 120 900")
        assert run.rc == 0, run.err
        assert "revision rev_a; 120 jobs, 900 observations\n" in run.out

    @pytest.mark.parametrize(
        ("result", "reason"),
        [
            ({"restore_rc": 1}, "pg_restore exited 1"),
            ({"facts_fail": True}, "could not read the restored data"),
            ({"facts": "rev_a 0 900"}, "jobs is empty"),
        ],
    )
    def test_a_live_restore_that_fails_never_reaches_the_live_database(
        self, stubbed, result, reason
    ):
        """Verification now runs before anything replaces live data, so every
        way a restore can fail leaves the live database alone and says so."""
        run = stubbed(stdin="roleband\n", **result)
        assert run.rc == 1
        assert f"FAILED: {reason}" in run.err
        assert "nothing replaced the live database; it is as it was" in run.err
        assert not [call for call in run.called("psql") if "RENAME TO" in call]
        # The half-built copy goes with it; only the live database is kept.
        assert not _drops(run, "roleband")
        assert [call for call in run.called("psql") if "roleband_restore_" in call and "DROP" in call]


# --- the real thing: a throwaway embedded cluster ---------------------------


@pytest.fixture(scope="module")
def cluster(tmp_path_factory):
    """One throwaway cluster for the module; never the shared server."""
    pytest.importorskip("pixeltable_pgserver", reason="embedded Postgres wheel not installed")
    from tests.embedded_utils import destroy
    from tracker.platform.embedded_db import ensure_server

    srv = ensure_server(tmp_path_factory.mktemp("restore-pg") / "db", database="postgres")
    yield srv
    destroy(srv.pgdata)


def _sql(srv, db: str, statement: str) -> str:
    from tracker.platform.embedded_db import run_psql

    return run_psql(_with_database(srv.dsn(), db), srv.bin_dir, statement)


def _make_db(
    srv,
    name: str,
    *,
    revision: str = "rev_a",
    jobs: int = 20_000,
    observations: int = 30_000,
    with_observations_table: bool = True,
) -> None:
    """A database shaped like the app's for what the drill reads back.

    `jobs` carries enough text that its data, not the table of contents,
    is most of a dump: a dump cut in half is then cut in its data."""
    _sql(srv, "postgres", f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
    _sql(srv, "postgres", f'CREATE DATABASE "{name}"')
    statements = [
        "CREATE TABLE alembic_version (version_num varchar(32) PRIMARY KEY)",
        f"INSERT INTO alembic_version VALUES ('{revision}')",
        "CREATE TABLE jobs (id bigint PRIMARY KEY, title text)",
        f"INSERT INTO jobs SELECT i, md5(i::text) || md5((i * 7)::text) FROM generate_series(1, {jobs}) i",
    ]
    if with_observations_table:
        statements += [
            "CREATE TABLE job_observations (id bigint PRIMARY KEY, job_id bigint)",
            f"INSERT INTO job_observations SELECT i, 1 + i % {max(jobs, 1)} "
            f"FROM generate_series(1, {observations}) i",
        ]
    _sql(srv, name, "; ".join(statements))


def _facts(srv, db: str) -> tuple[str, int]:
    revision, jobs = _sql(srv, db, "SELECT (SELECT version_num FROM alembic_version), (SELECT count(*) FROM jobs)").split("|")
    return revision, int(jobs)


def _mode(path: Path) -> int:
    """The permission bits of `path`, for comparing against 0o700 / 0o600."""
    return path.stat().st_mode & 0o777


def _exists(srv, db: str) -> bool:
    return _sql(srv, "postgres", f"SELECT count(*) FROM pg_database WHERE datname = '{db}'") == "1"


def _leftovers(srv, live: str) -> list[str]:
    """The databases a restore of `live` leaves beside it: the copy it builds
    and the one it sets aside."""
    rows = _sql(
        srv,
        "postgres",
        "SELECT datname FROM pg_database "
        f"WHERE datname LIKE '{live}\\_before\\_%' OR datname LIKE '{live}\\_restore\\_%' "
        "ORDER BY datname",
    )
    return [name for name in rows.splitlines() if name]


def _await_connection(srv, db: str, timeout: float = 10.0) -> None:
    """Block until some backend is connected to `db`."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _sql(srv, "postgres", f"SELECT count(*) FROM pg_stat_activity WHERE datname = '{db}'") != "0":
            return
        time.sleep(0.05)
    raise AssertionError(f"nothing connected to {db} within {timeout}s")


def _dump(srv, db: str, path: Path) -> Path:
    subprocess.run(
        [str(srv.tool("pg_dump")), _with_database(srv.dsn(), db), "-Fc", "-f", str(path)],
        check=True,
        capture_output=True,
    )
    return path


def _cut(source: Path, path: Path) -> Path:
    data = source.read_bytes()
    path.write_bytes(data[: len(data) // 2])
    return path


@dataclass
class Real:
    srv: object
    root: Path
    live: str
    run: object


@pytest.fixture
def real(tmp_path, cluster):
    root = tmp_path / "root"
    _copy_deploy(root, "restore_db.sh", "backup_db.sh")
    for package in ("scripts", "tracker"):
        (root / "backend" / package).parent.mkdir(parents=True, exist_ok=True)
        (root / "backend" / package).symlink_to(REPO / "backend" / package)
    # This interpreter running the real `scripts.db_uri`; `bin-dir` can be
    # pointed at a doctored tool directory to break one tool on purpose.
    _executable(
        root / "backend" / ".venv" / "bin" / "python",
        "#!/bin/sh\n"
        'if [ -n "$STUB_BIN_DIR" ] && [ "$*" = "-m scripts.db_uri bin-dir" ]; then\n'
        '  echo "$STUB_BIN_DIR"; exit 0\n'
        "fi\n"
        f'exec "{sys.executable}" "$@"\n',
    )
    live = f"live_{uuid.uuid4().hex[:8]}"
    assert live != "roleband"
    _make_db(cluster, live)
    calls = tmp_path / "calls.log"
    calls.write_text("")

    def run(script: str, *args: str, env: dict[str, str] | None = None) -> Run:
        proc = subprocess.run(
            ["bash", str(root / "deploy" / script), *args],
            input="",
            capture_output=True,
            text=True,
            timeout=300,
            env={
                "PATH": os.environ["PATH"],
                "HOME": str(tmp_path),
                "TMPDIR": str(tmp_path),
                "CALLS": str(calls),
                "ROLEBAND_DATABASE_URL": _with_database(cluster.uri(), live),
                **QUIET_OSASCRIPT,
                **(env or {}),
            },
        )
        return Run(proc.returncode, proc.stdout, proc.stderr, calls.read_text().splitlines())

    yield Real(cluster, root, live, run)
    for db in (live, CHECK_DB, *_leftovers(cluster, live)):
        _sql(cluster, "postgres", f'DROP DATABASE IF EXISTS "{db}" WITH (FORCE)')


class TestRealBackupAndDrill:
    def test_a_nightly_backup_passes_its_drill(self, real):
        backup = real.run("backup_db.sh")
        assert backup.rc == 0, backup.err
        (dump,) = (real.root / "data" / "backups").glob("roleband_*.dump")
        drill = real.run("restore_db.sh", "--check")
        assert drill.rc == 0, drill.err
        assert f"restoring {dump.name} -> {CHECK_DB}" in drill.out
        assert "revision rev_a; 20000 jobs, 30000 observations\n" in drill.out
        assert "drill passed" in drill.out
        assert not _exists(real.srv, CHECK_DB)
        assert _facts(real.srv, real.live) == ("rev_a", 20_000)

    def test_a_backup_cut_off_in_its_data_is_discarded(self, real, tmp_path):
        real_bin = real.srv.bin_dir
        doctored = tmp_path / "doctored-bin"
        for tool in ("psql", "pg_isready", "pg_restore"):
            doctored.mkdir(exist_ok=True)
            (doctored / tool).symlink_to(real_bin / tool)
        # The real pg_dump, then half its archive gone: a disk that filled up,
        # a copy that stopped. The table of contents, at the head, survives.
        _executable(
            doctored / "pg_dump",
            f'#!/bin/sh\n"{real_bin}/pg_dump" "$@" || exit $?\n'
            "for last; do :; done\n"
            'size=$(wc -c < "$last"); head -c $((size / 2)) "$last" > "$last.cut" && mv "$last.cut" "$last"\n',
        )
        backup = real.run("backup_db.sh", env={"STUB_BIN_DIR": str(doctored)})
        assert backup.rc == 1
        assert "dump failed verification — discarded" in backup.err
        assert list((real.root / "data" / "backups").glob("roleband_*")) == []
        # The exit code is the report; the health job raises the alert from the
        # supervisor's record of the run, so the script itself writes neither.
        assert not (real.root / "data" / "alerts.log").exists()
        assert not backup.called("osascript")

    def test_a_dump_cut_off_in_its_data_fails_the_drill(self, real, tmp_path):
        cut = _cut(_dump(real.srv, real.live, tmp_path / "good.dump"), tmp_path / "cut.dump")
        # A table-of-contents check passes this archive: the cut is in the data.
        listed = subprocess.run([str(real.srv.tool("pg_restore")), "--list", str(cut)], capture_output=True)
        assert listed.returncode == 0
        drill = real.run("restore_db.sh", "--check", str(cut))
        assert drill.rc == 1
        assert "FAILED: pg_restore exited 1" in drill.err
        assert "drill passed" not in drill.out
        assert not _exists(real.srv, CHECK_DB)

    def test_a_dump_with_no_postings_fails_the_drill(self, real, tmp_path):
        empty = f"src_{uuid.uuid4().hex[:8]}"
        _make_db(real.srv, empty, jobs=0, observations=10)
        try:
            dump = _dump(real.srv, empty, tmp_path / "empty.dump")
        finally:
            _sql(real.srv, "postgres", f'DROP DATABASE "{empty}" WITH (FORCE)')
        drill = real.run("restore_db.sh", "--check", str(dump))
        assert drill.rc == 1
        assert "FAILED: jobs is empty" in drill.err
        assert not _exists(real.srv, CHECK_DB)

    def test_a_dump_missing_a_core_table_fails_the_drill(self, real, tmp_path):
        partial = f"src_{uuid.uuid4().hex[:8]}"
        _make_db(real.srv, partial, with_observations_table=False)
        try:
            dump = _dump(real.srv, partial, tmp_path / "partial.dump")
        finally:
            _sql(real.srv, "postgres", f'DROP DATABASE "{partial}" WITH (FORCE)')
        drill = real.run("restore_db.sh", "--check", str(dump))
        assert drill.rc == 1
        assert "FAILED: could not read the restored data" in drill.err
        assert 'relation "job_observations" does not exist' in drill.err
        assert not _exists(real.srv, CHECK_DB)


class TestRealLiveRestore:
    def test_check_into_the_live_database_is_refused(self, real, tmp_path):
        dump = _dump(real.srv, real.live, tmp_path / "good.dump")
        _sql(real.srv, real.live, "UPDATE alembic_version SET version_num = 'rev_live'")
        run = real.run("restore_db.sh", "--check", "--into", real.live, str(dump))
        assert run.rc == 2
        assert "is the live database" in run.err
        assert _facts(real.srv, real.live) == ("rev_live", 20_000)

    def test_a_failed_restore_over_live_leaves_live_as_it_was(self, real, tmp_path):
        other = f"src_{uuid.uuid4().hex[:8]}"
        _make_db(real.srv, other, revision="rev_b", jobs=30_000)
        try:
            cut = _cut(_dump(real.srv, other, tmp_path / "other.dump"), tmp_path / "cut.dump")
        finally:
            _sql(real.srv, "postgres", f'DROP DATABASE "{other}" WITH (FORCE)')
        run = real.run("restore_db.sh", "--yes", str(cut))
        assert run.rc == 1
        assert "nothing replaced the live database; it is as it was" in run.err
        assert _facts(real.srv, real.live) == ("rev_a", 20_000)
        assert not _leftovers(real.srv, real.live), "the half-built copy is not kept"

    def test_a_confirmed_restore_replaces_live_and_keeps_what_it_replaced(self, real, tmp_path):
        other = f"src_{uuid.uuid4().hex[:8]}"
        _make_db(real.srv, other, revision="rev_b", jobs=50, observations=70)
        try:
            dump = _dump(real.srv, other, tmp_path / "other.dump")
        finally:
            _sql(real.srv, "postgres", f'DROP DATABASE "{other}" WITH (FORCE)')
        run = real.run("restore_db.sh", "--yes", str(dump))
        assert run.rc == 0, run.err
        assert f"{real.live} restored; revision rev_b; 50 jobs, 70 observations" in run.out
        assert _facts(real.srv, real.live) == ("rev_b", 50)

        # Restoring the wrong dump is recoverable only while the database it
        # replaced still exists, so the script keeps it and names it.
        (previous,) = _leftovers(real.srv, real.live)
        assert previous in run.out
        assert _sql(real.srv, "postgres", f"SELECT datallowconn FROM pg_database WHERE datname = '{previous}'") == "f"
        _sql(real.srv, "postgres", f'ALTER DATABASE "{previous}" WITH ALLOW_CONNECTIONS true')
        assert _facts(real.srv, previous) == ("rev_a", 20_000)

    def test_a_dump_older_than_the_live_schema_restores(self, real, tmp_path):
        """The case a drill on an empty scratch database cannot see: a later
        migration has given the live schema a table that depends on `jobs`, so
        dropping the live schema to make room for an older dump fails on it.
        Building the dump's own database beside the live one has nothing to
        drop. Fail-first: restoring in place exits 1 here."""
        other = f"src_{uuid.uuid4().hex[:8]}"
        _make_db(real.srv, other, revision="rev_a", jobs=40, observations=60)
        try:
            dump = _dump(real.srv, other, tmp_path / "older.dump")
        finally:
            _sql(real.srv, "postgres", f'DROP DATABASE "{other}" WITH (FORCE)')
        _sql(
            real.srv,
            real.live,
            "CREATE TABLE job_notes (id bigint PRIMARY KEY, "
            "job_id bigint REFERENCES jobs(id)); "
            "UPDATE alembic_version SET version_num = 'rev_newer'",
        )

        run = real.run("restore_db.sh", "--yes", str(dump))
        assert run.rc == 0, run.err
        assert _facts(real.srv, real.live) == ("rev_a", 40)
        # The dump's schema is the whole schema now: the table the newer
        # migration added is in the database that was set aside, not this one.
        assert _sql(real.srv, real.live, "SELECT to_regclass('job_notes') IS NULL") == "t"

    def test_a_connected_client_does_not_block_the_swap(self, real, tmp_path):
        """The always-on agents hold connections to the live database and
        reconnect on their own, so the swap closes it before it clears them:
        a reconnect between the two would make the rename fail."""
        other = f"src_{uuid.uuid4().hex[:8]}"
        _make_db(real.srv, other, revision="rev_b", jobs=50, observations=70)
        try:
            dump = _dump(real.srv, other, tmp_path / "other.dump")
        finally:
            _sql(real.srv, "postgres", f'DROP DATABASE "{other}" WITH (FORCE)')

        held = subprocess.Popen(
            [str(real.srv.tool("psql")), _with_database(real.srv.dsn(), real.live), "-X", "-q", "-f", "-"],
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        try:
            held.stdin.write("SELECT pg_sleep(60);\n")
            held.stdin.flush()
            _await_connection(real.srv, real.live)
            run = real.run("restore_db.sh", "--yes", str(dump))
        finally:
            held.kill()
            held.wait(timeout=10)
        assert run.rc == 0, run.err
        assert _facts(real.srv, real.live) == ("rev_b", 50)


class TestRealBackupPermissions:
    """A dump is the whole database. Dailies are kept for a fortnight and
    monthly copies forever, so the mode they land with is the mode they keep."""

    def test_a_backup_is_readable_by_its_owner_only(self, real):
        backup = real.run("backup_db.sh")
        assert backup.rc == 0, backup.err
        backups = real.root / "data" / "backups"
        (dump,) = backups.glob("roleband_*.dump")
        (monthly,) = (backups / "monthly").glob("roleband_*.dump")
        assert _mode(backups) == 0o700
        assert _mode(backups / "monthly") == 0o700
        assert _mode(dump) == 0o600
        assert _mode(monthly) == 0o600

    def test_backups_written_before_the_rule_are_tightened(self, real):
        """The rule has to reach archives already on disk: a dump taken once is
        kept, and nothing else would ever narrow it."""
        backups = real.root / "data" / "backups"
        (backups / "monthly").mkdir(parents=True)
        old = backups / "roleband_20260101_000000.dump"
        old.write_bytes(b"an older archive")
        old.chmod(0o644)
        backups.chmod(0o755)

        assert real.run("backup_db.sh").rc == 0
        assert _mode(old) == 0o600
        assert _mode(backups) == 0o700

    def test_a_drill_still_reads_a_tightened_backup(self, real):
        assert real.run("backup_db.sh").rc == 0
        drill = real.run("restore_db.sh", "--check")
        assert drill.rc == 0, drill.err
        assert "drill passed" in drill.out
