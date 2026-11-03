"""Backfill content fingerprints + embeddings over the existing corpus.

Run after a deploy or any bulk text change to (re)compute `content_changed_at` and
semantic embeddings for jobs the daily pipeline hasn't touched:

    python -m tracker.semantic.backfill              # all jobs
    python -m tracker.semantic.backfill --open       # only currently-open jobs
    python -m tracker.semantic.backfill --refresh    # force re-embed all
    python -m tracker.semantic.backfill --provision --refresh   # after a tier switch

Incremental by default: fingerprints only bump on text change, and embeddings only
re-run when `content_changed_at > embedded_at`. Skill requirements have their own
backfill (`python -m tracker.skills.backfill`).

`--provision` downloads the artifact the current tier needs before embedding —
this is the entry point a tier switch spawns, and after a switch the
required artifact is by definition not on disk yet. `--refresh` there is not
optional: fp32 and int8 are the same model in *nearly* the same space, so a
corpus half in each is a mixed space, not a slightly worse one.

Interruption is safe by construction. `--refresh` clears `embedded_at` but
leaves `jobs.embedding` in place, so the board keeps ranking on the old vectors
while new ones land — degraded, never blank — and the nightly pipeline embed
pass already picks up anything with `embedded_at IS NULL`, so an abandoned
switch finishes itself rather than stranding the corpus.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import time

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from tracker.config import get_settings
from tracker.content import fingerprint_content
from tracker.db.models import AppSetting, Job
from tracker.db.session import commit_in_batches, session_scope
from tracker.osnotify import banner, notify
from tracker.platform.locks import advisory_unlock, try_advisory_lock
from tracker.semantic import provision
from tracker.semantic.embed import EMBED_COMMIT_BATCH, embed_jobs, embed_query
from tracker.semantic.tier_store import reconcile_tier
from tracker.settings_store import (
    INTENT_EMBEDDING_KEY,
    get_intent_embedding,
    record_embed_measurement,
    set_intent_embedding,
)

logger = logging.getLogger(__name__)


class AlreadyEmbedding(RuntimeError):
    """Another embedder holds the lock. Two would rewrite the same vectors."""


async def is_running(session: AsyncSession) -> bool:
    """Whether any embedder holds the re-embed lock right now.

    A Postgres advisory lock rather than a PID file, because only the API's
    own spawner writes the PID file: a hand-run
    `python -m tracker.semantic.backfill`, the command this module documents,
    would be invisible to it, so the API would start a second embedder over
    the same rows and report "not re-embedding" while one was running.

    Probed by taking the lock and immediately releasing it: acquiring it proves
    nobody else holds it. Session-scoped, so the release is on the same
    connection that took it.
    """
    key = get_settings().reembed_lock_key
    if await try_advisory_lock(session, key):
        await advisory_unlock(session, key)
        return False
    return True


async def run(
    *, open_only: bool, refresh: bool, embed: bool = True, provision_first: bool = False
) -> dict:
    """Hold the re-embed lock for the whole pass, then do the work.

    The lock is taken on its own long-lived session because a Postgres advisory
    lock lives on the connection that took it — taking it inside one of the
    short scopes below would release it the moment that scope closed, which is
    most of the run.
    """
    key = get_settings().reembed_lock_key
    async with session_scope() as holder:
        if not await try_advisory_lock(holder, key):
            raise AlreadyEmbedding(
                "another embedder is already running; two would rewrite the same vectors"
            )
        try:
            return await _run_locked(
                open_only=open_only, refresh=refresh, embed=embed,
                provision_first=provision_first,
            )
        finally:
            await advisory_unlock(holder, key)


async def _run_locked(
    *, open_only: bool, refresh: bool, embed: bool, provision_first: bool
) -> dict:
    # Invalidate BEFORE downloading, not after. A download that fails after the
    # tier already moved would otherwise leave a corpus still marked embedded
    # at the OLD tier while the machine runs the new one — a mixed space that
    # nothing would ever repair, because the incremental trigger
    # (`content_changed_at > embedded_at`) does not fire on a tier change.
    # Clearing first makes the failure self-healing instead: the encoder cannot
    # load, so search degrades to lexical rather than querying across the seam,
    # and the nightly embed pass fills the corpus in as soon as weights land.
    if refresh:
        async with session_scope() as invalidation:
            await invalidation.execute(text("UPDATE jobs SET embedded_at = NULL"))

    if provision_first:
        await _provision_current_tier()

    # The standing intent vector is re-embedded FIRST, not last. It is one
    # sentence, but `get_intent_embedding` gates on (model, tier), so between
    # `set_tier` and this call the stored vector reads as ABSENT. Done after
    # the corpus, the board's default "Best matches" sort would lose its
    # statement term for the whole switch: a user with a statement and little
    # feedback would fall back to date ordering with nothing explaining why,
    # and the Settings promise "you can keep working while it runs" would be
    # false.
    async with session_scope() as session:
        intent = await _refresh_intent(session) if embed else False

    async with session_scope() as session:
        stmt = select(Job.id).order_by(Job.id)
        if open_only:
            stmt = stmt.where(Job.status == "open")
        job_ids = list((await session.scalars(stmt)).all())
    # Per batch, not one transaction over the corpus: idempotent, so
    # a rerun after a kill fingerprints only what is left.
    fingerprinted = await commit_in_batches(
        job_ids, fingerprint_content, size=FINGERPRINT_BATCH, label="jobs fingerprinted", report=None,
    )

    started = time.monotonic()
    embedded = await _embed_in_batches(job_ids) if embed else 0
    elapsed = time.monotonic() - started

    # What this computer actually managed, so the screen can quote a real
    # figure instead of a constant someone measured once on another machine.
    # Peak RSS rides along because it is free here (the interpreter already
    # tracks it) and it is the number a user genuinely wants when choosing
    # between the two models.
    if embedded:
        async with session_scope() as session:
            await record_embed_measurement(
                session,
                tier=provision.resolve_tier(),
                rows=embedded,
                seconds=elapsed,
                peak_rss_bytes=_peak_rss_bytes(),
            )
            await session.commit()

    # Tell the user it finished. Minutes of silence after an explicit
    # choice reads as "did that work?", and the one place they are guaranteed
    # NOT to be looking is the settings screen they started it from.
    if embedded >= _MIN_NOTIFY_ROWS:
        notify(
            banner("banner-matching-title"),
            banner("banner-matching-body", count=embedded),
        )

    return {
        "jobs": len(job_ids),
        "fingerprinted": fingerprinted,
        "embedded": embedded,
        "intent_reembedded": intent,
    }


#: Jobs per fingerprint transaction.
FINGERPRINT_BATCH = 500


async def _embed_in_batches(job_ids: list[int]) -> int:
    """Embed in committed chunks rather than one transaction for the corpus.

    Each chunk commits, so a kill loses only the chunk in flight, and
    `embedded_at`, which the Settings screen counts to show progress, moves
    during the run instead of jumping from zero to the total at the end.

    Chunking also lowers peak memory: `embed_texts` materialises a vector per
    input, so a chunk holds `EMBED_COMMIT_BATCH` vectors, never the whole corpus.
    """
    embedded = 0
    for start in range(0, len(job_ids), EMBED_COMMIT_BATCH):
        async with session_scope() as session:
            embedded += await embed_jobs(session, job_ids[start : start + EMBED_COMMIT_BATCH])
    return embedded


async def _provision_current_tier() -> None:
    """Reconcile the shared tier choice, then fetch whatever it needs.

    Blocking and deliberately outside the session below: downloading a model
    while holding a DB session open would pin a connection for minutes.
    """
    from tracker.config import get_settings
    from tracker.semantic import provision
    from tracker.semantic.embed import reset_model
    from tracker.semantic.manifest import spec_for

    async with session_scope() as session:
        tier = await reconcile_tier(session)
    reset_model()
    spec = spec_for(get_settings().embedding_model)
    logger.info("provisioning %s (%s) before backfill", spec.name, tier)
    await asyncio.to_thread(provision.ensure_artifacts, spec, tier)


async def _refresh_intent(session: AsyncSession) -> bool:
    """Recompute the standing intent vector into the current space, if needed.

    Read straight from the row rather than through `get_intent_embedding`: that
    reader deliberately reports a stale-space record as *absent*, which is
    exactly the state this repairs. Without it a tier switch would quietly drop
    direction ranking back to recency until the user happened to re-save their
    profile. The statement is untouched; only its vector is recomputed.

    Gated on the record being stale rather than on a CLI flag, so it is
    self-healing: any pass that runs while the stored vector belongs to another
    (model, tier) puts it back, and a pass with nothing to repair costs one row
    read. Cheap enough to be unconditional, which is what lets it run FIRST.
    """
    row = await session.get(AppSetting, INTENT_EMBEDDING_KEY)
    statement = row.value.get("statement") if row and isinstance(row.value, dict) else None
    if not (isinstance(statement, str) and statement.strip()):
        return False
    if await get_intent_embedding(session) is not None:
        return False  # already in this space
    vector = await embed_query(statement)
    if not vector:
        return False
    await set_intent_embedding(session, statement, vector)
    logger.info("re-embedded the standing intent statement")
    return True


#: A nightly pass touching a handful of new roles is routine and must stay
#: silent; only a corpus-sized job is worth a banner.
_MIN_NOTIFY_ROWS = 200

def _peak_rss_bytes() -> int | None:
    """Peak resident memory of this process, or None where unavailable.

    `ru_maxrss` is bytes on macOS and kilobytes on Linux — the one portability
    trap in this call — so the unit is normalised here rather than at every
    reader. Standard library only; measuring this must never cost a dependency.
    """
    try:
        import resource
    except ImportError:  # pragma: no cover - non-POSIX
        return None
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    if not peak:
        return None
    return int(peak) if sys.platform == "darwin" else int(peak) * 1024


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill content fingerprints + embeddings.")
    parser.add_argument("--open", action="store_true", help="only currently-open jobs")
    parser.add_argument("--refresh", action="store_true", help="force re-embedding of every job")
    parser.add_argument("--no-embed", action="store_true", help="skip semantic embedding")
    parser.add_argument(
        "--provision",
        action="store_true",
        help="download the current tier's artifact first (used after a tier switch)",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING)
    summary = asyncio.run(
        run(
            open_only=args.open,
            refresh=args.refresh,
            embed=not args.no_embed,
            provision_first=args.provision,
        )
    )
    print(summary)


if __name__ == "__main__":
    main()


