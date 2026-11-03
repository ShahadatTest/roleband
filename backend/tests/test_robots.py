"""RFC 9309 evaluation.

Every case here is a real file shape, and the two that
matter are the two `urllib.robotparser` gets wrong. They are not academic: read
with the stdlib, google's board looks permitted and microsoft's looks forbidden
— both backwards — and a review register built on either answer would record
the opposite of the truth.
"""

from __future__ import annotations

import pytest
from roleband_robots import agent_rules, path_allowed, robots_groups

# google.com/robots.txt opens with these two lines, in this order.
GROUPED_AGENTS = """\
User-agent: *
User-agent: Yandex
Disallow: /about/careers/applications/jobs/results?page=
Allow: /search/about
"""

# apply.careers.microsoft.com and explore.jobs.netflix.net (same Eightfold
# template): a blanket refusal with the API route we use explicitly permitted.
BLANKET_WITH_ALLOWLIST = """\
User-agent: *
Disallow: /
Allow: /$
Allow: /careers
Allow: /api/pcsx
Allow: /api/apply
"""


def test_consecutive_agent_lines_form_one_group():
    """The stdlib reads these as two groups, leaving `*` with no rules and every
    path allowed. Both agents share the rules below them."""
    (group,) = robots_groups(GROUPED_AGENTS)

    assert group.agents == ("*", "yandex")
    assert len(group.rules) == 2
    assert len(agent_rules(GROUPED_AGENTS, "*")) == 2


def test_a_new_group_starts_at_the_first_agent_after_a_rule():
    text = "User-agent: *\nDisallow: /a\nUser-agent: bot\nDisallow: /b\n"
    star, bot = robots_groups(text)

    assert star.agents == ("*",) and star.rules == (("disallow", "/a"),)
    assert bot.agents == ("bot",) and bot.rules == (("disallow", "/b"),)


def test_the_longest_matching_pattern_wins_not_the_first():
    """`Disallow: /` comes first in the file, and the stdlib stops there —
    refusing a route the operator went out of their way to permit by name."""
    allowed, rule = path_allowed(BLANKET_WITH_ALLOWLIST, "/api/pcsx/search")

    assert allowed is True
    assert rule == ("allow", "/api/pcsx")


def test_the_blanket_rule_still_refuses_everything_it_alone_matches():
    """The negative control for the rule above: precedence must not degrade into
    "an allowlist anywhere in the file permits everything"."""
    allowed, rule = path_allowed(BLANKET_WITH_ALLOWLIST, "/candidate/profile")

    assert allowed is False
    assert rule == ("disallow", "/")


def test_a_rule_can_match_on_the_query_string():
    """google disallows `.../jobs/results?page=` and leaves the bare path alone,
    so a matcher fed only the path reads the board as permitted. Our adapter
    sends `page` as its FIRST parameter, which is what makes the literal prefix
    match."""
    disallowed, rule = path_allowed(
        GROUPED_AGENTS,
        "/about/careers/applications/jobs/results?page=1&sort_by=date&location=US",
    )
    assert disallowed is False
    assert rule == ("disallow", "/about/careers/applications/jobs/results?page=")

    # Same path without the parameter: nothing matches, so it is permitted.
    bare, bare_rule = path_allowed(
        GROUPED_AGENTS, "/about/careers/applications/jobs/results"
    )
    assert bare is True and bare_rule is None


def test_no_matching_rule_is_allowed_and_says_so_by_returning_none():
    """Absence of a rule is permission, and it must stay distinguishable from an
    explicit `Allow:` — a register that cannot tell them apart records "allowed
    by the operator" where the operator said nothing at all."""
    assert path_allowed("User-agent: *\nDisallow: /admin\n", "/v1/boards/x/jobs") == (
        True,
        None,
    )


def test_an_empty_file_allows_everything():
    assert path_allowed("", "/anything") == (True, None)


def test_an_empty_disallow_value_is_not_a_rule():
    """`Disallow:` with no value means "nothing is disallowed" (RFC 9309 §2.2.2), and must
    never be read as a zero-length pattern matching every path."""
    allowed, rule = path_allowed("User-agent: *\nDisallow:\n", "/anything")

    assert allowed is True and rule is None


def test_a_trailing_dollar_anchors_the_end_of_the_path():
    text = "User-agent: *\nDisallow: /\nAllow: /$\n"

    assert path_allowed(text, "/")[0] is True
    assert path_allowed(text, "/careers")[0] is False


def test_a_named_group_replaces_the_star_group_rather_than_adding_to_it():
    """RFC 9309 §2.2.1: exactly one group applies. A crawler named in its own group does
    not also inherit `*`, so a permissive named group is not narrowed by a
    blanket `*` refusal elsewhere in the file."""
    text = "User-agent: *\nDisallow: /\nUser-agent: roleband\nAllow: /\n"

    assert path_allowed(text, "/jobs", agent="RoleBand/1.0")[0] is True
    assert path_allowed(text, "/jobs", agent="SomeoneElse/1.0")[0] is False


@pytest.mark.parametrize("comment", ["Disallow: /x  # trailing", "# whole line", ""])
def test_comments_and_blank_lines_are_ignored_without_breaking_a_group(comment):
    text = f"User-agent: *\n{comment}\nAllow: /ok\n"

    assert path_allowed(text, "/ok")[0] is True


def test_repeated_groups_for_one_agent_are_combined():
    """RFC 9309 §2.2.1: "if there is more than one group matching the user-agent, the
    matching groups' rules MUST be combined into one group".

    Keeping only the first match would report every later block's paths as ALLOWED
    — an operator's refusal read as permission because they wrote it in a second
    block. That is the direction a robots matcher must never be wrong in, and
    the register calls this module RFC-correct in writing.
    """
    text = "User-agent: RoleBand\nDisallow: /a\n\nUser-agent: RoleBand\nDisallow: /b\n"

    assert agent_rules(text, "RoleBand/1.0") == [("disallow", "/a"), ("disallow", "/b")]
    assert path_allowed(text, "/a", agent="RoleBand/1.0")[0] is False
    assert path_allowed(text, "/b", agent="RoleBand/1.0")[0] is False


def test_combining_does_not_reach_across_two_different_product_tokens():
    """Merging is per matching token, and specificity is resolved first.

    `RoleBand` and `RoleBandBot` are two crawlers. A file addressing both is
    answering two questions, so pulling the shorter token's rules into the
    longer one's group would be as wrong as dropping a repeated group.
    """
    text = "User-agent: roleband\nDisallow: /a\n\nUser-agent: rolebandbot\nDisallow: /b\n"

    assert agent_rules(text, "RoleBandBot/1.0") == [("disallow", "/b")]
    assert path_allowed(text, "/a", agent="RoleBandBot/1.0")[0] is True


@pytest.mark.parametrize(
    ("pattern", "target"),
    [
        ("/jobs", "/%6Aobs"),   # encoded in the request
        ("/%6Aobs", "/jobs"),   # encoded in the rule
        ("/~foo", "/%7Efoo"),   # the classic tilde case
        ("/%7Efoo", "/~foo"),
    ],
)
def test_a_percent_encoded_unreserved_character_is_the_same_path(pattern, target):
    """RFC 9309 §2.2.2: "if a percent-encoded ASCII octet is encountered in the URI, it
    MUST be unencoded prior to comparison, unless it is a reserved character
    [...] or outside the unreserved character range".

    Without it a disallow is evadable by spelling, which is the one property
    this matcher must not have. Both sides normalize, so an operator writing
    the encoded form is not answered with a false *deny* either.
    """
    text = f"User-agent: *\nDisallow: {pattern}\n"

    assert path_allowed(text, target)[0] is False


def test_a_reserved_octet_stays_encoded_because_it_means_something_else():
    """`%2F` is not `/`: decoding it would merge a path separator with a literal
    inside a segment, and disallow a route the operator never named."""
    assert path_allowed("User-agent: *\nDisallow: /a/b\n", "/a%2Fb")[0] is True
    # Spelling of the encoding itself is not significant, though.
    assert path_allowed("User-agent: *\nDisallow: /a%2Fb\n", "/a%2fb")[0] is False
