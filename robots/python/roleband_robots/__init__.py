"""RFC 9309 robots.txt evaluation. Pure, stdlib-only, no product knowledge.

Its own distribution because two things must answer this question the same
way: the host that fetches, and the fake host a plugin author tests against
(`roleband_plugin_sdk.testing`). A copy in each would agree on the day it was
copied and drift once they ship under separate versions, which is exactly the
failure a plugin author hits as "it passed my tests and failed live". One
package, one version, pinnable by both.

It is also why this is not inside the SDK: the API and the pipeline must
import without loading any plugin machinery, which
`test_the_api_and_the_pipeline_import_without_the_plugin_sdk` holds them to.

It knows nothing about companies, adapters or policy, and answers exactly one
question: does this robots.txt permit this path for this agent?

**Why not `urllib.robotparser`.** It follows the 1996 draft, not RFC 9309, and
gets both rules that matter here wrong:

* **Group accumulation.** A group is one or more `User-agent` lines followed
  by rules, and it ends at the next `User-agent` line that FOLLOWS a rule
  (RFC 9309 §2.2.1). A blank line does not end it. The 1996 draft treats a
  blank line as a record separator, so

      User-agent: *
      <blank>
      User-agent: Yandex
      Disallow: /private

  gives `*` an empty record and every path reads as allowed, where the RFC
  gives the rule to both names. (Consecutive agent lines with no blank
  between them the stdlib does accumulate; the blank is the trigger.)
* **Precedence.** The most specific (longest) matching pattern wins, and `allow`
  wins a tie (RFC 9309 §2.2.2); the stdlib takes the first match in file order.
  On a `Disallow: /` followed by `Allow: /api/pcsx`, first-match-wins refuses a
  path the operator explicitly permitted, and careers sites do name one API
  route in an `Allow:` line under a blanket disallow.

A directive is a technical access control, not a grant of rights: RFC 9309 §1
says so outright, and a permitted path can still be prohibited by terms. So
this module answers only the robots question, and `tracker.source_review` keeps
it as ONE input to a review decision rather than the decision.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlsplit

__all__ = ["RobotsRule", "agent_rules", "path_allowed", "robots_groups", "target_for"]

#: `allow` | `disallow` plus the pattern, verbatim as the file wrote it.
RobotsRule = tuple[str, str]


@dataclass(frozen=True)
class _Group:
    agents: tuple[str, ...]
    rules: tuple[RobotsRule, ...]


def robots_groups(text: str) -> list[_Group]:
    """Parse into agent groups, accumulating consecutive `User-agent` lines.

    A group ends at the first `User-agent` line that follows a rule, which is
    what makes the accumulation rule work: agent names pile up until a rule
    appears, and the next agent name after that starts a new group.
    """
    groups: list[_Group] = []
    agents: list[str] = []
    rules: list[RobotsRule] = []
    collecting_agents = True

    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        key, _, value = line.partition(":")
        key, value = key.strip().lower(), value.strip()
        if key == "user-agent":
            if not collecting_agents:
                groups.append(_Group(tuple(agents), tuple(rules)))
                agents, rules = [], []
            agents.append(value.lower())
            collecting_agents = True
        elif key in ("allow", "disallow"):
            collecting_agents = False
            rules.append((key, value))
    if agents or rules:
        groups.append(_Group(tuple(agents), tuple(rules)))
    return groups


def agent_rules(text: str, agent: str = "*") -> list[RobotsRule]:
    """Rules for one agent: its most specific named token, else the `*` group.

    Two rules from RFC 9309 §2.2.1, and they are not the same rule:

    * a crawler named in its own group does NOT also inherit the `*` rules —
      the wildcard is a fallback for agents no group names, not a base class;
    * "if there is more than one group matching the user-agent, the matching
      groups' rules MUST be combined into one group". Operators do split a
      crawler's rules across repeated `User-agent:` blocks, and keeping only
      the first reports the later blocks' paths as
      *allowed* — the direction that manufactures permission we were never
      given.

    Specificity is resolved before combining: the longest matching product
    token wins, and every group naming that token contributes. A file with
    `RoleBand` and `RoleBandBot` groups is answering two different crawlers, so
    merging those would be as wrong as dropping one.
    """
    lowered = agent.lower()
    groups = robots_groups(text)
    longest = max(
        (len(name) for group in groups for name in group.agents
         if name != "*" and name in lowered),
        default=0,
    )
    if longest:
        return [
            rule
            for group in groups
            for rule in group.rules
            if any(name != "*" and len(name) == longest and name in lowered
                   for name in group.agents)
        ]
    return [rule for group in groups if "*" in group.agents for rule in group.rules]


#: RFC 3986 §2.3. A percent-encoded octet standing for one of these is the same
#: character spelled the long way, and must be decoded before comparison.
_UNRESERVED = frozenset(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~"
)
_PERCENT = re.compile(r"%([0-9A-Fa-f]{2})")


def _normalize(value: str) -> str:
    """RFC 9309 §2.2.2 comparison form: decode unreserved octets, upper-case the rest.

    "If a percent-encoded ASCII octet is encountered in the URI, it MUST be
    unencoded prior to comparison, unless it is a reserved character [...] or
    the character is outside the unreserved character range." So `/%6Aobs` and
    `/jobs` are one path; disallowing the second while the first reads allowed
    would make a rule evadable by spelling, which is the one property
    a robots matcher must not have. Reserved octets stay encoded, because there
    `%2F` and `/` genuinely differ; their hex is upper-cased so the two
    spellings of an encoding still compare equal (RFC 3986 §6.2.2.1).
    """

    def decode(match: re.Match[str]) -> str:
        char = chr(int(match.group(1), 16))
        return char if char in _UNRESERVED else f"%{match.group(1).upper()}"

    return _PERCENT.sub(decode, value)


def _pattern_matches(pattern: str, target: str) -> bool:
    """RFC 9309 §2.2.2 path matching: `*` is any sequence, a trailing `$` anchors the end.

    `target` is a path plus query string, because operators write rules against
    query strings — a site can disallow `.../jobs/results?page=` while leaving
    the bare path alone, and a matcher fed only the path would miss it entirely.

    Both sides are put in comparison form first — see `_normalize`. The pattern
    too, not just the URI: an operator who writes `Disallow: /%7Efoo` and a
    request for `/~foo` are talking about the same path, and only normalizing
    one side would trade a false allow for a false deny.
    """
    if not pattern:
        return False
    anchored = pattern.endswith("$")
    body = _normalize(pattern[:-1] if anchored else pattern)
    expression = "".join(".*" if char == "*" else re.escape(char) for char in body)
    return re.match(f"^{expression}{'$' if anchored else ''}", _normalize(target)) is not None


def target_for(url: str) -> str:
    """What a rule is matched against: the path AND the query.

    A directive may name a query (`Disallow: /search?*`), so matching the path
    alone answers a different question. Here rather than in either caller,
    because two callers building this string separately is two chances to
    build it differently, and the difference only shows up as a plugin that
    passed its tests and was refused live.
    """
    parts = urlsplit(url)
    return (parts.path or "/") + (f"?{parts.query}" if parts.query else "")


def path_allowed(
    text: str, target: str, *, agent: str = "*"
) -> tuple[bool, RobotsRule | None]:
    """Is `target` (path + query) allowed? Returns the deciding rule too.

    The rule is returned because "disallowed" is not a useful record on its own:
    a review register has to say WHICH directive decided, or the next reader
    cannot tell a blanket refusal from one narrow pattern and has to re-derive
    the whole file.

    No matching rule means allowed with `None` — absence of a rule is
    permission, and it must be distinguishable from an explicit `Allow:`.
    """
    best: tuple[int, str, str] | None = None
    for kind, pattern in agent_rules(text, agent):
        if _pattern_matches(pattern, target):
            length = len(pattern)
            # Longest wins; `allow` wins a tie of equal length (RFC 9309 §2.2.2).
            if best is None or length > best[0] or (length == best[0] and kind == "allow"):
                best = (length, kind, pattern)
    if best is None:
        return True, None
    return best[1] == "allow", (best[1], best[2])
