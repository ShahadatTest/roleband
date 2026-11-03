"""Company Explorer reads: roster first, open-role counts second.

The roster (`/api/companies/discovery`) is what the screen needs to paint. It
must therefore be a *pure read* — no `ensure_builtins()` upsert+commit, no
`jobs` aggregate — so a running scrape holding `tracked_companies` row locks
cannot leave the screen blank. The counts are the slow, derived half and live
at `/api/companies/open-counts`.
"""

import asyncio

import pytest

from tracker.api.routers.companies import companies_discovery, companies_open_counts
from tracker.db.models import RoleCatalog, TrackedCompany

# Every test here reaches code that starts or signals a process on this
# machine, so none of them may.
pytestmark = pytest.mark.usefixtures("no_escape")


class _Scalars:
    def __init__(self, rows):
        self.rows = rows

    def all(self):
        return list(self.rows)


class _Rows:
    def __init__(self, rows):
        self.rows = rows

    def all(self):
        return list(self.rows)


class FakeSession:
    """Records every call so a hidden write on a read path fails the test."""

    def __init__(self, counts=(("meta", 16), ("amazon", 293))):
        self.counts = counts
        self.committed = 0
        self.executed = 0
        self.tracked = [
            TrackedCompany(
                slug="meta",
                display="Meta",
                adapter="meta",
                status="active",
                enabled=True,
                visible=True,
                source="builtin",
            )
        ]

    async def scalars(self, stmt):
        # Empty role catalog and hidden-slug inputs isolate the counts query.
        described = stmt.column_descriptions[0]
        if described.get("entity") is RoleCatalog or described.get("name") == "slug":
            return _Scalars([])
        return _Scalars(self.tracked)

    async def execute(self, stmt, _params=None):
        self.executed += 1
        if stmt.column_descriptions[0].get("entity") is RoleCatalog:
            return _Rows([])  # the same empty role catalog `scalars` answers
        return _Rows(self.counts)

    async def commit(self):
        self.committed += 1


def test_discovery_is_a_pure_read():
    session = FakeSession()
    state = asyncio.run(companies_discovery(session))

    assert state["companies"], "roster must render from the catalog alone"
    assert session.committed == 0, "a GET that writes can block behind a scrape's row locks"
    assert session.executed == 0, "no jobs aggregate belongs on the first-paint path"


def test_discovery_carries_no_open_role_counts():
    state = asyncio.run(companies_discovery(FakeSession()))
    meta = next(c for c in state["companies"] if c["slug"] == "meta")

    assert "job_count" not in meta
    # Identity + tracking state still come from this payload.
    assert meta["display"] == "Meta"
    assert meta["tracked"] is True
    assert meta["enabled"] is True


def test_open_counts_returns_count_per_slug():
    counts = asyncio.run(companies_open_counts(FakeSession()))["counts"]

    assert counts == {"meta": 16, "amazon": 293}


def test_open_counts_omits_companies_with_no_open_roles():
    counts = asyncio.run(companies_open_counts(FakeSession(counts=())))["counts"]

    # Absent, not zero: the client reads a missing slug as 0.
    assert counts == {}


@pytest.mark.parametrize("endpoint", [companies_discovery, companies_open_counts])
def test_read_endpoints_never_commit(endpoint):
    session = FakeSession()
    asyncio.run(endpoint(session))

    assert session.committed == 0
