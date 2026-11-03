"""Job browse reads: visibility, filter conditions, ordering and page context.

The one owner of the SQL that decides which `jobs` rows a browse surface shows
and in what order. The job list's lexical filter path, Best match
(`search/best_match.py`), the intelligence fit instruments and the statistics
lists all build from here, so a visibility rule cannot fork between them.

Request filters arrive as a plain `params` dict. HTTP parsing and serialization
stay at the API boundary (`api/routers/jobs.py`); this module imports no
`tracker.api` and no web framework.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal, TypedDict, cast, get_args

from sqlalchemy import Select, and_, case, false, func, not_, nullslast, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased, defer

from tracker.analytics.posting_reality import NEW_LISTING_WINDOW, ListingEvidence, role_age
from tracker.db.models import (
    Favorite,
    Job,
    JobFeedback,
    JobLifecycleEvent,
    JobLineage,
    JobPlaceSetMember,
    TrackedCompany,
)
from tracker.db.queries.companies import is_followed
from tracker.db.queries.scope import level_key_expr, unplaced_level_expr
from tracker.levels import UNSTATED_LEVEL
from tracker.lineage.counts import (
    is_new_job_clause,
    is_repost_job_clause,
    place_set_member_in,
    place_set_outranked,
)
from tracker.lineage.twins import TWIN_EFFECTIVE_SQL
from tracker.pay_disclosure import ROW_PAY_PERIODS
from tracker.pay_numbers import USD_PER_UNIT
from tracker.pay_period import SIZE_CLASSES
from tracker.platform.util import local_day_start_utc
from tracker.schema import LEVEL_BAND_ORDER, Arrival, band_slug
from tracker.search.policy import fold_query
from tracker.search.retrieval import tsquery
from tracker.taxonomy.role_catalog import UNCLASSIFIED_KEY

#: The columns no list row reads: the description, which only Job detail
#: serializes (`serialize_job(detail=True)`), and the search artifacts. Most of
#: a row's bytes, and pgvector parses every embedding it fetches.
LIST_DEFERRED = (
    Job.description_html,
    Job.description_sections,
    Job.description_text,
    Job.embedding,
    Job.search_vector,
)


def list_rows(stmt: Select) -> Select:
    """`stmt` loading its `Job` rows without `LIST_DEFERRED`. With raiseload, so
    a list reader that reaches for one fails at once instead of loading it
    lazily under the async session."""
    return stmt.options(*(defer(column, raiseload=True) for column in LIST_DEFERRED))


def exclude_hidden(stmt: Select, hidden: list[str], column=Job.company) -> Select:
    """Add a `column NOT IN (hidden)` guard when any company is off the Board.

    `hidden` is `company_store.off_board_company_slugs`: hidden by the user or
    not followed."""
    return stmt.where(column.notin_(hidden)) if hidden else stmt


def open_in_scope_count_stmt(hidden: list[str] | None = None, *narrowed) -> Select:
    """How many open, in-scope postings a visible board holds.

    One statement for every caller: the statistics routes and the MCP radar
    summary. An INNER JOIN on `TrackedCompany.visible` would also drop any
    posting whose company has no roster row.
    """
    return exclude_hidden(select(func.count()).where(*insights_role_conds(), *narrowed), hidden or [])


def insights_role_conds() -> list:
    """The roles Insights describes: open, in scope, a place set once.

    One rule for every Statistics tab, so a headline count cannot differ from
    tab to tab. Off-board companies are removed by the caller (`exclude_hidden`).
    Roles marked Not for me stay: Insights describes the market, the Board the
    person's list."""
    return [Job.status == "open", Job.in_scope.is_(True), not_(place_set_outranked())]


def place_set_later_ids() -> Select:
    """Ids of the postings a place set shows through another member,
    for the raw-SQL aggregates that cannot take the ORM clause.

    Asked of members only: the outranking test runs per row, and most postings
    are in no set."""
    return select(Job.id).where(
        Job.id.in_(select(JobPlaceSetMember.job_id).where(JobPlaceSetMember.status == "auto")),
        place_set_outranked(),
    )


def board_posting_ids(hidden: list[str]) -> Select:
    """Ids of the postings the Board can show: open, in scope, of a company on
    the Board, not marked Not for me. The Board's own standing conditions
    (`structured_conds`), before the one-row-per-place-set collapse: every
    member of a set is a posting the user can open, and a question about a
    pair is about postings, not Board rows."""
    return select(Job.id).where(
        *structured_conds({"status": "open", "hidden": hidden}, collapse=False)
    )


def pair_on_board(left, right, hidden: list[str]):
    """A relationship proposal the user can act on: at least one of its two
    postings is on the Board. A pair of closed postings, or of
    postings outside the scope or off the Board, gates no decision the user
    makes, so the review queue does not ask it; the proposal stays pending
    and returns when a posting does (a reopening, a wider scope, a follow).
    The queue routes and the nav badge both read this, so the count and the
    list cannot disagree."""
    ids = board_posting_ids(hidden)
    return or_(left.in_(ids), right.in_(ids))


def _open_members(columns: list, hidden: list[str]) -> Select:
    """Open, in-scope postings of visible companies with `columns`, each
    labelled with its role: a place set's id (negated, so it cannot meet a
    job id), else the posting's own. Counting distinct `role` per value
    counts a set once under EVERY value a member has, because a filter on
    that value lists the set through the member that has it."""
    member = aliased(JobPlaceSetMember)
    role = func.coalesce(-member.set_id, Job.id)
    return exclude_hidden(
        select(*columns, role.label("role"))
        .select_from(Job)
        .outerjoin(member, and_(member.job_id == Job.id, member.status == "auto"))
        .where(Job.status == "open", Job.in_scope.is_(True)),
        hidden,
    )


def _roles_per_value(value, hidden: list[str]) -> Select:
    sub = _open_members([value.label("value")], hidden).subquery()
    return select(sub.c.value, func.count(func.distinct(sub.c.role))).group_by(sub.c.value)


def facet_count_stmt(column, hidden: list[str]) -> Select:
    """Open roles per value of `column`: the count beside a filter option is
    the rows that option lists, so a place set counts once, under
    each value a member has."""
    return _roles_per_value(column, hidden)


def domain_facet_count_stmt(hidden: list[str]) -> Select:
    """Open roles per world (`domains` is an array, so it is unnested)."""
    return _roles_per_value(func.unnest(Job.domains), hidden)


def unclassified_domain_count_stmt(hidden: list[str]) -> Select:
    """Open roles no world was read for: NULL (never classified) or `{}` (honestly unknown)."""
    sub = _open_members(
        [], hidden
    ).where(or_(Job.domains.is_(None), func.cardinality(Job.domains) == 0)).subquery()
    return select(func.count(func.distinct(sub.c.role)))


def place_facet_count_stmt(hidden: list[str]) -> Select:
    """Open roles per location group. A place set counts once at EVERY place a
    member is at, because the place filter admits it there."""
    return _roles_per_value(func.unnest(Job.location_groups), hidden)


def listed_recently_clause(now: datetime):
    """ORM clause: the posting's listed age at `now` is under
    `NEW_LISTING_WINDOW`, by evidence that dates it: the employer's date, or
    our sighting unless a first read of the company made it."""
    return and_(
        _LISTED_SINCE > now - NEW_LISTING_WINDOW,
        or_(
            Job.arrival.is_distinct_from(Arrival.FIRST_READ.value),
            Job.first_posted_at < Job.first_seen,
        ),
    )


def new_listing_clause(*, now: datetime | None = None):
    """ORM clause: the row lights as new (`posting_reality.is_new_listing`,
    its Python twin): an open original listed recently. The header's count,
    the New view and Hiring read it; `ix_jobs_open_listed_since` serves the
    age test."""
    return and_(
        Job.status == "open",
        is_new_job_clause(),
        listed_recently_clause(now or datetime.now(UTC)),
    )


# Level band sorts by an ordinal rank, not its raw string.
_LEVEL_ORDER_CASE = case(LEVEL_BAND_ORDER, value=Job.level_band, else_=0)

# A posting that states no level is stored at Mid for sorting only:
# the Level facet counts it under its own key and the filter selects it by that
# key, so "Mid-level" means a posting that says Mid. A NULL basis (not
# recorded) reads its band, as every gate does.
_UNSTATED = unplaced_level_expr(Job)
#: Best fit's first key: a row whose level we place on the shared
#: levels before one whose level we cannot place (not stated, or not mapped).
#: False sorts first, so "placed" leads; the order inside each group is the
#: ranking's own. Ordering only, never a gate: both groups keep every row.
LEVEL_PLACED_FIRST = _UNSTATED.asc()
_PEER = aliased(Job)
#: The years a typical unplaced posting requires: the median over open, in-scope
#: unplaced postings that state years. Computed in the query (Postgres evaluates
#: it once), so it follows the data.
_TYPICAL_UNPLACED_YEARS = (
    select(func.percentile_cont(0.5).within_group(_PEER.required_years))
    .where(
        _PEER.status == "open", _PEER.in_scope.is_(True),
        unplaced_level_expr(_PEER), _PEER.required_years.is_not(None),
    )
    .scalar_subquery()
)
#: Best fit's second key: inside "Level not placed", a posting
#: requiring more years of experience first (`jobs.required_years`, the number
#: Job detail shows). One stating none lands where a typical posting does, at
#: the median, among those requiring that many and in the ranking's own order:
#: an unstated number is unknown, not low. On postings whose titles state their
#: level, required years order principal-and-up above senior. Empty for a placed
#: row, so the placed group keeps its order. Ordering only: never a level, a
#: label or a gate.
UNPLACED_BY_YEARS = nullslast(
    case((_UNSTATED, func.coalesce(Job.required_years, _TYPICAL_UNPLACED_YEARS))).desc()
)
LEVEL_FACET_KEY = level_key_expr(Job)


def level_band_clause(wanted: Iterable[str], entity=Job):
    """The Board's Level filter: stated bands, and `unstated` for a posting
    that names no level. Choosing a band never returns an unstated posting. A
    folded band a saved filter or an old link still names reads as its heir
    (`?level_band=junior` is Entry)."""
    chosen = {band_slug(band) for band in wanted}
    bands = sorted(chosen - {UNSTATED_LEVEL})
    unstated = unplaced_level_expr(entity)
    parts = []
    if bands:
        parts.append(and_(entity.level_band.in_(bands), not_(unstated)))
    if UNSTATED_LEVEL in chosen:
        parts.append(unstated)
    return or_(false(), *parts)


#: Every `sort` key the job list accepts: a column of `SORT_COLUMNS`, or Best
#: fit. `/api/jobs` publishes it, and the dashboard types its sort keys from
#: the generated schema, so a key the list does not know fails `tsc` there.
JobSort = Literal[
    "relevance",
    "first_seen",
    "dismissed_at",
    "posted_at",
    "last_seen",
    "comp_median",
    "base_pay",
    "location",
    "company",
    "title",
    "level_band",
    "days_open",
]
SortOrder = Literal["asc", "desc"]
DEFAULT_SORT: JobSort = "first_seen"
#: The sort key the Board calls Best fit.
BEST_FIT_SORT: JobSort = "relevance"
_JOB_SORTS: frozenset[str] = frozenset(get_args(JobSort))


def known_sort(value: object) -> JobSort:
    """A `sort` key as the list reads it: one it does not know reads as
    DEFAULT_SORT, the column `resolve_ordering` falls back to, so a link that
    names a retired key lists rows rather than failing."""
    return cast(JobSort, value) if isinstance(value, str) and value in _JOB_SORTS else DEFAULT_SORT


def known_order(value: object) -> SortOrder:
    """A direction as `resolve_ordering` reads one: `asc` in any case is
    ascending, anything else descending."""
    return "asc" if isinstance(value, str) and value.lower() == "asc" else "desc"


# When the reader marked a row "not for me": the Not-for-me lens orders by it,
# newest mark first, so a mis-click is the first row. Correlated
# rather than joined, so the ordinary list query is untouched.
_DISMISSED_AT = (
    select(JobFeedback.created_at).where(JobFeedback.job_id == Job.id).scalar_subquery()
)

# When the posting was first listed, by the earliest date either side states
# for THIS posting: the SQL twin of `analytics.posting_reality.listing_start`.
# Postgres LEAST skips NULL, so a posting without an
# employer date falls back to our own clock, as the Python rule does. The
# lineage does not move it (role age is Job detail's), and the employer's
# CURRENT `posted_at` never does: a re-date later cannot shorten the age. Age
# sorts by it so the order matches the age the row shows.
def listed_since(entity=Job):
    return func.least(entity.first_posted_at, entity.first_seen)


_LISTED_SINCE = listed_since()

# How long the row says it was listed: to its closing for a posting that is not
# open, to now otherwise (the serializer's `listed_until`). Sorting by the start
# alone would rank a posting listed for 10 days, two hundred days ago, above one
# listed 49 days until yesterday on the Closed board.
_LISTED_FOR = (
    func.coalesce(case((Job.status != "open", Job.closed_at)), func.now()) - _LISTED_SINCE
)

#: Above this a listed age reads as a stale or evergreen employer date, not a
#: role that has waited this long, and such rows would lead "Open the longest".
#: The posting keeps its age everywhere it is shown; only the longest-open lists
#: leave it out.
PLAUSIBLE_LISTING_DAYS = 365


def plausibly_listed():
    """ORM clause: the posting's listed age is within `PLAUSIBLE_LISTING_DAYS`."""
    return _LISTED_FOR <= timedelta(days=PLAUSIBLE_LISTING_DAYS)


def base_pay(entity=Job):
    """The yearly base in US dollars a list row shows, as one comparable
    figure: the posting's own base range from its low end, else the estimated
    base. Which posted range the row shows is the serializer's `posted_base`,
    whose period `pay_period.effective_period` checks against the amount's size;
    this is that rule in SQL. A posted range shown per hour or month, or in
    another currency, and an estimate in another currency, compare with nothing
    (the filters are yearly dollars), and a shown range never falls back to the
    estimate the row does not show."""
    J = entity
    low = func.coalesce(J.disclosed_base_min, J.disclosed_base_max)
    high = func.coalesce(J.disclosed_base_max, J.disclosed_base_min)
    factor = case(USD_PER_UNIT, value=func.upper(func.coalesce(J.disclosed_currency, "USD")), else_=1.0)

    def fits(period: str):
        floor, ceiling = next((f, c) for p, f, c in SIZE_CLASSES if p.value == period)
        return and_(low > 0, high >= low, low * factor >= floor, high * factor <= ceiling)

    stored = J.disclosed_pay_period
    yearly = or_(and_(stored == "year", fits("year")), and_(stored.is_(None), fits("year")))
    period_kept = or_(yearly, *(and_(stored == p, fits(p)) for p in ROW_PAY_PERIODS if p != "year"))
    shown = and_(J.disclosed_pay_basis == "base", J.disclosed_currency.isnot(None), period_kept)
    return case(
        (and_(shown, yearly, J.disclosed_currency == "USD"), low),
        (shown, None),
        (J.comp_currency == "USD", J.comp_base_median),
        else_=None,
    )


# Sortable columns registry. Each entry maps a client `sort` key to
# (column expression, invert) where invert flips the requested direction because
# the stored column runs opposite to the user-facing metric. A new sortable
# column is an entry here, its key in `JobSort`, and a label in the dashboard's
# SORTS list.
SORT_COLUMNS: dict[str, tuple] = {
    "first_seen": (Job.first_seen, False),
    "dismissed_at": (_DISMISSED_AT, False),
    "posted_at": (Job.posted_at, False),
    "last_seen": (Job.last_seen, False),
    "comp_median": (Job.comp_median, False),  # Estimated Total Compensation
    "base_pay": (base_pay(), False),
    "location": (Job.locations[1], False),  # primary (first) listed location
    "company": (Job.company, False),
    "title": (Job.title, False),
    "level_band": (_LEVEL_ORDER_CASE, False),
    # Age: the listed duration each row shows. The key keeps its name so saved
    # sorts and links still resolve.
    "days_open": (_LISTED_FOR, False),
}


def resolve_ordering(sort: str, order: str) -> list:
    """Map a `sort` key + `order` direction to ORDER BY clauses.

    Applied to the full filtered dataset before LIMIT/OFFSET so the whole result
    set is ordered, not just the current page. Missing values sort last in either
    direction, and a stable id tiebreaker keeps pagination consistent across rows
    that share a sort value. Unknown sort keys fall back to DEFAULT_SORT.
    """
    col, invert = SORT_COLUMNS.get(sort, SORT_COLUMNS[DEFAULT_SORT])
    descending = order.lower() != "asc"
    if invert:
        descending = not descending
    primary = col.desc() if descending else col.asc()
    # Best fit with no intent signal yet still puts the placed group first, and
    # orders "Level not placed" by the years it requires.
    tiers = [LEVEL_PLACED_FIRST, UNPLACED_BY_YEARS] if sort == BEST_FIT_SORT else []
    if sort == "comp_median":
        # Like with like: totals first, ordered by total; then
        # postings with only an estimated base, ordered by base. A base is never
        # ranked against a total.
        base = Job.comp_base_median.desc() if descending else Job.comp_base_median.asc()
        return [Job.comp_median.is_(None), nullslast(primary), nullslast(base), Job.id.desc()]
    return [*tiers, nullslast(primary), Job.id.desc()]



async def count_with_placed(session: AsyncSession, base: Select) -> tuple[int, int]:
    """(rows of `base`, rows whose level we place) in the ONE count query the
    list already runs: where Best fit's "level not placed" group starts,
    at no extra round trip (`test_api_query_counts`)."""
    sub = base.subquery()
    placed = func.count().filter(not_(unplaced_level_expr(sub.c)))
    total, placed_total = (await session.execute(select(func.count(), placed).select_from(sub))).one()
    return total or 0, placed_total or 0


def posting_conds(params: dict, entity=Job) -> list:
    """The request filters that are facts of one posting, over `entity`.

    Built per entity so the place-set collapse can ask them of a PEER: a
    filter selects the member that passes it, and only a member passing every
    one of them represents the set. Workplace, pay and dates differ
    by place; the read mark is the posting's own (Read and Unread, and "posted
    within", read the posting, not the role). Company,
    level and family are equal across a set by its rule, so asking them of a
    peer changes nothing. The role lenses (New, Reposted) and the standing
    visibility conditions are not here: they are `structured_conds`'s.
    """
    J = entity
    conds = []
    if params.get("company"):
        conds.append(J.company.in_(params["company"]))
    if params.get("level_band"):
        conds.append(level_band_clause(params["level_band"], J))
    if params.get("level_confidence"):
        conds.append(J.level_confidence == params["level_confidence"])
    if params.get("family"):
        conds.append(J.family.in_(params["family"]))
    if params.get("track"):
        conds.append(J.track.in_(params["track"]))
    if params.get("workplace_type"):
        conds.append(J.workplace_type.in_(params["workplace_type"]))
    if params.get("status"):
        conds.append(J.status == params["status"])
    if params.get("location_group"):
        conds.append(J.location_groups.op("&&")(params["location_group"]))
    if params.get("domain"):
        # Board triage over the worlds axis. "unclassified" is a first-class
        # option (the fail-open volume must stay findable), matching rows the
        # classifier honestly left empty — `{}` — or never classified (NULL).
        slugs = [d for d in params["domain"] if d != UNCLASSIFIED_KEY]
        domain_conds = []
        if slugs:
            domain_conds.append(J.domains.op("&&")(slugs))
        if UNCLASSIFIED_KEY in params["domain"]:
            domain_conds.append(or_(J.domains.is_(None), func.cardinality(J.domains) == 0))
        conds.append(or_(*domain_conds))
    # The estimate the agent tools filter on: its total, else its estimated
    # base. The Board's pay filters are `base_min` and `base_max`.
    shown_pay = func.coalesce(J.comp_median, J.comp_base_median)
    if params.get("comp_min") is not None:
        conds.append(shown_pay >= params["comp_min"])
    if params.get("comp_max") is not None:
        conds.append(shown_pay <= params["comp_max"])
    if params.get("base_min") is not None:
        conds.append(base_pay(J) >= params["base_min"])
    if params.get("base_max") is not None:
        conds.append(base_pay(J) <= params["base_max"])
    if params.get("posted_within_days") is not None:
        cutoff = datetime.now(UTC) - timedelta(days=params["posted_within_days"])
        # The same start the row's age shows: a posting listed 90
        # days ago and re-dated last week, or first seen here last week, is
        # not new. A `posted_at` OR `first_seen` test would let either one make
        # it so.
        conds.append(listed_since(J) >= cutoff)
    # The Show lens: the reader's own read/unread mark. An explicit
    # request filter like `status`, not a standing visibility condition, so a
    # by-ID or saved read that asks for it gets it too. A row is read once
    # `/view` stamped it; there is no third state.
    if params.get("viewed") == "read":
        conds.append(J.viewed_at.isnot(None))
    elif params.get("viewed") == "unread":
        conds.append(J.viewed_at.is_(None))
    if params.get("discloses_pay"):
        # `pay_disclosure.band_stated` in SQL, as the row's `discloses_pay`
        # serializes it: a stored band, whoever wrote it. Not the text pass's
        # stamp, which a page or connector band does not need.
        conds.append(or_(J.disclosed_base_min.isnot(None), J.disclosed_base_max.isnot(None)))
    return conds


#: A predicate builder over an entity: the caller's own per-posting match.
Matching = Callable[[Any], list]


def structured_conds(
    params: dict,
    *,
    browse_visibility: bool = True,
    matching: Matching | None = None,
    row_matched: bool = False,
    collapse: bool = True,
) -> list:
    """Structured (non-text) filters, AND-combined. Shared by the lexical and
    hybrid paths so filters behave identically across every candidate source.

    `browse_visibility=False` drops the three STANDING visibility conditions —
    scope, hidden companies, dismissed exclusion — while keeping every request
    filter (status included: the Open/Closed toggle is an explicit UI choice).
    Used by identifier resolution, which is a specific-row read: the
    same reasoning as the `ids`/favorites exemptions below — a row the user
    explicitly names must stay resolvable after a scope change, a hidden
    company, or a dismissal.

    `matching(entity)` is the caller's own per-posting match (the search box's
    text, an agent's phrase and window): applied to the row here unless
    `row_matched` (the caller's ranked sources already admit by exactly it),
    and always asked of the peer that may represent the row's place set.
    `collapse=False` leaves the one-row-per-set rule to the caller, which
    applies it over a match set SQL cannot express (`one_per_place_set`).
    """
    conds = posting_conds(params, Job)
    if matching is not None and not row_matched:
        conds.extend(matching(Job))
    if params.get("new_today_only"):
        conds.append(new_listing_clause())
    if params.get("repost_today_only"):
        today = local_day_start_utc()
        conds.append(
            Job.id.in_(
                select(JobLifecycleEvent.job_id).where(
                    JobLifecycleEvent.event_type == "opened",
                    JobLifecycleEvent.created_at >= today,
                )
            )
        )
        conds.append(is_repost_job_clause())
    if params.get("favorites_only"):
        conds.append(Job.id.in_(select(Favorite.job_id)))
    # Dismissed rows ("not for me") hide from browse by default and are
    # filterable back. By-ID picks and saved roles stay resolvable — a saved
    # job the user later dismissed must still open from Favorites/Compare.
    # Not for me is the role's: marking any member of a place set
    # hides every member, so no filter brings it back through a sibling.
    dismissed_ids = select(JobFeedback.job_id).where(JobFeedback.verdict == "dismissed")
    if params.get("dismissed_only"):
        conds.append(Job.id.in_(dismissed_ids))
    elif browse_visibility and not params.get("ids") and not params.get("favorites_only"):
        conds.append(not_(place_set_member_in(dismissed_ids)))
    if params.get("ids"):
        conds.append(Job.id.in_(params["ids"]))
    # Scope visibility mirrors hidden-company behavior: explicit saved/by-ID
    # reads remain resolvable even after a scope change. The New lens reads the
    # current scope like the open board it narrows, so New is always part of Open.
    if (
        browse_visibility
        and not params.get("ids")
        and not params.get("favorites_only")
    ):
        conds.append(Job.in_scope.is_(True))
    # Hidden-company exclusion for browse surfaces. By-ID picks are exempt: an
    # explicit `ids` (Compare) or `favorites_only` (Favorites) request must still
    # return a saved job whose company was later hidden.
    hidden = params.get("hidden")
    if hidden and browse_visibility and not params.get("ids") and not params.get("favorites_only"):
        conds.append(Job.company.notin_(hidden))
    # One row per place set: the earliest member that passes every
    # posting filter and the caller's match, so a place filter
    # admits a set when ANY member is at one of its places, a Remote filter
    # when any member is remote, and every total counts the set once. Rows a
    # person names (ids, Saved) and the Not-for-me lens list each posting they
    # hold. The New and Reposted lenses stay the role's: they read the
    # representative the posting filters chose.
    if (
        collapse
        and browse_visibility
        and not params.get("ids")
        and not params.get("favorites_only")
        and not params.get("dismissed_only")
    ):
        def eligible(peer) -> list:
            return [*posting_conds(params, peer), *(matching(peer) if matching else [])]

        conds.append(not_(place_set_outranked(eligible=eligible)))
    return conds


async def one_per_place_set(session: AsyncSession, ids: list[int]) -> list[int]:
    """`ids` less every posting another of `ids` represents: the collapse over
    a match set decided outside SQL (Best match's exact-title equality)."""
    if not ids:
        return []
    kept = await session.scalars(
        select(Job.id).where(
            Job.id.in_(ids), not_(place_set_outranked(eligible=lambda peer: [peer.id.in_(ids)]))
        )
    )
    return sorted(kept.all(), reverse=True)


def apply_job_filters(stmt: Select, params: dict) -> Select:
    """Lexical filter path: structured conditions + lexical `q` as a boolean match."""
    q = fold_query(params["q"]) if params.get("q") else None
    conds = structured_conds(
        params,
        matching=(lambda entity: [entity.search_vector.op("@@")(tsquery(q))]) if q else None,
    )
    if conds:
        stmt = stmt.where(and_(*conds))
    return stmt


def board_count_stmt(params: dict) -> Select:
    """How many rows the Board lists for `params`: `browse_jobs`' total, as a
    count. A chip that links to a Board view counts through this, so the
    number on the chip and the list it opens cannot disagree (a count that
    kept roles marked Not for me would not match the Board, which hides them).
    """
    return apply_job_filters(select(func.count()).select_from(Job), params)


def run_new_roles_stmt(run_id: int, hidden: list[str]) -> Select:
    """How many roles the New board lists that scan run `run_id` opened: the
    Board's own New count narrowed to that run, so a count that opens the New
    board never names a role the board leaves out."""
    opened = select(JobLifecycleEvent.job_id).where(
        JobLifecycleEvent.event_type == "opened", JobLifecycleEvent.run_id == run_id
    )
    return board_count_stmt({"status": "open", "hidden": hidden, "new_today_only": True}).where(
        Job.id.in_(opened)
    )


def most_updated_open_stmt(
    limit: int = 10, min_updates: int = 2, hidden: list[str] | None = None
) -> Select:
    changed_counts = (
        select(
            JobLifecycleEvent.job_id.label("job_id"),
            func.count().label("update_count"),
            func.max(JobLifecycleEvent.created_at).label("last_updated_at"),
        )
        .where(JobLifecycleEvent.event_type == "changed")
        .group_by(JobLifecycleEvent.job_id)
        .having(func.count() >= min_updates)
        .subquery()
    )
    closed_jobs = (
        select(JobLifecycleEvent.job_id)
        .where(JobLifecycleEvent.event_type == "closed")
        .distinct()
        .subquery()
    )
    stmt = (
        select(
            Job,
            changed_counts.c.update_count,
            changed_counts.c.last_updated_at,
        )
        .join(changed_counts, changed_counts.c.job_id == Job.id)
        .outerjoin(closed_jobs, closed_jobs.c.job_id == Job.id)
        .where(Job.status == "open", Job.in_scope.is_(True), closed_jobs.c.job_id.is_(None))
        .order_by(changed_counts.c.update_count.desc(), changed_counts.c.last_updated_at.desc())
        .limit(limit)
    )
    return exclude_hidden(stmt, hidden or [])


async def lineage_meta_for(session: AsyncSession, jobs) -> dict[int, JobLineage]:
    """One batched fetch of the JobLineage rows for a page (the stack sizes).

    Same shape as the fav_ids fetch: two extra queries per page total, independent
    of page size — the whole reason jobs.lineage_id + job_lineage.size are
    denormalized rather than derived per row.
    """
    lineage_ids = {j.lineage_id for j in jobs if j.lineage_id is not None}
    if not lineage_ids:
        return {}
    rows = (
        await session.scalars(select(JobLineage).where(JobLineage.id.in_(lineage_ids)))
    ).all()
    return {lin.id: lin for lin in rows}


@dataclass(frozen=True)
class PlaceSetCounts:
    """A posting's place set, counted: the places its role is listed in,
    the postings it holds, and how many OTHER postings of the role
    sit at this posting's own place (`relisted`), which the
    standing-posting sign counts as listings."""

    places: int
    postings: int
    here: int


async def relation_counts_for(
    session: AsyncSession, jobs
) -> tuple[dict[int, int], dict[int, PlaceSetCounts]]:
    """Each row's confirmed twins, and its place set counted when it is in one
    (`PlaceSetCounts`). ONE round trip for both: a list page's queries are
    budgeted (`test_api_query_counts`), and both are a row's relationships to
    other postings, read over the same ids."""
    ids = sorted({job.id for job in jobs})
    if not ids:
        return {}, {}
    rows = (
        await session.execute(
            text(
                f"""
                SELECT 'twin' AS kind, job_a_id AS a, job_b_id AS b, 0 AS places,
                       0 AS postings, 0 AS here
                  FROM job_twin_link
                 WHERE {TWIN_EFFECTIVE_SQL}
                   AND (job_a_id = ANY(cast(:ids AS integer[]))
                        OR job_b_id = ANY(cast(:ids AS integer[])))
                UNION ALL
                SELECT 'place', m.job_id, NULL, cardinality(s.places), s.size,
                       (SELECT count(*) FROM job_place_set_member o
                         WHERE o.set_id = m.set_id AND o.status = 'auto'
                           AND o.job_id <> m.job_id
                           AND o.evidence->>'place_key' = m.evidence->>'place_key')
                  FROM job_place_set_member m JOIN job_place_set s ON s.id = m.set_id
                 WHERE m.status = 'auto' AND m.job_id = ANY(cast(:ids AS integer[]))
                """
            ),
            {"ids": ids},
        )
    ).all()
    twins = {job_id: 0 for job_id in ids}
    places: dict[int, PlaceSetCounts] = {}
    for row in rows:
        if row.kind == "place":
            places[row.a] = PlaceSetCounts(int(row.places), int(row.postings), int(row.here))
            continue
        if row.a in twins:
            twins[row.a] += 1
        if row.b in twins:
            twins[row.b] += 1
    return twins, places


class RowContext(TypedDict):
    """Per-row reader state for one response, fetched once over every row it
    shows. Its keys are the keyword arguments `serialize_job` takes."""

    favorite_ids: set[int]
    dismissed_ids: set[int]
    lineage_meta: dict[int, JobLineage]
    twin_counts: dict[int, int]
    #: Places the role is listed in, for a posting in a place set.
    place_counts: dict[int, PlaceSetCounts]
    #: Each multi-posting lineage's role start, and the rows that
    #: came back after closing: what the standing-posting sign reads. None
    #: for a response whose rows do not carry the sign.
    role_starts: dict[int, datetime] | None
    reopened_ids: set[int] | None
    #: The rows' companies the user does not follow. Only rows the
    #: Board lets through by id or as Saved can be at one; such a row says it
    #: is not being checked.
    unfollowed: set[str]


async def row_context(
    session: AsyncSession,
    jobs: list[Job],
    *,
    unfollowed: Iterable[str] | None = None,
    standing: bool = True,
) -> RowContext:
    """One batched pass of the per-row lookups (favorites/dismissed/lineage/twins).

    Built once over the UNION of a response's sections, so an expanded direct
    match costs one set of round trips instead of one per section. Every
    response that sends job rows reads it: a row that says "not saved" must
    have been looked at, wherever it appears.

    `unfollowed` is the request's off-Board read when it has one; without it
    the rows' companies are read here, in one query. `standing` reads what the
    standing-posting sign needs, for the Board's list rows and Job detail; a
    `JobRow` elsewhere does not carry the sign, so its two reads are skipped.
    """
    ids = [job.id for job in jobs]
    fav_ids = set(
        (await session.scalars(select(Favorite.job_id).where(Favorite.job_id.in_(ids)))).all()
    ) if ids else set()
    dis_ids = set(
        (await session.scalars(select(JobFeedback.job_id).where(JobFeedback.job_id.in_(ids)))).all()
    ) if ids else set()
    lineage_meta = await lineage_meta_for(session, jobs)
    twin_counts, place_counts = await relation_counts_for(session, jobs)
    return {
        "favorite_ids": fav_ids,
        "dismissed_ids": dis_ids,
        "lineage_meta": lineage_meta,
        "twin_counts": twin_counts,
        "place_counts": place_counts,
        "role_starts": await role_starts_for(session, lineage_meta) if standing else None,
        "reopened_ids": (
            set(
                (
                    await session.scalars(
                        select(JobLifecycleEvent.job_id).where(
                            JobLifecycleEvent.job_id.in_(ids),
                            JobLifecycleEvent.event_type == "reopened",
                        )
                    )
                ).all()
            ) if ids else set()
        ) if standing else None,
        "unfollowed": (
            set(unfollowed) & {job.company for job in jobs}
            if unfollowed is not None
            else await unfollowed_among(session, {job.company for job in jobs})
        ),
    }


async def unfollowed_among(session: AsyncSession, companies: set[str]) -> set[str]:
    """Which of `companies` are tracked and not followed."""
    if not companies:
        return set()
    return set(
        (
            await session.scalars(
                select(TrackedCompany.slug).where(
                    TrackedCompany.slug.in_(companies), not_(is_followed())
                )
            )
        ).all()
    )


async def role_starts_for(
    session: AsyncSession, lineage_meta: dict[int, JobLineage]
) -> dict[int, datetime]:
    """Each page lineage's role start, by the rule Job detail uses:
    one query over the members of every lineage of two or more postings, so a
    Board page computes the standing-posting sign in the same round trips at
    any page size. A lineage of one has no role age and is left out."""
    shared = [lin_id for lin_id, lin in lineage_meta.items() if (lin.size or 0) >= 2]
    if not shared:
        return {}
    rows = (
        await session.execute(
            select(Job.lineage_id, Job.first_posted_at, Job.first_seen, Job.status, Job.closed_at)
            .where(Job.lineage_id.in_(shared))
        )
    ).all()
    members: dict[int, list[ListingEvidence]] = {}
    for lin_id, first_posted_at, first_seen, status, closed_at in rows:
        members.setdefault(lin_id, []).append(
            ListingEvidence(first_posted_at, first_seen, status, closed_at)
        )
    now = datetime.now(UTC)
    starts = {}
    for lin_id, evidence in members.items():
        age = role_age(evidence, now=now)
        if age is not None:
            starts[lin_id] = age[0]
    return starts


@dataclass(frozen=True)
class JobPage:
    """One page of the filtered set, ordered over the WHOLE set before paging."""

    total: int
    jobs: list[Job]
    context: RowContext
    #: Best fit only: rows whose level we place, which come first.
    placed_total: int | None = None


async def browse_jobs(
    session: AsyncSession, params: dict, *, sort: str, order: str, limit: int, offset: int
) -> JobPage:
    """The job list under any column sort: the filtered set's size, one ordered
    page of it, and that page's per-row context."""
    base = apply_job_filters(select(Job), params)

    placed_total = None
    if sort == BEST_FIT_SORT:
        total, placed_total = await count_with_placed(session, base)
    else:
        total = await session.scalar(select(func.count()).select_from(base.subquery()))

    stmt = list_rows(base.order_by(*resolve_ordering(sort, order)).limit(limit).offset(offset))
    jobs = list((await session.scalars(stmt)).all())
    return JobPage(
        total=total or 0,
        jobs=jobs,
        context=await row_context(session, jobs, unfollowed=params.get("unfollowed", ())),
        placed_total=placed_total,
    )
