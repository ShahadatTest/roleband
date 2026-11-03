"""The heartbeat names the kind and level of role the user looks for, as
taxonomy values only, and sending them widened what usage sharing covers."""

from __future__ import annotations

import pytest

from tests.usage_fixtures import share
from tracker.settings_store import set_persona_profile, set_role_answers
from tracker.taxonomy.role_answers import RoleAnswer
from tracker.usage_stats import registry
from tracker.usage_stats.batch import PERSON_PROPS
from tracker.usage_stats.consent import Status, get_sharing
from tracker.usage_stats.facts import heartbeat, target_craft
from tracker.usage_stats.registry import Event, Group

MACHINE = {"app_version": "0.1.0", "os": "macos", "arch": "arm64", "python": "3.12", "install_method": "source"}


@pytest.mark.parametrize(("answers", "craft"), [
    ((), None),
    ((RoleAnswer("technical", frozenset({"software_engineering"})),), "software_engineering"),
    ((RoleAnswer("technical", frozenset({"software_engineering"})), RoleAnswer("management", frozenset({"software_engineering"}))),
     "software_engineering"),
    ((RoleAnswer("technical", frozenset({"software_engineering", "data_science"})),), "several"),
    ((RoleAnswer("technical", None),), "any"),
])
def test_the_craft_is_one_family_several_or_any(answers, craft):
    assert target_craft(answers) == craft


@pytest.mark.asyncio
async def test_the_heartbeat_sends_the_target_as_catalogued_values_only(db_session):
    await set_role_answers(db_session, (RoleAnswer("product_program", frozenset({"product_management"})),))
    await set_persona_profile(db_session, {"experience_stage": "senior", "target_stage": "staff",
                                           "intent_statement": "Lead payments products at a fintech"})
    await db_session.commit()
    facts = await heartbeat(db_session, MACHINE)
    assert (facts["target_craft"], facts["target_seniority"]) == ("product_management", "staff")
    assert "fintech" not in str(facts), "the user's own words never leave"
    registry.validate("daily_heartbeat", facts)
    assert {"target_craft", "target_seniority"} <= set(PERSON_PROPS)


@pytest.mark.asyncio
async def test_a_user_who_shared_usage_before_is_asked_again_for_usage_only(db_session, sharing_allowed, monkeypatch):
    """Their consent was for the heartbeat without these two properties."""
    current = registry.CATALOGUE["daily_heartbeat"]
    before = Event(current.name, current.kind, current.group,
                   props={k: v for k, v in current.props.items() if k not in {"target_craft", "target_seniority"}},
                   required=current.required)
    monkeypatch.setattr(registry, "CATALOGUE", dict(registry.CATALOGUE) | {before.name: before})
    await share(db_session, Group.USAGE, Group.CRASHES)
    monkeypatch.undo()
    sharing = await get_sharing(db_session)
    assert sharing.status(Group.USAGE) is Status.STALE
    assert sharing.status(Group.CRASHES) is Status.SHARED
