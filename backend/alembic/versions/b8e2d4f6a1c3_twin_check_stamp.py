"""Each posting records when the twin pass last checked it, and what it read.

Three nullable columns on `jobs`, as the lineage pass has. Every stored row
starts unchecked, so the pass reads the corpus once, a capped number per run.
"""

import sqlalchemy as sa
from alembic import op

revision = "b8e2d4f6a1c3"
down_revision = "e4c8a2f6b9d1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("twin_checked_at", sa.TIMESTAMP(timezone=True), nullable=True))
    op.add_column("jobs", sa.Column("twin_detector_version", sa.String(32), nullable=True))
    op.add_column("jobs", sa.Column("twin_input_key", sa.String(32), nullable=True))


def downgrade() -> None:
    op.drop_column("jobs", "twin_input_key")
    op.drop_column("jobs", "twin_detector_version")
    op.drop_column("jobs", "twin_checked_at")
