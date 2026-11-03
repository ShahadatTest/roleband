"""A plugin benefit keeps the country it applies in.

`company_benefit` gains `country` (ISO 3166-1 alpha-2, NULL when the source
does not say), and `uq_company_benefit` gains it, NULLS NOT DISTINCT: the same
perk stated for two countries is two rows, and a perk with no country stays
unique as before. Rows already stored hold no country, so they are unique
under the new key.
"""

import sqlalchemy as sa
from alembic import op

revision = "e4b7c1d9a2f6"
down_revision = "d1f6a8b4e7c2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("company_benefit", sa.Column("country", sa.String(2), nullable=True))
    op.drop_constraint("uq_company_benefit", "company_benefit", type_="unique")
    op.create_unique_constraint(
        "uq_company_benefit",
        "company_benefit",
        ["provider", "company_slug", "name", "country"],
        postgresql_nulls_not_distinct=True,
    )


def downgrade() -> None:
    # Fails while one perk is stored for two countries: neither row is deleted
    # to make room for the narrower key.
    op.drop_constraint("uq_company_benefit", "company_benefit", type_="unique")
    op.create_unique_constraint("uq_company_benefit", "company_benefit", ["provider", "company_slug", "name"])
    op.drop_column("company_benefit", "country")
