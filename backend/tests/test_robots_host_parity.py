"""The fake host answers robots exactly as the live host does.

A plugin author's whole reason for `FakeHost` is that a green test predicts a
live run. Robots is where that promise is easiest to break, because the two
hosts once read the file with different parsers: the live one with RFC 9309
(`roleband_robots`), the fake one with `urllib.robotparser`, which follows the
1996 draft. The two disagree on real careers sites in both directions, so an
author could be refused live on a path their tests fetched, or fetch a path
live that their tests believed was refused.

They now share one package, so parity is structural. These hold the three
places a shared matcher alone would not have fixed: the string matched, the
agent whose rules are read, and what a refused robots file means.
"""

from __future__ import annotations

from urllib.robotparser import RobotFileParser

import pytest
from roleband_plugin_sdk.testing import DEFAULT_AGENT
from roleband_robots import path_allowed, target_for

#: A blank line between two agent lines: a record separator to the 1996
#: draft, nothing to RFC 9309, so the two read it differently.
ACCUMULATED_GROUP = "User-agent: *\n\nUser-agent: Yandex\nDisallow: /private\n"
#: A blanket refusal with one route named back, which careers sites do write.
ALLOW_UNDER_DISALLOW = "User-agent: *\nDisallow: /\nAllow: /api/pcsx\n"


@pytest.mark.parametrize(
    ("text", "url", "allowed"),
    [
        # The group runs to the next agent line that follows a RULE, so the
        # blank changes nothing and `*` carries the disallow (RFC 9309 2.2.1).
        # The stdlib ends the record at the blank and allows this.
        (ACCUMULATED_GROUP, "https://x.test/private/pay", False),
        (ACCUMULATED_GROUP, "https://x.test/public/pay", True),
        # Longest match wins and allow breaks a tie (2.2.2). The stdlib takes
        # the first match in file order and refuses this.
        (ALLOW_UNDER_DISALLOW, "https://x.test/api/pcsx/jobs", True),
        (ALLOW_UNDER_DISALLOW, "https://x.test/careers", False),
    ],
)
def test_the_shared_matcher_follows_the_rfc_where_the_stdlib_does_not(text, url, allowed):
    assert path_allowed(text, target_for(url), agent=DEFAULT_AGENT)[0] is allowed


def test_the_stdlib_parser_really_does_disagree():
    """The negative control. Without it these cases could silently become
    agreement, and the package would look unnecessary."""
    stdlib = []
    for text, url in ((ACCUMULATED_GROUP, "https://x.test/private/pay"),
                      (ALLOW_UNDER_DISALLOW, "https://x.test/api/pcsx/jobs")):
        parser = RobotFileParser()
        parser.parse(text.splitlines())
        stdlib.append(parser.can_fetch("*", url))
    ours = [path_allowed(ACCUMULATED_GROUP, "/private/pay", agent="*")[0],
            path_allowed(ALLOW_UNDER_DISALLOW, "/api/pcsx/jobs", agent="*")[0]]
    assert stdlib == [True, False], "the 1996 draft's answers"
    assert ours == [False, True], "and the RFC's, opposite on both"



def test_a_rule_is_matched_against_the_path_and_the_query():
    """A directive may name a query, so matching the path alone answers a
    different question. Both hosts build this string from `target_for`."""
    assert target_for("https://x.test/search?q=pay") == "/search?q=pay"
    text = "User-agent: *\nDisallow: /search?*\n"
    assert path_allowed(text, target_for("https://x.test/search?q=pay"))[0] is False
    assert path_allowed(text, target_for("https://x.test/search"))[0] is True


def test_the_agent_the_host_fetches_as_selects_the_group():
    """The live host matches the User-Agent it sends, so a group naming it
    wins over `*`. A fake host reading `*` would answer a different file."""
    text = (
        "User-agent: *\nDisallow: /\n\n"
        f"User-agent: {DEFAULT_AGENT}\nAllow: /\n"
    )
    assert path_allowed(text, "/pay", agent=DEFAULT_AGENT)[0] is True
    assert path_allowed(text, "/pay", agent="SomeOtherBot")[0] is False


# --------------------------------------------------------------------------- #
# Driving the fake host itself. The cases above exercise the shared functions;
# these prove `FakeHost` actually reaches them, which a test of the functions
# alone cannot say.
# --------------------------------------------------------------------------- #

PAGE = "https://data.example.com/v1/ladders/acme.json"


def _fake_run(robots, url=PAGE):
    """One job, one fetch, through the real FakeHost."""
    import copy
    import tomllib
    from pathlib import Path

    from roleband_plugin_sdk.manifest import validate_manifest
    from roleband_plugin_sdk.plugin import Plugin
    from roleband_plugin_sdk.testing import FakeHost, FakeResponse

    template = Path(__file__).resolve().parents[2] / "examples" / "plugin-template"
    manifest = validate_manifest(copy.deepcopy(tomllib.loads((template / "roleband-plugin.toml").read_text())))
    plugin = Plugin("plugin-template")
    plugin.job("refresh")(lambda ctx: ctx.get(url))
    host = FakeHost(manifest, companies={"acme": "Acme Corp"},
                    responses={url: FakeResponse(body={"ok": True})}, robots=robots)
    return host.run("refresh", plugin)


def test_the_fake_host_allows_the_path_the_rfc_allows():
    """`Disallow: /` with one route named back. The stdlib refuses it, so a
    fake host on the stdlib would fail a plugin the live host serves.
    Fail-first: the run ends `error` with a robots refusal."""
    result = _fake_run({"data.example.com": ALLOW_UNDER_DISALLOW},
                       url="https://data.example.com/api/pcsx/jobs")
    assert result.outcome != "error", result.message


def test_the_fake_host_refuses_the_path_the_rfc_refuses():
    result = _fake_run({"data.example.com": "User-agent: *\nDisallow: /v1\n"})
    assert result.outcome == "error"
    assert "disallows /v1/ladders/acme.json" in result.message


def test_a_host_that_refused_its_robots_file_disallows_everything():
    """The live host treats 401, 403 and 5xx on robots.txt as the site
    refusing us, not as stating no rule. `None` records that."""
    result = _fake_run({"data.example.com": None})
    assert result.outcome == "error"
    assert "refused us" in result.message


def test_a_host_with_no_robots_recorded_allows_everything():
    assert _fake_run({}).outcome != "error"


def test_the_fake_host_reads_the_group_naming_the_agent_it_fetches_as():
    """A file that refuses `*` and allows the host's own agent. Reading `*`
    would refuse a path the live host fetches. Fail-first: the run errors."""
    text = f"User-agent: *\nDisallow: /\n\nUser-agent: {DEFAULT_AGENT}\nAllow: /\n"
    assert _fake_run({"data.example.com": text}).outcome != "error"
