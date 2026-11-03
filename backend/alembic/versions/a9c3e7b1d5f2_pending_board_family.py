"""A pending company keeps the board family its careers page named.

`tracked_company` gains `detected_family` and `pending_reason`, both NULL for
every stored row: a URL company left pending before this was recorded names
no family, as an unrecognised page does.
"""

import sqlalchemy as sa
from alembic import op

revision = "a9c3e7b1d5f2"
down_revision = "f2a8d6c3b5e1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("tracked_company", sa.Column("detected_family", sa.String(64), nullable=True))
    op.add_column("tracked_company", sa.Column("pending_reason", sa.String(24), nullable=True))


def downgrade() -> None:
    op.drop_column("tracked_company", "pending_reason")
    op.drop_column("tracked_company", "detected_family")
