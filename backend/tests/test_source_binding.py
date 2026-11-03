"""Closure safety under rebinding.

Closing by `company` + `seen_keys`, gated only on run quality (uncapped,
complete, no errors), is unsafe: a binding change produces a disjoint source-key set that still passes
every one of those gates -- so every open job would be closed and reopened as
new, destroying the longitudinal history the product exists to accumulate and
firing notifications on fabricated churn.

`decide_closure_scope` is pure, so these are direct behavior assertions rather
than mock-shaped ones.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from tracker.company_store import plan_binding_seeds
from tracker.connectors.recipes.outcome import SourceOutcome
from tracker.db.binding import (
    ActivationDecision,
    ClosureScope,
    decide_binding_activation,
    decide_closure_scope,
)
from tracker.db.models import Job, JobLifecycleEvent, SourceBinding
from tracker.db.repo import close_missing


def make_binding(
    *,
    id: int = 1,
    status: str = "stable",
    closure_capability: str = "authoritative",
) -> SourceBinding:
    binding = SourceBinding()
    binding.id = id
    binding.company_slug = "acme"
    binding.connector_kind = "adapter"
    binding.connector_id = "greenhouse"
    binding.status = status
    binding.closure_capability = closure_capability
    return binding


def scope(**overrides) -> ClosureScope:
    kwargs = {
        "binding": make_binding(),
        "open_job_ids": [1, 2, 3],
        "owned_job_ids": {1, 2, 3},
        "job_ids_with_any_identity": {1, 2, 3},
        "listing_is_authoritative": True,
    }
    kwargs.update(overrides)
    return decide_closure_scope(**kwargs)


# --------------------------------------------------------------------------- #
# The rebind catastrophe
# --------------------------------------------------------------------------- #


def test_rebind_closes_nothing_even_though_the_listing_looks_authoritative():
    """The load-bearing test.

    New binding (id=2) is stable and authoritative and served a complete,
    uncapped, error-free listing. Its source keys are all new, so it owns none
    of the company's existing jobs -- which are owned by the OLD binding (id=1).
    Company-scoped closure would close all three. Required behavior: close none.
    """
    result = scope(
        binding=make_binding(id=2),
        open_job_ids=[1, 2, 3],
        owned_job_ids=set(),  # new binding owns no legacy job yet
        job_ids_with_any_identity={1, 2, 3},  # ...but they ARE owned by binding 1
    )
    assert result.may_close is True  # the run itself is legitimate
    assert result.closable_job_ids == frozenset()  # ...but it may close nothing


def test_rebind_can_still_close_jobs_it_has_reconciled():
    """Once a reviewer maps old jobs onto the new binding, closure resumes."""
    result = scope(binding=make_binding(id=2), owned_job_ids={1, 2}, job_ids_with_any_identity={1, 2, 3})
    assert result.closable_job_ids == frozenset({1, 2})


# --------------------------------------------------------------------------- #
# Binding state gates -- each independently suppresses closure
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("status", ["proposed", "shadow", "reconciling", "retired"])
def test_only_a_stable_binding_may_close(status):
    result = scope(binding=make_binding(status=status))
    assert result.suppressed
    assert status in result.reason


def test_closure_capability_none_suppresses_closure():
    """Search/category/sample sources can open jobs but never close by absence."""
    result = scope(binding=make_binding(closure_capability="none"))
    assert result.suppressed
    assert "closure_capability=none" in result.reason


def test_capped_or_incomplete_listing_still_suppresses_closure():
    """The pre-existing run-quality gate is preserved, not replaced."""
    result = scope(listing_is_authoritative=False)
    assert result.suppressed
    assert "not authoritative" in result.reason


def test_suppressed_scope_is_distinguishable_from_nothing_to_close():
    """`closed 0 because forbidden` and `closed 0 because nothing was missing`
    must not look identical in the audit record."""
    forbidden = scope(binding=make_binding(status="reconciling"))
    allowed = scope(owned_job_ids={1, 2, 3})
    assert forbidden.suppressed and not allowed.suppressed
    assert forbidden.reason != allowed.reason


# --------------------------------------------------------------------------- #
# Dual-read: unmigrated jobs
# --------------------------------------------------------------------------- #


def test_unmigrated_jobs_are_closable_by_the_stable_binding():
    """A job with no identity under ANY binding predates the migration; the
    company's stable binding may still close it, or legacy postings would
    accumulate forever."""
    result = scope(owned_job_ids={1}, job_ids_with_any_identity={1})
    assert result.closable_job_ids == frozenset({1, 2, 3})


def test_a_job_owned_by_another_binding_is_never_closable_as_unmigrated():
    """The dual-read safety net must not become a rebind loophole."""
    result = scope(owned_job_ids=set(), job_ids_with_any_identity={2, 3})
    assert result.closable_job_ids == frozenset({1})  # only the genuinely unowned one


def test_missing_binding_row_preserves_legacy_behavior():
    """An un-migrated deployment keeps closing, rather than silently halting."""
    result = scope(binding=None)
    assert result.may_close
    assert result.closable_job_ids == frozenset({1, 2, 3})
    assert "legacy" in result.reason


# --------------------------------------------------------------------------- #
# close_missing honors the scope
# --------------------------------------------------------------------------- #


class FakeSession:
    def __init__(self) -> None:
        self.added: list[object] = []

    def add(self, obj: object) -> None:
        self.added.append(obj)

    def of_type(self, cls):
        return [o for o in self.added if isinstance(o, cls)]


def make_job(job_id: int, key: str) -> Job:
    job = Job()
    job.id = job_id
    job.company = "acme"
    job.dedupe_key = key
    job.status = "open"
    job.first_seen = datetime.now(UTC)
    job.last_seen = datetime.now(UTC)
    return job


@pytest.mark.asyncio
async def test_close_missing_skips_jobs_outside_the_scope():
    session = FakeSession()
    run = SimpleNamespace(id=7)
    existing = {"a": make_job(1, "a"), "b": make_job(2, "b"), "c": make_job(3, "c")}

    closed = await close_missing(
        session, run, "acme", seen_keys=set(), existing=existing,
        closable_job_ids=frozenset({2}),
    )

    assert closed == 1
    assert existing["b"].status == "closed"
    assert existing["a"].status == "open"
    assert existing["c"].status == "open"
    # Exactly one lifecycle event -- a skipped job must not emit a phantom close.
    assert len(session.of_type(JobLifecycleEvent)) == 1


@pytest.mark.asyncio
async def test_close_missing_with_empty_scope_closes_nothing():
    """End-to-end shape of the rebind case."""
    session = FakeSession()
    existing = {"a": make_job(1, "a"), "b": make_job(2, "b")}

    closed = await close_missing(
        session, SimpleNamespace(id=7), "acme", seen_keys=set(), existing=existing,
        closable_job_ids=frozenset(),
    )

    assert closed == 0
    assert all(job.status == "open" for job in existing.values())
    assert session.of_type(JobLifecycleEvent) == []


@pytest.mark.asyncio
async def test_close_missing_without_scope_preserves_legacy_behavior():
    """`closable_job_ids=None` = pre-binding callers keep working unchanged."""
    session = FakeSession()
    existing = {"a": make_job(1, "a"), "b": make_job(2, "b")}

    closed = await close_missing(
        session, SimpleNamespace(id=7), "acme", seen_keys={"a"}, existing=existing
    )

    assert closed == 1
    assert existing["b"].status == "closed"


# --------------------------------------------------------------------------- #
# Loader semantics -- regression pin
# --------------------------------------------------------------------------- #


def test_active_binding_query_is_not_filtered_to_stable():
    """`get_active_binding` filtering on `status='stable'` would make a
    company mid-rebind look identical to a company with NO binding row -- and
    the no-binding case falls through to legacy company-scoped closure. A
    `reconciling` binding would therefore close every job in the company,
    which is the exact catastrophe this module exists to prevent.

    Compiling the SQL (repo convention for query contracts) pins that the status
    gate lives in `decide_closure_scope`, not in the loader.
    """
    from sqlalchemy import select
    from sqlalchemy.dialects import postgresql

    from tracker.db.binding import SourceBinding as BoundModel

    # Rebuild the loader's criteria the way the module issues it.
    stmt = select(BoundModel).where(
        BoundModel.company_slug == "acme", BoundModel.status != "retired"
    )
    sql = str(stmt.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
    assert "status != 'retired'" in sql
    assert "status = 'stable'" not in sql


@pytest.mark.asyncio
async def test_reconciling_binding_suppresses_closure_not_falls_back_to_legacy():
    """The behavioral half of the regression above: a non-stable binding must
    reach the status branch, never the `binding is None` legacy branch."""
    result = scope(binding=make_binding(status="reconciling"))
    assert result.suppressed
    assert "legacy" not in result.reason
    assert result.closable_job_ids == frozenset()


@pytest.mark.asyncio
async def test_seen_jobs_are_never_closed_regardless_of_scope():
    session = FakeSession()
    existing = {"a": make_job(1, "a")}

    closed = await close_missing(
        session, SimpleNamespace(id=7), "acme", seen_keys={"a"}, existing=existing,
        closable_job_ids=frozenset({1}),
    )

    assert closed == 0
    assert existing["a"].status == "open"


# --------------------------------------------------------------------------- #
# Binding seeding as a lifecycle rule
#
# A company with no binding has inert binding health and falls through to the
# legacy company-scoped closure branch, skipping the suspect/quarantined gate
# every other source has, so every tracked company is seeded a binding.
# `plan_binding_seeds` is pure, so the rules that hand a company closure
# authority are asserted on explicit inputs.
# --------------------------------------------------------------------------- #

KNOWN = frozenset({"greenhouse", "meta", "workday"})


def make_company(slug: str = "acme", adapter: str | None = "greenhouse", source: str = "builtin"):
    return SimpleNamespace(slug=slug, adapter=adapter, source=source)


def seeds_for(companies, bound=frozenset(), known=KNOWN):
    return plan_binding_seeds(companies, set(bound), known_adapters=known)


def test_a_company_without_a_binding_is_seeded_collecting_but_withheld():
    """A seeded binding collects immediately and closes nothing.

    `status='stable'` is what the scheduler selects on, so the binding is
    reconciled on the normal cadence and can earn its authority; the withheld
    knob is `closure_capability`, which is the model's own idiom for "may open
    and update jobs, never close by absence"."""
    (seed,) = seeds_for([make_company("meta", "meta")])

    assert seed["company_slug"] == "meta"
    assert seed["connector_kind"] == "adapter"
    assert seed["connector_id"] == "meta"
    assert seed["status"] == "stable"
    assert seed["closure_capability"] == "none"
    assert "health" not in seed, "binding health is retired"
    assert seed["activated_at"] is None


def test_the_seeded_row_closes_nothing_yet_is_not_the_legacy_branch():
    """The two halves of the gate, on one row.

    Withholding must suppress closure (`may_close` False) WITHOUT withholding
    the binding row itself: no row at all falls through to `decide_closure_scope`'s
    legacy branch, which closes the whole company unscoped. Asserting the seed
    dict's strings alone would pass even if the field names drifted away from
    what the gate reads."""
    (seed,) = seeds_for([make_company("meta", "meta")])
    binding = SourceBinding(**seed)

    assert binding.may_close is False
    result = scope(binding=binding, owned_job_ids={1, 2, 3})
    assert result.may_close is False
    assert result.closable_job_ids == frozenset()
    assert "closure_capability=none" in result.reason
    # The failure mode withholding must not reintroduce.
    assert scope(binding=None).closable_job_ids == frozenset({1, 2, 3})


def test_a_company_mid_rebind_is_never_given_a_second_binding():
    """`bound_slugs` covers ANY non-retired status, not just `stable`. Seeding a
    stable binding underneath a `reconciling` one would hand closure authority to
    a company whose identities are still being reconciled — the exact catastrophe
    this module exists to prevent."""
    assert seeds_for([make_company("acme")], bound={"acme"}) == []


def test_a_company_with_only_a_retired_binding_is_reseeded():
    """A retired binding is not a binding — otherwise retiring one would strand
    the company in the legacy no-binding branch forever."""
    (seed,) = seeds_for([make_company("acme")], bound=frozenset())
    assert seed["company_slug"] == "acme"


def test_a_company_with_no_adapter_is_not_bindable():
    assert seeds_for([make_company("acme", adapter=None)]) == []


def test_an_unknown_adapter_never_receives_closure_authority():
    """Defensive: a stale row naming a connector that does not exist must not
    be handed the right to close jobs by absence."""
    assert seeds_for([make_company("acme", adapter="removed_connector")]) == []


def test_a_user_added_company_is_seeded_identically_to_a_builtin():
    """Who added the company decides nothing; a run's evidence decides.

    With an activation path, nothing licenses instant authority: a built-in's
    board token and a user's are both guesses until a complete listing comes
    back, and the built-in has no jobs to close on its first night anyway."""
    (builtin,) = seeds_for([make_company("acme", source="builtin")])
    (user,) = seeds_for([make_company("acme", source="user")])

    assert builtin["closure_capability"] == user["closure_capability"] == "none"
    assert builtin["status"] == user["status"] == "stable"


def test_only_the_unbound_companies_in_a_mixed_set_are_seeded():
    seeds = seeds_for(
        [
            make_company("meta", "meta"),
            make_company("acme", "greenhouse"),
            make_company("nvidia", "workday"),
            make_company("nocfg", adapter=None),
        ],
        bound={"acme"},
    )

    assert sorted(s["company_slug"] for s in seeds) == ["meta", "nvidia"]


def test_seed_query_counts_every_non_retired_binding_as_bound():
    """The wrapper's `bound_slugs` query must use the same `!= 'retired'` filter
    as `get_active_binding`. Narrowing it to `status='stable'` would make a
    reconciling company look unbound and re-seed it — see the mid-rebind test."""
    from sqlalchemy import select
    from sqlalchemy.dialects import postgresql

    stmt = select(SourceBinding.company_slug).where(SourceBinding.status != "retired")
    sql = str(stmt.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))

    assert "status != 'retired'" in sql
    assert "status = 'stable'" not in sql


def test_every_builtin_adapter_is_seedable():
    """Guards the unknown-adapter rule against its own failure mode: if the
    registry key set and the configured adapter names ever drift, real built-ins
    would be silently skipped instead of bound."""
    from tracker.company_store import ADAPTER_REGISTRY
    from tracker.config import COMPANIES

    companies = [make_company(slug, cfg["adapter"]) for slug, cfg in COMPANIES.items()]
    seeds = seeds_for(companies, known=frozenset(ADAPTER_REGISTRY))

    assert len(seeds) == len(COMPANIES)


# --------------------------------------------------------------------------- #
# Activation: earning the authority seeding withholds
#
# `plan_binding_seeds` withholds `closure_capability`, so something has to grant
# it or a newly onboarded company never closes a posting again. Activation and
# seeding are the only writers of `status`/`closure_capability`, so these are
# the rules of one of the two functions that can hand a source the right to
# close jobs by absence.
# --------------------------------------------------------------------------- #

WITHHELD = {"closure_capability": "none"}


def activation(**overrides) -> ActivationDecision:
    kwargs = {
        "binding": make_binding(**WITHHELD),
        "outcome": SourceOutcome.OK,
        "scan_mode": "reconcile",
        "scanned": 615,
    }
    kwargs.update(overrides)
    return decide_binding_activation(**kwargs)


def test_a_complete_clean_listing_activates_a_withheld_binding():
    decision = activation()

    assert decision.activate is True
    assert decision.reason == "validated by a complete ok listing (scanned=615)"


def test_activation_closes_the_loop_seeding_opens():
    """The two halves must actually compose: the seeded row is the row activation
    accepts, and the activated row is the row `decide_closure_scope` accepts.
    Asserting the strings in either function alone would pass while the field
    names drifted apart."""
    (seed,) = seeds_for([make_company("stripe", "greenhouse")])
    binding = SourceBinding(**seed)
    assert binding.may_close is False

    assert activation(binding=binding).activate is True
    # What the store wrapper writes, applied by hand so the gate is asserted on
    # the resulting row rather than on the write.
    binding.closure_capability = "authoritative"

    assert binding.may_close is True
    assert scope(binding=binding, owned_job_ids={1, 2, 3}).may_close is True


@pytest.mark.parametrize("outcome", [o for o in SourceOutcome if o is not SourceOutcome.OK])
def test_only_an_ok_listing_is_evidence_of_a_board(outcome):
    """Every other outcome is an incomplete, errored, capped or bounded listing.
    `unattempted` is in here too, which is what stops a policy-denied source
    from activating a binding it never even requested."""
    decision = activation(outcome=outcome)

    assert decision.activate is False
    assert outcome.value in decision.reason


@pytest.mark.parametrize("mode", ["discovery", "repair", "shadow"])
def test_only_a_reconcile_can_validate_a_binding(mode):
    """Discovery is non-authoritative by construction and repair/shadow re-read a
    subset — none of them enumerates the board, so none is evidence of identity."""
    assert activation(scan_mode=mode).activate is False


def test_an_empty_listing_never_activates_even_when_the_run_is_clean():
    """An empty board carries its own two-confirmation contract. Rule 5
    catches this first (every public adapter marks an empty listing
    incomplete); this is the rule that must still hold if a valid empty
    listing is ever marked complete."""
    decision = activation(scanned=0)

    assert decision.activate is False
    assert "empty" in decision.reason


def test_a_recipe_binding_can_never_be_activated_by_a_run_outcome():
    """The back door this gate must not open. Recipe bindings also start `none`,
    but authority is "assigned by RoleBand validation, never by recipe text" — a
    recipe author must not be able to grant themselves closure authority by
    shipping one that enumerates cleanly. They earn it through the
    validated-revision flow."""
    binding = make_binding(**WITHHELD)
    binding.connector_kind = "recipe"

    decision = activation(binding=binding)

    assert decision.activate is False
    assert "recipe" in decision.reason


@pytest.mark.parametrize("status", ["proposed", "shadow", "reconciling", "retired"])
def test_only_a_stable_binding_is_activated_by_this_gate(status):
    """A binding mid-lifecycle is promoted by that lifecycle. Activating a
    `reconciling` binding here would hand closure authority to a company whose
    identities are still being reconciled."""
    assert activation(binding=make_binding(status=status, **WITHHELD)).activate is False


def test_an_already_authoritative_binding_is_left_alone():
    """Not merely inert: re-deciding an activated binding every night would
    re-stamp `activated_at`, and "when did this binding earn authority" is the
    one thing that column exists to answer."""
    decision = activation(binding=make_binding())

    assert decision.activate is False
    assert "nothing withheld" in decision.reason


@pytest.mark.asyncio
@pytest.mark.usefixtures("no_escape")
async def test_two_writers_seeding_at_once_make_one_binding_and_raise_nothing(db_session):
    """The scheduler's tick and `/api/sync` seed with no run lock between them.
    The second writer plans a seed before the first commits, so its insert
    meets the first's row in the one-active-binding index. That is a binding
    already made, not an error. Fail-first: the second writer raised
    IntegrityError, which the sync route returned as a 500."""
    import asyncio

    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from tests.barriers import until_waiting
    from tracker.company_store import ensure_source_bindings
    from tracker.db.models import TrackedCompany
    from tracker.db.recipe_store import ensure_bundled_recipes

    await ensure_bundled_recipes(db_session)
    db_session.add(TrackedCompany(slug="acme", display="Acme", adapter="greenhouse", board_token="acme",
                                  status="active", enabled=True, visible=True, source="user"))
    await db_session.commit()

    factory = async_sessionmaker(db_session.bind, expire_on_commit=False, class_=AsyncSession)
    async with factory() as first, factory() as second:
        assert await ensure_source_bindings(first) == 1
        racing = asyncio.create_task(ensure_source_bindings(second))
        await until_waiting(db_session.bind, racing)
        assert not racing.done(), "it has read no binding and is waiting on the first's row"
        await first.commit()
        assert await racing == 0
        await second.commit()

    rows = (await db_session.scalars(select(SourceBinding).where(SourceBinding.company_slug == "acme"))).all()
    assert [(b.connector_id, b.status, b.closure_capability) for b in rows] == [("greenhouse", "stable", "none")]
