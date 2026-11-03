"""The loopback trust boundary: what may reach an API that authenticates nobody.

One user, one machine, bound to 127.0.0.1 — that is the whole security model,
and it holds only while a web page the user happens to visit cannot cross the
loopback. A page can, two ways, and CORS sees neither:

* DNS rebinding. A hostile name re-resolves to 127.0.0.1 after its page has
  loaded; the page is then SAME-origin with this API, so CORS never runs. The
  Host header still carries the hostile name.
* A cross-site simple request. A form, or a `no-cors` fetch, POSTs with no
  preflight. The attacker never reads the answer, but the side effect lands.
  "The mutating routes take JSON bodies" is not the defence: many unsafe
  routes take no body at all, among them `POST /api/sync/cancel` and
  `POST /api/intelligence/cloud-models/{profile_id}/test`, which is billed.

Every request goes through the real app. If a boundary fails, a handler can
start processes or send outbound HTTP, so `no_escape` refuses both.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route

from tracker.config import Settings
from tracker.db.models import Job

pytestmark = pytest.mark.asyncio

_ROUTES = json.loads((Path(__file__).parent / "fixtures" / "route_table.json").read_text())["routes"]
UNSAFE_ROUTES = [(r["method"], r["path"]) for r in _ROUTES if r["method"] not in {"GET", "HEAD", "OPTIONS"}]

#: What a page may send with no preflight (the Fetch standard's CORS-safelisted
#: `Content-Type` values), each with a body a real attack would carry. The
#: `text/plain` one is the classic JSON-in-a-form trick.
SIMPLE_BODIES = {
    "application/x-www-form-urlencoded": b"enabled=true",
    "multipart/form-data; boundary=nl": (
        b'--nl\r\nContent-Disposition: form-data; name="enabled"\r\n\r\ntrue\r\n--nl--\r\n'
    ),
    "text/plain": b'{"enabled": true}',
}


def _url(path: str) -> str:
    """A requestable URL for a templated route. The boundary answers before routing."""
    return re.sub(r"\{[^}]+\}", "1", path)


async def _answer(client, method: str, path: str, **kwargs) -> int | str:
    """The status, or the exception a handler raised — which means it was reached."""
    try:
        return (await client.request(method, _url(path), **kwargs)).status_code
    except Exception as exc:  # noqa: BLE001 - reaching the handler at all is the finding
        return type(exc).__name__


async def _viewed_at(db_session, job: Job):
    return (await db_session.execute(select(Job.viewed_at).where(Job.id == job.id))).scalar_one()


@pytest_asyncio.fixture
async def job(db_session):
    now = datetime.now(UTC)
    row = Job(
        company="google", req_id="4410", dedupe_key="google:4410",
        title="Staff Product Manager, Search", url="https://careers.google.com/jobs/4410",
        level_band="staff", family="product_management", track="product_program",
        locations=["Mountain View, CA, USA"], location_groups=["silicon_valley"],
        status="open", in_scope=True, first_seen=now, last_seen=now,
    )
    db_session.add(row)
    await db_session.commit()
    return row


# --------------------------------------------------------------------------- #
# DNS rebinding: the Host header is the only thing that differs
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "host",
    [
        "evil.example",
        "evil.example:8010",
        "localhost.evil.example:8010",  # a loopback name as a PREFIX is still theirs
        "127.0.0.1.nip.io:8010",  # a wildcard-DNS name that resolves to loopback
        "[::1].evil.example:8010",  # not a bracketed literal, however it starts
    ],
)
async def test_a_request_naming_a_foreign_host_is_refused(api_client, no_escape, host):
    response = await api_client.get("/api/status", headers={"Host": host})
    assert response.status_code == 400, f"Host {host!r} was served"


@pytest.mark.parametrize(
    "host",
    ["127.0.0.1:8010", "localhost:8010", "[::1]:8010", "localhost:5173", "127.0.0.1", "LOCALHOST:8010"],
)
async def test_every_name_this_machine_answers_to_is_served(api_client, host):
    """The control: a guard that refused everything would pass the test above.

    IPv6 loopback must be accepted too: splitting a Host header at its first
    colon turns `[::1]:8010` into `[` and rejects a valid local host."""
    response = await api_client.get("/api/health", headers={"Host": host})
    assert response.status_code == 200, f"Host {host!r} was refused"


async def test_a_rebound_page_cannot_mark_a_role_viewed(api_client, db_session, no_escape, job):
    """The rebinding attack whole: to the browser, this page IS the API's origin."""
    response = await api_client.post(
        f"/api/jobs/{job.id}/view",
        json={},
        headers={"Host": "evil.example:8010", "Origin": "http://evil.example:8010"},
    )
    assert response.status_code == 400
    assert await _viewed_at(db_session, job) is None


# --------------------------------------------------------------------------- #
# Cross-site simple requests: no preflight, unreadable answer, real side effect
# --------------------------------------------------------------------------- #


async def test_a_cross_site_form_cannot_mark_a_role_viewed(api_client, db_session, no_escape, job):
    """`<form method=post action=http://127.0.0.1:8010/api/jobs/1/view>` on any site."""
    response = await api_client.post(
        f"/api/jobs/{job.id}/view",
        content=b"",
        headers={"Content-Type": "application/x-www-form-urlencoded", "Origin": "https://evil.example"},
    )
    assert not response.is_success, response.text
    assert await _viewed_at(db_session, job) is None


@pytest.mark.parametrize("content_type", sorted(SIMPLE_BODIES))
async def test_no_unsafe_route_accepts_a_body_a_page_can_send_without_preflight(
    api_client, no_escape, content_type
):
    """Walks the frozen route table, so a route added later is covered by default.

    No Origin header: this is the belt to the Origin braces below, for a client
    that omits it. The dashboard sends `application/json` or no body at all
    (`src/api/transport.ts` `requestJSON`), never one of these.
    """
    reached = {}
    for method, path in UNSAFE_ROUTES:
        got = await _answer(
            api_client, method, path,
            content=SIMPLE_BODIES[content_type], headers={"Content-Type": content_type},
        )
        if got != 415:
            reached[f"{method} {path}"] = got
    assert not reached, (
        f"{len(reached)} of {len(UNSAFE_ROUTES)} unsafe routes did not refuse "
        f"{content_type} with 415: {reached}"
    )


@pytest.mark.parametrize(
    "origin",
    [
        "https://evil.example",
        "http://localhost.evil.example:5173",
        "null",  # what a sandboxed iframe or a data: URL sends
    ],
)
async def test_no_unsafe_route_accepts_a_request_from_a_foreign_page(api_client, no_escape, origin):
    """A browser names the page behind every non-GET request in `Origin`."""
    reached = {}
    for method, path in UNSAFE_ROUTES:
        got = await _answer(api_client, method, path, json={}, headers={"Origin": origin})
        if got != 403:
            reached[f"{method} {path}"] = got
    assert not reached, (
        f"{len(reached)} of {len(UNSAFE_ROUTES)} unsafe routes did not refuse Origin "
        f"{origin!r} with 403: {reached}"
    )


@pytest.mark.parametrize(
    ("host", "origin"),
    [
        ("127.0.0.1:8010", "http://127.0.0.1:8010"),  # the built dashboard, served by this API
        ("127.0.0.1:8010", "http://localhost:5173"),  # Vite's proxy: changeOrigin rewrites Host, not Origin
        ("127.0.0.1:8010", "http://127.0.0.1:5174"),  # a second dev server on another port
        ("localhost:5173", "http://localhost:5173"),  # a proxy that keeps the browser's Host
        ("127.0.0.1:8010", None),  # curl and scripts: no browser, no Origin
    ],
)
async def test_the_dashboards_own_writes_still_land(api_client, db_session, job, host, origin):
    """The control for both walks above. Mirrors `src/api/transport.ts`: a body-less PUT, and a
    POST whose default body is `{}` as JSON."""
    headers = {"Host": host} | ({"Origin": origin} if origin else {})
    favorite = await api_client.put(f"/api/jobs/{job.id}/favorite", headers=headers)
    assert favorite.status_code == 200, favorite.text
    viewed = await api_client.post(f"/api/jobs/{job.id}/view", json={}, headers=headers)
    assert viewed.status_code == 200, viewed.text
    assert await _viewed_at(db_session, job) is not None


async def test_an_operator_can_add_a_host_but_never_loses_the_loopback(monkeypatch):
    """`ROLEBAND_API_TRUSTED_HOSTS` EXTENDS the set. Were it to replace it, an
    operator naming their LAN host would lock out the watchdog, which checks
    health at `api_host` — 127.0.0.1 by default — and restarts what it cannot reach."""
    # A local import keeps other boundary tests collectable when this symbol is absent.
    from tracker.api.boundary import LoopbackBoundary

    monkeypatch.setenv("ROLEBAND_API_TRUSTED_HOSTS", '["Mybox.local."]')
    settings = Settings(_env_file=None)
    assert settings.api_trusted_hosts == ["Mybox.local."]

    inner = Starlette(routes=[Route("/api/health", lambda _request: PlainTextResponse("ok"))])
    guarded = LoopbackBoundary(inner, trusted_hosts=[settings.api_host, *settings.api_trusted_hosts])
    async with AsyncClient(transport=ASGITransport(app=guarded), base_url="http://127.0.0.1:8010") as client:
        for host, expected in [
            ("mybox.local:8010", 200),
            ("127.0.0.1:8010", 200),
            ("[::1]:8010", 200),
            ("otherbox.local:8010", 400),
        ]:
            got = (await client.get("/api/health", headers={"Host": host})).status_code
            assert got == expected, f"Host {host!r}: {got}"


async def test_the_dev_servers_preflight_is_still_answered(api_client):
    response = await api_client.options(
        "/api/settings",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "PUT",
            "Host": "127.0.0.1:8010",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
