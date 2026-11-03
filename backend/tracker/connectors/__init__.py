"""Company connectors — listing adapters + detail parsers under one roof.

`listing/` holds the multi-tenant listing adapters (`ADAPTER_REGISTRY`,
`build_adapter`); `detail/` holds the per-company/per-source detail parsers
(`DETAIL_CONNECTORS`, `SOURCE_CONNECTORS`, `structure_job_detail`). The two
kinds stay separate classes: listing adapters are multi-tenant, detail parsers
per-company. `ConnectorBundle.resolve` is the one seam that pairs them.
"""

from __future__ import annotations

from dataclasses import dataclass

from tracker.connectors.detail import (
    DETAIL_CONNECTORS,
    SOURCE_CONNECTORS,
    get_detail_connector,
    structure_job_detail,
)
from tracker.connectors.detail.base import HtmlDetailConnector
from tracker.connectors.listing import (
    ADAPTER_REGISTRY,
    UnknownAdapterError,
    build_adapter,
    route_family_of,
    text_from_posting,
)
from tracker.connectors.listing.base import (
    BaseAdapter,
    BoardProbe,
    BreakerPool,
    RateLimiterPool,
    ReadPosition,
    RouteMoved,
)
from tracker.platform.clock import SourceClock


@dataclass(frozen=True)
class ConnectorBundle:
    """Both connector kinds for one company, resolved through the registries.

    Thin, named resolution seam with no behavior of its own. `listing` is a constructed
    adapter (via `build_adapter`); `detail` is the parser `structure_job_detail`
    would pick for the company/source, or None when only the shared default
    HTML parser applies.
    """

    company_slug: str
    listing: BaseAdapter
    detail: HtmlDetailConnector | None

    @classmethod
    def resolve(
        cls,
        company_slug: str,
        adapter_name: str,
        board_token: str | None = None,
        limiter_pool: RateLimiterPool | None = None,
        breaker_pool: BreakerPool | None = None,
        deadline: float | SourceClock | None = None,
    ) -> ConnectorBundle:
        listing = build_adapter(
            company_slug,
            adapter_name,
            board_token=board_token,
            limiter_pool=limiter_pool,
            breaker_pool=breaker_pool,
            deadline=deadline,
        )
        detail = DETAIL_CONNECTORS.get(company_slug) or SOURCE_CONNECTORS.get(adapter_name)
        return cls(company_slug=company_slug, listing=listing, detail=detail)


__all__ = [
    "ADAPTER_REGISTRY",
    "RouteMoved",
    "route_family_of",
    "BaseAdapter",
    "BoardProbe",
    "BreakerPool",
    "ConnectorBundle",
    "DETAIL_CONNECTORS",
    "HtmlDetailConnector",
    "RateLimiterPool",
    "ReadPosition",
    "SOURCE_CONNECTORS",
    "UnknownAdapterError",
    "build_adapter",
    "get_detail_connector",
    "structure_job_detail",
    "text_from_posting",
]
