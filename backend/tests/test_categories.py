"""Position categories are presentation-only; department rules refine titles."""

from tracker.enrich.classify import classify_family
from tracker.schema import RawJob
from tracker.taxonomy.categories import CATEGORY_GROUPS, category_role_groups, role_group_category
from tracker.taxonomy.roles import ROLE_GROUPS


def _job(title: str, department: str | None = None, team: str | None = None) -> RawJob:
    return RawJob(
        company="example",
        req_id="1",
        title=title,
        url="https://example.test/job/1",
        department=department,
        team=team,
    )


def test_department_refines_generic_or_unknown_title():
    assert classify_family(_job("SDE", department="Applied Science")) == "ml_ai_research"
    assert (
        classify_family(_job("Software Engineer", team="Data Infrastructure"))
        == "data_engineering"
    )


def test_specific_title_wins_over_department():
    assert (
        classify_family(_job("Engineering Manager", department="Artificial Intelligence"))
        == "engineering_management"
    )


def test_plain_generic_title_stays_software_engineering():
    assert classify_family(_job("Software Engineer", department="Consumer Products")) == "software_engineering"


def test_specialized_and_business_positions_are_explicit_families():
    assert classify_family(_job("Enterprise Account Executive")) == "sales_business_development"
    assert classify_family(_job("Product Marketing Manager")) == "marketing_communications"
    assert classify_family(_job("Solutions Engineer, Enterprise")) == "solutions_sales_eng"


def test_broad_department_tokens_do_not_trigger_domain_refinement():
    assert classify_family(_job("SDE", department="Research")) is None
    assert classify_family(_job("Software Engineer", department="Data Products")) == "software_engineering"


def test_every_role_group_belongs_to_exactly_one_category():
    listed = [slug for category in CATEGORY_GROUPS for slug in category.role_groups]
    assert sorted(listed) == sorted(group.slug for group in ROLE_GROUPS)
    assert len(listed) == len(set(listed))
    assert role_group_category("ml_ai_research") == "ai_data"
    assert category_role_groups("operations") == (
        "business_operations_strategy",
        "finance_accounting",
        "it_support",
        "operations_facilities",
    )
