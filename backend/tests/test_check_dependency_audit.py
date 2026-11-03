"""The dependency audit fails on any finding that no current, reviewed exception covers."""

from __future__ import annotations

import tomllib
from datetime import date

from scripts.check_dependency_audit import EXCEPTIONS, FIELDS, findings, main, problems

TODAY = date(2026, 10, 19)


def _report(*vulns: tuple[str, str, str, list[str]]) -> dict:
    """A `pip_audit -f json` report: (package, version, id, aliases) per advisory."""
    deps: dict[tuple[str, str], list[dict]] = {}
    for package, version, vid, aliases in vulns:
        deps.setdefault((package, version), []).append({"id": vid, "aliases": aliases, "fix_versions": ["9.9.9"]})
    return {"dependencies": [
        {"name": "Clean", "version": "1.0", "vulns": []},
        *({"name": p, "version": v, "vulns": vs} for (p, v), vs in deps.items()),
    ]}


def _exception(vid: str = "PYSEC-1", package: str = "starlette", expires: date = date(2026, 11, 1)) -> dict:
    return {"id": vid, "package": package, "reason": "loopback only", "expires": expires}


def test_a_clean_report_passes():
    assert problems(findings(_report()), [], TODAY) == []


def test_a_finding_with_no_exception_fails_naming_the_package_and_the_fix():
    out = problems(findings(_report(("starlette", "0.41.3", "PYSEC-1", ["GHSA-a"]))), [], TODAY)
    assert len(out) == 1 and "starlette 0.41.3: PYSEC-1" in out[0] and "9.9.9" in out[0]


def test_a_current_exception_accepts_its_finding_by_id_or_by_alias():
    found = findings(_report(("Starlette", "0.41.3", "PYSEC-1", ["GHSA-a"])))
    assert problems(found, [_exception()], TODAY) == []
    assert problems(found, [_exception(vid="GHSA-a")], TODAY) == []


def test_an_exception_for_another_package_does_not_accept_the_finding():
    """Advisory ids are per package in practice, but the entry names its package
    and the match holds it to that: an id copied onto the wrong line passes nothing."""
    out = problems(findings(_report(("starlette", "0.41.3", "PYSEC-1", []))), [_exception(package="fastapi")], TODAY)
    assert any("starlette 0.41.3: PYSEC-1" in line for line in out)
    assert any("matches no finding" in line for line in out)


def test_an_expired_exception_fails_and_one_expiring_today_still_holds():
    found = findings(_report(("starlette", "0.41.3", "PYSEC-1", [])))
    assert problems(found, [_exception(expires=TODAY)], TODAY) == []
    out = problems(found, [_exception(expires=date(2026, 10, 18))], TODAY)
    assert out == ["starlette 0.41.3: exception PYSEC-1 expired on 2026-10-18"]


def test_an_exception_matching_nothing_fails_so_the_list_shrinks():
    out = problems(findings(_report()), [_exception()], TODAY)
    assert out == ["exception PYSEC-1 (starlette) matches no finding; remove it"]


def test_an_entry_missing_a_field_or_with_a_text_date_fails_and_accepts_nothing():
    found = findings(_report(("starlette", "0.41.3", "PYSEC-1", [])))
    no_reason = {**_exception(), "reason": ""}
    out = problems(found, [no_reason], TODAY)
    assert "missing reason" in out[0] and any("starlette 0.41.3: PYSEC-1" in line for line in out)
    text_date = {**_exception(), "expires": "2026-11-01"}
    assert "TOML date" in problems(found, [text_date], TODAY)[0]


def test_the_committed_exception_list_parses_and_every_entry_is_complete():
    entries = tomllib.loads(EXCEPTIONS.read_text()).get("exception", [])
    for entry in entries:
        assert all(entry.get(f) for f in FIELDS), entry
        assert isinstance(entry["expires"], date), entry


def test_the_command_exits_one_on_a_finding_and_zero_once_it_is_excepted(tmp_path, capsys):
    import json

    report = tmp_path / "audit.json"
    report.write_text(json.dumps(_report(("starlette", "0.41.3", "PYSEC-1", [])), default=str))
    empty = tmp_path / "none.toml"
    empty.write_text("")
    assert main(["--report", str(report), "--exceptions", str(empty)]) == 1
    assert "PYSEC-1" in capsys.readouterr().out

    listed = tmp_path / "listed.toml"
    listed.write_text('[[exception]]\nid = "PYSEC-1"\npackage = "starlette"\n'
                      'reason = "loopback only"\nexpires = 2999-01-01\n')
    assert main(["--report", str(report), "--exceptions", str(listed)]) == 0


def test_every_lock_an_install_or_the_mac_app_uses_is_audited():
    """A pin that only the macOS lock or the app's runtime lock carries still ships:
    the audit reads every platform lock and the app's runtime lock, not only CI's."""
    from scripts.check_dependency_audit import BACKEND, LOCKS

    expected = {*(BACKEND / "constraints").glob("*.txt"), BACKEND.parent / "launcher" / "macos" / "runtime-lock.txt"}
    assert set(LOCKS) == expected
    assert all(lock.is_file() for lock in LOCKS)


def test_a_finding_only_in_the_mac_runtime_lock_fails_the_command(monkeypatch, capsys):
    from scripts import check_dependency_audit as audit

    def run(lock):
        if lock.name == "runtime-lock.txt":
            return _report(("setuptools", "83.0.0", "GHSA-xmj3-9gf7-h52w", []))
        return _report()

    monkeypatch.setattr(audit, "run_pip_audit", run)
    assert audit.main(["--exceptions", str(EXCEPTIONS)]) == 1
    out = capsys.readouterr().out
    assert "setuptools 83.0.0: GHSA-xmj3-9gf7-h52w" in out and "runtime-lock.txt" in out


def test_a_pin_shared_by_several_locks_is_one_finding_naming_each_lock():
    from scripts.check_dependency_audit import merged

    report = _report(("starlette", "0.41.3", "PYSEC-1", []))
    found = merged([findings(report, "a.txt"), findings(report, "b.txt"), findings(_report(), "c.txt")])
    out = problems(found, [], TODAY)
    assert len(out) == 1 and "in a.txt, b.txt" in out[0]
    assert problems(found, [_exception()], TODAY) == []
