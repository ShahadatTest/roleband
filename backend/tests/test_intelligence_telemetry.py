"""ai_task_log redaction contract (no raw prompt/output ever reaches the row)."""

from __future__ import annotations

import asyncio

from tracker.db.models import AiTaskLog
from tracker.intelligence_runtime.telemetry import log_ai_task


class _AddOnlySession:
    def __init__(self):
        self.added = []

    def add(self, obj):
        self.added.append(obj)


def test_log_row_fields_and_redacted_meta():
    session = _AddOnlySession()
    row = asyncio.run(
        log_ai_task(
            session,
            task_type="disclosed_comp",
            provider="apple_fm",
            availability_state="available",
            validation_result="ok",
            latency_ms=1234,
            input_tokens=800,
            prompt_version="disclosed_comp/v1",
            model_id="apple-fm-on-device",
            job_id=1,
            meta={
                "disclosed": True,
                "truncated": False,
                "input_scope": "pay_section",
                # These must be dropped — they are not on the allowlist.
                "prompt_text": "SECRET PROMPT",
                "raw_output": "SECRET OUTPUT",
            },
        )
    )
    assert isinstance(row, AiTaskLog)
    assert session.added == [row]
    assert row.task_type == "disclosed_comp"
    assert row.validation_result == "ok"
    assert row.job_id == 1
    # Redaction: only allowlisted keys survive; no raw text.
    assert set(row.meta) == {"disclosed", "truncated", "input_scope"}
    assert row.meta["input_scope"] == "pay_section"
    assert "prompt_text" not in row.meta
    assert "raw_output" not in row.meta
