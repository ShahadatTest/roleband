"""Places excepted inside the included ones.

"The US except New York" saved as the four other US metros would drop every US
role filed at the country itself (remote, towns outside the metros) along with
New York. The exception is stored and read per place: a posting stays
when one of its most specific places is covered by an included place before an
excepted one.

Real places, resolved the way ingest resolves them (`location_slugs_for`), and
real Postgres for the SQL half, which must agree with the Python gate row for
row.
"""

from __future__ import annotations

from datetime import UTC, datetime
from itertools import combinations

import pytest
from sqlalchemy import select

from tracker.db.models import Job
from tracker.db.repo import apply_saved_scope_to_jobs
from tracker.enrich.classify import location_slugs_for
from tracker.enrich.enricher import Annotation, ScopeFilter, passes_filters
from tracker.schema import LevelBand, LevelConfidence, RoleTrack
from tracker.taxonomy.domains import all_slugs as all_domains
from tracker.taxonomy.place_scope import excepted_under, place_admits
from tracker.taxonomy.role_answers import RoleAnswer

#: `PUT /api/settings` starts the directory scan when the set is followed.
pytestmark = pytest.mark.usefixtures("no_escape")

#: posting -> the places it names, as a board writes them
POSTINGS = {
    "nyc": ["New York, NY"],
    "remote_us": ["Remote, United States"],
    "nyc_or_austin": ["New York, NY", "Austin, TX"],
    "nyc_or_london": ["New York, NY", "London, UK"],
    "denver": ["Denver, CO"],
    "london": ["London, UK"],
    "manchester": ["Manchester, UK"],
    "berlin": ["Berlin, Germany"],
}
GROUPS = {key: location_slugs_for(places) for key, places in POSTINGS.items()}
NEW_YORK_CITY = "city_5128581"


def _in(included: set[str], excepted: set[str]) -> set[str]:
    return {key for key, groups in GROUPS.items() if place_admits(groups, included, excepted)}


def test_an_exception_removes_only_the_roles_whose_places_are_all_excepted():
    # The New York role leaves; the remote-US role (filed at the country), a
    # town outside the metros, and a role also offered in Austin all stay.
    assert _in({"united_states"}, {"new_york"}) == {"remote_us", "nyc_or_austin", "denver"}
    # Saving four metros for "every city except New York" keeps neither the
    # remote role nor Denver.
    metros = {"silicon_valley", "pacific_northwest", "austin", "dc_metro"}
    assert _in(metros, set()) == {"nyc_or_austin"}


def test_an_exception_never_admits_a_place_outside_the_included_ones():
    # New York or London, US except New York: London is not asked for.
    assert "nyc_or_london" not in _in({"united_states"}, {"new_york"})
    assert "nyc_or_london" in _in({"united_states", "uk"}, {"new_york"})


def test_the_more_specific_answer_wins():
    # Europe except the UK, but London: London stays, the rest of the UK leaves.
    assert _in({"europe", "london"}, {"uk"}) == {"london", "nyc_or_london", "berlin"}


def test_a_named_city_can_be_excepted():
    # The city itself, inside its metro: the metro's other roles would stay.
    assert _in({"united_states"}, {NEW_YORK_CITY}) == {"remote_us", "nyc_or_austin", "denver"}


def test_with_no_exceptions_the_gate_is_the_plain_overlap():
    places = ["united_states", "new_york", "uk", "london", "europe", "germany", "north_america"]
    for size in (1, 2):
        for included in combinations(places, size):
            for groups in GROUPS.values():
                assert place_admits(groups, set(included), set()) == bool(set(included) & set(groups))


def test_an_exception_outside_every_included_place_is_dropped():
    assert excepted_under({"united_states"}, ["new_york", "london", "united_states"]) == ["new_york"]


T0 = datetime(2026, 9, 26, 12, 0, tzinfo=UTC)
SCENARIOS = [
    ({"united_states"}, {"new_york"}),
    ({"united_states", "uk"}, {"new_york", "london"}),
    ({"europe", "london"}, {"uk"}),
    ({"north_america"}, {"new_york", "austin"}),
    ({"united_states"}, {NEW_YORK_CITY}),
    ({"united_states", "europe"}, set()),
]


def _job(key: str) -> Job:
    return Job(
        company="acme", req_id=key, dedupe_key=f"acme:{key}", title=key,
        url=f"https://careers.example.test/acme/{key}", locations=POSTINGS[key],
        location_groups=GROUPS[key], domains=[], workplace_type="onsite", level_band="staff",
        level_confidence="confirmed", family="software_engineering", track="technical",
        comp_currency="USD", status="open", in_scope=False, first_seen=T0, last_seen=T0,
        description_sections=[],
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(("included", "excepted"), SCENARIOS)
async def test_the_saved_scope_recompute_agrees_with_ingest_row_for_row(db_session, included, excepted):
    db_session.add_all(_job(key) for key in POSTINGS)
    await db_session.commit()
    answers = (RoleAnswer("technical", None),)
    await apply_saved_scope_to_jobs(
        db_session, [], ["staff"], [], sorted(included), all_domains(),
        excluded_domains=[], answers=answers, excluded_locations=sorted(excepted), include_unstated_level=False,
    )
    await db_session.commit()
    in_scope = dict((await db_session.execute(select(Job.req_id, Job.in_scope))).all())
    scope = ScopeFilter(
        enabled_bands=frozenset({"staff"}), enabled_roles=frozenset(), enabled_tracks=frozenset(),
        enabled_locations=frozenset(included), enabled_domains=frozenset(all_domains()),
        answers=answers, excluded_locations=frozenset(excepted),
    )
    for key in POSTINGS:
        annotation = Annotation(
            band=LevelBand.STAFF, confidence=LevelConfidence.CONFIRMED, family="software_engineering",
            location_groups=GROUPS[key], track=RoleTrack.TECHNICAL, domains=[],
        )
        assert in_scope[key] is passes_filters(annotation, scope), key
    assert {key for key, on in in_scope.items() if on} == _in(included, excepted)


@pytest.mark.asyncio
async def test_settings_save_exceptions_prune_and_echo_them(api_client, db_session):
    db_session.add_all(_job(key) for key in POSTINGS)
    await db_session.commit()
    body = {
        "enabled_role_groups": [], "enabled_seniority_bands": ["staff"],
        "enabled_location_groups": ["united_states"],
        "role_answers": [{"track": "technical", "roles": "any"}],
        # London sits under no included place: it means nothing and is dropped.
        "excluded_location_groups": ["new_york", "london"],
    }
    saved = await api_client.put("/api/settings", json=body)
    assert saved.status_code == 200, saved.text
    assert saved.json()["excluded_location_groups"] == ["new_york"]
    assert (await api_client.get("/api/settings")).json()["excluded_location_groups"] == ["new_york"]
    in_scope = dict((await db_session.execute(select(Job.req_id, Job.in_scope))).all())
    assert {key for key, on in in_scope.items() if on} == {"remote_us", "nyc_or_austin", "denver"}

    # Widening the base keeps the exception; removing the place it sits in drops it.
    widened = await api_client.put("/api/settings", json={
        **body, "enabled_location_groups": ["north_america"], "excluded_location_groups": None,
    })
    assert widened.json()["excluded_location_groups"] == ["new_york"]
    moved = await api_client.put("/api/settings", json={
        **body, "enabled_location_groups": ["uk"], "excluded_location_groups": None,
    })
    assert moved.json()["excluded_location_groups"] == []
