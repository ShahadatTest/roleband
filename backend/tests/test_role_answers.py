"""Which roles of each kind: one answer per track, OR'd.

Two flat lists whose cross product the gate admits would drop TPM and program
roles from BOTH answers to "leading a team of product & program managers" plus
"owning a product, in product management". Answers are disjoint slices of the
market, one per track: the tests below hold the properties a person assumes.

Real Postgres for the SQL half: the OR over answers must agree with the Python
gate row for row, and no answers must admit nothing (a bare `or_()` renders as
no clause at all).
"""

from __future__ import annotations

from datetime import UTC, datetime
from itertools import product

import pytest
from sqlalchemy import select

from tracker.db.models import Job
from tracker.db.repo import apply_saved_scope_to_jobs
from tracker.enrich.enricher import Annotation, ScopeFilter, passes_filters
from tracker.schema import LevelBand, LevelConfidence, RoleTrack
from tracker.taxonomy.domains import all_slugs as all_domains
from tracker.taxonomy.role_answers import (
    RoleAnswer,
    answer_admits,
    answers_from_axes,
    dump_answers,
    parse_answers,
    projection,
)
from tracker.taxonomy.roles import all_slugs as all_families

#: `PUT /api/settings` starts the directory scan when the set is followed.
pytestmark = pytest.mark.usefixtures("no_escape")

PM_FAMILIES = {"product_management", "technical_program_management", "program_management"}
REPORTED = (
    RoleAnswer("management", None),
    RoleAnswer("product_program", frozenset({"product_management"})),
)


def test_the_reported_case_keeps_every_leader_and_only_product_managers():
    # Leading a team, any: every management role at its level range...
    assert answer_admits(REPORTED, "management", "engineering_management", "director_plus")
    assert answer_admits(REPORTED, "management", "sales_business_development", "staff")
    # ...and owning a product, in product management: PM yes, TPM and program no.
    assert answer_admits(REPORTED, "product_program", "product_management", "staff")
    assert not answer_admits(REPORTED, "product_program", "technical_program_management", "staff")
    assert not answer_admits(REPORTED, "product_program", "program_management", "staff")
    # A kind nobody chose admits nothing, whatever its family.
    assert not answer_admits(REPORTED, "technical", "product_management", "staff")
    # A posting with no family is never admitted, even by "any".
    assert not answer_admits(REPORTED, "management", None, "staff")


def test_each_answer_holds_its_own_level_range():
    """Leading a team starts at Senior (TRACK_BAND_GATES), in the gate rather
    than a UI clamp, so a range widened by another answer never admits
    mid-level "managers" (mostly IC titles)."""
    both = (RoleAnswer("management", None), RoleAnswer("technical", None))
    assert not answer_admits(both, "management", "engineering_management", "mid")
    assert answer_admits(both, "management", "engineering_management", "senior")
    assert answer_admits(both, "technical", "software_engineering", "mid")
    # Working with customers tops out at Principal.
    customers = (RoleAnswer("business_customer", None),)
    assert answer_admits(customers, "business_customer", "sales_business_development", "principal")
    assert not answer_admits(customers, "business_customer", "sales_business_development", "director_plus")


FAMILIES = ["engineering_management", "product_management", "software_engineering", "design_ux"]
TRACKS = ["management", "product_program", "technical"]
CHOICES: list[frozenset[str] | None] = [None, frozenset({"software_engineering"}), frozenset({"design_ux", "engineering_management"})]


def _admitted(answers: tuple[RoleAnswer, ...]) -> set[tuple[str, str]]:
    return {(t, f) for t, f in product(TRACKS, FAMILIES) if answer_admits(answers, t, f, "senior")}


def _all_answer_sets():
    options: list[list[RoleAnswer | None]] = [[None, *(RoleAnswer(t, c) for c in CHOICES)] for t in TRACKS]
    for combo in product(*options):
        yield tuple(a for a in combo if a is not None)


def test_adding_an_answer_never_removes_a_role_and_a_change_never_reaches_another_answer():
    """Exhaustive over three tracks x (absent, any, two lists): the properties
    flat axes break."""
    for answers in _all_answer_sets():
        held = {a.track for a in answers}
        before = _admitted(answers)
        for track in TRACKS:
            others_before = {pair for pair in before if pair[0] != track}
            for choice in CHOICES:
                changed = tuple(a for a in answers if a.track != track) + (RoleAnswer(track, choice),)
                after = _admitted(changed)
                # Whatever this answer becomes, no other answer moves.
                assert {pair for pair in after if pair[0] != track} == others_before
                if track not in held:
                    # Adding an answer only adds.
                    assert before <= after


def test_answers_read_off_two_flat_axes_and_project_back():
    assert answers_from_axes(["technical", "management"], all_families()) == (
        RoleAnswer("management", None), RoleAnswer("technical", None),
    )
    held = answers_from_axes(["technical"], ["software_engineering", "nope"])
    assert held == (RoleAnswer("technical", frozenset({"software_engineering"})),)
    assert answers_from_axes(["technical"], []) == ()
    tracks, families = projection(REPORTED)
    assert tracks == ["management", "product_program"]
    assert set(families) == set(all_families())  # "any" projects to every family


def test_answers_survive_their_json_and_refuse_what_they_cannot_mean():
    assert parse_answers(dump_answers(REPORTED)) == REPORTED
    assert parse_answers([
        {"track": "technical", "roles": ["software_engineering", "unknown_family"]},
        {"track": "technical", "roles": "any"},  # a second answer for one track: the first wins
        {"track": "nope", "roles": "any"},  # unknown track dropped
        {"track": "management", "roles": []},  # admits nothing: dropped
        "garbage",
    ]) == (RoleAnswer("technical", frozenset({"software_engineering"})),)


def _scope(answers) -> ScopeFilter:
    return ScopeFilter(
        enabled_bands=frozenset({"mid", "senior", "staff"}),
        enabled_roles=frozenset(),  # ignored when answers are set
        enabled_tracks=frozenset(),
        enabled_locations=frozenset({"uk"}),
        enabled_domains=frozenset(all_domains()),
        answers=answers,
    )


T0 = datetime(2026, 9, 26, 12, 0, tzinfo=UTC)
#: posting -> (track, family, band)
POSTINGS = {
    "em_senior": ("management", "engineering_management", "senior"),
    "em_mid": ("management", "engineering_management", "mid"),
    "sales_mgr_staff": ("management", "sales_business_development", "staff"),
    "pm_staff": ("product_program", "product_management", "staff"),
    "tpm_staff": ("product_program", "technical_program_management", "staff"),
    "swe_staff": ("technical", "software_engineering", "staff"),
    "no_family": ("management", None, "senior"),
}


def _job(key: str, track: str, family: str | None, band: str) -> Job:
    return Job(
        company="acme", req_id=key, dedupe_key=f"acme:{key}", title=key,
        url=f"https://careers.example.test/acme/{key}", locations=["London, UK"],
        location_groups=["uk"], domains=[], workplace_type="onsite", level_band=band,
        level_confidence="confirmed", family=family, track=track, comp_currency="USD",
        status="open", in_scope=False, first_seen=T0, last_seen=T0, description_sections=[],
    )


@pytest.mark.asyncio
async def test_the_saved_scope_recompute_agrees_with_ingest_row_for_row(db_session):
    db_session.add_all(_job(key, *spec) for key, spec in POSTINGS.items())
    await db_session.commit()

    await apply_saved_scope_to_jobs(
        db_session, [], ["mid", "senior", "staff"], [], ["uk"], all_domains(),
        excluded_domains=[], answers=REPORTED, excluded_locations=[], include_unstated_level=False,
    )
    await db_session.commit()
    in_scope = dict((await db_session.execute(select(Job.req_id, Job.in_scope))).all())
    assert in_scope == {
        "em_senior": True, "em_mid": False, "sales_mgr_staff": True,
        "pm_staff": True, "tpm_staff": False, "swe_staff": False, "no_family": False,
    }
    scope = _scope(REPORTED)
    for key, (track, family, band) in POSTINGS.items():
        annotation = Annotation(
            band=LevelBand(band), confidence=LevelConfidence.CONFIRMED, family=family,
            location_groups=["uk"], track=RoleTrack(track), domains=[],
        )
        assert in_scope[key] is passes_filters(annotation, scope), key

    # No answers admit nothing: the OR over zero answers is FALSE, not absent.
    await apply_saved_scope_to_jobs(
        db_session, list(all_families()), ["mid", "senior", "staff"], TRACKS, ["uk"], all_domains(),
        excluded_domains=[], answers=(), excluded_locations=[], include_unstated_level=False,
    )
    await db_session.commit()
    assert not any(dict((await db_session.execute(select(Job.req_id, Job.in_scope))).all()).values())


@pytest.mark.asyncio
async def test_settings_save_answers_echo_them_and_write_the_flat_projection(api_client, db_session):
    db_session.add_all(_job(key, *spec) for key, spec in POSTINGS.items())
    await db_session.commit()
    body = {
        "enabled_role_groups": [], "enabled_seniority_bands": ["mid", "senior", "staff"],
        "enabled_role_tracks": [], "enabled_location_groups": ["uk"],
        "role_answers": dump_answers(REPORTED),
    }
    saved = await api_client.put("/api/settings", json=body)
    assert saved.status_code == 200, saved.text
    payload = saved.json()
    assert payload["role_answers"] == [
        {"track": "management", "roles": "any"},
        {"track": "product_program", "roles": ["product_management"]},
    ]
    # The flat fields are the projection, whatever the request carried in them.
    assert payload["enabled_role_tracks"] == ["management", "product_program"]
    assert set(payload["enabled_role_groups"]) == set(all_families())
    assert (await api_client.get("/api/settings")).json()["role_answers"] == payload["role_answers"]
    in_scope = dict((await db_session.execute(select(Job.req_id, Job.in_scope))).all())
    assert {key for key, on in in_scope.items() if on} == {"em_senior", "sales_mgr_staff", "pm_staff"}

    # A client that sends only the flat fields gets answers read off them.
    flat = await api_client.put("/api/settings", json={
        **{k: v for k, v in body.items() if k != "role_answers"},
        "enabled_role_tracks": ["technical"], "enabled_role_groups": ["software_engineering"],
    })
    assert flat.json()["role_answers"] == [{"track": "technical", "roles": ["software_engineering"]}]
