"""A pay rung is unique per country.

`uq_company_comp_level` gains `country`, NULLS NOT DISTINCT: the same label
stated for two countries is two rows, and a rung with no country stays unique
as before. Rows already stored are unique under the old key, so they are
unique under the new one.
"""

from alembic import op

revision = "b8e5d3f0c2a4"
down_revision = "a7d4c2e9b1f3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("uq_company_comp_level", "company_comp_level", type_="unique")
    op.create_unique_constraint(
        "uq_company_comp_level",
        "company_comp_level",
        ["provider", "company_slug", "family", "level_label", "country"],
        postgresql_nulls_not_distinct=True,
    )


def downgrade() -> None:
    # Fails while one label is stored for two countries: neither row is
    # deleted to make room for the narrower key.
    op.drop_constraint("uq_company_comp_level", "company_comp_level", type_="unique")
    op.create_unique_constraint(
        "uq_company_comp_level", "company_comp_level", ["provider", "company_slug", "family", "level_label"]
    )
