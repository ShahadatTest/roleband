"""Freeze the relevance eval fixture from the live DB.

One-shot builder for `tests/fixtures/relevance_eval.json` — the authored ground
truth for embedding-model relevance ranking. The DB has no usable behavioural
signal, so labels are hand-authored against real postings; this script
records the exact label spec and freezes the posting TEXTS so the eval runs
without a DB and cannot drift as the corpus changes.

    .venv/bin/python -m scripts.build_relevance_eval          # refuses to overwrite
    .venv/bin/python -m scripts.build_relevance_eval --force  # deliberate re-freeze

Re-freezing changes the benchmark and invalidates every recorded baseline —
do it deliberately, commit the new fixture and re-record baselines in the same
change (an eval that cannot fail measures nothing; one that silently
moves measures less).

Label rules:
- Labels follow the *domain* of the work, not the title (product framing:
  direction-by-domain). A generic title with a domain-specific body is labelled
  by the body — those rows are the long-context hard cases (e.g. microsoft
  "Principal Product Manager" whose body is Microsoft Security).
- `negative_control` is the strict subset of irrelevant rows that share the
  seniority/shape but not the domain (logistics/retail-ops PM rows for
  AI intents; DCEO facilities "data center engineering" for cloud-platform;
  physical-security managers for security engineering). Controls MUST rank
  below relevant rows; the eval counts each violation.
- Genuinely ambiguous rows (AI products *for* warehouse training, robotics NPI)
  are left unlabelled rather than coin-flipped into noise.
- `logistics_ops` is the two-directional control direction: AI rows are its
  negative controls, so a model cannot score well by ranking "impressive" AI
  text first regardless of the query.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from sqlalchemy import text

from tracker.db.session import session_scope

FIXTURE = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "relevance_eval.json"

INTENTS = {
    "ai_frontier": "Building AI products and platforms at the frontier of the field",
    "cloud_platform": "Senior product and engineering leadership for cloud infrastructure and developer platforms",
    "media_streaming": "Product leadership for streaming media and entertainment experiences",
    "logistics_ops": "Leading warehouse operations, logistics and supply chain at scale",
    "security_leadership": "Security engineering leadership and product security",
}

# intent -> {label -> [job_id, ...]}. Hand-authored against real postings.
LABELS: dict[str, dict[str, list[int]]] = {
    "ai_frontier": {
        "relevant": [3790, 1120, 1371, 1553, 931, 934, 935, 936, 937, 3732, 1917, 1034, 2155, 2127, 747],
        "negative_control": [1815, 1684, 2316, 2424, 2607, 2646, 578, 2377, 1857, 1837, 2358, 2564, 1099],
        "irrelevant": [2243, 2080, 3700, 1429, 458, 1073, 2388, 2087],
    },
    "cloud_platform": {
        "relevant": [1792, 1021, 3751, 1034, 2127, 2155, 2353, 993, 2731, 1371],
        "negative_control": [3694, 2407, 3787, 2285, 3706, 2388],
        "irrelevant": [1815, 578, 2243, 1857, 1073, 2080, 458],
    },
    "media_streaming": {
        "relevant": [2228, 3789, 1889, 2017, 2214, 2024, 2483, 1234, 1758, 3700, 3790],
        "negative_control": [1815, 2607, 2377],
        "irrelevant": [1543, 2353, 1112, 2243, 3694, 1789, 2646, 1446, 1591, 1034, 2087],
    },
    "logistics_ops": {
        "relevant": [1815, 1684, 2316, 2607, 2282, 2358, 2564, 2659, 2379, 2646, 1837, 2145, 1845, 3548, 1099, 1073, 2291, 1789, 578, 734],
        "negative_control": [3790, 1553, 931, 2155, 1034, 1371, 1120, 3732],
        "irrelevant": [3789, 1758, 1446, 623, 1543, 3783, 1591, 2139],
    },
    "security_leadership": {
        "relevant": [1591, 3788, 1446, 623, 3783, 1543, 2139, 1144, 1041, 952, 2310, 2581, 128, 249, 2656],
        "negative_control": [2407, 3706, 2285, 3723, 2087, 2311, 2590, 2101],
        "irrelevant": [1889, 1815, 3790, 2646, 2080, 1021, 2377, 1917, 1758],
    },
}


async def build() -> dict:
    ids = sorted({jid for spec in LABELS.values() for jids in spec.values() for jid in jids})
    async with session_scope() as session:
        rows = (
            await session.execute(
                text(
                    "select id, company, title, description_text from jobs "
                    "where id = any(:ids)"
                ),
                {"ids": ids},
            )
        ).all()
    by_id = {r.id: r for r in rows}
    missing = [i for i in ids if i not in by_id or not by_id[i].description_text]
    if missing:
        raise SystemExit(f"jobs missing or without description: {missing}")

    postings = []
    key_by_id: dict[int, str] = {}
    for jid in ids:
        r = by_id[jid]
        key = f"{r.company}-{jid}"
        key_by_id[jid] = key
        postings.append(
            {
                "key": key,
                "source_job_id": jid,
                "company": r.company,
                "title": r.title,
                # Exactly the composition embed_jobs uses.
                "text": f"{r.title or ''}\n{r.description_text or ''}",
            }
        )

    labels = []
    for intent, spec in LABELS.items():
        for jid in spec["relevant"]:
            labels.append({"intent": intent, "posting": key_by_id[jid], "relevant": True, "control": False})
        for jid in spec["negative_control"]:
            labels.append({"intent": intent, "posting": key_by_id[jid], "relevant": False, "control": True})
        for jid in spec["irrelevant"]:
            labels.append({"intent": intent, "posting": key_by_id[jid], "relevant": False, "control": False})

    return {
        "version": 1,
        "frozen_at": "2026-08-15",
        "note": "Authored ground truth for relevance ranking (R0). Texts frozen; do not regenerate casually.",
        "intents": [{"key": k, "statement": v} for k, v in INTENTS.items()],
        "postings": postings,
        "labels": labels,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="overwrite an existing fixture")
    args = parser.parse_args()
    if FIXTURE.exists() and not args.force:
        raise SystemExit(f"{FIXTURE} exists; re-freezing invalidates recorded baselines. Use --force deliberately.")
    fixture = asyncio.run(build())
    FIXTURE.write_text(json.dumps(fixture, indent=1, ensure_ascii=False) + "\n")
    n_pairs = len(fixture["labels"])
    n_controls = sum(1 for lab in fixture["labels"] if lab["control"])
    print(f"wrote {FIXTURE}: {len(fixture['postings'])} postings, {n_pairs} pairs ({n_controls} negative controls)")


if __name__ == "__main__":
    main()
