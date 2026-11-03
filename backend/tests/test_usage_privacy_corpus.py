"""The whole backend send, over a realistic database, carries none of the user's data.

The main guard of usage sharing (docs/architecture.md). A synthetic
corpus (the same one `scripts.seed_synthetic` gives a fresh install) plus canary
data where data really flows: a company the user added, on its own careers
site; the user's actions through the real API routes, which carry job ids and
company slugs in their URLs; crashes whose messages and paths name the company
and the home directory; a failing run of that company. Everything is shared,
one day passes, and the batch the flush posts is read back:

* no canary, no seeded job title or company name, no home directory, user name,
  host name or git branch appears anywhere in it;
* every string in it is a value the catalogue allows for its key (or one of the
  four structural strings: install ID, event uuid, timestamp, project key).

This is the test that fails when someone adds `str(exc)`, a slug or a title to
any event, wherever in the backend they add it.
"""

from __future__ import annotations

import getpass
import json
import re
import socket
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from scripts.seed_synthetic import seed
from tests.usage_fixtures import share
from tracker.db.models import (
    AiTaskLog,
    Job,
    ScrapeRun,
    ScrapeSourceRun,
    SourceBinding,
    TrackedCompany,
)
from tracker.platform.power import Power
from tracker.usage_stats import registry, rollup, scrub
from tracker.usage_stats.consent import get_sharing
from tracker.usage_stats.flush import flush_if_due
from tracker.usage_stats.registry import CATALOGUE, Group
from tracker.usage_stats.tally import TALLY, drain
from tracker.workflows import run_persistence
from tracker.workflows.collection_types import ScanMode

pytestmark = [pytest.mark.asyncio, pytest.mark.usefixtures("no_escape")]

CANARY_SLUG = "zyxwv-robotics"
CANARY_NAME = "Zyxwv Robotics"
CANARY_CITY = "Qwertyville"
CANARY_TITLE = "Principal Zyxwv Platform Manager"
CANARIES = (CANARY_SLUG, CANARY_NAME, CANARY_CITY, CANARY_TITLE, "zyxwv", "Zyxwv", "Qwerty")


def _scope(db_session):
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False, class_=AsyncSession)

    @asynccontextmanager
    async def scope():
        async with factory() as session:
            yield session

    return scope


def _branch() -> str | None:
    """This checkout's branch, read from `.git/HEAD` (no `git` subprocess under
    `no_escape`); a worktree's `.git` is a file naming its git directory."""
    root = Path(__file__).resolve().parents[2]
    dot_git = root / ".git"
    try:
        git_dir = dot_git if dot_git.is_dir() else Path(dot_git.read_text().split("gitdir:", 1)[1].strip())
        head = (git_dir / "HEAD").read_text().strip()
    except (OSError, IndexError):
        return None
    return head.removeprefix("ref: refs/heads/") if head.startswith("ref: ") else None


def _string_leaves(value, key: str = "") -> list[tuple[str, str]]:
    if isinstance(value, str):
        return [(key, value)]
    if isinstance(value, dict):
        return [leaf for k, v in value.items() for leaf in _string_leaves(v, k)]
    if isinstance(value, list):
        return [leaf for item in value for leaf in _string_leaves(item, key)]
    return []


def _allowed(key: str, value: str) -> bool:
    """Is `value` a string the catalogue (or the batch's structure) allows under `key`?"""
    if key in ("distinct_id", "uuid"):
        return re.fullmatch(r"[0-9a-f-]{36}", value) is not None
    if key in ("timestamp",):
        return datetime.fromisoformat(value) is not None
    if key == "day":
        return re.fullmatch(r"\d{4}-\d{2}-\d{2}", value) is not None
    if key == "api_key":
        return value.startswith("phc_")
    if key == "event":
        return value in CATALOGUE
    if key in ("$lib",):
        return value == "roleband-backend"
    if key in ("$exception_fingerprint",):
        return re.fullmatch(r"[0-9a-f]{32}", value) is not None
    if key in ("type",):
        return re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.]*", value) is not None or value == "raw"
    if key in ("platform", "lang"):
        return value in ("custom", "python")
    if key == "module":
        return re.fullmatch(r"tracker(\.[a-z_][a-z0-9_]*)*", value) is not None
    if key == "filename":
        return re.fullmatch(r"tracker(/[a-z_][a-z0-9_]*)*\.py", value) is not None
    if key == "function":
        return re.fullmatch(r"[A-Za-z0-9_<>.]+", value) is not None
    for spec in CATALOGUE.values():
        prop = spec.props.get(key)
        if prop is not None and prop.accepts(value):
            return True
    return False


async def _company_on_its_own_site(db_session, *, now: datetime) -> None:
    db_session.add(TrackedCompany(slug=CANARY_SLUG, display=CANARY_NAME, adapter="zyxwv-careers",
                                  status="active", enabled=True, visible=True, source="user"))
    await db_session.flush()
    binding = SourceBinding(company_slug=CANARY_SLUG, connector_kind="zyxwv-careers", connector_id=CANARY_SLUG)
    run = ScrapeRun(status="error", notes=f"pipeline exception: {CANARY_NAME} board in {CANARY_CITY} broke")
    db_session.add_all([binding, run])
    await db_session.flush()
    db_session.add(ScrapeSourceRun(
        run_id=run.id, binding_id=binding.id, company_slug=CANARY_SLUG, provider_key="zyxwv-careers",
        scan_mode="reconcile", outcome="failed", started_at=now, finished_at=now,
        errors=[f"{CANARY_TITLE} page 404"],
    ))


async def test_a_full_day_sends_none_of_the_users_data(db_session, api_client, sharing_allowed, monkeypatch) -> None:
    now = datetime.now(UTC)
    shared_at = now - timedelta(days=2)
    await seed(db_session, 24, seed_value=11, derived=False)
    await share(db_session, *Group, now=shared_at)
    await _company_on_its_own_site(db_session, now=now - timedelta(hours=20))
    # AI calls: a cloud vendor's model, and a local model the user named after the company.
    db_session.add_all([
        AiTaskLog(task_type="disclosed_comp", provider="cloud_openai", availability_state="available",
                  validation_result="ok", model_id="gpt-4o-mini", latency_ms=320,
                  input_tokens=900, output_tokens=40, created_at=now - timedelta(hours=20)),
        AiTaskLog(task_type="relevance_review", provider="ollama", availability_state="available",
                  validation_result="invalid", failure_class="validation", model_id=f"{CANARY_SLUG}-tuned",
                  latency_ms=1200, created_at=now - timedelta(hours=20)),
    ])
    await db_session.commit()

    # The user's day, through the real routes (URLs carry ids and slugs).
    monkeypatch.setattr(TALLY, "usage", True)
    monkeypatch.setattr(TALLY, "crashes", True)
    TALLY.take()
    job_ids = list((await db_session.execute(select(Job.id).limit(3))).scalars())
    for job_id in job_ids:
        assert (await api_client.put(f"/api/jobs/{job_id}/favorite")).status_code == 200
        await api_client.post(f"/api/jobs/{job_id}/view")
    await api_client.put("/api/compare-selection", json={"ids": job_ids[:2]})
    await api_client.put("/api/settings/locale", json={"language": "en", "region": None})
    assert sum(TALLY.actions.values()) >= 4

    # Crashes where data really is: the API, and a run of the user's company.
    try:
        raise LookupError(f"{CANARY_NAME} ({CANARY_SLUG}) has no board at {Path.home()}/{CANARY_CITY}")
    except LookupError as exc:
        TALLY.crash(scrub.scrub(exc))
    await drain(db_session, TALLY, now=now - timedelta(hours=1))
    # Today's heartbeat, which tomorrow's send carries.
    await rollup.heartbeat(db_session, sharing=await get_sharing(db_session), now=now - timedelta(hours=1))
    await db_session.commit()

    run = ScrapeRun(status="running")
    db_session.add(run)
    await db_session.commit()
    await run_persistence.record_run_failure(
        db_session, run.id, RuntimeError(f"{CANARY_TITLE} in {CANARY_CITY} for {getpass.getuser()}"),
        per_source={CANARY_SLUG: {"error": CANARY_NAME}}, drift_all=[],
        totals={"seen": 0, "new": 0, "closed": 0}, scan_mode=ScanMode.RECONCILE,
    )

    posted: list[bytes] = []

    def posthog(request: httpx.Request) -> httpx.Response:
        posted.append(request.content)
        return httpx.Response(200, json={"status": "Ok"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(posthog)) as client:
        result = await flush_if_due(
            scope=_scope(db_session), power=lambda: Power(dark_wake=False, on_battery=False),
            client=client, now=now + timedelta(days=1),
        )
    assert result["outcome"] == "sent", result
    [raw] = posted
    text = raw.decode()
    body = json.loads(text)
    events = {event["event"] for event in body["batch"]}
    assert {"daily_action", "daily_heartbeat", "daily_scan_health", "daily_ai_task", "$exception", "first_job_saved"} <= events

    forbidden = list(CANARIES)
    forbidden += [str(Path.home()), getpass.getuser(), socket.gethostname()]
    branch = _branch()
    if branch:
        forbidden.append(branch)
    titles = (await db_session.execute(select(Job.title))).scalars().all()
    names = (await db_session.execute(select(TrackedCompany.display))).scalars().all()
    forbidden += [value for value in [*titles, *names] if value and " " in value]
    for value in forbidden:
        assert value not in text, f"{value!r} left the machine"

    strays = [(key, value) for key, value in _string_leaves(body) if not _allowed(key, value)]
    assert strays == []
    assert registry.SINGLE_COMPANY in text  # the user's own careers site, reported as no one
