"""Company blueprint — the single declaration point for a tracked built-in.

One `CompanyBlueprint` entry per company declares its identity (slug, display,
adapter, public/ticker, brand color). Everything else derives:

- `config.COMPANIES` is generated from `BLUEPRINT`.
- `ensure_builtins()` seeds `tracked_company` rows from that.
- `profiles.seed.ensure_company_profiles()` materializes a `company_profile`
  row per tracked company and records the identity fields as `"blueprint"`
  claims (rank below a plugin, market data or a manual pin — any real source supersedes).

Coverage of the per-company tables that stay in their own modules (the
leveling model in `tracker/levels/`, price fixtures, dashboard branding) is
ENFORCED rather than consolidated: each surface registers a check in
`ARTIFACT_CHECKS`, and `tests/test_company_blueprint.py` runs every check for
every company. Adding a company = one `BLUEPRINT` entry; the test then names
every artifact left to fill. Adding a per-company feature = register one check
here in the same change.

Intentionally partial tables are NOT gated — do not add checks for them:
`PayPolicy.equity_vehicle`/`vesting` (exceptions only).

Location/office surfaces are jobs-derived (aggregated from open postings at
read time), deliberately not a declared per-company artifact — a declared
office list would rot, while the derived view stays current with each scrape.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_PRICES_FIXTURE = Path(__file__).resolve().parent / "prices" / "fixtures" / "prices.json"
_DASHBOARD_COMPANIES = _REPO_ROOT / "dashboard" / "src" / "companies.json"


@dataclass(frozen=True)
class CompanyBlueprint:
    slug: str
    display: str
    adapter: str  # must resolve in connectors.ADAPTER_REGISTRY
    is_public: bool
    ticker: str | None = None  # required iff is_public
    brand_color: str | None = None  # hex; seeds profile + dashboard branding
    enabled: bool = True
    # On the curated list: a fresh install follows it (`ensure_builtins` seeds
    # the row enabled only when this is set). Written on every entry below
    # rather than left to the default — membership is decided per company,
    # and a new built-in silently landing outside the list is exactly
    # the choice nobody made. Catalog rows carry the same flag
    # (`company_catalog.CATALOG`, key `curated`), and a fresh install follows
    # those too.
    curated: bool = False


BLUEPRINT: dict[str, CompanyBlueprint] = {
    # Not curated: Google's robots.txt disallows the paginated listing we request,
    # so it is walled, and a walled company is followed only with consent.
    # `is_curated` would refuse it anyway; saying so here keeps the
    # declaration honest.
    "google": CompanyBlueprint("google", "Google", "google", True, ticker="GOOGL", brand_color="#4285F4", curated=False),
    "apple": CompanyBlueprint("apple", "Apple", "apple", True, ticker="AAPL", brand_color="#555b62", curated=True),
    "netflix": CompanyBlueprint("netflix", "Netflix", "eightfold", True, ticker="NFLX", brand_color="#E50914", curated=True),
    "openai": CompanyBlueprint("openai", "OpenAI", "ashby", False, brand_color="#10a37f", curated=True),
    "anthropic": CompanyBlueprint("anthropic", "Anthropic", "greenhouse", False, brand_color="#c9662b", curated=True),
    "amazon": CompanyBlueprint("amazon", "Amazon", "amazon", True, ticker="AMZN", brand_color="#FF9900", curated=True),
    "nvidia": CompanyBlueprint("nvidia", "Nvidia", "workday", True, ticker="NVDA", brand_color="#76b900", curated=False),
    "microsoft": CompanyBlueprint("microsoft", "Microsoft", "microsoft", True, ticker="MSFT", brand_color="#0067b8", curated=True),
    "spotify": CompanyBlueprint("spotify", "Spotify", "lever", True, ticker="SPOT", brand_color="#1DB954", curated=False),
}


# --------------------------------------------------------------------------- #
# Artifact-surface registry. A check = (name, fn(bp) -> list of problems).
# Checks lazily import their surface so this module stays import-light (it is
# imported by config.py) and free of cycles.
# --------------------------------------------------------------------------- #


def _check_adapter_registered(bp: CompanyBlueprint) -> list[str]:
    from tracker.connectors import ADAPTER_REGISTRY

    if bp.adapter not in ADAPTER_REGISTRY:
        return [f"adapter '{bp.adapter}' not in ADAPTER_REGISTRY"]
    return []


def _check_connector_resolves(bp: CompanyBlueprint) -> list[str]:
    from tracker.connectors import DETAIL_CONNECTORS, SOURCE_CONNECTORS, ConnectorBundle

    try:
        bundle = ConnectorBundle.resolve(bp.slug, bp.adapter)
    except Exception as exc:  # noqa: BLE001 — any construction failure is the finding
        return [f"ConnectorBundle.resolve failed: {exc!r}"]
    problems: list[str] = []
    if bundle.listing.company != bp.slug:
        problems.append(f"listing adapter bound to '{bundle.listing.company}', not '{bp.slug}'")
    # Convention: every built-in owns a replaceable DETAIL_CONNECTORS entry
    # (per-source parsers cover DB-registered companies, not built-ins).
    if bp.slug not in DETAIL_CONNECTORS:
        problems.append("missing from DETAIL_CONNECTORS (every built-in owns an entry)")
    elif bundle.detail is not DETAIL_CONNECTORS[bp.slug]:
        problems.append("bundle.detail does not resolve to the DETAIL_CONNECTORS entry")
    if bundle.detail is None and bp.adapter not in SOURCE_CONNECTORS:
        problems.append("no detail parser resolves (neither company nor source registry)")
    return problems


def _check_level_bands(bp: CompanyBlueprint) -> list[str]:
    from tracker.levels.ladder import ladder_for
    from tracker.schema import LevelBand

    ladder = ladder_for(bp.slug)
    if ladder is None or not ladder.rungs:
        return ["missing from levels/companies.COMPANIES (no engineering ladder)"]
    if not any(rung.band is LevelBand.SENIOR for rung in ladder.rungs):
        return ["levels ladder has no SENIOR rung"]
    return []


def _check_title_profile(bp: CompanyBlueprint) -> list[str]:
    """Every company declares a title profile, and every rung it names must exist.

    `calibrated=False` is a legal, honest declaration ("ladder not measured yet")
    and changes nothing at runtime. What is never legal is a rung rule pointing at
    a spelling absent from the company's ladder (own or parent's): that would map
    silently to no band instead of failing.
    """
    from tracker.levels.ladder import ladder_for, rung_for_code, rung_in
    from tracker.levels.titles import PROFILES

    profile = PROFILES.get(bp.slug)
    if profile is None:
        return ["missing from levels/titles.PROFILES"]

    problems: list[str] = []
    for rule in profile.rung_rules:
        if rung_for_code(bp.slug, rule.rung) is None:
            problems.append(
                f"rung rule {rule.pattern!r} -> {rule.rung!r} is not a rung of the {bp.slug} ladder"
            )
    # A family rule names a rung of ITS family's ladder: a rule for a
    # family with no ladder, or naming a rung that ladder lacks, would band
    # nothing.
    for family, rules in profile.family_rules.items():
        ladder = ladder_for(bp.slug, family)
        if ladder is None or ladder.family != family:
            problems.append(f"family rules for {family!r} but no {family} ladder")
            continue
        problems.extend(
            f"{family} rule {rule.pattern!r} -> {rule.rung!r} is not a rung of the {family} ladder"
            for rule in rules if rung_in(ladder, rule.rung) is None
        )
    if (profile.rung_rules or profile.family_rules) and not profile.calibrated:
        problems.append("has rung rules but is declared uncalibrated")
    return problems


def _check_pay_reference(bp: CompanyBlueprint) -> list[str]:
    """Senior, staff and principal each read a rung with seed pay, so a posting
    at those levels always has a fallback estimate. The rung comes from the
    ladder, so a lookup label cannot name a rung the ladder lacks."""
    from tracker.levels.pay import seed_range
    from tracker.schema import LevelBand

    return [
        f"no seeded rung for {band.value}"
        for band in (LevelBand.SENIOR, LevelBand.STAFF, LevelBand.PRINCIPAL)
        if seed_range(bp.slug, band) is None
    ]


def _check_offer_policy(bp: CompanyBlueprint) -> list[str]:
    """Every built-in declares how it builds an offer (`levels.pay`), even if only
    as "unverified": the package must know a no-bonus company from an unchecked
    one, and an absent entry is silently the latter."""
    from tracker.levels.pay import PAY_POLICIES

    policy = PAY_POLICIES.get(bp.slug)
    if policy is None:
        return ["missing from levels/pay.PAY_POLICIES"]
    problems: list[str] = []
    if policy.company != bp.slug:
        problems.append(f"pay policy keyed '{bp.slug}' names '{policy.company}'")
    return problems


def _check_stage_ladder(bp: CompanyBlueprint) -> list[str]:
    from tracker.levels.ladder import walk_guide

    if not walk_guide(bp.slug):
        return ["no guide ladder in levels/companies.COMPANIES (Walk level guide)"]
    return []


def _check_price_fixture(bp: CompanyBlueprint) -> list[str]:
    if not bp.is_public:
        return []
    if not bp.ticker:
        return ["is_public but no ticker declared"]
    try:
        tickers = json.loads(_PRICES_FIXTURE.read_text())["tickers"]
    except (OSError, ValueError, KeyError) as exc:
        return [f"prices fixture unreadable: {exc}"]
    if bp.ticker not in tickers:
        return [f"ticker {bp.ticker} missing from prices/fixtures/prices.json"]
    return []


def _check_dashboard_branding(bp: CompanyBlueprint) -> list[str]:
    try:
        companies = json.loads(_DASHBOARD_COMPANIES.read_text())
    except (OSError, ValueError) as exc:
        return [f"dashboard/src/companies.json unreadable: {exc}"]
    entry = companies.get(bp.slug)
    if entry is None:
        return ["missing from dashboard/src/companies.json"]
    problems = []
    if entry.get("name") != bp.display:
        problems.append(f"dashboard name '{entry.get('name')}' != display '{bp.display}'")
    if bp.brand_color and entry.get("color") != bp.brand_color:
        problems.append(f"dashboard color '{entry.get('color')}' != brand_color '{bp.brand_color}'")
    return problems


ARTIFACT_CHECKS: list[tuple[str, Callable[[CompanyBlueprint], list[str]]]] = [
    ("adapter_registered", _check_adapter_registered),
    ("connector_resolves", _check_connector_resolves),
    ("level_bands", _check_level_bands),
    ("title_profile", _check_title_profile),
    ("pay_reference", _check_pay_reference),
    ("offer_policy", _check_offer_policy),
    ("stage_ladder", _check_stage_ladder),
    ("price_fixture", _check_price_fixture),
    ("dashboard_branding", _check_dashboard_branding),
]
