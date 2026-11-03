"""The shared table statement: one rule set for CSV and JSON Lines files."""

from __future__ import annotations

import pytest

from tracker.platform.tables import Field, Table, TableError, problems, read

FIELDS = (
    Field("id", required=True),
    Field("count", "integer"),
    Field("open", "boolean"),
    Field("kind", enum=("a", "b")),
)
CSV = Table("things", "", FIELDS, ("id",))
JSONL = Table("things", "", FIELDS, ("id",), format="jsonl")


def test_a_csv_cell_is_read_for_its_type_and_a_json_value_carries_its_own(tmp_path):
    (tmp_path / "things.csv").write_text("id,count,open,kind\nx,500,true,a\n", encoding="utf-8")
    (tmp_path / "things.jsonl").write_text('{"id": "x", "count": "500", "open": "true", "kind": "a"}\n', encoding="utf-8")
    assert problems(CSV, tmp_path / "things.csv") == []
    assert problems(JSONL, tmp_path / "things.jsonl") == [
        "things.jsonl:1 count: '500' is not an integer",
        "things.jsonl:1 open: 'true' is not true/false",
    ]


def test_problems_lists_every_break_and_read_raises_on_the_first(tmp_path):
    path = tmp_path / "things.csv"
    path.write_text("id,count,open,kind\n,1,true,a\ny,one,true,c\ny,2,maybe,a\nz,3\n", encoding="utf-8")
    assert problems(CSV, path) == [
        "things.csv:2 id: required",
        "things.csv:3 count: 'one' is not an integer",
        "things.csv:3 kind: 'c' not in ['a', 'b']",
        "things.csv:4 open: 'maybe' is not true/false",
        "things.csv:4: duplicate key ('y',)",
        "things.csv:5: 2 cells, the header has 4",
    ]
    with pytest.raises(TableError, match="^things.csv:2 id: required$"):
        read(CSV, path)


def test_a_json_line_names_what_it_is_not(tmp_path):
    path = tmp_path / "things.jsonl"
    path.write_text('{"id": "x"}\n[1]\n{"id": "y", "colour": "red"}\n{"id": "x"}\n', encoding="utf-8")
    assert problems(JSONL, path) == [
        "things.jsonl:2: not a JSON object",
        "things.jsonl:3: unknown fields ['colour']",
        "things.jsonl:4: duplicate key ('x',)",
    ]


def test_an_older_header_is_read_cut_down_to_the_current_columns(tmp_path):
    path = tmp_path / "things.csv"
    path.write_text("id,count,open,kind,retired\nx,1,true,a,old\n", encoding="utf-8")
    with pytest.raises(TableError, match="columns"):
        read(CSV, path)
    assert read(CSV, path, accept=(("id", "count", "open", "kind", "retired"),)) == [
        {"id": "x", "count": "1", "open": "true", "kind": "a"}]
