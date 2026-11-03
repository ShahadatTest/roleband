"""Audited source changes; shadow listings never write canonical postings."""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit, urlunsplit

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from tracker.company_store import CompanyNotFound, RecipeConflict, RecipeNotFound
from tracker.config import get_settings
from tracker.connectors.extract.version import validation_is_current
from tracker.db.binding import get_active_binding
from tracker.db.models import (
    BindingReconciliationDecision,
    ConnectorRecipe,
    ConnectorRecipeRevision,
    Job,
    JobSourceIdentity,
    SourceBinding,
    TrackedCompany,
)


def canonical_url(url: str) -> str:
    """Keep path and query exact; only host case and fragments are immaterial."""
    try:
        parts = urlsplit(url)
        if parts.scheme not in ("http", "https") or not parts.hostname or parts.username is not None:
            return ""
        return urlunsplit((parts.scheme, parts.netloc.lower(), parts.path, parts.query, ""))
    except ValueError:
        return ""


async def _company_lock(session: AsyncSession, company: str) -> TrackedCompany:
    # The pipeline holds the same key across collection and persistence. A switch
    # cannot change the meaning of rows a running collector has already read.
    if not await session.scalar(text("SELECT pg_try_advisory_xact_lock(:key)"),
                                {"key": get_settings().advisory_lock_key}):
        raise RecipeConflict("collection is running; retry the source change when it finishes")
    row = await session.scalar(select(TrackedCompany).where(
        TrackedCompany.slug == company).with_for_update())
    if row is None:
        raise CompanyNotFound(f"'{company}' is not a tracked company")
    return row


async def recipe_revision(session: AsyncSession, recipe_slug: str) -> ConnectorRecipeRevision:
    recipe = await session.scalar(select(ConnectorRecipe).where(ConnectorRecipe.slug == recipe_slug))
    if recipe is None:
        raise RecipeNotFound(f"no recipe '{recipe_slug}'")
    revision = await session.get(ConnectorRecipeRevision, recipe.default_revision_id) if recipe.default_revision_id else None
    if recipe.status != "active" or revision is None:
        raise RecipeConflict("the proposed recipe needs an activated revision")
    return revision


async def _comparison_jobs(session: AsyncSession, company: str, proposed: list[dict]) -> list[dict]:
    jobs = (await session.scalars(select(Job).where(
        Job.company == company).order_by(Job.id))).all()
    req_ids = {job["req_id"] for job in proposed}
    urls = {canonical_url(job["url"]) for job in proposed} - {""}
    aliases: dict[int, list[str]] = defaultdict(list)
    for job_id, key in (await session.execute(select(JobSourceIdentity.job_id, JobSourceIdentity.source_key)
        .join(SourceBinding, SourceBinding.id == JobSourceIdentity.binding_id)
        .where(SourceBinding.company_slug == company, SourceBinding.status == "stable")
        .order_by(JobSourceIdentity.source_key))).all():
        aliases[job_id].append(key.removeprefix(f"{company}:"))
    return [{"job_id": job.id, "req_id": job.req_id, "source_key": job.dedupe_key,
             "url": job.url, "title": job.title, "locations": list(job.locations or []),
             "status": job.status, "provider_ids": aliases.get(job.id, [job.req_id])}
            for job in jobs if job.status == "open" or set(aliases.get(job.id, [job.req_id])) & req_ids
            or canonical_url(job.url) in urls]


def _audit(session: AsyncSession, binding_id: int, decision: str, *, job_id: int | None = None,
           source_key: str | None = None, evidence: dict | None = None, actor: str = "system",
           reason: str | None = None) -> None:
    session.add(BindingReconciliationDecision(
        binding_id=binding_id, decision=decision, job_id=job_id, source_key=source_key,
        evidence=evidence or {}, actor=actor, reason=reason,
    ))


def exact_matches(old: list[dict], new: list[dict]) -> dict[str, tuple[int, str]]:
    """Only mutually unique exact identities link, including across match methods."""
    ids: dict[str, set[int]] = defaultdict(set)
    urls: dict[str, set[int]] = defaultdict(set)
    for job in old:
        for req_id in job.get("provider_ids", [job["req_id"]]):
            if req_id:
                ids[req_id].add(job["job_id"])
        url = canonical_url(job["url"])
        if url:
            urls[url].add(job["job_id"])
    candidates: dict[str, dict[int, str]] = {}
    for posting in new:
        matches = {job_id: "provider_id" for job_id in ids.get(posting["req_id"], ())}
        url = canonical_url(posting["url"])
        for job_id in urls.get(url, ()):
            matches.setdefault(job_id, "canonical_url")
        candidates[posting["source_key"]] = matches
    uses = Counter(job_id for matches in candidates.values() for job_id in matches)
    return {key: next(iter(matches.items())) for key, matches in candidates.items()
            if len(matches) == 1 and uses[next(iter(matches))] == 1}


async def propose(
    session: AsyncSession, company: str, *, recipe_slug: str, revision_id: int,
    jobs: list[dict], evidence: dict,
) -> dict:
    row = await _company_lock(session, company)
    previous = await get_active_binding(session, company)
    if previous is None or previous.status != "stable":
        raise RecipeConflict("the company needs a stable current binding")
    if await session.scalar(select(SourceBinding.id).where(
        SourceBinding.company_slug == company, SourceBinding.status.in_(("shadow", "reconciling")))):
        raise RecipeConflict("a source change is already awaiting review")
    revision = await recipe_revision(session, recipe_slug)
    if revision.id != revision_id or not evidence.get("passed") or len(jobs) != evidence.get("found"):
        raise RecipeConflict("the shadow listing is incomplete or its revision changed; run it again")
    new = [{**job, "source_key": f"{company}:{job['req_id']}"} for job in jobs]
    keys = [job["source_key"] for job in new]
    if len(set(keys)) != len(keys) or any(not job["req_id"] for job in new) or any(len(key) > 256 for key in keys):
        raise RecipeConflict("the shadow listing has missing or duplicate source identities")
    old = await _comparison_jobs(session, company, new)
    binding = SourceBinding(company_slug=company, connector_kind="recipe", connector_id=recipe_slug,
                            recipe_revision_id=revision.id, status="reconciling", closure_capability="none")
    session.add(binding)
    await session.flush()
    _audit(session, binding.id, "shadow", evidence={
        "previous_binding_id": previous.id, "old": old, "new": new, "check": evidence,
        "previous_company": {"adapter": row.adapter, "board_token": row.board_token, "status": row.status},
    })
    matches = exact_matches(old, new)
    linked = {job_id for job_id, _ in matches.values()}
    review_candidates: dict[tuple[str, tuple[str, ...]], list[int]] = defaultdict(list)
    for job in old:
        review_candidates[job["title"], tuple(job["locations"])].append(job["job_id"])
    for job in new:
        key = job["source_key"]
        if key in matches:
            job_id, basis = matches[key]
            _audit(session, binding.id, "exact_auto", source_key=key, job_id=job_id, evidence={"basis": basis})
        else:
            review = review_candidates[job["title"], tuple(job["locations"])]
            _audit(session, binding.id, "unresolved", source_key=key, evidence={"title_location_candidates": review})
    for job in old:
        if job["status"] == "open" and job["job_id"] not in linked:
            _audit(session, binding.id, "unresolved", job_id=job["job_id"])
    await session.flush()
    return await detail(session, company, binding.id)


async def _records(
    session: AsyncSession, company: str, binding_id: int
) -> tuple[SourceBinding, Sequence[BindingReconciliationDecision]]:
    binding = await session.get(SourceBinding, binding_id)
    if binding is None or binding.company_slug != company:
        raise RecipeNotFound("no source change for this company and binding")
    records = (await session.scalars(select(BindingReconciliationDecision).where(
        BindingReconciliationDecision.binding_id == binding_id).order_by(BindingReconciliationDecision.id))).all()
    if not records or records[0].decision != "shadow":
        raise RecipeNotFound("the binding has no shadow listing")
    return binding, records


def _resolved(
    records: Sequence[BindingReconciliationDecision],
) -> tuple[dict[str | None, int | None], set[int], list[int], list[str], bool]:
    snapshot = records[0].evidence
    links: dict[str | None, int | None] = {}
    retired: set[int] = set()
    for record in records[1:]:
        if record.decision in ("exact_auto", "map", "new"):
            links[record.source_key] = record.job_id
        elif record.decision == "retire" and record.job_id is not None:
            retired.add(record.job_id)
    old = {j["job_id"] for j in snapshot["old"] if j["status"] == "open"}
    new = {j["source_key"] for j in snapshot["new"]}
    linked = [j for j in links.values() if j is not None]
    conflicts = len(linked) != len(set(linked)) or bool(set(linked) & retired)
    return links, retired, sorted(old - set(linked) - retired), sorted(new - links.keys()), conflicts


async def detail(session: AsyncSession, company: str, binding_id: int) -> dict:
    binding, records = await _records(session, company, binding_id)
    _, _, old, new, conflicts = _resolved(records)
    return {"company": company, "binding_id": binding.id, "status": binding.status,
            "previous_binding_id": records[0].evidence["previous_binding_id"],
            "unresolved_job_ids": old, "unresolved_source_keys": new, "conflicts": conflicts,
            "ready": binding.status == "reconciling" and not old and not new and not conflicts,
            "decisions": [{"id": r.id, "decision": r.decision, "job_id": r.job_id,
                           "source_key": r.source_key, "evidence": r.evidence,
                           "actor": r.actor, "reason": r.reason} for r in records]}


async def review(session: AsyncSession, company: str, binding_id: int, *,
                 decision: str, source_key: str | None, job_id: int | None, reason: str) -> dict:
    await _company_lock(session, company)
    binding, records = await _records(session, company, binding_id)
    if binding.status != "reconciling" or not reason.strip():
        raise RecipeConflict("only an awaiting source change can be reviewed, with a reason")
    snapshot = records[0].evidence
    old = {j["job_id"] for j in snapshot["old"]}
    new = {j["source_key"] for j in snapshot["new"]}
    if (decision == "map" and (source_key not in new or job_id not in old)
        or decision == "new" and (source_key not in new or job_id is not None)
        or decision == "retire" and (job_id not in old or source_key is not None)
        or decision not in ("map", "new", "retire")):
        raise RecipeConflict("the decision must name postings from this shadow listing")
    links, retired, _, _, _ = _resolved(records)
    if decision == "map" and (job_id in retired or any(k != source_key and v == job_id for k, v in links.items())):
        raise RecipeConflict("a posting can map only once and cannot also be retired")
    if decision == "retire" and job_id in links.values():
        raise RecipeConflict("a mapped posting cannot be retired")
    _audit(session, binding_id, decision, source_key=source_key, job_id=job_id, actor="user", reason=reason.strip())
    await session.flush()
    return await detail(session, company, binding_id)


async def activate(session: AsyncSession, company: str, binding_id: int) -> dict:
    row = await _company_lock(session, company)
    binding, records = await _records(session, company, binding_id)
    snapshot = records[0].evidence
    links, retired, old, new, conflicts = _resolved(records)
    if binding.status != "reconciling" or old or new or conflicts:
        raise RecipeConflict("activation requires every posting resolved one-to-one")
    previous = await get_active_binding(session, company)
    if previous is None or previous.id != snapshot["previous_binding_id"]:
        raise RecipeConflict("the current binding changed; run a fresh shadow listing")
    if datetime.now(UTC) - records[0].created_at > timedelta(hours=24) or await _comparison_jobs(session, company, snapshot["new"]) != snapshot["old"]:
        raise RecipeConflict("the shadow listing is stale; cancel it and run a fresh one")
    revision = await session.get(ConnectorRecipeRevision, binding.recipe_revision_id)
    if revision is None or not validation_is_current(revision.validation):
        raise RecipeConflict("the pinned recipe revision needs RoleBand validation")
    # A source key already used by another canonical row cannot be reused even
    # when the reviewer called it new: the unique job key outlives bindings.
    for key, job_id in links.items():
        collision = await session.scalar(select(Job.id).where(Job.dedupe_key == key))
        if collision is not None and collision != job_id:
            raise RecipeConflict("a proposed source key belongs to another canonical posting")
    stamp = datetime.now(UTC)
    previous.status, previous.retired_at = "retired", stamp
    _audit(session, binding.id, "retire_binding", evidence={"binding_id": previous.id})
    await session.flush()
    for key, job_id in links.items():
        if job_id is not None:
            automatic = next(r for r in reversed(records) if r.source_key == key and r.decision in ("map", "exact_auto")).decision == "exact_auto"
            session.add(JobSourceIdentity(binding_id=binding.id, job_id=job_id, source_key=key,
                                          first_seen=stamp, origin="exact_auto" if automatic else "reviewer_map"))
    binding.status, binding.closure_capability = "stable", "none"
    row.adapter, row.board_token, row.status = "recipe", binding.connector_id, "active"
    _audit(session, binding.id, "activate", evidence={"retired_job_ids": sorted(retired)})
    await session.flush()
    return await detail(session, company, binding_id)


async def rollback(session: AsyncSession, company: str, binding_id: int, *, reason: str) -> dict:
    row = await _company_lock(session, company)
    binding, records = await _records(session, company, binding_id)
    if not reason.strip() or binding.status not in ("stable", "reconciling"):
        raise RecipeConflict("a source change can be cancelled or rolled back once, with a reason")
    stamp = datetime.now(UTC)
    if binding.status == "stable":
        active = await get_active_binding(session, company)
        if active is None or active.id != binding.id:
            raise RecipeConflict("another binding is current; rollback would overwrite it")
        previous = await session.get(SourceBinding, records[0].evidence["previous_binding_id"])
        if previous is None:
            raise RecipeConflict("the previous binding is missing")
        binding.status, binding.retired_at = "retired", stamp
        await session.flush()
        previous.status, previous.retired_at, previous.closure_capability = "stable", None, "none"
        previous.activated_at = None
        saved = records[0].evidence["previous_company"]
        row.adapter, row.board_token, row.status = saved["adapter"], saved["board_token"], saved["status"]
        _audit(session, binding.id, "retire_binding", evidence={"binding_id": binding.id})
    else:
        binding.status, binding.retired_at = "retired", stamp
    _audit(session, binding.id, "rollback", actor="user", reason=reason.strip())
    await session.flush()
    return await detail(session, company, binding_id)
