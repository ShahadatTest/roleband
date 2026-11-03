"""Generic bounded pagination over an async page fetcher.

One bounded loop for every listing adapter: terminate on empty page, page-count ceiling, or a cycle (a page that yields
nothing new), so a drifting source can never spin an adapter forever.

`expand_saturated` is the companion for the other end of the same problem: a
query whose declared total is really the source's result window is not a
listing at all, and no amount of paging will finish it.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable, Hashable, Sequence
from dataclasses import dataclass
from enum import Enum

#: Never tune a query below this many pages. A board that briefly returns one
#: page must not leave a bound that cannot survive its own recovery.
MAX_PAGES_FLOOR = 8
#: The published `RECIPE_V1_SCHEMA` maximum. A learned bound may not exceed the
#: value a hand-written recipe is allowed to declare — auto-tuning moves inside
#: operator limits, never past them.
MAX_PAGES_HARD = 1000


class StopReason(str, Enum):
    """Why one query's pagination ended.

    The distinction that matters is `CEILING`/`FRONTIER` versus everything else:
    they are the values meaning *we* stopped the source, and therefore the only
    ones whose page count is censored rather than measured. Everything
    downstream that treats a bound differently from the source's own behavior
    keys off this.
    """

    #: The fetcher called ``stop()`` — declared total reached, or a deliberate abort.
    STOPPED = "stopped"
    #: A page came back empty; the listing ran dry on its own.
    EXHAUSTED = "exhausted"
    #: OUR page ceiling cut a listing that was still serving items.
    CEILING = "ceiling"
    #: A discovery probe paged back into rows it already knew, so there was
    #: nothing newer to find. Also our stop, and also censored — the listing was
    #: still serving — but unlike CEILING it is the HEALTHY outcome: it means the
    #: probe reached the frontier instead of running out of allowance before it.
    FRONTIER = "frontier"

    @property
    def is_natural(self) -> bool:
        """True when the source, not our bound, ended the scan."""
        return self is not StopReason.CEILING


@dataclass(frozen=True)
class QueryObservation:
    """What one query did on one run — the unit per-binding tuning learns from.

    Lives here rather than beside the tuner so an adapter can record one without
    importing a workflow: this module imports no other tracker module and must
    keep doing so.
    """

    query_key: str
    pages_used: int
    items: int
    stop_reason: StopReason
    #: The ceiling in force for this query on this run — what `CEILING` was
    #: censored *by*, and so what an escalation multiplies.
    ceiling: int
    #: The source's own count for this query, when it declared one.
    declared_total: int | None = None
    #: Page size, needed to turn a declared total into a page count.
    page_size: int | None = None


async def paginate[T](
    fetch_page: Callable[[int], Awaitable[Sequence[T]]],
    *,
    max_pages: int,
    start: int = 0,
    dedupe_key: Callable[[T], Hashable] | None = None,
    on_repeat: Callable[[int], None] | None = None,
) -> AsyncIterator[T]:
    """Yield items from ``fetch_page(page_index)`` for pages ``start..max_pages-1``.

    Stops early on an empty page. With ``dedupe_key``, items already seen
    are skipped; a page containing only repeats stops iteration (cycle guard)
    after calling ``on_repeat(page_index)`` so the caller can record drift.
    """
    seen: set[Hashable] = set()
    for page_index in range(start, max_pages):
        items = await fetch_page(page_index)
        if not items:
            return
        yielded_any = False
        for item in items:
            if dedupe_key is not None:
                key = dedupe_key(item)
                if key in seen:
                    continue
                seen.add(key)
            yielded_any = True
            yield item
        if dedupe_key is not None and not yielded_any:
            if on_repeat is not None:
                on_repeat(page_index)
            return


async def expand_saturated[Q](
    roots: Sequence[Q],
    *,
    declared_total: Callable[[Q], Awaitable[int | None]],
    refine: Callable[[Q], Sequence[Q]],
    window: int,
    max_depth: int = 1,
) -> list[Q]:
    """Replace every root query that saturates ``window`` with its refinements.

    A source's declared total is a *count* only while it stays below the result
    window that source will serve. At or above it, the number is the window and
    the query is a view, not a listing: paging it collects the first ``window``
    rows and can never reach the rest, so treating it as complete would
    authorize closing every posting the window hides. The answer is
    to ask a narrower question — ``refine`` supplies the source's own declared
    facet values, and each leaf that fits under the window pages to a true
    natural stop.

    Only nodes that could still be *split* are probed: a node is probed, and if
    it saturates and depth remains it is replaced by ``refine(node)``, whose
    children are probed in turn. At ``max_depth`` the children are returned
    unprobed, because a leaf that is paged normally reports its own total on
    its first page — one request per internal node, not per leaf. For a single
    root split one level wide that is exactly one extra request.

    Fails safe in both directions. An unknown total (``None``, e.g. the probe
    errored) is not evidence of saturation, so the node is kept whole and paged
    as it is. A node with no refinements, or one still saturated at the depth
    cap, is returned as a leaf — the caller pages it and records ``truncated``,
    which is honest rather than a false claim of completeness.
    """
    frontier = list(roots)
    leaves: list[Q] = []
    for _ in range(max_depth):
        if not frontier:
            break
        next_frontier: list[Q] = []
        for node in frontier:
            total = await declared_total(node)
            if total is None or total < window:
                leaves.append(node)
                continue
            children = list(refine(node))
            if not children:
                leaves.append(node)
                continue
            next_frontier.extend(children)
        frontier = next_frontier
    # Whatever the depth cap left unresolved is paged as-is.
    leaves.extend(frontier)
    return leaves
