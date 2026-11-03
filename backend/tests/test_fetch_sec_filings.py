"""The SEC fetcher declares who is asking and never mistakes a refusal for absence.

The SEC's fair-access policy asks an automated client to name a contact in its
User-Agent; without one it may refuse, and a refusal read as "no filings"
leaves the pay dataset silently short while the command reports success.
Mocked transport: nothing here reaches the SEC.
"""

from __future__ import annotations

import json

import httpx
import pytest

from scripts import fetch_sec_filings as sec

SUBMISSIONS = {"filings": {"recent": {
    "form": ["10-K"], "accessionNumber": ["0001-26-000001"], "filingDate": ["2026-02-01"],
    "reportDate": ["2025-12-31"], "primaryDocument": ["annual.htm"],
}}}


def _run(monkeypatch, tmp_path, answers: dict[str, int], *, contact: str | None = "ops@example.com"):
    """Run the command over one company, each URL kind answered by its status."""
    company = sorted(json.loads(sec.COMPANIES.read_text()))[0]
    agents: list[str] = []

    def handle(request: httpx.Request) -> httpx.Response:
        agents.append(request.headers["user-agent"])
        kind = ("facts" if "companyfacts" in request.url.path else
                "submissions" if "submissions" in request.url.path else "annual")
        status = answers.get(kind, 200)
        body = SUBMISSIONS if kind == "submissions" and status == 200 else {}
        return httpx.Response(status, json=body)

    real = httpx.Client
    monkeypatch.setattr(sec.httpx, "Client", lambda **kw: real(transport=httpx.MockTransport(handle), **kw))
    monkeypatch.setattr(sec, "_DELAY", 0)
    monkeypatch.delenv(sec.CONTACT_ENV, raising=False)
    args = [company, "--dir", str(tmp_path)] + (["--contact", contact] if contact else [])
    return sec.main(args), agents


def test_every_request_declares_the_operator_s_contact(monkeypatch, tmp_path):
    code, agents = _run(monkeypatch, tmp_path, {})
    assert code == 0
    assert agents and all(a.endswith("ops@example.com") for a in agents)


def test_no_contact_is_a_clear_refusal_before_any_request(monkeypatch, tmp_path):
    with pytest.raises(SystemExit, match="ROLEBAND_SEC_CONTACT"):
        _run(monkeypatch, tmp_path, {}, contact=None)


@pytest.mark.parametrize(("answers", "code"), [
    ({"facts": 404}, 0),          # a company with no XBRL facts: absent, not refused
    ({"facts": 403}, 1),          # the SEC refused us
    ({"submissions": 429}, 1),    # throttled
    ({"annual": 503}, 1),         # a report it would not serve
])
def test_a_refusal_fails_the_command_and_a_404_does_not(monkeypatch, tmp_path, capsys, answers, code):
    assert _run(monkeypatch, tmp_path, answers)[0] == code
    assert ("REFUSED" in capsys.readouterr().err) is bool(code)
