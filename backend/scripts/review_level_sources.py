"""Prepare source review packets and compile explicitly reviewed study targets.

    .venv/bin/python -m scripts.review_level_sources prepare --snapshot <capture> --groups <groups> \\
        --ids <explicit-ids> --out <private-json>
    .venv/bin/python -m scripts.review_level_sources compile --reviews ... --mappings ... \\
        --documents ... --group-reviews ... --multi-level exclude|preserve ...

`prepare` writes source and complete group packets plus pending decision
records. These are provenance reviews, kept separate from the blind scope-label
protocol of `scripts.prepare_level_review`.

`compile`: documents map SHA-256 fingerprints to captured text. Approved
decisions declare a human reviewer, reason, role, source evidence and
permissible bands. Mapping records name company/code/band, allowed
families/tracks, document fingerprint and exact quote offsets; their basis is
`employer_ladder` or `independently_reviewed_vocabulary`. Group decisions bind
the full member list and each member's source fingerprint.

Every input is hashed and outputs remain immutable and private. The compiler
validates source links and declarations; human identity and the semantic
correctness of reviews require independent review.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from scripts.bench_level_identification import load_snapshot, write_artifact
from tracker.analytics.level_study_sources import compile_sources, source_fingerprint
from tracker.levels.ladder import printed_field
from tracker.taxonomy.stated_level import stated_rungs


def _read(path: Path) -> Any:
    return json.loads(path.read_bytes())


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    subcommands = parser.add_subparsers(dest="command", required=True)
    prepare = subcommands.add_parser("prepare")
    compile_command = subcommands.add_parser("compile")
    for child in (prepare, compile_command):
        child.add_argument("--snapshot", type=Path, required=True)
        child.add_argument("--groups", type=Path, required=True)
        child.add_argument("--out", type=Path, required=True)
    prepare.add_argument("--ids", type=Path, required=True)
    for name in ("reviews", "mappings", "documents", "group-reviews"):
        compile_command.add_argument("--" + name, type=Path, required=True)
    compile_command.add_argument("--multi-level", choices=("exclude", "preserve"), required=True)
    args = parser.parse_args(argv)
    rows, snapshot_sha256 = load_snapshot(args.snapshot)
    if any(type(row.get("id")) is not int for row in rows):
        raise ValueError("integer snapshot identities required")
    group_values = _read(args.groups).get("groups")
    if not isinstance(group_values, dict) or any(not isinstance(v, str) or not v for v in group_values.values()):
        raise ValueError("frozen group mapping required")
    groups = {int(k): v for k, v in group_values.items()}
    if len(groups) != len(group_values) or set(groups) != {r["id"] for r in rows}:
        raise ValueError("groups must cover the complete frozen snapshot")
    inputs = {key: {"path": str(value.resolve()), "sha256": hashlib.sha256(value.read_bytes()).hexdigest()}
              for key, value in vars(args).items() if isinstance(value, Path) and key != "out"}
    result: dict[str, Any]
    if args.command == "prepare":
        ids = _read(args.ids)
        index = {row["id"]: row for row in rows}
        if (not isinstance(ids, list) or not ids or any(type(i) is not int or i not in index for i in ids)
                or len(set(ids)) != len(ids)):
            raise ValueError("explicit unique frozen source ids required")
        members = defaultdict(list)
        for job_id, group in groups.items():
            members[group].append(job_id)
        packets = []
        for job_id in ids:
            row = index[job_id]
            description = row.get("description_text")
            packets.append({"id": job_id, "source_sha256": source_fingerprint(row),
                            "source": {k: row.get(k) for k in ("company", "req_id", "title", "department", "team", "raw_level",
                                                              "description_text", "description_sections", "family", "track")},
                            "configured_field": printed_field(str(row["company"])),
                            "description_codes": stated_rungs(str(row["company"]), description if isinstance(description, str) else None),
                            "group": groups[job_id], "group_members": sorted(members[groups[job_id]]),
                            "status": "pending", "permissible_bands": None})
        group_packets = [{"group": group, "members": sorted(members[group]), "status": "pending",
                          "source_sha256": {str(i): source_fingerprint(index[i]) for i in members[group]},
                          "sources": [{"id": i, **{k: index[i].get(k) for k in ("company", "title", "description_text", "family", "track")}}
                                      for i in sorted(members[group])]} for group in sorted({groups[i] for i in ids})]
        result = {"source_packets": packets, "group_packets": group_packets,
                  "reviews": [{"id": i, "source_sha256": source_fingerprint(index[i]), "status": "pending"} for i in ids],
                  "authority": "review preparation only; no approval or target band inferred"}
    else:
        result = compile_sources(rows, _read(args.reviews), mappings=_read(args.mappings), documents=_read(args.documents),
                                 groups=groups, group_reviews=_read(args.group_reviews), multi_level=args.multi_level)
    result["inputs"] = inputs
    result["snapshot_sha256"] = snapshot_sha256
    print(write_artifact(args.out, result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
