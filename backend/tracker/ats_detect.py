"""Resolve what a careers-page URL IS, and separately whether we may collect it.

Two questions, deliberately not one. `detect_surface()` answers "what surface is
this?" and `detect_ats()` answers "which connector may collect it?" — the second
being the collectable-only view of the first. Greenhouse, Ashby, Lever, Workable,
SmartRecruiters, Deel, Oracle, Avature (on `*.avature.net`), Workday and Google
DeepMind's board are collectable. A family whose tenant is on the tenant's own
host (Jibe, Radancy, Avature on `jobs.ea.com`) carries no marker in its URL and
needs page detection. Everything else returns None; the caller records the company as
`status="pending"` (adapter needed) rather than pretending it scrapes.

Splitting the two is the point rather than an abstraction: detection
confers neither permission nor readiness. A family recognised before it is
onboarded, or while its provider is under review, must not start collecting
because a URL matched; that is `SurfaceReadiness.CANDIDATE`. Every family
recognised here is collectable; the state is kept for the next one that is
recognised before it is onboarded.

Pure/stdlib-only so it is unit-testable without a DB or network.
"""

from __future__ import annotations

import re
from enum import Enum
from typing import NamedTuple
from urllib.parse import parse_qs, urlparse

from tracker.schema import BoardRegion

# Tokens remain opaque and case-preserving. Ashby also uses dotted board names
# (e.g. mistral.ai); a URL path is never searched for a plausible later segment.
_SLUG = re.compile(r"[a-z0-9][a-z0-9-]{0,63}", re.IGNORECASE)
_ASHBY_NAME = re.compile(r"[a-z0-9][a-z0-9.-]{0,63}", re.IGNORECASE)
#: Workday site ids are tenant-chosen and commonly underscored
#: (`NVIDIAExternalCareerSite`, `Acme_External`).
_WORKDAY_SITE = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}", re.IGNORECASE)

# Path segments that are never a board token even though they sit right after the
# host (generic careers wrappers).
#: Lever's regional deployments. Separate hosts AND separate tenant namespaces:
#: a global tenant 404s on the EU host and vice versa, with the same body a
#: nonexistent site returns. This maps hosts -> regions for detection; the
#: adapter's `lever.REGION_HOSTS` maps regions -> hosts for fetching. They are
#: deliberately in different layers (detection is L4, the adapter L3, and L4
#: must not import a concrete adapter), so the invariant that they are exact
#: inverses is gated by a test rather than asserted here.
_LEVER_HOSTS = {
    "jobs.lever.co": BoardRegion.GLOBAL,
    "api.lever.co": BoardRegion.GLOBAL,
    "jobs.eu.lever.co": BoardRegion.EU,
    "api.eu.lever.co": BoardRegion.EU,
}

_NOISE = {"embed", "v1", "boards", "job_board", "jobs", "careers", "en", "en-us"}

#: `{tenant}.wd{N}.myworkdayjobs.com`. The pod label (`wd5`) is matched exactly,
#: so an implementation tenant (`wd5-impl`) and the vendor's own marketing site
#: (`www.workday.com`) are both unrecognised — recognising a sandbox as a
#: careers surface would name a tenant that publishes nothing.
_WORKDAY_HOST = re.compile(r"(?P<tenant>[a-z0-9][a-z0-9-]{0,63})\.wd\d+\.myworkdayjobs\.com")
#: Workday's SHARED host, `wd{N}.myworkdaysite.com`: several employers, so the
#: host names no tenant and the path does (`/recruiting/{tenant}/{site}`, snap).
_WORKDAY_SHARED_HOST = re.compile(r"wd\d+\.myworkdaysite\.com")
#: The locale segment Workday's own links carry, always language-REGION
#: (`en-US`, `zh-CN`). Requiring the region subtag keeps a two-letter *site* id
#: from being read as a locale; a site named exactly `xx-YY` would fail closed
#: to pending, which is the safe direction.
_WORKDAY_LOCALE = re.compile(r"[a-z]{2}-[a-z]{2}", re.IGNORECASE)

#: Oracle Recruiting Cloud's candidate-experience pod, `{pod}.fa.{dc}.oraclecloud.com`
#: (Fortinet: `edel.fa.us2`). The `fa` label is the Fusion Applications tier; any
#: other oraclecloud.com host is not a careers site.
_ORACLE_HOST = re.compile(r"[a-z0-9][a-z0-9-]{0,63}\.fa\.[a-z0-9-]{1,63}\.oraclecloud\.com")
#: Oracle site numbers (`CX_2001`) and Avature portal segments (`careers`,
#: `en_US`) share Workday's shape: tenant-chosen, often underscored.
_SITE = _WORKDAY_SITE
#: An Avature portal's locale segment (`en_US`), underscored where Workday's is
#: hyphenated. Only ever the FIRST segment of a two-segment portal.
_AVATURE_LOCALE = re.compile(r"[a-z]{2}_[A-Z]{2}")
#: Avature template pages; the portal is everything before one of them.
_AVATURE_PAGES = {"SearchJobs", "JobDetail", "ApplicationMethods", "Register"}


class SurfaceReadiness(str, Enum):
    """Whether a recognised surface may be collected from today.

    Not a permission and not a review result — both of those live in
    `tracker/source_review.py`, and only `tracker/source_policy.py` can refuse a
    request. This says which of RoleBand's own connectors, if any, is entitled to
    be selected by a URL.
    """

    #: A connector exists, the family is onboarded, and a URL match selects it.
    COLLECTABLE = "collectable"
    #: Recognised, and that is all. No connector is selected, no binding is
    #: created and no company becomes `active`; the company stays `pending`
    #: exactly as an unrecognised URL would leave it.
    CANDIDATE = "candidate"


class DetectedSurface(NamedTuple):
    """What a careers URL is: provider, readiness, opaque identity, region.

    `identity` is provider-shaped and deliberately not a `board_token`. For a
    collectable family it is the one-element tuple `(token,)`, which
    `detect_ats()` unpacks. A candidate carries its parts UNJOINED, so a candidate cannot become a
    collectable board by assignment; it takes a deliberate change here.
    """

    provider: str
    readiness: SurfaceReadiness
    identity: tuple[str, ...]
    region: BoardRegion | None = None


class DetectedBoard(NamedTuple):
    """What a careers URL resolves to: connector, board token, and region.

    `region` is `None` for a single-deployment family (Greenhouse, Ashby,
    Google) and explicit for a multi-region one, so "this family has one host"
    stays distinguishable from "this tenant is on the global host". Lever runs
    separate namespaces per region and answers an identical 404 for a wrong
    region and a wrong token alike, so the region cannot be inferred later —
    see `BoardRegion`.
    """

    adapter: str
    board_token: str
    region: BoardRegion | None = None


def _token(value: str, pattern: re.Pattern[str] = _SLUG) -> str | None:
    if value.lower() in _NOISE or not pattern.fullmatch(value):
        return None
    if ".." in value or value.endswith("."):
        return None
    return value


def _collectable(
    provider: str, token: str | None, region: BoardRegion | None = None
) -> DetectedSurface | None:
    if not token:
        return None
    return DetectedSurface(provider, SurfaceReadiness.COLLECTABLE, (token,), region)


def detect_ats(url: str) -> DetectedBoard | None:
    """Resolve a supported careers URL to connector + token + region, else None.

    The collectable-only view of `detect_surface()`: a candidate surface is not
    an answer to "which connector may collect this", so it resolves to None here
    and the company stays pending.

    Recognized forms:
      Greenhouse: boards.greenhouse.io/{token}
                  job-boards.greenhouse.io/{token}
                  boards-api.greenhouse.io/v1/boards/{token}/...
                  boards.greenhouse.io/embed/job_board?for={token}
                  {token}.greenhouse.io
      Ashby:      jobs.ashbyhq.com/{name}
      Workable:   apply.workable.com/{account}
                  apply.workable.com/api/v1/widget/accounts/{account}
      SmartRecruiters: careers.smartrecruiters.com/{company}
                  jobs.smartrecruiters.com/{company}[/{posting}]
                  api.smartrecruiters.com/v1/companies/{company}
      Lever:      jobs.lever.co/{site}            -> global
                  jobs.eu.lever.co/{site}         -> EU
                  api.lever.co/v0/postings/{site} -> global
                  api.eu.lever.co/v0/postings/{site} -> EU
      DeepMind:   deepmind.google/careers -> Google Careers company=DeepMind
      Deel:       jobs.deel.com/{org}[/job-details/...]
      Oracle:     {pod}.fa.{dc}.oraclecloud.com/hcmUI/CandidateExperience/{lang}/sites/{site}
                  -> "{host}|{site}"
      Avature:    {tenant}.avature.net/[{locale}/]{portal}[/SearchJobs|/JobDetail/...]
                  -> "{host}|[{locale}/]{portal}"
    """
    surface = detect_surface(url)
    if surface is None or surface.readiness is not SurfaceReadiness.COLLECTABLE:
        return None
    (token,) = surface.identity
    return DetectedBoard(surface.provider, token, surface.region)


def detect_surface(url: str) -> DetectedSurface | None:
    """Resolve a careers URL to the surface it names, else None.

    Adds Workday to the collectable list in `detect_ats` (token "{host}|{site}"):
      Workday:    {tenant}.wd{N}.myworkdayjobs.com/{site}
                  {tenant}.wd{N}.myworkdayjobs.com/{lang-REGION}/{site}
                  .../{site}/job/...                      (posting deep-link)
                  .../wday/cxs/{tenant}/{site}/...        (the CXS endpoint)
                  wd{N}.myworkdaysite.com/[{ll-CC}/]recruiting/{tenant}/{site}
                  -> "{host}|{site}|{tenant}" (a shared host names no tenant)
    """
    if not url or not isinstance(url, str):
        return None
    raw = url.strip()
    # urllib strips some controls instead of rejecting them. Do not turn a
    # malformed input into a different company's apparently valid URL.
    if any(ord(char) <= 32 or ord(char) == 127 for char in raw):
        return None
    if "://" not in raw:
        raw = "https://" + raw
    try:
        parsed = urlparse(raw)
        host = (parsed.hostname or "").lower()
        port = parsed.port
    except ValueError:
        return None
    if (
        not host
        or parsed.scheme not in {"http", "https"}
        or parsed.username is not None
        or parsed.password is not None
        or port not in {None, 443 if parsed.scheme == "https" else 80}
        or parsed.params
    ):
        return None

    path = parsed.path.removeprefix("/").removesuffix("/")
    parts = path.split("/") if path else []
    if any(part in {"", ".", ".."} or "\\" in part for part in parts):
        return None
    query = parse_qs(parsed.query, keep_blank_values=True)

    if host in {"boards.greenhouse.io", "job-boards.greenhouse.io"}:
        if parts == ["embed", "job_board"]:
            values = query.get("for", [])
            token = _token(values[0]) if len(values) == 1 else None
        else:
            token = _token(parts[0]) if parts and "for" not in query else None
        return _collectable("greenhouse", token)

    if host == "boards-api.greenhouse.io":
        if len(parts) < 3 or parts[:2] != ["v1", "boards"] or "for" in query:
            return None
        return _collectable("greenhouse", _token(parts[2]))

    if host.endswith(".greenhouse.io"):
        # Single tenant subdomain owns identity; a job path cannot replace it.
        if "for" in query:
            return None
        return _collectable("greenhouse", _token(host.removesuffix(".greenhouse.io")))

    if host == "jobs.ashbyhq.com":
        return _collectable("ashby", _token(parts[0], _ASHBY_NAME) if parts else None)

    if host == "apply.workable.com":
        # Two forms name the account, and one form names nothing. The board is
        # `apply.workable.com/{account}`; the widget API the adapter fetches is
        # `/api/v1/widget/accounts/{account}`, read from its known position
        # rather than by hunting the path. A posting deep-link
        # `/j/{SHORTCODE}` identifies the POSTING and not the account, so it
        # resolves to nothing rather than to a token named `j`.
        if parts[:1] == ["j"]:
            return None
        if parts[:4] == ["api", "v1", "widget", "accounts"]:
            return _collectable("workable", _token(parts[4]) if len(parts) > 4 else None)
        return _collectable("workable", _token(parts[0]) if parts else None)

    if host in ("careers.smartrecruiters.com", "jobs.smartrecruiters.com"):
        # The board and a posting both name the company in the first segment
        # (`/{company}` and `/{company}/{posting}`), case-preserved: the
        # identifier is `ServiceNow`, not `servicenow`. Always the BOARD route;
        # route detection moves a company whose board is not on SmartRecruiters
        # to the API route at its first scan.
        return _collectable("smartrecruiters", _token(parts[0]) if parts else None)

    if host == "api.smartrecruiters.com":
        if parts[:2] == ["v1", "companies"] and len(parts) > 2:
            return _collectable("smartrecruiters", _token(parts[2]))
        return None

    if host in _LEVER_HOSTS:
        region = _LEVER_HOSTS[host]
        # Both the careers site (`jobs[.eu].lever.co/{site}`) and the postings
        # API (`api[.eu].lever.co/v0/postings/{site}`) name the tenant, and the
        # API form must be read from its known position rather than by hunting
        # the path for a plausible segment.
        if host.startswith("api."):
            if len(parts) < 3 or parts[:2] != ["v0", "postings"]:
                return None
            site = _token(parts[2])
        else:
            site = _token(parts[0]) if parts else None
        return _collectable("lever", site, region)

    if host == "deepmind.google" and parts == ["careers"]:
        return _collectable("google", "DeepMind")

    if host == "jobs.deel.com":
        # `/{org}` and `/{org}/job-details/{uuid}/...` both name the org first.
        # `/api/` is Deel's own API (robots disallows it), never an org.
        if not parts or parts[0].lower() == "api":
            return None
        return _collectable("deel", _token(parts[0]))

    if _ORACLE_HOST.fullmatch(host):
        # `/hcmUI/CandidateExperience/{lang}/sites/{site}[/...]`, read at its
        # known position. The token is `host|site`: the pod IS the tenant.
        if len(parts) < 5 or parts[:2] != ["hcmUI", "CandidateExperience"] or parts[3] != "sites":
            return None
        site = _token(parts[4], _SITE)
        return _collectable("oracle", f"{host}|{site}" if site else None)

    if host.endswith(".avature.net") and host.count(".") == 2:
        return _collectable("avature", _avature_token(host, parts))

    workday = _WORKDAY_HOST.fullmatch(host)
    if workday:
        return _workday_board(host, workday["tenant"], parts)

    if _WORKDAY_SHARED_HOST.fullmatch(host):
        return _workday_shared_board(host, parts)

    return None


def _workday_board(host: str, tenant: str, parts: list[str]) -> DetectedSurface | None:
    """`host|site` for a Workday tenant URL, or None if it names no site.

    Collectable: a user choosing a Workday company is the decision, and
    pasting its board is that choice. The
    source stays `user_directed`, so the scheduler still never collects it on
    its own (`scheduler.collectable_now`).

    The site is read from its known position in each documented form; the path
    is never searched for a plausible later segment. The CXS form
    additionally has to agree with the host about the tenant, because the
    adapter derives the CXS tenant from the host's first label — a URL where the
    two disagree is one this resolver cannot honestly name.
    """
    if parts[:2] == ["wday", "cxs"]:
        if len(parts) < 5 or parts[2] != tenant:
            return None
        site = _token(parts[3], _WORKDAY_SITE)
    else:
        index = 1 if len(parts) >= 2 and _WORKDAY_LOCALE.fullmatch(parts[0]) else 0
        site = _token(parts[index], _WORKDAY_SITE) if len(parts) > index else None
    return _collectable("workday", f"{host}|{site}" if site else None)


def _workday_shared_board(host: str, parts: list[str]) -> DetectedSurface | None:
    """`host|site|tenant` on a shared `myworkdaysite.com` host, or None.

    The host names no tenant, so the token must. Read at known
    positions: `[{ll-CC}/]recruiting/{tenant}/{site}[/...]`, or the CXS route
    `wday/cxs/{tenant}/{site}/...`. `/{tenant}/{site}` without `recruiting`
    answers 404 there and is not a board.
    """
    if parts[:2] == ["wday", "cxs"]:
        tenant, site = (parts[2], parts[3]) if len(parts) >= 5 else ("", "")
    else:
        index = 1 if parts and _WORKDAY_LOCALE.fullmatch(parts[0]) else 0
        if parts[index:index + 1] != ["recruiting"] or len(parts) < index + 3:
            return None
        tenant, site = parts[index + 1], parts[index + 2]
    tenant_ok = _token(tenant)
    site_ok = _token(site, _WORKDAY_SITE)
    if not tenant_ok or not site_ok:
        return None
    return _collectable("workday", f"{host}|{site_ok}|{tenant_ok}")


def _avature_token(host: str, parts: list[str]) -> str | None:
    """`host|portal` for an `{tenant}.avature.net` URL, or None.

    The portal is one segment (`careers`) or a locale and one (`en_US/careers`).
    It is read from the front, up to a template page (`SearchJobs`, `JobDetail`,
    ...) or the end of the path; anything longer is a page we cannot place, and
    fails closed rather than guessing which segments are the portal. A tenant on
    its own host (`jobs.ea.com`) carries no marker in its URL at all, so it is
    left to page detection.
    """
    end = next((i for i, part in enumerate(parts) if part in _AVATURE_PAGES), len(parts))
    portal = parts[:end]
    if not (len(portal) == 1 or (len(portal) == 2 and _AVATURE_LOCALE.fullmatch(portal[0]))):
        return None
    # Not `_token`: its noise words (`careers`, `jobs`) are exactly what
    # Avature tenants name their portals.
    if not all(_SITE.fullmatch(part) for part in portal):
        return None
    return f"{host}|{'/'.join(portal)}"


#: Page markers of the families whose tenant is on the tenant's own host, so the
#: URL alone cannot name them. Checked IN ORDER: a TalentBrew site that
#: applies through Avature (Synopsys) mentions both, and the page is
#: TalentBrew's. Eightfold, Greenhouse and a plain company careers page carry
#: none of the three.
_PAGE_MARKERS = (("jibe", "jibeapply"), ("radancy", "talentbrew"), ("avature", "portalpacks"))
#: Hosts whose page may mention another vendor's name without being that
#: vendor's board (`*.eightfold.ai` pages can say "talentbrew"). A family we
#: detect by URL is never detected by page.
_VENDOR_HOST_SUFFIXES = (".eightfold.ai", ".greenhouse.io", ".ashbyhq.com", ".lever.co",
                         ".myworkdayjobs.com", ".myworkdaysite.com", ".smartrecruiters.com",
                         ".workable.com", ".avature.net", ".icims.com", ".oraclecloud.com")


def detect_page(final_url: str, html: str) -> DetectedBoard | None:
    """The board a fetched careers page IS, read from the page's own markers.

    `final_url` is where the page was served after redirects; the tenant is
    that host, because these families serve each tenant from its own host
    (GitHub: `www.github.careers`). The token is built from the URL, never from
    page text: the page chooses only WHICH family, and that choice is verified
    against the family's own board route before anything activates (the page
    is attacker-influenced; `board_resolve.detect_by_page`).
    """
    surface = detect_surface(final_url)
    if surface is not None:
        return None  # a URL-detectable board is never re-decided by its page
    try:
        parsed = urlparse(final_url)
        host = (parsed.hostname or "").lower()
    except ValueError:
        return None
    if not host or host.endswith(_VENDOR_HOST_SUFFIXES) or parsed.scheme != "https":
        return None
    low = html.lower()
    for provider, marker in _PAGE_MARKERS:
        if marker not in low:
            continue
        if provider == "avature":
            path = parsed.path.removeprefix("/").removesuffix("/")
            token = _avature_token(host, path.split("/") if path else [])
        else:
            token = host
        return DetectedBoard(provider, token) if token else None
    return None
