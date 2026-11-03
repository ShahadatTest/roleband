"""Per-source collection review: classification, decision, and the evidence.

A source-by-source register of access method, robots status, terms, request
identity, fetch tier, review decision, review date and reviewer. It **enforces
nothing**: `source_policy.collection_access` remains the only thing that can
refuse a request, and a second refusal path would be a competing policy
system.

Three separate questions, deliberately not collapsed:

* **access classification** — how we reach the source (A-E). A documented
  public API is not the same claim as an undocumented careers endpoint, and
  neither is a permission.
* **review decision** — whether a human has reviewed this source and what they
  concluded. `UNREVIEWED` is the honest default and is **not** approval:
  "Unknown review status is not evidence of approval."
* **closure capability** — whether the binding may close jobs by absence. Lives
  on `SourceBinding` and is not repeated here. A permitted source may
  still lack closure authority, and an approved one is not thereby validated.

Why code-as-data rather than a table: a review decision is a dated, cited,
reviewable record, as provenance is in `tracker/vendored.py`; provenance in
prose rots unverified. In version control a decision arrives with a diff and
an author. `scripts.check_source_review` re-measures the robots
evidence against what is recorded here, so a stale entry is detectable rather
than merely old.

**Provider approval is not tenant approval.** `effective_review` requires BOTH
levels, which is how the rule "do not approve one employer by approving its
whole ATS" is expressed rather than commented. An ATS's terms permitting
anonymous board reads say nothing about whether a particular employer's board
is one we may collect.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum

from tracker.company_catalog import CATALOG, FAMILY_CONNECTORS
from tracker.config import COMPANIES

__all__ = [
    "AccessClass",
    "FetchTier",
    "Wall",
    "RobotsEvidence",
    "RobotsStatus",
    "ReviewResult",
    "SourceReview",
    "SOURCE_REVIEWS",
    "declared_adapter",
    "effective_review",
    "source_review",
    "source_wall",
    "unreviewed_providers",
    "user_directed_source",
]


class AccessClass(StrEnum):
    """How we reach the source (A-E). A method, never a permission."""

    PUBLIC_API = "documented_public_api"          # A
    PUBLIC_FEED = "structured_public_feed"        # B
    UNDOCUMENTED_ENDPOINT = "undocumented_endpoint"  # C
    HTML_EXTRACTION = "html_extraction"           # D
    BROWSER_AUTOMATION = "browser_automation"     # E


class ReviewResult(StrEnum):
    """What a human concluded. `UNREVIEWED` is never approval."""

    UNREVIEWED = "unreviewed"
    APPROVED = "approved"
    DENIED = "denied"


class RobotsStatus(StrEnum):
    """What robots.txt said about the route we actually request."""

    ALLOWED = "allowed"
    DISALLOWED = "disallowed"
    #: 4xx on robots.txt. RFC 9309 §2.3.1.3: treat as unrestricted. Recorded as
    #: its own status because "no file" is a weaker claim than "explicitly
    #: permitted", and a register that prints `allowed` for both overstates it.
    NOT_SERVED = "not_served"
    #: We have not read it. Distinct from every verdict above: silence about a
    #: source is not a finding about it.
    UNVERIFIED = "unverified"


class Wall(StrEnum):
    """Why a source is WALLED: collected only for a user who consents.

    Robots and bot walls gate on the user's consent, not on our refusal
    (`docs/sources.md`, "Walled and user-directed sources"). Both are FACTS
    read off this row — what the source asks or does — and the user decides
    whether RoleBand collects it for them.

    A wall is only ever the SOURCE's: a consent dialog asks the user to agree
    to something a source asked of us. A source RoleBand collects only on
    request asks nothing of the user, since following the company already IS
    the decision; that case is `SourceReview.user_directed`, which needs no
    consent and shows no dialog.
    """

    #: robots.txt disallows the route the adapter actually requests.
    ROBOTS = "robots"
    #: The host refuses an identified client on a robots-allowed route.
    BOT_WALL = "bot_wall"


class FetchTier(StrEnum):
    """How a source is fetched, weakest first.

    A tier above `IDENTIFIED` is a recorded, per-source decision on this
    register row, never an escalation the runtime makes on its own after a
    block. It is legal only on a WALLED row (`SourceReview.__post_init__`) and
    released only by `source_policy.collection_access` for a company whose user
    consented; every other request is fetched as an identified client. The
    implementations live in `connectors/runtime/tiers.py`, never the SDK.
    """

    #: Our own client: `Settings.scraper_user_agent`, httpx's TLS stack.
    IDENTIFIED = "identified"
    #: A full browser header set (client hints included) over httpx.
    BROWSER_IDENTITY = "browser_identity"
    #: A browser TLS + HTTP/2 fingerprint via `curl_cffi` impersonation.
    TLS_FINGERPRINT = "tls_fingerprint"
    #: A headless browser. Not in this build: a new dependency needs review.
    HEADLESS = "headless"
    #: A headless browser behind a proxy. Not in this build, as above.
    PROXY = "proxy"

    @property
    def rank(self) -> int:
        return list(FetchTier).index(self)


@dataclass(frozen=True)
class RobotsEvidence:
    """One dated reading of a robots file, and what it decided for OUR route.

    `sha256` and `winning_rule` are what make this re-checkable: the hash says
    whether the file moved, and the rule says which directive decided, so the
    next reader need not re-derive a 6KB file to understand a one-word verdict.
    """

    status: RobotsStatus
    checked: date | None = None
    robots_url: str | None = None
    #: sha256 of the body as read, or None when nothing was read.
    sha256: str | None = None
    #: The path + query evaluated — operators write rules against query strings.
    target: str | None = None
    #: `"disallow: /pattern"`, verbatim, or None when no rule matched. No rule
    #: means permitted by absence, which is not the same as an explicit `Allow`.
    winning_rule: str | None = None
    crawl_delay_seconds: float | None = None
    note: str = ""


@dataclass(frozen=True)
class SourceReview:
    """The register row for one provider."""

    provider: str
    access_class: AccessClass
    review: ReviewResult
    #: The listing route, as the adapter issues it.
    listing_surface: str
    detail_surface: str | None
    robots: RobotsEvidence
    #: What we send as `User-Agent`. It must match the declared collection
    #: posture.
    request_identity: str
    #: Modes a reviewer has approved. Empty while `UNREVIEWED` — an approved
    #: mode list on an unreviewed source would be an approval by another name.
    approved_modes: tuple[str, ...] = ()
    #: The tier this source needs, released only for a consented company
    #: (`FetchTier`): what a source may be fetched with is a user's consent,
    #: not a blanket refusal.
    fetch_tier: FetchTier = FetchTier.IDENTIFIED
    docs_url: str | None = None
    terms_url: str | None = None
    reviewer: str | None = None
    review_date: date | None = None
    evidence: tuple[str, ...] = field(default_factory=tuple)
    #: Measured: the host refuses a client that identifies itself (a WAF-style
    #: uniform 403 on a robots-allowed route). One of the walls.
    refuses_identified_client: bool = False
    #: Collect this source only when a user asks for it, company by company,
    #: as its review decided. Two effects, both
    #: enforced elsewhere — it keeps every company on the source off the
    #: curated list (`company_discovery.is_curated`, so nobody follows one
    #: without choosing it), and it keeps the source out of AUTOMATIC
    #: scheduling (`scheduler.collectable_now`), so a followed company is
    #: collected only by a sync the user starts.
    #:
    #: It is NOT a wall and asks for no consent: a wall is what a
    #: SOURCE asks of us, and there is nothing here for a user to agree to.
    #: Following the company is the decision, and a dialog saying so would tell
    #: the reader what they had just done.
    user_directed: bool = False
    #: The family this route belongs to, as its adapter declares it
    #: (`route_family`; `tests/test_source_review.py` holds the two equal).
    #: Two routes of one family reach the same tenants, and a company moves
    #: between them only by route detection (`company_store.record_route`), so
    #: the route it is on answers for it (`declared_adapter`).
    route_family: str | None = None

    def __post_init__(self) -> None:
        # A disguise on an unwalled source would fetch every follower's
        # companies that way, consent or not: the one tier an unwalled row may
        # record is our own identity.
        if self.fetch_tier is not FetchTier.IDENTIFIED and self.wall is None:
            raise ValueError(
                f"{self.provider}: fetch tier {self.fetch_tier.value!r} needs a wall;"
                " an unwalled source is fetched as an identified client"
            )

    @property
    def wall(self) -> Wall | None:
        """The wall this source puts up, if any. Robots first: it is the
        source's own stated request, where a bot wall is only its behaviour."""
        if self.robots.status is RobotsStatus.DISALLOWED:
            return Wall.ROBOTS
        if self.refuses_identified_client:
            return Wall.BOT_WALL
        return None

    @property
    def wall_fingerprint(self) -> str | None:
        """What a user consented TO: the wall and the evidence that decided it.

        Stored with the consent as the record of what was agreed. It is never
        compared with a later register: the user is asked once per company
        (`source_policy.collection_access`).
        """
        wall = self.wall
        if wall is None:
            return None
        return f"{wall.value}:{self.robots.sha256 or '-'}"


_CHECKED = date(2026, 9, 10)
#: The default `Settings.scraper_user_agent`. A plain Chrome string: it does
#: not identify RoleBand, so no operator can allow, throttle or refuse us
#: specifically. Recorded as the fact it is; the
#: fix is a review decision, not a register entry.
_CHROME_UA = "Mozilla/5.0 ... Chrome/131.0 Safari/537.36 (default)"


def _robots(
    status: RobotsStatus,
    url: str,
    *,
    sha256: str | None = None,
    target: str | None = None,
    rule: str | None = None,
    crawl_delay: float | None = None,
    note: str = "",
) -> RobotsEvidence:
    return RobotsEvidence(
        status=status,
        checked=_CHECKED if status is not RobotsStatus.UNVERIFIED else None,
        robots_url=url,
        sha256=sha256,
        target=target,
        winning_rule=rule,
        crawl_delay_seconds=crawl_delay,
        note=note,
    )


#: Every listing adapter in `ADAPTER_REGISTRY`, by provider key.
#: `tests/test_source_review.py` fails by name on an unregistered one.
#:
#: A `review` stays `UNREVIEWED` until a person decides it: a review weighs
#: terms of service and is a human decision, not a measurement, and recording
#: approvals nobody made is the exact failure this register exists to end.
SOURCE_REVIEWS: dict[str, SourceReview] = {
    "greenhouse": SourceReview(
        provider="greenhouse",
        access_class=AccessClass.PUBLIC_API,
        review=ReviewResult.UNREVIEWED,
        listing_surface="GET https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true",
        # Read for the application form (counts only) and structured
        # pay, only for radar postings whose text states no pay. Robots: the
        # same file's only rule is `Disallow: /embed/`, which this route misses.
        detail_surface=(
            "GET https://boards-api.greenhouse.io/v1/boards/{token}/jobs/{id}"
            "?questions=true&pay_transparency=true"
        ),
        robots=_robots(
            RobotsStatus.ALLOWED,
            "https://boards-api.greenhouse.io/robots.txt",
            sha256="0bc35a3bc59e53b4932c848ba1f33890320d2de73fa0c1357555dd79c5629be9",
            target="/v1/boards/anthropic/jobs?content=true",
            rule=None,
            note="only `Disallow: /embed/`; our route matches no rule",
        ),
        request_identity=_CHROME_UA,
        docs_url="https://developers.greenhouse.io/job-board.html",
        evidence=("board root also states the tenant name, which is what makes a"
                  " wrong-but-live token detectable",),
    ),
    "ashby": SourceReview(
        provider="ashby",
        access_class=AccessClass.PUBLIC_API,
        review=ReviewResult.UNREVIEWED,
        listing_surface="GET https://api.ashbyhq.com/posting-api/job-board/{name}",
        detail_surface=None,
        robots=_robots(
            RobotsStatus.NOT_SERVED,
            "https://api.ashbyhq.com/robots.txt",
            note="HTTP 401, 12-byte body: no robots file is served. RFC 9309"
                 " §2.3.1.3 treats 4xx as unrestricted, which is weaker than a"
                 " permission — the host simply states nothing.",
        ),
        request_identity=_CHROME_UA,
        docs_url="https://developers.ashbyhq.com/docs/public-job-posting-api",
    ),
    "lever": SourceReview(
        provider="lever",
        access_class=AccessClass.PUBLIC_API,
        review=ReviewResult.UNREVIEWED,
        listing_surface=(
            "GET https://api.lever.co/v0/postings/{site}?mode=json&limit=50&skip=N"
            " (EU tenants: api.eu.lever.co, same path)"
        ),
        detail_surface=None,
        robots=_robots(
            RobotsStatus.ALLOWED,
            "https://api.lever.co/robots.txt",
            sha256="6aa3556bd611889c4480a143bb6186f9d0c5e919c6b4c9901f3a6a8141549a1b",
            target="/v0/postings/spotify?mode=json&limit=50&skip=0",
            rule="allow: /",
            crawl_delay=1.0,
            note="the adapter's docstring claim, independently confirmed; our"
                 " 2.0s pacer is stricter than the declared 1s crawl-delay."
                 " BOTH deployments read separately (2026-09-10):"
                 " api.eu.lever.co serves a byte-identical file, same sha256,"
                 " same verdict — so one row covers both hosts rather than"
                 " asserting the EU host from the global one.",
        ),
        request_identity=_CHROME_UA,
        docs_url="https://github.com/lever/postings-api",
        evidence=("the one prose access claim in the codebase that re-measured true",
                  "two deployments, SEPARATE tenant namespaces: a global site"
                  " 404s on the EU host with the same body a nonexistent site"
                  " returns, so the region is carried and never inferred"
                  ""),
    ),
    "google": SourceReview(
        provider="google",
        access_class=AccessClass.HTML_EXTRACTION,
        review=ReviewResult.UNREVIEWED,
        listing_surface=(
            "GET https://www.google.com/about/careers/applications/jobs/results"
            "?page=N&sort_by=date&location=..."
        ),
        detail_surface="GET https://www.google.com/about/careers/applications/{path}",
        robots=_robots(
            RobotsStatus.DISALLOWED,
            "https://www.google.com/robots.txt",
            sha256="1aba570a1b32deb66941e0c29d4f37be71ee58aa1a624aa20754b3639538cf2c",
            target="/about/careers/applications/jobs/results?page=1&sort_by=date&location=United+States",
            rule="disallow: /about/careers/applications/jobs/results?page=",
            note="THE PAGINATED LISTING ONLY. The bare results path and the job"
                 " detail pages match no rule and are permitted; the adapter"
                 " always sends `page` as its first parameter, so every listing"
                 " request is a literal prefix match. The rule is in the opening"
                 " group, whose two consecutive `User-agent` lines (`*` then"
                 " `Yandex`) make it apply to us.",
        ),
        request_identity=_CHROME_UA,
        evidence=(
            "affects google and google-deepmind, both default-enabled built-ins",
            "RFC 9309 §1 does not grant or deny authorization, so this is one"
            " input to a review decision and not the decision",
        ),
    ),
    "amazon": SourceReview(
        provider="amazon",
        access_class=AccessClass.UNDOCUMENTED_ENDPOINT,
        review=ReviewResult.UNREVIEWED,
        listing_surface="GET https://www.amazon.jobs/en/search.json",
        detail_surface="GET https://www.amazon.jobs/{locale}/jobs/{id} (HTML)",
        robots=_robots(
            RobotsStatus.ALLOWED,
            "https://www.amazon.jobs/robots.txt",
            sha256="23a665abcf5da6674c3d6ba3242dd651febd0d21ed7b50487f5060f53cdfb24e",
            target="/en/search.json?base_query=&offset=0",
            rule=None,
            note="disallows only `/internal` and its locale variants",
        ),
        request_identity=_CHROME_UA,
        evidence=("listing and detail are separate surfaces and are classified"
                  " separately (§3): a JSON search endpoint and HTML extraction",),
    ),
    "apple": SourceReview(
        provider="apple",
        access_class=AccessClass.UNDOCUMENTED_ENDPOINT,
        review=ReviewResult.UNREVIEWED,
        listing_surface="POST https://jobs.apple.com/api/v1/search (CSRF token + session cookies)",
        detail_surface="GET https://jobs.apple.com/api/v1/jobDetails/{id}",
        robots=_robots(
            RobotsStatus.NOT_SERVED,
            "https://jobs.apple.com/robots.txt",
            note="HTTP 404 carrying a 111KB HTML body — the app shell is served"
                 " for any unknown path, so a status-code-only check would read"
                 " a page as a robots file. No robots file exists.",
        ),
        request_identity=_CHROME_UA,
        evidence=(
            "the search POST is a read, not an application submission",
            "country codes come from GET https://jobs.apple.com/api/v1/refData/postlocation"
            "?input={name}, the lookup the search page's place box calls, read by"
            " `scripts.build_apple_places` and never by a scan",
        ),
    ),
    "microsoft": SourceReview(
        provider="microsoft",
        access_class=AccessClass.UNDOCUMENTED_ENDPOINT,
        review=ReviewResult.UNREVIEWED,
        listing_surface="POST https://apply.careers.microsoft.com/api/pcsx/search",
        detail_surface="POST https://apply.careers.microsoft.com/api/pcsx/position_details",
        robots=_robots(
            RobotsStatus.ALLOWED,
            "https://apply.careers.microsoft.com/robots.txt",
            sha256="e658ad39f6765e6fdcbdb8a13cf3d4808327ad1c701c92c64a46052f3b9e2a29",
            target="/api/pcsx/search",
            rule="allow: /api/pcsx",
            note="`Disallow: /` with an allowlist that NAMES our exact API path."
                 " Longest-match-wins is load-bearing: read first-match-wins"
                 " (as `urllib.robotparser` does) this reads as refused.",
        ),
        request_identity=_CHROME_UA,
        evidence=("the strongest robots evidence in the register: the operator"
                  " explicitly permitted the route we use",),
    ),
    "workday": SourceReview(
        provider="workday",
        access_class=AccessClass.UNDOCUMENTED_ENDPOINT,
        # APPROVED here permits COLLECTION from this source on the terms
        # `user_directed` enforces — it is not a finding about any tenant's
        # terms of service, and it grants no company: `effective_review` still
        # answers UNREVIEWED for every one of them, because approving an ATS
        # approves no employer on it.
        review=ReviewResult.APPROVED,
        reviewer="owner",
        review_date=date(2026, 9, 23),
        listing_surface=(
            "POST https://nvidia.wd5.myworkdayjobs.com/wday/cxs/nvidia/"
            "NVIDIAExternalCareerSite/jobs"
        ),
        detail_surface="GET .../wday/cxs/{tenant}/{site}{externalPath}",
        robots=_robots(
            RobotsStatus.ALLOWED,
            "https://nvidia.wd5.myworkdayjobs.com/robots.txt",
            sha256="8911476ca1f87a96392d0cfc3f19790142ed4da5c905a670eabb5507b34f0f33",
            target="/wday/cxs/nvidia/NVIDIAExternalCareerSite/jobs",
            rule=None,
            note="allowed by ABSENCE of a rule, not by permission: the file"
                 " allows `/NVIDIAExternalCareerSite/` (the UI path) and"
                 " disallows `/talentcommunity/` and `/refreshFacet/`, neither"
                 " of which the adapter calls. Our `/wday/cxs/` route is"
                 " unmentioned.",
        ),
        request_identity=_CHROME_UA,
        user_directed=True,
        evidence=("APPROVED: collection from this source, conditioned on the"
                  " user directing it: every"
                  " Workday company is disabled by default, is followed one at"
                  " a time, and is scanned only by a sync the user starts."
                  " The condition is not prose: `user_directed` enforces both"
                  " halves, and an approval nobody could act on differently"
                  " would be the kind of record this register exists to"
                  " prevent. No tenant's terms are weighed: the judgement"
                  " would be the same for all of them, so the choice"
                  " of WHICH companies is the user's",
                  "the tenant is per-company, so a Workday review is not"
                  " transferable to another employer's Workday site — the"
                  " reason the decision is the user's per company rather than"
                  " ours once for the family",
                  "the source is not paused: collection continues at the"
                  " user's direction rather than the scheduler's"),
    ),
    "eightfold": SourceReview(
        provider="eightfold",
        access_class=AccessClass.UNDOCUMENTED_ENDPOINT,
        review=ReviewResult.UNREVIEWED,
        listing_surface="GET https://{host}/api/apply/v2/jobs?domain={domain} (v2 tenants),"
                        " GET https://{host}/api/pcsx/search?domain={domain} (PCSX tenants)",
        detail_surface="GET https://{host}/api/apply/v2/jobs/{id} (v2),"
                       " GET https://{host}/api/pcsx/position_details?position_id={id} (PCSX)",
        robots=_robots(
            RobotsStatus.ALLOWED,
            "https://explore.jobs.netflix.net/robots.txt",
            sha256="323d58820850093169d1a0c1825251268dc173846771c5f8479d9bec23a6c4bb",
            target="/api/apply/v2/jobs?domain=netflix.com",
            rule="allow: /api/apply",
            note="same Eightfold template as microsoft, and the same"
                 " longest-match dependency: `Disallow: /` with our route named"
                 " in the allowlist.",
        ),
        request_identity=_CHROME_UA,
        evidence=(
            "multi-tenant: netflix (v2), paypal and qualcomm (PCSX)",
            "robots evidence above is Netflix's host ONLY. paypal.eightfold.ai and"
            " careers.qualcomm.com were read 2026-09-21 and serve the same template"
            " (`Disallow: /` with `Allow: /api/apply` and `Allow: /api/pcsx`), but"
            " per-host evidence is NOT recorded: the register holds one robots"
            " record per provider. Their files are not re-read by"
            " `scripts.check_source_review`.",
        ),
    ),
    "workable": SourceReview(
        provider="workable",
        # C, not A. This is the route a tenant's own public board widget calls,
        # and it needs no key — but "no key" is not "documented". Workable's
        # published API reference covers the authenticated SPI
        # (`{subdomain}.workable.com/spi/v3/...`); no published reference for
        # this widget route was found, and claiming A on that basis would be
        # the register asserting something nobody read. A reviewer who finds
        # one moves this to PUBLIC_API with the URL.
        access_class=AccessClass.UNDOCUMENTED_ENDPOINT,
        review=ReviewResult.UNREVIEWED,
        listing_surface=(
            "GET https://apply.workable.com/api/v1/widget/accounts/{token}?details=true"
        ),
        # The listing carries every description inline, so there is no second
        # route: `hydrate()` is a no-op and no per-posting request is issued.
        detail_surface=None,
        robots=_robots(
            RobotsStatus.ALLOWED,
            "https://apply.workable.com/robots.txt",
            sha256="3594bfb0ec0bbfce844cf6ab5cd2aac430e784f3fb1581e5c8f74066b6997df7",
            target="/api/v1/widget/accounts/{token}",
            note="78 bytes, one group. `Disallow:` with an EMPTY value is RFC"
                 " 9309 §2.2.2's 'nothing is disallowed': it matches no path,"
                 " so no rule decides, and no Crawl-delay is declared — the 2.0s default pacer is"
                 " stricter than anything asked for. The file also carries a"
                 " `Content-Signal` line, `search=yes, ai-input=yes,"
                 " ai-train=no`: recorded because it is what the host states"
                 " about USE rather than access. RoleBand reads postings into a"
                 " seeker's own radar and trains nothing, but this register"
                 " records, it does not rule.",
        ),
        request_identity=_CHROME_UA,
        evidence=(
            "the account payload states the tenant's own name, so a wrong-but-live"
            " token is detectable here — the second family after greenhouse that"
            " can say this",
        ),
    ),
    "atlassian": SourceReview(
        provider="atlassian",
        access_class=AccessClass.UNDOCUMENTED_ENDPOINT,
        review=ReviewResult.UNREVIEWED,
        listing_surface="GET https://www.atlassian.com/endpoint/careers/listings",
        # The listing carries every description inline; no second route.
        detail_surface=None,
        robots=RobotsEvidence(
            status=RobotsStatus.ALLOWED,
            checked=date(2026, 9, 22),
            robots_url="https://www.atlassian.com/robots.txt",
            sha256="c0a6d137d17b75f9f916b616a77e87fde588b0adb4338127b03b55ea77ba3841",
            target="/endpoint/careers/listings",
            winning_rule=None,
            note="Allowed by ABSENCE: the `User-agent: *` group disallows blog,"
                 " dam, purchase and variants paths only. The `atlassian-bot`"
                 " group's `Disallow: /company/careers/detail/*` names another"
                 " agent and another route.",
        ),
        request_identity=_CHROME_UA,
        evidence=(
            "the endpoint Atlassian's own careers page loads (observed in the"
            " browser, 2026-09-21): 285 rows, 268 unique postings, descriptions"
            " and pay text inline",
            "chosen over the company's iCIMS hosts: their sitemaps"
            " listed 82 (global) and 59 (APAC, overlapping) postings",
        ),
    ),
    "accenture": SourceReview(
        provider="accenture",
        access_class=AccessClass.UNDOCUMENTED_ENDPOINT,
        review=ReviewResult.UNREVIEWED,
        listing_surface=(
            "POST https://www.accenture.com/api/accenture/elastic/findjobs (form, per"
            " jobCountry/countrySite/jobLanguage); for every other country POST"
            " https://accenture.wd103.myworkdayjobs.com/wday/cxs/accenture/AccentureCareers/jobs"
            " (json, per locationCountry facet)"
        ),
        # The own search carries every description inline; board rows read theirs here.
        detail_surface="GET https://accenture.wd103.myworkdayjobs.com/wday/cxs/accenture/AccentureCareers{externalPath}",
        robots=RobotsEvidence(
            status=RobotsStatus.ALLOWED,
            checked=date(2026, 9, 22),
            robots_url="https://www.accenture.com/robots.txt",
            sha256="8b1cbd4395d69a8369d142e91c966f9299c4682f3aa5d56c4b380158ffddea63",
            target="/api/accenture/elastic/findjobs",
            winning_rule=None,
            note="Allowed by ABSENCE. The careers rules are `*/Careers/Registration`,"
                 " `*/Careers/Form`, `*/Careers/Profiles`, `/us-en/careers/admin/"
                 "careersxmlresult` and `*/careers/jobsearch?` — the search PAGE with"
                 " a query string, not the API it calls.",
        ),
        request_identity=_CHROME_UA,
        evidence=(
            "the API accenture.com's own job search calls (observed in the"
            " browser, 2026-09-22); it is the source for every country it answers",
            "the Workday board the own search's rows link to, for every other"
            " country: its robots.txt allows `/AccentureCareers/` and disallows"
            " only `/refreshFacet/`, which the adapter never calls; the"
            " `/wday/cxs/` route is unmentioned, the basis recorded for Workday",
            "chosen over the company's Pinpoint tenant, which holds"
            " 7 Irish graduate postings",
        ),
    ),
    "avature": SourceReview(
        provider="avature",
        access_class=AccessClass.HTML_EXTRACTION,
        review=ReviewResult.UNREVIEWED,
        listing_surface=(
            "GET https://{host}/{portal}/SearchJobs/?jobRecordsPerPage=20&jobOffset=N"
            " (folder portals: ?folderRecordsPerPage=10&folderOffset=N&folderSort={posted-date field}"
            "&folderSortDirection=DESC)"
        ),
        detail_surface="GET https://{host}/{portal}/JobDetail|FolderDetail/{slug}/{id} (labelled field blocks)",
        robots=RobotsEvidence(
            status=RobotsStatus.ALLOWED,
            checked=date(2026, 9, 22),
            robots_url="https://jobs.ea.com/robots.txt",
            sha256="3bdac1be7bf1fc17c6bc90eac9acd0f887ad84e89a8070d192529bea55c22f1b",
            target="/en_US/careers/SearchJobs/?jobRecordsPerPage=20&jobOffset=0",
            winning_rule="allow: /*/careers",
            note="EA's tenant host only (P6: one row per provider). `Allow: /*/careers`"
                 " with `Disallow: /*/careers/*qtvc=`; the adapter never sends `qtvc`."
                 " Synopsys' tenant host (synopsys.avature.net, sha256 d8c827c1...,"
                 " 2026-09-22): `Allow: /careers`, `Disallow: /careers/*qtvc=`."
                 " Two Sigma (careers.twosigma.com, sha256 b446dacd..., 2026-09-25)"
                 " and Deloitte (apply.deloitte.com, sha256 959ca123..., 2026-09-26):"
                 " the same `Allow: /careers` / `Disallow: /careers/*qtvc=` pair."
                 " Bain (careers.bain.com, sha256 21c185a5..., 2026-09-27): `Allow:"
                 " /jobs`, `Disallow: /jobs/*qtvc=`.",
        ),
        request_identity=_CHROME_UA,
        route_family="avature",
        evidence=(
            "server-rendered portal template shared by Avature tenants",
            "TSMC's Avature portal refuses identified clients behind a Cloudflare"
            " challenge: it is collected on the walled `avature_tls` route, with"
            " the user's consent, never on this one",
        ),
    ),
    "avature_tls": SourceReview(
        provider="avature_tls",
        access_class=AccessClass.HTML_EXTRACTION,
        review=ReviewResult.UNREVIEWED,
        listing_surface="GET https://{host}/{portal}/SearchJobs/?jobRecordsPerPage=20&jobOffset=N",
        detail_surface="GET https://{host}/{portal}/JobDetail?jobId={id} (labelled field blocks)",
        robots=RobotsEvidence(
            status=RobotsStatus.ALLOWED,
            checked=date(2026, 9, 26),
            robots_url="https://careers.tsmc.com/robots.txt",
            sha256="cf9d435042718a5a4d030f95afe0d3f800f86fe8b68dbd817dc7cb2a30e34f7a",
            target="/en_US/careers/SearchJobs/?jobRecordsPerPage=20&jobOffset=0",
            winning_rule="allow: /*/careers",
            note="Read on the TLS tier: the identified client gets the Cloudflare"
                 " challenge for robots.txt too. `Allow: /*/careers` with"
                 " `Disallow: /*/careers/*qtvc=`; the adapter never sends `qtvc`.",
        ),
        request_identity=_CHROME_UA,
        fetch_tier=FetchTier.TLS_FINGERPRINT,
        refuses_identified_client=True,
        route_family="avature",
        evidence=(
            "TSMC's Avature portal: identified client 403 'Just a moment'"
            " on search and robots; curl_cffi Chrome impersonation 200, 798/798"
            " postings over 80 pages, 2026-09-26",
            "the walled route of the avature family; parsing is the family's",
        ),
    ),
    "deel": SourceReview(
        provider="deel",
        access_class=AccessClass.HTML_EXTRACTION,
        review=ReviewResult.UNREVIEWED,
        listing_surface="GET https://jobs.deel.com/{org}/sitemap.xml (the board's own enumeration)",
        detail_surface="GET https://jobs.deel.com/{org}/job-details/{uuid}/overview (JSON-LD JobPosting)",
        robots=_robots(
            RobotsStatus.ALLOWED,
            "https://jobs.deel.com/robots.txt",
            sha256="fec29e63c66e622e9fa994ef62dc1d94f8580428bbf1fddb2a01017433b035e3",
            target="/klarna/sitemap.xml",
            rule="allow: /",
            note="`Allow: /` with two disallows: `/api/` and"
                 " `/*/job-details/*/application`. The adapter requests neither —"
                 " and the file's own comment points at the per-org sitemap this"
                 " adapter reads. One host for every tenant.",
        ),
        request_identity=_CHROME_UA,
        evidence=(
            "the board page renders its list from the disallowed /api/ route, so the"
            " sitemap is the allowed listing",
        ),
    ),
    "radancy": SourceReview(
        provider="radancy",
        access_class=AccessClass.HTML_EXTRACTION,
        review=ReviewResult.UNREVIEWED,
        listing_surface="GET https://{host}/sitemap.xml (the board's own enumeration)",
        detail_surface="GET https://{host}/job/{city}/{slug}/{site}/{id} (JSON-LD JobPosting)",
        robots=_robots(
            RobotsStatus.ALLOWED,
            "https://careers.arm.com/robots.txt",
            sha256="ec23d75d4379fc1226f6ef6d925165e7438fb40261265b6be428f5a28c91ee03",
            target="/sitemap.xml",
            rule=None,
            note="Arm's tenant host (P6: one row per provider). The whole file is"
                 " `Disallow:/search-jobs/` — the SEARCH. The sitemap and the"
                 " posting pages match no rule, and the adapter never requests"
                 " /search-jobs/. Synopsys' TalentBrew site serves the same one"
                 " rule.",
        ),
        request_identity=_CHROME_UA,
        evidence=(
            "the sitemap is the board: no category page states a total",
            "the posting JSON-LD carries the HIRING MANAGER's name in `workHours`;"
            " it is never read, like every other recruiter contact",
            "Arm's ATS behind the site is iCIMS, whose host robots is `Disallow: /`"
            " — walled, and not what this adapter reads",
        ),
    ),
    "jibe": SourceReview(
        provider="jibe",
        access_class=AccessClass.UNDOCUMENTED_ENDPOINT,
        review=ReviewResult.UNREVIEWED,
        listing_surface="GET https://{host}/api/jobs?page=N&limit=100 (tenant careers host)",
        detail_surface=None,
        robots=_robots(
            RobotsStatus.ALLOWED,
            "https://www.github.careers/robots.txt",
            sha256="3df3aa523e1ace5efb8f2343e347ecbdb13834a47d723d3bb90c540c34429d13",
            target="/api/jobs?page=1&limit=100",
            rule="allow: /",
            crawl_delay=5.0,
            note="GitHub's tenant host (P6: one row per provider). Booking's"
                 " jobs.booking.com serves the same rules (sha256 39bb2db2..., the"
                 " sitemap line differs): `Allow: /`, `crawl-delay: 5`, honoured by"
                 " the 5s provider pacing.",
        ),
        request_identity=_CHROME_UA,
        evidence=(
            "the JSON the tenant's own careers page calls; descriptions inline",
            "apply links are the tenant's iCIMS site, never requested",
        ),
    ),
    "kpmg": SourceReview(
        provider="kpmg",
        access_class=AccessClass.HTML_EXTRACTION,
        review=ReviewResult.UNREVIEWED,
        listing_surface="GET https://www.kpmguscareers.com/job-search/?spage=N&order=posted",
        detail_surface="GET https://www.kpmguscareers.com/jobdetail/?jobId={id} (JSON-LD JobPosting)",
        robots=RobotsEvidence(
            status=RobotsStatus.ALLOWED,
            checked=date(2026, 9, 22),
            robots_url="https://www.kpmguscareers.com/robots.txt",
            sha256="9923c7f1139d93050f41d8a47b045ac16d553d1275649f6831d437c3b50fda23",
            target="/job-search/?spage=1&order=posted",
            winning_rule=None,
            note="One rule: `Disallow: /wp-content/themes/understrap-child-main/"
                 "page-templates/google/record-click.php` (click tracking). Neither"
                 " the search nor the posting pages match it.",
        ),
        request_identity=_CHROME_UA,
        evidence=(
            "KPMG US's own WordPress careers search, server-rendered",
            "a result card is a job at a place: 798 cards, 739-740 jobs;"
            " completeness is unique card ids against the stated count",
        ),
    ),
    "shopify": SourceReview(
        provider="shopify",
        access_class=AccessClass.HTML_EXTRACTION,
        review=ReviewResult.UNREVIEWED,
        listing_surface="GET https://www.shopify.com/careers (React Router loader data in the page)",
        detail_surface="GET https://www.shopify.com/careers/{slug}_{posting id} (loader data)",
        robots=RobotsEvidence(
            status=RobotsStatus.ALLOWED,
            checked=date(2026, 9, 27),
            robots_url="https://www.shopify.com/robots.txt",
            sha256="8c90bf29637302cb2290753d5b750ff2ba0b1b47e84dd4c34359bf56dce04722",
            target="/careers",
            winning_rule=None,
            note="No rule matches `/careers` or `/careers/{slug}_{id}`. Careers rules:"
                 " `Disallow: /careers/search?*` and `/careers/portal/*`; site-wide"
                 " `*page=*`, `*country=*`, `*.data$` (React Router's data route)."
                 " None is requested. Read through the redirect-following safe fetch.",
        ),
        request_identity=_CHROME_UA,
        evidence=(
            "Shopify's own careers page; its Ashby board (`shopify`) answers 404",
            "the streamed rows carry the hiring team's names and emails; the adapter"
            " reads a field allowlist and never keeps a raw row",
        ),
    ),
    "successfactors": SourceReview(
        provider="successfactors",
        access_class=AccessClass.HTML_EXTRACTION,
        review=ReviewResult.UNREVIEWED,
        listing_surface=(
            "GET https://{host}/{site}/search/?q=&sortColumn=referencedate"
            "&sortDirection=desc&startrow=N"
        ),
        detail_surface="GET https://{host}/{site}/job/{slug}/{id}/ (schema.org microdata)",
        robots=RobotsEvidence(
            status=RobotsStatus.ALLOWED,
            checked=date(2026, 9, 27),
            robots_url="https://careers.ey.com/robots.txt",
            sha256="91669efc2767d124199e1d848655af18d64ac71e61ae1227be7b6aa866f03caf",
            target="/ey/search/?q=&sortColumn=referencedate&sortDirection=desc&startrow=0",
            winning_rule=None,
            note="EY's tenant host only (P6: one row per provider). Ten disallows"
                 " (`/applybutton/`, `/talentcommunity/`, `/services/`, `/preapply/`,"
                 " ...); neither `/ey/search/` nor `/ey/job/` matches one. Read"
                 " through the redirect-following safe fetch.",
        ),
        request_identity=_CHROME_UA,
        evidence=(
            "the career-site builder SAP ships with SuccessFactors Recruiting,"
            " server-rendered per tenant host",
            "apply and talent-community routes are robots-disallowed and never requested",
        ),
    ),
    "tiktok": SourceReview(
        provider="tiktok",
        access_class=AccessClass.UNDOCUMENTED_ENDPOINT,
        review=ReviewResult.UNREVIEWED,
        listing_surface=(
            "POST https://api.lifeattiktok.com/api/v1/public/supplier/search/job/posts"
            " (header `website-path: tiktok`, body offset/limit)"
        ),
        detail_surface="GET https://lifeattiktok.com/search/{id} (pay block only)",
        robots=RobotsEvidence(
            status=RobotsStatus.ALLOWED,
            checked=date(2026, 9, 26),
            robots_url="https://api.lifeattiktok.com/robots.txt",
            sha256="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
            target="/api/v1/public/supplier/search/job/posts",
            winning_rule=None,
            note="An empty file (200, 0 bytes): nothing is disallowed on the API"
                 " host. The posting host's file (`careers.tiktok.com/robots.txt`"
                 " 302s to `lifeattiktok.com/robots.txt`, sha256 c8844579...333a6)"
                 " disallows only `/referral/` for `*`; `/search/{id}` matches no"
                 " rule. Both read through the redirect-following safe fetch.",
        ),
        request_identity=_CHROME_UA,
        evidence=(
            "the JSON the careers site's own search page calls; the route and the"
            " required header were read from its JS chunk",
            "descriptions arrive with the listing; the posting page is read only"
            " for a US posting's pay band",
            "apply links (`careers.tiktok.com/resume/{id}/apply`) are never requested",
        ),
    ),
    "oracle": SourceReview(
        provider="oracle",
        access_class=AccessClass.UNDOCUMENTED_ENDPOINT,
        review=ReviewResult.UNREVIEWED,
        listing_surface=(
            "GET https://{host}/hcmRestApi/resources/latest/recruitingCEJobRequisitions"
            "?finder=findReqs;siteNumber={site},limit=200,offset=N (Oracle Cloud HCM CE)"
        ),
        detail_surface="GET https://{host}/hcmRestApi/resources/latest/recruitingCEJobRequisitionDetails?finder=ById;Id=\"{id}\",siteNumber={site}",
        robots=RobotsEvidence(
            status=RobotsStatus.NOT_SERVED,
            checked=date(2026, 9, 22),
            robots_url="https://edel.fa.us2.oraclecloud.com/robots.txt",
            note="HTTP 404 with a 196-byte Apache 'Not Found' page: no robots file"
                 " is served on Fortinet's tenant host. RFC 9309 §2.3.1.3: 4xx is"
                 " unrestricted. Per-host evidence for other tenants is not"
                 " recorded (P6, one row per provider).",
        ),
        request_identity=_CHROME_UA,
        evidence=(
            "the REST API behind every tenant's Candidate Experience site;"
            " Fortinet's careers page links its CX site directly",
            "`TotalJobsCount` declares the board; measured Fortinet 938 declared,"
            " 937 listable by any route, the gap explained by the workplace-type"
            " facet partition",
            "the detail payload carries recruiter contact fields; the adapter"
            " never reads them",
        ),
    ),
    "smartrecruiters": SourceReview(
        provider="smartrecruiters",
        access_class=AccessClass.HTML_EXTRACTION,
        review=ReviewResult.UNREVIEWED,
        listing_surface=(
            "GET https://careers.smartrecruiters.com/{company} (index),"
            " GET .../{company}/api/groups?page=N, GET .../{company}/api/more"
            "?type=location&value=V&page=P"
        ),
        detail_surface="GET https://jobs.smartrecruiters.com/{company}/{posting_id} (HTML microdata)",
        robots=_robots(
            RobotsStatus.NOT_SERVED,
            "https://careers.smartrecruiters.com/robots.txt",
            note="Read 2026-09-21. The careers host 302s `/robots.txt` to"
                 " `jobs.smartrecruiters.com`, whose `/robots.txt` answers 404"
                 " with an HTML page (the posting host's app shell), so NEITHER"
                 " host we request serves a robots file. RFC 9309 §2.3.1.3: 4xx"
                 " is unrestricted. Distinct from `api.smartrecruiters.com` (the"
                 " `smartrecruiters_api` row), which disallows us.",
        ),
        request_identity=_CHROME_UA,
        route_family="smartrecruiters",
        evidence=(
            "the career page SmartRecruiters publishes for job seekers; chosen over"
            " the documented API on 2026-09-21 because it is not"
            " walled, so its companies can be curated and followed without a"
            " consent dialog",
            "completeness is per location group (`data-qty` vs postings listed):"
            " ServiceNow 656/656, Roland Berger 204/204, Ubisoft 297/297 measured"
            " 2026-09-21",
            "the board names its company (`og:title` \"Careers at {Name}\"), so a"
            " wrong-but-live token is detectable",
        ),
    ),
    "smartrecruiters_api": SourceReview(
        provider="smartrecruiters_api",
        access_class=AccessClass.PUBLIC_API,
        review=ReviewResult.UNREVIEWED,
        listing_surface="GET https://api.smartrecruiters.com/v1/companies/{company}/postings?limit=100&offset=N",
        detail_surface="GET https://api.smartrecruiters.com/v1/companies/{company}/postings/{posting_id}",
        robots=RobotsEvidence(
            status=RobotsStatus.DISALLOWED,
            checked=date(2026, 9, 21),
            robots_url="https://api.smartrecruiters.com/robots.txt",
            sha256="834faf99999604ead9af2c371e8e41a914b67fecd52e51c3e1125595c28564ec",
            target="/v1/companies/ServiceNow/postings?limit=100&offset=0",
            winning_rule="disallow: /",
            note="Two groups: `User-agent: LinkedInBot` / `Allow: /v1/companies/`,"
                 " then `User-agent: *` / `Disallow: /`. Only LinkedIn's crawler is"
                 " permitted, so the documented Posting API is WALLED for us"
                 ": collected only for a company whose user consented.",
        ),
        request_identity=_CHROME_UA,
        docs_url="https://developers.smartrecruiters.com/docs/posting-api",
        route_family="smartrecruiters",
        evidence=(
            "the fallback route of the smartrecruiters family, for a"
            " tenant whose board is not published on SmartRecruiters (Wise"
            " redirects to wise.jobs); a company moves here, and back, only by"
            " route detection recorded through company_store.record_route",
            "`totalFound` declares the board size; unique ids are compared to it"
            "",
        ),
    ),
}

#: Per-company review decisions. Empty, and structurally required: approving a
#: provider must never approve every tenant on it. A company absent here
#: is `UNREVIEWED` whatever its provider says.
COMPANY_REVIEWS: dict[str, ReviewResult] = {}


def declared_adapter(company: str | None, provider_key: str | None = None) -> str | None:
    """The provider a named company is declared on, or None.

    A built-in's blueprint adapter, else its catalog row's, else its
    connector family's: the declared half of
    `company_discovery.collecting_provider`, which answers through this. Every
    gate that names a company consults it beside the provider it was handed,
    so a path that presents itself under another name (a recipe) cannot shed
    the declared provider's deny, wall or user-directed rule.

    `provider_key` is the provider the caller collects through. When it is
    another route of the declared provider's family (a board that moved route),
    that route answers for itself and this is None: its own row decides, and a
    walled route's tier is never released for an unwalled one. A company RoleBand
    does not name (added by URL, or from the directory) has no declared provider.
    """
    if not company:
        return None
    if company in COMPANIES:
        declared = str(COMPANIES[company]["adapter"])
    elif company in CATALOG:
        declared = str(CATALOG[company]["adapter"])
    elif company in FAMILY_CONNECTORS:
        declared = str(FAMILY_CONNECTORS[company]["adapter"])
    else:
        return None
    if provider_key and provider_key != declared:
        family = _route_family(provider_key)
        if family is not None and family == _route_family(declared):
            return None
    return declared


def _route_family(provider_key: str) -> str | None:
    entry = SOURCE_REVIEWS.get(provider_key)
    return entry.route_family if entry is not None else None


def source_review(provider_key: str, *, company: str | None = None) -> SourceReview | None:
    """The register row for a provider, resolving a company's declared adapter.

    Mirrors `source_policy.collection_access`: a company's declared provider is
    consulted so an alternate execution path (a recipe, say) cannot present
    itself as an unregistered source.
    """
    for candidate in (provider_key, declared_adapter(company, provider_key)):
        if candidate in SOURCE_REVIEWS:
            return SOURCE_REVIEWS[candidate]
    return None


def effective_review(provider_key: str, *, company: str | None = None) -> ReviewResult:
    """The decision that would gate collection — BOTH levels must approve.

    This is the rule "do not approve one employer by approving its whole ATS",
    expressed rather than commented. A provider `DENIED` refuses outright; past
    that, an approved provider still leaves an unlisted company `UNREVIEWED`.

    Returns a decision only. It gates nothing today: no caller refuses on it,
    and `source_policy` remains the single path that can stop a request.
    """
    entry = source_review(provider_key, company=company)
    if entry is None or entry.review is ReviewResult.DENIED:
        return ReviewResult.DENIED if entry else ReviewResult.UNREVIEWED
    if entry.review is not ReviewResult.APPROVED:
        return entry.review
    if company is None:
        return ReviewResult.APPROVED
    return COMPANY_REVIEWS.get(company, ReviewResult.UNREVIEWED)


def unreviewed_providers() -> tuple[str, ...]:
    """Providers with no review decision."""
    return tuple(
        sorted(
            key for key, entry in SOURCE_REVIEWS.items()
            if entry.review is ReviewResult.UNREVIEWED
        )
    )


def user_directed_source(provider_key: str, *, company: str | None = None) -> bool:
    """Is this source collected only when the user asks for it?

    Resolved exactly as `source_wall` resolves a provider, so a recipe cannot
    present a user-directed company as a schedulable source. Consent is not the
    same answer: a user may have consented months ago, which says "you may",
    never "now".
    """
    declared = declared_adapter(company, provider_key)
    return any(
        entry.user_directed
        for entry in (SOURCE_REVIEWS.get(key) for key in (provider_key, declared) if key)
        if entry is not None
    )


def source_wall(provider_key: str, *, company: str | None = None) -> SourceReview | None:
    """The register row of a WALLED source, or None when nothing walls it.

    Resolves a company's declared provider exactly as `source_review` does, so
    a recipe cannot present a walled company as an unwalled source.
    """
    for candidate in (provider_key, declared_adapter(company, provider_key)):
        entry = SOURCE_REVIEWS.get(candidate) if candidate else None
        if entry is not None and entry.wall is not None:
            return entry
    return None
