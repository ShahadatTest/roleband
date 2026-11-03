"""Every error the API answers on purpose is a code (tracker/api/errors.py).

The dashboard says errors in the reader's language from `error-<code>`
messages; English in a `detail` would reach the screen verbatim. So no module under `tracker/api` builds an
`HTTPException` itself: a router raises `api_error(...)`."""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

from tracker.api.errors import ErrorCode, ErrorDetail, api_error

API = Path(__file__).resolve().parents[1] / "tracker" / "api"


def raw_http_exceptions() -> list[str]:
    found = []
    for path in sorted(API.rglob("*.py")):
        if path.name == "errors.py":
            continue
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "HTTPException":
                found.append(f"{path.relative_to(API.parent.parent)}:{node.lineno}")
    return found


def test_no_router_builds_an_http_exception_itself():
    assert raw_http_exceptions() == []


def test_the_scan_sees_a_raw_exception(tmp_path, monkeypatch):
    planted = tmp_path / "tracker" / "api"
    planted.mkdir(parents=True)
    (planted / "probe.py").write_text('raise HTTPException(status_code=404, detail="job not found")\n')
    monkeypatch.setattr(sys.modules[__name__], "API", planted)
    assert raw_http_exceptions() == ["tracker/api/probe.py:1"]


def test_codes_are_kebab_case_and_distinct():
    values = [code.value for code in ErrorCode]
    assert len(values) == len(set(values))
    assert all(re.fullmatch(r"[a-z]+(-[a-z]+)*", v) for v in values), values


def test_an_error_carries_its_code_params_and_english_for_logs():
    error = api_error(409, ErrorCode.SCHEDULING_UNAVAILABLE, "paused: google", companies=["google"])
    assert error.status_code == 409
    assert error.detail == {"code": "scheduling-unavailable", "params": {"companies": ["google"]}, "message": "paused: google"}
    ErrorDetail.model_validate(error.detail)
