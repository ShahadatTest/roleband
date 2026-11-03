"""World-affinity inference: score the candidate's pull toward each world from
signals they already produced, and propose scope adjustments as SUGGESTIONS.

Pure of DB and settings (the workflows wrapper loads signals and persists
suggestions), mirror-tested against the loader the same way `prefilter` is held
to `candidate_stmt`. Every weight surfaces in the suggestion's `basis` so the
UI can say WHY — an unexplainable suggestion teaches the user nothing and earns
no trust.

Standing invariant: inference proposes, the human
disposes. Nothing here writes `enabled_domain_groups`, `jobs.domains`, or
`in_scope`; accepting a suggestion in the API is the only path to any scope
effect. Thresholds carry hysteresis so one dismissal never flips a world.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from tracker.taxonomy.domains import SECTOR_WORLDS, all_slugs, match_domains

# Signal weights. A pursuit outranks a favorite (the
# user acted, not just starred); a "wrong world" dismissal is the strongest
# negative because it names the axis; an unexplained dismissal barely counts —
# it could be about comp, level, or the company.
WEIGHT_FAVORITE = 3.0
WEIGHT_PURSUIT = 4.0
WEIGHT_DISMISS_WRONG_DOMAIN = -4.0
WEIGHT_DISMISS_OTHER = -1.0
WEIGHT_SECTOR = 2.0
WEIGHT_INTENT = 3.0
# A background experience whose title/summary names a world: the
# candidate has actually worked there — stronger than a tracked sector, weaker
# than acting on a live posting.
WEIGHT_BACKGROUND = 2.0

# A world_on proposal needs modest positive evidence; intent + one sector
# already clears it — that is the cold-start story working as designed.
ON_THRESHOLD = 5.0
# A world_off proposal needs strongly negative evidence AND repeated explicit
# "wrong world" dismissals (hysteresis): worlds default all-on and fail open,
# so narrowing is the consequential direction.
OFF_THRESHOLD = -8.0
MIN_OFF_DISMISSALS = 2

SUGGESTION_KINDS = ("world_on", "world_off")


@dataclass(frozen=True)
class WorldSignals:
    """Aggregated per-world event counts plus the two non-event signals."""

    favorited: Mapping[str, int] = field(default_factory=dict)
    pursued: Mapping[str, int] = field(default_factory=dict)
    dismissed_wrong_domain: Mapping[str, int] = field(default_factory=dict)
    dismissed_other: Mapping[str, int] = field(default_factory=dict)
    tracked_sectors: tuple[str, ...] = ()
    intent_statement: str = ""
    # world -> count of active background experiences matching it.
    background: Mapping[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class WorldSuggestion:
    kind: str  # world_on | world_off
    world: str
    score: float
    basis: dict  # JSON-serializable evidence breakdown, shown verbatim in UI

    @property
    def dedupe_key(self) -> str:
        return f"{self.kind}:{self.world}"


def _sector_worlds(tracked_sectors: tuple[str, ...]) -> dict[str, list[str]]:
    """world -> the tracked sectors that evidence it."""
    hits: dict[str, list[str]] = {}
    for sector in tracked_sectors:
        for world in SECTOR_WORLDS.get(sector, ()):
            hits.setdefault(world, []).append(sector)
    return hits


def world_affinities(signals: WorldSignals) -> dict[str, float]:
    """Deterministic affinity score per world. Unknown world keys in the
    signal maps are ignored — the vocabulary owns the axis."""
    sector_hits = _sector_worlds(signals.tracked_sectors)
    intent_worlds = set(match_domains(signals.intent_statement))
    scores: dict[str, float] = {}
    for world in all_slugs():
        scores[world] = (
            signals.favorited.get(world, 0) * WEIGHT_FAVORITE
            + signals.pursued.get(world, 0) * WEIGHT_PURSUIT
            + signals.dismissed_wrong_domain.get(world, 0) * WEIGHT_DISMISS_WRONG_DOMAIN
            + signals.dismissed_other.get(world, 0) * WEIGHT_DISMISS_OTHER
            + len(sector_hits.get(world, [])) * WEIGHT_SECTOR
            + (WEIGHT_INTENT if world in intent_worlds else 0.0)
            + signals.background.get(world, 0) * WEIGHT_BACKGROUND
        )
    return scores


def _basis(signals: WorldSignals, world: str, score: float) -> dict:
    sector_hits = _sector_worlds(signals.tracked_sectors)
    return {
        "score": score,
        "favorited": signals.favorited.get(world, 0),
        "pursued": signals.pursued.get(world, 0),
        "dismissed_wrong_domain": signals.dismissed_wrong_domain.get(world, 0),
        "dismissed_other": signals.dismissed_other.get(world, 0),
        "sectors": sector_hits.get(world, []),
        "intent_matched": world in set(match_domains(signals.intent_statement)),
        "background": signals.background.get(world, 0),
    }


def suggest_worlds(
    signals: WorldSignals, enabled: frozenset[str]
) -> list[WorldSuggestion]:
    """Propose scope adjustments the user may confirm.

    - `world_off`: an enabled world with strongly negative affinity backed by
      repeated explicit wrong-world dismissals.
    - `world_on`: a currently-excluded world with positive affinity — the user
      narrowed it away but their behaviour points back at it.

    No signals -> no suggestions (cold start stays silent; worlds stay all-on).
    """
    scores = world_affinities(signals)
    out: list[WorldSuggestion] = []
    for world in all_slugs():  # taxonomy order, deterministic output
        score = scores[world]
        if (
            world in enabled
            and score <= OFF_THRESHOLD
            and signals.dismissed_wrong_domain.get(world, 0) >= MIN_OFF_DISMISSALS
        ):
            out.append(
                WorldSuggestion("world_off", world, score, _basis(signals, world, score))
            )
        elif world not in enabled and score >= ON_THRESHOLD:
            out.append(
                WorldSuggestion("world_on", world, score, _basis(signals, world, score))
            )
    return out
