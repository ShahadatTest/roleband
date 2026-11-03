"""Regenerate tests/fixtures/schema_metadata.json from the models' metadata.

Run only for a deliberate schema change, in the same change as the migration
that performs it; the snapshot test explains what each field is for.

    .venv/bin/python -m scripts.freeze_schema_metadata

This module imports `Base` and nothing else from `tracker`, deliberately: that
is exactly what `alembic/env.py` does, so the metadata frozen here is the
metadata autogenerate compares against. A generator that imported the app would
see model modules `env.py` never loads, and would freeze tables a migration run
cannot know about.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from pgvector.sqlalchemy import Vector
from sqlalchemy import Table
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import configure_mappers
from sqlalchemy.schema import CreateIndex, CreateTable

from tracker.db.models import Base

_DIALECT = postgresql.dialect()

#: The embedding width this fixture was frozen at. `models.py` reads
#: `embedding_dim` from settings AT IMPORT, so the compiled `vector(N)` follows
#: whatever `.env` the machine happens to carry — and a fixture that recorded
#: that would report one developer's configuration as another's schema drift.
#: Pinning alone would only move the blindness: the pin would then hide a real
#: change to the configured width. So the pin is CHECKED (`_pinned_dim`), and a
#: machine configured differently is refused by name instead of freezing a
#: schema the app would never build.
PINNED_EMBEDDING_DIM = 768

_WHY = (
    "The schema as the models declare it, frozen so a change to a column, index, "
    "constraint or default cannot land without showing up in a reviewer's diff. "
    "`alembic check` already answers 'do the models and the migrations agree?', but "
    "only against a live cluster and only in a CI log; this fixture answers 'did the "
    "models change at all?' with no database, in the pull request itself. The two "
    "claims are independent: a model edit WITH a matching migration keeps `check` "
    "green and still belongs in review, which is what this catches. Regenerate "
    "deliberately, in the same change as the migration: "
    "`.venv/bin/python -m scripts.freeze_schema_metadata`."
)


def _lines(ddl: str) -> list[str]:
    """Compiled DDL as a list of lines, so the fixture diffs line by line.

    Stored as one JSON string, the diff would be a single changed line holding
    several hundred escaped characters — technically a diff, useless to read.
    Trailing whitespace is stripped because the compiler emits `col TYPE, ` with
    a trailing space, which no reviewer should have to see or preserve.
    """

    return [line.expandtabs(4).rstrip() for line in ddl.strip().splitlines()]


def _default_repr(default: object) -> str:
    """A column default named stably, with no memory address in it.

    `repr()` of a callable default is `<function dict at 0x112d7a660>`, which
    changes every run and would make the fixture flap. The three kinds that
    occur here are normalized to what a reader needs: the callable's name, the
    scalar value, or the compiled SQL expression.
    """

    arg = getattr(default, "arg", None)
    if callable(arg):
        return f"{getattr(arg, '__name__', repr(arg))}()"
    if arg is not None and hasattr(arg, "compile"):
        return str(arg.compile(dialect=_DIALECT))
    if getattr(default, "is_sequence", False):
        return f"sequence:{getattr(default, 'name', '?')}"
    return repr(arg)


def _class_map() -> dict[str, str]:
    """Mapped class name -> table name, with no module paths in it.

    Module paths are omitted on purpose: splitting `models.py` into a package
    moves every class without changing one column, and a fixture that recorded
    where each class lived would report that refactor as schema drift. What is
    worth freezing is that the class still maps to the same table.
    """

    mapping: dict[str, str] = {}
    for mapper in Base.registry.mappers:
        name = mapper.class_.__name__
        table = mapper.local_table.name
        if name in mapping and mapping[name] != table:
            raise SystemExit(
                f"two mapped classes are both named {name!r} ({mapping[name]}, {table}); "
                "the class map is keyed by name, so rename one before freezing"
            )
        mapping[name] = table
    return dict(sorted(mapping.items()))


def table_fingerprint(table: Table) -> dict:
    """One table's frozen shape: its DDL, its indexes, and what DDL omits.

    Takes the table rather than reading `Base.metadata`, so a test can hand it a
    throwaway `Table` and prove the gate reports a planted change — the same
    reason `freeze_route_table.route_rows` accepts an application.
    """

    python_defaults = {
        column.name: _default_repr(column.default)
        for column in table.columns
        if column.default is not None
    }
    python_onupdate = {
        column.name: _default_repr(column.onupdate)
        for column in table.columns
        if column.onupdate is not None
    }
    column_comments = {c.name: c.comment for c in table.columns if c.comment}
    return {
        "create": _lines(str(CreateTable(table).compile(dialect=_DIALECT))),
        "indexes": [
            str(CreateIndex(index).compile(dialect=_DIALECT)).strip()
            for index in sorted(table.indexes, key=lambda i: i.name or "")
        ],
        # Python-side defaults never reach the DDL above: `default=list` is
        # applied by SQLAlchemy on insert, so adding one, dropping one, or
        # swapping it for a server default compiles to a byte-identical
        # CREATE TABLE. Recording them is the only way the fixture can see it.
        "python_defaults": dict(sorted(python_defaults.items())),
        "python_onupdate": dict(sorted(python_onupdate.items())),
        "comment": table.comment,
        "column_comments": dict(sorted(column_comments.items())),
    }


def _pinned_dim() -> int:
    """`PINNED_EMBEDDING_DIM`, or refuse and say how to get it.

    Read from the compiled metadata rather than from settings, because the
    vector width that reached the column is the fact the DDL carries; a setting
    read after import could disagree with what the column was built with.
    """

    dims = {
        column.type.dim
        for table in Base.metadata.tables.values()
        for column in table.columns
        if isinstance(column.type, Vector)
    }
    if not dims:
        return PINNED_EMBEDDING_DIM
    if dims != {PINNED_EMBEDDING_DIM}:
        raise SystemExit(
            f"models compiled vector{sorted(dims)} but this fixture is pinned to "
            f"vector({PINNED_EMBEDDING_DIM}). Either this machine's embedding_dim differs "
            f"from the pin — re-run as `ROLEBAND_EMBEDDING_DIM={PINNED_EMBEDDING_DIM} .venv/bin/python "
            "-m scripts.freeze_schema_metadata` — or the configured width really changed, in "
            "which case move PINNED_EMBEDDING_DIM in the same change as the migration that "
            "rebuilds the column."
        )
    return PINNED_EMBEDDING_DIM


def schema_metadata() -> dict:
    """The full fingerprint: DDL, indexes, and the parts DDL cannot show."""

    configure_mappers()
    embedding_dim = _pinned_dim()
    tables = {
        table.name: table_fingerprint(table)
        for table in sorted(Base.metadata.tables.values(), key=lambda t: t.name)
    }

    return {
        "_why": _WHY,
        "embedding_dim": embedding_dim,
        "table_count": len(tables),
        "classes": _class_map(),
        "tables": tables,
    }


def main(argv: list[str] | None = None) -> None:
    default_out = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "schema_metadata.json"
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=default_out, help="where to write the fixture")
    args = parser.parse_args(argv)

    payload = schema_metadata()
    args.out.write_text(json.dumps(payload, indent=1) + "\n")
    print(f"{payload['table_count']} tables -> {args.out}")


if __name__ == "__main__":
    main()
