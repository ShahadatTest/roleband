"""Pre-scope role/seniority inventory: what a company's board contains.

Counting titles and bands is vocabulary work — it needs a posting and its
annotation, and nothing else. Persistence of the tally lives a tier up, in
`scope/catalog_store.py`, beside the read that renders it.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Protocol

from tracker.levels import UNSTATED_LEVEL
from tracker.schema import UNPLACED_BASES, LevelBand, LevelBasis, RawJob, RoleTrack
from tracker.taxonomy.domains import source_category

# Verbatim employer category strings kept per domain — the worlds UI shows the
# text the classifier actually read, so a couple per domain is evidence enough.
MAX_DOMAIN_EXAMPLES = 3
# JSONB key for rows whose classifier honestly said nothing. A first-class
# bucket, not an omission: the fail-open volume must stay visible.
UNCLASSIFIED_KEY = "unclassified"


#: One posting's scope coordinates: (band, track, locations, domains). The two
#: set-valued axes are stored SORTED, because the gate asks them for overlap
#: and never for order — sorting is what collapses two postings with the same
#: coordinates into one cell, and without it `["uk","london"]` and
#: `["london","uk"]` would be two.
ScopeCellKey = tuple[str, str, tuple[str, ...], tuple[str, ...]]


@dataclass
class RoleTally:
    band_counts: Counter[str] = field(default_factory=Counter)
    band_track_counts: dict[str, Counter[str]] = field(default_factory=dict)
    titles: Counter[str] = field(default_factory=Counter)
    # Domain-axis observability: rows count once per matched domain, [] counts
    # under UNCLASSIFIED_KEY. domain_examples holds employer-verbatim category
    # text (department/team), never titles — it is the classifier's evidence.
    domain_counts: Counter[str] = field(default_factory=Counter)
    domain_examples: dict[str, list[str]] = field(default_factory=dict)
    # The JOINT over all four remaining axes, so a scope screen can intersect
    # instead of adding up marginals. `band_counts` and
    # `domain_counts` answer "what would turning this off remove"; only this
    # answers "how many postings pass the whole gate". Multi-label domains make
    # the marginals overlap, which is why summing them is not an alternative.
    scope_cells: Counter[ScopeCellKey] = field(default_factory=Counter)

    @property
    def count(self) -> int:
        return sum(self.band_counts.values())


CatalogTallies = dict[str, RoleTally]


def catalog_collection_error(
    *, errors: list[str], scanned: int, drift_alerts: list[str]
) -> str | None:
    """Reject failed lists while allowing non-fatal detail/hydrate drift."""
    if errors:
        return "; ".join(errors)
    if scanned == 0 and drift_alerts:
        return f"zero-result list drift: {drift_alerts[0]}"
    return None


class CatalogAnnotation(Protocol):
    """What the tally reads off an enrichment result.

    Structural on purpose: `enrich.enricher.Annotation` is what satisfies it,
    but naming that class here would make the vocabulary
    tier import a service tier to describe its own input. The members are real
    L1 types, so this states the contract rather than blurring it.

    This module is outside the mypy typed set, so the Protocol is documentation
    and the gate is `tests/test_role_catalog.py`, which pushes a genuine `annotate()` result
    through `add_to_catalog`.
    """

    band: LevelBand
    track: RoleTrack
    family: str | None
    location_groups: list[str]
    domains: list[str]

    @property
    def basis(self) -> LevelBasis | None: ...


def count_level(ann: CatalogAnnotation) -> str:
    """The level a posting is counted under: its band, or `UNSTATED_LEVEL`
    when it states none. Its stored `mid` is for sorting only, and
    a count under Mid-level would promise a level the title never claimed."""
    return UNSTATED_LEVEL if ann.basis in UNPLACED_BASES else ann.band.value


def catalog_drop_reason(ann: CatalogAnnotation) -> str | None:
    """Why `add_to_catalog` would drop this posting: "unplaced" (no recognised
    place, whatever its family), "unsorted" (a place but no role family), or
    None when it counts. Disjoint, so the two counts add up to the drops."""
    if not ann.location_groups:
        return "unplaced"
    if ann.family is None:
        return "unsorted"
    return None


def add_to_catalog(tallies: CatalogTallies, raw: RawJob, ann: CatalogAnnotation) -> bool:
    """Add one already-deduplicated, location-eligible raw posting.

    False when it cannot be counted: no role family or no recognised place.
    Such a posting can never reach the Board either; callers count the two
    reasons apart (`catalog_drop_reason`) so the screen can say which."""
    if ann.family is None or not ann.location_groups:
        return False
    tally = tallies.setdefault(ann.family, RoleTally())
    level = count_level(ann)
    tally.band_counts[level] += 1
    tally.band_track_counts.setdefault(level, Counter())[ann.track.value] += 1
    # Domains are kept VERBATIM here, empty tuple included: an unclassified row
    # passes the domain axis whatever the user selected (`passes_filters`
    # fail-open), so the cell must be able to say "this row has no domains"
    # rather than borrowing UNCLASSIFIED_KEY, which is a display bucket.
    tally.scope_cells[
        (
            level,
            ann.track.value,
            tuple(sorted(ann.location_groups)),
            tuple(sorted(ann.domains or ())),
        )
    ] += 1
    title = raw.title.strip()
    if title:
        tally.titles[title] += 1
    for domain in ann.domains or [UNCLASSIFIED_KEY]:
        tally.domain_counts[domain] += 1
    category = source_category(raw)
    if category:
        for domain in ann.domains:
            examples = tally.domain_examples.setdefault(domain, [])
            if category not in examples and len(examples) < MAX_DOMAIN_EXAMPLES:
                examples.append(category)
    return True
