"""Benchmark description-signature Jaccard as a duplicate feature.

freehire merges near-duplicates on Jaccard >= 0.9 over each description's word
SET (distinct words longer than three characters), and reports that cosine
failed for them because boilerplate dominates an embedding. This measures that
feature beside the two we already use, on our own pairs, before any detector
reads it:

- `cosine`: the posting embeddings, what lineage proposes on;
- `signature`: freehire's word-set Jaccard, computed here;
- `bag`: `content_diff.compare_descriptions(...).token_similarity`, the twin
  detector's whole-description gate (`twin_text_jaccard_min`).

COHORTS. Human verdicts are the ground truth, and there are few: a confirmed
lineage link is one opening listed twice; a confirmed twin is two openings
with the same text (a rejected lineage link that was then confirmed as a twin
counts once, as a twin). Pending proposals are unlabelled and are reported by
the cosine band the detector sorts them into. Two control arms make the bench
able to fail: same-company, same-role-group postings under different titles
(the hard control: shared boilerplate, different work), and cross-company
postings in one role group (the easy control). If a feature cannot place the
easy control below every human-confirmed opening, the feature or its inputs
are broken, and the run exits 1. If either side of that comparison has no
scored pair, the run exits 3 (unmeasured): a check with nothing to compare
cannot fail, so it cannot pass either.

Read-only. Live DB, so it lives here and not in pytest (`docs/testing.md`:
model and live accuracy are benches); the arithmetic is pinned in
`tests/test_bench_dedup_features.py`.

    python -m scripts.bench_dedup_features
    python -m scripts.bench_dedup_features --controls 800 --list 20
"""

from __future__ import annotations

import argparse
import asyncio
import statistics
import sys
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import text

from tracker.config import get_settings
from tracker.db.session import session_scope
from tracker.lineage.content_diff import compare_descriptions, signature_jaccard

#: Below this share of distinct words, two descriptions are treated as saying
#: different things in the disagreement report. Chosen above the hard-control
#: arm's p90; a report threshold, not a gate.
DISAGREE_BELOW = 0.6

#: The easy control must sit below every confirmed opening this reliably, or
#: the run fails. Cross-company postings share no team, product or req.
EASY_CONTROL_MIN_SEPARATION = 0.95

#: The run's exit when the arm that lets it fail scored nothing: no confirmed
#: opening, or no cross-company control, with a description on both sides. A
#: verdict with nothing on one side is not a pass.
EXIT_UNMEASURED = 3
MEASURED_ARMS = ("same_opening", "control_cross_company")


def lineage_bands() -> tuple[float, float]:
    """The lineage detector's suspect floor and auto-link line, read from the
    settings it runs on (`lineage_cos_suspect`, `lineage_cos_auto`): the band
    where cosine alone sends a link to review, so where a second opinion pays.
    A copy here could report a band the detector does not use."""
    settings = get_settings()
    return settings.lineage_cos_suspect, settings.lineage_cos_auto


FEATURES = ("cosine", "signature", "bag")


def separation(higher: Sequence[float], lower: Sequence[float]) -> float | None:
    """Probability a random `higher` value outranks a random `lower` one (ties
    count half): 1.0 separates perfectly, 0.5 is a coin, 0.0 is inverted. The
    rank form of ROC AUC, exact because the cohorts are small."""
    if not higher or not lower:
        return None
    wins = sum(1.0 if h > lo else 0.5 if h == lo else 0.0 for h in higher for lo in lower)
    return wins / (len(higher) * len(lower))


def spread(values: Sequence[float]) -> str:
    if not values:
        return "n/a"
    v = sorted(values)
    return f"min {v[0]:.2f}  p10 {v[len(v) // 10]:.2f}  p50 {statistics.median(v):.2f}  max {v[-1]:.2f}"


@dataclass(frozen=True)
class Pair:
    cohort: str
    a: int
    b: int
    company: str
    title_a: str
    title_b: str
    cosine: float | None
    signature: float | None
    bag: float | None

    def value(self, feature: str) -> float | None:
        return getattr(self, feature)


_LINEAGE = "select job_id a, prior_job_id b from job_lineage_link where status = '{status}'"
_TWIN = "select job_a_id a, job_b_id b from job_twin_link where status = '{status}'"
_CONTROL = """
    select a.id a, b.id b from jobs a join jobs b
      on a.family = b.family and a.id < b.id and {company}
     and a.description_text is not null and b.description_text is not null
     and a.embedding is not null and b.embedding is not null
   where (a.id * 7919 + b.id) % {modulus} = 1
   limit {limit}
"""


def cohort_queries(controls: int) -> dict[str, str]:
    twins = _TWIN.format(status="confirmed")
    return {
        "same_opening": _LINEAGE.format(status="confirmed"),
        "twin": twins,
        # A rejected link that became a twin is already in `twin`.
        "rejected_not_twin": (
            f"select l.a, l.b from ({_LINEAGE.format(status='rejected')}) l "
            f"where (least(l.a, l.b), greatest(l.a, l.b)) not in (select a, b from ({twins}) t)"
        ),
        "pending_lineage": _LINEAGE.format(status="pending"),
        "pending_twin": _TWIN.format(status="pending"),
        "control_same_company": _CONTROL.format(
            company="a.company = b.company and lower(a.title) <> lower(b.title)",
            modulus=997, limit=controls,
        ),
        "control_cross_company": _CONTROL.format(
            company="a.company <> b.company", modulus=9973, limit=controls,
        ),
    }


async def load_pairs(controls: int) -> list[Pair]:
    pairs: list[Pair] = []
    async with session_scope() as session:
        for cohort, query in cohort_queries(controls).items():
            rows = (await session.execute(text(f"""
                with p as ({query})
                select p.a, p.b, ja.company, ja.title ta, jb.title tb,
                       1 - (ja.embedding <=> jb.embedding) cos,
                       ja.description_text da, jb.description_text db,
                       ja.description_sections sa, jb.description_sections sb
                  from p join jobs ja on ja.id = p.a join jobs jb on jb.id = p.b
            """))).all()
            for r in rows:
                has_both = bool(r.da or r.sa) and bool(r.db or r.sb)
                pairs.append(Pair(
                    cohort=cohort, a=r.a, b=r.b, company=r.company, title_a=r.ta, title_b=r.tb,
                    cosine=float(r.cos) if r.cos is not None else None,
                    signature=signature_jaccard(r.da, r.db),
                    bag=compare_descriptions(r.sa, r.da, r.sb, r.db).token_similarity if has_both else None,
                ))
    return pairs


def comparable(pair: Pair) -> bool:
    """Every feature scored. The features are compared on the SAME pairs: a pair
    one side lacks a description for has no signature, and its embedding was
    built from the title alone, so letting cosine alone count it would compare
    the features on different evidence."""
    return all(pair.value(f) is not None for f in FEATURES)


def values(pairs: list[Pair], cohort: str, feature: str) -> list[float]:
    return [v for p in pairs if p.cohort == cohort and comparable(p) and (v := p.value(feature)) is not None]


def render(pairs: list[Pair], listing: int) -> int:
    cohorts = list(dict.fromkeys(p.cohort for p in pairs))
    count = {c: sum(p.cohort == c for p in pairs) for c in cohorts}
    labelled = count.get("same_opening", 0) + count.get("twin", 0) + count.get("rejected_not_twin", 0)
    print(f"Human-labelled pairs: {labelled} "
          f"(same opening {count.get('same_opening', 0)}, twins {count.get('twin', 0)}, "
          f"other rejections {count.get('rejected_not_twin', 0)})")

    print("\n1. Distributions")
    for cohort in cohorts:
        dropped = sum(p.cohort == cohort and not comparable(p) for p in pairs)
        note = f" ({dropped} without both descriptions, left out)" if dropped else ""
        print(f"  {cohort:22} n={count[cohort] - dropped}{note}")
        for feature in FEATURES:
            print(f"    {feature:9} {spread(values(pairs, cohort, feature))}")

    print("\n2. Separation (1.0 = the first cohort always scores higher)")
    questions = [
        ("same_opening", "twin", "one opening vs two openings with one text"),
        ("same_opening", "control_same_company", "one opening vs same company, other work"),
        ("same_opening", "control_cross_company", "one opening vs another company"),
    ]
    failed = False
    for high, low, meaning in questions:
        row = []
        for feature in FEATURES:
            s = separation(values(pairs, high, feature), values(pairs, low, feature))
            row.append(f"{feature} {'n/a' if s is None else f'{s:.2f}'}")
            if low == "control_cross_company" and s is not None and s < EASY_CONTROL_MIN_SEPARATION:
                failed = True
        print(f"  {meaning:44} {'  '.join(row)}")

    suspect, auto = lineage_bands()
    print(f"\n3. Where the words disagree with the embedding "
          f"(pending lineage, cosine >= {suspect}, signature < {DISAGREE_BELOW})")
    pending = [p for p in pairs if p.cohort == "pending_lineage" and p.cosine is not None]
    high_cos = [p for p in pending if p.cosine >= suspect]
    disagree = [p for p in high_cos if p.signature is not None and p.signature < DISAGREE_BELOW]
    print(f"  {len(disagree)} of {len(high_cos)} high-cosine proposals")
    for lo, hi in ((suspect, auto), (auto, 1.01)):
        band = [p for p in high_cos if lo <= p.cosine < hi]
        n = sum(p.signature is not None and p.signature < DISAGREE_BELOW for p in band)
        print(f"    cosine [{lo:.3f}, {min(hi, 1.0):.3f}): {n} of {len(band)}")
    for p in sorted(disagree, key=lambda p: p.signature or 0)[:listing]:
        print(f"    {p.a}<-{p.b} {p.company:10} cos {p.cosine:.3f} sig {p.signature:.2f}  "
              f"{p.title_a[:48]} | {p.title_b[:48]}")

    missing = [p for p in pairs if p.cohort in ("same_opening", "twin") and not comparable(p)]
    if missing:
        print("\n4. Human-labelled pairs left out: a description is missing on one side")
        for p in missing:
            cos = "n/a" if p.cosine is None else f"{p.cosine:.3f}"
            print(f"    {p.a}<-{p.b} {p.company} ({p.cohort}): cosine now {cos}  {p.title_a[:60]}")

    unmeasured = [arm for arm in MEASURED_ARMS if not any(p.cohort == arm and comparable(p) for p in pairs)]
    if unmeasured:
        print(f"\nUNMEASURED: no scored pairs in {', '.join(unmeasured)}; without both sides the "
              f"control arm cannot fail, so this run is no evidence either way.")
        return EXIT_UNMEASURED
    if failed:
        print(f"\nFAIL: a feature placed another company's posting above a confirmed opening "
              f"more than {1 - EASY_CONTROL_MIN_SEPARATION:.0%} of the time; its inputs are broken.")
        return 1
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--controls", type=int, default=400, help="pairs per control arm")
    parser.add_argument("--list", type=int, default=12, help="disagreeing proposals to print")
    args = parser.parse_args()
    return render(asyncio.run(load_pairs(args.controls)), args.list)


if __name__ == "__main__":
    sys.exit(main())
