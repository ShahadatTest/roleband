"""Shared adapter machinery: polite async HTTP client, rate limiting, backoff,
and a schema-drift detector.

Every company adapter subclasses `BaseAdapter` and implements `fetch()` as an
async generator of `RawJob`. The base class owns the HTTP client so politeness
(min-delay pacing + exponential backoff on 429/503) is uniform across sources.

The primitives live in `tracker.platform`;
this module re-exports them so adapter code and tests keep one import path.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Awaitable, Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Any, ClassVar, Literal
from urllib.parse import urlsplit

import httpx

from tracker.config import get_settings
from tracker.connectors.extract.sitemap import SitemapSource
from tracker.connectors.runtime.context import RuntimeContext
from tracker.connectors.runtime.httpx_transport import HttpxTransport
from tracker.connectors.runtime.tiers import make_tier_client
from tracker.connectors.sdk import Capabilities
from tracker.platform.breaker import BreakerPool, CircuitBreaker, CircuitOpenError
from tracker.platform.clock import SourceClock
from tracker.platform.drift import DriftError, SchemaDriftDetector
from tracker.platform.http import DEFAULT_TIMEOUT, RetryPolicy, request_with_retry
from tracker.platform.paging import (
    MAX_PAGES_FLOOR,
    MAX_PAGES_HARD,
    QueryObservation,
    StopReason,
    paginate,
)
from tracker.platform.ratelimit import RateLimiter, RateLimiterPool
from tracker.platform.safe_fetch import BlockedDestination, check_url
from tracker.provider_pacing import HostScope, pacing_for
from tracker.schema import PostingPage, RawJob, SourceLocation, dedupe_key_for
from tracker.source_policy import CollectionAccess, CollectionPolicyDenied, collection_access
from tracker.taxonomy.countries import COUNTRIES, Country
from tracker.taxonomy.locations import (
    default_enabled_location_groups,
    location_group_covers,
    uncovered_groups,
)

#: What an adapter's `posted_at` is (`BaseAdapter.posted_date`).
PostedDate = Literal["published", "created", "none"]
#: How much of a board one listing reads (`BaseAdapter.listing_scope`).
ListingScope = Literal["board", "filtered", "windowed"]
#: Where a posting's text comes from (`BaseAdapter.detail`).
DetailMode = Literal["inline", "per_posting"]


def country_manifest(term_for: Callable[[Country], object]) -> dict[str, list]:
    """A coverage manifest over every country, built from one term rule.

    Safe to generate for every country only because every source using this
    filters **fail-closed**: a term the source does not recognise returns
    nothing, so a wrong entry under-collects rather than silently returning the
    whole board. A filter that ignores an unknown term fails the other way, and
    this is the property `scripts.check_location_coverage` exists to keep
    verifying.

    New countries also ship disabled, so a generated term only ever runs once
    someone deliberately tracks that country.
    """
    return {country.slug: [term_for(country)] for country in COUNTRIES}

logger = logging.getLogger(__name__)


def _context_key(context: Mapping) -> str:
    """Stable tuning key for a query described only by log context.

    Sorted `k=v` pairs, so the key does not depend on kwarg order, and `*` for a
    source with a single unnamed query. Adapters whose query
    object does not stringify stably pass `query_key=` explicitly instead —
    a key that changes shape between runs would silently start a new tuning row
    every night and learn nothing.
    """
    return "|".join(f"{k}={v}" for k, v in sorted(context.items())) or "*"

class RouteMoved(CollectionPolicyDenied):
    """The company's board now lives on another route of this family.

    Raised by a route-family adapter that DETECTED the move before collecting.
    A local decision, never evidence against the source: the run is
    `unattempted` (no evidence about the source, no closure), `collect_source` carries
    `route` out on the collection, and the pipeline records it through
    `company_store.record_route`, so the NEXT run scans the right route under
    that route's own policy (a walled route waits for the user's consent).
    """

    def __init__(self, provider_key: str, route: str, reason: str) -> None:
        super().__init__(CollectionAccess(provider_key, reason))
        self.route = route


__all__ = [
    "BaseAdapter",
    "RouteMoved",
    "BreakerPool",
    "CircuitBreaker",
    "CircuitOpenError",
    "DriftError",
    "RateLimiter",
    "RateLimiterPool",
    "BoardProbe",
    "SchemaDriftDetector",
    "TenantMap",
]


class TenantMap:
    """Multi-tenant board resolution shared by the board-token adapters.

    Resolution order: an explicit ``board_token`` (DB-registered company) wins,
    else the adapter's built-in module map, else the company slug itself. The
    per-adapter mapping dicts stay in their own modules (per-source vocabulary);
    only this resolution order is shared.
    """

    def __init__(self, mapping: Mapping[str, str]) -> None:
        self._mapping = mapping

    def resolve(self, company_slug: str, board_token: str | None) -> str:
        return board_token or self._mapping.get(company_slug, company_slug)


@dataclass(frozen=True)
class BoardProbe:
    """How to verify ONE tenant's board without going through the adapter.

    Declared on the adapter class so a token check and the adapter cannot
    disagree about what a board even is: a checker with its own table of board
    roots would verify the wrong endpoint, with nothing able to notice if a
    listing URL moved.

    Declaring one is also the definition of **multi-tenant** for verification
    purposes, and that is the load-bearing part. "This row has no stored
    `board_token`" is not the same question: `TenantMap.resolve` falls back to
    the module map and then to the slug, so a company with no stored token still
    scrapes an *effective* token that can rot exactly like a catalog token. A
    source that hard-codes its own listing URL declares no probe, and there is
    genuinely nothing there to check.
    """

    #: `{token}`-templated board root. Must be the route the adapter fetches.
    #: May also carry `{host}` when the family has regional deployments.
    jobs_url: str
    #: Resolves slug + stored token to the token the adapter would really use.
    #: The same object the adapter resolves through, never a second copy.
    tenants: TenantMap
    #: A route where the board states its own name, so a 200 from the WRONG
    #: tenant is detectable. `None` = this family declares no identity, which
    #: must be reported as unverified rather than quietly counted as verified.
    #: A board root that answers a bare array, or a key set without a name,
    #: does not name its tenant, so a wrong-but-live token there is
    #: undetectable here.
    identity_url: str | None = None
    #: JSON key holding that declared name.
    identity_key: str = "name"
    #: `BoardRegion` value -> API host, for a family with regional deployments.
    #: Empty for a single-host family. The adapter resolves its own host from
    #: this same mapping, so a token check cannot probe a host the adapter does
    #: not use, which would report a live board in another region DEAD,
    #: since a wrong region answers the same 404 as a wrong token.
    region_hosts: Mapping[str, str] = field(default_factory=dict)
    #: Does `jobs_url` return the whole board? A probe that asks for `limit=1`
    #: to keep the verification payload to one posting has a count that proves
    #: PRESENCE and not size. A check that prints "1 postings" for a board of
    #: fifty is reporting a number it never measured.
    counts_whole_board: bool = True
    #: For a family some of whose tenants state NO total (a shape declared in
    #: the token, such as a `|openroles` suffix): given the token and the page, the rows
    #: the page shows for such a tenant, else None (the token is counted and
    #: `read_count` applies). Reported as a floor, never as the board's size.
    uncounted_rows: Callable[[str, str], int | None] | None = None
    #: For a family whose token is COMPOSITE (`host|domain|shape`),
    #: which a `{token}` template cannot take apart: the family's own parser
    #: builds the route, so adapter and checker still cannot disagree.
    tenant_url: Callable[[str], str] | None = None
    #: The verb the board route answers, when a GET is not it. A route that
    #: answers 400 to a GET would make a checker that can only GET report every
    #: live board on it DEAD, and an adapter whose route cannot be checked at
    #: all is how dead tokens survive.
    #: `probe_body` is sent with it, asking for the smallest page the board
    #: will serve.
    method: str = "GET"
    probe_body: Mapping[str, object] | None = None
    #: How `probe_body` is encoded: JSON, or an HTML form. It must be what the
    #: adapter sends, or
    #: the probe tests a request the adapter never makes.
    probe_encoding: Literal["json", "form"] = "json"
    #: Headers the route requires. A route that answers 400 without a header
    #: its own site sends would read DEAD to a checker that leaves it out.
    probe_headers: Mapping[str, str] | None = None
    #: For a board that answers HTML rather than JSON (a career page): read
    #: the posting count, and the name the board states,
    #: from the page body. None = the JSON readers apply.
    read_count: Callable[[str], int | None] | None = None
    read_identity: Callable[[str], str | None] | None = None
    #: Multi-document inventory; collection and verification share this declaration.
    sitemap: Callable[[str], SitemapSource] | None = None

    def url_for(self, token: str, region: str | None = None) -> str:
        """The board route for one tenant, region included.

        One method rather than two format calls: the adapter and the token
        checker must agree on the host, and the only way to guarantee that is
        for neither to build it.
        """
        if self.tenant_url is not None:
            return self.tenant_url(token)
        host = self.region_hosts.get(region or "") if self.region_hosts else None
        if host is None and self.region_hosts:
            # Unknown/absent region on a regional family: fall back to the
            # first declared host, which is the global one by convention.
            host = next(iter(self.region_hosts.values()))
        return self.jobs_url.format(token=token, host=host or "")


@dataclass(frozen=True)
class ReadPosition:
    """Where a listing read that was cut short can continue.

    Written by an adapter whose listing can resume (`BaseAdapter.resume_point`),
    kept by the directory scan for a read our host cut (asleep or offline), and
    handed back on the next read (`BaseAdapter.resume_from`). `at` is the
    adapter's own and is checked against the board before it is trusted: a page
    number alone is no address, since pages shift as postings come and go.
    `listed` names the postings (req ids) the read held up to `at`, and
    `unread_by_choice` counts what it left unread there, so a resumed read
    merges them with its own. Ids, not a count: a posting listed under two
    places on either side of the cut is one posting, and boards that list a
    posting under several cities are common.
    """

    at: Mapping[str, object]
    listed: frozenset[str] = frozenset()
    unread_by_choice: int = 0


def set_places(job: RawJob, places: list[str]) -> None:
    """A posting's places, in its locations and in its source facts alike, the
    first primary. A source that keeps no facts has its locations."""
    job.locations = places
    if job.source_facts is not None:
        job.source_facts = replace(job.source_facts, locations=[
            SourceLocation(label=label, is_primary=i == 0) for i, label in enumerate(places)
        ])


def require_tenant_host(url: str, host: str) -> None:
    """Refuse `url` unless it is on `host` itself.

    For families known by the host their careers page is served from, which a
    pasted page can choose (`ats_detect.detect_page`): such an adapter is
    `public_only`, and this is its `validate_destination`.
    """
    if (urlsplit(check_url(url)).hostname or "") != host.lower():
        raise BlockedDestination("URL is outside the tenant's host")


class BaseAdapter(ABC):
    """One source's listing reader: a subclass implements `fetch()`.

    A new adapter fetches through `self.context.fetch` (or `self.context.stream`
    for a body too large to buffer), which returns the SDK's `FetchResponse`,
    and declares the transport abilities it needs in `required_capabilities`.
    `self.get` and `self.post` return an `httpx.Response` and serve only the
    adapters that already call them; new code does not add to them.
    """

    #: Dynamic sitemap destinations require pinned public connections and hop checks.
    public_only = False

    def validate_destination(self, url: str) -> None:
        """Overridden by adapters that restrict dynamic URLs to a tenant."""
        raise NotImplementedError("public-only adapters must validate their destinations")

    #: adapter identifier used in logs / drift alerts
    name: str = "base"
    #: What feeds `RawJob.posted_at`: the employer's `published`
    #: date, the posting's `created` time, or `none` when this source states
    #: no date. Never an update time: an update moves on every edit, so it
    #: would re-date the posting each time and the listing age would reset.
    #: Declared on EVERY registered adapter's own class, not inherited
    #: (`tests/contracts/test_posted_date_kind.py`), so a fallback onto an
    #: update field cannot arrive without someone writing down what it is.
    posted_date: ClassVar[PostedDate]
    #: default per-request pacing; overridable per adapter
    min_delay: float | None = None
    #: Companies on the same backend share this run-scoped pacing bucket.
    rate_limit_scope: str | None = None
    #: How to verify one tenant's board root, for multi-tenant families only.
    #: `None` = this source hard-codes its own listing URL, so it carries no
    #: token that can rot. See `BoardProbe`; read by
    #: `scripts.check_catalog_tokens`, which must never re-derive a board root.
    board_probe: BoardProbe | None = None
    #: Adapters that are ROUTES of one family: the same tenants and
    #: posting ids reached two ways, so a company may move between them and
    #: keep its jobs. `None` = this adapter is its own family. Read by
    #: `route_family_of`; `company_store.record_route` refuses a move across
    #: families.
    route_family: str | None = None
    #: Per-query page BACKSTOP for non-authoritative discovery. None = connector
    #: has no paged request loop (for example one board-feed GET), so discovery
    #: reads that one response normally.
    #:
    #: A backstop, not the working bound: `_page_reaches_frontier` normally ends a
    #: probe as soon as it pages into rows we already have, so depth follows how
    #: much the board actually moved. This number only binds when the frontier is
    #: never reached: a first run against an empty database, or a burst larger
    #: than the allowance. As the only bound, it would stop every discovery
    #: query at `ceiling` without ever proving the probe had read back past the
    #: newest posting we already hold.
    discovery_max_pages: int | None = None
    #: Does this source serve its listing newest-first? Only then can one
    #: recognized row prove everything below it is older, which is the whole
    #: basis of the frontier stop. Off by default: a source whose order is
    #: unknown must read its backstop rather than stop above unseen rows.
    discovery_frontier_ordered: bool = False
    #: Coverage manifest: location-group slug -> the query terms this source
    #: must run to cover it. `None` = the source is not location-narrowed (one
    #: board feed returns every region), so it covers everything trivially.
    #:
    #: The keys are a CLAIM, checked by `tests/contracts/test_location_coverage.py`
    #: and by `location_gaps()` at run time. Declare the group a term actually
    #: returns, never the one it is named after: a `location=London, UK` term
    #: covers `london`, NOT `uk`. Over-claiming here is the failure this manifest
    #: exists to prevent — an unasked region yields no error, no drift, and no
    #: anomaly, so it is indistinguishable from a region with no open roles.
    location_queries: Mapping[str, Sequence] | None = None
    #: How much of the board one listing reads. The fact closure rests on,
    #: declared so it is readable without reading the adapter's code;
    #: collection does not read it.
    #:
    #: `board`: the whole board, however it is paged or grouped. `filtered`:
    #: only the slice its query terms select (`location_queries`), complete
    #: over that filter and only because each filter fails closed
    #: (`country_manifest`). `windowed`: filtered, and a query can saturate the
    #: source's result window, so `expand_saturated` refines it and the listing
    #: is complete only when an audit shows the leaves cover the parent.
    #: `tests/contracts/test_capability_markers.py` names a
    #: class whose code reads a slice while it declares `board`.
    listing_scope: ClassVar[ListingScope] = "board"
    #: Where a posting's text comes from: `inline` in its listing row, or
    #: `per_posting`, one request per kept posting in `hydrate()`. Declared if
    #: and only if the class overrides `hydrate` (same contract test).
    detail: ClassVar[DetailMode] = "inline"
    #: Whether `hydrate()` reads a posting's text from the posting alone (its
    #: `url` or `req_id`), with nothing its listing row carried. The description
    #: backfill rebuilds a stored posting from only those, so it asks only
    #: these adapters. False for `inline` (nothing to fetch), for a
    #: hydrate that needs the listing's `detail_payload` and cannot rebuild it
    #: (unless it overrides `payload_from_posting`, for example to rebuild a
    #: tenant path from the posting url), and for one that reads no text (a
    #: posting page that carries only pay).
    #: Held to the code by `tests/contracts/test_capability_markers.py`.
    text_from_posting: ClassVar[bool] = False
    #: The transport abilities this adapter needs. Building `self.context`
    #: negotiates them against its transport, so an adapter that needs what
    #: the transport cannot do raises `CapabilityError` before any request is
    #: sent, instead of failing mid-listing. Declare the minimum the code uses:
    #: a requirement it does not use refuses a transport that would serve it.
    #: None declares nothing, and nothing is checked.
    required_capabilities: ClassVar[Capabilities | None] = None

    def __init__(
        self,
        company_slug: str,
        board_token: str | None = None,
        board_region: str | None = None,
        limiter_pool: RateLimiterPool | None = None,
        breaker_pool: BreakerPool | None = None,
        deadline: float | SourceClock | None = None,
        page_budgets: Mapping[str, int] | None = None,
        discovery: bool = False,
        location_groups: Iterable[str] | None = None,
        known_keys: Iterable[str] | None = None,
        consent: str | None = None,
    ) -> None:
        self.company = company_slug
        #: optional board token/name for DB-registered multi-tenant companies;
        #: when None, adapters fall back to their module map or the slug.
        self.board_token = board_token
        #: Regional deployment (`schema.BoardRegion` value) for a multi-region
        #: family, else None. Set before the pacer below because the scope
        #: depends on it: two regions are two hosts, and pacing them as one
        #: bucket would halve each one's allowance while a breaker trip on one
        #: silenced the other.
        self.board_region = board_region
        #: The user's consent fingerprint for a walled company, read from the
        #: company's row by whoever builds the adapter. None for every unwalled
        #: source, and for a walled one it means "refuse": this adapter never
        #: collects a walled company the user did not consent to, whoever
        #: built it.
        self.collection_consent: str | None = consent
        self.settings = get_settings()
        self.drift = SchemaDriftDetector(f"{self.name}:{company_slug}")
        self._completed_rows: Callable[[], Iterable[RawJob]] | None = None
        #: True once OUR page ceiling cut a listing that was still serving items
        #: (`paged_listing`). A bound we imposed, kept off the drift channel so
        #: it can never read as source pathology; the pipeline maps it to
        #: `SourceOutcome.TRUNCATED` (not a pathology, closure-suppressing).
        self.truncated = False
        #: Postings left unread because their place group was not wanted
        #: (`wanted_place`). Always 0 where the hook is unset.
        self.unread_by_choice = 0
        #: Learned page ceilings, `query_key -> max_pages`.
        #: Absent key = fall back to the adapter's hand-written constant, which
        #: is therefore a *seed* rather than the standing bound. Empty/None here
        #: is the standalone case (CLI, tests): every adapter must still work
        #: with no tuning at all.
        self._page_budgets: Mapping[str, int] = page_budgets or {}
        self._discovery = discovery
        #: The user's tracked location groups, or None when nobody narrowed the
        #: scope (CLI, smoke, tests). None means "run the default scope", so an
        #: adapter keeps working standalone.
        self._enabled_locations: frozenset[str] | None = (
            frozenset(location_groups) if location_groups is not None else None
        )
        #: Dedupe keys already open in our records, for the discovery frontier
        #: stop. None = caller supplied none (CLI, smoke, tests), so the probe
        #: falls back to its page backstop.
        self._known_keys: frozenset[str] | None = (
            frozenset(known_keys) if known_keys is not None else None
        )
        #: One entry per query paged this run, for the tuning pass to learn from.
        self.query_observations: list[QueryObservation] = []
        # Three sources, most specific first: the adapter's own
        # declared delay, then the provider's standing policy, then the global
        # default. The class attribute stays the override because an adapter can
        # know something the table cannot: a delay that is a property of one
        # connector, not of a family.
        delay = self.pacing_delay()
        scope = self.pacing_scope()
        self._limiter = (
            limiter_pool.get(scope, delay)
            if limiter_pool is not None
            else RateLimiter(delay)
        )
        # The breaker keys off the SAME scope as the pacer: a
        # backend hosting several tracked companies is one backend, so pressure
        # it applies to one company must count against all of them. No pool =>
        # no breaker (standalone/CLI use), rather than a private one per adapter
        # that could never see a streak.
        self._breaker: CircuitBreaker | None = (
            breaker_pool.get(
                scope,
                self.settings.scraper_breaker_threshold,
                cooldown_seconds=self.settings.scraper_breaker_cooldown_seconds,
                # `blocked_threshold` keeps its default of two consecutive
                # identically-refused requests: counted per request, it needs no
                # arithmetic against the retry budget.
            )
            if breaker_pool is not None
            else None
        )
        #: monotonic timestamp this source's collection must stop by, or None.
        self._deadline = deadline
        self._client: httpx.AsyncClient | None = None

    @classmethod
    def pacing_delay(cls) -> float:
        """Seconds between two requests to this family's backend: the adapter's
        own `min_delay`, else its provider's standing policy, else the global
        default. Anything else that reads a family's boards (`board_relocate`)
        paces by the same answer."""
        if cls.min_delay is not None:
            return cls.min_delay
        policy = pacing_for(cls.name).min_delay_seconds
        return policy if policy is not None else get_settings().scraper_min_delay_seconds

    def pacing_scope(self) -> str:
        """The rate-limit AND circuit-breaker bucket this instance shares.

        One key for both, deliberately: a backend hosting several
        tracked companies is one backend, so pressure it applies to one company
        must count against all of them.

        Overridable because it is not always a property of the CLASS. A family
        with regional deployments serves each region from its own host, with its
        own capacity and its own failure modes, so two regional hosts must not
        share a pacer (each region would get half the allowance it is entitled
        to) nor a breaker (a regional outage would open the circuit on a host
        that is answering fine).

        **A tenant-hosted family is that same case taken to its limit**. Such a
        family serves every tenant from the tenant's OWN deployment, so "one
        backend" is one TENANT, not the family: `provider_pacing` says which
        families those are and the bucket carries the tenant. One shared bucket
        would give N tenants each an Nth of an allowance none of them share, and
        one tenant's outage would open the circuit on hosts answering fine.
        """
        if self.rate_limit_scope:
            return self.rate_limit_scope
        if pacing_for(self.name).host_scope is HostScope.PER_TENANT:
            # The stored token identifies the deployment for exactly the
            # families this applies to (`host|site`, `host|domain`). A company
            # with no token falls back to its slug, which is still per-tenant
            # and never collapses two tenants into one bucket.
            return f"{self.name}:{self.board_token or self.company}"
        return self.name

    # -- Set by callers after build_adapter -------------------------------- #
    # Each default suits a standalone run (CLI, smoke, tests). Only the caller
    # named on a hook assigns it, on the adapter it built.

    #: Places already read for this company's open postings, by req_id
    #: (`repo.load_known_places`). Set by the collection path
    #: (`workflows/collection.py`); empty everywhere else, which only means
    #: "read the posting page".
    known_places: Mapping[str, Sequence[str]] = {}

    #: "Passes every scope axis but location", set by the collection path
    #: (`workflows/collection.py`). None everywhere else (smoke, tests), where
    #: every posting is worth placing.
    place_gate: Callable[[RawJob], bool] | None = None

    #: "Is a posting at this place label one the caller could keep?", set ONLY
    #: by the background directory scan (`workflows/directory_sweep.py`), which
    #: asks whether a board has roles for the radar and closes nothing. An
    #: adapter whose listing is grouped by place may then leave an unwanted
    #: group's further pages unread (`unread_by_choice`); such a listing is
    #: never closure evidence, which is why the collection path never sets
    #: this. None everywhere else.
    wanted_place: Callable[[str], bool] | None = None

    #: A position an earlier read of this board reached, to continue from; set
    #: ONLY by the directory scan (`workflows/directory_sweep.py`), for a read
    #: our host cut. A read stitched from two moments is no closure evidence (a
    #: posting that moved from the unread part to the read part between them
    #: would be missing), which is why the collection path never sets this.
    #: None everywhere else.
    resume_from: ReadPosition | None = None

    #: Retries per request when the caller has less time than a run, set by
    #: the posting page reads (`workflows/posting_pages.py`): someone is waiting
    #: on the page. None = the settings' budget.
    max_retries: int | None = None

    # -- Kept by the adapter during a read, for its caller ------------------ #

    #: The furthest position this read has reached, kept current by an adapter
    #: that can resume; None for every adapter that cannot.
    resume_point: ReadPosition | None = None
    #: True once this read has continued from `resume_from`; False when it read
    #: the board from its start, `resume_from` given or not.
    resumed: bool = False

    # -- Places ------------------------------------------------------------ #

    def place_wanted(self, job: RawJob) -> bool:
        """Whether a posting whose place is only on its detail page is worth a
        request to name it. A posting the role gate drops is dropped wherever it
        is, and reading every such page at the pacing interval can keep a large
        board from ever finishing a listing."""
        return self.place_gate is None or self.place_gate(job)

    def keep_held_places(self, job: RawJob) -> None:
        """Keep the places a page read named, for a scan that did not read it.

        A card names a posting's places only as well as the board's listing
        does, and for several sources the posting's own page names more. A
        rescan inside `description_refresh_days` does not read that page, so
        the card's labels alone would withdraw what the page said. Locations
        fail closed, so the posting then drops out of a scope its page place
        matched, until something reads the page again.

        Held places first, then any the card adds, compared case-insensitively
        because boards change the case of their labels between runs. A page
        read later in the same scan still replaces the set: this is what a scan
        that did not read one falls back to. The observation
        (`source_facts.locations`) keeps recording only what the listing said.
        """
        held = self.known_places.get(job.req_id)
        if not held:
            return
        out = list(held)
        seen = {place.casefold() for place in out}
        for place in job.locations:
            if place.casefold() not in seen:
                seen.add(place.casefold())
                out.append(place)
        job.locations = out

    async def place_from_page(
        self,
        job: RawJob,
        read: Callable[[RawJob], Awaitable[list[str] | None]],
        *,
        clear_listed_place: bool = False,
    ) -> None:
        """Name a posting's places from its own page, before scope reads them.

        For a row the listing places partly or not at all ("+N more",
        "2 Locations", "Multiple Locations"). Scope runs before hydration and
        locations fail closed, so this is the only point at which the page can
        still decide whether the row is shown. One sequence for every source:

        - only a posting the scope's role gate admits (`place_wanted`);
        - places read within the refresh window are reused, no request
          (`known_places`);
        - otherwise `read` fetches the page, keeps what else it states for
          hydration, and returns its places: [] when it names none, None when
          it could not be read (`read` records why; the evidence is the
          source's);
        - with no place found, the listed one stays, unless it names no place
          at all (`clear_listed_place`: "Multiple Locations") and the page
          was read and named none. A page that could not be read says nothing
          about the posting, so the row stays as listed.
        """
        if not self.place_wanted(job):
            return
        known = self.known_places.get(job.req_id)
        places = list(known) if known else await read(job)
        if places:
            set_places(job, places)
        elif places is not None and clear_listed_place:
            set_places(job, [])

    # -- HTTP plumbing ----------------------------------------------------- #

    def _retry_policy(self) -> RetryPolicy:
        budget = self.settings.scraper_max_retries if self.max_retries is None else self.max_retries
        return RetryPolicy(max_retries=budget)

    @property
    def access(self) -> CollectionAccess:
        return collection_access(
            self.name, company=self.company, settings=self.settings, consent=self.collection_consent,
        )

    def default_headers(self) -> dict[str, str]:
        return {
            "User-Agent": self.settings.scraper_user_agent,
            "Accept": "application/json, text/html;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }

    async def __aenter__(self) -> BaseAdapter:
        access = self.access
        access.require()
        # The tier comes from the policy answer and nowhere else:
        # identified unless this company is walled and its user consented.
        # The proxy URL is read here rather than inside the runtime: settings
        # are the adapter's to resolve, and a tier that needs one refuses
        # without it (`unavailable_reason`) rather than fetching unproxied.
        proxy = self.settings.scraper_proxy_url
        self._client = make_tier_client(
            access,
            headers=self.default_headers(),
            timeout=DEFAULT_TIMEOUT,
            proxy_url=proxy.get_secret_value() if proxy is not None else None,
            public_only=self.public_only,
        )
        return self

    async def __aexit__(self, *exc: object) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    @property
    def client(self) -> httpx.AsyncClient:
        # Also guards direct fetch/hydrate and streaming paths, which
        # may run over an already-created or injected client.
        self.access.require()
        if self._client is None:
            raise RuntimeError("Adapter must be used as an async context manager")
        return self._client

    async def request(self, method: str, url: str, **kwargs: object) -> httpx.Response:
        """Paced request with exponential backoff on 429/5xx."""
        return await request_with_retry(
            self.client,
            method,
            url,
            retry=self._retry_policy(),
            limiter=self._limiter,
            breaker=self._breaker,
            deadline=self._deadline,
            log_name=self.name,
            **kwargs,
        )

    async def get(self, url: str, **kwargs: object) -> httpx.Response:
        return await self.request("GET", url, **kwargs)

    async def post(self, url: str, **kwargs: object) -> httpx.Response:
        return await self.request("POST", url, **kwargs)

    # -- SDK bridge -------------------------------------------------------- #
    @property
    def context(self) -> RuntimeContext:
        """SDK `ConnectorContext` over this adapter's transport.

        The client is reached through a callable and the context is rebuilt per
        access rather than cached, so both the real client created in
        `__aenter__` and the contract suite's post-construction swap of
        `_client`/`_limiter` are always observed. Caching here would freeze
        whichever transport happened to exist at first access. Adapters on the
        SDK use this; the others call `self.get`/`self.post`. Each build
        negotiates `required_capabilities` against the transport.
        """
        return RuntimeContext(
            transport=HttpxTransport(
                lambda: self.client,
                limiter=self._limiter,
                breaker=self._breaker,
                deadline=self._deadline,
                retry=self._retry_policy(),
                log_name=self.name,
                access=self.access,
                validate_url=self.validate_destination if self.public_only else None,
            ),
            drift=self.drift,
            limiter=self._limiter,
            required_capabilities=self.required_capabilities,
            connector_name=self.name,
            access=self.access,
        )

    # -- Shared listing mechanics ------------------------------------------ #

    #: Whether this board STATES how many postings it has.
    #:
    #: It decides what a MISSING total means, which is the one thing adapters
    #: cannot be left to answer for themselves. For a board documented to
    #: declare a total, a run that finds none has met a board whose shape
    #: changed, and a listing we cannot read as documented is not closure evidence.
    #: A board that never declares one is not in doubt: it ends on an empty
    #: page, and that IS the evidence.
    #:
    #: False is the safe default only because an adapter that leaves it False
    #: while passing a declared total is named by
    #: `tests/contracts/test_listing_completeness.py`.
    declares_total: bool = False

    def close_listing(
        self, *, declared: int | None, unique: int, field: str = "total", **context: object
    ) -> None:
        """End a counted listing with the completeness verdict it earned.

        `listing_complete` defaults to TRUE and only an explicit invalidation
        takes it away (`platform/drift.py`), so an adapter that ends a listing
        by saying nothing keeps closure authority — the right to conclude that
        a posting absent from this run is gone. Both ways of failing to earn it
        live here rather than in each adapter, so every adapter gives the same
        answer to the same question:

        * **The declared total is gone** (`declares_total`). The board changed
          shape under us. Not guarded by `truncated`: our ceiling explains why
          we stopped reading, never why the board stopped counting.
        * **Fewer unique ids than declared**. The pages we read do
          not add up to the board — never a complete listing. Guarded by
          `truncated`, which is our bound and is never evidence against a
          source. The shortfall is a COUNT of unread rows, not an unknown
          slice, so it is recorded as lost records: closure is
          suppressed either way, and only a shortfall above the record-drop
          ratio reads as a pathology. A board that loses one posting during a
          long walk is a moving board, not a broken one.

        `field` names the board's own count in the drift note, so the alert
        still says which number went missing.
        """
        if declared is None:
            if self.declares_total:
                self.drift.invalidate_listing(f"the board stated no {field}", **context)
            return
        if not self.truncated and unique < declared:
            self.drift.records_unaccounted(
                declared - unique,
                f"fewer unique postings than {field}",
                declared=declared,
                unique=unique,
                **context,
            )

    async def paged_listing(
        self,
        fetch_page: Callable[[int, Callable[[], None]], Awaitable[Sequence]],
        *,
        max_pages: int,
        query_key: str | None = None,
        declared_total: int | Callable[[], int | None] | None = None,
        page_size: int | None = None,
        start: int = 0,
        item_key: Callable[[Any], str | None] | None = None,
        **context: object,
    ) -> AsyncIterator:
        """Drive ``fetch_page`` through ``platform.paging.paginate`` with the
        bookkeeping every paginating adapter shares.

        ``fetch_page(page_index, stop)`` returns one page of raw items; it
        calls ``stop()`` to mark a deliberate end (total reached, aborted on
        drift). When all ``max_pages`` pages served items and no stop condition
        hit (``while/for ... else`` semantics), the listing was cut by OUR
        ceiling, so it is recorded as ``self.truncated``,
        never as drift: drift is the source's own misbehavior, and routing a
        bound we chose through it would read as source pathology every run, the
        same category error as counting ``capped``/``bounded`` against a source.
        ``context`` names the query in the log line (e.g. the location term).

        ``max_pages`` is a *seed*: when the binding has a learned bound for
        ``query_key`` that value wins. Either way the run is
        recorded in ``query_observations`` so the next tuning pass can move the
        bound on evidence — including the fact that it fired.

        ``start`` is the first page index asked for: a read continuing from a
        position an earlier read reached (`resume_from`). The ceiling
        stays a bound on the page INDEX, so a resumed read stops where a fresh
        one would.

        ``item_key`` names the requisition of a page item that is not a
        `RawJob`, the same id the adapter's `RawJob` for that item carries as
        ``req_id``, so a discovery probe can recognize the rows we already hold
        (`_page_reaches_frontier`). Without it, only `RawJob` items are keyed.
        """
        key = query_key if query_key is not None else _context_key(context)
        ceiling = self.page_budget(key, max_pages)
        stopped = False
        frontier = False
        calls = 0
        yielded = 0
        last_page_had_items = False

        def stop() -> None:
            nonlocal stopped
            stopped = True

        async def page(index: int) -> Sequence:
            nonlocal calls, last_page_had_items, frontier
            if stopped:
                return ()
            calls += 1
            items = await fetch_page(index, stop)
            last_page_had_items = bool(items)
            if items and self._page_reaches_frontier(items, item_key):
                # Newest-first listing, and this page holds a row we already
                # have: everything newer is behind us. Paging on would spend
                # requests re-reading the past. Depth therefore follows how much
                # the board actually moved, instead of one constant for a quiet
                # night and a hiring burst alike.
                frontier = True
                stop()
            return items

        async for item in paginate(page, max_pages=ceiling, start=start):
            yielded += 1
            yield item
        cut_by_ceiling = not stopped and calls == ceiling - start and last_page_had_items
        if cut_by_ceiling or frontier:
            # Both are OUR stop over a listing that was still serving, so the
            # page count is censored either way and the run must not claim to
            # have enumerated the board. They differ in what they MEAN: a
            # ceiling hit is a bound that ran out (warn — it may be too low), a
            # frontier stop is the probe finishing its job (debug).
            self.truncated = True
        if cut_by_ceiling:
            logger.warning(
                "%s: page ceiling cut a still-serving listing (max_pages=%s %s)",
                self.name,
                ceiling,
                context or "",
            )
        elif frontier:
            logger.debug(
                "%s: reached the known frontier after %s page(s) %s",
                self.name,
                calls,
                context or "",
            )
        self.query_observations.append(
            QueryObservation(
                query_key=key,
                pages_used=calls,
                items=yielded,
                stop_reason=(
                    StopReason.CEILING
                    if cut_by_ceiling
                    else StopReason.FRONTIER
                    if frontier
                    else StopReason.STOPPED
                    if stopped
                    else StopReason.EXHAUSTED
                ),
                ceiling=ceiling,
                # Callable form because a source declares its total on the first
                # page, not at the call site — the adapter hands over a reader
                # rather than a value it does not have yet.
                declared_total=(
                    declared_total() if callable(declared_total) else declared_total
                ),
                page_size=page_size,
            )
        )

    def _page_reaches_frontier(
        self, items: Sequence, item_key: Callable[[Any], str | None] | None = None
    ) -> bool:
        """This page contains a row we already hold, so we have caught up.

        On a newest-first listing one recognized row is the boundary: everything
        below it was posted earlier, so it has already been through a scan. That
        is why ANY match ends the probe and not ALL of them: we keep only the
        in-scope slice, often a small share of a board's rows, so a page is
        essentially never *entirely* known and an all-must-match rule would let
        every query run to its backstop.

        Three guards, each load-bearing:
        * `_discovery` — reconcile is the only closure authority and must read
          the whole listing to keep it.
        * `discovery_frontier_ordered` — the inference is only valid when the
          source really does serve newest first. A source that reorders would
          have us stop above rows we have never seen.
        * a supplied key set — with none (CLI, smoke, tests) there is no
          frontier to reach and the backstop applies.

        A raw item is keyed by `item_key` under this company, exactly as its
        `RawJob` would be; an item with no key is never a match, since no claim
        is safer than a guessed one.
        """
        if not (self._discovery and self.discovery_frontier_ordered):
            return False
        if not self._known_keys or not items:
            return False
        for item in items:
            if item_key is not None:
                req_id = item_key(item)
                key = dedupe_key_for(self.company, req_id) if req_id else None
            else:
                method = getattr(item, "dedupe_key", None)
                key = method() if callable(method) else None
            if key is not None and key in self._known_keys:
                return True
        return False

    def observe_unusable(self, req_id: str, message: str, **context: object) -> None:
        """This listing row named a requisition but could not become a posting.

        The row is skipped either way; what differs is the claim we make about
        the board. With the id in hand the listing is still complete — that req
        is present, we simply cannot refresh it this run — so this must not go
        through `drift.drop_record()`, which says a row was *lost* and closes
        the closure gate for the whole source. Call it only when
        `req_id` is non-empty; a row that identifies nothing is a real drop.
        """
        self.drift.observe_present(
            dedupe_key_for(self.company, req_id), message, req=req_id, **context
        )

    def drain_completed(self) -> Iterable[RawJob]:
        """Transfer buffered, already-read rows after enumeration was interrupted.

        No fetching or enrichment here. Clean scans clear the buffer before
        yielding; the collector drains only work that never reached its iterator.
        """
        reader, self._completed_rows = self._completed_rows, None
        return reader() if reader is not None else ()

    def page_budget(self, query_key: str, seed: int) -> int:
        """The page ceiling in force for one query: learned if we have one.

        A learned bound is already clamped when it is written; clamping again on
        read means a row hand-edited in the DB still cannot push an adapter past
        the published maximum.
        """
        if self._discovery and self.discovery_max_pages is not None:
            # Per-query, not a global item cap, so a location-narrowed source
            # inspects every configured location instead of spending the whole probe on the
            # first location's newest pages.
            return int(max(1, min(seed, self.discovery_max_pages)))
        learned = self._page_budgets.get(query_key)
        if learned is None:
            return seed
        return int(max(MAX_PAGES_FLOOR, min(MAX_PAGES_HARD, learned)))

    def planned_location_items(self) -> list[tuple[str, Sequence]]:
        """`(group, terms)` manifest entries to run for the tracked scope.

        An entry is run when it is tracked, when it is an ancestor of a tracked
        group (the `united_states` query is how New York gets covered), or when
        it is a descendant of one (a `london` query is partial coverage of a
        tracked `uk` — worth running, and separately reported by
        `location_gaps()` as the incomplete claim it is).
        """
        manifest = self.location_queries
        if manifest is None:
            return []
        # No scope supplied (CLI, smoke, tests) falls back to the SHIPPED
        # DEFAULTS, not to the whole manifest. Manifests are generated per
        # country, so "everything declared" is a query per country, and a
        # standalone run would issue every one of them. The default scope is
        # what an unconfigured run should mean.
        wanted = self._enabled_locations
        if wanted is None:
            wanted = frozenset(default_enabled_location_groups())
        return [
            (declared, terms)
            for declared, terms in manifest.items()
            if any(
                location_group_covers(declared, w) or location_group_covers(w, declared)
                for w in wanted
            )
        ]

    def planned_location_terms(self) -> list:
        """`planned_location_items()` flattened — the query vocabulary to iterate."""
        return [term for _, terms in self.planned_location_items() for term in terms]

    def location_gaps(self) -> list[str]:
        """Tracked groups this source cannot ask about, sorted.

        A gap is a question never sent, so it leaves no trace in the response:
        no error, no drift, no anomaly. Returning it here is the only way the
        run can say "you asked to track canada and this source was never queried
        for it" instead of showing you an empty region and letting you conclude
        there are no roles.
        """
        manifest = self.location_queries
        if manifest is None or self._enabled_locations is None:
            return []
        return sorted(uncovered_groups(manifest, self._enabled_locations))

    async def scan_location_queries(
        self,
        queries: Iterable,
        fetch_query: Callable[..., AsyncIterator[RawJob]],
        *,
        empty_message: str = "parsed zero postings (schema/endpoint drift?)",
        seen: set[str] | None = None,
    ) -> AsyncIterator[RawJob]:
        """Shared outer mechanics of location-narrowed listing scans: iterate the per-source query vocabulary,
        share one req-id ``seen`` set across queries so cross-query duplicates
        collapse, and record listing drift when the whole scan parsed nothing.

        ``fetch_query(query, seen)`` pages one narrowed query; it owns adding
        yielded req_ids to ``seen``. Passing ``seen`` in lets a caller inspect
        the union afterwards, for example to audit it against the parent query a
        refined vocabulary replaced.
        """
        seen = seen if seen is not None else set()
        for query in queries:
            async for job in fetch_query(query, seen):
                yield job
        if not seen:
            self.drift.invalidate_listing(empty_message)

    # -- Contract ---------------------------------------------------------- #
    @abstractmethod
    def fetch(self) -> AsyncIterator[RawJob]:
        """Yield `RawJob`s for this company. Implemented as `async def ... yield`.

        The list pass should be cheap and may omit the full description — sources
        whose descriptions require a per-job detail call populate them lazily in
        `hydrate()`, which the pipeline invokes only for jobs that pass filtering.
        """
        raise NotImplementedError

    async def hydrate(self, job: RawJob) -> None:
        """Optionally enrich a single kept job in place (e.g. fetch its full
        description via a detail endpoint). Default: no-op (description already
        inline). A class that overrides it declares `detail = "per_posting"`."""
        return None

    def payload_from_posting(self, job: RawJob) -> dict | None:
        """What this adapter's listing row carried for `hydrate`, rebuilt from
        the posting alone (its `url` or `req_id`), or None: nothing to rebuild.
        An adapter whose `hydrate` reads the listing's `detail_payload` may
        declare `text_from_posting` only by overriding this; the description
        backfill sets it before `hydrate`."""
        return None

    async def read_posting_page(self, posting_id: str) -> PostingPage | None:
        """What one posting's own page states beyond its listing row: the size
        of its application form and its structured pay tiers.
        Default None: the source publishes neither."""
        return None
