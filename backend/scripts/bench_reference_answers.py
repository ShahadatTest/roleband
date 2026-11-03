"""What the pay reference answers, frozen, so a change to where it comes from is
measured instead of guessed.

    deploy/restore_db.sh --into roleband_parity     # newest nightly dump -> scratch DB
    .venv/bin/python -m scripts.bench_reference_answers snapshot ~/.roleband/parity/t0.json --database roleband_parity
    # ... change the code ...
    .venv/bin/python -m scripts.bench_reference_answers snapshot /tmp/b.json --database roleband_parity
    .venv/bin/python -m scripts.bench_reference_answers compare ~/.roleband/parity/t0.json /tmp/b.json --expect moves.json

`snapshot` reads one SCRATCH database on the embedded server and refuses the live
one: the answers are read through the real API routes, in process, with GETs
only, and nothing in this script writes. It records, per open job,
the stored estimate and the job detail's `comp_package` and `comp_sources`;
every company profile; and the four pay statistics. Keys that depend on the
clock are dropped by name (`VOLATILE`), never by pattern.

`compare` exits 1 when any answer moved that `--expect` does not name. The expect
file is a JSON list of `{"path": "<fnmatch over the flattened path>", "reason":
"..."}`; a listed move still prints, with its reason. The snapshot can hold a
plugin's figures: keep it under the git-ignored `~/.roleband/parity/`, never in the repo.
"""

from __future__ import annotations

import argparse
import asyncio
import fnmatch
import hashlib
import json
import math
import subprocess
import sys
from collections import Counter
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

#: Keys whose value moves with the clock, not with the data. Dropped wherever
#: they appear; a new clock-relative key is added here by name.
VOLATILE = frozenset({
    "freshness",          # profile field age class, relative to now
    "levels_fetched_at",  # moves on every manual refresh
    "open_roles",         # live posting counts, not pay
    "locations",
    "prices",
    "price",
    "generated_at",
    "as_of_now",
})

STATISTICS = (
    "/api/statistics/compensation",
    "/api/statistics/comp-trends",
    "/api/statistics/comp-trajectory",
    "/api/statistics/equity-validation",
)

#: Floats closer than this are the same answer.
TOLERANCE = 1e-9


# --------------------------------------------------------------------------- #
# Pure helpers (tested in tests/test_bench_reference_answers.py)
# --------------------------------------------------------------------------- #


def strip_volatile(value):
    """`value` with every `VOLATILE` key removed, at any depth."""
    if isinstance(value, dict):
        return {k: strip_volatile(v) for k, v in value.items() if k not in VOLATILE}
    if isinstance(value, list):
        return [strip_volatile(v) for v in value]
    return value


def flatten(value, prefix: str = "") -> dict[str, object]:
    """Leaf path -> value. Lists index by position; an empty container is a leaf."""
    if isinstance(value, dict) and value:
        out: dict[str, object] = {}
        for key in sorted(value):
            out.update(flatten(value[key], f"{prefix}.{key}" if prefix else str(key)))
        return out
    if isinstance(value, list) and value:
        out = {}
        for n, item in enumerate(value):
            out.update(flatten(item, f"{prefix}[{n}]"))
        return out
    return {prefix: value}


def same(a, b) -> bool:
    if isinstance(a, float) or isinstance(b, float):
        if isinstance(a, int | float) and isinstance(b, int | float) and not isinstance(a, bool) and not isinstance(b, bool):
            return math.isclose(float(a), float(b), rel_tol=TOLERANCE, abs_tol=TOLERANCE)
    return a == b


def diff(a: dict, b: dict) -> list[tuple[str, object, object]]:
    """Every leaf that differs between two snapshots, as (path, before, after).
    A leaf present on one side only reads `<absent>` on the other."""
    fa, fb = flatten(strip_volatile(a)), flatten(strip_volatile(b))
    absent = "<absent>"
    moved = []
    for path in sorted(set(fa) | set(fb)):
        before, after = fa.get(path, absent), fb.get(path, absent)
        if not same(before, after):
            moved.append((path, before, after))
    return moved


def split_expected(moved, expect: list[dict]) -> tuple[list, list]:
    """(expected, unexpected): a move is expected when an `expect` pattern matches its path."""
    expected, unexpected = [], []
    for move in moved:
        rule = next((e for e in expect if fnmatch.fnmatchcase(move[0], e["path"])), None)
        (expected if rule else unexpected).append((*move, rule["reason"] if rule else None))
    return expected, unexpected


# --------------------------------------------------------------------------- #
# Snapshot (reads a scratch database through the real routes)
# --------------------------------------------------------------------------- #


def _scratch_url(database: str) -> tuple[str, str]:
    """(SQLAlchemy URL for `database` on the app's server, the live database name)."""
    from tracker.config import get_settings

    live = urlsplit(get_settings().database_url)
    return urlunsplit(live._replace(path=f"/{database}")), live.path.lstrip("/")


def _atlas_checksum() -> str:
    from tracker.levels.atlas import ATLAS_DIR

    digest = hashlib.sha256()
    for path in sorted(Path(ATLAS_DIR).iterdir()):
        if path.is_file():
            digest.update(path.name.encode())
            digest.update(path.read_bytes())
    return digest.hexdigest()


def _git_sha() -> str:
    try:
        return subprocess.run(  # noqa: S603, S607 - fixed argv
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


async def _snapshot(database: str, concurrency: int) -> dict:
    from httpx import ASGITransport, AsyncClient
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from tracker.api.app import app
    from tracker.api.deps import get_session

    url, live = _scratch_url(database)
    if database == live:
        raise SystemExit(f"refusing to read {database!r}: it is the live database. Restore a scratch copy first.")
    engine = create_async_engine(url, pool_size=concurrency, max_overflow=0)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        if (await session.execute(text("select current_database()"))).scalar() == live:
            raise SystemExit("refusing: the connection reached the live database")
        head = (await session.execute(text("select version_num from alembic_version"))).scalar()
        estimates = {
            str(r.id): [r.comp_low, r.comp_median, r.comp_high, r.comp_provenance]
            for r in await session.execute(text(
                "select id, comp_low, comp_median, comp_high, comp_provenance from jobs "
                "where comp_median is not null order by id"
            ))
        }
        open_ids = [r[0] for r in await session.execute(text("select id from jobs where status = 'open' order by id"))]
        slugs = [r[0] for r in await session.execute(text("select slug from company_profile order by slug"))]

    async def request_session():
        async with factory() as session:
            yield session

    app.dependency_overrides[get_session] = request_session
    gate = asyncio.Semaphore(concurrency)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://127.0.0.1:8010") as client:

            async def get(path: str):
                async with gate:
                    response = await client.get(path)
                if response.status_code != 200:
                    return {"status": response.status_code}
                return response.json()

            async def package(job_id: int):
                body = await get(f"/api/jobs/{job_id}")
                return str(job_id), {k: body.get(k) for k in ("comp_package", "comp_sources", "status")}

            packages = dict(await asyncio.gather(*(package(i) for i in open_ids)))
            profiles = dict(zip(slugs, await asyncio.gather(*(get(f"/api/company-profiles/{s}") for s in slugs)), strict=True))
            profile_list = await get("/api/company-profiles")
            statistics = {path: await get(path) for path in STATISTICS}
    finally:
        app.dependency_overrides.pop(get_session, None)
        await engine.dispose()

    return {
        "meta": {
            "git_sha": _git_sha(),
            "database": database,
            "alembic_head": head,
            "atlas_sha256": _atlas_checksum(),
            "counts": {"estimates": len(estimates), "open_jobs": len(open_ids), "profiles": len(slugs)},
        },
        "estimates": estimates,
        "packages": packages,
        "profiles": profiles,
        "profile_list": profile_list,
        "statistics": statistics,
    }


def cmd_snapshot(out: str, database: str, concurrency: int) -> int:
    snapshot = asyncio.run(_snapshot(database, concurrency))
    path = Path(out).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(snapshot, sort_keys=True, default=str), encoding="utf-8")
    print(f"wrote {path}: {snapshot['meta']['counts']} at {snapshot['meta']['git_sha'][:10]}")
    return 0


def cmd_compare(a_path: str, b_path: str, expect_path: str | None) -> int:
    a = json.loads(Path(a_path).expanduser().read_text(encoding="utf-8"))
    b = json.loads(Path(b_path).expanduser().read_text(encoding="utf-8"))
    expect = json.loads(Path(expect_path).read_text(encoding="utf-8")) if expect_path else []
    a.pop("meta", None)
    b.pop("meta", None)
    expected, unexpected = split_expected(diff(a, b), expect)
    by_reason = Counter(reason for *_, reason in expected)
    for reason, n in sorted(by_reason.items()):
        print(f"expected  {n:6}  {reason}")
    sections = Counter(path.split(".")[0] for path, *_ in unexpected)
    for section, n in sorted(sections.items()):
        print(f"UNEXPECTED {n:6}  in {section}")
    for path, before, after, _ in unexpected[:25]:
        print(f"  {path}: {before!r} -> {after!r}")
    return 1 if unexpected else 0


async def _replay_estimates(database: str) -> list[dict]:
    """Every open job's stored estimate beside what the stored-row estimator
    (`ReferenceTableProvider` + static seed, as the pipeline builds it) answers."""
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from tracker.analytics.comp_package import pay_level_index
    from tracker.comp_providers.base import CompContext
    from tracker.comp_providers.static import StaticCompProvider
    from tracker.comp_providers.table import ReferenceTableProvider
    from tracker.db.queries.reference_pay import pay_level_rows
    from tracker.enrich.comp import CompResolver
    from tracker.schema import parse_band

    url, live = _scratch_url(database)
    if database == live:
        raise SystemExit(f"refusing to read {database!r}: it is the live database.")
    engine = create_async_engine(url)
    try:
        async with async_sessionmaker(engine)() as session:
            rows = await pay_level_rows(session)
            jobs = (await session.execute(text(
                "select id, company, level_band, family, title, location_groups, comp_median, comp_provenance "
                "from jobs where status = 'open' order by id"
            ))).all()
    finally:
        await engine.dispose()
    resolver = CompResolver([ReferenceTableProvider(pay_level_index(rows)), StaticCompProvider()])
    out = []
    for job in jobs:
        try:
            band = parse_band(job.level_band)
        except ValueError:
            continue
        ctx = CompContext(job.company, band, job.family, (job.location_groups or [None])[0], job.title)
        new, _ = await resolver.resolve(ctx)
        out.append({
            "id": job.id, "company": job.company, "band": job.level_band, "family": job.family,
            "old": job.comp_median, "old_source": job.comp_provenance,
            "new": new.median if new else None, "new_source": new.source if new else None,
        })
    return out


def moved_report(replayed: list[dict]) -> dict:
    """Counts of what moved, overall and per company: same, moved (with the
    ratio's median), gained (no estimate before), lost (none now)."""
    from statistics import median

    def bucket(r):
        if r["old"] is None and r["new"] is None:
            return "none"
        if r["old"] is None:
            return "gained"
        if r["new"] is None:
            return "lost"
        return "same" if r["old"] == r["new"] else "moved"

    overall: Counter = Counter()
    companies: dict[str, Counter] = {}
    ratios: dict[str, list[float]] = {}
    for r in replayed:
        b = bucket(r)
        overall[b] += 1
        companies.setdefault(r["company"], Counter())[b] += 1
        if b == "moved":
            ratios.setdefault(r["company"], []).append(r["new"] / r["old"])
    return {
        "overall": dict(overall),
        "companies": {
            c: {**dict(n), "median_ratio": round(median(ratios[c]), 3) if c in ratios else None}
            for c, n in sorted(companies.items(), key=lambda kv: -sum(v for k, v in kv[1].items() if k != "none"))
        },
    }


def cmd_replay_estimates(database: str, out: str | None) -> int:
    replayed = asyncio.run(_replay_estimates(database))
    report = moved_report(replayed)
    print("overall", report["overall"])
    for company, counts in list(report["companies"].items())[:30]:
        print(f"  {company:28} {counts}")
    if out:
        path = Path(out).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"report": report, "rows": replayed}, sort_keys=True, default=str), encoding="utf-8")
        print(f"wrote {path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("snapshot")
    p.add_argument("out")
    p.add_argument("--database", required=True, help="a scratch database on the app's server, never the live one")
    p.add_argument("--concurrency", type=int, default=8)
    p = sub.add_parser("compare")
    p.add_argument("a")
    p.add_argument("b")
    p.add_argument("--expect", help="JSON list of {path, reason} moves allowed")
    p = sub.add_parser("replay-estimates", help="open jobs: stored estimate vs the stored-row estimator")
    p.add_argument("--database", required=True)
    p.add_argument("--out")
    args = parser.parse_args(argv)
    if args.cmd == "replay-estimates":
        return cmd_replay_estimates(args.database, args.out)
    if args.cmd == "snapshot":
        return cmd_snapshot(args.out, args.database, args.concurrency)
    return cmd_compare(args.a, args.b, args.expect)


if __name__ == "__main__":
    sys.exit(main())
