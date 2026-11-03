"""Canonical role taxonomy.

Companies name the same underlying role differently ("Member of Technical Staff"
vs "Research Engineer" vs "Research Scientist"). We map each posting's title to a
canonical role group so the user picks a *role*, not a company-specific phrase.
The per-company wording is learned from live data by the discovery pass
(`discover_roles.py`) and shown next to each group in settings.

Groups are checked in list order — first keyword match wins — so more specific /
management roles are matched before the generic "software engineer" bucket.

One deliberate exception to list order: a title can carry both a specialization
and the generic "<X> Engineering Manager" pattern, and the management keyword
would always win on position alone. A group flagged
`outranks_engineering_management` takes such a title instead (see
`classify_role`). Only `engineering_management` is overridable this way; every
other precedence remains plain list order.

A second one: the team after the comma is not the role. A business
family yields to an engineering one only when the part of the title carrying
it names no role (a team: "Core Communications", "Supply Chain & Logistics")
and an earlier part names an engineering role by a specific word ("Software
Engineer III, Infra, Core Communications" is software engineering). The bare
"engineer" fallback is not specific: "Sr. Environmental Health & Safety
Engineer, EHS Training Programs" stays operations and facilities. Everything else keeps list
order: a part naming a role keeps its family wherever it sits ("Wireless SoC
System Validation, FW and NPI Engineering Program Manager" is program
management), a business keyword spanning parts retains precedence unless it names the
Product Security specialization, and a later part may still say WHICH engineering
("Software Engineer, Machine Learning" is ML).

The team rule extends to earlier named business roles: a recruiter
serving Business Development recruits. Short Product leadership phrases
exclude Production and Product Security; physical RF/radar/propulsion/PCB
titles name hardware. Manufacturing production heads require department
corroboration in `enrich.classify`, never a title-only guess.
"""

from __future__ import annotations

import functools
import re
from dataclasses import dataclass, field

from tracker.taxonomy.title_parse import names_a_role, segments


@dataclass(frozen=True)
class RoleGroup:
    slug: str
    display: str
    # Substrings (lowercased) that indicate this group. First group to match wins.
    keywords: tuple[str, ...]
    # Department/team phrases used only to refine generic/unclassified titles.
    department_keywords: tuple[str, ...] = field(default_factory=tuple)
    # Whether this group is tracked by default (before the user customizes).
    default_enabled: bool = False
    # Whether this specialization claims a title that ALSO reads as engineering
    # management ("Forward Deployed Engineering Manager"). See module docstring.
    outranks_engineering_management: bool = False
    # A couple of hand-seeded example phrasings, used only until discovery runs.
    seed_examples: tuple[str, ...] = field(default_factory=tuple)


# Priority-ordered. Management/specialized groups precede the generic SWE bucket.
ROLE_GROUPS: tuple[RoleGroup, ...] = (
    RoleGroup(
        "engineering_management",
        "Engineering Management",
        ("engineering manager", "eng manager", "manager, engineering", "manager of engineering",
         "director of engineering", "director, engineering", "engineering director",
         "head of engineering", "vp of engineering", "vp, engineering", "technical lead manager",
         "senior engineering manager", "tech lead manager",
         # Google's "Software Engineer Manager II": the same role spelled
         # another way, so the same family.
         "engineer manager"),
        default_enabled=True,
    ),
    RoleGroup(
        "product_management",
        "Product Management",
        ("product manager", "product management", "group product manager", "director of product",
         "head of product", "chief product", "director, product", "vp of product", "product lead"),
        default_enabled=True,
    ),
    RoleGroup(
        "technical_program_management",
        "Technical Program Management (TPM)",
        ("technical program manager", "technical project manager", "tpm"),
        default_enabled=True,
    ),
    RoleGroup(
        "program_management",
        "Program / Project Management",
        ("program manager", "project manager", "program lead"),
        default_enabled=True,
    ),
    RoleGroup(
        "ml_ai_research",
        "ML / AI Research",
        # "applied science" is the canonical TITLE phrase, not only a department
        # one: "Applied Science Manager" is a science-team leadership role, and
        # the group's `applied scientist` keyword does not cover it. Without it
        # `classify_role` returns None for that title, so a query for it parses
        # no family and search cannot narrow.
        # Listed before `applied scientist` because it subsumes it.
        ("research scientist", "research engineer", "member of technical staff", "machine learning",
         "ml engineer", "deep learning", "ai researcher", "applied science", "applied scientist",
         "applied ai", "ai/ml", "ai / ml", "research resident", "research manager",
         "model behavior",
         # Interns filed by their field: a student researcher does research.
         "student researcher"),
        department_keywords=("applied science", "machine learning", "artificial intelligence",
                             "ai/ml", "deep learning", "model research"),
    ),
    RoleGroup(
        "data_science",
        "Data Science & Analytics",
        ("data scientist", "data science", "data analyst", "analytics", "quantitative",
         "business intelligence", "decision scientist",
         "economist", "analytical lead", "insights analyst", "engineering analyst"),
        department_keywords=("data science", "decision science", "business intelligence", "analytics"),
    ),
    RoleGroup(
        "data_engineering",
        "Data Engineering",
        ("data engineer", "analytics engineer", "data platform", "data infrastructure"),
        department_keywords=("data engineering", "data platform", "data infrastructure"),
    ),
    RoleGroup(
        "security_engineering",
        "Security",
        ("security engineer", "security researcher", "application security", "appsec", "infosec",
         "information security", "cryptograph", "detection engineer", "offensive security",
         "product security", "security architect",
         # Consulting and response practices (Mandiant).
         "security consultant", "security consulting", "incident response", "red team",
         "threat defense", "cyber defense", "cybersecurity", "security analyst"),
        department_keywords=("application security", "information security", "product security",
                             "cybersecurity", "security engineering"),
    ),
    RoleGroup(
        "infrastructure_sre",
        "Infrastructure / SRE / Systems",
        ("site reliability", "reliability engineer", " sre", "devops", "infrastructure engineer",
         "platform engineer", "systems engineer", "network engineer", "cloud engineer",
         # One word each, so "devops" cannot start inside it.
         "compute", "kernel", "netdevops", "secdevops"),
        department_keywords=("site reliability", "production engineering", "cloud infrastructure",
                             "compute platform", "infrastructure engineering"),
    ),
    RoleGroup(
        "hardware_engineering",
        "Hardware / Silicon",
        ("hardware engineer", "asic", "fpga", "postsilicon", "wsoc ",
         # One word each, so "mechanical engineer" cannot start inside it.
         "optomechanical engineer", "hydromechanical engineer", "electromechanical engineer",
         "silicon", "electrical engineer", "firmware",
         "rtl", "chip", "soc ", "verification engineer", "physical design",
         # Processor, package and power design.
         " dft ", "serdes", "power integrity", "signal integrity",
         "hardware system", "hardware power", "power architect", "package design",
         "micro-architect", "battery cell", "epitaxy", "fab process",
         # Physical engineering the generic "engineer" fallback would call software.
         "mechanical engineer", "controls engineer", "calibration engineer", "wireless system",
         "emulation", "manufacturing test", "power modeling",
         "radar engineer", "propulsion engineer", " rf engineer", "rf communications engineer",
         "pcb designer", "pcb layout"),
        department_keywords=("hardware engineering", "silicon", "asic", "fpga", "firmware",
                             "electrical engineering", "physical design", "hardware test"),
    ),
    RoleGroup(
        "software_engineering",
        "Software Engineering",
        ("software engineer", "software engineering", " swe", "backend engineer", "frontend engineer",
         "full stack", "full-stack", "ios engineer", "android engineer", "web engineer",
         "software developer", "distributed systems", "engineer,", "engineer -", "engineer ",
         # How senior engineers are titled without the word "engineer".
         "tech lead", "technical lead", "technical leader", "staff engineer", "engineer/"),
    ),
    RoleGroup(
        "design_ux",
        "Design / UX",
        ("designer", "ux ", "ux,", "user experience", "product design", "ui/ux", "ux research",
         "design lead", "creative director", "visual design", "interaction design"),
    ),
    RoleGroup(
        "developer_relations",
        "Developer Relations",
        ("developer advocate", "developer relations", "devrel", "developer experience",
         "developer marketing"),
    ),
    RoleGroup(
        "solutions_sales_eng",
        "Solutions / Forward-Deployed",
        ("solutions engineer", "solutions architect", "sales engineer", "forward deployed",
         "forward-deployed", "customer engineer", "solutions consultant", "field engineer",
         # Partner and customer architecture.
         "solution architect", "principal architect", "enterprise architect", "practice architect",
         "solutions developer", "field cto", "deployment engineer", "partner engineer",
         "technical engagement", "presales engineer", "presales consultant", "presales architect"),
        # A Forward Deployed Engineering Manager manages a forward-deployed
        # function; the family must say so, or this group's toggle can never
        # exclude the role and Engineering Management silently owns it.
        outranks_engineering_management=True,
    ),
    RoleGroup(
        "technical_writing",
        "Technical Writing",
        ("technical writer", "documentation engineer", "content designer", "technical content"),
    ),
    RoleGroup(
        "it_support",
        "IT / Support Engineering",
        ("it engineer", "help desk", "support engineer", "technical support", "system administrator",
         "it support", "desktop support"),
    ),
    RoleGroup(
        "sales_business_development",
        "Sales & Business Development",
        ("account executive", "sales representative", "sales development", "business development",
         "partnerships", "account manager", "sales manager", "sales director", "sales lead",
         "commercial sales", "enterprise sales", "inside sales", "revenue officer",
         # Google's ads and cloud sales titles.
         "sales specialist", "account strategist", "account representative", "account lead",
         "partner development", "strategic alliance", "alliance manager", "head of channel sales",
         "head of industry", "lead of industry", "customer growth", "pursuit lead",
         # One word, so "sales" cannot start inside it.
         "presales manager", "presales lead", "presales specialist", "telesales"),
    ),
    RoleGroup(
        "customer_success",
        "Customer Success & Service",
        ("customer success", "client success", "customer service", "customer experience",
         "customer care", "implementation manager", "implementation consultant",
         "product support"),
    ),
    RoleGroup(
        "marketing_communications",
        "Marketing & Communications",
        ("product marketing", "growth marketing", "demand generation", "content marketing",
         "brand marketing", "marketing manager", "marketing director", "communications",
         "public relations", "media relations", "social media",
         "performance marketing", "content strategist"),
    ),
    RoleGroup(
        "business_operations_strategy",
        "Business Operations & Strategy",
        ("business operations", "strategy and operations", "strategy & operations", "bizops",
         "operations manager", "operations analyst", "strategic planning", "corporate strategy",
         "chief of staff", "procurement", "supply chain",
         # Strategy, planning and sourcing titles.
         "sales operations", "strategy manager", "strategy associate",
         "strategy analyst", "strategic negotiator", "business planning", "category manager",
         "commodity manager", "capacity planning",
         # Administrative partners to executives.
         "administrative business partner", "executive business partner"),
    ),
    # Data centre and site operations: the
    # technicians, facilities and safety staff a live board lists in
    # hundreds, which would otherwise fit no family.
    # After business operations, so a procurement or sourcing title that
    # names a data centre keeps its own family.
    RoleGroup(
        "operations_facilities",
        "Operations & Facilities",
        ("data center technician", "data centre technician", "datacenter technician",
         "data center operations", "data centre operations", "data center facilities",
         "data centre facilities", "facilities technician", "facilities manager",
         "facility manager", "critical facilities", "site operations",
         "environmental, health and safety", "health and safety", "ehs "),
    ),
    RoleGroup(
        "finance_accounting",
        "Finance & Accounting",
        ("financial analyst", "finance manager", "finance director", "accountant", "accounting",
         "controller", "treasury", "tax manager", "auditor", "audit manager",
         "finance analyst", "accounts receivable", "collections associate"),
    ),
    RoleGroup(
        "people_recruiting",
        "People / HR / Recruiting",
        ("recruiter", "recruiting", "talent acquisition", "human resources", "people operations",
         "people partner", "hr business partner", "compensation and benefits",
         "compensation & benefits", "people consultant"),
    ),
    RoleGroup(
        "legal_policy",
        "Legal / Policy / Compliance",
        ("legal counsel", "corporate counsel", "general counsel", "attorney", "paralegal",
         "legal operations", "compliance", "public policy", "government affairs",
         "regulatory affairs", "policy manager",
         # Counsel and policy work under any title; last in order, so any
         # earlier family claims its own policy titles first.
         " counsel", "policy", "public affairs", "political strategy",
         # Trust and safety enforcement. The analyst shapes only: an engineer on a trust and safety team is
         # still an engineer.
         "analyst, trust and safety", "trust and safety analyst", "trust & safety analyst",
         "specialist, trust and safety", "trust and safety specialist", "trust and safety manager"),
    ),
)

_BY_SLUG: dict[str, RoleGroup] = {g.slug: g for g in ROLE_GROUPS}

#: Families of engineering work. A part naming one of them keeps the title
#: against a business family that only the team names.
ENGINEERING_FAMILIES: frozenset[str] = frozenset({
    "engineering_management", "ml_ai_research", "data_science", "data_engineering",
    "security_engineering", "infrastructure_sre", "hardware_engineering",
    "software_engineering", "solutions_sales_eng", "developer_relations",
    "technical_writing", "it_support",
})


def _management_qualifier(hay: str) -> str | None:
    """Specialization group that a generic "... Engineering Manager" title shadows."""
    for group in ROLE_GROUPS:
        if group.outranks_engineering_management and any(kw in hay for kw in group.keywords):
            return group.slug
    return None


#: An hourly frontline role named by its workplace and "Associate":
#: a store, warehouse or delivery-station job is the first rung of no
#: professional discipline, so it is filed in none. The workplace word must
#: sit right before "Associate": "Retail Inside Sales Associate" sells to
#: merchants, and a "Production Associate" at a publisher makes media, so
#: "production" is no marker. Without this, "Retail Lead Associate" and
#: "Delivery Station Customer Service Associate" would file under Customer
#: Success by their keywords.
_FRONTLINE_ASSOCIATE_RE = re.compile(
    r"\b(?:delivery station(?: customer service)?|warehouse(?: forklift)?|forklift|retail(?: lead)?|store"
    r"|seasonal(?: [\w/&]+){1,2}|manufacturing|materials|inventory|shipping|receiving"
    r"|fulfil+ment|sortation|grocery)\s+associates?\b",
    re.IGNORECASE,
)


def is_frontline_associate(title: str) -> bool:
    """The title names an hourly frontline role: no discipline files it."""
    return bool(_FRONTLINE_ASSOCIATE_RE.search(title))


def classify_role(text: str) -> str | None:
    """Return the canonical role-group slug for a title/haystack, or None."""
    # A Chief of Staff runs an office, whichever discipline the office leads:
    # "Chief of Staff to the VP of Applied Science" is not a science role.
    if _word_start("chief of staff").search(text.lower()):
        return "business_operations_strategy"
    family = _first_family(text)
    if family == "developer_relations":
        # "Developer Experience" is also a team of tooling engineers: after
        # the comma it names the team, and the role before it decides.
        parts = segments(text)
        carriers = [i for i, part in enumerate(parts) if _first_family(part) == family]
        devex = ("developer experience",)
        if carriers and carriers[0] > 0 and not any(
            _first_family(_without(parts[i], devex)) == family or names_a_role(_without(parts[i], devex))
            for i in carriers
        ):
            for part in parts[: carriers[0]]:
                own = _first_family(part)
                if own is not None and names_a_role(part):
                    return own
    if family is None or family in ENGINEERING_FAMILIES:
        return family
    # The team is not the role: see the module docstring.
    parts = segments(text)
    carriers = [i for i, part in enumerate(parts) if _first_family(part) == family]
    if not carriers or any(_names_business_role(parts[i]) for i in carriers):
        return family
    for part in parts[: carriers[0]]:
        own = _names_engineering(part)
        if own is not None and names_a_role(part):
            return own
        # A recruiter serving Business Development still recruits. A second
        # named role keeps list precedence through the carrier guard above.
        own = _first_family(part)
        if own is not None and _names_business_role(part):
            return own
    return family


def _without(part: str, phrases: tuple[str, ...]) -> str:
    """`part` with every one of `phrases` taken out, case-insensitively."""
    out = part.lower()
    for phrase in phrases:
        out = out.replace(phrase, " ")
    return " ".join(out.split())


#: Software engineering's catch-all words: any engineer title has one, so they
#: name no engineering work by themselves.
_BARE_ENGINEER: frozenset[str] = frozenset({"engineer,", "engineer -", "engineer ", "engineer/"})
#: Amazon's SDE and SysDE name software work only through a catch-all word.
#: Specific for the team rule alone; as a family keyword it would file titles
#: no family claims today ("Clinical Development Engineer").
_ENGINEERING_TITLES: tuple[str, ...] = ("development engineer",)


def _names_business_role(part: str) -> bool:
    """A part naming a role that is not engineering ("Project Manager",
    "Operations Analyst"): a dual title, which keeps its business family. A
    part whose only role word is engineer or developer is a team ("Compliance
    Engineering", "Developer & End-user Experience Platform")."""
    return names_a_role(part) and not any(w in part.lower() for w in ("engineer", "developer"))


def _names_engineering(part: str) -> str | None:
    """The engineering family a part names by a specific word, else None."""
    own = _first_family(part)
    if own not in ENGINEERING_FAMILIES:
        return None
    if own != "software_engineering":
        return own
    hay = f" {part.lower()} "
    specific = [kw for kw in _BY_SLUG[own].keywords if kw not in _BARE_ENGINEER]
    return own if any(kw in hay for kw in (*specific, *_ENGINEERING_TITLES)) else None


def _first_family(text: str) -> str | None:
    """The first group whose keyword the text carries, as module order says."""
    # Padded, so a keyword can end the title: unpadded, "Measurement Engineer"
    # would never match "engineer " and would fall out of every family.
    hay = f" {text.lower()} "
    # The SWE group intentionally contains broad `engineer` fallbacks. Evaluate
    # every specialized family first so Sales Engineer, Support Engineer, and
    # Documentation Engineer do not disappear into Software Engineering.
    for group in (g for g in ROLE_GROUPS if g.slug != "software_engineering"):
        if any(_title_keyword(hay, kw, group.slug) for kw in group.keywords):
            # Engineering Management sits first in the list, so its keyword wins
            # any title that is *also* a specialization. Give the specialization
            # its title back; every other group keeps plain list precedence.
            if group.slug == "engineering_management":
                return _management_qualifier(hay) or group.slug
            return group.slug
    software = _BY_SLUG["software_engineering"]
    if any(kw in hay for kw in software.keywords):
        return software.slug
    return None


def _title_keyword(hay: str, keyword: str, family: str) -> bool:
    """Whether `keyword` names this family in the padded title `hay`.

    A keyword starts a word: "ux " is not the end of "linux " or "redux ". It
    may still run on ("recruit" in "recruiter"), which the keyword lists rely on.

    Product leadership names a product role, never production or security.
    The exact Product Manager head still wins over a Security team qualifier;
    only the short leadership phrases need this distinction.

    "controller" is finance only as a finance title ("Financial Controller",
    "Assistant Controller", "Controller"): a memory, flight or battery
    controller is the device an engineer builds.
    """
    if family == "product_management" and keyword.endswith("product"):
        return bool(re.search(re.escape(keyword) + r"s?\b(?!\s+security\b)", hay))
    if family == "finance_accounting" and keyword == "controller":
        return bool(_FINANCE_CONTROLLER.search(hay))
    return bool(_word_start(keyword).search(hay))


@functools.cache
def _word_start(keyword: str) -> re.Pattern[str]:
    edge = r"(?<![a-z0-9])" if keyword[:1].isalnum() else ""
    return re.compile(edge + re.escape(keyword))


#: The words that make "controller" a finance title when they precede it, or
#: nothing at all: the title is the controller. An engineering noun after it
#: makes it a device whatever comes before.
_FINANCE_CONTROLLER = re.compile(
    r"(?:^\s*|,\s*|\b(?:financial|finance|assistant|associate|corporate|group|regional|divisional|division"
    r"|plant|country|entity|global|deputy|senior|sr\.?|chief|lead|principal|revenue|accounting"
    r"|credit|cost|business|project|commercial|budget|fund|product|sales|operations)\s+)"
    r"controller\b(?!\s+(?:engineer|designer|developer|architect|design|verification|validation"
    r"|firmware|software|hardware|lead engineer))"
)


def family_named(text: str) -> str | None:
    """The family `text`'s own words name, by the precedence every posting is
    filed with: specialised families before software engineering's catch-all
    `engineer`, and a management title keeps its specialisation. Without
    `classify_role`'s chief-of-staff, segment and team rules, which read a
    posting title, not a search."""
    return _first_family(text)


def classify_department(text: str) -> str | None:
    """Classify department/team text using conservative domain-only phrases."""
    hay = " ".join(text.lower().replace("/", " / ").split())
    # Preserve the common compact spelling after whitespace normalization.
    hay_compact = hay.replace("ai / ml", "ai/ml")
    for group in ROLE_GROUPS:
        if any(keyword in hay_compact for keyword in group.department_keywords):
            return group.slug
    return None


def role_display(slug: str | None) -> str:
    if slug is None:
        return "Other"
    g = _BY_SLUG.get(slug)
    return g.display if g else slug


def default_enabled_slugs() -> list[str]:
    return [g.slug for g in ROLE_GROUPS if g.default_enabled]


def all_slugs() -> list[str]:
    return [g.slug for g in ROLE_GROUPS]


def get_group(slug: str) -> RoleGroup | None:
    return _BY_SLUG.get(slug)


#: Who is paid on commission, for a posting that defines its pay range per kind
#: of role ("base salary for non-sales roles, on-target earnings for sales roles").
#: Sales sells. Pre-sales engineers and customer success are on
#: variable pay at some employers and not others, so their family cannot say.
_SELLING_FAMILIES = frozenset({"sales_business_development"})
_COMMISSION_VARIES = frozenset({"solutions_sales_eng", "customer_success"})
#: A customer-facing architect filed under another family: an "Applied AI
#: Architect" sits in ML research, yet its posted ranges can top the base the
#: employer files for the role, as on-target earnings would.
_CUSTOMER_ARCHITECT_RE = re.compile(r"\bapplied\s+ai\b[^,]*\barchitect|\b(?:solutions?|customer|field)\s+architect", re.I)


def sells(family: str | None, title: str | None = None) -> bool | None:
    """True for a sales role, False for a role that is not, None when it cannot
    be told (no family, a family paid on commission only sometimes, or a
    customer-facing architect title)."""
    if family is None or family in _COMMISSION_VARIES:
        return None
    if title and _CUSTOMER_ARCHITECT_RE.search(title):
        return None
    return family in _SELLING_FAMILIES
