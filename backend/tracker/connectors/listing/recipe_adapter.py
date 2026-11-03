"""Generic recipe listing connector.

Makes a stored recipe *run* in the real pipeline. It is a `BaseAdapter`, so it
plugs into the scrape lifecycle (async context manager, shared pacer, drift
detector, `hydrate`), but its `fetch()` delegates to the deterministic recipe
runner over the SDK context. One class runs every recipe-bound company; adding
a company is data, not code.

Closure safety carries through: when the runner reports the listing incomplete
(bound hit, non-200, malformed payload, cross-host block), this marks the
shared drift detector's listing incomplete, so the pipeline's
`should_close_missing` gate and the binding scope on top of it suppress
closure exactly as they do for a hand-written adapter.
"""

from __future__ import annotations

import urllib.robotparser
from collections.abc import AsyncIterator
from typing import Any
from urllib.parse import urlsplit

from tracker.config import get_settings
from tracker.connectors.listing.base import BaseAdapter
from tracker.connectors.recipes import ExecutablePlan, RecipeRunResult, run_plan, runtime_problems
from tracker.connectors.sdk import FetchRequest
from tracker.platform.safe_fetch import BlockedDestination
from tracker.schema import RawJob
from tracker.source_policy import CollectionAccess, CollectionPolicyDenied

__all__ = ["RecipeAdapter"]


class RecipeAdapter(BaseAdapter):
    """Runs one compiled recipe. Instantiated per company from its binding."""

    name = "recipe"
    #: Recipe text is untrusted input: every request, redirect hop
    #: included, goes to a pinned public address on a host the recipe declared,
    #: in production exactly as in preview.
    public_only = True

    def __init__(self, company_slug: str, plan: ExecutablePlan, **kwargs: Any) -> None:
        # `plan` is this adapter's only extra argument; every injected bound
        # (limiter/breaker/deadline) forwards verbatim to the base.
        self.plan = plan
        # One pacer per recipe host, never one for every recipe: two
        # recipes are two sites. A recipe may ask to go SLOWER than the global
        # pacing (`delay_ms`), never faster.
        self.rate_limit_scope = f"recipe:{plan.domains[0]}"
        self.min_delay = max(get_settings().scraper_min_delay_seconds, plan.delay_ms / 1000)
        super().__init__(company_slug, **kwargs)
        #: The last run's result, for a caller that inspects it after fetch().
        self.last_result: RecipeRunResult | None = None

    def validate_destination(self, url: str) -> None:
        if not self.plan.host_allowed(url):
            raise BlockedDestination("URL is outside the recipe's declared hosts")

    async def robots_allows(self) -> bool:
        """Does the site's robots.txt allow the recipe's start URL for us?

        Checked on EVERY run, not only when a recipe is validated:
        robots is the site's standing request and can change after a recipe
        was bound. A recipe carries no register row, so it has no consent path:
        a disallow is a refusal. 401/403 and a server error read as
        disallowed; a missing file (404) restricts nothing."""
        parts = urlsplit(self.plan.start_url)
        try:
            resp = await self.context.fetch(FetchRequest(
                url=f"{parts.scheme}://{parts.netloc}/robots.txt", source_key=self.company,
            ))
        except BlockedDestination:
            return False
        if resp.status in (401, 403) or resp.status >= 500:
            return False
        if resp.status != 200:
            return True
        parser = urllib.robotparser.RobotFileParser()
        parser.parse(resp.text().splitlines())
        return parser.can_fetch(self.settings.scraper_user_agent, self.plan.start_url)

    async def fetch(self) -> AsyncIterator[RawJob]:
        self.access.require()
        if runtime_problems(self.plan):
            # A stored revision may name a reserved transport (static_impersonate
            # needs the curl transport, render a rendering service); the base
            # context provides neither. Refused before any request, by the same
            # test preview and validation apply, rather than scraped over the
            # wrong transport.
            self.drift.invalidate_listing(
                "recipe transport not available in pipeline",
                mode=self.plan.transport_mode,
            )
            return
        if not await self.robots_allows():
            raise CollectionPolicyDenied(CollectionAccess(
                self.name,
                f"robots.txt on {urlsplit(self.plan.start_url).hostname} does not allow"
                " the recipe's start URL; a recipe has no consent path",
                walled=True,
            ))

        result = await run_plan(self.plan, self.context, self.company, access=self.access)
        self.last_result = result

        if not result.list_complete:
            # Same effect as a hand-written adapter's drift: closure suppressed.
            self.drift.invalidate_listing(
                "recipe listing incomplete", **_summary(result.diagnostics)
            )
        for err in result.diagnostics.get("errors", []):
            self.drift.note("recipe error", detail=err)
        if result.list_complete and not result.jobs and result.diagnostics.get("structural_empty"):
            # The recipe's own empty-state sentinel matched: the page says it
            # lists nothing. Without the sentinel a zero is unexplained, and
            # the collector records it as such.
            self.drift.board_empty("the recipe's empty-state sentinel matched")

        for job in result.jobs:
            yield job


def _summary(diagnostics: dict) -> dict:
    """Drift-safe subset of run diagnostics (no payloads, no proxy values)."""
    return {
        key: diagnostics.get(key)
        for key in ("pages", "items", "dropped")
        if key in diagnostics
    }
