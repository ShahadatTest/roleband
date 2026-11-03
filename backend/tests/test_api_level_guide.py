"""`GET /api/statistics/levels`, the Levels tab's reference read.

Every reviewed ladder answers, followed or not, each cell with every spelling
of the rungs behind its label: a search reads the spellings, never the label,
so a rung the label hides is still found and a range never invents a rung.
"""

from __future__ import annotations

import re

import pytest
import pytest_asyncio

from tracker.company_discovery import COMPANY_DISCOVERY
from tracker.levels.companies import COMPANIES
from tracker.levels.ladder import stage_decoder, walk_guide

pytestmark = [pytest.mark.asyncio, pytest.mark.usefixtures("no_escape")]


@pytest_asyncio.fixture
async def guide(api_client) -> dict:
    response = await api_client.get("/api/statistics/levels")
    assert response.status_code == 200
    return response.json()


def _entries(cell: dict) -> list[dict]:
    return [cell["company_wide"]] if "company_wide" in cell else list(cell["per_track"].values())


async def test_every_reviewed_ladder_answers_with_the_walk_guides_labels(guide):
    companies = {row["slug"]: row for row in guide["companies"]}
    assert list(companies) == sorted(stage_decoder())
    for slug, row in companies.items():
        labels = {
            band: ({"company_wide": cell["company_wide"]["label"]} if "company_wide" in cell
                   else {"per_track": {track: entry["label"] for track, entry in cell["per_track"].items()}})
            for band, cell in row["levels"].items()
        }
        assert labels == walk_guide(slug), slug


async def test_a_cell_holds_exactly_one_key_and_never_a_null(guide):
    for row in guide["companies"]:
        for band, cell in row["levels"].items():
            assert len(cell) == 1 and None not in cell.values(), (row["slug"], band, cell)


async def test_spellings_cover_the_label_they_sit_under(guide):
    # A label is one rung's code, a span "first–last" of two spellings, or
    # "first+": each part it shows is one of the cell's spellings.
    for row in guide["companies"]:
        for cell in row["levels"].values():
            for entry in _entries(cell):
                label, spellings = entry["label"], entry["spellings"]
                parts = [label[:-1]] if label.endswith("+") and label not in spellings else re.split("–", label)
                if label in spellings:
                    parts = [label]
                assert all(part in spellings for part in parts), (row["slug"], entry)


async def test_a_rung_the_label_hides_is_still_spelled(guide):
    nvidia = next(row for row in guide["companies"] if row["slug"] == "nvidia")
    top = nvidia["levels"]["director_plus"]["company_wide"]
    assert top["label"] == "IC7+"
    assert "Distinguished Engineer" in top["spellings"]
    microsoft = next(row for row in guide["companies"] if row["slug"] == "microsoft")
    assert "66" in microsoft["levels"]["principal"]["company_wide"]["spellings"]


async def test_a_range_never_invents_a_rung(guide):
    # Amazon's "L8–L10" spans L8 and L10; Amazon has no L9.
    amazon = next(row for row in guide["companies"] if row["slug"] == "amazon")
    top = amazon["levels"]["director_plus"]["company_wide"]
    assert top["label"] == "L8–L10"
    assert "L9" not in top["spellings"]


async def test_a_split_level_answers_per_track(guide):
    google = next(row for row in guide["companies"] if row["slug"] == "google")
    principal = google["levels"]["principal"]["per_track"]
    assert principal["technical"] == {"label": "L7–L8", "spellings": ["L7", "L8"]}
    assert principal["management"] == {"label": "L7", "spellings": ["L7"]}


async def test_flat_marks_the_ladders_whose_titles_state_no_level(guide):
    flat = {row["slug"] for row in guide["companies"] if row["flat"]}
    assert {"meta", "jane-street", "citadel"} <= flat
    # A ladder that skips a level is not flat: Amazon has no Staff rung.
    assert flat.isdisjoint({"amazon", "google", "apple", "anthropic"})
    assert flat == {
        slug for slug, record in COMPANIES.items()
        if any(ladder.flat for ladder in record.ladders if ladder.guide)
    }


async def test_unguided_names_catalog_companies_only_and_their_shared_ladder(guide):
    unguided = {row["slug"]: row["same_as"] for row in guide["unguided"]}
    guided = {row["slug"] for row in guide["companies"]}
    assert unguided["stripe"] is None
    assert unguided["google-deepmind"] == "google"
    assert guided.isdisjoint(unguided)
    assert set(unguided) <= set(COMPANY_DISCOVERY)
    # A ladder the catalog does not name stays out: the app cannot name it.
    assert "sambanova" not in unguided


async def test_each_track_names_the_levels_it_can_hold(guide):
    assert guide["tracks"]["management"] == ["senior", "staff", "principal", "director_plus"]
    assert guide["tracks"]["technical"][0] == "intern"
