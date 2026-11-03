"""The leveling model (vocabulary tier; pure, no DB, no network).

This module: the bands a person can choose (``LEVELS``) layered over
``LevelBand``. The package holds every per-company leveling
and pay fact, each stated once:

- ``companies``: each company's ladders, one ``Rung`` per rung (band, codes,
  seed pay, bonus target), and the codes it prints on postings.
- ``ladder``: questions over the rungs (``band_for``, ``rung_for_band``, the
  Walk guide's cells).
- ``titles``: how a company's titles name its rungs, per family ladder.
- ``pay_grades``: posted base ranges the company pays at one rung.
- ``words``: banding a rung label nobody wrote a rung for.
- ``vocabulary``: the generic seniority words and their whole-word match,
  read by ``words`` and by the posting level mapper alike.
- ``pay``: how each company builds an offer, and the pay a band reads.

Nothing outside this package declares a per-company leveling or pay fact.
"""

from __future__ import annotations

from dataclasses import dataclass

from tracker.schema import LevelBand


@dataclass(frozen=True)
class LevelDefinition:
    slug: str
    display: str
    order: int
    default_enabled: bool


# A full-market ladder: every stage is a first-class rung, no stage is defined
# as "below" another. Defaults reflect the shipped persona; all are selectable.
LEVELS: tuple[LevelDefinition, ...] = (
    # Internships are their own rung so a person starting out is not shown
    # them; Junior is part of Entry, the first full-time rung.
    LevelDefinition(LevelBand.INTERN.value, "Intern", 0, False),
    LevelDefinition(LevelBand.ENTRY.value, "Entry / Junior", 1, False),
    LevelDefinition(LevelBand.MID.value, "Mid-level", 2, False),
    LevelDefinition(LevelBand.SENIOR.value, "Senior", 3, True),
    LevelDefinition(LevelBand.STAFF.value, "Staff", 4, True),
    LevelDefinition(LevelBand.PRINCIPAL.value, "Principal", 5, True),
    LevelDefinition(LevelBand.DIRECTOR_PLUS.value, "Director+", 6, True),
)

_BY_SLUG = {level.slug: level for level in LEVELS}

#: The count key for a posting that states no level (`LevelBasis.NONE`).
#: Not a level and never in `LEVELS`: its stored band is `mid` for
#: sorting only, so a count keyed by band would file it under Mid-level and the
#: level step would promise mid roles the title never claimed.
UNSTATED_LEVEL = "unstated"

#: Whether roles whose level isn't stated pass the level axis when the user
#: has not said: on, since the company family ladders leave few roles
#: unstated. The dashboard holds the same value; `tests/fixtures/level_basis_gate.json` binds the two.
INCLUDE_UNSTATED_LEVEL_DEFAULT = True


def all_band_slugs() -> list[str]:
    return [level.slug for level in LEVELS]


def default_enabled_bands() -> list[str]:
    return [level.slug for level in LEVELS if level.default_enabled]


def get_level(slug: str) -> LevelDefinition | None:
    return _BY_SLUG.get(slug)
