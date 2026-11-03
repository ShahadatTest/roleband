"""Classify a posting into a role track.

Deterministic and title-first. Crucially this does NOT reuse the seniority keyword
sets in ``level_mapper`` — those treat ``distinguished``/``fellow`` as a high band,
but those are the *most senior individual contributors*, not managers. The track
classifier keys off explicit people-leadership words, with a guard that keeps
distinguished/fellow/architect on the technical side even when senior.

"Manager" is the one leadership word that usually is not. In a
business function the words before it name the WORK: a Customer Success
Manager, a Product Marketing Manager, a Tax Manager or a Technical Account
Manager leads no one. There leadership is spelled "Manager, X", "Manager of X",
"Senior Manager", or a people form ("Operations Manager" running a site, "Sales
Manager"). In a technical family the words before it name the TEAM ("Applied
Science Manager"), so there it stays leadership, except for the same IC heads
when a business title lands in a technical family.
"""

from __future__ import annotations

import re

from tracker.schema import RoleTrack

# Unambiguous people/org-leadership signals. "manager" is read separately.
_MGMT_STRONG = (
    "director",
    "head of",
    "vp ",
    "vice president",
    "svp",
    "evp",
)
# Senior IC signals that must never be read as management, even next to "chief".
_IC_STRONG = ("distinguished", "fellow", "architect")

_BUSINESS_CUSTOMER_FAMILIES = frozenset(
    {
        "sales_business_development",
        "customer_success",
        "marketing_communications",
        "business_operations_strategy",
        "finance_accounting",
        "people_recruiting",
        "legal_policy",
    }
)

# Words before "manager" that only rank the person, never name the work.
_RANK = frozenset(
    {"senior", "sr", "staff", "principal", "lead", "associate", "assoc", "group", "global", "i", "ii", "iii"}
)
# "<phrase> Manager" forms that lead people in any family.
_PEOPLE_PHRASES = frozenset(
    {
        "operations", "sales", "area", "district", "general", "site", "store", "shift",
        "team", "people", "engineering", "software engineering", "software development",
        "hiring", "customer service", "customer support", "support", "sales development",
        "factory", "plant", "warehouse", "facility", "fulfillment", "station", "office",
    }
)
# The last word of a "<phrase> Manager" that names individual work. A business
# title that a family rule filed under a technical family still carries it.
_IC_HEADS = frozenset(
    {
        "account", "accounts", "success", "marketing", "partner", "partnerships", "channel",
        "growth", "media", "community", "implementation", "tax", "accounting", "audit",
        "finance", "treasury", "procurement", "category", "commodity", "communications",
        "relations", "compliance", "risk", "incident", "campaign", "brand", "content",
        "event", "events", "alliance", "alliances", "development", "territory", "chain",
    }
)
_MANAGER = re.compile(r"\bmanagers?\b")
_CLAUSE_BREAK = re.compile(r"[,(|:;–—]| - ")
_WORD = re.compile(r"[a-z&]+")


def _manager_phrase(title: str) -> str | None:
    """The words before the first "manager" in its clause, rank words dropped.

    None when the title has no "manager"; "" when nothing but rank precedes it
    ("Senior Manager, Communications", "Manager of Sales Development")."""
    lowered = title.lower().replace("/", " ")
    match = _MANAGER.search(lowered)
    if match is None:
        return None
    clause = _CLAUSE_BREAK.split(lowered[: match.start()])[-1]
    words = _WORD.findall(clause)
    # "Accounting Senior Manager": the grade sits against "manager", not the work.
    if words and words[-1] in ("senior", "sr"):
        return ""
    while words and words[0] in _RANK:
        words.pop(0)
    while words and words[-1] in _RANK:
        words.pop()
    return " ".join(words)


def _manager_leads(phrase: str, family: str | None) -> bool:
    """Whether a "<phrase> Manager" title leads people (see module docstring)."""
    if phrase == "" or phrase in _PEOPLE_PHRASES:
        return True
    if phrase.split()[-1] in _IC_HEADS:
        return False
    return family not in _BUSINESS_CUSTOMER_FAMILIES


def classify_track(title: str, family: str | None) -> RoleTrack:
    """Return the role track for a posting, given its title and classified family."""
    # Product/Program managers are their own bucket regardless of the "manager" word.
    if family in (
        "product_management",
        "program_management",
        "technical_program_management",
    ):
        return RoleTrack.PRODUCT_PROGRAM
    # Engineering management is definitionally management even if the title is terse.
    if family == "engineering_management":
        return RoleTrack.MANAGEMENT

    hay = f" {title.lower().strip()} "
    # Unambiguous management words win first (a "Director of Architecture" is a manager).
    if any(word in hay for word in _MGMT_STRONG):
        return RoleTrack.MANAGEMENT
    phrase = _manager_phrase(title)
    if phrase is not None and _manager_leads(phrase, family):
        return RoleTrack.MANAGEMENT
    # Senior-IC words keep the role technical (a "Chief Architect" is an IC, not a manager).
    if any(word in hay for word in _IC_STRONG):
        return RoleTrack.TECHNICAL
    # "Chief" not paired with an IC word is leadership (Chief Product Officer, Chief of Staff).
    if "chief " in hay:
        return RoleTrack.MANAGEMENT
    if family in _BUSINESS_CUSTOMER_FAMILIES:
        return RoleTrack.BUSINESS_CUSTOMER
    return RoleTrack.TECHNICAL
