"""`scripts.check_datasets`: the published datasets keep their statements.

The command is what a data checkout's CI runs, so each rule it claims is held
here twice: today's data passes, and a broken copy laid out as the data
repository is (`atlas/`, `benefits/`) fails, naming the file and line. The app's
own copy is never what a `--root` check reads.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from scripts import check_datasets
from tracker.levels import atlas
from tracker.profiles import benefits_builtin


@pytest.fixture
def checkout(tmp_path) -> Path:
    """A data checkout holding today's data, in the data repository's layout."""
    root = tmp_path / "roleband-data"
    shutil.copytree(atlas.ATLAS_DIR, root / "atlas")
    shutil.copytree(benefits_builtin.DATASET, root / "benefits")
    return root


def _edit(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    assert old in text, old
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def _line_of(path: Path, start: str) -> int:
    (number,) = [n for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1) if line.startswith(start)]
    return number


def test_the_app_s_copy_passes():
    assert check_datasets.check() == []
    assert check_datasets.main([]) == 0


def test_a_checkout_of_today_s_data_passes(checkout):
    assert check_datasets.check(checkout) == []
    assert check_datasets.main(["--root", str(checkout)]) == 0


def test_a_broken_atlas_cell_is_named_by_file_line_and_column(checkout, capsys):
    rungs = checkout / "atlas" / "rungs.csv"
    line = _line_of(rungs, "google,company,L5,senior,")
    _edit(rungs, "google,company,L5,senior,,,false,408000,15,20,2026-10-02,",
          "google,company,L5,senior,,,false,408000,15,20,,")
    assert check_datasets.main(["--root", str(checkout)]) == 1
    assert capsys.readouterr().out.splitlines() == [f"atlas/rungs.csv:{line} as_of: required"]


def test_a_rule_across_atlas_rows_is_held(checkout):
    """A rung on a ladder the company does not have breaks no single cell."""
    _edit(checkout / "atlas" / "rungs.csv", "google,product_management,L4,", "google,sales,L4,")
    (problem,) = check_datasets.check(checkout)
    assert problem.startswith("atlas/") and "no ladder" in problem


def test_an_atlas_file_out_of_canonical_form_is_named(checkout):
    """A spreadsheet that quotes every cell still loads, but the app's writer
    would rewrite it: the copy would differ from what the app produces."""
    printed = checkout / "atlas" / "printed.csv"
    _edit(printed, "company,code,band\n", '"company","code","band"\n')
    assert check_datasets.check(checkout) == ["atlas/printed.csv: not in canonical form (the app's writer would change it)"]


def test_a_hand_edited_descriptor_is_named(checkout):
    descriptor = checkout / "atlas" / "datapackage.json"
    raw = json.loads(descriptor.read_text(encoding="utf-8"))
    raw["title"] = "Someone's atlas"
    descriptor.write_text(json.dumps(raw, indent=2) + "\n", encoding="utf-8")
    assert check_datasets.check(checkout) == [
        "atlas/datapackage.json: differs from the tables' statement (written by the app's descriptor_text)"]


def test_a_file_a_dataset_does_not_state_is_named(checkout):
    (checkout / "atlas" / "scratch.csv").write_text("a,b\n", encoding="utf-8")
    (checkout / "benefits" / "observations.jsonl").rename(checkout / "benefits" / "cells.jsonl")
    assert check_datasets.check(checkout) == [
        "atlas/scratch.csv: not an atlas file",
        "benefits/cells.jsonl: not a benefits dataset file",
        "benefits/observations.jsonl: missing",
    ]


def test_a_broken_benefits_record_is_named_by_its_line(checkout):
    observations = checkout / "benefits" / "observations.jsonl"
    lines = observations.read_text(encoding="utf-8").splitlines()
    record = json.loads(lines[1])
    lines[1] = json.dumps({**record, "benefit_type": "moon_base"})
    observations.write_text("\n".join(lines) + "\n", encoding="utf-8")
    assert check_datasets.check(checkout) == ["benefits/observations.jsonl:2: benefit_type 'moon_base' is not in taxonomy.json"]


def test_a_missing_dataset_folder_is_named(checkout):
    shutil.rmtree(checkout / "benefits")
    assert check_datasets.check(checkout) == ["benefits/: missing"]


def test_checking_a_checkout_leaves_the_app_reading_its_own_copy(checkout):
    """The check reads the checkout through the atlas's own loaders; after it,
    the app reads its copy again, with nothing cached from the checkout."""
    before = atlas.ATLAS_DIR
    _edit(checkout / "atlas" / "level_base.csv", "1password,", "1passwordx,")
    check_datasets.check(checkout)
    assert atlas.ATLAS_DIR == before
    assert not any(company == "1passwordx" for company, _ in atlas.load_level_base())
