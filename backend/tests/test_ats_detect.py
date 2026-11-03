"""ATS detection from careers-page URLs — pure, no network."""

from __future__ import annotations

import httpx
import pytest

from tracker.ats_detect import detect_ats, detect_surface
from tracker.schema import BoardRegion


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://boards.greenhouse.io/stripe", ("greenhouse", "stripe", None)),
        ("https://boards.greenhouse.io/stripe/jobs/123", ("greenhouse", "stripe", None)),
        ("https://job-boards.greenhouse.io/databricks", ("greenhouse", "databricks", None)),
        ("https://boards-api.greenhouse.io/v1/boards/figma/jobs", ("greenhouse", "figma", None)),
        (
            "https://boards.greenhouse.io/embed/job_board?for=airbnb",
            ("greenhouse", "airbnb", None),
        ),
        ("https://coinbase.greenhouse.io/", ("greenhouse", "coinbase", None)),
        ("https://jobs.ashbyhq.com/Notion", ("ashby", "Notion", None)),
        ("https://jobs.ashbyhq.com/mistral.ai", ("ashby", "mistral.ai", None)),
        ("https://jobs.ashbyhq.com/mistral.ai/posting-id", ("ashby", "mistral.ai", None)),
        ("https://BOARDS.GREENHOUSE.IO/Acme", ("greenhouse", "Acme", None)),
        ("https://boards-api.greenhouse.io/v1/boards/Acme/jobs/123", ("greenhouse", "Acme", None)),
        ("https://boards.greenhouse.io/embed/job_board?for=Acme", ("greenhouse", "Acme", None)),
        ("https://coinbase.greenhouse.io/jobs/123", ("greenhouse", "coinbase", None)),
        ("https://jobs.ashbyhq.com/ramp/careers", ("ashby", "ramp", None)),
        ("https://deepmind.google/careers/", ("google", "DeepMind", None)),
        # protocol-less input is tolerated
        ("boards.greenhouse.io/lyft", ("greenhouse", "lyft", None)),
    ],
)
def test_detects_supported_ats(url, expected):
    """Compared as a tuple including the region, so every case has to state one.
    All of these are single-deployment families and every region is `None` —
    asserted rather than omitted, because `None` and `GLOBAL` are different
    records."""
    assert detect_ats(url) == expected


@pytest.mark.parametrize(
    "url",
    [
        "https://www.workday.com/en-us/company/careers.html",
        "https://careers.google.com/jobs",
        "https://example.com/careers",
        "not a url",
        "",
        "https://boards.greenhouse.io/",  # host only, no token
    ],
)
def test_unsupported_or_unparseable_returns_none(url):
    assert detect_ats(url) is None


@pytest.mark.parametrize(
    "url",
    [
        "https://notgreenhouse.io/acme",
        "https://notashbyhq.com/acme",
        "https://boards.greenhouse.io.evil.example/acme",
        "https://jobs.ashbyhq.com.evil.example/acme",
        "https://boards.greenhouse.io@evil.example/acme",
        "https://evil.example@boards.greenhouse.io/acme",
        "https://jobs.ashbyhq.com:8443/acme",
        "https://jobs.ashbyhq.com:bad/acme",
        "https://[broken/acme",
        "ftp://boards.greenhouse.io/acme",
        "https://jobs.ashbyhq.com/ac\nme",
        "https://jobs.ashbyhq.com/ac%2Fme",
        "https://jobs.ashbyhq.com/../acme",
        "https://jobs.ashbyhq.com//acme",
        "https://app.ashbyhq.com/acme",
        "https://boards.greenhouse.io/careers/acme",
        "https://jobs.ashbyhq.com/careers/acme",
        "https://boards-api.greenhouse.io/acme/jobs",
        "https://boards-api.greenhouse.io/v2/boards/acme/jobs",
        "https://boards.greenhouse.io/embed/job_board?for=acme&for=other",
        "https://boards.greenhouse.io/embed/job_board?for=",
        "https://boards.greenhouse.io/acme?for=other",
        "https://deepmind.google/about",
    ],
)
def test_ambiguous_or_deceptive_url_cannot_select_a_connector(url):
    assert detect_ats(url) is None


@pytest.mark.parametrize(
    "url",
    ["https://notgreenhouse.io/acme", "https://notashbyhq.com/acme"],
)
def test_deceptive_url_leaves_company_pending(url):
    from tracker.company_store import resolve_company

    fields = resolve_company(name="Review fixture", careers_url=url)
    assert fields["status"] == "pending"
    assert fields["adapter"] is None
    assert fields["board_token"] is None


@pytest.mark.asyncio
async def test_case_preserved_through_company_resolution_and_request():
    from tracker.company_store import resolve_company
    from tracker.connectors.listing import build_adapter

    fields = resolve_company(
        name="Review fixture", careers_url="https://jobs.ashbyhq.com/CaseSensitive.ai"
    )
    assert fields["board_token"] == "CaseSensitive.ai"
    adapter = build_adapter(fields["slug"], fields["adapter"], fields["board_token"])
    requests = []

    def serve_board(request):
        requests.append(request)
        return httpx.Response(200, json={"apiVersion": "1", "jobs": [
            {"id": "posting-1", "title": "Engineering Manager", "isListed": True},
        ]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(serve_board)) as client:
        adapter._client = client
        jobs = [job async for job in adapter.fetch()]
    assert [job.req_id for job in jobs] == ["posting-1"]
    assert len(requests) == 1
    assert requests[0].url.host == "api.ashbyhq.com"
    assert requests[0].url.path == "/posting-api/job-board/CaseSensitive.ai"


# -- Lever's regional deployments ---------------------------------- #
#
# Two hosts with SEPARATE tenant namespaces.
# `api.eu.lever.co/v0/postings/spotify` answers 404
# `{"ok":false,"error":"Document not found"}`, byte-identical to what the global
# host answers for a site name that exists nowhere. So a wrong region cannot be
# told from a wrong token after the fact, and recognising an EU URL while
# fetching the global host manufactures the dead-token failure:
# invalidated listing, scanned 0, `failed` -> ANOMALY, three of which quarantine
# the binding with no user-reachable exit.


@pytest.mark.parametrize("url,region", [
    ("https://jobs.lever.co/spotify", BoardRegion.GLOBAL),
    ("https://api.lever.co/v0/postings/spotify", BoardRegion.GLOBAL),
    ("https://jobs.eu.lever.co/someco", BoardRegion.EU),
    ("https://api.eu.lever.co/v0/postings/someco", BoardRegion.EU),
    ("https://JOBS.EU.LEVER.CO/someco", BoardRegion.EU),
])
def test_a_lever_url_resolves_its_region_explicitly(url, region):
    detected = detect_ats(url)

    assert detected is not None
    assert detected.adapter == "lever"
    assert detected.region is region


def test_the_site_name_survives_the_region(): 
    """The region must not be read out of the token, nor the token out of the
    host: `someco` on EU and `someco` on global are two different boards."""
    eu = detect_ats("https://jobs.eu.lever.co/Someco")
    glob = detect_ats("https://jobs.lever.co/Someco")

    assert eu.board_token == glob.board_token == "Someco"   # case preserved
    assert eu.region is not glob.region


@pytest.mark.parametrize("url", [
    "https://jobs.lever.co/",                     # no site
    "https://jobs.notlever.co/spotify",           # lookalike host
    "https://jobs.lever.co.evil.example/spotify", # suffix-attack host
    "https://notjobs.eu.lever.co/spotify",        # lookalike regional host
    "https://api.lever.co/spotify",               # token not at the known position
    "https://api.lever.co/v1/postings/spotify",   # wrong API version
    "https://api.eu.lever.co/v0/jobs/spotify",    # wrong path segment
    "https://jobs.lever.co/jobs",                 # a generic wrapper segment
])
def test_a_lever_url_that_does_not_identify_a_board_stays_pending(url):
    """Recognition requires exact hosts and known token positions, without
    hunting the path for a plausible later segment."""
    assert detect_ats(url) is None


def test_a_single_deployment_family_reports_no_region():
    """`None` is not `GLOBAL`. Greenhouse has one host, so recording `global`
    would assert a choice nobody made and make the column unable to tell a
    single-host family from a global tenant of a multi-region one."""
    assert detect_ats("https://boards.greenhouse.io/stripe").region is None
    assert detect_ats("https://jobs.ashbyhq.com/mistral.ai").region is None
    assert detect_ats("https://deepmind.google/careers").region is None


def test_detection_and_fetching_agree_on_what_a_region_means():
    """Two maps in two layers, and they must be exact inverses.

    Detection resolves host -> region (L4); the adapter resolves region -> host
    (L3), and L4 must not import a concrete adapter. So nothing structural stops
    them drifting, and a drift is silent in the worst way: an EU URL recognised
    as EU but fetched from a host the adapter maps differently answers the same
    404 as a dead token.
    """
    from tracker.ats_detect import _LEVER_HOSTS
    from tracker.connectors.listing.lever import REGION_HOSTS

    # Every region the adapter can fetch is one detection can produce.
    assert {r.value for r in _LEVER_HOSTS.values()} == set(REGION_HOSTS)
    # And every API host the adapter would call is recognised as that region.
    for region, host in REGION_HOSTS.items():
        assert _LEVER_HOSTS[host].value == region


# -- Workday: recognised, and recognition confers nothing --------- #
#
# Workday is recognised and nothing more: detection confers neither
# permission nor readiness. Workday is collected when a user chooses the
# company, and a pasted board IS that choice. The source stays `user_directed`, so nothing collects it automatically.


@pytest.mark.parametrize("url,host,site", [
    (
        "https://nvidia.wd5.myworkdayjobs.com/NVIDIAExternalCareerSite",
        "nvidia.wd5.myworkdayjobs.com", "NVIDIAExternalCareerSite",
    ),
    (   # the locale segment Workday's own links carry
        "https://nvidia.wd5.myworkdayjobs.com/en-US/NVIDIAExternalCareerSite",
        "nvidia.wd5.myworkdayjobs.com", "NVIDIAExternalCareerSite",
    ),
    (   # a posting deep-link: the site is still read from its known position
        "https://nvidia.wd5.myworkdayjobs.com/NVIDIAExternalCareerSite"
        "/job/US-CA-Santa-Clara/Senior-Manager_JR1993367",
        "nvidia.wd5.myworkdayjobs.com", "NVIDIAExternalCareerSite",
    ),
    (   # the CXS endpoint the adapter actually calls
        "https://nvidia.wd5.myworkdayjobs.com/wday/cxs/nvidia"
        "/NVIDIAExternalCareerSite/jobs",
        "nvidia.wd5.myworkdayjobs.com", "NVIDIAExternalCareerSite",
    ),
    (   # Another pod and an underscored site id: case is preserved.
        "https://acme.wd1.myworkdayjobs.com/Acme_External",
        "acme.wd1.myworkdayjobs.com", "Acme_External",
    ),
])
def test_a_workday_board_url_resolves_to_the_adapters_host_site_token(url, host, site):
    # `wd5` is a Workday pod, part of the host and therefore part of the token.
    # It is not a data-residency region in the Lever sense, and recording it as
    # one would put a second meaning in `BoardRegion`.
    assert detect_ats(url) == ("workday", f"{host}|{site}", None)


def test_the_detected_workday_token_is_the_one_the_adapter_scrapes():
    """A recognition that names the wrong tenant is worse than none, so the
    token is checked against the live tenant the adapter is configured for."""
    from tracker.connectors.listing.workday import WORKDAY_TENANTS

    detected = detect_ats("https://nvidia.wd5.myworkdayjobs.com/en-US/NVIDIAExternalCareerSite")
    assert detected.board_token == WORKDAY_TENANTS["nvidia"]


def test_a_pasted_workday_board_is_added_active_and_stays_user_directed():
    from tracker.company_store import resolve_company
    from tracker.source_review import SOURCE_REVIEWS

    fields = resolve_company(
        name="Workday Fixture",
        careers_url="https://acme.wd1.myworkdayjobs.com/Acme_External",
    )

    assert (fields["status"], fields["adapter"], fields["board_token"]) == (
        "active", "workday", "acme.wd1.myworkdayjobs.com|Acme_External",
    )
    assert fields["board_region"] is None
    # Added by the user, collected only when the user syncs: the scheduler's
    # automatic work skips a user-directed source.
    assert SOURCE_REVIEWS["workday"].user_directed


@pytest.mark.parametrize("url", [
    "https://www.workday.com/en-us/company/careers.html",  # the vendor's own site
    "https://myworkdayjobs.com/Acme_External",             # no tenant
    "https://nvidia.myworkdayjobs.com/Site",               # no pod label
    "https://nvidia.wdx.myworkdayjobs.com/Site",           # pod label is not numbered
    "https://nvidia.wd5-impl.myworkdayjobs.com/Site",      # implementation tenant
    "https://nvidia.wd5.myworkdayjobs.com.evil.example/Site",
    "https://notmyworkdayjobs.com/Site",
    "https://nvidia.wd5.myworkdayjobs.com",                # host only, no site
    "https://nvidia.wd5.myworkdayjobs.com/en-US",          # locale, no site
    "https://nvidia.wd5.myworkdayjobs.com/wday/cxs/other/Site/jobs",  # tenant disagrees
    "https://nvidia.wd5.myworkdayjobs.com/wday/cxs/nvidia/Site",      # short of the site
])
def test_a_url_that_does_not_identify_a_workday_tenant_is_recognised_as_nothing(url):
    """Fails closed in the same direction as every other family: an
    unrecognised URL is pending, never a guess at a tenant."""
    assert detect_surface(url) is None
    assert detect_ats(url) is None


def test_a_collectable_family_reports_its_readiness_too():
    """The readiness is a property of every surface: `detect_ats` is the
    collectable-only view of one resolver."""
    from tracker.ats_detect import SurfaceReadiness

    surface = detect_surface("https://boards.greenhouse.io/stripe")

    assert surface.provider == "greenhouse"
    assert surface.readiness is SurfaceReadiness.COLLECTABLE
    assert surface.identity == ("stripe",)
    assert detect_ats("https://boards.greenhouse.io/stripe") == ("greenhouse", "stripe", None)


# --- Further ATS families ---------------------------------------- #


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://jobs.deel.com/klarna", ("deel", "klarna", None)),
        ("https://jobs.deel.com/klarna/job-details/0b5e-4c1a-9f2d-77aa/overview", ("deel", "klarna", None)),
        (
            "https://edel.fa.us2.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_2001",
            ("oracle", "edel.fa.us2.oraclecloud.com|CX_2001", None),
        ),
        (
            "https://edel.fa.us2.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_2001/job/12345",
            ("oracle", "edel.fa.us2.oraclecloud.com|CX_2001", None),
        ),
        ("https://synopsys.avature.net/careers", ("avature", "synopsys.avature.net|careers", None)),
        (
            "https://synopsys.avature.net/careers/SearchJobs/?jobOffset=20",
            ("avature", "synopsys.avature.net|careers", None),
        ),
        (
            "https://synopsys.avature.net/careers/JobDetail/Staff-Engineer/12345",
            ("avature", "synopsys.avature.net|careers", None),
        ),
        (
            "https://acme.avature.net/en_US/careers/SearchJobs",
            ("avature", "acme.avature.net|en_US/careers", None),
        ),
    ],
)
def test_detects_the_families_built_since_url_detection(url, expected):
    assert detect_ats(url) == expected


@pytest.mark.parametrize(
    "url",
    [
        "https://jobs.deel.com/",                      # no org
        "https://jobs.deel.com/api/eor/jobs",          # Deel's own API, not an org
        "https://jobs.deel.com.evil.example/klarna",
        "https://edel.fa.us2.oraclecloud.com/",        # pod, no site
        "https://edel.fa.us2.oraclecloud.com/hcmUI/CandidateExperience/en/sites",
        "https://edel.fa.us2.oraclecloud.com/hcmUI/Other/en/sites/CX_2001",
        "https://www.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_2001",  # not an fa pod
        "https://edel.fa.us2.oraclecloud.com.evil.example/hcmUI/CandidateExperience/en/sites/CX_2001",
        "https://acme.avature.net/",                   # no portal
        "https://acme.avature.net/a/b/c",              # a page we cannot place
        "https://x.acme.avature.net/careers",          # not a tenant host
        "https://avature.net/careers",
        "https://jobs.ea.com/en_US/careers/SearchJobs",  # Avature on its own host: page detection
    ],
)
def test_phase_c_forms_fail_closed(url):
    assert detect_ats(url) is None


def _board_url(adapter: str, token: str) -> str | None:
    """The page a user would paste for a catalog row, built from its token."""
    if adapter == "deel":
        return f"https://jobs.deel.com/{token}"
    host, _, rest = token.partition("|")
    if adapter == "oracle":
        return f"https://{host}/hcmUI/CandidateExperience/en/sites/{rest}/requisitions"
    if adapter == "avature" and host.endswith(".avature.net"):
        return f"https://{host}/{rest}/SearchJobs/"
    if adapter == "workday":
        site, _, tenant = rest.partition("|")
        if tenant:  # a shared host names its tenant in the path
            return f"https://{host}/en-US/recruiting/{tenant}/{site}"
        return f"https://{host}/en-US/{site}"
    return None


def test_a_pasted_board_resolves_to_the_token_its_catalog_row_scrapes():
    """Detection is only right if it produces the token the adapter really
    uses. Every catalog row on these families, pasted as its board page, must
    resolve back to its own token — so a family's token shape cannot drift
    from what its detector builds."""
    from tracker.company_catalog import CATALOG

    checked = []
    for slug, entry in CATALOG.items():
        url = _board_url(entry["adapter"], entry["board_token"])
        if url is None:
            continue
        assert detect_ats(url) == (entry["adapter"], entry["board_token"], None), slug
        checked.append(slug)
    assert {"klarna", "fortinet", "synopsys", "salesforce", "asml", "snap"} <= set(checked)


def test_a_detected_phase_c_board_is_added_active():
    from tracker.company_store import resolve_company
    from tracker.connectors import build_adapter

    fields = resolve_company(name="Klarna Fixture", careers_url="https://jobs.deel.com/klarnafixture")
    assert (fields["status"], fields["adapter"], fields["board_token"]) == ("active", "deel", "klarnafixture")
    # And the adapter accepts what detection stored.
    adapter = build_adapter(fields["slug"], fields["adapter"], board_token=fields["board_token"])
    assert adapter.board_probe.url_for(fields["board_token"]) == "https://jobs.deel.com/klarnafixture/sitemap.xml"


@pytest.mark.parametrize("url", [
    "https://wd1.myworkdaysite.com/recruiting/snapchat/snap",
    "https://wd1.myworkdaysite.com/en-US/recruiting/snapchat/snap",
    "https://wd1.myworkdaysite.com/recruiting/snapchat/snap/job/London-United-Kingdom/Accountant_R0046881-1",
    "https://wd1.myworkdaysite.com/wday/cxs/snapchat/snap/jobs",
])
def test_a_shared_workday_host_names_its_tenant_in_the_token(url):
    """`wd1.myworkdaysite.com` serves several employers: the host's first label
    ("wd1") is not the tenant, so the token carries it."""
    from tracker.connectors.listing.workday import cxs_jobs_url

    detected = detect_ats(url)
    assert detected == ("workday", "wd1.myworkdaysite.com|snap|snapchat", None)
    assert cxs_jobs_url(detected.board_token) == (
        "https://wd1.myworkdaysite.com/wday/cxs/snapchat/snap/jobs"
    )


@pytest.mark.parametrize("url", [
    "https://wd1.myworkdaysite.com/snapchat/snap",            # 404s live: not a board
    "https://wd1.myworkdaysite.com/recruiting/snapchat",      # no site
    "https://wd1.myworkdaysite.com/",
    "https://wd1.myworkdaysite.com/wday/cxs/snapchat/snap",   # short of the route
    "https://x.wd1.myworkdaysite.com/recruiting/a/b",
    "https://wd1.myworkdaysite.com.evil.example/recruiting/snapchat/snap",
])
def test_a_shared_workday_url_that_names_no_board_is_nothing(url):
    assert detect_ats(url) is None
