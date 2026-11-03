"""The plugin template and the only internet its tests have.

`Web` serves the template's recorded Acme ladder and a 404 for Globex, and
records every request and user agent; the helpers seed the two companies the
template reads and read back the levels a run published.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
from sqlalchemy import select

from tracker.db.models import CompanyCompLevel, CompanyProfile, TrackedCompany

REPO = Path(__file__).resolve().parents[2]
TEMPLATE = REPO / "examples" / "plugin-template"
ACME = json.loads((TEMPLATE / "tests" / "fixtures" / "acme.json").read_text())
BASE = "https://data.example.com/v1/ladders"


class Web:
    """The only internet these tests have."""

    def __init__(self, pages: dict[str, httpx.Response] | None = None, robots: str = "User-agent: *\nAllow: /\n"):
        self.requests: list[str] = []
        self.user_agents: set[str] = set()
        self.pages = pages if pages is not None else {
            f"{BASE}/acme.json": httpx.Response(200, json=ACME),
            f"{BASE}/globex.json": httpx.Response(404),
        }
        self.robots = robots

    def handler(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        self.requests.append(url)
        self.user_agents.add(request.headers.get("user-agent", ""))
        if url == "https://data.example.com/robots.txt":
            return httpx.Response(200, text=self.robots)
        return self.pages.get(url, httpx.Response(599, text="not recorded"))

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(self.handler),
                                 headers={"User-Agent": "RoleBand-test/1"})


async def seed_plugin_companies(db) -> None:
    """The two companies the template plugin reads: Acme and Globex."""
    for slug, name in (("acme", "Acme Corp"), ("globex", "Globex")):
        db.add(CompanyProfile(slug=slug, display_name=name))
        db.add(TrackedCompany(slug=slug, display=name, adapter="greenhouse", status="active", enabled=True,
                              visible=True, source="builtin"))
    await db.commit()


async def plugin_levels(db, provider="plugin-template"):
    """The pay levels `provider` published, by label."""
    rows = (await db.execute(select(CompanyCompLevel).where(CompanyCompLevel.provider == provider)
                             .order_by(CompanyCompLevel.level_label))).scalars().all()
    return rows
