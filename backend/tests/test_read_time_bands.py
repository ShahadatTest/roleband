"""A plugin's rung is banded from our atlas when it is READ, never in its row.

Our atlas is the source of truth for which level a rung is. Our data and a
plugin's must not change each other's stored data: a plugin's row keeps what the plugin sent (label, aliases, source
level) and every reader places it at read time, so an atlas change moves the
next read and never rewrites the row. A row of ours keeps the band it was
entered with. The labels are real rows: Accenture's "Manager" reads mid until
Accenture's ladder is in the atlas.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from sqlalchemy import select

from tests.plugin_seed import cover
from tracker.db.models import (
    CompanyCompLevel,
    CompanyProfile,
    ExternalCompObservation,
    PluginInstall,
)
from tracker.db.queries.reference_pay import package_rows, reported_rows
from tracker.levels import words
from tracker.levels.words import ATLAS, WORDS, atlas_band, resolve_band, rung_band
from tracker.plugins.registry import PAY_LEVELS, PAY_OBSERVATIONS, reader_providers
from tracker.schema import LevelBand

PLUGIN = "acme-pay"
AT = datetime(2026, 10, 1, tzinfo=UTC)


def test_our_dataset_places_a_rung_by_its_ladder_code_or_printed_code_never_by_words():
    assert atlas_band("google", "L6") is LevelBand.STAFF  # the ladder's own spelling
    assert atlas_band("accenture", "Manager") is LevelBand.SENIOR
    assert atlas_band("dropbox", "IC4") is LevelBand.SENIOR  # a code Dropbox prints
    # Labels the atlas does not know: no reading of ours, whatever the words say.
    assert atlas_band("accenture", "Associate TPM") is None
    assert atlas_band("meta", "E5") is None
    assert atlas_band("acme", "Senior Software Engineer") is None
    # The words still band them, for the rungs the atlas cannot place.
    assert resolve_band("accenture", "Associate TPM") is LevelBand.ENTRY
    assert resolve_band("acme", "Senior Software Engineer") is LevelBand.SENIOR


def test_our_dataset_answers_before_a_plugin_s_aliases():
    """A label the atlas places is never re-read through an alias the plugin sent."""
    assert rung_band("accenture", "Manager", ["Team Leader"]) == ("senior", ATLAS)
    assert rung_band("accenture", "Associate TPM") == ("entry", WORDS)


async def _plugin(db, companies: tuple[str, ...]) -> None:
    for slug in companies:
        db.add(CompanyProfile(slug=slug, display_name=slug.title()))
    db.add(PluginInstall(
        plugin_id=PLUGIN, name="Acme pay", version="1.0.0", source_dir="/x", manifest_sha="m", code_sha="c",
        fingerprint="fp", approved_fingerprint="fp", enabled=True,
        manifest={"plugin": {"id": PLUGIN}, "provides": [{"slot": PAY_LEVELS}, {"slot": PAY_OBSERVATIONS}]},
    ))
    await db.flush()
    cover(db, PLUGIN, (PAY_LEVELS, PAY_OBSERVATIONS), companies)


def _rung(company: str, label: str, *, aliases=(), provider: str = PLUGIN, band: str | None = None,
          base: int = 200_000) -> CompanyCompLevel:
    return CompanyCompLevel(company_slug=company, family="software_engineering", level_label=label, band=band,
                            aliases=list(aliases), base_amount=base, tc_median=base, provider=provider,
                            country="US", fetched_at=AT)


async def _stored(db) -> dict[tuple[str, str], tuple]:
    rows = (await db.scalars(select(CompanyCompLevel))).all()
    return {(r.company_slug, r.level_label): (r.band, r.band_source, list(r.aliases)) for r in rows}


@pytest.mark.asyncio
async def test_a_plugin_s_rung_is_banded_when_read_and_its_row_keeps_what_the_plugin_sent(db_session):
    await _plugin(db_session, ("accenture", "google"))
    db_session.add_all([
        _rung("accenture", "Manager"),  # the atlas places it: senior
        _rung("accenture", "Associate TPM"),  # the atlas cannot: its words, entry
        # The atlas cannot place the label, but the plugin's alias is a rung it
        # knows: senior, where the label's own words would read mid.
        _rung("google", "Software Engineer", aliases=["L5"]),
    ])
    await db_session.commit()
    before = await _stored(db_session)
    providers = await reader_providers(db_session)

    read = {(r.company_slug, r.level_label): (r.band, r.band_source)
            for company in ("accenture", "google") for r in await package_rows(db_session, providers, company, "US")}
    assert read == {
        ("accenture", "Manager"): ("senior", ATLAS),
        ("accenture", "Associate TPM"): ("entry", WORDS),
        ("google", "Software Engineer"): ("senior", WORDS),
    }
    assert await _stored(db_session) == before, "reading never writes the band into the plugin's row"
    assert {band for band, _, _ in before.values()} == {None}


@pytest.mark.asyncio
async def test_an_atlas_change_moves_the_next_read_and_never_the_row(db_session, monkeypatch):
    await _plugin(db_session, ("accenture",))
    db_session.add(_rung("accenture", "Manager"))
    await db_session.commit()
    before = await _stored(db_session)
    providers = await reader_providers(db_session)
    assert [r.band for r in await package_rows(db_session, providers, "accenture", "US")] == ["senior"]

    # A new atlas edition re-levels Accenture's Manager.
    real = words.atlas_band
    monkeypatch.setattr(words, "atlas_band",
                        lambda company, label: LevelBand.STAFF if (company, label) == ("accenture", "Manager")
                        else real(company, label))
    assert [r.band for r in await package_rows(db_session, providers, "accenture", "US")] == ["staff"]
    assert await _stored(db_session) == before


@pytest.mark.asyncio
async def test_a_row_of_ours_keeps_the_band_it_was_entered_with(db_session):
    db_session.add(CompanyProfile(slug="google", display_name="Google"))
    await db_session.flush()
    db_session.add(_rung("google", "L5", provider="manual", band="principal"))  # by hand, against the atlas
    await db_session.commit()
    rows = await package_rows(db_session, await reader_providers(db_session), "google", "US")
    assert [(r.level_label, r.band) for r in rows] == [("L5", "principal")]


@pytest.mark.asyncio
async def test_a_reported_point_is_banded_when_read_by_the_atlas_then_its_words(db_session):
    await _plugin(db_session, ("google",))

    def obs(level: str, key: str) -> ExternalCompObservation:
        return ExternalCompObservation(company_slug="google", provider=PLUGIN, dedup_key=key,
                                       source_level=level, band=None, total_amount=400_000, base_amount=200_000,
                                       equity_amount=150_000, bonus_amount=50_000, currency="USD", country="US",
                                       snapshot_date=date(2026, 10, 9))

    db_session.add_all([obs("L6", "a"), obs("Senior Wizard", "b")])
    await db_session.commit()
    rows, _ = await reported_rows(db_session, await reader_providers(db_session))
    assert sorted((r.company_slug, r.band) for r in rows) == [("google", "senior"), ("google", "staff")]
    stored = (await db_session.scalars(select(ExternalCompObservation.band))).all()
    assert stored == [None, None], "the stored points keep no band of ours"


def _submission(key: str, **over) -> dict:
    from roleband_plugin_sdk.slots import PayObservation

    sent = {"source_level": "L6", "total": 400_000, "base": 200_000, "equity": 150_000, "bonus": None,
            "currency": "USD", "country": "US", "snapshot_date": date(2026, 10, 9), "dedup_key": key, **over}
    return PayObservation(**sent).model_dump(mode="json")


@pytest.mark.asyncio
async def test_a_partial_submission_keeps_its_unknowns_and_only_us_pay_enters_the_us_comparison(db_session):
    """An unstated bonus is stored as unknown and the point is read; a point
    with no equity, one paid in another market, and one with no market are
    kept and never compared with US pay."""
    from tracker.plugins.writer import write_batch

    await _plugin(db_session, ("google",))
    await db_session.commit()
    await write_batch(db_session, PLUGIN, PAY_OBSERVATIONS, "google", [
        _submission("partial"),
        _submission("no-equity", equity=None),
        _submission("london", currency="GBP", country="GB", total=200_000, base=120_000, equity=60_000),
        _submission("nowhere", country=None),
    ])
    await db_session.commit()
    stored = {o.dedup_key: o for o in (await db_session.scalars(select(ExternalCompObservation))).all()}
    assert (stored["partial"].bonus_amount, stored["no-equity"].equity_amount) == (None, None)
    assert (stored["london"].currency, stored["london"].country, stored["nowhere"].country) == ("GBP", "GB", None)

    rows, _ = await reported_rows(db_session, await reader_providers(db_session))
    assert [(r.total_usd, r.equity_usd) for r in rows] == [(400_000, 150_000)]
