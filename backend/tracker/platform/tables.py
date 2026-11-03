"""Dataset tables stated once in code: the shape a file must keep.

A `Table` names a file's columns and the rules each cell keeps on its own:
required, type, allowed values, and a key no two rows share. `problems` lists
every break in a file, each naming the file, line and column; `read` returns
the rows, or raises `TableError` with the first break. CSV and JSON Lines
share one statement, so a dataset's checks read the same whatever its format.

A table states shape, not location: its dataset passes the file to read, so one
statement checks the app's copy and a data checkout alike. Rules that span rows
or files (a rung's ladder exists, a record names a known company) stay beside
the loader that needs them.

Pure: reads files, imports no other tracker module.
"""

from __future__ import annotations

import csv
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

#: Frictionless Table Schema type names.
TYPES = ("string", "integer", "boolean", "date", "object", "array")
FORMATS = ("csv", "jsonl")


@dataclass(frozen=True)
class Field:
    name: str
    type: str = "string"
    required: bool = False
    enum: tuple[str, ...] | None = None
    description: str = ""


@dataclass(frozen=True)
class Table:
    name: str
    description: str
    fields: tuple[Field, ...]
    primary_key: tuple[str, ...]
    foreign_keys: tuple[tuple[tuple[str, ...], str, tuple[str, ...]], ...] = ()
    #: Outside records the table is derived from, as Frictionless `sources` titles.
    sources: tuple[str, ...] = ()
    format: str = "csv"

    @property
    def file(self) -> str:
        return f"{self.name}.{self.format}"

    @property
    def columns(self) -> list[str]:
        return [f.name for f in self.fields]


class TableError(ValueError):
    """A file breaks its table's statement; the message names the file and row."""


#: Rewrites an older row into the current form, in place, before it is checked.
Upgrade = Callable[[dict[str, Any]], None]


def read(
    table: Table, path: Path, accept: tuple[tuple[str, ...], ...] = (), upgrade: Upgrade | None = None,
) -> list[dict[str, Any]]:
    """The file's rows, checked against `table`; raises on the first break.

    `accept` lists older CSV headers still read, each holding every current
    column; rows are cut down to the current columns. `upgrade` brings an older
    row's values to the current form before its cells are checked."""
    rows, found = _check(table, path, accept, upgrade, first=True)
    if found:
        raise TableError(found[0])
    return rows


def problems(
    table: Table, path: Path, accept: tuple[tuple[str, ...], ...] = (), upgrade: Upgrade | None = None,
) -> list[str]:
    """Every break in the file, in file order: `file:line column: problem`."""
    return _check(table, path, accept, upgrade, first=False)[1]


def _check(
    table: Table, path: Path, accept: tuple[tuple[str, ...], ...], upgrade: Upgrade | None, first: bool,
) -> tuple[list[dict[str, Any]], list[str]]:
    if table.format == "csv":
        return _check_csv(table, path, accept, upgrade, first)
    if table.format == "jsonl":
        return _check_jsonl(table, path, upgrade, first)
    raise ValueError(f"{table.name}: format {table.format!r} not in {list(FORMATS)}")


def _check_csv(
    table: Table, path: Path, accept: tuple[tuple[str, ...], ...], upgrade: Upgrade | None, first: bool,
) -> tuple[list[dict[str, Any]], list[str]]:
    # utf-8-sig: a spreadsheet's "CSV UTF-8" save starts with a byte order
    # mark, which plain utf-8 keeps as part of the first column's name.
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        columns = reader.fieldnames
        if columns != table.columns and tuple(columns or ()) not in accept:
            return [], [f"{table.file}: columns {columns} != {table.columns}"]
        raw = list(reader)
    rows: list[dict[str, Any]] = []
    out: list[str] = []
    keys: set[tuple[Any, ...]] = set()
    for line, cells in enumerate(raw, start=2):
        # DictReader pads a short row with None and files a long one's extra
        # cells under None: either is a broken row, named as such.
        filled = sum(value is not None for key, value in cells.items() if key is not None)
        if filled != len(columns or ()) or None in cells:
            width = filled + len(cells.get(None) or [])
            out.append(f"{table.file}:{line}: {width} cells, the header has {len(columns or ())}")
            if first:
                break
            continue
        row = {name: cells[name] for name in table.columns}
        if upgrade:
            upgrade(row)
        rows.append(row)
        out += _row_problems(table, row, line, keys)
        if first and out:
            break
    return rows, out


def _check_jsonl(table: Table, path: Path, upgrade: Upgrade | None, first: bool) -> tuple[list[dict[str, Any]], list[str]]:
    rows: list[dict[str, Any]] = []
    out: list[str] = []
    keys: set[tuple[Any, ...]] = set()
    known = set(table.columns)
    with path.open(encoding="utf-8") as handle:
        for line, text in enumerate(handle, start=1):
            try:
                row = json.loads(text)
            except ValueError:
                row = None
            if not isinstance(row, dict):
                out.append(f"{table.file}:{line}: not a JSON object")
            else:
                if extra := sorted(set(row) - known):
                    out.append(f"{table.file}:{line}: unknown fields {extra}")
                if upgrade:
                    upgrade(row)
                rows.append(row)
                out += _row_problems(table, row, line, keys)
            if first and out:
                break
    return rows, out


def _row_problems(table: Table, row: dict[str, Any], line: int, keys: set[tuple[Any, ...]]) -> list[str]:
    out = []
    for f in table.fields:
        value = row.get(f.name)
        if value is None or value == "":
            if f.required:
                out.append(f"{table.file}:{line} {f.name}: required")
            continue
        if problem := _cell_problem(f, value, typed=table.format == "jsonl"):
            out.append(f"{table.file}:{line} {f.name}: {problem}")
    key = tuple(_hashable(row.get(k)) for k in table.primary_key)
    if key in keys:
        out.append(f"{table.file}:{line}: duplicate key {key}")
    keys.add(key)
    return out


def _cell_problem(f: Field, value: Any, typed: bool) -> str | None:
    """What is wrong with one non-empty cell, or None. A CSV cell is always
    text and is read for its type; a JSON value must carry its own (`typed`):
    "500" is not an integer there."""
    text = not typed
    if f.enum and value not in f.enum:
        return f"{value!r} not in {list(f.enum)}"
    if f.type == "string":
        return None if isinstance(value, str) else f"{value!r} is not a string"
    if f.type == "integer":
        ok = value.lstrip("-").isdigit() if text else isinstance(value, int) and not isinstance(value, bool)
        return None if ok else f"{value!r} is not an integer"
    if f.type == "boolean":
        ok = value in ("true", "false") if text else isinstance(value, bool)
        return None if ok else f"{value!r} is not true/false"
    if f.type == "date":
        try:
            date.fromisoformat(value)
        except (TypeError, ValueError):
            return f"{value!r} is not a date (YYYY-MM-DD)"
        return None
    if f.type == "object":
        return None if isinstance(value, dict) else f"{value!r} is not an object"
    if f.type == "array":
        return None if isinstance(value, list) else f"{value!r} is not an array"
    raise ValueError(f"{f.name}: type {f.type!r} not in {list(TYPES)}")


def _hashable(value: Any) -> Any:
    return json.dumps(value, sort_keys=True) if isinstance(value, (dict, list)) else value
