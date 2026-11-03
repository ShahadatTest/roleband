"""The slots as the core keeps them: one row per slot.

The SDK says what a plugin may SEND into a slot (`roleband_plugin_sdk.slots`,
the row models, validated on both sides). This table says what the core DOES
with it, once, for every module that branches on a slot:

- `table`, `provider_column`: where the rows land and which column names who
  published them (`provider`; `source` on the append-only claims);
- `key`: (row field, column) pairs naming a row within (provider, company), the
  identity a complete snapshot repeats or retires (`writer`);
- `retires`: a clean complete snapshot retires the rows it did not repeat;
  append-only history (observations, claims) never retires;
- `removable`: the user's Remove data deletes the provider's rows;
- `builtin`: our own dataset answers what no plugin does (`status.capabilities`);
- `estimate`: stored estimates read it, so its provider set is part of the
  reference fingerprint and readers take it from the APPLIED set.

The constants are the SDK's strings, repeated here because the API, the
scheduler and the pipeline never import the SDK; `tests/test_plugin_slots.py`
holds the two equal and fails by name when the SDK gains a slot this table
does not describe.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from tracker.db.models import (
    Base,
    CompanyBenefit,
    CompanyCompLevel,
    CompanyFact,
    ExternalCompObservation,
)

PAY_LEVELS = "pay.levels"
PAY_OBSERVATIONS = "pay.observations"
COMPANY_FACTS = "company.facts"
COMPANY_BENEFITS = "company.benefits"


@dataclass(frozen=True)
class SlotSpec:
    name: str
    table: type[Base]
    provider_column: str = "provider"
    key: tuple[tuple[str, str], ...] = ()
    retires: bool = False
    removable: bool = False
    builtin: bool = False
    estimate: bool = False


SPECS: tuple[SlotSpec, ...] = (
    SlotSpec(PAY_LEVELS, CompanyCompLevel, key=(("family", "family"), ("label", "level_label"), ("country", "country")),
             retires=True, removable=True, builtin=True, estimate=True),
    # Individual reported pay points: history, kept whole; nothing of ours answers them.
    SlotSpec(PAY_OBSERVATIONS, ExternalCompObservation, key=(("dedup_key", "dedup_key"),)),
    # Claims: append-only, never resolved into the profile.
    SlotSpec(COMPANY_FACTS, CompanyFact, provider_column="source", builtin=True),
    SlotSpec(COMPANY_BENEFITS, CompanyBenefit, key=(("name", "name"), ("country", "country")), retires=True, removable=True,
             builtin=True),
)

BY_NAME: dict[str, SlotSpec] = {s.name: s for s in SPECS}
SLOTS: tuple[str, ...] = tuple(BY_NAME)
#: The slots a job's stored estimate reads.
ESTIMATE_SLOTS: tuple[str, ...] = tuple(s.name for s in SPECS if s.estimate)
#: Slots our own dataset answers when no plugin does.
BUILTIN_SLOTS: frozenset[str] = frozenset(s.name for s in SPECS if s.builtin)


def spec(slot: str) -> SlotSpec:
    """The core's row for `slot`; `ValueError` for a slot it does not keep."""
    try:
        return BY_NAME[slot]
    except KeyError:
        raise ValueError(f"unknown slot {slot!r}; the core keeps {sorted(BY_NAME)}") from None


def row_key(slot: str, row: Mapping[str, Any]) -> tuple[Any, ...]:
    """The identity of a published row within (provider, company) in `slot`."""
    return tuple(row[field] for field, _ in spec(slot).key)
