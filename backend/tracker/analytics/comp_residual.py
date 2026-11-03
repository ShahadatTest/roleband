"""Validate the modeled equity slice against employer-stated base bands.

`Job.comp_median` is a level-seeded TOTAL-comp estimate whose equity slice is
always modeled (`comp_split`: heuristic band shares, overridden by observed
`company_comp_level.stock_pct`). Employer-stated base bands
(`disclosed_base_min/max`, basis='base', often with a stated bonus share) are
ground truth for CASH. The difference is therefore an *implied equity* figure:

    implied_equity = comp_median - stated_base * (1 + bonus_share)

Aggregated per (company, band), the implied range can be compared against the
modeled equity share. This is a consistency check on the model, emphatically NOT
an "estimate error" metric — the gap between the estimate and a stated base band
is equity by construction. Vocabulary in the output sticks
to `implied_*`, `residual_vs_model`, `consistent`.

Pure and DB-free: the API/report layer runs the SQL and injects rows, mirroring
`comp_stats.build_disclosed_bands`.
"""

from __future__ import annotations

from collections.abc import Collection, Sequence
from statistics import median

from tracker.analytics.comp_split import (
    SOURCE_HEURISTIC,
    SOURCE_OBSERVED,
    ObservedSplits,
    equity_assumptions,
    equity_pct,
)
from tracker.analytics.comp_stats import DISCLOSED_FLOOR
from tracker.pay_period import not_yearly_usd
from tracker.schema import LEVEL_BAND_ORDER, LevelBand, parse_band

BONUS_STATED = "stated"
BONUS_MODELED = "modeled"

# Last-resort target-bonus share of BASE when a company has no stated bonus and
# no observed split at all. Grounded in the stated `disclosed_bonus_pct`
# distribution, NOT in comp_split's share-of-TC heuristic:
# the equity model under test must never leak into the cash side of the
# measurement, or the residual would move when the model's knobs move.
FALLBACK_BONUS_PER_BASE = 0.15


def _observed_bonus_per_base(row: dict | None) -> float | None:
    """bonus/base of an observed split row (both are shares of TC), or None."""
    if not row:
        return None
    b, base = row.get("bonus_pct"), row.get("base_pct")
    if b is None or not base:
        return None
    return float(b) / float(base)


def _bonus_ratio(
    bonus_pct: float | None,
    company: str,
    band: LevelBand,
    observed: ObservedSplits,
) -> tuple[float, str]:
    """Target-bonus share of BASE, preferring what the employer printed.

    Fallback order keeps the cash side independent of the equity model:
    stated -> observed (company, band) -> median across the company's other
    observed bands (bonus culture is company-wide: OpenAI/Amazon pay ~none,
    Google ~15-30% of base) -> flat FALLBACK_BONUS_PER_BASE.
    """
    if bonus_pct is not None:
        return float(bonus_pct), BONUS_STATED

    same_band = _observed_bonus_per_base(observed.get((company, band.value)))
    if same_band is not None:
        return same_band, BONUS_MODELED

    company_ratios = sorted(
        r
        for (slug, _band), row in observed.items()
        if slug == company and (r := _observed_bonus_per_base(row)) is not None
    )
    if company_ratios:
        return median(company_ratios), BONUS_MODELED

    return FALLBACK_BONUS_PER_BASE, BONUS_MODELED


def _modeled_equity(
    company: str, band: LevelBand, observed: ObservedSplits, *, heuristic: bool = True
) -> tuple[float, str] | None:
    """Equity share of TC the product currently models for this (company, band).

    An observed 0.0 is a real measurement (Netflix's cash election) and must not
    fall through to the heuristic — only a missing/None stock_pct does.
    `heuristic=False` while a plugin answers pay: no observed split is
    then None, never our guess.
    """
    row = observed.get((company, band.value))
    if row and row.get("stock_pct") is not None:
        return float(row["stock_pct"]), SOURCE_OBSERVED
    if not heuristic:
        return None
    return equity_pct(company, band), SOURCE_HEURISTIC


def build_source_comparison(
    obs_rows: Sequence[tuple],
    *,
    observed: ObservedSplits | None = None,
    sources: Collection[str] = (),
) -> dict:
    """Modeled equity share vs an external source's REALIZED equity share.

    `obs_rows` are per-submission `(company, band, total_usd, equity_usd)` from
    `external_comp_observation` (band already mapped; None-band rows skipped),
    published by the plugins named in `sources`. `observed` is the measured
    per-level split dict (as `_observed_splits` yields), so the comparison is
    model-vs-source, not heuristic.

    Per (company, band): `eq_share = equity/total`, reported as the median over all
    reported points and (separately) over points with non-zero equity — the latter
    drops base-only misreports and not-yet-vested year-1 rows (back-loaded
    vesting). `delta = eq_share_estd - model_stock_pct`. This is a
    consistency read on the model, never an "error": realized equity and an
    amortized offer-grant `stock_pct` are different quantities.
    """
    observed = observed or {}
    groups: dict[tuple[str, str], dict] = {}
    for company, band, total_usd, equity_usd in obs_rows:
        if not band or not total_usd:
            continue
        g = groups.setdefault((company, band), {"all": [], "estd": []})
        share = float(equity_usd) / float(total_usd)
        g["all"].append(share)
        if equity_usd > 0:
            g["estd"].append(share)

    out = []
    for (company, band), g in groups.items():
        row = observed.get((company, band))
        model = float(row["stock_pct"]) if row and row.get("stock_pct") is not None else None
        estd = round(median(g["estd"]), 4) if g["estd"] else None
        delta = round(estd - model, 4) if (estd is not None and model is not None) else None
        out.append(
            {
                "company": company,
                "band": band,
                "n": len(g["all"]),
                "n_estd": len(g["estd"]),
                "source_eq_share": round(median(g["all"]), 4),
                "source_eq_share_estd": estd,
                "model_stock_pct": round(model, 4) if model is not None else None,
                "delta_estd_vs_model": delta,
            }
        )
    out.sort(key=lambda d: (LEVEL_BAND_ORDER.get(d["band"], 0), d["company"]))
    return {
        "sources": sorted(sources),
        "groups": out,
        "coverage": {"observations": sum(len(g["all"]) for g in groups.values()), "bands": len(out)},
    }


def build_equity_residuals(
    rows: Sequence[tuple],
    *,
    observed: ObservedSplits | None = None,
    accepted_versions: Collection[str] = (),
    heuristic: bool = True,
) -> dict:
    """Implied-equity residuals per (company, band) from stated base bands.

    `rows` are per-job tuples:

        (company, band, comp_median, base_min, base_max, currency,
         pay_basis, pay_period, bonus_pct, prompt_version)

    Guards (each counted in `excluded`, never silently dropped):
      * only `pay_basis == 'base'` enters the math — an `unclear`/`total` band is
        not a cash figure and would fabricate equity (this alone keeps Netflix's
        all-`unclear` bands out; its check lives in the model-side tests);
      * only US-dollar bands enter (`not_usd`): `comp_median` is a dollar
        figure, so a rupee base against it would imply absurd negative equity.
        Nothing is converted; a row stored with no currency is a dollar band,
        as the pass stores it;
      * only YEARLY bands enter, by `pay_period.effective_period`:
        hourly and monthly are never annualized, and a stored
        period its amount contradicts ("$600,000 / hr") or its words
        contradicted (`unclear`) is not trusted either way. Counted under
        `not_yearly` (hourly, monthly and unclear alike). Same semantics as
        `comp_package`'s no-split reasons;
      * only rows written by an accepted prompt version: labels written before
        the basis was derived are not trusted;
      * sub-floor / inverted / non-positive figures are implausible;
      * `heuristic=False` while a plugin answers pay: a (company,
        band) the plugin's rows do not split has no modeled share to check, so
        its rows are counted under `unsplit`, never checked against our
        heuristic's guess.

    The honest unit is the distinct band, not the req: many reqs hang off one
    (company, band, seed, base range) tuple, so duplicates collapse with a `reqs`
    count. Uncertainty is carried as a RANGE by propagating base_min..base_max
    (and the envelope across a group's distinct tuples) — no point estimate is
    pretended. Negative implied equity is reported as-is: it means the seeded
    estimate does not even cover stated cash there, which is signal.
    """
    observed = observed or {}
    accepted = set(accepted_versions)

    excluded = {
        "basis_not_base": 0, "not_usd": 0, "not_yearly": 0, "stale_version": 0, "implausible": 0,
        "unsplit": 0,
    }
    tuples: dict[tuple, int] = {}
    total_rows = 0

    for (company, band, comp_median, base_min, base_max, currency,
         basis, period, bonus_pct, version) in rows:
        total_rows += 1
        if company is None or band is None or comp_median is None or base_min is None or base_max is None:
            continue
        try:
            level = parse_band(band)
        except ValueError:
            continue
        if basis != "base":
            excluded["basis_not_base"] += 1
            continue
        # An amount that is no pay at any size is left to the `implausible` count.
        refused = not_yearly_usd(base_min, base_max, currency, period)
        if refused:
            excluded[refused] += 1
            continue
        if version not in accepted:
            excluded["stale_version"] += 1
            continue
        comp_median, base_min, base_max = int(comp_median), int(base_min), int(base_max)
        if base_min < DISCLOSED_FLOOR or base_max < base_min or comp_median <= 0:
            excluded["implausible"] += 1
            continue
        if _modeled_equity(company, level, observed, heuristic=heuristic) is None:
            excluded["unsplit"] += 1
            continue
        key =(company, level, comp_median, base_min, base_max, bonus_pct)
        tuples[key] = tuples.get(key, 0) + 1

    groups: dict[tuple[str, LevelBand], dict] = {}
    for (company, level, comp_median, base_min, base_max, bonus_pct), reqs in tuples.items():
        bonus_r, bonus_source = _bonus_ratio(bonus_pct, company, level, observed)
        cash_low = base_min * (1 + bonus_r)
        cash_high = base_max * (1 + bonus_r)
        implied_low = comp_median - cash_high
        implied_high = comp_median - cash_low
        implied_mid = comp_median - (cash_low + cash_high) / 2

        g = groups.setdefault(
            (company, level),
            {"reqs": 0, "bands": 0, "seeds": set(), "lows": [], "mids": [], "highs": [],
             "dollars": [], "bonus_sources": set()},
        )
        g["reqs"] += reqs
        g["bands"] += 1
        g["seeds"].add(comp_median)
        g["lows"].append(implied_low / comp_median)
        g["mids"].append(implied_mid / comp_median)
        g["highs"].append(implied_high / comp_median)
        g["dollars"].append((implied_low, implied_mid, implied_high))
        g["bonus_sources"].add(bonus_source)

    out_groups = []
    for (company, level), g in groups.items():
        low_pct = min(g["lows"])
        high_pct = max(g["highs"])
        mid_pct = median(g["mids"])
        modeled = _modeled_equity(company, level, observed, heuristic=heuristic)
        assert modeled is not None  # an unsplit (company, band) never reaches a group
        modeled_pct, model_source = modeled
        out_groups.append(
            {
                "company": company,
                "band": level.value,
                "reqs": g["reqs"],
                "bands": g["bands"],
                "comp_medians": sorted(g["seeds"]),
                "implied_equity": {
                    "low": round(min(t[0] for t in g["dollars"])),
                    "mid": round(median(t[1] for t in g["dollars"])),
                    "high": round(max(t[2] for t in g["dollars"])),
                },
                "implied_pct": {
                    "low": round(low_pct, 4),
                    "mid": round(mid_pct, 4),
                    "high": round(high_pct, 4),
                },
                "modeled_pct": round(modeled_pct, 4),
                "model_source": model_source,
                # Worst case wins: one modeled bonus taints the group's cash side.
                "bonus_source": BONUS_MODELED if BONUS_MODELED in g["bonus_sources"] else BONUS_STATED,
                "residual_vs_model_pct": round(mid_pct - modeled_pct, 4),
                "consistent": low_pct <= modeled_pct <= high_pct,
            }
        )
    out_groups.sort(key=lambda d: (LEVEL_BAND_ORDER.get(d["band"], 0), d["company"]))

    companies: dict[str, int] = {}
    for grp in out_groups:
        companies[grp["company"]] = companies.get(grp["company"], 0) + grp["reqs"]

    return {
        "groups": out_groups,
        "coverage": {
            "rows": total_rows,
            "used_reqs": sum(tuples.values()),
            "distinct_bands": len(tuples),
            "companies": companies,
        },
        "excluded": excluded,
        "assumptions": equity_assumptions(),
    }
