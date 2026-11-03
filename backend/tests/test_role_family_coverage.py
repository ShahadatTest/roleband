"""Role-family coverage over titles a live board sends.

A posting with no role family is kept by no answer on the walk, however well
it is placed. The titles below are a real listing's, verbatim. Three kinds of
case:

- sorted: titles the classifier files;
- controls: titles whose family must not move, including ones a broader
  keyword moves (a software engineer on TPU performance, a marketing-tech SDE,
  a chief of staff in sales);
- the family rules: data centre, facilities and safety roles are Operations &
  facilities, administrative partners business operations, trust and safety
  analysts legal and policy, and interns their field; clinical roles and placeholders stay None, and a keyword that
  sweeps them into a family fails here.

`scripts.bench_role_families` reports what a classifier change moves across
every stored title; run it before landing a keyword.
"""

from __future__ import annotations

import pytest

from tracker.enrich.classify import classify_family
from tracker.schema import RawJob


def _family(title: str) -> str | None:
    return classify_family(RawJob(company="google", req_id="t", title=title, url=""))


@pytest.mark.parametrize("title,department,family", [
    ("Senior Recruiter, Business Development", "People : Talent Acquisition", "people_recruiting"),
    ("Senior Director, Product Security", "Information Security", "security_engineering"),
    ("Deputy Head of Production, Autonomous Airpower", "Manufacturing", "operations_facilities"),
    ("Head of Production, Compute & Comms", "Manufacturing", "operations_facilities"),
    ("Principal Propulsion Engineer, Air Vehicles", None, "hardware_engineering"),
    ("Principal Radar Engineer, Space", None, "hardware_engineering"),
    ("Principal RF Engineer, EW", None, "hardware_engineering"),
    ("Principal Test & Evaluation Engineer", "Hardware Test Operations", "hardware_engineering"),
    ("Senior RF Communications Engineer, Space", None, "hardware_engineering"),
    ("Staff PCB Designer/Layout Engineer", None, "hardware_engineering"),
    ("Product Manager, Security", "Information Security", "product_management"),
    ("Director, Product Line Management", None, "product_management"),
    ("Head of Product", None, "product_management"),
    ("Head of Production, Publishing", None, None),
    ("Communications Manager, RF Systems", None, "marketing_communications"),
    ("Software Test Engineer", "Software Engineering", "software_engineering"),
    ("Staff Software Engineer, Security", "Manufacturing", "software_engineering"),
    ("Production Associate", "Manufacturing", None),
    ("Senior Software Engineer, Radar", None, "software_engineering"),
    ("Business Development Manager, Recruiting", None, "sales_business_development"),
    ("Staff Product Designer, Hardware", None, "design_ux"),
])
def test_role_subject_and_physical_engineering_keep_their_family(title, department, family):
    assert classify_family(RawJob(company="anduril", req_id="t", title=title, url="",
                                  department=department)) == family


SORTED = {
    # A keyword at the very end of the title still matches ("engineer ").
    "Software Test Engineer": "software_engineering",
    "Senior Staff Tech Lead, YouTube Shorts Discovery": "software_engineering",
    "Staff Engineer/Technical Lead, Google Distributed Cloud Storage": "software_engineering",
    "Technical Lead, Android Growth Systems and App Foundations": "software_engineering",
    "Tech Lead Manager, Mobile, iOS, Google Ads": "engineering_management",
    "CPU DFT Engineer": "hardware_engineering",
    "Signal and Power Integrity Engineer": "hardware_engineering",
    "Staff Hardware System Architect, Pixel Watch": "hardware_engineering",
    "Data Center Mechanical Engineer": "hardware_engineering",
    "Senior Incident Response Security Consultant, Mandiant, Google Cloud": "security_engineering",
    "Red Team Security Consultant, Mandiant, Google Cloud": "security_engineering",
    "Account Strategist, Mid-Market Sales, Google Customer Solutions": "sales_business_development",
    "AI Sales Specialist, US North, Google Cloud": "sales_business_development",
    "Strategic Partner Development Lead, Ad Platforms": "sales_business_development",
    "Head of Industry, Programmatic, Telecom": "sales_business_development",
    "Partner Solution Architect, Regional System Integrators and Strategic Partners": "solutions_sales_eng",
    "Principal Architect, SLED, State of New York, Google Public Sector": "solutions_sales_eng",
    "Payments Partner Engineer": "solutions_sales_eng",
    "Product Support Manager, Google Fi": "customer_success",
    "Global Commodity Manager, SSD/NAND": "business_operations_strategy",
    "Strategic Negotiator, Data Center Leasing and Investments": "business_operations_strategy",
    "Sales Operations Senior Associate": "business_operations_strategy",
    "Senior Business Finance Analyst, AppDev, Google Customer Solutions": "finance_accounting",
    "People Consultant, Onsite Data Center": "people_recruiting",
    "Associate Product Counsel, Ads": "legal_policy",
    "Senior Policy Specialist, Google Play": "legal_policy",
    "Public Affairs Manager, Regional Data Centers": "legal_policy",
    "Senior Economist, Economic Impact Estimation": "data_science",
    "Analytical Lead, Large Customer Sales": "data_science",
    "Senior Director, UX, YouTube Emerging Experience and Community": "design_ux",
    # The groups the family rules above name.
    "Data Center Technician II, Global Server Operations": "operations_facilities",
    "Data Center Facilities Technician, Electrical": "operations_facilities",
    "Facilities Manager, Data Center Operations": "operations_facilities",
    "Data Center Operations Lead, Sovereign Operations, Hampshire or Wiltshire": "operations_facilities",
    "Environmental, Health and Safety Area Manager, EHS Operations": "operations_facilities",
    "Administrative Business Partner III, Cloud AI": "business_operations_strategy",
    "Analyst, Trust and Safety": "legal_policy",
    "Student Researcher, PhD, Fall 2026": "ml_ai_research",
}

CONTROLS = {
    # Stored titles a broader keyword moves; each keeps its family.
    "Staff Software Engineer, TPU Performance": "software_engineering",
    "Software Development Engineer, Lead Management and Account-Based Marketing Tech": "software_engineering",
    "Senior Operations Manager, Wafer Fabrication, Raxium": "business_operations_strategy",
    "Chief of Staff, Global Channel Sales (GCS)": "business_operations_strategy",
    # Stored titles near the family rules that keep their family.
    "Head of Data Center Operations Procurement - Americas, Infrastructure Planning and Sourcing": "business_operations_strategy",
    "ML Staff Software Engineer, Trust and Safety, YouTube": "software_engineering",
    # Families that must not be disturbed by the keywords above.
    "Accountant": "finance_accounting",
    "Senior Security Engineer, Detection": "security_engineering",
    "Staff Product Manager, Payments": "product_management",
    "Developer Marketing Manager": "developer_relations",
    "Senior Engineering Manager, Search": "engineering_management",
    "Solutions Architect, Startups": "solutions_sales_eng",
}

#: The team after the comma is not the role. An engineer title whose
#: team names a business function is not filed in that function (a
#: Communications team to marketing, Supply Chain to business operations,
#: Accounting to finance, Partnerships to sales). The team may
#: still say WHICH engineering ("Software Engineer, Machine Learning").
TEAM_IS_NOT_THE_ROLE = {
    "Software Engineer III, Infra, Core Communications": "software_engineering",
    "Senior Software Engineer - Accounting & Ledger Systems": "software_engineering",
    "Backend Engineer - Supply Chain & Logistics (m/f/d)": "software_engineering",
    "Senior Software Engineer I, Product Partnerships": "software_engineering",
    "Enterprise Solutions Engineer - Benelux": "solutions_sales_eng",
    "Software Engineer - Yocto/Linux": "software_engineering",  # "lin-ux" read as UX
    "Software Development Engineer, Amazon Customer Service": "software_engineering",
    # "<X> Engineering" and "Developer ..." name a team, not a second role.
    "Senior Backend Engineer, Compliance Engineering": "software_engineering",
    "Sr. Software Engineer, Customer Experience Engineering": "software_engineering",
    "Backend Engineer, Developer & End-user Experience Platform": "software_engineering",
}

#: Google spells the role "Software Engineer Manager" as often as "Software
#: Engineering Manager", and both are managers, or their manager ladder never
#: reads them.
ENGINEER_MANAGER = {
    "Software Engineer Manager II, Full Stack": "engineering_management",
    "Software Engineer Manager II, Embedded Systems/Firmware": "engineering_management",
    "Software Engineer Manager, TPU Silicon Validation": "engineering_management",
}

#: Must not move: a team naming an engineering specialisation still refines
#: the family; a business head keeps its family whatever the team is; a
#: specialisation that outranks engineering management still takes its title.
TEAM_CONTROLS = {
    "Software Engineer, Machine Learning": "ml_ai_research",
    "Communications Manager, Google Cloud": "marketing_communications",
    "Product Manager, Security": "product_management",
    "Account Executive, Partnerships": "sales_business_development",
    "Marketing Manager, Developer Platform": "marketing_communications",
    "Cloud Technical Solutions Engineer Manager, Networking (English)": "solutions_sales_eng",
    # A first part with no role noun still names the role: the team after it
    # does not take these (a rule reading `title_head` moves both).
    "Product Lead, Developer Experience": "product_management",
    "Pre-Sales Program Lead, Forward Deployed Engineering": "program_management",
    # A part naming a role keeps its family wherever it sits; a looser rule
    # moves each of these.
    "Wireless SoC System Validation, FW and NPI Engineering Program Manager": "program_management",
    "Member of Technical Staff - Technical Program Manager, Frontier AI & Robotics": "technical_program_management",
    "Senior Technical Program Manager, Software Engineering, Core Systems": "technical_program_management",
    "Director, Product Line Management - Custom Silicon": "product_management",
    # The bare "engineer" names no engineering work: the operations and
    # facilities rule keeps these.
    "Sr. Environmental Health & Safety Engineer, EHS Training Programs": "operations_facilities",
    "Quality Engineer, Data Center Operations": "operations_facilities",
    # A dual title: the second part names a role of its own, which keeps it.
    "Senior Transit Engineer - Project Manager": "program_management",
    "Staff Engineer, Operations Analyst (R5807)": "business_operations_strategy",
}

#: Unfiled: a word the team rule reads must not become a family keyword
#: (listing "development engineer" would file these).
STILL_UNSORTED = (
    "Senior Clinical Development Engineer- SP, I&A",
)


#: Left out: clinical roles are outside
#: the radar's audience, and a placeholder is not a role.
LEFT_OUT = (
    "Clinical Specialist, Mental Health",
    "Clinical Specialist, Youth Mental Health",
    "Open Career Opportunities",
)


@pytest.mark.parametrize(("title", "family"), SORTED.items())
def test_a_title_google_lists_is_filed_in_its_family(title, family):
    assert _family(title) == family


@pytest.mark.parametrize(("title", "family"), CONTROLS.items())
def test_a_control_title_keeps_its_family(title, family):
    assert _family(title) == family


@pytest.mark.parametrize("title", LEFT_OUT)
def test_a_group_the_owner_left_out_stays_unsorted(title):
    assert _family(title) is None


@pytest.mark.parametrize(("title", "family"), {**TEAM_IS_NOT_THE_ROLE, **ENGINEER_MANAGER}.items())
def test_the_role_decides_the_family_not_the_team(title, family):
    assert _family(title) == family


@pytest.mark.parametrize(("title", "family"), TEAM_CONTROLS.items())
def test_a_team_control_keeps_its_family(title, family):
    assert _family(title) == family


@pytest.mark.parametrize("title", ENGINEER_MANAGER)
def test_engineer_manager_is_engineering_manager_spelled_another_way(title):
    assert _family(title) == _family(title.replace("Engineer Manager", "Engineering Manager"))
    assert _family(title) == "engineering_management"


@pytest.mark.parametrize("title", STILL_UNSORTED)
def test_the_team_rule_files_no_title_that_had_no_family(title):
    assert _family(title) is None



#: Hourly frontline roles named "<workplace> Associate": a store,
#: warehouse or delivery-station job is the first rung of no professional
#: discipline, so it is filed in none, whatever its department says. Real
#: titles (Amazon, Anduril, Fanatics).
FRONTLINE = (
    "Retail Lead Associate (Reduced-Time), Customer Experience Operations",
    "Retail Lead Associate (Full-Time), Customer Experience Operations",
    "Delivery Station Customer Service Associate, SDS",
    "Warehouse Forklift Associate",
    "Warehouse Associate (Starlink)",
    "Seasonal Loss Prevention/EHS Associate",
    "Store Associate - Orlando",
)
#: "Associate" titles at work a discipline owns: each keeps its family.
FRONTLINE_CONTROLS = {
    "Retail Inside Sales Associate": "sales_business_development",
    "Customer Success Associate": "customer_success",
    "IT Support Associate II, Ops Tech Solutions (OTS)": "it_support",
    "Production Engineer Associate": "software_engineering",
    "Business Operations Associate": "business_operations_strategy",
}


@pytest.mark.parametrize("title", FRONTLINE)
def test_a_frontline_associate_is_filed_in_no_discipline(title):
    assert _family(title) is None
    # Not by its department either: Amazon files its store roles under
    # "Fulfillment & Operations Management".
    job = RawJob(company="amazon", req_id="t", title=title, url="",
                 department="Customer Experience Operations", team="Customer Service")
    assert classify_family(job) is None


@pytest.mark.parametrize(("title", "family"), FRONTLINE_CONTROLS.items())
def test_an_associate_at_a_discipline_keeps_its_family(title, family):
    assert _family(title) == family


def test_a_publisher_production_associate_keeps_its_family():
    # "Production" is no frontline marker: at a publisher it makes media
    # (Penske Media).
    job = RawJob(company="penske-media-corp", req_id="t", url="",
                 title="The Hollywood Reporter: Production Associate, Video & Social Media",
                 department="The Hollywood Reporter - Content & Editorial")
    assert classify_family(job) == "marketing_communications"
