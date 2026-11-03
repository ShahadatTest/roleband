"""A killed suite's leftovers are cleared, and nothing that is not one.

A throwaway cluster under the suite's temp root is stopped and the root removed;
a cluster beside it, under a root whose name only starts the same, keeps running.
A scratch database is dropped when the process its name carries is gone, and kept
while that process lives or when the name is not a scratch database's at all.
"""

from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from tests.conftest import _base_url
from tracker.supervisor import residue

pytest.importorskip("pixeltable_pgserver", reason="embedded Postgres wheel not installed")

from tests.embedded_utils import cluster_locale, destroy  # noqa: E402
from tracker.platform.embedded_db import ensure_server  # noqa: E402

#: Above any real pid_max, so never a live process.
DEAD = 2**22


def test_a_live_process_is_alive_and_an_impossible_pid_is_not():
    assert residue.pid_alive(os.getpid())
    assert not residue.pid_alive(DEAD)


def test_clusters_under_the_suite_root_are_stopped_and_a_neighbour_is_not(tmp_path):
    suite = tmp_path / "suite"
    neighbour = tmp_path / "suite2"
    inside = ensure_server(suite / "popen-gw0" / "pg", database="probe", locale=cluster_locale())
    beside = ensure_server(neighbour / "pg", database="probe", locale=cluster_locale())
    try:
        assert residue.clusters_under(suite) == [inside.pgdata.resolve()]

        outcome = residue.clean(suite, None)

        assert outcome == {"failures": [], "dropped": []}
        assert residue.clusters_under(suite) == []
        assert not suite.exists(), "the root goes once nothing runs there"
        assert residue.clusters_under(neighbour) == [beside.pgdata.resolve()]
    finally:
        for server in (inside, beside):
            if server.pgdata.exists():
                destroy(server.pgdata)


@pytest.mark.asyncio
async def test_only_scratch_databases_of_gone_processes_are_dropped():
    base = _base_url()
    if base is None:
        pytest.skip("no database configured")
    tag = uuid.uuid4().int % 10**6
    dead = f"roleband_test_{DEAD + tag}"
    live = f"roleband_test_{DEAD + tag + 1}"
    other = f"roleband_test_{DEAD + tag}_kept"
    names = (dead, live, other)
    admin = create_async_engine(base.set(database="postgres"), isolation_level="AUTOCOMMIT")
    try:
        async with admin.connect() as conn:
            for name in names:
                await conn.execute(text(f'CREATE DATABASE "{name}"'))

        # Only `dead`'s process is gone: every other scratch database counts as
        # alive, so a real suite elsewhere is untouched.
        dropped = await residue.drop_dead_test_databases(base, alive=lambda pid: pid != DEAD + tag)

        async with admin.connect() as conn:
            present = set((await conn.execute(text("SELECT datname FROM pg_database"))).scalars())
        assert dropped == [dead]
        assert dead not in present
        assert {live, other} <= present
    finally:
        async with admin.connect() as conn:
            for name in names:
                await conn.execute(text(f'DROP DATABASE IF EXISTS "{name}"'))
        await admin.dispose()
