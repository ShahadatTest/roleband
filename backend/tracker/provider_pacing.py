"""How hard one provider may be driven, and why — one declaration, two readers.

The roster can grow far faster than any one provider tolerates: the catalog
offers many more boards than a fresh install collects. Enabling them
must not become a way to discover a provider's rate limit by tripping it, so the
numbers that decide load live here, once, next to the evidence for each.

Two readers, deliberately the same table:

* `connectors.listing.base.BaseAdapter` takes `min_delay_seconds` for the pacer
  every board on that provider SHARES, and `host_scope` for what "shares" means;
* `workflows.scheduler.choose_due_work` takes `max_boards_in_flight` for how
  many of that provider's boards one shard may carry.

**Adding boards must never multiply a provider's request rate.** That property
is what makes a bigger roster safe, and it is already structural rather than
hoped for: `RateLimiterPool` hands one pacer to every consumer of a scope, and
`collect_sources` admits backends concurrently while draining each backend's
companies SERIALLY. So eight Greenhouse boards in one shard are eight requests
down one paced queue, not eight at once. This module only decides how deep that
queue may get and how fast it may drain.

**A provider is not always one server**, which is the distinction `host_scope`
exists for and the one a flat table gets wrong. Greenhouse, Ashby, Lever and
Workable answer every tenant from one shared API host, so adding tenants adds
load to a single service and they must share a pacer. Workday and Eightfold
serve each tenant from the tenant's OWN host (`nvidia.wd5.myworkdayjobs.com`,
`explore.jobs.netflix.net`), so pacing them as one bucket both starves each
tenant of the allowance it is entitled to and misdescribes where the load lands
— and one tenant's outage would open a breaker on hosts that are answering
fine. That is the argument for keying Lever's two regions apart,
applied to the case where every tenant is its own deployment.

Numbers are conservative by construction. `DEFAULT` governs any provider with no
row, at one board in flight, so a family added without a measurement cannot
acquire parallelism by omission — the failure mode is slow, never blocked.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class HostScope(StrEnum):
    """Does one provider mean one server, or one per tenant?"""

    #: Every tenant is served by one shared API host. Boards share a pacer.
    SHARED = "shared"
    #: Each tenant is its own deployment. Boards pace (and trip breakers)
    #: independently, because they are independent services.
    PER_TENANT = "per_tenant"


@dataclass(frozen=True)
class ProviderPacing:
    """The standing load policy for one provider."""

    provider: str
    #: Seconds between requests on the pacer this provider's boards share.
    #: `None` = use `Settings.scraper_min_delay_seconds`, the global default.
    min_delay_seconds: float | None
    #: How many of this provider's boards one scheduler shard may carry. They
    #: are drained serially behind the shared pacer, so this is queue DEPTH,
    #: not parallelism — it decides how much of the roster a tick can retire.
    max_boards_in_flight: int
    host_scope: HostScope
    #: Why these numbers. A pacing number with no evidence is a guess that
    #: looks like a measurement, and the next person cannot tell which.
    evidence: str


#: Any provider with no row. One board per shard and the global delay: a family
#: onboarded without a measurement gets the most cautious load, which is the
#: only safe default for a number that decides whether we get blocked.
DEFAULT = ProviderPacing(
    provider="*",
    min_delay_seconds=None,
    max_boards_in_flight=1,
    host_scope=HostScope.SHARED,
    evidence="no measurement for this provider; conservative default",
)


PROVIDER_PACING: dict[str, ProviderPacing] = {
    "greenhouse": ProviderPacing(
        provider="greenhouse",
        min_delay_seconds=1.0,
        max_boards_in_flight=6,
        host_scope=HostScope.SHARED,
        evidence="one GET per board on the shared `boards-api.greenhouse.io`;"
                 " 50 catalog tenants probed back to back at ~0.6s spacing on"
                 " 2026-09-20 with no 429 and no slowdown, and directory sweeps"
                 " at 1.0s from 2026-09-24 to 10-02 drew no 429 or 5xx. 6 boards"
                 " is 6s of queue, well inside a tick.",
    ),
    "ashby": ProviderPacing(
        provider="ashby",
        min_delay_seconds=1.0,
        max_boards_in_flight=4,
        host_scope=HostScope.SHARED,
        evidence="documented public posting API on the shared"
                 " `api.ashbyhq.com`; 18 catalog tenants probed on 2026-09-20"
                 " with no 429, and directory sweeps at 1.0s from 2026-09-24"
                 " to 10-02 drew no 429 or 5xx. Fewer boards than greenhouse"
                 " only because no published limit was found; the evidence is"
                 " of the same quality.",
    ),
    "lever": ProviderPacing(
        provider="lever",
        min_delay_seconds=1.0,
        max_boards_in_flight=3,
        host_scope=HostScope.SHARED,
        evidence="`api.lever.co/robots.txt` is `Allow: /` with `Crawl-delay:"
                 " 1`, which 1.0s meets exactly. Fewer boards than the others"
                 " because a Lever board PAGES (limit=50), so one"
                 " board is several requests rather than one — palantir alone"
                 " was 313 postings on 2026-09-20. Regions pace separately"
                 ", which the adapter's own `pacing_scope` handles.",
    ),
    "workable": ProviderPacing(
        provider="workable",
        min_delay_seconds=None,
        max_boards_in_flight=4,
        host_scope=HostScope.SHARED,
        evidence="one GET returns the whole board on the shared"
                 " `apply.workable.com`; robots is `Disallow:` with an empty"
                 " value and declares no Crawl-delay. It stays at the 2.0s"
                 " default while the other directory hosts run at 1.0s: from"
                 " 2026-09-24 16:36 to 09-25 03:46 it answered every directory"
                 " read with 429 while two processes did not share one pacer."
                 " Its limit is real and unmeasured; at 2.0s, no 429.",
    ),
    "atlassian": ProviderPacing(
        provider="atlassian",
        min_delay_seconds=None,
        max_boards_in_flight=1,
        host_scope=HostScope.SHARED,
        evidence="one company, one GET of the whole board (~1.9 MB JSON) on"
                 " `www.atlassian.com`; robots declares no Crawl-delay, and one"
                 " request per run needs no allowance beyond the 2.0s default.",
    ),
    "accenture": ProviderPacing(
        provider="accenture",
        min_delay_seconds=None,
        max_boards_in_flight=1,
        host_scope=HostScope.SHARED,
        evidence="one company, ~16 POSTs of 100 rows across four country queries"
                 " (1,533 postings in 32s on 2026-09-22, no 429); own-search"
                 " descriptions come inline. A country read from the Workday board"
                 " adds POSTs of 20 rows and one detail GET per kept posting, on"
                 " the same pacer.",
    ),
    "avature": ProviderPacing(
        provider="avature",
        min_delay_seconds=None,
        max_boards_in_flight=2,
        host_scope=HostScope.PER_TENANT,
        evidence="each tenant is served from its own host (jobs.ea.com), so pacing"
                 " and the breaker are per tenant. EA: 17 search pages of 20 (33s on"
                 " 2026-09-22, no 429) plus one detail page per KEPT posting."
                 " Synopsys serves 6 a page: 85 pages for 510.",
    ),
    "shopify": ProviderPacing(
        provider="shopify",
        min_delay_seconds=None,
        max_boards_in_flight=1,
        host_scope=HostScope.SHARED,
        evidence="one company's page: one listing request (600 KB, 114 postings,"
                 " 2026-09-27) plus one posting page per kept posting. No"
                 " Crawl-delay declared; the 2.0s default applies.",
    ),
    "successfactors": ProviderPacing(
        provider="successfactors",
        min_delay_seconds=None,
        max_boards_in_flight=2,
        host_scope=HostScope.PER_TENANT,
        evidence="each tenant is served from its own host (careers.ey.com), so pacing"
                 " and the breaker are per tenant. EY: 343 search pages of 25 at the"
                 " 2.0s default, plus one posting page per kept \"+N more\""
                 " row and per kept posting. No Crawl-delay declared.",
    ),
    "avature_tls": ProviderPacing(
        provider="avature_tls",
        min_delay_seconds=None,
        max_boards_in_flight=1,
        host_scope=HostScope.PER_TENANT,
        evidence="TSMC's portal on the consented TLS tier: 80 search"
                 " pages of 10 at 2.5 s, all 200, no challenge, 2026-09-26.",
    ),
    "deel": ProviderPacing(
        provider="deel",
        min_delay_seconds=None,
        max_boards_in_flight=2,
        host_scope=HostScope.SHARED,
        evidence="one host (jobs.deel.com) serves every tenant, so boards share the"
                 " pacer and the breaker. No crawl-delay declared;"
                 " the 2.0s default applies. One request per posting listed"
                 " (Klarna: 1 sitemap + 93 pages).",
    ),
    "radancy": ProviderPacing(
        provider="radancy",
        min_delay_seconds=None,
        max_boards_in_flight=2,
        host_scope=HostScope.PER_TENANT,
        evidence="each tenant is its own careers host; Arm's robots declares no"
                 " crawl-delay, so the 2.0s default applies. One posting request"
                 " per posting listed (Arm: 1 sitemap + 379 pages, ~13 min), which"
                 " is why the family's ceiling is 1,500 postings a scan.",
    ),
    "jibe": ProviderPacing(
        provider="jibe",
        min_delay_seconds=5.0,
        max_boards_in_flight=2,
        host_scope=HostScope.PER_TENANT,
        evidence="each tenant is its own careers host; both measured tenants' robots"
                 " declare `crawl-delay: 5`, so 5s between requests. GitHub 1 page,"
                 " Booking 2 pages of 100 (2026-09-22); descriptions inline.",
    ),
    "kpmg": ProviderPacing(
        provider="kpmg",
        min_delay_seconds=None,
        max_boards_in_flight=1,
        host_scope=HostScope.SHARED,
        evidence="one company's WordPress site: ~67 search pages of 12 cards"
                 " (133s at the 2.0s default, 2026-09-22, no 429) plus one posting"
                 " page per KEPT job. No Crawl-delay declared.",
    ),
    "tiktok": ProviderPacing(
        provider="tiktok",
        min_delay_seconds=None,
        max_boards_in_flight=1,
        host_scope=HostScope.SHARED,
        evidence="one company's API: 9 search pages of 500 (4275 postings,"
                 " 2026-09-26, no 429) plus one posting page per KEPT job. No"
                 " Crawl-delay declared; the 2.0s default applies.",
    ),
    "oracle": ProviderPacing(
        provider="oracle",
        min_delay_seconds=None,
        max_boards_in_flight=2,
        host_scope=HostScope.PER_TENANT,
        evidence="each tenant is its own Oracle Cloud deployment ({host}), so"
                 " pacing and the breaker are per tenant. A board is"
                 " TotalJobsCount/200 list pages (Fortinet: 5) plus one detail per"
                 " KEPT posting. ~60 requests at ~1.2s on 2026-09-22 with no 429.",
    ),
    "smartrecruiters": ProviderPacing(
        provider="smartrecruiters",
        min_delay_seconds=0.6,
        max_boards_in_flight=2,
        host_scope=HostScope.SHARED,
        evidence="the shared `careers.smartrecruiters.com` board host: a board is"
                 " its index, N group pages and a more-page walk per large group"
                 " (ServiceNow: 19 group pages + ~40 more-pages), then one"
                 " posting page per KEPT posting. Walked back to back at ~1.2s"
                 " spacing on 2026-09-21 (3 tenants, ~130 requests) with no 429."
                 " Two boards, not more: freehire measured SmartRecruiters"
                 " throttling a shared bucket at ~8 req/s. Directory sweeps at"
                 " 1.2s, then at 0.6s, from 2026-09-24 to 10-02 drew no 429 or"
                 " 5xx. 0.6s is ~1.7 req/s, under a quarter of the reported"
                 " throttle.",
    ),
    "smartrecruiters_api": ProviderPacing(
        provider="smartrecruiters_api",
        min_delay_seconds=None,
        max_boards_in_flight=1,
        host_scope=HostScope.SHARED,
        evidence="walled fallback route, consented companies only; the"
                 " 2.0s default is well under the ~8 req/s at which freehire saw"
                 " `api.smartrecruiters.com` answer 429 on a shared bucket.",
    ),
    "workday": ProviderPacing(
        provider="workday",
        min_delay_seconds=None,
        max_boards_in_flight=3,
        host_scope=HostScope.PER_TENANT,
        evidence="each tenant is its OWN deployment"
                 " (`{tenant}.wd{N}.myworkdayjobs.com`), so boards neither"
                 " share capacity nor share a failure. The adapter already"
                 " retries in-band on 403/429, which is the tenant's signal"
                 " and not the provider's.",
    ),
    "eightfold": ProviderPacing(
        provider="eightfold",
        min_delay_seconds=None,
        max_boards_in_flight=2,
        host_scope=HostScope.PER_TENANT,
        evidence="tenant-hosted (`explore.jobs.netflix.net`,"
                 " `paypal.eightfold.ai`). The number is a shape rather than a"
                 " measurement, kept low until a second tenant has been"
                 " measured.",
    ),
    "microsoft": ProviderPacing(
        provider="microsoft",
        min_delay_seconds=3.0,
        max_boards_in_flight=1,
        host_scope=HostScope.SHARED,
        evidence="single-tenant adapter carrying the fleet's most conservative"
                 " declared delay; one board exists, so depth is 1 by fact.",
    ),
    "amazon": ProviderPacing(
        provider="amazon",
        min_delay_seconds=None,
        max_boards_in_flight=1,
        host_scope=HostScope.SHARED,
        evidence="single-tenant, and the heaviest source in the fleet: a"
                 " location-sharded board with a 10,000-result window. One"
                 " company, so depth is 1 by fact rather than by caution.",
    ),
    "apple": ProviderPacing(
        provider="apple",
        min_delay_seconds=None,
        max_boards_in_flight=1,
        host_scope=HostScope.SHARED,
        evidence="single-tenant; hard-codes its own listing URL and carries no"
                 " board token, so there is nothing to queue.",
    ),
    "google": ProviderPacing(
        provider="google",
        min_delay_seconds=None,
        max_boards_in_flight=2,
        host_scope=HostScope.SHARED,
        evidence="google plus google-deepmind collect through this connector"
                 " on one host, so two boards is the whole population.",
    ),
}


def pacing_for(provider_key: str | None) -> ProviderPacing:
    """The policy for a provider, or the conservative default."""
    return PROVIDER_PACING.get(provider_key or "", DEFAULT)
