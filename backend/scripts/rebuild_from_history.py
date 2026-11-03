"""Rebuild what plugin data reached in OUR derived data, from our own history.

    .venv/bin/python -m scripts.rebuild_from_history snapshots            # dry run: what would be written
    .venv/bin/python -m scripts.rebuild_from_history snapshots --write    # write it; one day per transaction
    .venv/bin/python -m scripts.rebuild_from_history profiles             # dry run: which profiles would change
    .venv/bin/python -m scripts.rebuild_from_history profiles --write     # resolve them; one batch per transaction

Our data and a plugin's never mix; what already mixed is rebuilt from our own
history, and nothing is deleted.

`snapshots`: every day `comp_snapshot` holds as `mixed` (written while a posting
showed whichever source answered first) gets a `roleband` series rebuilt from
`job_observations`: for each posting open that day and in scope now, its latest
observation by the end of the day, counted under the level and family it was
observed at, at OUR answer that night (the first `comp_sources` entry from one of
our providers). A posting our data did not price is left out, as it would have
been. The `mixed` rows stay, unread. A day that already has a `roleband` series
is skipped, so a rerun resumes. Approximations, stated: whether a posting was in
scope that day is today's answer, and a closed-and-reopened posting counts as
open across the gap.

`profiles`: every profile resolved again from our sources only, the inferred
equity vehicle claimed again from OUR listing (resolve, claim, resolve), so a
value no source of ours states clears and the inference stops reading it.
Claims are appended, never deleted; a profile that would not change is not
written. A rerun skips what is done (`record_fact` skips a repeat).

Run the dry run first and read its counts before `--write` on a database you
care about (AGENTS.md "Data safety"). Run it detached.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections import Counter
from datetime import datetime, timedelta

#: Our providers' names as `comp_sources` records them (`CompProvider.name`).
OUR_PROVIDERS = frozenset({"static", "builtin_pay"})
PROFILE_BATCH = 100


def _ours(payload: dict) -> int | None:
    """Our estimate that night: the first answer one of our providers gave."""
    for answer in payload.get("comp_sources") or []:
        if answer.get("provider") in OUR_PROVIDERS and answer.get("median") is not None:
            return int(answer["median"])
    return None


def _level(payload: dict, unplaced: tuple[str, ...], unstated: str) -> str:
    basis = payload.get("level_basis") or "generic"
    return unstated if basis in unplaced else (payload.get("level_band") or "")


async def _day_rows(session, day: datetime) -> dict[tuple[str, str, str], list[int]]:
    from sqlalchemy import text

    from tracker.levels import UNSTATED_LEVEL
    from tracker.schema import UNPLACED_BASIS_VALUES

    end = day + timedelta(days=1)
    rows = (await session.execute(text(
        """
        SELECT DISTINCT ON (o.job_id) o.job_id, j.company, o.payload
        FROM job_observations o JOIN jobs j ON j.id = o.job_id
        WHERE o.observed_at < :end AND j.first_seen < :end
          AND (j.closed_at IS NULL OR j.closed_at >= :start) AND j.in_scope IS TRUE
        ORDER BY o.job_id, o.observed_at DESC
        """
    ), {"start": day, "end": end})).all()
    grouped: dict[tuple[str, str, str], list[int]] = {}
    for _job_id, company, payload in rows:
        median = _ours(payload or {})
        if median is None:
            continue
        key = (company, _level(payload, UNPLACED_BASIS_VALUES, UNSTATED_LEVEL), payload.get("family") or "")
        grouped.setdefault(key, []).append(median)
    return grouped


async def _snapshots(write: bool) -> int:
    from sqlalchemy import insert, select

    from tracker.db.models import CompSnapshot
    from tracker.db.session import session_scope
    from tracker.schema import OUR_ESTIMATE_SOURCE

    report: dict = {"days": 0, "skipped": 0, "rows": 0, "values": 0}
    async with session_scope() as session:
        days = sorted(set((await session.scalars(
            select(CompSnapshot.metric_date).where(CompSnapshot.source == "mixed"))).all()))
        done = set((await session.scalars(
            select(CompSnapshot.metric_date).where(CompSnapshot.source == OUR_ESTIMATE_SOURCE))).all())
    for day in days:
        if day in done:
            report["skipped"] += 1
            continue
        async with session_scope() as session:
            grouped = await _day_rows(session, day)
            report["days"] += 1
            report["rows"] += len(grouped)
            report["values"] += sum(len(v) for v in grouped.values())
            if write and grouped:
                await session.execute(insert(CompSnapshot), [
                    {"metric_date": day, "company": company, "level_band": level, "family": family,
                     "source": OUR_ESTIMATE_SOURCE, "comp_values": values}
                    for (company, level, family), values in grouped.items()
                ])
            if not write:
                await session.rollback()
        print(f"{day.date().isoformat()}: {len(grouped)} groups" + ("" if write else " (dry run)"), flush=True)
    report["mode"] = "write" if write else "dry run"
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


def _columns(profile) -> dict:
    from tracker.profiles.store import PROFILE_FIELDS

    return {f: getattr(profile, f, None) for f in PROFILE_FIELDS}


async def _profiles(write: bool, after: str | None) -> int:
    from sqlalchemy import select

    from tracker.db.models import CompanyProfile
    from tracker.db.session import session_scope
    from tracker.profiles.seed import claim_pay_policy
    from tracker.profiles.store import resolve_and_materialize

    changed_fields: Counter[str] = Counter()
    report: dict = {"profiles": 0, "changed": 0}
    cursor = after or ""
    while True:
        async with session_scope() as session:
            batch = (await session.scalars(
                select(CompanyProfile).where(CompanyProfile.slug > cursor)
                .order_by(CompanyProfile.slug).limit(PROFILE_BATCH))).all()
            if not batch:
                break
            for profile in batch:
                before = _columns(profile)
                await resolve_and_materialize(session, profile.slug)
                await claim_pay_policy(session, profile)
                await resolve_and_materialize(session, profile.slug)
                after_values = _columns(profile)
                moved = [f for f in before if before[f] != after_values[f]]
                report["profiles"] += 1
                if moved:
                    report["changed"] += 1
                    changed_fields.update(moved)
            cursor = batch[-1].slug
            if not write:
                await session.rollback()
        print(f"through {cursor}: {report['changed']} of {report['profiles']} would change"
              if not write else f"through {cursor}: {report['changed']} of {report['profiles']} changed", flush=True)
    report["fields"] = dict(changed_fields)
    report["mode"] = "write" if write else "dry run"
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    snaps = sub.add_parser("snapshots")
    snaps.add_argument("--write", action="store_true", help="write the rebuilt series (default: dry run)")
    profs = sub.add_parser("profiles")
    profs.add_argument("--write", action="store_true", help="write the resolved profiles (default: dry run)")
    profs.add_argument("--after", help="resume after this slug (printed by an earlier run)")
    args = parser.parse_args(argv)
    if args.cmd == "snapshots":
        return asyncio.run(_snapshots(args.write))
    return asyncio.run(_profiles(args.write, args.after))


if __name__ == "__main__":
    sys.exit(main())
