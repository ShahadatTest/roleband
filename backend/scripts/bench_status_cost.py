"""What run history costs `/api/status`.

`/api/status` reads every followed company's active binding with what its runs
say (`binding_attention.followed_bindings`): per binding the last full scan,
the last attempt, the cause of a gap, the newest outcome, the empty streak and
the last listed count, each a subquery over `scrape_source_runs`. That table
is append-only, so the history each subquery reads grows with every scan. The
live database answers at its own depth only, so this measures deeper ones.

This seeds a scratch database on the same server (`roleband_bench_status_<pid>`,
schema from the models, dropped at the end; the live database is never opened)
with N followed companies, one binding each, and a growing number of runs per
binding in the live mix (about 3 in 4 reconciles; ok, lossy, failed, degraded
and empty outcomes). At each depth it times `followed_bindings` itself without
and with `ix_scrape_source_runs_binding_started`; `--explain` prints the
slowest per-binding plan nodes at the last depth.

What dominates as history deepens is the gap lateral's anti-join; the gap is
written as one bound per binding, and the index keeps the per-binding reads
flat, so a regression in either shows here first.

    .venv/bin/python -m scripts.bench_status_cost
    .venv/bin/python -m scripts.bench_status_cost --bindings 1000 --depths 6 50 200 400
"""

from __future__ import annotations

import argparse
import asyncio
import os
import statistics
import time
from datetime import UTC, datetime, timedelta

from sqlalchemy import text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

DB_NAME = f"roleband_bench_status_{os.getpid()}"
INDEX = "ix_scrape_source_runs_binding_started"  # the model's own
START = datetime(2026, 1, 1, tzinfo=UTC)

# One run in four is a discovery read, the usual mix; the outcome
# is spread by a fixed hash so every depth sees the same mix.
_SOURCE_RUNS = """
INSERT INTO scrape_source_runs (run_id, binding_id, company_slug, provider_key, scan_mode,
    outcome, started_at, finished_at, scanned, kept, jobs_new, jobs_closed, list_complete,
    closure_eligible, errors, drift, stats)
SELECT r.id, b.id, b.company_slug, 'greenhouse',
    CASE WHEN r.id % 4 = 0 THEN 'discovery' ELSE 'reconcile' END,
    CASE WHEN (b.id * 7 + r.id) % 29 = 0 THEN 'failed'
         WHEN (b.id * 5 + r.id) % 19 = 0 THEN 'lossy'
         WHEN (b.id * 3 + r.id) % 47 = 0 THEN 'degraded'
         WHEN (b.id * 11 + r.id) % 97 = 0 THEN 'empty'
         ELSE 'ok' END,
    r.started_at + (b.id % 600) * interval '1 second',
    r.started_at + (b.id % 600) * interval '1 second' + interval '40 seconds',
    40, 40, 0, 0, true, true, '[]'::jsonb, '[]'::jsonb, '{}'::jsonb
FROM scrape_runs r CROSS JOIN source_bindings b
WHERE r.id > :after
"""


def _scratch(base: URL) -> URL:
    if not DB_NAME.startswith("roleband_bench_"):
        raise SystemExit("refusing: the bench writes only to a roleband_bench_ database")
    return base.set(database=DB_NAME)


async def _admin(base: URL, sql: str) -> None:
    admin = create_async_engine(base.set(database="postgres"), isolation_level="AUTOCOMMIT")
    try:
        async with admin.connect() as conn:
            await conn.execute(text(sql))
    finally:
        await admin.dispose()


async def _create(base: URL) -> AsyncEngine:
    from tracker.db.models import Base

    await _admin(base, f'DROP DATABASE IF EXISTS "{DB_NAME}" WITH (FORCE)')
    await _admin(base, f'CREATE DATABASE "{DB_NAME}"')
    engine = create_async_engine(_scratch(base))
    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
        await conn.run_sync(Base.metadata.create_all)
    return engine


async def _seed_companies(engine: AsyncEngine, n: int) -> None:
    from tracker.db.models import SourceBinding, TrackedCompany

    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        session.add_all(
            TrackedCompany(slug=f"bench-{i:04d}", display=f"Bench {i}", adapter="greenhouse",
                           status="active", enabled=True)
            for i in range(n)
        )
        await session.flush()
        session.add_all(
            SourceBinding(company_slug=f"bench-{i:04d}", connector_kind="adapter",
                          connector_id="greenhouse", status="stable")
            for i in range(n)
        )
        await session.commit()


async def _grow(engine: AsyncEngine, have: int, want: int) -> None:
    """Add runs until every binding has `want` (one source run per binding per run)."""
    from tracker.db.models import ScrapeRun

    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        last = (await session.execute(text("SELECT coalesce(max(id), 0) FROM scrape_runs"))).scalar_one()
        session.add_all(
            ScrapeRun(started_at=START + timedelta(hours=8 * k), status="ok")
            for k in range(have, want)
        )
        await session.flush()
        await session.execute(text(_SOURCE_RUNS), {"after": last})
        await session.commit()
    async with engine.connect() as conn:
        await (await conn.execution_options(isolation_level="AUTOCOMMIT")).execute(
            text("VACUUM ANALYZE scrape_source_runs")
        )


async def _time(engine: AsyncEngine, repeat: int) -> tuple[float, float, int]:
    from tracker.db.queries.binding_attention import followed_bindings

    factory = async_sessionmaker(engine, expire_on_commit=False)
    times: list[float] = []
    rows = 0
    for i in range(repeat + 2):  # two warm-ups
        async with factory() as session:
            started = time.perf_counter()
            rows = len(await followed_bindings(session, automatic=lambda *_: True))
            elapsed = (time.perf_counter() - started) * 1000
        if i >= 2:
            times.append(elapsed)
    return statistics.median(times), max(times), rows


def _statement() -> str:
    """`followed_bindings`'s own statement, compiled for EXPLAIN."""
    from sqlalchemy.dialects import postgresql

    from tracker.db.queries.binding_attention import followed_bindings

    captured: list = []

    class _Capture:
        async def execute(self, stmt):
            captured.append(stmt)

            class _Empty:
                def all(self):
                    return []

            return _Empty()

    asyncio.run(followed_bindings(_Capture(), automatic=lambda *_: True))  # type: ignore[arg-type]
    return str(captured[0].compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))


async def _explain(engine: AsyncEngine, sql: str) -> None:
    """The plan's nodes that run once per binding, with their total time."""
    async with engine.connect() as conn:
        plan = (await conn.execute(text("EXPLAIN (ANALYZE, FORMAT JSON) " + sql))).scalar_one()
    rows: list[tuple[float, str]] = []

    def walk(node: dict, depth: int) -> None:
        loops = node.get("Actual Loops", 0)
        total = node.get("Actual Total Time", 0.0) * loops
        if loops > 1:
            what = node["Node Type"] + (f" using {node['Index Name']}" if "Index Name" in node else "")
            rows.append((total, f"{'  ' * depth}{what}: {loops} loops, {total:.1f} ms, "
                                f"{node.get('Actual Rows', 0)} rows/loop"))
        for child in node.get("Plans", []):
            walk(child, depth + 1)

    walk(plan[0]["Plan"], 0)
    for _, line in sorted(rows, reverse=True)[:8]:
        print("   ", line.strip())


async def _index(engine: AsyncEngine, create: bool) -> None:
    sql = (f"CREATE INDEX IF NOT EXISTS {INDEX} ON scrape_source_runs (binding_id, started_at)" if create
           else f"DROP INDEX IF EXISTS {INDEX}")
    async with engine.begin() as conn:
        await conn.execute(text(sql))
        await conn.execute(text("ANALYZE scrape_source_runs"))


async def run(bindings: int, depths: list[int], repeat: int, explain: bool = False) -> None:
    from tracker.config import get_settings

    base = make_url(get_settings().database_url)
    sql = await asyncio.to_thread(_statement) if explain else ""
    engine = await _create(base)
    try:
        await _seed_companies(engine, bindings)
        print(f"{bindings:,} followed bindings; followed_bindings, ms (median / max of {repeat})")
        print(f"{'runs each':>9} {'source runs':>12} {'without':>15} {'(binding_id, started_at)':>26}")
        have = 0
        for depth in sorted(depths):
            await _grow(engine, have, depth)
            have = depth
            await _index(engine, create=False)
            plain = await _time(engine, repeat)
            await _index(engine, create=True)
            indexed = await _time(engine, repeat)
            assert plain[2] == indexed[2] == bindings, "every followed binding is read"
            print(f"{depth:>9} {depth * bindings:>12,} {plain[0]:>8.0f} / {plain[1]:<5.0f} "
                  f"{indexed[0]:>15.0f} / {indexed[1]:<5.0f}")
        if explain:
            await _index(engine, create=False)
            print(f"slowest per-binding nodes at {have} runs each, without the index:")
            await _explain(engine, sql)
            await _index(engine, create=True)
            print("with (binding_id, started_at):")
            await _explain(engine, sql)
    finally:
        await engine.dispose()
        await _admin(base, f'DROP DATABASE IF EXISTS "{DB_NAME}" WITH (FORCE)')


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--bindings", type=int, default=1126)
    parser.add_argument("--depths", type=int, nargs="+", default=[6, 50, 200, 400])
    parser.add_argument("--repeat", type=int, default=7)
    parser.add_argument("--explain", action="store_true", help="print the slowest per-binding plan nodes at the last depth")
    args = parser.parse_args(argv)
    asyncio.run(run(args.bindings, args.depths, args.repeat, args.explain))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
