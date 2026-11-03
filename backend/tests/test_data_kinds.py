"""Our dataset answers every kind of data; a plugin switches the same kinds whole; nothing is lost.

With the plugin off the app uses ONLY our
dataset; with it on, each kind it serves switches to the plugin's data whole,
never mixed with ours; identity and the pay policy never switch. Two contracts:

1. **Every file is accounted for.** Each file in `levels/atlas/` and
   `profiles/benefits_dataset/` is declared in `plugins/data_kinds.py` with the
   kind it serves (or as tooling, with a reason). A new file fails here by name.
2. **The switch is whole and reversible.** One company, real dataset files, the
   plugin's own rows and claims, and rows under a name no plugin publishes
   (read by nothing): off answers ours, on answers the
   plugin for every switching kind and ours for identity, off again answers
   exactly what off answered first. Per kind: the estimate stored on a posting,
   the pay ladder, the benefits, company size, and identity.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import select, update

from tests.plugin_seed import cover
from tracker.db.models import (
    CompanyBenefit,
    CompanyCompLevel,
    CompanyFact,
    CompanyProfile,
    Job,
    PluginInstall,
)
from tracker.plugins import data_kinds
from tracker.plugins.reestimate import reestimate
from tracker.plugins.registry import SLOTS

pytestmark = pytest.mark.usefixtures("no_escape")

TRACKER = Path(__file__).resolve().parents[1] / "tracker"
AT = datetime(2026, 10, 1, tzinfo=UTC)
PLUGIN = "acme-pay"
#: A name no plugin publishes, with its own family spelling: its rows are read by
#: nothing, even while a manifest still names it.
LEGACY = "acme.legacy"
LEGACY_FAMILY = "software-engineer"


# --------------------------------------------------------------------------- #
# 1. Every file
# --------------------------------------------------------------------------- #


def _dataset_files() -> set[str]:
    out = set()
    for folder in (data_kinds.ATLAS, data_kinds.BENEFITS):
        for path in (TRACKER / folder).iterdir():
            if path.is_file():
                out.add(f"{folder}{path.name}")
    return out


def test_every_dataset_file_says_which_kind_it_serves():
    declared = {f for k in data_kinds.KINDS for f in k.files} | set(data_kinds.TOOLING)
    assert sorted(_dataset_files() - declared) == [], "declare each new file in plugins/data_kinds.py"
    assert sorted(declared - _dataset_files()) == [], "a declared file no longer exists"


def test_every_plugin_slot_is_exactly_one_kind_and_levels_never_switch():
    slots = [k.slot for k in data_kinds.KINDS if k.slot is not None]
    assert sorted(slots) == sorted(SLOTS)
    assert data_kinds.kind_of_slot("pay.levels").name == "per_level_pay"
    assert next(k for k in data_kinds.KINDS if k.name == "levels").slot is None


# --------------------------------------------------------------------------- #
# 2. The switch
# --------------------------------------------------------------------------- #


async def _seed(db) -> None:
    db.add(CompanyProfile(slug="google", display_name="Google"))
    await db.flush()
    legacy = dict(provider=LEGACY)
    plugin = dict(provider=PLUGIN)
    db.add_all([
        # Under a name no plugin publishes: read by nothing.
        CompanyCompLevel(company_slug="google", family=LEGACY_FAMILY, level_label="L5", band="senior",
                         tc_median=777_000, base_amount=111_000, fetched_at=AT, **legacy),
        CompanyBenefit(company_slug="google", name="Dental Insurance", category="Insurance, Health, & Wellness",
                       value_text="The old source's words", **legacy),
        CompanyFact(company_slug="google", field="hq_city", value={"v": "Legacyville"}, source=LEGACY,
                    observed_at=AT),
        # The plugin's own, as it sends them (no band: ours bands L5 when read).
        CompanyCompLevel(company_slug="google", family="software_engineering", level_label="L5", band=None,
                         tc_median=999_000, base_amount=333_000, stock_amount=500_000, bonus_amount=166_000,
                         country="US", fetched_at=AT, **plugin),
        CompanyBenefit(company_slug="google", name="Health Insurance", category="Insurance, Health, & Wellness",
                       value_text="The plugin's words", **plugin),
        CompanyFact(company_slug="google", field="hq_city", value={"v": "Pluginville"}, source=PLUGIN,
                    observed_at=AT),
        CompanyFact(company_slug="google", field="headcount", value={"v": 190_000}, source=PLUGIN, observed_at=AT),
        Job(company="google", req_id="1", dedupe_key="google:1", title="Senior Software Engineer",
            url="https://example.com/1", level_band="senior", family="software_engineering",
            location_groups=["silicon_valley"], status="open"),
    ])
    await db.commit()


async def _answers(db, api_client) -> dict:
    """What every kind answers for google right now."""
    await reestimate(db)
    job = (await db.execute(select(Job))).scalar_one()
    await db.refresh(job)
    body = (await api_client.get("/api/company-profiles/google")).json()
    benefits = sorted(
        (i["benefit_type"] or i["name"], i["provider"], i["value_text"] or "")
        for g in body["benefits"] for i in g["items"]
    )
    return {
        "per_level_pay": (job.comp_median, job.comp_base_median, job.comp_provider),
        "ladder": [(r["level_label"], r["tc_median"], r["source"]) for r in body["comp_levels"]],
        "company_identity": body["fields"]["hq_city"]["value"],
        "company_size": body["fields"]["headcount"]["value"],
        "benefits": benefits,
    }


async def _set_plugin(db, *, enabled: bool) -> None:
    row = await db.get(PluginInstall, PLUGIN)
    if row is None:
        db.add(PluginInstall(
            plugin_id=PLUGIN, name="Acme pay data", version="1.0.0", source_dir="/x", manifest_sha="m",
            code_sha="c", fingerprint="fp", approved_fingerprint="fp", enabled=enabled,
            manifest={"plugin": {"id": PLUGIN, "legacy_sources": [LEGACY],
                                 "legacy_families": {LEGACY_FAMILY: "software_engineering"}},
                      "provides": [{"slot": "pay.levels"}, {"slot": "company.facts", "rank": 50},
                                   {"slot": "company.benefits"}]},
        ))
        await db.flush()
        cover(db, PLUGIN, ("pay.levels", "company.facts", "company.benefits"), ("google",))
    else:
        await db.execute(update(PluginInstall).values(enabled=enabled))
    await db.commit()


@pytest.mark.asyncio
async def test_off_is_ours_on_is_the_plugins_and_off_again_loses_nothing(db_session, api_client, monkeypatch):
    await _seed(db_session)

    off = await _answers(db_session, api_client)
    assert off["per_level_pay"][0] != 999_000 and off["per_level_pay"][2] not in (PLUGIN, LEGACY)
    assert off["company_identity"] is None  # our dataset holds no headquarters
    assert off["company_size"] is None  # nor a company size
    assert off["benefits"] and all(provider == "builtin" for _, provider, _ in off["benefits"])
    assert off["ladder"] == []

    await _set_plugin(db_session, enabled=True)
    on = await _answers(db_session, api_client)
    assert on["per_level_pay"] == (999_000, 333_000, PLUGIN)
    assert on["ladder"] == [("L5", 999_000, PLUGIN)]
    assert on["company_size"] == 190_000
    assert on["benefits"] == [("medical_insurance", PLUGIN, "The plugin's words")]  # whole: none of ours beside it
    assert on["company_identity"] is None, "identity never switches"
    assert LEGACY not in str(on) and "Legacyville" not in str(on)

    await _set_plugin(db_session, enabled=False)
    assert await _answers(db_session, api_client) == off
