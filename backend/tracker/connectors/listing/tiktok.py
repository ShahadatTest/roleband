"""TikTok: the search API its own careers site calls.

    POST https://api.lifeattiktok.com/api/v1/public/supplier/search/job/posts
    GET  https://lifeattiktok.com/search/{id}

`lifeattiktok.com/search` renders its results client-side
from this API; the site's own fetch wrapper sends `website-path: tiktok`, and
without that header the API answers 400 `invalid request` (an `origin` alone
is not enough). The body pages by `offset`/`limit`; `data.count` states the
board's size, identical on every page, and a walk at 500 a page reads every
id, with no result window below the board's size.

**A row is a whole posting.** Title, `description` and `requirement` arrive in
full with the listing, and the place as a chain: `city_info` (city) ->
`parent` (state) -> `parent` (country), one place per posting. The chain is
joined with repeats dropped, so "Singapore, Singapore, Singapore" reads as
"Singapore" and "Seoul, Seoul, Korea, Republic of" as "Seoul, Korea, Republic
of". The rows never name the employer: the board is TikTok's by the header and
the host, and some of its rows are ByteDance, Lark or CapCut roles it posts.

**Detail is pay only.** Salary fields in the listing's `job_post_info` are null
on every row; the posting page states a US posting's band under "Compensation
Description" ("The base salary range ... is $<min> - $<max> annually").
Hydrate reads that block and nothing else.

Robots: `careers.tiktok.com/robots.txt` 302s to `lifeattiktok.com/robots.txt`,
which disallows `/referral/` for `*` only; `api.lifeattiktok.com/robots.txt`
is empty.
"""

from __future__ import annotations

import html
import json
from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime

from selectolax.lexbor import LexborHTMLParser as HTMLParser
from selectolax.lexbor import LexborNode as Node

from tracker.connectors.listing.base import BaseAdapter, BoardProbe, TenantMap
from tracker.connectors.sdk import Capabilities, FetchRequest
from tracker.schema import (
    AccessSurface,
    CompensationFacts,
    EmploymentType,
    RawJob,
    RetrievalState,
    SourceJobFacts,
    SourceLocation,
)

SEARCH_URL = "https://api.lifeattiktok.com/api/v1/public/supplier/search/job/posts"
POSTING_URL = "https://lifeattiktok.com/search/{id}"
#: The site's own fetch wrapper sends this; the API refuses a request without it.
HEADERS = {"website-path": "tiktok"}
_TENANTS = TenantMap({})
#: Rows a page. The site asks for 10; 500 answers whole, and
#: fewer pages is both lighter on the host and a shorter window for the
#: unsorted listing to shift under the walk.
PAGE_SIZE = 500
_MAX_PAGES = 30  # 15,000 postings at 500 a page


def search_body(offset: int, limit: int = PAGE_SIZE) -> dict[str, object]:
    return {
        "recruitment_id_list": [], "job_category_id_list": [], "subject_id_list": [],
        "location_code_list": [], "keyword": "", "limit": limit, "offset": offset,
    }


def declared_total(page: str) -> int | None:
    """`data.count` from a search answer, or None if it is not one."""
    try:
        payload = json.loads(page)
    except ValueError:
        return None
    data = payload.get("data") if isinstance(payload, dict) else None
    count = data.get("count") if isinstance(data, dict) else None
    return count if isinstance(count, int) and not isinstance(count, bool) else None


def place_label(city: object) -> str | None:
    """The city -> state -> country chain as one place, repeats dropped."""
    names: list[str] = []
    node = city
    while isinstance(node, dict):
        name = (node.get("en_name") or "").strip()
        if name and name not in names:
            names.append(name)
        node = node.get("parent")
    return ", ".join(names) or None


_EMPLOYMENT = {"Regular": EmploymentType.FULL_TIME, "Intern": EmploymentType.INTERN}


def _name(node: object) -> str | None:
    if isinstance(node, dict):
        name = (node.get("en_name") or "").strip()
        return name or None
    return None


class TikTokAdapter(BaseAdapter):
    name = "tiktok"
    posted_date = "none"  # the listing states no date
    detail = "per_posting"  # `hydrate` reads each kept posting's text
    # Its text is inline; the page adds only pay, into the listing's payload.
    text_from_posting = False
    #: The search states `data.count` on every page.
    declares_total = True
    board_probe = BoardProbe(
        jobs_url=SEARCH_URL,
        tenants=_TENANTS,
        # One company, one fixed route: the token names nothing.
        tenant_url=lambda _token: SEARCH_URL,
        method="POST",
        probe_body=search_body(0, limit=1),
        probe_headers=HEADERS,
        read_count=declared_total,
    )
    required_capabilities = Capabilities(stream=False, post=True, impersonate=False, render=False)

    async def fetch(self) -> AsyncIterator[RawJob]:
        declared: int | None = None
        jobs: dict[str, RawJob] = {}
        self._completed_rows = jobs.values

        async def fetch_page(index: int, stop: Callable[[], None]) -> list[dict]:
            nonlocal declared
            resp = await self.context.fetch(FetchRequest(
                url=SEARCH_URL, method="POST", headers=HEADERS,
                json_body=search_body(index * PAGE_SIZE), source_key=self.company,
            ))
            if resp.status != 200:
                self.drift.invalidate_listing("search page failed", page=index + 1, status=resp.status)
                stop()
                return []
            try:
                payload = resp.json()
                if not isinstance(payload, dict):
                    raise TypeError("the search answered no object")
                data = payload["data"]
                rows = data["job_post_list"] or []
            except (ValueError, KeyError, TypeError):
                self.drift.invalidate_listing("search page is not a result list", page=index + 1)
                stop()
                return []
            if declared is None:
                declared = declared_total(resp.text())
            if len(rows) < PAGE_SIZE or (declared is not None and (index + 1) * PAGE_SIZE >= declared):
                stop()
            return rows

        async for row in self.paged_listing(
            fetch_page, max_pages=_MAX_PAGES, query_key="search", declared_total=lambda: declared,
            page_size=PAGE_SIZE,
        ):
            job = self._job(row)
            if job is None:
                continue
            jobs.setdefault(job.req_id, job)

        self.drift.require(bool(jobs), "empty job list")
        self.close_listing(declared=declared, unique=len(jobs), field="the search's `data.count`")
        for key, job in list(jobs.items()):
            yield job
            jobs.pop(key)

    def _job(self, row: dict) -> RawJob | None:
        posting_id = str(row.get("id") or "").strip()
        title = (row.get("title") or "").strip()
        if not posting_id or not title:
            self.drift.drop_record("row without id or title", req=posting_id or None)
            return None
        place = place_label(row.get("city_info"))
        track = _name(row.get("recruit_type"))
        texts = [text for text in (row.get("description"), row.get("requirement"))
                 if isinstance(text, str) and text.strip()]
        return RawJob(
            company=self.company,
            req_id=posting_id,
            title=title,
            url=POSTING_URL.format(id=posting_id),
            locations=[place] if place else [],
            department=_name(row.get("job_category")),
            description_html="".join(
                f"<p>{html.escape(text).replace(chr(10), '<br>')}</p>" for text in texts
            ) or None,
            description_complete=bool(texts),
            # The row's own fields: `detail/tiktok.py` builds the sections from
            # them, and reads a band only from the `pay` hydrate adds.
            detail_payload={"description": row.get("description"), "requirement": row.get("requirement")},
            source_facts=SourceJobFacts(
                provider=self.name,
                access_surface=AccessSurface.UNDOCUMENTED_ENDPOINT,
                tenant_identity="lifeattiktok.com",
                posting_id=posting_id,
                requisition_label=(row.get("code") or None),
                # "Regular", "Intern", "Third-party Associate" (agency staff:
                # not TikTok's own contract).
                employment_type_raw=track,
                employment_type_normalized=_EMPLOYMENT.get(track or "", EmploymentType.UNKNOWN),
                locations=[SourceLocation(label=place, is_primary=True)] if place else [],
                compensation=CompensationFacts(state=RetrievalState.NOT_REQUESTED),
                observed_at=datetime.now(UTC),
            ),
        )

    async def hydrate(self, job: RawJob) -> None:
        resp = await self.context.fetch(FetchRequest(url=job.url, source_key=self.company))
        if resp.status != 200:
            self.drift.note("posting page failed", req=job.req_id, status=resp.status)
            return
        pay = pay_block(resp.text())
        if pay is not None and isinstance(job.detail_payload, dict):
            job.detail_payload = {**job.detail_payload, "pay": pay}


def pay_block(page: str) -> str | None:
    """The text under the posting page's "Compensation Description" heading."""
    for heading in HTMLParser(page).css("p"):
        if "Compensation Description" not in heading.text():
            continue
        body: Node | None = heading.next
        while body is not None and body.tag in {"-text", "-comment"}:
            body = body.next
        if body is None:
            return None
        text = "\n".join(
            line.strip(" ​") for line in body.text(separator="\n").splitlines()
        )
        text = "\n".join(line for line in text.splitlines() if line)
        return text or None
    return None
