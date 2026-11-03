"""Our dataset as a pay source, built in, dark.

Contracts: rows are keyed by OUR taxonomy family; a missing component is no
row, never zero (an unverified bonus policy has no bonus row, a no-bonus firm
has a 0 row); no equity is invented, so no total is ever claimed; traceability
metadata is absent; the build is cached by fingerprint; and while the built-in
pay switch is off nothing about the reference set or any estimate changes.
"""

from __future__ import annotations

from dataclasses import asdict

import pytest
from sqlalchemy import select

from tracker.comp_providers.base import BUILTIN, CompContext
from tracker.config import get_settings
from tracker.db.models import Job
from tracker.enrich import builtin_pay
from tracker.enrich.builtin_pay import BuiltinPayProvider, build_rows, cached_rows, index_rows
from tracker.enrich.estimated_pay import EstimatedPay
from tracker.enrich.level_pay import FiledBase, LevelBase, PostedBase
from tracker.plugins.reestimate import reestimate, reference_inputs
from tracker.schema import LevelBand
from tracker.taxonomy.roles import ROLE_GROUPS

SWE = "software_engineering"


def _bases() -> dict:
    """Three companies, one per kind of evidence. google states a bonus target
    per rung; netflix pays no annual bonus; a company with no policy has none."""
    return {
        ("google", SWE, LevelBand.STAFF): LevelBase(
            "google", SWE, LevelBand.STAFF, filed=FiledBase(year=2025, filings=40, titles=3, base=260_000), posted=None),
        ("netflix", SWE, LevelBand.SENIOR): LevelBase(
            "netflix", SWE, LevelBand.SENIOR, filed=None,
            posted=PostedBase(year=2026, ranges=2, base_min=300_000, base_max=500_000, postings=9)),
        ("acme-robotics", SWE, LevelBand.SENIOR): LevelBase(
            "acme-robotics", SWE, LevelBand.SENIOR, filed=None, posted=None,
            estimated=EstimatedPay(rung="L5", base=190_000, equity=None, cash_bonus=None)),
    }


@pytest.fixture
def synthetic(monkeypatch):
    monkeypatch.setattr(builtin_pay, "level_bases", _bases)
    ratios = {"google": 0.15, "netflix": 0.0}
    monkeypatch.setattr(builtin_pay, "bonus_ratio_for", lambda company, band: ratios.get(company))


def _by(rows):
    return {(r.company, r.component): r for r in rows}


def test_all_base_inputs_keep_their_values_without_traceability_fields(synthetic):
    rows = _by(build_rows())
    assert rows["google", "base"].value == 260_000
    assert rows["netflix", "base"].value == 400_000
    assert rows["acme-robotics", "base"].value == 190_000
    for row in rows.values():
        assert set(asdict(row)) == {"company", "family", "band", "component", "value", "country"}


def test_a_missing_component_is_no_row_and_a_stated_zero_is_a_zero(synthetic):
    rows = _by(build_rows())
    assert rows["google", "bonus"].value == 39_000
    assert rows["netflix", "bonus"].value == 0  # a company that pays no annual bonus
    assert ("acme-robotics", "bonus") not in rows  # an unverified policy says nothing
    assert not any(r.component == "equity" for r in build_rows())  # never invented


@pytest.mark.asyncio
async def test_the_provider_answers_the_base_and_never_a_total_it_cannot_measure(synthetic):
    provider = BuiltinPayProvider(index_rows(build_rows()))
    est = await provider.lookup(CompContext(company="google", band=LevelBand.STAFF, family=SWE,
                                            location_group=None, country="US", title="Staff Software Engineer"))
    assert est is not None
    assert est.median is None and est.component == "base"
    assert est.base_median == 260_000 and est.provider == BUILTIN
    assert est.source == "RoleBand estimated base"
    assert est.detail == {"provider": "builtin_pay", "components": ["base", "bonus"]}
    # A family the dataset has no row for is no answer, never a borrowed one.
    assert await provider.lookup(CompContext(company="google", band=LevelBand.STAFF, family="product_management",
                                             location_group=None, country="US", title="Staff PM")) is None
    # Our dataset is US pay: a posting in another country, or in several, reads none of it.
    for country in ("GB", None):
        assert await provider.lookup(CompContext(company="google", band=LevelBand.STAFF, family=SWE,
                                                 location_group=None, country=country, title="Staff SWE")) is None


def test_the_build_is_cached_by_fingerprint(synthetic, tmp_path, monkeypatch):
    monkeypatch.setenv("ROLEBAND_CACHE_DIR", str(tmp_path))
    get_settings.cache_clear()
    monkeypatch.setattr(builtin_pay, "build_fingerprint", lambda: "fp-one")
    try:
        first = cached_rows()
        assert (tmp_path / "builtin-pay-fp-one.json").is_file()
        monkeypatch.setattr(builtin_pay, "build_rows", lambda: (_ for _ in ()).throw(AssertionError("rebuilt")))
        assert cached_rows() == first  # read back, not rebuilt
        monkeypatch.setattr(builtin_pay, "build_fingerprint", lambda: "fp-two")
        with pytest.raises(AssertionError, match="rebuilt"):
            cached_rows()  # a new fingerprint is a new build
    finally:
        get_settings.cache_clear()


def test_every_real_row_is_keyed_by_our_taxonomy_never_a_ladder_slug():
    # A source's ladder slug is hyphenated ("software-engineer"); our taxonomy
    # is a role group slug.
    groups = {g.slug for g in ROLE_GROUPS}
    rows = build_rows()
    assert rows, "the atlas prices something"
    assert {r.family for r in rows} <= groups, sorted({r.family for r in rows} - groups)
    assert not any("-" in r.family for r in rows)
    assert {r.component for r in rows} <= {"base", "bonus"}


# --------------------------------------------------------------------------- #
# The switch
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_while_the_switch_is_off_nothing_changes(db_session, synthetic, monkeypatch):
    """The built-in pay switch turned off, then on."""
    monkeypatch.setenv("ROLEBAND_BUILTIN_PAY", "false")
    get_settings.cache_clear()
    db_session.add(Job(company="acme-robotics", req_id="1", dedupe_key="acme-robotics:1",
                       title="Senior Software Engineer", url="https://example.com/1", level_band="senior",
                       family=SWE, location_groups=["silicon_valley"]))
    await db_session.commit()
    off = await reference_inputs(db_session)
    assert off.ours.builtin_pay is None and "builtin_pay" not in off.providers
    await reestimate(db_session)
    job = (await db_session.execute(select(Job))).scalar_one()
    assert job.comp_median is None and job.comp_base_median is None  # nothing prices it yet

    monkeypatch.setenv("ROLEBAND_BUILTIN_PAY", "true")
    get_settings.cache_clear()
    monkeypatch.setattr(builtin_pay, "cached_rows", lambda: build_rows())
    from tracker.plugins import reestimate as reestimate_module

    monkeypatch.setattr(reestimate_module, "cached_rows", lambda: build_rows())
    try:
        on = await reference_inputs(db_session)
        assert on.fingerprint != off.fingerprint  # the switch is one reference change
        result = await reestimate(db_session)
        assert result.applied and result.report["gained"] == 1  # a base estimate where none was
        await db_session.refresh(job)
        assert (job.comp_median, job.comp_base_median, job.comp_component, job.comp_provider) == (
            None, 190_000, "base", BUILTIN)
    finally:
        get_settings.cache_clear()
