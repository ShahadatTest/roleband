"""User-selectable role-track taxonomy layered over ``RoleTrack``.

The track axis separates managerial from purely technical roles. It cross-cuts the
role-group (domain) and seniority (level) axes, so it is its own scope dimension.
Mirrors ``tracker/levels``.
"""

from __future__ import annotations

from dataclasses import dataclass

from tracker.levels import all_band_slugs
from tracker.schema import LEVEL_BAND_ORDER, LevelBand, RoleTrack


@dataclass(frozen=True)
class TrackDefinition:
    slug: str
    display: str
    order: int
    default_enabled: bool


TRACKS: tuple[TrackDefinition, ...] = (
    TrackDefinition(RoleTrack.MANAGEMENT.value, "Management / Leadership", 0, True),
    TrackDefinition(RoleTrack.PRODUCT_PROGRAM.value, "Product & Program", 1, True),
    TrackDefinition(RoleTrack.TECHNICAL.value, "Technical (IC)", 2, True),
    TrackDefinition(RoleTrack.BUSINESS_CUSTOMER.value, "Business & Customer (IC)", 3, True),
)

# Realistic seniority range (floor, ceiling) each track can occupy, grounded in
# market leveling reality. Tiers outside the range are disabled in
# the scope wizard so we don't offer nonsensical choices:
#   - Management: no intern/new-grad/mid people-managers; first-line EM ~ Google L6.
#   - Product & Program: internships and APM/RPM new-grad programs are real, so
#     floor=intern.
#   - Technical (IC): full ladder; director+ IC = Distinguished Engineer / Fellow.
#   - Business & Customer (IC): tops out at Principal; director+ there is management.
# Every gate is a contiguous [floor, ceiling]; the wizard shows the union across
# selected tracks (which stays contiguous). Google/Amazon numeric levels are
# function-agnostic, so these gates are an honesty aid, not a hard market law.
TRACK_BAND_GATES: dict[str, tuple[LevelBand, LevelBand]] = {
    RoleTrack.MANAGEMENT.value: (LevelBand.SENIOR, LevelBand.DIRECTOR_PLUS),
    RoleTrack.PRODUCT_PROGRAM.value: (LevelBand.INTERN, LevelBand.DIRECTOR_PLUS),
    RoleTrack.TECHNICAL.value: (LevelBand.INTERN, LevelBand.DIRECTOR_PLUS),
    RoleTrack.BUSINESS_CUSTOMER.value: (LevelBand.INTERN, LevelBand.PRINCIPAL),
}


def allowed_bands_for(track_slug: str) -> list[str]:
    """Contiguous band slugs a track can occupy (floor..ceiling, in ladder order).

    Unknown tracks are ungated (full ladder), so a new track is permissive until
    its gate is defined.
    """
    gate = TRACK_BAND_GATES.get(track_slug)
    if gate is None:
        return all_band_slugs()
    lo, hi = LEVEL_BAND_ORDER[gate[0].value], LEVEL_BAND_ORDER[gate[1].value]
    return [slug for slug in all_band_slugs() if lo <= LEVEL_BAND_ORDER[slug] <= hi]


_BY_SLUG = {track.slug: track for track in TRACKS}


def all_track_slugs() -> list[str]:
    return [track.slug for track in TRACKS]


def default_enabled_tracks() -> list[str]:
    # All tracks on by default -> the axis is a no-op until the user narrows it.
    return [track.slug for track in TRACKS if track.default_enabled]


