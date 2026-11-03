"""`posting_inventory` keeps free space on each page for a scan's updates.

A scan that sees a stored role again refreshes only `last_seen_at` and
`last_seen_run_id`. Neither is indexed, so with room on the row's page Postgres
updates it in place (a HOT update) and leaves the table's five indexes alone;
on a full page it writes a new row version elsewhere and an entry in every
index. Existing pages gain the room as they are rewritten: nothing is rewritten
or locked for long here.
"""

from alembic import op

revision = "544950844911"
down_revision = "b8e2d4f6a1c3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE posting_inventory SET (fillfactor = 85)")


def downgrade() -> None:
    op.execute("ALTER TABLE posting_inventory RESET (fillfactor)")
