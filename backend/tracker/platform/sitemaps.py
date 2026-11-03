"""Bounded sitemap graph traversal. No product or network policy decisions."""

from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from xml.etree import ElementTree


@dataclass(frozen=True)
class SitemapDocument:
    kind: str
    urls: tuple[str, ...]


def parse_sitemap(xml: str) -> SitemapDocument | None:
    try:
        root = ElementTree.fromstring(xml)
    except ElementTree.ParseError:
        return None
    kind = root.tag.rsplit("}", 1)[-1]
    if kind not in {"sitemapindex", "urlset"}:
        return None
    urls = tuple(dict.fromkeys(
        node.text.strip() for node in root.iter()
        if node.tag.rsplit("}", 1)[-1] == "loc" and node.text and node.text.strip()
    ))
    return SitemapDocument(kind, urls)


@dataclass(frozen=True)
class SitemapInventory:
    urls: tuple[str, ...]
    recognized: bool
    truncated: bool
    failures: tuple[str, ...]

    @property
    def complete(self) -> bool:
        return self.recognized and not self.truncated and not self.failures


async def walk_sitemaps(
    root: str,
    read: Callable[[str], Awaitable[str | None]],
    *,
    is_posting: Callable[[str], bool],
    accepts: Callable[[str], bool],
    max_documents: int = 21,
    max_postings: int = 1500,
) -> SitemapInventory:
    pending = deque([root])
    visited: set[str] = set()
    postings: dict[str, None] = {}
    failures: list[str] = []
    recognized = truncated = False
    while pending:
        url = pending.popleft()
        if url in visited:
            continue
        if len(visited) >= max_documents:
            truncated = True
            break
        visited.add(url)
        if not accepts(url):
            failures.append(f"sitemap destination rejected: {url}")
            continue
        body = await read(url)
        document = parse_sitemap(body) if body is not None else None
        if document is None:
            failures.append(f"unreadable sitemap: {url}")
            continue
        if url == root:
            recognized = True
        if document.urls and document.kind == "urlset" and not any(
            is_posting(loc) or loc.endswith(".xml") for loc in document.urls
        ):
            failures.append(f"sitemap names no postings: {url}")
        for loc in document.urls:
            posting = document.kind == "urlset" and is_posting(loc)
            # Some boards mix child documents and postings in a urlset.
            child = document.kind == "sitemapindex" or (not posting and loc.endswith(".xml"))
            if not (posting or child):
                continue  # a page that is not inventory (the board's own root): never read
            if not accepts(loc):
                failures.append(f"sitemap destination rejected: {loc}")
            elif child:
                pending.append(loc)
            elif loc not in postings and len(postings) >= max_postings:
                truncated = True
            else:
                postings[loc] = None
    return SitemapInventory(tuple(postings), recognized, truncated, tuple(failures))
