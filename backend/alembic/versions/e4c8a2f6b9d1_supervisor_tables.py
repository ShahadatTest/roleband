"""The supervisor's tables and the price request ledger.

`job_requests` (durable run-now requests), `job_runs` (one row per supervised
process), `job_status` (what each job is doing now) and `price_feed_requests`
(every request to the price provider, reserved before it is sent). Additive:
four new tables, nothing existing changes, so code that does not know them reads
and writes as before.
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "e4c8a2f6b9d1"
down_revision = "a9c3e7b1d5f2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "job_requests",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("job", sa.String(length=32), nullable=False),
        sa.Column("key", sa.String(length=96), nullable=False),
        sa.Column(
            "args", postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"), nullable=False,
        ),
        sa.Column("coalesce_key", sa.String(length=160), nullable=False),
        sa.Column("requested_by", sa.String(length=32), nullable=False),
        sa.Column(
            "requested_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("state", sa.String(length=16), server_default="queued", nullable=False),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempts", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "state IN ('queued', 'claimed', 'done', 'cancelled', 'failed')",
            name="ck_job_requests_state",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_job_requests_key_state", "job_requests", ["key", "state"])
    op.create_index(
        "uq_job_requests_queued", "job_requests", ["coalesce_key"],
        unique=True, postgresql_where=sa.text("state = 'queued'"),
    )

    op.create_table(
        "job_runs",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("job", sa.String(length=32), nullable=False),
        sa.Column("key", sa.String(length=96), nullable=False),
        sa.Column("trigger", sa.String(length=16), nullable=False),
        sa.Column("request_id", sa.BigInteger(), nullable=True),
        sa.Column("state", sa.String(length=16), server_default="starting", nullable=False),
        sa.Column(
            "started_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("exit_code", sa.Integer(), nullable=True),
        sa.Column("pid", sa.Integer(), nullable=True),
        sa.Column("pgid", sa.Integer(), nullable=True),
        sa.Column("proc_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("code_version", sa.String(length=64), nullable=True),
        sa.Column("cancel_requested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancel_reason", sa.String(length=32), nullable=True),
        sa.Column("log_path", sa.Text(), nullable=True),
        sa.Column("log_offset", sa.BigInteger(), nullable=True),
        sa.Column("log_rotated", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column(
            "progress", postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"), nullable=False,
        ),
        sa.Column("result", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.CheckConstraint(
            "state IN ('starting', 'running', 'exited', 'timed_out', 'cancelled', 'lost', 'spawn_failed')",
            name="ck_job_runs_state",
        ),
        sa.ForeignKeyConstraint(["request_id"], ["job_requests.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_job_runs_request_id", "job_runs", ["request_id"])
    op.create_index("ix_job_runs_key_started", "job_runs", ["key", "started_at"])
    op.create_index(
        "uq_job_runs_live", "job_runs", ["key"],
        unique=True, postgresql_where=sa.text("state IN ('starting', 'running')"),
    )

    op.create_table(
        "job_status",
        sa.Column("key", sa.String(length=96), nullable=False),
        sa.Column("job", sa.String(length=32), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("reason", sa.String(length=32), nullable=True),
        sa.Column("since", sa.DateTime(timezone=True), nullable=False),
        sa.Column("next_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("run_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "detail", postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"), nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.PrimaryKeyConstraint("key"),
    )

    op.create_table(
        "price_feed_requests",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("provider", sa.String(length=16), nullable=False),
        sa.Column("key_fingerprint", sa.String(length=16), nullable=False),
        sa.Column("purpose", sa.String(length=16), nullable=False),
        sa.Column("symbol", sa.String(length=16), nullable=False),
        sa.Column(
            "requested_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("outcome", sa.String(length=16), server_default="pending", nullable=False),
        sa.Column("http_status", sa.Integer(), nullable=True),
        sa.Column("bytes", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_price_feed_requests_requested_at", "price_feed_requests", ["requested_at"])


def downgrade() -> None:
    op.drop_index("ix_price_feed_requests_requested_at", table_name="price_feed_requests")
    op.drop_table("price_feed_requests")
    op.drop_table("job_status")
    op.drop_index("uq_job_runs_live", table_name="job_runs")
    op.drop_index("ix_job_runs_key_started", table_name="job_runs")
    op.drop_index("ix_job_runs_request_id", table_name="job_runs")
    op.drop_table("job_runs")
    op.drop_index("uq_job_requests_queued", table_name="job_requests")
    op.drop_index("ix_job_requests_key_state", table_name="job_requests")
    op.drop_table("job_requests")
