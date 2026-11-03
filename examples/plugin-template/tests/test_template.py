"""The template's own suite: what a plugin repo's CI runs.

Parser tests on a recorded document, the job under the SDK's fake host (in
process and as a real runner process), and the no-direct-network check.
Nothing here reaches the network: the fake host answers only recorded URLs.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from roleband_plugin_sdk import COMPANY_FACTS, PAY_LEVELS
from roleband_plugin_sdk.checks import scan
from roleband_plugin_sdk.testing import FakeHost, FakeResponse

from roleband_plugin_template import BASE_URL
from roleband_plugin_template.parse import parse_ladders

ROOT = Path(__file__).resolve().parents[1]
ACME = json.loads((ROOT / "tests" / "fixtures" / "acme.json").read_text())


def _host(**overrides):
    kwargs = {
        "companies": {"acme": "Acme Corp", "globex": "Globex"},
        "responses": {
            f"{BASE_URL}/acme.json": FakeResponse(body=ACME, headers={"content-type": "application/json"}),
            f"{BASE_URL}/globex.json": FakeResponse(status=404),
        },
    }
    kwargs.update(overrides)
    return FakeHost(ROOT, **kwargs)


def test_parser_keeps_labels_verbatim_and_a_missing_part_unknown():
    levels, facts = parse_ladders(ACME, "https://data.example.com/v1/ladders/acme.json")
    assert [(lv.label, lv.tc, lv.base, lv.stock, lv.bonus) for lv in levels] == [
        ("E3", 180000, 150000, 20000, 10000),
        ("E4", 240000, 175000, 45000, None),
        ("E5", 330000, None, None, None),
    ]
    assert {lv.family for lv in levels} == {"software_engineering"}
    assert levels[0].aliases == ("Engineer I",)
    assert {(f.field, f.value) for f in facts} == {("headcount", 1200)}


def test_a_family_the_map_does_not_name_is_skipped_not_guessed():
    levels, _ = parse_ladders(ACME, "https://data.example.com/x")
    assert "F1" not in {lv.label for lv in levels}


def test_refresh_publishes_each_ladder_once_and_nothing_for_a_missing_one():
    result = _host().run("refresh")
    assert result.outcome == "clean", result.message
    assert [lv.label for lv in result.rows(PAY_LEVELS, "acme")] == ["E3", "E4", "E5"]
    assert result.rows(PAY_LEVELS, "globex") == []
    assert {b.complete for b in result.published} == {True}
    assert result.progress[-1] == (2, 2)
    assert result.state == {"resume.refresh": None}, "the pass is through: the next run starts a new one"
    assert result.more is False
    assert result.retires == {(PAY_LEVELS, "acme")}
    # Its own words for the run: the one ladder it read, never the missing one.
    assert result.summary == "Read ladders for 1 company"


def test_a_pass_the_budget_cannot_hold_continues_in_the_next_run():
    """Each read costs the host's 2 s pacing floor and `ctx.resume` keeps a
    120 s margin: with 121 s left after acme, the run stops before globex, ends
    clean, and asks to be continued; the next run starts after acme."""
    first = _host(budget_seconds=121).run("refresh")
    assert (first.outcome, first.more) == ("clean", True)
    assert [b.company for b in first.published] == ["acme", "acme"]
    assert first.state == {"resume.refresh": "acme"}
    second = _host(budget_seconds=121, state=first.state).run("refresh")
    assert (second.outcome, second.more) == ("clean", False)
    assert second.requests == [f"{BASE_URL}/globex.json"]


def test_a_ladder_the_parser_maps_nothing_of_publishes_no_levels_and_retires_none():
    """A document whose every family is one the map does not name parses to no
    rungs. A complete publish of nothing would retire the company's whole
    ladder, so no levels go out, and the facts still do."""
    renamed = dict(ACME, ladders=[dict(ladder, name=f"{ladder['name']} (renamed)") for ladder in ACME["ladders"]])
    result = _host(responses={
        f"{BASE_URL}/acme.json": FakeResponse(body=renamed),
        f"{BASE_URL}/globex.json": FakeResponse(status=404),
    }).run("refresh")
    assert result.outcome == "clean", result.message
    assert [b.slot for b in result.published] == [COMPANY_FACTS]
    assert result.retires == set()
    assert ("warning", "acme: no ladder this plugin maps, levels not published") in result.logs
    assert result.summary is None, "a company with no ladder read is not counted as read"


def test_a_server_error_skips_that_company_and_keeps_the_run():
    result = _host(responses={
        f"{BASE_URL}/acme.json": FakeResponse(body=ACME),
        f"{BASE_URL}/globex.json": FakeResponse(status=503),
    }).run("refresh")
    assert result.outcome == "clean"
    assert {b.company for b in result.published} == {"acme"}
    assert ("warning", "globex: HTTP 503, skipped") in result.logs


def test_only_followed_companies_are_read():
    result = _host(followed=["globex"]).run("refresh")
    assert result.requests == [f"{BASE_URL}/globex.json"]


def test_the_runner_process_publishes_exactly_what_the_in_process_run_does():
    in_process = _host().run("refresh")
    as_process = _host().run("refresh", subprocess=True)
    assert as_process.outcome == "clean", as_process.stderr
    assert as_process.published == in_process.published
    assert as_process.rows(COMPANY_FACTS, "acme") == in_process.rows(COMPANY_FACTS, "acme")


@pytest.mark.parametrize("path", [ROOT / "src"])
def test_the_plugin_reaches_the_network_only_through_the_host(path):
    assert [str(f) for f in scan(path)] == []
