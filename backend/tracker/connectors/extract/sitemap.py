"""One sitemap source declaration for collection and safe token verification."""

import posixpath
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import unquote, urlsplit

import httpx

from tracker.platform.safe_fetch import BlockedDestination, check_url, fetch_public
from tracker.platform.sitemaps import SitemapInventory, walk_sitemaps


@dataclass(frozen=True)
class SitemapProbe:
    """What one bounded read of a sitemap root and its children established."""

    inventory: SitemapInventory
    #: The root's HTTP status. None = no usable response: transport error,
    #: refused destination, or a body past the size cap. Never a verdict alone.
    root_status: int | None


@dataclass(frozen=True)
class SitemapSource:
    root: str
    posting_id: Callable[[str], str | None]
    path_prefix: str = "/"

    def validate(self, url: str) -> None:
        candidate, root = urlsplit(check_url(url)), urlsplit(check_url(self.root))
        if (candidate.scheme, candidate.hostname, candidate.port or 443) != (
            root.scheme, root.hostname, root.port or 443
        ):
            raise BlockedDestination("URL is outside the sitemap's origin")
        # The tenant's own root, written without a trailing slash (`/acme`), is
        # inside the tenant; `/acmex/` is not.
        path = posixpath.normpath(unquote(candidate.path)) + "/"
        if self.path_prefix != "/" and not path.startswith(self.path_prefix):
            raise BlockedDestination("URL is outside the sitemap's tenant")

    def accepts(self, url: str) -> bool:
        try:
            self.validate(url)
        except (BlockedDestination, ValueError):
            return False
        return True

    async def probe(self, client: httpx.AsyncClient) -> SitemapProbe:
        statuses: dict[str, int | None] = {}

        async def read(url: str) -> str | None:
            try:
                page = await fetch_public(client, url, validate_url=self.validate)
            except (BlockedDestination, httpx.HTTPError, ValueError):
                statuses[url] = None
                return None
            statuses[url] = None if page.truncated else page.status
            return page.text if page.status == 200 and not page.truncated else None

        inventory = await walk_sitemaps(
            self.root, read, accepts=self.accepts,
            is_posting=lambda url: self.posting_id(url) is not None,
        )
        return SitemapProbe(inventory, statuses.get(self.root))
