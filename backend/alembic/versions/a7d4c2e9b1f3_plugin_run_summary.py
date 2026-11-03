"""A plugin run keeps the plugin's own summary of what it did.

`plugin_run.summary`: the latest `ctx.summary`, nullable. Additive:
code that does not know the column reads and writes the table as before.
"""

import sqlalchemy as sa

from alembic import op

revision = "a7d4c2e9b1f3"
down_revision = "c5e1a9d3f7b2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("plugin_run", sa.Column("summary", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("plugin_run", "summary")
