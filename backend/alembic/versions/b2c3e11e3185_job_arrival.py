"""A role records how it arrived, so a first read of a company is not news.

`jobs.arrival` says whether our first sighting of a posting dates its
appearance: `new` when the company was already read in full and the posting
was not on it, `already_listed` when the posting was on the board before we
stored it, `first_read` when it came from the first full read of a company.
NULL is a role not yet classified; `db/arrival.py` fills it, and the app's
update runs that over the existing roles after this migration.

The partial index serves the listed age of open roles, which the header's
New count and the New view range over on every request.
"""

import sqlalchemy as sa

from alembic import op

revision = "b2c3e11e3185"
down_revision = "d3f9b1c7e5a2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("arrival", sa.String(length=16), nullable=True))
    op.create_check_constraint(
        "ck_jobs_arrival", "jobs", "arrival IN ('new', 'already_listed', 'first_read')"
    )
    op.create_index(
        "ix_jobs_open_listed_since",
        "jobs",
        [sa.text("least(first_posted_at, first_seen)")],
        postgresql_where=sa.text("status = 'open'"),
    )


def downgrade() -> None:
    op.drop_index("ix_jobs_open_listed_since", table_name="jobs")
    op.drop_constraint("ck_jobs_arrival", "jobs", type_="check")
    op.drop_column("jobs", "arrival")
