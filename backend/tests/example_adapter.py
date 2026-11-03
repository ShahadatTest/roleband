"""A worked listing adapter, complete and offline: the one to copy.

`docs/development.md` §6.2 describes the seam and lists the steps that turn
this into a real adapter, each with the test that fails by name if you skip
it. This file is the same thing as code you can run. It is the shortest
adapter that is still honest: it pages through `paged_listing`, it stops on
the source's own signal, it turns a source's payload into `RawJob`s and lets
nothing source-shaped escape, and it records every row it cannot use.

**It lives in `tests/` on purpose and that is the whole safety argument.**
`tracker/` never imports `tests/`, so this cannot be discovered, scheduled or
run against a real board however it is registered, which is what "a fake
provider is test-only and cannot appear in production discovery or start live
work" means in practice. `test_contribution_rehearsal.py` proves each half.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable

from tracker.connectors.listing.base import BaseAdapter
from tracker.connectors.sdk import Capabilities
from tracker.schema import RawJob

#: Stands in for what the source serves. A real adapter never carries its
#: payload inline: it fetches, and its fixtures live under
#: `tests/fixtures/listings/<name>/`. Two pages, so paging is exercised rather
#: than described, and the second is short, which is how this source says "done".
EXAMPLE_PAGES: tuple[list[dict], ...] = (
    [
        {
            "id": "EX-1",
            "title": "Staff Software Engineer",
            "absolute_url": "https://boards.example.test/EX-1",
            "location": {"name": "Remote - United States"},
            "department": "Engineering",
        },
        {
            "id": "EX-2",
            "title": "Engineering Manager, Platform",
            "absolute_url": "https://boards.example.test/EX-2",
            "location": {"name": "London, UK"},
            "department": "Engineering",
        },
    ],
    [
        {
            "id": "EX-3",
            "title": "Principal Product Manager",
            "absolute_url": "https://boards.example.test/EX-3",
            "location": {"name": "New York, NY"},
            "department": "Product",
        }
    ],
)

#: What a full page holds. A page shorter than this is the last one: this
#: source declares no total, so its length IS the end-of-board signal.
PAGE_SIZE = 2
#: Backstop against a source that never serves a short page. `paged_listing`
#: records hitting it as `truncated`, our bound, never as the source's drift.
_MAX_PAGES = 50


class ExampleAdapter(BaseAdapter):
    """Turns one source's listing into `RawJob`s, and nothing else.

    A `RawJob` is provider-neutral (`tracker/schema.py`). Keeping the source's
    own shapes inside this module is what lets every layer above stay unaware of
    which ATS a posting came from.

    The class markers are read without running the adapter. `posted_date` is
    declared on every adapter's own class. The others keep their `BaseAdapter`
    defaults, because this source matches them: one listing reads the whole
    board (`listing_scope = "board"`), each row carries its posting
    (`detail = "inline"`, no `hydrate`), and the board states no count
    (`declares_total = False`). A source that differs declares the marker, and
    the contract suite in `tests/contracts/` holds each one to the code.
    """

    name = "example"
    posted_date = "none"  # the listing states no date; `published` or `created` when it does
    #: One buffered GET per page: no streaming, POST, impersonation or render.
    required_capabilities = Capabilities(stream=False, post=False, impersonate=False, render=False)

    async def fetch(self) -> AsyncIterator[RawJob]:
        async def fetch_page(index: int, stop: Callable[[], None]) -> list[dict]:
            # A real adapter awaits `self.context.fetch(FetchRequest(...))` here,
            # once per page. A page it cannot read is lost, unknown rows and
            # all: `self.drift.invalidate_listing(...)`, then `stop()`.
            page = list(EXAMPLE_PAGES[index]) if index < len(EXAMPLE_PAGES) else []
            if len(page) < PAGE_SIZE:
                # Short page = last page. A real adapter STOPS on the source's
                # own signal; looping until a page repeats is how a scan runs
                # forever, and the contract suite plants exactly that case.
                stop()
            return page

        async for row in self.paged_listing(
            fetch_page, max_pages=_MAX_PAGES, query_key="board", page_size=PAGE_SIZE
        ):
            job = self._to_raw_job(row)
            if job is not None:
                yield job

    def _to_raw_job(self, row: dict) -> RawJob | None:
        """One source row -> one `RawJob`, or None for a row we cannot use.

        A row we cannot use is skipped, never raised: an exception costs the
        whole page. What the skip records decides whether this run may still
        close postings (`docs/architecture.md`, "Incomplete is not broken"):

        * No id: the row could be any posting we hold, so no posting's absence
          from this listing proves it closed. `drift.drop_record` counts it as
          lost, which makes the listing incomplete, and an incomplete listing
          closes nothing.
        * An id but no title or url: the posting is on the board and cannot be
          built this run. `observe_unusable` records its key as present, so
          that posting stays open and the listing stays complete.

        Returning None without either call is the mistake to avoid: the
        listing reads as complete, and closure can close a live posting.
        """

        req_id = str(row.get("id") or "").strip()
        title = (row.get("title") or "").strip()
        url = (row.get("absolute_url") or "").strip()
        if not req_id:
            self.drift.drop_record("row missing id", keys=list(row)[:8])
            return None
        if not title or not url:
            self.observe_unusable(req_id, "row missing title/absolute_url", keys=list(row)[:8])
            return None

        location = (row.get("location") or {}).get("name")
        return RawJob(
            company=self.company,
            req_id=req_id,
            title=title,
            url=url,
            locations=[location] if location else [],
            department=(row.get("department") or None),
        )
