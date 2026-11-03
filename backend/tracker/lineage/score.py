"""Pure scoring for a candidate repost/duplicate pair.

A decision TREE, not a weighted sum: the review UI has to explain every verdict to
a human, and the standing repo rule is "the model proposes, deterministic
code verifies." These rules are the verifier.

Nothing here touches the DB or the disclosed-comp ESTIMATE. The estimate is a static
company x level lookup, identical for every candidate that passes the same-company/
same-level gate, so it carries zero discriminating power and is deliberately absent.
The DISCLOSED band enters only as ``band_relation`` (computed in detect.py) and is
used as counter-evidence: disjoint comparable bands and period mismatch reject;
overlap never boosts (published bands are level-and-locale-wide).
"""

from __future__ import annotations

from dataclasses import dataclass, field

#: The gate reason for a pair inside one place set.
SAME_PLACE_SET_REASON = "the same role, listed once per place"
#: The gate reason for a pair a person answered in the twin queue as "Related
#: roles" or "Different": never proposed again as one opening.
HUMAN_SAID_NOT_ONE_OPENING = "a person decided these are not one opening"


@dataclass(frozen=True)
class LineageThresholds:
    # Defaults mirror config.py's values, calibrated for the configured
    # `embedding_model`; config is what production reads: keep the two in lockstep.
    cos_auto: float = 0.955
    cos_title_equal: float = 0.82
    cos_suspect: float = 0.915
    cos_floor: float = 0.89
    jaccard_suspect: float = 0.75
    location_jaccard_min: float = 0.50
    duplicate_auto: bool = False
    max_size: int = 6
    word_overlap_min: float = 0.6


@dataclass(frozen=True)
class Candidate:
    job_id: int
    prior_job_id: int
    cosine: float
    title_display_equal: bool
    title_equal: bool
    title_jaccard: float
    title_grade_compatible: bool
    # True when the prior posting was still live at the moment this posting
    # appeared (their lifetimes overlapped) -> a concurrent DUPLICATE listing.
    # False -> the prior had closed before this appeared -> a true REPOST.
    concurrent: bool
    gap_days: int | None
    location_overlap: bool
    both_locations_empty: bool
    location_jaccard: float
    same_family: bool
    same_level_band: bool
    prior_lineage_size: int
    has_descriptions: bool
    band_relation: str           # unknown | overlap | disjoint | period_mismatch
    # Share of distinct description words the two postings have in common
    # (`content_diff.signature_jaccard`); None when either lacks a description.
    word_overlap: float | None = None
    # Both postings are one role listed once per place: a sibling,
    # never a predecessor, whatever the cosine says.
    same_place_set: bool = False
    # A person answered the pair in the twin queue: twins, or different roles.
    # Their word outranks every score.
    human_said_not_one_opening: bool = False


@dataclass(frozen=True)
class Verdict:
    decision: str                # auto | suspected | reject
    relation: str                # repost | duplicate
    score: float
    method: str                  # title+embedding | embedding | title_jaccard | gate
    reasons: list[str] = field(default_factory=list)


def _relation(c: Candidate) -> str:
    return "duplicate" if c.concurrent else "repost"


def score_pair(c: Candidate, cfg: LineageThresholds) -> Verdict:
    relation = _relation(c)

    # --- GATES: any failure -> reject outright -------------------------------
    if c.human_said_not_one_opening:
        return Verdict("reject", relation, c.cosine, "gate", [HUMAN_SAID_NOT_ONE_OPENING])
    if c.same_place_set:
        return Verdict("reject", relation, c.cosine, "gate", [SAME_PLACE_SET_REASON])
    if not c.same_family:
        return Verdict("reject", relation, c.cosine, "gate", ["family mismatch"])
    if not c.same_level_band:
        return Verdict("reject", relation, c.cosine, "gate", ["level_band mismatch"])
    if relation == "duplicate" and not c.title_display_equal:
        return Verdict(
            "reject", relation, c.cosine, "gate",
            ["concurrent listings require identical normalized titles"],
        )
    if not (c.location_overlap or (c.both_locations_empty and c.title_equal)):
        return Verdict("reject", relation, c.cosine, "gate", ["no location overlap"])
    if not c.both_locations_empty and c.location_jaccard < cfg.location_jaccard_min:
        return Verdict("reject", relation, c.cosine, "gate", ["location overlap too small"])
    if not c.title_grade_compatible:
        return Verdict("reject", relation, c.cosine, "gate", ["explicit title grade mismatch"])
    if not c.title_equal and c.title_jaccard < cfg.jaccard_suspect:
        return Verdict("reject", relation, c.cosine, "gate", ["title overlap below review threshold"])
    if not (c.has_descriptions or c.title_equal):
        # title-only embeddings are inflated; refuse to auto-infer from them.
        return Verdict("reject", relation, c.cosine, "gate", ["no descriptions and titles differ"])
    if c.band_relation == "period_mismatch":
        return Verdict("reject", relation, c.cosine, "gate", ["pay stated per different periods"])
    if c.band_relation == "disjoint":
        return Verdict("reject", relation, c.cosine, "gate", ["comparable disclosed pay bands do not overlap"])

    # --- DECIDE --------------------------------------------------------------
    reasons: list[str] = []
    if c.title_equal and c.cosine >= cfg.cos_title_equal:
        decision, method = "auto", "title+embedding"
        reasons.append(f"normalized titles identical; cosine {c.cosine:.2f} >= {cfg.cos_title_equal}")
    elif c.cosine >= cfg.cos_auto:
        decision, method = "auto", "embedding"
        reasons.append(f"cosine {c.cosine:.2f} >= {cfg.cos_auto}")
    elif c.cosine >= cfg.cos_suspect:
        decision, method = "suspected", "embedding"
        reasons.append(f"cosine {c.cosine:.2f} in review band [{cfg.cos_suspect}, {cfg.cos_auto})")
    elif c.title_jaccard >= cfg.jaccard_suspect and c.cosine >= cfg.cos_floor:
        decision, method = "suspected", "title_jaccard"
        reasons.append(
            f"title jaccard {c.title_jaccard:.2f} >= {cfg.jaccard_suspect} with cosine {c.cosine:.2f}"
        )
    else:
        return Verdict("reject", relation, c.cosine, "embedding",
                       [f"cosine {c.cosine:.2f} below floor {cfg.cos_floor}"])

    # --- DEMOTIONS: auto -> suspected (never the reverse) --------------------
    def demote(reason: str) -> None:
        nonlocal decision
        if decision == "auto":
            decision = "suspected"
        reasons.append(reason)

    if relation == "duplicate" and not cfg.duplicate_auto:
        demote("prior still open (duplicate listing) — human review")
    if c.prior_lineage_size >= cfg.max_size:
        demote(f"prior lineage already {c.prior_lineage_size} deep")
    # Identical titles below the embedding-only bar, over descriptions that
    # share few words: the title is generic and the work may differ.
    # Demote only: a review, never a reject.
    if (
        method == "title+embedding"
        and c.cosine < cfg.cos_auto
        and c.word_overlap is not None
        and c.word_overlap < cfg.word_overlap_min
    ):
        demote(
            f"titles identical but descriptions share {c.word_overlap:.0%} of their words "
            f"(under {cfg.word_overlap_min:.0%}), human review"
        )

    return Verdict(decision, relation, c.cosine, method, reasons)
