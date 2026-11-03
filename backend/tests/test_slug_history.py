"""A category can be added or retired, never silently.

Roles, bands, tracks and locations are stored as what the user switched ON.
New categories therefore arrive off, which is right; a RENAMED or SPLIT
category would arrive off too — whatever the user had on disappears. `slug_history` records
every slug each axis has shipped and what replaced each retired one; these
tests hold the taxonomy to it, and pin how a stored setting is read through it.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

import pytest

from tracker import settings_store
from tracker.config import all_location_group_slugs
from tracker.db.models import AppSetting
from tracker.levels import all_band_slugs
from tracker.taxonomy import slug_history
from tracker.taxonomy.roles import all_slugs
from tracker.taxonomy.tracks import all_track_slugs

CURRENT = {
    "roles": all_slugs,
    "bands": all_band_slugs,
    "tracks": all_track_slugs,
    "locations": all_location_group_slugs,
}


# --- The taxonomy is held to the registry ----------------------------------- #


@pytest.mark.parametrize("axis", slug_history.AXES)
def test_every_category_the_taxonomy_ships_is_recorded(axis):
    """A new category goes in `added` with its date. Unrecorded, nobody could
    tell a user it is new — and the next check could not see it retired."""
    missing = sorted(set(CURRENT[axis]()) - slug_history.known(axis))
    assert not missing, (
        f"{axis}: {missing} shipped without an entry in tracker/taxonomy/slug_history.json "
        f"(`added`: slug -> date). New categories arrive OFF; recording them is what "
        f"lets Settings mark them New."
    )


@pytest.mark.parametrize("axis", slug_history.AXES)
def test_no_category_disappears_without_its_heirs(axis):
    """Made impossible: a slug that leaves the taxonomy must
    name what replaced it (or `[]`, retired on purpose), or every user who had
    it on silently loses it."""
    current = set(CURRENT[axis]())
    gone = sorted(slug_history.known(axis) - current)
    unaccounted = [slug for slug in gone if slug not in slug_history.renamed(axis)]
    assert not unaccounted, (
        f"{axis}: {unaccounted} left the taxonomy with no entry in `renamed`. Name the "
        f"slugs that replace each one, so a user who had it on keeps it."
    )
    for old in gone:
        heirs = slug_history.carry_forward(axis, [old])
        assert heirs <= current, f"{axis}: {old} -> {sorted(heirs - current)}, which do not exist"


def test_the_baseline_is_every_category_as_of_the_freeze():
    """The baseline stands in for the list a user saw before saves recorded it.
    Every current slug is in it or recorded as added since, so nothing is new
    to anyone unless it was added after the freeze."""
    for axis in slug_history.AXES:
        assert set(CURRENT[axis]()) <= slug_history.known(axis), axis
    # The first role type added after the freeze.
    assert set(CURRENT["roles"]()) - slug_history.baseline("roles") == {"operations_facilities"}


# --- Reading a stored setting through the registry -------------------------- #


def test_carry_forward_follows_splits_and_chains_and_survives_a_cycle(monkeypatch):
    monkeypatch.setattr(slug_history, "_axes", lambda: {"bands": {
        "baseline": ["staff", "director_plus"], "added": {},
        "renamed": {"director_plus": ["director", "vp"], "vp": ["vp_plus"],
                    "loop_a": ["loop_b"], "loop_b": ["loop_a"], "gone": []},
    }})
    assert slug_history.carry_forward("bands", ["staff", "director_plus"]) == {"staff", "director", "vp_plus"}
    assert slug_history.carry_forward("bands", ["gone"]) == set()
    assert slug_history.carry_forward("bands", ["loop_a"]) == set()


@dataclass
class _Row:
    value: object


class _Session:
    def __init__(self, value: object | None):
        self.row = _Row(value) if value is not None else None

    async def get(self, model, _key):
        assert model is AppSetting
        return self.row


def _split_director(monkeypatch, current: list[str]) -> None:
    """A future taxonomy that split `director_plus` into two bands."""
    monkeypatch.setattr(slug_history, "_axes", lambda: {"bands": {
        "baseline": ["senior", "staff", "principal", "director_plus"],
        "added": {"director": "2026-10-01", "vp_plus": "2026-10-01", "fellow": "2026-10-01"},
        "renamed": {"director_plus": ["director", "vp_plus"]},
    }})
    monkeypatch.setattr(settings_store, "all_band_slugs", lambda: current)


def test_a_split_category_stays_on_for_everyone_who_had_it_on(monkeypatch):
    current = ["senior", "staff", "principal", "director", "vp_plus", "fellow"]
    _split_director(monkeypatch, current)

    stored = {"slugs": ["staff", "director_plus"]}
    enabled = asyncio.run(settings_store.get_enabled_bands(_Session(stored)))

    assert enabled == {"staff", "director", "vp_plus"}
    assert "fellow" not in enabled  # genuinely new: arrives off


def test_new_is_what_the_user_was_not_shown(monkeypatch):
    current = ["senior", "staff", "principal", "director", "vp_plus", "fellow"]
    _split_director(monkeypatch, current)
    key = settings_store.ENABLED_BANDS_KEY

    def new(value):
        return asyncio.run(settings_store.new_slugs(_Session(value), key, current))

    # Saved before `seen` existed: the baseline is what they saw. The heirs of
    # a category they saw are not new; the one nobody ever showed them is.
    assert new({"slugs": ["staff"]}) == {"fellow"}
    # Saved after: exactly the list recorded at that save.
    assert new({"slugs": ["staff"], "seen": current}) == set()
    assert new({"slugs": ["staff"], "seen": ["senior", "staff", "principal", "director_plus"]}) == {"fellow"}
    # Never saved: on the shipped defaults, so nothing was left out of a choice.
    assert new(None) == set()
    assert new({"slugs": "damaged"}) == set()


def test_the_real_registry_marks_only_what_was_added_since_as_new():
    """A setting saved before `seen` existed saw the baseline: only a category
    added since carries the badge. Operations & facilities is the
    first, the Intern rung the second; every other axis
    shows none. Junior, renamed into Entry, is never new: Entry was seen."""
    added = {"roles": {"operations_facilities"}, "bands": {"intern"}}
    for key, axis in settings_store._AXIS_OF_KEY.items():
        current = list(CURRENT[axis]())
        expected = added.get(axis, set())
        assert asyncio.run(settings_store.new_slugs(_Session({"slugs": current[:1]}), key, current)) == expected, axis


def test_a_saved_junior_choice_reads_as_entry_and_intern_arrives_off():
    """Junior is folded into Entry. A person who chose Junior keeps
    the first full-time rung, and Intern, a new rung, is not switched on for
    anyone: a person starting out is not shown internships unless they say so."""
    bands = all_band_slugs()
    enabled = settings_store._enabled_from(
        {"slugs": ["junior", "mid"], "seen": slug_history.baseline("bands")},
        settings_store.ENABLED_BANDS_KEY, bands, ["senior"],
    )
    assert enabled == {"entry", "mid"}
    assert "junior" not in bands and "intern" in bands


def test_a_persona_saved_at_junior_reads_at_entry():
    persona = settings_store._persona({"experience_stage": "junior", "target_stage": "senior", "intent_statement": ""})
    assert persona == {"experience_stage": "entry", "target_stage": "senior", "intent_statement": ""}

