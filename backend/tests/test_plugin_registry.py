"""One source answers each kind of data, app-wide, never mixed.

Per slot either OUR data answers (the core's own sources) or ONE plugin does: the
first runnable plugin declaring the slot, selected from the moment it is on.
While it is selected only its rows are read, and only for the companies it has
read whole; a company it has not read is "not covered", never answered from
ours. Rows under a name no plugin publishes are read by nothing.

The planted plugin rows carry absurd figures (999,000 base), so a reader that
lets the wrong source through shows it in the number, not only in a count.
"""

from __future__ import annotations

import os
import subprocess
import sys
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from tests.plugin_seed import cover, covers
from tracker.db.models import (
    CompanyBenefit,
    CompanyCompLevel,
    CompanyFact,
    CompanyProfile,
    PluginInstall,
)
from tracker.db.queries.reference_pay import package_rows, pay_level_rows, reported_rows, split_rows
from tracker.plugins.registry import (
    COMPANY_BENEFITS,
    COMPANY_FACTS,
    PAY_LEVELS,
    PAY_OBSERVATIONS,
    REFERENCE_SOURCES_KEY,
    InstallRecord,
    Providers,
    load_providers,
    providers_from,
    reader_providers,
)
from tracker.profiles.benefits_builtin import builtin_cells
from tracker.profiles.store import candidates_for, resolve_and_materialize
from tracker.settings_store import set_setting_dict
from tracker.taxonomy.comp_families import REFERENCE_FAMILY

#: Names no plugin publishes, and plugins whose manifests still name them in
#: `legacy_sources`.
LEGACY, PLUGIN = "acme.legacy", "acme-pay"
LEGACY_OBS, PLUGIN_OBS = "acme.reports", "acme-reports"

BACKEND = Path(__file__).resolve().parents[1]
AT = datetime(2026, 10, 1, tzinfo=UTC)
PROVIDES = [{"slot": PAY_LEVELS}, {"slot": COMPANY_FACTS, "fields": ["hq_city"], "rank": 80},
            {"slot": COMPANY_BENEFITS}]
SLOTS = (PAY_LEVELS, COMPANY_FACTS, COMPANY_BENEFITS, PAY_OBSERVATIONS)


def _record(pid="tpl", *, enabled=True, approved="fp1", fingerprint="fp1", removed=None, provides=PROVIDES,
            attribution=None):
    plugin = {"id": pid, "name": pid}
    if attribution:
        plugin["attribution"] = attribution
    return InstallRecord(pid, enabled, fingerprint, approved, removed, {"plugin": plugin, "provides": provides})


def _adopter(enabled=True, approved="fp1"):
    """A plugin whose manifest still names a legacy source and its families."""
    plugin = {"id": PLUGIN, "name": "Acme pay data", "attribution": "Data source: Acme",
              "legacy_sources": [LEGACY], "legacy_families": {"software-engineer": REFERENCE_FAMILY}}
    manifest = {"plugin": plugin,
                "provides": [{"slot": PAY_LEVELS}, {"slot": COMPANY_FACTS, "rank": 50}, {"slot": COMPANY_BENEFITS}]}
    return InstallRecord(PLUGIN, enabled, "fp1", approved, None, manifest)


def _sql(p: Providers, slot: str = PAY_LEVELS) -> str:
    return str(p.where(slot, CompanyCompLevel.provider, CompanyCompLevel.company_slug)
               .compile(compile_kwargs={"literal_binds": True}))


# --------------------------------------------------------------------------- #
# The rule, pure
# --------------------------------------------------------------------------- #


def test_with_no_plugin_selected_only_our_own_sources_are_read():
    """With no plugin on, RoleBand reads only its
    own data. The core names its own sources, never another's."""
    p = Providers()
    for slot in SLOTS:
        assert p.source_for(slot) is None
    assert p.visible(PAY_LEVELS, "manual") and p.visible(COMPANY_FACTS, "blueprint")
    assert p.visible(COMPANY_FACTS, "sec_edgar")
    assert not p.visible(PAY_OBSERVATIONS, LEGACY_OBS) and not p.visible(PAY_LEVELS, LEGACY)
    assert not p.visible(COMPANY_FACTS, LEGACY) and not p.visible(PAY_LEVELS, "anything.else")
    assert "IN (" in _sql(p) and "'manual'" in _sql(p) and LEGACY not in _sql(p)


def test_legacy_rows_are_read_by_nothing_even_while_a_manifest_names_them():
    """Rows under a name no plugin publishes belong to no
    source. A manifest's `legacy_sources` and `legacy_families` adopt nothing,
    on or off, before or after the plugin reads anything."""
    for p in (providers_from([_adopter()], {}),
              providers_from([_adopter()], covers(PLUGIN, PAY_LEVELS, COMPANY_FACTS, COMPANY_BENEFITS)),
              providers_from([_adopter(enabled=False)], {})):
        for slot in SLOTS:
            assert not p.visible(slot, LEGACY) and not p.visible(slot, LEGACY, "acme")
        assert LEGACY not in _sql(p) and LEGACY not in p.fact_ranks and LEGACY not in p.fact_labels
    obs = InstallRecord(PLUGIN_OBS, True, "f", "f", None,
                        {"plugin": {"id": PLUGIN_OBS, "legacy_sources": [LEGACY_OBS]},
                         "provides": [{"slot": PAY_OBSERVATIONS}]})
    assert not providers_from([obs], {}).visible(PAY_OBSERVATIONS, LEGACY_OBS)


def test_a_plugin_is_selected_the_moment_it_is_on_and_ours_stops_answering_at_once():
    """Before it has read anything it answers no company, and ours answers none
    either: every company is "not covered" until the plugin reads it."""
    p = providers_from([_record()], {})
    assert p.source_for(PAY_LEVELS) == "tpl" and p.source_for(PAY_OBSERVATIONS) is None
    assert not p.visible(PAY_LEVELS, "tpl") and not p.visible(PAY_LEVELS, "tpl", "acme")
    assert not p.visible(PAY_LEVELS, "manual") and not p.visible(COMPANY_FACTS, "blueprint")
    assert not p.covers(PAY_LEVELS, "acme")
    assert _sql(p) == "false", "nothing is read in a selected slot until the plugin reads a company"


@pytest.mark.parametrize(
    ("case", "record", "selected"),
    [
        ("enabled and approved", _record(), True),
        ("not enabled", _record(enabled=False), False),
        ("never approved", _record(approved=None), False),
        ("changed since approval", _record(fingerprint="fp2"), False),
        ("removed", _record(removed=AT), False),
    ],
    ids=lambda v: v if isinstance(v, str) else "",
)
def test_a_runnable_plugin_is_selected_and_any_other_leaves_the_slot_ours(case, record, selected):
    p = providers_from([record], covers("tpl", PAY_LEVELS))
    assert (p.source_for(PAY_LEVELS) == "tpl") is selected
    assert p.visible(PAY_LEVELS, "tpl", "acme") is selected
    assert p.visible(PAY_LEVELS, "manual", "acme") is not selected, "exactly one of the two answers"


def test_coverage_cannot_select_a_plugin_for_a_slot_its_manifest_does_not_provide():
    p = providers_from([_record(provides=[{"slot": PAY_LEVELS}])], covers("tpl", PAY_LEVELS, COMPANY_FACTS))
    assert p.source_for(PAY_LEVELS) == "tpl" and p.source_for(COMPANY_FACTS) is None
    assert not p.visible(COMPANY_FACTS, "tpl", "acme") and p.visible(COMPANY_FACTS, "blueprint", "acme")


def test_of_two_plugins_on_one_slot_only_the_first_in_order_answers():
    both = {**covers("aaa", PAY_LEVELS), **covers("zzz", PAY_LEVELS)}
    p = providers_from([_record("aaa"), _record("zzz")], both, {PAY_LEVELS: ["zzz"]})
    assert p.active[PAY_LEVELS] == ("zzz",)
    assert p.visible(PAY_LEVELS, "zzz", "acme") and not p.visible(PAY_LEVELS, "aaa", "acme")
    assert providers_from([_record("aaa"), _record("zzz")], both).active[PAY_LEVELS] == ("aaa",), "then by id"


def test_while_a_plugin_is_selected_no_row_of_ours_is_read_for_any_company():
    """No fall-through per key: a company the plugin has read
    answers from it alone, one it has not answers from nothing."""
    p = providers_from([_record()], covers("tpl", PAY_LEVELS, companies=("google",)))
    rows = [("google", "tpl", 1), ("google", "manual", 2), ("apple", "manual", 3), ("apple", "tpl", 4)]
    kept = p.admit(PAY_LEVELS, rows, provider=lambda r: r[1], company=lambda r: r[0])
    assert kept == [("google", "tpl", 1)]
    assert p.covers(PAY_LEVELS, "google") and not p.covers(PAY_LEVELS, "apple")


def test_a_plugin_fact_rank_is_capped_by_the_core():
    p = providers_from([_record()], covers("tpl", COMPANY_FACTS))
    assert p.fact_ranks == {"tpl": 50}


@pytest.mark.parametrize(
    "p",
    [
        Providers(),
        providers_from([_record()], {}),
        providers_from([_record()], covers("tpl", PAY_LEVELS, companies=("acme",))),
        providers_from([_record("aaa"), _record("zzz", enabled=False)], covers("zzz", PAY_LEVELS)),
    ],
    ids=["ours", "selected, nothing read", "selected, acme read", "a disabled plugin's coverage"],
)
def test_the_sql_filter_admits_exactly_what_visible_admits(p):
    """A reader that filters in SQL (`where`) and one that filters in Python
    (`visible`) read the same rows."""
    sql = _sql(p)
    for provider in ("tpl", "aaa", "zzz", "manual", "blueprint", LEGACY):
        for company in ("acme", "globex"):
            admitted = p.visible(PAY_LEVELS, provider, company)
            in_sql = sql != "false" and f"'{provider}'" in sql and (
                "company_slug" not in sql or f"'{company}'" in sql)
            assert admitted is in_sql, (provider, company, sql)


def test_a_plugin_answers_company_by_company_as_each_is_read_whole():
    """Without a fall-through: a company it has read whole answers
    from its rows, one it has not answers from nothing."""
    p = providers_from([_record()], covers("tpl", PAY_LEVELS, companies=("acme",)))
    assert p.visible(PAY_LEVELS, "tpl", "acme") and not p.visible(PAY_LEVELS, "tpl", "globex")
    assert not p.visible(PAY_LEVELS, "manual", "globex")
    assert "'acme'" in _sql(p) and "'globex'" not in _sql(p) and "'manual'" not in _sql(p)


def test_selecting_a_plugin_moves_the_reference_record_before_it_reads_anything():
    """The stored estimates must move off ours the moment a plugin is selected,
    so the record (and with it the reference fingerprint) names it at once."""
    assert Providers().record()["active"] == {}
    # Every slot it declares: one flip applies them all.
    assert providers_from([_record()], {}).record()["active"] == {
        PAY_LEVELS: ["tpl"], COMPANY_FACTS: ["tpl"], COMPANY_BENEFITS: ["tpl"]}


def test_the_applied_set_still_reads_a_disabled_plugin_until_the_re_estimate_drops_it():
    """Between a disable and the re-estimate that drops the plugin, readers take
    EVERY slot from the APPLIED set, credited and named as it was: the
    whole app changes source at the flip, not one slot before the others."""
    record = _record(attribution="Data source: Acme")
    applied = providers_from([record], covers("tpl", PAY_LEVELS, COMPANY_FACTS)).record()
    off = _record(enabled=False, attribution="Data source: Acme")
    mid = providers_from([off], covers("tpl", PAY_LEVELS, COMPANY_FACTS)).with_applied(applied)
    assert mid.visible(PAY_LEVELS, "tpl", "acme") and not mid.visible(PAY_LEVELS, "manual", "acme")
    assert mid.attribution([PAY_LEVELS]) == "Data source: Acme"
    assert mid.visible(COMPANY_FACTS, "tpl", "acme") and not mid.visible(COMPANY_FACTS, "blueprint", "acme")
    assert mid.attribution([COMPANY_FACTS]) == "Data source: Acme"
    # The flip that drops it: ours answers every slot again.
    after = providers_from([off], covers("tpl", PAY_LEVELS, COMPANY_FACTS)).with_applied(
        providers_from([off], {}).record())
    assert all(after.source_for(slot) is None for slot in (PAY_LEVELS, COMPANY_FACTS, COMPANY_BENEFITS))


def test_the_applied_set_reads_only_the_companies_read_whole_when_it_was_applied():
    """The stored estimates were computed when only acme was read whole; globex,
    read since, answers only once the re-estimate moves them (a list and a
    detail never disagree), in every slot alike: facts had read
    nothing when the set was applied, so they answer nothing yet."""
    later = AT + timedelta(hours=1)
    applied = providers_from([_record()], covers("tpl", PAY_LEVELS, companies=("acme",))).record()
    now = {"tpl": {PAY_LEVELS: {"acme": AT, "globex": later}, COMPANY_FACTS: {"acme": AT, "globex": later}}}
    mid = providers_from([_record()], now).with_applied(applied)
    assert mid.visible(PAY_LEVELS, "tpl", "acme") and not mid.visible(PAY_LEVELS, "tpl", "globex")
    assert not mid.visible(COMPANY_FACTS, "tpl", "globex") and not mid.visible(COMPANY_FACTS, "tpl", "acme")


def test_an_applied_record_written_while_plugins_adopted_rows_adopts_nothing():
    """An older `reference_state` still names adopted sources;
    reading it neither adopts them nor loses the plugin it names."""
    old = {"plugins": [PLUGIN], "active": {PAY_LEVELS: [PLUGIN]}, "adopted": {PAY_LEVELS: {LEGACY: PLUGIN}},
           "families": {LEGACY: {"software-engineer": REFERENCE_FAMILY}}}
    mid = providers_from([_adopter()], covers(PLUGIN, PAY_LEVELS)).with_applied(old)
    assert mid.source_for(PAY_LEVELS) == PLUGIN and not mid.visible(PAY_LEVELS, LEGACY, "acme")
    assert mid.attribution([PAY_LEVELS]) == "Data source: Acme"


# --------------------------------------------------------------------------- #
# Readers, against the database
# --------------------------------------------------------------------------- #


async def _seed(db, *, active: bool, approved: bool = True, enabled: bool = True) -> None:
    db.add_all([CompanyProfile(slug="acme", display_name="Acme"), CompanyProfile(slug="globex", display_name="Globex")])
    db.add(PluginInstall(
        plugin_id="tpl", name="Template", version="0.1.0", source_dir="/x", manifest_sha="m", code_sha="c",
        manifest={"provides": PROVIDES}, fingerprint="fp1",
        approved_fingerprint="fp1" if approved else None, enabled=enabled,
    ))
    await db.flush()
    if active:
        cover(db, "tpl", (PAY_LEVELS, COMPANY_FACTS, COMPANY_BENEFITS), ("acme",))
    core = dict(family=REFERENCE_FAMILY, band="senior", provider="manual", fetched_at=AT)
    db.add_all([
        CompanyCompLevel(company_slug="acme", level_label="L5", tc_median=300_000, base_amount=200_000, **core),
        CompanyCompLevel(company_slug="globex", level_label="G5", tc_median=250_000, base_amount=180_000, **core),
        CompanyCompLevel(company_slug="acme", family=REFERENCE_FAMILY, level_label="E5", band="senior",
                         tc_median=999_000, base_amount=999_000, provider="tpl", country="US", fetched_at=AT),
        CompanyCompLevel(company_slug="globex", family=REFERENCE_FAMILY, level_label="X5", band="senior",
                         tc_median=777_000, base_amount=777_000, provider=LEGACY, country="US", fetched_at=AT),
        CompanyBenefit(company_slug="acme", name="Free yacht", category="Perks", value_usd=999_000,
                       provider="tpl"),
    ])
    await db.commit()


def _tc(rows) -> dict[str, list[int]]:
    out: dict[str, list[int]] = {}
    for r in rows:
        out.setdefault(r.company_slug, []).append(r.tc_median)
    return out


@pytest.mark.asyncio
async def test_every_pay_surface_answers_a_company_from_the_one_source(db_session):
    """Here the selected plugin's acme rung states a base but no total, and our
    ladder states everything: the estimate (reads the base and leaves the
    total unknown), the job package (needs a base) and the measured splits
    (need every share) all read the plugin alone, so none of them fills the gap
    from ours."""
    db_session.add(CompanyProfile(slug="acme", display_name="Acme"))
    db_session.add(PluginInstall(
        plugin_id="tpl", name="Template", version="0.1.0", source_dir="/x", manifest_sha="m", code_sha="c",
        manifest={"provides": PROVIDES}, fingerprint="fp1", approved_fingerprint="fp1", enabled=True,
    ))
    await db_session.flush()
    cover(db_session, "tpl", (PAY_LEVELS,), ("acme",))
    db_session.add_all([
        CompanyCompLevel(company_slug="acme", family=REFERENCE_FAMILY, level_label="L5", band="senior",
                         tc_median=300_000, base_amount=200_000, stock_amount=70_000, bonus_amount=30_000,
                         base_pct=0.667, stock_pct=0.233, bonus_pct=0.1, provider="manual",
                         fetched_at=AT),
        CompanyCompLevel(company_slug="acme", family=REFERENCE_FAMILY, level_label="E5", band="senior",
                         tc_median=None, base_amount=999_000, provider="tpl", country="US", fetched_at=AT),
    ])
    await db_session.commit()
    providers = await reader_providers(db_session)
    assert [(r.provider, r.base_amount, r.tc_median) for r in await pay_level_rows(db_session, providers)] == [
        ("tpl", 999_000, None)], "the plugin answers acme and states no total"
    assert [(r.provider, r.base_amount) for r in await package_rows(db_session, providers, "acme", "US")] == [("tpl", 999_000)]
    assert await split_rows(db_session, providers, "US") == [], "the plugin answers acme and states no split"


@pytest.mark.asyncio
async def test_estimated_pay_reads_the_selected_plugin_s_own_rows_and_never_the_legacy_ones(db_session):
    from datetime import date

    from tracker.db.models import ExternalCompObservation

    # Companies our atlas has ladders for: a reported level is banded when read.
    db_session.add_all([CompanyProfile(slug="google", display_name="Google"),
                        CompanyProfile(slug="apple", display_name="Apple")])
    manifest = {"plugin": {"id": PLUGIN_OBS, "name": "Reports", "legacy_sources": [LEGACY_OBS]},
                "provides": [{"slot": PAY_OBSERVATIONS}]}
    db_session.add(PluginInstall(plugin_id=PLUGIN_OBS, name="Reports", version="1.0.0", source_dir="/x",
                                 manifest_sha="m", code_sha="c", manifest=manifest, fingerprint="f",
                                 approved_fingerprint="f", enabled=True))
    await db_session.flush()
    cover(db_session, PLUGIN_OBS, (PAY_OBSERVATIONS,), ("google",))

    def obs(company, provider, key, day, level="L5"):
        return ExternalCompObservation(company_slug=company, provider=provider, dedup_key=key,
                                       source_level=level, band=None, total_amount=400_000, base_amount=200_000,
                                       equity_amount=150_000, bonus_amount=50_000, currency="USD", country="US",
                                       snapshot_date=date(2026, 10, day))

    db_session.add_all([obs("google", LEGACY_OBS, "a1", 1), obs("google", LEGACY_OBS, "a2", 1),
                        obs("google", PLUGIN_OBS, "a1", 9), obs("google", PLUGIN_OBS, "a2", 9),
                        obs("apple", LEGACY_OBS, "g1", 12, level="ICT4")])
    await db_session.commit()
    rows, latest = await reported_rows(db_session, await reader_providers(db_session))
    assert sorted((r.company_slug, r.provider, r.band) for r in rows) == [
        ("google", PLUGIN_OBS, "senior"), ("google", PLUGIN_OBS, "senior")]
    assert latest == date(2026, 10, 9), "the legacy row's later snapshot is not read either"


@pytest.mark.asyncio
async def test_a_company_refreshed_on_an_older_day_is_still_read(db_session):
    """A plugin may refresh company by company. Taking the newest snapshot per
    PROVIDER hides every company it did not publish on its newest day, with no
    row retired and nothing said: the company simply stops having reported pay
    the moment another company is refreshed. Fail-first: only google comes back.
    """
    from datetime import date

    from tracker.db.models import ExternalCompObservation

    db_session.add_all([CompanyProfile(slug="google", display_name="Google"),
                        CompanyProfile(slug="apple", display_name="Apple")])
    manifest = {"plugin": {"id": PLUGIN_OBS, "name": "Reports"},
                "provides": [{"slot": PAY_OBSERVATIONS}]}
    db_session.add(PluginInstall(plugin_id=PLUGIN_OBS, name="Reports", version="1.0.0", source_dir="/x",
                                 manifest_sha="m", code_sha="c", manifest=manifest, fingerprint="f",
                                 approved_fingerprint="f", enabled=True))
    await db_session.flush()
    cover(db_session, PLUGIN_OBS, (PAY_OBSERVATIONS,), ("google", "apple"))

    def obs(company, key, day, level="L5"):
        return ExternalCompObservation(company_slug=company, provider=PLUGIN_OBS, dedup_key=key,
                                       source_level=level, band=None, total_amount=400_000, base_amount=200_000,
                                       equity_amount=150_000, bonus_amount=50_000, currency="USD", country="US",
                                       snapshot_date=date(2026, 10, day))

    db_session.add_all([
        # Apple last refreshed on the 3rd, google on the 9th. Both of apple's
        # rungs must survive google's newer day.
        obs("apple", "p1", 3, level="ICT4"), obs("apple", "p2", 3, level="ICT4"),
        obs("google", "g1", 9), obs("google", "g2", 9),
        # Google's own older day is still superseded: latest per company, not all of them.
        obs("google", "g0", 1),
    ])
    await db_session.commit()

    rows, latest = await reported_rows(db_session, await reader_providers(db_session))
    assert sorted(Counter((r.company_slug, r.snapshot_date) for r in rows).items()) == [
        (("apple", date(2026, 10, 3)), 2),
        (("google", date(2026, 10, 9)), 2),
    ]
    assert latest == date(2026, 10, 9), "the newest snapshot read, across companies"


@pytest.mark.asyncio
async def test_an_unapproved_plugin_leaves_every_company_ours(db_session):
    await _seed(db_session, active=True, approved=False)
    assert _tc(await pay_level_rows(db_session)) == {"acme": [300_000], "globex": [250_000]}


@pytest.mark.asyncio
async def test_a_plugin_that_has_read_nothing_answers_nothing_and_ours_is_not_read(db_session):
    await _seed(db_session, active=False)
    assert _tc(await pay_level_rows(db_session)) == {}


@pytest.mark.asyncio
async def test_a_selected_plugin_answers_only_its_companies_and_off_brings_ours_back_unchanged(db_session):
    await _seed(db_session, active=True)
    assert _tc(await pay_level_rows(db_session)) == {"acme": [999_000]}, "globex is not covered: not ours"

    install = await db_session.get(PluginInstall, "tpl")
    install.enabled = False
    await db_session.commit()
    assert _tc(await pay_level_rows(db_session)) == {"acme": [300_000], "globex": [250_000]}, (
        "disabling gives ours back, because it was never overwritten; the legacy row stays unread"
    )


@pytest.mark.asyncio
async def test_a_retired_row_is_never_read(db_session):
    await _seed(db_session, active=False, enabled=False)
    globex = next(r for r in (await db_session.execute(
        CompanyCompLevel.__table__.select().where(CompanyCompLevel.company_slug == "globex",
                                                  CompanyCompLevel.provider == "manual"))).all())
    await db_session.execute(
        CompanyCompLevel.__table__.update().where(CompanyCompLevel.id == globex.id).values(retired_at=AT))
    await db_session.commit()
    assert "globex" not in _tc(await pay_level_rows(db_session))


@pytest.mark.asyncio
async def test_the_order_setting_is_read_from_settings(db_session):
    await _seed(db_session, active=True)
    await set_setting_dict(db_session, REFERENCE_SOURCES_KEY, {PAY_LEVELS: ["tpl"]})
    await db_session.commit()
    p = await load_providers(db_session)
    assert p.active[PAY_LEVELS] == ("tpl",)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("state", "tcs", "perks"),
    [
        ("unapproved: ours", [300_000], set()),
        ("selected, acme not read yet", [], set()),
        ("selected, acme read", [999_000], {("Free yacht", "tpl")}),
    ],
)
async def test_the_profile_route_shows_one_source_s_ladder_and_benefits(api_client, db_session, state, tcs, perks):
    await _seed(db_session, active=state.endswith("read"), approved=not state.startswith("unapproved"))
    body = (await api_client.get("/api/company-profiles/acme")).json()
    assert [r["tc_median"] for r in body["comp_levels"]] == tcs
    assert {(i["name"], i["provider"]) for c in body["benefits"] for i in c["items"]} == perks


@pytest.mark.asyncio
async def test_no_dataset_benefit_appears_beside_a_plugin_s_and_off_brings_the_dataset_back(api_client, db_session):
    """No per-cell precedence: a company in our dataset shows the
    plugin's rows alone while the plugin answers, and the dataset alone after."""
    company = "google"
    assert builtin_cells(company), "the fixture needs a company our dataset lists"
    db_session.add(CompanyProfile(slug=company, display_name="Google"))
    db_session.add(PluginInstall(
        plugin_id="tpl", name="Template", version="0.1.0", source_dir="/x", manifest_sha="m", code_sha="c",
        manifest={"provides": PROVIDES}, fingerprint="fp1", approved_fingerprint="fp1", enabled=True,
    ))
    await db_session.flush()
    cover(db_session, "tpl", (COMPANY_BENEFITS,), (company,))
    db_session.add_all([
        CompanyBenefit(company_slug=company, name="401K", category="Financial", value_usd=7_000,
                       provider="tpl"),
        CompanyBenefit(company_slug=company, name="Free yacht", category="Perks", value_usd=999_000,
                       provider="tpl"),
    ])
    await db_session.commit()
    on = (await api_client.get(f"/api/company-profiles/{company}")).json()
    items = [i for c in on["benefits"] for i in c["items"]]
    assert {(i["name"], i["benefit_type"]) for i in items} == {("401K", "retirement_plan"), ("Free yacht", None)}
    assert not any(i["builtin"] for i in items)

    (await db_session.get(PluginInstall, "tpl")).enabled = False
    await db_session.commit()
    off = (await api_client.get(f"/api/company-profiles/{company}")).json()
    items = [i for c in off["benefits"] for i in c["items"]]
    assert items and all(i["builtin"] and i["provider"] == "builtin" for i in items)


# --------------------------------------------------------------------------- #
# Company facts
# --------------------------------------------------------------------------- #


async def _claim(db, source, value, field="hq_city"):
    db.add(CompanyFact(company_slug="acme", field=field, value={"v": value}, source=source, observed_at=AT))
    await db.commit()


@pytest.mark.asyncio
async def test_a_plugin_s_identity_claim_never_reaches_the_profile_on_or_off(db_session):
    """Identity is ours: a selected plugin that read acme
    whole and outranks the blueprint still never names its HQ."""
    await _seed(db_session, active=True)
    await _claim(db_session, "blueprint", "Springfield")
    await _claim(db_session, "tpl", "Shelbyville")

    await resolve_and_materialize(db_session, "acme")
    profile = await db_session.get(CompanyProfile, "acme")
    assert (profile.hq_city, profile.field_meta["hq_city"]["source"]) == ("Springfield", "blueprint")
    assert [c["source"] for c in (await candidates_for(db_session, "acme"))["hq_city"]] == ["blueprint"]

    (await db_session.get(PluginInstall, "tpl")).enabled = False
    await db_session.commit()
    await resolve_and_materialize(db_session, "acme")
    assert (profile.hq_city, profile.field_meta["hq_city"]["source"]) == ("Springfield", "blueprint")


@pytest.mark.asyncio
async def test_a_plugin_s_company_size_is_read_beside_ours_and_never_written_into_it(db_session):
    """Company size is the one field a plugin answers: resolved from its
    claims when read, while the profile column keeps ours, on and off."""
    from tracker.profiles.store import plugin_fields

    await _seed(db_session, active=True)
    await _claim(db_session, "reported", 500, field="headcount")
    await _claim(db_session, "tpl", 999_000, field="headcount")
    await resolve_and_materialize(db_session, "acme")
    profile = await db_session.get(CompanyProfile, "acme")
    stamped = profile.profile_updated_at
    assert profile.headcount == 500

    on = await plugin_fields(db_session, await reader_providers(db_session))
    assert {slug: f["headcount"]["value"] for slug, f in on.items()} == {"acme": 999_000}
    assert [c["source"] for c in (await candidates_for(db_session, "acme"))["headcount"]] == ["tpl"]

    await resolve_and_materialize(db_session, "acme")  # a plugin event re-resolves: ours is unchanged
    assert (profile.headcount, profile.profile_updated_at) == (500, stamped)

    (await db_session.get(PluginInstall, "tpl")).enabled = False
    await db_session.commit()
    assert await plugin_fields(db_session, await reader_providers(db_session)) == {}
    assert [c["source"] for c in (await candidates_for(db_session, "acme"))["headcount"]] == ["reported"]


@pytest.mark.asyncio
async def test_the_claims_route_shows_the_claims_of_the_source_answering_each_field(api_client, db_session):
    await _seed(db_session, active=True)
    await _claim(db_session, "blueprint", "Springfield")
    await _claim(db_session, "tpl", "Shelbyville")
    await _claim(db_session, "reported", 500, field="headcount")
    await _claim(db_session, "tpl", 999_000, field="headcount")
    claims = (await api_client.get("/api/company-profiles/acme/claims")).json()["claims"]
    assert sorted((c["field"], c["source"]) for c in claims) == [("headcount", "tpl"), ("hq_city", "blueprint")]

    (await db_session.get(PluginInstall, "tpl")).enabled = False
    await db_session.commit()
    claims = (await api_client.get("/api/company-profiles/acme/claims")).json()["claims"]
    assert sorted((c["field"], c["source"]) for c in claims) == [("headcount", "reported"), ("hq_city", "blueprint")]


# --------------------------------------------------------------------------- #
# The long-lived processes never load the SDK
# --------------------------------------------------------------------------- #


def test_the_api_and_the_pipeline_import_without_the_plugin_sdk():
    """The registry reads the manifest the core stored as JSON; only install and
    the plugin host process import the SDK. Run with the SDK off the path."""
    probe = (
        "import sys; import tracker.api.app, tracker.workflows.pipeline, tracker.plugins.registry; "
        "print(sorted(m for m in sys.modules if m.startswith('roleband_plugin_sdk')))"
    )
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    env["PYTHONPATH"] = str(BACKEND)
    done = subprocess.run([sys.executable, "-c", probe], cwd=BACKEND, env=env, capture_output=True,
                          text=True, timeout=120, check=False)
    assert done.returncode == 0, done.stderr[-2000:]
    assert done.stdout.strip().splitlines()[-1] == "[]"
