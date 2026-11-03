"""Reading a source's own payload: JSON values, and JSON-LD embedded in a page.

`job_posting` reads every shape a board serves (a bare object, an array, an
`@graph`) and parses leniently. "This page carries no posting" is a legitimate
answer, so it must only ever be given about the page, never because the reader
skipped the shape the page uses.
"""

from __future__ import annotations

import json

from selectolax.lexbor import LexborHTMLParser as HTMLParser

__all__ = ["job_posting", "text_of"]

_LD_SELECTOR = 'script[type="application/ld+json"]'


def text_of(value: object) -> str | None:
    """A payload value as text, with blank and absent treated alike.

    An employer who sends `""` and one who sends nothing have said the same
    thing, and a caller that has to distinguish them reads the raw value.
    """
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _types(entry: object) -> tuple[str, ...]:
    """`@type` is a string or a list of them — schema.org permits both, and a
    posting that also declares another type is still a posting."""
    if not isinstance(entry, dict):
        return ()
    declared = entry.get("@type")
    if isinstance(declared, str):
        return (declared,)
    if isinstance(declared, list):
        return tuple(t for t in declared if isinstance(t, str))
    return ()


def _entries(data: object):
    """Every node a document can hold a posting in: the document itself, the
    array form, and `@graph` (which a CMS emits when one page describes several
    things — the posting, the employer, the breadcrumbs)."""
    for node in data if isinstance(data, list) else [data]:
        if not isinstance(node, dict):
            continue
        yield node
        graph = node.get("@graph")
        if isinstance(graph, list):
            yield from (item for item in graph if isinstance(item, dict))


def job_posting(page: str) -> dict | None:
    """The page's schema.org `JobPosting`, or None if it carries none.

    Parsed with `strict=False`: employers paste job descriptions into JSON
    strings with raw control characters in them, and refusing the document over
    a stray tab loses a posting that is otherwise complete.
    """
    for node in HTMLParser(page or "").css(_LD_SELECTOR):
        try:
            data = json.loads(node.text(), strict=False)
        except ValueError:
            continue
        for entry in _entries(data):
            if "JobPosting" in _types(entry):
                return entry
    return None
