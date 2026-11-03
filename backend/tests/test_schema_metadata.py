"""The schema the models declare, frozen as a reviewable artifact.

Three claims, kept apart because each is blind to the others:

1. **The committed fixture matches the models** — checked in a FRESH
   interpreter that imports `Base` and nothing else, exactly as
   `alembic/env.py:11` does. In-process would be a weaker claim twice over:
   pytest has already imported most of the app, so model modules `env.py` never
   loads would be in `Base.metadata`, and the embedding width would be whatever
   this machine's `.env` happens to say.

2. **A planted change is reported** — the fixture is only worth committing if it
   moves when the schema moves. Each control below mutates one thing on a
   throwaway table and names the field that must react.

3. **What the DDL cannot show is recorded anyway** — a Python-side `default=`
   never reaches `CREATE TABLE`, so a control proves the compiled DDL stays
   byte-identical while the fingerprint still changes.

This gate does NOT replace `alembic check`, which answers a different question
("do models and migrations agree?") and needs a cluster to answer it. This one
answers "did the models change at all?" with no database, in the diff. A model
edit that ships its migration keeps `check` green and still shows up here.
"""

from __future__ import annotations

import difflib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from pgvector.sqlalchemy import Vector
from sqlalchemy import Column, ForeignKey, Index, Integer, MetaData, String, Table, text

from scripts.freeze_schema_metadata import PINNED_EMBEDDING_DIM, table_fingerprint

_BACKEND = Path(__file__).resolve().parents[1]
_FIXTURE = _BACKEND / "tests" / "fixtures" / "schema_metadata.json"


# --------------------------------------------------------------------------- #
# 1. The fixture is current
# --------------------------------------------------------------------------- #


def _regenerate(out: Path) -> subprocess.CompletedProcess:
    """Run the generator the way `env.py` would see the models: alone."""

    env = {
        **os.environ,
        "ROLEBAND_EMBEDDING_DIM": str(PINNED_EMBEDDING_DIM),
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    return subprocess.run(
        [sys.executable, "-m", "scripts.freeze_schema_metadata", "--out", str(out)],
        cwd=_BACKEND,
        env=env,
        capture_output=True,
        text=True,
    )


def test_the_committed_fixture_matches_the_models(tmp_path):
    fresh = tmp_path / "schema_metadata.json"
    run = _regenerate(fresh)
    assert run.returncode == 0, (run.stderr or run.stdout)[-2000:]

    committed = _FIXTURE.read_text().splitlines()
    current = fresh.read_text().splitlines()
    diff = list(
        difflib.unified_diff(committed, current, "committed", "models", n=1, lineterm="")
    )
    assert not diff, (
        "the models and tests/fixtures/schema_metadata.json disagree:\n"
        + "\n".join(diff[:80])
        + "\n\nIf the schema change is deliberate, regenerate the fixture in the same "
        "change as its migration:\n"
        "    .venv/bin/python -m scripts.freeze_schema_metadata"
    )


def test_the_fixture_records_every_mapped_table_and_class():
    """The two halves of the payload agree with each other.

    A class map that drifted out of the table list would make the file-split
    blindness it exists to provide into a hole: a class whose table vanished
    would still be listed.
    """

    payload = json.loads(_FIXTURE.read_text())
    assert payload["table_count"] == len(payload["tables"])
    orphans = sorted(set(payload["classes"].values()) - set(payload["tables"]))
    assert not orphans, f"classes map to tables the fixture does not record: {orphans}"


def test_the_class_map_carries_no_module_paths():
    """Recording where a class lives would make a file split read as drift."""

    payload = json.loads(_FIXTURE.read_text())
    dotted = sorted(name for name in payload["classes"] if "." in name)
    assert not dotted, (
        f"these class keys look like module paths: {dotted}. The map is keyed by bare "
        "class name so splitting models.py into a package shows no schema diff."
    )


# --------------------------------------------------------------------------- #
# 2. A planted change is reported
# --------------------------------------------------------------------------- #


def _pair(build) -> tuple[dict, dict]:
    """Two fingerprints of the same table name, built on separate metadata."""

    left, right = MetaData(), MetaData()
    return table_fingerprint(build(left, False)), table_fingerprint(build(right, True))


def _nullable(meta: MetaData, mutated: bool) -> Table:
    return Table("probe", meta, Column("x", Integer, nullable=bool(mutated)))


def _server_default(meta: MetaData, mutated: bool) -> Table:
    kwargs = {"server_default": text("7")} if mutated else {}
    return Table("probe", meta, Column("x", Integer, **kwargs))


def _dropped_index(meta: MetaData, mutated: bool) -> Table:
    table = Table("probe", meta, Column("x", Integer))
    if not mutated:
        Index("ix_probe_x", table.c.x)
    return table


def _fk_ondelete(meta: MetaData, mutated: bool) -> Table:
    Table("parent", meta, Column("id", Integer, primary_key=True))
    target = ForeignKey("parent.id", ondelete="CASCADE") if mutated else ForeignKey("parent.id")
    return Table("probe", meta, Column("parent_id", Integer, target))


def _vector_dim(meta: MetaData, mutated: bool) -> Table:
    dim = 384 if mutated else PINNED_EMBEDDING_DIM
    return Table("probe", meta, Column("embedding", Vector(dim)))


def _column_type(meta: MetaData, mutated: bool) -> Table:
    kind = String(128) if mutated else String(64)
    return Table("probe", meta, Column("x", kind))


@pytest.mark.parametrize(
    ("name", "build", "field"),
    [
        ("nullable", _nullable, "create"),
        ("server_default", _server_default, "create"),
        ("dropped index", _dropped_index, "indexes"),
        ("FK ondelete", _fk_ondelete, "create"),
        ("vector dim", _vector_dim, "create"),
        ("column type", _column_type, "create"),
    ],
)
def test_the_fingerprint_reports_a_planted_change(name, build, field):
    before, after = _pair(build)
    assert before[field] != after[field], (
        f"changing {name} left {field!r} identical, so the frozen fixture would not move "
        "and the change would reach a reviewer invisible"
    )


# --------------------------------------------------------------------------- #
# 3. What the DDL cannot show
# --------------------------------------------------------------------------- #


def _python_default(meta: MetaData, mutated: bool) -> Table:
    kwargs = {} if mutated else {"default": list}
    return Table("probe", meta, Column("x", Integer, **kwargs))


def test_a_dropped_python_default_is_invisible_to_ddl_and_caught_anyway():
    """The control that justifies recording defaults separately.

    `default=list` is applied by SQLAlchemy on insert, never by the database, so
    dropping it compiles to the same CREATE TABLE. Only `python_defaults` moves —
    and a behaviour change that no DDL can show is exactly the one worth freezing.
    """

    before, after = _pair(_python_default)
    assert before["create"] == after["create"], (
        "this control assumes a Python-side default leaves no trace in the DDL; "
        "if that stopped being true, the control is no longer testing what it claims"
    )
    assert before["python_defaults"] != after["python_defaults"]
    assert "x" in before["python_defaults"] and "x" not in after["python_defaults"]


def test_a_callable_default_is_named_not_addressed():
    """A memory address in the fixture would make it flap every run."""

    fingerprint = table_fingerprint(
        Table("probe", MetaData(), Column("x", Integer, default=list))
    )
    assert fingerprint["python_defaults"]["x"] == "list()"


# --------------------------------------------------------------------------- #
# The pin
# --------------------------------------------------------------------------- #


def test_a_width_other_than_the_pin_is_refused_by_name(tmp_path):
    """A pin that silently froze the wrong width would only move the blindness.

    The generator compares the width the columns actually compiled with against
    `PINNED_EMBEDDING_DIM` and refuses, so a machine whose `.env` disagrees gets
    an error naming both numbers rather than a fixture the app would never build.
    """

    out = tmp_path / "schema_metadata.json"
    env = {
        **os.environ,
        "ROLEBAND_EMBEDDING_DIM": str(PINNED_EMBEDDING_DIM + 1),
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    run = subprocess.run(
        [sys.executable, "-m", "scripts.freeze_schema_metadata", "--out", str(out)],
        cwd=_BACKEND,
        env=env,
        capture_output=True,
        text=True,
    )
    assert run.returncode != 0, "a mismatched embedding width was accepted"
    assert str(PINNED_EMBEDDING_DIM) in run.stderr and str(PINNED_EMBEDDING_DIM + 1) in run.stderr
    assert not out.exists(), "the generator wrote a fixture it had already refused"
