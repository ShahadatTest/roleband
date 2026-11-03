"""Re-read open postings whose stored text an older detail parser produced.

A connector fix changes only what the next detail fetch stores. Rows already
held keep the old parse until something fetches them again, and for some rows
nothing ordinary will: a walled company is scanned only when its user asks,
and a scan does not re-read a row inside `description_refresh_days`.

This fetches them directly, one detail call per row through the company's own
adapter, at the source's own pace (one shared pacer and breaker per host, as
the pipeline's description backfill uses; `open_adapters`). A row is selected when it is open, its company
collects through `--adapter`, and its text was fetched before
`--fetched-before`, the moment the parser fix landed. A saved row's fetch time
moves past that moment, so the selector is the cursor: a rerun after a kill
skips every row a committed batch saved. `--text-matches` narrows the
selection to rows whose stored text matches a PostgreSQL regular expression,
so a fix that touched only some postings re-reads only those.

    .venv/bin/python -m scripts.refetch_descriptions --adapter google --fetched-before <ISO time>
    .venv/bin/python -m scripts.refetch_descriptions --adapter google --fetched-before <ISO time> \
        --apply --backup old-descriptions.jsonl
    .venv/bin/python -m scripts.refetch_descriptions --adapter google --fetched-before <ISO time> \
        --text-matches '[.!?]Individual pay is determined'

Only the description fields are rewritten, then what the post-passes derive
from text for the rows they touch: the search vector, the content fingerprint
(which queues the embedding pass) and the requirements. `disclosed_*` follows
`backfill_severed_pay_sections`: a connector band stays, and any other row is
left for the text pass to re-read. A source that serves no text leaves its row
exactly as it was, still selected. Closed rows are never selected: the source
answers 404, and their text is the record of what was published.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
from collections import Counter
from contextlib import AsyncExitStack
from datetime import UTC, datetime

from sqlalchemy import select

from tracker.company_store import ScanTarget, get_active_targets
from tracker.connectors import (
    BaseAdapter,
    BreakerPool,
    RateLimiterPool,
    build_adapter,
    structure_job_detail,
)
from tracker.connectors.detail.base import sections_to_text
from tracker.content import fingerprint_content
from tracker.db.models import Job
from tracker.db.repo import refresh_search_vectors
from tracker.db.session import commit_in_batches, session_scope
from tracker.platform.util import html_to_text
from tracker.schema import RawJob
from tracker.skills.extract import extract_requirements
from tracker.source_policy import collection_access

log = logging.getLogger(__name__)

#: Small, because a batch's transaction stays open while its rows are fetched
#: at the source's pace.
BATCH = 25


def _pending(companies: list[str], before: datetime, text_matches: str | None = None):
    query = select(Job.id).where(
        Job.status == "open",
        Job.company.in_(companies),
        Job.description_fetched_at < before,
    )
    if text_matches:
        query = query.where(Job.description_text.regexp_match(text_matches))
    # Rows on the Board first: they are the ones the person reads.
    return query.order_by(Job.in_scope.is_(True).desc(), Job.id)


def collectable(targets: dict[str, ScanTarget]) -> tuple[dict[str, ScanTarget], list[str]]:
    """`targets` split into the companies policy lets us read and the denied
    ones (a walled company without the user's consent, among them)."""
    allowed: dict[str, ScanTarget] = {}
    denied: list[str] = []
    for slug, cfg in sorted(targets.items()):
        if collection_access(cfg["adapter"], company=slug, consent=cfg.get("consent")).denied:
            denied.append(slug)
        else:
            allowed[slug] = cfg
    return allowed, denied


async def _companies(session, adapter_key: str) -> tuple[dict[str, ScanTarget], list[str]]:
    """Followed companies on the adapter, split into collectable and denied."""
    targets = await get_active_targets(session)
    return collectable({slug: cfg for slug, cfg in targets.items() if cfg.get("adapter") == adapter_key})


async def open_adapters(stack: AsyncExitStack, targets: dict[str, ScanTarget]) -> dict[str, BaseAdapter]:
    """One entered adapter per company, all on one pacer and one breaker per
    host: a repair's detail reads go out at the source's pace, and a streak of
    refusals stops them, as in a scan. An adapter built per row would start
    unpaced every time and never see a streak."""
    limiter_pool, breaker_pool = RateLimiterPool(), BreakerPool()
    adapters = {}
    for slug, cfg in targets.items():
        adapter = build_adapter(
            slug,
            cfg["adapter"],
            cfg.get("board_token"),
            board_region=cfg.get("board_region"),
            limiter_pool=limiter_pool,
            breaker_pool=breaker_pool,
            # The adapter re-checks the policy on entry against this consent.
            consent=cfg.get("consent"),
        )
        adapters[slug] = await stack.enter_async_context(adapter)
    return adapters


def _snapshot(job: Job) -> dict:
    fetched = job.description_fetched_at
    return {
        "id": job.id,
        "description_html": job.description_html,
        "description_sections": job.description_sections,
        "description_text": job.description_text,
        "description_fetched_at": fetched.isoformat() if fetched else None,
        "structured_at": job.structured_at.isoformat() if job.structured_at else None,
    }


async def run(
    *,
    adapter_key: str,
    before: datetime,
    apply: bool,
    limit: int | None = None,
    backup: str | None = None,
    text_matches: str | None = None,
    batch: int = BATCH,
) -> dict:
    async with session_scope() as session:
        targets, denied = await _companies(session, adapter_key)
        query = _pending(sorted(targets), before, text_matches)
        ids = list((await session.scalars(query)).all()) if targets else []
    if limit is not None:
        ids = ids[:limit]
    stats: Counter[str] = Counter(pending=len(ids))
    result = {"companies": sorted(targets), "denied": denied, "stats": stats}
    if not apply or not ids:
        return result

    async with AsyncExitStack() as stack:
        adapters = await open_adapters(stack, targets)

        async def work(session, chunk: list[int]) -> int:
            by_id = {
                job.id: job
                for job in (await session.scalars(select(Job).where(Job.id.in_(chunk)))).all()
            }
            saved: list[int] = []
            for job in (by_id[job_id] for job_id in chunk if job_id in by_id):
                if job.status != "open" or not job.description_fetched_at or job.description_fetched_at >= before:
                    stats["skipped"] += 1
                    continue
                adapter = adapters[job.company]
                raw = RawJob(
                    company=job.company,
                    req_id=job.req_id,
                    title=job.title,
                    url=job.url,
                    locations=list(job.locations or []),
                    # `RawJob` defaults to complete, and some adapters skip a
                    # posting whose text is complete.
                    description_complete=False,
                )
                try:
                    raw.detail_payload = adapter.payload_from_posting(raw)
                    await adapter.hydrate(raw)
                    structure_job_detail(
                        raw, adapter.drift, payload=raw.detail_payload, source=adapter_key
                    )
                except Exception as exc:  # noqa: BLE001 - a repair pass is best effort
                    log.warning("re-read failed for job %s: %s", job.id, exc)
                    stats["failed"] += 1
                    continue
                text = sections_to_text(raw.description_sections) or html_to_text(raw.description_html)
                if not text:
                    stats["no_text"] += 1
                    continue
                if backup:
                    # Append: a rerun must not truncate the rows an earlier run saved.
                    with open(backup, "a", encoding="utf-8") as fh:
                        fh.write(json.dumps(_snapshot(job)) + "\n")
                job.description_html = raw.description_html
                job.description_sections = [s.as_dict() for s in raw.description_sections]
                job.description_text = text
                job.description_fetched_at = datetime.now(UTC)
                if job.disclosed_source != "connector":
                    job.structured_at = None
                saved.append(job.id)
            if saved:
                await session.flush()
                await refresh_search_vectors(session, saved)
                await fingerprint_content(session, saved)
                await extract_requirements(session, saved)
            stats["saved"] += len(saved)
            return len(saved)

        await commit_in_batches(ids, work, size=batch, label="re-read descriptions")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="python -m scripts.refetch_descriptions",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--adapter", required=True, help="adapter key, e.g. google")
    parser.add_argument(
        "--fetched-before",
        required=True,
        type=datetime.fromisoformat,
        help="ISO time the parser fix landed; rows fetched earlier are re-read",
    )
    parser.add_argument("--apply", action="store_true", help="re-read and save (default: count only)")
    parser.add_argument(
        "--text-matches",
        help="only rows whose stored description text matches this PostgreSQL regular expression",
    )
    parser.add_argument("--limit", type=int, help="stop after this many rows")
    parser.add_argument("--backup", help="append each row's previous description fields to this JSONL file")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING)
    before = args.fetched_before
    if before.tzinfo is None:
        parser.error("--fetched-before needs a timezone, e.g. 2026-01-01T00:00:00+00:00")

    result = asyncio.run(
        run(
            adapter_key=args.adapter,
            before=before,
            apply=args.apply,
            limit=args.limit,
            backup=args.backup,
            text_matches=args.text_matches,
        )
    )
    stats = result["stats"]
    print(f"companies: {', '.join(result['companies']) or 'none'}")
    if result["denied"]:
        print(f"not collectable (no consent or denied): {', '.join(result['denied'])}")
    if args.apply:
        print(
            f"saved {stats['saved']} of {stats['pending']}; no text {stats['no_text']}, "
            f"failed {stats['failed']}, skipped {stats['skipped']}"
        )
    else:
        print(f"{stats['pending']} row(s) to re-read; re-run with --apply to save them")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
