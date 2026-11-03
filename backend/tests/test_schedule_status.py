"""The schedule projection, exercised without HTTP.

`/api/schedule` and `/api/status` are projections of stored rows: a roster, its
bindings, their schedule rows and provider pressure, read against a clock. Four
claims live here, each one a thing the router cannot decide on its own:

1. **The status ladder is ordered.** Every row below satisfies more than one
   condition at once, so a reordered ladder answers differently — which a table
   of one-condition cases would not notice.
2. **A blocked provider has no eligible time**, whatever deadline is stored.
3. **One vocabulary for "blocked".** `BLOCKED_PROVIDER_STATES`, the dispatcher's
   two constants and the wire Literals must name the same pair.
4. **The projection reads no clock and no settings of its own.** The ops
   contract pins `routers/ops.py`'s `datetime` and `get_settings`; a projection
   that fetched its own would answer from the real machine inside a pinned test.

Observed, not changed: `schedule_payload` overlays
`collection_access` on the stored provider state, and `scheduler_status` does
not — so a provider denied by policy but `ready` in the pressure table reads
`policy_denied` on `/api/schedule` and schedulable on `/api/status`.
"""

from __future__ import annotations

import ast
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import get_args

import pytest

from tracker.api.schemas.ops import ExcludedBinding, ScheduleBindingPayload
from tracker.db.models import ProviderPressureState, SourceBinding, SyncScheduleState
from tracker.workflows import scheduler
from tracker.workflows.schedule_status import (
    BLOCKED_PROVIDER_STATES,
    blocks_by_provider,
    eligible_schedule_at,
    manual_block_reason,
    schedule_payload,
)

BACKEND = Path(__file__).resolve().parents[1]
OWNER = BACKEND / "tracker" / "workflows" / "schedule_status.py"

NOW = datetime(2026, 7, 20, 12, 0, tzinfo=UTC)
PAST = NOW - timedelta(hours=1)
FUTURE = NOW + timedelta(hours=4)

SETTINGS = SimpleNamespace(
    sync_scheduler_enabled=True,
    sync_scheduler_max_providers=2,
    sync_authoritative_stale_hours=30,
    sync_policy_denied_providers=frozenset({"meta"}),
)


def _binding() -> SourceBinding:
    return SourceBinding(
        id=1,
        company_slug="google",
        connector_id="google",
        status="stable",
        closure_capability="authoritative",
    )


def _state(*, manual: datetime | None) -> SyncScheduleState:
    return SyncScheduleState(
        binding_id=1,
        provider_key="google",
        discovery_enabled=True,
        discovery_cadence_seconds=21_600,
        reconcile_cadence_seconds=86_400,
        last_discovery_at=PAST,
        last_reconcile_at=PAST,
        next_discovery_at=FUTURE,
        next_reconcile_at=FUTURE,
        manual_requested_at=manual,
        last_outcome="ok",
        last_new_count=2,
        consecutive_empty_discoveries=0,
    )


def _row(*, provider_state: str | None, cooldown: datetime | None, manual: bool, scheduled=True):
    pressure = (
        [
            ProviderPressureState(
                pressure_key="google", state=provider_state, cooldown_until=cooldown
            )
        ]
        if provider_state is not None
        else []
    )
    payload = schedule_payload(
        bindings=[_binding()],
        states=[_state(manual=NOW if manual else None)] if scheduled else [],
        pressure_rows=pressure,
        targets={"google": {"adapter": "google"}},
        settings=SETTINGS,
        now=NOW,
    )
    return payload["bindings"][0]


# --------------------------------------------------------------------------- #
# 1. The ladder, in order
# --------------------------------------------------------------------------- #

#: Each row satisfies the conditions BELOW its expected status as well, so a
#: swapped pair of branches changes the answer.
LADDER = [
    ("unscheduled", dict(provider_state="paused", cooldown=FUTURE, manual=True, scheduled=False)),
    ("policy_denied", dict(provider_state="policy_denied", cooldown=FUTURE, manual=True)),
    ("paused", dict(provider_state="paused", cooldown=FUTURE, manual=True)),
    ("cooldown", dict(provider_state="backoff", cooldown=FUTURE, manual=True)),
    ("manual", dict(provider_state="backoff", cooldown=PAST, manual=True)),
    ("scheduled", dict(provider_state="ready", cooldown=None, manual=False)),
]


@pytest.mark.parametrize(("expected", "case"), LADDER, ids=[row[0] for row in LADDER])
def test_the_status_ladder_answers_the_highest_condition_that_holds(expected, case):
    assert _row(**case)["status"] == expected


def test_an_expired_cooldown_is_not_a_cooldown():
    assert _row(provider_state="backoff", cooldown=PAST, manual=False)["status"] == "scheduled"


def test_a_provider_the_policy_denies_outranks_the_pressure_table():
    """`collection_access` is the live policy; the stored state can be stale."""
    payload = schedule_payload(
        bindings=[
            SourceBinding(
                id=2, company_slug="meta", connector_id="meta", status="stable",
                closure_capability="authoritative",
            )
        ],
        states=[],
        pressure_rows=[ProviderPressureState(pressure_key="meta", state="ready", cooldown_until=None)],
        targets={"meta": {"adapter": "meta"}},
        settings=SETTINGS,
        now=NOW,
    )
    assert payload["providers"][0]["state"] == "policy_denied"


# --------------------------------------------------------------------------- #
# 2. A blocked provider has no eligible time
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("state", sorted(BLOCKED_PROVIDER_STATES))
def test_a_blocked_provider_makes_every_stored_deadline_ineligible(state):
    assert eligible_schedule_at(FUTURE, provider_state=state, cooldown_until=None) is None
    row = _row(provider_state=state, cooldown=None, manual=False)
    assert row["eligible_reconcile_at"] is None
    assert row["eligible_discovery_at"] is None


def test_a_cooldown_pushes_an_eligible_deadline_out_but_never_pulls_it_in():
    assert eligible_schedule_at(FUTURE, provider_state="ready", cooldown_until=PAST) == FUTURE
    later = FUTURE + timedelta(hours=2)
    assert eligible_schedule_at(FUTURE, provider_state="ready", cooldown_until=later) == later


@pytest.mark.parametrize("state", sorted(BLOCKED_PROVIDER_STATES))
def test_a_queued_binding_behind_a_blocked_provider_reports_no_end_time(state):
    blocked = manual_block_reason(
        "google",
        provider_key="google",
        provider_state=state,
        cooldown_until=FUTURE,
        now=NOW,
    )
    assert blocked == {"company": "google", "provider": "google", "reason": state, "until": None}


def test_a_queue_of_every_company_is_one_block_per_provider():
    """Scan now for everyone while two providers cool down queues hundreds of
    companies, and the status answer the dashboard polls every few seconds
    carries the blocks: one row per company would grow it by a row each."""
    behind = [("ashby", "backoff", FUTURE)] * 300 + [("smartrecruiters", "backoff", FUTURE)] * 40
    blocked = [
        manual_block_reason(
            f"company-{i}", provider_key=provider, provider_state="ready", cooldown_until=until, now=NOW,
        )
        for i, (provider, _reason, until) in enumerate(behind)
    ]
    blocked.append(manual_block_reason(
        "google", provider_key="google", provider_state="paused", cooldown_until=None, now=NOW,
    ))

    assert blocks_by_provider(blocked) == [
        {"provider": "ashby", "reason": "backoff", "until": FUTURE, "companies": 300},
        {"provider": "google", "reason": "paused", "until": None, "companies": 1},
        {"provider": "smartrecruiters", "reason": "backoff", "until": FUTURE, "companies": 40},
    ]
    assert blocks_by_provider([]) == []


# --------------------------------------------------------------------------- #
# 3. One vocabulary for "blocked"
# --------------------------------------------------------------------------- #


def test_the_blocked_set_is_the_dispatcher_s_two_states():
    """The owner cannot import the dispatcher — the dependency runs the other
    way — so the two spellings are tied here instead."""
    assert BLOCKED_PROVIDER_STATES == {scheduler.POLICY_DENIED, scheduler.PAUSED}


@pytest.mark.parametrize(
    ("model", "field"),
    [(ExcludedBinding, "reason"), (ScheduleBindingPayload, "status")],
    ids=["excluded_reason", "binding_status"],
)
def test_the_wire_vocabulary_names_every_blocked_state(model, field):
    assert BLOCKED_PROVIDER_STATES <= set(get_args(model.model_fields[field].annotation))


# --------------------------------------------------------------------------- #
# 4. The projection asks the machine for nothing
# --------------------------------------------------------------------------- #

#: Reading the clock is `datetime.now(...)`, an attribute; reading the settings
#: is the `get_settings` name. Both are looked for in CODE, not in the file's
#: text -- this module's own docstring says it does neither, and a substring
#: search cannot tell that from doing it.
FETCHES_CLOCK = frozenset({"now", "utcnow", "today"})
FETCHES_SETTINGS = frozenset({"get_settings"})


def _asks_the_machine(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in FETCHES_CLOCK:
            found.add(f"{ast.unparse(node.value)}.{node.attr}")
        elif isinstance(node, ast.Name) and node.id in FETCHES_SETTINGS:
            found.add(node.id)
        elif isinstance(node, ast.ImportFrom):
            found |= {a.name for a in node.names if a.name in FETCHES_SETTINGS}
    return found


@pytest.mark.parametrize(
    "owner",
    [OWNER, BACKEND / "tracker" / "db" / "queries" / "binding_attention.py"],  # reports into /api/status too
    ids=lambda p: p.name,
)
def test_the_projection_reads_no_clock_and_no_settings_of_its_own(owner):
    assert _asks_the_machine(owner) == set()


def test_the_router_is_the_control_for_that_probe():
    """The ops contract pins both names in `routers/ops.py`. If the probe stopped
    finding them there it would be blind, and the check above vacuous."""
    asked = _asks_the_machine(BACKEND / "tracker" / "api" / "routers" / "ops.py")
    assert "datetime.now" in asked and "get_settings" in asked, asked
