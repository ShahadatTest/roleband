"""Place sets over real Postgres: the text identity is SQL, the
withdrawal is a join, and a person's verdict must survive the rebuild."""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import event, func, select, text

from tests.place_set_rows import BODY, NOW, pending_duplicate, place_set_job
from tracker.db.models import Job, JobLineageLink, JobPlaceSet, JobPlaceSetMember, JobTwinLink
from tracker.lineage import detect as detect_module
from tracker.lineage import place_sets as place_sets_module
from tracker.lineage.detect import detect_lineage, fetch_candidates
from tracker.lineage.place_sets import (
    NotAMember,
    rebuild_place_sets,
    review_place_set_member,
    still_listed_elsewhere,
)
from tracker.lineage.score import SAME_PLACE_SET_REASON

pytestmark = pytest.mark.asyncio


#: More than `explained_text.MAX_OTHER_WORDS` words of other duties: the
#: same title over a different job (kept a question).
OTHER_DUTIES = (
    "You will also own the rail signalling programme end to end, run the supplier "
    "framework for track renewals, and report weekly to the network operator on "
    "possession planning and safety assurance."
)


async def _members(session) -> dict[int, tuple[int | None, str]]:
    rows = (await session.execute(select(JobPlaceSetMember))).scalars().all()
    return {m.job_id: (m.set_id, m.status) for m in rows}


async def test_one_role_in_three_cities_becomes_one_set_and_leaves_the_queue(db_session):
    london = await place_set_job(db_session, 1, "London")
    bristol = await place_set_job(db_session, 2, "Bristol")
    st_albans = await place_set_job(db_session, 3, "St Albans")
    closed = await place_set_job(db_session, 4, "Leeds", status="closed")
    other_role = await place_set_job(db_session, 5, "Leeds", title="Project Director - Rail")
    db_session.add_all(
        [
            pending_duplicate(st_albans, london),
            pending_duplicate(bristol, london),
            # Not between two members: stays.
            pending_duplicate(other_role, london),
        ]
    )
    await db_session.commit()

    summary = await rebuild_place_sets(db_session)

    assert summary["sets"] == 1 and summary["members"] == 3
    assert summary["withdrawn_lineage"] == 2
    place_set = (await db_session.execute(select(JobPlaceSet))).scalar_one()
    assert place_set.places == ["London, UK", "Bristol, UK", "St Albans, UK"]
    assert place_set.size == 3
    members = await _members(db_session)
    assert set(members) == {london.id, bristol.id, st_albans.id}
    assert closed.id not in members
    links = (await db_session.execute(select(JobLineageLink))).scalars().all()
    assert [(link.job_id, link.prior_job_id) for link in links] == [(other_role.id, london.id)]


async def test_the_rebuild_is_idempotent_and_keeps_the_set_id(db_session):
    await place_set_job(db_session, 1, "London")
    await place_set_job(db_session, 2, "Bristol")
    await db_session.commit()
    await rebuild_place_sets(db_session)
    first = (await db_session.execute(select(JobPlaceSet.id))).scalar_one()
    again = await rebuild_place_sets(db_session)
    assert again["memberships_dropped"] == 0 and again["sets_dropped"] == 0
    assert (await db_session.execute(select(JobPlaceSet.id))).scalar_one() == first


async def _written(session) -> tuple[dict, dict]:
    """Each set (id, size, updated_at, last writer) and each membership (set, last writer)."""
    sets = (
        await session.execute(
            text("SELECT id, size, updated_at, xmin::text AS writer FROM job_place_set")
        )
    ).all()
    members = (
        await session.execute(
            text("SELECT job_id, set_id, xmin::text AS writer FROM job_place_set_member")
        )
    ).all()
    return (
        {s.id: (s.size, s.updated_at, s.writer) for s in sets},
        {m.job_id: (m.set_id, m.writer) for m in members},
    )


async def test_a_rebuild_that_changes_nothing_rewrites_no_set_or_membership(db_session):
    london = await place_set_job(db_session, 1, "London")
    bristol = await place_set_job(db_session, 2, "Bristol")
    await db_session.commit()
    await rebuild_place_sets(db_session)
    sets, members = await _written(db_session)
    assert set(members) == {london.id, bristol.id}

    await rebuild_place_sets(db_session)
    assert await _written(db_session) == (sets, members)

    # A real change still writes, and only what it changed.
    leeds = await place_set_job(db_session, 3, "Leeds")
    await db_session.commit()
    await rebuild_place_sets(db_session)
    after_sets, after_members = await _written(db_session)
    ((set_id, (size, updated_at, _)),) = sets.items()
    assert list(after_sets) == [set_id]
    assert after_sets[set_id][0] == 3 and after_sets[set_id][1] > updated_at
    assert after_members[leeds.id][0] == set_id
    assert {j: after_members[j] for j in (london.id, bristol.id)} == {
        j: members[j] for j in (london.id, bristol.id)
    }


async def test_whitespace_and_case_are_not_a_different_text_but_a_level_word_is(db_session):
    # A few reworded words get through; a word that changes the
    # level of the team never is one of them.
    await place_set_job(db_session, 1, "London")
    await place_set_job(db_session, 2, "Bristol", body="  " + BODY.upper().replace(" ", "\n\t "))
    await place_set_job(db_session, 3, "Leeds", body=BODY.replace("team of analysts", "team of senior analysts"))
    await db_session.commit()
    await rebuild_place_sets(db_session)
    assert len(await _members(db_session)) == 2


async def test_a_thin_description_is_no_identity_evidence(db_session):
    stub = "Apply on our careers site." * 3
    await place_set_job(db_session, 1, "London", body=stub)
    await place_set_job(db_session, 2, "Bristol", body=stub)
    await db_session.commit()
    assert (await rebuild_place_sets(db_session))["sets"] == 0


async def test_a_pair_a_person_decided_is_never_overruled(db_session):
    london = await place_set_job(db_session, 1, "London")
    bristol = await place_set_job(db_session, 2, "Bristol")
    db_session.add(
        pending_duplicate(
            bristol, london, status="rejected", evidence={"review_outcome": "twin"}
        )
    )
    await db_session.commit()
    summary = await rebuild_place_sets(db_session)
    assert summary["sets"] == 0
    assert list(summary["skipped"]) == ["a person already decided a pair of these postings"]
    link = (await db_session.execute(select(JobLineageLink))).scalar_one()
    assert link.status == "rejected"


async def test_a_pending_twin_between_members_is_withdrawn_and_a_confirmed_one_blocks(db_session):
    a = await place_set_job(db_session, 1, "London")
    b = await place_set_job(db_session, 2, "Bristol")
    twin = JobTwinLink(
        job_a_id=a.id, job_b_id=b.id, method="content_overlap", confidence="suspected",
        status="pending", detector_version="twin/v1", evidence={},
    )
    db_session.add(twin)
    await db_session.commit()
    assert (await rebuild_place_sets(db_session))["withdrawn_twins"] == 1

    db_session.add(
        JobTwinLink(
            job_a_id=a.id, job_b_id=b.id, method="manual", confidence="suspected",
            status="confirmed", detector_version="twin/v1", evidence={},
        )
    )
    await db_session.commit()
    assert (await rebuild_place_sets(db_session))["sets"] == 0


async def test_different_roles_splits_a_posting_out_and_survives_the_rebuild(db_session):
    london = await place_set_job(db_session, 1, "London")
    bristol = await place_set_job(db_session, 2, "Bristol")
    leeds = await place_set_job(db_session, 3, "Leeds")
    await db_session.commit()
    await rebuild_place_sets(db_session)

    state = await review_place_set_member(db_session, bristol.id, "different")
    assert state["set"] is None and state["rejected"] is True
    await rebuild_place_sets(db_session)
    members = await _members(db_session)
    assert members[bristol.id][1] == "rejected"
    assert {k for k, (_, s) in members.items() if s == "auto"} == {london.id, leeds.id}
    assert (await db_session.execute(select(JobPlaceSet.size))).scalar_one() == 2

    back = await review_place_set_member(db_session, bristol.id, "pending")
    assert back["set"] is not None and set(back["set"]["member_ids"]) == {
        london.id, bristol.id, leeds.id,
    }


async def test_splitting_one_of_two_dissolves_the_set_but_keeps_the_verdict(db_session):
    london = await place_set_job(db_session, 1, "London")
    bristol = await place_set_job(db_session, 2, "Bristol")
    await db_session.commit()
    await rebuild_place_sets(db_session)
    await review_place_set_member(db_session, london.id, "different")
    assert await db_session.scalar(select(func.count()).select_from(JobPlaceSet)) == 0
    members = await _members(db_session)
    assert members == {london.id: (None, "rejected")}
    assert bristol.id not in members


async def test_a_verdict_needs_a_posting_in_the_matching_state(db_session):
    lone = await place_set_job(db_session, 1, "London")
    await db_session.commit()
    with pytest.raises(NotAMember):
        await review_place_set_member(db_session, lone.id, "different")
    with pytest.raises(NotAMember):
        await review_place_set_member(db_session, lone.id, "pending")


async def test_the_lineage_detector_rejects_a_pair_inside_one_set(db_session):
    london = await place_set_job(db_session, 1, "London")
    bristol = await place_set_job(db_session, 2, "Bristol")
    await db_session.commit()

    before = {sc.candidate.prior_job_id: sc for sc in await fetch_candidates(db_session, bristol, k=5)}
    assert SAME_PLACE_SET_REASON not in before[london.id].verdict.reasons

    await rebuild_place_sets(db_session)
    after = {sc.candidate.prior_job_id: sc for sc in await fetch_candidates(db_session, bristol, k=5)}
    assert after[london.id].verdict.decision == "reject"
    assert after[london.id].verdict.reasons == [SAME_PLACE_SET_REASON]


async def test_the_routes_serve_the_set_and_take_a_verdict(api_client, db_session):
    london = await place_set_job(db_session, 1, "London")
    bristol = await place_set_job(db_session, 2, "Bristol")
    lone = await place_set_job(db_session, 3, "Leeds", title="Project Director - Rail")
    await db_session.commit()
    await rebuild_place_sets(db_session)

    read = await api_client.get(f"/api/jobs/{bristol.id}/place-set")
    assert read.status_code == 200, read.text
    body = read.json()
    assert body["place_set"]["places"] == ["London, UK", "Bristol, UK"]
    assert [(m["job"]["id"], m["is_this"]) for m in body["place_set"]["members"]] == [
        (london.id, False),
        (bristol.id, True),
    ]
    detail = (await api_client.get(f"/api/jobs/{bristol.id}")).json()
    assert detail["place_count"] == 2
    assert (await api_client.get(f"/api/jobs/{lone.id}")).json()["place_count"] is None
    none = (await api_client.get(f"/api/jobs/{lone.id}/place-set")).json()
    assert none == {"job_id": lone.id, "place_set": None, "rejected": False, "rejected_at": None}

    split = await api_client.post(
        f"/api/jobs/{bristol.id}/place-set/review", json={"decision": "different"}
    )
    assert split.status_code == 200, split.text
    assert split.json()["place_set"] is None and split.json()["rejected"] is True
    assert (await api_client.get(f"/api/jobs/{london.id}")).json()["place_count"] is None

    again = await api_client.post(
        f"/api/jobs/{bristol.id}/place-set/review", json={"decision": "different"}
    )
    assert again.status_code == 409
    undo = await api_client.post(
        f"/api/jobs/{bristol.id}/place-set/review", json={"decision": "pending"}
    )
    assert undo.status_code == 200 and undo.json()["place_set"]["size"] == 2
    assert (await api_client.get("/api/jobs/999999/place-set")).status_code == 404


async def test_one_title_and_text_at_two_levels_stores_no_set(api_client, db_session):
    """Broken rule caught: two partitions of one title and text
    upserted ONE stored set holding all four postings with the last group's
    size, and the Board collapsed them into one row (none under the later
    partition's level filter)."""
    senior = [await place_set_job(db_session, 1, "London"), await place_set_job(db_session, 2, "Bristol")]
    staff = [await place_set_job(db_session, 3, "London"), await place_set_job(db_session, 4, "Bristol")]
    for job in senior:
        job.level_band = "senior"
    for job in staff:
        job.level_band = "staff"
    await db_session.commit()

    summary = await rebuild_place_sets(db_session)

    assert summary["sets"] == 0
    assert (await db_session.execute(select(func.count()).select_from(JobPlaceSet))).scalar_one() == 0
    assert await _members(db_session) == {}
    body = (await api_client.get("/api/jobs", params={"limit": 50, "status": "open"})).json()
    assert body["total"] == 4
    staff_rows = (
        await api_client.get("/api/jobs", params={"limit": 50, "level_band": "staff"})
    ).json()
    assert sorted(item["id"] for item in staff_rows["items"]) == sorted(j.id for j in staff)


# --------------------------------------------------------------------------- #
# v2: the posting's own place, and a member that closes.
# --------------------------------------------------------------------------- #

OFFICES = ["London", "Zurich"]
LEDGY_TITLE = "Engineering Manager (Hands-on)"


async def _listed(session, n: int, primary: str, *, status: str = "open") -> Job:
    """A Greenhouse posting as stored: its primary first, then the company's
    office list, the primary flagged in `source_facts` (greenhouse `_facts`)."""
    job = await place_set_job(session, n, "London", title=LEDGY_TITLE, status=status, company="ledgy")
    job.locations = [primary, *OFFICES]
    job.location_cities = ["Remote" if "Remote" in primary else "London, UK", "London, UK", "Zurich"]
    job.source_facts = {
        "provider": "greenhouse",
        "locations": [
            {"label": primary, "is_primary": True},
            *({"label": office, "is_primary": False} for office in OFFICES),
        ],
    }
    await session.flush()
    return job


async def test_the_rebuild_reads_each_postings_own_place_from_its_source_facts(db_session):
    # Fails if the SQL stops reading the primary: these four lists name the
    # same places by city, so v1 formed no set (ledgy 4853283101/4875819101).
    jobs = [
        await _listed(db_session, n, primary)
        for n, primary in enumerate(
            ["Poland (Remote)", "London, United Kingdom", "Spain (Remote)", "Germany (Remote)"], 1
        )
    ]
    db_session.add(pending_duplicate(jobs[3], jobs[1]))
    await db_session.commit()

    summary = await rebuild_place_sets(db_session)

    assert (summary["sets"], summary["members"], summary["withdrawn_lineage"]) == (1, 4, 1)
    place_set = (await db_session.execute(select(JobPlaceSet))).scalar_one()
    assert place_set.places == ["Poland (Remote)", "London, United Kingdom", "Spain (Remote)", "Germany (Remote)"]
    assert place_set.rule_version == "place_set/v5"
    assert place_set.evidence["place_basis"] == "primary"


@pytest.mark.parametrize("closing", ["earlier", "later"])
async def test_a_member_that_closes_does_not_come_back_as_a_duplicate(db_session, closing):
    """A set holds open postings, so a closed member leaves it, its detector
    input changes, and the detector reads it again. Read naively, the pair is
    then a concurrent same-title pair with half its places shared, and goes
    back to the queue as a suspected duplicate."""
    earlier = await _listed(db_session, 1, "Germany (Remote)")
    later = await _listed(db_session, 2, "Spain (Remote)")
    await db_session.commit()

    # Control: with no set, the detector proposes the pair for review.
    before = {sc.candidate.prior_job_id: sc for sc in await fetch_candidates(db_session, later, k=5)}
    assert before[earlier.id].verdict.decision == "suspected"

    await rebuild_place_sets(db_session)
    closed = earlier if closing == "earlier" else later
    closed.status, closed.closed_at = "closed", NOW - timedelta(hours=1)
    await db_session.commit()
    await rebuild_place_sets(db_session)
    assert await _members(db_session) == {}, "a set holds open postings only"

    after = {sc.candidate.prior_job_id: sc for sc in await fetch_candidates(db_session, later, k=5)}
    assert after[earlier.id].verdict.decision == "reject"
    assert after[earlier.id].verdict.reasons == [SAME_PLACE_SET_REASON]


async def test_a_closed_posting_with_other_text_is_still_proposed(db_session):
    # Negative control for the rule gate: it answers for the same role only.
    earlier = await _listed(db_session, 1, "Germany (Remote)")
    later = await _listed(db_session, 2, "Spain (Remote)")
    earlier.description_text = BODY + " " + OTHER_DUTIES
    earlier.status, earlier.closed_at = "closed", NOW - timedelta(hours=1)
    await db_session.commit()
    after = {sc.candidate.prior_job_id: sc for sc in await fetch_candidates(db_session, later, k=5)}
    assert after[earlier.id].verdict.decision == "suspected"


# --------------------------------------------------------------------------- #
# v3: texts that differ only by where the role is.
# --------------------------------------------------------------------------- #

PLACE_BODY = BODY + " This role is based in {city} and reports to the programme director."


async def test_texts_that_differ_only_by_their_place_form_one_set(db_session):
    london = await place_set_job(db_session, 1, "London", body=PLACE_BODY.format(city="London"))
    bristol = await place_set_job(db_session, 2, "Bristol", body=PLACE_BODY.format(city="Bristol"))
    other = await place_set_job(db_session, 3, "Leeds", body=PLACE_BODY.format(city="Leeds") + " " + OTHER_DUTIES)
    await db_session.commit()

    summary = await rebuild_place_sets(db_session)

    assert (summary["sets"], summary["members"]) == (1, 2)
    place_set = (await db_session.execute(select(JobPlaceSet))).scalar_one()
    assert place_set.evidence["text_match"] == "place"
    assert set(await _members(db_session)) == {london.id, bristol.id}
    assert other.id not in await _members(db_session)


async def test_a_closed_posting_finds_the_sibling_whose_text_names_another_place(db_session):
    london = await place_set_job(db_session, 1, "London", body=PLACE_BODY.format(city="London"), status="closed")
    bristol = await place_set_job(db_session, 2, "Bristol", body=PLACE_BODY.format(city="Bristol"))
    await db_session.commit()
    found = await still_listed_elsewhere(db_session, [london.id], companies={"aecom"})
    assert [p.id for p in found[london.id]] == [bristol.id]


# --------------------------------------------------------------------------- #
# v4: the role listed again at one place.
# --------------------------------------------------------------------------- #


async def test_postings_at_one_place_are_the_role_listed_again(api_client, db_session):
    """Same title and text at one place is one role, not the
    headcount question v1 refused. Three London postings and a Bristol one: one
    set, two places, London held by the employer's earliest date. Fails v1 (no
    set at all) and any rule that calls every member a place."""
    first = await place_set_job(db_session, 1, "London")
    again = await place_set_job(db_session, 2, "London")
    third = await place_set_job(db_session, 3, "London")
    bristol = await place_set_job(db_session, 4, "Bristol")
    # We saw `again` second, but the employer dated it first: it holds London.
    again.first_posted_at = NOW - timedelta(days=60)
    first.first_posted_at = NOW - timedelta(days=10)
    db_session.add(pending_duplicate(third, first))
    await db_session.commit()

    summary = await rebuild_place_sets(db_session)

    assert (summary["sets"], summary["members"], summary["withdrawn_lineage"]) == (1, 4, 1)
    place_set = (await db_session.execute(select(JobPlaceSet))).scalar_one()
    assert place_set.places == ["London, UK", "Bristol, UK"]
    assert place_set.evidence["relisted"] == 2

    body = (await api_client.get(f"/api/jobs/{first.id}/place-set")).json()["place_set"]
    assert {m["job"]["id"]: m["relation"] for m in body["members"]} == {
        first.id: "relisted", again.id: "place", third.id: "relisted", bristol.id: "place",
    }
    # Same place is said from the asked-for posting: London's others, never Bristol, never itself.
    assert {m["job"]["id"]: m["same_place"] for m in body["members"]} == {
        first.id: False, again.id: True, third.id: True, bristol.id: False,
    }

    row = (await api_client.get(f"/api/jobs/{first.id}")).json()
    assert (row["place_count"], row["place_set_size"]) == (2, 4)
    # Three listings at London (this one and the two others there); Bristol is
    # another place, not a relisting.
    assert row["posting_reality"]["listings"] == 3
    assert "relisted" in row["posting_reality"]["met"]
    assert (await api_client.get(f"/api/jobs/{bristol.id}")).json()["posting_reality"]["listings"] == 1


# --------------------------------------------------------------------------- #
# v5: every difference explained.
# --------------------------------------------------------------------------- #

LINE_BODY = "\n".join([
    "AECOM is seeking a Project Director to lead controls analytics across our infrastructure portfolio.",
    "You will own schedule and cost performance and build the reporting the programme board reads.",
    "You will grow a team of analysts and set the standards the portfolio reports to.",
] * 3)
INTRO = (
    "AECOM is a global infrastructure leader committed to delivering a better world, with teams in "
    "more than one hundred and fifty countries designing, building and managing the places people rely on."
)


async def test_a_local_benefits_block_does_not_split_one_role(db_session):
    london = await place_set_job(db_session, 1, "London", body=LINE_BODY + "\nPrivate medical insurance, 25 days holiday and a pension.")
    bristol = await place_set_job(db_session, 2, "Bristol", body=LINE_BODY)
    await db_session.commit()

    await rebuild_place_sets(db_session)

    assert set(await _members(db_session)) == {london.id, bristol.id}
    place_set = (await db_session.execute(select(JobPlaceSet))).scalar_one()
    assert place_set.evidence["text_match"] == "explained"


async def test_the_companys_intro_is_boilerplate_only_when_its_postings_repeat_it(db_session):
    london = await place_set_job(db_session, 1, "London", body=INTRO + "\n" + LINE_BODY)
    bristol = await place_set_job(db_session, 2, "Bristol", body=LINE_BODY)
    await db_session.commit()
    await rebuild_place_sets(db_session)
    # Said once, more than a few words: the role's own text, a question.
    assert await _members(db_session) == {}

    # Repeated across the company's other postings (any title, closed too):
    # the company's, so it does not split the role.
    for n in (3, 4, 5):
        await place_set_job(db_session, n, "Leeds", title=f"Graduate Engineer {n}", status="closed",
                   body=INTRO + "\nA different job entirely, in a different team, with other duties.")
    await db_session.commit()
    await rebuild_place_sets(db_session)
    assert set(await _members(db_session)) == {london.id, bristol.id}


async def test_a_different_headline_years_ask_keeps_two_texts_apart_even_as_boilerplate(db_session):
    """Amazon prints each requirement bullet in
    several postings, so both read as boilerplate; 7+ against 5+ years of
    management is still a different opening."""
    seven, five = "- 7+ years of direct management experience", "- 5+ years of direct management experience"
    a = await place_set_job(db_session, 1, "Vacaville", body=LINE_BODY + "\n" + seven)
    b = await place_set_job(db_session, 2, "Shepherdsville", body=LINE_BODY + "\n" + five)
    for n, line in ((3, seven), (4, seven), (5, seven), (6, five), (7, five), (8, five)):
        await place_set_job(db_session, n, "Leeds", title=f"Other Role {n}", status="closed", body="Other duties.\n" + line)
    await db_session.commit()

    await rebuild_place_sets(db_session)

    assert not ({a.id, b.id} <= set(await _members(db_session)))


async def test_the_rebuild_keeps_a_proposal_holding_a_withdrawn_verdict(db_session):
    """A place set withdraws the machine's proposals between its members. A
    verdict a person took back is not one of those: `review.py` returns the
    link to `pending` and leaves the decision it withdrew in
    `evidence.decision_history`, which the review surfaces count and
    `_restore_rows` relies on. Deleting the row deletes the only record of it.

    The sibling without history is the negative control: the guard must be
    narrow enough that ordinary proposals are still withdrawn. Fail-first:
    `withdrawn_lineage` is 2 and the history is gone.
    """
    london = await place_set_job(db_session, 1, "London")
    bristol = await place_set_job(db_session, 2, "Bristol")
    st_albans = await place_set_job(db_session, 3, "St Albans")
    undone = pending_duplicate(
        st_albans,
        london,
        evidence={
            "reasons": ["prior still open (duplicate listing)"],
            "decision_history": [{"decision": "duplicate", "changed_at": NOW.isoformat()}],
        },
    )
    ordinary = pending_duplicate(bristol, london)
    db_session.add_all([undone, ordinary])
    await db_session.commit()

    summary = await rebuild_place_sets(db_session)

    assert summary["withdrawn_lineage"] == 1, "only the proposal with no history is withdrawn"
    links = (await db_session.execute(select(JobLineageLink))).scalars().all()
    assert [(link.job_id, link.prior_job_id) for link in links] == [(st_albans.id, london.id)]
    assert [h["decision"] for h in links[0].evidence["decision_history"]] == ["duplicate"]


async def test_the_rebuild_keeps_a_twin_proposal_holding_a_withdrawn_verdict(db_session):
    """The same rule on the twin half of the queue."""
    london = await place_set_job(db_session, 1, "London")
    bristol = await place_set_job(db_session, 2, "Bristol")
    a, b = sorted((london.id, bristol.id))
    db_session.add(
        JobTwinLink(
            job_a_id=a, job_b_id=b, method="content_overlap", score=1.0, confidence="suspected",
            status="pending", detector_version="twins/v1",
            evidence={"decision_history": [{"decision": "different"}]},
        )
    )
    await db_session.commit()

    summary = await rebuild_place_sets(db_session)

    assert summary["withdrawn_twins"] == 0
    twin = (await db_session.execute(select(JobTwinLink))).scalar_one()
    assert [h["decision"] for h in twin.evidence["decision_history"]] == ["different"]


async def test_each_member_carries_the_pay_band_it_states(api_client, db_session):
    """A set groups postings that may state different bands for different
    places: each member says its own, and a posting that states none says null."""
    london = await place_set_job(db_session, 1, "London")
    bristol = await place_set_job(db_session, 2, "Bristol")
    leeds = await place_set_job(db_session, 3, "Leeds")
    london.disclosed_base_min, london.disclosed_base_max = 60_000, 75_000
    london.disclosed_currency, london.disclosed_pay_period = "GBP", "year"
    bristol.disclosed_base_min, bristol.disclosed_base_max = 52_000, 64_000
    bristol.disclosed_currency, bristol.disclosed_pay_period = "GBP", "year"
    await db_session.commit()
    await rebuild_place_sets(db_session)

    body = (await api_client.get(f"/api/jobs/{london.id}/place-set")).json()["place_set"]
    stated = {m["job"]["id"]: m["stated_pay"] for m in body["members"]}
    assert stated == {
        london.id: {"low": 60_000, "high": 75_000, "currency": "GBP", "period": "year"},
        bristol.id: {"low": 52_000, "high": 64_000, "currency": "GBP", "period": "year"},
        leeds.id: None,
    }


# --------------------------------------------------------------------------- #
# One detection pass reads each company's place-set texts once.
# --------------------------------------------------------------------------- #

#: Where each company's role is listed, oldest first; the closed ones are what
#: every later posting's candidates ask the rule about.
_STATUSES = ("closed", "open", "closed", "open", "closed", "open", "open")
_CITIES = {
    "aecom": ("Manchester", "London", "Glasgow", "Bristol", "Cardiff", "Leeds", "York"),
    "arup": ("Belfast", "Bath", "Derby", "Exeter", "Hull", "Oxford", "Perth"),
}


async def _role_listed_in_seven_places(session, company: str, first_n: int) -> list[Job]:
    return [
        await place_set_job(
            session, first_n + i, city, body=PLACE_BODY.format(city=city), status=status, company=company
        )
        for i, (city, status) in enumerate(zip(_CITIES[company], _STATUSES, strict=True))
    ]


async def test_one_detection_pass_reads_and_compares_each_companys_texts_once(db_session, monkeypatch):
    """Every posting with a closed same-title candidate asks the rule whether
    the pair is one role listed in two places. Broken rule caught: each
    question re-hashed every open description of the company, re-read its
    whole description history and compared the same two texts again, so a
    pass did that work once per candidate (here four times per company)."""
    jobs = [
        *await _role_listed_in_seven_places(db_session, "aecom", 1),
        *await _role_listed_in_seven_places(db_session, "arup", 11),
    ]
    await db_session.commit()

    asked: list[str] = []

    async def counted(session, job_ids, **kwargs):
        asked.append(next(iter(kwargs["companies"])))
        return await still_listed_elsewhere(session, job_ids, **kwargs)

    compared: list[tuple] = []
    compare = place_sets_module.differs_only_by_place

    def spied(left, left_places, right, right_places):
        compared.append((tuple(left_places), tuple(right_places)))
        return compare(left, left_places, right, right_places)

    monkeypatch.setattr(detect_module, "still_listed_elsewhere", counted)
    monkeypatch.setattr(place_sets_module, "differs_only_by_place", spied)
    statements: list[str] = []

    def record(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    engine = db_session.bind.sync_engine
    event.listen(engine, "before_cursor_execute", record)
    try:
        await detect_lineage(db_session, [j.id for j in jobs if j.status == "open"])
    finally:
        event.remove(engine, "before_cursor_execute", record)

    assert sorted(asked) == ["aecom"] * 4 + ["arup"] * 4, "several candidates of each company ask"
    open_reads = [s for s in statements if "md5(lower(btrim(" in s and "j.status = 'open'" in s]
    history_reads = [s for s in statements if "SELECT company, description_text, description_sections" in s]
    assert len(open_reads) == 2, "each company's open postings are hashed once per pass"
    assert len(history_reads) == 2, "each company's description history is counted once per pass"
    assert compared and len(compared) == len(set(compared)), "no two texts are compared twice"


async def _one_company_with_every_kind_of_answer(session) -> dict[str, Job]:
    """One title with a role listed in two open places, a closed posting of
    the same role, a closed one of the same title over other duties and an open
    pair whose texts differ by a benefits block; a second title with an open
    and a closed posting of one text."""
    jobs = {
        "leeds": await place_set_job(session, 1, "Leeds", body=PLACE_BODY.format(city="Leeds"), status="closed"),
        "york": await place_set_job(
            session, 2, "York", body=PLACE_BODY.format(city="York") + " " + OTHER_DUTIES, status="closed"
        ),
        "london": await place_set_job(session, 3, "London", body=PLACE_BODY.format(city="London")),
        "bristol": await place_set_job(session, 4, "Bristol", body=PLACE_BODY.format(city="Bristol")),
        "bath": await place_set_job(session, 5, "Bath", body=LINE_BODY, status="closed"),
        "derby": await place_set_job(
            session, 6, "Derby", body=LINE_BODY + "\nPrivate medical insurance, 25 days holiday and a pension."
        ),
        "glasgow": await place_set_job(session, 7, "Glasgow", title="Project Director - Rail", status="closed"),
        "perth": await place_set_job(session, 8, "Perth", title="Project Director - Rail"),
    }
    await session.commit()
    return jobs


def _ids(found: dict, jobs: dict[str, Job]) -> dict[str, list[str]]:
    name = {job.id: key for key, job in jobs.items()}
    return {name[job_id]: [name[p.id] for p in postings] for job_id, postings in found.items()}


async def test_a_shared_read_answers_every_question_as_a_fresh_read_does(db_session):
    jobs = await _one_company_with_every_kind_of_answer(db_session)
    questions = [
        ["leeds"], ["york"], ["bath"], ["glasgow"], ["leeds", "york"],
        ["glasgow", "bath", "leeds"], ["london"], ["york", "leeds", "bath", "glasgow"],
    ]
    shared = place_sets_module.PlaceSetReads()
    for names in questions:
        ids = [jobs[n].id for n in names]
        fresh = await still_listed_elsewhere(db_session, ids, companies={"aecom"})
        assert await still_listed_elsewhere(db_session, ids, companies={"aecom"}, reads=shared) == fresh, names
        assert await still_listed_elsewhere(db_session, ids) == fresh, names

    every = await still_listed_elsewhere(
        db_session, [jobs[n].id for n in ("leeds", "york", "bath", "glasgow")], reads=shared
    )
    assert _ids(every, jobs) == {
        "leeds": ["london", "bristol"],
        "bath": ["derby"],
        "glasgow": ["perth"],
    }, "York's other duties keep it out; the rest are their roles' other places"

    for key in ("london", "bristol", "derby", "perth"):
        job = jobs[key]
        verdicts = {
            sc.candidate.prior_job_id: (sc.verdict.decision, sc.verdict.reasons)
            for sc in await fetch_candidates(db_session, job, k=10, place_sets=shared)
        }
        assert verdicts == {
            sc.candidate.prior_job_id: (sc.verdict.decision, sc.verdict.reasons)
            for sc in await fetch_candidates(db_session, job, k=10)
        }, key
    london = {
        sc.candidate.prior_job_id: sc.verdict
        for sc in await fetch_candidates(db_session, jobs["london"], k=10, place_sets=shared)
    }
    assert london[jobs["leeds"].id].reasons == [SAME_PLACE_SET_REASON]
    assert SAME_PLACE_SET_REASON not in london[jobs["york"].id].reasons


async def test_a_shared_read_still_reads_a_persons_split_made_during_the_pass(db_session):
    """The reads a pass shares hold texts, never decisions: a "Different
    roles" a person gives between two candidates is the answer for the next."""
    jobs = await _one_company_with_every_kind_of_answer(db_session)
    shared = place_sets_module.PlaceSetReads()
    leeds = [jobs["leeds"].id]
    before = await still_listed_elsewhere(db_session, leeds, companies={"aecom"}, reads=shared)
    assert _ids(before, jobs) == {"leeds": ["london", "bristol"]}

    db_session.add(JobPlaceSetMember(job_id=jobs["bristol"].id, set_id=None, status="rejected"))
    await db_session.commit()

    after = await still_listed_elsewhere(db_session, leeds, companies={"aecom"}, reads=shared)
    assert _ids(after, jobs) == {"leeds": ["london"]}
