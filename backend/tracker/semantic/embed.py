"""Semantic embedding of jobs — the vector half of the intelligence layer.

Encodes each job's (title + description) into `jobs.embedding` (pgvector) with
a bundled ONNX model — no torch, no sentence-transformers, no cloud call. The
artifacts are app-provisioned (`provision.py`, sha256-pinned) and the runtime
shape (window, pooling, prefixes) comes from the pinned spec (`manifest.py`).
Incremental: a job is (re)embedded only when it has never been embedded or its
text changed since (`content_changed_at > embedded_at`), the generic
content-fingerprint signal owned by `tracker/content.py`.

Degradation contract: while weights are missing the
API paths return no vector and the board falls back to lexical + first_seen —
never an error dialog. The pipeline embed pass, by contrast, fails honestly
(`ModelNotReady` -> fatal pass) so missing coverage is visible, not silent.

The encoder is a heavy singleton loaded lazily on first use.

Encoding never runs on the caller's event loop. A document takes long enough
that a corpus-sized batch would hold the loop for the better part of an hour,
and the pipeline's liveness heartbeat is a task on that same loop: a blocked
loop is a run the stale-run reconciler declares dead.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Collection

from sqlalchemy import Integer, any_, func, literal, or_, select
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.ext.asyncio import AsyncSession

from tracker.config import get_settings
from tracker.db.models import Job
from tracker.platform import preparation
from tracker.platform.paths import DATA_DIR, PACKAGED
from tracker.semantic import provision
from tracker.semantic.encoder import OnnxEncoder
from tracker.semantic.manifest import spec_for

logger = logging.getLogger(__name__)

_model: OnnxEncoder | None = None
_warming = False


def model_warming() -> bool:
    return _warming

#: app_settings key holding what was actually provisioned (tier, shas, RAM).
PROVENANCE_KEY = "embedding_provision"

#: Rows per committed embed transaction. The encoder is batch-1 internally
#: (`encoder.py` pins that), so this is a COMMIT size, not an inference batch:
#: it buys durability and visible progress, never throughput. Every caller
#: chunks on it, so `embed_jobs` never holds more than this many vectors and a
#: killed embedder loses at most this many rows of work.
EMBED_COMMIT_BATCH = 200


def get_model() -> OnnxEncoder:
    """Lazily load and cache the ONNX encoder for the configured model.

    Raises `provision.ModelNotReady` when artifacts are absent or fail
    verification — provisioning belongs to `warm_model`/install pre-warm,
    never to a caller's request path.
    """
    global _model
    if _model is None:
        spec = spec_for(get_settings().embedding_model)
        tier = provision.resolve_tier()
        provision.require_ready(spec, tier)
        _model = OnnxEncoder(
            spec,
            tier,
            str(provision.artifact_path(spec, spec.tiers[tier])),
            str(provision.artifact_path(spec, spec.tokenizer)),
        )
    return _model


def reset_model() -> None:
    """Drop the cached encoder so the next call reloads at the current tier.

    A tier switch changes which graph `get_model` should open, and the API
    process outlives the switch — without this the user would keep querying
    through the old artifact until the next restart, against a corpus being
    re-embedded through the new one.
    """
    global _model
    _model = None


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Encode documents to normalized vectors (cosine == dot product). Pure, testable."""
    if not texts:
        return []
    return get_model().encode(texts, kind="document")


async def embed_query(text: str) -> list[float]:
    """Encode a single search/intent query to a normalized vector, off the event loop.

    Query and document embeddings must come from the same model (one space for
    every consumer); the spec decides whether a query prefix applies. Blocking
    CPU work runs in a threadpool to avoid stalling FastAPI's loop. If weights
    are not provisioned yet this returns [] — search degrades to lexical, the
    board never blanks. Tests patch this to avoid loading the model.
    """
    from fastapi.concurrency import run_in_threadpool

    if not text or not text.strip():
        return []

    def _encode() -> list[float]:
        try:
            return get_model().encode([text], kind="query")[0]
        except provision.ModelNotReady:
            logger.warning("embedding model not provisioned; query runs lexical-only")
            return []

    return await run_in_threadpool(_encode)


async def warm_model() -> None:
    global _warming
    if _warming:
        return
    _warming = True
    try:
        await _warm_model()
    finally:
        _warming = False


async def _warm_model() -> None:
    """Provision (download if needed) and load the encoder ahead of first use.

    Best-effort background task at API startup — the one place downloading is
    allowed besides `deploy/install.sh` pre-warm. Failure logs and leaves the
    app lexical-only; the next startup retries. On success the provenance
    record is mirrored to app_settings for the Settings quiet line.
    """
    from fastapi.concurrency import run_in_threadpool

    # The shared choice decides the tier before anything is downloaded. Its own
    # failure is not fatal: a DB that is not up yet must leave the machine on
    # the tier already on file rather than block warm-up entirely.
    try:
        await _reconcile_tier()
    except Exception:  # noqa: BLE001 — the file's decision still stands
        logger.warning("could not read the shared embedding-tier choice", exc_info=True)

    def _provision_and_load() -> None:
        spec = spec_for(get_settings().embedding_model)
        tier = provision.resolve_tier()

        def progress(state: provision.ProvisionState) -> None:
            preparation.update(DATA_DIR, model="verifying" if state.status == "ready" else "downloading",
                               downloaded_bytes=state.downloaded_bytes, total_bytes=state.total_bytes,
                               tier=tier, reason=None)

        if PACKAGED:
            provision.ensure_artifacts(spec, tier, progress=progress)
        else:
            provision.ensure_artifacts(spec, tier)
        get_model()
        if PACKAGED:
            state = provision.progress_state(spec, tier)
            preparation.update(DATA_DIR, model="ready", downloaded_bytes=state.total_bytes,
                               total_bytes=state.total_bytes, tier=tier, reason=None)

    while True:
        try:
            await run_in_threadpool(_provision_and_load)
            break
        except Exception as error:  # noqa: BLE001 - the API stays usable while preparation retries
            logger.warning("embedding model warm-up failed; running lexical-only", exc_info=True)
            if not PACKAGED:
                return
            reason = getattr(error, "reason", "model_failed")
            preparation.update(DATA_DIR, model="waiting" if reason == "offline" else "failed", reason=reason)
            await asyncio.sleep(30)

    try:
        await _record_provenance()
    except Exception:  # noqa: BLE001 — observability only
        logger.warning("could not record embedding provenance", exc_info=True)


async def _reconcile_tier() -> str:
    """Apply the shared tier choice to this checkout before provisioning."""
    from tracker.db.session import session_scope
    from tracker.semantic.tier_store import reconcile_tier

    async with session_scope() as session:
        return await reconcile_tier(session)


async def _record_provenance() -> None:
    from sqlalchemy.dialects.postgresql import insert

    from tracker.db.models import AppSetting
    from tracker.db.session import session_scope

    spec = spec_for(get_settings().embedding_model)
    record = provision.provenance_record(spec, provision.resolve_tier())
    async with session_scope() as session:
        stmt = insert(AppSetting).values(key=PROVENANCE_KEY, value=record)
        stmt = stmt.on_conflict_do_update(index_elements=[AppSetting.key], set_={"value": record})
        await session.execute(stmt)
        await session.commit()


def stale_predicate(active_tier: str):
    """A row needs embedding when it has none, when its text moved on, or when
    the vector was produced by a DIFFERENT model artifact than the active one.

    The third clause is what makes a tier switch representable without a bulk
    UPDATE clearing `embedded_at`: the condition IS the state, so an
    interrupted switch is simply a corpus that is partly at the other tier,
    and it converges by running the ordinary pass.
    """
    return or_(
        Job.embedded_at.is_(None),
        Job.content_changed_at > Job.embedded_at,
        Job.embedded_tier.is_distinct_from(active_tier),
    )


async def stale_job_ids(session: AsyncSession, job_ids: Collection[int]) -> list[int]:
    """Which of `job_ids` still need embedding, in id order. Commit-free.

    The queue a chunking caller walks, so it can size the work and commit
    between chunks before any encoding starts. Id order makes the cut a caller
    takes deterministic: the next pass resumes after it rather than
    re-selecting the same head.

    The ids go to Postgres as ONE array parameter rather than an expanded
    `IN (...)`: a full reconcile touches a row per open posting, and a bind
    parameter per id reaches the protocol's 32767 limit on a corpus this size.
    """
    if not job_ids:
        return []
    active_tier = provision.resolve_tier()
    stmt = (
        select(Job.id)
        .where(Job.id == any_(literal(list(job_ids), ARRAY(Integer))), stale_predicate(active_tier))
        .order_by(Job.id)
    )
    return list(await session.scalars(stmt))


async def embed_jobs(session: AsyncSession, job_ids: list[int]) -> int:
    """Embed the given jobs that are new or stale. Returns the number embedded.

    Commit-free: the caller owns the transaction, and passes at most
    `EMBED_COMMIT_BATCH` ids so one call is one durable chunk of work.
    """
    if not job_ids:
        return 0

    active_tier = provision.resolve_tier()
    stale = (
        await session.scalars(
            select(Job).where(Job.id.in_(job_ids), stale_predicate(active_tier))
        )
    ).all()
    if not stale:
        return 0

    texts = [f"{j.title or ''}\n{j.description_text or ''}" for j in stale]
    # Off the event loop: see the module docstring. `embed_texts` stays
    # synchronous and pure so it remains the seam tests and scripts drive.
    vectors = await asyncio.to_thread(embed_texts, texts)

    now = func.now()
    for job, vec in zip(stale, vectors, strict=True):
        job.embedding = vec
        job.embedded_at = now
        # Stamped with the SAME resolution the encoder used above, not read
        # again here: a tier change landing mid-batch would otherwise label
        # these vectors with the tier that did not produce them.
        job.embedded_tier = active_tier

    logger.info("embedded %d/%d jobs", len(stale), len(job_ids))
    return len(stale)
