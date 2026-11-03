"""Realistic rows for the notification contract.

Every timestamp is fixed, so two runs of the same request return the same bytes.
`meta` is copied from the shapes the real writers build (`notifications/events.py`,
`notifications/digest.py`, `notifications/pursuit_due.py`); the route returns it
as stored, whatever its category.

| row | what it exercises |
|---|---|
| `failed` | high `sync_failed` from a run, unread, run meta with diagnostics |
| `warning` | normal `sync_warning` from a run, read, same `created_at` as `failed`: priority breaks the tie |
| `closed` | high `closed` lifecycle event on an acme role: the linked job's company is resolved |
| `changed` | low `changed` event on a globex role, read, same `created_at` as `closed`; its body holds a literal `%` |
| `digest` | normal `daily_digest`: no job, no run |
| `pursuit` | high `pursuit_due` on an acme role, with no next action and no due date |
| `legacy` | normal `new_match`, a category no writer produces: no body, empty meta |
| `dismissed` | high `saved_update`, dismissed: never listed, and restorable |

A real table can hold only run and digest notifications, none linked to a
job, so the job-linked branches are seeded here.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from tracker.db.models import Job, Notification, ScrapeRun, TrackedCompany

T0 = datetime(2026, 7, 1, 12, 0, tzinfo=UTC)


@dataclass(frozen=True)
class SeededNotifications:
    failed: int
    warning: int
    closed: int
    changed: int
    digest: int
    pursuit: int
    legacy: int
    dismissed: int


def _company(slug: str, display: str) -> TrackedCompany:
    return TrackedCompany(
        slug=slug, display=display, adapter="greenhouse", board_token=slug,
        careers_url=f"https://careers.example.test/{slug}", status="active", enabled=True,
        visible=True, source="catalog", role_catalog_status="ready",
        role_catalog_scanned_at=T0, role_catalog_error=None, created_at=T0,
    )


def _job(company: str, key: str, title: str) -> Job:
    return Job(
        company=company, req_id=key, dedupe_key=f"{company}:{key}", title=title,
        url=f"https://careers.example.test/{company}/{key}", locations=["London, UK"],
        location_groups=["uk"], domains=["ai_ml"], workplace_type="onsite", level_band="staff",
        level_confidence="confirmed", family="software_engineering", track="technical",
        comp_currency="USD", status="open", in_scope=True, first_seen=T0, last_seen=T0,
        description_sections=[],
    )


def _run_meta(state: str, *, started: datetime, finished: datetime, errors: bool) -> dict:
    """The sync result meta `events.classify_run` builds, with its diagnostics."""
    source_errors = {"globex": ["HTTPError: 503 on page 2"]} if errors else {}
    return {
        "sync_state": state,
        "started_at": started.isoformat(),
        "finished_at": finished.isoformat(),
        "duration_seconds": 1834.52,
        "jobs_found": 1204,
        "jobs_created": 12,
        "jobs_updated": 30,
        "jobs_skipped_or_unchanged": 1162,
        "jobs_closed": 4,
        "error_sources": sorted(source_errors),
        "source_errors": source_errors,
        "suspended_sources": {},
        "drift_alerts": [{"source": "acme", "message": "listing shrank by 40%", "context": {"before": 50, "after": 30}}],
        "diagnostics": {
            "run_id": None,
            "run_status": "partial" if state == "warning" else "error",
            "started_at": started.isoformat(),
            "finished_at": finished.isoformat(),
            "duration_seconds": 1834.52,
            "totals": {"jobs_seen": 1204, "jobs_new": 12, "jobs_closed": 4, "sources_ok": 1, "sources_total": 2},
            "sources": [
                {"source": "acme", "outcome": "list_complete", "errors": 0, "drift_count": 1,
                 "duration_seconds": 12.4, "scanned": 50, "kept": 30, "new": 2, "closed": 1},
            ],
            "drift": [{"source": "acme", "message": "listing shrank by 40%", "context": {}}],
            "errors": [{"source": "globex", "error": "HTTPError: 503 on page 2"}] if errors else [],
            "notes": None,
        },
    }


def _notification(**row) -> Notification:
    row.setdefault("read_at", None)
    row.setdefault("dismissed_at", None)
    return Notification(**row)


async def seed_notification_contract(session: AsyncSession) -> SeededNotifications:
    session.add_all([_company("acme", "Acme"), _company("globex", "Globex")])
    acme_saved = _job("acme", "role-1", "Staff Software Engineer, Platform")
    acme_pursued = _job("acme", "role-2", "Principal Engineer, Infrastructure")
    globex_saved = _job("globex", "role-3", "Staff Engineer (100% remote)")
    partial = ScrapeRun(started_at=T0, finished_at=T0 + timedelta(minutes=30), status="partial")
    errored = ScrapeRun(started_at=T0, finished_at=T0 + timedelta(minutes=31), status="error")
    session.add_all([acme_saved, acme_pursued, globex_saved, partial, errored])
    await session.flush()

    rows = {
        "failed": _notification(
            created_at=T0 + timedelta(hours=3), priority="high", category="sync_failed",
            title="Sync failed", body="No source produced usable data", job_id=None, run_id=errored.id,
            source_type="run", source_id=errored.id,
            meta=_run_meta("failed", started=T0, finished=T0 + timedelta(minutes=31), errors=True),
        ),
        "warning": _notification(
            created_at=T0 + timedelta(hours=3), priority="normal", category="sync_warning",
            title="Sync finished with warnings", body="1204 found / 12 created / 30 updated",
            job_id=None, run_id=partial.id, source_type="run", source_id=partial.id,
            read_at=T0 + timedelta(hours=4),
            meta=_run_meta("warning", started=T0, finished=T0 + timedelta(minutes=30), errors=False),
        ),
        "closed": _notification(
            created_at=T0 + timedelta(hours=2), priority="high", category="closed",
            title="Acme closed a role you saved", body=acme_saved.title, job_id=acme_saved.id,
            run_id=partial.id, source_type="event", source_id=901,
            meta={"company": "acme", "tracked": True, "lineage_role": None},
        ),
        "changed": _notification(
            created_at=T0 + timedelta(hours=2), priority="low", category="changed",
            title="Globex changed a role you saved", body=globex_saved.title, job_id=globex_saved.id,
            run_id=partial.id, source_type="event", source_id=902, read_at=T0 + timedelta(hours=5),
            meta={"company": "globex", "tracked": True, "lineage_role": "repost", "fields": ["locations", "title"]},
        ),
        "digest": _notification(
            created_at=T0 + timedelta(hours=1), priority="normal", category="daily_digest",
            title="2 new roles for you today", body="Acme, Globex", job_id=None, run_id=None,
            source_type="digest", source_id=T0.date().toordinal(), read_at=T0 + timedelta(hours=6),
            meta={
                "day": "2026-07-01", "count": 2, "companies": ["acme", "globex"], "ranked": True,
                "top": [
                    {"job_id": acme_saved.id, "company": "acme", "title": acme_saved.title, "fit": 0.8123, "fit_band": "strong"},
                    {"job_id": globex_saved.id, "company": "globex", "title": globex_saved.title, "fit": None, "fit_band": None},
                ],
            },
        ),
        "pursuit": _notification(
            created_at=T0 + timedelta(hours=1), priority="high", category="pursuit_due",
            title="Follow up with Acme · 2d overdue", body="No next action set - Principal Engineer, Infrastructure (interviewing)",
            job_id=acme_pursued.id, run_id=None, source_type="pursuit", source_id=77,
            meta={"company": "acme", "stage": "interviewing", "days_overdue": 2, "next_action": None, "due_at": None},
        ),
        "legacy": _notification(
            created_at=T0, priority="normal", category="new_match", title="New match at Acme",
            body=None, job_id=acme_saved.id, run_id=None, source_type="event", source_id=903, meta={},
        ),
        "dismissed": _notification(
            created_at=T0 + timedelta(minutes=30), priority="high", category="saved_update",
            title="Acme listed a role you saved", body=acme_pursued.title, job_id=acme_pursued.id,
            run_id=None, source_type="event", source_id=904, dismissed_at=T0 + timedelta(minutes=45),
            meta={"company": "acme", "tracked": True, "lineage_role": None},
        ),
    }
    # One flush per row, so ids follow the table above.
    for row in rows.values():
        session.add(row)
        await session.flush()
    await session.commit()
    return SeededNotifications(**{name: row.id for name, row in rows.items()})


async def seed_unread_backlog(session: AsyncSession, count: int) -> None:
    """`count` unread sync warnings, for a clear too large to undo."""
    session.add_all([
        _notification(
            created_at=T0 - timedelta(minutes=i + 1), priority="normal", category="sync_warning",
            title=f"Sync finished with warnings #{i}", body=None, job_id=None, run_id=None,
            source_type="run", source_id=10_000 + i, meta={},
        )
        for i in range(count)
    ])
    await session.commit()
