"""What the MCP tools actually do.

`tracker/mcp/server.py` is the second front door: an MCP client reaches pursuit
writes and the whole in-scope board through it, so these tests call the tool
bodies. `test_agents.py` lists the tool names and checks two annotations, which
is a check on the decorators: every filter, every clamp, both access gates and
the two writes go unexercised there, and a tool that returned an empty list for
everything would pass.

FastMCP's `tool()` returns the undecorated function
so the bodies are ordinary coroutines and
need no client: the only thing standing between them and the scratch database is
`session_scope`, which this file points at it. Real Postgres, because what the
tools are is SQL — a visibility join, an array overlap, a NULLS LAST sort and an
ON CONFLICT-free upsert cannot be judged against a fake session.

Parity tests require MCP search, open-role counts, and overdue pursuits
to agree with the shared query owners used by the HTTP surfaces.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import func, select

import tracker.mcp.server as server
from tracker.agents.config import AgentAccessConfig, set_agent_access
from tracker.company_store import off_board_company_slugs
from tracker.db.models import Favorite, Job, JobFeedback, Pursuit, PursuitEvent, TrackedCompany
from tracker.db.queries.jobs import apply_job_filters, open_in_scope_count_stmt
from tracker.enrich.classify import location_slugs_for
from tracker.notifications.pursuit_due import overdue_pursuit_clause
from tracker.settings_store import set_enabled_locations

#: The tools reach `procs`-free code, but a write tool that escaped its session
#: would still act on the user's data; `no_escape` keeps the network shut too.
pytestmark = [pytest.mark.asyncio, pytest.mark.usefixtures("no_escape")]

NOW = datetime(2026, 7, 20, 12, 0, tzinfo=UTC)

#: Every tool but the status one, with the smallest call that reaches its gate.
READ_TOOLS = {
    "get_radar_summary": lambda: server.get_radar_summary(),
    "search_opportunities": lambda: server.search_opportunities(),
    "get_opportunity": lambda: server.get_opportunity(1),
    "listing_history": lambda: server.listing_history(1),
    "get_pursuits": lambda: server.get_pursuits(),
}
WRITE_TOOLS = {
    "save_opportunity": lambda: server.save_opportunity(1),
    "update_pursuit": lambda: server.update_pursuit(1, stage="applied"),
}


def _job(
    job_id: int,
    company: str = "openai",
    *,
    title: str = "Staff Product Manager",
    comp_median: int | None = 600_000,
    first_seen: datetime | None = None,
    in_scope: bool = True,
    status: str = "open",
    structured: bool = False,
    locations: list[str] | None = None,
) -> Job:
    return Job(
        id=job_id,
        company=company,
        req_id=f"r{job_id}",
        dedupe_key=f"{company}:r{job_id}",
        title=title,
        url=f"https://careers.example.test/{job_id}",
        locations=["San Francisco, CA"],
        # Real slugs: an invented one is, correctly, an unknown value.
        location_groups=locations or ["silicon_valley"],
        workplace_type="hybrid",
        level_band="staff",
        family="product_management",
        track="product_program",
        department="Product",
        team="Platform",
        description_text="Own the roadmap for inference platform products.",
        description_sections=[{"heading": "About", "body": "Own the roadmap."}],
        status=status,
        in_scope=in_scope,
        comp_low=500_000,
        comp_median=comp_median,
        comp_high=700_000,
        comp_currency="USD",
        comp_provenance="model",
        disclosed_base_min=300_000 if structured else None,
        disclosed_base_max=360_000 if structured else None,
        disclosed_currency="USD" if structured else None,
        disclosed_pay_basis="salary" if structured else None,
        disclosed_pay_period="year" if structured else None,
        disclosed_snippet="$300,000 - $360,000" if structured else None,
        structured_at=NOW if structured else None,
        first_seen=first_seen or NOW - timedelta(days=10),
        last_seen=NOW,
    )


def _company(slug: str, *, visible: bool = True) -> TrackedCompany:
    return TrackedCompany(
        slug=slug, display=slug.title(), adapter="greenhouse", status="active",
        enabled=True, visible=visible, source="catalog",
    )


@pytest.fixture
def scoped(db_session, scratch_scope):
    """The server's transaction scope on the scratch database.

    Each tool opens its own scope and the writes commit, exactly as in the live
    process — so a write tool's effect is asserted by reading it back from
    another session rather than from the one that wrote it.
    """
    return db_session


async def _allow(session, *, enabled: bool = True, writes: bool = True) -> None:
    await set_agent_access(session, AgentAccessConfig(enabled=enabled, allow_writes=writes))
    await session.commit()


async def _seed_board(session) -> dict[str, int]:
    """Four postings: two visible and in scope, one at a hidden company, one out of scope."""
    session.add_all([_company("openai"), _company("anthropic"), _company("shadow", visible=False)])
    jobs = {
        "newest": _job(1, "openai", first_seen=NOW - timedelta(days=1), comp_median=400_000),
        "richest": _job(2, "anthropic", first_seen=NOW - timedelta(days=30), comp_median=900_000),
        "hidden_company": _job(3, "shadow"),
        "out_of_scope": _job(4, "openai", in_scope=False),
    }
    session.add_all(jobs.values())
    await session.commit()
    return {name: job.id for name, job in jobs.items()}


# --------------------------------------------------------------------------- #
# 1. Both gates
# --------------------------------------------------------------------------- #


async def test_the_status_tool_answers_even_with_access_switched_off(scoped):
    status = await server.get_server_status()

    assert status == {
        "enabled": False,
        "allow_writes": False,
        "transport": "stdio",
        "privacy": "Local process; data is returned only to the connected MCP client.",
    }


@pytest.mark.parametrize("name", sorted(READ_TOOLS | WRITE_TOOLS))
async def test_every_other_tool_is_refused_while_access_is_off(scoped, name):
    """Access defaults off (`AgentAccessConfig()`), and nothing but the status
    tool may read a single row before the user turns it on."""
    call = (READ_TOOLS | WRITE_TOOLS)[name]

    with pytest.raises(PermissionError, match="agent access is disabled"):
        await call()


@pytest.mark.parametrize("name", sorted(WRITE_TOOLS))
async def test_a_read_only_grant_refuses_exactly_the_writes(scoped, name):
    await _allow(scoped, enabled=True, writes=False)
    ids = await _seed_board(scoped)

    assert (await server.get_opportunity(ids["newest"]))["id"] == ids["newest"]
    with pytest.raises(PermissionError, match="agent writes are disabled"):
        await WRITE_TOOLS[name]()


def _labels(file: str) -> dict[str, str]:
    """`id = text` of the single-line messages in one English copy file."""
    text = (Path(__file__).resolve().parents[2] / "dashboard/src/copy/en" / file).read_text()
    return dict(re.findall(r"^([a-z0-9-]+) = (.+)$", text, flags=re.M))


async def test_a_refusal_names_the_switch_and_the_tab_as_the_dashboard_labels_them(scoped):
    """The user meets this through their agent app, before they have opted in:
    a tab or a switch they cannot find on the screen is no way forward."""
    tab = _labels("shell.ftl")["shell-tab-settings-ai"]
    switches = _labels("ai.ftl")
    with pytest.raises(PermissionError) as off:
        await server.search_opportunities()
    assert f"Settings > {tab}" in str(off.value)
    assert f"'{switches['ai-assistants-card-allow-assistant-apps-to-connect']}'" in str(off.value)

    await _allow(scoped, enabled=True, writes=False)
    ids = await _seed_board(scoped)
    with pytest.raises(PermissionError) as read_only:
        await server.save_opportunity(ids["newest"])
    assert f"Settings > {tab}" in str(read_only.value)
    assert f"'{switches['ai-assistants-card-allow-assistant-apps-to-update']}'" in str(read_only.value)


# --------------------------------------------------------------------------- #
# 2. Search
# --------------------------------------------------------------------------- #


async def test_search_answers_only_visible_in_scope_open_postings(scoped):
    await _allow(scoped)
    ids = await _seed_board(scoped)

    found = await server.search_opportunities()

    assert [item["id"] for item in found["items"]] == [ids["newest"], ids["richest"]]
    assert found["count"] == 2


@pytest.mark.parametrize(
    ("limit", "expected"),
    [(0, 1), (-5, 1), (1, 1), (2, 2), (1000, 2)],
    ids=["zero", "negative", "one", "two", "far_above_the_cap"],
)
async def test_the_limit_is_clamped_to_one_through_a_hundred(scoped, limit, expected):
    """A limit of 0 or below would answer nothing at all, and an unbounded one
    would hand a model the whole board."""
    await _allow(scoped)
    await _seed_board(scoped)

    assert len((await server.search_opportunities(limit=limit))["items"]) == expected


async def test_rows_that_tie_on_the_sort_key_break_by_id_descending(scoped):
    """Without the tie-break, two postings first seen in the same scrape come
    back in whatever order the scan returns, so paging is not stable."""
    await _allow(scoped)
    scoped.add(_company("openai"))
    same = NOW - timedelta(days=3)
    scoped.add_all([_job(n, "openai", first_seen=same) for n in (11, 12, 13)])
    await scoped.commit()

    found = await server.search_opportunities()

    assert [item["id"] for item in found["items"]] == [13, 12, 11]


@pytest.mark.parametrize(
    ("sort", "order"),
    [("newest", ["newest", "richest"]), ("oldest", ["richest", "newest"]),
     ("compensation", ["richest", "newest"])],
)
async def test_each_sort_orders_the_board_the_way_it_is_named(scoped, sort, order):
    await _allow(scoped)
    ids = await _seed_board(scoped)

    found = await server.search_opportunities(sort=sort)

    assert [item["id"] for item in found["items"]] == [ids[name] for name in order]


async def test_a_posting_without_an_estimate_sorts_last_on_compensation(scoped):
    """`nullslast`: an unpriced posting is not the cheapest one."""
    await _allow(scoped)
    scoped.add(_company("openai"))
    scoped.add_all([_job(21, "openai", comp_median=None), _job(22, "openai", comp_median=100_000)])
    await scoped.commit()

    found = await server.search_opportunities(sort="compensation")

    assert [item["id"] for item in found["items"]] == [22, 21]


async def test_saved_only_narrows_to_saved_postings(scoped):
    await _allow(scoped)
    ids = await _seed_board(scoped)
    scoped.add(Favorite(job_id=ids["richest"]))
    await scoped.commit()

    found = await server.search_opportunities(saved_only=True)

    assert [item["id"] for item in found["items"]] == [ids["richest"]]
    assert found["items"][0]["saved"] is True


@pytest.mark.parametrize(
    ("filters", "expected"),
    [
        ({"query": "inference platform"}, ["newest", "richest"]),
        ({"query": "ANTHROPIC"}, ["richest"]),
        ({"query": "   "}, ["newest", "richest"]),
        ({"query": "quantum"}, []),
        ({"companies": ["anthropic"]}, ["richest"]),
        ({"companies": ["anthropic", "openai"]}, ["newest", "richest"]),
        ({"families": ["product_management"]}, ["newest", "richest"]),
        ({"families": ["software_engineering"]}, []),
        ({"locations": ["silicon_valley"]}, ["newest", "richest"]),
        ({"locations": ["new_york"]}, []),
        ({"minimum_estimated_comp": 500_000}, ["richest"]),
        ({"companies": ["anthropic"], "minimum_estimated_comp": 1_000_000}, []),
    ],
    ids=[
        "text_matches_description", "text_is_case_insensitive", "blank_text_filters_nothing",
        "text_matches_nothing", "one_company", "either_company", "family", "other_family",
        "location_overlap", "other_location", "comp_floor", "filters_are_anded",
    ],
)
async def test_each_filter_narrows_the_way_the_docstring_says(scoped, filters, expected):
    """"Filters are ANDed; list values are ORed" — including the blank query,
    which must not become a `%%` match on every row."""
    await _allow(scoped)
    ids = await _seed_board(scoped)

    found = await server.search_opportunities(**filters)

    assert sorted(item["id"] for item in found["items"]) == sorted(ids[n] for n in expected)


@pytest.mark.parametrize(
    ("filters", "expected"),
    [
        ({"families": ["Product Management"]}, ["newest", "richest"]),
        ({"families": ["product-management"]}, ["newest", "richest"]),
        ({"companies": ["OpenAI"]}, ["newest"]),
        ({"locations": ["Silicon Valley"]}, ["newest", "richest"]),
        ({"locations": ["NEW YORK"]}, []),
    ],
    ids=["family_by_name", "family_hyphenated", "company_by_name", "location_by_name", "known_location_true_zero"],
)
async def test_a_person_s_spelling_resolves_to_the_slug(scoped, filters, expected):
    """Case, spaces and hyphens are spelling, not meaning. A KNOWN value
    that matches no posting still narrows to zero: that zero is true."""
    await _allow(scoped)
    ids = await _seed_board(scoped)

    found = await server.search_opportunities(**filters)

    assert sorted(item["id"] for item in found["items"]) == sorted(ids[n] for n in expected)
    assert (found["ignored"], found["dropped_filters"]) == ([], [])


async def test_an_unknown_value_widens_and_is_named_instead_of_answering_zero(scoped):
    """"ML" matches nothing verbatim. Answering zero would let the agent tell a
    person there are no such roles."""
    await _allow(scoped)
    ids = await _seed_board(scoped)

    found = await server.search_opportunities(families=["ML"], locations=["Narnia"])

    assert sorted(item["id"] for item in found["items"]) == sorted([ids["newest"], ids["richest"]]), (
        "both filters dropped, so the search is the unfiltered radar"
    )
    assert found["dropped_filters"] == ["families", "locations"]
    assert found["ignored"] == [
        {"filter": "families", "value": "ML", "reason": "not a known families value"},
        {"filter": "locations", "value": "Narnia", "reason": "not a known locations value"},
    ]


async def _seed_places(session) -> dict[str, int]:
    """Three postings tagged the way enrichment tags them: Seattle (its GeoNames
    city under the Pacific Northwest), Redmond (the same metro, no Seattle) and
    Seoul."""
    session.add_all([_company("openai"), _company("anthropic")])
    places = {"seattle": "Seattle, WA, USA", "redmond": "Redmond, WA, USA", "seoul": "Seoul, South Korea"}
    jobs = {}
    for n, (name, place) in enumerate(places.items(), start=41):
        job = _job(n, "openai" if n % 2 else "anthropic", locations=location_slugs_for([place]))
        job.locations = [place]
        jobs[name] = job
    session.add_all(jobs.values())
    await session.commit()
    return {name: job.id for name, job in jobs.items()}


@pytest.mark.parametrize(
    ("value", "tracked_city", "expected"),
    [
        ("Seattle", False, ["seattle", "redmond"]),
        ("Seattle", True, ["seattle"]),
        ("USA", False, ["seattle", "redmond"]),
        ("Korea", False, ["seoul"]),
        ("Bay Area", False, []),
    ],
    ids=["city_as_its_metro", "tracked_city", "country_alias", "short_country_name", "metro_place_true_zero"],
)
async def test_a_place_resolves_the_way_the_search_box_and_the_board_read_it(
    scoped, value, tracked_city, expected
):
    """Slugs and display names alone would ignore "Seattle", "USA", "Bay
    Area" and widen the search to the whole radar. A city the
    user tracks is the city; any other is the metro that holds it."""
    await _allow(scoped)
    ids = await _seed_places(scoped)
    seattle = next(s for s in location_slugs_for(["Seattle, WA, USA"]) if s.startswith("city_"))
    if tracked_city:
        await set_enabled_locations(scoped, ["united_states", "pacific_northwest", seattle])
        await scoped.commit()

    found = await server.search_opportunities(locations=[value])

    assert sorted(item["id"] for item in found["items"]) == sorted(ids[n] for n in expected)
    assert (found["ignored"], found["dropped_filters"]) == ([], [])


async def test_an_unknown_place_is_still_named_beside_a_known_one(scoped):
    await _allow(scoped)
    ids = await _seed_places(scoped)

    found = await server.search_opportunities(locations=["USA", "Gondor"])

    assert sorted(item["id"] for item in found["items"]) == sorted([ids["seattle"], ids["redmond"]])
    assert found["dropped_filters"] == []
    assert found["ignored"] == [{"filter": "locations", "value": "Gondor", "reason": "not a known locations value"}]


async def test_a_mix_narrows_on_the_known_value_and_names_the_rest(scoped):
    await _allow(scoped)
    ids = await _seed_board(scoped)

    found = await server.search_opportunities(companies=["anthropic", "Initech"])

    assert [item["id"] for item in found["items"]] == [ids["richest"]]
    assert found["dropped_filters"] == []
    assert found["ignored"] == [{"filter": "companies", "value": "Initech", "reason": "not a known companies value"}]


async def test_first_seen_within_days_counts_from_our_first_sighting(scoped):
    await _allow(scoped)
    ids = await _seed_board(scoped)
    # The board's clock is NOW; the tool reads the real one. Re-anchor the two
    # visible postings to the real clock: one seen 2 days ago, one 30.
    real_now = datetime.now(UTC)
    for name, days in (("newest", 2), ("richest", 30)):
        job = await scoped.get(Job, ids[name])
        job.first_seen = real_now - timedelta(days=days)
        job.posted_at = real_now  # re-stamped by the employer: must not count
    await scoped.commit()

    week = await server.search_opportunities(first_seen_within_days=7)
    assert [item["id"] for item in week["items"]] == [ids["newest"]]

    nonsense = await server.search_opportunities(first_seen_within_days=0)
    assert len(nonsense["items"]) == 2, "an invalid window filters nothing"
    assert nonsense["ignored"] == [
        {"filter": "first_seen_within_days", "value": 0, "reason": "must be 1 or more"},
    ]

    # A window wider than anything stored is all of it: a million
    # days must not overflow date arithmetic into a tool error.
    everything = await server.search_opportunities(first_seen_within_days=1_000_000)
    assert len(everything["items"]) == 2


# --------------------------------------------------------------------------- #
# 3. One opportunity
# --------------------------------------------------------------------------- #


async def test_an_unknown_opportunity_is_a_lookup_error(scoped):
    await _allow(scoped)
    await _seed_board(scoped)

    with pytest.raises(LookupError, match="opportunity not found"):
        await server.get_opportunity(999_999)


async def test_a_posting_read_by_id_carries_its_full_text(scoped):
    """The detail keys are what "fetch detail before making a recommendation"
    means; the list shape must not carry them."""
    await _allow(scoped)
    ids = await _seed_board(scoped)

    detail = await server.get_opportunity(ids["newest"])
    listed = (await server.search_opportunities())["items"][0]

    assert {"department", "team", "description", "description_sections"} <= set(detail)
    assert not {"department", "team", "description", "description_sections"} & set(listed)
    assert detail["listed_days"] is not None


async def test_the_age_an_agent_reads_is_the_age_the_board_shows(scoped):
    """Every surface has one listing age, from the earlier of the employer's
    date and our first sighting. A tool on our sighting clock would call a
    posting the employer dated 164 days ago 2 days old and sort it among the
    newest."""
    await _allow(scoped)
    scoped.add(_company("openai"))
    real_now = datetime.now(UTC)
    employer_dated = _job(51, "openai", first_seen=real_now - timedelta(days=2, hours=1))
    # In the writer's shape: read once, the employer's date is also its first.
    employer_dated.posted_at = employer_dated.first_posted_at = real_now - timedelta(days=164, hours=1)
    watched = _job(52, "openai", first_seen=real_now - timedelta(days=30, hours=1))
    watched.posted_at = watched.first_posted_at = real_now - timedelta(days=30, hours=1)
    scoped.add_all([employer_dated, watched])
    await scoped.commit()

    newest = (await server.search_opportunities(sort="newest"))["items"]
    oldest = (await server.search_opportunities(sort="oldest"))["items"]
    detail = await server.get_opportunity(51)

    assert [item["id"] for item in newest] == [52, 51]
    assert [item["id"] for item in oldest] == [51, 52]
    assert [item["listed_days"] for item in oldest] == [164, 30]
    assert detail["listed_days"] == 164
    assert detail["listed_basis"] == "employer"
    assert [item["listed_basis"] for item in oldest] == ["employer", "sighting"]
    assert "days_open" not in detail, "one age per posting, not a second clock beside it"


async def test_the_history_tool_answers_what_the_history_route_answers(scoped, api_client):
    """One builder behind both doors: the tool's payload is the
    route's, key for key, so an agent and the History popover read one history."""
    await _allow(scoped)
    scoped.add(_company("openai"))
    real_now = datetime.now(UTC)
    job = _job(61, "openai", first_seen=real_now - timedelta(days=20, hours=1))
    job.posted_at = real_now - timedelta(days=5)
    job.first_posted_at = real_now - timedelta(days=90, hours=1)
    scoped.add(job)
    await scoped.commit()

    tool = await server.listing_history(61)
    route = (await api_client.get("/api/jobs/61/history")).json()

    assert tool["headline"]["days"] == 90 and tool["headline"]["basis"] == "employer"
    assert [e["kind"] for e in tool["events"]] == [e["kind"] for e in route["events"]]
    assert set(tool) == set(route) == {"headline", "role", "events", "unconfirmed"}
    with pytest.raises(LookupError, match="opportunity not found"):
        await server.listing_history(999_999)


async def test_a_hidden_company_s_posting_is_still_readable_by_id(scoped):
    """Search excludes it; a by-id read does not, exactly as the HTTP by-id
    exemption works. Characterized, not asserted as desirable."""
    await _allow(scoped)
    ids = await _seed_board(scoped)

    assert (await server.get_opportunity(ids["hidden_company"]))["company"] == "shadow"


async def test_employer_stated_pay_is_absent_until_the_posting_was_parsed(scoped):
    """`structured_at is None` means nothing was extracted, so an empty pay block
    would read as "the employer disclosed nothing" — a different claim."""
    await _allow(scoped)
    scoped.add(_company("openai"))
    scoped.add_all([_job(31, "openai"), _job(32, "openai", structured=True)])
    await scoped.commit()

    assert (await server.get_opportunity(31))["employer_stated_pay"] is None
    stated = (await server.get_opportunity(32))["employer_stated_pay"]
    assert stated["low"] == 300_000 and stated["snippet"] == "$300,000 - $360,000"
    assert (await server.get_opportunity(31))["estimated_total_comp"]["provenance"] == "model"


async def test_a_checked_posting_that_states_no_pay_has_no_period(scoped):
    """With no stated amount, the period guard has nothing to check.
    An absent band must not produce a period uncertainty claim."""
    await _allow(scoped)
    scoped.add(_company("openai"))
    silent = _job(33, "openai")
    silent.structured_at = NOW
    salary_stored_hourly = _job(34, "openai", structured=True)
    salary_stored_hourly.disclosed_pay_period = "hour"
    scoped.add_all([silent, salary_stored_hourly])
    await scoped.commit()

    stated = (await server.get_opportunity(33))["employer_stated_pay"]
    assert stated["low"] is None and stated["period"] is None
    # Control: with an amount, the guard still serves a contradiction as such.
    assert (await server.get_opportunity(34))["employer_stated_pay"]["period"] == "unclear"


# --------------------------------------------------------------------------- #
# 4. Pursuits, read
# --------------------------------------------------------------------------- #


async def _seed_pursuits(session) -> dict[str, int]:
    ids = await _seed_board(session)
    session.add_all(
        [
            Pursuit(job_id=ids["newest"], stage="applied", priority=2, updated_at=NOW),
            Pursuit(job_id=ids["richest"], stage="offer", priority=1, updated_at=NOW),
        ]
    )
    await session.commit()
    return ids


async def test_pursuits_are_listed_by_priority_then_recency(scoped):
    await _allow(scoped)
    ids = await _seed_pursuits(scoped)

    listed = await server.get_pursuits()

    assert [item["job_id"] for item in listed["items"]] == [ids["richest"], ids["newest"]]
    assert listed["count"] == 2
    assert listed["items"][0]["opportunity"]["company"] == "anthropic"


async def test_a_stage_filter_answers_only_that_stage(scoped):
    await _allow(scoped)
    ids = await _seed_pursuits(scoped)

    assert [item["job_id"] for item in (await server.get_pursuits(stage="applied"))["items"]] == [
        ids["newest"]
    ]
    assert (await server.get_pursuits(stage="withdrawn"))["items"] == []


@pytest.mark.parametrize(("limit", "expected"), [(0, 1), (1, 1), (500, 2)])
async def test_the_pursuit_limit_is_clamped_too(scoped, limit, expected):
    await _allow(scoped)
    await _seed_pursuits(scoped)

    assert len((await server.get_pursuits(limit=limit))["items"]) == expected


# --------------------------------------------------------------------------- #
# 5. Pursuits, write
# --------------------------------------------------------------------------- #


async def test_saving_an_opportunity_creates_the_pursuit_the_favorite_and_the_event(scoped):
    await _allow(scoped)
    ids = await _seed_board(scoped)

    saved = await server.save_opportunity(ids["newest"], priority=1)

    assert (saved["stage"], saved["priority"], saved["job_id"]) == ("saved", 1, ids["newest"])
    scoped.expire_all()
    assert await scoped.scalar(select(Favorite.job_id).where(Favorite.job_id == ids["newest"]))
    event = await scoped.scalar(select(PursuitEvent))
    assert (event.actor, event.event_type, event.to_stage) == ("agent", "created", "saved")


async def test_saving_the_same_opportunity_twice_leaves_one_pursuit_and_one_favorite(scoped):
    """`idempotentHint=True` is what the tool annotation promises the client."""
    await _allow(scoped)
    ids = await _seed_board(scoped)

    first = await server.save_opportunity(ids["newest"])
    second = await server.save_opportunity(ids["newest"])

    assert first["id"] == second["id"]
    scoped.expire_all()
    favorites = (await scoped.scalars(select(Favorite.id))).all()
    pursuits = (await scoped.scalars(select(Pursuit.id))).all()
    assert (len(favorites), len(pursuits)) == (1, 1)


async def test_an_update_leaves_the_fields_it_was_not_given(scoped):
    """The tool drops `None` before building the payload, so an absent argument
    is "unchanged" rather than "clear it"."""
    await _allow(scoped)
    ids = await _seed_board(scoped)
    await server.save_opportunity(ids["newest"], priority=2)
    await server.update_pursuit(ids["newest"], notes="Referred by A.")

    updated = await server.update_pursuit(ids["newest"], stage="applied")

    assert (updated["stage"], updated["priority"], updated["notes"]) == (
        "applied", 2, "Referred by A.",
    )


async def test_an_update_that_names_no_field_is_refused(scoped):
    await _allow(scoped)
    ids = await _seed_board(scoped)
    await server.save_opportunity(ids["newest"])

    with pytest.raises(ValueError, match="at least one pursuit field"):
        await server.update_pursuit(ids["newest"])


async def test_a_stage_change_appends_an_event_naming_both_stages(scoped):
    await _allow(scoped)
    ids = await _seed_board(scoped)
    await server.save_opportunity(ids["newest"])

    await server.update_pursuit(ids["newest"], stage="interviewing")

    scoped.expire_all()
    events = (await scoped.scalars(select(PursuitEvent).order_by(PursuitEvent.id))).all()
    assert [(e.event_type, e.from_stage, e.to_stage) for e in events] == [
        ("created", None, "saved"),
        ("updated", "saved", "interviewing"),
    ]


async def test_saving_a_role_already_pursued_moves_nothing_back(scoped):
    """"Save this role" on a pursuit the user moved on must not reset it: the
    stage, the priority and the notes are the user's."""
    await _allow(scoped)
    ids = await _seed_board(scoped)
    await server.update_pursuit(ids["newest"], stage="interviewing", priority=1, notes="Panel on Thursday.")

    again = await server.save_opportunity(ids["newest"])

    assert (again["stage"], again["priority"], again["notes"]) == ("interviewing", 1, "Panel on Thursday.")
    reprioritised = await server.save_opportunity(ids["newest"], priority=4)
    assert (reprioritised["stage"], reprioritised["priority"]) == ("interviewing", 4)


async def test_a_change_keeps_the_value_it_replaced_in_the_event_log(scoped):
    """The dashboard and docs/mcp.md promise both versions survive an agent's
    write: the event carries what each field was and what it became."""
    await _allow(scoped)
    ids = await _seed_board(scoped)
    await server.update_pursuit(ids["newest"], notes="Recruiter: Ada, call on Monday.")

    await server.update_pursuit(ids["newest"], notes="Emailed the recruiter.", priority=2)

    scoped.expire_all()
    last = await scoped.scalar(select(PursuitEvent).order_by(PursuitEvent.id.desc()).limit(1))
    assert last.detail["changed"] == ["notes", "priority"]
    assert last.detail["before"]["notes"] == "Recruiter: Ada, call on Monday."
    assert last.detail["after"] == {"notes": "Emailed the recruiter.", "priority": 2}


async def test_writing_against_an_unknown_opportunity_changes_nothing(scoped):
    await _allow(scoped)
    await _seed_board(scoped)

    with pytest.raises(LookupError, match="opportunity not found"):
        await server.save_opportunity(999_999)

    scoped.expire_all()
    assert (await scoped.scalars(select(Pursuit.id))).all() == []
    assert (await scoped.scalars(select(Favorite.id))).all() == []


# --------------------------------------------------------------------------- #
# 6. The radar summary
# --------------------------------------------------------------------------- #


async def test_the_radar_summary_counts_what_each_of_its_names_says(scoped):
    await _allow(scoped)
    ids = await _seed_pursuits(scoped)
    scoped.add(Favorite(job_id=ids["newest"]))
    await scoped.commit()

    summary = await server.get_radar_summary()

    assert summary["open_opportunities"] == 2, "visible and in scope only"
    assert summary["saved_opportunities"] == 1
    assert summary["active_pursuits"] == 2
    assert summary["pursuits_by_stage"] == {"applied": 1, "offer": 1}


async def test_an_empty_radar_answers_zeros_rather_than_nulls(scoped):
    await _allow(scoped)

    assert await server.get_radar_summary() == {
        "open_opportunities": 0,
        "saved_opportunities": 0,
        "active_pursuits": 0,
        "overdue_next_actions": 0,
        "pursuits_by_stage": {},
    }


# --------------------------------------------------------------------------- #
# 7. Where MCP and HTTP mean different things by the same word
# --------------------------------------------------------------------------- #


async def test_saved_only_keeps_a_role_the_reader_hid_or_dismissed(scoped):
    """`saved_only` maps to the browse owner's `favorites_only`, which carries
    the exemptions with it — and that is the point of routing through one owner
    rather than copying three conditions. A saved role stays reachable after the
    reader dismisses it or hides its company, exactly as it does on Saved; an
    inner join here would answer the opposite for the hidden one.
    """
    await _allow(scoped)
    ids = await _seed_board(scoped)
    scoped.add_all([
        Favorite(job_id=ids["richest"]),
        Favorite(job_id=ids["hidden_company"]),
        JobFeedback(job_id=ids["richest"], verdict="dismissed", created_at=NOW),
    ])
    await scoped.commit()

    saved = {item["id"] for item in (await server.search_opportunities(saved_only=True))["items"]}
    assert saved == {ids["richest"], ids["hidden_company"]}

    # The ordinary board still answers neither of them.
    browsed = {item["id"] for item in (await server.search_opportunities())["items"]}
    assert browsed == {ids["newest"]}


async def test_search_answers_the_same_set_as_the_browse_owner(scoped):
    """One board, ONE answer.

    A posting the user dismissed ("not for me") is hidden from every HTTP
    surface, and must be hidden from the agent too, the one consumer most
    likely to recommend it back. The tool builds its conditions from
    `db/queries/jobs.py`, so the comparison below is the standing contract.
    """
    await _allow(scoped)
    ids = await _seed_board(scoped)
    scoped.add(JobFeedback(job_id=ids["richest"], verdict="dismissed", created_at=NOW))
    await scoped.commit()

    browse = set(
        (
            await scoped.scalars(
                apply_job_filters(select(Job.id), {"status": "open", "hidden": ["shadow"]})
            )
        ).all()
    )
    agent = {item["id"] for item in (await server.search_opportunities())["items"]}

    assert agent == browse


async def test_the_open_count_agrees_with_the_count_the_dashboard_shows(scoped):
    """The same fact on two surfaces. `/api/stats` counts open in-scope postings
    with the hidden companies excluded. An INNER JOIN on the roster would answer
    the same number here and NOT in general: a posting whose company has no
    roster row is dropped by a join and kept by an exclusion. Both call
    `open_in_scope_count_stmt`.
    """
    await _allow(scoped)
    await _seed_board(scoped)

    shown = await scoped.scalar(open_in_scope_count_stmt(await off_board_company_slugs(scoped)))
    summary = await server.get_radar_summary()

    assert summary["open_opportunities"] == shown == 2


async def test_the_overdue_count_agrees_with_the_notification_owner(scoped):
    """One definition of "owed".

    `pursuit_due.TERMINAL_STAGES` deliberately omits `offer` — "an outstanding
    offer is the point at which a missed follow-up costs the most" — so a tool
    that excluded it would hide the one overdue follow-up the product considers
    most expensive. The boundary is `<=`, so a follow-up due exactly now is
    owed. Both read `overdue_pursuit_clause`, which is what this compares
    against — a re-spelled predicate here would be a third definition.
    """
    await _allow(scoped)
    ids = await _seed_board(scoped)
    scoped.add_all(
        [
            Pursuit(job_id=ids["newest"], stage="offer", priority=1,
                    next_action_due=NOW - timedelta(days=2), updated_at=NOW),
            Pursuit(job_id=ids["richest"], stage="applied", priority=2,
                    next_action_due=NOW - timedelta(days=1), updated_at=NOW),
        ]
    )
    await scoped.commit()

    owed = await scoped.scalar(
        select(func.count(Pursuit.id)).where(overdue_pursuit_clause(datetime.now(UTC)))
    )
    summary = await server.get_radar_summary()

    assert summary["overdue_next_actions"] == owed


async def test_a_base_only_estimate_is_a_base_never_an_empty_total(scoped):
    """Our dataset prices some postings by their base alone. The agent reads
    that as a base, with no total, never a total object of nulls beside a
    provenance and no base at all."""
    await _allow(scoped)
    scoped.add(_company("openai"))
    base_only = _job(41, "openai", comp_median=None)
    base_only.comp_component, base_only.comp_provider = "base", "builtin"
    base_only.comp_low = base_only.comp_high = None  # as the writer stores a base-only estimate
    base_only.comp_base_low, base_only.comp_base_median, base_only.comp_base_high = 255_000, 300_000, 345_000
    total = _job(42, "openai")
    total.comp_component = "total"
    scoped.add_all([base_only, total])
    await scoped.commit()

    got = await server.get_opportunity(41)
    assert got["estimated_total_comp"] is None
    assert got["estimate_component"] == "base"
    assert got["estimated_base"] == {"low": 255_000, "median": 300_000, "high": 345_000, "currency": "USD",
                                     "provider": "builtin", "as_of": None}
    priced = await server.get_opportunity(42)
    assert priced["estimate_component"] == "total" and priced["estimated_total_comp"]["median"] == 600_000
    assert priced["estimated_base"] is None
