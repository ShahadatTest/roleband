"""Deel job boards — multi-tenant.

    GET https://jobs.deel.com/{org}/sitemap.xml    (the board: every posting)
    GET https://jobs.deel.com/{org}/job-details/{uuid}/overview  (JSON-LD)

Deel hosts every tenant's board on one host under the org slug, which is the
token — Klarna: `klarna` (linked from `klarna.com/careers`).

`jobs.deel.com/robots.txt` allows `/` and disallows exactly two things: `/api/`
and `/*/job-details/*/application`. The board PAGE renders its list from that
disallowed API, so the allowed route is the one robots points at in its own
comment — the per-org sitemap ("Per-org sitemaps are available at
/<orgSlug>/sitemap.xml") — and then each posting page, whose JSON-LD carries
title, `datePosted`, `employmentType` (schema.org's own words), `jobLocation`
and the whole description. The adapter requests neither the API nor an
application URL.

A `SitemapBoardAdapter`: that module holds the listing rule (the
sitemap is the inventory), the completeness rule (a listed id is never lost)
and the fields this shape never reads.

The board page states no tenant name a checker could trust (its title is
Deel's own marketing line), so identity stays `unstated` rather than guessed.
"""

from __future__ import annotations

import re

from tracker.connectors.extract.sitemap import SitemapSource
from tracker.connectors.listing.base import BoardProbe, TenantMap
from tracker.connectors.listing.sitemap_board import SitemapBoardAdapter, sitemap_locs
from tracker.connectors.sdk import Capabilities
from tracker.schema import AccessSurface

HOST = "https://jobs.deel.com"
_TENANTS = TenantMap({})
#: `/{org}/job-details/{uuid}/overview`; the uuid is the Deel ATS posting id.
_JOB_URL = re.compile(r"/job-details/([0-9a-f-]{16,})(?:/|$)", re.I)


def sitemap_url(org: str) -> str:
    org = org.strip().strip("/")
    if not org or "/" in org or "|" in org:
        raise ValueError(f"deel board_token must be the org slug, got {org!r}")
    return f"{HOST}/{org}/sitemap.xml"


def posting_id(url: str) -> str | None:
    match = _JOB_URL.search(url)
    return match.group(1) if match else None


def posting_urls(xml: str) -> list[str]:
    return [u for u in sitemap_locs(xml) if posting_id(u) is not None]


class DeelAdapter(SitemapBoardAdapter):
    name = "deel"
    posted_date = "published"  # the sitemap board's `datePosted`
    access_surface = AccessSurface.HTML
    board_probe = BoardProbe(
        jobs_url=f"{HOST}/{{token}}/sitemap.xml",
        tenants=_TENANTS,
        tenant_url=lambda token: sitemap_url(token),
        sitemap=lambda token: SitemapSource(sitemap_url(token), posting_id, f"/{token}/"),
    )
    required_capabilities = Capabilities(stream=False, post=False, impersonate=False, render=False)

    @property
    def org(self) -> str:
        return _TENANTS.resolve(self.company, self.board_token).strip().strip("/")

    @property
    def tenant_identity(self) -> str:
        return self.org

    @property
    def sitemap_url(self) -> str:
        return sitemap_url(self.org)

    def posting_id(self, url: str) -> str | None:
        return posting_id(url)
