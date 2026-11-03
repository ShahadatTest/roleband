"""The leveling model's record types.

One rung is stated once. A company's ladder is an ordered list of `Rung`s, and
every other answer about it (rung -> band, band -> pay
lookup label, band -> seed pay, band -> bonus target, the Walk guide's cells)
is a function over these records in `tracker.levels.ladder` and
`tracker.levels.pay`, never a second copy.

Pure: no DB, no network, no other tracker tier.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from tracker.schema import LevelBand

#: The family a ladder belongs to, in the taxonomy's own slugs. The engineering
#: IC ladder is the one every company states; it is also the one pay lookups
#: read when no family is asked for.
ENGINEERING = "software_engineering"
#: A company-wide grade every function shares (Google's L3-L10). A company
#: with family ladders states its grade once on this row: pay and the Walk
#: guide read it, and the mapper falls back to it for a family with no ladder
#: of its own. A company without one uses its engineering ladder as its row.
COMPANY_ROW = "company"


@dataclass(frozen=True)
class Rung:
    """One rung of one company's ladder.

    `band` is the company's own word for the rung (a rung titled Senior is
    senior). `code` is how the company names it in the Walk guide; `aliases`
    are every other spelling of THIS rung found in data ("SDE III" is Amazon's
    L6). No spelling may belong to two rungs of one company.
    """

    code: str
    band: LevelBand
    aliases: tuple[str, ...] = ()
    #: The label pay rows key this rung by, when it is not `code`.
    pay_label: str | None = None
    people_manager: bool = False
    #: Seed median total pay, USD a year: the fallback when no live figure
    #: resolves. None = the rung has no seed.
    seed_median_usd: int | None = None
    #: (low, high) annual bonus target as a share of base, where the company's
    #: policy states one for this rung.
    bonus_target: tuple[float, float] | None = None

    @property
    def spellings(self) -> tuple[str, ...]:
        return (self.code, *self.aliases)

    @property
    def lookup_label(self) -> str:
        """The label pay tables key this rung by."""
        return self.pay_label or self.code


@dataclass(frozen=True)
class Ladder:
    """A company's rungs for one family, lowest first (position is rank)."""

    family: str
    rungs: tuple[Rung, ...]
    #: A reviewed ladder: the Walk's level guide can show it.
    guide: bool = False
    #: True: the code grades every function (Google L5). False: only `tracks`
    #: (Apple ICT is Individual Contributor Technical); other tracks read the
    #: seniority word instead.
    company_wide: bool = True
    tracks: tuple[str, ...] = ()
    #: True: the employer's titles state no level beyond these rungs (its
    #: postings print none), so a band without a rung here is unstated, not
    #: skipped.
    flat: bool = False
    #: Taxonomy families besides `family` whose postings this ladder levels
    #: (Google's IC ladder also reads ML research and SRE titles). A family
    #: with no ladder of its own reads the company row.
    families: tuple[str, ...] = ()

    def levels(self, family: str | None) -> bool:
        """True when a posting of this taxonomy family reads this ladder."""
        return family is not None and (family == self.family or family in self.families)


#: How a `RungTitle` phrase meets a title's words.
PHRASE_MATCHES = ("exact", "prefix", "word")
#: The kind of evidence behind an atlas fact: a kind, never a site.
EVIDENCE_BASES = (
    "employer_titles", "employer_posted_ranges", "government_disclosure", "employer_published", "reviewed_judgement",
    # Not yet checked against an employer or a filing. Reverifying a row
    # replaces it.
    "unverified",
)


@dataclass(frozen=True)
class RungTitle:
    """A phrase a company uses for one of its rungs in its postings ("senior
    manager" is Apple's M2, say): a title whose words meet it reads that rung.
    Phrases, never regexes, so a person reviewing the row reads
    exactly what it matches."""

    company: str
    family: str  # the ladder the rung is on (`COMPANY_ROW` or a taxonomy family)
    code: str
    phrase: str  # lowercase words, single-spaced: what the title says
    #: exact: the title's words are the phrase; prefix: they start with it;
    #: word: it appears among them as whole words.
    match: str
    as_of: date
    basis: str  # one of EVIDENCE_BASES


@dataclass(frozen=True)
class CompanyLevels:
    slug: str
    ladders: tuple[Ladder, ...] = ()
    #: A sibling employer that shares this one's ladder (google-deepmind ->
    #: google). Resolution: own ladders first, then the parent's.
    parent: str | None = None
    #: Codes the employer PRINTS on a posting ("Product Management IC5"),
    #: banded as calibrated. Kept at band level because which numbered rung
    #: each printed code is has not been measured, only its band.
    printed: dict[str, LevelBand] = field(default_factory=dict)
    #: The board field the employer prints its rung in (a custom field on the
    #: listing, read into `raw_level`). None: the rung,
    #: if printed, is in the posting's text (Microsoft's pay sentence).
    printed_field: str | None = None
    #: A bare "Senior" in this employer's titles is weak evidence: read senior,
    #: never confirmed (Apple, whose ICT ladder is not spoken in titles).
    senior_unconfirmed: bool = False


# How the annual bonus is determined.
BONUS_PCT_OF_BASE = "pct_of_base"  # a level-set target percentage of base salary
BONUS_NONE = "none"  # the company pays no annual cash bonus
BONUS_UNVERIFIED = "unverified"

# How the equity grant is sized.
EQUITY_DOLLAR_BY_LEVEL = "dollar_grant_by_level"  # a $ value per level, units at grant price
EQUITY_TC_TARGET_MINUS_BASE = "tc_target_minus_base"  # grant fills a per-level TC target
EQUITY_EMPLOYEE_ELECTION = "employee_election"  # employee picks the cash/stock mix
EQUITY_NONE = "none"
EQUITY_UNVERIFIED = "unverified"

#: The values a company's `bonus_rule` and `equity_rule` may state: the atlas
#: refuses any other, and the API's offer contract is pinned to the same names.
BONUS_RULES = frozenset({BONUS_PCT_OF_BASE, BONUS_NONE, BONUS_UNVERIFIED})
EQUITY_RULES = frozenset({
    EQUITY_DOLLAR_BY_LEVEL, EQUITY_TC_TARGET_MINUS_BASE, EQUITY_EMPLOYEE_ELECTION, EQUITY_NONE, EQUITY_UNVERIFIED,
})

# Who says a pay fact. `employer`: the employer states it (its filings, postings,
# pages). `estimated`: a value used where the employer does not state the fact.
STATED_BY_EMPLOYER = "employer"
STATED_BY_ESTIMATED = "estimated"
STATED_BY = (STATED_BY_EMPLOYER, STATED_BY_ESTIMATED)
# A fact searched for and not found: employer sources and estimated pay were read
# and nobody states it. An answer with a date, never a value: the field stays
# unverified, and pay math and the UI read it as unverified.
VALUE_UNKNOWN = "unknown"


@dataclass(frozen=True)
class PayPolicy:
    """How a company constructs an offer. A field left None is "unverified",
    which the UI treats as unknown, never as zero. Per-rung facts (seed pay,
    bonus target) live on the rung."""

    company: str
    bonus_rule: str = BONUS_UNVERIFIED
    equity_rule: str = EQUITY_UNVERIFIED
    #: The vehicle where no scraped field expresses it ("cash_election": Netflix
    #: lets the employee choose cash or stock). None = not curated.
    equity_vehicle: str | None = None
    # Annual vest fractions as the company states them ("5/15/40/40"). None = unverified.
    vesting: str | None = None
    #: A company that grants equity one year at a time ("one_year") or fully vested at grant
    #: ("vested_at_grant"), where a multi-year fraction would mislead. Shown on the
    #: company profile only; the job package never reads it.
    grant_term: str | None = None
    # Cash paid in early years explicitly to offset a back-loaded vest.
    sign_on_bridges_vesting: bool = False
    base_cap_usd: int | None = None
    # Annual equity refresh sized by performance rating.
    annual_refresh: bool | None = None
    verified: date | None = None
    #: The facts above that are estimated, not employer-stated, in `_POLICY_FACTS`
    #: order; every other stated fact is the employer's own.
    estimated: tuple[str, ...] = ()
    #: Facts searched for and not found (`VALUE_UNKNOWN`), in `_POLICY_FACTS` order.
    unknown: tuple[str, ...] = ()

    @property
    def is_verified(self) -> bool:
        return self.verified is not None

    def stated_by(self, fact: str) -> str:
        return STATED_BY_ESTIMATED if fact in self.estimated else STATED_BY_EMPLOYER


@dataclass(frozen=True)
class CompanyIdentity:
    """Who a company is, from our own dataset: always ours,
    never switched to a plugin. A None is "not researched yet", never "no": a
    company whose `listed` is None is neither listed nor private as far as we know."""

    slug: str
    display_name: str | None = None
    listed: bool | None = None
    ticker: str | None = None
    exchange: str | None = None
    cik: int | None = None
    grant_ticker: str | None = None
    website: str | None = None
    hq_city: str | None = None
    headcount: int | None = None
    year_founded: int | None = None
    logo: str | None = None
    brand_color: str | None = None
    basis: str | None = None  # one of EVIDENCE_BASES, for the researched cells
