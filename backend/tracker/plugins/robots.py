"""The robots rules a plugin's sites set for RoleBand, as the user is shown them
before allowing the plugin past them.

The host follows every declared site's robots file (path and query, the group
naming our agent first). The user may allow a plugin past them: one
choice per plugin, covering everything it reads, recorded as the sha256 of each
file they were shown (`plugin_install.robots_consent`). The host reads a
disallowed page only while the site's file is still that one; a site that changes
its file is asked about again. A site that refuses its robots file (401, 403,
5xx) is refusing us, not stating a rule, and is never consented past.

The dialog and the host read a file the same way (`read_robots`), so the rules
the user is shown are the rules a run follows. This module imports nothing of
the plugin SDK, so the API may use it.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from typing import Any

import httpx
from roleband_robots import agent_rules

from tracker.config import get_settings
from tracker.platform.safe_fetch import BlockedDestination, fetch_public, public_client

#: How long the dialog waits for one site's robots file.
ROBOTS_TIMEOUT = 10.0
#: The most of a robots file that is read: RFC 9309's lowest allowed parsing
#: limit. Rules past it are not read.
ROBOTS_MAX_BYTES = 500 * 1024

#: What `read_robots` found: a file (its text), a site that refused it, or no
#: answer now.
ROBOTS_READ, ROBOTS_REFUSED, ROBOTS_FAILED = "read", "refused", "failed"


def robots_sha(text: str) -> str:
    """A robots file's identity, as a consent names it: sha256 of its text, so
    the dialog that showed it and the host that reads it agree."""
    return hashlib.sha256(text.encode()).hexdigest()


def disallowed(text: str, agent: str) -> list[str]:
    """The patterns `text` disallows for `agent` (its own group, else `*`)."""
    return [pattern for kind, pattern in agent_rules(text, agent) if kind == "disallow" and pattern]


async def read_robots(client: httpx.AsyncClient, host: str) -> tuple[str, str | None]:
    """`host`'s robots file, as both the dialog and the host read it.

    Redirects are followed, five hops as RFC 9309 asks, each re-checked
    (`fetch_public`), and the body is capped at `ROBOTS_MAX_BYTES`.
    `(ROBOTS_READ, text)`: the file, empty when the site serves none (any other
    4xx, or a 3xx with nowhere to go). `(ROBOTS_REFUSED, None)`: 401, 403 or
    5xx, which disallows everything. `(ROBOTS_FAILED, None)`: no answer now (the
    network, a hop that is not public, too many redirects)."""
    try:
        page = await fetch_public(client, f"https://{host}/robots.txt", max_bytes=ROBOTS_MAX_BYTES)
    except (httpx.HTTPError, httpx.InvalidURL, BlockedDestination, ValueError):
        return ROBOTS_FAILED, None
    if page.status in (401, 403) or page.status >= 500:
        return ROBOTS_REFUSED, None
    return ROBOTS_READ, page.text if 200 <= page.status < 300 else ""


async def site_rules(hosts: Iterable[str], *, client: httpx.AsyncClient | None = None) -> list[dict[str, Any]]:
    """Each host's robots file as the user is shown it: `state` `rules` (it
    disallows something for us, listed in `disallow`), `none` (nothing, or no
    file), `refused` (the site would not show it; it disallows everything and
    cannot be consented past) or `failed` (unreachable now); `sha256` names the
    file a consent is for (null when refused or failed)."""
    own = client is None
    client = client or public_client(user_agent=get_settings().scraper_user_agent, timeout=ROBOTS_TIMEOUT)
    agent = client.headers.get("user-agent", "*")
    out: list[dict[str, Any]] = []
    try:
        for host in hosts:
            state, text = await read_robots(client, host)
            if text is None:
                out.append({"host": host, "state": state, "sha256": None, "disallow": []})
                continue
            rules = disallowed(text, agent)
            out.append({"host": host, "state": "rules" if rules else "none", "sha256": robots_sha(text),
                        "disallow": rules})
    finally:
        if own:
            await client.aclose()
    return out
