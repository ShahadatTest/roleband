"""Preparation stays observable before any database connection is possible."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from tracker.platform import preparation


@pytest.mark.asyncio
async def test_engine_identity_health_does_not_open_a_database(monkeypatch):
    from tracker.api.app import app
    from tracker.db import session

    def unavailable(*args, **kwargs):
        raise AssertionError("health must not open a database")

    monkeypatch.setattr(session, "get_session_factory", unavailable)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://127.0.0.1") as client:
        response = await client.get("/api/launcher-health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["launcher"]["product"] == "roleband"
    assert len(body["launcher"]["instance"]) == 24
    assert body["preparation"] is None


def test_preparation_progress_is_atomic_and_refuses_a_symbolic_link(tmp_path):
    data = tmp_path / "app data"
    preparation.update(data, database="creating")
    preparation.update(data, database="ready", model="downloading", downloaded_bytes=17, total_bytes=100)
    state = preparation.read(data)
    assert state.database == "ready" and state.downloaded_bytes == 17
    assert not state.ready
    preparation.update(data, service="ready")
    assert preparation.read(data).ready
    assert not list((data / "launcher").glob(".preparation-*"))
    foreign = tmp_path / "foreign"
    foreign.mkdir()
    linked = tmp_path / "linked"
    linked.symlink_to(foreign, target_is_directory=True)
    with pytest.raises(ValueError):
        preparation.update(linked, database="creating")
    assert not list(foreign.iterdir())


def test_missing_or_malformed_progress_cannot_claim_readiness(tmp_path):
    import json

    from tracker.platform.launcher import installation_identity

    identity = installation_identity(tmp_path, api_host="127.0.0.1", api_port=58329, version="0.1.0")
    assert preparation.payload(tmp_path, identity)["preparation"]["database"] == "waiting"
    preparation.update(tmp_path, database="ready", service="ready")
    path = tmp_path / "launcher/preparation.json"
    state = json.loads(path.read_text())
    state["downloaded_bytes"] = True
    path.write_text(json.dumps(state))
    assert preparation.read(tmp_path) is None
    assert preparation.payload(tmp_path, identity)["preparation"]["database"] == "waiting"


def test_bootstrap_answers_before_migration_and_releases_the_port(tmp_path, monkeypatch):
    import http.client
    import json
    import socket
    from types import SimpleNamespace

    from tracker.supervisor import prepare

    with socket.socket() as available:
        available.bind(("127.0.0.1", 0))
        port = available.getsockname()[1]
    data = tmp_path / "home" / ".roleband"
    monkeypatch.setenv("HOME", str(data.parent))
    settings = SimpleNamespace(api_host="127.0.0.1", api_port=port, database_url_override="",
                               db_embedded=True, embedded_pgdata=lambda: data / "db")
    monkeypatch.setattr(prepare, "get_settings", lambda: settings)
    monkeypatch.setattr(prepare, "DATA_DIR", data)

    def migrate(arguments, **kwargs):
        assert arguments[-1] == "prepare-database" and "-I" in arguments
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
        try:
            connection.request("GET", "/api/launcher-health")
            response = connection.getresponse()
            body = json.loads(response.read())
            assert response.status == 200
            assert body["preparation"]["database"] == "creating"
            assert body["launcher"]["api_origin"] == f"http://127.0.0.1:{port}"
            assert not (data / "db/PG_VERSION").exists()
            connection.request("GET", "/api/launcher-health", headers={"Host": "outside.invalid"})
            response = connection.getresponse()
            assert response.status == 400
            response.read()
            connection.request("GET", "/api/status")
            response = connection.getresponse()
            assert response.status == 404
            response.read()
        finally:
            connection.close()

    monkeypatch.setattr(prepare.subprocess, "run", migrate)
    prepare.run()
    assert preparation.read(data).database == "ready"
    with socket.socket() as available:
        available.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        available.bind(("127.0.0.1", port))


def test_first_open_refuses_a_foreign_database_without_writing_progress(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from tracker.platform.embedded_db import ClusterOwnedElsewhere
    from tracker.supervisor import prepare

    data = tmp_path / "home" / ".roleband"
    monkeypatch.setenv("HOME", str(data.parent))
    pgdata = data / "db"
    pgdata.mkdir(parents=True)
    (pgdata / "PG_VERSION").write_text("16\n")
    (pgdata / "history").write_text("irreplaceable observations")
    settings = SimpleNamespace(database_url_override="", db_embedded=True, embedded_pgdata=lambda: pgdata)
    monkeypatch.setattr(prepare, "get_settings", lambda: settings)
    monkeypatch.setattr(prepare, "DATA_DIR", data)
    with pytest.raises(ClusterOwnedElsewhere):
        prepare.run()
    assert (pgdata / "history").read_text() == "irreplaceable observations"
    assert not (data / "launcher").exists()
    assert not (data / "db.owner.json").exists()
