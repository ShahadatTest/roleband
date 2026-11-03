"""Persistence half of per-binding learned bounds.

`workflows/tuning.py` owns the policy and is pure. This module is the only
place that reads a run's observations and writes `source_binding_tuning`, and
it runs as a `POST_PASSES` entry so a scrape maintains its own bounds, never a
CLI-only producer, the bug class `db/ownership.py` exists to
prevent.

**Which runs are allowed to teach.** Only a source that actually enumerated its
board on its own terms:

* not capped — the pass is registered `capped_ok=False`, so `--max-list` never
  reaches here at all;
* no errors and not blocked — a source that half-refused paged fewer pages for
  reasons that say nothing about the board's size, and learning from it would
  ratchet a bound down toward a failure;
* not `bounded` — our time ceiling cut it mid-listing, so its page counts are
  censored by *us*. A bounded run teaches one thing only: the learned time
  budget that cut it was too low, so that budget is multiplied
  (`tuning.escalate_budget`) and nothing of the run is folded in;
* not `suspended` — our host slept mid-listing, censoring the page counts the
  same way. Excluded explicitly rather than left to the `errors` clause, which
  covers it only because a suspension usually kills a socket: a sleep that lands
  in a pacing gap instead ends the run short with no error at all, and that run
  would otherwise teach a bound down toward a night the machine was asleep.

A `truncated` run is deliberately still allowed in, and is the important case:
it is the evidence that a bound was too low. Its page count is censored, which
is exactly why the policy escalates from the *bound* rather than fitting to the
sample.
"""

from __future__ import annotations

import logging
from statistics import median

from sqlalchemy import func, select

from tracker.config import Settings
from tracker.db.models import Job, SourceBinding, SourceBindingTuning
from tracker.platform.paging import QueryObservation, StopReason
from tracker.workflows.collection_types import SourceCost
from tracker.workflows.tuning import TuningPolicy, TuningState, escalate_budget, next_tuning

logger = logging.getLogger(__name__)

__all__ = [
    "SOURCE_LEVEL_KEY",
    "budget_cut",
    "is_teachable",
    "learn_bounds",
    "load_page_budgets",
    "load_source_budgets",
    "load_source_costs",
    "policy_from_settings",
]

#: Reserved `query_key` for the source-level row, where the time budget lives.
#: A real query key is a location term / facet name / board site, so `*` cannot
#: collide with one.
SOURCE_LEVEL_KEY = "*"


def policy_from_settings(settings: Settings) -> TuningPolicy:
    return TuningPolicy(
        headroom=settings.scraper_tuning_headroom,
        escalate=settings.scraper_tuning_escalate,
        decay=settings.scraper_tuning_decay,
        samples=settings.scraper_tuning_samples,
        # The operator's global budget is the hard ceiling a learned budget may
        # never exceed. Auto-tuning that can raise its own ceiling is not a bound.
        budget_ceiling_seconds=float(settings.scraper_source_budget_seconds),
    )


def is_teachable(stats: dict) -> bool:
    """Whether one source's run is evidence about the size of its board."""
    return not (
        stats.get("errors")
        or stats.get("blocked")
        or stats.get("capped")
        or stats.get("bounded")
        or stats.get("suspended")
    )


async def load_page_budgets(session, company_slugs) -> dict[str, dict[str, int]]:
    """`company -> {query_key: tuned_max_pages}` for the active bindings.

    Read once before collection and handed to each adapter, so the hot path
    never queries per query. A company with no row simply gets none, and its
    adapter falls back to its seed constant — tuning must be additive, or the
    first run after adding a company would behave differently from every later
    one.
    """
    slugs = list(company_slugs)
    if not slugs:
        return {}
    rows = (
        await session.execute(
            select(SourceBinding.company_slug, SourceBindingTuning.query_key,
                   SourceBindingTuning.tuned_max_pages)
            .join(SourceBindingTuning, SourceBindingTuning.binding_id == SourceBinding.id)
            .where(
                SourceBinding.company_slug.in_(slugs),
                SourceBinding.status == "stable",
                SourceBindingTuning.tuned_max_pages.is_not(None),
            )
        )
    ).all()
    budgets: dict[str, dict[str, int]] = {}
    for slug, query_key, tuned in rows:
        if query_key == SOURCE_LEVEL_KEY:
            continue  # the source-level row carries the time budget, not pages
        budgets.setdefault(slug, {})[query_key] = int(tuned)
    return budgets


async def load_source_budgets(session, company_slugs) -> dict[str, float]:
    """`company -> tuned_budget_seconds` from each binding's source-level row."""
    slugs = list(company_slugs)
    if not slugs:
        return {}
    rows = (
        await session.execute(
            select(SourceBinding.company_slug, SourceBindingTuning.tuned_budget_seconds)
            .join(SourceBindingTuning, SourceBindingTuning.binding_id == SourceBinding.id)
            .where(
                SourceBinding.company_slug.in_(slugs),
                SourceBinding.status == "stable",
                SourceBindingTuning.query_key == SOURCE_LEVEL_KEY,
                SourceBindingTuning.tuned_budget_seconds.is_not(None),
            )
        )
    ).all()
    return {slug: float(budget) for slug, budget in rows}


async def load_source_costs(session, company_slugs) -> dict[str, SourceCost]:
    """`company -> SourceCost`: learned scan time and the postings it holds.

    Read once per run, for ORDER only (`collection.collector_lanes`): the
    median of the source-level scan times the tuner kept, and the open
    in-scope postings each company holds now. A company with no learned time
    is absent, and keeps its place.
    """
    slugs = list(company_slugs)
    if not slugs:
        return {}
    samples = (
        await session.execute(
            select(SourceBinding.company_slug, SourceBindingTuning.duration_samples)
            .join(SourceBindingTuning, SourceBindingTuning.binding_id == SourceBinding.id)
            .where(
                SourceBinding.company_slug.in_(slugs),
                SourceBinding.status == "stable",
                SourceBindingTuning.query_key == SOURCE_LEVEL_KEY,
            )
        )
    ).all()
    held = dict(
        (
            await session.execute(
                select(Job.company, func.count())
                .where(Job.company.in_(slugs), Job.status == "open", Job.in_scope.is_(True))
                .group_by(Job.company)
            )
        ).all()
    )
    return {
        slug: SourceCost(seconds=float(median(values)), kept=int(held.get(slug, 0)))
        for slug, values in samples
        if values
    }


def _state_from_row(row: SourceBindingTuning) -> TuningState:
    return TuningState(
        query_key=row.query_key,
        page_samples=tuple(int(v) for v in (row.page_samples or [])),
        duration_samples=tuple(float(v) for v in (row.duration_samples or [])),
        declared_total_last=row.declared_total_last,
        saturated=bool(row.saturated),
        stop_reason_hist=dict(row.stop_reason_hist or {}),
        tuned_max_pages=row.tuned_max_pages,
        tuned_budget_seconds=row.tuned_budget_seconds,
    )


def _apply(row: SourceBindingTuning, state: TuningState) -> None:
    row.page_samples = list(state.page_samples)
    row.duration_samples = list(state.duration_samples)
    row.declared_total_last = state.declared_total_last
    row.saturated = state.saturated
    row.stop_reason_hist = dict(state.stop_reason_hist)
    row.tuned_max_pages = state.tuned_max_pages
    row.tuned_budget_seconds = state.tuned_budget_seconds


async def learn_bounds(session, per_source: dict, settings: Settings) -> dict:
    """Fold this run's per-query observations into every teachable binding.

    Returns a small summary for the pass results (and therefore for
    `derivation_state`), so a pass that ran but taught nothing is
    distinguishable from one that never ran.
    """
    policy = policy_from_settings(settings)
    teachable = {c: s for c, s in per_source.items() if is_teachable(s) and s.get("queries")}
    cut = [c for c, s in per_source.items() if budget_cut(s)]
    escalated = await _escalate_cut_budgets(session, cut, policy) if cut else 0
    if not teachable:
        return {"bindings": 0, "queries": 0, "skipped": len(per_source), "budgets_raised": escalated}

    bindings = {
        row.company_slug: row
        for row in (
            await session.execute(
                select(SourceBinding).where(
                    SourceBinding.company_slug.in_(list(teachable)),
                    SourceBinding.status == "stable",
                )
            )
        ).scalars()
    }

    existing = {
        (row.binding_id, row.query_key): row
        for row in (
            await session.execute(
                select(SourceBindingTuning).where(
                    SourceBindingTuning.binding_id.in_([b.id for b in bindings.values()] or [-1])
                )
            )
        ).scalars()
    }

    touched_bindings = 0
    touched_queries = 0
    for company, stats in teachable.items():
        binding = bindings.get(company)
        if binding is None:
            # No stable binding yet (a company added this run). Nothing to key
            # tuning to; the next run seeds it.
            continue
        touched_bindings += 1
        observations = [_observation(o) for o in stats["queries"]]

        for observation in observations:
            row = existing.get((binding.id, observation.query_key))
            if row is None:
                row = SourceBindingTuning(
                    binding_id=binding.id, query_key=observation.query_key
                )
                session.add(row)
                existing[(binding.id, observation.query_key)] = row
            _apply(row, next_tuning(_state_from_row(row), observation, policy=policy))
            touched_queries += 1

        # The source-level row: one duration sample per run, and a page
        # observation aggregated across queries so the row is never empty.
        # `max` rather than sum — the bound it would inform is per query.
        source_row = existing.get((binding.id, SOURCE_LEVEL_KEY))
        if source_row is None:
            source_row = SourceBindingTuning(
                binding_id=binding.id, query_key=SOURCE_LEVEL_KEY
            )
            session.add(source_row)
            existing[(binding.id, SOURCE_LEVEL_KEY)] = source_row
        widest = max(observations, key=lambda o: o.pages_used)
        _apply(
            source_row,
            next_tuning(
                _state_from_row(source_row),
                QueryObservation(
                    query_key=SOURCE_LEVEL_KEY,
                    pages_used=widest.pages_used,
                    items=sum(o.items for o in observations),
                    stop_reason=widest.stop_reason,
                    ceiling=widest.ceiling,
                ),
                duration_seconds=stats.get("duration_seconds"),
                policy=policy,
            ),
        )

    logger.info(
        "tuning: %s bindings, %s queries (%s sources not teachable)",
        touched_bindings,
        touched_queries,
        len(per_source) - len(teachable),
    )
    return {
        "bindings": touched_bindings,
        "queries": touched_queries,
        "skipped": len(per_source) - len(teachable),
        "budgets_raised": escalated,
    }


def budget_cut(stats: dict) -> bool:
    """Whether our time budget, and nothing else, ended this source's read.

    An error, a block, a cap or a host sleep explains a short read on its own,
    so none of them is evidence that the budget was too low."""
    return bool(stats.get("bounded")) and not (
        stats.get("errors") or stats.get("blocked") or stats.get("capped") or stats.get("suspended")
    )


async def _escalate_cut_budgets(session, companies: list[str], policy) -> int:
    """Multiply each cut source's learned budget (its source-level row)."""
    rows = list(
        (
            await session.execute(
                select(SourceBindingTuning)
                .join(SourceBinding, SourceBindingTuning.binding_id == SourceBinding.id)
                .where(
                    SourceBinding.company_slug.in_(companies),
                    SourceBinding.status == "stable",
                    SourceBindingTuning.query_key == SOURCE_LEVEL_KEY,
                )
            )
        ).scalars()
    )
    raised = 0
    for row in rows:
        before = row.tuned_budget_seconds
        _apply(row, escalate_budget(_state_from_row(row), policy))
        raised += int(row.tuned_budget_seconds != before)
    if raised:
        logger.info("tuning: raised %s learned time budgets cut by their own bound", raised)
    return raised


def _observation(raw: dict) -> QueryObservation:
    """Rebuild an observation from the plain dict the stats blob carries."""
    return QueryObservation(
        query_key=raw["query_key"],
        pages_used=int(raw["pages_used"]),
        items=int(raw["items"]),
        stop_reason=StopReason(raw["stop_reason"]),
        ceiling=int(raw["ceiling"]),
        declared_total=raw.get("declared_total"),
        page_size=raw.get("page_size"),
    )
