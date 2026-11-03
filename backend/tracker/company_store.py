"""DB access for tracked companies (`tracked_company` table).

The table is the single source of truth for every company — built-in and
user-added alike. Built-ins are seeded from `config.COMPANIES` by
`ensure_builtins()` (idempotent) and then obey identical rules: the same
`enabled` (future scans) and `visible` (browse/aggregate display) columns, the
same API, the same pipeline targeting via `get_active_targets()`. The only thing
that marks a company built-in is `source="builtin"`, which blocks deletion.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime
from typing import NotRequired, TypedDict

from sqlalchemy import and_, not_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from tracker.ats_detect import detect_ats
from tracker.company_catalog import CATALOG
from tracker.company_directory import FOLLOWED_BY_NAME, FOLLOWED_WITH_SET, directory_company
from tracker.company_discovery import (
    COMPANY_DISCOVERY,
    company_wall,
    discovery_company_fields,
    is_curated,
)
from tracker.config import COMPANIES
from tracker.connectors import ADAPTER_REGISTRY, route_family_of
from tracker.connectors.recipes import ExecutablePlan
from tracker.db.models import ConnectorRecipe, SourceBinding, TrackedCompany
from tracker.db.queries.companies import is_followed
from tracker.db.recipe_store import ensure_bundled_recipes
from tracker.platform.language_tags import is_locale_tag

logger = logging.getLogger(__name__)


class CompanyError(ValueError):
    """The store refuses the request as given: bad input, or a change it does not make.

    A subclass says what kind of refusal it is. `tracker.api.company_errors`
    gives each class its one API answer, so a new kind needs a row there.
    """


class CompanyNotFound(CompanyError):
    """The request names a company that is not tracked."""


class CompanyConflict(CompanyError):
    """The company is already tracked (built-in or an existing row)."""


class RecipeNotFound(CompanyError):
    """The request names a recipe, or a recipe source change, that does not exist."""


class RecipeConflict(CompanyConflict):
    """The company's source cannot move to, or between, recipes as asked now."""


def slugify(name: str) -> str:
    """company display name -> canonical slug (lowercase, hyphen-separated)."""
    s = re.sub(r"[^a-z0-9]+", "-", (name or "").strip().lower()).strip("-")
    return s[:64]


def is_builtin(slug: str) -> bool:
    return slug in COMPANIES


def resolve_company(
    *,
    name: str | None = None,
    careers_url: str | None = None,
    catalog_slug: str | None = None,
) -> dict:
    """Turn an add request into concrete `tracked_company` fields (no DB).

    Precedence: an explicit `catalog_slug` (or a `name` that matches a catalog
    slug) yields an `active` catalog company. Otherwise a `careers_url` is run
    through ATS detection: a board on a family `detect_ats` collects becomes
    `active`; anything else is queued `pending` (adapter needed). Raises CompanyError on bad input.
    """
    if catalog_slug:
        if catalog_slug in CATALOG:
            entry = CATALOG[catalog_slug]
            discovery_fields = discovery_company_fields(catalog_slug)
            return {
                "slug": catalog_slug,
                "display": entry["display"],
                "adapter": entry["adapter"],
                "board_token": entry["board_token"],
                # Carried from the catalog row, absent for a single-deployment
                # family. Never defaulted: region-less and global are different
                # claims, and Lever answers the same 404 for a wrong region as
                # for a wrong token, so a region the row never stated cannot be
                # recovered from the failure.
                "board_region": entry.get("board_region"),
                "careers_url": (
                    discovery_fields["careers_url"] if discovery_fields is not None else None
                ),
                "status": "active",
                "source": "catalog",
            }
        listed = directory_company(catalog_slug)
        if listed is not None:
            # A directory company followed by name. Its board was
            # live when the directory was built; a board closed since fails
            # like any dead token, and its binding starts without closure
            # authority until a clean scan grants it.
            return {
                "slug": listed.slug,
                "display": listed.display,
                "adapter": listed.adapter,
                "board_token": listed.board_token,
                "board_region": listed.board_region,
                "careers_url": None,
                "status": "active",
                "source": FOLLOWED_BY_NAME,
            }
        try:
            fields = discovery_company_fields(catalog_slug)
        except ValueError as exc:
            raise CompanyError(f"'{catalog_slug}' is not currently available: {exc}") from exc
        if fields is None:
            raise CompanyError(f"'{catalog_slug}' is not in the catalog")
        # Same key set whichever branch answered; the discovery directory has no
        # region either, and a caller must not have to know which path it took.
        return {"board_region": None, **fields}

    if not name and not careers_url:
        raise CompanyError("provide a catalog company, or a name and careers URL")

    # A bare name that happens to match the catalog -> treat as a catalog add.
    if name:
        maybe = slugify(name)
        if maybe in CATALOG:
            return resolve_company(catalog_slug=maybe)

    if not careers_url:
        raise CompanyError("company not in catalog; a careers URL is required")

    display = (name or "").strip() or _display_from_url(careers_url)
    slug = slugify(display) or slugify(_display_from_url(careers_url))
    if not slug:
        raise CompanyError("could not derive a company slug")

    detected = detect_ats(careers_url)
    if detected is not None:
        return {
            "slug": slug,
            "display": display or slug,
            "adapter": detected.adapter,
            "board_token": detected.board_token,
            # Stored at resolution time because it cannot be recovered later:
            # Lever answers the same 404 for a wrong region and a wrong token,
            # so an EU tenant fetched from the global host looks exactly like a
            # dead board.
            "board_region": detected.region.value if detected.region else None,
            "careers_url": careers_url.strip(),
            "status": "active",
            "source": "url",
        }
    return {
        "slug": slug,
        "display": display or slug,
        "adapter": None,
        "board_token": None,
        "board_region": None,
        "careers_url": careers_url.strip(),
        "status": "pending",
        "source": "url",
    }


def _display_from_url(url: str) -> str:
    from urllib.parse import urlparse

    host = urlparse(url if "://" in url else "https://" + url).hostname or ""
    parts = [p for p in host.split(".") if p not in {"www", "com", "io", "co", "net", "org"}]
    return (parts[0].capitalize() if parts else "").strip()


async def get_tracked_companies(session: AsyncSession) -> list[TrackedCompany]:
    rows = (
        await session.scalars(select(TrackedCompany).order_by(TrackedCompany.display))
    ).all()
    return list(rows)


async def visible_company_names(session: AsyncSession) -> list[tuple[str, str]]:
    """`(slug, display)` of every visible tracked company, by display name: the
    two columns a company picker needs, without building every row."""
    rows = await session.execute(
        select(TrackedCompany.slug, TrackedCompany.display)
        .where(TrackedCompany.visible.is_(True))
        .order_by(TrackedCompany.display)
    )
    return [(slug, display) for slug, display in rows]


class ScanTarget(TypedDict):
    """One company a scan reads, as `get_active_targets` builds it."""

    display: str
    adapter: str
    board_token: str | None
    board_region: str | None
    enabled: bool
    #: The user's consent to collect a walled company, as the register
    #: fingerprint it covers. Every collection path hands it to
    #: `collection_access`; None for the unwalled majority.
    consent: str | None
    #: A recipe binding's pinned, compiled revision, or None when it is missing
    #: or does not compile. Only a run that collects attaches it
    #: (`recipe_store.attach_recipe_plans`), and only to a recipe-bound target.
    recipe_plan: NotRequired[ExecutablePlan | None]


async def get_active_targets(session: AsyncSession) -> dict[str, ScanTarget]:
    """Scrapeable DB companies as pipeline targets: only active + enabled rows."""
    rows = await session.scalars(
        select(TrackedCompany).where(
            TrackedCompany.status == "active", TrackedCompany.enabled.is_(True)
        )
    )
    return {
        r.slug: {
            "display": r.display,
            "adapter": r.adapter,
            "board_token": r.board_token,
            "board_region": r.board_region,
            "enabled": True,
            "consent": r.consent_fingerprint,
        }
        for r in rows
        if r.adapter
    }


async def add_company(session: AsyncSession, fields: dict) -> TrackedCompany:
    slug = fields["slug"]
    if is_builtin(slug):
        raise CompanyConflict(f"'{slug}' is a built-in company and is always tracked")
    existing = await session.get(TrackedCompany, slug)
    if existing is not None:
        raise CompanyConflict(f"'{slug}' is already tracked")
    row = TrackedCompany(**fields, role_catalog_status="pending")
    session.add(row)
    await session.flush()
    return row


class ConsentRequired(CompanyError):
    """Following a walled company needs the user's consent."""


#: Longest consent text stored. The dialogs are a few sentences; anything past
#: this is not a dialog a person read.
CONSENT_TEXT_MAX = 4000


def record_consent(
    row: TrackedCompany, text: str, *, locale: str = "en", now: datetime | None = None
) -> None:
    """Record that the user consented to collecting this walled company.

    The only writer of the consent columns. It stores the dialog text the user
    confirmed, the language it was shown in, and the register fingerprint of
    the wall they were shown, as the record of what was agreed. The record is
    never re-checked against the register: the user is asked once per company,
    and a stored consent stands whatever the register later records.
    """
    wall = company_wall(row.slug, row)
    if wall is None:
        raise CompanyError(f"'{row.slug}' is not walled; there is nothing to consent to")
    text = text.strip()
    if not text or len(text) > CONSENT_TEXT_MAX:
        raise CompanyError("consent needs the text of the dialog the user confirmed")
    if not is_locale_tag(locale):
        raise CompanyError(f"consent needs the language it was shown in, got {locale!r}")
    row.consented_at = now or datetime.now(UTC)
    row.consent_text = text
    row.consent_locale = locale
    row.consent_fingerprint = wall.wall_fingerprint


def require_consent_to_follow(row: TrackedCompany) -> None:
    """Refuse to START following a walled company the user never consented to.

    Only the transition needs it. A walled company already followed without
    consent (an older install) stays followed and simply is not
    scanned — so re-sending the roster for some other change never fails on it.
    A consent is kept on unfollow, so following again never asks again.
    """
    wall = company_wall(row.slug, row)
    if wall is not None and not row.consent_fingerprint:
        raise ConsentRequired(
            f"'{row.slug}' limits automated collection; follow it through its consent dialog"
        )


async def record_route(
    session: AsyncSession, slug: str, route: str, *, now: datetime | None = None
) -> bool:
    """Move a company to another route of its connector family.

    Called by the pipeline when a route-family adapter detected that the
    company's board now lives on another route. Three writes, one decision:

    * `adapter` becomes the new route, so every gate reads the new route's
      register row — a move onto a walled route waits for the user's consent;
    * the company's current binding is RETIRED, because a binding names its
      connector and this one stops speaking for the company;
    * a fresh binding is seeded with closure withheld (`plan_binding_seeds`), so
      the new route may close nothing until a complete listing validates it.

    Refuses a move across families, to an unknown adapter, or for a company
    with no adapter: this is a route change, never a way to rebind a company to
    an unrelated source. Returns False when the company is already there.
    """
    row = await session.get(TrackedCompany, slug)
    if row is None:
        raise CompanyNotFound(f"unknown company '{slug}'")
    if row.adapter == route:
        return False
    family = route_family_of(route)
    if route not in ADAPTER_REGISTRY or family is None or family != route_family_of(row.adapter):
        raise CompanyError(
            f"'{slug}' cannot move from {row.adapter!r} to {route!r}: not routes of one family"
        )
    previous = row.adapter
    row.adapter = route
    await _rebind(
        session, row, f"retired: route moved {previous} -> {route}", now or datetime.now(UTC)
    )
    logger.info("%s: route moved %s -> %s; binding reseeded, closure withheld", slug, previous, route)
    return True


async def _rebind(session: AsyncSession, row: TrackedCompany, note: str, moved_at: datetime) -> None:
    """Retire the company's current bindings and seed one for what the row now names.

    A binding names its connector, so once the row points somewhere else the
    old one stops speaking for the company. The fresh seed withholds closure
    (`plan_binding_seeds`) until a complete listing validates it.
    """
    for binding in (
        await session.scalars(
            select(SourceBinding).where(
                SourceBinding.company_slug == row.slug, SourceBinding.status != "retired"
            )
        )
    ).all():
        binding.status = "retired"
        binding.retired_at = moved_at
        binding.notes = note
    await session.flush()
    session.add_all(
        SourceBinding(**seed)
        for seed in plan_binding_seeds([row], set(), known_adapters=frozenset(ADAPTER_REGISTRY))
    )
    await session.flush()


async def record_board_move(
    session: AsyncSession,
    slug: str,
    *,
    adapter: str,
    board_token: str,
    board_region: str | None = None,
    now: datetime | None = None,
) -> bool:
    """Point a company at the careers page it moved to.

    Companies move boards, to another ATS or to a renamed board on the same
    one, and the stored address then answers 404 on every scan. The caller has already verified the new board answers (`board_relocate`);
    this writes the move, the way `record_route` writes a route change:

    * `adapter`, `board_token` and `board_region` name the new board;
    * the current binding is RETIRED and a fresh one seeded with closure
      withheld, so the new board closes nothing until a complete listing
      validates it. Postings are keyed `company:req_id`, not by binding, so once
      it does, the old board's postings close by the ordinary two-miss rule and
      a posting the new board lists under the same id simply continues;
    * the role catalog goes back to `pending`, since it described the old board.

    A built-in's board is declared in `config.COMPANIES` and re-seeded from
    there, so it moves by a code change, never here. Returns False when the
    company already reads that board.
    """
    if adapter not in ADAPTER_REGISTRY:
        raise CompanyError(f"unknown adapter {adapter!r}")
    if is_builtin(slug):
        raise CompanyError(f"'{slug}' is built in; its careers page is set in config")
    row = await session.get(TrackedCompany, slug)
    if row is None:
        raise CompanyNotFound(f"'{slug}' is not a tracked company")
    if (row.adapter, row.board_token, row.board_region) == (adapter, board_token, board_region):
        return False
    previous = f"{row.adapter}:{row.board_token}"
    row.adapter = adapter
    row.board_token = board_token
    row.board_region = board_region
    row.status = "active"
    row.role_catalog_status = "pending"
    row.role_catalog_error = None
    await _rebind(
        session, row, f"retired: board moved {previous} -> {adapter}:{board_token}",
        now or datetime.now(UTC),
    )
    logger.info("%s: board moved %s -> %s:%s; binding reseeded, closure withheld",
                slug, previous, adapter, board_token)
    return True


async def set_enabled(session: AsyncSession, slug: str, enabled: bool) -> TrackedCompany:
    row = await session.get(TrackedCompany, slug)
    if row is None:
        raise CompanyNotFound(f"'{slug}' is not a tracked company")
    if enabled and not row.enabled:
        require_consent_to_follow(row)
    row.enabled = enabled
    await session.flush()
    return row


async def follow_with_set(session: AsyncSession, slug: str) -> TrackedCompany | None:
    """Follow a directory company because the whole-set follow found it roles.

    None when the slug is not in the directory or is already a row: a company
    the user followed by name, unfollowed, or muted keeps its own row as they
    left it — the set never overrules a choice about one company.
    """
    try:
        fields = resolve_company(catalog_slug=slug)
    except CompanyError:
        return None
    if fields.get("source") != FOLLOWED_BY_NAME:
        return None  # a catalog or recommended company is never the set's to add
    try:
        return await add_company(session, {**fields, "source": FOLLOWED_WITH_SET})
    except CompanyConflict:
        return None


async def set_followed_with_set(
    session: AsyncSession, enabled: bool, slugs: Iterable[str] | None = None,
) -> list[str]:
    """Turn the set's own rows on or off; returns the slugs that changed.

    Only rows the set brought in (`source="directory-set"`) are touched, so a
    directory company followed by name stays followed when the set is turned
    off. `slugs` narrows the change: turning the set back on restores exactly
    the rows turning it off stopped, and never one the user switched off alone.
    """
    query = select(TrackedCompany).where(
        TrackedCompany.source == FOLLOWED_WITH_SET, TrackedCompany.enabled.is_(not enabled)
    )
    if slugs is not None:
        query = query.where(TrackedCompany.slug.in_(list(slugs)))
    rows = (await session.scalars(query)).all()
    for row in rows:
        row.enabled = enabled
    await session.flush()
    return sorted(row.slug for row in rows)


async def set_visible(session: AsyncSession, slug: str, visible: bool) -> TrackedCompany:
    """Toggle a user-added company's visibility (browse/aggregate display switch)."""
    row = await session.get(TrackedCompany, slug)
    if row is None:
        raise CompanyNotFound(f"'{slug}' is not a tracked company")
    row.visible = visible
    await session.flush()
    return row


class OffBoardSlugs(list[str]):
    """`off_board_company_slugs`' answer: the slugs, a plain list as every
    reader takes it, plus which of them the user does not follow, read in the
    same round trip so a row that says "not checked any more" costs a list
    response no extra query."""

    def __init__(self, slugs: Iterable[str] = (), unfollowed: Iterable[str] = ()) -> None:
        super().__init__(slugs)
        self.unfollowed: frozenset[str] = frozenset(unfollowed)


async def off_board_company_slugs(session: AsyncSession) -> OffBoardSlugs:
    """Companies whose postings stay off every browse/aggregate surface: the
    ones the user hid, and the ones the user does not follow.

    The Board, search, counts and statistics show only companies the user
    follows. Unfollowing sets `enabled` false and leaves `visible` true, so a
    visible-only list would keep an unfollowed company's postings on the Board,
    unverified for as long as nobody followed it again: nothing scans it, and
    closure needs a scan. Its rows are kept, untouched (`jobs` is the
    longitudinal asset); following again restores them at once, and its first
    scan starts at once. Reads by id, Saved and Compare bypass this
    list, as they bypass hiding.

    Every company (built-in or user-added) is a row here, so this is a single
    query, no built-in special case. A posting whose company has no row is
    never named, so it stays.
    """
    rows = (
        await session.execute(
            select(TrackedCompany.slug, is_followed()).where(
                not_(and_(TrackedCompany.visible.is_(True), is_followed()))
            )
        )
    ).all()
    return OffBoardSlugs(
        sorted(slug for slug, _ in rows), (slug for slug, followed in rows if not followed)
    )


async def unfollowed_company_slugs(session: AsyncSession) -> list[str]:
    """Companies the user does not follow: their postings are not checked any
    more, which a Saved role at one says."""
    rows = await session.scalars(select(TrackedCompany.slug).where(not_(is_followed())))
    return sorted(rows.all())


async def ensure_builtins(session: AsyncSession) -> None:
    """Seed/refresh one `tracked_company` row per built-in from `config.COMPANIES`.

    Idempotent and safe to call on every startup / pipeline run: it inserts any
    missing built-in (visible, and followed only when it is on the curated list)
    and keeps its `adapter`/`display` in sync with the code, but never overrides
    an operator's `enabled`/`visible`/`status` choice. Insert-only is also what
    keeps an existing install's follows when curated membership changes: the
    curated list decides where a user STARTS, never what they chose since.
    This is what lets built-ins and user-added companies share one code path —
    and lets a new built-in appear just by declaring it in `blueprint.BLUEPRINT`.

    On a fresh install (no company row at all) it also follows the rest of the
    curated list, the catalog companies on it (`_follow_the_curated_list`), in
    the same transaction, so the install starts on the whole list before its
    first screen asks anything.

    A built-in the code moves to another adapter is rebound as any move is
    (`_rebind`): its old binding stops speaking for it, and the new one closes
    nothing until a complete listing validates it. A move to another route of
    the same family is the pipeline's to record (`record_route`), so a stored
    route of the blueprint's family stays.
    """
    # Read before anything is inserted: a row of any kind, built-in included,
    # means an install that has started and whose follows are its own.
    fresh = (await session.execute(select(TrackedCompany.slug).limit(1))).first() is None
    stored = dict(
        (
            await session.execute(
                select(TrackedCompany.slug, TrackedCompany.adapter).where(
                    TrackedCompany.slug.in_(list(COMPANIES))
                )
            )
        ).all()
    )
    moved: list[tuple[str, str, str]] = []
    for slug, cfg in COMPANIES.items():
        adapter = cfg["adapter"]
        previous = stored.get(slug)
        family = route_family_of(adapter)
        if previous and family is not None and route_family_of(previous) == family:
            adapter = previous
        elif previous and previous != adapter:
            moved.append((slug, previous, adapter))
        stmt = pg_insert(TrackedCompany).values(
            slug=slug,
            display=cfg["display"],
            adapter=adapter,
            board_token=None,
            careers_url=None,
            status="active",
            # `is_curated`, not the blueprint flag alone: a walled built-in is
            # never curated whatever its blueprint says, and a fresh
            # install must not follow a wall nobody consented to.
            enabled=is_curated(slug),
            visible=True,
            source="builtin",
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=[TrackedCompany.slug],
            set_={"display": cfg["display"], "adapter": adapter, "source": "builtin"},
        )
        await session.execute(stmt)
    now = datetime.now(UTC)
    for slug, previous, adapter in moved:
        row = await session.get(TrackedCompany, slug, populate_existing=True)
        if row is None:
            continue
        await _rebind(session, row, f"retired: built-in moved {previous} -> {adapter}", now)
        logger.info("%s: built-in moved %s -> %s; binding reseeded, closure withheld", slug, previous, adapter)
    if fresh:
        await _follow_the_curated_list(session)


async def _follow_the_curated_list(session: AsyncSession) -> None:
    """Follow every curated company that is not a built-in, as a fresh install.

    A company a person never followed has no row, so this runs only while there
    is no row at all: after that a missing curated company is one the person
    has not chosen, and adding it would follow it behind their back. Insert-only
    and conflict-free, so two first processes racing on one empty database end
    with the same rows.
    """
    for slug in COMPANY_DISCOVERY:
        if slug in COMPANIES or not is_curated(slug):
            continue
        try:
            fields = resolve_company(catalog_slug=slug)
        except CompanyError as exc:
            logger.warning("%s: on the curated list but not followed on a fresh install: %s", slug, exc)
            continue
        stmt = pg_insert(TrackedCompany).values(
            **fields, enabled=True, visible=True, role_catalog_status="pending",
        )
        await session.execute(stmt.on_conflict_do_nothing(index_elements=[TrackedCompany.slug]))


async def ensure_catalog_connectors(session: AsyncSession) -> list[str]:
    """Give a `pending` company its connector once the catalog gains one.

    Adding a `CATALOG` entry makes `connector_state` report **ready**, because
    that reads the catalog; without this pass the stored row would keep
    `adapter=None, status="pending"` forever, because nothing else reads the
    catalog back into it. `ensure_builtins` is the
    equivalent pass for `config.COMPANIES` and covers built-ins only.

    Without it the failure is silent in the worst direction: the card says
    "Ready to enable" and enabling it does **nothing**, because
    `get_active_targets` filters on `if r.adapter`, so the company is dropped
    from every run with no error, no drift alert and no binding.

    Deliberately narrow, for the reason `ensure_builtins` is: it only ever
    UPGRADES a row that has no adapter and is still `pending`. A company already
    carrying an adapter is left alone whatever the catalog now says — a
    URL-added row resolved its own board, and an operator who edited one is not
    to be overruled by a table. `enabled` and `visible` are never touched here
    either: acquiring a connector is not consent to start scraping.

    Returns the slugs it upgraded, so a caller can log what changed.
    """
    rows = (
        await session.scalars(
            select(TrackedCompany).where(
                TrackedCompany.status == "pending",
                TrackedCompany.adapter.is_(None),
                TrackedCompany.slug.in_(list(CATALOG)),
            )
        )
    ).all()
    upgraded: list[str] = []
    for row in rows:
        entry = CATALOG[row.slug]
        row.adapter = entry["adapter"]
        row.board_token = entry["board_token"]
        row.board_region = entry.get("board_region")
        row.status = "active"
        # `role_catalog_status` goes back to `pending` so the next run scans the
        # inventory; the stored value described a board we had no way to read.
        row.role_catalog_status = "pending"
        row.role_catalog_error = None
        upgraded.append(row.slug)
    if upgraded:
        await session.flush()
    return upgraded


# --------------------------------------------------------------------------- #
# Source binding seeding
#
# Every company row needs a binding, whenever it was created: a new built-in
# added to `config.COMPANIES` or a user-added company. A company without one
# falls back to `decide_closure_scope`'s company-scoped branch and skips the
# binding's closure gate. So this is an `ensure_*` reconciliation like
# `ensure_builtins` and `ensure_company_profiles`, not a one-shot migration:
# the gap cannot reopen the next time a company is added.
# --------------------------------------------------------------------------- #

#: Recorded on seeded rows so a binding's provenance stays readable in the DB.
_SEED_NOTE = (
    "seeded by ensure_source_bindings; closure withheld until a "
    "complete listing validates the binding"
)


def plan_binding_seeds(
    companies: Iterable[TrackedCompany],
    bound_slugs: set[str],
    *,
    known_adapters: Sequence[str] | frozenset[str],
) -> list[dict]:
    """Which companies need a seeded adapter binding, and with what fields.

    Pure and total, following `decide_closure_scope`: every branch
    that decides whether a company gains closure authority is testable on
    explicit inputs rather than through a session.

    Rules (top-down, first match wins):

    1. no `adapter` — not scrapeable, nothing to bind;
    2. already in `bound_slugs` — has a binding in ANY non-retired status.
       Deliberately not filtered to `stable`: a company mid-rebind sits at
       `reconciling`, and seeding a second `stable` binding underneath it would
       let two sources close the same company's jobs;
    3. `adapter` not in `known_adapters` — a stale row naming a connector that
       does not exist must never be handed closure authority;
    4. otherwise seed `stable`/**`none`** — collecting, not closing.

    Rule 4 withholds closure authority. Granting it at seeding would hand every
    newly onboarded company the right to close jobs by absence on the strength
    of a board token nobody had checked. A wrong-but-live token answers 200
    with a complete listing of somebody else's board, which passes every
    run-quality gate there is.

    The two knobs are deliberately split rather than both withheld:

    * `status` stays `stable`, because that is what the scheduler selects on
      (`scheduler._ensure_state`). A `shadow` row would never be reconciled, so
      it could never produce the evidence that activates it — the gate would be
      a deadlock, not a gate.
    * `closure_capability` is `none`, the model's own idiom for "may open and
      update jobs, never close by absence" (see `SourceBinding`). Authority is
      granted afterwards, from a run's evidence, by
      `db.binding.decide_binding_activation`.

    A row is still always emitted. Withholding must never become "no binding",
    which is a *widening*: `decide_closure_scope`'s no-row branch falls back to
    legacy company-scoped closure and closes everything.

    `activated_at` is left `None`: it means the binding was activated, which
    seeding is not.

    This function only ever emits `connector_kind` `adapter` — recipe bindings
    are created by `bind_recipe` and must still earn authority.
    """
    adapters = frozenset(known_adapters)
    seeds: list[dict] = []
    for company in companies:
        adapter = company.adapter
        if not adapter:
            continue
        if company.slug in bound_slugs:
            continue
        if adapter not in adapters:
            logger.warning(
                "skipping binding seed for %s: unknown adapter %r", company.slug, adapter
            )
            continue
        seeds.append(
            {
                "company_slug": company.slug,
                "connector_kind": "adapter",
                "connector_id": adapter,
                "status": "stable",
                "closure_capability": "none",
                "activated_at": None,
                "notes": _SEED_NOTE,
            }
        )
    return seeds


async def ensure_source_bindings(session: AsyncSession) -> int:
    """Seed a collecting, non-closing adapter binding for any company lacking one.

    Adapter seeds follow the withholding rule in `plan_binding_seeds`.

    Idempotent and safe on every pipeline/discovery run, like its `ensure_*`
    siblings. Returns the number seeded so the caller can log the heal.

    Safe under concurrent callers, which it has: the pipeline and discovery
    hold the run lock, but the scheduler's tick and the `/api/sync` route reach
    it through `_ensure_state` holding no lock that covers the other. Every
    seed is `stable`, so the partial unique index
    (`ix_source_bindings_one_active_per_company`) decides a race: a seed
    another writer already inserted is skipped, not raised. A recipe binding
    is made in a savepoint for the same reason.
    """
    # Recipe companies: the bundled recipes exist before anything
    # binds to them, and a company whose catalog entry names a recipe is bound
    # to its activated revision here.
    await ensure_bundled_recipes(session)
    for row in (await session.scalars(select(TrackedCompany).where(
        TrackedCompany.adapter == "recipe", TrackedCompany.board_token.is_not(None),
    ))).all():
        has_binding = await session.scalar(select(SourceBinding.id).where(
            SourceBinding.company_slug == row.slug, SourceBinding.status != "retired",
        ))
        if has_binding is None:
            try:
                async with session.begin_nested():
                    await bind_recipe(session, row.slug, str(row.board_token))
            except (CompanyError, CompanyConflict) as exc:
                logger.warning("recipe binding for %s not created: %s", row.slug, exc)
            except IntegrityError:
                logger.info("recipe binding for %s was made by another writer", row.slug)
    companies = (await session.scalars(select(TrackedCompany))).all()
    bound = set(
        (
            await session.scalars(
                select(SourceBinding.company_slug).where(SourceBinding.status != "retired")
            )
        ).all()
    )
    seeds = plan_binding_seeds(
        companies,
        bound,
        known_adapters=frozenset(ADAPTER_REGISTRY),
    )
    if not seeds:
        return 0
    seeded = list((await session.scalars(
        pg_insert(SourceBinding)
        .values(seeds)
        .on_conflict_do_nothing(index_elements=["company_slug"], index_where=SourceBinding.status == "stable")
        .returning(SourceBinding.company_slug)
    )).all())
    if not seeded:
        return 0
    logger.info(
        "seeded %d source binding(s), closure withheld pending validation: %s",
        len(seeded),
        ", ".join(sorted(seeded)),
    )
    return len(seeded)


async def bind_recipe(
    session: AsyncSession, slug: str, recipe_slug: str, *, now: datetime | None = None
) -> SourceBinding:
    """Collect a company through a stored recipe.

    Pins the recipe's DEFAULT (activated) revision; a later activation never
    retargets this binding. The binding collects from the start but closes
    nothing (`closure_capability='none'`) until a run earns it, and a recipe can
    earn it only while its pinned revision carries RoleBand's own validation
    (`db.binding.decide_binding_activation`).

    Refused for a company already collected by an adapter: moving live jobs to
    another source needs a shadow-and-reconcile migration, which this is not.
    Re-binding a recipe company retires its previous recipe binding (same
    company, same `req_id`s), and its authority starts again from `none`.
    """
    row = await session.get(TrackedCompany, slug)
    if row is None:
        raise CompanyNotFound(f"'{slug}' is not a tracked company")
    recipe = await session.scalar(select(ConnectorRecipe).where(ConnectorRecipe.slug == recipe_slug))
    if recipe is None:
        raise RecipeNotFound(f"no recipe '{recipe_slug}'")
    if recipe.status != "active" or recipe.default_revision_id is None:
        raise RecipeConflict(f"recipe '{recipe_slug}' has no activated revision")
    stamp = now or datetime.now(UTC)
    current = (await session.scalars(
        select(SourceBinding).where(SourceBinding.company_slug == slug, SourceBinding.status != "retired")
    )).all()
    for binding in current:
        if binding.connector_kind != "recipe":
            raise RecipeConflict(
                f"'{slug}' is collected by {binding.connector_id!r}; moving it to a recipe"
                " needs a reviewed shadow-and-reconcile proposal"
            )
        binding.status = "retired"
        binding.retired_at = stamp
    await session.flush()
    binding = SourceBinding(
        company_slug=slug,
        connector_kind="recipe",
        connector_id=recipe_slug,
        recipe_revision_id=recipe.default_revision_id,
        status="stable",
        closure_capability="none",
        notes=f"bound to recipe {recipe_slug} revision {recipe.default_revision_id} {stamp.isoformat(timespec='seconds')}",
    )
    session.add(binding)
    row.adapter = "recipe"
    row.status = "active"
    await session.flush()
    return binding
