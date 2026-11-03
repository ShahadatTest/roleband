"""A pay rung carries the currency its figures are in.

`company_comp_level` gains `currency`, and the amount columns lose the `_usd`
in their names: a rung is stored in the currency its publisher stated and
nothing converts it, so a column called `base_usd` holding euros would be a
lie the next reader believes. Every stored row is USD, because the writer
refused anything else, so the default backfills them correctly and no figure
moves.
"""

import sqlalchemy as sa
from alembic import op

revision = "d1f6a8b4e7c2"
down_revision = "b8e5d3f0c2a4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "company_comp_level",
        sa.Column("currency", sa.String(length=3), nullable=False, server_default="USD"),
    )
    op.alter_column("company_comp_level", "base_usd", new_column_name="base_amount")
    op.alter_column("company_comp_level", "stock_usd", new_column_name="stock_amount")
    op.alter_column("company_comp_level", "bonus_usd", new_column_name="bonus_amount")


def downgrade() -> None:
    # Refuses while a row states anything but USD: the old columns say USD in
    # their names and no figure is converted to make them true.
    rows = op.get_bind().execute(
        sa.text("SELECT count(*) FROM company_comp_level WHERE currency <> 'USD'")
    ).scalar()
    if rows:
        raise RuntimeError(f"{rows} rungs are not in USD; the narrower columns cannot hold them")
    op.alter_column("company_comp_level", "base_amount", new_column_name="base_usd")
    op.alter_column("company_comp_level", "stock_amount", new_column_name="stock_usd")
    op.alter_column("company_comp_level", "bonus_amount", new_column_name="bonus_usd")
    op.drop_column("company_comp_level", "currency")
