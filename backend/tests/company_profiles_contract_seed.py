"""Realistic rows and a pinned clock for the company-profile contract.

Every profile is built the way production builds one: source claims go through
`profiles.store.record_fact` and the profile is materialized by
`resolve_and_materialize`, so `field_meta`, `data_health` and each conflict are
the resolver's, never restated. Quotes and daily bars go through the price
store's own upserts. `pin_profile_clock` freezes `datetime.now` in the router,
the profile store and the price store at `NOW`, so a pin, a price window and a
freshness verdict answer the same bytes on every run.

Two sources, never mixed: OUR claims (the blueprint, our dataset,
filings, reported facts, a pin), which the profile columns resolve
from; and a plugin's (`PLUGIN`), whose ladder, benefits and claims are stored
for google only and read only while the plugin is installed and on
(`install_plugin`). The plugin also claims google's headquarters, which no
reader may ever show: identity is ours.

| slug | what it exercises |
|---|---|
| `google` | public and priced, every required field fresh (`ok`); a lower-trust headcount within tolerance (a candidate, not a conflict); the plugin's ladder (a second family that neither counts nor lists), benefits in two categories, one valued only in text, and its own headcount and HQ claims; bars inside and outside each price range, one with no open, high, low or volume; open roles in four cities, the HQ among them, beside a closed and an out-of-scope role |
| `reddit` | SEC EDGAR against a reported source's claims on `is_public` and `ticker` (conflicts), a headcount past its TTL (stale), no equity vehicle (missing): the worklist in all three reasons; a quote with no move; never read by the plugin |
| `anthropic` | private, unpriced; a manual headcount outranking an older disagreeing claim (conflict kept, nothing to review); an equity vehicle aging; comp notes; no roles; never read by the plugin |
| `hidden-co` | a profile whose tracked company is not visible: absent from the list, still answerable by slug |
| `acme-labs` | open roles and no profile: the card falls back to the slug |
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from tests.factories import make_company, make_job
from tracker.db.models import CompanyBenefit, CompanyCompLevel, CompanyProfile
from tracker.prices.provider import FIXTURE_SOURCE, Bar, Quote
from tracker.profiles import prices as price_store
from tracker.profiles import store as profile_store
from tracker.taxonomy.comp_families import REFERENCE_FAMILY

NOW = datetime(2026, 7, 20, 12, 0, tzinfo=UTC)
TODAY = NOW.date()
OTHER_FAMILY = "product_management"
#: The plugin whose own rows and claims the seed stores for google.
PLUGIN = "acme-pay"
PLUGIN_NAME = "Acme pay data"
PLUGIN_ATTRIBUTION = "Data source: Acme (https://pay.example)"


class _Clock(datetime):
    @classmethod
    def now(cls, tz=None):
        return NOW if tz is not None else NOW.replace(tzinfo=None)


def pin_profile_clock(monkeypatch) -> None:
    """`datetime.now` answers `NOW` wherever these routes read the clock."""
    import tracker.api.routers.companies as router

    for module in (router, profile_store, price_store):
        monkeypatch.setattr(module, "datetime", _Clock)


async def _profile(
    session: AsyncSession,
    slug: str,
    display: str,
    claims: list[tuple[str, object, str, int]],
    **columns,
) -> None:
    """A profile row, then each `(field, value, source, age in days)` claim, then resolution."""
    session.add(CompanyProfile(slug=slug, display_name=display, **columns))
    await session.flush()
    for field, value, source, age in claims:
        await profile_store.record_fact(
            session, slug, field, value, source, observed_at=NOW - timedelta(days=age)
        )
    await profile_store.resolve_and_materialize(session, slug, now=NOW)


def _rung(slug: str, label: str, tc: int | None, base: int | None, stock: int | None,
          bonus: int | None, *, family: str = REFERENCE_FAMILY) -> CompanyCompLevel:
    """A plugin's rung as it sends it: no band (ours bands it when read)."""
    return CompanyCompLevel(
        company_slug=slug, family=family, level_label=label, band=None, tc_median=tc,
        base_amount=base, stock_amount=stock, bonus_amount=bonus,
        base_pct=round(base / tc, 4) if tc and base is not None else None,
        stock_pct=round(stock / tc, 4) if tc and stock is not None else None,
        bonus_pct=round(bonus / tc, 4) if tc and bonus is not None else None,
        provider=PLUGIN, country="US", source_url=f"https://pay.example/companies/{slug}/salaries/{family}",
        fetched_at=NOW - timedelta(days=10),
    )


def _benefit(slug: str, category: str, name: str, value_usd: int | None, value_text: str | None,
             description: str | None) -> CompanyBenefit:
    return CompanyBenefit(
        company_slug=slug, category=category, name=name, value_usd=value_usd, value_text=value_text,
        description=description, provider=PLUGIN, fetched_at=NOW - timedelta(days=10),
    )


def _role(company: str, key: str, cities: list[str], **over):
    return make_job(
        f"{company}-{key}", company=company, dedupe_key=f"{company}:{key}", location_cities=cities, **over
    )


async def seed_company_profiles(session: AsyncSession) -> None:
    await _profile(
        session, "google", "Google",
        [
            ("display_name", "Google", "blueprint", 30),
            ("is_public", True, "blueprint", 30),
            ("ticker", "GOOG", "blueprint", 30),
            ("brand_color", "#4285F4", "blueprint", 30),
            ("is_public", True, "roleband", 10),
            ("hq_city", "Mountain View", "roleband", 10),
            ("website", "https://careers.google.com", "roleband", 10),
            ("logo_url", "https://static.example/custom/google.webp", "roleband", 10),
            ("headcount", 182502, "reported", 10),
            ("headcount", 190000, "blueprint", 5),
            ("equity_vehicle", "rsu", "reported", 10),
            ("vesting_schedule", "33/33/22/12", "reported", 10),
            # The plugin's own claims: its headcount answers while it is on; its
            # HQ is identity, never read.
            ("headcount", 180000, PLUGIN, 2),
            ("hq_city", "Plugin City", PLUGIN, 2),
        ],
    )
    await _profile(
        session, "reddit", "Reddit",
        [
            ("display_name", "Reddit", "roleband", 20),
            ("is_public", True, "sec_edgar", 20),
            ("ticker", "RDDT", "sec_edgar", 20),
            ("is_public", False, "reported", 20),
            ("ticker", None, "reported", 20),
            ("headcount", 2013, "reported", 200),
        ],
    )
    await _profile(
        session, "anthropic", "Anthropic",
        [
            ("display_name", "Anthropic", "blueprint", 30),
            ("is_public", False, "blueprint", 30),
            ("headcount", 45, "reported", 70),
            ("headcount", 1100, "manual", 3),
            ("equity_vehicle", "options", "reported", 120),
        ],
        comp_notes="Options with a ten-year exercise window.",
        manual_fields=["headcount"],
    )
    await _profile(session, "hidden-co", "Hidden Co", [("is_public", False, "blueprint", 30)])

    session.add_all([
        _rung("google", "L7", 907556, 315444, 499333, 92779),
        _rung("google", "L6", 594000, 272000, 272000, 50000),
        _rung("google", "L5", 400000, 220000, 180000, 0),
        _rung("google", "L3", None, 150000, None, None),
        _rung("google", "PM7", 850000, 300000, 450000, 100000, family=OTHER_FAMILY),
        _benefit("google", "Financial & Retirement", "401k", 9750, None, "50% match up to the IRS limit"),
        _benefit("google", "Financial & Retirement", "ESPP", None, "15% discount", None),
        _benefit("google", "Home", "Remote work stipend", 1000, None, None),
        make_company("hidden-co", "Hidden Co", visible=False, enabled=False, source="url"),
    ])

    await price_store.upsert_quote(
        session, "google", Quote("GOOG", 213.95, "USD", TODAY - timedelta(days=1), -1.03, -0.48), FIXTURE_SOURCE
    )
    await price_store.upsert_history(
        session, "google",
        [
            Bar(TODAY - timedelta(days=200), 150.0, 152.5, 149.25, 151.0, 21000000),
            Bar(TODAY - timedelta(days=120), 170.0, 171.0, 168.5, 170.75, 18000000),
            Bar(TODAY - timedelta(days=60), 190.5, 193.0, 189.0, 192.25, 17500000),
            Bar(TODAY - timedelta(days=2), None, None, None, 214.98, None),
            Bar(TODAY - timedelta(days=1), 214.98, 215.4, 212.6, 213.95, 16250000),
        ],
        FIXTURE_SOURCE,
    )
    await price_store.upsert_quote(
        session, "reddit", Quote("RDDT", 168.4, "USD", TODAY - timedelta(days=1), None, None), FIXTURE_SOURCE
    )
    await price_store.upsert_history(
        session, "reddit", [Bar(TODAY - timedelta(days=20), 160.0, 170.0, 158.0, 168.4, 5100000)], FIXTURE_SOURCE
    )

    session.add_all([
        _role("google", "mv-1", ["Mountain View, CA"]),
        _role("google", "mv-2", ["Mountain View, CA", "Sunnyvale, CA"]),
        _role("google", "ldn", ["London, UK"]),
        _role("google", "nyc", ["New York, NY"]),
        _role("google", "closed", ["Zurich, Switzerland"], status="closed", closed_at=NOW - timedelta(days=4)),
        _role("google", "out-of-scope", ["Tokyo, Japan"], in_scope=False),
        _role("reddit", "sf", ["San Francisco, CA"]),
        _role("acme-labs", "atx", ["Austin, TX"]),
    ])
    await session.commit()


async def install_plugin(session: AsyncSession) -> None:
    """The plugin installed, approved and on, having read google whole in every
    slot it serves; reddit and anthropic it has not read."""
    from tests.plugin_seed import cover
    from tracker.db.models import PluginInstall

    session.add(PluginInstall(
        plugin_id=PLUGIN, name=PLUGIN_NAME, version="1.0.0", source_dir="/x", manifest_sha="m",
        code_sha="c", fingerprint="fp", approved_fingerprint="fp", enabled=True,
        manifest={"plugin": {"id": PLUGIN, "name": PLUGIN_NAME, "attribution": PLUGIN_ATTRIBUTION},
                  "provides": [{"slot": "pay.levels"}, {"slot": "company.facts", "rank": 50},
                               {"slot": "company.benefits"}]},
    ))
    await session.flush()
    cover(session, PLUGIN, ("pay.levels", "company.facts", "company.benefits"), ("google",))
    await session.commit()
