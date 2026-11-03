"""The plugin SDK holds the host's rules, not just its shapes.

Three surfaces, each with planted failures:
- slot rows are strict: an amount is an int and never a bool, a missing part
  is None, a fact's value fits its field;
- the fake host refuses what the manifest does not declare (slot per job,
  host, header, need, company), revalidates rows on its own side, and ends a
  run `bounded` or `stopped` in a way a plugin's `except Exception` cannot hide;
- the runner process keeps stdout for the protocol and refuses a protocol it
  does not speak.

The fake host is the one plugin authors test against; the core's host must
give the same answers, and these cases are its contract.
"""

from __future__ import annotations

import copy
import io
import subprocess
import sys
import textwrap
import tomllib
from datetime import date, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError
from roleband_plugin_sdk import (
    COMPANY_BENEFITS,
    COMPANY_FACTS,
    PAY_LEVELS,
    PAY_OBSERVATIONS,
    PROTOCOL_VERSION,
    Benefit,
    FactClaim,
    HostError,
    JobContext,
    PayLevel,
    PayObservation,
    Plugin,
    Refused,
    RunEnded,
    protocol,
)
from roleband_plugin_sdk.manifest import validate_manifest
from roleband_plugin_sdk.runner import StdioTransport
from roleband_plugin_sdk.testing import FakeHost, FakeResponse

from tracker.taxonomy.roles import all_slugs

REPO = Path(__file__).resolve().parents[2]
SDK = REPO / "sdk" / "python"
TEMPLATE = REPO / "examples" / "plugin-template"
BASE = tomllib.loads((TEMPLATE / "roleband-plugin.toml").read_text())
URL = "https://data.example.com/v1/ladders/acme.json"


def _level(**overrides):
    row = {"family": "software_engineering", "label": "L5", "tc": 300000, "currency": "USD", "as_of": "2026-09-30"}
    row.update(overrides)
    return row


# --------------------------------------------------------------------------- #
# Slot rows
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"tc": None}, "at least one of tc, base, stock or bonus"),
        ({"tc": True}, "valid integer"),
        ({"tc": "300000"}, "valid integer"),
        ({"tc": 300000.0}, "valid integer"),
        ({"tc": -1}, "greater than or equal to 0"),
        ({"currency": "usd"}, "pattern"),
        ({"country": "USA"}, "pattern"),
        ({"label": "x" * 49}, "at most 48"),
        ({"family": "Software Engineer"}, "pattern"),
        ({"source_url": "http://data.example.com/x"}, "pattern"),
        ({"band": "senior"}, "Extra inputs"),
        ({"provider": "levels"}, "Extra inputs"),
    ],
)
def test_a_pay_level_row_is_strict(overrides, reason):
    with pytest.raises(ValidationError, match=reason):
        PayLevel.model_validate(_level(**overrides))


def test_a_missing_pay_part_is_unknown_not_zero():
    row = PayLevel.model_validate(_level(base=200000))
    assert (row.tc, row.base, row.stock, row.bonus) == (300000, 200000, None, None)


@pytest.mark.parametrize(
    ("field", "value", "ok"),
    [
        ("headcount", 1200, True),
        ("headcount", None, True),
        ("headcount", True, False),
        ("headcount", -5, False),
        ("headcount", "1200", False),
        # A company's identity is RoleBand's own: any
        # claim on it is refused, a well-formed one included.
        ("is_public", True, False),
        ("ticker", "RDDT", False),
        ("brand_color", "#1a2B3c", False),
        ("website", "https://acme.example", False),
        ("year_founded", 1998, False),
        ("display_name", None, False),
    ],
)
def test_a_fact_claim_value_fits_its_field(field, value, ok):
    claim = {"field": field, "value": value, "observed_at": "2026-09-30T00:00:00+00:00"}
    if ok:
        assert FactClaim.model_validate(claim).value == value
    else:
        with pytest.raises(ValidationError):
            FactClaim.model_validate(claim)


def test_a_fact_claim_needs_a_timezone():
    with pytest.raises(ValidationError, match="timezone"):
        FactClaim(field="is_public", value=True, observed_at=datetime(2026, 9, 30))


def test_benefit_detail_is_small_plain_json():
    assert Benefit(name="401k", category="Financial", detail={"match": "50%"}).detail == {"match": "50%"}
    with pytest.raises(ValidationError, match="limit"):
        Benefit(name="401k", category="Financial", detail={"blob": "x" * 9000})


def test_a_pay_observation_leaves_an_unstated_component_unknown():
    base = {"source_level": "L6", "total": 1, "base": 1, "equity": 0, "bonus": 0, "currency": "USD",
            "snapshot_date": date(2026, 9, 1), "dedup_key": "k"}
    assert PayObservation(**base).equity == 0
    partial = PayObservation(**{k: v for k, v in base.items() if k != "bonus"})
    assert partial.bonus is None, "an unstated bonus is unknown, never zero"
    with pytest.raises(ValidationError, match="at least one"):
        PayObservation(**{**base, "total": None, "base": None, "equity": None, "bonus": None})
    with pytest.raises(ValidationError):
        PayObservation(**{k: v for k, v in base.items() if k != "currency"})
    assert PayObservation(**base, country="DE", family="software_engineering").country == "DE"
    with pytest.raises(ValidationError):
        PayObservation(**base, country="Germany")


# --------------------------------------------------------------------------- #
# The fake host's rules
# --------------------------------------------------------------------------- #


def _manifest(mutate=None, **job):
    data = copy.deepcopy(BASE)
    data["jobs"][0].update(job)
    if mutate:
        mutate(data)
    return validate_manifest(data)


def _plugin(fn) -> Plugin:
    plugin = Plugin("plugin-template")
    plugin.job("refresh")(fn)
    return plugin


def _host(manifest=None, **kwargs):
    kwargs.setdefault("companies", {"acme": "Acme Corp"})
    kwargs.setdefault("responses", {URL: FakeResponse(body={"ok": True})})
    return FakeHost(manifest or _manifest(), **kwargs)


def _run(fn, manifest=None, **kwargs):
    return _host(manifest, **kwargs).run("refresh", _plugin(fn))


def test_publishing_a_slot_the_job_does_not_declare_is_refused():
    def add_perks_job(d):
        d["provides"].append({"slot": "company.benefits"})
        d["jobs"].append({"name": "perks", "publishes": ["company.benefits"], "schedule": "manual",
                          "budget_seconds": 60})

    manifest = _manifest(add_perks_job)
    seen = []

    def job(ctx):
        try:
            ctx.publish("company.benefits", company="acme", rows=[{"name": "401k", "category": "Financial"}])
        except Refused as exc:
            seen.append(exc.message)

    plugin = Plugin()
    plugin.job("refresh")(job)
    plugin.job("perks")(lambda ctx: None)
    result = _host(manifest).run("refresh", plugin)
    assert seen and "does not publish 'company.benefits'" in seen[0]
    assert result.published == []
    assert result.outcome == "partial"


def test_an_uncaught_refusal_ends_the_run_in_error_with_nothing_published():
    result = _run(lambda ctx: ctx.get("https://evil.example.com/steal"))
    assert result.outcome == "error"
    assert "not declared in [network]" in result.message
    assert result.requests == [] and result.published == []


@pytest.mark.parametrize(
    ("url", "headers", "reason"),
    [
        ("https://evil.example.com/x", None, "not declared in [network]"),
        ("https://sub.data.example.com/x", None, "not declared in [network]"),
        ("http://data.example.com/x", None, "only https"),
        (URL, {"User-Agent": "Mozilla/5.0"}, "set by the host"),
        (URL, {"Cookie": "session=1"}, "set by the host"),
    ],
)
def test_the_host_fetches_only_declared_hosts_with_its_own_identity(url, headers, reason):
    caught = []

    def job(ctx):
        try:
            ctx.get(url, headers=headers)
        except Refused as exc:
            caught.append(exc.message)

    result = _run(job)
    assert caught and reason in caught[0]
    assert result.requests == []


def test_a_plugin_without_a_network_section_fetches_nothing():
    manifest = _manifest(lambda d: d.pop("network"))
    result = _run(lambda ctx: ctx.get(URL), manifest)
    assert result.outcome == "error" and "not declared" in result.message


def test_followed_companies_are_only_for_a_job_that_needs_them():
    result = _run(lambda ctx: ctx.companies(), _manifest(needs=[]))
    assert result.outcome == "error" and "does not declare needs" in result.message
    names = []
    _run(lambda ctx: names.extend(c.name for c in ctx.companies()))
    assert names == ["Acme Corp"]


def test_publishing_for_a_company_the_core_does_not_know_is_refused():
    result = _run(lambda ctx: ctx.publish(PAY_LEVELS, company="initech", rows=[_level()]))
    assert result.outcome == "error" and "not a company the core knows" in result.message


def test_the_host_revalidates_rows_a_plugin_sends_past_the_sdk():
    """A plugin can skip the SDK's validation and write to the transport
    directly; the host must refuse the row anyway."""

    def job(ctx):
        ctx._transport.call("publish", {"slot": PAY_LEVELS, "company": "acme", "complete": True,
                                        "rows": [_level(tc=True)]})

    result = _run(job)
    assert result.outcome == "error" and "row 0" in result.message
    assert result.published == []


def test_a_fact_claim_on_a_company_s_identity_is_refused_and_headcount_is_read():
    observed = "2026-09-30T00:00:00+00:00"
    ok = _run(lambda ctx: ctx.publish(COMPANY_FACTS, company="acme",
                                      rows=[{"field": "headcount", "value": 10, "observed_at": observed}]))
    assert ok.outcome == "clean" and [(f.field, f.value) for f in ok.rows(COMPANY_FACTS)] == [("headcount", 10)]
    bad = _run(lambda ctx: ctx.publish(COMPANY_FACTS, company="acme",
                                       rows=[{"field": "website", "value": "https://acme.example",
                                              "observed_at": observed}]))
    assert bad.outcome == "error" and "headcount" in (bad.message or "")


def test_a_pay_level_must_name_a_taxonomy_family():
    families = all_slugs()
    assert "software_engineering" in families
    ok = _run(lambda ctx: ctx.publish(PAY_LEVELS, company="acme", rows=[_level()]), families=families)
    assert ok.outcome == "clean"
    bad = _run(lambda ctx: ctx.publish(PAY_LEVELS, company="acme", rows=[_level(family="swe")]),
               families=families)
    assert bad.outcome == "error" and "not a taxonomy family" in bad.message


def test_a_url_with_no_recorded_response_never_reaches_the_network():
    result = _run(lambda ctx: ctx.get("https://data.example.com/v1/ladders/unrecorded.json"))
    assert result.outcome == "error" and protocol.NO_FIXTURE in result.message


def test_a_spent_budget_ends_the_run_bounded_past_except_exception():
    """Budget 4s, each request costs the core's 2s pacing floor (the manifest
    asks for 1s, and the real host never paces faster): the third request is
    over budget. The plugin catches Exception around every request, as a
    per-company skip would; the run must still end bounded, and every later
    call must get the same answer instead of being served."""
    after = []

    def job(ctx):
        for _ in range(5):
            try:
                ctx.get(URL)
            except Exception:  # noqa: BLE001 (the pattern under test)
                after.append("swallowed")
        after.append("kept going")

    result = _run(job, _manifest(budget_seconds=4))
    assert result.outcome == "bounded"
    assert after == []
    assert len(result.requests) == 2


def test_bounded_holds_even_when_the_plugin_catches_the_end_itself():
    calls = []

    def job(ctx):
        try:
            ctx.get(URL)
            ctx.get(URL)
        except RunEnded:
            pass
        for _ in range(3):
            try:
                ctx.publish(PAY_LEVELS, company="acme", rows=[_level()])
            except RunEnded as exc:
                calls.append(exc.code)

    result = _run(job, _manifest(budget_seconds=1))
    assert result.outcome == "bounded"
    assert calls == ["bounded"] * 3
    assert result.published == []


def test_a_stop_mid_run_keeps_what_was_published_and_serves_nothing_after():
    def job(ctx):
        ctx.publish(PAY_LEVELS, company="acme", rows=[_level()])
        ctx.publish(PAY_LEVELS, company="acme", rows=[_level(label="L6")])

    result = _run(job, stop_after_calls=1)
    assert result.outcome == "stopped"
    assert [r.label for r in result.rows(PAY_LEVELS)] == ["L5"]


def test_a_plugin_whose_jobs_differ_from_its_manifest_does_not_run():
    plugin = _plugin(lambda ctx: None)
    plugin.job("extra")(lambda ctx: None)
    with pytest.raises(ValueError, match="registers jobs"):
        _host().run("refresh", plugin)


def test_a_failing_job_is_an_error_with_its_reason():
    def job(ctx):
        raise KeyError("ladders")

    result = _run(job)
    assert result.outcome == "error" and "KeyError" in result.message


def test_state_round_trips_between_runs():
    first = _run(lambda ctx: ctx.state.set("cursor", {"page": 3}))
    seen = []
    _run(lambda ctx: seen.append((ctx.state.get("cursor"), ctx.state.get("missing", "dflt"))), state=first.state)
    assert seen == [({"page": 3}, "dflt")]


def test_a_report_keeps_the_latest_number_and_its_words_and_none_withdraws_it():
    def job(ctx):
        ctx.report("absent", 900, "followed companies the site does not list")
        ctx.report("stale", 3, "ladders older than a year")
        ctx.report("absent", 912, "followed companies the site does not list")
        ctx.report("stale", None, "ladders older than a year")

    result = _run(job)
    assert result.outcome == "clean", result.message
    assert result.reports == {"absent": (912, "followed companies the site does not list")}


@pytest.mark.parametrize(("key", "value", "label"), [
    ("Absent", 1, "x"), ("absent", -1, "x"), ("absent", 1, ""), ("absent", 1, "x" * 161), ("absent", True, "x"),
])
def test_a_report_the_host_cannot_show_is_refused(key, value, label):
    refused = []

    def job(ctx):
        try:
            ctx.report(key, value, label)
        except HostError as exc:
            refused.append(str(exc))

    result = _run(job)
    assert refused and result.reports == {}


def test_a_summary_keeps_the_latest_words():
    def job(ctx):
        ctx.summary("Read 1 of 2 companies")
        ctx.summary("Read 2 of 2 companies")

    result = _run(job)
    assert result.outcome == "clean", result.message
    assert result.summary == "Read 2 of 2 companies"


@pytest.mark.parametrize("text", ["", "x" * 161])
def test_a_summary_the_host_cannot_show_is_refused(text):
    refused = []

    def job(ctx):
        try:
            ctx.summary(text)
        except HostError as exc:
            refused.append(str(exc))

    result = _run(job)
    assert refused and result.summary is None


def test_a_plugin_reports_at_most_eight_numbers_and_may_still_update_them():
    refused = []

    def job(ctx):
        for i in range(9):
            try:
                ctx.report(f"k{i}", i, "numbers")
            except HostError:
                refused.append(i)
        ctx.report("k0", 99, "numbers")

    result = _run(job)
    assert refused == [8]
    assert len(result.reports) == 8 and result.reports["k0"] == (99, "numbers")


def test_numbers_an_earlier_run_reported_count_toward_the_cap():
    """The host keeps reports across runs, so a run that adds one key to eight
    kept ones is refused even though it reported only one itself."""
    kept = {f"k{i}": (i, "numbers") for i in range(protocol.MAX_REPORTS)}
    refused = []

    def job(ctx):
        for key, value in (("new", 1), ("k0", None), ("new", 2)):
            try:
                ctx.report(key, value, "numbers")
            except HostError:
                refused.append((key, value))

    result = _run(job, reports=kept)
    assert refused == [("new", 1)], "the first is refused; once k0 is withdrawn there is room"
    assert result.reports["new"] == (2, "numbers") and "k0" not in result.reports


@pytest.mark.parametrize(("kept", "refused"), [(protocol.MAX_STATE_KEYS - 1, False), (protocol.MAX_STATE_KEYS, True)])
def test_a_plugin_keeps_at_most_the_cap_of_state_keys_and_may_still_rewrite_them(kept, refused):
    state = {f"k{i}": i for i in range(kept)}
    seen = []

    def job(ctx):
        try:
            ctx.state.set("cursor", 1)
        except HostError as exc:
            seen.append(str(exc))
        ctx.state.set("k0", "rewritten")

    result = _run(job, state=state)
    assert bool(seen) is refused, seen
    assert ("cursor" in result.state) is not refused
    assert result.state["k0"] == "rewritten"


def _rows_manifest():
    def provide(d):
        d["provides"] = [{"slot": s} for s in (PAY_LEVELS, PAY_OBSERVATIONS, COMPANY_BENEFITS)]
        d["jobs"][0]["publishes"] = [PAY_LEVELS, PAY_OBSERVATIONS, COMPANY_BENEFITS]
    return _manifest(provide)


def _obs(key, total):
    return {"source_level": "L5", "total": total, "base": total, "equity": 0, "bonus": 0, "currency": "USD",
            "snapshot_date": "2026-09-01", "dedup_key": key}


def test_rows_are_what_the_store_keeps_one_per_key():
    """The store's unique key collapses rows that share it: a snapshot slot
    keeps the latest, history the first, and an observation's key spans
    companies. `published` still holds every row as it was sent."""

    def job(ctx):
        ctx.publish(PAY_LEVELS, company="acme", rows=[
            _level(country="US", tc=300000), _level(country="US", tc=310000),
            _level(country="GB", currency="GBP", tc=150000), _level(tc=280000)])
        ctx.publish(COMPANY_BENEFITS, company="acme", rows=[
            {"name": "401k", "category": "Financial", "value_text": "4%"},
            {"name": "401k", "category": "Financial", "value_text": "6%"}])
        ctx.publish(COMPANY_BENEFITS, company="globex", rows=[
            {"name": "401k", "category": "Financial", "value_text": "3%"}])
        ctx.publish(PAY_OBSERVATIONS, company="acme", rows=[_obs("k1", 200000), _obs("k1", 999999)])
        ctx.publish(PAY_OBSERVATIONS, company="globex", rows=[_obs("k1", 111111), _obs("k2", 222222)])

    result = _run(job, _rows_manifest(), companies={"acme": "Acme Corp", "globex": "Globex"})
    assert result.outcome == "clean", result.message
    assert [(r.country, r.currency, r.tc) for r in result.rows(PAY_LEVELS, "acme")] == [
        ("US", "USD", 310000), ("GB", "GBP", 150000), (None, "USD", 280000)]
    assert [r.value_text for r in result.rows(COMPANY_BENEFITS, "acme")] == ["6%"]
    assert [r.value_text for r in result.rows(COMPANY_BENEFITS, "globex")] == ["3%"]
    assert [(r.dedup_key, r.total) for r in result.rows(PAY_OBSERVATIONS)] == [("k1", 200000), ("k2", 222222)]
    assert [r.dedup_key for r in result.rows(PAY_OBSERVATIONS, "globex")] == ["k2"]
    assert sum(len(b.rows) for b in result.published) == 11


def test_a_snapshot_sent_in_chunks_is_read_whole_at_its_last_chunk():
    """More rows than one publish takes go in chunks, `complete=False` until the
    last and `complete=True` on it. The last closes the snapshot over every
    chunk: the company is read whole, and the rows of both chunks are kept, so
    none of them retires. A run that sends a company only incomplete chunks
    reads and retires nothing."""

    def chunked(ctx):
        ctx.publish(PAY_LEVELS, company="acme", rows=[_level(label="L4"), _level(label="L5")], complete=False)
        ctx.publish(PAY_LEVELS, company="acme", rows=[_level(label="L6")], complete=True)

    result = _run(chunked)
    assert result.outcome == "clean", result.message
    assert result.retires == {(PAY_LEVELS, "acme")}
    assert [r.label for r in result.rows(PAY_LEVELS, "acme")] == ["L4", "L5", "L6"]

    unfinished = _run(lambda ctx: ctx.publish(PAY_LEVELS, company="acme", rows=[_level(label="L4")], complete=False))
    assert unfinished.outcome == "clean" and unfinished.retires == set()


def test_every_fact_claim_is_kept_even_a_repeated_one():
    claim = {"field": "headcount", "value": 1200, "observed_at": "2026-09-30T00:00:00+00:00"}
    result = _run(lambda ctx: ctx.publish(COMPANY_FACTS, company="acme", rows=[claim, claim]))
    assert len(result.rows(COMPANY_FACTS, "acme")) == 2


def test_rows_cross_the_wire_as_json():
    """In process the fake host still encodes every call: a row that is not
    JSON on the wire fails here, not first against the real host."""
    result = _run(lambda ctx: ctx.publish(PAY_LEVELS, company="acme", rows=[PayLevel.model_validate(_level())]))
    (row,) = result.rows(PAY_LEVELS)
    assert row.as_of == date(2026, 9, 30)
    assert isinstance(row, PayLevel)


# --------------------------------------------------------------------------- #
# The runner process
# --------------------------------------------------------------------------- #


def _runner(tmp_path: Path, body: str, lines: list[dict]) -> subprocess.CompletedProcess:
    (tmp_path / "noisy_plugin.py").write_text(textwrap.dedent(body))
    env = {"PYTHONPATH": f"{SDK}:{tmp_path}", "PATH": "/usr/bin:/bin"}
    stdin = "".join(protocol.encode(m) for m in lines)
    return subprocess.run(
        [sys.executable, "-m", "roleband_plugin_sdk.runner", "--entry", "noisy_plugin:plugin", "--job", "refresh"],
        input=stdin, capture_output=True, text=True, env=env, timeout=30, check=False,
    )


START = {"type": "start", "protocol": PROTOCOL_VERSION, "run_id": "r1", "job": "refresh", "args": {}}

NOISY = """
    import os
    from roleband_plugin_sdk import Plugin
    plugin = Plugin()
    print("hello from import time")

    @plugin.job("refresh")
    def refresh(ctx):
        print("hello from the job")
        os.write(1, b"raw bytes on fd 1\\n")
        ctx.log("done")
"""


def test_the_runner_keeps_stdout_for_the_protocol(tmp_path):
    done = _runner(tmp_path, NOISY, [START, protocol.reply_ok(1, None)])
    messages = [protocol.decode(line) for line in done.stdout.splitlines()]
    assert [m["type"] for m in messages] == ["call", "end"], done.stdout
    assert messages[0]["method"] == "log" and messages[1]["status"] == "ok"
    assert "hello from the job" in done.stderr and "raw bytes on fd 1" in done.stderr
    assert done.returncode == 0


def test_the_runner_refuses_a_protocol_it_does_not_speak(tmp_path):
    done = _runner(tmp_path, NOISY, [{**START, "protocol": PROTOCOL_VERSION + 1}])
    (end,) = [protocol.decode(line) for line in done.stdout.splitlines()]
    assert end["type"] == "end" and end["status"] == "error" and "protocol" in end["message"]
    assert done.returncode == 2
    assert "hello from the job" not in done.stderr


def test_the_runner_reports_an_entry_that_does_not_load(tmp_path):
    done = _runner(tmp_path, "raise ImportError('broken plugin')\n", [START])
    (end,) = [protocol.decode(line) for line in done.stdout.splitlines()]
    assert end["status"] == "error" and "broken plugin" in end["message"]
    assert done.returncode == 1


def test_a_reply_to_the_wrong_call_is_a_protocol_error():
    reader = io.StringIO(protocol.encode(protocol.reply_ok(7, None)))
    transport = StdioTransport(reader, io.StringIO())
    with pytest.raises(protocol.ProtocolError, match="reply to call 1"):
        transport.call("log", {"level": "info", "message": "x"})


@pytest.mark.parametrize(
    ("code", "raised"),
    [(protocol.REFUSED, Refused), (protocol.INVALID, HostError), (protocol.BOUNDED, RunEnded),
     (protocol.STOPPED, RunEnded)],
)
def test_each_error_code_raises_its_kind(code, raised):
    class Once:
        def call(self, method, params):
            from roleband_plugin_sdk.context import raise_for

            return raise_for(protocol.reply_error(1, code, "x"))

    with pytest.raises(raised):
        JobContext(Once(), job="refresh", run_id="r").log("x")
    assert issubclass(RunEnded, BaseException) and not issubclass(RunEnded, Exception)


def test_the_host_validates_call_parameters():
    with pytest.raises(protocol.CallError, match="unknown method"):
        protocol.parse_call({"type": "call", "id": 1, "method": "sql.execute", "params": {}})
    with pytest.raises(protocol.CallError, match="limit"):
        protocol.parse_call({"type": "call", "id": 1, "method": "state.set",
                             "params": {"key": "k", "value": "x" * 70000}})
    with pytest.raises(protocol.ProtocolError):
        protocol.parse_call({"type": "call", "id": "1", "method": "log", "params": {}})


def test_progress_cannot_pass_its_total():
    with pytest.raises(protocol.CallError, match="exceeds"):
        protocol.parse_call({"type": "call", "id": 1, "method": "progress", "params": {"done": 3, "total": 2}})



# --------------------------------------------------------------------------- #
# Long jobs: a pass across runs
# --------------------------------------------------------------------------- #

SLUGS = ("acme", "brix", "cora", "dune", "evex", "fizz")


def _pass_host(state=None, **kwargs):
    """Six companies; each read costs the 2 s pacing floor. With a 9 s budget and
    the job's 3.5 s margin, a run reads three (9, 7 and 5 s left) and stops
    before the fourth (3 s left)."""
    kwargs.setdefault("budget_seconds", 9)
    return FakeHost(_manifest(), companies={s: s.title() for s in SLUGS}, state=state,
                    responses={f"https://data.example.com/v1/ladders/{s}.json": FakeResponse(body={}) for s in SLUGS},
                    **kwargs)


def _pass_job(failing=()):
    def job(ctx):
        def read(company):
            if company.slug in failing:
                raise ValueError(f"{company.slug} page changed shape")
            ctx.get(f"https://data.example.com/v1/ladders/{company.slug}.json")
            ctx.publish(PAY_LEVELS, company=company.slug, rows=[_level()])

        ctx.resume("refresh", ctx.companies(), read, key=lambda c: c.slug, margin=3.5)

    return job


def test_a_pass_spans_runs_each_ends_clean_and_the_last_says_it_is_through():
    """Every run stops at a unit boundary before its budget, so each ends clean:
    what it published is read, and what it published complete retires. `more`
    asks the host to continue; the last run clears the cursor."""
    first = _pass_host().run("refresh", _plugin(_pass_job()))
    assert (first.outcome, first.more) == ("clean", True)
    assert {b.company for b in first.published} == {"acme", "brix", "cora"}
    assert first.retires == {(PAY_LEVELS, s) for s in ("acme", "brix", "cora")}
    assert first.state["resume.refresh"] == "cora"

    second = _pass_host(state=first.state).run("refresh", _plugin(_pass_job()))
    assert (second.outcome, second.more) == ("clean", False)
    assert {b.company for b in second.published} == {"dune", "evex", "fizz"}
    assert second.state["resume.refresh"] is None
    assert second.progress[-1] == (6, 6)

    third = _pass_host(state=second.state).run("refresh", _plugin(_pass_job()))
    assert {b.company for b in third.published} == {"acme", "brix", "cora"}, "a new pass starts at the top"


def test_one_unit_that_fails_is_logged_and_the_pass_moves_on():
    result = _pass_host(budget_seconds=100).run("refresh", _plugin(_pass_job(failing={"brix"})))
    assert (result.outcome, result.more) == ("clean", False)
    assert "brix" not in {b.company for b in result.published} and len(result.published) == 5
    assert ("warning", "refresh: brix skipped: ValueError: brix page changed shape") in result.logs


def test_a_run_the_host_ends_keeps_the_cursor_before_the_unit_it_interrupted():
    """A budget too small for the margin to save it (one read costs 2 s, 3 s
    left): the host ends the run `bounded` mid-unit, and the next run reads that
    unit again."""
    def job(ctx):
        ctx.resume("refresh", ctx.companies(),
                   lambda c: ctx.get(f"https://data.example.com/v1/ladders/{c.slug}.json"),
                   key=lambda c: c.slug, margin=0)

    result = _pass_host(budget_seconds=5).run("refresh", _plugin(job))
    assert result.outcome == "bounded" and result.state["resume.refresh"] == "brix"
    assert result.retires == set(), "nothing was published, so nothing is read or retires"


def test_time_left_is_unknown_to_a_job_whose_host_did_not_say():
    assert JobContext(object(), job="refresh", run_id="r").time_left() is None  # type: ignore[arg-type]


def test_the_fake_host_refuses_what_the_real_host_refuses():
    stealthy = _manifest(lambda d: d["network"].update(identity="tls_fingerprint"))
    assert any("consent" in r for r in _run(lambda ctx: ctx.get(URL), stealthy).refusals)
    walled = _run(lambda ctx: ctx.get(URL), robots={"data.example.com": "User-agent: *\nDisallow: /v1/\n"})
    assert any("robots.txt on data.example.com disallows" in r for r in walled.refusals)
    made_up = _run(lambda ctx: ctx.publish(PAY_LEVELS, company="acme", rows=[_level(family="rocket_science")]))
    assert made_up.outcome == "error" and "taxonomy family" in (made_up.message or "")


def test_the_sdk_s_taxonomy_families_are_the_core_s():
    from roleband_plugin_sdk.slots import TAXONOMY_FAMILIES

    assert sorted(TAXONOMY_FAMILIES) == sorted(all_slugs())


def test_a_pass_crosses_the_real_runner_with_its_budget_and_more(monkeypatch):
    """`budget_seconds` reaches the runner in `start` and `more` comes back in
    `end`, over stdio as the host runs it."""
    entry_dir = Path(__file__).parent / "fixtures" / "plugin_pass"
    assert entry_dir.is_dir()
    # The jobs are checked in this process before the runner starts.
    monkeypatch.syspath_prepend(str(entry_dir))
    host = _pass_host(budget_seconds=0.5, code=entry_dir)
    host.manifest = _manifest(lambda d: d["plugin"].update(entry="pass_plugin:plugin"))
    result = host.run("refresh", subprocess=True)
    assert (result.outcome, result.more) == ("clean", True), (result.message, result.stderr)
    assert result.published == []


def test_a_runner_process_starts_where_the_live_host_starts_it(tmp_path, monkeypatch):
    """The live host runs the plugin isolated, in `/`, with only the SDK and
    the plugin's code on its path. A plugin that reads a file relative to the
    test's working directory passes in process and must fail over the runner
    as it fails live."""
    entry_dir = Path(__file__).parent / "fixtures" / "plugin_where"
    (tmp_path / "notes.txt").write_text("found")
    monkeypatch.chdir(tmp_path)
    monkeypatch.syspath_prepend(str(entry_dir))

    def host():
        made = _host(code=entry_dir)
        made.manifest = _manifest(lambda d: d["plugin"].update(entry="where_plugin:plugin"))
        return made

    from where_plugin import plugin

    assert host().run("refresh", plugin).outcome == "clean"
    live = host().run("refresh", subprocess=True)
    assert live.outcome == "error", live.stderr
    assert "notes.txt" in (live.message or "") + live.stderr


def test_a_runner_process_needs_to_know_where_the_plugin_is():
    with pytest.raises(ValueError, match="manifest's path, or `code=`"):
        _host().run("refresh", subprocess=True)


def test_the_sdk_paces_at_the_core_s_default_delay():
    """`FakeHost` charges each request the floor the real host applies."""
    from roleband_plugin_sdk.policy import CORE_MIN_DELAY_SECONDS

    from tracker.config import Settings

    assert CORE_MIN_DELAY_SECONDS == Settings.model_fields["scraper_min_delay_seconds"].default
