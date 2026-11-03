"""Role-track classification across management, product/program, technical, and business.

The load-bearing rule: the track is derived from leadership words in the title, NOT
from seniority — so Distinguished Engineer / Fellow / (Chief) Architect stay technical
even at a director+ band, while a Director in any domain is management.
"""

from tracker.db.models import Job
from tracker.enrich.track import classify_track
from tracker.schema import RoleTrack
from tracker.taxonomy.tracks import all_track_slugs


def test_engineering_management_family_is_management():
    assert classify_track("Engineering Manager", "engineering_management") == RoleTrack.MANAGEMENT


def test_pm_and_tpm_families_are_product_program():
    assert classify_track("Product Manager, Core", "product_management") == RoleTrack.PRODUCT_PROGRAM
    assert classify_track("Technical Program Manager", "program_management") == RoleTrack.PRODUCT_PROGRAM
    assert (
        classify_track("Technical Program Manager", "technical_program_management")
        == RoleTrack.PRODUCT_PROGRAM
    )


def test_cross_domain_manager_is_management_not_the_domain():
    # The whole point: a manager hiding inside a technical family.
    assert classify_track("Director of Data Science", "data_science") == RoleTrack.MANAGEMENT
    assert classify_track("Machine Learning Manager", "ml_ai_research") == RoleTrack.MANAGEMENT
    assert classify_track("Head of Security", "security_engineering") == RoleTrack.MANAGEMENT


def test_senior_ic_titles_stay_technical_despite_high_band():
    assert classify_track("Distinguished Engineer", "software_engineering") == RoleTrack.TECHNICAL
    assert classify_track("Engineering Fellow", "software_engineering") == RoleTrack.TECHNICAL
    assert classify_track("Principal ML Scientist", "ml_ai_research") == RoleTrack.TECHNICAL
    assert classify_track("Staff Software Engineer", "software_engineering") == RoleTrack.TECHNICAL


def test_chief_architect_is_technical_but_chief_officer_is_management():
    # "chief" + an IC word stays technical; "chief" alone is leadership.
    assert classify_track("Chief Architect", "software_engineering") == RoleTrack.TECHNICAL
    assert classify_track("Chief Product Officer", None) == RoleTrack.MANAGEMENT


def test_plain_ic_roles_are_technical():
    assert classify_track("Senior Software Engineer", "software_engineering") == RoleTrack.TECHNICAL
    assert classify_track("Data Scientist", "data_science") == RoleTrack.TECHNICAL
    assert classify_track("Security Engineer", "security_engineering") == RoleTrack.TECHNICAL


def test_business_and_customer_ic_roles_are_not_mislabeled_technical():
    assert (
        classify_track("Enterprise Account Executive", "sales_business_development")
        == RoleTrack.BUSINESS_CUSTOMER
    )
    assert (
        classify_track("Customer Success Specialist", "customer_success")
        == RoleTrack.BUSINESS_CUSTOMER
    )
    assert classify_track("Director of Sales", "sales_business_development") == RoleTrack.MANAGEMENT


def test_every_track_slug_fits_the_persisted_column():
    assert Job.__table__.c.track.type.length >= max(map(len, all_track_slugs()))


# "manager" names the work in a business function, the team in a
# technical one. Real catalog titles; the people managers are the negative
# controls a rule that just dropped "manager" would fail.
_IC_MANAGERS = (
    ("Senior Customer Success Manager", "customer_success"),
    ("Customer Success Lead/Manager", "customer_success"),
    ("Client Success Manager", "customer_success"),
    ("Implementation Manager", "customer_success"),
    ("Product Marketing Manager", "marketing_communications"),
    ("Staff Technical Marketing Manager (Staff TMM) – Browser Security", "marketing_communications"),
    ("Growth Marketing Manager, Socials", "marketing_communications"),
    ("Social Media Manager", "marketing_communications"),
    ("Partner Public Relations Manager (Remote)", "marketing_communications"),
    ("Senior Technical Account Manager (EMEA)", "sales_business_development"),
    ("Channel Sales Manager", "sales_business_development"),
    ("Regional Sales Manager", "sales_business_development"),
    ("Business Development Manager", "sales_business_development"),
    ("Key Account Manager", "sales_business_development"),
    ("Tax Manager", "finance_accounting"),
    ("Accounting Manager, GL Operations & Intercompany", "finance_accounting"),
    ("Internal Audit Manager", "finance_accounting"),
    ("Senior Finance Manager, FP&A - Mobile", "finance_accounting"),
    ("Revenue Operations Manager", "business_operations_strategy"),
    ("Senior Sales Operations Manager, New Seller Recruitment", "business_operations_strategy"),
    ("Supply Chain Manager III", "business_operations_strategy"),
    ("Senior Event Operations Manager", "business_operations_strategy"),
    ("Talent Acquisition Manager", "people_recruiting"),
    ("Regulatory Compliance Manager", "legal_policy"),
)
_PEOPLE_MANAGERS = (
    ("Senior Manager, Communications", "marketing_communications"),
    ("Manager, Sales Development", "sales_business_development"),
    ("Sales Manager", "sales_business_development"),
    ("Manager of Customer Success", "customer_success"),
    ("Manager, Regional Treasury", "finance_accounting"),
    ("Accounting Senior Manager, Brazil", "finance_accounting"),
    ("Sr. Operations Manager, Fulfillment Operations", "business_operations_strategy"),
    ("Operations Manager (Manager III, Operations P03091), AMZL-Delivery Station", "business_operations_strategy"),
    ("Customer Support Manager", "customer_success"),
    ("Director of Customer Success", "customer_success"),
    ("Head of Strategic Partnerships", "sales_business_development"),
    ("Applied Science Manager", "ml_ai_research"),
    ("Data Science Manager", "data_science"),
    ("Machine Learning Manager", "ml_ai_research"),
    ("Security Engineer Manager", "security_engineering"),
    ("Product Design Manager", "design_ux"),
    ("Software Development Manager", "data_engineering"),
    ("Forward Deployed Engineering Manager", "solutions_sales_eng"),
    ("Manager, Software Engineering - Payments", "software_engineering"),
)


def test_ic_manager_titles_are_not_leadership():
    wrong = [t for t, f in _IC_MANAGERS if classify_track(t, f) != RoleTrack.BUSINESS_CUSTOMER]
    assert wrong == []


def test_people_managers_stay_leadership():
    wrong = [t for t, f in _PEOPLE_MANAGERS if classify_track(t, f) != RoleTrack.MANAGEMENT]
    assert wrong == []


def test_business_ic_manager_in_a_technical_family_stays_with_that_family():
    # A family rule filed these under a technical family; the title still names IC work.
    assert classify_track("Senior Technical Account Manager", "ml_ai_research") == RoleTrack.TECHNICAL
    assert classify_track("Product Marketing Manager", "data_science") == RoleTrack.TECHNICAL


def test_management_is_not_a_manager():
    assert classify_track("Program Management Specialist", "business_operations_strategy") == RoleTrack.BUSINESS_CUSTOMER
