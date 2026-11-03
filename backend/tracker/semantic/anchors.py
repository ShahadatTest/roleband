"""World-anchor relevance classifier: the relevance advisory in embedding space.

Every posting has a whole-document vector in `jobs.embedding`, and each world in
the taxonomy gets an ANCHOR: the embedding of its display name plus its
`match_domains` lexicon terms, encoded as a query probe into document space.
Classification is nearest-anchor with a margin requirement: fast per row, fully
offline, deterministic, and explainable (the rationale names the anchor and its
vocabulary instead of paraphrasing a model's chain of thought).

Assign the top world iff `cos(top) >= TAU_ACCEPT` AND
`cos(top) - cos(second) >= TAU_MARGIN`, else `uncertain`. `relevance` is whether
the assigned world is tracked. Confidence is margin-derived and monotone: a flat
confidence produced regardless of correctness is not calibrated.

The thresholds are internal and bench-set (never UI), with
`scripts.bench_relevance_review --builtin`. A wider margin raises decided-only
precision but abstains on many more rows. Anchor-to-document cosines are
compressed, so the absolute floor is a degenerate-row guard and the MARGIN
carries the decision.

Every verdict is validated through `RelevanceAssessment`: an unknown world slug
fails closed by construction.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from tracker.intelligence.relevance_review import RelevanceAssessment
from tracker.taxonomy.domains import DOMAIN_GROUPS

#: prompt_version written with anchor verdicts; bumping it re-reviews the corpus.
ANCHOR_PROMPT_VERSION = "relevance_review/emb-v1"

#: provider recorded on verdict rows: no model call happened.
BUILTIN_PROVIDER = "builtin"

# Bench-set internal thresholds (see the module docstring).
TAU_ACCEPT = 0.20
TAU_MARGIN = 0.005

_DISPLAY = {g.slug: g.display for g in DOMAIN_GROUPS}
_KEYWORDS = {g.slug: g.keywords for g in DOMAIN_GROUPS}

# Anchor vectors per (embedding model, artifact tier); anchors are a pure
# function of (model, tier, taxonomy), so process lifetime caching is safe.
# The tier belongs in the key: fp32 and int8 are the same model in *nearly* the
# same space, so anchors cached before a tier switch would be
# compared against freshly re-embedded jobs across that gap — and the process
# outlives the switch.
_cache: dict[tuple[str, str], tuple[tuple[str, ...], list[list[float]]]] = {}


def anchor_text(slug: str) -> str:
    """One world's anchor sentence: display name + its lexicon terms."""
    return f"Roles about {_DISPLAY[slug].lower()}, e.g. {', '.join(_KEYWORDS[slug][:8])}"


def anchor_matrix() -> tuple[tuple[str, ...], list[list[float]]]:
    """(slugs, unit vectors), computed once per (embedding model, tier, taxonomy).

    Raises `provision.ModelNotReady` when weights are not provisioned; the
    caller skips cleanly.
    """
    from tracker.config import get_settings
    from tracker.semantic import provision
    from tracker.semantic.embed import get_model

    key = (get_settings().embedding_model, provision.resolve_tier())
    if key not in _cache:
        slugs = tuple(g.slug for g in DOMAIN_GROUPS)
        vectors = get_model().encode([anchor_text(s) for s in slugs], kind="query")
        _cache[key] = (slugs, vectors)
    return _cache[key]


def classify_scores(
    scores: Mapping[str, float], tracked: frozenset[str] | set[str]
) -> RelevanceAssessment:
    """Pure verdict from per-world cosines. Fail-closed: the assessment is
    built through the validated `RelevanceAssessment` schema, so a score map
    carrying an off-vocabulary slug raises rather than persisting."""
    if len(scores) < 2:
        raise ValueError("need at least two world scores to measure a margin")
    ordered = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    (top_slug, top), (second_slug, second) = ordered[0], ordered[1]
    margin = top - second

    if top_slug not in _DISPLAY or second_slug not in _DISPLAY:
        # Surface the bad slug through the schema's own validator.
        return RelevanceAssessment(
            domain=top_slug if top_slug not in _DISPLAY else second_slug,
            relevance="uncertain", confidence=0.0, rationale="invalid world slug",
        )

    if top < TAU_ACCEPT or margin < TAU_MARGIN:
        return RelevanceAssessment(
            domain=None,
            relevance="uncertain",
            confidence=round(0.2 + min(margin, 0.05) * 4, 2),
            rationale=(
                f"No world is clearly nearest: '{_DISPLAY[top_slug]}' at cosine {top:.2f} "
                f"is only {margin:.3f} ahead of '{_DISPLAY[second_slug]}'."
            ),
        )

    return RelevanceAssessment(
        domain=top_slug,
        relevance="relevant" if top_slug in tracked else "irrelevant",
        confidence=min(0.95, round(0.55 + margin * 4, 2)),
        rationale=(
            f"Nearest world anchor: '{_DISPLAY[top_slug]}' "
            f"(cosine {top:.2f}, margin {margin:.3f} over '{_DISPLAY[second_slug]}'). "
            f"Anchor vocabulary: {', '.join(_KEYWORDS[top_slug][:5])}."
        ),
    )


def classify_embedding(
    embedding: Sequence[float], tracked: frozenset[str] | set[str]
) -> RelevanceAssessment:
    """Verdict for one job vector against the cached anchors."""
    slugs, anchors = anchor_matrix()
    scores = {
        slug: sum(a * b for a, b in zip(anchor, embedding, strict=True))
        for slug, anchor in zip(slugs, anchors, strict=True)
    }
    return classify_scores(scores, tracked)
