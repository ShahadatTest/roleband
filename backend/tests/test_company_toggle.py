"""Built-in and user-added companies share one store: the tracked_company table.

Built-ins are seeded as rows by `ensure_builtins`; toggling enable/visibility and
computing off-Board slugs go through the same table for every company. No app_settings
special case applies.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from tracker import company_store
from tracker.config import COMPANIES


class _Result:
    """Minimal stand-in for a compiled/executed statement capture."""

    def __init__(self, stmt):
        self.stmt = stmt


class EnsureFakeSession:
    """Captures the upsert statements ensure_builtins issues (no real DB)."""

    def __init__(self):
        self.executed = []

    async def execute(self, stmt):
        if stmt.is_select:
            # An install that has started (a row exists), so only built-ins are
            # upserted; with no stored adapter, none of them has moved.
            return SimpleNamespace(all=list, first=lambda: ("apple",))
        self.executed.append(stmt)
        return _Result(stmt)


def test_ensure_builtins_upserts_one_row_per_config_company():
    session = EnsureFakeSession()
    asyncio.run(company_store.ensure_builtins(session))

    # Exactly one upsert per built-in; each carries source='builtin' and the
    # config adapter/display.
    assert len(session.executed) == len(COMPANIES)
    compiled = [str(s.compile(compile_kwargs={"literal_binds": True})) for s in session.executed]
    joined = "\n".join(compiled)
    for slug in COMPANIES:
        assert slug in joined
    assert "'builtin'" in joined
    # It must not clobber operator state: the conflict update touches only
    # display/adapter/source, never enabled/visible/status.
    for sql in compiled:
        upsert = sql.split("ON CONFLICT", 1)[1] if "ON CONFLICT" in sql else ""
        assert "enabled" not in upsert
        assert "visible" not in upsert


@pytest.mark.asyncio
async def test_off_the_board_is_hidden_or_not_followed(db_session):
    """On real rows: hidden (followed or not), unfollowed and pending
    companies are off the Board; a followed, visible company is the only kind
    on it."""
    from tests.factories import make_company

    db_session.add_all([
        make_company("on-board", "On Board"),
        make_company("hidden", "Hidden", visible=False),
        make_company("unfollowed", "Unfollowed", enabled=False),
        make_company("both", "Both", visible=False, enabled=False),
        make_company("pending", "Pending", status="pending", enabled=True),
    ])
    await db_session.commit()
    off = set(await company_store.off_board_company_slugs(db_session))
    mine = {"on-board", "hidden", "unfollowed", "both", "pending"}
    assert off & mine == {"hidden", "unfollowed", "both", "pending"}
    assert set(await company_store.unfollowed_company_slugs(db_session)) & mine == {
        "unfollowed", "both", "pending",
    }


def test_is_builtin_still_identifies_config_companies():
    assert company_store.is_builtin("google") is True
    assert company_store.is_builtin("amazon") is True
    assert company_store.is_builtin("acme-startup") is False


def test_builtin_slug_cannot_be_added_as_a_new_company():
    # add_company must still reject built-in slugs (they are seeded, not user-added).
    fields = {"slug": "google", "display": "Google", "adapter": "google"}

    class _GetNoneSession:
        async def get(self, model, key):
            return None

    try:
        asyncio.run(company_store.add_company(_GetNoneSession(), fields))
        raised = False
    except company_store.CompanyConflict:
        raised = True
    assert raised, "adding a built-in slug should raise CompanyConflict"
