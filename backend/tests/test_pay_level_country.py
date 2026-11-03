"""A pay rung is for one country, stored and read as such.

The same label a plugin states for two countries is two rows, a complete
publish retires a country it does not repeat, and a posting is priced only
from rows for the one country it is in: a figure true for one country is never
shown for a posting in another.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from sqlalchemy import select

from tests.plugin_seed import cover
from tracker.db.models import CompanyCompLevel, CompanyProfile, Job, PluginInstall
from tracker.db.queries.reference_pay import package_rows, pay_level_rows
from tracker.plugins.reestimate import reestimate
from tracker.plugins.registry import PAY_LEVELS, reader_providers
from tracker.plugins.writer import retire_unpublished, write_batch

pytestmark = pytest.mark.asyncio

PLUGIN = "tpl"
AT = datetime(2026, 10, 1, tzinfo=UTC)


def _rung(country: str | None, tc: int, *, label: str = "L6") -> dict:
    return {"family": "software_engineering", "vendor_family": None, "label": label, "aliases": [],
            "tc": tc, "base": tc // 2, "stock": None, "bonus": None, "currency": "USD", "country": country,
            "source_url": None, "as_of": date(2026, 10, 1).isoformat()}


async def _company(db) -> None:
    db.add(CompanyProfile(slug="acme", display_name="Acme"))
    await db.commit()


async def _live(db) -> list[tuple[str, str | None, int]]:
    rows = (await db.execute(select(CompanyCompLevel).where(CompanyCompLevel.retired_at.is_(None))
                             .order_by(CompanyCompLevel.country.nulls_first()))).scalars().all()
    return [(r.level_label, r.country, r.tc_median) for r in rows]


async def test_one_rung_stated_for_two_countries_is_two_rows(db_session):
    await _company(db_session)
    await write_batch(db_session, PLUGIN, PAY_LEVELS, "acme", [_rung("US", 600_000), _rung("GB", 260_000)])
    await db_session.commit()
    assert await _live(db_session) == [("L6", "GB", 260_000), ("L6", "US", 600_000)]


async def test_a_republished_country_updates_its_own_row_only(db_session):
    await _company(db_session)
    await write_batch(db_session, PLUGIN, PAY_LEVELS, "acme", [_rung("US", 600_000), _rung("GB", 260_000)])
    await write_batch(db_session, PLUGIN, PAY_LEVELS, "acme", [_rung("GB", 270_000)])
    await db_session.commit()
    assert await _live(db_session) == [("L6", "GB", 270_000), ("L6", "US", 600_000)]


async def test_a_complete_publish_retires_a_country_it_does_not_repeat(db_session):
    await _company(db_session)
    await write_batch(db_session, PLUGIN, PAY_LEVELS, "acme", [_rung("US", 600_000), _rung("GB", 260_000)])
    kept = await write_batch(db_session, PLUGIN, PAY_LEVELS, "acme", [_rung("US", 600_000)])
    assert await retire_unpublished(db_session, PLUGIN, PAY_LEVELS, "acme", kept) == 1
    await db_session.commit()
    assert await _live(db_session) == [("L6", "US", 600_000)]


async def test_a_rung_with_no_country_stays_one_row_and_still_retires(db_session):
    """No country is one value: a re-publish updates the row, never adds one,
    and a complete publish without it retires it (`NOT IN` against a NULL
    would keep it forever)."""
    await _company(db_session)
    await write_batch(db_session, PLUGIN, PAY_LEVELS, "acme", [_rung(None, 500_000)])
    await write_batch(db_session, PLUGIN, PAY_LEVELS, "acme", [_rung(None, 510_000)])
    await db_session.commit()
    assert await _live(db_session) == [("L6", None, 510_000)]
    kept = await write_batch(db_session, PLUGIN, PAY_LEVELS, "acme", [_rung("US", 600_000)])
    assert await retire_unpublished(db_session, PLUGIN, PAY_LEVELS, "acme", kept) == 1
    unchanged = await write_batch(db_session, PLUGIN, PAY_LEVELS, "acme", [_rung("US", 600_000)])
    assert await retire_unpublished(db_session, PLUGIN, PAY_LEVELS, "acme", unchanged) == 0
    await db_session.commit()
    assert await _live(db_session) == [("L6", "US", 600_000)]


async def _plugin_selected(db) -> None:
    db.add(PluginInstall(
        plugin_id=PLUGIN, name="Template", version="0.1.0", source_dir="/x", manifest_sha="m", code_sha="c",
        manifest={"provides": [{"slot": PAY_LEVELS}]}, fingerprint="fp1", approved_fingerprint="fp1", enabled=True,
    ))
    await db.flush()
    cover(db, PLUGIN, (PAY_LEVELS,), ("acme",))
    await db.commit()


async def test_each_posting_reads_only_its_own_country_s_rows(db_session):
    await _company(db_session)
    await _plugin_selected(db_session)
    await write_batch(db_session, PLUGIN, PAY_LEVELS, "acme", [
        _rung("US", 600_000, label="Senior Engineer"), _rung("GB", 260_000, label="Senior Engineer"),
    ])
    places = {"us": ["new_york"], "gb": ["london"], "both": ["new_york", "london"], "de": ["germany"]}
    for key, groups in places.items():
        db_session.add(Job(company="acme", req_id=key, dedupe_key=f"acme:{key}", title="Senior Software Engineer",
                           url=f"https://example.com/{key}", level_band="senior", family="software_engineering",
                           location_groups=groups))
    await db_session.commit()
    await reestimate(db_session)

    shown = {job.req_id: job.comp_median for job in (await db_session.execute(select(Job))).scalars()}
    assert shown == {"us": 600_000, "gb": 260_000, "both": None, "de": None}

    providers = await reader_providers(db_session)
    assert {r.country for r in await pay_level_rows(db_session, providers)} == {"US", "GB"}
    assert [r.country for r in await package_rows(db_session, providers, "acme", "GB")] == ["GB"]
    assert await package_rows(db_session, providers, "acme", None) == []


async def test_our_own_pay_prices_us_postings_only(db_session):
    """No plugin: our seed pay is US pay, so a London posting shows none of it."""
    for key, groups in {"us": ["silicon_valley"], "gb": ["london"]}.items():
        db_session.add(Job(company="google", req_id=key, dedupe_key=f"google:{key}", title="Staff Software Engineer",
                           url=f"https://example.com/{key}", level_band="staff", family=None,
                           location_groups=groups))
    await db_session.commit()
    await reestimate(db_session)
    shown = {job.req_id: job.comp_median for job in (await db_session.execute(select(Job))).scalars()}
    assert shown["us"] is not None and shown["gb"] is None
