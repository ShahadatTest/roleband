"""Company scraper adapters, each normalizing to `RawJob`."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, fields

from tracker.connectors.listing.accenture import AccentureAdapter
from tracker.connectors.listing.amazon import AmazonAdapter
from tracker.connectors.listing.apple import AppleAdapter
from tracker.connectors.listing.ashby import AshbyAdapter
from tracker.connectors.listing.atlassian import AtlassianAdapter
from tracker.connectors.listing.avature import AvatureAdapter, AvatureTlsAdapter
from tracker.connectors.listing.base import (
    BaseAdapter,
    BoardProbe,
    BreakerPool,
    DetailMode,
    ListingScope,
    RateLimiterPool,
)
from tracker.connectors.listing.deel import DeelAdapter
from tracker.connectors.listing.eightfold import EightfoldAdapter
from tracker.connectors.listing.google import GoogleAdapter
from tracker.connectors.listing.greenhouse import GreenhouseAdapter
from tracker.connectors.listing.jibe import JibeAdapter
from tracker.connectors.listing.kpmg import KpmgAdapter
from tracker.connectors.listing.lever import LeverAdapter
from tracker.connectors.listing.microsoft import MicrosoftAdapter
from tracker.connectors.listing.oracle import OracleAdapter
from tracker.connectors.listing.radancy import RadancyAdapter
from tracker.connectors.listing.recipe_adapter import RecipeAdapter
from tracker.connectors.listing.shopify import ShopifyAdapter
from tracker.connectors.listing.smartrecruiters import (
    SmartRecruitersAdapter,
    SmartRecruitersApiAdapter,
)
from tracker.connectors.listing.successfactors import SuccessFactorsAdapter
from tracker.connectors.listing.tiktok import TikTokAdapter
from tracker.connectors.listing.workable import WorkableAdapter
from tracker.connectors.listing.workday import WorkdayAdapter
from tracker.connectors.recipes import ExecutablePlan
from tracker.platform.clock import SourceClock
from tracker.taxonomy.locations import uncovered_groups

# Adapter-name -> class. Company config's "adapter" field selects one.
ADAPTER_REGISTRY: dict[str, type[BaseAdapter]] = {
    "greenhouse": GreenhouseAdapter,
    "lever": LeverAdapter,
    "ashby": AshbyAdapter,
    "eightfold": EightfoldAdapter,
    "apple": AppleAdapter,
    "google": GoogleAdapter,
    "amazon": AmazonAdapter,
    "workday": WorkdayAdapter,
    "microsoft": MicrosoftAdapter,
    "workable": WorkableAdapter,
    "smartrecruiters": SmartRecruitersAdapter,
    "smartrecruiters_api": SmartRecruitersApiAdapter,
    "atlassian": AtlassianAdapter,
    "oracle": OracleAdapter,
    "kpmg": KpmgAdapter,
    "accenture": AccentureAdapter,
    "avature": AvatureAdapter,
    "avature_tls": AvatureTlsAdapter,
    "jibe": JibeAdapter,
    "radancy": RadancyAdapter,
    "deel": DeelAdapter,
    "tiktok": TikTokAdapter,
    "successfactors": SuccessFactorsAdapter,
    "shopify": ShopifyAdapter,
}


def text_from_posting(adapter_name: str | None) -> bool:
    """Whether this adapter reads a stored posting's text from the posting
    alone (`BaseAdapter.text_from_posting`). False for an unknown or
    missing adapter: nothing to ask."""
    cls = ADAPTER_REGISTRY.get(adapter_name or "")
    return bool(cls is not None and cls.text_from_posting)


def route_family_of(adapter_name: str | None) -> str | None:
    """The route family an adapter belongs to, or None.

    Two adapters in one family reach the same tenants and posting ids by
    different routes, so a company may move between them and keep its jobs.
    `company_store.record_route` refuses any other move.
    """
    cls = ADAPTER_REGISTRY.get(adapter_name or "")
    return getattr(cls, "route_family", None) if cls is not None else None


@dataclass(frozen=True)
class AdapterCapabilities:
    """One adapter's class-level declarations, as `capability_table` reads them.

    Read off the class, never inferred from a run. `transport` names the
    SDK capabilities the class requires, or is None when it declares no
    `required_capabilities` (an adapter still on `self.get`/`self.post`).
    """

    name: str
    listing_scope: ListingScope
    detail: DetailMode
    text_from_posting: bool
    declares_total: bool
    board_probe: bool
    posting_page: bool
    transport: tuple[str, ...] | None


def capability_table() -> list[AdapterCapabilities]:
    """One row per registered adapter, sorted by name. Pure: no DB, no network.

    The single place the markers are tabulated, so a surface that wants to
    print them (ops status, Settings > Companies) reads this instead of
    restating them. `posting_page` is the same test `posting_pages.PAGE_PROVIDERS`
    derives from: the class overrides `read_posting_page`.
    """
    rows = []
    for name, cls in sorted(ADAPTER_REGISTRY.items()):
        required = cls.required_capabilities
        rows.append(
            AdapterCapabilities(
                name=name,
                listing_scope=cls.listing_scope,
                detail=cls.detail,
                text_from_posting=cls.text_from_posting,
                declares_total=cls.declares_total,
                board_probe=cls.board_probe is not None,
                posting_page=cls.read_posting_page is not BaseAdapter.read_posting_page,
                transport=(
                    None
                    if required is None
                    else tuple(f.name for f in fields(required) if getattr(required, f.name))
                ),
            )
        )
    return rows


class UnknownAdapterError(LookupError):
    """No connector in THIS build can serve a company's configured adapter.

    A deployment fact, never a source fact. Companies live in the database and
    connectors live in the code, so the two can disagree in either direction:
    a checkout older than the row, a rollback, or a typo on a user-added
    company. A bare `KeyError` would be charged to the *source* as a failed
    read.
    """

    def __init__(self, company_slug: str, adapter_name: str, available: list[str]) -> None:
        super().__init__(
            f"{company_slug}: no connector named {adapter_name!r} in this build "
            f"(available: {', '.join(sorted(available))})"
        )
        self.company_slug = company_slug
        self.adapter_name = adapter_name


def adapter_location_gaps(adapter_name: str, wanted: Iterable[str]) -> list[str]:
    """Location groups `adapter_name` has no query for, sorted.

    Reads the manifest off the class, so callers that only want to *describe*
    coverage (the scope settings screen) never construct an adapter or touch a
    board token. An unknown adapter reports no gaps: a company whose connector
    is missing from this build is already `unattempted`, and naming
    it here would blame a coverage manifest for a build problem.
    """
    cls = ADAPTER_REGISTRY.get(adapter_name)
    manifest = getattr(cls, "location_queries", None) if cls is not None else None
    if manifest is None:
        return []
    return sorted(uncovered_groups(manifest, wanted))


def build_adapter(
    company_slug: str,
    adapter_name: str,
    board_token: str | None = None,
    board_region: str | None = None,
    limiter_pool: RateLimiterPool | None = None,
    breaker_pool: BreakerPool | None = None,
    deadline: float | SourceClock | None = None,
    page_budgets: Mapping[str, int] | None = None,
    discovery: bool = False,
    location_groups: Iterable[str] | None = None,
    known_keys: Iterable[str] | None = None,
    recipe_plan: ExecutablePlan | None = None,
    consent: str | None = None,
) -> BaseAdapter:
    """The registered adapter for one company, configured for one read.

    `consent` is the company row's consent fingerprint
    (`BaseAdapter.collection_consent`), which the adapter's policy check reads
    on entry and on every request.
    """
    if adapter_name == RecipeAdapter.name:
        # A recipe binding runs its pinned, compiled revision; the
        # plan is loaded by the pipeline, never built from a stored token.
        if recipe_plan is None:
            raise UnknownAdapterError(company_slug, adapter_name, ["recipe (with its compiled plan)"])
        return RecipeAdapter(
            company_slug, recipe_plan, limiter_pool=limiter_pool, breaker_pool=breaker_pool,
            deadline=deadline, page_budgets=page_budgets, discovery=discovery,
            location_groups=location_groups, known_keys=known_keys, consent=consent,
        )
    try:
        cls = ADAPTER_REGISTRY[adapter_name]
    except KeyError:
        raise UnknownAdapterError(
            company_slug, adapter_name, list(ADAPTER_REGISTRY)
        ) from None
    return cls(
        company_slug,
        board_token=board_token,
        board_region=board_region,
        limiter_pool=limiter_pool,
        breaker_pool=breaker_pool,
        deadline=deadline,
        page_budgets=page_budgets,
        discovery=discovery,
        location_groups=location_groups,
        known_keys=known_keys,
        consent=consent,
    )


__all__ = [
    "ADAPTER_REGISTRY",
    "AdapterCapabilities",
    "capability_table",
    "route_family_of",
    "text_from_posting",
    "build_adapter",
    "UnknownAdapterError",
    "BaseAdapter",
    "BoardProbe",
    "BreakerPool",
    "RateLimiterPool",
    "GreenhouseAdapter",
    "LeverAdapter",
    "AshbyAdapter",
    "EightfoldAdapter",
    "AppleAdapter",
    "GoogleAdapter",
    "AmazonAdapter",
    "WorkdayAdapter",
    "MicrosoftAdapter",
    "WorkableAdapter",
    "SmartRecruitersAdapter",
    "SmartRecruitersApiAdapter",
    "AtlassianAdapter",
    "OracleAdapter",
    "KpmgAdapter",
    "AccentureAdapter",
    "AvatureAdapter",
    "AvatureTlsAdapter",
    "JibeAdapter",
    "RadancyAdapter",
    "DeelAdapter",
    "TikTokAdapter",
    "SuccessFactorsAdapter",
    "ShopifyAdapter",
]
