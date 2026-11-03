"""The core's slot table describes every slot the SDK accepts, and only those
(`tracker/plugins/slots.py`).

A slot added to the SDK is refused nowhere and stored nowhere until the core
says what it does with it: which table, which provider column, which key a
snapshot repeats, whether it retires, whether Remove data deletes it. These
tests fail by name when the two drift, before a plugin can publish into a slot
the writer would not know how to store.
"""

from __future__ import annotations

import pytest
from roleband_plugin_sdk import slots as sdk

from tracker import plugin_manifest
from tracker.db.ownership import TABLE_OWNERS
from tracker.plugins import registry, status, writer
from tracker.plugins import slots as core


def test_the_core_keeps_exactly_the_slots_the_sdk_accepts():
    assert set(core.SLOTS) == set(sdk.V1_SLOTS)
    for name in ("PAY_LEVELS", "PAY_OBSERVATIONS", "COMPANY_FACTS", "COMPANY_BENEFITS"):
        assert getattr(core, name) == getattr(sdk, name) == getattr(registry, name), name
    assert plugin_manifest.COMPANY_FACTS == core.COMPANY_FACTS
    assert registry.SLOTS == core.SLOTS and registry.ESTIMATE_SLOTS == core.ESTIMATE_SLOTS
    assert status.BUILTIN_SLOTS == core.BUILTIN_SLOTS


@pytest.mark.parametrize("spec", core.SPECS, ids=lambda s: s.name)
def test_each_slot_s_key_is_a_field_of_its_row_and_a_column_of_its_table(spec):
    model = sdk.row_model(spec.name)
    columns = spec.table.__table__.columns
    assert spec.provider_column in columns
    assert "company_slug" in columns
    for field, column in spec.key:
        assert field in model.model_fields, f"{spec.name}: {field} is not a {model.__name__} field"
        assert column in columns, f"{spec.name}: {column} is not a {spec.table.__tablename__} column"
    if spec.retires:
        assert spec.key, f"{spec.name} retires, so it needs the key a snapshot repeats"
        assert "retired_at" in columns


@pytest.mark.parametrize("spec", core.SPECS, ids=lambda s: s.name)
def test_each_slot_has_a_writer_and_its_table_names_the_plugin_writer(spec):
    assert spec.name in writer.WRITERS
    claim = TABLE_OWNERS[spec.table.__tablename__]
    assert {"tracker/plugins/writer.py", "tracker/profiles/store.py"} & set(claim.writers), (
        spec.table.__tablename__, claim.writers)


def test_an_unknown_slot_is_refused_by_name():
    with pytest.raises(ValueError, match="unknown slot 'listing.source'"):
        core.spec("listing.source")


def test_the_wire_names_exactly_the_core_s_slots():
    from typing import get_args

    from tracker.api.schemas.plugins import PluginSlot

    assert set(get_args(PluginSlot)) == set(core.SLOTS)


def test_the_sdk_retires_in_the_slots_the_core_retires():
    """`FakeHost.retires` reports what the core's writer will retire."""
    assert sdk.RETIRING_SLOTS == {s.name for s in core.SPECS if s.retires}


@pytest.mark.parametrize("spec", core.SPECS, ids=lambda s: s.name)
def test_the_sdk_s_row_key_is_the_store_s_unique_key(spec):
    """`FakeHost.rows` collapses what the table's unique constraint collapses.
    Read from the constraint itself, not from `SlotSpec.key`: an observation's
    key spans companies, which the per-company retirement key does not say."""
    from sqlalchemy import UniqueConstraint

    uniques = [c for c in spec.table.__table__.constraints if isinstance(c, UniqueConstraint)]
    if not uniques:
        assert spec.name not in sdk.ROW_KEYS, f"{spec.name} keeps every row; the fake host must too"
        return
    (unique,) = uniques
    field = {column: field for field, column in spec.key} | {"company_slug": "company"}
    columns = [c.name for c in unique.columns if c.name != spec.provider_column]
    assert sdk.ROW_KEYS[spec.name] == tuple(field[c] for c in columns)
