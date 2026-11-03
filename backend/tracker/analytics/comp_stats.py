"""Compensation analytics for the Statistics "Compensation" sub-tab.

Pure, DB-free aggregation over the estimated compensation on open jobs: overall
percentile summary, a distribution histogram, and per-level / per-company /
per-family breakdowns. The API layer fetches `(company, level_band, family,
comp_median)` for open jobs and hands the rows here, so all the math is unit-
testable without a database. Comp is an *estimate* (see `Job.comp_provenance`);
the UI surfaces that caveat.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from tracker.analytics.comp_split import (
    SOURCE_HEURISTIC,
    SOURCE_OBSERVED,
    ObservedSplits,
    equity_assumptions,
    is_public,
    parent_ticker,
    split_tc_observed,
    ticker_for,
)
from tracker.levels import UNSTATED_LEVEL
from tracker.pay_disclosure import band_stated, disclosure_known
from tracker.pay_period import not_yearly_usd
from tracker.schema import LEVEL_BAND_ORDER, LevelBand, parse_band

# Candidate "nice" histogram bucket widths (USD), smallest first.
_NICE_STEPS = (25_000, 50_000, 100_000, 150_000, 200_000, 250_000, 500_000)


def _percentile(sorted_vals: Sequence[int], p: float) -> float | None:
    """Linear-interpolated percentile (p in [0,1]) matching Postgres percentile_cont."""
    n = len(sorted_vals)
    if n == 0:
        return None
    if n == 1:
        return float(sorted_vals[0])
    idx = p * (n - 1)
    lo = int(idx)
    hi = min(lo + 1, n - 1)
    frac = idx - lo
    return sorted_vals[lo] * (1 - frac) + sorted_vals[hi] * frac


def _summary(vals: Sequence[int]) -> dict:
    """Count + min/max + p25/p50/p75/p90 for one group of comp values."""
    s = sorted(vals)
    return {
        "count": len(s),
        "min": s[0] if s else None,
        "max": s[-1] if s else None,
        "p25": _percentile(s, 0.25),
        "p50": _percentile(s, 0.50),
        "p75": _percentile(s, 0.75),
        "p90": _percentile(s, 0.90),
    }


def _nice_step(rough: float) -> int:
    """Smallest 'nice' bucket width >= rough."""
    for step in _NICE_STEPS:
        if step >= rough:
            return step
    return 1_000_000


def _histogram(vals: Sequence[int], target_bins: int = 8) -> list[dict]:
    """Bucket comp values into ~target_bins even bands aligned to a nice step."""
    if not vals:
        return []
    lo, hi = min(vals), max(vals)
    if hi == lo:
        return [{"lo": lo, "hi": lo, "count": len(vals)}]
    step = _nice_step((hi - lo) / target_bins)
    start = (lo // step) * step
    n_bins = int((hi - start) // step) + 1
    counts = [0] * n_bins
    for v in vals:
        i = min(int((v - start) // step), n_bins - 1)
        counts[i] += 1
    return [
        {"lo": start + i * step, "hi": start + (i + 1) * step, "count": c}
        for i, c in enumerate(counts)
    ]


def _grouped(rows: Iterable[tuple], key_idx: int) -> dict[object, list[int]]:
    groups: dict[object, list[int]] = {}
    for r in rows:
        key = r[key_idx]
        val = r[3]
        if val is None:
            continue
        groups.setdefault(key, []).append(int(val))
    return groups


# The fewest priced roles a level, company or discipline needs to be shown.
# The estimate is a lookup with few distinct values, so a group of
# one is one lookup cell, not a market.
COMP_MIN_ROLES = 5


def level_order(key: object) -> int:
    """Seniority rank of a level key: the rungs in order, then `unstated`
    (a role whose level we cannot place), as the Board lists it."""
    if key == UNSTATED_LEVEL:
        return max(LEVEL_BAND_ORDER.values()) + 1
    return LEVEL_BAND_ORDER.get(str(key), 0)


def build_comp_stats(
    rows: Sequence[tuple],
    total_open: int,
    *,
    company_limit: int = 15,
    min_roles: int = COMP_MIN_ROLES,
) -> dict:
    """Aggregate open-job comp into the Compensation panel payload.

    `rows` are `(company, level, family, comp_median)`, `level` the level key
    (`db.queries.scope.level_key_expr`); rows with a null
    comp_median are ignored in the math but `total_open` reflects all open jobs so
    the UI can report coverage. `by_level` is ordered by seniority and leaves
    out `unstated` rows: their estimate was looked up at a guessed band, so a
    row of them restates the guess. `by_company`
    and `by_family` are ranked by median (p50) descending. A group needs
    `min_roles` priced roles to be listed; `min_roles` is returned so the UI
    can say so, and every group carries its `count`.
    """
    vals = [int(r[3]) for r in rows if r[3] is not None]

    def _enough(groups: dict[object, list[int]]) -> list[tuple[object, list[int]]]:
        return [(k, vs) for k, vs in groups.items() if k is not None and len(vs) >= min_roles]

    by_level = [
        {"level_band": lb, **_summary(vs)}
        for lb, vs in sorted(_enough(_grouped(rows, 1)), key=lambda kv: level_order(kv[0]))
        if lb != UNSTATED_LEVEL
    ]
    by_company = sorted(
        ({"company": c, **_summary(vs)} for c, vs in _enough(_grouped(rows, 0))),
        # Name breaks a tie in the median, so equal medians never swap places,
        # or swap which company the limit cuts, between two reads of one table.
        key=lambda d: (-(d["p50"] or 0), d["company"]),
    )[:company_limit]
    by_family = sorted(
        ({"family": f, **_summary(vs)} for f, vs in _enough(_grouped(rows, 2))),
        key=lambda d: (-(d["p50"] or 0), d["family"] or ""),
    )

    return {
        "min_roles": min_roles,
        "coverage": {
            "with_comp": len(vals),
            "total_open": total_open,
            "pct": round(len(vals) / total_open, 3) if total_open else 0.0,
        },
        "overall": _summary(vals) if vals else None,
        "histogram": _histogram(vals),
        "by_level": by_level,
        "by_company": by_company,
        "by_family": by_family,
    }


def _pctiles(vals: Sequence[int]) -> dict:
    """Count + p25/p50/p75/p90 for a comp group (the trend rollup slice shape)."""
    s = sorted(vals)
    return {
        "count": len(s),
        "p25": _percentile(s, 0.25),
        "p50": _percentile(s, 0.50),
        "p75": _percentile(s, 0.75),
        "p90": _percentile(s, 0.90),
    }


def build_comp_metric_rows(rows: Sequence[tuple]) -> list[dict]:
    """Independently computed comp percentile slices for the daily trend rollup.

    `rows` are `(company, level_band, family, comp_median)` (same shape as
    `build_comp_stats`). Returns one `{dim, key, count, p25, p50, p75, p90}` per
    grouping: a single `overall` row plus one row per company, per level band, and
    per non-null family. Rows with a null comp_median are ignored. Each slice's
    percentiles are computed from that group's raw values (not re-aggregated), so
    every stored series is exact.
    """
    out: list[dict] = []

    overall = [int(r[3]) for r in rows if r[3] is not None]
    if overall:
        out.append({"dim": "overall", "key": "", **_pctiles(overall)})

    for dim, idx in (("company", 0), ("level", 1), ("family", 2)):
        for key, vals in _grouped(rows, idx).items():
            if key is None:  # unclassified family (or company) — skip
                continue
            out.append({"dim": dim, "key": key, **_pctiles(vals)})

    return out


def _as_band(raw: object) -> LevelBand | None:
    """Coerce a stored level_band (str or enum) into a LevelBand, or None."""
    if isinstance(raw, LevelBand):
        return raw
    try:
        return parse_band(raw)
    except (ValueError, TypeError):
        return None


def _decompose_group(
    items: Sequence[tuple[str, LevelBand, int]],
    observed: ObservedSplits | None = None,
    *,
    heuristic: bool = True,
) -> dict | None:
    """Blend (company, band, tc) postings into a median package + equity share.

    Each posting is split by `split_tc_observed` — the REAL per-level base/stock/bonus
    where we have it, the heuristic only where we don't. The group's equity and bonus
    shares are dollar-weighted blends (Σcomponent / Σtc), applied to the group's
    *median* TC so base+bonus+equity always reconstruct the headline median_tc.

    `split_source` reports whether the figures are measured, estimated, or a mix —
    the UI must not present a guess as if it were an observation.

    `heuristic=False` while a plugin answers pay: only postings the
    plugin's own rows split are blended; None when it splits none of them.
    """
    parts = [(tc, split_tc_observed(tc, company, band, observed, heuristic=heuristic))
             for company, band, tc in items]
    split = [(tc, part) for tc, part in parts if part is not None]
    if not split:
        return None
    tcs = sorted(tc for tc, _ in split)
    total_tc = sum(tcs)

    total_equity = 0
    total_bonus = 0
    seen_sources: set[str] = set()
    for _, part in split:
        total_equity += part["equity"]
        total_bonus += part["bonus"]
        seen_sources.add(part["source"])

    eq_pct = (total_equity / total_tc) if total_tc else 0.0
    bonus_pct = (total_bonus / total_tc) if total_tc else 0.0

    median_tc = int(_percentile(tcs, 0.5) or 0)
    equity = round(median_tc * eq_pct)
    bonus = round(median_tc * bonus_pct)
    base = median_tc - equity - bonus

    if seen_sources == {SOURCE_OBSERVED}:
        split_source = SOURCE_OBSERVED
    elif seen_sources == {SOURCE_HEURISTIC}:
        split_source = SOURCE_HEURISTIC
    else:
        split_source = "mixed"

    return {
        "count": len(tcs),
        "median_tc": median_tc,
        "base": base,
        "bonus": bonus,
        "equity": equity,
        "equity_pct": round(eq_pct, 4),
        "split_source": split_source,
    }


def build_comp_trajectory(
    rows: Sequence[tuple],
    *,
    observed: ObservedSplits | None = None,
    profiles: dict[str, dict] | None = None,
    company_limit: int = 20,
    heuristic: bool = True,
) -> dict:
    """Equity decomposition for the "Stock trajectory" panel.

    `heuristic=False` while a plugin answers pay: a company the
    plugin's rows split for none of its roles is left out, never split by ours.

    `rows` are `(company, level_band, family, comp_median)` — same shape as
    `build_comp_stats`. `observed` carries the real per-level splits from
    `company_comp_level`; `profiles` carries resolved identity from
    `company_profile` (is_public / ticker / equity_vehicle). Both are injected so
    this module stays pure and DB-free. Without them, identity falls back to the
    atlas (`comp_split.ticker_for`) and the split to the heuristic.

    Companies split into `public` (equity tracks a listed ticker, so it re-prices
    with the stock) and `private` (illiquid, context only). `overall` is the
    dollar-weighted package across public roles — the slider baseline.

    A company can be listed AND carry ~0% equity: Netflix pays a cash election, so
    it appears under `public` with `equity_pct == 0` and does not move at all under
    a price scenario. That is a fact read from the observed split, not a shape a
    heuristic could produce.

    Rows with a null comp_median or an undecodable band are skipped.
    """
    profiles = profiles or {}

    # A subsidiary granted its listed parent's stock is read from
    # `parent_ticker` first: its own profile truly says "not listed", which is
    # not what the equity does.
    def _public(company: str) -> bool:
        if parent_ticker(company):
            return True
        p = profiles.get(company)
        return bool(p["is_public"]) if p and p.get("is_public") is not None else is_public(company)

    def _ticker(company: str) -> str | None:
        if parent := parent_ticker(company):
            return parent
        p = profiles.get(company)
        return p.get("ticker") if p and p.get("ticker") else ticker_for(company)

    by_company: dict[str, list[tuple[str, LevelBand, int]]] = {}
    for r in rows:
        band = _as_band(r[1])
        if r[3] is None or band is None:
            continue
        by_company.setdefault(r[0], []).append((r[0], band, int(r[3])))

    public: list[dict] = []
    private: list[dict] = []
    for company, items in by_company.items():
        group = _decompose_group(items, observed, heuristic=heuristic)
        if group is None:
            continue
        entry = {"company": company, **group}
        prof = profiles.get(company) or {}
        entry["equity_vehicle"] = "rsu" if parent_ticker(company) else prof.get("equity_vehicle")
        if _public(company):
            entry["ticker"] = _ticker(company)
            public.append(entry)
        else:
            private.append(entry)

    public.sort(key=lambda d: d["equity_pct"], reverse=True)
    private.sort(key=lambda d: d["median_tc"], reverse=True)

    public_items = [it for c, its in by_company.items() if _public(c) for it in its]
    overall = _decompose_group(public_items, observed, heuristic=heuristic) if public_items else None

    return {
        "currency": "USD",
        "assumptions": equity_assumptions(),
        "overall": overall,
        "public": public[:company_limit],
        "private": private[:company_limit],
    }


# A skill's premium compares like with like: its roles against all
# roles at the same level in the same discipline. A cell counts only when the
# skill has `SKILL_CELL_MIN` roles in it and the cell has `CELL_MIN`.
SKILL_CELL_MIN = 3
CELL_MIN = 6


def rank_skill_comp(
    rows: Iterable[tuple],
    market: Iterable[tuple],
    *,
    min_jobs: int = 15,
    limit: int = 12,
) -> list[dict]:
    """Rank skills by what roles naming them pay over like roles that do not say.

    `rows` are `(term, level_band, family, comp_median)`, one per (job, skill)
    pair; `market` is `(level_band, family, comp_median)` for every priced role.

    "Skill median minus market median" would measure mix, not pay: a skill named
    mostly by Directors would read as a premium. So `premium` is the role-weighted
    mean, over the (level, discipline) cells the skill has enough roles in, of
    the skill's median there minus the cell's. The estimate is a lookup keyed by
    company, level and discipline, so what is left is which EMPLOYERS ask for
    the skill. `count` is the roles behind the premium (`min_jobs` at least);
    `p50` their median. Highest premium first; past `limit`, the top and the
    bottom halves, so a skill that pays less is shown too.
    """
    cells: dict[tuple, list[int]] = {}
    for level, family, comp in market:
        if comp is not None:
            cells.setdefault((level, family), []).append(int(comp))
    cell_median = {k: _percentile(sorted(vs), 0.5) or 0.0 for k, vs in cells.items() if len(vs) >= CELL_MIN}

    by_skill: dict[str, dict[tuple, list[int]]] = {}
    for term, level, family, comp in rows:
        if comp is not None:
            by_skill.setdefault(term, {}).setdefault((level, family), []).append(int(comp))

    out: list[dict] = []
    for term, skill_cells in by_skill.items():
        counted = [
            (vs, cell_median[k])
            for k, vs in skill_cells.items()
            if k in cell_median and len(vs) >= SKILL_CELL_MIN
        ]
        n = sum(len(vs) for vs, _ in counted)
        if n < min_jobs:
            continue
        diff = sum(len(vs) * ((_percentile(sorted(vs), 0.5) or 0.0) - med) for vs, med in counted)
        pooled = sorted(v for vs, _ in counted for v in vs)
        out.append({"term": term, "count": n, "p50": _percentile(pooled, 0.5), "premium": round(diff / n)})
    out.sort(key=lambda d: (-d["premium"], d["term"]))
    if len(out) <= limit:
        return out
    return out[: (limit + 1) // 2] + out[len(out) - limit // 2 :]


# Below this an annual figure is not a salary: Anthropic posts a literal
# "Annual Salary: $1—$2 USD" placeholder on some reqs. The extraction is correct
# (the span is verbatim), so the posting is what is junk — drop it here rather
# than let it set the axis floor.
DISCLOSED_FLOOR = 50_000
BAND_LIMIT = 200


def _band_order(d: dict) -> tuple:
    """Seniority, then the widest-paying band first within a level; the low end
    breaks the last tie, so two reads of one table list the same bands in the
    same order (two bands sharing level, top and company swapped places)."""
    return (level_order(d["level_band"]), -d["high"], d["company"], d["low"])


def build_disclosed_bands(rows: Sequence[tuple], *, limit: int = BAND_LIMIT) -> dict:
    """Collapse employer-disclosed pay bands into one entry per distinct band.

    `rows` are `(company, level, base_min, base_max, pay_basis, currency,
    pay_period)`, where `level` is the level key (`db.queries.scope.level_key_expr`):
    a band printed on roles whose level we cannot place is its own `unstated`
    row, listed last, never Mid-level. Postings do
    not state a salary per role: an employer publishes a band per (company, level)
    and hangs many reqs off it.
    So the honest unit here is the *band*, with the number of open reqs sitting on
    it; this is emphatically not a per-role sample, and must not be charted as a
    distribution.

    Only `base` rows are kept. `unclear` rows (the posting gives a range but never
    says whether it bundles bonus/equity, like Netflix's bare "the range for this
    role is ...") cannot share an axis with base pay, and `total` rows are
    a different quantity altogether. Both are counted in `excluded` so the UI can
    say what it left out instead of silently dropping it (pay_basis is
    derived from the span, never taken from the model).

    The axis is yearly US dollars: a band `pay_period.not_yearly_usd` refuses
    is counted under the reason it gives, `not_usd` or `not_yearly`. An amount
    that is no pay at any size stays `implausible`.
    """
    counts: dict[tuple[str, str, int, int], int] = {}
    excluded = {"unclear": 0, "total": 0, "not_usd": 0, "not_yearly": 0, "implausible": 0}

    for company, band, lo, hi, basis, currency, period in rows:
        if lo is None or hi is None or company is None or band is None:
            continue
        if basis != "base":
            if basis in excluded:
                excluded[basis] += 1
            continue
        refused = not_yearly_usd(lo, hi, currency, period)
        if refused:
            excluded[refused] += 1
            continue
        lo, hi = int(lo), int(hi)
        if lo < DISCLOSED_FLOOR or hi < lo:
            excluded["implausible"] += 1
            continue
        counts[(company, band, lo, hi)] = counts.get((company, band, lo, hi), 0) + 1

    bands = [
        {"company": c, "level_band": b, "low": lo, "high": hi, "reqs": n}
        for (c, b, lo, hi), n in counts.items()
    ]
    # Seniority, then the widest-paying band first within a level.
    bands.sort(key=_band_order)

    truncated = len(bands) > limit
    if truncated:
        # Keep the bands carrying the most open reqs, then restore the sort order.
        bands = sorted(bands, key=lambda d: (-d["reqs"], _band_order(d)))[:limit]
        bands.sort(key=_band_order)

    return {
        "bands": bands,
        "reqs": sum(b["reqs"] for b in bands),
        "companies": len({b["company"] for b in bands}),
        "excluded": excluded,
        "truncated": truncated,
    }


# --- pay transparency: the disclosure RATE and its longitudinal grain ---------
#
# `build_disclosed_bands` above answers "what did employers print?". These answer
# "how many of them printed anything?" — a different question with a different
# denominator, and the one field nothing aggregated. Both builders take the same
# per-role row shape:
#
#     (company, level_band, structured_at, disclosed_base_min,
#      disclosed_base_max, disclosed_pay_basis)

# A band with no stated basis still counts as disclosed (the employer printed a
# range), but it cannot be pooled with base pay — park it with the other rows
# that can't sit on a base-pay axis.
DISCLOSED_BASIS_FALLBACK = "unclear"


def _disclosure_state(
    structured_at: object, base_min: object, base_max: object, pay_basis: object
) -> tuple[bool, str]:
    """`(checked, pay_basis)` for one open role; `pay_basis` is `''` if it stated nothing.

    `pay_disclosure.disclosure_known`, the reading the detail and the
    `discloses_pay` filter share: a stored band discloses whoever
    wrote it, and a role with no band counts only once the text pass has read
    it. An unread role with no band contributes to neither side of the rate:
    absence of a band is not evidence the employer stated nothing, and
    counting it as a non-discloser would make the rate track extraction
    backlog instead of employer behaviour.
    """
    checked = disclosure_known(structured_at, base_min, base_max)
    if band_stated(base_min, base_max):
        return True, (str(pay_basis) if pay_basis else DISCLOSED_BASIS_FALLBACK)
    return checked, ""


def _rate(disclosed: int, checked: int) -> float | None:
    """Disclosure share, or None when nothing in the group has been checked yet."""
    return round(disclosed / checked, 4) if checked else None


def build_disclosure_rates(
    rows: Sequence[tuple],
    *,
    company_limit: int = 15,
) -> dict:
    """Share of open roles whose posting states a pay band, overall / per company / per level.

    `level_band` in each row is the level key (`db.queries.scope.level_key_expr`): roles
    whose level we cannot place are one `unstated` row, listed last.

    Basis-independent by construction: a posted range counts the same whether it
    is base, total or unclear — the question is whether the employer said
    anything, not what they said. (Band *values* are basis-scoped and handled by
    `build_disclosed_bands` / the snapshot below.)

    Each row is `(company, level_band, structured_at, base_min, base_max,
    pay_basis)`; the snapshot's rows carry two more columns after these, which
    the rate does not read.

    The denominator is `checked`, not `open`: `open - checked` roles are still
    queued for the disclosure pass, so folding them in would report extraction
    progress as employer silence. Both counts are returned so the UI can state the
    backlog rather than hide it. A group with `checked == 0` keeps `rate: None`:
    no rate is honest there, and 0.0 would be a lie.

    `by_company` keeps the `company_limit` employers with the most checked
    roles, most first.
    """
    overall = {"open": 0, "checked": 0, "disclosed": 0}
    by_company: dict[str, dict] = {}
    by_level: dict[str, dict] = {}

    for company, level_band, structured_at, lo, hi, basis, *_ in rows:
        checked, cell_basis = _disclosure_state(structured_at, lo, hi, basis)
        for bucket in (
            overall,
            by_company.setdefault(company, {"open": 0, "checked": 0, "disclosed": 0}),
            by_level.setdefault(level_band or "", {"open": 0, "checked": 0, "disclosed": 0}),
        ):
            bucket["open"] += 1
            bucket["checked"] += int(checked)
            bucket["disclosed"] += int(bool(cell_basis))

    def _largest(entries: list[dict]) -> list[dict]:
        # The employers most checked roles are at, whatever they post. Cut by
        # rate instead, the limit keeps only employers that all post a range
        # (or, lowest first, all post none), since many sit at each end. The
        # name breaks a tie, so the limit cuts the same employers on every
        # read of one table.
        return sorted(entries, key=lambda d: (-d["checked"], d["company"]))

    companies = _largest(
        [{"company": c, **v, "rate": _rate(v["disclosed"], v["checked"])} for c, v in by_company.items()]
    )[:company_limit]
    levels = [
        {"level_band": lb, **v, "rate": _rate(v["disclosed"], v["checked"])}
        for lb, v in sorted(by_level.items(), key=lambda kv: level_order(kv[0]))
    ]

    return {
        "overall": {**overall, "rate": _rate(overall["disclosed"], overall["checked"])},
        "by_company": companies,
        "by_level": levels,
    }


def build_disclosure_snapshot_rows(rows: Sequence[tuple]) -> list[dict]:
    """Collapse open roles into the daily `disclosure_snapshot` grain.

    One entry per `(company, level_band, pay_basis)` carrying `roles`, `checked`
    and the *distinct* bands in that cell as `{low, high, reqs}`. Roles that
    stated nothing land under `pay_basis == ""`, so the open count is the sum over
    every basis and the disclosed count is the sum over the non-empty ones.

    Each row is the rate's six columns followed by the band's currency and
    period. Band values (not the rate) apply `build_disclosed_bands`' rules, as
    the trend draws them on a yearly US-dollar axis: a band in another currency
    or period (`pay_period.not_yearly_usd`) still counts as disclosed and adds
    no band entry, and so does one under the plausibility floor. Anthropic's
    literal `Annual Salary: $1—$2 USD` is a real disclosure, so it belongs in
    the rate, but it is not a salary, so it must never enter a band percentile.
    A one-sided band (only a min, or only a max) counts as disclosed and
    contributes no band entry, since it spans nothing.
    """
    cells: dict[tuple[str, str, str], dict] = {}

    for company, level_band, structured_at, lo, hi, basis, currency, period in rows:
        if company is None:
            continue
        checked, cell_basis = _disclosure_state(structured_at, lo, hi, basis)
        cell = cells.setdefault(
            (company, level_band or "", cell_basis),
            {"roles": 0, "checked": 0, "bands": {}},
        )
        cell["roles"] += 1
        cell["checked"] += int(checked)
        if cell_basis and lo is not None and hi is not None and not not_yearly_usd(lo, hi, currency, period):
            lo, hi = int(lo), int(hi)
            if lo >= DISCLOSED_FLOOR and hi >= lo:
                cell["bands"][(lo, hi)] = cell["bands"].get((lo, hi), 0) + 1

    return [
        {
            "company": company,
            "level_band": level_band,
            "pay_basis": pay_basis,
            "roles": cell["roles"],
            "checked": cell["checked"],
            "bands": [
                {"low": lo, "high": hi, "reqs": reqs}
                for (lo, hi), reqs in sorted(cell["bands"].items())
            ],
        }
        for (company, level_band, pay_basis), cell in cells.items()
    ]
