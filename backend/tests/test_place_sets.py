"""The place-set rule, pure.

Each test names the plausible wrong rule it exists to fail: "same text is
enough", "the title key is enough", "merge the rest of a group", "different
spelling is a different place", "the employer's job id is the role".
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from tracker.lineage.place_sets import (
    SKIP_HUMAN_VERDICT,
    SKIP_MIXED_CLASS,
    SKIP_NO_PLACE,
    Posting,
    form_place_sets,
    primary_place_key,
)
from tracker.lineage.score import SAME_PLACE_SET_REASON, Candidate, LineageThresholds, score_pair
from tracker.taxonomy.locations import normalize_cities

T0 = datetime(2026, 10, 2, tzinfo=UTC)
TITLE = "Project Director - Controls Analytics"


def post(
    pid: int,
    place: str | tuple[str, ...],
    *,
    title: str = TITLE,
    text_hash: str = "h1",
    cities: tuple[str, ...] | None = None,
    band: str = "director_plus",
    family: str | None = "data_science",
    label: str | None = None,
    job: str | None = None,
    company: str = "aecom",
    primary: str | None = None,
) -> Posting:
    places = (place,) if isinstance(place, str) else place
    return Posting(
        id=pid,
        company=company,
        title=title,
        locations=places,
        cities=places if cities is None else cities,
        text_hash=text_hash,
        family=family,
        level_band=band,
        first_seen=T0 + timedelta(minutes=pid),
        employer_label=label,
        employer_job=job,
        primary=primary,
    )


def test_one_role_in_two_cities_is_one_set_with_both_places():
    sets, skipped = form_place_sets([post(2, "St Albans, UK"), post(1, "London, UK")])
    assert skipped == []
    assert len(sets) == 1
    assert sets[0].member_ids == (1, 2)  # earliest first
    assert sets[0].places == ("London, UK", "St Albans, UK")


def test_the_same_text_at_the_same_place_is_the_role_listed_again():
    # The headcount question is not the applicant's; one role, the later
    # posting `relisted`. Fails "same place keeps the group out" and "every
    # member holds a place".
    sets, skipped = form_place_sets([post(1, "London, UK"), post(2, "London, UK")])
    assert skipped == []
    assert [(s.member_ids, s.places, s.relations) for s in sets] == [
        ((1, 2), ("London, UK",), {1: "place", 2: "relisted"})
    ]
    assert sets[0].evidence["relisted"] == 1


def test_a_repeated_place_joins_the_role_beside_its_other_places():
    sets, _ = form_place_sets([post(1, "London, UK"), post(2, "London, UK"), post(3, "St Albans, UK")])
    assert [(s.member_ids, s.places) for s in sets] == [((1, 2, 3), ("London, UK", "St Albans, UK"))]
    assert sets[0].relations == {1: "place", 2: "relisted", 3: "place"}


def test_the_employers_earliest_date_holds_the_place():
    # Fails "first sighting decides": we saw both the same night (ledgy), and
    # the employer dated one a month earlier. That one holds the place.
    first = post(1, "London, UK")
    later_dated = Posting(**{**post(2, "London, UK").__dict__, "first_posted": T0 - timedelta(days=30)})
    first = Posting(**{**first.__dict__, "first_posted": T0})
    sets, _ = form_place_sets([first, later_dated])
    assert sets[0].relations == {1: "relisted", 2: "place"}
    assert sets[0].member_ids == (1, 2), "the set's own order stays by first sighting"


def test_a_different_level_word_is_a_different_role():
    # Fails "title_key is enough": the key drops level words.
    sets, _ = form_place_sets(
        [
            post(1, "London, UK", title="Senior Data Engineer"),
            post(2, "Bristol, UK", title="Staff Data Engineer"),
        ]
    )
    assert sets == []


def test_two_classifications_under_one_title_and_text_form_no_set():
    """Broken rule caught: the rule split London+Bristol at
    `senior` from London+Bristol at `staff`, but a set is stored by
    (company, title, text), so both partitions wrote ONE row and four
    memberships. The same title and text read as two levels (a printed rung,
    a pay grade, a department) is not a question the rule can answer: no set."""
    for field, a, b in (("band", "senior", "staff"), ("family", "data_science", "engineering")):
        postings = [
            post(1, "London, UK", **{field: a}),
            post(2, "Bristol, UK", **{field: a}),
            post(3, "London, UK", **{field: b}),
            post(4, "Bristol, UK", **{field: b}),
            post(5, "Leeds, UK", **{field: b}),
        ]
        sets, skipped = form_place_sets(postings)
        assert sets == [], field
        assert [(s.member_ids, s.reason) for s in skipped] == [((1, 2, 3, 4, 5), SKIP_MIXED_CLASS)]
    # One classification still forms its set.
    sets, _ = form_place_sets([post(1, "London, UK", band="staff"), post(2, "Bristol, UK", band="staff")])
    assert [s.member_ids for s in sets] == [(1, 2)]


def test_a_different_text_or_band_or_family_is_not_the_same_role():
    for other in (
        post(2, "Bristol, UK", text_hash="h2"),
        post(2, "Bristol, UK", band="senior"),
        post(2, "Bristol, UK", family="engineering"),
        post(2, "Bristol, UK", company="assystem"),
    ):
        sets, _ = form_place_sets([post(1, "London, UK"), other])
        assert sets == [], other


def test_a_different_spelling_of_one_place_is_the_same_place():
    # Fails "compare the raw strings": "New York City" and "New York, NY" are
    # one city, so the second is the role listed again, not a second place.
    sets, _ = form_place_sets(
        [
            post(1, "New York City", cities=("New York, NY",)),
            post(2, "New York, NY", cities=("New York, NY",)),
        ]
    )
    assert [(s.places, s.relations) for s in sets] == [(("New York, NY",), {1: "place", 2: "relisted"})]


def test_brex_listing_every_city_on_every_posting_names_the_same_places():
    every = ("New York, NY", "Remote", "Salt Lake City, UT", "San Francisco, CA", "Seattle, WA")
    sets, _ = form_place_sets(
        [
            post(1, ("Vancouver, British Columbia, Canada", *every), cities=("Vancouver, BC", *every)),
            post(2, ("Seattle, Washington, United States", *every), cities=every + ("Vancouver, BC",)),
        ]
    )
    # With no primary stated, the lists name the same places: one place, the
    # second posting listed again there.
    assert [(s.evidence["place_basis"], s.relations) for s in sets] == [
        ("places", {1: "place", 2: "relisted"})
    ]


# --------------------------------------------------------------------------- #
# v2: a posting's own place is its primary, when every member has one.
# --------------------------------------------------------------------------- #

OFFICES = ("London", "Zurich")


def ledgy(pid: int, primary: str, cities: tuple[str, ...]) -> Posting:
    return post(pid, (primary, *OFFICES), cities=cities, primary=primary, company="ledgy",
                title="Engineering Manager (Hands-on)")


def test_one_role_per_primary_place_over_a_shared_office_list_is_one_set():
    # Fails "compare the full lists" (v1): every posting carries the same
    # office list, so the lists nest and v1 read the same places. Ledgy
    # 4853283101 / 4875819101 and their two siblings, as stored.
    postings = [
        ledgy(1, "Poland (Remote)", ("Remote", "London, UK", "Zurich")),
        ledgy(2, "London, United Kingdom", ("London, UK", "Zurich")),
        ledgy(3, "Spain (Remote)", ("Remote", "London, UK", "Zurich")),
        ledgy(4, "Germany (Remote)", ("Remote", "London, UK", "Zurich")),
    ]
    sets, skipped = form_place_sets(postings)
    assert skipped == []
    assert [s.member_ids for s in sets] == [(1, 2, 3, 4)]
    # The set's places are the postings' own, so the Board chip counts four,
    # not the six labels the lists hold together.
    assert sets[0].places == ("Poland (Remote)", "London, United Kingdom", "Spain (Remote)", "Germany (Remote)")
    assert sets[0].evidence["place_basis"] == "primary"
    # The same postings with no primary stated compare by their lists, where
    # the three remote ones read as one place ("Remote"): one place held, two
    # listed again. The primary is what tells the four places apart.
    unstated = [Posting(**{**p.__dict__, "primary": None}) for p in postings]
    (by_lists,) = form_place_sets(unstated)[0]
    assert by_lists.evidence["place_basis"] == "places"
    assert by_lists.relations == {1: "place", 2: "place", 3: "relisted", 4: "relisted"}


def test_a_remote_place_keeps_its_country():
    # Fails "compare canonical cities": the canonical label folds every remote
    # place to "Remote", which would read Germany and Spain as one place.
    assert primary_place_key(ledgy(1, "Germany (Remote)", ("Remote",))) != primary_place_key(
        ledgy(2, "Spain (Remote)", ("Remote",))
    )
    sets, _ = form_place_sets(
        [ledgy(1, "Germany (Remote)", ("Remote",)), ledgy(2, "Spain (Remote)", ("Remote",))]
    )
    assert [s.member_ids for s in sets] == [(1, 2)]


def test_remote_places_in_two_countries_are_two_places_with_no_primary_stated():
    # Fails "fold remote to one label": with no primary the comparison reads
    # the stored canonical labels, which once read Germany and Poland alike.
    def remote(pid: int, place: str) -> Posting:
        return post(pid, (place,), cities=tuple(normalize_cities([place])), primary=None, company="ledgy",
                    title="Engineering Manager (Hands-on)")

    (german, polish) = remote(1, "Germany (Remote)"), remote(2, "Poland (Remote)")
    assert german.cities != polish.cities
    (both,) = form_place_sets([german, polish])[0]
    assert both.relations == {1: "place", 2: "place"}


def test_one_remote_country_spelled_two_ways_is_the_same_place():
    assert primary_place_key(ledgy(1, "Germany (Remote)", ())) == primary_place_key(
        ledgy(2, "Remote - Germany", ()))


def test_one_primary_city_spelled_two_ways_is_the_same_place():
    # Fails "compare primary labels raw": the same city twice is the
    # same-place question, which keeps the group out as in v1.
    sets, _ = form_place_sets(
        [
            post(1, ("San Francisco, CA", "Remote"), primary="San Francisco, CA"),
            post(2, ("San Francisco, California, United States", "Remote"),
                 primary="San Francisco, California, United States"),
        ]
    )
    # One place on the chip, the second posting listed again there.
    assert [(s.places, s.relations) for s in sets] == [(("San Francisco, CA",), {1: "place", 2: "relisted"})]


def test_an_arrangement_word_recorded_as_primary_is_no_place():
    # Fails "trust any primary": Greenhouse records Cloudflare's "Hybrid" as
    # primary and keeps only the offices as places, and a bare
    # "Remote" says how, not where. Either sends the group back to the lists,
    # which here are the same.
    for primary, places in (("Hybrid", OFFICES), ("Remote", ("Remote", *OFFICES))):
        postings = [post(1, places, primary=primary), post(2, places, primary=primary)]
        assert primary_place_key(postings[0]) is None
        sets, _ = form_place_sets(postings)
        assert [(s.evidence["place_basis"], s.relations) for s in sets] == [
            ("places", {1: "place", 2: "relisted"})
        ], primary


def test_one_member_without_a_primary_keeps_the_group_on_the_lists():
    # Fails "compare primaries where present": one member read by its list
    # and the others by their primary are not comparable keys. Both postings
    # list the same places; only the primaries tell them apart.
    both = ("Berlin", "Munich", *OFFICES)
    sets, _ = form_place_sets([post(1, both, primary="Berlin"), post(2, both, primary=None)])
    assert [(s.evidence["place_basis"], s.relations) for s in sets] == [("places", {1: "place", 2: "relisted"})]
    sets, _ = form_place_sets([post(1, both, primary="Berlin"), post(2, both, primary="Munich")])
    assert [(s.member_ids, s.evidence["place_basis"]) for s in sets] == [((1, 2), "primary")]


def test_brex_by_primary_is_one_role_and_a_repeated_primary_is_listed_again():
    every = ("New York, NY", "Remote", "Salt Lake City, UT", "San Francisco, CA", "Seattle, WA")
    vancouver, seattle, sf = (
        "Vancouver, British Columbia, Canada", "Seattle, Washington, United States",
        "San Francisco, California, United States",
    )
    sets, _ = form_place_sets(
        [post(1, (vancouver, *every), primary=vancouver), post(2, (seattle, *every), primary=seattle)]
    )
    assert [s.member_ids for s in sets] == [(1, 2)]
    # Two postings with one primary: the role listed again at that place.
    sets, _ = form_place_sets(
        [post(1, (sf, *every), primary=sf), post(2, (sf, *every), primary=sf),
         post(3, (seattle, *every), primary=seattle)]
    )
    assert [(s.places, s.relations) for s in sets] == [((sf, seattle), {1: "place", 2: "relisted", 3: "place"})]


def test_a_title_that_names_its_own_place_still_matches():
    sets, _ = form_place_sets(
        [
            post(1, "London", title="Associate Director - Water - London"),
            post(2, "Bristol", title="Associate Director - Water - Bristol"),
        ]
    )
    assert len(sets) == 1


def test_a_posting_that_names_no_place_cannot_prove_a_different_place():
    sets, skipped = form_place_sets([post(1, "London, UK"), post(2, (), cities=())])
    assert sets == []
    assert [s.reason for s in skipped] == [SKIP_NO_PLACE]


def test_a_pair_a_person_decided_keeps_the_group_out():
    postings = [post(1, "London, UK"), post(2, "Bristol, UK"), post(3, "Leeds, UK")]
    sets, skipped = form_place_sets(postings, decided_pairs={frozenset((1, 3))})
    assert sets == []
    assert [s.reason for s in skipped] == [SKIP_HUMAN_VERDICT]
    # A decided pair outside the group does not block it.
    sets, _ = form_place_sets(postings, decided_pairs={frozenset((1, 99))})
    assert len(sets) == 1


def test_a_posting_a_person_split_out_joins_no_set():
    postings = [post(1, "London, UK"), post(2, "Bristol, UK"), post(3, "Leeds, UK")]
    sets, _ = form_place_sets(postings, rejected={2})
    assert [s.member_ids for s in sets] == [(1, 3)]
    sets, _ = form_place_sets(postings[:2], rejected={2})
    assert sets == []


def test_the_employer_label_is_evidence_only_when_every_member_shares_it():
    shared, _ = form_place_sets(
        [post(1, "London, UK", label="JR1"), post(2, "Bristol, UK", label="JR1")]
    )
    assert shared[0].evidence["employer_label"] == "JR1"
    mixed, _ = form_place_sets(
        [post(1, "London, UK", label="JR1"), post(2, "Bristol, UK", label=None)]
    )
    assert len(mixed) == 1 and mixed[0].evidence["employer_label"] is None


def test_one_employer_job_id_over_different_titles_is_not_one_role():
    # Fails "the employer's job id is the role": Brex files Card, Embedded and
    # Expenses PMs under one Greenhouse job.
    sets, _ = form_place_sets(
        [
            post(1, "San Francisco, CA", title="Staff Product Manager, Card", job="636", text_hash="a"),
            post(2, "New York, NY", title="Staff Product Manager, Embedded", job="636", text_hash="b"),
        ]
    )
    assert sets == []


def test_the_lineage_detector_never_links_two_postings_of_one_set():
    candidate = Candidate(
        job_id=2, prior_job_id=1, cosine=1.0, title_display_equal=True, title_equal=True,
        title_jaccard=1.0, title_grade_compatible=True, concurrent=True, gap_days=0,
        location_overlap=True, both_locations_empty=False, location_jaccard=1.0,
        same_family=True, same_level_band=True, prior_lineage_size=1, has_descriptions=True,
        band_relation="unknown", word_overlap=1.0,
    )
    assert score_pair(candidate, LineageThresholds()).decision == "suspected"
    gated = score_pair(
        Candidate(**{**candidate.__dict__, "same_place_set": True}), LineageThresholds()
    )
    assert gated.decision == "reject"
    assert gated.reasons == [SAME_PLACE_SET_REASON]
