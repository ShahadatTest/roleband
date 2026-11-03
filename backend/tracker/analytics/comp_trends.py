"""Compensation-trend rollup engine.

Mirrors `demand.compute_demand_metrics` / `skills.analytics.compute_skill_demand`
for the comp layer: once per pipeline run it snapshots comp percentiles over
currently-open roles at four grains (overall + per company / level / family) and
upserts one dated slice per grouping into `comp_metrics`. This is the longitudinal
series the Statistics "Compensation" trend reads. The percentile math is the pure,
DB-free `comp_stats.build_comp_metric_rows`; this module only does the SQL + upsert.

The same shape is repeated for pay *transparency* (`disclosure_snapshot`): what
employers literally published, versus the imputed estimate the comp tables track.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import UTC, datetime

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from tracker.analytics.comp_stats import (
    _pctiles,
    _percentile,
    _rate,
    build_comp_metric_rows,
    build_disclosure_snapshot_rows,
)
from tracker.db.models import (
    CompMetric,
    CompSnapshot,
    DisclosureSnapshot,
    Job,
    JobCompEstimate,
    ReferenceState,
)
from tracker.db.queries.scope import level_key_expr
from tracker.levels import UNSTATED_LEVEL
from tracker.schema import OUR_ESTIMATE_SOURCE

# Posted bands may only ever be pooled within one pay basis: base pay and total
# comp are different quantities, so mixing them would chart a number
# that measures nothing. Base is the only basis with a trustworthy span.
DISCLOSURE_BASIS = "base"


def build_comp_trend_series(
    rows: Iterable[tuple[str, str, str, str, Sequence[int]]], dim: str
) -> dict:
    """Recompute the comp trend for `dim` from raw daily snapshot values.

    `rows` are `(date_iso, company, level_band, family, comp_values)` — the
    `comp_snapshot` grain. For the requested `dim` the raw value arrays are
    concatenated up to that grouping and percentiles taken fresh, so the result is
    *exact* for whatever set of companies is present in `rows`. This is the property
    stored percentiles cannot provide: a subset's median is not recoverable from
    per-company medians. Returns `{axis, series}` where each series is
    `{key, count, points:[{date,p25,p50,p75,p90}]}`; callers add display labels.
    """

    def _key_for(company: str, level_band: str, family: str) -> str | None:
        if dim == "overall":
            return ""
        if dim == "company":
            return company
        if dim == "level" and level_band == UNSTATED_LEVEL:
            return None  # an estimate looked up at a guessed band
        value = level_band if dim == "level" else family
        return value or None  # skip the "" sentinel rows for level/family

    raw: dict[str, dict[str, list[int]]] = {}  # key -> date_iso -> values
    dates: set[str] = set()
    for date_iso, company, level_band, family, comp_values in rows:
        key = _key_for(company, level_band or "", family or "")
        if key is None:
            continue
        dates.add(date_iso)
        raw.setdefault(key, {}).setdefault(date_iso, []).extend(comp_values or [])

    axis = sorted(dates)
    latest_date = axis[-1] if axis else None

    by_key: dict[str, dict[str, dict]] = {}
    latest_count: dict[str, int] = {}
    for key, by_date in raw.items():
        for date_iso, vals in by_date.items():
            pct = _pctiles(vals)
            by_key.setdefault(key, {})[date_iso] = {
                "date": date_iso,
                "p25": pct["p25"],
                "p50": pct["p50"],
                "p75": pct["p75"],
                "p90": pct["p90"],
            }
            if date_iso == latest_date:
                latest_count[key] = pct["count"]

    def _recent_p50(key: str) -> float:
        return (by_key[key].get(latest_date or "") or {}).get("p50") or 0.0

    empty = {"date": None, "p25": None, "p50": None, "p75": None, "p90": None}
    series = [
        {
            "key": key,
            "count": latest_count.get(key, 0),
            "points": [by_key[key].get(d, {**empty, "date": d}) for d in axis],
        }
        for key in sorted(by_key, key=_recent_p50, reverse=True)
    ]
    return {"axis": axis, "series": series}


async def compute_comp_metrics(session: AsyncSession) -> int:
    """Recompute today's comp percentile slices. Returns the number of rows written.

    Writes two representations of the same open-role comp: `comp_metrics` (stored
    percentiles, read directly) and `comp_snapshot` (raw values per company/level/
    family, so the trend can recompute exact percentiles over a visible-company
    subset at read time). Both REPLACE today's rows: a group that no
    longer has an open in-scope posting with comp is gone from today, and its
    old values never pool with the survivors. Earlier days are untouched.

    Grouped by the level key (`db.queries.scope.level_key_expr`): a role whose
    level we cannot place is `unstated`. Older days may hold the band instead,
    with an unplaced role under its sort band or guess; they carry no basis to
    re-split and are kept as written.

    One series per source, never mixed: `comp_snapshot` keeps ours
    every day and the selected plugin's while it answers pay (the applied
    reference set's), each from its own stored estimates (`job_comp_estimate`).
    `comp_metrics` keeps ours. The values carry no currency and the trend draws
    them in US dollars, so an estimate in another currency is left out.
    """
    today = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    applied = await session.scalar(select(ReferenceState.applied_providers).where(ReferenceState.id == 1))
    plugin = ((applied or {}).get("active") or {}).get("pay.levels") or []
    sources = [OUR_ESTIMATE_SOURCE, *plugin[:1]]

    estimated = (
        await session.execute(
            select(Job.company, level_key_expr(Job), Job.family, JobCompEstimate.comp_median,
                   JobCompEstimate.source)
            .join(JobCompEstimate, JobCompEstimate.job_id == Job.id)
            .where(Job.status == "open", Job.in_scope.is_(True), JobCompEstimate.source.in_(sources),
                   JobCompEstimate.comp_currency == "USD")
        )
    ).all()
    rows = [(company, level, family, median) for company, level, family, median, source in estimated
            if source == OUR_ESTIMATE_SOURCE]

    metrics = [
        {"metric_date": today, "dim": slice_["dim"], "key": slice_["key"],
         **{k: slice_[k] for k in ("count", "p25", "p50", "p75", "p90")}}
        for slice_ in build_comp_metric_rows([tuple(r) for r in rows])
    ]
    # `filter_by`, not `CompMetric.metric_date`: the table is written and read
    # by nothing (`db/ownership.py`), and the reader scan counts a column.
    await session.execute(delete(CompMetric).filter_by(metric_date=today))
    if metrics:
        await session.execute(insert(CompMetric), metrics)

    # Raw values grouped by (company, level_band, family); "" is the sentinel the
    # read path never queries by, so it just needs to be NULL-free for the upsert.
    grouped: dict[tuple[str, str, str, str], list[int]] = {}
    for company, level_band, family, comp_median, source in estimated:
        if comp_median is None:
            continue
        key = (company, level_band or "", family or "", source)
        grouped.setdefault(key, []).append(int(comp_median))
    await session.execute(delete(CompSnapshot).where(CompSnapshot.metric_date == today,
                                                     CompSnapshot.source != "mixed"))
    if grouped:
        await session.execute(
            insert(CompSnapshot),
            [
                {"metric_date": today, "company": company, "level_band": level_band,
                 "family": family, "source": source, "comp_values": comp_values}
                for (company, level_band, family, source), comp_values in grouped.items()
            ],
        )

    return len(metrics)


def build_disclosure_trend_series(
    rows: Iterable[tuple[str, str, str, str, int, int, Sequence[dict]]],
    dim: str,
    *,
    basis: str = DISCLOSURE_BASIS,
) -> dict:
    """Recompute the pay-transparency trend for `dim` from raw daily snapshot cells.

    `rows` are `(date_iso, company, level_band, pay_basis, roles, checked, bands)` —
    the `disclosure_snapshot` grain. Returns `{axis, series}` where each series is
    `{key, checked, disclosed, points}` and a point is
    `{date, open, checked, disclosed, rate, bands, reqs, low_p50, high_p50}`.

    Two aggregations with different scopes, which is the whole reason the snapshot
    keeps `pay_basis` on the row:

    * **rate** sums every basis (including `''`, the roles that stated nothing),
      because "did the employer publish anything?" does not care what they
      published. Recomputed from counts rather than stored, so hiding a company
      removes it exactly from every historical point.
    * **band medians** pool only rows whose `pay_basis == basis`. One vote per
      *distinct* band, not per req: an employer hangs many reqs off one published
      band, so req-weighting would report which band is most reposted
      rather than what employers publish. `reqs` is carried alongside so the UI
      can still say how many open roles ride on those bands.

    The market line moves when the company set does: companies added
    mid-window may state pay more or less often than the first set, so the
    all-companies rate can move while the original companies' does not. For `overall`, when a company was read on a
    later day that was not on the first, a second series keyed `cohort` follows
    only the companies read on the first day, and `cohort` names them by count
    and date. Otherwise `cohort` is None.
    """
    rows = list(rows)

    def _key_for(company: str, level_band: str) -> str | None:
        if dim == "overall":
            return ""
        if dim == "company":
            return company
        return level_band or None  # skip the "" unclassified sentinel for level

    # key -> date -> counters + the distinct bands seen on that date
    raw: dict[str, dict[str, dict]] = {}
    dates: set[str] = set()
    for date_iso, company, level_band, pay_basis, roles, checked, bands in rows:
        key = _key_for(company, level_band or "")
        if key is None:
            continue
        dates.add(date_iso)
        cell = raw.setdefault(key, {}).setdefault(
            date_iso, {"open": 0, "checked": 0, "disclosed": 0, "bands": []}
        )
        cell["open"] += roles
        cell["checked"] += checked
        if pay_basis:
            cell["disclosed"] += roles
        if pay_basis == basis:
            cell["bands"].extend(bands or [])

    axis = sorted(dates)
    latest_date = axis[-1] if axis else None

    def _point(date_iso: str, cell: dict) -> dict:
        bands = cell["bands"]
        lows = sorted(int(b["low"]) for b in bands)
        highs = sorted(int(b["high"]) for b in bands)
        return {
            "date": date_iso,
            "open": cell["open"],
            "checked": cell["checked"],
            "disclosed": cell["disclosed"],
            "rate": _rate(cell["disclosed"], cell["checked"]),
            "bands": len(bands),
            "reqs": sum(int(b["reqs"]) for b in bands),
            "low_p50": _percentile(lows, 0.5),
            "high_p50": _percentile(highs, 0.5),
        }

    by_key = {
        key: {date_iso: _point(date_iso, cell) for date_iso, cell in by_date.items()}
        for key, by_date in raw.items()
    }

    def _latest(key: str) -> dict:
        return by_key[key].get(latest_date or "") or {}

    empty = {
        "open": 0, "checked": 0, "disclosed": 0, "rate": None,
        "bands": 0, "reqs": 0, "low_p50": None, "high_p50": None,
    }
    series = [
        {
            "key": key,
            "checked": _latest(key).get("checked", 0),
            "disclosed": _latest(key).get("disclosed", 0),
            "points": [by_key[key].get(d, {**empty, "date": d}) for d in axis],
        }
        # Most-transparent first; a group with nothing checked yet has no rate and
        # sorts last rather than pretending to a 0% disclosure rate.
        for key in sorted(
            by_key,
            key=lambda k: (_latest(k).get("rate") is None, -(_latest(k).get("rate") or 0)),
        )
    ]
    cohort = None
    if dim == "overall" and len(axis) > 1:
        first = {r[1] for r in rows if r[0] == axis[0] and r[5] > 0}
        later = {r[1] for r in rows if r[5] > 0} - first
        if first and later:
            sub = build_disclosure_trend_series([r for r in rows if r[1] in first], "overall", basis=basis)
            on = {p["date"]: p for p in sub["series"][0]["points"]}
            fixed = sub["series"][0]
            series.append({**fixed, "key": "cohort", "points": [on.get(d, {**empty, "date": d}) for d in axis]})
            cohort = {"since": axis[0], "companies": len(first)}
    return {"axis": axis, "series": series, "cohort": cohort}


async def compute_disclosure_metrics(session: AsyncSession) -> int:
    """Recompute today's pay-transparency snapshot. Returns the number of cells written.

    Replaces (rather than upserts) the day's rows: these cells are *denominators*,
    so a cell that emptied since an earlier run today — every role in it closed —
    must disappear, not linger and inflate the open count. The comp tables upsert
    because a stale percentile is merely stale; a stale denominator is wrong.
    Delete + insert runs inside the pass's single transaction, so the day is never
    observably empty.
    """
    today = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)

    rows = (
        await session.execute(
            select(
                Job.company,
                level_key_expr(Job),
                Job.structured_at,
                Job.disclosed_base_min,
                Job.disclosed_base_max,
                Job.disclosed_pay_basis,
                Job.disclosed_currency,
                Job.disclosed_pay_period,
            ).where(Job.status == "open", Job.in_scope.is_(True))
        )
    ).all()

    cells = build_disclosure_snapshot_rows([tuple(r) for r in rows])

    await session.execute(
        delete(DisclosureSnapshot).where(DisclosureSnapshot.metric_date == today)
    )
    session.add_all([DisclosureSnapshot(metric_date=today, **cell) for cell in cells])

    return len(cells)
