"""Prepare blind review packets and collect explicit human scope judgments.

    .venv/bin/python -m scripts.prepare_level_review representative --cohort <frozen-cohort> \\
        --groups <frozen-groups> --seed <seed> --out <private-json>
    .venv/bin/python -m scripts.prepare_level_review packets --cohort ... --groups ... --seed ... \\
        --snapshot ... --selection ... --candidate ... --reviewers <primary> <secondary> --out-dir ...
    .venv/bin/python -m scripts.prepare_level_review collect --key <private-key> --reviews <responses> --out <private-json>
    .venv/bin/python -m scripts.prepare_level_review adjudicate ... --decisions <decisions-json>

`representative` draws a provisional 250-case representative frame. Its
employer-size proxy is representation in the frozen cohort, not company
headcount.

`packets`: the selection maps `high_confidence`, `representative` and `edge` to
frozen ids; the candidate file binds `snapshot_sha256` and a unique
`predictions` array whose selected high-confidence cases have
`high_confidence: true`. It describes a candidate's declared subset, not
calibrated confidence. Give each reviewer only their packet; retain
`private-key.json` separately.

`collect` validates all 750 readings and reports agreement; `collect --partial`
validates completed responses during collection and reports incompleteness
explicitly. `adjudicate` requires 600 explicit decisions and always the full
review set.

Reads and decisions state `method: human`, permissible `bands`,
`not_identifiable`, `confidence`, `reason` and exact `evidence` spans; reads
identify `case_id` and `reviewer`, decisions `job_id` and `adjudicator`. Each
span names `field` (`title` or `description_text`), `start`, `end` and `quote`.
These declarations record reviewer responsibility; the CLI cannot authenticate
human identity. Incomplete samples or review sets fail rather than certify
labels.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from scripts.bench_level_identification import write_artifact
from tracker.analytics.level_review import (
    adjudicate,
    draw_representative,
    prepare_review,
    validate_reviews,
)


def _load(path: Path) -> Any:
    return json.loads(path.read_bytes())


def _groups(path: Path) -> dict[int, str]:
    content = _load(path)
    raw = content.get("groups") if isinstance(content, dict) else None
    if not isinstance(raw, dict) or any(not isinstance(v, str) or not v for v in raw.values()):
        raise ValueError("frozen groups object required")
    result = {int(k): v for k, v in raw.items()}
    if len(result) != len(raw):
        raise ValueError("duplicate numeric group identities")
    return result


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    representative = commands.add_parser("representative")
    representative.add_argument("--cohort", type=Path, required=True)
    representative.add_argument("--groups", type=Path, required=True)
    representative.add_argument("--seed", type=int, required=True)
    representative.add_argument("--out", type=Path, required=True)
    packets = commands.add_parser("packets")
    packets.add_argument("--cohort", type=Path, required=True)
    packets.add_argument("--snapshot", type=Path, required=True)
    packets.add_argument("--groups", type=Path, required=True)
    packets.add_argument("--selection", type=Path, required=True)
    packets.add_argument("--candidate", type=Path, required=True)
    packets.add_argument("--reviewers", nargs=2, required=True)
    packets.add_argument("--seed", type=int, required=True)
    packets.add_argument("--out-dir", type=Path, required=True)
    for command in ("collect", "adjudicate"):
        child = commands.add_parser(command)
        child.add_argument("--key", type=Path, required=True)
        child.add_argument("--reviews", type=Path, required=True)
        child.add_argument("--out", type=Path, required=True)
        if command == "adjudicate":
            child.add_argument("--decisions", type=Path, required=True)
        else:
            child.add_argument("--partial", action="store_true")
    args = parser.parse_args(argv)
    inputs = {key: {"path": str(value.resolve()), "sha256": hashlib.sha256(value.read_bytes()).hexdigest()}
              for key, value in vars(args).items() if isinstance(value, Path) and key not in {"out", "out_dir"}}
    if args.command == "representative":
        cohort = _load(args.cohort)["targets"]
        ids = draw_representative(cohort, _groups(args.groups), seed=args.seed)
        result = {"ids": ids, "seed": args.seed, "inputs": inputs,
                  "status": "representative frame only; high-confidence and edge strata pending",
                  "sampling": "proportional joint strata; group-disjoint; Apple capped at 40%",
                  "employer_size_basis": "frozen-cohort representation, not company headcount"}
    elif args.command == "packets":
        snapshot = _load(args.snapshot)["jobs"]
        cohort = _load(args.cohort)["targets"]
        candidate = _load(args.candidate)
        if candidate.get("snapshot_sha256") != inputs["snapshot"]["sha256"]:
            raise ValueError("candidate does not bind the frozen snapshot")
        predictions = candidate.get("predictions")
        if (not isinstance(predictions, list) or any(not isinstance(p, dict) or type(p.get("id")) is not int for p in predictions)
                or len({p["id"] for p in predictions}) != len(predictions)):
            raise ValueError("unique candidate prediction identities required")
        high = {p["id"] for p in predictions if p.get("high_confidence") is True}
        by_id = {r["id"]: r for r in snapshot}
        if (len(by_id) != len(snapshot) or any(r["id"] not in by_id for r in cohort)
                or any(r["company"] != by_id[r["id"]]["company"] for r in cohort)):
            raise ValueError("cohort source identities missing or duplicated")
        # Sampling facts stay frozen; only captured source text enters reviewer packets.
        rows = [r | {k: by_id[r["id"]].get(k) for k in ("title", "description_text")} for r in cohort]
        bundle = prepare_review(rows, _groups(args.groups), _load(args.selection), high_confidence_ids=high,
                                seed=args.seed, reviewers=tuple(args.reviewers))
        if args.out_dir.exists():
            raise FileExistsError(args.out_dir)
        primary, secondary = args.reviewers
        print(write_artifact(args.out_dir / "reviewer-primary.json", {"cases": bundle["packets"][primary]}))
        print(write_artifact(args.out_dir / "reviewer-secondary.json", {"cases": bundle["packets"][secondary]}))
        print(write_artifact(args.out_dir / "private-key.json", {"sealed": bundle["sealed"], "inputs": inputs,
                                                               "seed": args.seed, "sealed_sha256": bundle["sealed_sha256"]}))
        return 0
    else:
        sealed = _load(args.key)["sealed"]
        reviews = _load(args.reviews)
        if args.command == "collect":
            result = validate_reviews(sealed, reviews, complete=not args.partial)
        else:
            result = adjudicate(sealed, reviews, _load(args.decisions))
        result["inputs"] = inputs
    print(write_artifact(args.out, result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
