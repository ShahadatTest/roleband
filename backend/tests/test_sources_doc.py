"""`docs/sources.md` is the source review register, rendered.

The committed file must equal what `scripts.gen_sources_doc` renders from
`SOURCE_REVIEWS` and `ADAPTER_REGISTRY` today, and `--check` must fail when
the two drift apart, in either direction: a line planted in the file, or a
register field that changed without a regeneration.
"""

from __future__ import annotations

import dataclasses

import pytest

from scripts import gen_sources_doc as gen
from tracker.connectors import ADAPTER_REGISTRY
from tracker.source_review import SOURCE_REVIEWS


def _table_rows(text: str) -> dict[str, list[str]]:
    """Source key -> its cells, read from the rendered Markdown table."""
    rows: dict[str, list[str]] = {}
    for line in text.splitlines():
        if not line.startswith("| `"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split(" | ")]
        rows[cells[0].strip("`")] = cells
    return rows


def test_the_committed_doc_equals_the_generator_output():
    assert gen.OUT.read_text(encoding="utf-8") == gen.render(), (
        f"docs/sources.md is stale; run: {gen.COMMAND}"
    )


def test_the_doc_has_one_row_per_listing_adapter():
    rows = _table_rows(gen.OUT.read_text(encoding="utf-8"))
    assert sorted(rows) == sorted(ADAPTER_REGISTRY)


def test_the_collection_column_says_what_the_register_says():
    rows = _table_rows(gen.render())
    for key, review in SOURCE_REVIEWS.items():
        collection = rows[key][4]
        if review.wall is not None:
            assert collection.startswith("walled"), key
        elif review.user_directed:
            assert collection == "user-directed", key
        else:
            assert collection == "default", key
    # The register carries both kinds today; a renderer that flattened them
    # would pass the loop above only if neither existed.
    assert any(r[4].startswith("walled") for r in rows.values())
    assert any(r[4] == "user-directed" for r in rows.values())


def test_check_passes_on_a_current_file(tmp_path, monkeypatch, capsys):
    out = tmp_path / "sources.md"
    out.write_text(gen.render(), encoding="utf-8")
    monkeypatch.setattr(gen, "OUT", out)
    assert gen.main(["--check"]) == 0


def test_check_fails_on_a_planted_extra_row(tmp_path, monkeypatch, capsys):
    out = tmp_path / "sources.md"
    planted = (
        "| `madeup` | documented public API | GET `example.com` | allowed | default"
        " | `x` | default client |\n"
    )
    out.write_text(gen.render() + planted, encoding="utf-8")
    monkeypatch.setattr(gen, "OUT", out)

    assert gen.main(["--check"]) == 1
    assert gen.COMMAND in capsys.readouterr().out


def test_check_fails_when_a_register_field_changes(tmp_path, monkeypatch, capsys):
    out = tmp_path / "sources.md"
    out.write_text(gen.render(), encoding="utf-8")
    monkeypatch.setattr(gen, "OUT", out)
    changed = dict(SOURCE_REVIEWS)
    changed["greenhouse"] = dataclasses.replace(
        changed["greenhouse"], request_identity="RoleBand-test/1.0"
    )
    monkeypatch.setattr(gen, "SOURCE_REVIEWS", changed)

    assert gen.main(["--check"]) == 1
    assert _table_rows(gen.render())["greenhouse"][5] == "`RoleBand-test/1.0`"


def test_render_refuses_a_registry_the_register_does_not_cover():
    partial = {k: v for k, v in SOURCE_REVIEWS.items() if k != "lever"}
    with pytest.raises(ValueError, match="lever"):
        gen.render(partial, ADAPTER_REGISTRY)
