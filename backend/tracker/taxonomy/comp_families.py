"""Which ladder a role group's pay is measured in, and the order to borrow in.

Pay rows are keyed by OUR taxonomy family (`software_engineering`,
`product_management`), the same vocabulary as `jobs.family`, so the "measured
split" tier of the comp package (the company's own base/bonus/equity for THIS
family at THIS level) is a plain key match. A plugin publishes taxonomy
families, so no source's own family vocabulary lives in the core.

A family with no row of its own at a band borrows another family's row at
that band, and says so (`cross_family`). The order is fixed here rather than
read from whichever rows exist, so a borrowed figure never depends on row or
dict order.
"""

from __future__ import annotations

# The ladder every company publishes, and the one the company profile, the
# observed splits and the scope decoder read. It is also the first family a
# job without its own row borrows from.
REFERENCE_FAMILY = "software_engineering"

#: The borrow order after the reference family. Fixed, so which family a split
#: is borrowed from never depends on which rows exist. A family not listed
#: borrows after every listed one, by name.
BORROW_ORDER: tuple[str, ...] = (
    REFERENCE_FAMILY,
    "business_operations_strategy",
    "sales_business_development",
    "data_engineering",
    "data_science",
    "finance_accounting",
    "hardware_engineering",
    "people_recruiting",
    "it_support",
    "legal_policy",
    "marketing_communications",
    "design_ux",
    "product_management",
    "program_management",
    "security_engineering",
    "engineering_management",
    "solutions_sales_eng",
    "technical_program_management",
    "technical_writing",
)


def borrow_rank(family: str) -> tuple[int, str]:
    """Sort key: the reference family first, then `BORROW_ORDER`, then by name."""
    try:
        return BORROW_ORDER.index(family), family
    except ValueError:
        return len(BORROW_ORDER), family
