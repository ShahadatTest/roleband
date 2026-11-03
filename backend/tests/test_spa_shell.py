"""The built-dashboard shell must never be served from a stale cache.

`index.html` names the hashed bundle for a specific build. If a browser is
allowed to reuse an old shell it will either render a build that is not
on disk, or 404 its own script tag — both of which look exactly like
"my change did not deploy". The hashed assets under /assets are the opposite
case: their name IS their version, so they stay freely cacheable.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tracker.api.routers import spa


@pytest.fixture()
def built_dashboard(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A minimal `dashboard/dist` the SPA router will serve."""
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text(
        '<!doctype html><script src="/assets/index-abc123.js"></script>',
        encoding="utf-8",
    )
    (dist / "assets" / "index-abc123.js").write_text("console.log(1)", encoding="utf-8")
    monkeypatch.setattr(spa, "DASHBOARD_DIST", dist)
    return dist


@pytest.fixture()
def client(built_dashboard: Path) -> TestClient:
    app = FastAPI()
    app.include_router(spa.router)
    return TestClient(app)


def test_shell_is_revalidated_on_every_load(client: TestClient) -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-cache"


def test_client_routes_get_the_same_revalidating_shell(client: TestClient) -> None:
    # A deep link is the shell too, so it carries the same guarantee.
    response = client.get("/settings/companies")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-cache"
    assert "index-abc123.js" in response.text


def test_a_rebuilt_shell_is_served_not_the_previous_one(
    client: TestClient, built_dashboard: Path
) -> None:
    """The regression this header exists for: rebuild, then read the shell."""
    assert "index-abc123.js" in client.get("/").text
    (built_dashboard / "index.html").write_text(
        '<!doctype html><script src="/assets/index-def456.js"></script>',
        encoding="utf-8",
    )
    body = client.get("/").text
    assert "index-def456.js" in body
    assert "index-abc123.js" not in body


def test_hashed_assets_are_not_forced_to_revalidate(client: TestClient) -> None:
    # Their filename is their version; making these no-cache would throw away
    # the whole point of hashing them.
    response = client.get("/assets/index-abc123.js")
    assert response.status_code == 200
    assert response.headers.get("cache-control") != "no-cache"


def test_unknown_api_path_still_404s_instead_of_returning_the_shell(
    client: TestClient,
) -> None:
    response = client.get("/api/definitely-not-a-route")
    assert response.status_code == 404
    assert "<!doctype html>" not in response.text.lower()


def test_serving_headlessly_still_404s(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(spa, "DASHBOARD_DIST", tmp_path / "absent")
    app = FastAPI()
    app.include_router(spa.router)
    assert TestClient(app).get("/").status_code == 404


def _directives(header: str) -> dict[str, list[str]]:
    return {name: values for name, *values in (part.split() for part in header.split(";"))}


@pytest.mark.parametrize("path", ["/", "/settings/companies"])
def test_the_shell_is_served_under_a_policy_that_allows_this_origin_s_scripts_alone(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, path: str
) -> None:
    """Where the page talks is enforced by the browser, not by review: scripts
    from this origin only, and connections to this origin and the configured
    usage-statistics host's origin alone."""
    from tracker.config import get_settings

    monkeypatch.setattr(get_settings(), "usage_stats_host", "https://stats.example.test/ingest")
    policy = _directives(client.get(path).headers["content-security-policy"])
    assert policy["script-src"] == ["'self'"]
    assert policy["connect-src"] == ["'self'", "https://stats.example.test"]
    assert policy["object-src"] == ["'none'"] and policy["frame-ancestors"] == ["'none'"]
    assert "'unsafe-eval'" not in sum(policy.values(), [])


def test_the_policy_file_names_every_directive_once_and_the_host_by_placeholder() -> None:
    import json

    from tracker.api.csp import POLICY_FILE

    directives = json.loads(POLICY_FILE.read_text())["directives"]
    assert "{usage_host}" in directives["connect-src"]
    assert all("unsafe" not in value for value in directives["script-src"])
