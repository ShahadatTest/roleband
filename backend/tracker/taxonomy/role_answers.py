"""Which roles of each kind: the walk's per-answer role choice.

The walk asks one question per kind of role ("lead a team OF engineers",
"hands-on IN software"). An answer is a track with either ANY (every role of
that kind, including families added to the taxonomy later) or the families
picked for it. A posting has exactly one track, so answers are disjoint slices:
adding an answer or a family can only add roles, and a choice under one answer
never touches another. Two flat lists gated as every combination of tracks and
families would let one answer's narrowing rewrite another's. Each answer also
holds its own track's level range (`TRACK_BAND_GATES`), which the gate applies.

The two flat axes are also written, as a projection, for readers of them
(`projection`).
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from tracker.taxonomy.roles import all_slugs as all_family_slugs
from tracker.taxonomy.tracks import all_track_slugs, allowed_bands_for

ANY = "any"


@dataclass(frozen=True)
class RoleAnswer:
    track: str
    #: None = any role of this kind; otherwise the families picked for it.
    families: frozenset[str] | None

    @property
    def any(self) -> bool:
        return self.families is None


def answers_from_axes(tracks: Iterable[str], roles: Iterable[str]) -> tuple[RoleAnswer, ...]:
    """The answers two flat axes mean: every saved track, holding every saved
    family. "Any" when the families are the whole taxonomy. Used by a client
    that still sends the flat axes (Welcome) and by an install that has none."""
    chosen = set(tracks)
    families = set(roles) & set(all_family_slugs())
    held = None if families >= set(all_family_slugs()) else frozenset(families)
    return tuple(
        RoleAnswer(track, held)
        for track in all_track_slugs()
        if track in chosen and (held is None or held)
    )


def parse_answers(value: object) -> tuple[RoleAnswer, ...]:
    """Answers from their stored or sent JSON: `[{"track", "roles": "any" | [..]}]`.

    Unknown tracks and families are dropped; an answer left with no family
    admits nothing, so it is dropped too. Tracks keep taxonomy order, one
    answer per track (the first wins)."""
    if not isinstance(value, list):
        return ()
    valid_families = set(all_family_slugs())
    by_track: dict[str, RoleAnswer] = {}
    for item in value:
        if not isinstance(item, dict):
            continue
        track = item.get("track")
        roles = item.get("roles")
        if not isinstance(track, str) or track in by_track:
            continue
        if roles == ANY:
            by_track[track] = RoleAnswer(track, None)
        elif isinstance(roles, list):
            families = frozenset(r for r in roles if isinstance(r, str) and r in valid_families)
            if families:
                by_track[track] = RoleAnswer(track, families)
    return tuple(by_track[track] for track in all_track_slugs() if track in by_track)


def dump_answers(answers: Sequence[RoleAnswer]) -> list[dict]:
    order = {slug: index for index, slug in enumerate(all_family_slugs())}
    return [
        {
            "track": answer.track,
            "roles": ANY if answer.families is None else sorted(answer.families, key=order.__getitem__),
        }
        for answer in answers
    ]


def answer_admits(
    answers: Sequence[RoleAnswer], track: str, family: str | None, band: str | None
) -> bool:
    """The role part of the gate: some answer holds this track, admits this
    family, and the band is inside that track's level range.

    `band` None is a posting that states no level and that the caller has
    already admitted on the level axis: its stored `mid` is not a
    level, so no track's range is asked about it."""
    if family is None:
        return False
    for answer in answers:
        if answer.track == track:
            in_range = band is None or band in allowed_bands_for(track)
            return (answer.any or family in (answer.families or ())) and in_range
    return False


def projection(answers: Sequence[RoleAnswer]) -> tuple[list[str], list[str]]:
    """The flat (tracks, families) the answers project to, for readers that
    still read the two axes. "Any" projects to every family."""
    tracks = [answer.track for answer in answers]
    families: set[str] = set()
    for answer in answers:
        families |= set(all_family_slugs()) if answer.families is None else answer.families
    return tracks, [slug for slug in all_family_slugs() if slug in families]
