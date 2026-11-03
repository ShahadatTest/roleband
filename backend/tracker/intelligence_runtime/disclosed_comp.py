"""The disclosed-salary-band extraction pass.

For each stale job with a monetary signal, scan the posting for a salary range,
validate it (grounding + bounds), and persist it into the `disclosed_*` columns —
alongside, never overwriting, the comp_* estimate. Gated exactly like embeddings
(`structured_at IS NULL OR content_changed_at > structured_at OR parser version changed`)
and slotted after the content-fingerprint step so `content_changed_at` is fresh.

The task's identity and the pure gating predicate stay in
`tracker/intelligence/extract.py`; what needs the store lives here.

WHY NO MODEL. Most stored bands never involve a model at all: connector parsers
read them straight out of the source payload. On the rest, `extract_grounded_band`
reproduces what a model answers, invents nothing on a no-band control set, and
never joins the low bound of one level band to the high bound of another, a
range printed nowhere in the posting, as a model can.

Salary extraction is core functionality, so it must work identically on every
machine with nothing installed and nothing configured. A deterministic scanner
does; a model that exists only on recent Apple silicon, or only after the user
installs a separate inference server, does not. Apple FM remains reachable from
Settings > Experimental for one-off testing, and the local/cloud tier ladder is
the model bench's; neither is consulted here.

Commits nothing: the post pass commits once per pass and the backfill command
commits each batch, so an interrupted backfill keeps every finished batch
(`extract_disclosed_comp`).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime

from sqlalchemy import and_, false, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from tracker.connectors.detail.base import PAY_SECTION_KEY
from tracker.db.models import Job, JobLifecycleEvent
from tracker.db.pay_band import BandChange, apply_band, pay_place_key
from tracker.enrich.classify import first_place, specific_places
from tracker.intelligence.extract import EXTRACTOR, EXTRACTOR_ID, TASK
from tracker.intelligence.prefilter import has_pay_pattern
from tracker.intelligence.provider import AvailabilityState
from tracker.intelligence_runtime.telemetry import log_ai_task
from tracker.pay_disclosure import (
    PAY_PARSER_VERSION,
    DisclosedComp,
    PayBasis,
    extract_grounded_band,
    settle_band,
)
from tracker.pay_period import effective_period
from tracker.settings_store import get_active_prompt_version

logger = logging.getLogger(__name__)


def pay_input_text(job: Job) -> tuple[str, str]:
    """Prefer the pay section a connector carved (`PAY_SECTION_KEY`); the full
    text still grounds the output."""
    for section in job.description_sections or []:
        if not isinstance(section, dict) or section.get("key") != PAY_SECTION_KEY:
            continue
        content = section.get("content")
        if isinstance(content, str) and content.strip():
            return content.strip(), "pay_section"
    return job.description_text or "", "full_description"


def stale_clause(active_version: str):
    """Re-run when never processed, content changed since last pass, or the
    extractor version moved. `content_changed_at` bumps only when title/description
    changed, so this reuses that generic signal without a second content hash.

    Never a row whose band a connector wrote: the text cannot re-derive
    a figure read from a structured field, so a version bump must never hand
    those rows to it."""
    return and_(
        or_(
            Job.structured_at.is_(None),
            Job.content_changed_at > Job.structured_at,
            Job.structured_prompt_version != active_version,
        ),
        Job.disclosed_source.is_distinct_from("connector"),
    )


async def active_parser_version(session: AsyncSession) -> str:
    """The version the text pass stamps and compares: `PAY_PARSER_VERSION`, or
    a pin stored under the task in settings."""
    return await get_active_prompt_version(session, TASK, PAY_PARSER_VERSION)


#: Stamps whose bands the equity residuals read: the current parser's and the
#: last prompt-era stamp, which already derived the stated bonus share (v5).
#: A band stamped by either is one the residuals' guard was written to admit.
LEGACY_BAND_VERSION = "disclosed_comp/v5"


async def residual_band_versions(session: AsyncSession) -> set[str]:
    return {await active_parser_version(session), LEGACY_BAND_VERSION}


#: The band a row's posting page states, as `disclosed_*` columns, or None
#: (`workflows.posting_pages.page_band`). Passed in by the workflow
#: that runs this pass: the page read lives a layer above this one.
PageBand = Callable[[Job], dict | None]


def _settled(
    job: Job, basis: str | None, bounds: list[int | None], span: tuple[int, int] | None = None,
) -> dict:
    """The basis and bonus columns of a band this row states: an unclear band
    takes this role's reading or its stated salary, and the bonus is read
    against that (`pay_disclosure.settle_band`, which every writer of a band asks)."""
    settled = settle_band(basis, job.description_text, job.family, job.title, bounds, span=span)
    return {"disclosed_pay_basis": settled.pay_basis, "disclosed_bonus_pct": settled.bonus_pct}


async def settle_stored_bands(session: AsyncSession, job_ids: list[int]) -> int:
    """Settle stored connector and page bands left `unclear`.

    The text pass never re-reads a connector or page band, so one stored before
    these rules keeps `unclear` until its own source writes it again. This
    applies `settle_band` to it now, the bonus with the basis; text bands are
    settled by their re-read. Returns how many rows changed. Commits nothing."""
    rows = await session.scalars(
        select(Job).where(
            Job.id.in_(job_ids),
            Job.disclosed_pay_basis == PayBasis.unclear.value,
            Job.disclosed_source.in_(("connector", "page")),
        )
    )
    changed = 0
    for job in rows:
        before = (job.disclosed_pay_basis, job.disclosed_bonus_pct)
        for column, value in _settled(
            job, job.disclosed_pay_basis, [job.disclosed_base_min, job.disclosed_base_max],
        ).items():
            setattr(job, column, value)
        changed += (job.disclosed_pay_basis, job.disclosed_bonus_pct) != before
    return changed


def _apply(job: Job, dc: DisclosedComp, page_band: PageBand | None, version: str) -> BandChange | None:
    """Write what the text says, or what the page said when the text says
    nothing, or clear this reader's band. Through `db/pay_band.apply_band`, so
    the stamp, the place key and the precedence are the ones every writer
    keeps, and settled before it is written; returns the change for the
    caller to record. A write precedence refuses leaves the stored band as its
    own source wrote it."""
    place_key = pay_place_key(job.locations)
    if not dc.disclosed and page_band is not None:
        # The text states no band, but the posting page may have: fall back to
        # it rather than erase it. Otherwise a parser-version move or a
        # `--force` backfill would wipe a page band for good, since the page is
        # not owed again until the text changes.
        stated = page_band(job)
        if stated is not None:
            # A band the text stated outranks the page's, so the text withdraws
            # its own first; the gap is then the page's to fill.
            withdrawn = apply_band(
                job, None, source="text", version=version, now=func.now(), place_key=place_key,
            )
            bounds = [stated.get("disclosed_base_min"), stated.get("disclosed_base_max")]
            filled = apply_band(
                job, {**stated, **_settled(job, stated.get("disclosed_pay_basis"), bounds)},
                source="page", version=version, now=func.now(), place_key=place_key,
            )
            if withdrawn is None or filled is None:
                return filled
            return BandChange(before=withdrawn.before, after=filled.after)
    values = {
        "disclosed_base_min": dc.base_min,
        "disclosed_base_max": dc.base_max,
        "disclosed_currency": dc.currency or "USD",
        "disclosed_pay_period": dc.pay_period.value,
        "disclosed_snippet": dc.source_snippet,
        "disclosed_confidence": dc.confidence,
        **_settled(job, dc.pay_basis.value, [dc.base_min, dc.base_max], dc.span),
    } if dc.disclosed else None
    return apply_band(
        job, values, source="text", version=version, now=func.now(), place_key=place_key,
    )


def _mark_processed(job: Job, version: str) -> None:
    job.structured_at = func.now()
    job.structured_prompt_version = version
    job.disclosed_place_key = pay_place_key(job.locations)


async def owed_ids(
    session: AsyncSession, job_ids: list[int], active: str, *, read_before: datetime | None = None
) -> list[int]:
    """Which of `job_ids` the text pass owes a read, newest first.

    Stale by the text or the parser (`stale_clause`), or the place
    the band was chosen for has moved: a text that states one
    band per city is read for the posting's first place, and a listing that
    changes ONLY its place changes no text, so `content_changed_at` never
    moves. A row with no key was read before the key existed and is owed
    once. Read from narrow columns, so the touched set is never loaded whole.

    `read_before` is a forced re-read: also owed, every row the text
    pass last read before that moment. Never a connector's row, as above, and
    nothing is cleared first: a row keeps its band and its stamp until its own
    read replaces them, and a rerun naming the same moment skips what the
    interrupted one finished.
    """
    if not job_ids:
        return []
    forced = (
        or_(Job.structured_at.is_(None), Job.structured_at < read_before)
        if read_before is not None
        else false()
    )
    rows = (
        await session.execute(
            select(
                Job.id, Job.locations, Job.disclosed_place_key,
                stale_clause(active).label("stale"), forced.label("forced"),
            )
            .where(Job.id.in_(job_ids), Job.disclosed_source.is_distinct_from("connector"))
            .order_by(Job.id.desc())
        )
    ).all()
    return [
        r.id
        for r in rows
        if r.stale
        or r.forced
        or r.disclosed_place_key is None
        or r.disclosed_place_key != pay_place_key(r.locations)
    ]


async def backlog_ids(session: AsyncSession, *, limit: int) -> list[int]:
    """Open rows the text pass owes a read, touched or not: in-scope first,
    then oldest first.

    The touched rows go newest first and stop at the cap, and a row is in a
    run's touched set only when that run reaches its post-passes. While runs
    keep bringing more owed rows than the cap, an old one would never be
    reached; a query over the open rows has no such blind spot, and oldest
    first reaches every row in turn. A moved place is not asked here: only a
    scan moves a place, and that scan touches the row."""
    active = await active_parser_version(session)
    return list(
        (
            await session.scalars(
                select(Job.id)
                .where(
                    Job.status == "open",
                    Job.disclosed_source.is_distinct_from("connector"),
                    or_(stale_clause(active), Job.disclosed_place_key.is_(None)),
                )
                .order_by(Job.in_scope.desc(), Job.id)
                .limit(limit)
            )
        ).all()
    )


async def extract_disclosed_comp(
    session: AsyncSession,
    job_ids: list[int],
    *,
    cap: int | None = None,
    page_band: PageBand | None,
    read_before: datetime | None = None,
    run_id: int | None = None,
) -> dict:
    """Extract each owed job's band from its text. `page_band` is required so
    every caller decides what a row falls back to when its text states none;
    None only where no posting page can have been read.

    Writes and never commits: the post pass's loop commits once
    per pass (this pass is capped per run), and the backfill command commits
    each batch it hands over, so an interrupted backfill keeps every finished
    batch and a rerun resumes through `owed_ids`."""
    active = await active_parser_version(session)
    summary = {"processed": 0, "disclosed": 0, "prefiltered": 0}
    if not job_ids:
        return summary

    owed = await owed_ids(session, job_ids, active, read_before=read_before)
    if cap is not None:
        owed = owed[:cap]
    jobs = list(
        (
            await session.scalars(select(Job).where(Job.id.in_(owed)).order_by(Job.id.desc()))
        ).all()
    ) if owed else []

    for job in jobs:
        desc = job.description_text or ""
        input_text, input_scope = pay_input_text(job)

        # Pre-filter: no monetary/salary signal => processed as "none disclosed"
        # without scanning. Kept although scanning is cheap, because it is
        # also what makes "no band" a decision rather than a failed search.
        prefiltered = not has_pay_pattern(input_text)
        band = (
            DisclosedComp(disclosed=False)
            if prefiltered
            # The pay section is what we read; the FULL posting is what grounds
            # the answer, so a band lifted from a section must still appear
            # verbatim in the stored text.
            else extract_grounded_band(
                input_text, desc, place=first_place(job.locations or []), places_in=specific_places,
            )
        )

        if (input_text or desc).strip():
            change = _apply(job, band, page_band, active)
            # A band the employer moved is a fact about THIS posting, so it
            # reaches the history whichever reader saw it move: the connector
            # (`repo.upsert_job`) and the page read
            # (`posting_pages._record_move`) record theirs the same way.
            if change is not None and change.moved and change.had_band:
                session.add(JobLifecycleEvent(
                    job_id=job.id, run_id=run_id, event_type="changed",
                    detail={"disclosed_base": change.event_detail()},
                ))
        else:
            # No text to read at all (a posting whose text went missing after
            # its band was read): nothing is withdrawn on no evidence, but the
            # read is still recorded so the posting is not owed again until
            # text returns and bumps `content_changed_at`.
            _mark_processed(job, active)
        await log_ai_task(
            session,
            task_type=TASK,
            provider=EXTRACTOR,
            availability_state=AvailabilityState.AVAILABLE.value,
            validation_result="ok",
            prompt_version=active,
            model_id=EXTRACTOR_ID,
            job_id=job.id,
            meta={
                "disclosed": band.disclosed,
                "prefiltered": prefiltered,
                "input_chars": len(input_text),
                "input_scope": input_scope,
            },
        )

        summary["processed"] += 1
        if prefiltered:
            summary["prefiltered"] += 1
        if band.disclosed:
            summary["disclosed"] += 1

    logger.info("disclosed-comp extraction: %s", summary)
    return summary


# --------------------------------------------------------------------------- #
# Correcting stored periods
# --------------------------------------------------------------------------- #


def _written_dotted(reread: DisclosedComp) -> bool:
    """Does the re-read's text write both amounts with a dot before the
    thousands ("€104.800—€165.700")? That is the misread the repair is for: a
    salary written with commas whose thousands match a small stored band is
    another band of the same posting."""
    snippet = reread.source_snippet or ""
    return all(
        f"{amount // 1000}.{amount % 1000:03d}" in snippet
        for amount in (reread.base_min, reread.base_max)
        if amount is not None
    )


def corrected_band(
    stored: tuple[int | None, int | None, str | None, str | None],
    reread: DisclosedComp | None,
) -> dict | None:
    """The `disclosed_*` columns to rewrite for one stored band, or None.

    Only a band whose stored period contradicts its amount is touched
    (`effective_period` differs from what is stored), and only with what the
    posting's own text says when read again under the period rule:

    - the re-read finds the SAME amounts: its period replaces the stored one
      (a $600,000 salary stored as hourly);
    - the stored amounts are the re-read's with the thousands dropped, and the
      text writes them with a dot before the thousands, the signature of the
      "€104.800" misread: the amounts are replaced too;
    - anything else (another band in the same posting, such as a second city's
      range, or nothing found): the row is left as it is. A band is never
      removed here; the read-time guard keeps showing it as "could not tell".

    A stored `unclear` is never a candidate: it is what the rule itself writes
    when the words contradict the size, so re-reading it every run could only
    write it again.
    """
    low, high, currency, period = stored
    if effective_period(period, low, high, currency) == period:
        return None
    if reread is None or not reread.disclosed or reread.base_min is None or reread.base_max is None:
        return None
    new_period = reread.pay_period.value
    if (reread.base_min, reread.base_max) == (low, high):
        return {"disclosed_pay_period": new_period} if new_period != period else None
    if low is not None and high is not None and (
        reread.base_min // 1000,
        reread.base_max // 1000,
    ) == (low, high) and _written_dotted(reread):
        return {
            "disclosed_base_min": reread.base_min,
            "disclosed_base_max": reread.base_max,
            "disclosed_pay_period": new_period,
            "disclosed_snippet": reread.source_snippet,
        }
    return None


async def correct_pay_periods(session: AsyncSession) -> dict:
    """Rewrite stored periods the period rule shows to be wrong.

    A stored-field derivation like the role and place backfills: rows the
    scanner will not rewrite keep an old rule's answer forever otherwise.
    The fourth writer of a band (`db/pay_band.py`): it corrects what a source
    stated rather than restating it, so the source keeps the row and only the
    stamp moves.
    Narrow columns first, so the full text is loaded only for
    the rows whose stored period contradicts their amount; once corrected, a
    row stops being a candidate and the pass writes nothing.
    """
    rows = (
        await session.execute(
            select(
                Job.id, Job.disclosed_base_min, Job.disclosed_base_max,
                Job.disclosed_currency, Job.disclosed_pay_period,
            ).where(or_(Job.disclosed_base_min.isnot(None), Job.disclosed_base_max.isnot(None)))
        )
    ).all()
    candidates = [
        row.id for row in rows
        if effective_period(
            row.disclosed_pay_period, row.disclosed_base_min,
            row.disclosed_base_max, row.disclosed_currency,
        ) != row.disclosed_pay_period
    ]
    summary = {"candidates": len(candidates), "relabelled": 0, "amounts_fixed": 0, "kept": 0}
    for start in range(0, len(candidates), 200):
        for job in (await session.scalars(
            select(Job).where(Job.id.in_(candidates[start:start + 200]))
        )).all():
            pay_text, _scope = pay_input_text(job)
            reread = (
                extract_grounded_band(
                    pay_text, job.description_text or pay_text,
                    place=first_place(job.locations or []), places_in=specific_places,
                )
                if pay_text.strip() else None
            )
            change = corrected_band(
                (job.disclosed_base_min, job.disclosed_base_max,
                 job.disclosed_currency, job.disclosed_pay_period),
                reread,
            )
            if change is None:
                summary["kept"] += 1
                continue
            for column, value in change.items():
                setattr(job, column, value)
            # A correction is a rewrite of the figure, so the stamp moves with
            # it: a reader asking when this band was last decided must not be
            # told the moment before it changed. `disclosed_source` stays,
            # because this corrects the band that source stated rather than
            # restating it from somewhere else.
            job.structured_at = func.now()
            summary["amounts_fixed" if "disclosed_base_min" in change else "relabelled"] += 1
    logger.info("pay period correction: %s", summary)
    return summary
