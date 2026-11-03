"""How each company constructs an offer, and the pay each rung reads.

Each company's policy is data (`tracker/levels/atlas/company_facts.csv`, one fact
per row, each saying who states it); this module reads it. The rules the package is
modelled on:

1. **Base** is the posted band. A fact when the posting says "base"; see
   `intelligence.schema.derive_pay_basis`.
2. **Bonus is a percentage of base, set by level, by policy**, or there is none.
   `comp_package` scales it off base. A company whose policy is no annual bonus gets
   none: a heuristic that invents one for it is wrong by construction.
3. **Equity is a dollar amount sized by level, never a multiple of base.** It comes
   from its own per-level budget; at some companies a higher base means less equity
   for the same target total. Scaling equity off the two ends of a posted base band
   manufactures a spread out of geography. The estimator is the measured per-level
   grant with equity's OWN uncertainty, the most negotiated component: the centre is
   knowable, the band must be wide and labelled.
4. **Year-1 cash is not annualised equity.** Vesting schedules and sign-on cash
   differ by company. The package shows annualised equity ("per year, vests over
   time"); a year-1 view is a different, also-legitimate number.
5. **No same-company, same-level family premium.** Scientist and engineer ladders at
   one company and rung pay alike; the premium that exists is between companies
   (already in their own rows) and in the tail (band width). Never add a family
   multiplier. At a company with no annual bonus, a measured "bonus" is one-time
   sign-on cash, not annual.

Per-RUNG facts (seed pay, bonus target) live on the rungs; every per-band answer
below is read through `ladder.rung_for_band`, so pay is keyed by rung, never by band.
A field left None is "unverified", which the UI must treat as unknown, never as zero.
"""

from __future__ import annotations

from tracker.levels.atlas import load_pay_policies
from tracker.levels.ladder import rung_for_band
from tracker.levels.model import (
    BONUS_NONE,
    BONUS_PCT_OF_BASE,
    BONUS_UNVERIFIED,
    EQUITY_UNVERIFIED,
    PayPolicy,
)
from tracker.schema import LEVEL_BAND_ORDER, LevelBand, parse_band

#: Each company's offer policy, from `tracker/levels/atlas/company_facts.csv`:
#: one fact per row; an absent fact is unverified, never zero.
PAY_POLICIES: dict[str, PayPolicy] = load_pay_policies()

_UNKNOWN = PayPolicy("")


def policy_for(company: str) -> PayPolicy:
    """The company's policy, or an all-unverified one: never a guess dressed as fact."""
    return PAY_POLICIES.get(company, _UNKNOWN)


def _band(band: LevelBand | str | None) -> LevelBand | None:
    try:
        return parse_band(band) if band else None
    except ValueError:  # a band string outside the enum: not ours to interpret
        return None


def bonus_ratio_for(company: str, band: LevelBand | str | None) -> float | None:
    """The policy target bonus as a share of base: 0.0 for a no-bonus company, the
    midpoint of the rung's target range where one is known, None when unverified.

    None means "use the next estimator", not "no bonus": the distinction between a
    company that pays none and one we have not checked is the whole point of the table.
    """
    policy = policy_for(company)
    if policy.bonus_rule == BONUS_NONE:
        return 0.0
    if policy.bonus_rule != BONUS_PCT_OF_BASE:
        return None
    level = _band(band)
    rung = rung_for_band(company, level) if level else None
    if rung is None or rung.bonus_target is None:
        return None
    low, high = rung.bonus_target
    return (low + high) / 2


def vesting_for(company: str) -> str | None:
    """The stated vest schedule, for the profile's `vesting_schedule` claim."""
    return policy_for(company).vesting


def equity_vehicle_for(company: str) -> str | None:
    """The curated equity vehicle where no scraped field expresses it."""
    return policy_for(company).equity_vehicle


#: The company profile's vesting value for a company that grants equity one year at a time or fully
#: vested: a code the dashboard words, never a fraction a job package would read.
PROFILE_VESTING = {"one_year": "one_year_grants", "vested_at_grant": "vested_at_grant"}


def profile_vesting(company: str) -> tuple[str, str] | None:
    """(value, source) for the company profile's vesting claim: the stated schedule, else the
    grant term as a code; None when neither is known. Jobs read `vesting_for`, never this."""
    policy = policy_for(company)
    if policy.vesting:
        return policy.vesting, policy.stated_by("vesting")
    if policy.grant_term:
        return PROFILE_VESTING[policy.grant_term], policy.stated_by("grant_term")
    return None


#: The offer facts the company profile states on their own rows, in its order.
#: Vesting and the equity vehicle are not here: the profile shows them as resolved
#: fields, claimed from this policy (`profiles.seed.claim_pay_policy`).
PROFILE_OFFER_FACTS = ("equity_rule", "bonus_rule", "annual_refresh", "sign_on_bridges_vesting", "base_cap_usd")
#: Atlas fact -> the resolved profile field it answers.
_PROFILE_FIELD_OF = {"vesting": "vesting_schedule", "equity_vehicle": "equity_vehicle"}


def profile_offer(company: str) -> dict | None:
    """How the company builds an offer, for its profile; None when the atlas has
    not researched it, which is not the same as researched and found nothing.

    Each fact is stated (a value and who states it) or searched and not found
    (`value` and `stated_by` null). A fact that is neither is left out:
    `sign_on_bridges_vesting` and `base_cap_usd` are recorded only where they
    hold, so their absence states nothing. `unknown_fields` names the resolved
    profile fields the atlas searched for and found nothing, so the profile can
    say so instead of a bare dash."""
    if company not in PAY_POLICIES:
        return None
    p = PAY_POLICIES[company]
    stated: dict[str, str | int | bool | None] = {
        "equity_rule": None if p.equity_rule == EQUITY_UNVERIFIED else p.equity_rule,
        "bonus_rule": None if p.bonus_rule == BONUS_UNVERIFIED else p.bonus_rule,
        "annual_refresh": p.annual_refresh,
        "sign_on_bridges_vesting": p.sign_on_bridges_vesting or None,
        "base_cap_usd": p.base_cap_usd,
    }
    facts: list[dict[str, str | int | bool | None]] = []
    for fact in PROFILE_OFFER_FACTS:
        if fact in p.unknown:
            facts.append({"fact": fact, "value": None, "stated_by": None})
        elif stated[fact] is not None:
            facts.append({"fact": fact, "value": stated[fact], "stated_by": p.stated_by(fact)})
    # A grant term answers the vesting row, so vesting searched-and-not-found
    # with a stated term is not unknown on the profile.
    unknown_fields = [
        field for fact, field in _PROFILE_FIELD_OF.items()
        if fact in p.unknown and not (fact == "vesting" and p.grant_term)
    ]
    return {
        "verified_on": p.verified.isoformat() if p.verified else None,
        "facts": facts,
        "unknown_fields": unknown_fields,
    }


def stated_by(company: str, fact: str) -> str:
    """`employer` or `estimated`: who says this fact. Ask only of a stated fact."""
    return policy_for(company).stated_by(fact)


def describe(company: str) -> dict:
    """The presentable facts for a job's package payload. Unverified fields are None."""
    p = policy_for(company)
    return {
        "verified": p.is_verified,
        "bonus_rule": None if p.bonus_rule == BONUS_UNVERIFIED else p.bonus_rule,
        "equity_rule": None if p.equity_rule == EQUITY_UNVERIFIED else p.equity_rule,
        "vesting": p.vesting,
        "sign_on_bridges_vesting": p.sign_on_bridges_vesting,
        "base_cap_usd": p.base_cap_usd,
        "annual_refresh": p.annual_refresh,
        # `grant_term` is the company profile's: a job's package never names it.
        "estimated": [f for f in p.estimated if f != "grant_term"],
        "unknown": list(p.unknown),
    }


# --- the rung a band reads its pay from ----------------------------------------

# The spread that turns a point median into a range.
_SPREAD = 0.20


#: Pay reference data starts at Senior (`enrich.comp.CompResolver` asks for no
#: estimate below it), so no band below it names a pay rung: a per-band
#: baseline there stays the median row rather than the band's lowest rung.
_PRICED_FROM = LEVEL_BAND_ORDER[LevelBand.SENIOR.value]
_BAND_WORDS = frozenset(b.value for b in LevelBand)


def pay_label(company: str, band: LevelBand, family: str | None = None) -> str | None:
    """The label pay rows key this band's rung by, or None when
    the company has no ladder or the band sits below the priced range."""
    if LEVEL_BAND_ORDER[band.value] < _PRICED_FROM:
        return None
    rung = rung_for_band(company, band, family)
    if rung is None:
        return None
    # A rung pinned to a band word is looked up by the band asked for, never by
    # its own: a band with no rung of its own reads the rung below, but by the
    # word it was asked for, so a ladder topping out at Senior never reads staff
    # pay off Senior's row.
    if rung.pay_label in _BAND_WORDS:
        return band.value
    return rung.lookup_label


def level_label(company: str, band: LevelBand) -> str:
    """`pay_label`, falling back to the band word for a company with no ladder
    (the lookup then finds nothing and the next estimator answers)."""
    return pay_label(company, band) or band.value


def seed_range(company: str, band: LevelBand) -> tuple[int, int, int] | None:
    """(low, median, high) seed pay for the rung this band reads, or None if unseeded."""
    rung = rung_for_band(company, band) if LEVEL_BAND_ORDER[band.value] >= _PRICED_FROM else None
    median = rung.seed_median_usd if rung is not None else None
    if median is None:
        return None
    return int(median * (1 - _SPREAD)), median, int(median * (1 + _SPREAD))
