"""Fail on a known vulnerability in the locked install graph unless it is excepted.

Usage (from `backend/`):
    .venv/bin/python -m scripts.check_dependency_audit
    .venv/bin/python -m scripts.check_dependency_audit --report audit.json

Audits every platform lock in `constraints/` (the whole graph each source install
gets, every requirements file and transitive package included) and the Mac app's
`launcher/macos/runtime-lock.txt`, with the `pip_audit` module. A pin that only one
platform or only the app carries still ships, so each lock is read. Every pin is
exact, so the audit reads the pins as written and installs nothing.

The only way to accept a finding is an entry in `audit-exceptions.toml`: the
advisory id (or any of its aliases), the package, the reason it does not reach
RoleBand or why it waits, and an expiry date. The run exits 1 naming every
finding with no entry, every entry past its expiry, every malformed entry, and
every entry that matches no finding, so the list never outlives the reason for it.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
import tomllib
from dataclasses import dataclass, replace
from datetime import date
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
LOCKS = (*sorted((BACKEND / "constraints").glob("*.txt")), BACKEND.parent / "launcher" / "macos" / "runtime-lock.txt")
EXCEPTIONS = BACKEND / "audit-exceptions.toml"
FIELDS = ("id", "package", "reason", "expires")


@dataclass(frozen=True)
class Finding:
    package: str
    version: str
    id: str
    aliases: tuple[str, ...]
    fix_versions: tuple[str, ...]
    #: The lock files that pin it; empty for a report read with --report.
    locks: tuple[str, ...] = ()

    @property
    def names(self) -> set[str]:
        return {self.id, *self.aliases}


def findings(report: dict, lock: str | None = None) -> list[Finding]:
    """Every advisory against a pinned package in a JSON report from `pip_audit -f json`."""
    out: list[Finding] = []
    for dep in report.get("dependencies", []):
        for vuln in dep.get("vulns", []):
            out.append(Finding(
                package=dep["name"].lower(), version=dep.get("version", ""), id=vuln["id"],
                aliases=tuple(vuln.get("aliases", [])), fix_versions=tuple(vuln.get("fix_versions", [])),
                locks=(lock,) if lock else (),
            ))
    return out


def merged(per_lock: list[list[Finding]]) -> list[Finding]:
    """One finding per package, version and advisory, naming every lock that pins it,
    so a pin shared by several locks needs one exception, not one per lock."""
    out: dict[tuple[str, str, str], Finding] = {}
    for found in per_lock:
        for f in found:
            key = (f.package, f.version, f.id)
            seen = out.get(key)
            out[key] = f if seen is None else replace(seen, locks=(*seen.locks, *f.locks))
    return list(out.values())


def problems(found: list[Finding], exceptions: list[dict], today: date) -> list[str]:
    """What fails the gate, one line each; empty when it passes."""
    out: list[str] = []
    valid: list[dict] = []
    for i, entry in enumerate(exceptions):
        missing = [f for f in FIELDS if not entry.get(f)]
        if missing:
            out.append(f"exception #{i + 1} ({entry.get('id', '?')}): missing {', '.join(missing)}")
        elif not isinstance(entry["expires"], date):
            out.append(f"exception {entry['id']}: expires must be a TOML date (YYYY-MM-DD)")
        else:
            valid.append(entry)

    used: set[int] = set()
    for f in found:
        match = next(
            (i for i, e in enumerate(valid)
             if e["id"] in f.names and str(e["package"]).lower() == f.package),
            None,
        )
        if match is None:
            fix = f"fixed in {', '.join(f.fix_versions)}" if f.fix_versions else "no fixed release"
            where = f" in {', '.join(f.locks)}" if f.locks else ""
            out.append(f"{f.package} {f.version}: {f.id} ({fix}){where}; upgrade it, or add a reviewed exception")
            continue
        used.add(match)
        entry = valid[match]
        if entry["expires"] < today:
            out.append(f"{f.package} {f.version}: exception {entry['id']} expired on {entry['expires']}")

    for i, entry in enumerate(valid):
        if i not in used:
            out.append(f"exception {entry['id']} ({entry['package']}) matches no finding; remove it")
    return out


def run_pip_audit(lock: Path) -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        report = Path(tmp) / "audit.json"
        # Exit 1 means findings, which the report holds; only a missing report is a failure.
        subprocess.run(
            [sys.executable, "-m", "pip_audit", "-r", str(lock), "--no-deps", "--disable-pip",
             "--progress-spinner", "off", "-f", "json", "-o", str(report)],
            check=False,
        )
        if not report.exists():
            raise SystemExit("pip_audit wrote no report; see its output above")
        return json.loads(report.read_text())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--report", type=Path, help="a JSON report from pip_audit instead of running it")
    parser.add_argument("--exceptions", type=Path, default=EXCEPTIONS)
    args = parser.parse_args(argv)

    if args.report:
        found = findings(json.loads(args.report.read_text()))
    else:
        found = merged([findings(run_pip_audit(lock), lock.relative_to(BACKEND.parent).as_posix()) for lock in LOCKS])
    exceptions = tomllib.loads(args.exceptions.read_text()).get("exception", [])
    lines = problems(found, exceptions, date.today())
    for line in lines:
        print(line)
    if lines:
        print(f"\n{len(lines)} problem(s). Exceptions live in {args.exceptions.name}.")
        return 1
    print(f"dependency audit: {len(found)} finding(s), all excepted and current")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
