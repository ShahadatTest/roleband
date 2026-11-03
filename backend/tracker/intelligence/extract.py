"""What the disclosed-comp pass IS: its task name, its extractor identity, and
the pure gating predicate.

The pass itself — the query, the per-job commit, the telemetry write — needs the
store, so it lives in `tracker/intelligence_runtime/disclosed_comp.py`.
This module is what a reader that only wants to know *which* task a log row
belongs to, or *whether* a job is stale, can import without loading the database
layer: `api/routers/statistics.py` and `scripts/report_equity_residuals.py` both
take only `TASK`.
"""

from __future__ import annotations

TASK = "disclosed_comp"

# Recorded in `ai_task_log.provider`, which is how the Settings telemetry tells
# runs apart. A distinct name (not "apple_fm", not "null") is what keeps the
# historical model rows comparable instead of silently merged into this pass.
EXTRACTOR = "deterministic"
EXTRACTOR_ID = "built-in-band-scanner"


def is_stale(
    structured_at,
    content_changed_at,
    structured_version: str | None,
    active_version: str,
    disclosed_source: str | None = None,
) -> bool:
    """Pure mirror of `stale_clause` for unit testing the gating decision. A
    band a connector wrote is never the text pass's to re-read."""
    if disclosed_source == "connector":
        return False
    if structured_at is None:
        return True
    if content_changed_at is not None and content_changed_at > structured_at:
        return True
    return structured_version != active_version
