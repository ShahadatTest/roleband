"""Every backend script imports, and importing one starts no database.

A script runs by hand (monthly, once, or before a release), so nothing exercises
it between uses: a script whose import names a deleted module fails silently
until someone runs it. Importing is the cheapest proof a script still matches
the code it drives.

The imports run in a child interpreter under the guard `test_db_url_precedence.py`
holds app modules to: no database URL, and a throwaway PGDATA. An import that
resolves the URL would initialise a cluster there, never attach to the live one,
and the report names the script that did it.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from tracker.platform.embedded_db import stop_server

BACKEND = Path(__file__).resolve().parents[1]

_CHILD = r"""
import importlib, json, pathlib, sys

package, directory, pgdata = sys.argv[1], pathlib.Path(sys.argv[2]), pathlib.Path(sys.argv[3])
report = {"modules": [], "failures": {}, "server_started_by": None}
for path in sorted(directory.glob("*.py")):
    if path.stem == "__init__":
        continue
    report["modules"].append(path.stem)
    try:
        importlib.import_module(f"{package}.{path.stem}")
    except BaseException as exc:
        report["failures"][path.stem] = f"{type(exc).__name__}: {exc}"
    if report["server_started_by"] is None and (pgdata / "PG_VERSION").exists():
        report["server_started_by"] = path.stem
print(json.dumps(report))
"""


def _import_all(package: str, directory: Path, root: Path, tmp_path: Path) -> dict:
    pgdata = tmp_path / "db"
    env = {key: value for key, value in os.environ.items() if key != "ROLEBAND_DATABASE_URL"}
    env["ROLEBAND_PGDATA"] = str(pgdata)
    env["PYTHONPATH"] = os.pathsep.join([str(root), str(BACKEND)])
    try:
        proc = subprocess.run(
            [sys.executable, "-c", _CHILD, package, str(directory), str(pgdata)],
            cwd=BACKEND,
            env=env,
            capture_output=True,
            text=True,
            timeout=300,
        )
    finally:
        # `pg_ctl` detaches the postmaster, so a cluster an import started would
        # outlive the child: stop it here, whatever the assertions below say.
        if (pgdata / "PG_VERSION").exists():
            stop_server(pgdata)
    assert proc.returncode == 0, proc.stderr[-2000:]
    return json.loads(proc.stdout.strip().splitlines()[-1])


def _stems(directory: Path) -> list[str]:
    return sorted(path.stem for path in directory.glob("*.py") if path.stem != "__init__")


def test_every_script_imports_without_starting_a_database(tmp_path):
    report = _import_all("scripts", BACKEND / "scripts", BACKEND, tmp_path)

    assert report["modules"] == _stems(BACKEND / "scripts"), "every script was attempted"
    assert report["failures"] == {}, "\n".join(
        f"scripts/{name}.py: {error}" for name, error in report["failures"].items()
    )
    assert report["server_started_by"] is None, (
        f"importing scripts/{report['server_started_by']}.py initialised a Postgres cluster"
    )


def test_the_gate_names_a_script_that_no_longer_imports(tmp_path):
    """A gate that cannot fail measures nothing: plant the rot this file exists for."""
    package = tmp_path / "planted" / "planted_scripts"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("")
    (package / "still_fine.py").write_text("from tracker.notifications import run_diagnostics\n")
    (package / "stale.py").write_text("from tracker.notifications import classify_run_health\n")

    report = _import_all("planted_scripts", package, tmp_path / "planted", tmp_path)

    assert report["modules"] == ["stale", "still_fine"]
    assert set(report["failures"]) == {"stale"}
    assert "classify_run_health" in report["failures"]["stale"]
    assert report["server_started_by"] is None
