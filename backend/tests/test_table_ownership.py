"""Table-ownership completeness — the gate that keeps derived data automated.

A table whose only producer is a manual CLI (an empty `clusters` table because
`rebuild_clusters` ran only by hand) survives unless something asserts that
every table has an automatic populator. This suite is that assertion:

* Every mapped table is claimed exactly once in `tracker/db/ownership.py`.
  Adding a model without a claim fails here, naming the table.
* Every `post_pass:<name>` claim names a real POST_PASSES entry, so a derived
  table can't claim a pass that doesn't run it.
* Every `manual:<route>` claim names a route in the frozen route table, so the
  refresh trigger can't silently vanish.

Each entry is a `TableOwnership`, so a claim arrives beside
the table's writers, read owner and lifecycle. Those three are held to the code
by `test_table_writers.py`; this file still owns the claim itself.

Never weaken this to land a table — declare its populator instead.
"""

from __future__ import annotations

import json
from pathlib import Path

from tracker.db.models import Base
from tracker.db.ownership import TABLE_OWNERS, parse_claim
from tracker.workflows.post_passes import POST_PASSES

_VALID_KINDS = {"core", "post_pass", "user", "manual", "seed", "infra", "planned"}
_ROUTE_TABLE = Path(__file__).parent / "fixtures" / "route_table.json"


def _frozen_paths() -> set[str]:
    # The fixture is an object so it can also carry each route's declared
    # response model; `routes` is the route list.
    return {row["path"] for row in json.loads(_ROUTE_TABLE.read_text())["routes"]}


def test_every_table_is_claimed_exactly_once():
    tables = set(Base.metadata.tables)
    claimed = set(TABLE_OWNERS)
    unclaimed = tables - claimed
    unknown = claimed - tables
    assert not unclaimed, (
        "tables with no ownership claim (declare a populator in "
        f"tracker/db/ownership.py): {sorted(unclaimed)}"
    )
    assert not unknown, f"ownership claims for nonexistent tables: {sorted(unknown)}"


def test_claim_kinds_are_valid():
    bad = {
        table: claim.claim
        for table, claim in TABLE_OWNERS.items()
        if parse_claim(claim.claim)[0] not in _VALID_KINDS
    }
    assert not bad, f"unknown claim kind(s): {bad}"


def test_post_pass_claims_name_real_passes():
    pass_names = {p.name for p in POST_PASSES}
    dangling = {
        table: parse_claim(claim.claim)[1]
        for table, claim in TABLE_OWNERS.items()
        if parse_claim(claim.claim)[0] == "post_pass" and parse_claim(claim.claim)[1] not in pass_names
    }
    assert not dangling, (
        f"post_pass claims naming no registered POST_PASSES entry: {dangling}. "
        f"Known passes: {sorted(pass_names)}"
    )


def test_every_derived_pass_owns_at_least_one_table():
    # A pass that persists rows should be discoverable through ownership. The
    # column-only passes write into existing tables (jobs.*), so they own none;
    # the row-producing passes must each appear. This catches wiring a pass but
    # forgetting to reclaim the table it now owns.
    claimed_passes = {
        parse_claim(claim.claim)[1]
        for claim in TABLE_OWNERS.values()
        if parse_claim(claim.claim)[0] == "post_pass"
    }
    row_producing = {
        "skills_requirements",
        "lineage",
        "twins",
        "clusters",
        "similarity",
        "demand_metrics",
        "skill_demand",
        "comp_metrics",
        "disclosure_metrics",
        "prices",
    }
    missing = row_producing - claimed_passes
    assert not missing, f"row-producing passes owning no table: {sorted(missing)}"


def test_manual_claims_name_frozen_routes():
    paths = _frozen_paths()
    dangling = {
        table: parse_claim(claim.claim)[1]
        for table, claim in TABLE_OWNERS.items()
        if parse_claim(claim.claim)[0] == "manual" and parse_claim(claim.claim)[1] not in paths
    }
    assert not dangling, (
        f"manual claims naming a route absent from the frozen route table: {dangling}"
    )
