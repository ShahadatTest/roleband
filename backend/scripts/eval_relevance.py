"""Score the current embedding model against the frozen relevance fixture.

Ranking eval, not a unit test: it loads the real embedding model (whatever
`tracker.semantic.embed` is configured to serve), embeds the frozen posting
texts and intent statements through the SAME seams production uses
(`embed_texts` for documents, `embed_query` for statements — so document/query
prefix handling is exercised, not bypassed), and reports per-intent ranking
quality. Never part of pytest; live-model confidence lives in bench scripts
(repo testing policy).

    .venv/bin/python -m scripts.eval_relevance
    .venv/bin/python -m scripts.eval_relevance --save out.json
    .venv/bin/python -m scripts.eval_relevance --baseline tests/fixtures/relevance_eval_baseline_denseon.json

Metrics per intent, all computed from cosine(intent statement, posting):
- auc            P(relevant ranks above irrelevant), all irrelevant rows.
- control_viol   count of (relevant, negative-control) pairs where the control
                 scores >= the relevant row. The hard claim that controls
                 "must rank below", made countable. 0 is the target.
- p_at_5         precision in the top 5 of the intent's labelled pool.

With --baseline the exit code enforces the gate (`gate_failures`): macro
AUC must be >= the baseline's and total control violations <= the baseline's,
and the same two hold for every intent on its own, else exit 1. The baseline
is the production model's own result (DenseOn); the MiniLM file is a second
model's result, kept for comparison.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from itertools import product
from pathlib import Path

FIXTURE = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "relevance_eval.json"


def _auc(pos: list[float], neg: list[float]) -> float:
    """Mann-Whitney AUC: P(pos > neg), ties count half."""
    if not pos or not neg:
        return float("nan")
    wins = sum(1.0 if p > n else 0.5 if p == n else 0.0 for p, n in product(pos, neg))
    return wins / (len(pos) * len(neg))


async def run(fixture: dict) -> dict:
    from tracker.semantic.embed import embed_query, embed_texts

    postings = fixture["postings"]
    doc_vecs = dict(zip((p["key"] for p in postings), embed_texts([p["text"] for p in postings]), strict=True))

    intents = {}
    total_viol = 0
    aucs = []
    for intent in fixture["intents"]:
        qv = await embed_query(intent["statement"])
        labels = [lab for lab in fixture["labels"] if lab["intent"] == intent["key"]]
        scored = [
            (sum(a * b for a, b in zip(qv, doc_vecs[lab["posting"]], strict=True)), lab)
            for lab in labels
        ]
        rel = [s for s, lab in scored if lab["relevant"]]
        irr = [s for s, lab in scored if not lab["relevant"]]
        ctl = [s for s, lab in scored if lab["control"]]
        viol = sum(1 for r, c in product(rel, ctl) if c >= r)
        top5 = sorted(scored, key=lambda t: t[0], reverse=True)[:5]
        auc = _auc(rel, irr)
        aucs.append(auc)
        total_viol += viol
        intents[intent["key"]] = {
            "auc": round(auc, 4),
            "control_violations": viol,
            "control_pairs": len(rel) * len(ctl),
            "p_at_5": round(sum(1 for _, lab in top5 if lab["relevant"]) / 5, 2),
        }

    return {
        "fixture_version": fixture["version"],
        "macro_auc": round(sum(aucs) / len(aucs), 4),
        "total_control_violations": total_viol,
        "intents": intents,
    }


def gate_failures(result: dict, base: dict) -> list[str]:
    """Every way `result` is worse than `base`; empty means the gate passes.

    Macro AUC and the violation total, AND each intent on its own: a macro
    average hides one direction getting worse while another improves, and the
    totals alone would call that a pass. An intent missing from the result
    fails; a result on another fixture version is not comparable at all.
    """
    if result["fixture_version"] != base["fixture_version"]:
        return [f"fixture_version {result['fixture_version']} vs baseline {base['fixture_version']}: not comparable"]
    failures = []
    if result["macro_auc"] < base["macro_auc"]:
        failures.append(f"macro_auc {result['macro_auc']} < {base['macro_auc']}")
    if result["total_control_violations"] > base["total_control_violations"]:
        failures.append(
            f"total_control_violations {result['total_control_violations']} > {base['total_control_violations']}"
        )
    for key, b in base["intents"].items():
        r = result["intents"].get(key)
        if r is None:
            failures.append(f"{key}: missing from the result")
            continue
        if r["auc"] < b["auc"]:
            failures.append(f"{key}: auc {r['auc']} < {b['auc']}")
        if r["control_violations"] > b["control_violations"]:
            failures.append(f"{key}: control_violations {r['control_violations']} > {b['control_violations']}")
    return failures


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--save", type=Path, default=None, help="write the result JSON here")
    parser.add_argument("--baseline", type=Path, default=None, help="compare against a saved result; exit 1 if worse")
    args = parser.parse_args()

    fixture = json.loads(FIXTURE.read_text())
    result = asyncio.run(run(fixture))
    print(json.dumps(result, indent=2))

    if args.save:
        args.save.write_text(json.dumps(result, indent=2) + "\n")
        print(f"saved -> {args.save}")

    if args.baseline:
        base = json.loads(args.baseline.read_text())
        failures = gate_failures(result, base)
        print(
            f"gate vs {args.baseline.name}: macro_auc {result['macro_auc']} vs {base['macro_auc']}, "
            f"violations {result['total_control_violations']} vs {base['total_control_violations']} "
            f"-> {'FAIL' if failures else 'PASS'}"
        )
        for failure in failures:
            print(f"  {failure}")
        raise SystemExit(1 if failures else 0)


if __name__ == "__main__":
    main()
