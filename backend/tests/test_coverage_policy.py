"""Current collection policy reaches SQL coverage, the status API and the bell."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from tests.ops_contract_seed import NOW, _binding, _company, pin_ops_environment
from tracker import source_policy
from tracker.api.routers import ops
from tracker.config import get_settings
from tracker.db.models import Notification, ProviderPressureState
from tracker.notifications import coverage
from tracker.source_review import SOURCE_REVIEWS
from tracker.workflows import scheduler

pytestmark = [pytest.mark.asyncio, pytest.mark.usefixtures("no_escape")]


def _policy(monkeypatch, denied):
    settings = get_settings().model_copy(update={"sync_policy_denied_providers": frozenset(denied)})
    for module in (ops, scheduler, source_policy, coverage):
        monkeypatch.setattr(module, "get_settings", lambda: settings)


@pytest.mark.parametrize(("provider", "denied", "consent", "pressure", "automatic"), [
    ("greenhouse", True, None, None, False),
    ("greenhouse", True, None, "ready", False),
    ("greenhouse", True, None, "policy_denied", False),
    ("greenhouse", False, None, None, True),
    ("greenhouse", False, None, "ready", True),
    ("greenhouse", False, None, "paused", False),
    ("greenhouse", False, None, "policy_denied", False),
    ("google", False, None, None, False),
    ("google", False, None, "ready", False),
    ("google", False, SOURCE_REVIEWS["google"].wall_fingerprint, None, True),
    ("workday", False, None, None, False),
    ("workday", False, None, "ready", False),
])
async def test_coverage_and_rings_follow_current_policy_independently_of_cached_pressure(
    api_client, db_session, monkeypatch, tmp_path, provider, denied, consent, pressure, automatic,
):
    pin_ops_environment(monkeypatch, tmp_path)
    _policy(monkeypatch, {provider} if denied else set())
    company = _company("coverage-fixture", "Coverage Fixture", provider)
    company.consent_fingerprint = consent
    db_session.add(company)
    await db_session.flush()
    binding = _binding(company.slug, provider)
    db_session.add(binding)
    if pressure is not None:
        db_session.add(ProviderPressureState(pressure_key=provider, state=pressure))
    await db_session.commit()

    [item], outage = await coverage.coverage_report(db_session, NOW)
    assert item["company"] == company.slug
    assert item["automatic"] is automatic and item["stale"]
    assert coverage.rings(item, outage=outage) is automatic
    response = await api_client.get("/api/status")
    assert response.status_code == 200, response.text
    attention = response.json()["bindings_attention"]
    assert attention["followed"] == 1 and attention["automatic"] == int(automatic)
    assert attention["items"][0]["automatic"] is automatic
    assert not attention["outage"]

    assert await coverage.generate_coverage_notifications(db_session, now=NOW) == int(automatic)
    await db_session.commit()
    rows = list(await db_session.scalars(select(Notification).where(Notification.category == "coverage")))
    assert [row.source_id for row in rows] == ([binding.id] if automatic else [])


async def test_a_new_policy_denial_retracts_the_existing_coverage_notice(api_client, db_session, monkeypatch, tmp_path):
    pin_ops_environment(monkeypatch, tmp_path)
    _policy(monkeypatch, set())
    company = _company("coverage-fixture", "Coverage Fixture", "greenhouse")
    db_session.add(company)
    await db_session.flush()
    db_session.add(_binding(company.slug, "greenhouse"))
    await db_session.commit()
    assert await coverage.generate_coverage_notifications(db_session, now=NOW) == 1
    await db_session.commit()

    _policy(monkeypatch, {"greenhouse"})
    assert await coverage.generate_coverage_notifications(db_session, now=NOW) == 0
    await db_session.commit()
    assert not list(await db_session.scalars(select(Notification).where(Notification.category == "coverage")))
    response = await api_client.get("/api/status")
    assert response.status_code == 200, response.text
    assert response.json()["bindings_attention"]["automatic"] == 0
