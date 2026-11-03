"""What the matching model IS, and what switching it costs.

The tier switch is the most expensive button in Settings: fp32 and int8 are the
same model in *nearly* the same space, so a corpus half in each ranks against a
seam, and moving between them re-embeds every row. Its policy (when a switch is
a no-op, what order the choice, the decision file, the loaded encoder and the
spawn must happen in, where "stop and go back" goes back to) lives here, testable
without a FastAPI handler; the HTTP mapping stays in `routers/intelligence.py`.
Each operation answers an outcome, which the router turns into a status code:

| outcome | HTTP |
|---|---|
| `TierSwitch.BUSY`, `StopSwitch.NOT_RUNNING`, `StopSwitch.UNMANAGED`, `ResumeSwitch.BUSY` | 409 |
| `TierSwitch.SPAWN_FAILED`, `StopSwitch.COULD_NOT_STOP`, `ResumeSwitch.SPAWN_FAILED` | 503 |
| everything else | 200 |

**Process facts are injected, never imported.** The re-embed runs under the
supervisor; asking for it, stopping it and asking whether it runs are the API's
(`tracker.api.job_requests`, L6), and this module is L4: it may not reach up,
and it must not, because that is what makes these decisions testable with a fake
spawn instead of a real one. The router looks them up lazily at call time.

Two orderings are load-bearing and are stated here because nothing else states
them:

* **Switching**: record the choice and COMMIT, push it to this checkout's
  decision file, drop the loaded encoder, then spawn. A spawn before the commit
  can read the old choice; a decision file written before the commit makes this
  checkout disagree with the shared row if the commit fails.
* **Stopping**: stop the process FIRST, then restore the choice. A batch that
  lands after the choice moves back is harmless — every row carries the tier that
  produced it — but moving the choice under a live encoder manufactures exactly
  the mixed-space state the stop exists to prevent. The stop waits until the
  supervisor has ended the run; one still live at its deadline is an "error",
  and the choice stays.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import Enum
from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from tracker.config import get_settings
from tracker.db.models import Job
from tracker.platform.locks import advisory_lock_held
from tracker.semantic import embed, provision
from tracker.semantic.embed import stale_predicate
from tracker.semantic.manifest import spec_for
from tracker.semantic.tier_store import get_tier_choice, set_tier_choice
from tracker.settings_store import get_embed_measurements

logger = logging.getLogger(__name__)

#: int8 embeds at roughly this fraction of fp32's rate on the same machine.
#: Applied only to scale ACROSS tiers when just one
#: has been measured; a direct measurement always wins.
INT8_RATE_RATIO = 0.81


class TierSwitch(Enum):
    """Why a switch request ended the way it did."""

    BUSY = "busy"
    #: Same choice, same tier: nothing was written and nothing spawned.
    NOOP = "noop"
    #: The choice was recorded, but it resolves to the tier already active — so
    #: there is nothing to re-embed. Pinning the value auto-detection produced.
    CHOSEN_SAME_TIER = "chosen_same_tier"
    STARTED = "started"
    #: The choice is committed and the corpus disagrees with it; the nightly
    #: pass will finish the work. Reported rather than swallowed, or the screen
    #: would look settled while nothing runs.
    SPAWN_FAILED = "spawn_failed"


class StopSwitch(Enum):
    NOT_RUNNING = "not_running"
    #: The process could not be signalled, so the choice was left alone.
    COULD_NOT_STOP = "could_not_stop"
    #: An embedder exists that we did not spawn (a hand-run backfill). Never
    #: reinterpreted as a stopped switch.
    UNMANAGED = "unmanaged"
    STOPPED = "stopped"


class ResumeSwitch(Enum):
    BUSY = "busy"
    SPAWN_FAILED = "spawn_failed"
    STARTED = "started"


@dataclass(frozen=True)
class StopResult:
    """The verdict, plus what the terminate call itself reported."""

    verdict: StopSwitch
    outcome: str | None = None


async def lock_held(session: AsyncSession) -> bool:
    """Is the corpus re-embed advisory lock taken by anyone?

    Catches a hand-run `python -m tracker.semantic.backfill`, which no
    supervisor request names. A probe that fails must never fail the
    screen, so an unreachable lock reads as "not running" and says so in the log.
    """
    from tracker.semantic.backfill import is_running

    try:
        return await is_running(session)
    except Exception:  # noqa: BLE001 — a lock probe must never fail the screen
        logger.warning("could not probe the re-embed lock", exc_info=True)
        return False


async def reembed_in_progress(session: AsyncSession, *, requested: bool) -> bool:
    """Is any corpus re-embed running — ours or the user's?

    Both signals, because neither alone is complete. The lock catches an embedder
    we did not ask for; `requested` (ours is queued or live) covers the time
    before the child reaches the lock, during which the lock is genuinely free
    and the switch would otherwise look already finished.
    """
    return requested or await lock_held(session)


def estimate_seconds(measured: dict, tier: str | None, rows: int) -> int | None:
    """How long `rows` will take on `tier`, from what this computer has done.

    Never a constant: a duration measured on one corpus and one machine is
    wrong anywhere else. With no measurement for either tier this returns None
    and the caller must show no figure at all rather than invent one.

    Pure, and given the measurements rather than a session: `matching_state`
    needs three estimates per request from one settings read.
    """
    if not rows or tier is None:
        return None
    own = measured.get(tier)
    if own and own.get("seconds") and own.get("rows"):
        rate = own["rows"] / own["seconds"]
    else:
        other_tier = "int8" if tier == "fp32" else "fp32"
        other = measured.get(other_tier)
        if not (other and other.get("seconds") and other.get("rows")):
            return None
        rate = other["rows"] / other["seconds"]
        # Scale from the tier we did measure toward the one we did not.
        rate *= INT8_RATE_RATIO if tier == "int8" else 1 / INT8_RATE_RATIO
    if rate <= 0:
        return None
    return int(rows / rate)


JobPhase = Literal["downloading", "converting", "none"]


def phase_of(provision_status: str | None, *, reembed_running: bool) -> JobPhase:
    """Which background job the matching model is in, named rather than
    inferred by a screen from a combination of booleans. `downloading` and
    `converting` matter apart: during a download nothing has been converted
    yet, so backing out costs nothing, while during conversion it costs the
    rows already moved."""
    if provision_status is None:
        return "none"
    if provision_status == "downloading":
        return "downloading"
    if reembed_running:
        return "converting"
    return "none"


async def running_phase(session: AsyncSession, *, requested: bool) -> JobPhase:
    """`phase_of` at the price of a status poll: the weights on disk and who
    holds the re-embed lock, with no corpus count and no lock taken."""
    status, held = await activity_facts(session)
    return phase_of(status, reembed_running=requested or held)


async def activity_facts(session: AsyncSession) -> tuple[str | None, bool]:
    try:
        spec = spec_for(get_settings().embedding_model)
    except ValueError:
        return None, False
    state = provision.provision_state(spec, provision.resolve_tier())
    return state.status, await advisory_lock_held(session, get_settings().reembed_lock_key)


async def matching_state(session: AsyncSession, *, reembed_running: bool) -> dict:
    """Provisioning state of the bundled embedding model — what the Settings
    outcome card may truthfully claim. `ready` backs "Matching runs on this
    Mac"; anything else renders the one quiet progress line, never a dialog.

    The card itself still carries no controls. The tier fields below feed the
    Advanced disclosure, which is where a user who wants the choice
    can find it without it becoming a first-run question for everyone else.
    """
    settings = get_settings()
    try:
        spec = spec_for(settings.embedding_model)
    except ValueError:
        return {
            "status": "missing", "tier": None, "model_id": settings.embedding_model,
            "downloaded_bytes": 0, "total_bytes": 0, "chosen_by": "auto",
            "detected_ram_bytes": None, "ram_threshold_bytes": provision.TIER_RAM_THRESHOLD,
            "tiers": [], "reembedding": False,
            "stale_count": 0, "other_tier_count": 0, "job_phase": "none",
            "corpus_embedded": 0, "corpus_total": 0,
        }
    tier = provision.resolve_tier()
    state = provision.provision_state(spec, tier)
    decision = provision.read_decision() or {}

    # Corpus progress is COUNTED, not derived from a bulk write we had to
    # remember to perform. "On the active model" is a property each row
    # carries, so a half-finished switch reports an honest fraction even if
    # the job that was performing it died, rather than rendering as settled.
    on_active, on_other, total = (
        await session.execute(
            select(
                func.count().filter(Job.embedded_tier == state.tier),
                func.count().filter(Job.embedded_tier.is_distinct_from(state.tier) & Job.embedded_tier.is_not(None)),
                func.count(),
            ).select_from(Job)
        )
    ).one()
    stale = (
        await session.scalar(
            select(func.count()).select_from(Job).where(stale_predicate(state.tier))
        )
        or 0
    )
    # Read only when something will use it. Nothing is estimated for an empty
    # corpus with no work owed, and reading unconditionally would add a query
    # to every request on a fresh install.
    measured = (
        await get_embed_measurements(session) if (total or stale) else {}
    )

    job_phase = phase_of(state.status, reembed_running=reembed_running)

    return {
        "status": state.status,
        "tier": state.tier,
        "model_id": spec.name,
        "downloaded_bytes": state.downloaded_bytes,
        "total_bytes": state.total_bytes,
        # Who decided, and what the hardware would have said. Shown together so
        # a user can see that "auto" picked the smaller artifact because
        # detection FAILED (detected_ram_bytes null) rather than because their
        # Mac is small.
        #
        # The DB row is the ONLY authority here. Falling back to the file's own
        # `chosen_by` would break that: after another checkout restores auto,
        # this one would keep reporting "user" from its stale file until its
        # next warm-up, rendering a "Use automatic" button whose every click
        # hits the no-op branch and so can never clear itself.
        "chosen_by": "user" if await get_tier_choice(session) else "auto",
        "detected_ram_bytes": decision.get("detected_ram_bytes"),
        # The line the automatic choice draws, stated beside the machine's
        # reading so the screen never carries a copy of it.
        "ram_threshold_bytes": provision.TIER_RAM_THRESHOLD,
        # Each option carries what SWITCHING to it would cost on this machine
        # — the whole corpus, not the work currently owed, because that is the
        # question the confirm dialog asks. Null where nothing has been
        # measured yet: the dialog then states the work without a duration
        # rather than inventing one.
        "tiers": [
            {**option, "switch_seconds": estimate_seconds(measured, option["tier"], int(total or 0))}
            for option in provision.tier_options(spec)
        ],
        "reembedding": reembed_running,
        "corpus_embedded": int(on_active or 0),
        "corpus_total": int(total or 0),
        # All the work owed: rows never embedded, rows whose text moved on, and
        # rows on the other artifact.
        "stale_count": int(stale),
        # Only rows still on the other artifact make a switch interrupted: with
        # `job_phase == "none"` they are a switch that stopped partway, which the
        # screen must say out loud. Rows that were never embedded are a scan's
        # ordinary backlog, as on a fresh install where no switch ever ran.
        "other_tier_count": int(on_other or 0),
        "job_phase": job_phase,
        # Seconds this computer is expected to need for the work still owed.
        # None when nothing has been measured yet — a screen may then say how
        # many roles are left, but never how long, because we do not know.
        "estimate_seconds": estimate_seconds(measured, state.tier, int(stale)),
    }


async def switch_tier(
    session: AsyncSession,
    target: str | None,
    *,
    reembed_running: bool,
    spawn: Callable[[], Awaitable[bool]],
) -> TierSwitch:
    """Choose which artifact of the bundled model this Mac runs, or restore auto.

    `target is None` restores auto-detection. A no-op switch writes nothing and
    spawns nothing: re-selecting the active tier must not cost a full re-embed
    for zero change.

    No corpus invalidation happens here. `jobs.embedded_tier` records
    which artifact produced each vector, so "needs re-embedding" is a PROPERTY of
    each row rather than something to stamp across the table. Three things
    follow: an abandoned switch self-heals on the next pass, stopping costs only
    the rows already moved, and switching A->B->A is nearly free.
    """
    if reembed_running:
        return TierSwitch.BUSY

    current_tier = provision.resolve_tier()
    current_choice = await get_tier_choice(session)
    if target == current_choice and (target is None or target == current_tier):
        return TierSwitch.NOOP

    # Does this actually move the tier? Asked before anything is written, so the
    # choice and the corpus invalidation can commit together.
    moves = provision.would_resolve(target) != current_tier

    await set_tier_choice(session, target)
    await session.commit()

    provision.set_tier(target)
    if not moves:
        return TierSwitch.CHOSEN_SAME_TIER

    embed.reset_model()
    return TierSwitch.STARTED if await spawn() else TierSwitch.SPAWN_FAILED


async def stop_switch(
    session: AsyncSession,
    *,
    reembed_running: bool,
    terminate: Callable[[], Awaitable[tuple[str, int | None]]],
    still_running: Callable[[], Awaitable[bool]],
) -> StopResult:
    """Stop the running switch AND put the choice back. One operation.

    There is deliberately no operation that only kills the job. The corpus is
    converted in place, so a bare stop would leave the tier pointing at the model
    the user just cancelled with most rows still on the old one — and the next
    scheduled pass would finish the switch they believed they had stopped. The
    only honest cancel is stop-and-revert.
    """
    if not reembed_running:
        return StopResult(StopSwitch.NOT_RUNNING)

    outcome, _pid = await terminate()
    if outcome == "error":
        # The worker may still be writing vectors for the active tier. Moving
        # the choice underneath it would manufacture the mixed-space state this
        # operation exists to prevent.
        return StopResult(StopSwitch.COULD_NOT_STOP, outcome)
    if outcome == "not_running" and await still_running():
        return StopResult(StopSwitch.UNMANAGED, outcome)

    # A switch always moves between the two offered artifacts, so the tier to
    # restore is the one that is NOT active now. Corpus majority is not an
    # origin record: after a switch crosses 50%, the majority is the NEW tier
    # and using it makes "Stop and go back" stop without going back. Deriving
    # from the active tier stays correct at every progress point and survives an
    # API restart without another piece of mutable switch state.
    active_tier = provision.resolve_tier()
    previous = next(tier for tier in provision.TIERS if tier != active_tier)
    current_choice = await get_tier_choice(session)
    target = previous if previous in {"fp32", "int8"} else None

    # Restoring "automatic" rather than pinning is right when auto already
    # resolves to the tier we are returning to: the user was on auto before they
    # tried this, and coming back should not silently pin them.
    if target is not None and provision.would_resolve(None) == target:
        target = None
    if target != current_choice:
        await set_tier_choice(session, target)
        await session.commit()
        provision.set_tier(target)
        embed.reset_model()

    # Anything already converted goes back on the next pass; nothing is
    # scheduled here, because the user asked for this to stop.
    return StopResult(StopSwitch.STOPPED, outcome)


async def resume_switch(*, reembed_running: bool, spawn: Callable[[], Awaitable[bool]]) -> ResumeSwitch:
    """Finish an interrupted switch now, without touching the choice.

    Its own operation rather than a re-selection of the current tier, because
    that would be a different act with two wrong side effects: it records the
    tier as a USER choice (the screen would start offering "Choose
    automatically" to someone who never chose), and it starts nothing at all —
    the tier is not moving, so `switch_tier` correctly treats it as a no-op. The
    work owed here is not a choice, it is the remainder of one already made.
    """
    if reembed_running:
        return ResumeSwitch.BUSY
    return ResumeSwitch.STARTED if await spawn() else ResumeSwitch.SPAWN_FAILED
