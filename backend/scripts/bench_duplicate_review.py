"""Benchmark the duplicate review advisory against human verdicts.

Live-model confidence, so it lives here rather than in pytest: live
confidence belongs in smoke commands (`docs/testing.md`). Read-only with respect to
verdicts — the advisory never writes `JobLineageLink.status` /
`JobTwinLink.status`, and neither does this.

    python -m scripts.bench_duplicate_review              # full cohort set
    python -m scripts.bench_duplicate_review --synthetic 0
    python -m scripts.bench_duplicate_review --reps 3     # self-consistency

COHORTS. The real candidates are all near-identical by construction — the
detector only proposes pairs scoring ~0.97+ — so a model that answered
"confirmed" every time would look strong on them alone. The synthetic negatives
are unrelated cross-company postings the detector would never propose; without
that arm the benchmark cannot fail, which is the whole point of including it.

GROUND TRUTH. A confirmed lineage link is "same opening" -> `confirmed`. A
rejected one is "not the same opening" -> `rejected`. A confirmed TWIN is
"twin openings", i.e. separate roles, so under the duplicate prompt its correct
answer is also `rejected`.

Telemetry: real candidates log `duplicate_review`, synthetic controls log
`duplicate_review_control`, so synthetic pairs never enter the measurement
substrate that routing policy reads.
"""

from __future__ import annotations

import argparse
import asyncio
import collections
import statistics
import time
from types import SimpleNamespace

from sqlalchemy import select

from tracker.db.models import Job, JobLineageLink, JobTwinLink
from tracker.db.session import session_scope
from tracker.intelligence.duplicate_review import PROMPT_VERSION, assess_duplicate
from tracker.intelligence_runtime.local_profiles import get_active_profile
from tracker.intelligence_runtime.telemetry import log_ai_task
from tracker.local_llm.client import LocalLLMClient, LocalLLMError

CONTROL_TASK = "duplicate_review_control"
REAL_TASK = "duplicate_review"


async def _pair_cases(session) -> list[tuple]:
    """(cohort, expected, link, prior, newer, is_control)."""
    cases: list[tuple] = []

    for link in (
        await session.scalars(
            select(JobLineageLink).where(
                JobLineageLink.status.in_(("confirmed", "rejected"))
            )
        )
    ).all():
        prior = await session.get(Job, link.prior_job_id)
        newer = await session.get(Job, link.job_id)
        if prior and newer:
            cases.append((f"lineage_{link.status}", link.status, link, prior, newer, False))

    for twin in (
        await session.scalars(select(JobTwinLink).where(JobTwinLink.status == "confirmed"))
    ).all():
        a = await session.get(Job, twin.job_a_id)
        b = await session.get(Job, twin.job_b_id)
        if a and b:
            link = SimpleNamespace(
                id=twin.id, relation="twin", method=twin.method,
                score=twin.score, gap_days=None, evidence=twin.evidence,
            )
            cases.append(("twin_confirmed", "rejected", link, a, b, False))
    return cases


async def _synthetic_cases(session, count: int) -> list[tuple]:
    """Unrelated cross-company pairs. The falsifiability arm."""
    if count <= 0:
        return []
    jobs = (
        await session.scalars(
            select(Job)
            .where(Job.description_text.is_not(None), Job.status == "open")
            .order_by(Job.id.desc())
            .limit(400)
        )
    ).all()
    by_company: dict[str, list[Job]] = collections.defaultdict(list)
    for job in jobs:
        by_company[job.company].append(job)

    companies = sorted(by_company)
    pairs: list[tuple[Job, Job]] = []
    for i in range(len(companies)):
        for k in range(i + 1, len(companies)):
            a, b = by_company[companies[i]][0], by_company[companies[k]][0]
            if (a.family or "") != (b.family or ""):
                pairs.append((a, b))

    out = []
    for index, (a, b) in enumerate(pairs[:count]):
        link = SimpleNamespace(
            id=-(index + 1), relation="duplicate", method="synthetic_control",
            score=None, gap_days=None, evidence={"reasons": []},
        )
        out.append(("synthetic_negative", "rejected", link, a, b, True))
    return out


async def _one_call(session, profile, case) -> dict:
    cohort, expected, link, prior, newer, control = case
    task = CONTROL_TASK if control else REAL_TASK
    started = time.monotonic()
    row = {"cohort": cohort, "expected": expected, "link": link.id,
           "pair": (prior.id, newer.id)}
    try:
        result = await assess_duplicate(LocalLLMClient(profile), link, prior, newer)
    except LocalLLMError as exc:
        elapsed = int((time.monotonic() - started) * 1000)
        row.update(got=f"ERROR:{exc.failure_class}", confidence=None, latency_ms=elapsed)
        await log_ai_task(
            session, task_type=task, provider=profile.provider,
            availability_state="available", validation_result="invalid",
            failure_class=exc.failure_class, latency_ms=elapsed,
            prompt_version=PROMPT_VERSION, model_id=profile.model[:64],
            job_id=newer.id, meta={"link_id": link.id},
        )
        await session.commit()
        return row

    assessment, metrics = result["assessment"], result["metrics"]
    row.update(
        got=assessment["recommendation"],
        confidence=assessment["confidence"],
        latency_ms=metrics.get("wall_time_ms") or int((time.monotonic() - started) * 1000),
        prompt_tokens=metrics.get("prompt_tokens"),
        completion_tokens=metrics.get("completion_tokens"),
        summary=assessment["summary"][:100],
    )
    await log_ai_task(
        session, task_type=task, provider=profile.provider,
        availability_state="available", validation_result="ok",
        latency_ms=row["latency_ms"], input_tokens=row["prompt_tokens"],
        output_tokens=row["completion_tokens"], prompt_version=PROMPT_VERSION,
        model_id=profile.model[:64], job_id=newer.id,
        meta={"link_id": link.id, "recommendation": row["got"]},
    )
    await session.commit()
    return row


def _report(results: list[dict], reps: int) -> None:
    print("\n================ RESULTS ================")
    by_cohort: dict[str, list[dict]] = collections.defaultdict(list)
    for row in results:
        by_cohort[row["cohort"]].append(row)

    real_hits = real_total = 0
    for cohort, rows in sorted(by_cohort.items()):
        hits = sum(1 for r in rows if r["got"] == r["expected"])
        print(f"\n{cohort}: {hits}/{len(rows)}")
        if cohort != "synthetic_negative":
            real_hits, real_total = real_hits + hits, real_total + len(rows)
        for row in rows:
            mark = "OK " if row["got"] == row["expected"] else "MISS"
            print(f"  {mark} link={row['link']:<5} pair={row['pair']} -> "
                  f"{row['got']} (conf {row.get('confidence')})")

    print("\n--- what the advisory is for ---")
    print(f"  real human-adjudicated pairs : {real_hits}/{real_total}")
    synthetic = by_cohort.get("synthetic_negative", [])
    if synthetic:
        hits = sum(1 for r in synthetic if r["got"] == r["expected"])
        print(f"  synthetic obvious negatives : {hits}/{len(synthetic)}")

    latencies = sorted(r["latency_ms"] for r in results if r.get("latency_ms"))
    if latencies:
        print(f"\nlatency_ms p50={statistics.median(latencies):.0f} "
              f"min={min(latencies)} max={max(latencies)}")
    print(f"recommendations: {dict(collections.Counter(r['got'] for r in results))}")
    confidences = [r["confidence"] for r in results if isinstance(r.get("confidence"), (int, float))]
    if confidences:
        wrong = [r["confidence"] for r in results
                 if r["got"] != r["expected"] and isinstance(r.get("confidence"), (int, float))]
        print(f"confidence: all p50={statistics.median(confidences):.2f}"
              + (f"  on WRONG answers p50={statistics.median(wrong):.2f}" if wrong else ""))
    errors = [r for r in results if str(r["got"]).startswith("ERROR:")]
    if errors:
        print(f"hard failures: {len(errors)}/{len(results)}")
    if reps > 1:
        unstable = 0
        by_case: dict[tuple, set] = collections.defaultdict(set)
        for row in results:
            by_case[(row["cohort"], row["link"])].add(row["got"])
        for verdicts in by_case.values():
            if len(verdicts) > 1:
                unstable += 1
        print(f"unstable cases (verdict changed across {reps} reps): {unstable}/{len(by_case)}")


async def run(*, synthetic: int, reps: int, limit: int | None) -> None:
    async with session_scope() as session:
        profile = await get_active_profile(session)
        if profile is None:
            print("No active local model profile. Add one in Settings / Intelligence.")
            return
        cases = await _pair_cases(session)
        cases += await _synthetic_cases(session, synthetic)

    if limit:
        cases = cases[:limit]
    if not cases:
        print("No human-adjudicated links to benchmark against.")
        return

    print(f"model={profile.model}  cases={len(cases)}  reps={reps}")
    for cohort in sorted({c[0] for c in cases}):
        print(f"   {cohort}: {sum(1 for c in cases if c[0] == cohort)}")
    print()

    results = []
    async with session_scope() as session:
        for rep in range(reps):
            for index, case in enumerate(cases, 1):
                row = await _one_call(session, profile, case)
                results.append(row)
                tag = f"r{rep + 1} " if reps > 1 else ""
                print(f"  {tag}[{index}/{len(cases)}] {row['cohort']:<20} "
                      f"expect={row['expected']:<9} got={row['got']:<10} "
                      f"conf={row.get('confidence')} {row['latency_ms']}ms", flush=True)
    _report(results, reps)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--synthetic", type=int, default=6,
                        help="unrelated control pairs (0 disables the falsifiability arm)")
    parser.add_argument("--reps", type=int, default=1, help="repeats, for self-consistency")
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()
    asyncio.run(run(synthetic=args.synthetic, reps=args.reps, limit=args.limit))


if __name__ == "__main__":
    main()
