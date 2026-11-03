"""Preview and validate a recipe document against the live site.

Both run the recipe exactly as a scheduled run does: the same compiler, the
same `RecipeAdapter` transport (pinned public addresses, every redirect hop
checked against the recipe's declared hosts), the same pacing, and the same
`runtime_problems` test, so a recipe the scheduled run refuses never
previews, validates or shadows. A document is compiled against the contract
(`compile_recipe` without `stored`), so a stored revision outside it fails
here with a named problem. The difference is only what they are allowed to
conclude:

* **preview** reads at most `PREVIEW_PAGES` pages and `PREVIEW_ITEMS` postings
  and writes nothing. It answers "does this recipe extract anything sensible?".
* **validate** reads the whole listing within `VALIDATE_SECONDS` and passes only
  when the listing ended on its own (never a page or time bound), found at
  least one posting, and robots.txt allows the start URL for our user agent.
  Its evidence is what `recipe_store.record_validation` stamps; `validated_at`
  on a revision is the single fact that lets a recipe binding earn closure.

Recipe text is untrusted input. A robots-disallowed start URL is refused here:
consent-gated collection is a register decision per source, and a
recipe carries no register row.
"""

from __future__ import annotations

import hashlib
import time
import urllib.robotparser
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from urllib.parse import urlsplit

import httpx

from tracker.config import get_settings
from tracker.connectors import build_adapter
from tracker.connectors.recipes import (
    ExecutablePlan,
    RecipeError,
    compile_recipe,
    run_plan,
    runtime_problems,
)
from tracker.platform.clock import SourceClock
from tracker.platform.ratelimit import RateLimiterPool
from tracker.platform.safe_fetch import BlockedDestination, fetch_public, public_client

__all__ = ["PREVIEW_ITEMS", "PREVIEW_PAGES", "RecipeCheck", "preview_document", "validate_document"]

PREVIEW_PAGES = 2
PREVIEW_ITEMS = 5
VALIDATE_SECONDS = 240.0
_PREVIEW_SECONDS = 45.0


@dataclass
class RecipeCheck:
    """What one preview or validation established."""

    problems: list[str] = field(default_factory=list)
    jobs: list[dict] = field(default_factory=list)
    found: int = 0
    pages: int = 0
    list_complete: bool = False
    errors: list[str] = field(default_factory=list)
    robots: dict = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return (
            not self.problems and not self.errors and self.list_complete and self.found > 0
            and self.robots.get("allowed") is True
        )

    def evidence(self) -> dict:
        now = datetime.now(UTC).isoformat(timespec="seconds")
        out = {
            "passed": self.passed, "checked_at": now, "found": self.found, "pages": self.pages,
            "list_complete": self.list_complete, "errors": self.errors[:10], "robots": self.robots,
        }
        if self.passed:
            out["validated_at"] = now
        return out


async def _robots(plan: ExecutablePlan) -> dict:
    """robots.txt verdict for the start URL, fetched on a pinned public client."""
    parts = urlsplit(plan.start_url)
    robots_url = f"{parts.scheme}://{parts.netloc}/robots.txt"
    agent = get_settings().scraper_user_agent
    async with public_client(user_agent=agent) as client:
        try:
            page = await fetch_public(client, robots_url)
        except (BlockedDestination, httpx.HTTPError, OSError, ValueError) as exc:
            return {"url": robots_url, "allowed": None, "detail": f"unread: {type(exc).__name__}"}
    if page.status in (401, 403) or page.status >= 500:
        # The same reading `RecipeAdapter.robots_allows` applies on every run.
        return {"url": robots_url, "allowed": False, "status": page.status,
                "detail": "robots.txt refused or failed: treated as disallowed"}
    if page.status >= 400:
        # No file served: nothing restricts the route.
        return {"url": robots_url, "allowed": True, "status": page.status, "detail": "no robots.txt"}
    parser = urllib.robotparser.RobotFileParser()
    parser.parse(page.text.splitlines())
    return {
        "url": robots_url, "status": page.status,
        "sha256": hashlib.sha256(page.text.encode()).hexdigest(),
        "allowed": parser.can_fetch(agent, plan.start_url),
    }


async def _run(
    plan: ExecutablePlan, *, seconds: float, max_items: int | None,
    sample_items: int | None = PREVIEW_ITEMS,
) -> RecipeCheck:
    refused = runtime_problems(plan)
    if refused:
        return RecipeCheck(problems=refused)
    check = RecipeCheck()
    adapter = build_adapter(
        "recipe-preview", "recipe", recipe_plan=plan, limiter_pool=RateLimiterPool(),
        deadline=SourceClock(stall_seconds=seconds, hard_deadline=time.monotonic() + seconds),
    )
    try:
        async with adapter:
            result = await run_plan(plan, adapter.context, "recipe-preview",
                                    max_items=max_items, access=adapter.access)
    except Exception as exc:  # noqa: BLE001 - any failure is a diagnostic, never a crash
        check.errors.append(f"{type(exc).__name__}: {exc}"[:300])
        return check
    check.found = len(result.jobs)
    check.pages = int(result.diagnostics.get("pages", 0))
    check.list_complete = result.list_complete
    check.errors.extend(str(e) for e in result.diagnostics.get("errors", []))
    check.jobs = [
        {
            "req_id": job.req_id, "title": job.title, "url": job.url,
            "locations": list(job.locations),
            "posted_at": job.posted_at.isoformat() if job.posted_at else None,
        }
        for job in result.jobs[:sample_items]
    ]
    return check


def _compile(document: dict) -> tuple[ExecutablePlan | None, list[str]]:
    try:
        return compile_recipe(document), []
    except RecipeError as exc:
        return None, list(exc.problems)


async def preview_document(document: dict) -> RecipeCheck:
    """Bounded, write-free: at most two pages and five postings."""
    plan, problems = _compile(document)
    if plan is None:
        return RecipeCheck(problems=problems)
    robots = await _robots(plan)
    if robots.get("allowed") is not True:
        return RecipeCheck(robots=robots, errors=["robots.txt does not allow the start URL for our user agent"])
    pagination = dict(plan.pagination) if plan.pagination else None
    if pagination:
        pagination["max_pages"] = min(int(pagination.get("max_pages", 1)), PREVIEW_PAGES)
    check = await _run(replace(plan, pagination=pagination), seconds=_PREVIEW_SECONDS,
                       max_items=PREVIEW_ITEMS)
    check.robots = robots
    # A preview is capped by design; its completeness means nothing.
    check.list_complete = False
    return check


async def validate_document(document: dict) -> RecipeCheck:
    """The whole listing, to its own end, within `VALIDATE_SECONDS`."""
    plan, problems = _compile(document)
    if plan is None:
        return RecipeCheck(problems=problems)
    check = RecipeCheck(robots=await _robots(plan))
    if check.robots.get("allowed") is not True:
        check.errors.append("robots.txt does not allow the start URL for our user agent")
        return check
    ran = await _run(plan, seconds=VALIDATE_SECONDS, max_items=None)
    ran.robots = check.robots
    return ran


async def shadow_document(document: dict) -> RecipeCheck:
    """Read the complete proposed listing without persisting any posting."""
    plan, problems = _compile(document)
    if plan is None:
        return RecipeCheck(problems=problems)
    robots = await _robots(plan)
    if robots.get("allowed") is not True:
        return RecipeCheck(robots=robots, errors=["robots.txt does not allow the start URL"])
    check = await _run(plan, seconds=VALIDATE_SECONDS, max_items=None, sample_items=None)
    check.robots = robots
    return check
