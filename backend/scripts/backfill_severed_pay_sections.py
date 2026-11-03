"""Re-read postings whose Compensation section was severed mid-sentence.

A promoted pay section cut from a *padded quote* of the body, rather than the
sentence around it, begins in the middle of a word:

    Business Analytics M6 - The typical bas | e pay range for this role across
    the U.S. is USD $155,800 - $277,200 per year.

`description_text` is rebuilt FROM the sections, so after that cut the intact
sentence exists nowhere and `derive_pay_basis` can only answer `unclear`.

The connector cuts at sentences, but it only reaches a job when its detail is
fetched again, and no ordinary run will do that for these rows:

- `description_refresh_days` holds the row fresh, and
- the pipeline's own description backfill only takes rows with NO text, and
- a row out of scope (`in_scope = False`, a filtered role still open on the
  board) is never reached by a scrape at all, so invalidating a timestamp
  fixes nothing.

So this fetches them directly, one detail call per job through the company's own
adapter, at the source's pace (`refetch_descriptions.open_adapters`), and
rewrites only the description fields. A company policy does not let us read
(a walled one without the user's consent) is reported and never fetched. It touches no `disclosed_*`
value: the extraction pass re-derives those from the repaired text, which is the
only thing that can be right.

    .venv/bin/python -m scripts.backfill_severed_pay_sections            # dry run
    .venv/bin/python -m scripts.backfill_severed_pay_sections --apply
    .venv/bin/python -m scripts.backfill_severed_pay_sections --apply --company microsoft

Idempotent by construction: a re-fetched section starts at a sentence, so it
does not match again. Best-effort per job, like the pipeline's own backfill: a source
that fails to answer leaves its row exactly as it was.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
from collections import Counter
from contextlib import AsyncExitStack
from datetime import UTC, datetime

from sqlalchemy import select

from scripts.refetch_descriptions import collectable, open_adapters
from tracker.company_store import get_active_targets
from tracker.connectors import BaseAdapter, structure_job_detail
from tracker.connectors.detail.base import PAY_SECTION_KEY, sections_to_text
from tracker.db.models import Job
from tracker.db.session import session_scope
from tracker.platform.util import html_to_text
from tracker.schema import RawJob

log = logging.getLogger(__name__)


def is_severed(sections: object) -> bool:
    """True when the stored pay section starts mid-sentence.

    A sentence starts with a capital, a digit or a currency symbol. Lowercase is
    the fingerprint of the severed cut, and the ONLY fingerprint available: the
    source payload it was cut from is not retained, so the severance cannot be
    confirmed against the original. See `run` for why closed rows are left alone.
    """
    if not isinstance(sections, list):
        return False
    for section in sections:
        if not isinstance(section, dict) or section.get("key") != PAY_SECTION_KEY:
            continue
        content = (section.get("content") or "").strip()
        return bool(content) and content[0].islower()
    return False


async def _refetch(job: Job, adapter: BaseAdapter, source: str) -> bool:
    """Re-read one posting's detail through its company's adapter. True if rewritten."""
    raw = RawJob(
        company=job.company,
        req_id=job.req_id,
        title=job.title,
        url=job.url,
        locations=list(job.locations or []),
    )
    try:
        await adapter.hydrate(raw)
        structure_job_detail(raw, adapter.drift, payload=raw.detail_payload, source=source)
    except Exception as exc:  # noqa: BLE001 - a repair pass is best effort
        log.warning("re-read failed for job %s: %s", job.id, exc)
        return False
    text = sections_to_text(raw.description_sections) or html_to_text(raw.description_html)
    if not text:
        # The source served no text this time. Keeping the severed row is right:
        # a repair we could not make is not a reason to lose what we hold.
        return False
    job.description_html = raw.description_html
    job.description_sections = [s.as_dict() for s in raw.description_sections]
    job.description_text = text
    job.description_fetched_at = datetime.now(UTC)
    # Let the extraction pass re-derive the band from the repaired text. Not a
    # connector's row: the text pass never reads one, so a cleared stamp would
    # never be written again.
    if job.disclosed_source != "connector":
        job.structured_at = None
    return True


async def run(*, apply: bool, company: str | None, limit: int | None) -> dict:
    found: Counter[str] = Counter()
    repaired: Counter[str] = Counter()
    denied: list[str] = []
    async with session_scope() as session:
        # Open rows only. A closed posting cannot be re-read (the source answers 404)
        # and its stored text is a HISTORICAL record of what the employer published,
        # not a live claim to repair. Without this the pass would spend a fetch
        # per closed row learning that, and report the same rows every run.
        query = select(Job).where(
            Job.description_sections.isnot(None), Job.status == "open"
        )
        if company:
            query = query.where(Job.company == company)
        jobs = [j for j in (await session.scalars(query)).all() if is_severed(j.description_sections)]
        jobs.sort(key=lambda j: j.id)
        if limit is not None:
            jobs = jobs[:limit]
        for job in jobs:
            found[job.company] += 1
        if not apply:
            return {"found": dict(found), "repaired": {}, "denied": denied}

        targets = await get_active_targets(session)
        wanted = {slug: targets[slug] for slug in found if slug in targets and targets[slug].get("adapter")}
        allowed, denied = collectable(wanted)
        async with AsyncExitStack() as stack:
            adapters = await open_adapters(stack, allowed)
            for job in jobs:
                adapter = adapters.get(job.company)
                if adapter is None:
                    continue
                if await _refetch(job, adapter, allowed[job.company]["adapter"]):
                    repaired[job.company] += 1
                    # Commit per job: an interrupted repair must lose at most one.
                    await session.commit()
    return {"found": dict(found), "repaired": dict(repaired), "denied": denied}


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="python -m scripts.backfill_severed_pay_sections",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--apply", action="store_true", help="re-read (default: report only)")
    parser.add_argument("--company", help="restrict to one company slug")
    parser.add_argument("--limit", type=int, help="stop after this many jobs")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING)

    result = asyncio.run(run(apply=args.apply, company=args.company, limit=args.limit))
    for slug, count in sorted(result["found"].items()):
        print(f"  {slug:16s} severed {count:4d}  repaired {result['repaired'].get(slug, 0)}")
    total = sum(result["found"].values())
    if result["denied"]:
        print(f"not collectable (no consent or denied): {', '.join(result['denied'])}")
    if args.apply:
        print(f"re-read {sum(result['repaired'].values())} of {total} severed description(s)")
    else:
        print(f"{total} severed description(s); re-run with --apply to re-read them")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
