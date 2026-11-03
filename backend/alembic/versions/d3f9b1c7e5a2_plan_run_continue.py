"""A schedule plan run can be the continuation of a full read.

A full read that a quit, a crash or an update stopped is continued with the
companies it has not read, not started over. The continuation is its own
`kind`, so it never counts as a full read's start.
"""

from alembic import op
from sqlalchemy import text

revision = "d3f9b1c7e5a2"
down_revision = "544950844911"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("ck_schedule_plan_runs_kind", "schedule_plan_runs", type_="check")
    op.create_check_constraint(
        "ck_schedule_plan_runs_kind", "schedule_plan_runs", "kind IN ('full', 'quick', 'manual', 'continue')"
    )


def downgrade() -> None:
    held = op.get_bind().execute(
        text("SELECT count(*) FROM schedule_plan_runs WHERE kind = 'continue'")
    ).scalar_one()
    if held:
        raise RuntimeError(
            f"{held} schedule plan runs are continuations, which the older schema cannot hold; "
            "they are left in place"
        )
    op.drop_constraint("ck_schedule_plan_runs_kind", "schedule_plan_runs", type_="check")
    op.create_check_constraint(
        "ck_schedule_plan_runs_kind", "schedule_plan_runs", "kind IN ('full', 'quick', 'manual')"
    )
