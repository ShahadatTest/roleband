"""Google — careers SSR HTML (no public JSON API).

We GET the results page and parse job cards from the server-rendered HTML,
anchoring on stable hooks (aria-label, material-icon labels) because CSS class
names are obfuscated and rotate. Results stay unfiltered by level so every
user-selectable seniority band remains observable downstream.
Descriptions come from the detail page's schema.org JobPosting JSON-LD (hydrate).

Google DeepMind's careers page delegates to this same endpoint with
``company=DeepMind``. Its company-filtered results do not support Google's
``target_level`` filter, so downstream title classification handles seniority
for token-backed company boards.
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator, Callable

from selectolax.lexbor import LexborHTMLParser as HTMLParser
from selectolax.lexbor import LexborNode as Node

from tracker.connectors.listing.base import BaseAdapter, country_manifest
from tracker.platform.util import clean_location, without_query
from tracker.schema import RawJob, WorkplaceType
from tracker.taxonomy.locations import countries_for

_RESULTS = "https://www.google.com/about/careers/applications/jobs/results"
# Pure backstop against a source that neither declares a total nor runs dry.
# Sized well above the largest total google serves (the unfiltered board), so a
# query's growth never puts its last page over the ceiling and truncates the
# binding.
_MAX_PAGES = 400
# Rows per results page. Not a request parameter — google fixes it — so this is
# a recorded observation of the source, used only to turn a declared total into
# a page count for tuning.
_PAGE = 20

# Human location strings Google's `location=` param understands. Covers our geos.
#
# A metro query adds nothing to its country's: `location` unions up to five
# values, and the union of a country with its metros equals the country alone.
#
# Every country by its display name. Google's `location` filter is free text,
# regional rather than per-city (`United Kingdom` and `London, UK` return the
# same postings), and fails closed — a nonsense value returns no
# total at all. So the term rule is uniform and the manifest is generated.
GOOGLE_LOCATION_QUERIES: dict[str, list[str]] = country_manifest(lambda c: c.query_name)
#: Flattened manifest — the full query vocabulary, scope-independent.
GOOGLE_LOCATIONS = [term for terms in GOOGLE_LOCATION_QUERIES.values() for term in terms]
_TERM_COUNTRY = {term: slug for slug, terms in GOOGLE_LOCATION_QUERIES.items() for term in terms}
_JOB_HREF_RE = re.compile(r"jobs/results/(\d+)")
_ARIA_TITLE_RE = re.compile(r"^Learn more about (.+)$")
#: The card's "+2 more" for places it does not list.
_MORE = re.compile(r"\+\s*\d+\s*more", re.IGNORECASE)
_APPLICATIONS_BASE = "https://www.google.com/about/careers/applications/"
# The results page publishes an exact per-query total in a stable
# `aria-live="polite"` region: "Showing 1981 to 1999 of 1999 rows". Reading it
# turns the last full page into a NATURAL stop instead of a ceiling hit: a
# query whose total fills its last page exactly serves items on that page, and
# without the total that page reads as a ceiling hit when it is the last one
# `max_pages` allows.
# Absence is deliberately not drift: the marker is an optimization, and without
# it the scan simply pages to empty or the backstop.
_ROWS_SHOWN_RE = re.compile(r"Showing\s+[\d,]+\s+to\s+([\d,]+)\s+of\s+([\d,]+)\s+rows")
# Google publishes no result window, so a declared total is always a count.
#
# Metro totals can sum to more than their country's, which looks like a window
# capping the country. That sum counts overlapping sets: a posting listed in two
# offices is counted by both metro queries. Unioned instead (`location` accepts
# up to five values), the metros are strictly subsumed by the country, and the
# unfiltered global query pages to completion past any country's total, so no
# shared cap exists.
#
# Treating a total as a window would mark every run `truncated`, which
# suppresses closure, so the source could never reach a complete run.
_RESULT_WINDOW: int | None = None


class GoogleAdapter(BaseAdapter):
    name = "google"
    posted_date = "none"  # the listing states no date
    listing_scope = "filtered"  # one query per location term
    detail = "per_posting"  # `hydrate` reads each kept posting's text
    text_from_posting = True  # from its url or req_id alone
    # Google scans each location query separately, so this is per location, not
    # per run. The frontier stop normally ends a probe on page 1-2; six is the
    # burst allowance (120 newest rows per location) for when it does not.
    discovery_max_pages = 6
    # `sort_by=date` on every listing request (see `_params`), so a recognized
    # row proves everything below it is older.
    discovery_frontier_ordered = True
    location_queries = GOOGLE_LOCATION_QUERIES

    def _params(self, location: str, page: int) -> list[tuple[str, str]]:
        # Google zeroes out results when many `location` values are combined in
        # one request, so query one location at a time. Level filtering
        # belongs downstream: `below` is user-selectable and
        # must remain observable in the list inventory.
        params: list[tuple[str, str]] = [
            ("page", str(page)),
            ("sort_by", "date"),
            ("location", location),
        ]
        if self.board_token:
            params.append(("company", self.board_token))
        return params

    async def fetch(self) -> AsyncIterator[RawJob]:
        async for job in self.scan_location_queries(
            self.planned_location_terms(),
            self._fetch_location,
            empty_message="parsed zero job cards (selector drift?)",
        ):
            yield job

    async def _fetch_location(self, location: str, seen: set[str]) -> AsyncIterator[RawJob]:
        declared_total: int | None = None
        term_ids: set[str] = set()

        async def fetch_page(index: int, stop: Callable[[], None]) -> list[RawJob]:
            nonlocal declared_total
            page = index + 1
            resp = await self.get(_RESULTS, params=self._params(location, page))
            if resp.status_code != 200:
                self.drift.invalidate_listing(
                    "non-200 results",
                    status=resp.status_code,
                    location=location,
                    page=page,
                )
                stop()
                return []
            shown = _ROWS_SHOWN_RE.search(resp.text)
            if shown:
                through = int(shown.group(1).replace(",", ""))
                declared = int(shown.group(2).replace(",", ""))
                declared_total = declared
                if _RESULT_WINDOW is not None and declared >= _RESULT_WINDOW:
                    # Saturated: the number would be the window, so absence past
                    # it is OUR bound, not evidence the posting is gone. Google
                    # declares no window, so this does not fire; it keeps a
                    # source that grows one from silently claiming a view is a
                    # complete listing.
                    self.truncated = True
                if through >= declared:
                    # This page ends at the declared total, so the listing is
                    # complete: a natural stop, not a ceiling hit.
                    stop()
            # Every parsed card, duplicates included. Filtering `seen` HERE
            # would be what `paginate` reads as end-of-results: a page whose
            # cards were all seen under an earlier location would end the scan
            # and still report a complete listing (`truncated=False`, no drift),
            # authorizing closure over a board we stopped reading.
            # Multi-location roles are exactly that page: a
            # Singapore posting also listed in a US office is already `seen` by
            # the time the Singapore query runs. Dedup belongs after the pager.
            return list(self._parse_cards(resp.text, location))

        async for job in self.paged_listing(
            fetch_page,
            max_pages=_MAX_PAGES,
            query_key=location,
            declared_total=lambda: declared_total,
            page_size=_PAGE,
            location=location,
        ):
            term_ids.add(job.req_id)
            if job.req_id in seen:
                continue
            seen.add(job.req_id)
            yield job
        # The "Showing .. of N rows" marker is optional (its absence is not
        # drift), so google does not DECLARE a total; where the page states
        # one, the query is held to it.
        self.close_listing(declared=declared_total, unique=len(term_ids), field="rows", location=location)

    def _parse_cards(self, html: str, queried_location: str) -> list[RawJob]:
        tree = HTMLParser(html)
        out: list[RawJob] = []
        # Each job card is an <a aria-label="Learn more about {Title}"
        # href="jobs/results/{id}-{slug}?..."> (relative href, no leading slash).
        for anchor in tree.css("a[href*='jobs/results/']"):
            aria = anchor.attributes.get("aria-label") or ""
            m_title = _ARIA_TITLE_RE.match(aria.strip())
            if not m_title:
                continue
            href = anchor.attributes.get("href") or ""
            m = _JOB_HREF_RE.search(href)
            if not m:
                continue

            req_id = m.group(1)
            title = m_title.group(1).strip()
            card = self._enclosing_card(anchor)
            locations = self._card_locations(card)
            team = self._card_by_icon(card, "corporate_fare")
            # Google filtered server-side by `queried_location`, but a card
            # folds its later places into "+2 more", so the queried country is
            # recorded to keep the posting filed under it. Not when a listed
            # place already lies there: the country would only be said twice,
            # and it reads as a place of its own.
            if _TERM_COUNTRY.get(queried_location) not in countries_for(locations):
                locations.append(queried_location)

            # The href echoes the results page's own state (`?page=81&sort_by=
            # date&location=...`). Kept, the stored URL moves whenever the
            # listing shifts and never equals the link a user shares, so the
            # posting is its path alone.
            path = without_query(href)
            if path.startswith("http"):
                url = path
            else:
                url = _APPLICATIONS_BASE + path.lstrip("/")

            out.append(
                RawJob(
                    company=self.company,
                    req_id=req_id,
                    title=title,
                    url=url,
                    locations=locations,
                    team=team,
                    description_complete=False,
                    workplace_type=WorkplaceType.UNKNOWN,
                )
            )
        return out

    def _enclosing_card(self, anchor: Node) -> Node:
        """Climb to the enclosing <li> card (or a few levels up as a fallback)."""
        node = anchor
        for _ in range(8):
            parent = node.parent
            if parent is None:
                break
            node = parent
            if node.tag == "li":
                return node
        return node

    def _card_locations(self, card: Node | None) -> list[str]:
        loc = self._card_by_icon(card, "place")
        if not loc:
            return []
        # A card may list "Mountain View, CA, USA; Sunnyvale, CA, USA; +2 more".
        # Only that marker goes: a place whose name holds "more" (Baltimore,
        # Livermore, Morelia) is a place.
        parts = re.split(r";|•", loc)
        cleaned = [clean_location(p) for p in parts]
        return [c for c in cleaned if c and not _MORE.fullmatch(c)]

    def _card_by_icon(self, card: Node | None, icon_name: str) -> str | None:
        """Find text adjacent to a material icon (<i>place</i> / <i>corporate_fare</i>)."""
        if card is None:
            return None
        for icon in card.css("i"):
            if icon.text(strip=True) == icon_name:
                # The label is usually the parent's text minus the icon glyph.
                parent = icon.parent
                if parent is not None:
                    text = parent.text(strip=True).replace(icon_name, "").strip()
                    if text:
                        return text
        return None

    async def hydrate(self, job: RawJob) -> None:
        resp = await self.get(job.url)
        if resp.status_code != 200:
            self.drift.note("non-200 detail", status=resp.status_code, req=job.req_id)
            return
        text = self._extract_description(resp.text)
        if text:
            job.description_html = text
            job.description_complete = True
        else:
            self.drift.note("could not extract description", req=job.req_id)

    # Google detail pages carry no JobPosting JSON-LD. The JD lives in blocks,
    # each opened by a heading element ("About the job", "Minimum
    # qualifications:", ...). Class names rotate, so we anchor on the heading
    # text and fall back to the stable meta description.
    _SECTION_HEADERS = (
        "About the job",
        "Minimum qualifications",
        "Preferred qualifications",
        "Responsibilities",
    )

    def _extract_description(self, html: str) -> str | None:
        """The markup of each block a known heading opens, in page order.

        Markup, not text: the detail connector reads paragraph, list-item and
        heading boundaries from the tags, and flattened text runs sentences and
        bullets together ("the way.With", "8 years.3 years"). Both
        qualifications headings share one block, so a block is taken once.
        """
        tree = HTMLParser(html)
        blocks: dict[int, str] = {}
        for heading in tree.css("h2, h3, h4"):
            block = heading.parent
            if self._is_section_heading(heading) and block is not None and block.mem_id not in blocks:
                blocks[block.mem_id] = self._from_first_heading(block)
        if blocks:
            return "\n".join(blocks.values())
        md = tree.css_first('meta[name="description"]')
        return md.attributes.get("content") if md else None

    def _is_section_heading(self, node: Node) -> bool:
        if node.tag not in ("h2", "h3", "h4"):
            return False
        title = node.text(strip=True).rstrip(":").strip().lower()
        return title in {header.lower() for header in self._SECTION_HEADERS}

    def _from_first_heading(self, block: Node) -> str:
        """The block's markup from its first section heading on.

        The qualifications block opens with a location tooltip (an icon
        ligature, a close glyph, an interview note) that is page chrome, not
        posting text.
        """
        children = list(block.iter(include_text=True))
        start = next(i for i, child in enumerate(children) if self._is_section_heading(child))
        return "".join(child.html or "" for child in children[start:])
