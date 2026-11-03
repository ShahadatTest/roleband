"""Benchmark the relevance review advisory against deterministic ground truth.

Live-model confidence, so it lives here rather than in pytest: live
confidence belongs in smoke commands (`docs/testing.md`). Read-only with respect to
verdicts — nothing here writes `job_relevance_reviews`, `jobs.domains`, or
`in_scope`.

    python -m scripts.bench_relevance_review --builtin       # the shipped anchor classifier
    python -m scripts.bench_relevance_review                 # LLM ladder (comparison mode)
    python -m scripts.bench_relevance_review --per-cohort=10
    python -m scripts.bench_relevance_review --reps 3        # self-consistency (LLM only)

COHORTS — negative controls in BOTH directions. Ground truth comes
from rows the deterministic ladder ALREADY classified from the employer's own
metadata; the prompt never carries that classification (the independence pin in
`test_relevance_review.py`), so the model re-derives it blind:

    classified_tracked    domains intersect the bench's tracked set
                          -> expected `relevant`
    classified_untracked  domains disjoint from the tracked set
                          -> expected `irrelevant`

A model that answers "relevant" every time fails the untracked arm; one that
answers "irrelevant" every time fails the tracked arm. Without both, the
benchmark cannot fail — and a benchmark that cannot fail measures nothing.

DOMAIN ACCURACY is scored separately on every case: the model's `domain` must
be one of the worlds the deterministic ladder assigned. `uncertain` verdicts
count as misses in the cohort score (the advisory exists to resolve exactly
these rows) but are reported on their own line so systematic abstention is
visible rather than buried.

The bench fixes its own tracked-worlds set (`_TRACKED`) instead of reading the
user's: expectations must be deterministic, and the user's scope changes.

Telemetry: every bench case logs `relevance_review_control`, never the real
task — deterministically-labeled controls must not enter the measurement
substrate that routing policy reads for live `relevance_review` traffic.
"""

from __future__ import annotations

import argparse
import asyncio
import collections
import statistics
import time

from sqlalchemy import func, select

from tracker.db.models import Job
from tracker.db.session import session_scope
from tracker.intelligence.relevance_review import (
    INSTRUCTIONS,
    PROMPT_VERSION,
    RELEVANCE_REVIEW_SCHEMA,
    build_relevance_prompt,
    coerce_relevance,
)
from tracker.intelligence_runtime.routing import resolve_provider
from tracker.intelligence_runtime.telemetry import log_ai_task

CONTROL_TASK = "relevance_review_control"

# The bench's fixed tracked-worlds set: tech-platform worlds. Rows classified
# into these read as "relevant"; rows classified only outside read as
# "irrelevant". Fixed here, never read from the user's scope — see docstring.
_TRACKED = frozenset({"ai_ml", "cloud_infra", "developer_platform", "data_analytics"})


async def _cohort_cases(session, per_cohort: int, *, require_embedding: bool = False) -> list[tuple]:
    """(cohort, expected, job). Deterministically-classified rows only."""
    rows = (
        await session.scalars(
            select(Job)
            .where(
                Job.status == "open",
                Job.description_text.is_not(None),
                func.cardinality(Job.domains) >= 1,
                *( [Job.embedding.isnot(None)] if require_embedding else [] ),
            )
            .order_by(Job.id.desc())
            .limit(600)
        )
    ).all()

    tracked, untracked = [], []
    for job in rows:
        domains = list(job.domains or [])
        # Tracked arm: the PRIMARY world (domains[0], company hits first)
        # must be tracked. Any-overlap is too weak a label here — a
        # facilities posting that also matched cloud_infra would count as
        # "expected relevant" and punish the model for reading it correctly.
        if domains and domains[0] in _TRACKED:
            tracked.append(job)
        elif not set(domains) & _TRACKED:
            untracked.append(job)

    cases = [("classified_tracked", "relevant", job) for job in tracked[:per_cohort]]
    cases += [("classified_untracked", "irrelevant", job) for job in untracked[:per_cohort]]
    return cases


async def _one_call(session, provider, case) -> dict:
    cohort, expected, job = case
    started = time.monotonic()
    row = {"cohort": cohort, "expected": expected, "job": job.id,
           "true_domains": sorted(job.domains or [])}

    res = await provider.generate(
        instructions=INSTRUCTIONS,
        prompt=build_relevance_prompt(job, _TRACKED),
        schema=RELEVANCE_REVIEW_SCHEMA,
        budget_tokens=8192,
    )
    elapsed = res.latency_ms or int((time.monotonic() - started) * 1000)

    if res.fields is None:
        row.update(got=f"ERROR:{res.failure_class or 'sdk_error'}", domain=None,
                   confidence=None, latency_ms=elapsed)
        await log_ai_task(
            session, task_type=CONTROL_TASK,
            provider=res.provider_name or provider.name,
            availability_state=res.availability_state.value,
            validation_result="invalid", failure_class=res.failure_class or "sdk_error",
            latency_ms=elapsed, prompt_version=PROMPT_VERSION, job_id=job.id,
        )
        await session.commit()
        return row

    try:
        assessment = coerce_relevance(res.fields)
    except ValueError:
        row.update(got="ERROR:validation", domain=None, confidence=None,
                   latency_ms=elapsed)
        await log_ai_task(
            session, task_type=CONTROL_TASK,
            provider=res.provider_name or provider.name,
            availability_state=res.availability_state.value,
            validation_result="invalid", failure_class="validation",
            latency_ms=elapsed, prompt_version=PROMPT_VERSION, job_id=job.id,
        )
        await session.commit()
        return row

    row.update(
        got=assessment.relevance,
        domain=assessment.domain,
        domain_hit=assessment.domain in (job.domains or []),
        confidence=assessment.confidence,
        latency_ms=elapsed,
        rationale=assessment.rationale[:100],
    )
    await log_ai_task(
        session, task_type=CONTROL_TASK,
        provider=res.provider_name or provider.name,
        availability_state=res.availability_state.value,
        validation_result="ok", latency_ms=elapsed,
        input_tokens=res.input_tokens, output_tokens=res.output_tokens,
        prompt_version=PROMPT_VERSION, job_id=job.id,
        meta={"relevance": assessment.relevance, "domain": assessment.domain},
    )
    await session.commit()
    return row


def _report(results: list[dict], reps: int) -> None:
    print("\n================ RESULTS ================")
    by_cohort: dict[str, list[dict]] = collections.defaultdict(list)
    for row in results:
        by_cohort[row["cohort"]].append(row)

    for cohort, rows in sorted(by_cohort.items()):
        hits = sum(1 for r in rows if r["got"] == r["expected"])
        print(f"\n{cohort}: {hits}/{len(rows)}")
        for row in rows:
            mark = "OK " if row["got"] == row["expected"] else "MISS"
            print(f"  {mark} job={row['job']:<5} true={','.join(row['true_domains'])[:40]:<40} "
                  f"-> {row['got']}/{row.get('domain')} (conf {row.get('confidence')})")

    print("\n--- both directions (the falsifiability requirement) ---")
    for cohort in ("classified_tracked", "classified_untracked"):
        rows = by_cohort.get(cohort, [])
        if rows:
            hits = sum(1 for r in rows if r["got"] == r["expected"])
            print(f"  {cohort:<22}: {hits}/{len(rows)}")

    judged = [r for r in results if not str(r["got"]).startswith("ERROR:")]
    domain_scored = [r for r in judged if r.get("domain") is not None]
    if domain_scored:
        hits = sum(1 for r in domain_scored if r.get("domain_hit"))
        print(f"  domain accuracy (named) : {hits}/{len(domain_scored)}")
    abstained = [r for r in judged if r["got"] == "uncertain"]
    if abstained:
        print(f"  uncertain verdicts      : {len(abstained)}/{len(judged)}")
    # Internal coherence: a verdict that names an untracked world but says
    # "relevant" (or vice versa) contradicts itself regardless of ground truth.
    incoherent = [
        r for r in judged
        if r.get("domain") is not None and r["got"] != "uncertain"
        and (r["got"] == "relevant") != (r["domain"] in _TRACKED)
    ]
    if judged:
        print(f"  incoherent verdicts     : {len(incoherent)}/{len(judged)} "
              "(named world contradicts the relevance verdict)")

    latencies = sorted(r["latency_ms"] for r in results if r.get("latency_ms"))
    if latencies:
        print(f"\nlatency_ms p50={statistics.median(latencies):.0f} "
              f"min={min(latencies)} max={max(latencies)}")
    print(f"verdicts: {dict(collections.Counter(r['got'] for r in results))}")
    wrong = [r["confidence"] for r in results
             if r["got"] != r["expected"] and isinstance(r.get("confidence"), (int, float))]
    if wrong:
        print(f"confidence on WRONG answers p50={statistics.median(wrong):.2f}")
    errors = [r for r in results if str(r["got"]).startswith("ERROR:")]
    if errors:
        print(f"hard failures: {len(errors)}/{len(results)}")
    if reps > 1:
        by_case: dict[tuple, set] = collections.defaultdict(set)
        for row in results:
            by_case[(row["cohort"], row["job"])].add(row["got"])
        unstable = sum(1 for verdicts in by_case.values() if len(verdicts) > 1)
        print(f"unstable cases (verdict changed across {reps} reps): {unstable}/{len(by_case)}")


def _one_builtin(case) -> dict:
    """Anchor-classifier arm: same cohorts, same report, no model call and no
    telemetry (nothing here may enter the routing measurement substrate)."""
    from tracker.semantic import anchors

    cohort, expected, job = case
    started = time.monotonic()
    row = {"cohort": cohort, "expected": expected, "job": job.id,
           "true_domains": sorted(job.domains or [])}
    try:
        assessment = anchors.classify_embedding(list(job.embedding), _TRACKED)
    except ValueError as exc:
        row.update(got=f"ERROR:{exc}", domain=None, confidence=None,
                   latency_ms=int((time.monotonic() - started) * 1000))
        return row
    row.update(
        got=assessment.relevance,
        domain=assessment.domain,
        domain_hit=assessment.domain in (job.domains or []),
        confidence=assessment.confidence,
        latency_ms=int((time.monotonic() - started) * 1000),
        rationale=assessment.rationale[:100],
    )
    return row


async def run_builtin(*, per_cohort: int) -> None:
    from tracker.semantic import anchors

    async with session_scope() as session:
        cases = await _cohort_cases(session, per_cohort, require_embedding=True)
    if not cases:
        print("No deterministically-classified, embedded rows to benchmark against.")
        return
    anchors.anchor_matrix()  # load once, outside the timed loop
    cohorts = collections.Counter(c[0] for c in cases)
    print(f"provider=builtin (anchors)  cases={len(cases)}")
    for cohort, count in sorted(cohorts.items()):
        print(f"   {cohort}: {count}")
    print()
    results = []
    for index, case in enumerate(cases, 1):
        row = _one_builtin(case)
        results.append(row)
        print(f"  [{index}/{len(cases)}] {row['cohort']:<22} "
              f"expect={row['expected']:<10} got={row['got']:<12} "
              f"domain={row.get('domain')} {row['latency_ms']}ms", flush=True)
    _report(results, reps=1)


async def run(*, per_cohort: int, reps: int) -> None:
    async with session_scope() as session:
        provider = await resolve_provider(session, task_type=CONTROL_TASK)
        avail = await provider.availability()
        if not avail.ok:
            print(f"No usable model backend ({avail.state.value}). "
                  "Configure one in Settings / Intelligence.")
            return
        cases = await _cohort_cases(session, per_cohort)

    if not cases:
        print("No deterministically-classified rows to benchmark against.")
        return
    cohorts = collections.Counter(c[0] for c in cases)
    if len(cohorts) < 2:
        print(f"WARNING: only one cohort present ({dict(cohorts)}) — this run "
              "cannot fail in both directions and measures less than it should.")

    print(f"provider={provider.name}  cases={len(cases)}  reps={reps}")
    for cohort, count in sorted(cohorts.items()):
        print(f"   {cohort}: {count}")
    print()

    results = []
    async with session_scope() as session:
        for rep in range(reps):
            for index, case in enumerate(cases, 1):
                row = await _one_call(session, provider, case)
                results.append(row)
                tag = f"r{rep + 1} " if reps > 1 else ""
                print(f"  {tag}[{index}/{len(cases)}] {row['cohort']:<22} "
                      f"expect={row['expected']:<10} got={row['got']:<12} "
                      f"domain={row.get('domain')} {row['latency_ms']}ms", flush=True)
    _report(results, reps)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--per-cohort", type=int, default=6,
                        help="cases per direction (both arms are required for falsifiability)")
    parser.add_argument("--reps", type=int, default=1, help="repeats, for self-consistency")
    parser.add_argument("--builtin", action="store_true",
                        help="bench the shipped anchor classifier instead of the LLM ladder")
    args = parser.parse_args()
    if args.builtin:
        asyncio.run(run_builtin(per_cohort=args.per_cohort))
    else:
        asyncio.run(run(per_cohort=args.per_cohort, reps=args.reps))


if __name__ == "__main__":
    main()
