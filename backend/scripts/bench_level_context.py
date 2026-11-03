"""Extract grounded context from explicit frozen ids without database access.

    .venv/bin/python -m scripts.bench_level_context --snapshot <capture> --ids <ids-json> --out <private-json>

Extracts years and responsibility facts for the given ids. It defaults to hard
`M3` masking; `--mask realistic` keeps seniority words and `--mask none` is for
source audits only. Every fact retains exact quote offsets and a fingerprint of
the source. A duty inherited from an ownership heading also retains that heading
as a separate context span. Required, preferred and unclassified experience stay
separate; alternative degree or level routes keep all stated years. Scope facts
require direct role statements, and missing features remain null.

It uses the shared section and years grammars, excludes company, team and
benefit text, and emits neither a level nor a probability. It does not persist
canonical fields.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path
from typing import Any

from scripts.bench_level_identification import load_snapshot, write_artifact
from tracker.analytics.level_context import CONTEXT_VERSION, FEATURES, extract_context
from tracker.analytics.level_evaluation import (
    MaskMode,
    assert_no_grade_leak,
    mask_inputs,
    sealed_ids,
)
from tracker.taxonomy.stated_level import stated_level


def build_context_rows(rows: list[dict[str, Any]], ids: list[int], *, mask: str) -> dict[str, Any]:
    if mask not in {"none", "hard", "realistic"}:
        raise ValueError("unsupported mask")
    if not ids or any(not isinstance(job_id, int) or isinstance(job_id, bool) for job_id in ids):
        raise ValueError("nonempty integer ids required")
    if len(set(ids)) != len(ids):
        raise ValueError("duplicate selected id")
    index = {row["id"]: row for row in rows}
    if set(ids) - index.keys():
        raise ValueError("selected id absent from frozen snapshot")
    output = []
    for job_id in ids:
        row = index[job_id]
        source = {key: row.get(key) for key in ("description_text", "description_sections")}
        if mask != "none":
            excluded = sealed_ids(rows, row, MaskMode.SIGNATURE)
            grades = sorted({grade for member in rows if member["id"] in excluded
                             for grade in (member.get("raw_level"), member.get("independent_raw_level"),
                                           stated_level(member["company"], member.get("description_text"))) if grade})
            source = mask_inputs(source, grades, hard=mask == "hard")
            assert_no_grade_leak(source, grades)
        profile = extract_context(source["description_text"], sections=source["description_sections"])
        output.append({"id": job_id, "company": row["company"], "profile": asdict(profile),
                       "missing": list(profile.missing)})
    coverage = Counter(key for row in output for key in FEATURES if row["profile"]["features"][key] is not None)
    return {"version": CONTEXT_VERSION, "mask": mask, "cases": output,
            "coverage": {key: coverage[key] for key in FEATURES}, "postings": len(output),
            "authority": "offline quoted facts only; no inferred band or canonical writes"}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--ids", type=Path, required=True, help="JSON array of frozen posting ids")
    parser.add_argument("--mask", choices=("hard", "realistic", "none"), default="hard")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    rows, source_hash = load_snapshot(args.snapshot)
    ids_content = args.ids.read_bytes()
    ids = json.loads(ids_content)
    if not isinstance(ids, list):
        raise ValueError("ids must be a JSON array")
    result = build_context_rows(rows, ids, mask=args.mask)
    result["inputs"] = {"snapshot_sha256": source_hash, "ids_sha256": hashlib.sha256(ids_content).hexdigest()}
    print(write_artifact(args.out, result))
    print(json.dumps({"postings": result["postings"], "coverage": result["coverage"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
