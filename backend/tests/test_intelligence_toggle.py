"""The Apple Intelligence toggle: DB row is the source of truth, env is the default.

The toggle and device availability are INDEPENDENT — a user can turn it on while
the Mac still can't run a model. `build_provider` must reflect the toggle, and the
provider must then report the device reason (not "turned off").
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from tests.factories import Upserted
from tracker import settings_store
from tracker.db.models import AppSetting
from tracker.intelligence.apple_fm import AppleFMProvider
from tracker.intelligence.provider import AvailabilityState
from tracker.intelligence.registry import build_provider


@dataclass
class _Row:
    value: dict


class FakeSession:
    """Minimal AppSetting store: `get` by key."""

    def __init__(self, row=None):
        self._row = row
        self.executed = []

    async def get(self, model, key):
        assert model is AppSetting
        return self._row

    async def execute(self, stmt):
        self.executed.append(stmt)
        return Upserted(stmt)


def test_defaults_to_env_setting_when_no_row(monkeypatch):
    monkeypatch.setattr(
        settings_store, "get_settings", lambda: type("S", (), {"apple_fm_enabled": False})()
    )
    assert asyncio.run(settings_store.get_apple_fm_enabled(FakeSession(None))) is False

    monkeypatch.setattr(
        settings_store, "get_settings", lambda: type("S", (), {"apple_fm_enabled": True})()
    )
    assert asyncio.run(settings_store.get_apple_fm_enabled(FakeSession(None))) is True


def test_db_row_overrides_env(monkeypatch):
    # Env says off, user turned it on -> DB wins.
    monkeypatch.setattr(
        settings_store, "get_settings", lambda: type("S", (), {"apple_fm_enabled": False})()
    )
    session = FakeSession(_Row(value={"enabled": True}))
    assert asyncio.run(settings_store.get_apple_fm_enabled(session)) is True

    # Env says on, user turned it off -> DB wins.
    monkeypatch.setattr(
        settings_store, "get_settings", lambda: type("S", (), {"apple_fm_enabled": True})()
    )
    session = FakeSession(_Row(value={"enabled": False}))
    assert asyncio.run(settings_store.get_apple_fm_enabled(session)) is False


def test_malformed_row_falls_back_to_env(monkeypatch):
    monkeypatch.setattr(
        settings_store, "get_settings", lambda: type("S", (), {"apple_fm_enabled": True})()
    )
    assert asyncio.run(settings_store.get_apple_fm_enabled(FakeSession(_Row(value={})))) is True
    assert (
        asyncio.run(settings_store.get_apple_fm_enabled(FakeSession(_Row(value="junk")))) is True
    )


def test_set_issues_an_upsert():
    session = FakeSession(None)
    assert asyncio.run(settings_store.set_apple_fm_enabled(session, True)) is True
    assert len(session.executed) == 1


def test_toggle_on_yields_apple_provider_reporting_device_state():
    p = build_provider(enabled=True)
    assert isinstance(p, AppleFMProvider)
    # With the toggle ON, availability must describe the DEVICE (ready, no SDK,
    # ineligible, ...) and never "turned off" — that is what lets the UI tell the
    # user why it can't run. The concrete state depends on the host, so we assert
    # the invariant rather than a machine-specific value.
    assert asyncio.run(p.availability()).state is not AvailabilityState.DISABLED_BY_FLAG
