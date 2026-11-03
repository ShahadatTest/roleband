"""A pay rung is stored in the currency its publisher stated, and read in it.

No figure is converted. A rate belongs to the day it was read, and an amount
converted once is wrong from then on, so a rung published in euros is stored
in euros, priced in euros, and never compared with a dollar figure.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from sqlalchemy import select

from tests.plugin_seed import cover
from tracker.db.models import CompanyCompLevel, CompanyProfile, Job, PluginInstall
from tracker.plugins.reestimate import reestimate
from tracker.plugins.registry import PAY_LEVELS
from tracker.plugins.writer import write_batch

pytestmark = pytest.mark.asyncio

PLUGIN = "tpl"
AT = datetime(2026, 10, 1, tzinfo=UTC)


def _rung(currency: str, tc: int, *, country: str, label: str = "L6") -> dict:
    return {"family": "software_engineering", "vendor_family": None, "label": label, "aliases": [],
            "tc": tc, "base": tc // 2, "stock": None, "bonus": None, "currency": currency,
            "country": country, "source_url": None, "as_of": date(2026, 10, 1).isoformat()}


async def _company(db) -> None:
    db.add(CompanyProfile(slug="acme", display_name="Acme"))
    await db.commit()


async def _plugin_selected(db) -> None:
    db.add(PluginInstall(
        plugin_id=PLUGIN, name="Template", version="0.1.0", source_dir="/x", manifest_sha="m", code_sha="c",
        manifest={"provides": [{"slot": PAY_LEVELS}]}, fingerprint="fp1", approved_fingerprint="fp1", enabled=True,
    ))
    await db.flush()
    cover(db, PLUGIN, (PAY_LEVELS,), ("acme",))
    await db.commit()


async def test_a_rung_is_stored_in_the_currency_it_was_published_in(db_session):
    """Fail-first: the writer refused anything but USD, so a euro rung could
    not be published at all."""
    await _company(db_session)
    await write_batch(db_session, PLUGIN, PAY_LEVELS, "acme",
                      [_rung("USD", 600_000, country="US"), _rung("EUR", 120_000, country="DE")])
    await db_session.commit()

    rows = (await db_session.execute(
        select(CompanyCompLevel.currency, CompanyCompLevel.country, CompanyCompLevel.tc_median,
               CompanyCompLevel.base_amount).order_by(CompanyCompLevel.country))).all()
    assert [tuple(r) for r in rows] == [
        ("EUR", "DE", 120_000, 60_000),
        ("USD", "US", 600_000, 300_000),
    ]


async def test_a_posting_is_priced_in_the_currency_its_rung_was_published_in(db_session):
    """End to end: the figure and its currency travel together onto the job,
    or the number on the screen is a euro amount labelled in dollars."""
    await _company(db_session)
    await _plugin_selected(db_session)
    await write_batch(db_session, PLUGIN, PAY_LEVELS, "acme", [
        _rung("USD", 600_000, country="US", label="Senior Engineer"),
        _rung("EUR", 120_000, country="DE", label="Senior Engineer"),
    ])
    for key, groups in {"us": ["new_york"], "de": ["germany"]}.items():
        db_session.add(Job(company="acme", req_id=key, dedupe_key=f"acme:{key}",
                           title="Senior Software Engineer", url=f"https://example.com/{key}",
                           level_band="senior", family="software_engineering", location_groups=groups))
    await db_session.commit()
    await reestimate(db_session)

    priced = {j.req_id: (j.comp_median, j.comp_currency)
              for j in (await db_session.execute(select(Job))).scalars()}
    assert priced == {"us": (600_000, "USD"), "de": (120_000, "EUR")}
