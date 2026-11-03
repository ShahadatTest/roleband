"""Materialize user-facing notifications from lifecycle events and run health.

`events` classifies a tracked role's lifecycle, `run_result` a scan's start and
end, and the digest, pursuit and coverage classifiers sit beside their
generators (`digest`, `pursuit_due`, `coverage`). `render` formats, `store`
persists/queries, `channels` names the delivery seam. This module re-exports the
public surface, so callers import from `tracker.notifications`.
"""

from __future__ import annotations

from tracker.notifications.channels import CHANNELS
from tracker.notifications.coverage import classify_coverage, generate_coverage_notifications
from tracker.notifications.digest import (
    DigestMatch,
    classify_daily_digest,
    collect_digest_matches,
    fit_label,
    generate_daily_digest,
)
from tracker.notifications.events import ClassifiedNotif, JobLike, classify_event
from tracker.notifications.pursuit_due import (
    classify_pursuit_due,
    classify_pursuit_quiet,
    generate_pursuit_due_notifications,
    overdue_pursuit_clause,
)
from tracker.notifications.run_result import (
    classify_sync_result,
    classify_sync_started,
    run_diagnostics,
)
from tracker.notifications.store import (
    generate_notifications,
    generate_sync_result_notification,
    generate_sync_started_notification,
    update_sync_progress,
)
from tracker.notifications.tracked import tracked_job_ids

__all__ = [
    "CHANNELS",
    "ClassifiedNotif",
    "DigestMatch",
    "JobLike",
    "classify_coverage",
    "classify_daily_digest",
    "classify_event",
    "classify_pursuit_due",
    "classify_pursuit_quiet",
    "classify_sync_result",
    "classify_sync_started",
    "collect_digest_matches",
    "fit_label",
    "generate_coverage_notifications",
    "generate_daily_digest",
    "generate_notifications",
    "generate_pursuit_due_notifications",
    "overdue_pursuit_clause",
    "generate_sync_result_notification",
    "generate_sync_started_notification",
    "run_diagnostics",
    "tracked_job_ids",
    "update_sync_progress",
]
