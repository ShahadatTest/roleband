"""Job-seeker-facing company discovery catalog.

``company_catalog`` answers an implementation question: which
boards can be enabled immediately? This module answers the product question:
where might a job seeker want to look? Company identity is canonical and sector
membership is many-to-many, so selecting Microsoft in Gaming and Technology
still creates one tracking target.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from functools import cache
from typing import Any

from tracker.company_catalog import CATALOG, FAMILY_CONNECTORS
from tracker.company_directory import DIRECTORY_SOURCES
from tracker.config import COMPANIES
from tracker.source_review import SourceReview, declared_adapter, source_wall, user_directed_source


@dataclass(frozen=True)
class Sector:
    slug: str
    display: str
    description: str


@dataclass(frozen=True)
class DiscoveryCompany:
    slug: str
    display: str
    careers_url: str
    sectors: tuple[str, ...] = ()
    aliases: tuple[str, ...] = ()


SECTORS = (
    Sector("faang", "FAANG", "The exact five globally recognized big-tech employers."),
    Sector("ai", "AI", "Frontier labs, model companies, and AI infrastructure."),
    Sector("technology", "Technology", "Large and category-defining technology employers outside FAANG."),
    Sector("gaming", "Gaming", "Studios, platforms, engines, and interactive entertainment."),
    Sector("consulting", "Consulting", "Strategy, technology, and transformation consultancies."),
    Sector("fintech", "Fintech & payments", "Payments, financial infrastructure, consumer finance, and crypto."),
    Sector("quant", "Quantitative trading", "High-compensation research, trading, and low-latency engineering."),
    Sector("cybersecurity", "Cybersecurity", "Security, identity, threat research, and incident response."),
    Sector("cloud-data-devtools", "Cloud, data & devtools", "Infrastructure and tools used by technical teams."),
    Sector("semiconductors", "Semiconductors & compute", "Chip design, manufacturing, EDA, and compute platforms."),
    Sector("robotics", "Robotics, autonomy & defense", "Robotics, self-driving, aerospace, and defense technology."),
    Sector("consumer", "Consumer platforms", "Large consumer networks, marketplaces, and growth platforms."),
)


def _c(
    slug: str,
    display: str,
    careers_url: str,
    aliases: tuple[str, ...] = (),
) -> DiscoveryCompany:
    return DiscoveryCompany(slug, display, careers_url, aliases=aliases)


# Ordered within each sector: this order is the product recommendation, not a
# connector implementation queue.
_SECTOR_COMPANIES: dict[str, tuple[DiscoveryCompany, ...]] = {
    "faang": (
        _c("meta", "Meta", "https://www.metacareers.com/jobs/"),
        _c("amazon", "Amazon", "https://www.amazon.jobs/"),
        _c("apple", "Apple", "https://jobs.apple.com/en-us/search"),
        _c("netflix", "Netflix", "https://www.netflixjobs.com/"),
        _c("google", "Google", "https://www.google.com/about/careers/applications/jobs/results"),
    ),
    "ai": (
        _c("openai", "OpenAI", "https://openai.com/careers/search/"),
        _c("anthropic", "Anthropic", "https://www.anthropic.com/careers/jobs"),
        _c("google-deepmind", "Google DeepMind", "https://deepmind.google/careers/", ("DeepMind",)),
        _c("xai", "SpaceXAI", "https://x.ai/careers", ("xAI", "SpaceX AI", "SpaceXSI")),
        _c("mistral", "Mistral AI", "https://mistral.ai/careers/", ("Mistral",)),
        _c("cohere", "Cohere", "https://cohere.com/careers"),
        _c("scaleai", "Scale AI", "https://scale.com/careers", ("Scale",)),
        _c("perplexity", "Perplexity", "https://www.perplexity.ai/hub/careers"),
        _c("runway", "Runway", "https://runway.com/careers"),
        _c("databricks", "Databricks", "https://www.databricks.com/company/careers/open-positions"),
        _c("snowflake", "Snowflake", "https://careers.snowflake.com/us/en/search-results"),
        _c("hugging-face", "Hugging Face", "https://apply.workable.com/huggingface/"),
        # amilabs.xyz has no careers path of its own (/careers, /jobs, /join all
        # 404); the Ashby board is the company's own published careers page.
        _c("ami-labs", "AMI Labs", "https://jobs.ashbyhq.com/ami", ("AMI",)),
        _c("lovable", "Lovable", "https://lovable.dev/careers", ("Lovable AB", "GPT Engineer")),
    ),
    "technology": (
        _c("microsoft", "Microsoft", "https://careers.microsoft.com/"),
        _c("nvidia", "NVIDIA", "https://www.nvidia.com/en-us/about-nvidia/careers/"),
        _c("salesforce", "Salesforce", "https://www.salesforce.com/company/careers/jobs/"),
        _c("adobe", "Adobe", "https://careers.adobe.com/us/en/search-results"),
        _c("servicenow", "ServiceNow", "https://careers.servicenow.com/"),
        _c("palantir", "Palantir", "https://www.palantir.com/careers/"),
        _c("atlassian", "Atlassian", "https://www.atlassian.com/company/careers/all-jobs"),
        _c("shopify", "Shopify", "https://www.shopify.com/careers"),
        _c("spotify", "Spotify", "https://www.lifeatspotify.com/jobs"),
        _c("dropbox", "Dropbox", "https://www.dropbox.jobs/en/jobs/"),
        _c("asana", "Asana", "https://asana.com/jobs/all"),
        _c("figma", "Figma", "https://www.figma.com/careers/"),
        _c("notion", "Notion", "https://www.notion.com/careers"),
        _c("linear", "Linear", "https://linear.app/careers"),
        _c("flexport", "Flexport", "https://www.flexport.com/careers/"),
    ),
    "gaming": (
        _c("microsoft", "Microsoft", "https://careers.microsoft.com/", ("Xbox", "Microsoft Gaming")),
        # "PlayStation Global" is the name its board declares.
        _c("playstation", "PlayStation", "https://careers.playstation.com/",
           ("Sony Interactive Entertainment", "PlayStation Global")),
        _c("nintendo", "Nintendo", "https://careers.nintendo.com/"),
        _c("epic-games", "Epic Games", "https://www.epicgames.com/site/careers/jobs?lang=en-US"),
        _c("riot-games", "Riot Games", "https://www.riotgames.com/en/work-with-us"),
        _c("roblox", "Roblox", "https://careers.roblox.com/jobs"),
        _c("electronic-arts", "Electronic Arts", "https://www.ea.com/careers", ("EA",)),
        # The legal name is an alias because the board declares it
        # ("Take-Two Interactive Software, Inc."), and an identity probe may
        # only be settled by a name WE assert.
        _c("take-two-interactive", "Take-Two Interactive", "https://careers.take2games.com/",
           ("Take-Two", "Take-Two Interactive Software")),
        _c("ubisoft", "Ubisoft", "https://www.ubisoft.com/en-us/company/careers/search"),
        _c("valve", "Valve", "https://www.valvesoftware.com/en/"),
        _c("unity", "Unity", "https://careers.unity.com/"),
        _c("discord", "Discord", "https://discord.com/careers"),
        _c("twitch", "Twitch", "https://www.twitch.tv/jobs/en/"),
        _c("supercell", "Supercell", "https://supercell.com/en/careers/"),
    ),
    "consulting": (
        _c("mckinsey-company", "McKinsey & Company", "https://www.mckinsey.com/careers/search-jobs", ("McKinsey",)),
        _c("boston-consulting-group", "Boston Consulting Group", "https://careers.bcg.com/global/en/search-results", ("BCG",)),
        _c("bain-company", "Bain & Company", "https://www.bain.com/careers/find-a-role/", ("Bain",)),
        _c("accenture", "Accenture", "https://www.accenture.com/us-en/careers/jobsearch"),
        _c("deloitte", "Deloitte", "https://www.deloitte.com/global/en/careers/job-search.html"),
        # The US search; jobs.us.pwc.com does not resolve.
        _c("pwc", "PwC", "https://jobs-us.pwc.com/us/en/search-results", ("PricewaterhouseCoopers",)),
        _c("ey", "EY", "https://careers.ey.com/", ("Ernst & Young",)),
        _c("kpmg", "KPMG", "https://kpmg.com/xx/en/careers.html"),
        _c("oliver-wyman", "Oliver Wyman", "https://careers.marsh.com/global/en/oliver-wyman"),
        _c("roland-berger", "Roland Berger", "https://www.rolandberger.com/en/Join/All-Jobs/"),
    ),
    "fintech": (
        _c("stripe", "Stripe", "https://stripe.com/jobs/search"),
        _c("block", "Block", "https://block.xyz/careers/jobs", ("Square",)),
        _c("adyen", "Adyen", "https://careers.adyen.com/vacancies"),
        _c("paypal", "PayPal", "https://careers.pypl.com/home/"),
        _c("wise", "Wise", "https://wise.jobs/", ("TransferWise",)),
        _c("revolut", "Revolut", "https://www.revolut.com/careers/"),
        _c("klarna", "Klarna", "https://www.klarna.com/careers/"),
        _c("coinbase", "Coinbase", "https://www.coinbase.com/careers/positions"),
        _c("robinhood", "Robinhood", "https://careers.robinhood.com/"),
        _c("plaid", "Plaid", "https://plaid.com/careers/"),
        _c("ramp", "Ramp", "https://ramp.com/careers"),
        _c("brex", "Brex", "https://www.brex.com/careers"),
        _c("affirm", "Affirm", "https://www.affirm.com/careers"),
        _c("gusto", "Gusto", "https://gusto.com/about/careers"),
    ),
    "quant": (
        _c("jane-street", "Jane Street", "https://www.janestreet.com/join-jane-street/open-roles/"),
        _c("citadel-securities", "Citadel Securities", "https://www.citadelsecurities.com/careers/open-opportunities/"),
        _c("citadel", "Citadel", "https://www.citadel.com/careers/open-opportunities/"),
        _c("hudson-river-trading", "Hudson River Trading", "https://www.hudsonrivertrading.com/careers/", ("HRT",)),
        _c("two-sigma", "Two Sigma", "https://www.twosigma.com/careers/"),
        _c("optiver", "Optiver", "https://www.optiver.com/join-us/jobs/"),
        _c("imc-trading", "IMC Trading", "https://www.imc.com/eu/search-careers", ("IMC",)),
        _c("jump-trading", "Jump Trading", "https://www.jumptrading.com/careers/"),
        _c("drw", "DRW", "https://www.drw.com/work-at-drw/listings"),
        _c("susquehanna-international-group", "Susquehanna International Group", "https://careers.sig.com/", ("SIG",)),
        _c("tower-research-capital", "Tower Research Capital", "https://tower-research.com/open-positions/"),
        _c("xtx-markets", "XTX Markets", "https://www.xtxmarkets.com/careers/"),
    ),
    "cybersecurity": (
        _c("crowdstrike", "CrowdStrike", "https://www.crowdstrike.com/en-us/careers/"),
        _c("palo-alto-networks", "Palo Alto Networks", "https://jobs.paloaltonetworks.com/en/"),
        _c("cloudflare", "Cloudflare", "https://www.cloudflare.com/careers/jobs/"),
        _c("zscaler", "Zscaler", "https://www.zscaler.com/careers/search"),
        _c("okta", "Okta", "https://www.okta.com/company/careers/"),
        _c("wiz", "Wiz", "https://www.wiz.io/careers"),
        _c("snyk", "Snyk", "https://snyk.io/careers/"),
        _c("sentinelone", "SentinelOne", "https://www.sentinelone.com/jobs/"),
        _c("fortinet", "Fortinet", "https://www.fortinet.com/corporate/careers"),
        _c("1password", "1Password", "https://1password.com/careers"),
    ),
    "cloud-data-devtools": (
        _c("datadog", "Datadog", "https://careers.datadoghq.com/"),
        _c("github", "GitHub", "https://www.github.careers/careers-home"),
        _c("gitlab", "GitLab", "https://about.gitlab.com/jobs/all-jobs/"),
        _c("hashicorp", "HashiCorp", "https://www.hashicorp.com/en/careers"),
        _c("mongodb", "MongoDB", "https://www.mongodb.com/company/careers/jobs"),
        _c("confluent", "Confluent", "https://careers.confluent.io/jobs"),
        _c("vercel", "Vercel", "https://vercel.com/careers"),
        _c("docker", "Docker", "https://www.docker.com/careers/"),
        _c("elastic", "Elastic", "https://jobs.elastic.co/"),
        _c("grafana-labs", "Grafana Labs", "https://grafana.com/about/careers/open-positions/"),
        _c("cloudflare", "Cloudflare", "https://www.cloudflare.com/careers/jobs/"),
        _c("figma", "Figma", "https://www.figma.com/careers/"),
        _c("linear", "Linear", "https://linear.app/careers"),
        _c("lovable", "Lovable", "https://lovable.dev/careers"),
    ),
    "semiconductors": (
        _c("nvidia", "NVIDIA", "https://www.nvidia.com/en-us/about-nvidia/careers/"),
        _c("amd", "AMD", "https://careers.amd.com/careers-home", ("Advanced Micro Devices",)),
        _c("intel", "Intel", "https://jobs.intel.com/en"),
        _c("arm", "Arm", "https://careers.arm.com/search-jobs"),
        _c("qualcomm", "Qualcomm", "https://careers.qualcomm.com/careers"),
        _c("broadcom", "Broadcom", "https://careers.broadcom.com/"),
        _c("tsmc", "TSMC", "https://careers.tsmc.com/en_US/careers/"),
        _c("asml", "ASML", "https://www.asml.com/en/careers/find-your-job"),
        _c("micron", "Micron", "https://careers.micron.com/careers"),
        _c("applied-materials", "Applied Materials", "https://www.appliedmaterials.com/us/en/careers/search-jobs.html"),
        _c("cadence", "Cadence", "https://www.cadence.com/en_US/home/company/life-at-cadence/careers.html"),
        _c("synopsys", "Synopsys", "https://careers.synopsys.com/"),
    ),
    "robotics": (
        _c("tesla", "Tesla", "https://www.tesla.com/careers/search/"),
        _c("waymo", "Waymo", "https://waymo.com/careers/"),
        _c("anduril", "Anduril", "https://www.anduril.com/open-roles/", ("Anduril Industries",)),
        _c("shield-ai", "Shield AI", "https://shield.ai/careers/"),
        _c("skydio", "Skydio", "https://www.skydio.com/careers"),
        _c("zoox", "Zoox", "https://zoox.com/careers/"),
        _c("aurora", "Aurora", "https://aurora.tech/careers"),
        _c("nuro", "Nuro", "https://www.nuro.ai/careers"),
        _c("figure", "Figure", "https://www.figure.ai/careers", ("Figure AI",)),
        _c("zipline", "Zipline", "https://www.zipline.com/careers"),
        _c("rocket-lab", "Rocket Lab", "https://rocketlabcorp.com/careers/positions/"),
        _c("samsara", "Samsara", "https://www.samsara.com/company/careers/roles"),
    ),
    "consumer": (
        _c("airbnb", "Airbnb", "https://careers.airbnb.com/positions/"),
        _c("uber", "Uber", "https://jobs.uber.com/en/jobs/"),
        # "DoorDash USA" is what the board declares, and accepting it is a human
        # decision rather than a string one: it is the same shape as the board
        # token `figure` declaring "Figure Lending", a DIFFERENT company. The
        # alias is where that knowledge is recorded.
        _c("doordash", "DoorDash", "https://careersatdoordash.com/jobs/", ("DoorDash USA",)),
        _c("lyft", "Lyft", "https://www.lyft.com/careers"),
        _c("instacart", "Instacart", "https://instacart.careers/current-openings/"),
        _c("pinterest", "Pinterest", "https://www.pinterestcareers.com/jobs/"),
        _c("reddit", "Reddit", "https://www.redditinc.com/careers"),
        _c("spotify", "Spotify", "https://www.lifeatspotify.com/jobs"),
        _c("discord", "Discord", "https://discord.com/careers"),
        _c("snap", "Snap", "https://careers.snap.com/jobs", ("Snapchat",)),
        _c("tiktok", "TikTok", "https://careers.tiktok.com/"),
        _c("booking", "Booking.com", "https://careers.booking.com/", ("Booking",)),
    ),
}


def _canonical_catalog() -> dict[str, DiscoveryCompany]:
    companies: dict[str, DiscoveryCompany] = {}
    for sector in SECTORS:
        for incoming in _SECTOR_COMPANIES[sector.slug]:
            existing = companies.get(incoming.slug)
            if existing is None:
                companies[incoming.slug] = replace(incoming, sectors=(sector.slug,))
                continue
            if existing.careers_url != incoming.careers_url:
                raise RuntimeError(f"conflicting careers URLs for {incoming.slug}")
            companies[incoming.slug] = replace(
                existing,
                sectors=(*existing.sectors, sector.slug),
                aliases=tuple(dict.fromkeys((*existing.aliases, *incoming.aliases))),
            )
    return companies


COMPANY_DISCOVERY = _canonical_catalog()

#: Companies with no collectable source, and the reason a seeker sees. `planned`
#: is a promise ("Connector planned") and these are not promises: tesla's board
#: refuses an identified client on a robots-allowed path, and Valve publishes no
#: machine-readable board at all — not on an ATS we run, not on one we could
#: add, and not through anybody else's index either. A
#: company parked here stops being selectable, which is the point: adding it
#: today creates a `pending` row that can never scrape, and saying so is more
#: use than a queue position that will not come up.
#: slug -> why it is parked, as a code the dashboard says (`ParkedReason`).
_PARKED = {
    "tesla": "bot_protected",
    # Valve's one jobs page is plain HTML a recipe could read, but its robots.txt
    # (served at /en/robots.txt) says `Disallow: /jobs` and `Disallow: /en/jobs`
    # for every agent. A recipe has no consent path, so
    # it stays parked for that reason rather than for having no board.
    "valve": "robots_disallow",
    # metacareers robots prohibits automated collection without express written
    # permission. There is no adapter; the catalog row stays
    # because Meta is a company a seeker looks for, and "we are not permitted to
    # collect this" is more use than silent absence, and it is the record of
    # why there is no adapter.
    "meta": "prohibits_collection",
    # tsmc is not in this table: its careers portal refuses identified
    # clients, so it is collected walled, on the TLS tier, only for a user
    # who follows it (`avature_tls`).
}
#: The same reasons in English, for the log line a refused selection writes.
_PARKED_WHY = {
    "bot_protected": "Careers source is currently bot-protected",
    "robots_disallow": "Valve asks not to have its jobs page read automatically",
    "prohibits_collection": "Source prohibits automated collection",
}
#: Every connector state; the dashboard names each (`ConnectorState`).
CONNECTOR_STATES = ("live", "ready", "family", "active", "planned", "parked")


def connector_state(slug: str, tracked: Any | None = None) -> str:
    if slug in _PARKED:
        return "parked"
    if slug in COMPANIES:
        return "live"
    if slug in CATALOG:
        return "ready"
    if slug in FAMILY_CONNECTORS:
        return "family"
    if tracked is not None and tracked.status == "active" and tracked.adapter:
        return "active"
    return "planned"


def collecting_provider(slug: str, tracked: Any | None = None) -> str | None:
    """The listing provider a company is collected through, however it is known.

    The declared provider wins (`source_review.declared_adapter`, the rule the
    collection gates read too), with one exception: a stored row on another
    ROUTE of the declared family (a company whose board moved to another route
    of its family) is collected through the stored route, so that is the one
    whose wall and consent apply. A company with no declared provider is
    collected through its stored one.
    """
    stored = getattr(tracked, "adapter", None) if tracked is not None else None
    return declared_adapter(slug, stored) or stored


def company_wall(slug: str, tracked: Any | None = None) -> SourceReview | None:
    """The register row walling this company's source, or None.

    A wall is the SOURCE's (robots or a bot wall on the route we request), so
    every company on that source is walled — `google-deepmind` rides the Google
    connector family and shares Google's robots verdict.
    """
    provider = collecting_provider(slug, tracked)
    return source_wall(provider, company=slug) if provider else None


def has_consented(slug: str, tracked: Any | None) -> bool:
    """Whether the user consented to collecting this walled company.

    The dashboard shows the consent dialog only when this is false, so a
    consent given once is never asked for again.
    """
    if company_wall(slug, tracked) is None or tracked is None:
        return False
    return bool(getattr(tracked, "consent_fingerprint", None))


def is_curated(slug: str, tracked: Any | None = None) -> bool:
    """On the curated list: the well-known companies a user starts with.

    One rule for every kind of row. A built-in answers from its blueprint, a
    catalog or connector-family row from its own `curated` key (absent means
    no), and a company added by URL is never curated — it is the user's own
    choice, not a list RoleBand ships. Parked companies are never curated either:
    the list promises companies RoleBand can scan. And a WALLED company is never
    curated: the curated list is what a user gets without being asked, and a
    wall is exactly what must be asked about.

    Nor is a company on a USER-DIRECTED source. That source needs no consent,
    but it is collected only when a user chooses the company, and the curated
    list is exactly the place a company arrives without being chosen.
    """
    if slug in _PARKED or company_wall(slug, tracked) is not None:
        return False
    provider = collecting_provider(slug, tracked)
    if provider and user_directed_source(provider, company=slug):
        return False
    if slug in COMPANIES:
        return bool(COMPANIES[slug]["curated"])
    if slug in CATALOG:
        return bool(CATALOG[slug].get("curated", False))
    if slug in FAMILY_CONNECTORS:
        return bool(FAMILY_CONNECTORS[slug].get("curated", False))
    return False


def discovery_company_fields(slug: str) -> dict[str, Any] | None:
    """Concrete ``TrackedCompany`` fields for a discovery selection."""
    company = COMPANY_DISCOVERY.get(slug)
    if company is None:
        return None
    if slug in _PARKED:
        raise ValueError(_PARKED_WHY[_PARKED[slug]])
    if slug in CATALOG:
        entry = CATALOG[slug]
        return {
            "slug": slug,
            "display": entry["display"],
            "adapter": entry["adapter"],
            "board_token": entry["board_token"],
            # Same rule as `company_store.resolve_company`, which reaches the
            # catalog first and is the path an add actually takes. Repeated
            # rather than omitted because two readings of one row that disagree
            # about a Lever tenant's region fail silently: a wrong region
            # answers the same 404 as a wrong token.
            "board_region": entry.get("board_region"),
            "careers_url": company.careers_url,
            "status": "active",
            "source": "catalog",
        }
    if slug in FAMILY_CONNECTORS:
        family = FAMILY_CONNECTORS[slug]
        return {
            "slug": slug,
            "display": company.display,
            "adapter": family["adapter"],
            "board_token": family["board_token"],
            "careers_url": company.careers_url,
            "status": "active",
            "source": "catalog",
        }
    return {
        "slug": slug,
        "display": company.display,
        "adapter": None,
        "board_token": None,
        "careers_url": company.careers_url,
        "status": "pending",
        "source": "catalog",
    }


def _wall_fields(slug: str, row: Any | None) -> dict[str, Any]:
    wall = company_wall(slug, row)
    return {
        "wall": None if wall is None else wall.wall.value if wall.wall else None,
        "consented": has_consented(slug, row),
    }


def build_company_discovery(
    *,
    tracked: Mapping[str, Any],
) -> dict[str, list[dict[str, Any]]]:
    """Merge the static recommendation catalog with the user's live roster.

    Deliberately carries no open-role counts. Identity and tracking state come
    from the catalog plus one company table read; the counts are an aggregate
    over `jobs` that answers a different question and is served separately
    (`GET /api/companies/open-counts`), so the roster can render before the
    aggregate is ready.
    """
    items: list[dict[str, Any]] = []
    for company in COMPANY_DISCOVERY.values():
        row = tracked.get(company.slug)
        state = connector_state(company.slug, row)
        items.append(
            {
                "slug": company.slug,
                "display": company.display,
                "careers_url": company.careers_url,
                "sectors": list(company.sectors),
                "aliases": list(company.aliases),
                "connector_state": state,
                "parked_reason": _PARKED.get(company.slug),
                "selectable": state != "parked",
                "tracked": row is not None,
                "enabled": bool(row and row.enabled),
                "visible": True if row is None else row.visible,
                "builtin": company.slug in COMPANIES,
                "curated": is_curated(company.slug, row),
                "directory": False,
                **_wall_fields(company.slug, row),
                "status": None if row is None else row.status,
            }
        )

    # Preserve URL-added/local companies without forcing them into a made-up
    # industry. They remain searchable under All companies.
    for slug, row in tracked.items():
        if slug in COMPANY_DISCOVERY:
            continue
        state = connector_state(slug, row)
        items.append(
            {
                "slug": slug,
                "display": row.display,
                "careers_url": row.careers_url,
                "sectors": [],
                "aliases": [],
                "connector_state": state,
                "parked_reason": None,
                "selectable": True,
                "tracked": True,
                "enabled": row.enabled,
                "visible": row.visible,
                "builtin": slug in COMPANIES,
                "curated": is_curated(slug, row),
                "directory": row.source in DIRECTORY_SOURCES,
                **_wall_fields(slug, row),
                "status": row.status,
                "detected_family": row.detected_family if row.status == "pending" else None,
                "pending_reason": row.pending_reason if row.status == "pending" else None,
            }
        )

    sector_out = []
    for sector in SECTORS:
        members = [item for item in items if sector.slug in item["sectors"]]
        sector_out.append(
            {
                "slug": sector.slug,
                "company_count": len(members),
                "ready_count": sum(
                    item["connector_state"] in {"live", "ready", "family", "active"}
                    for item in members
                ),
                "selected_count": sum(item["enabled"] for item in members),
            }
        )
    return {"sectors": sector_out, "companies": items}


def named_companies() -> frozenset[str]:
    """The companies the app names and ships atlas data for: the built-ins,
    the catalog and the discovery list. The directory is not named; it reads
    the generic ladder."""
    return frozenset(COMPANIES) | frozenset(CATALOG) | frozenset(COMPANY_DISCOVERY)


@cache
def company_names() -> dict[str, tuple[str, ...]]:
    """Every named company with what a person types for it, lowercased: the
    slug, each display name its sources give (the blueprint, the catalog, the
    discovery list) and the discovery list's aliases. What `search.parse`
    matches a query's company names against."""
    names: dict[str, tuple[str, ...]] = {}
    for slug in sorted(named_companies()):
        found = {slug}
        if slug in COMPANIES:
            found.add(COMPANIES[slug]["display"])
        if slug in CATALOG:
            found.add(CATALOG[slug]["display"])
        if slug in COMPANY_DISCOVERY:
            found.add(COMPANY_DISCOVERY[slug].display)
            found.update(COMPANY_DISCOVERY[slug].aliases)
        names[slug] = tuple(sorted({name.lower() for name in found if name}))
    return names
