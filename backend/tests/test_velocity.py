"""Pure-logic tests for hiring-velocity assembly (no DB).

Pins the aging buckets, medians, activity merge, and the observed-duration sample gate
behind the Statistics "Velocity" sub-tab.
"""

from __future__ import annotations

from tracker.analytics.velocity import (
    DURATION_KEY,
    MIN_DURATION_SAMPLE,
    _median,
    aging_histogram,
    build_velocity,
)


def test_median_even_odd_and_empty():
    assert _median([1, 2, 3]) == 2
    assert _median([1, 2, 3, 4]) == 2.5
    assert _median([]) is None
    assert _median([5]) == 5.0


def test_aging_histogram_band_boundaries_are_zero_filled():
    hist = aging_histogram([0, 6.9, 7, 13, 40, 90, 200])
    counts = {h["lo"]: h["count"] for h in hist}
    assert counts[0] == 2  # under a week: 0 and 6.9
    assert counts[7] == 2  # 1-2 weeks: 7 (inclusive) and 13
    assert counts[14] == 0  # zero-filled, band still present
    assert counts[30] == 1  # 1-2 months: 40
    assert counts[90] == 2  # 90 (inclusive) and 200
    assert len(hist) == 6  # every band present


def _fixture():
    open_rows = [("google", 2), ("google", 10), ("openai", 40), ("openai", 100), ("meta", 3)]
    event_rows = [
        ("google", "opened", 5),
        ("google", "changed", 2),
        ("google", "closed", 1),
        ("openai", "opened", 8),
        ("openai", "closed", 3),
        ("meta", "opened", 1),
    ]
    # 6 closed samples (>= MIN_DURATION_SAMPLE) so the overall median reports.
    duration_rows = [("google", 10), ("google", 20), ("openai", 5), ("openai", 15), ("openai", 25), ("meta", 8)]
    return open_rows, event_rows, duration_rows


def test_build_velocity_kpis_sum_activity_and_flow():
    v = build_velocity(*_fixture(), open_total=5, days=30)
    k = v["kpis"]
    assert (k["opened"], k["updated"], k["closed"]) == (14, 2, 4)  # changed -> updated
    assert k["net"] == 10  # opened - closed
    assert k["median_days_open"] == 10  # median of [2,3,10,40,100]
    assert k[DURATION_KEY] == 12.5  # median of [5,8,10,15,20,25]
    assert k["closed_sample"] == 6


def test_build_velocity_observed_duration_gated_by_min_sample():
    open_rows, event_rows, _ = _fixture()
    thin = [("google", 10), ("openai", 20)]  # only 2 < MIN_DURATION_SAMPLE
    assert MIN_DURATION_SAMPLE > 2
    v = build_velocity(open_rows, event_rows, thin, open_total=5, days=30)
    assert v["kpis"][DURATION_KEY] is None
    assert v["kpis"]["closed_sample"] == 2


def test_build_velocity_by_company_ranked_by_opened_with_medians():
    v = build_velocity(*_fixture(), open_total=5, days=30)
    order = [c["company"] for c in v["by_company"]]
    assert order == ["openai", "google", "meta"]  # opened 8 > 5 > 1
    openai = v["by_company"][0]
    assert openai["open"] == 2 and openai["closed"] == 3 and openai["updated"] == 0
    assert openai["median_days_open"] == 70  # median of [40,100]
    assert openai[DURATION_KEY] == 15  # median of [5,15,25]


def test_the_duration_is_never_named_a_time_to_fill():
    """`median_time_to_fill` would assert a hire from a posting going away.

    The measure goes out under one name, in the payload and in the response
    model the OpenAPI document is built from, the thin-sample None included.
    """
    from tracker.api.routers.statistics import VelocityOut

    reported = build_velocity(*_fixture(), open_total=5, days=30)
    open_rows, event_rows, _ = _fixture()
    thin = build_velocity(open_rows, event_rows, [("google", 10)], open_total=5, days=30)

    for payload in (reported, thin):
        rows = [payload["kpis"], *payload["by_company"]]
        assert rows, "the fixture must produce rows for this contract to mean anything"
        for row in rows:
            assert DURATION_KEY in row
            assert not [key for key in row if "fill" in key], row
    assert reported["kpis"][DURATION_KEY] is not None
    assert thin["kpis"][DURATION_KEY] is None
    served = VelocityOut.model_json_schema()["$defs"]
    assert not [
        (model, field)
        for model, spec in served.items()
        for field in spec.get("properties", {})
        if "fill" in field
    ]


def test_the_response_model_drops_nothing_build_velocity_reports():
    """A `response_model` FILTERS: a field it omits leaves the payload silently.

    That is the whole hazard of modelling a route as a typed model rather than
    a bare dict — the alias, or a KPI nobody thought to declare, would simply stop
    being served with every test still green. Imported here (not at module
    scope) so the pure-logic suite above keeps costing no API import.
    """
    from tracker.api.routers.statistics import VelocityOut

    payload = build_velocity(*_fixture(), open_total=5, days=30)
    assert VelocityOut.model_validate(payload).model_dump() == payload

    empty = build_velocity([], [], [], open_total=0, days=7)
    assert VelocityOut.model_validate(empty).model_dump() == empty


def test_build_velocity_empty_is_safe():
    v = build_velocity([], [], [], open_total=0, days=7)
    assert v["kpis"]["opened"] == 0 and v["kpis"]["median_days_open"] is None
    assert v["by_company"] == []
    assert sum(b["count"] for b in v["aging"]) == 0
    assert len(v["aging"]) == 6


def test_reposted_events_are_a_separate_bucket_and_excluded_from_opened_and_net():
    # The SQL remaps a repost/duplicate successor's opened event to 'reposted', so
    # build_velocity sees it as its own type. It must NOT count as opened or shift net.
    event_rows = [
        ("google", "opened", 4),
        ("google", "reposted", 3),
        ("google", "closed", 1),
    ]
    v = build_velocity([("google", 5)], event_rows, [], open_total=1, days=30)
    k = v["kpis"]
    assert k["opened"] == 4  # reposts excluded
    assert k["reposted"] == 3
    assert k["net"] == 3  # opened(4) - closed(1); reposts do not move net
    assert v["by_company"][0]["reposted"] == 3


def test_each_age_aggregate_states_its_employer_dated_share_over_its_own_sample():
    """The ages keep our first-sighting clock; each sample says how much of it
    the employer dated (`analytics.age_basis`). The open share is over the open
    rows behind the median and the bands, the closed share over the duration
    sample, and an empty sample is None, never "0% dated"."""
    open_rows, event_rows, duration_rows = _fixture()  # 5 open, 6 closed
    v = build_velocity(
        open_rows, event_rows, duration_rows, open_total=5, days=30,
        open_employer_dated=2, closed_employer_dated=3,
    )
    assert v["kpis"]["employer_dated_share"] == 2 / 5
    assert v["kpis"]["closed_employer_dated_share"] == 3 / 6
    # The clock is untouched by the share: the median is still over the ages given.
    assert v["kpis"]["median_days_open"] == 10

    empty = build_velocity([], [], [], open_total=0, days=7)
    assert (empty["kpis"]["employer_dated_share"], empty["kpis"]["closed_employer_dated_share"]) == (None, None)
    undated = build_velocity(open_rows, event_rows, duration_rows, open_total=5, days=30)
    assert (undated["kpis"]["employer_dated_share"], undated["kpis"]["closed_employer_dated_share"]) == (0.0, 0.0)


def test_posted_bands_count_each_closed_posting_once_on_the_aging_bands():
    """Pace draws how long postings stayed up beside the age of open
    roles, on the same bands, so the two read as one pair."""
    v = build_velocity([("a", 1)], [], [("a", 3), ("a", 10), ("b", 45), ("b", 200)], open_total=1, days=30)
    assert [(b["lo"], b["count"]) for b in v["posted"]] == [(0, 1), (7, 1), (14, 0), (30, 1), (60, 0), (90, 1)]
    assert [b["lo"] for b in v["posted"]] == [b["lo"] for b in v["aging"]]
