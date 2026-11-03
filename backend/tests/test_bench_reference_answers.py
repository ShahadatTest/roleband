"""The parity harness must be able to fail: a planted move it does not
see, a clock key it compares, or an expect rule that swallows everything would
each let a pay change land unmeasured."""

from __future__ import annotations

import json

import pytest

from scripts.bench_reference_answers import cmd_compare, diff, split_expected, strip_volatile

_BEFORE = {
    "packages": {"7": {"comp_package": {"split_source": "measured", "equity": {"usd": 120_000.0}}}},
    "profiles": {"acme": {"fields": {"headcount": {"value": 900, "freshness": "fresh"}}}},
}


def _after(**changes) -> dict:
    after = json.loads(json.dumps(_BEFORE))
    for path, value in changes.items():
        node = after
        *head, leaf = path.split("/")
        for key in head:
            node = node[key]
        node[leaf] = value
    return after


def test_identical_snapshots_have_no_moves():
    assert diff(_BEFORE, json.loads(json.dumps(_BEFORE))) == []


def test_a_planted_move_is_seen_with_its_path():
    moved = diff(_BEFORE, _after(**{"packages/7/comp_package/split_source": "heuristic"}))
    assert moved == [("packages.7.comp_package.split_source", "measured", "heuristic")]


def test_float_noise_is_not_a_move_but_a_real_change_is():
    assert diff(_BEFORE, _after(**{"packages/7/comp_package/equity/usd": 120_000.0 + 1e-12})) == []
    assert diff(_BEFORE, _after(**{"packages/7/comp_package/equity/usd": 120_001.0})) != []


def test_a_clock_key_is_never_compared_but_its_neighbour_is():
    assert diff(_BEFORE, _after(**{"profiles/acme/fields/headcount/freshness": "stale"})) == []
    assert diff(_BEFORE, _after(**{"profiles/acme/fields/headcount/value": 901})) != []
    assert "freshness" not in json.dumps(strip_volatile(_BEFORE))


def test_a_lost_key_is_a_move():
    after = _after()
    del after["profiles"]["acme"]
    assert "profiles.acme.fields.headcount.value" in [path for path, *_ in diff(_BEFORE, after)]


def test_an_expect_rule_covers_only_what_it_names():
    moved = diff(_BEFORE, _after(**{
        "packages/7/comp_package/split_source": "heuristic",
        "profiles/acme/fields/headcount/value": 901,
    }))
    expected, unexpected = split_expected(moved, [{"path": "packages.*.split_source", "reason": "determinism"}])
    assert [m[0] for m in expected] == ["packages.7.comp_package.split_source"]
    assert [m[0] for m in unexpected] == ["profiles.acme.fields.headcount.value"]


@pytest.mark.parametrize(("expect", "code"), [(None, 1), ([{"path": "packages.*", "reason": "listed"}], 0)])
def test_compare_exits_one_on_an_unlisted_move(tmp_path, expect, code):
    a, b = tmp_path / "a.json", tmp_path / "b.json"
    a.write_text(json.dumps({"meta": {"git_sha": "x"}, **_BEFORE}))
    b.write_text(json.dumps({"meta": {"git_sha": "y"}, **_after(**{"packages/7/comp_package/split_source": "heuristic"})}))
    expect_file = None
    if expect is not None:
        expect_file = tmp_path / "expect.json"
        expect_file.write_text(json.dumps(expect))
    assert cmd_compare(str(a), str(b), str(expect_file) if expect_file else None) == code
