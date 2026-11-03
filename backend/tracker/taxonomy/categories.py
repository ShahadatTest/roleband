"""Presentation-only grouping for canonical role groups."""

from __future__ import annotations

from dataclasses import dataclass

from tracker.taxonomy.roles import ROLE_GROUPS


@dataclass(frozen=True)
class RoleCategory:
    slug: str
    display: str
    role_groups: tuple[str, ...]


CATEGORY_GROUPS: tuple[RoleCategory, ...] = (
    RoleCategory(
        "technology",
        "Technology",
        (
            "engineering_management",
            "software_engineering",
            "infrastructure_sre",
            "security_engineering",
            "hardware_engineering",
        ),
    ),
    RoleCategory(
        "ai_data",
        "AI & Data",
        ("ml_ai_research", "data_science", "data_engineering"),
    ),
    RoleCategory(
        "product",
        "Product",
        (
            "product_management",
            "technical_program_management",
            "program_management",
            "design_ux",
        ),
    ),
    RoleCategory(
        "developer_customer",
        "Developer & Customer",
        ("developer_relations", "solutions_sales_eng", "technical_writing"),
    ),
    RoleCategory(
        "business_revenue",
        "Business & Revenue",
        ("sales_business_development", "customer_success", "marketing_communications"),
    ),
    RoleCategory(
        "operations",
        "Operations & Finance",
        ("business_operations_strategy", "finance_accounting", "it_support", "operations_facilities"),
    ),
    RoleCategory(
        "people_governance",
        "People & Governance",
        ("people_recruiting", "legal_policy"),
    ),
)

_CATEGORY_BY_SLUG = {category.slug: category for category in CATEGORY_GROUPS}
_ROLE_TO_CATEGORY = {
    role_slug: category.slug
    for category in CATEGORY_GROUPS
    for role_slug in category.role_groups
}

_known_roles = {group.slug for group in ROLE_GROUPS}
_listed_roles = [role for category in CATEGORY_GROUPS for role in category.role_groups]
if len(_listed_roles) != len(set(_listed_roles)):
    raise ValueError("CATEGORY_GROUPS contains duplicate role-group slugs")
if set(_listed_roles) != _known_roles:
    missing = sorted(_known_roles - set(_listed_roles))
    unknown = sorted(set(_listed_roles) - _known_roles)
    raise ValueError(f"CATEGORY_GROUPS mismatch: missing={missing}, unknown={unknown}")


def role_group_category(role_slug: str) -> str | None:
    return _ROLE_TO_CATEGORY.get(role_slug)


def category_role_groups(category_slug: str) -> tuple[str, ...]:
    category = _CATEGORY_BY_SLUG.get(category_slug)
    return category.role_groups if category else ()
