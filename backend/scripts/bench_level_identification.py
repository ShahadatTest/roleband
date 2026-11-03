"""Build private, immutable level-evaluation artifacts from frozen evidence.

    .venv/bin/python -m scripts.bench_level_identification capture --database <scratch-name> --out <private-path>
    .venv/bin/python -m scripts.bench_level_identification provenance|cohort|groups|benchmark <snapshot> --out <private-path>
    .venv/bin/python -m scripts.bench_level_identification mask <snapshot> --target <id> --mode <mode> --out <private-path>

`capture` reads a repeatable-read, read-only database snapshot; a live capture
requires explicit `--allow-live`. Every other command works over a frozen
snapshot. Outputs must be outside a Git checkout and cannot overwrite existing
artifacts. Grouping requires captured descriptions and requisition identities.
Masked features and salary references must be rebuilt from the permitted
training data; precomputed embeddings and held-out salary signatures cannot be
reused.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import tempfile
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import asdict
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from tracker.analytics.level_evaluation import (
    EvidenceLabel,
    GroupInput,
    MaskMode,
    MatchRule,
    assert_no_grade_leak,
    independent_label,
    leakage_groups,
    majority_band,
    mask_inputs,
    match_anchors,
    sealed_ids,
    usable_base,
)
from tracker.config import get_settings
from tracker.enrich.level_mapper import level_date
from tracker.schema import RawJob


def write_artifact(path: Path, value: object) -> str:
    """Publish a complete private artifact once; existing evidence cannot be replaced."""
    path = path.expanduser().resolve()
    if any((parent / ".git").exists() for parent in path.parents):
        raise ValueError("evaluation artifacts must stay outside a repository")
    path.parent.mkdir(parents=True, exist_ok=True)
    content = (json.dumps(value, default=str, indent=2, sort_keys=True) + "\n").encode()
    fd, temporary = tempfile.mkstemp(prefix=".level-artifact-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temporary, path)
    finally:
        os.unlink(temporary)
    return hashlib.sha256(content).hexdigest()


def load_snapshot(path: Path) -> tuple[list[dict[str, object]], str]:
    content = path.read_bytes()
    value = json.loads(content)
    if not isinstance(value, dict) or not isinstance(value.get("jobs"), list):
        raise ValueError("snapshot requires a jobs array")
    rows = value["jobs"]
    if not all(isinstance(row, dict) and isinstance(row.get("id"), int) for row in rows):
        raise ValueError("snapshot jobs require integer ids")
    if len({row["id"] for row in rows}) != len(rows):
        raise ValueError("snapshot contains duplicate job ids")
    return rows, hashlib.sha256(content).hexdigest()


def provenance(rows: Sequence[Mapping[str, object]]) -> dict[str, object]:
    labels = [label for row in rows if (label := independent_label(row)) is not None]
    units = {label.unit: label for label in labels}
    tiers: dict[str, object] = {}
    for tier in ("A", "B", "C"):
        selected = [label for label in units.values() if label.tier.value == tier]
        tiers[tier] = {"units": len(selected), "employers": dict(Counter(label.company for label in selected))}
    conflicts: dict[tuple[str, str, int, int], set[str]] = defaultdict(set)
    for label in labels:
        conflicts[label.unit].add(label.band.value)
    return {
        "anchor_rows": len(labels), "anchor_units": len(units), "tiers": tiers,
        "units": [asdict(label) for label in sorted(units.values(), key=lambda label: label.unit)],
        "conflicting_units": [list(unit) for unit, bands in conflicts.items() if len(bands) > 1],
        "deduplication": "last frozen row per company/normalized-title/range; conflicts are reported",
        "truth_policy": "A printed; B company vocabulary pending independent review; C weak; D excluded",
    }


def frozen_cohort(rows: Sequence[Mapping[str, object]]) -> dict[str, object]:
    anchor_titles: dict[tuple[object, ...], set[str]] = defaultdict(set)
    for row in rows:
        label = independent_label(row)
        if label is not None:
            anchor_key = (label.company, label.family, label.track, row.get("level_year"))
            anchor_titles[anchor_key].add(label.unit[1])
    targets = []
    for row in rows:
        if not usable_base(row) or row.get("status") != "open" or not row.get("family"):
            continue
        if row.get("level_basis") not in {"none", "unmapped"} and row.get("level_confidence") != "unconfirmed":
            continue
        if not isinstance(row.get("level_year"), int):
            raise ValueError("cohort requires a frozen evidence year")
        key = tuple(row.get(k) for k in ("company", "family", "track", "level_year"))
        count = len(anchor_titles.get(key, set()))
        target = dict(row)
        target["displayed_band"] = None if row.get("level_basis") in {"none", "unmapped"} else row.get("level_band")
        target["anchor_titles"] = count
        target["reachable"] = count >= 2
        targets.append(target)
    return {
        "targets": targets,
        "counts": {
            "postings": len(targets), "employers": len({row["company"] for row in targets}),
            "basis": dict(Counter(str(row["level_basis"]) for row in targets)),
            "track": dict(Counter(str(row["track"]) for row in targets)),
            "year": dict(Counter(str(row["level_year"]) for row in targets)),
            "company": dict(Counter(str(row["company"]) for row in targets)),
            "reachable": sum(bool(row["reachable"]) for row in targets),
            "with_one_anchor": sum(isinstance(row["anchor_titles"], int) and row["anchor_titles"] >= 1
                                   for row in targets),
            "with_embedding": sum(bool(row.get("has_embedding")) for row in targets),
            "with_required_years": sum(row.get("required_years") is not None for row in targets),
        },
    }


def grouped_snapshot(rows: Sequence[Mapping[str, object]]) -> dict[str, object]:
    if any("description_text" not in row or "req_id" not in row for row in rows):
        raise ValueError("grouping requires captured descriptions and requisition identities")
    inputs = []
    for row in rows:
        job_id, cluster, places = row["id"], row.get("cluster_id"), row.get("place_set_id")
        if not isinstance(job_id, int):
            raise ValueError("job id must be an integer")
        inputs.append(GroupInput(
            job_id=job_id, company=str(row["company"]), req_id=str(row.get("req_id") or ""),
            title=str(row.get("title") or ""), description=str(row.get("description_text") or ""),
            cluster_id=cluster if isinstance(cluster, int) else None,
            place_set_id=places if isinstance(places, int) else None,
        ))
    groups = leakage_groups(inputs)
    return {"groups": groups, "group_count": len(set(groups.values())),
            "group_sizes": dict(Counter(Counter(groups.values()).values())),
            "review_required": True,
            "policy": "same-company identities/place sets/role templates; cluster membership alone is not a link"}


def masked_snapshot(rows: Sequence[Mapping[str, object]], target_id: int,
                    mode: MaskMode, hard: bool) -> dict[str, object]:
    target = next((row for row in rows if row["id"] == target_id), None)
    if target is None:
        raise ValueError("target is absent from frozen evidence")
    excluded = sealed_ids(rows, target, mode)
    grades = [str(row.get("raw_level") or row.get("independent_raw_level") or "")
              for row in rows if row["id"] in excluded]
    inputs = [mask_inputs(row, grades, hard=hard) for row in rows if row["id"] in excluded]
    for row in inputs:
        assert_no_grade_leak(row, grades)
    return {"mode": mode.value, "hard": hard, "excluded_label_ids": sorted(excluded),
            "masked_inputs": inputs,
            "training_ids": [row["id"] for row in rows if row["id"] not in excluded],
            "derived_references": "must be rebuilt from training ids; committed pay tables are not admitted"}


#: Group isolation and signature sealing, from the weakest holdout to the deployment condition.
LANES: dict[str, tuple[bool, bool | None]] = {
    "title_identity": (False, None),
    "grouped": (True, None),
    "grouped_m3": (True, False),
    "grouped_m3_hard": (True, True),
}
SAME_COMPANY_RULES = (MatchRule.EXACT, MatchRule.NEAREST_NEAR, MatchRule.NEAREST)
CROSS_EMPLOYER_RULES = (MatchRule.EXACT, MatchRule.WITHIN_NEAR, MatchRule.NEAREST_FIVE)


def _signature(label: EvidenceLabel) -> tuple[str, str, str, int, int]:
    return label.company, label.family, label.track, label.base_min, label.base_max


def _resealed(row: Mapping[str, object], grades: Sequence[str], *, hard: bool) -> EvidenceLabel | None:
    """What an opening still anchors once its employer grade is withheld."""
    masked = mask_inputs(row, grades, hard=hard)
    assert_no_grade_leak(masked, grades)
    return independent_label(masked)


def _score(outcomes: Sequence[tuple[str, bool]], eligible: int) -> dict[str, object]:
    predicted = len(outcomes)
    correct = sum(hit for _, hit in outcomes)
    tiers = {}
    for tier in ("A", "B", "C"):
        selected = [hit for label, hit in outcomes if label == tier]
        if selected:
            tiers[tier] = {"predicted": len(selected), "correct": sum(selected),
                           "agreement": round(sum(selected) / len(selected), 4)}
    return {"eligible": eligible, "predicted": predicted, "correct": correct,
            "agreement": round(correct / predicted, 4) if predicted else None,
            "coverage": round(predicted / eligible, 4) if eligible else None,
            "per_tier": tiers}


def benchmark(rows: Sequence[Mapping[str, object]]) -> dict[str, object]:
    """Same-company and cross-employer salary agreement under each holdout lane.

    Every lane scores the same labelled units, so a lane's loss is the leakage the
    weaker holdout was counting. Tier C labels are the title reader's own output:
    agreement with them measures consistency, not accuracy.
    """
    by_id: dict[int, Mapping[str, object]] = {}
    for row in rows:
        job_id = row.get("id")
        if not isinstance(job_id, int):
            raise ValueError("snapshot jobs require integer ids")
        by_id[job_id] = row
    labels = {job_id: label for job_id, row in by_id.items()
              if (label := independent_label(row)) is not None}
    units: dict[tuple[str, str, int, int], EvidenceLabel] = {}
    for job_id in sorted(labels):
        units[labels[job_id].unit] = labels[job_id]
    membership = grouped_snapshot(rows)["groups"]
    if not isinstance(membership, dict):
        raise ValueError("grouping did not return a membership map")
    groups: dict[int, str] = {}
    for job_id, group in membership.items():
        if not isinstance(job_id, int) or not isinstance(group, str):
            raise ValueError("grouping did not return a membership map")
        groups[job_id] = group

    cells: dict[tuple[object, ...], list[EvidenceLabel]] = defaultdict(list)
    families: dict[tuple[object, ...], list[EvidenceLabel]] = defaultdict(list)
    sealed: dict[tuple[str, str, str, int, int], list[str]] = defaultdict(list)
    for label in units.values():
        year = by_id[label.job_id].get("level_year")
        cells[(label.company, label.family, label.track, year)].append(label)
        families[(label.family, label.track, year)].append(label)
        sealed[_signature(label)].append(str(by_id[label.job_id].get("raw_level")
                                            or label.printed or ""))
    reseal: dict[tuple[int, bool], EvidenceLabel | None] = {}
    for label in units.values():
        for hard in (False, True):
            reseal[(label.job_id, hard)] = _resealed(
                by_id[label.job_id], sealed[_signature(label)], hard=hard)

    bands = Counter(label.band for label in units.values())
    constant = max(bands.items(), key=lambda item: (item[1], item[0].value))[0]
    results: dict[str, object] = {}
    for lane, (grouped, seal) in LANES.items():
        same: dict[str, object] = {}
        cross: dict[str, object] = {}
        cell_outcomes: list[tuple[str, bool]] = []
        for rule in SAME_COMPANY_RULES:
            same[rule.value] = _score([
                outcome for label in units.values()
                if (outcome := _predict(label, _permitted(
                    label, cells[(label.company, label.family, label.track,
                                  by_id[label.job_id].get("level_year"))],
                    grouped=grouped, hard=seal, groups=groups, reseal=reseal),
                    rule, per_employer=False)) is not None], len(units))
        for rule in CROSS_EMPLOYER_RULES:
            cross[rule.value] = _score([
                outcome for label in units.values()
                if (outcome := _predict(label, [
                    anchor for anchor in families[(label.family, label.track,
                                                   by_id[label.job_id].get("level_year"))]
                    if anchor.company != label.company],
                    rule, per_employer=True)) is not None], len(units))
        for label in units.values():
            pool = _permitted(label, cells[(label.company, label.family, label.track,
                                            by_id[label.job_id].get("level_year"))],
                              grouped=grouped, hard=seal, groups=groups, reseal=reseal)
            if pool:
                modal = Counter(anchor.band for anchor in pool).most_common(1)[0][0]
                cell_outcomes.append((label.tier.value, modal is label.band))
        results[lane] = {
            "same_company": same, "cross_employer": cross,
            "constant_cell_band": _score(cell_outcomes, len(units)),
        }
    title_only = []
    for label in units.values():
        masked = reseal[(label.job_id, False)]
        if masked is not None:
            title_only.append((label.tier.value, masked.band is label.band))
    return {
        "labelled_units": len(units),
        "anchor_rows": len(labels),
        "tiers": dict(Counter(label.tier.value for label in units.values())),
        "lanes": results,
        "constant_band": {"band": constant.value,
                          "share": round(bands[constant] / len(units), 4),
                          "per_tier": {tier: round(
                              sum(1 for label in units.values()
                                  if label.tier.value == tier and label.band is constant)
                              / max(1, sum(1 for label in units.values() if label.tier.value == tier)), 4)
                              for tier in ("A", "B", "C")}},
        "title_only": _score(title_only, len(units)),
        "rules": ("One company/title/range is one unit. A vote needs two distinct identities and "
                  "four of five agreeing; cross-employer votes are employer-normalised and need two "
                  "employers. Tier B and C labels come from the title, so title-only agreement with "
                  "them is tautological and only tier A measures it."),
    }


def _permitted(target: EvidenceLabel, pool: Sequence[EvidenceLabel], *, grouped: bool,
               hard: bool | None, groups: Mapping[int, str],
               reseal: Mapping[tuple[int, bool], EvidenceLabel | None]) -> list[EvidenceLabel]:
    """Anchors a lane leaves standing: never the target's own identity or group."""
    signature = _signature(target)
    permitted = []
    for anchor in pool:
        if anchor.unit[:2] == target.unit[:2]:
            continue
        if grouped and groups[anchor.job_id] == groups[target.job_id]:
            continue
        if hard is None or _signature(anchor) != signature:
            permitted.append(anchor)
            continue
        resealed = reseal.get((anchor.job_id, hard))
        if resealed is not None:
            permitted.append(resealed)
    return permitted


def _predict(target: EvidenceLabel, pool: Sequence[EvidenceLabel], rule: MatchRule, *,
             per_employer: bool) -> tuple[str, bool] | None:
    vote = majority_band(match_anchors(target, pool, rule), per_employer=per_employer)
    if vote is None:
        return None
    return target.tier.value, vote.band is target.band


def database_url(database: str, *, allow_live: bool) -> str:
    live = make_url(get_settings().database_url)
    if database == live.database and not allow_live:
        raise ValueError("live capture requires --allow-live; evaluation uses frozen files")
    return live.set(drivername="postgresql+asyncpg", database=database).render_as_string(hide_password=False)


async def capture(database: str, *, allow_live: bool) -> dict[str, object]:
    engine = create_async_engine(database_url(database, allow_live=allow_live), poolclass=NullPool,
                                 connect_args={"server_settings": {
                                     "default_transaction_read_only": "on", "statement_timeout": "30000",
                                     "application_name": "level_evaluation_capture",
                                 }})
    try:
        async with engine.connect() as connection:
            await connection.execution_options(isolation_level="REPEATABLE READ")
            await connection.execute(text("SET TRANSACTION READ ONLY"))
            actual = (await connection.execute(text("select current_database()"))).scalar_one()
            if actual != database:
                raise ValueError("capture reached a different database")
            stamp = (await connection.execute(text("select now()"))).scalar_one()
            rows = [dict(row._mapping) for row in await connection.execute(text("""
                select j.id,j.company,j.req_id,j.title,j.description_text,j.department,j.team,
                j.family,j.track,j.raw_level,j.level_band,j.level_basis,j.level_confidence,
                j.status,j.in_scope,j.locations,j.location_groups,j.location_cities,j.required_years,
                j.cluster_id,j.first_seen,j.first_posted_at,j.posted_at,j.last_seen,
                j.disclosed_base_min,j.disclosed_base_max,j.disclosed_currency,j.disclosed_pay_basis,
                j.disclosed_pay_period,j.disclosed_source,j.disclosed_confidence,
                j.embedding is not null as has_embedding,
                case when p.status='auto' then p.set_id end as place_set_id
                from jobs j left join job_place_set_member p on p.job_id=j.id order by j.id
            """))]
            observations = (await connection.execute(text("select count(*) from job_observations"))).scalar_one()
            inventory = [dict(row._mapping) for row in await connection.execute(text("""
                select id,company,req_id,title,raw_level,family,track,level_band,level_basis,
                location_groups,gone_at from posting_inventory where raw_level is not null order by id
            """))]
            version_table = (await connection.execute(text("select to_regclass('public.alembic_version')"))).scalar_one()
            revision = ((await connection.execute(text("select version_num from alembic_version"))).scalar_one()
                        if version_table else None)
            read_only = (await connection.execute(text("show transaction_read_only"))).scalar_one()
            if read_only != "on":
                raise ValueError("capture transaction is not read-only")
        for row in rows:
            raw = RawJob(company=row["company"], req_id=row["req_id"], title=row["title"], url="",
                         posted_at=row["posted_at"])
            raw.held_first_posted_at, raw.held_first_seen = row["first_posted_at"], row["first_seen"]
            row["level_year"] = level_date(raw).year
            row["has_description"] = bool(row["description_text"])
            row["observed_at"] = str(stamp)
        return {"metadata": {"snapshot_at": str(stamp), "database": actual,
                             "read_only": read_only, "revision": revision,
                             "observation_count": observations, "capture_schema": 1,
                             "collector_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()},
                "jobs": rows, "printed_inventory": inventory}
    finally:
        await engine.dispose()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("provenance", "cohort", "groups", "mask", "benchmark"):
        child = commands.add_parser(name)
        child.add_argument("snapshot", type=Path)
        child.add_argument("--out", type=Path, required=True)
        if name == "mask":
            child.add_argument("--target", type=int, required=True)
            child.add_argument("--mode", choices=[mode.value for mode in MaskMode], required=True)
            child.add_argument("--hard", action="store_true")
    child = commands.add_parser("capture")
    child.add_argument("--database", required=True)
    child.add_argument("--allow-live", action="store_true")
    child.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command == "capture":
        result = asyncio.run(capture(args.database, allow_live=args.allow_live))
    else:
        rows, digest = load_snapshot(args.snapshot)
        if args.command == "provenance":
            result = provenance(rows)
        elif args.command == "cohort":
            result = frozen_cohort(rows)
        elif args.command == "groups":
            result = grouped_snapshot(rows)
        elif args.command == "benchmark":
            result = benchmark(rows)
        else:
            result = masked_snapshot(rows, args.target, MaskMode(args.mode), args.hard)
        result = {"source_sha256": digest, "source_snapshot": str(args.snapshot.resolve()), **result}
    digest = write_artifact(args.out, result)
    print(json.dumps({"artifact": str(args.out.resolve()), "sha256": digest}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
