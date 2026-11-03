"""Domain vocabulary: *what the work is about*, orthogonal to what the role is.

`family` answers "is this an engineering manager?"; `domain` answers "an
engineering manager of what?". A fulfillment, supply-chain, facilities or
corporate-operations manager is correctly classified as a management role, and
irrelevant to someone looking for AI/infrastructure leadership. No other axis
can express that.

Two inputs, because coverage is uneven and neither alone is enough:

1. **The employer's own category field**, such as a `department` value
   ("Fulfillment & Operations Management") or a `team` value. These are
   authoritative, enumerable, and stable.
2. **Title org-path keywords.** The only signal for an employer whose category
   field is empty or only names the company itself.

Per-company category maps live on the company's `TitleProfile`; the keyword
fallback is shared. A row with neither is `None` — honestly unclassified, never
guessed into a bucket, because a wrong domain hides a job the user wanted.

**How a keyword matches.** Whole words, never substrings: a substring match
fires `construction` on "Neural Reconstruction", `soc` on "Social Advertising",
and could never list a bare `ai` because it is inside "maintain". The text is
lowercased with `-`/`_` read as spaces (some employers' teams are slugs, and
`team-last-mile` must match `last mile`). A keyword also matches its plural
(`device` -> "devices"). A trailing `*` makes it a stem (`health*` ->
"healthcare"); a leading `*` lets it end a compound (`*security` ->
"cybersecurity"); both, an infix (`*cloud*` -> "iCloud", "CloudFront").

**Kinds are display-only.** `kind` groups the worlds for reading — business
functions (almost always what a seeker hides), technology, industries — and
never enters the gate. Building a product and running the matching department
are different worlds of different kinds: `payments_fintech` (industry) beside
`finance_accounting` (function), `advertising` (industry) beside
`marketing_brand` (function). That is exactly the distinction `kind` exists
for, and the one a seeker filters on.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from tracker.schema import RawJob


FUNCTION, TECHNOLOGY, INDUSTRY = "function", "technology", "industry"
KINDS: tuple[str, ...] = (FUNCTION, TECHNOLOGY, INDUSTRY)


@dataclass(frozen=True)
class DomainGroup:
    slug: str
    display: str
    # Matched against the category text, the title's org path, and the whole
    # title — as whole words, with the stem syntax in the module docstring.
    keywords: tuple[str, ...] = field(default_factory=tuple)
    # Required: a world with no kind would fall out of every grouped listing.
    kind: str = field(kw_only=True)
    # What the world covers, in one line under its name on the Interests card.
    # Written from the keywords, never from the postings' department names,
    # which describe the matched postings rather than the world. A short list
    # that repeats no word of the name and fits one line on the narrowest card.
    hint: str = field(kw_only=True)


# Ordered: the first match wins, so specific domains precede broad ones. Derived
# from the measured vocabulary of the in-scope corpus, not invented.
DOMAIN_GROUPS: tuple[DomainGroup, ...] = (
    DomainGroup(
        "logistics_fulfillment",
        "Logistics & Fulfillment",
        ("fulfillment", "supply chain", "transportation", "last mile", "delivery station",
         "warehouse", "instock", "middle mile", "hub delivery", "logistics", "shipping",
         "freight"),
        kind=FUNCTION,
        hint="Supply chain, warehouses",
    ),
    DomainGroup(
        "facilities_realestate",
        "Facilities & Real Estate",
        ("facilities", "real estate", "maintenance", "construction", "engg ops",
         "engineering operations", "data centre engineering"),
        kind=FUNCTION,
        hint="Buildings, construction",
    ),
    DomainGroup(
        "retail_commerce",
        "Retail & Commerce",
        ("retail", "grocery", "whole foods", "selling partner", "merchant", "storefront",
         "marketplace", "buying", "consumables", "commerce", "e commerce", "ecommerce",
         "seller"),
        kind=INDUSTRY,
        hint="Marketplaces, grocery",
    ),
    # Building an ads PRODUCT and doing a company's MARKETING are different
    # work, and the seeker hiding one rarely means the other: "Search Ads Data
    # Platform" is not "Marketing & PR".
    DomainGroup(
        "advertising",
        "Advertising",
        ("advertis*", "ads", "sponsored products", "ad tech", "adtech"),
        kind=INDUSTRY,
        hint="Ad tech, programmatic",
    ),
    DomainGroup(
        "marketing_brand",
        "Marketing & Brand",
        ("marketing", "brand", "demand generation", "media & pr", "communications"),
        kind=FUNCTION,
        hint="Demand gen, PR, comms",
    ),
    DomainGroup(
        "media_entertainment",
        "Media & Entertainment",
        # Not bare `content`: it named product marketing, SEO, content finance
        # and customer data storage as often as it named media.
        ("prime video", "studios", "music", "youtube", "gaming", "games", "content platform",
         "streaming", "sports"),
        kind=INDUSTRY,
        hint="Streaming, games, music",
    ),
    DomainGroup(
        "public_sector",
        "Public Sector & Defense",
        ("public sector", "federal", "national security", "defense", "government", "sled",
         "public policy", "aerospace", "kuiper", "leo for government"),
        kind=INDUSTRY,
        hint="Federal, state, aerospace",
    ),
    DomainGroup(
        "health_bio",
        "Health & Life Sciences",
        ("health*", "clinical", "medical", "life sciences", "hcls", "biolog*"),
        kind=INDUSTRY,
        hint="Clinical, medical, biotech",
    ),
    DomainGroup(
        "security_privacy",
        "Security, Privacy & Trust",
        # Not `compliance`: in scope it named trade, tax, asset and eco-design
        # regulatory compliance — none of it security work.
        ("*security", "privacy", "trust & safety", "trust and safety", "safeguards",
         "fraud", "loss prevention", "abuse"),
        kind=TECHNOLOGY,
        hint="Fraud, abuse, safety",
    ),
    DomainGroup(
        "ai_ml",
        "AI & Machine Learning",
        ("machine learning", "applied ai", "artificial intelligence", "genai*", "gen ai",
         "generative ai", "foundation model", "applied science", "ai research", "ml science",
         "deep learning", "agentic", "inference", "model behavior", "ai platform",
         "ai", "ml", "ai/ml", "llm", "coreai", "multimodal", "siri"),
        kind=TECHNOLOGY,
        hint="LLMs, applied science",
    ),
    DomainGroup(
        "cloud_infra",
        "Cloud & Infrastructure",
        ("aws", "*cloud*", "compute", "infrastructure", "infra", "data center", "datacenter",
         "kubernetes", "networking", "storage", "reliability", "platform engineering",
         "distributed systems", "kernel", "azure", "gcp", "serverless", "tpu", "gpu"),
        kind=TECHNOLOGY,
        hint="Compute, data centers",
    ),
    DomainGroup(
        "devices_hardware",
        "Devices & Hardware",
        ("hardware", "silicon", "asic", "soc", "firmware", "device", "robotics", "sensor",
         "chip", "wearable", "camera"),
        kind=TECHNOLOGY,
        hint="Chips, wearables, robotics",
    ),
    DomainGroup(
        "data_analytics",
        "Data & Analytics",
        ("data science", "business intelligence", "analytics", "data engineering",
         "data & insights", "data and insights", "data platform"),
        kind=TECHNOLOGY,
        hint="BI, dashboards, pipelines",
    ),
    DomainGroup(
        "developer_platform",
        "Developer & Productivity Platform",
        # Not bare `productivity` or `office`: they named Apple's internal
        # employee-IT and an accounting programme office.
        ("developer", "workspace", "developer productivity", "collaboration", "devrel",
         "api platform", "sdk", "devtools"),
        kind=TECHNOLOGY,
        hint="Tooling, APIs, SDKs",
    ),
    # A payments PRODUCT is an industry a seeker chooses; a company's own
    # finance department is a function they almost always hide: "Stores
    # FinTech" is not "Finance & Accounting".
    DomainGroup(
        "payments_fintech",
        "Payments & Fintech",
        ("payments", "fintech", "billing", "treasury", "transactions"),
        kind=INDUSTRY,
        hint="Billing, wallets, treasury",
    ),
    DomainGroup(
        "finance_accounting",
        "Finance & Accounting",
        ("finance", "accounting", "tax", "procurement", "audit", "controller",
         "financial planning"),
        kind=FUNCTION,
        hint="FP&A, tax, audit",
    ),
    DomainGroup(
        "people_workplace",
        "People & Workplace",
        ("human resources", "people operations", "recruiting", "talent", "workforce staffing",
         "administrative support", "employee experience"),
        kind=FUNCTION,
        hint="HR, recruiting, talent",
    ),
    DomainGroup(
        "customer_support",
        "Customer Support & Service",
        # Not `support engineering`: an employer uses it as a data-center
        # engineering category ("Operations, IT, & Support Engineering").
        ("customer service", "customer support", "user operations", "customer experience"),
        kind=FUNCTION,
        hint="Help desk, user ops",
    ),
    DomainGroup(
        "corporate_operations",
        "Corporate Operations",
        ("corporate operations", "business operations", "strategy and operations",
         "bizops", "corporate functions", "operations management"),
        kind=FUNCTION,
        hint="Strategy, planning, BizOps",
    ),
)

_BY_SLUG = {g.slug: g for g in DOMAIN_GROUPS}

_NON_WORD_JOINERS = re.compile(r"[-_]+")


def keyword_pattern(keyword: str) -> re.Pattern[str]:
    """One keyword as a whole-word pattern; see the module docstring for `*`."""
    kw = keyword.strip()
    lead, stem = kw.startswith("*"), kw.endswith("*")
    body = re.escape(kw.strip("*").strip()).replace(r"\ ", r"\s+")
    head = r"[a-z0-9]*" if lead else r"(?<![a-z0-9])"
    tail = r"[a-z0-9]*" if stem else r"(?:e?s)?(?![a-z0-9])"
    return re.compile(f"{head}{body}{tail}")


_COMPILED: tuple[tuple[str, tuple[re.Pattern[str], ...]], ...] = tuple(
    (g.slug, tuple(keyword_pattern(k) for k in g.keywords)) for g in DOMAIN_GROUPS
)

# Company-discovery sector -> the worlds a company in that sector *evidences*.
# Consumed by profile inference: tracking companies from
# a sector is a weak positive signal for its worlds. Conservative on purpose —
# a sector maps only where membership genuinely implies the work's subject
# (faang/technology/consulting say nothing about WHAT the work is about).
# Keys are validated against `company_discovery.SECTORS` and values against
# `all_slugs()` by tests, without either module importing the other.
SECTOR_WORLDS: dict[str, tuple[str, ...]] = {
    "faang": (),
    "ai": ("ai_ml",),
    "technology": (),
    "gaming": ("media_entertainment",),
    "consulting": (),
    "fintech": ("payments_fintech",),
    "quant": ("payments_fintech",),
    "cybersecurity": ("security_privacy",),
    "cloud-data-devtools": ("cloud_infra", "data_analytics", "developer_platform"),
    "semiconductors": ("devices_hardware",),
    "robotics": ("devices_hardware", "public_sector"),
    "consumer": ("retail_commerce",),
}


def classify_domain_text(text: str) -> str | None:
    """First domain whose vocabulary appears in this text, or None."""
    matches = match_domains(text)
    return matches[0] if matches else None


def match_domains(text: str) -> list[str]:
    """EVERY domain whose vocabulary appears in this text, in declared order.

    Multi-label on purpose: a posting can genuinely live in two worlds ("ML
    Engineering Manager, Ads Ranking" is both ads and AI), and a single
    first-match label would let the scope gate drop it for a user who enabled
    the other world. The scope gate passes a row if ANY of its domains is
    enabled, so recording all of them is what keeps the axis fail-soft.
    """
    if not text:
        return []
    hay = _NON_WORD_JOINERS.sub(" ", text.lower())
    return [
        slug for slug, patterns in _COMPILED if any(p.search(hay) for p in patterns)
    ]


def source_category(job: RawJob) -> str:
    """The employer's own category text, minus useless self-references.

    An employer may stamp its own name as the team (`team="Google"`); a company
    naming itself carries no information and must not be read as vocabulary.
    """
    company = (job.company or "").lower().replace("-", " ")
    parts = []
    for value in (job.department, job.team):
        if not value or not value.strip():
            continue
        if value.strip().lower().replace("-", " ") == company:
            continue
        parts.append(value.strip())
    return " ".join(parts)


def domain_display(slug: str | None) -> str:
    if slug is None:
        return "Unclassified"
    group = _BY_SLUG.get(slug)
    return group.display if group else slug


def all_slugs() -> list[str]:
    return [g.slug for g in DOMAIN_GROUPS]


def get_group(slug: str) -> DomainGroup | None:
    return _BY_SLUG.get(slug)
