"""Remeasure exact salary signatures without connecting to a database.

    .venv/bin/python -m scripts.refresh_level_signatures --snapshot <capture> --cohort <cohort> \\
        --original <baseline> --out <private-json>

Remeasures exact-range title-vocabulary transfer. It requires source identities
and captured descriptions, counts repeated titles and linked openings once, and
quarantines conflicting or ambiguous anchors. Same-employer fuzzy templates
require nested title token sets across every pair in a linked component,
title-token Jaccard of at least 0.6, and pay/code-free text trigram Jaccard of
at least 0.85; short descriptions cannot establish independent support.
Management and sales are excluded. Family and track keys are rebuilt with the
runtime classifiers while captured classifications are retained.

The output reconciles removed proposals, records source hashes and employer
rejection ceilings, and remains a draft requiring source review and the
reference gates before any atlas change. It never writes an atlas table.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from scripts.bench_level_identification import load_snapshot, write_artifact
from tracker.analytics.signature_refresh import assignment, measure, signature_key
from tracker.enrich.classify import classify_family
from tracker.enrich.track import classify_track
from tracker.levels.pay_grades import PAY_BANDS, PAY_GRADES
from tracker.schema import RawJob


def project_context(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Rebuild runtime family/track keys while retaining captured classifications."""
    projected = []
    for row in rows:
        raw = RawJob(company=row["company"], req_id=str(row.get("req_id") or ""),
                     title=row["title"], url="", department=row.get("department"), team=row.get("team"))
        family = classify_family(raw)
        projected.append(row | {"captured_family": row.get("family"), "captured_track": row.get("track"),
                                "family": family, "track": classify_track(raw.title, family).value})
    return projected


def review_proposals(rows: list[dict[str, Any]], targets: list[dict[str, Any]],
                     original: list[dict[str, Any]], measurement: dict[str, Any]) -> dict[str, Any]:
    """Reconcile every old assignment and every new exact-range candidate.

    Mechanical acceptance means eligible for source review, never promotion.
    The employer rejection ceiling counts the whole reconciled proposal set.
    """
    index = {tuple(s["key"]): s for s in measurement["signatures"]}
    groups = {int(key): value for key, value in measurement["groups"].items()}
    captured = {row["id"]: row for row in rows}
    previous = {row["id"]: row for row in original}
    target_index = {row["id"]: row for row in targets}
    if len(previous) != len(original) or len(target_index) != len(targets):
        raise ValueError("duplicate proposal or target identity")
    if set(previous) - set(target_index):
        raise ValueError("original proposal absent from frozen cohort")
    reviews = []
    for job_id, target in target_index.items():
        signature = index.get(signature_key(target))
        capture = captured.get(job_id)
        if capture is None or any(capture.get(k) != target.get(k) for k in (
            "company", "title", "family", "track", "raw_level", "disclosed_base_min", "disclosed_base_max",
        )):
            band, reason = None, "frozen target differs from captured source evidence"
        else:
            band, reason = assignment(target, signature, groups)
        if job_id not in previous and (signature is None or not signature["eligible"]):
            continue
        old = previous.get(job_id)
        reviews.append({
            "id": job_id, "company": target["company"], "title": target["title"],
            "key": list(signature_key(target)), "original": old,
            "candidate_band": band, "decision": "source-review-required" if band else "reject",
            "reason": reason,
            "reconciliation": "addition" if old is None else "removal" if band is None else
                              "unchanged" if band == old["predicted_band"] else "changed",
            "signature": signature,
        })
    companies = {}
    for company in sorted({row["company"] for row in reviews}):
        selected = [row for row in reviews if row["company"] == company]
        rejected = sum(row["decision"] == "reject" for row in selected)
        companies[company] = {"proposals": len(selected), "rejected": rejected,
                              "rejection_share": rejected / len(selected),
                              "ceiling_passes": rejected * 10 <= len(selected)}
    return {"reviews": reviews, "companies": companies,
            "original_count": len(original), "reviewed_original_count": sum(r["original"] is not None for r in reviews),
            "reconciliation": dict(Counter(r["reconciliation"] for r in reviews)),
            "promotion_allowed": False,
            "remaining_gates": ["source review of each surviving assignment and signature",
                                "review real fuzzy-template groups and false-negative sample",
                                "evidence-check, controls and expected moved-posting compare",
                                "backend change-scoped gate"]}


def table_diff(measurement: dict[str, Any]) -> list[dict[str, Any]]:
    candidates: dict[tuple, list[dict]] = defaultdict(list)
    for signature in measurement["signatures"]:
        if signature["eligible"]:
            company, family, _track, year, low, high = signature["key"]
            candidates[(company, family, low, high, year)].append(signature)
    committed = {(row.company, row.family, row.base_min, row.base_max, row.year): row
                 for row in (*PAY_GRADES, *PAY_BANDS)}
    result = []
    for key in sorted(set(candidates) | set(committed), key=str):
        old = committed.get(key)
        new = candidates.get(key, [])
        result.append({"key": list(key), "committed_rung": old.rung if old else None,
                       "committed_band": old.band.value if old and old.band else None,
                       "candidate_signatures": new,
                       "status": "removed" if not new else "added" if old is None else "remeasured",
                       "track_collision": len({s["band"] for s in new}) > 1,
                       "review_required": True})
    return result


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--cohort", type=Path, required=True)
    parser.add_argument("--original", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    rows, snapshot_hash = load_snapshot(args.snapshot)
    cohort_content, original_content = args.cohort.read_bytes(), args.original.read_bytes()
    cohort, original = json.loads(cohort_content), json.loads(original_content)
    rows = project_context(rows)
    targets = project_context(cohort["targets"])
    measurement = measure(rows)
    review = review_proposals(rows, targets, original["proposals"], measurement)
    result = {
        "inputs": {"snapshot": str(args.snapshot), "snapshot_sha256": snapshot_hash,
                   "cohort": str(args.cohort), "cohort_sha256": hashlib.sha256(cohort_content).hexdigest(),
                   "original": str(args.original), "original_sha256": hashlib.sha256(original_content).hexdigest()},
        "context_changes": [
            {key: row.get(key) for key in ("id", "captured_family", "family", "captured_track", "track")}
            for row in rows if row["captured_family"] != row["family"] or row["captured_track"] != row["track"]
        ],
        "mechanism": "title-vocabulary transfer keyed by identical annual US base range",
        "measurement": measurement, "proposal_review": review, "table_diff": table_diff(measurement),
    }
    print(write_artifact(args.out, result))
    print(json.dumps({"proposals": review["reconciliation"], "companies": review["companies"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
