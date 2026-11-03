"""Source binding resolution + closure scoping.

This module answers one question the pipeline must never get wrong: **which
jobs is this run allowed to close by absence?**

The dual-read rule
------------------
Closure is scoped to source identities, and a job may exist without one. Two
failure modes follow:

- scope closure to identities only -> jobs without an identity never close,
  stale postings accumulate forever;
- silently fall back to `company` + `seen_keys` -> a binding change lets one
  source close postings another source owns.

A job with no identity under any binding is closable *only* by a binding that
is both `stable` and `authoritative`; a job owned by a different binding is never
closable. A non-stable binding closes nothing, ever.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tracker.connectors.extract.version import validation_is_current
from tracker.connectors.recipes.outcome import SourceOutcome
from tracker.db.models import (
    BindingReconciliationDecision,
    ConnectorRecipeRevision,
    Job,
    JobSourceIdentity,
    SourceBinding,
)

__all__ = [
    "ActivationDecision",
    "ClosureScope",
    "activate_validated_binding",
    "decide_binding_activation",
    "decide_closure_scope",
    "get_active_binding",
    "load_identity_map",
    "resolve_closure_scope",
]


@dataclass(frozen=True)
class ClosureScope:
    """What a run may close, and why.

    `reason` is recorded in the run audit so a suppressed closure is always
    explainable after the fact -- "closed nothing" and "was not allowed to close
    anything" must never look the same in the record.
    """

    may_close: bool
    closable_job_ids: frozenset[int]
    reason: str
    #: The open postings this listing is evidence about: the ones whose misses
    #: it counts. Equal to `closable_job_ids`; a posting closes only on its
    #: second miss, which `repo.record_absence` decides.
    speaks_for: frozenset[int] = frozenset()

    @property
    def suppressed(self) -> bool:
        return not self.may_close


async def get_active_binding(session: AsyncSession, company: str) -> SourceBinding | None:
    """The company's current (non-retired) binding, **whatever its status**.

    Deliberately unfiltered by status. Filtering to `stable` here would make a
    company mid-rebind (`status='reconciling'`) indistinguishable from a company
    with no binding row at all -- and the no-binding case falls through to
    company-scoped closure, which would close the entire company exactly
    when reconciliation is protecting it. The status gate belongs in
    `decide_closure_scope`, where "exists but not stable" is its own branch.
    """
    result = await session.execute(
        select(SourceBinding)
        .where(SourceBinding.company_slug == company, SourceBinding.status != "retired")
        # A stable binding wins if several coexist (proposed/shadow may overlap
        # during a rebind); otherwise the newest.
        .order_by((SourceBinding.status == "stable").desc(), SourceBinding.id.desc())
    )
    return result.scalars().first()


async def load_identity_map(
    session: AsyncSession, binding_id: int
) -> dict[str, JobSourceIdentity]:
    """`source_key -> identity` for one binding."""
    result = await session.execute(
        select(JobSourceIdentity).where(JobSourceIdentity.binding_id == binding_id)
    )
    return {identity.source_key: identity for identity in result.scalars()}


async def _identity_owned_job_ids(session: AsyncSession, binding_id: int) -> set[int]:
    result = await session.execute(
        select(JobSourceIdentity.job_id).where(JobSourceIdentity.binding_id == binding_id)
    )
    return set(result.scalars())


async def _job_ids_with_any_identity(session: AsyncSession, job_ids: Iterable[int]) -> set[int]:
    """Job ids some LIVE binding claims.

    A retired binding claims nothing. When a company moves boards its old
    binding is retired and a fresh one seeded, and the postings the old board
    listed keep its aliases; counting those would put every one of them
    outside the new binding's closure scope, where no listing could ever close
    them. Retired aliases stay on the row as provenance, and say nothing about
    who may close it.
    """
    ids = list(job_ids)
    if not ids:
        return set()
    result = await session.execute(
        select(JobSourceIdentity.job_id)
        .join(SourceBinding, SourceBinding.id == JobSourceIdentity.binding_id)
        .where(JobSourceIdentity.job_id.in_(ids), SourceBinding.status != "retired")
    )
    return set(result.scalars())


def decide_closure_scope(
    *,
    binding: SourceBinding | None,
    open_job_ids: Sequence[int],
    owned_job_ids: set[int],
    job_ids_with_any_identity: set[int],
    listing_is_authoritative: bool,
) -> ClosureScope:
    """The whole closure decision, as a pure function.

    Split from its queries deliberately: every way this repo can destroy its
    longitudinal asset runs through these branches, so they are tested directly
    on explicit inputs rather than through a mocked session that would mostly
    assert the shape of the mock.
    """
    if not listing_is_authoritative:
        return ClosureScope(
            False, frozenset(), "listing not authoritative (capped/incomplete/errors)"
        )

    if binding is None:
        # No binding row: company-scoped closure, rather than silently halting
        # closure for a company that has no binding yet.
        return ClosureScope(
            True,
            frozenset(open_job_ids),
            "legacy: no binding row, company-scoped closure",
            speaks_for=frozenset(open_job_ids),
        )

    if binding.status != "stable":
        return ClosureScope(False, frozenset(), f"binding status={binding.status}")
    if binding.closure_capability != "authoritative":
        return ClosureScope(False, frozenset(), "binding closure_capability=none")

    open_ids = set(open_job_ids)
    owned = owned_job_ids & open_ids
    # Dual-read safety net: a job with NO identity under ANY binding may still be
    # closed by this stable+authoritative binding. A job owned by a *different*
    # binding is deliberately excluded: that is the rebind case, and closing it
    # would close live postings another source still lists.
    unmigrated = {job_id for job_id in open_ids if job_id not in job_ids_with_any_identity}
    scope = frozenset(owned | unmigrated)

    # No health gate: a failed, degraded or blocked scan starts every
    # posting's absence count again, so protection is kept per posting and there
    # is no company state to release.
    return ClosureScope(
        True,
        scope,
        f"binding {binding.id} stable/authoritative; "
        f"{len(owned)} owned, {len(unmigrated)} unmigrated",
        speaks_for=scope,
    )


# --------------------------------------------------------------------------- #
# Activation: how a withheld binding earns closure authority
#
# `plan_binding_seeds` creates every new binding `stable`/`none`: it collects,
# and closes nothing. This is the promotion path that grants the authority
# afterwards, without which a newly onboarded company's postings stay open
# forever.
#
# The evidence is the same evidence closure itself depends on: one reconcile
# that enumerated the board to a natural stop with no errors (`SourceOutcome.OK`)
# and saw rows. That proves the binding's connector and board token really do
# enumerate this tenant's listing.
#
# What it does NOT prove is that the tenant is the right *company*: a
# wrong-but-live board token answers 200 with somebody else's complete listing
# and satisfies every rule below. Nothing automatic can close that gap; it stays
# with the onboarding checks, `detect_ats()` resolving the token from the
# company's own careers URL, and `scripts.check_catalog_tokens`. What this gate
# prevents is a token nobody has checked carrying closure authority from the
# moment it is typed.
# --------------------------------------------------------------------------- #

#: The only scan mode that can validate a binding. Discovery is
#: non-authoritative by construction, and repair/shadow re-read a subset of the
#: board -- neither enumerates the listing, so neither is evidence of identity.
_VALIDATING_SCAN_MODE = "reconcile"


@dataclass(frozen=True)
class ActivationDecision:
    """Whether one run's evidence grants a withheld binding closure authority.

    `reason` is recorded on the run like `ClosureScope.reason`: "still withheld"
    must always be explainable, or a company that silently never closes looks
    identical to one with nothing to close.
    """

    activate: bool
    reason: str


def decide_binding_activation(
    *,
    binding: SourceBinding,
    outcome: SourceOutcome,
    scan_mode: str,
    scanned: int,
    revision_validated: bool = False,
) -> ActivationDecision:
    """Pure, total: may this run's evidence promote this binding?

    Split from its writes like `decide_closure_scope`, and for the same reason —
    this is the second function in the repo that can hand a source the right to
    close jobs by absence, so its branches are asserted on explicit inputs.

    Rules (top-down, first match wins). The first three are about the row, the
    rest about the run:

    1. nothing is withheld — already `authoritative`, so there is no decision;
    2. not an adapter binding, unless it is a recipe pinned to a revision
       RoleBand itself validated (`revision_validated`) — a recipe
       earns authority through the validated-revision flow, never from a
       run outcome alone. Without this rule a recipe author could grant
       themselves closure authority by shipping a recipe that enumerates
       cleanly, which is exactly what `SourceBinding`'s "assigned by RoleBand
       validation, never by recipe text" forbids. A validated recipe still has
       to pass every rule below, like an adapter;
    3. not `stable` — a `proposed`/`reconciling` binding is mid-lifecycle and
       promotion belongs to that lifecycle, not here;
    4. not a reconcile — see `_VALIDATING_SCAN_MODE`;
    5. outcome is not `OK` — anything else is an incomplete, errored, capped or
       bounded listing. Note this also excludes `unattempted`, so a
       policy-denied source can never activate anything;
    6. `scanned` is zero — an empty board is a *separate* question with its own
       two-confirmation contract, and an empty response must never be
       mistaken for proof that a board exists. A zero-row listing is never
       complete (`SchemaDriftDetector.settle_listing`) and a board proven
       empty classifies `empty`, so rule 5 catches this first; the rule is
       explicit anyway so it holds if rule 5 stops catching it.
    """
    if binding.closure_capability != "none":
        return ActivationDecision(
            False, f"closure_capability={binding.closure_capability}; nothing withheld"
        )
    if binding.connector_kind == "recipe" and not revision_validated:
        return ActivationDecision(
            False, "connector_kind=recipe; pinned revision not validated by RoleBand"
        )
    if binding.connector_kind not in ("adapter", "recipe"):
        return ActivationDecision(
            False, f"connector_kind={binding.connector_kind}; not activated by run evidence"
        )
    if binding.status != "stable":
        return ActivationDecision(False, f"binding status={binding.status}")
    if scan_mode != _VALIDATING_SCAN_MODE:
        return ActivationDecision(False, f"scan_mode={scan_mode} cannot validate a binding")
    if outcome is not SourceOutcome.OK:
        return ActivationDecision(False, f"outcome={outcome.value}; listing not complete and clean")
    if scanned <= 0:
        return ActivationDecision(False, "listing served no rows; empty boards are W2's question")
    return ActivationDecision(
        True, f"validated by a complete {outcome.value} listing (scanned={scanned})"
    )


async def activate_validated_binding(
    session: AsyncSession,
    binding: SourceBinding,
    *,
    outcome: SourceOutcome,
    scan_mode: str,
    scanned: int,
    now: datetime,
    run_id: int | None = None,
) -> ActivationDecision:
    """Apply `decide_binding_activation` to storage.

    Called after closure has already been resolved for this run, so the run that
    supplies the evidence is never also the run that acts on it ("first
    reconcile confirms, second closes"), and the reason a first listing cannot
    both prove a board exists and close jobs against it.

    `activated_at` is stamped here and nowhere else: seeding leaves it NULL.
    """
    revision_validated = False
    if binding.connector_kind == "recipe" and binding.recipe_revision_id is not None:
        validation = await session.scalar(
            select(ConnectorRecipeRevision.validation).where(
                ConnectorRecipeRevision.id == binding.recipe_revision_id
            )
        )
        revision_validated = validation_is_current(validation)
    decision = decide_binding_activation(
        binding=binding, outcome=outcome, scan_mode=scan_mode, scanned=scanned,
        revision_validated=revision_validated,
    )
    if not decision.activate:
        return decision

    binding.closure_capability = "authoritative"
    binding.activated_at = now
    evidence = (
        f"activated {now.isoformat(timespec='seconds')}: {decision.reason}"
        f"{f' (run {run_id})' if run_id is not None else ''}"
    )
    # Appended, not replaced: the notes record who created the row, and how a
    # binding came to exist stays worth reading after it is activated.
    binding.notes = f"{binding.notes}; {evidence}" if binding.notes else evidence
    await session.flush()
    return decision


async def resolve_closure_scope(
    session: AsyncSession,
    company: str,
    *,
    open_jobs: Sequence[Job],
    listing_is_authoritative: bool,
) -> ClosureScope:
    """Load binding + identity state, then apply `decide_closure_scope`."""
    if not listing_is_authoritative:
        return ClosureScope(
            False, frozenset(), "listing not authoritative (capped/incomplete/errors)"
        )

    binding = await get_active_binding(session, company)
    if binding is not None and binding.connector_kind == "recipe":
        validation = await session.scalar(select(ConnectorRecipeRevision.validation).where(
            ConnectorRecipeRevision.id == binding.recipe_revision_id))
        if not validation_is_current(validation):
            return ClosureScope(False, frozenset(), "recipe validation uses a different extractor or parser")
    open_ids = [job.id for job in open_jobs]
    owned: set[int] = set()
    with_any: set[int] = set()
    if binding is not None:
        owned = await _identity_owned_job_ids(session, binding.id)
        with_any = await _job_ids_with_any_identity(session, open_ids)
        # Retiring an unmatched identity is a review decision, never evidence
        # of source absence. Its canonical posting and history stay intact.
        retired = set((await session.scalars(select(BindingReconciliationDecision.job_id).where(
            BindingReconciliationDecision.binding_id == binding.id,
            BindingReconciliationDecision.decision == "retire",
            BindingReconciliationDecision.job_id.is_not(None),
        ))).all())
        open_ids = [job_id for job_id in open_ids if job_id not in retired]

    return decide_closure_scope(
        binding=binding,
        open_job_ids=open_ids,
        owned_job_ids=owned,
        job_ids_with_any_identity=with_any,
        listing_is_authoritative=True,
    )
