"""Persistence half of profile inference.

`user_profile/inference.py` owns the scoring and is pure of DB and settings.
This module loads the signals, runs it, and is the ONLY writer of
`profile_suggestions`, registered as a `POST_PASSES` entry so a scrape
maintains suggestion freshness, never a CLI-only producer.

Write rules (the sharp edges):
- A resolved (accepted/dismissed) `dedupe_key` is never re-raised.
- A pending row is refreshed in place while its evidence still supports it,
  and DELETED when it stops: a suggestion must never outlive its reasons.
- Nothing here touches `enabled_domain_groups`, `jobs.domains`, or `in_scope`;
  the accept endpoint is the only apply path.
"""

from __future__ import annotations

import logging
from collections import Counter

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tracker.company_discovery import COMPANY_DISCOVERY
from tracker.db.models import (
    Favorite,
    Job,
    JobFeedback,
    ProfileClaim,
    ProfileSuggestion,
    Pursuit,
    TrackedCompany,
)
from tracker.settings_store import get_enabled_domains, get_persona_profile
from tracker.taxonomy.domains import match_domains
from tracker.user_profile.background import EXPERIENCE
from tracker.user_profile.inference import WorldSignals, suggest_worlds

logger = logging.getLogger(__name__)


async def _domain_counts(session: AsyncSession, stmt) -> Counter[str]:
    """Aggregate `jobs.domains` arrays from a (domains,) row statement."""
    counts: Counter[str] = Counter()
    for (domains,) in await session.execute(stmt):
        for world in domains or []:
            counts[world] += 1
    return counts


async def load_world_signals(session: AsyncSession) -> WorldSignals:
    """The signal loader `suggest_worlds` runs on. Counts one event per
    (job, signal) pair; a job carrying two worlds counts once for each —
    multi-label mirrors the scope gate's own semantics."""
    favorited = await _domain_counts(
        session, select(Job.domains).join(Favorite, Favorite.job_id == Job.id)
    )
    pursued = await _domain_counts(
        session, select(Job.domains).join(Pursuit, Pursuit.job_id == Job.id)
    )
    wrong = await _domain_counts(
        session,
        select(Job.domains)
        .join(JobFeedback, JobFeedback.job_id == Job.id)
        .where(JobFeedback.verdict == "dismissed", JobFeedback.reason == "wrong_domain"),
    )
    other = await _domain_counts(
        session,
        select(Job.domains)
        .join(JobFeedback, JobFeedback.job_id == Job.id)
        .where(
            JobFeedback.verdict == "dismissed",
            (JobFeedback.reason.is_(None)) | (JobFeedback.reason != "wrong_domain"),
        ),
    )
    tracked = (
        await session.scalars(
            select(TrackedCompany.slug).where(TrackedCompany.enabled.is_(True))
        )
    ).all()
    sectors: list[str] = []
    for slug in tracked:
        entry = COMPANY_DISCOVERY.get(slug)
        if entry is not None:
            sectors.extend(entry.sectors)
    persona = await get_persona_profile(session)
    intent = str((persona or {}).get("intent_statement") or "")
    # Active background experiences: each entry votes once per world its
    # title/summary names, through the same lexicon the classifier uses.
    background: Counter[str] = Counter()
    experience_rows = (
        await session.scalars(
            select(ProfileClaim.value).where(
                ProfileClaim.field == EXPERIENCE,
                ProfileClaim.superseded_at.is_(None),
            )
        )
    ).all()
    for value in experience_rows:
        text = f"{value.get('title', '')} {value.get('summary', '')}"
        for world in match_domains(text):
            background[world] += 1
    return WorldSignals(
        favorited=dict(favorited),
        pursued=dict(pursued),
        dismissed_wrong_domain=dict(wrong),
        dismissed_other=dict(other),
        tracked_sectors=tuple(sectors),
        intent_statement=intent,
        background=dict(background),
    )


async def run_profile_inference(session: AsyncSession) -> dict:
    signals = await load_world_signals(session)
    enabled = frozenset(await get_enabled_domains(session))
    desired = suggest_worlds(signals, enabled)
    desired_by_key = {s.dedupe_key: s for s in desired}

    existing = (await session.scalars(select(ProfileSuggestion))).all()
    by_key = {row.dedupe_key: row for row in existing}

    summary = {"created": 0, "refreshed": 0, "expired": 0, "suppressed": 0}
    for suggestion in desired:
        row = by_key.get(suggestion.dedupe_key)
        if row is None:
            session.add(
                ProfileSuggestion(
                    kind=suggestion.kind,
                    dedupe_key=suggestion.dedupe_key,
                    payload={"world": suggestion.world},
                    basis=suggestion.basis,
                )
            )
            summary["created"] += 1
        elif row.status == "pending":
            row.basis = suggestion.basis
            summary["refreshed"] += 1
        else:
            # Resolved once = resolved forever for this key.
            summary["suppressed"] += 1

    for row in existing:
        if row.status == "pending" and row.dedupe_key not in desired_by_key:
            await session.delete(row)
            summary["expired"] += 1

    await session.commit()
    if summary["created"] or summary["expired"]:
        logger.info("profile_inference: %s", summary)
    return summary


