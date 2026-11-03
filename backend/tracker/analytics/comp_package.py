"""The compensation package shown on a job: cash, bonus, equity — and how sure we are.

Two independent things about a role's pay, which the UI must never conflate:

  WHAT KIND of money it is   -> base / bonus / equity
  HOW SURE we are of it      -> stated by the employer, or estimated by us

A trustworthy `disclosed_pay_basis` is what makes this module possible. When the posting states a band AND we know that band is base salary, the base
figure is a HARD FACT. We anchor the package on it and scale only bonus and equity off
the company's measured base->bonus/equity ratios, so the one number we are certain of is
the one everything else is derived from.

When the employer states a figure but never says what it means (`unclear`), we do NOT
decompose it. Splitting a number whose
meaning the employer withheld would invent a fact the employer never stated. We
show it as-is beside the estimate and say the basis is unstated. Netflix is distinct:
its range is total compensation, but each employee elects the salary/stock-option mix,
so the total is stated while its component split is not.

Pure: no DB access. The API injects `baselines`, mirroring `comp_split.py`.
"""

from __future__ import annotations

from tracker.analytics.comp_market import us_rows
from tracker.analytics.comp_split import split_tc
from tracker.comp_providers.base import OUR_PAY_COUNTRY
from tracker.levels.ladder import rung_for_band
from tracker.levels.pay import bonus_ratio_for, pay_label
from tracker.levels.pay import describe as describe_policy
from tracker.schema import LevelBand, parse_band
from tracker.taxonomy.comp_families import borrow_rank

# How the base/bonus/equity ratios were obtained, worst case last. This is the honesty
# dial: a package scaled from another job family's ratios is NOT a measured split, and
# saying so is the difference between a real instrument and a plausible-looking one.
SPLIT_MEASURED = "measured"  # the company's own numbers for THIS family + level
SPLIT_CROSS_FAMILY = "cross_family"  # right level, different job family
SPLIT_HEURISTIC = "heuristic"  # no observed split at all; comp_split's guess

# Why a stated band was not broken into components.
NO_SPLIT_BASIS_UNCLEAR = "basis_unclear"
NO_SPLIT_HOURLY = "hourly"
NO_SPLIT_MONTHLY = "monthly"
NO_SPLIT_PERIOD_UNCLEAR = "period_unclear"
NO_SPLIT_EMPLOYEE_ELECTION = "employee_election"
NO_SPLIT_TOTAL = "total_compensation"
# A plugin answers pay and its rows state no split for this level: our heuristic
# is our data, so the figure stays whole.
NO_SPLIT_PLUGIN = "plugin_without_split"
# A plugin answers pay and has not read this company: it gave nothing to split,
# and ours is never put in its place.
NO_SPLIT_NOT_COVERED = "plugin_not_covered"
# Ours answers pay, and the posting's pay is not US pay (another country, or
# places in several): our split is measured on US pay only.
NO_SPLIT_NOT_US = "not_us_pay"

PROV_STATED = "stated"
PROV_ESTIMATED = "estimated"

# Does the band the employer posted look like the band we think this level pays?
# The two numbers come from different places -- the posting states its own range, the
# ladder measures a median -- so they can disagree, and the disagreement is a signal
# about the INPUTS: a posted band far above the measured base for its level usually
# means the level is wrong, not that the employer is generous.
VERDICT_CONSISTENT = "consistent"
VERDICT_STATED_ABOVE = "stated_above_measured"
VERDICT_STATED_BELOW = "stated_below_measured"

# Read over USD annual `base` bands that have a measured row for their own company x
# family x band. The ratio (posted TOP / measured median base) is NOT centred on 1.0 and
# cannot be -- the top of a range that spans locations and adjacent levels sits above a
# median by construction. So the bounds sit outside the ordinary spread rather than at
# 1.0; a tighter top would flag ordinary bands and say nothing. A band past either bound
# usually sits at the wrong level, in one direction or the other.
_RATIO_STATED_ABOVE = 1.50
_RATIO_STATED_BELOW = 0.75

# How the equity figure was arrived at. Equity is a DOLLAR GRANT SIZED BY LEVEL, from a
# separate budget -- Microsoft tables stock awards in dollars per level, Amazon sizes
# the grant to a per-level total-comp target with base capped (so a higher base buys
# LESS equity, not more). Scaling it off the two ends of a posted base band would
# manufacture an equity spread out of geography, from a band that only varies by market.
EQUITY_MEASURED_GRANT = "measured_grant"  # the company's own annualised grant at this band
EQUITY_RATIO = "ratio"  # nothing measured: a share of base, fallback only

# The grant is a median, so it needs a band of its own -- and that band must come from
# equity's distribution, never from the base band's width. A pay row carries one
# median per component, not its distribution.
#
# So this is a STATED TOLERANCE rather than a per-row measurement: 0.60-1.40 of the
# level's own median, at or outside the interquartile range of per-level equity
# distributions and well inside their p10-p90 spread -- wide enough not to imply a
# precision the median cannot carry, narrow enough to still say something. Replacing
# it with real per-row percentiles needs data that carries them and two new columns.
_EQUITY_SPREAD_LOW = 0.60
_EQUITY_SPREAD_HIGH = 1.40

# The package total and the reported TC median answer the same question from opposite
# ends, so ONE of them is the headline and the other is a check on it. They are not the
# same statistic -- the package is a stated base plus a modelled bonus plus a median
# grant, the market figure is a median total -- so they ordinarily disagree by a wide
# margin, and a warning at 25% would fire on ordinary bands and mean nothing. Past 50%
# the disagreement is more than the two statistics being different and usually means
# the level or the family is wrong.
MARKET_CONSISTENT = "consistent"
MARKET_DIVERGES = "diverges"
_MARKET_GAP_TOLERANCE = 0.50

# (company_slug, family, band) -> the company_comp_level row. `family` is our taxonomy
# family (`software_engineering`), as every stored row is keyed.
# Injected by the API so this module stays DB-free.
Baselines = dict[tuple[str, str | None, str], dict]


def choose_rung_row(company: str, band: str, candidates: list):
    """The ONE ladder row that stands for (company, band) among `candidates`.

    The row of the atlas rung the band reads its pay from (`levels.ladder.
    rung_for_band`), recognised by any spelling of that rung in the row's label
    or its aliases: two sources that name one rung differently pick the same
    row. Else the median candidate by base, ties broken by label: never
    physical row order. Shared by `select_baselines` and every other reader
    that keys a ladder by band, so the package, the observed splits and the
    median beside them read the same row.
    """
    if len(candidates) == 1:
        return candidates[0]
    spellings = _rung_spellings(company, band)
    named = sorted(
        (r for r in candidates if spellings & _row_spellings(r)),
        key=lambda r: (r.family or "", r.base_amount or 0),
    )
    ordered = sorted(
        candidates, key=lambda r: (r.base_amount or 0, r.level_label or "", r.family or "")
    )
    return named[0] if named else ordered[len(ordered) // 2]


def select_baselines(rows) -> Baselines:
    """Collapse the ladder to ONE row per (company, family, band), deterministically.

    A band is coarser than a ladder: Microsoft has rungs 65, 66 AND 67 and our
    seed calls all three `principal`, so a key can have several candidate rows,
    whose pay can differ widely. The comp a role shows must never depend on
    physical row order.

    `levels.pay.pay_label` declares which rung represents a band (microsoft
    `principal` is 65), and `comp_median` is estimated at exactly that rung, so
    the rule is not a tie-break, it is an alignment: prefer the rung the estimate
    already uses, so the package and the median it is compared with read the same
    row. The fallback for a band with no declared rung is the MEDIAN candidate by
    base, never the extreme, and never row order.

    `rows` is any iterable with `company_slug`, `family`, `band`, `level_label`,
    `base_amount`, `stock_amount`, `bonus_amount`; `provider` and `as_of` ride
    along, so the package can say who supplied the split and when.
    """
    grouped: dict[tuple[str, str | None, str], list] = {}
    for row in rows:
        grouped.setdefault((row.company_slug, row.family, row.band), []).append(row)

    selected: Baselines = {}
    for key, candidates in grouped.items():
        chosen = choose_rung_row(key[0], key[2], candidates)
        as_of = getattr(chosen, "as_of", None)
        selected[key] = {
            "base_amount": chosen.base_amount,
            "stock_amount": chosen.stock_amount,
            "bonus_amount": chosen.bonus_amount,
            "provider": getattr(chosen, "provider", None),
            "as_of": as_of.isoformat() if as_of is not None else None,
        }
    return selected


def country_rows(rows, country: str | None) -> list:
    """The rows for one country, those that can stand for its pay: a US row
    also passes `comp_market.us_rows`. None (a posting with no one country)
    reads none."""
    if country is None:
        return []
    mine = [row for row in rows if row.country == country]
    return us_rows(mine) if country == OUR_PAY_COUNTRY else mine


def pay_level_index(rows) -> dict:
    """(company, ladder family, band, country) -> the ONE row the comp estimate reads.

    Each country's rows apart (`country_rows`), priced and banded, through
    `choose_rung_row`, so the estimate reads the rung the package beside it reads.
    Rows carry `company_slug`, `family`, `band`, `level_label`, `base_amount`,
    `tc_median`, `country`.
    """
    grouped: dict[tuple[str, str, str, str], list] = {}
    for country in sorted({row.country for row in rows if row.country}):
        for row in country_rows(rows, country):
            if row.band is None or not (row.tc_median or row.base_amount):
                continue
            grouped.setdefault((row.company_slug, row.family, row.band, country), []).append(row)
    return {key: choose_rung_row(key[0], key[2], candidates) for key, candidates in grouped.items()}


def _rung_spellings(company: str, band: str) -> frozenset[str]:
    """Every name of the rung this band reads its pay from, folded: the label
    pay rows key it by (`levels.pay.pay_label`), its code and its aliases.
    Empty for a band below the priced range or a company with no ladder."""
    try:
        parsed = parse_band(band)
    except ValueError:  # a band string outside the enum: not ours to interpret
        return frozenset()
    declared = pay_label(company, parsed)
    if declared is None:
        return frozenset()
    rung = rung_for_band(company, parsed)
    names = {declared}
    if rung is not None and declared != parsed.value:
        names.update(rung.spellings)
    return frozenset(name.casefold() for name in names)


def _row_spellings(row) -> frozenset[str]:
    """The names a pay row gives its rung: its label and any aliases."""
    names = [row.level_label, *(getattr(row, "aliases", None) or ())]
    return frozenset(name.casefold() for name in names if name)


def is_split(row: dict | None) -> bool:
    """A row measures a split only when base, bonus AND stock are all known.

    A missing part is unknown, never zero: a row with base alone
    (our own per-level base, which measures no grant) read as `stock_amount or 0`
    would claim the company grants no equity and draw no equity segment. A
    measured 0 (Netflix stock, Amazon bonus) is a value and stays a split. Such a
    row falls through to the next estimator, the same as no row at all.
    """
    return bool(
        row
        and row.get("base_amount")
        and row.get("bonus_amount") is not None
        and row.get("stock_amount") is not None
    )


def _lookup(baselines: Baselines, company: str, family: str | None, band: str) -> tuple[dict | None, str]:
    """The best available base/bonus/equity ratios for this role, plus how good they are.

    `family` is the JOB's family; the baselines are keyed by the same taxonomy, so a
    same-family split is a plain key match.

    Falls back across job families rather than failing — a Google L6 TPM has no measured
    split of its own, but Google's L6 numbers are still a far better guide than a generic
    heuristic. The borrow order is fixed, not dict order (`comp_families.BORROW_ORDER`):
    the reference (SWE) family first, because it is the family rows most often cover.
    The caller must surface the downgrade; it is not a detail.
    """
    exact = baselines.get((company, family, band)) if family else None
    if is_split(exact):
        return exact, SPLIT_MEASURED

    borrowable = sorted(
        (
            (fam or "", row)
            for (slug, fam, bnd), row in baselines.items()
            if slug == company and bnd == band and is_split(row)
        ),
        key=lambda item: borrow_rank(item[0]),
    )
    if borrowable:
        return borrowable[0][1], SPLIT_CROSS_FAMILY

    return None, SPLIT_HEURISTIC


def _ratios(row: dict | None, company: str, band: str) -> tuple[float, float]:
    """(bonus_per_base, equity_per_base) — what the company adds ON TOP of each $1 of base.

    Expressed against BASE, not against total comp, because base is the number the
    employer actually stated. Scaling a stated base by a share-of-total would be circular.
    """
    if row and row.get("base_amount"):
        base = float(row["base_amount"])
        return (
            float(row.get("bonus_amount") or 0.0) / base,
            float(row.get("stock_amount") or 0.0) / base,
        )

    # No observed split: fall back to comp_split's share-of-TC heuristic and convert it
    # into the same base-relative form. The BONUS side prefers the company's stated
    # policy (`levels.pay`): a flat 12% for Amazon or OpenAI, which pay none, is an
    # invented segment the user can see.
    try:
        level = parse_band(band)
    except ValueError:
        level = LevelBand.SENIOR
    guess = split_tc(1_000_000, company, level)
    base = float(guess["base"]) or 1.0
    policy_bonus = bonus_ratio_for(company, level)
    bonus_r = policy_bonus if policy_bonus is not None else float(guess["bonus"]) / base
    return bonus_r, float(guess["equity"]) / base


def _reconcile(row: dict | None, split_source: str | None, stated_high: int | None) -> dict:
    """Compare the posted band's top against the measured base for the SAME ladder.

    Only against an exact family match. A borrowed row measures a different job family,
    so a disagreement with it says "wrong family", which the split source already says;
    reading it as "wrong level" would put a second, weaker claim in the same slot.
    """
    measured = row.get("base_amount") if row and split_source == SPLIT_MEASURED else None
    if not measured or not stated_high:
        return {"measured_base": None, "ratio_high": None, "verdict": None}
    ratio = stated_high / float(measured)
    if ratio > _RATIO_STATED_ABOVE:
        verdict = VERDICT_STATED_ABOVE
    elif ratio < _RATIO_STATED_BELOW:
        verdict = VERDICT_STATED_BELOW
    else:
        verdict = VERDICT_CONSISTENT
    return {"measured_base": int(measured), "ratio_high": round(ratio, 3), "verdict": verdict}


def _market_gap(total: dict | None, estimate: dict | None) -> dict | None:
    """How far the headline sits from the market median for the same level."""
    median = estimate.get("median") if estimate else None
    if not total or not median:
        return None
    mid = (total["low"] + total["high"]) / 2
    ratio = mid / float(median)
    verdict = MARKET_CONSISTENT if abs(ratio - 1.0) <= _MARKET_GAP_TOLERANCE else MARKET_DIVERGES
    return {"ratio": round(ratio, 3), "verdict": verdict}


def _shares(total: int, bonus_r: float, equity_r: float) -> tuple[int, int]:
    """Bonus and equity dollars inside a TOTAL-comp figure, given base-relative ratios."""
    base = total / (1 + bonus_r + equity_r)
    return round(base * bonus_r), round(base * equity_r)


def _equity(
    row: dict | None, company: str, band: str, lo: int, hi: int
) -> tuple[float, float, str]:
    """Annual equity for this role, and which estimator produced it.

    Preferred: the measured annualised grant at this company x family x band, as a POINT
    widened by equity's own tolerance. A pay row reports stock as annualised grant
    value, which is the same quantity the package shows.

    Fallback only: a share of the stated base, for the heuristic tier, where
    there is no grant to read.
    """
    stock = row.get("stock_amount") if row else None
    if stock:
        grant = float(stock)
        return grant * _EQUITY_SPREAD_LOW, grant * _EQUITY_SPREAD_HIGH, EQUITY_MEASURED_GRANT
    _, equity_r = _ratios(row, company, band)
    return lo * equity_r, hi * equity_r, EQUITY_RATIO


def _component(kind: str, low: float, high: float, provenance: str) -> dict | None:
    """A package segment. Zero-valued segments are omitted entirely — Netflix grants no
    stock and Anthropic pays no bonus, and rendering an empty sliver would imply they do."""
    lo, hi = round(low), round(high)
    if lo <= 0 and hi <= 0:
        return None
    return {"kind": kind, "low": lo, "high": hi, "provenance": provenance}


def build_job_package(
    *,
    company: str,
    band: str | None,
    family: str | None,
    comp_low: int | None,
    comp_median: int | None,
    comp_high: int | None,
    comp_provenance: str | None,
    disclosed: dict | None,
    baselines: Baselines | None = None,
    base_estimate: dict | None = None,
    heuristic: bool = True,
    us_pay: bool = True,
    covered: bool = True,
) -> dict:
    """The full comp story for one role, ready to render.

    `disclosed` is the `disclosed_comp` payload: None = the pay-disclosure pass has not
    run; `{"disclosed": False}` = it ran and the posting stated nothing; otherwise a band.

    `heuristic=False` while a plugin answers pay: the split heuristic and
    the pay policy's bonus are our data, so a level the plugin's rows do not split
    gets no split (`NO_SPLIT_PLUGIN`), never ours under its total; and the offer
    policy line is left out of the plugin's card altogether.
    `covered=False`: that plugin has not read the company, so a stated band is
    left whole as `NO_SPLIT_NOT_COVERED`, not as a split the plugin did not report.
    `us_pay=False`: the posting's pay country is not the US, or it names places
    in several countries. Our split heuristic is measured on US pay, so while ours
    answers, a level no row splits gets no split (`NO_SPLIT_NOT_US`); the offer
    policy, which is the company's, stays.
    """
    baselines = baselines or {}
    estimate = (
        {
            "low": comp_low,
            "median": comp_median,
            "high": comp_high,
            "provenance": comp_provenance,
        }
        if comp_median is not None
        else None
    )
    package: dict = {
        "state": "unchecked",
        "basis": None,
        "currency": None,
        "pay_period": None,
        "stated": None,
        "bonus_pct": None,
        "components": [],
        "total": None,
        "estimate": estimate,
        "split_source": None,
        # Who supplied the per-level split the segments are scaled by, and when:
        # the rung row's provider and as-of date. None with no measured split.
        "split_provider": None,
        "split_as_of": None,
        # Which estimator produced the equity segment, when there is one.
        "equity_basis": None,
        # How the single headline total compares to the reported median beside it.
        # The median stays in `estimate`; this only says whether to trust the pair.
        "market_gap": None,
        # Only populated for a decomposed, stated BASE band in USD per year: there is
        # nothing to reconcile against a band the employer never called base, and a
        # CAD band over a USD median is not a ratio at all.
        "reconciliation": None,
        "no_split_reason": None,
        "snippet": None,
        "confidence": None,
        # How this company builds an offer (bonus rule, equity rule, vest schedule):
        # verified knowledge, so the panel can say "vests 5/15/40/40, sign-on bridges
        # years 1-2" instead of leaving the user to find it. Unverified = None. It is
        # our data, so it rides only on our figures: the card a plugin answers shows
        # none of it.
        "policy": describe_policy(company) if heuristic else None,
        # Our base alone where no total is estimated: "Est. base", labelled.
        "base_estimate": base_estimate if comp_median is None and base_estimate else None,
    }

    if disclosed is None:
        package["state"] = "unchecked"
    elif not disclosed.get("disclosed"):
        package["state"] = "none_stated"
    else:
        package["state"] = "band"

    row, split_source = (None, None)
    if band:
        row, split_source = _lookup(baselines, company, family, band)
    unsplit = not (heuristic and us_pay) and row is None
    package["split_source"] = None if unsplit else split_source
    if row is not None:
        package["split_provider"], package["split_as_of"] = row.get("provider"), row.get("as_of")

    # --- no band stated: the package is entirely our estimate -------------------------
    if package["state"] != "band":
        if comp_median is None and package["base_estimate"]:
            # A base with nothing to split: one estimated base segment, and no
            # total (bonus and equity are unknown, never zero).
            est = package["base_estimate"]
            package["components"] = [
                c for c in (_component("base", est["low"] or est["median"], est["high"] or est["median"],
                                       PROV_ESTIMATED),) if c
            ]
            return package
        if comp_median is not None and band and unsplit:
            # The total stands alone: the headline reads the estimate.
            package["no_split_reason"] = NO_SPLIT_PLUGIN if not heuristic else NO_SPLIT_NOT_US
            return package
        if comp_median is not None and band:
            bonus_r, equity_r = _ratios(row, company, band)
            lo_tc, hi_tc = comp_low or comp_median, comp_high or comp_median
            # Base absorbs the rounding, exactly as `comp_split.split_tc` does, so the
            # segments always add back up to the total they were derived from — a bar
            # whose parts do not sum to its own headline is a bug the user can see.
            bonus_lo, equity_lo = _shares(lo_tc, bonus_r, equity_r)
            bonus_hi, equity_hi = _shares(hi_tc, bonus_r, equity_r)
            package["components"] = [
                c
                for c in (
                    _component("base", lo_tc - bonus_lo - equity_lo, hi_tc - bonus_hi - equity_hi, PROV_ESTIMATED),
                    _component("bonus", bonus_lo, bonus_hi, PROV_ESTIMATED),
                    _component("equity", equity_lo, equity_hi, PROV_ESTIMATED),
                )
                if c
            ]
            # Nothing was stated, so there is no base to size a grant against: this
            # branch splits an ESTIMATED total and every part of it is a ratio.
            package["equity_basis"] = EQUITY_RATIO
            package["total"] = {"low": lo_tc, "high": hi_tc, "provenance": PROV_ESTIMATED}
        return package

    # --- a band was stated ------------------------------------------------------------
    basis = disclosed.get("pay_basis")
    package.update(
        {
            "basis": basis,
            "currency": disclosed.get("currency"),
            "pay_period": disclosed.get("pay_period"),
            "snippet": disclosed.get("snippet"),
            "confidence": disclosed.get("confidence"),
            "bonus_pct": disclosed.get("bonus_pct"),
        }
    )
    lo = disclosed.get("base_min")
    hi = disclosed.get("base_max")
    lo = lo if lo is not None else hi
    hi = hi if hi is not None else lo
    package["stated"] = {"low": lo, "high": hi} if lo is not None else None

    # An hourly or monthly rate cannot be scaled by annual base->equity ratios, and
    # we will not annualize it ourselves — that is inference, not disclosure.
    # A band whose period we could not tell is not split
    # either: splitting it would claim it is a yearly salary.
    period = disclosed.get("pay_period")
    if period in ("hour", "month", "unclear"):
        package["no_split_reason"] = {
            "hour": NO_SPLIT_HOURLY,
            "month": NO_SPLIT_MONTHLY,
            "unclear": NO_SPLIT_PERIOD_UNCLEAR,
        }[period]
        return package

    # A stated total is itself the package headline. Never decompose it using an
    # estimated split. Netflix explicitly makes the mix an employee election.
    if basis == "total" and lo is not None:
        package["total"] = {"low": lo, "high": hi, "provenance": PROV_STATED}
        package["no_split_reason"] = (
            NO_SPLIT_EMPLOYEE_ELECTION if company == "netflix" else NO_SPLIT_TOTAL
        )
        return package

    # THE guard-rail. The employer stated a number but not what it covers. Decomposing it
    # would require assuming it is base — the precise class of invented fact
    # pay_basis must never carry. Show it, do not explain it.
    if basis != "base" or lo is None or not band:
        if basis != "base":
            package["no_split_reason"] = NO_SPLIT_BASIS_UNCLEAR
        return package

    if unsplit:
        package["no_split_reason"] = (
            NO_SPLIT_NOT_US if heuristic else NO_SPLIT_PLUGIN if covered else NO_SPLIT_NOT_COVERED
        )
        return package

    if disclosed.get("currency") in (None, "USD"):
        package["reconciliation"] = _reconcile(row, split_source, hi)

    bonus_r, equity_r = _ratios(row, company, band)
    stated_pct = disclosed.get("bonus_pct")
    # The posting's own "+ 25% bonus target" beats our modelled ratio: it is stated.
    bonus_prov = PROV_STATED if stated_pct else PROV_ESTIMATED
    if stated_pct:
        bonus_r = float(stated_pct)

    bonus_lo, bonus_hi = lo * bonus_r, hi * bonus_r
    equity_lo, equity_hi, equity_basis = _equity(row, company, band, lo, hi)
    package["equity_basis"] = equity_basis

    components = [
        _component("base", lo, hi, PROV_STATED),
        _component("bonus", bonus_lo, bonus_hi, bonus_prov),
        _component("equity", equity_lo, equity_hi, PROV_ESTIMATED),
    ]
    package["components"] = [c for c in components if c]
    # The headline is the SUM of the segments the user can see, not a second computation
    # of the same quantity: equity does not scale with the base band, so a re-derived
    # total would not be the total of the bar beside it.
    package["total"] = {
        "low": round(lo) + round(bonus_lo) + round(equity_lo),
        "high": round(hi) + round(bonus_hi) + round(equity_hi),
        # Estimated even though base is stated: bonus and equity are still modelled, so
        # the sum is not something the employer committed to.
        "provenance": PROV_ESTIMATED,
    }
    if disclosed.get("currency") in (None, "USD"):
        package["market_gap"] = _market_gap(package["total"], estimate)
    return package
