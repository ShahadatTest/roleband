"""The shell learns that a matching-model job runs from `/api/status`.

Settings is where a model switch is watched; everywhere else, the status poll
the shell already makes says one is running. It must cost that poll no corpus
count and take no lock: a probe that acquired the re-embed lock, even for an
instant, could make a starting embedder's own attempt fail.

Real Postgres.
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.ops_contract_seed import pin_ops_environment
from tracker.config import get_settings
from tracker.platform.locks import advisory_lock_held, advisory_unlock, try_advisory_lock
from tracker.semantic import matching, provision

pytestmark = [pytest.mark.asyncio, pytest.mark.usefixtures("no_escape")]

KEY = get_settings().reembed_lock_key


def _other(db_session) -> AsyncSession:
    return async_sessionmaker(db_session.bind, expire_on_commit=False)()


async def test_the_probe_sees_a_lock_held_elsewhere_and_takes_nothing(db_session):
    async with _other(db_session) as holder, _other(db_session) as embedder:
        assert not await advisory_lock_held(db_session, KEY)
        assert await try_advisory_lock(holder, KEY)
        try:
            assert await advisory_lock_held(db_session, KEY)
            assert not await advisory_lock_held(db_session, KEY + 1), "another key is another lock"
        finally:
            await advisory_unlock(holder, KEY)
        assert not await advisory_lock_held(db_session, KEY)
        # Probing left the lock free for whoever starts next.
        assert await try_advisory_lock(embedder, KEY)
        await advisory_unlock(embedder, KEY)


def _weights(monkeypatch, status: str) -> None:
    monkeypatch.setattr(provision, "resolve_tier", lambda: "int8")
    monkeypatch.setattr(provision, "provision_state", lambda _spec, tier: provision.ProvisionState(status, tier, 1, 2))


@pytest.mark.parametrize(("weights", "pid", "locked", "phase"), [
    ("downloading", False, False, "downloading"),
    ("ready", True, False, "converting"),
    ("ready", False, True, "converting"),
    ("ready", False, False, "none"),
    ("missing", False, False, "none"),
])
async def test_the_phase_is_read_from_the_weights_and_the_lock(db_session, monkeypatch, weights, pid, locked, phase):
    _weights(monkeypatch, weights)
    async with _other(db_session) as holder:
        if locked:
            assert await try_advisory_lock(holder, KEY)
        try:
            assert await matching.running_phase(db_session, requested=pid) == phase
        finally:
            if locked:
                await advisory_unlock(holder, KEY)


async def test_status_says_a_model_job_is_running(api_client, db_session, monkeypatch, tmp_path):
    pin_ops_environment(monkeypatch, tmp_path)
    _weights(monkeypatch, "downloading")
    body = (await api_client.get("/api/status")).json()
    assert body["matching_switch"] == "downloading"

    _weights(monkeypatch, "ready")
    async with _other(db_session) as holder:
        assert await try_advisory_lock(holder, KEY)
        try:
            assert (await api_client.get("/api/status")).json()["matching_switch"] == "converting"
        finally:
            await advisory_unlock(holder, KEY)
    assert (await api_client.get("/api/status")).json()["matching_switch"] == "none"
