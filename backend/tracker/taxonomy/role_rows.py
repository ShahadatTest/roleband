"""The rows of the walk's "which roles" step, one question per role track.

Each track is one answer on the walk ("Leading a team", "Owning a product",
"Hands-on, as the expert", "Working with customers"), and each row is
a noun a person reads with the role families it stands for. A family appears in
at most one row per track.

The rows are what `enrich/track.py` actually files under each track: a row
whose families never occur under its track can never match, and a family filed
under a track no row names cannot be picked there, so once rows are picked it
is exactly the tail a count silently drops.
`tests/test_role_rows.py` holds both directions against the classifier itself,
over probe titles for each of its branches. "Any" is every role of the track,
named by a row or not.

The dashboard reads this table from `dashboard/src/features/scope/walk/
roleQuestions.gen.json` (`python -m scripts.export_role_questions`); a test
fails when the committed file differs from it.
"""

from __future__ import annotations

from dataclasses import dataclass

from tracker.schema import RoleTrack


@dataclass(frozen=True)
class RoleRow:
    key: str
    label: str
    families: tuple[str, ...]
    examples: str
    # Specialists pick a craft first; the rows of one craft share it.
    craft: str | None = None


@dataclass(frozen=True)
class RoleQuestion:
    # How the sentence continues: "leading a team" + " of " + rows.
    joiner: str
    # The "any" choice, worded for this answer.
    any: str
    rows: tuple[RoleRow, ...]
    crafts: tuple[str, ...] = ()


_BUSINESS = (
    "sales_business_development", "customer_success", "marketing_communications",
    "business_operations_strategy", "finance_accounting", "people_recruiting", "legal_policy",
)
_ENGINEERING = (
    "software_engineering", "infrastructure_sre", "security_engineering",
    "hardware_engineering", "data_engineering",
)

ROLE_QUESTIONS: dict[str, RoleQuestion] = {
    # Product and program managers are never "leading a team": the classifier
    # files their families under owning a product or program, whatever the title.
    RoleTrack.MANAGEMENT.value: RoleQuestion(
        joiner=" of ",
        any="All",
        rows=(
            RoleRow(
                "engineers", "Engineers", ("engineering_management", *_ENGINEERING),
                "software, infrastructure, security, hardware, data",
            ),
            RoleRow("designers", "Designers", ("design_ux",), "product, interaction and visual design, UX research"),
            RoleRow(
                "research", "Data science & AI", ("data_science", "ml_ai_research"),
                "data science, analytics, ML and AI research",
            ),
            RoleRow(
                "customers", "Sales & customer teams",
                (
                    "sales_business_development", "customer_success", "solutions_sales_eng",
                    "developer_relations", "marketing_communications", "technical_writing",
                ),
                "sales, customer success, solutions, DevRel, marketing",
            ),
            RoleRow(
                "business", "Operations, finance, HR or legal",
                (
                    "business_operations_strategy", "finance_accounting", "people_recruiting",
                    "legal_policy", "it_support", "operations_facilities",
                ),
                "operations, strategy, finance, recruiting, legal, IT, facilities",
            ),
        ),
    ),
    RoleTrack.PRODUCT_PROGRAM.value: RoleQuestion(
        joiner=" in ",
        any="All",
        rows=(
            RoleRow("pm", "Product management", ("product_management",), "product manager, group PM, head of product"),
            RoleRow("tpm", "TPM", ("technical_program_management",), "technical program manager, technical program lead"),
            RoleRow("program", "Program & project management", ("program_management",), "program manager, project manager, PMO"),
        ),
    ),
    # Solutions engineers and developer advocates are hands-on (no leadership
    # word, and not a customer-track family).
    RoleTrack.TECHNICAL.value: RoleQuestion(
        joiner=" in ",
        any="All",
        crafts=(
            "Engineering & hardware", "Design", "Data & research", "Solutions & advocacy", "Support & docs",
            "Operations & facilities",
        ),
        rows=(
            RoleRow("software", "Software", ("software_engineering",), "backend, frontend, mobile, full-stack", "Engineering & hardware"),
            RoleRow(
                "infra", "Infrastructure / SRE", ("infrastructure_sre",),
                "platform, SRE, DevOps, cloud, networking, systems", "Engineering & hardware",
            ),
            RoleRow("security", "Security", ("security_engineering",), "application security, detection, offensive security", "Engineering & hardware"),
            RoleRow("hardware", "Hardware / silicon", ("hardware_engineering",), "silicon, electrical, firmware, embedded", "Engineering & hardware"),
            RoleRow("data_eng", "Data engineering", ("data_engineering",), "pipelines, warehousing, analytics engineering", "Engineering & hardware"),
            RoleRow("design", "Product / UX design", ("design_ux",), "product design, interaction, UX research", "Design"),
            RoleRow("data_science", "Data science & analytics", ("data_science",), "data scientist, analyst, experimentation", "Data & research"),
            RoleRow("ml", "ML & AI research", ("ml_ai_research",), "research scientist, ML engineer, applied AI", "Data & research"),
            RoleRow("solutions", "Solutions & forward-deployed", ("solutions_sales_eng",), "solutions engineer, sales engineer, forward-deployed", "Solutions & advocacy"),
            RoleRow("devrel", "Developer relations", ("developer_relations",), "developer advocate, community, evangelism", "Solutions & advocacy"),
            # A business family filed hands-on: an "architect" title the family
            # rules read as the business it serves ("SAP Supply Chain
            # Architect", "Workday Application Architect").
            RoleRow(
                "business_systems", "Business systems architecture", _BUSINESS,
                "Workday, SAP, supply chain, compliance architects", "Solutions & advocacy",
            ),
            RoleRow("it", "IT support", ("it_support",), "IT, help desk, corporate engineering", "Support & docs"),
            RoleRow("writing", "Technical writing", ("technical_writing",), "documentation, developer docs, content", "Support & docs"),
            RoleRow(
                "facilities", "Data centre & facilities", ("operations_facilities",),
                "data centre technician, site operations, health and safety", "Operations & facilities",
            ),
        ),
    ),
    # Finance, people, legal and operations ICs work with customers.
    RoleTrack.BUSINESS_CUSTOMER.value: RoleQuestion(
        joiner=" in ",
        any="All",
        rows=(
            RoleRow("sales", "Sales & partnerships", ("sales_business_development",), "account executive, enterprise sales, business development"),
            RoleRow("success", "Customer success", ("customer_success",), "customer success, account management, support"),
            RoleRow("marketing", "Marketing", ("marketing_communications",), "product marketing, brand, communications"),
            RoleRow("operations", "Operations & strategy", ("business_operations_strategy",), "business operations, strategy, supply chain"),
            RoleRow(
                "finance", "Finance & accounting", ("finance_accounting",),
                "financial analyst, controller, accounting, tax, audit, treasury",
            ),
            RoleRow(
                "people", "People & recruiting", ("people_recruiting",),
                "recruiter, talent acquisition, HR partner, people operations",
            ),
            RoleRow("legal", "Legal & policy", ("legal_policy",), "counsel, compliance, public policy, trust & safety"),
        ),
    ),
}


def named_pairs() -> set[tuple[str, str]]:
    """Every (track, family) some row names."""
    return {
        (track, family)
        for track, question in ROLE_QUESTIONS.items()
        for row in question.rows
        for family in row.families
    }


def export() -> dict:
    """The table as the dashboard reads it (`roleQuestions.gen.json`)."""
    out: dict = {}
    for track, question in ROLE_QUESTIONS.items():
        entry: dict = {"joiner": question.joiner, "any": question.any}
        if question.crafts:
            entry["crafts"] = list(question.crafts)
        entry["rows"] = [
            {
                "key": row.key,
                "label": row.label,
                "families": list(row.families),
                "examples": row.examples,
                **({"craft": row.craft} if row.craft else {}),
            }
            for row in question.rows
        ]
        out[track] = entry
    return out
