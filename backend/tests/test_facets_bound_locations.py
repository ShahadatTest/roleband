"""The board offers the locations that HAVE roles; Settings offers all of them.

Two surfaces, deliberately different answers, and the difference is the whole
point of a taxonomy of hundreds of groups:

* `/api/facets` feeds the opportunities board. A filter option that can only
  ever return nothing is noise, and at hundreds of groups it is a wall of it.
* `/api/scope/catalog` feeds Settings. A market you cannot select is a market
  you cannot grow into, so every group is listed regardless of job count.

On the board, locations follow bands and workplace types, which offer no
zero-count options either.
"""

from __future__ import annotations

import asyncio

from tracker.api.routers.jobs import facets


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return list(self._rows)


class _FakeSession:
    """Answers the shapes `facets()` issues: grouped counts, the location
    unnest, the board total, and the settings lookup for the tracked scope."""

    def __init__(self, location_counts: dict[str, int], total: int = 0):
        self._location_counts = location_counts
        self._total = total

    async def execute(self, stmt, params=None):
        text = str(stmt).lower()
        if "unnest(jobs.location_groups)" in text:
            return _Result(list(self._location_counts.items()))
        return _Result([])

    async def scalar(self, stmt):
        return self._total

    async def scalars(self, stmt):
        return _Result([])

    async def get(self, *args, **kwargs):
        return None


async def _facets(
    location_counts: dict[str, int], tracked: list[str], monkeypatch, total: int = 0
):
    import tracker.api.routers.jobs as jobs_mod

    async def fake_enabled(session):
        return frozenset(tracked)

    async def fake_companies(session):
        return {}

    monkeypatch.setattr(jobs_mod, "get_enabled_locations", fake_enabled)
    monkeypatch.setattr(jobs_mod, "_visible_company_options", fake_companies)
    return await facets(_FakeSession(location_counts, total), [])


def test_a_tracked_location_with_no_jobs_is_not_offered_as_a_filter(monkeypatch):
    payload = asyncio.run(
        _facets({"united_states": 12}, ["united_states", "india", "uae"], monkeypatch)
    )

    assert set(payload["location_groups"]) == {"united_states"}
    # India and the UAE are tracked — the user asked for them — but nothing is
    # bound to them yet, so the board must not offer a filter that returns zero.
    assert "india" not in payload["location_groups"]
    assert "uae" not in payload["location_groups"]


def test_a_bound_location_that_is_not_tracked_is_also_not_offered(monkeypatch):
    """Both conditions, not either. Stored rows can carry a group the user has
    since untracked; the board follows the saved scope."""
    payload = asyncio.run(
        _facets({"united_states": 12, "japan": 4}, ["united_states"], monkeypatch)
    )

    assert set(payload["location_groups"]) == {"united_states"}


def test_offered_locations_all_carry_a_nonzero_count(monkeypatch):
    """The invariant, stated directly: every option the board renders can
    return at least one role."""
    payload = asyncio.run(
        _facets(
            {"united_states": 12, "uk": 3, "india": 0},
            ["united_states", "uk", "india", "singapore"],
            monkeypatch,
        )
    )

    counts = payload["counts"]["location_group"]
    assert set(payload["location_groups"]) == {"united_states", "uk"}
    for slug in payload["location_groups"]:
        assert counts.get(slug, 0) > 0, slug


def test_a_location_option_carries_the_parent_it_nests_under(monkeypatch):
    """The board register renders locations NESTED (metro under country), and
    the nesting is the taxonomy's, not a second tree invented in the client —
    so the option carries its own parent."""
    payload = asyncio.run(
        _facets(
            {"north_america": 20, "united_states": 12, "silicon_valley": 7},
            ["north_america", "united_states", "silicon_valley"],
            monkeypatch,
        )
    )

    # The real chain, three deep: metro -> country -> region.
    assert payload["location_groups"]["silicon_valley"]["parent"] == "united_states"
    assert payload["location_groups"]["united_states"]["parent"] == "north_america"
    # A root has the key with a null value, never a missing key: a client that
    # has to ask `"parent" in option` will get it wrong on exactly one group.
    assert payload["location_groups"]["north_america"]["parent"] is None


def test_facets_state_the_board_total_the_counts_are_a_share_of(monkeypatch):
    """Every count in the payload is a share of one number, and the client
    cannot compute it: summing `location_group` double-counts a role in two
    groups, and summing `company` includes companies the user has hidden. A
    value whose count equals this total narrows nothing, which is the whole
    reason the board is told."""
    payload = asyncio.run(
        _facets({"united_states": 40, "uk": 3}, ["united_states", "uk"], monkeypatch, total=40)
    )

    assert payload["total"] == 40
    assert payload["counts"]["location_group"]["united_states"] == payload["total"]


def test_domain_facet_offers_only_worlds_with_roles_plus_unclassified(monkeypatch):
    """Worlds follow the same board rule as locations: options track the data.
    The unclassified bucket appears only when fail-open rows exist."""

    class _DomainSession(_FakeSession):
        def __init__(self, domain_counts, unclassified):
            super().__init__({})
            self._domain_counts = domain_counts
            self._unclassified = unclassified

        async def execute(self, stmt, params=None):
            text = str(stmt).lower()
            if "unnest(jobs.domains)" in text:
                return _Result(list(self._domain_counts.items()))
            return await super().execute(stmt, params)

        async def scalar(self, stmt):
            if "cardinality(jobs.domains)" in str(stmt).lower():
                return self._unclassified
            return await super().scalar(stmt)

    async def _domain_facets(domain_counts, unclassified):
        import tracker.api.routers.jobs as jobs_mod

        async def fake_enabled(session):
            return frozenset()

        async def fake_companies(session):
            return {}

        monkeypatch.setattr(jobs_mod, "get_enabled_locations", fake_enabled)
        monkeypatch.setattr(jobs_mod, "_visible_company_options", fake_companies)
        return await facets(_DomainSession(domain_counts, unclassified), [])  # type: ignore[arg-type]

    payload = asyncio.run(_domain_facets({"ai_ml": 5, "retail_commerce": 2}, 3))
    assert set(payload["domains"]) == {"ai_ml", "retail_commerce", "unclassified"}
    # Named by the dashboard from its catalog: the option carries no English.
    assert payload["domains"]["unclassified"] == {}
    assert payload["counts"]["domain"] == {"ai_ml": 5, "retail_commerce": 2, "unclassified": 3}

    # No fail-open rows -> no unclassified option; a world with no roles is
    # never offered (nothing to return).
    empty = asyncio.run(_domain_facets({"ai_ml": 5}, 0))
    assert set(empty["domains"]) == {"ai_ml"}
    assert "unclassified" not in empty["counts"]["domain"]


def test_a_tracked_city_with_roles_is_offered_named_and_nested(monkeypatch):
    """A GeoNames city the user tracks is a board filter like any
    group: named by the gazetteer, nested under its country. An untracked city
    with roles is not offered, exactly as an untracked country is not."""
    stockholm, gothenburg = "city_2673730", "city_2711537"
    payload = asyncio.run(
        _facets(
            {"sweden": 5, "europe": 5, stockholm: 3, gothenburg: 2},
            ["sweden", stockholm],
            monkeypatch,
        )
    )
    assert payload["location_groups"][stockholm] == {"display": "Stockholm", "parent": "sweden"}
    assert gothenburg not in payload["location_groups"]
    assert list(payload["location_groups"]) == ["sweden", stockholm], "taxonomy first, then cities"
