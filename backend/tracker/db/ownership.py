"""Table-ownership registry — every DB table declares who populates it.

The bug class: a derived-data producer ships as a standalone CLI, its
consumer API ships, but nothing ever wires it into the scrape pipeline, so the
table stays empty and no test notices. This registry is the structural fix.
`tests/test_table_ownership.py` asserts that every table in
``Base.metadata`` is claimed here exactly once, so adding a model *forces* a
claim declaring its populator — the same gate mechanism as
``blueprint.py``/``test_company_blueprint.py``.

A claim is one of:

* ``core`` — written by the pipeline's persist stage, the recipes/binding
  engine, company/profile bootstrapping, or notifications. Populated every run
  as part of the scrape itself, not a post-pass.
* ``post_pass:<name>`` — produced by a POST_PASSES entry. ``<name>`` must match
  a registered pass, so a renamed/removed pass fails the gate.
* ``user`` — user-driven mutations (favorites, pursuits, settings).
* ``manual:<route>`` — populated only by an explicit API-triggered refresh.
  ``<route>`` must exist in the frozen route table, so the trigger can't
  silently disappear.
* ``seed`` — one-time reference data loaded by a script.
* ``infra`` — operational bookkeeping, not domain data.
* ``planned:<note>`` — schema exists ahead of its feature; intentionally
  unpopulated. Explicit so "no writer" reads as a decision, not an oversight.

Each entry is a ``TableOwnership``, so the registry answers "where is this
written, where is it read, and how do its rows age?" without a grep.

**Its three other fields are not all the same kind of statement, and confusing
them would be worse than not having them.** `tests/test_table_writers.py` scans the
code and can only ever prove a declaration WRONG, never complete:

* ``writers`` is meant to be exhaustive. The scan asserts every writer it finds
  is declared here, so an undeclared one fails by name. It cannot prove a
  declared writer is real, and it cannot see a row reached through a function's
  return value: a getter that hands back a row its caller then mutates is
  invisible to an AST scan.
* ``readers`` is the read OWNER — where to look first — NOT every reader.
  `jobs` is queried across the codebase; listing every reader would be
  unreadable and would churn on every refactor. The one reader claim that IS checked is the empty
  one: ``readers=()`` asserts nothing reads the table, and the scan fails it if
  anything does.
* ``lifecycle`` is how rows age, which the claim does not say: `jobs` and
  `job_observations` are both ``core``, and one is upserted in place while the
  other is history that must never be overwritten (AGENTS.md, "Data safety").
  Only ``append_only`` is enforced, and only in one direction: the scan fails
  an ``append_only`` table if it finds an update, delete or upsert, but
  silence is not proof.

Keep this map in sync with reality: a new derived table is a ``post_pass``
claim plus a POST_PASSES entry in the same change, never a bare model.
"""

from __future__ import annotations

from dataclasses import dataclass

#: How a table's rows age. Orthogonal to `claim`, which says who writes them.
LIFECYCLES = frozenset(
    {
        # History. Rows are inserted and never updated or deleted; replacing
        # this with overwrite logic destroys the longitudinal asset.
        "append_only",
        # Current state. The row IS the truth now and is upserted in place.
        "canonical",
        # Recomputable. Rebuilt from other tables by the pass that claims it,
        # so losing it costs time, not information.
        "derived",
        # The user's own entries. Nothing upstream can rebuild them.
        "authored",
        # External or seed reference data, refreshed wholesale.
        "reference",
        # Runtime bookkeeping: schedules, pressure, derivation cursors.
        "operational",
        # Declared but never written. Pairs with a `planned:` claim, or records
        # a table whose writer was never built.
        "unpopulated",
    }
)


@dataclass(frozen=True)
class TableOwnership:
    """One table's answer to: who writes it, who reads it, how do rows age?"""

    claim: str
    lifecycle: str
    #: Every module that writes rows, relative to `backend/`. Exhaustive; the
    #: writer scan fails on one it finds that is not named here.
    writers: tuple[str, ...] = ()
    #: The read owner — where to look first, not every reader. Empty means
    #: nothing reads this table, which the scan checks.
    readers: tuple[str, ...] = ()


# Route paths referenced by `manual:` claims (validated against the frozen
# route table by the ownership test).
PLUGIN_REFRESH = "manual:/api/plugins/{plugin_id}/refresh"

TABLE_OWNERS: dict[str, TableOwnership] = {
    # --- core: written by the scrape/persist path every run --------------------
    # Claims, one per source per assertion: the core's (seed, blueprint,
    # filings), a plugin's (`company.facts`, through `plugins/writer`), the
    # user's (`manual`). Not `append_only` while the user's unpin deletes their
    # own pin (`store.clear_manual`); a plugin's claims are not recomputable
    # without its run, so `derived` is approximate.
    "company_fact": TableOwnership(
        claim="core",
        lifecycle="derived",
        writers=("tracker/profiles/store.py",),
        readers=("tracker/api/routers/companies.py",),
    ),
    # The unpin route blanks `comp_notes`; `core` names who FILLS it.
    "company_profile": TableOwnership(
        claim="core",
        lifecycle="canonical",
        writers=(
            "tracker/profiles/seed.py",
            "tracker/profiles/store.py",
        ),
        readers=("tracker/api/routers/companies.py",),
    ),
    "connector_recipe_revisions": TableOwnership(
        claim="core",
        lifecycle="canonical",
        writers=("tracker/db/recipe_store.py",),
        readers=("tracker/db/recipe_store.py", "tracker/db/binding.py"),
    ),
    "connector_recipes": TableOwnership(
        claim="core",
        lifecycle="canonical",
        writers=("tracker/db/recipe_store.py",),
        readers=("tracker/db/recipe_store.py", "tracker/company_store.py"),
    ),
    "job_lifecycle_events": TableOwnership(
        claim="core",
        lifecycle="append_only",
        writers=(
            "tracker/db/repo.py",
            # A band the employer moved, recorded by whichever reader saw it
            # move: the connector above, the text pass and the page read
            # (`db/pay_band.py`).
            "tracker/intelligence_runtime/disclosed_comp.py",
            "tracker/workflows/posting_pages.py",
        ),
        readers=("tracker/db/queries/jobs.py",),
    ),
    # Each source's estimate per job, side by side: ours always, a
    # selected plugin's while it answers pay; `jobs.comp_*` copies the shown one.
    # Rebuilt by the re-estimate from jobs and the reference rows. The plugin's
    # rows go with its Remove data.
    "job_comp_estimate": TableOwnership(
        claim="core",
        lifecycle="derived",
        writers=("tracker/db/repo.py", "tracker/plugins/reestimate.py", "tracker/plugins/writer.py"),
        readers=("tracker/api/routers/jobs.py",),
    ),
    "job_observations": TableOwnership(
        claim="core",
        lifecycle="append_only",
        writers=("tracker/db/repo.py",),
        # Read by the history rebuild, which recomputes our estimate night by night.
        readers=("scripts/rebuild_from_history.py",),
    ),
    # Written as a posting is seen: `(binding, source_key) -> job`, the alias
    # closure scope reads to tell a binding's own postings from another live
    # binding's. A retired binding's aliases stay as provenance and say
    # nothing about who may close the row.
    "job_source_identities": TableOwnership(
        claim="core",
        lifecycle="canonical",
        writers=("tracker/db/repo.py", "tracker/db/reconciliation.py"),
        readers=("tracker/db/binding.py", "tracker/db/repo.py"),
    ),
    "jobs": TableOwnership(
        claim="core",
        lifecycle="canonical",
        writers=(
            "tracker/api/routers/jobs.py",
            "tracker/db/repo.py",
            # The text pass's `disclosed_*` band and processed marker.
            "tracker/intelligence_runtime/disclosed_comp.py",
            "tracker/lineage/backfill.py",
            "tracker/lineage/detect.py",
            "tracker/lineage/twins.py",
            "tracker/semantic/backfill.py",
            "tracker/semantic/cluster.py",
            "tracker/workflows/backfill_disclosed_comp.py",
            # A posting page read: `source_facts` form and tiers, and a page band.
            "tracker/workflows/posting_pages.py",
            # The estimate fields and `comp_ref_fp`, moved together when the
            # reference set changes.
            "tracker/plugins/reestimate.py",
            # `--apply` strips the listing's query off stored posting URLs. The
            # scan cannot see it (rows reach the write through a loop variable).
            "scripts/backfill_google_urls.py",
            # `--apply` drops a searched country the listed places already name.
            # Rows reach the write through a loop variable, as above.
            "scripts/backfill_google_places.py",
            # `--clear` deletes the rows it seeded. The scan cannot see this one
            # (it deletes rows loaded by a `select`), so it is declared by hand.
            "scripts/seed_synthetic.py",
        ),
        readers=("tracker/db/queries/jobs.py",),
    ),
    "notifications": TableOwnership(
        claim="core",
        lifecycle="canonical",
        writers=(
            "tracker/api/routers/notifications.py",
            "tracker/notifications/channels.py",
            "tracker/notifications/coverage.py",
            "tracker/notifications/pursuit_due.py",
            "tracker/notifications/store.py",
        ),
        readers=("tracker/notifications/store.py",),
    ),
    # Every posting a sync read, written at each company's finalize
    # and re-derived by the `inventory_promotion` pass; promotion
    # reads it and writes `jobs` through `db/repo.py`. Rows no scan read within
    # the user's retention window are deleted by `inventory_store.remove_unread`,
    # called from the `inventory_retention` pass and the scheduler's idle tick;
    # the only sanctioned bulk delete of postings, and only here.
    "posting_inventory": TableOwnership(
        claim="core",
        lifecycle="canonical",
        writers=(
            "tracker/db/inventory_store.py",
            # Posting URL repair, `url` only (see the `jobs` entry).
            "scripts/backfill_google_urls.py",
            # Place list repair, `locations` only (see the `jobs` entry).
            "scripts/backfill_google_places.py",
        ),
        readers=(
            "tracker/scope/promotion.py",
            "tracker/scope/inventory_joint.py",
            # the titles a moved careers page must overlap
            "tracker/db/queries/companies.py",
        ),
    ),
    "role_catalog": TableOwnership(
        claim="core",
        lifecycle="derived",
        writers=("tracker/scope/catalog_store.py",),
        readers=("tracker/scope/catalog.py",),
    ),
    "scrape_runs": TableOwnership(
        claim="core",
        lifecycle="canonical",
        writers=(
            "tracker/db/repo.py",
            "tracker/workflows/pipeline.py",
            "tracker/workflows/run_persistence.py",
            # The synthetic seeder opens one run to persist through the real seam.
            "scripts/seed_synthetic.py",
            # The status bench seeds its own scratch database, never this one.
            "scripts/bench_status_cost.py",
        ),
        readers=("tracker/db/queries/runs.py",),
    ),
    "scrape_source_runs": TableOwnership(
        claim="core",
        lifecycle="append_only",
        writers=(
            "tracker/workflows/run_persistence.py",
            # The status bench seeds its own scratch database, never this one.
            "scripts/bench_status_cost.py",
        ),
        readers=("tracker/api/routers/companies.py", "tracker/scope/inventory_joint.py"),
    ),
    "source_bindings": TableOwnership(
        claim="core",
        lifecycle="canonical",
        writers=(
            "tracker/company_store.py",
            "tracker/db/reconciliation.py",
            # The status bench seeds its own scratch database, never this one.
            "scripts/bench_status_cost.py",
        ),
        readers=("tracker/company_store.py", "tracker/db/recipe_store.py"),
    ),
    "tracked_company": TableOwnership(
        claim="core",
        lifecycle="canonical",
        writers=(
            "tracker/company_store.py",
            "tracker/db/reconciliation.py",
            "tracker/scope/catalog_store.py",
            # The status bench seeds its own scratch database, never this one.
            "scripts/bench_status_cost.py",
        ),
        readers=("tracker/company_store.py",),
    ),

    # --- post_pass: produced by a POST_PASSES entry ----------------------------
    "clusters": TableOwnership(
        claim="post_pass:clusters",
        lifecycle="derived",
        writers=("tracker/semantic/cluster.py",),
        readers=("tracker/api/routers/skills.py",),
    ),
    # Written by the comp_metrics pass, read by nothing
    # (`readers=()`); `comp_snapshot`, written beside it, is what statistics reads.
    "comp_metrics": TableOwnership(
        claim="post_pass:comp_metrics",
        lifecycle="derived",
        writers=("tracker/analytics/comp_trends.py",),
        readers=(),
    ),
    # Ours and the selected plugin's series per day. Days stored as one `mixed`
    # series are unread; `scripts.rebuild_from_history` adds our series for them
    # from `job_observations`, one explicitly requested run at a time.
    "comp_snapshot": TableOwnership(
        claim="post_pass:comp_metrics",
        lifecycle="derived",
        writers=("tracker/analytics/comp_trends.py", "scripts/rebuild_from_history.py", "tracker/plugins/writer.py"),
        readers=("tracker/api/routers/statistics.py",),
    ),
    "company_price": TableOwnership(
        claim="post_pass:prices",
        lifecycle="derived",
        writers=("tracker/profiles/prices.py",),
        readers=("tracker/profiles/prices.py",),
    ),
    # Only spending quota could rebuild these bars, so they are the price record,
    # not a cache: corrected in place within the overlap window, never deleted.
    # Every request to the price feed, reserved before it is sent: the budget.
    "price_feed_requests": TableOwnership(
        claim="post_pass:prices",
        lifecycle="operational",
        writers=("tracker/profiles/prices.py",),
        readers=("tracker/profiles/prices.py",),
    ),
    "company_price_history": TableOwnership(
        claim="post_pass:prices",
        lifecycle="canonical",
        writers=("tracker/profiles/prices.py",),
        readers=("tracker/profiles/prices.py",),
    ),
    "demand_metrics": TableOwnership(
        claim="post_pass:demand_metrics",
        lifecycle="derived",
        writers=("tracker/analytics/demand.py",),
        # Dated history only: Hiring counts roles live.
        readers=(),
    ),
    "disclosure_snapshot": TableOwnership(
        claim="post_pass:disclosure_metrics",
        lifecycle="derived",
        writers=("tracker/analytics/comp_trends.py",),
        readers=("tracker/analytics/comp_trends.py",),
    ),
    "job_lineage": TableOwnership(
        claim="post_pass:lineage",
        lifecycle="derived",
        writers=("tracker/lineage/detect.py",),
        readers=("tracker/db/queries/jobs.py",),
    ),
    "job_lineage_link": TableOwnership(
        claim="post_pass:lineage",
        lifecycle="derived",
        writers=(
            "tracker/api/routers/lineage.py",
            "tracker/lineage/detect.py",
            # Withdraws a pending suspected proposal between two members of one
            # place set; never a verdict.
            "tracker/lineage/place_sets.py",
            "tracker/lineage/review.py",
        ),
        readers=("tracker/lineage/detect.py",),
    ),
    "job_qualifications": TableOwnership(
        claim="post_pass:skills_requirements",
        lifecycle="derived",
        writers=("tracker/skills/extract.py",),
        readers=("tracker/db/queries/skills.py",),
    ),
    "job_relevance_reviews": TableOwnership(
        claim="post_pass:relevance_review",
        lifecycle="derived",
        writers=("tracker/workflows/relevance_pass.py",),
        readers=("tracker/workflows/relevance_pass.py",),
    ),
    "job_similarity": TableOwnership(
        claim="post_pass:similarity",
        lifecycle="derived",
        writers=("tracker/semantic/similarity.py",),
        readers=("tracker/semantic/similarity.py",),
    ),
    # Reaches the database through the `JobSkill.evidence` relationship cascade,
    # never through a direct add — which is why a bare `Model(...)` counts as a write.
    "job_skill_evidence": TableOwnership(
        claim="post_pass:skills_requirements",
        lifecycle="derived",
        writers=("tracker/skills/extract.py",),
        readers=(),
    ),
    "job_skills": TableOwnership(
        claim="post_pass:skills_requirements",
        lifecycle="derived",
        writers=("tracker/skills/extract.py",),
        readers=("tracker/db/queries/skills.py",),
    ),
    "job_twin_link": TableOwnership(
        claim="post_pass:twins",
        lifecycle="derived",
        writers=(
            # Withdraws a pending proposal between two members of one place
            # set; never a verdict.
            "tracker/lineage/place_sets.py",
            "tracker/lineage/review.py",
            "tracker/lineage/twins.py",
        ),
        readers=("tracker/db/queries/jobs.py",),
    ),
    # One role listed once per place. Rebuilt whole by the pass;
    # a person's `rejected` membership is the one row it never writes.
    "job_place_set": TableOwnership(
        claim="post_pass:place_sets",
        lifecycle="derived",
        writers=("tracker/lineage/place_sets.py",),
        readers=("tracker/lineage/place_sets.py",),
    ),
    "job_place_set_member": TableOwnership(
        claim="post_pass:place_sets",
        lifecycle="derived",
        writers=("tracker/lineage/place_sets.py",),
        readers=("tracker/lineage/place_sets.py",),
    ),
    "profile_suggestions": TableOwnership(
        claim="post_pass:profile_inference",
        lifecycle="derived",
        writers=(
            "tracker/api/routers/profile.py",
            "tracker/workflows/profile_inference_pass.py",
        ),
        readers=("tracker/api/routers/profile.py",),
    ),
    "skill_aliases": TableOwnership(
        claim="post_pass:skills_requirements",
        lifecycle="derived",
        writers=("tracker/skills/sync.py",),
        readers=("tracker/skills/sync.py",),
    ),
    "skill_concepts": TableOwnership(
        claim="post_pass:skills_requirements",
        lifecycle="derived",
        writers=("tracker/skills/sync.py",),
        readers=("tracker/db/queries/skills.py",),
    ),
    "skill_demand_daily": TableOwnership(
        claim="post_pass:skill_demand",
        lifecycle="derived",
        writers=("tracker/skills/analytics.py",),
        readers=("tracker/api/routers/skills.py",),
    ),
    "source_binding_tuning": TableOwnership(
        claim="post_pass:tuning",
        lifecycle="derived",
        writers=("tracker/workflows/tuning_pass.py",),
        readers=("tracker/workflows/tuning_pass.py",),
    ),

    # --- user: user-driven mutations -------------------------------------------
    "app_settings": TableOwnership(
        claim="user",
        lifecycle="authored",
        writers=(
            "tracker/agents/config.py",
            # The price feed's key the user saved in Settings.
            "tracker/profiles/prices.py",
            "tracker/semantic/embed.py",
            "tracker/semantic/tier_store.py",
            "tracker/settings_store.py",
            # Usage sharing: the consent record and the install ID.
            "tracker/usage_stats/consent.py",
            "tracker/usage_stats/install_id.py",
        ),
        readers=("tracker/settings_store.py",),
    ),
    "company_scope_rules": TableOwnership(
        claim="user",
        lifecycle="authored",
        writers=("tracker/api/routers/settings.py",),
        readers=("tracker/db/repo.py",),
    ),
    "compare_selection": TableOwnership(
        claim="user",
        lifecycle="authored",
        writers=("tracker/api/routers/jobs.py",),
        readers=("tracker/api/routers/jobs.py",),
    ),
    "favorites": TableOwnership(
        claim="user",
        lifecycle="authored",
        writers=(
            "tracker/agents/pursuits.py",
            "tracker/api/routers/jobs.py",
        ),
        readers=("tracker/db/queries/jobs.py",),
    ),
    "job_feedback": TableOwnership(
        claim="user",
        lifecycle="authored",
        writers=("tracker/api/routers/jobs.py",),
        readers=("tracker/db/queries/jobs.py",),
    ),
    "profile_claims": TableOwnership(
        claim="user",
        lifecycle="authored",
        writers=(),
        readers=("tracker/workflows/profile_inference_pass.py",),
    ),
    "pursuit_events": TableOwnership(
        claim="user",
        lifecycle="append_only",
        writers=("tracker/agents/pursuits.py",),
        readers=(),
    ),
    "pursuits": TableOwnership(
        claim="user",
        lifecycle="authored",
        writers=("tracker/agents/pursuits.py",),
        readers=("tracker/agents/pursuits.py",),
    ),

    # --- manual: explicit API-triggered refresh --------------------------------
    # A plugin's rows, written only by that plugin's refresh.
    "company_benefit": TableOwnership(
        claim=PLUGIN_REFRESH,
        lifecycle="canonical",
        writers=("tracker/plugins/writer.py",),
        readers=("tracker/api/routers/companies.py",),
    ),
    # A plugin's rows, as it sent them: banded from our atlas when read, never
    # rewritten by us.
    "company_comp_level": TableOwnership(
        claim=PLUGIN_REFRESH,
        lifecycle="canonical",
        writers=("tracker/plugins/writer.py",),
        readers=("tracker/db/queries/reference_pay.py",),
    ),
    # Reported pay observations: only a plugin publishes them (`pay.observations`);
    # the host's writer is the one writer, and the route or the schedule only
    # starts its run.
    "external_comp_observation": TableOwnership(
        claim=PLUGIN_REFRESH,
        lifecycle="append_only",
        writers=("tracker/plugins/writer.py",),
        readers=("tracker/api/routers/statistics.py",),
    ),

    # --- seed / infra ----------------------------------------------------------
    "ai_task_log": TableOwnership(
        claim="infra",
        lifecycle="append_only",
        writers=("tracker/intelligence_runtime/telemetry.py",),
        readers=("tracker/intelligence_runtime/telemetry.py",),
    ),
    "derivation_state": TableOwnership(
        claim="infra",
        lifecycle="operational",
        writers=("tracker/workflows/post_passes.py",),
        # The demand rollup's day: an empty day is still current.
        # The Stock prices card's last run.
        readers=("tracker/workflows/schedule_status.py", "tracker/analytics/demand.py", "tracker/profiles/prices.py"),
    ),
    "directory_checks": TableOwnership(
        claim="infra",
        lifecycle="operational",
        writers=("tracker/workflows/directory_sweep.py",),
        readers=("tracker/workflows/directory_sweep.py",),
    ),
    "provider_pressure_state": TableOwnership(
        claim="infra",
        lifecycle="operational",
        writers=("tracker/workflows/scheduler.py",),
        readers=("tracker/api/routers/ops.py",),
    ),
    "sync_schedule_state": TableOwnership(
        claim="infra",
        lifecycle="operational",
        writers=("tracker/workflows/scheduler.py",),
        readers=("tracker/api/routers/ops.py",),
    ),
    # Usage sharing's outbox (docs/architecture.md): written only while
    # the user shares, read by the daily flush and Settings > Privacy. Sent
    # rows are pruned after 30 days; unsent rows of a group the user stops
    # sharing are marked withdrawn and kept.
    "usage_events": TableOwnership(
        claim="infra",
        lifecycle="operational",
        writers=("tracker/usage_stats/outbox.py",),
        readers=("tracker/usage_stats/outbox.py",),
    ),
    # The schedule plan: when the machine is seen awake, and the
    # plan's own run clock. Written by the scheduler's plan module only.
    "machine_awake_samples": TableOwnership(
        claim="infra",
        lifecycle="operational",
        writers=("tracker/workflows/schedule_plan.py",),
        readers=("tracker/workflows/schedule_plan.py",),
    ),
    "schedule_plan_runs": TableOwnership(
        claim="infra",
        lifecycle="operational",
        writers=("tracker/workflows/schedule_plan.py",),
        readers=("tracker/workflows/schedule_plan.py",),
    ),
    # The supervisor's bookkeeping: run-now requests, the processes it runs and
    # what each job is doing now. Every write goes through the one store, which
    # the supervisor, its children and the API's routers call.
    "job_requests": TableOwnership(
        claim="infra",
        lifecycle="operational",
        writers=("tracker/db/job_store.py",),
        readers=("tracker/db/job_store.py",),
    ),
    "job_runs": TableOwnership(
        claim="infra",
        lifecycle="operational",
        writers=("tracker/db/job_store.py",),
        readers=("tracker/db/job_store.py",),
    ),
    "job_status": TableOwnership(
        claim="infra",
        lifecycle="operational",
        writers=("tracker/db/job_store.py",),
        readers=("tracker/db/job_store.py",),
    ),

    "binding_reconciliation_decisions": TableOwnership(
        claim="user",
        lifecycle="append_only",
        writers=("tracker/db/reconciliation.py",),
        readers=("tracker/db/reconciliation.py", "tracker/db/binding.py"),
    ),

    # --- planned: schema ahead of feature, intentionally unpopulated -----------
    "skill_candidates": TableOwnership(
        claim="planned:skills curation backlog (no writer yet)",
        lifecycle="unpopulated",
        writers=(),
        readers=(),
    ),
    "skill_relations": TableOwnership(
        claim="planned:skill graph edges (no writer yet)",
        lifecycle="unpopulated",
        writers=(),
        readers=(),
    ),
    # --- plugins ----------------------------------------------------------------
    # The install CLI and the plugin host write these through one store; the
    # registry reads them.
    "plugin_install": TableOwnership(
        claim="user",
        lifecycle="authored",
        writers=("tracker/plugins/store.py",),
        readers=("tracker/plugins/registry.py",),
    ),
    "plugin_run": TableOwnership(
        claim="infra",
        lifecycle="operational",
        writers=("tracker/plugins/store.py",),
        readers=("tracker/plugins/registry.py",),
    ),
    "plugin_state": TableOwnership(
        claim="infra",
        lifecycle="operational",
        writers=("tracker/plugins/store.py",),
        readers=("tracker/plugins/store.py",),
    ),
    # Numbers a plugin reports for the user (`ctx.report`): the plugin's
    # settings show them; cascade with the install.
    "plugin_report": TableOwnership(
        claim="infra",
        lifecycle="operational",
        writers=("tracker/plugins/store.py",),
        readers=("tracker/plugins/status.py",),
    ),
    # Companies with published rows per (provider, slot): the Plugins tab's
    # coverage; cleared with the user's Remove data.
    "plugin_coverage": TableOwnership(
        claim="infra",
        lifecycle="operational",
        writers=("tracker/plugins/store.py",),
        readers=("tracker/plugins/status.py",),
    ),
    "reference_state": TableOwnership(
        claim="post_pass:reference",
        lifecycle="operational",
        writers=("tracker/plugins/reestimate.py",),
        readers=("tracker/plugins/registry.py", "tracker/plugins/status.py", "tracker/plugins/lifecycle.py",
                 "tracker/api/routers/jobs.py"),
    ),
    "reference_change": TableOwnership(
        claim="post_pass:reference",
        lifecycle="append_only",
        writers=("tracker/plugins/reestimate.py",),
        readers=("tracker/plugins/reestimate.py", "tracker/plugins/status.py"),
    ),
}


def parse_claim(claim: str) -> tuple[str, str | None]:
    """Split a claim into ``(kind, arg)``; ``arg`` is None for bare kinds."""
    kind, _, arg = claim.partition(":")
    return kind, (arg or None)
