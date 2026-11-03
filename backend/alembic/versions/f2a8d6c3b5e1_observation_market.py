"""A reported pay submission keeps its market and its unknown components.

`external_comp_observation` amounts lose the `_usd` suffix and become
nullable: a component the submission does not state is NULL, never zero. The
table gains `currency` (stored rows were whole USD, so they read `USD`),
`country` (NULL: unknown, which no US comparison reads) and `family`.
"""

import sqlalchemy as sa
from alembic import op

revision = "f2a8d6c3b5e1"
down_revision = "e4b7c1d9a2f6"
branch_labels = None
depends_on = None

_AMOUNTS = ("total", "base", "equity", "bonus")


def upgrade() -> None:
    for name in _AMOUNTS:
        op.alter_column("external_comp_observation", f"{name}_usd", new_column_name=f"{name}_amount", nullable=True)
    op.add_column("external_comp_observation", sa.Column("currency", sa.String(3), nullable=False, server_default="USD"))
    op.alter_column("external_comp_observation", "currency", server_default=None)
    op.add_column("external_comp_observation", sa.Column("country", sa.String(2), nullable=True))
    op.add_column("external_comp_observation", sa.Column("family", sa.String(48), nullable=True))


def downgrade() -> None:
    # Refuses while a stored row holds a NULL amount or a currency other than
    # USD: the old columns say USD in their names and hold every component, and
    # no figure is converted or invented to make them true.
    rows = op.get_bind().execute(
        sa.text(
            "SELECT count(*) FROM external_comp_observation WHERE currency <> 'USD'"
            " OR total_amount IS NULL OR base_amount IS NULL"
            " OR equity_amount IS NULL OR bonus_amount IS NULL"
        )
    ).scalar()
    if rows:
        raise RuntimeError(
            f"{rows} reported pay rows are not whole USD; the narrower columns cannot hold them"
        )
    op.drop_column("external_comp_observation", "family")
    op.drop_column("external_comp_observation", "country")
    op.drop_column("external_comp_observation", "currency")
    for name in _AMOUNTS:
        op.alter_column("external_comp_observation", f"{name}_amount", new_column_name=f"{name}_usd", nullable=False)
