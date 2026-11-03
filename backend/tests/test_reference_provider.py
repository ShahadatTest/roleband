"""The reference tables name who published each row.

A plugin's pay row and the built-in one for the same company, family and rung
must coexist, so disabling the plugin gives the built-in row back instead of
having overwritten it. Keyed without `provider`, the second insert would be a
unique violation.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from sqlalchemy import insert, select
from sqlalchemy.exc import IntegrityError

from tracker.db.models import (
    CompanyBenefit,
    CompanyCompLevel,
    CompanyProfile,
    ExternalCompObservation,
)

pytestmark = pytest.mark.asyncio

_AT = datetime(2026, 10, 1, tzinfo=UTC)


def _rung(**kw) -> CompanyCompLevel:
    return CompanyCompLevel(
        company_slug="acme", family="software-engineer", level_label="L5", band="senior",
        tc_median=400_000, fetched_at=_AT, **kw,
    )


async def _profile(db_session) -> None:
    db_session.add(CompanyProfile(slug="acme", display_name="Acme"))
    await db_session.flush()


async def test_a_row_written_without_a_provider_is_refused(db_session):
    """Every writer names who published a row, so a row with no provider is an
    error, never a row nobody answers for."""
    await _profile(db_session)
    db_session.add(_rung())
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_two_providers_hold_the_same_rung_side_by_side(db_session):
    await _profile(db_session)
    db_session.add_all([_rung(provider="manual"), _rung(provider="example-plugin")])
    await db_session.flush()
    providers = (await db_session.execute(select(CompanyCompLevel.provider))).scalars().all()
    assert sorted(providers) == ["example-plugin", "manual"]


async def test_one_provider_still_holds_a_rung_once(db_session):
    await _profile(db_session)
    db_session.add_all([_rung(provider="manual"), _rung(provider="manual")])
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_benefits_and_observations_coexist_across_providers(db_session):
    await _profile(db_session)
    db_session.add_all([
        CompanyBenefit(company_slug="acme", name="401k", category="Financial", provider="manual"),
        CompanyBenefit(company_slug="acme", name="401k", category="Financial", provider="example-plugin"),
    ])
    row = dict(
        company_slug="acme", source_level="L5", total_amount=1, base_amount=1, equity_amount=0, bonus_amount=0, currency="USD",
        snapshot_date=date(2026, 10, 1),
        dedup_key="k", ingested_at=_AT,
    )
    # A multi-row insert names its provider, as every writer does.
    await db_session.execute(insert(ExternalCompObservation).values([{**row, "provider": "example"}]))
    db_session.add(ExternalCompObservation(**row, provider="other-plugin"))
    await db_session.flush()
    assert sorted((await db_session.execute(select(ExternalCompObservation.provider))).scalars()) == [
        "example", "other-plugin",
    ]
