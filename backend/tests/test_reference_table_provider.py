"""The comp estimate reads stored per-level rows, never a live fetch.

A family table fetched on every pipeline run, with the family guessed from the
title, would match no stored row. These tests pin the stored read: the job's own family at its band, through the rung the
package reads, rows for the posting's own country only (and US rows that can
stand for US pay), and no network inside enrichment.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from tracker.analytics.comp_package import pay_level_index
from tracker.comp_providers.base import CompContext
from tracker.comp_providers.static import StaticCompProvider
from tracker.comp_providers.table import ReferenceTableProvider
from tracker.db.models import CompanyCompLevel, CompanyProfile
from tracker.enrich.comp import CompResolver
from tracker.schema import LevelBand


def _row(company, family, band, label, base, tc, country="US", currency="USD"):
    return SimpleNamespace(
        company_slug=company, family=family, band=band, level_label=label, base_amount=base, tc_median=tc,
        currency=currency, provider="example", as_of=None, country=country,
    )


def _ctx(company="google", band=LevelBand.STAFF, family="software_engineering", country="US"):
    return CompContext(company=company, band=band, family=family, location_group=None, country=country,
                       title="any title")


def _provider(*rows):
    return ReferenceTableProvider(pay_level_index(rows))


@pytest.mark.asyncio
async def test_the_jobs_own_family_prices_it_and_the_source_names_no_site():
    provider = _provider(
        _row("google", "software_engineering", "staff", "L6", 280_000, 600_000),
        _row("google", "product_management", "staff", "L6", 270_000, 520_000),
    )
    estimate = await provider.lookup(_ctx(family="product_management"))
    assert estimate is not None and estimate.median == 520_000
    assert (estimate.low, estimate.high) == (int(520_000 * 0.85), int(520_000 * 1.15))
    # It says which of our families priced it, and names no site.
    assert estimate.source.endswith("(product_management)") and "://" not in estimate.source
    assert estimate.detail["borrowed"] is False



@pytest.mark.asyncio
async def test_a_source_names_the_company_as_people_write_it():
    """`openai` is OpenAI, not Openai; a company outside the built-in roster reads as words."""
    table = await _provider(
        _row("openai", "software_engineering", "senior", "L4", 250_000, 500_000),
        _row("acme-robotics", "software_engineering", "senior", "Senior", 180_000, 300_000),
    ).lookup(_ctx(company="openai", band=LevelBand.SENIOR))
    other = await _provider(
        _row("acme-robotics", "software_engineering", "senior", "Senior", 180_000, 300_000),
    ).lookup(_ctx(company="acme-robotics", band=LevelBand.SENIOR))
    seed = await StaticCompProvider().lookup(_ctx(company="openai", band=LevelBand.SENIOR))
    assert table is not None and table.source.startswith("OpenAI ")
    assert other is not None and other.source.startswith("Acme Robotics ")
    assert seed is not None and seed.source.startswith("OpenAI ")
    assert "seed" not in seed.source.lower()

@pytest.mark.asyncio
async def test_a_family_with_no_ladder_borrows_the_reference_ladder():
    provider = _provider(_row("google", "software_engineering", "staff", "L6", 280_000, 600_000))
    estimate = await provider.lookup(_ctx(family="ml_ai_research"))
    assert estimate is not None and estimate.median == 600_000
    assert estimate.detail["borrowed"] is True


@pytest.mark.asyncio
async def test_a_band_with_several_rungs_reads_the_declared_rung():
    """Microsoft 65-67 are all principal; the package reads 65, so must the estimate."""
    provider = _provider(
        _row("microsoft", "software_engineering", "principal", "67", 260_000, 700_000),
        _row("microsoft", "software_engineering", "principal", "65", 220_000, 400_000),
        _row("microsoft", "software_engineering", "principal", "66", 235_000, 520_000),
    )
    estimate = await provider.lookup(_ctx(company="microsoft", band=LevelBand.PRINCIPAL))
    assert estimate is not None and estimate.median == 400_000


@pytest.mark.asyncio
async def test_a_worldwide_mix_row_never_prices_a_posting():
    provider = _provider(_row("accenture", "software_engineering", "senior", "Manager", 27_677, 40_000))
    assert await provider.lookup(_ctx(company="accenture", band=LevelBand.SENIOR)) is None


@pytest.mark.asyncio
async def test_no_row_no_estimate():
    assert await _provider().lookup(_ctx()) is None


@pytest.mark.asyncio
async def test_the_pipeline_resolver_reads_the_stored_row_without_the_network(db_session, no_escape):
    """The resolver a run collects under (`reference_inputs(...).resolver()`)
    loads the rows once; resolving makes no outbound call
    (`no_escape` refuses one), the stored figure is the estimate, and the
    estimate names who published it and the fingerprint it ran under."""
    from tracker.plugins.reestimate import reference_inputs

    db_session.add(CompanyProfile(slug="google", display_name="Google"))
    await db_session.flush()
    db_session.add(CompanyCompLevel(
        company_slug="google", family="software_engineering", level_label="L6", band="staff",
        base_amount=280_000, tc_median=612_345, provider="manual",
        fetched_at=datetime(2026, 10, 1, tzinfo=UTC),
    ))
    await db_session.flush()

    inputs = await reference_inputs(db_session)
    resolver = inputs.resolver()
    primary, sources = await resolver.resolve(_ctx())
    assert primary is not None and primary.median == 612_345
    assert primary.provider == "manual" and primary.base_median == 280_000
    assert [s["provider"] for s in sources][0] == "reference_table"
    assert resolver.fingerprint == inputs.fingerprint


@pytest.mark.asyncio
async def test_a_stored_base_only_rung_is_read_and_answers_the_base(db_session, no_escape):
    """The read kept only rows with a total, so a rung stating a base alone
    never reached the estimate. A stored base-only rung is read; ours still
    answers the total from the seed after it."""
    from tracker.db.queries.reference_pay import pay_level_rows
    from tracker.plugins.reestimate import reference_inputs

    db_session.add(CompanyProfile(slug="google", display_name="Google"))
    await db_session.flush()
    db_session.add(CompanyCompLevel(
        company_slug="google", family="software_engineering", level_label="L6", band="staff",
        base_amount=280_000, tc_median=None, provider="manual", fetched_at=datetime(2026, 10, 1, tzinfo=UTC),
    ))
    await db_session.flush()

    assert [(r.level_label, r.base_amount, r.tc_median) for r in await pay_level_rows(db_session)] == [
        ("L6", 280_000, None)]
    primary, sources = await (await reference_inputs(db_session)).resolver().resolve(_ctx())
    assert sources[0]["provider"] == "reference_table" and sources[0]["median"] is None
    assert primary.median is not None, "the seed's total still leads"


def test_the_default_resolver_fetches_nothing():
    """With no rows handed in, the resolver is the static seed alone: no provider
    that opens a network client."""
    assert [p.name for p in CompResolver().providers] == ["static"]


@pytest.mark.asyncio
async def test_a_row_prices_only_a_posting_in_its_own_country():
    provider = _provider(_row("google", "software_engineering", "staff", "L6", 150_000, 260_000, country="GB"))
    assert await provider.lookup(_ctx(country="US")) is None
    estimate = await provider.lookup(_ctx(country="GB"))
    assert estimate is not None and estimate.median == 260_000


@pytest.mark.asyncio
async def test_the_same_rung_for_two_countries_prices_each_country_from_its_own_row():
    provider = _provider(
        _row("google", "software_engineering", "staff", "L6", 280_000, 600_000, country="US"),
        _row("google", "software_engineering", "staff", "L6", 150_000, 260_000, country="GB"),
    )
    assert (await provider.lookup(_ctx(country="US"))).median == 600_000
    assert (await provider.lookup(_ctx(country="GB"))).median == 260_000
    assert await provider.lookup(_ctx(country="DE")) is None


@pytest.mark.asyncio
async def test_a_posting_with_no_one_country_and_a_rung_with_no_country_are_never_priced():
    provider = _provider(_row("google", "software_engineering", "staff", "L6", 280_000, 600_000))
    assert await provider.lookup(_ctx(country=None)) is None
    unstated = _provider(_row("google", "software_engineering", "staff", "L6", 280_000, 600_000, country=None))
    assert await unstated.lookup(_ctx(country="US")) is None


@pytest.mark.asyncio
async def test_the_us_pay_floor_holds_us_rows_only():
    """A base under the US floor is a worldwide mix in a US row, and plain pay in another country's."""
    low = ("google", "software_engineering", "staff", "L6", 40_000, 70_000)
    assert await _provider(_row(*low, country="US")).lookup(_ctx(country="US")) is None
    assert (await _provider(_row(*low, country="IN")).lookup(_ctx(country="IN"))).median == 70_000



@pytest.mark.asyncio
async def test_a_rung_stating_a_base_alone_answers_the_base_and_leaves_the_total_unknown():
    """A plugin may answer base pay alone, and the row is stored; it must move
    the base estimate. Fail-first: no total, no row read, no estimate."""
    estimate = await _provider(_row("google", "software_engineering", "staff", "L6", 280_000, None)).lookup(_ctx())
    assert estimate is not None and estimate.component == "base"
    assert (estimate.median, estimate.low, estimate.high) == (None, None, None)
    assert estimate.base_median == 280_000


@pytest.mark.asyncio
async def test_components_are_never_added_up_into_a_total():
    """The negative control: a base and a grant with no total is a base."""
    row = _row("google", "software_engineering", "staff", "L6", 280_000, None)
    row.stock_amount = 200_000
    estimate = await _provider(row).lookup(_ctx())
    assert (estimate.median, estimate.base_median) == (None, 280_000)


@pytest.mark.asyncio
async def test_a_base_answer_does_not_hide_a_later_total_of_the_same_source():
    """Our chain is stored rows, then the seed's total, then the dataset's
    base. A stored base-only rung answers the base, and the seed still answers
    the total; a source with nothing else keeps its base."""
    from tracker.comp_providers.base import CompEstimate, CompProvider

    class Total(CompProvider):
        name = "seed"

        async def lookup(self, ctx):
            return CompEstimate(median=600_000, low=500_000, high=700_000, currency="USD", source="seed", detail={})

    base_only = _provider(_row("google", "software_engineering", "staff", "L6", 280_000, None))
    primary, sources = await CompResolver([base_only, Total()]).resolve(_ctx())
    assert primary.median == 600_000 and len(sources) == 2
    alone, _ = await CompResolver([base_only]).resolve(_ctx())
    assert (alone.median, alone.base_median) == (None, 280_000)
