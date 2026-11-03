"""Create the schema for a fresh database.

The revision ID also identifies databases already at this baseline. Its schema
is frozen here; subsequent model changes belong in new revisions.
"""

import sqlalchemy as sa
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "c5e1a9d3f7b2"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.create_table(
        "ai_task_log",
        sa.Column("id", sa.BIGINT(), autoincrement=True, nullable=False),
        sa.Column(
            "created_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("task_type", sa.VARCHAR(length=32), nullable=False),
        sa.Column("provider", sa.VARCHAR(length=24), nullable=False),
        sa.Column("availability_state", sa.VARCHAR(length=32), nullable=False),
        sa.Column("latency_ms", sa.INTEGER(), nullable=True),
        sa.Column("input_tokens", sa.INTEGER(), nullable=True),
        sa.Column("output_tokens", sa.INTEGER(), nullable=True),
        sa.Column("validation_result", sa.VARCHAR(length=16), nullable=False),
        sa.Column("failure_class", sa.VARCHAR(length=32), nullable=True),
        sa.Column("prompt_version", sa.VARCHAR(length=32), nullable=True),
        sa.Column("model_id", sa.VARCHAR(length=64), nullable=True),
        sa.Column("job_id", sa.INTEGER(), nullable=True),
        sa.Column("meta", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("route_reason", sa.VARCHAR(length=32), nullable=True),
        sa.PrimaryKeyConstraint("id", name="ai_task_log_pkey"),
    )
    op.create_index("ix_ai_task_log_created_at", "ai_task_log", ["created_at"], unique=False)
    op.create_index("ix_ai_task_log_job_id", "ai_task_log", ["job_id"], unique=False)
    op.create_index("ix_ai_task_log_task_type", "ai_task_log", ["task_type"], unique=False)
    op.create_index(
        "ix_ai_task_log_type_time", "ai_task_log", ["task_type", "created_at"], unique=False
    )
    op.create_table(
        "app_settings",
        sa.Column("key", sa.VARCHAR(length=64), autoincrement=False, nullable=False),
        sa.Column("value", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.PrimaryKeyConstraint("key", name="app_settings_pkey"),
    )
    op.create_table(
        "binding_reconciliation_decisions",
        sa.Column("id", sa.BIGINT(), autoincrement=True, nullable=False),
        sa.Column("binding_id", sa.INTEGER(), nullable=False),
        sa.Column("job_id", sa.INTEGER(), nullable=True),
        sa.Column("source_key", sa.VARCHAR(length=256), nullable=True),
        sa.Column("decision", sa.VARCHAR(length=24), nullable=False),
        sa.Column(
            "evidence",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "actor",
            sa.VARCHAR(length=16),
            server_default=sa.text("'system'::character varying"),
            nullable=False,
        ),
        sa.Column("reason", sa.TEXT(), nullable=True),
        sa.Column(
            "created_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="binding_reconciliation_decisions_pkey"),
    )
    op.create_index(
        "ix_binding_reconciliation_decisions_binding_id",
        "binding_reconciliation_decisions",
        ["binding_id"],
        unique=False,
    )
    op.create_index(
        "ix_binding_reconciliation_decisions_decision",
        "binding_reconciliation_decisions",
        ["decision"],
        unique=False,
    )
    op.create_table(
        "clusters",
        sa.Column("id", sa.INTEGER(), autoincrement=True, nullable=False),
        sa.Column("model_version", sa.VARCHAR(length=48), nullable=False),
        sa.Column("label", sa.TEXT(), nullable=False),
        sa.Column("top_terms", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("family_hint", sa.VARCHAR(length=64), nullable=True),
        sa.Column("size", sa.INTEGER(), nullable=False),
        sa.Column(
            "created_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="clusters_pkey"),
    )
    op.create_table(
        "comp_metrics",
        sa.Column("id", sa.BIGINT(), autoincrement=True, nullable=False),
        sa.Column("metric_date", postgresql.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("dim", sa.VARCHAR(length=16), nullable=False),
        sa.Column("key", sa.VARCHAR(length=64), nullable=False),
        sa.Column("count", sa.INTEGER(), server_default=sa.text("0"), nullable=False),
        sa.Column("p25", sa.DOUBLE_PRECISION(precision=53), nullable=True),
        sa.Column("p50", sa.DOUBLE_PRECISION(precision=53), nullable=True),
        sa.Column("p75", sa.DOUBLE_PRECISION(precision=53), nullable=True),
        sa.Column("p90", sa.DOUBLE_PRECISION(precision=53), nullable=True),
        sa.PrimaryKeyConstraint("id", name="comp_metrics_pkey"),
        sa.UniqueConstraint("metric_date", "dim", "key", name="uq_comp_slice"),
    )
    op.create_index("ix_comp_metrics_dim", "comp_metrics", ["dim"], unique=False)
    op.create_index("ix_comp_metrics_key", "comp_metrics", ["key"], unique=False)
    op.create_index("ix_comp_metrics_metric_date", "comp_metrics", ["metric_date"], unique=False)
    op.create_table(
        "comp_snapshot",
        sa.Column("id", sa.BIGINT(), autoincrement=True, nullable=False),
        sa.Column("metric_date", postgresql.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("company", sa.VARCHAR(length=64), nullable=False),
        sa.Column(
            "level_band",
            sa.VARCHAR(length=32),
            server_default=sa.text("''::character varying"),
            nullable=False,
        ),
        sa.Column(
            "family",
            sa.VARCHAR(length=64),
            server_default=sa.text("''::character varying"),
            nullable=False,
        ),
        sa.Column(
            "comp_values",
            postgresql.ARRAY(sa.INTEGER()),
            server_default=sa.text("'{}'::integer[]"),
            nullable=False,
        ),
        sa.Column(
            "source",
            sa.VARCHAR(length=64),
            server_default=sa.text("'mixed'::character varying"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="comp_snapshot_pkey"),
        sa.UniqueConstraint(
            "metric_date", "company", "level_band", "family", "source", name="uq_comp_snapshot"
        ),
    )
    op.create_index("ix_comp_snapshot_company", "comp_snapshot", ["company"], unique=False)
    op.create_index("ix_comp_snapshot_metric_date", "comp_snapshot", ["metric_date"], unique=False)
    op.create_index("ix_comp_snapshot_source", "comp_snapshot", ["source"], unique=False)
    op.create_table(
        "company_benefit",
        sa.Column("id", sa.BIGINT(), autoincrement=True, nullable=False),
        sa.Column("company_slug", sa.VARCHAR(length=64), nullable=False),
        sa.Column("perk_id", sa.INTEGER(), nullable=True),
        sa.Column("category", sa.VARCHAR(length=48), nullable=False),
        sa.Column("name", sa.VARCHAR(length=128), nullable=False),
        sa.Column("value_usd", sa.BIGINT(), nullable=True),
        sa.Column("value_text", sa.TEXT(), nullable=True),
        sa.Column("description", sa.TEXT(), nullable=True),
        sa.Column(
            "detail",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "fetched_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("provider", sa.VARCHAR(length=32), nullable=False),
        sa.Column("retired_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name="company_benefit_pkey"),
        sa.UniqueConstraint("provider", "company_slug", "name", name="uq_company_benefit"),
    )
    op.create_index("ix_company_benefit_category", "company_benefit", ["category"], unique=False)
    op.create_index(
        "ix_company_benefit_company_slug", "company_benefit", ["company_slug"], unique=False
    )
    op.create_index("ix_company_benefit_provider", "company_benefit", ["provider"], unique=False)
    op.create_table(
        "company_comp_level",
        sa.Column("id", sa.BIGINT(), autoincrement=True, nullable=False),
        sa.Column("company_slug", sa.VARCHAR(length=64), nullable=False),
        sa.Column("family", sa.VARCHAR(length=48), nullable=False),
        sa.Column("level_label", sa.VARCHAR(length=48), nullable=False),
        sa.Column("band", sa.VARCHAR(length=24), nullable=True),
        sa.Column("tc_median", sa.BIGINT(), nullable=True),
        sa.Column("base_usd", sa.BIGINT(), nullable=True),
        sa.Column("stock_usd", sa.BIGINT(), nullable=True),
        sa.Column("bonus_usd", sa.BIGINT(), nullable=True),
        sa.Column("base_pct", sa.DOUBLE_PRECISION(precision=53), nullable=True),
        sa.Column("stock_pct", sa.DOUBLE_PRECISION(precision=53), nullable=True),
        sa.Column("bonus_pct", sa.DOUBLE_PRECISION(precision=53), nullable=True),
        sa.Column("source_url", sa.TEXT(), nullable=True),
        sa.Column(
            "fetched_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("band_source", sa.VARCHAR(length=16), nullable=True),
        sa.Column("provider", sa.VARCHAR(length=32), nullable=False),
        sa.Column("vendor_family", sa.VARCHAR(length=48), nullable=True),
        sa.Column("country", sa.VARCHAR(length=2), nullable=True),
        sa.Column("as_of", sa.DATE(), nullable=True),
        sa.Column("retired_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column(
            "aliases",
            postgresql.ARRAY(sa.TEXT()),
            server_default=sa.text("'{}'::text[]"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="company_comp_level_pkey"),
        sa.UniqueConstraint(
            "provider", "company_slug", "family", "level_label", name="uq_company_comp_level"
        ),
    )
    op.create_index("ix_company_comp_level_band", "company_comp_level", ["band"], unique=False)
    op.create_index(
        "ix_company_comp_level_company_slug", "company_comp_level", ["company_slug"], unique=False
    )
    op.create_index(
        "ix_company_comp_level_provider", "company_comp_level", ["provider"], unique=False
    )
    op.create_table(
        "company_fact",
        sa.Column("id", sa.BIGINT(), autoincrement=True, nullable=False),
        sa.Column("company_slug", sa.VARCHAR(length=64), nullable=False),
        sa.Column("field", sa.VARCHAR(length=48), nullable=False),
        sa.Column("value", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("source", sa.VARCHAR(length=32), nullable=False),
        sa.Column(
            "confidence",
            sa.DOUBLE_PRECISION(precision=53),
            server_default=sa.text("'1'::double precision"),
            nullable=False,
        ),
        sa.Column("observed_at", postgresql.TIMESTAMP(timezone=True), nullable=False),
        sa.Column(
            "fetched_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="company_fact_pkey"),
    )
    op.create_index("ix_company_fact_company_slug", "company_fact", ["company_slug"], unique=False)
    op.create_index("ix_company_fact_field", "company_fact", ["field"], unique=False)
    op.create_index(
        "ix_company_fact_lookup", "company_fact", ["company_slug", "field", "source"], unique=False
    )
    op.create_index("ix_company_fact_observed_at", "company_fact", ["observed_at"], unique=False)
    op.create_index("ix_company_fact_source", "company_fact", ["source"], unique=False)
    op.create_table(
        "company_price",
        sa.Column("company_slug", sa.VARCHAR(length=64), autoincrement=False, nullable=False),
        sa.Column("ticker", sa.VARCHAR(length=12), nullable=False),
        sa.Column("price", sa.NUMERIC(precision=14, scale=4), nullable=False),
        sa.Column(
            "currency",
            sa.VARCHAR(length=8),
            server_default=sa.text("'USD'::character varying"),
            nullable=False,
        ),
        sa.Column("change_abs", sa.NUMERIC(precision=14, scale=4), nullable=True),
        sa.Column("change_pct", sa.DOUBLE_PRECISION(precision=53), nullable=True),
        sa.Column("as_of", sa.DATE(), nullable=False),
        sa.Column(
            "source",
            sa.VARCHAR(length=24),
            server_default=sa.text("'market'::character varying"),
            nullable=False,
        ),
        sa.Column(
            "fetched_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("company_slug", name="company_price_pkey"),
    )
    op.create_table(
        "company_price_history",
        sa.Column("id", sa.BIGINT(), autoincrement=True, nullable=False),
        sa.Column("company_slug", sa.VARCHAR(length=64), nullable=False),
        sa.Column("date", sa.DATE(), nullable=False),
        sa.Column("open", sa.NUMERIC(precision=14, scale=4), nullable=True),
        sa.Column("high", sa.NUMERIC(precision=14, scale=4), nullable=True),
        sa.Column("low", sa.NUMERIC(precision=14, scale=4), nullable=True),
        sa.Column("close", sa.NUMERIC(precision=14, scale=4), nullable=False),
        sa.Column("volume", sa.BIGINT(), nullable=True),
        sa.Column(
            "source",
            sa.VARCHAR(length=24),
            server_default=sa.text("'market'::character varying"),
            nullable=False,
        ),
        sa.Column(
            "fetched_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="company_price_history_pkey"),
        sa.UniqueConstraint("company_slug", "date", name="uq_company_price_bar"),
    )
    op.create_index(
        "ix_company_price_history_company_slug",
        "company_price_history",
        ["company_slug"],
        unique=False,
    )
    op.create_table(
        "company_profile",
        sa.Column("slug", sa.VARCHAR(length=64), autoincrement=False, nullable=False),
        sa.Column("display_name", sa.VARCHAR(length=128), nullable=False),
        sa.Column("is_public", sa.BOOLEAN(), nullable=True),
        sa.Column("ticker", sa.VARCHAR(length=12), nullable=True),
        sa.Column("headcount", sa.INTEGER(), nullable=True),
        sa.Column("hq_city", sa.VARCHAR(length=64), nullable=True),
        sa.Column("website", sa.TEXT(), nullable=True),
        sa.Column("year_founded", sa.INTEGER(), nullable=True),
        sa.Column("equity_vehicle", sa.VARCHAR(length=16), nullable=True),
        sa.Column("vesting_schedule", sa.VARCHAR(length=32), nullable=True),
        sa.Column("comp_notes", sa.TEXT(), nullable=True),
        sa.Column(
            "manual_fields",
            postgresql.ARRAY(sa.TEXT()),
            server_default=sa.text("'{}'::text[]"),
            nullable=False,
        ),
        sa.Column(
            "profile_updated_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "field_meta",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "data_health",
            sa.VARCHAR(length=16),
            server_default=sa.text("'missing'::character varying"),
            nullable=False,
        ),
        sa.Column("logo_url", sa.TEXT(), nullable=True),
        sa.Column("brand_color", sa.VARCHAR(length=16), nullable=True),
        sa.PrimaryKeyConstraint("slug", name="company_profile_pkey"),
    )
    op.create_table(
        "company_scope_rules",
        sa.Column("id", sa.INTEGER(), autoincrement=True, nullable=False),
        sa.Column("company", sa.VARCHAR(length=64), nullable=False),
        sa.Column("kind", sa.VARCHAR(length=16), nullable=False),
        sa.Column("value", sa.TEXT(), nullable=False),
        sa.Column(
            "created_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="company_scope_rules_pkey"),
        sa.UniqueConstraint("company", "kind", "value", name="uq_company_scope_rule"),
    )
    op.create_index(
        "ix_company_scope_rules_company", "company_scope_rules", ["company"], unique=False
    )
    op.create_table(
        "compare_selection",
        sa.Column("id", sa.INTEGER(), autoincrement=True, nullable=False),
        sa.Column("job_id", sa.INTEGER(), nullable=False),
        sa.Column("position", sa.INTEGER(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "created_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="compare_selection_pkey"),
        sa.UniqueConstraint("job_id", name="uq_compare_selection_job"),
    )
    op.create_index("ix_compare_selection_job_id", "compare_selection", ["job_id"], unique=False)
    op.create_table(
        "connector_recipe_revisions",
        sa.Column("id", sa.INTEGER(), autoincrement=True, nullable=False),
        sa.Column("recipe_id", sa.INTEGER(), nullable=False),
        sa.Column("version", sa.INTEGER(), nullable=False),
        sa.Column("document", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("checksum", sa.VARCHAR(length=64), nullable=False),
        sa.Column(
            "validation",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "created_by",
            sa.VARCHAR(length=32),
            server_default=sa.text("'system'::character varying"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="connector_recipe_revisions_pkey"),
        sa.UniqueConstraint("recipe_id", "version", name="uq_recipe_revision_version"),
    )
    op.create_index(
        "ix_recipe_revisions_checksum", "connector_recipe_revisions", ["checksum"], unique=False
    )
    op.create_index(
        "ix_recipe_revisions_recipe_id", "connector_recipe_revisions", ["recipe_id"], unique=False
    )
    op.create_table(
        "connector_recipes",
        sa.Column("id", sa.INTEGER(), autoincrement=True, nullable=False),
        sa.Column("slug", sa.VARCHAR(length=64), nullable=False),
        sa.Column(
            "kind",
            sa.VARCHAR(length=32),
            server_default=sa.text("'job_listing'::character varying"),
            nullable=False,
        ),
        sa.Column("format_version", sa.INTEGER(), server_default=sa.text("1"), nullable=False),
        sa.Column("default_revision_id", sa.INTEGER(), nullable=True),
        sa.Column(
            "status",
            sa.VARCHAR(length=16),
            server_default=sa.text("'draft'::character varying"),
            nullable=False,
        ),
        sa.Column(
            "provenance",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="connector_recipes_pkey"),
    )
    op.create_index("ix_connector_recipes_slug", "connector_recipes", ["slug"], unique=True)
    op.create_index("ix_connector_recipes_status", "connector_recipes", ["status"], unique=False)
    op.create_table(
        "demand_metrics",
        sa.Column("id", sa.BIGINT(), autoincrement=True, nullable=False),
        sa.Column("metric_date", postgresql.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("company", sa.VARCHAR(length=64), nullable=False),
        sa.Column("family", sa.VARCHAR(length=64), nullable=True),
        sa.Column("location_group", sa.VARCHAR(length=64), nullable=True),
        sa.Column("open_count", sa.INTEGER(), nullable=False),
        sa.Column("new_count", sa.INTEGER(), nullable=False),
        sa.Column("closed_count", sa.INTEGER(), nullable=False),
        sa.Column("reposted_count", sa.INTEGER(), nullable=False),
        sa.Column("long_open_count", sa.INTEGER(), nullable=False),
        sa.Column("median_days_open", sa.DOUBLE_PRECISION(precision=53), nullable=True),
        sa.PrimaryKeyConstraint("id", name="demand_metrics_pkey"),
        sa.UniqueConstraint(
            "metric_date", "company", "family", "location_group", name="uq_demand_slice"
        ),
    )
    op.create_index("ix_demand_metrics_company", "demand_metrics", ["company"], unique=False)
    op.create_index(
        "ix_demand_metrics_metric_date", "demand_metrics", ["metric_date"], unique=False
    )
    op.create_table(
        "derivation_state",
        sa.Column("name", sa.VARCHAR(length=32), autoincrement=False, nullable=False),
        sa.Column("last_run_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("last_ok_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column(
            "last_status",
            sa.VARCHAR(length=16),
            server_default=sa.text("'ok'::character varying"),
            nullable=False,
        ),
        sa.Column(
            "detail",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("name", name="derivation_state_pkey"),
    )
    op.create_table(
        "directory_checks",
        sa.Column("slug", sa.VARCHAR(length=80), autoincrement=False, nullable=False),
        sa.Column("checked_at", postgresql.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("outcome", sa.VARCHAR(length=16), nullable=False),
        sa.Column("scanned", sa.INTEGER(), nullable=False),
        sa.Column("roles_for_you", sa.INTEGER(), nullable=False),
        sa.Column("error", sa.TEXT(), nullable=True),
        sa.PrimaryKeyConstraint("slug", name="directory_checks_pkey"),
    )
    op.create_index(
        "ix_directory_checks_checked_at", "directory_checks", ["checked_at"], unique=False
    )
    op.create_table(
        "disclosure_snapshot",
        sa.Column("id", sa.BIGINT(), autoincrement=True, nullable=False),
        sa.Column("metric_date", postgresql.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("company", sa.VARCHAR(length=64), nullable=False),
        sa.Column("level_band", sa.VARCHAR(length=32), nullable=False),
        sa.Column("pay_basis", sa.VARCHAR(length=8), nullable=False),
        sa.Column("roles", sa.INTEGER(), nullable=False),
        sa.Column("checked", sa.INTEGER(), nullable=False),
        sa.Column("bands", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.PrimaryKeyConstraint("id", name="disclosure_snapshot_pkey"),
        sa.UniqueConstraint(
            "metric_date", "company", "level_band", "pay_basis", name="uq_disclosure_snapshot"
        ),
    )
    op.create_index(
        "ix_disclosure_snapshot_company", "disclosure_snapshot", ["company"], unique=False
    )
    op.create_index(
        "ix_disclosure_snapshot_metric_date", "disclosure_snapshot", ["metric_date"], unique=False
    )
    op.create_table(
        "external_comp_observation",
        sa.Column("id", sa.BIGINT(), autoincrement=True, nullable=False),
        sa.Column("company_slug", sa.VARCHAR(length=64), nullable=False),
        sa.Column("source_level", sa.VARCHAR(length=48), nullable=False),
        sa.Column("band", sa.VARCHAR(length=24), nullable=True),
        sa.Column("function", sa.VARCHAR(length=48), nullable=True),
        sa.Column("location", sa.VARCHAR(length=64), nullable=True),
        sa.Column("yoe", sa.INTEGER(), nullable=True),
        sa.Column("total_usd", sa.BIGINT(), nullable=False),
        sa.Column("base_usd", sa.BIGINT(), nullable=False),
        sa.Column("equity_usd", sa.BIGINT(), nullable=False),
        sa.Column("bonus_usd", sa.BIGINT(), nullable=False),
        sa.Column("snapshot_date", sa.DATE(), nullable=False),
        sa.Column("dedup_key", sa.VARCHAR(length=200), nullable=False),
        sa.Column(
            "ingested_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("provider", sa.VARCHAR(length=32), nullable=False),
        sa.PrimaryKeyConstraint("id", name="external_comp_observation_pkey"),
        sa.UniqueConstraint("provider", "dedup_key", name="uq_external_comp_obs"),
    )
    op.create_index(
        "ix_external_comp_observation_band", "external_comp_observation", ["band"], unique=False
    )
    op.create_index(
        "ix_external_comp_observation_company_slug",
        "external_comp_observation",
        ["company_slug"],
        unique=False,
    )
    op.create_index(
        "ix_external_comp_observation_provider",
        "external_comp_observation",
        ["provider"],
        unique=False,
    )
    op.create_index(
        "ix_external_comp_observation_snapshot_date",
        "external_comp_observation",
        ["snapshot_date"],
        unique=False,
    )
    op.create_table(
        "favorites",
        sa.Column("id", sa.INTEGER(), autoincrement=True, nullable=False),
        sa.Column("job_id", sa.INTEGER(), nullable=False),
        sa.Column(
            "created_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="favorites_pkey"),
        sa.UniqueConstraint("job_id", name="uq_favorite_job"),
    )
    op.create_index("ix_favorites_job_id", "favorites", ["job_id"], unique=False)
    op.create_table(
        "job_comp_estimate",
        sa.Column("job_id", sa.INTEGER(), autoincrement=False, nullable=False),
        sa.Column("source", sa.VARCHAR(length=64), autoincrement=False, nullable=False),
        sa.Column("comp_low", sa.BIGINT(), nullable=True),
        sa.Column("comp_high", sa.BIGINT(), nullable=True),
        sa.Column("comp_median", sa.BIGINT(), nullable=True),
        sa.Column("comp_currency", sa.VARCHAR(length=8), nullable=False),
        sa.Column("comp_provenance", sa.TEXT(), nullable=True),
        sa.Column("comp_base_low", sa.BIGINT(), nullable=True),
        sa.Column("comp_base_median", sa.BIGINT(), nullable=True),
        sa.Column("comp_base_high", sa.BIGINT(), nullable=True),
        sa.Column("comp_component", sa.VARCHAR(length=8), nullable=True),
        sa.Column("comp_provider", sa.VARCHAR(length=32), nullable=True),
        sa.Column("comp_as_of", sa.DATE(), nullable=True),
        sa.Column("sources", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("ref_fp", sa.VARCHAR(length=64), nullable=True),
        sa.Column(
            "estimated_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("job_id", "source", name="job_comp_estimate_pkey"),
    )
    op.create_index("ix_job_comp_estimate_source", "job_comp_estimate", ["source"], unique=False)
    op.create_table(
        "job_feedback",
        sa.Column("id", sa.INTEGER(), autoincrement=True, nullable=False),
        sa.Column("job_id", sa.INTEGER(), nullable=False),
        sa.Column("verdict", sa.VARCHAR(length=16), nullable=False),
        sa.Column("reason", sa.VARCHAR(length=32), nullable=True),
        sa.Column(
            "created_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="job_feedback_pkey"),
    )
    op.create_index("ix_job_feedback_job_id", "job_feedback", ["job_id"], unique=True)
    op.create_table(
        "job_lifecycle_events",
        sa.Column("id", sa.BIGINT(), autoincrement=True, nullable=False),
        sa.Column("job_id", sa.INTEGER(), nullable=False),
        sa.Column("run_id", sa.INTEGER(), nullable=True),
        sa.Column("event_type", sa.VARCHAR(length=24), nullable=False),
        sa.Column("detail", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="job_lifecycle_events_pkey"),
    )
    op.create_index(
        "ix_job_lifecycle_events_created_at", "job_lifecycle_events", ["created_at"], unique=False
    )
    op.create_index(
        "ix_job_lifecycle_events_event_type", "job_lifecycle_events", ["event_type"], unique=False
    )
    op.create_index(
        "ix_job_lifecycle_events_job_id", "job_lifecycle_events", ["job_id"], unique=False
    )
    op.create_table(
        "job_lineage",
        sa.Column("id", sa.BIGINT(), autoincrement=True, nullable=False),
        sa.Column("company", sa.VARCHAR(length=64), nullable=False),
        sa.Column("root_job_id", sa.INTEGER(), nullable=False),
        sa.Column("size", sa.INTEGER(), server_default=sa.text("1"), nullable=False),
        sa.Column("open_members", sa.INTEGER(), server_default=sa.text("0"), nullable=False),
        sa.Column("first_seen", postgresql.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("last_seen", postgresql.TIMESTAMP(timezone=True), nullable=False),
        sa.Column(
            "updated_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="job_lineage_pkey"),
    )
    op.create_index("ix_job_lineage_company", "job_lineage", ["company"], unique=False)
    op.create_index("uq_job_lineage_root", "job_lineage", ["root_job_id"], unique=True)
    op.create_table(
        "job_lineage_link",
        sa.Column("id", sa.BIGINT(), autoincrement=True, nullable=False),
        sa.Column("job_id", sa.INTEGER(), nullable=False),
        sa.Column("prior_job_id", sa.INTEGER(), nullable=False),
        sa.Column("relation", sa.VARCHAR(length=12), nullable=False),
        sa.Column("method", sa.VARCHAR(length=24), nullable=False),
        sa.Column("score", sa.DOUBLE_PRECISION(precision=53), nullable=True),
        sa.Column("title_similarity", sa.DOUBLE_PRECISION(precision=53), nullable=True),
        sa.Column("gap_days", sa.INTEGER(), nullable=True),
        sa.Column("confidence", sa.VARCHAR(length=12), nullable=False),
        sa.Column(
            "status",
            sa.VARCHAR(length=12),
            server_default=sa.text("'pending'::character varying"),
            nullable=False,
        ),
        sa.Column("reviewed_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("detector_version", sa.VARCHAR(length=32), nullable=False),
        sa.Column(
            "evidence",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="job_lineage_link_pkey"),
        sa.UniqueConstraint("job_id", "prior_job_id", name="uq_job_lineage_link"),
    )
    op.create_index("ix_job_lineage_link_job_id", "job_lineage_link", ["job_id"], unique=False)
    op.create_index(
        "ix_job_lineage_link_prior_job_id", "job_lineage_link", ["prior_job_id"], unique=False
    )
    op.create_index(
        "ix_job_lineage_link_review",
        "job_lineage_link",
        ["status", "confidence", "created_at"],
        unique=False,
    )
    op.create_table(
        "job_observations",
        sa.Column("id", sa.BIGINT(), autoincrement=True, nullable=False),
        sa.Column("job_id", sa.INTEGER(), nullable=False),
        sa.Column("run_id", sa.INTEGER(), nullable=False),
        sa.Column(
            "observed_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("title", sa.TEXT(), nullable=False),
        sa.Column("level_band", sa.VARCHAR(length=32), nullable=False),
        sa.Column("family", sa.VARCHAR(length=64), nullable=True),
        sa.Column("locations", postgresql.ARRAY(sa.TEXT()), nullable=False),
        sa.Column("comp_median", sa.BIGINT(), nullable=True),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("binding_id", sa.INTEGER(), nullable=True),
        sa.Column("source_identity_id", sa.BIGINT(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="job_observations_pkey"),
    )
    op.create_index(
        "ix_job_observations_binding_id", "job_observations", ["binding_id"], unique=False
    )
    op.create_index("ix_job_observations_job_id", "job_observations", ["job_id"], unique=False)
    op.create_index("ix_job_observations_run_id", "job_observations", ["run_id"], unique=False)
    op.create_table(
        "job_place_set",
        sa.Column("id", sa.BIGINT(), autoincrement=True, nullable=False),
        sa.Column("company", sa.VARCHAR(length=64), nullable=False),
        sa.Column("title", sa.TEXT(), nullable=False),
        sa.Column("text_hash", sa.VARCHAR(length=32), nullable=False),
        sa.Column("size", sa.INTEGER(), nullable=False),
        sa.Column("places", postgresql.ARRAY(sa.TEXT()), nullable=False),
        sa.Column("rule_version", sa.VARCHAR(length=32), nullable=False),
        sa.Column("evidence", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="job_place_set_pkey"),
        sa.UniqueConstraint("company", "title", "text_hash", name="uq_job_place_set_identity"),
    )
    op.create_index("ix_job_place_set_company", "job_place_set", ["company"], unique=False)
    op.create_table(
        "job_place_set_member",
        sa.Column("job_id", sa.INTEGER(), autoincrement=False, nullable=False),
        sa.Column("set_id", sa.BIGINT(), nullable=True),
        sa.Column("status", sa.VARCHAR(length=12), nullable=False),
        sa.Column("evidence", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("reviewed_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("status IN ('auto', 'rejected')", name="ck_job_place_set_member_status"),
        sa.PrimaryKeyConstraint("job_id", name="job_place_set_member_pkey"),
    )
    op.create_index(
        "ix_job_place_set_member_set_id", "job_place_set_member", ["set_id"], unique=False
    )
    op.create_table(
        "job_qualifications",
        sa.Column("id", sa.BIGINT(), autoincrement=True, nullable=False),
        sa.Column("job_id", sa.INTEGER(), nullable=False),
        sa.Column("kind", sa.VARCHAR(length=16), nullable=False),
        sa.Column("display", sa.TEXT(), nullable=False),
        sa.Column("value", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("modality", sa.VARCHAR(length=12), nullable=False),
        sa.Column(
            "confidence",
            sa.VARCHAR(length=8),
            server_default=sa.text("'high'::character varying"),
            nullable=False,
        ),
        sa.Column("section_key", sa.VARCHAR(length=64), nullable=True),
        sa.Column("section_title", sa.TEXT(), nullable=True),
        sa.Column("quote", sa.TEXT(), nullable=False),
        sa.Column("start_offset", sa.INTEGER(), nullable=False),
        sa.Column("end_offset", sa.INTEGER(), nullable=False),
        sa.Column("extractor_version", sa.VARCHAR(length=16), nullable=False),
        sa.PrimaryKeyConstraint("id", name="job_qualifications_pkey"),
    )
    op.create_index("ix_job_qualifications_job_id", "job_qualifications", ["job_id"], unique=False)
    op.create_table(
        "job_relevance_reviews",
        sa.Column("id", sa.INTEGER(), autoincrement=True, nullable=False),
        sa.Column("job_id", sa.INTEGER(), nullable=False),
        sa.Column("domain", sa.VARCHAR(length=64), nullable=True),
        sa.Column("relevance", sa.VARCHAR(length=16), nullable=False),
        sa.Column("confidence", sa.DOUBLE_PRECISION(precision=53), nullable=False),
        sa.Column("rationale", sa.TEXT(), nullable=False),
        sa.Column("tracked_worlds", postgresql.ARRAY(sa.TEXT()), nullable=True),
        sa.Column("prompt_version", sa.VARCHAR(length=64), nullable=False),
        sa.Column("provider", sa.VARCHAR(length=64), nullable=True),
        sa.Column("model_id", sa.VARCHAR(length=64), nullable=True),
        sa.Column(
            "reviewed_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "relevance IN ('relevant','irrelevant','uncertain')", name="ck_relevance_review_verdict"
        ),
        sa.PrimaryKeyConstraint("id", name="job_relevance_reviews_pkey"),
    )
    op.create_index(
        "ix_job_relevance_reviews_job_id", "job_relevance_reviews", ["job_id"], unique=True
    )
    op.create_table(
        "job_similarity",
        sa.Column("id", sa.BIGINT(), autoincrement=True, nullable=False),
        sa.Column("job_id", sa.INTEGER(), nullable=False),
        sa.Column("neighbor_job_id", sa.INTEGER(), nullable=False),
        sa.Column("scope", sa.VARCHAR(length=12), nullable=False),
        sa.Column("rank", sa.INTEGER(), nullable=False),
        sa.Column("score", sa.DOUBLE_PRECISION(precision=53), nullable=False),
        sa.PrimaryKeyConstraint("id", name="job_similarity_pkey"),
        sa.UniqueConstraint("job_id", "scope", "neighbor_job_id", name="uq_job_similarity"),
    )
    op.create_index("ix_job_similarity_job_id", "job_similarity", ["job_id"], unique=False)
    op.create_index(
        "ix_job_similarity_lookup", "job_similarity", ["job_id", "scope", "rank"], unique=False
    )
    op.create_table(
        "job_skill_evidence",
        sa.Column("id", sa.BIGINT(), autoincrement=True, nullable=False),
        sa.Column("job_skill_id", sa.BIGINT(), nullable=False),
        sa.Column("job_id", sa.INTEGER(), nullable=False),
        sa.Column("concept_id", sa.INTEGER(), nullable=False),
        sa.Column("section_key", sa.VARCHAR(length=64), nullable=True),
        sa.Column("section_title", sa.TEXT(), nullable=True),
        sa.Column("unit_index", sa.INTEGER(), server_default=sa.text("0"), nullable=False),
        sa.Column("quote", sa.TEXT(), nullable=False),
        sa.Column("start_offset", sa.INTEGER(), nullable=False),
        sa.Column("end_offset", sa.INTEGER(), nullable=False),
        sa.Column("aspect", sa.VARCHAR(length=16), nullable=False),
        sa.Column("modality", sa.VARCHAR(length=16), nullable=False),
        sa.Column("proficiency", sa.VARCHAR(length=16), nullable=True),
        sa.Column("years", sa.DOUBLE_PRECISION(precision=53), nullable=True),
        sa.Column("actor", sa.VARCHAR(length=12), nullable=False),
        sa.Column("boilerplate_score", sa.DOUBLE_PRECISION(precision=53), nullable=True),
        sa.Column(
            "extractor",
            sa.VARCHAR(length=12),
            server_default=sa.text("'dictionary'::character varying"),
            nullable=False,
        ),
        sa.Column(
            "confidence",
            sa.VARCHAR(length=8),
            server_default=sa.text("'high'::character varying"),
            nullable=False,
        ),
        sa.Column("score", sa.INTEGER(), server_default=sa.text("0"), nullable=False),
        sa.PrimaryKeyConstraint("id", name="job_skill_evidence_pkey"),
    )
    op.create_index("ix_job_skill_evidence_job_id", "job_skill_evidence", ["job_id"], unique=False)
    op.create_index(
        "ix_job_skill_evidence_job_skill_id", "job_skill_evidence", ["job_skill_id"], unique=False
    )
    op.create_table(
        "job_skills",
        sa.Column("id", sa.BIGINT(), autoincrement=True, nullable=False),
        sa.Column("job_id", sa.INTEGER(), nullable=False),
        sa.Column("concept_id", sa.INTEGER(), nullable=False),
        sa.Column("importance_score", sa.INTEGER(), nullable=False),
        sa.Column("importance_band", sa.VARCHAR(length=12), nullable=False),
        sa.Column("confidence", sa.VARCHAR(length=8), nullable=False),
        sa.Column("modality", sa.VARCHAR(length=16), nullable=False),
        sa.Column(
            "proficiency",
            sa.VARCHAR(length=16),
            server_default=sa.text("'unspecified'::character varying"),
            nullable=False,
        ),
        sa.Column("evidence_count", sa.INTEGER(), server_default=sa.text("1"), nullable=False),
        sa.Column("content_hash", sa.VARCHAR(length=32), nullable=False),
        sa.Column("extractor_version", sa.VARCHAR(length=16), nullable=False),
        sa.Column("taxonomy_version", sa.VARCHAR(length=16), nullable=False),
        sa.Column(
            "extracted_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="job_skills_pkey"),
        sa.UniqueConstraint("job_id", "concept_id", name="uq_job_skill"),
    )
    op.create_index("ix_job_skills_concept_id", "job_skills", ["concept_id"], unique=False)
    op.create_index("ix_job_skills_job_id", "job_skills", ["job_id"], unique=False)
    op.create_table(
        "job_source_identities",
        sa.Column("id", sa.BIGINT(), autoincrement=True, nullable=False),
        sa.Column("binding_id", sa.INTEGER(), nullable=False),
        sa.Column("job_id", sa.INTEGER(), nullable=False),
        sa.Column("source_key", sa.VARCHAR(length=256), nullable=False),
        sa.Column(
            "first_seen",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("last_seen", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column(
            "origin",
            sa.VARCHAR(length=24),
            server_default=sa.text("'exact_auto'::character varying"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="job_source_identities_pkey"),
        sa.UniqueConstraint("binding_id", "source_key", name="uq_identity_binding_source_key"),
    )
    op.create_index("ix_identity_job", "job_source_identities", ["job_id"], unique=False)
    op.create_index(
        "ix_job_source_identities_binding_id", "job_source_identities", ["binding_id"], unique=False
    )
    op.create_table(
        "job_twin_link",
        sa.Column("id", sa.BIGINT(), autoincrement=True, nullable=False),
        sa.Column("job_a_id", sa.INTEGER(), nullable=False),
        sa.Column("job_b_id", sa.INTEGER(), nullable=False),
        sa.Column("method", sa.VARCHAR(length=24), nullable=False),
        sa.Column("score", sa.DOUBLE_PRECISION(precision=53), nullable=True),
        sa.Column("title_similarity", sa.DOUBLE_PRECISION(precision=53), nullable=True),
        sa.Column("confidence", sa.VARCHAR(length=12), nullable=False),
        sa.Column(
            "status",
            sa.VARCHAR(length=12),
            server_default=sa.text("'pending'::character varying"),
            nullable=False,
        ),
        sa.Column("detector_version", sa.VARCHAR(length=32), nullable=False),
        sa.Column(
            "evidence",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("reviewed_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("job_a_id < job_b_id", name="ck_job_twin_link_canonical_pair"),
        sa.PrimaryKeyConstraint("id", name="job_twin_link_pkey"),
        sa.UniqueConstraint("job_a_id", "job_b_id", name="uq_job_twin_link_pair"),
    )
    op.create_index("ix_job_twin_link_job_a_id", "job_twin_link", ["job_a_id"], unique=False)
    op.create_index("ix_job_twin_link_job_b_id", "job_twin_link", ["job_b_id"], unique=False)
    op.create_index(
        "ix_job_twin_link_review",
        "job_twin_link",
        ["status", "confidence", "created_at"],
        unique=False,
    )
    op.create_table(
        "jobs",
        sa.Column("id", sa.INTEGER(), autoincrement=True, nullable=False),
        sa.Column("company", sa.VARCHAR(length=64), nullable=False),
        sa.Column("req_id", sa.VARCHAR(length=128), nullable=False),
        sa.Column("dedupe_key", sa.VARCHAR(length=256), nullable=False),
        sa.Column("title", sa.TEXT(), nullable=False),
        sa.Column("url", sa.TEXT(), nullable=False),
        sa.Column("department", sa.TEXT(), nullable=True),
        sa.Column("team", sa.TEXT(), nullable=True),
        sa.Column("description_html", sa.TEXT(), nullable=True),
        sa.Column("description_text", sa.TEXT(), nullable=True),
        sa.Column("locations", postgresql.ARRAY(sa.TEXT()), nullable=False),
        sa.Column("location_groups", postgresql.ARRAY(sa.TEXT()), nullable=False),
        sa.Column("workplace_type", sa.VARCHAR(length=16), nullable=False),
        sa.Column("raw_level", sa.VARCHAR(length=128), nullable=True),
        sa.Column("level_band", sa.VARCHAR(length=32), nullable=False),
        sa.Column("level_confidence", sa.VARCHAR(length=16), nullable=False),
        sa.Column("family", sa.VARCHAR(length=64), nullable=True),
        sa.Column("comp_low", sa.BIGINT(), nullable=True),
        sa.Column("comp_high", sa.BIGINT(), nullable=True),
        sa.Column("comp_median", sa.BIGINT(), nullable=True),
        sa.Column("comp_currency", sa.VARCHAR(length=8), nullable=False),
        sa.Column("comp_provenance", sa.TEXT(), nullable=True),
        sa.Column("status", sa.VARCHAR(length=16), nullable=False),
        sa.Column("posted_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column(
            "first_seen",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "last_seen",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("closed_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("total_days_open", sa.INTEGER(), nullable=False),
        sa.Column("repost_count", sa.INTEGER(), nullable=False),
        sa.Column("search_vector", postgresql.TSVECTOR(), nullable=True),
        sa.Column("content_hash", sa.VARCHAR(length=32), nullable=True),
        sa.Column("content_changed_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("embedding", Vector(768), nullable=True),
        sa.Column("embedded_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("cluster_id", sa.INTEGER(), nullable=True),
        sa.Column("cluster_distance", sa.DOUBLE_PRECISION(precision=53), nullable=True),
        sa.Column("disclosed_base_min", sa.BIGINT(), nullable=True),
        sa.Column("disclosed_base_max", sa.BIGINT(), nullable=True),
        sa.Column("disclosed_currency", sa.VARCHAR(length=8), nullable=True),
        sa.Column("disclosed_pay_basis", sa.VARCHAR(length=8), nullable=True),
        sa.Column("disclosed_pay_period", sa.VARCHAR(length=8), nullable=True),
        sa.Column("disclosed_snippet", sa.TEXT(), nullable=True),
        sa.Column("disclosed_confidence", sa.VARCHAR(length=8), nullable=True),
        sa.Column("structured_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("structured_prompt_version", sa.VARCHAR(length=32), nullable=True),
        sa.Column("disclosed_bonus_pct", sa.DOUBLE_PRECISION(precision=53), nullable=True),
        sa.Column(
            "description_sections",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("lineage_id", sa.BIGINT(), nullable=True),
        sa.Column("lineage_seq", sa.INTEGER(), nullable=True),
        sa.Column("lineage_role", sa.VARCHAR(length=12), nullable=True),
        sa.Column("lineage_first_seen", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("lineage_checked_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("lineage_detector_version", sa.VARCHAR(length=32), nullable=True),
        sa.Column("in_scope", sa.BOOLEAN(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "track",
            sa.VARCHAR(length=32),
            server_default=sa.text("'technical'::character varying"),
            nullable=False,
        ),
        sa.Column("viewed_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("requirements_content_hash", sa.VARCHAR(length=32), nullable=True),
        sa.Column("requirements_extractor_version", sa.VARCHAR(length=16), nullable=True),
        sa.Column("requirements_taxonomy_version", sa.VARCHAR(length=16), nullable=True),
        sa.Column("requirements_extracted_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column(
            "location_cities",
            postgresql.ARRAY(sa.TEXT()),
            server_default=sa.text("'{}'::text[]"),
            nullable=False,
        ),
        sa.Column("description_fetched_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("domains", postgresql.ARRAY(sa.TEXT()), nullable=True),
        sa.Column("embedded_tier", sa.VARCHAR(length=8), nullable=True),
        sa.Column("source_facts", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("closure_basis", sa.VARCHAR(length=48), nullable=True),
        sa.Column("closure_run_id", sa.INTEGER(), nullable=True),
        sa.Column("first_posted_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("absent_scans", sa.INTEGER(), server_default=sa.text("0"), nullable=False),
        sa.Column("absent_since", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("level_basis", sa.VARCHAR(length=16), nullable=True),
        sa.Column("disclosed_source", sa.VARCHAR(length=12), nullable=True),
        sa.Column("required_years", sa.DOUBLE_PRECISION(precision=53), nullable=True),
        sa.Column("disclosed_place_key", sa.VARCHAR(length=200), nullable=True),
        sa.Column("lineage_input_key", sa.VARCHAR(length=32), nullable=True),
        sa.Column("comp_base_low", sa.BIGINT(), nullable=True),
        sa.Column("comp_base_median", sa.BIGINT(), nullable=True),
        sa.Column("comp_base_high", sa.BIGINT(), nullable=True),
        sa.Column("comp_component", sa.VARCHAR(length=8), nullable=True),
        sa.Column("comp_provider", sa.VARCHAR(length=32), nullable=True),
        sa.Column("comp_as_of", sa.DATE(), nullable=True),
        sa.Column("comp_ref_fp", sa.VARCHAR(length=64), nullable=True),
        sa.PrimaryKeyConstraint("id", name="jobs_pkey"),
    )
    op.create_index("ix_jobs_cluster_id", "jobs", ["cluster_id"], unique=False)
    op.create_index("ix_jobs_company", "jobs", ["company"], unique=False)
    op.create_index(
        "ix_jobs_company_family_level", "jobs", ["company", "family", "level_band"], unique=False
    )
    op.create_index("ix_jobs_company_status", "jobs", ["company", "status"], unique=False)
    op.create_index(
        "ix_jobs_company_trgm",
        "jobs",
        ["company"],
        unique=False,
        postgresql_using="gin",
        postgresql_ops={"company": "gin_trgm_ops"},
    )
    op.create_index("ix_jobs_dedupe_key", "jobs", ["dedupe_key"], unique=True)
    op.create_index(
        "ix_jobs_effective_age",
        "jobs",
        [sa.text("COALESCE(lineage_first_seen, first_seen)")],
        unique=False,
    )
    op.create_index(
        "ix_jobs_embedding_hnsw",
        "jobs",
        ["embedding"],
        unique=False,
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )
    op.create_index("ix_jobs_family", "jobs", ["family"], unique=False)
    op.create_index("ix_jobs_in_scope", "jobs", ["in_scope"], unique=False)
    op.create_index("ix_jobs_level_band", "jobs", ["level_band"], unique=False)
    op.create_index("ix_jobs_lineage", "jobs", ["lineage_id", "lineage_seq"], unique=False)
    op.create_index("ix_jobs_lineage_role", "jobs", ["lineage_role"], unique=False)
    op.create_index(
        "ix_jobs_search_vector", "jobs", ["search_vector"], unique=False, postgresql_using="gin"
    )
    op.create_index("ix_jobs_status", "jobs", ["status"], unique=False)
    op.create_index("ix_jobs_status_in_scope", "jobs", ["status", "in_scope"], unique=False)
    op.create_index(
        "ix_jobs_title_trgm",
        "jobs",
        ["title"],
        unique=False,
        postgresql_using="gin",
        postgresql_ops={"title": "gin_trgm_ops"},
    )
    op.create_index("ix_jobs_track", "jobs", ["track"], unique=False)
    op.create_table(
        "machine_awake_samples",
        sa.Column(
            "seen_at", postgresql.TIMESTAMP(timezone=True), autoincrement=False, nullable=False
        ),
        sa.Column("source", sa.VARCHAR(length=8), nullable=False),
        sa.PrimaryKeyConstraint("seen_at", name="machine_awake_samples_pkey"),
    )
    op.create_table(
        "notifications",
        sa.Column("id", sa.BIGINT(), autoincrement=True, nullable=False),
        sa.Column("created_at", postgresql.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("priority", sa.VARCHAR(length=8), nullable=False),
        sa.Column("category", sa.VARCHAR(length=32), nullable=False),
        sa.Column("title", sa.TEXT(), nullable=False),
        sa.Column("body", sa.TEXT(), nullable=True),
        sa.Column("job_id", sa.INTEGER(), nullable=True),
        sa.Column("run_id", sa.INTEGER(), nullable=True),
        sa.Column("source_type", sa.VARCHAR(length=8), nullable=False),
        sa.Column("source_id", sa.BIGINT(), nullable=False),
        sa.Column("read_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("dismissed_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("meta", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.PrimaryKeyConstraint("id", name="notifications_pkey"),
        sa.UniqueConstraint("source_type", "source_id", "category", name="uq_notification_source"),
    )
    op.create_index("ix_notifications_category", "notifications", ["category"], unique=False)
    op.create_index("ix_notifications_created_at", "notifications", ["created_at"], unique=False)
    op.create_index("ix_notifications_job_id", "notifications", ["job_id"], unique=False)
    op.create_index(
        "ix_notifications_unread",
        "notifications",
        ["dismissed_at", "read_at", "created_at"],
        unique=False,
    )
    op.create_table(
        "plugin_coverage",
        sa.Column("provider", sa.VARCHAR(length=32), autoincrement=False, nullable=False),
        sa.Column("slot", sa.VARCHAR(length=32), autoincrement=False, nullable=False),
        sa.Column("company_slug", sa.VARCHAR(length=64), autoincrement=False, nullable=False),
        sa.Column("last_attempt_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("last_published_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("rows", sa.INTEGER(), server_default=sa.text("0"), nullable=False),
        sa.Column("last_run_id", sa.BIGINT(), nullable=True),
        sa.Column("complete_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("provider", "slot", "company_slug", name="plugin_coverage_pkey"),
    )
    op.create_table(
        "plugin_install",
        sa.Column("plugin_id", sa.VARCHAR(length=32), autoincrement=False, nullable=False),
        sa.Column("name", sa.TEXT(), nullable=False),
        sa.Column("version", sa.VARCHAR(length=64), nullable=False),
        sa.Column("source_dir", sa.TEXT(), nullable=False),
        sa.Column("code_sha", sa.VARCHAR(length=64), nullable=False),
        sa.Column("commit_sha", sa.VARCHAR(length=64), nullable=True),
        sa.Column("manifest_sha", sa.VARCHAR(length=64), nullable=False),
        sa.Column("lock_sha", sa.VARCHAR(length=64), nullable=True),
        sa.Column("manifest", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("fingerprint", sa.VARCHAR(length=64), nullable=False),
        sa.Column("approved_fingerprint", sa.VARCHAR(length=64), nullable=True),
        sa.Column("approved_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("approved_text", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("enabled", sa.BOOLEAN(), server_default=sa.text("false"), nullable=False),
        sa.Column("enabled_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column(
            "installed_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("removed_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("schedule", sa.VARCHAR(length=16), nullable=True),
        sa.Column("paused_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("sdk_version", sa.VARCHAR(length=32), nullable=True),
        sa.Column("robots_consent", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("robots_consent_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("robots_seen", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.PrimaryKeyConstraint("plugin_id", name="plugin_install_pkey"),
    )
    op.create_table(
        "plugin_report",
        sa.Column("plugin_id", sa.VARCHAR(length=32), autoincrement=False, nullable=False),
        sa.Column("key", sa.VARCHAR(length=64), autoincrement=False, nullable=False),
        sa.Column("value", sa.BIGINT(), nullable=False),
        sa.Column("label", sa.VARCHAR(length=160), nullable=False),
        sa.Column(
            "reported_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("plugin_id", "key", name="plugin_report_pkey"),
    )
    op.create_table(
        "plugin_run",
        sa.Column("id", sa.BIGINT(), autoincrement=True, nullable=False),
        sa.Column("plugin_id", sa.VARCHAR(length=32), nullable=False),
        sa.Column("job", sa.VARCHAR(length=32), nullable=False),
        sa.Column("trigger", sa.VARCHAR(length=16), nullable=False),
        sa.Column("fingerprint", sa.VARCHAR(length=64), nullable=False),
        sa.Column(
            "outcome",
            sa.VARCHAR(length=16),
            server_default=sa.text("'running'::character varying"),
            nullable=False,
        ),
        sa.Column(
            "started_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("heartbeat_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("ended_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("pid", sa.INTEGER(), nullable=True),
        sa.Column("progress_done", sa.INTEGER(), nullable=True),
        sa.Column("progress_total", sa.INTEGER(), nullable=True),
        sa.Column(
            "published",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "refusals",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("message", sa.TEXT(), nullable=True),
        sa.Column("continues", sa.BOOLEAN(), server_default=sa.text("false"), nullable=False),
        sa.CheckConstraint(
            "outcome IN ('running', 'clean', 'partial', 'bounded', 'stopped', 'error')",
            name="ck_plugin_run_outcome",
        ),
        sa.PrimaryKeyConstraint("id", name="plugin_run_pkey"),
    )
    op.create_index("ix_plugin_run_clean", "plugin_run", ["plugin_id", "outcome"], unique=False)
    op.create_index("ix_plugin_run_plugin_id", "plugin_run", ["plugin_id"], unique=False)
    op.create_table(
        "plugin_state",
        sa.Column("plugin_id", sa.VARCHAR(length=32), autoincrement=False, nullable=False),
        sa.Column("key", sa.VARCHAR(length=128), autoincrement=False, nullable=False),
        sa.Column("value", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "updated_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("plugin_id", "key", name="plugin_state_pkey"),
    )
    op.create_table(
        "posting_inventory",
        sa.Column("id", sa.BIGINT(), autoincrement=True, nullable=False),
        sa.Column("dedupe_key", sa.VARCHAR(length=256), nullable=False),
        sa.Column("company", sa.VARCHAR(length=64), nullable=False),
        sa.Column("req_id", sa.VARCHAR(length=128), nullable=False),
        sa.Column("binding_id", sa.INTEGER(), nullable=True),
        sa.Column("title", sa.TEXT(), nullable=False),
        sa.Column("url", sa.TEXT(), nullable=False),
        sa.Column("department", sa.TEXT(), nullable=True),
        sa.Column("team", sa.TEXT(), nullable=True),
        sa.Column("raw_level", sa.TEXT(), nullable=True),
        sa.Column("locations", postgresql.ARRAY(sa.TEXT()), nullable=False),
        sa.Column("workplace_type", sa.VARCHAR(length=16), nullable=False),
        sa.Column("posted_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("level_band", sa.VARCHAR(length=32), nullable=False),
        sa.Column("level_confidence", sa.VARCHAR(length=16), nullable=False),
        sa.Column("family", sa.VARCHAR(length=64), nullable=True),
        sa.Column("track", sa.VARCHAR(length=32), nullable=False),
        sa.Column("location_groups", postgresql.ARRAY(sa.TEXT()), nullable=False),
        sa.Column("domains", postgresql.ARRAY(sa.TEXT()), nullable=True),
        sa.Column("content_hash", sa.VARCHAR(length=64), nullable=False),
        sa.Column("first_seen_at", postgresql.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("last_seen_at", postgresql.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("last_seen_run_id", sa.INTEGER(), nullable=True),
        sa.Column("gone_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("level_basis", sa.VARCHAR(length=16), nullable=True),
        sa.PrimaryKeyConstraint("id", name="posting_inventory_pkey"),
    )
    op.create_index(
        "ix_posting_inventory_company_gone",
        "posting_inventory",
        ["company", "gone_at"],
        unique=False,
    )
    op.create_index(
        "ix_posting_inventory_dedupe_key", "posting_inventory", ["dedupe_key"], unique=True
    )
    op.create_index(
        "ix_posting_inventory_live_role",
        "posting_inventory",
        ["family", "level_band", "track"],
        unique=False,
        postgresql_where="(gone_at IS NULL)",
    )
    op.create_index(
        "ix_posting_inventory_location_groups",
        "posting_inventory",
        ["location_groups"],
        unique=False,
        postgresql_using="gin",
    )
    op.create_table(
        "profile_claims",
        sa.Column("id", sa.INTEGER(), autoincrement=True, nullable=False),
        sa.Column("field", sa.VARCHAR(length=64), nullable=False),
        sa.Column("value", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("source", sa.VARCHAR(length=16), nullable=False),
        sa.Column("confidence", sa.DOUBLE_PRECISION(precision=53), nullable=False),
        sa.Column("evidence", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "created_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("superseded_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.CheckConstraint(
            "field IN ('identity','experience','skill')", name="ck_profile_claim_field"
        ),
        sa.CheckConstraint("source IN ('user','linkedin')", name="ck_profile_claim_source"),
        sa.PrimaryKeyConstraint("id", name="profile_claims_pkey"),
    )
    op.create_index("ix_profile_claims_field", "profile_claims", ["field"], unique=False)
    op.create_index(
        "ix_profile_claims_superseded_at", "profile_claims", ["superseded_at"], unique=False
    )
    op.create_table(
        "profile_suggestions",
        sa.Column("id", sa.INTEGER(), autoincrement=True, nullable=False),
        sa.Column("kind", sa.VARCHAR(length=32), nullable=False),
        sa.Column("dedupe_key", sa.VARCHAR(length=128), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("basis", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.VARCHAR(length=16), nullable=False),
        sa.Column(
            "created_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("resolved_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.CheckConstraint("kind IN ('world_on','world_off')", name="ck_profile_suggestion_kind"),
        sa.CheckConstraint(
            "status IN ('pending','accepted','dismissed')", name="ck_profile_suggestion_status"
        ),
        sa.PrimaryKeyConstraint("id", name="profile_suggestions_pkey"),
    )
    op.create_index(
        "ix_profile_suggestions_dedupe_key", "profile_suggestions", ["dedupe_key"], unique=True
    )
    op.create_index(
        "ix_profile_suggestions_status", "profile_suggestions", ["status"], unique=False
    )
    op.create_table(
        "provider_pressure_state",
        sa.Column("pressure_key", sa.VARCHAR(length=128), autoincrement=False, nullable=False),
        sa.Column("state", sa.VARCHAR(length=24), nullable=False),
        sa.Column("cooldown_until", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("last_started_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("last_finished_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("consecutive_pressure_events", sa.INTEGER(), nullable=False),
        sa.Column("last_outcome", sa.VARCHAR(length=24), nullable=True),
        sa.Column("evidence", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "updated_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("pressure_key", name="provider_pressure_state_pkey"),
    )
    op.create_index(
        "ix_provider_pressure_state_cooldown_until",
        "provider_pressure_state",
        ["cooldown_until"],
        unique=False,
    )
    op.create_index(
        "ix_provider_pressure_state_state", "provider_pressure_state", ["state"], unique=False
    )
    op.create_table(
        "pursuit_events",
        sa.Column("id", sa.BIGINT(), autoincrement=True, nullable=False),
        sa.Column("pursuit_id", sa.INTEGER(), nullable=False),
        sa.Column("actor", sa.VARCHAR(length=16), nullable=False),
        sa.Column("event_type", sa.VARCHAR(length=24), nullable=False),
        sa.Column("from_stage", sa.VARCHAR(length=24), nullable=True),
        sa.Column("to_stage", sa.VARCHAR(length=24), nullable=False),
        sa.Column(
            "detail",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pursuit_events_pkey"),
    )
    op.create_index("ix_pursuit_events_created_at", "pursuit_events", ["created_at"], unique=False)
    op.create_index("ix_pursuit_events_pursuit_id", "pursuit_events", ["pursuit_id"], unique=False)
    op.create_table(
        "pursuits",
        sa.Column("id", sa.INTEGER(), autoincrement=True, nullable=False),
        sa.Column("job_id", sa.INTEGER(), nullable=False),
        sa.Column(
            "stage",
            sa.VARCHAR(length=24),
            server_default=sa.text("'saved'::character varying"),
            nullable=False,
        ),
        sa.Column("priority", sa.INTEGER(), server_default=sa.text("3"), nullable=False),
        sa.Column("notes", sa.TEXT(), nullable=True),
        sa.Column("next_action", sa.TEXT(), nullable=True),
        sa.Column("next_action_due", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "stage IN ('saved','researching','networking','applied','interviewing','offer','rejected','withdrawn')",
            name="ck_pursuit_stage",
        ),
        sa.CheckConstraint("priority BETWEEN 1 AND 5", name="ck_pursuit_priority"),
        sa.PrimaryKeyConstraint("id", name="pursuits_pkey"),
    )
    op.create_index("ix_pursuits_job_id", "pursuits", ["job_id"], unique=True)
    op.create_index("ix_pursuits_next_action_due", "pursuits", ["next_action_due"], unique=False)
    op.create_index("ix_pursuits_stage", "pursuits", ["stage"], unique=False)
    op.create_index("ix_pursuits_updated_at", "pursuits", ["updated_at"], unique=False)
    op.create_table(
        "reference_change",
        sa.Column("id", sa.BIGINT(), autoincrement=True, nullable=False),
        sa.Column(
            "at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("from_fp", sa.VARCHAR(length=64), nullable=True),
        sa.Column("to_fp", sa.VARCHAR(length=64), nullable=False),
        sa.Column(
            "providers",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "moved_report",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="reference_change_pkey"),
    )
    op.create_index("ix_reference_change_at", "reference_change", ["at"], unique=False)
    op.create_table(
        "reference_state",
        sa.Column("id", sa.INTEGER(), autoincrement=True, nullable=False),
        sa.Column("applied_fp", sa.VARCHAR(length=64), nullable=True),
        sa.Column(
            "applied_providers",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("target_fp", sa.VARCHAR(length=64), nullable=True),
        sa.Column("cursor_job_id", sa.BIGINT(), nullable=True),
        sa.Column("last_change_id", sa.BIGINT(), nullable=True),
        sa.Column(
            "updated_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "target_providers",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "target_report",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.CheckConstraint("id = 1", name="ck_reference_state_singleton"),
        sa.PrimaryKeyConstraint("id", name="reference_state_pkey"),
    )
    op.create_table(
        "role_catalog",
        sa.Column("id", sa.INTEGER(), autoincrement=True, nullable=False),
        sa.Column("role_group", sa.VARCHAR(length=64), nullable=False),
        sa.Column("company", sa.VARCHAR(length=64), nullable=False),
        sa.Column("count", sa.INTEGER(), nullable=False),
        sa.Column("examples", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "updated_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "band_counts",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "band_track_counts",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "domain_counts",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "domain_examples",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "scope_cells",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="role_catalog_pkey"),
        sa.UniqueConstraint("role_group", "company", name="uq_role_company"),
    )
    op.create_index("ix_role_catalog_company", "role_catalog", ["company"], unique=False)
    op.create_index("ix_role_catalog_role_group", "role_catalog", ["role_group"], unique=False)
    op.create_table(
        "schedule_plan_runs",
        sa.Column("id", sa.INTEGER(), autoincrement=True, nullable=False),
        sa.Column("kind", sa.VARCHAR(length=8), nullable=False),
        sa.Column("started_at", postgresql.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("finished_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("companies", sa.INTEGER(), nullable=False),
        sa.Column("roster", sa.INTEGER(), nullable=False),
        sa.Column("outcome", sa.VARCHAR(length=12), nullable=True),
        sa.CheckConstraint(
            "kind IN ('full', 'quick', 'manual')", name="ck_schedule_plan_runs_kind"
        ),
        sa.PrimaryKeyConstraint("id", name="schedule_plan_runs_pkey"),
    )
    op.create_index(
        "ix_schedule_plan_runs_started_at", "schedule_plan_runs", ["started_at"], unique=False
    )
    op.create_table(
        "scrape_runs",
        sa.Column("id", sa.INTEGER(), autoincrement=True, nullable=False),
        sa.Column(
            "started_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("finished_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("status", sa.VARCHAR(length=16), nullable=False),
        sa.Column("jobs_seen", sa.INTEGER(), nullable=False),
        sa.Column("jobs_new", sa.INTEGER(), nullable=False),
        sa.Column("jobs_closed", sa.INTEGER(), nullable=False),
        sa.Column("per_source", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("drift_alerts", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("notes", sa.TEXT(), nullable=True),
        sa.Column("heartbeat_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column(
            "scope",
            sa.VARCHAR(length=16),
            server_default=sa.text("'full'::character varying"),
            nullable=False,
        ),
        sa.Column("code_version", sa.VARCHAR(length=64), nullable=True),
        sa.Column("process_group", sa.INTEGER(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="scrape_runs_pkey"),
    )
    op.create_index("ix_scrape_runs_scope_status", "scrape_runs", ["scope", "status"], unique=False)
    op.create_table(
        "scrape_source_runs",
        sa.Column("id", sa.BIGINT(), autoincrement=True, nullable=False),
        sa.Column("run_id", sa.INTEGER(), nullable=False),
        sa.Column("binding_id", sa.INTEGER(), nullable=False),
        sa.Column("company_slug", sa.VARCHAR(length=64), nullable=False),
        sa.Column("provider_key", sa.VARCHAR(length=128), nullable=False),
        sa.Column("scan_mode", sa.VARCHAR(length=16), nullable=False),
        sa.Column("outcome", sa.VARCHAR(length=24), nullable=False),
        sa.Column("started_at", postgresql.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("finished_at", postgresql.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("scanned", sa.INTEGER(), nullable=False),
        sa.Column("kept", sa.INTEGER(), nullable=False),
        sa.Column("jobs_new", sa.INTEGER(), nullable=False),
        sa.Column("jobs_closed", sa.INTEGER(), nullable=False),
        sa.Column("request_count", sa.INTEGER(), nullable=True),
        sa.Column("retry_count", sa.INTEGER(), nullable=True),
        sa.Column("bytes_received", sa.BIGINT(), nullable=True),
        sa.Column("list_complete", sa.BOOLEAN(), nullable=False),
        sa.Column("closure_eligible", sa.BOOLEAN(), nullable=False),
        sa.Column("errors", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("drift", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("stats", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.PrimaryKeyConstraint("id", name="scrape_source_runs_pkey"),
        sa.UniqueConstraint("run_id", "binding_id", name="uq_scrape_source_run_binding"),
    )
    op.create_index(
        "ix_scrape_source_runs_binding_finished",
        "scrape_source_runs",
        ["binding_id", "finished_at"],
        unique=False,
    )
    op.create_index(
        "ix_scrape_source_runs_binding_id", "scrape_source_runs", ["binding_id"], unique=False
    )
    op.create_index(
        "ix_scrape_source_runs_binding_started",
        "scrape_source_runs",
        ["binding_id", "started_at"],
        unique=False,
    )
    op.create_index(
        "ix_scrape_source_runs_company_slug", "scrape_source_runs", ["company_slug"], unique=False
    )
    op.create_index(
        "ix_scrape_source_runs_outcome", "scrape_source_runs", ["outcome"], unique=False
    )
    op.create_index(
        "ix_scrape_source_runs_provider_finished",
        "scrape_source_runs",
        ["provider_key", "finished_at"],
        unique=False,
    )
    op.create_index(
        "ix_scrape_source_runs_provider_key", "scrape_source_runs", ["provider_key"], unique=False
    )
    op.create_index("ix_scrape_source_runs_run_id", "scrape_source_runs", ["run_id"], unique=False)
    op.create_index(
        "ix_scrape_source_runs_scan_mode", "scrape_source_runs", ["scan_mode"], unique=False
    )
    op.create_table(
        "skill_aliases",
        sa.Column("id", sa.INTEGER(), autoincrement=True, nullable=False),
        sa.Column("concept_id", sa.INTEGER(), nullable=False),
        sa.Column("alias", sa.VARCHAR(length=96), nullable=False),
        sa.Column(
            "match_mode",
            sa.VARCHAR(length=16),
            server_default=sa.text("'exact_ci'::character varying"),
            nullable=False,
        ),
        sa.Column("required_context", sa.TEXT(), nullable=True),
        sa.Column("excluded_context", sa.TEXT(), nullable=True),
        sa.Column(
            "source",
            sa.VARCHAR(length=32),
            server_default=sa.text("'catalog'::character varying"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="skill_aliases_pkey"),
        sa.UniqueConstraint("concept_id", "alias", name="uq_skill_alias"),
    )
    op.create_index("ix_skill_aliases_concept_id", "skill_aliases", ["concept_id"], unique=False)
    op.create_table(
        "skill_candidates",
        sa.Column("id", sa.INTEGER(), autoincrement=True, nullable=False),
        sa.Column("label", sa.VARCHAR(length=96), nullable=False),
        sa.Column("proposed_facet", sa.VARCHAR(length=32), nullable=True),
        sa.Column("job_count", sa.INTEGER(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "requirement_context_count", sa.INTEGER(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column("sample_quotes", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("ambiguity_notes", sa.TEXT(), nullable=True),
        sa.Column("proposed_by", sa.VARCHAR(length=64), nullable=True),
        sa.Column(
            "verdict",
            sa.VARCHAR(length=16),
            server_default=sa.text("'open'::character varying"),
            nullable=False,
        ),
        sa.Column("verdict_reason", sa.TEXT(), nullable=True),
        sa.Column("concept_id", sa.INTEGER(), nullable=True),
        sa.Column(
            "created_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="skill_candidates_pkey"),
        sa.UniqueConstraint("label", name="uq_skill_candidate_label"),
    )
    op.create_table(
        "skill_concepts",
        sa.Column("id", sa.INTEGER(), autoincrement=True, nullable=False),
        sa.Column("slug", sa.VARCHAR(length=64), nullable=False),
        sa.Column("display", sa.VARCHAR(length=96), nullable=False),
        sa.Column("facet", sa.VARCHAR(length=32), nullable=False),
        sa.Column("category", sa.VARCHAR(length=32), nullable=False),
        sa.Column("parent_id", sa.INTEGER(), nullable=True),
        sa.Column("description", sa.TEXT(), nullable=False),
        sa.Column("external_refs", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "status",
            sa.VARCHAR(length=16),
            server_default=sa.text("'active'::character varying"),
            nullable=False,
        ),
        sa.Column("taxonomy_version", sa.VARCHAR(length=16), nullable=False),
        sa.Column(
            "updated_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="skill_concepts_pkey"),
    )
    op.create_index("ix_skill_concepts_facet", "skill_concepts", ["facet"], unique=False)
    op.create_index("ix_skill_concepts_slug", "skill_concepts", ["slug"], unique=True)
    op.create_table(
        "skill_demand_daily",
        sa.Column("id", sa.BIGINT(), autoincrement=True, nullable=False),
        sa.Column("metric_date", postgresql.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("company", sa.VARCHAR(length=64), nullable=False),
        sa.Column("family", sa.VARCHAR(length=64), nullable=True),
        sa.Column("concept_id", sa.INTEGER(), nullable=False),
        sa.Column("job_count", sa.INTEGER(), server_default=sa.text("0"), nullable=False),
        sa.PrimaryKeyConstraint("id", name="skill_demand_daily_pkey"),
        sa.UniqueConstraint(
            "metric_date", "company", "family", "concept_id", name="uq_skill_demand_slice"
        ),
    )
    op.create_index(
        "ix_skill_demand_daily_company", "skill_demand_daily", ["company"], unique=False
    )
    op.create_index(
        "ix_skill_demand_daily_concept_id", "skill_demand_daily", ["concept_id"], unique=False
    )
    op.create_index(
        "ix_skill_demand_daily_metric_date", "skill_demand_daily", ["metric_date"], unique=False
    )
    op.create_table(
        "skill_relations",
        sa.Column("id", sa.INTEGER(), autoincrement=True, nullable=False),
        sa.Column("from_id", sa.INTEGER(), nullable=False),
        sa.Column("to_id", sa.INTEGER(), nullable=False),
        sa.Column("kind", sa.VARCHAR(length=32), nullable=False),
        sa.Column("strength", sa.DOUBLE_PRECISION(precision=53), nullable=True),
        sa.Column(
            "source",
            sa.VARCHAR(length=32),
            server_default=sa.text("'catalog'::character varying"),
            nullable=False,
        ),
        sa.CheckConstraint("from_id <> to_id", name="ck_skill_relation_no_self"),
        sa.PrimaryKeyConstraint("id", name="skill_relations_pkey"),
        sa.UniqueConstraint("from_id", "to_id", "kind", name="uq_skill_relation"),
    )
    op.create_index("ix_skill_relations_from_id", "skill_relations", ["from_id"], unique=False)
    op.create_index("ix_skill_relations_to_id", "skill_relations", ["to_id"], unique=False)
    op.create_table(
        "source_binding_tuning",
        sa.Column("id", sa.INTEGER(), autoincrement=True, nullable=False),
        sa.Column("binding_id", sa.INTEGER(), nullable=False),
        sa.Column("query_key", sa.VARCHAR(length=120), nullable=False),
        sa.Column("page_samples", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("duration_samples", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("declared_total_last", sa.INTEGER(), nullable=True),
        sa.Column("saturated", sa.BOOLEAN(), nullable=False),
        sa.Column("stop_reason_hist", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("tuned_max_pages", sa.INTEGER(), nullable=True),
        sa.Column("tuned_budget_seconds", sa.DOUBLE_PRECISION(precision=53), nullable=True),
        sa.Column(
            "updated_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="source_binding_tuning_pkey"),
        sa.UniqueConstraint("binding_id", "query_key", name="uq_source_binding_tuning_query"),
    )
    op.create_index(
        "ix_source_binding_tuning_binding_id", "source_binding_tuning", ["binding_id"], unique=False
    )
    op.create_table(
        "source_bindings",
        sa.Column("id", sa.INTEGER(), autoincrement=True, nullable=False),
        sa.Column("company_slug", sa.VARCHAR(length=64), nullable=False),
        sa.Column("connector_kind", sa.VARCHAR(length=32), nullable=False),
        sa.Column("connector_id", sa.VARCHAR(length=128), nullable=False),
        sa.Column("recipe_revision_id", sa.INTEGER(), nullable=True),
        sa.Column(
            "status",
            sa.VARCHAR(length=16),
            server_default=sa.text("'proposed'::character varying"),
            nullable=False,
        ),
        sa.Column(
            "closure_capability",
            sa.VARCHAR(length=16),
            server_default=sa.text("'none'::character varying"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("activated_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("retired_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("notes", sa.TEXT(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="source_bindings_pkey"),
    )
    op.create_index(
        "ix_source_bindings_company_slug", "source_bindings", ["company_slug"], unique=False
    )
    op.create_index(
        "ix_source_bindings_company_status",
        "source_bindings",
        ["company_slug", "status"],
        unique=False,
    )
    op.create_index(
        "ix_source_bindings_one_active_per_company",
        "source_bindings",
        ["company_slug"],
        unique=True,
        postgresql_where="((status)::text = 'stable'::text)",
    )
    op.create_index("ix_source_bindings_status", "source_bindings", ["status"], unique=False)
    op.create_table(
        "sync_schedule_state",
        sa.Column("id", sa.INTEGER(), autoincrement=True, nullable=False),
        sa.Column("binding_id", sa.INTEGER(), nullable=False),
        sa.Column("provider_key", sa.VARCHAR(length=128), nullable=False),
        sa.Column("discovery_enabled", sa.BOOLEAN(), nullable=False),
        sa.Column("discovery_cadence_seconds", sa.INTEGER(), nullable=False),
        sa.Column("reconcile_cadence_seconds", sa.INTEGER(), nullable=False),
        sa.Column("last_discovery_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("last_reconcile_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("next_discovery_at", postgresql.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("next_reconcile_at", postgresql.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("manual_requested_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column(
            "manual_previous_reconcile_at", postgresql.TIMESTAMP(timezone=True), nullable=True
        ),
        sa.Column("last_outcome", sa.VARCHAR(length=24), nullable=True),
        sa.Column("last_new_count", sa.INTEGER(), nullable=False),
        sa.Column("consecutive_empty_discoveries", sa.INTEGER(), nullable=False),
        sa.Column(
            "updated_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("discovery_anchor_minute", sa.INTEGER(), nullable=True),
        sa.Column("reconcile_anchor_minute", sa.INTEGER(), nullable=True),
        sa.Column("schedule_timezone", sa.VARCHAR(length=64), nullable=True),
        sa.CheckConstraint(
            "discovery_anchor_minute IS NULL OR discovery_anchor_minute BETWEEN 0 AND 1439",
            name="ck_sync_schedule_discovery_anchor_minute",
        ),
        sa.CheckConstraint(
            "reconcile_anchor_minute IS NULL OR reconcile_anchor_minute BETWEEN 0 AND 1439",
            name="ck_sync_schedule_reconcile_anchor_minute",
        ),
        sa.PrimaryKeyConstraint("id", name="sync_schedule_state_pkey"),
    )
    op.create_index(
        "ix_sync_schedule_state_binding_id", "sync_schedule_state", ["binding_id"], unique=True
    )
    op.create_index(
        "ix_sync_schedule_state_next_discovery_at",
        "sync_schedule_state",
        ["next_discovery_at"],
        unique=False,
    )
    op.create_index(
        "ix_sync_schedule_state_next_reconcile_at",
        "sync_schedule_state",
        ["next_reconcile_at"],
        unique=False,
    )
    op.create_index(
        "ix_sync_schedule_state_provider_key", "sync_schedule_state", ["provider_key"], unique=False
    )
    op.create_table(
        "tracked_company",
        sa.Column("slug", sa.VARCHAR(length=64), autoincrement=False, nullable=False),
        sa.Column("display", sa.VARCHAR(length=128), nullable=False),
        sa.Column("adapter", sa.VARCHAR(length=32), nullable=True),
        sa.Column("board_token", sa.VARCHAR(length=128), nullable=True),
        sa.Column("careers_url", sa.VARCHAR(length=512), nullable=True),
        sa.Column(
            "status",
            sa.VARCHAR(length=16),
            server_default=sa.text("'active'::character varying"),
            nullable=False,
        ),
        sa.Column("enabled", sa.BOOLEAN(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "source",
            sa.VARCHAR(length=16),
            server_default=sa.text("'catalog'::character varying"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("visible", sa.BOOLEAN(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "role_catalog_status",
            sa.VARCHAR(length=16),
            server_default=sa.text("'pending'::character varying"),
            nullable=False,
        ),
        sa.Column("role_catalog_scanned_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("role_catalog_error", sa.TEXT(), nullable=True),
        sa.Column("board_region", sa.VARCHAR(length=16), nullable=True),
        sa.Column("consented_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("consent_text", sa.TEXT(), nullable=True),
        sa.Column("consent_fingerprint", sa.VARCHAR(length=128), nullable=True),
        sa.Column("role_catalog_places", postgresql.ARRAY(sa.VARCHAR()), nullable=True),
        sa.Column("role_catalog_unplaced", sa.INTEGER(), nullable=True),
        sa.Column("role_catalog_unsorted", sa.INTEGER(), nullable=True),
        sa.Column("consent_locale", sa.VARCHAR(length=35), nullable=True),
        sa.PrimaryKeyConstraint("slug", name="tracked_company_pkey"),
    )
    op.create_table(
        "usage_events",
        sa.Column("id", sa.BIGINT(), autoincrement=True, nullable=False),
        sa.Column("dedupe_key", sa.VARCHAR(length=160), nullable=False),
        sa.Column("kind", sa.VARCHAR(length=16), nullable=False),
        sa.Column("name", sa.VARCHAR(length=64), nullable=False),
        sa.Column("consent_group", sa.VARCHAR(length=16), nullable=False),
        sa.Column("props", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("day", sa.DATE(), nullable=True),
        sa.Column("count", sa.INTEGER(), nullable=False),
        sa.Column("first_at", postgresql.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("last_at", postgresql.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("attempted_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("sent_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("rejected_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("withdrawn_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name="usage_events_pkey"),
    )
    op.create_index("ix_usage_events_dedupe_key", "usage_events", ["dedupe_key"], unique=True)
    op.create_index("ix_usage_events_sent_at", "usage_events", ["sent_at"], unique=False)
    # Foreign keys follow all tables because jobs and job_lineage reference each other.
    op.create_foreign_key(
        "job_lifecycle_events_job_id_fkey",
        "job_lifecycle_events",
        "jobs",
        ["job_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "job_lifecycle_events_run_id_fkey",
        "job_lifecycle_events",
        "scrape_runs",
        ["run_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_jobs_lineage_id", "jobs", "job_lineage", ["lineage_id"], ["id"], ondelete="SET NULL"
    )
    op.create_foreign_key(
        "fk_jobs_closure_run_id_scrape_runs",
        "jobs",
        "scrape_runs",
        ["closure_run_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_jobs_cluster_id", "jobs", "clusters", ["cluster_id"], ["id"], ondelete="SET NULL"
    )
    op.create_foreign_key(
        "job_lineage_root_job_id_fkey",
        "job_lineage",
        "jobs",
        ["root_job_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "favorites_job_id_fkey", "favorites", "jobs", ["job_id"], ["id"], ondelete="CASCADE"
    )
    op.create_foreign_key(
        "notifications_run_id_fkey",
        "notifications",
        "scrape_runs",
        ["run_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "notifications_job_id_fkey", "notifications", "jobs", ["job_id"], ["id"], ondelete="CASCADE"
    )
    op.create_foreign_key(
        "job_similarity_job_id_fkey",
        "job_similarity",
        "jobs",
        ["job_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "job_similarity_neighbor_job_id_fkey",
        "job_similarity",
        "jobs",
        ["neighbor_job_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "company_fact_company_slug_fkey",
        "company_fact",
        "company_profile",
        ["company_slug"],
        ["slug"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "company_price_company_slug_fkey",
        "company_price",
        "company_profile",
        ["company_slug"],
        ["slug"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "company_price_history_company_slug_fkey",
        "company_price_history",
        "company_profile",
        ["company_slug"],
        ["slug"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "job_lineage_link_prior_job_id_fkey",
        "job_lineage_link",
        "jobs",
        ["prior_job_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "job_lineage_link_job_id_fkey",
        "job_lineage_link",
        "jobs",
        ["job_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "job_twin_link_job_a_id_fkey",
        "job_twin_link",
        "jobs",
        ["job_a_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "job_twin_link_job_b_id_fkey",
        "job_twin_link",
        "jobs",
        ["job_b_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "pursuits_job_id_fkey", "pursuits", "jobs", ["job_id"], ["id"], ondelete="CASCADE"
    )
    op.create_foreign_key(
        "pursuit_events_pursuit_id_fkey",
        "pursuit_events",
        "pursuits",
        ["pursuit_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "skill_concepts_parent_id_fkey",
        "skill_concepts",
        "skill_concepts",
        ["parent_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "skill_aliases_concept_id_fkey",
        "skill_aliases",
        "skill_concepts",
        ["concept_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "skill_relations_from_id_fkey",
        "skill_relations",
        "skill_concepts",
        ["from_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "skill_relations_to_id_fkey",
        "skill_relations",
        "skill_concepts",
        ["to_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "job_skills_concept_id_fkey",
        "job_skills",
        "skill_concepts",
        ["concept_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "job_skills_job_id_fkey", "job_skills", "jobs", ["job_id"], ["id"], ondelete="CASCADE"
    )
    op.create_foreign_key(
        "job_skill_evidence_job_id_fkey",
        "job_skill_evidence",
        "jobs",
        ["job_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "job_skill_evidence_job_skill_id_fkey",
        "job_skill_evidence",
        "job_skills",
        ["job_skill_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "job_skill_evidence_concept_id_fkey",
        "job_skill_evidence",
        "skill_concepts",
        ["concept_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "job_qualifications_job_id_fkey",
        "job_qualifications",
        "jobs",
        ["job_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "skill_candidates_concept_id_fkey",
        "skill_candidates",
        "skill_concepts",
        ["concept_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "skill_demand_daily_concept_id_fkey",
        "skill_demand_daily",
        "skill_concepts",
        ["concept_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "source_bindings_company_slug_fkey",
        "source_bindings",
        "tracked_company",
        ["company_slug"],
        ["slug"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "job_source_identities_job_id_fkey",
        "job_source_identities",
        "jobs",
        ["job_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "job_source_identities_binding_id_fkey",
        "job_source_identities",
        "source_bindings",
        ["binding_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "binding_reconciliation_decisions_job_id_fkey",
        "binding_reconciliation_decisions",
        "jobs",
        ["job_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "binding_reconciliation_decisions_binding_id_fkey",
        "binding_reconciliation_decisions",
        "source_bindings",
        ["binding_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_job_observations_binding",
        "job_observations",
        "source_bindings",
        ["binding_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_job_observations_identity",
        "job_observations",
        "job_source_identities",
        ["source_identity_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "job_observations_job_id_fkey",
        "job_observations",
        "jobs",
        ["job_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "job_observations_run_id_fkey",
        "job_observations",
        "scrape_runs",
        ["run_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "connector_recipe_revisions_recipe_id_fkey",
        "connector_recipe_revisions",
        "connector_recipes",
        ["recipe_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "ai_task_log_job_id_fkey", "ai_task_log", "jobs", ["job_id"], ["id"], ondelete="SET NULL"
    )
    op.create_foreign_key(
        "source_binding_tuning_binding_id_fkey",
        "source_binding_tuning",
        "source_bindings",
        ["binding_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "scrape_source_runs_binding_id_fkey",
        "scrape_source_runs",
        "source_bindings",
        ["binding_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "scrape_source_runs_run_id_fkey",
        "scrape_source_runs",
        "scrape_runs",
        ["run_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "sync_schedule_state_binding_id_fkey",
        "sync_schedule_state",
        "source_bindings",
        ["binding_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "job_feedback_job_id_fkey", "job_feedback", "jobs", ["job_id"], ["id"], ondelete="CASCADE"
    )
    op.create_foreign_key(
        "job_relevance_reviews_job_id_fkey",
        "job_relevance_reviews",
        "jobs",
        ["job_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "compare_selection_job_id_fkey",
        "compare_selection",
        "jobs",
        ["job_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "posting_inventory_binding_id_fkey",
        "posting_inventory",
        "source_bindings",
        ["binding_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "posting_inventory_last_seen_run_id_fkey",
        "posting_inventory",
        "scrape_runs",
        ["last_seen_run_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "job_place_set_member_set_id_fkey",
        "job_place_set_member",
        "job_place_set",
        ["set_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "job_place_set_member_job_id_fkey",
        "job_place_set_member",
        "jobs",
        ["job_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "company_benefit_company_slug_fkey",
        "company_benefit",
        "company_profile",
        ["company_slug"],
        ["slug"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "plugin_state_plugin_id_fkey",
        "plugin_state",
        "plugin_install",
        ["plugin_id"],
        ["plugin_id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "plugin_run_plugin_id_fkey",
        "plugin_run",
        "plugin_install",
        ["plugin_id"],
        ["plugin_id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "job_comp_estimate_job_id_fkey",
        "job_comp_estimate",
        "jobs",
        ["job_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "company_comp_level_company_slug_fkey",
        "company_comp_level",
        "company_profile",
        ["company_slug"],
        ["slug"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "plugin_report_plugin_id_fkey",
        "plugin_report",
        "plugin_install",
        ["plugin_id"],
        ["plugin_id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    raise RuntimeError(
        "The schema baseline cannot be downgraded; restore a database backup instead."
    )
