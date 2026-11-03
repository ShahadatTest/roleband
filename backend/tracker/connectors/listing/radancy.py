"""Radancy TalentBrew career sites — multi-tenant.

    GET https://{host}/sitemap.xml            (the board: every posting URL)
    GET https://{host}/job/{city}/{slug}/{site}/{id}   (JSON-LD JobPosting)

TalentBrew is Radancy's hosted career site, served from the tenant's own host
and detected by a `talentbrew` page marker. Token = that host — Arm:
`careers.arm.com`.

Tenants disallow `/search-jobs/` in robots (Arm, Synopsys), which is the
search; the sitemap and the posting pages are allowed, and the sitemap
enumerates the whole board. The
category pages state no total server-side, so this is a `SitemapBoardAdapter`
— that module holds the listing rule, the completeness rule and the
fields this shape never reads, including `workHours`, where Arm puts its
**hiring manager's name**.

Arm's ATS behind TalentBrew is iCIMS (`experienced-arm.icims.com`), whose
robots is `Disallow: /`: walled, and not what this adapter reads.
"""

from __future__ import annotations

import re

from tracker.connectors.extract.sitemap import SitemapSource
from tracker.connectors.listing.base import BoardProbe, TenantMap
from tracker.connectors.listing.sitemap_board import SitemapBoardAdapter, sitemap_locs
from tracker.connectors.sdk import Capabilities
from tracker.schema import RawJob

_TENANTS = TenantMap({})
_JOB_URL = re.compile(r"/job/.+/(\d+)/?$")
#: `/job/{city}/{title-slug}/{site}/{id}`: the URL names the posting's title.
_JOB_PATH = re.compile(r"/job/([^/]+)/([^/]+)/\d+/(\d+)/?$")


def sitemap_url(host: str) -> str:
    host = host.strip().strip("/")
    if not host or "/" in host or "|" in host:
        raise ValueError(f"radancy board_token must be the careers host, got {host!r}")
    return f"https://{host}/sitemap.xml"


def posting_id(url: str) -> str | None:
    """TalentBrew posting URLs end in the site id and the posting id."""
    match = _JOB_URL.search(url)
    return match.group(1) if match else None


def url_title(url: str) -> tuple[str, str] | None:
    """(title, city) as the posting URL spells them, lowercased words: for
    reading likely matches first, never a posting's facts."""
    match = _JOB_PATH.search(url)
    if match is None:
        return None
    city, title = (part.replace("-", " ").strip() for part in match.group(1, 2))
    return (title, city) if title else None


def sitemap_links(xml: str) -> tuple[list[str], list[str]]:
    """(posting URLs, child sitemap URLs), deduplicated in document order."""
    locs = sitemap_locs(xml)
    return (
        [u for u in locs if posting_id(u) is not None],
        [u for u in locs if posting_id(u) is None and u.endswith(".xml")],
    )


class RadancyAdapter(SitemapBoardAdapter):
    name = "radancy"
    posted_date = "published"  # the sitemap board's `datePosted`
    board_probe = BoardProbe(
        jobs_url="https://{token}/sitemap.xml",
        tenants=_TENANTS,
        tenant_url=lambda token: sitemap_url(token),
        # The sitemap names postings, never the tenant: identity stays unstated
        # rather than guessed from a posting page the checker would have to pick.
        sitemap=lambda token: SitemapSource(sitemap_url(token), posting_id),
    )
    required_capabilities = Capabilities(stream=False, post=False, impersonate=False, render=False)

    @property
    def host(self) -> str:
        return _TENANTS.resolve(self.company, self.board_token).strip().strip("/")

    @property
    def sitemap_url(self) -> str:
        return sitemap_url(self.host)

    @property
    def tenant_identity(self) -> str:
        return self.host

    def url_hint(self, url: str) -> RawJob | None:
        named = url_title(url)
        if named is None:
            return None
        title, city = named
        return RawJob(company=self.company, req_id=posting_id(url) or url, title=title,
                      url=url, locations=[city] if city else [])

    def posting_id(self, url: str) -> str | None:
        return posting_id(url)
