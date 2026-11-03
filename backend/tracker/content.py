"""Generic source-content fingerprint.

`jobs.content_hash` + `jobs.content_changed_at` are the pipeline-owned "the stored
posting text changed" signal. A small standalone step owns them, so the downstream
enrichments that gate on a content change — embeddings (`embed.py`) and the
disclosed-comp pass (`intelligence/extract.py`) — depend on no keyword system.
`content_changed_at` bumps only when `md5(title || description_text)` moves.
"""

from __future__ import annotations

import hashlib
import logging

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from tracker.db.models import Job

logger = logging.getLogger(__name__)


def content_fingerprint(title: str | None, description_text: str | None) -> str:
    """Stable hash of the text the content-gated enrichments depend on."""
    payload = f"{title or ''}\n{description_text or ''}"
    return hashlib.md5(payload.encode("utf-8")).hexdigest()


async def fingerprint_content(session: AsyncSession, job_ids: list[int]) -> int:
    """Refresh `content_hash`/`content_changed_at` for changed jobs. Returns count bumped.

    Idempotent: a job whose title/description_text is unchanged since the last run is
    skipped, so `content_changed_at` stays put and the embedding/disclosed-comp
    staleness gates do not re-fire.
    """
    if not job_ids:
        return 0
    jobs = (await session.scalars(select(Job).where(Job.id.in_(job_ids)))).all()
    bumped = 0
    for job in jobs:
        new_hash = content_fingerprint(job.title, job.description_text)
        if job.content_hash == new_hash:
            continue
        job.content_hash = new_hash
        job.content_changed_at = func.now()
        bumped += 1
    if bumped:
        logger.info("content fingerprint: %d/%d jobs changed", bumped, len(jobs))
    return bumped
