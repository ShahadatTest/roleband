"""A plugin benefit keeps the country it applies in.

The same perk stated for two countries is two rows, the profile shows each
with its country, and a perk whose source names no country is shown as
unscoped, never as a company-wide policy.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError
from roleband_plugin_sdk.slots import Benefit
from roleband_plugin_sdk.testing import Batch, RunResult
from sqlalchemy import select

from tracker.db.models import CompanyBenefit, CompanyProfile
from tracker.plugins.registry import COMPANY_BENEFITS
from tracker.plugins.writer import retire_unpublished, write_batch
from tracker.profiles.benefits_builtin import plugin_benefits

PLUGIN = "tpl"


def _perk(country: str | None, value_text: str) -> dict:
    return Benefit(name="Parental leave", category="Family", value_text=value_text, country=country).model_dump()


async def _company(db) -> None:
    db.add(CompanyProfile(slug="acme", display_name="Acme"))
    await db.commit()


async def _live(db) -> list[CompanyBenefit]:
    return list((await db.execute(
        select(CompanyBenefit).where(CompanyBenefit.retired_at.is_(None))
        .order_by(CompanyBenefit.country.nulls_first())
    )).scalars())


def test_a_benefit_names_its_country_by_iso_code():
    assert Benefit(name="Leave", category="Family", country="DE").country == "DE"
    assert Benefit(name="Leave", category="Family").country is None
    with pytest.raises(ValidationError):
        Benefit(name="Leave", category="Family", country="germany")


@pytest.mark.asyncio
async def test_one_perk_for_two_countries_is_two_rows_and_each_reads_its_own(db_session):
    await _company(db_session)
    await write_batch(db_session, PLUGIN, COMPANY_BENEFITS, "acme", [_perk("DE", "14 months"), _perk("US", "16 weeks")])
    await write_batch(db_session, PLUGIN, COMPANY_BENEFITS, "acme", [_perk("US", "20 weeks")])
    await db_session.commit()
    rows = await _live(db_session)
    assert [(r.country, r.value_text) for r in rows] == [("DE", "14 months"), ("US", "20 weeks")]
    (item,) = [item for group in plugin_benefits(rows) for item in group["items"]]
    said = [(item["country"], item["value_text"])] + [(w["country"], w["text"]) for w in item["wordings"]]
    assert sorted(said) == [("DE", "14 months"), ("US", "20 weeks")], "each wording keeps its country"


@pytest.mark.asyncio
async def test_a_perk_with_no_country_reads_as_unscoped_and_still_retires(db_session):
    """No country is one value: a re-publish updates its row, and a complete
    publish without it retires it."""
    await _company(db_session)
    await write_batch(db_session, PLUGIN, COMPANY_BENEFITS, "acme", [_perk(None, "16 weeks")])
    await write_batch(db_session, PLUGIN, COMPANY_BENEFITS, "acme", [_perk(None, "18 weeks")])
    await db_session.commit()
    rows = await _live(db_session)
    assert [(r.country, r.value_text) for r in rows] == [(None, "18 weeks")]
    items = [item for group in plugin_benefits(rows) for item in group["items"]]
    assert [i["country"] for i in items] == [None]

    kept = await write_batch(db_session, PLUGIN, COMPANY_BENEFITS, "acme", [_perk("DE", "14 months")])
    assert await retire_unpublished(db_session, PLUGIN, COMPANY_BENEFITS, "acme", kept) == 1
    await db_session.commit()
    assert [r.country for r in await _live(db_session)] == ["DE"]


def test_the_sdk_test_host_keys_a_benefit_by_name_and_country():
    rows = [Benefit(name="Parental leave", category="Family", value_text=text, country=country)
            for country, text in (("DE", "14 months"), ("US", "16 weeks"), ("US", "20 weeks"))]
    result = RunResult("clean", [Batch(COMPANY_BENEFITS, "acme", tuple(rows), True)], [], [], [], [], {})
    assert sorted((r.country, r.value_text) for r in result.rows(COMPANY_BENEFITS, "acme")) == [
        ("DE", "14 months"), ("US", "20 weeks")]
