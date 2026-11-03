"""Tie level, family, location, and comp into an `EnrichedJob`.

Split into a cheap `annotate()` and a separate comp step so the pipeline can
filter *before* paying for description hydration and comp estimates.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from types import SimpleNamespace

from tracker.comp_providers.base import CompContext
from tracker.enrich.classify import classify_domains, classify_family, match_location_groups
from tracker.enrich.comp import OURS, CompResolver, EstimateSet
from tracker.enrich.level_mapper import read_level
from tracker.enrich.track import classify_track
from tracker.levels import INCLUDE_UNSTATED_LEVEL_DEFAULT, all_band_slugs
from tracker.schema import (
    UNPLACED_BASES,
    EnrichedJob,
    LevelBand,
    LevelBasis,
    LevelConfidence,
    RawJob,
    RoleTrack,
)
from tracker.taxonomy.locations import pay_country
from tracker.taxonomy.place_scope import place_admits
from tracker.taxonomy.role_answers import RoleAnswer, answer_admits


@dataclass
class Annotation:
    band: LevelBand
    confidence: LevelConfidence
    family: str | None
    location_groups: list[str]
    track: RoleTrack
    # Every world the posting is about, primary first; [] = honestly
    # unclassified (see classify_domains). Never a guess.
    domains: list[str]
    # What decided `band`; NONE = the posting states no level.
    basis: LevelBasis = LevelBasis.GENERIC


@dataclass(frozen=True)
class ScopeFilter:
    enabled_bands: frozenset[str]
    enabled_roles: frozenset[str]
    enabled_tracks: frozenset[str]
    # Required (no default) so every construction site consciously supplies the
    # locations axis; an empty set fails everything, matching the other axes.
    enabled_locations: frozenset[str]
    # The 5th axis differs from the other four in BOTH empty directions, and
    # deliberately: an unclassified row (ann.domains == []) always
    # passes, because domain classification is best-effort and a title-only
    # company must never lose rows to a silent lexicon; and an empty enabled
    # set means "no domain narrowing" rather than "fail everything", because
    # with fail-open-unknown an empty-fails-classified axis would be an
    # inverse filter no user can ask for. Still required (no default) so every
    # construction site consciously supplies it.
    enabled_domains: frozenset[str]
    # Learned per-company exclusions (company_scope_rules), as
    # (company, kind, lowercased value) triples; kind is "team"|"department".
    # DEFAULTED, unlike the axes above: an axis left unset is a forgotten
    # decision, but an empty rule set is the true state of a system that has
    # not learned any rules, and every construction site is correct with it.
    company_exclusions: frozenset[tuple[str, str, str]] = frozenset()
    # Subjects the user is not interested in: a veto. A row tagged with any of
    # them fails whatever else it is about; an untagged row passes. Defaulted
    # for the same reason as the exclusions above: empty is the true state of
    # an install where nobody has said no to anything.
    excluded_domains: frozenset[str] = frozenset()
    # Which roles of each kind: when set, a posting passes the role
    # part of the gate if SOME answer holds its track, admits its family and
    # its track's level range holds its band, and the two flat axes above are
    # not read for it. None keeps the flat cross product, for a caller that
    # has no answers, such as a test of the other axes.
    answers: tuple[RoleAnswer, ...] | None = None
    # Places excepted inside the included ones, read per place by
    # `place_admits`. Empty = the plain overlap with `enabled_locations`.
    excluded_locations: frozenset[str] = frozenset()
    # Whether a posting that states no level (basis NONE) passes the level
    # axis, both the flat bands and each answer's range. Its stored
    # `mid` is never read as a level.
    include_unstated_level: bool = INCLUDE_UNSTATED_LEVEL_DEFAULT


def rule_excluded(job: RawJob, exclusions: frozenset[tuple[str, str, str]]) -> bool:
    """True when a learned rule names this posting's verbatim team/department.

    Case-insensitive exact match on the employer's own field — never a
    substring, so a rule for team "Ads" cannot swallow "Ads Integrity".
    """
    if not exclusions:
        return False
    for kind, raw_value in (("team", job.team), ("department", job.department)):
        if not raw_value:
            continue
        if (job.company, kind, raw_value.strip().lower()) in exclusions:
            return True
    return False


def annotate(job: RawJob) -> Annotation:
    # Family first: it picks the ladder whose words read the title.
    family = classify_family(job)
    band, confidence, basis = read_level(job, family)
    groups = match_location_groups(job)
    track = classify_track(job.title, family)
    domains = classify_domains(job)
    return Annotation(
        band=band, confidence=confidence, family=family, location_groups=groups,
        track=track, domains=domains, basis=basis,
    )


def reread_level(job: RawJob, ann: Annotation) -> Annotation:
    """`ann` with the level read again from `job` as it is now: after the
    detail read, a posting's stated base range can name the rung its title did
    not (`LevelBasis.PAY_GRADE`). The same annotation when nothing moved."""
    band, confidence, basis = read_level(job, ann.family)
    if (band, confidence, basis) == (ann.band, ann.confidence, ann.basis):
        return ann
    return replace(ann, band=band, confidence=confidence, basis=basis)


def passes_filters(ann: Annotation, scope: ScopeFilter, *, read_place: bool = True) -> bool:
    """Apply the five AND-combined user scope axes (seniority/position/track/location/domain).

    ``read_place=False`` skips the location axis only: "would this posting be
    kept if its place were in scope?", asked before a source spends a request
    naming the place.
    """
    # An empty level axis admits nothing, a posting that states no level
    # included (the SQL gate returns false() for it).
    if not scope.enabled_bands:
        return False
    unstated = ann.basis in UNPLACED_BASES
    if unstated and not scope.include_unstated_level:
        return False
    if not unstated and ann.band.value not in scope.enabled_bands:
        return False
    if scope.answers is not None:
        band = None if unstated else ann.band.value
        if not answer_admits(scope.answers, ann.track.value, ann.family, band):
            return False
    elif ann.family is None or ann.family not in scope.enabled_roles:
        return False
    elif ann.track.value not in scope.enabled_tracks:
        return False
    if read_place and not place_admits(
        ann.location_groups, scope.enabled_locations, scope.excluded_locations
    ):
        return False
    # Domain narrows only when both sides have an opinion (see ScopeFilter).
    if (
        scope.enabled_domains
        and ann.domains
        and not scope.enabled_domains.intersection(ann.domains)
    ):
        return False
    if scope.excluded_domains.intersection(ann.domains):
        return False
    return True


def passes_filters_but_level(ann: Annotation, scope: ScopeFilter) -> bool:
    """`passes_filters` with every band admitted, unstated included: would
    this posting be kept if its level were in scope? A track's own level
    range still applies; it is part of the role, not the person's choice."""
    return passes_filters(ann, replace(
        scope, enabled_bands=frozenset(all_band_slugs()), include_unstated_level=True,
    ))


#: The fields an estimate writes, on `jobs` (the selected source's copy) and on
#: each source's `job_comp_estimate` row.
ESTIMATE_FIELDS = (
    "comp_low",
    "comp_high",
    "comp_median",
    "comp_currency",
    "comp_provenance",
    "comp_base_low",
    "comp_base_median",
    "comp_base_high",
    "comp_component",
    "comp_provider",
    "comp_as_of",
)


def estimate_values(est) -> dict:
    """Every estimate field for one resolved estimate, or the empty one."""
    out: dict = {name: None for name in ESTIMATE_FIELDS}
    out["comp_currency"] = "USD"
    if est is not None:
        holder = SimpleNamespace()
        apply_estimate(holder, est)
        out.update(vars(holder))
    return out


async def build_enriched(
    job: RawJob, ann: Annotation, resolver: CompResolver | EstimateSet | None
) -> EnrichedJob:
    ctx = CompContext(
        company=job.company,
        band=ann.band,
        family=ann.family,
        location_group=ann.location_groups[0] if ann.location_groups else None,
        country=pay_country(ann.location_groups),
        title=job.title,
    )
    # Completed buffers can be retained after a source bound without starting
    # any more network work. Their enrichment is local; estimates are deferred.
    # Ours and the selected plugin's, each from its own data: the job
    # shows the selected one, and neither fills a gap in the other.
    estimates = EstimateSet.of(resolver)
    answers = await estimates.resolve(ctx) if estimates is not None else {}
    primary, sources = answers.get(estimates.selected if estimates else OURS, (None, []))
    enriched = EnrichedJob(
        raw=job,
        level_band=ann.band,
        level_confidence=ann.confidence,
        family=ann.family,
        location_groups=ann.location_groups,
        track=ann.track,
        domains=ann.domains,
        level_basis=ann.basis,
        comp_sources=sources,
        estimated=estimates is not None,
    )
    if estimates is not None:
        # None = not stamped: a resolver outside a run has no reference set.
        enriched.comp_ref_fp = estimates.fingerprint
        enriched.estimates = {
            source: {**estimate_values(est), "sources": answered, "ref_fp": estimates.fingerprints.get(source)}
            for source, (est, answered) in answers.items()
        }
    if primary is not None:
        apply_estimate(enriched, primary)
    return enriched


def apply_estimate(target, est) -> None:
    """Copy one resolved estimate onto a job-shaped object: the pipeline's
    `EnrichedJob` and the re-estimate's stored row take the same fields, so
    the two can never disagree about what an estimate writes."""
    target.comp_low = est.low
    target.comp_high = est.high
    target.comp_median = est.median
    target.comp_currency = est.currency
    target.comp_provenance = est.source
    target.comp_base_low = est.base_low
    target.comp_base_median = est.base_median
    target.comp_base_high = est.base_high
    target.comp_component = est.component
    target.comp_provider = est.provider
    target.comp_as_of = est.as_of
