"""Hiring-velocity analytics for the Statistics "Velocity" sub-tab.

Pure, DB-free assembly of pipeline-motion signals over a time window: how many
roles opened / were updated / closed, the net flow, the aging distribution of
still-open roles, and how long the postings that disappeared had been observed.
Unlike the other analytics sub-tabs this one is inherently period-scoped, so it
honors the shared period lens. The API layer runs the SQL (event counts, ages in
days, observed durations) and hands primitives here so all the shaping is
unit-testable.

**This is not time-to-fill, and never was.** The sample is
`closed_at - first_seen`: from the first observation in a posting's lineage to
the reconciliation that found it gone. RoleBand sees a public board, so it can
say a posting stopped being advertised and cannot say a person was hired —
employers legitimately unpublish, pause, re-post and schedule expiry, and a
posting can also vanish because our own scan of that board changed. A name like
"time to fill" would assert an employer outcome from an availability
observation, so the measure is `median_observed_listing_duration_days`.

Young-data note: the duration needs closed roles with a spread of values, and
the aging bands only spread as history accrues — the UI flags this.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from tracker.analytics.age_basis import employer_dated_share

# (lo_days_inclusive, hi_days_exclusive|None): fixed so the axis is stable. The
# dashboard names each band by `lo` (`insights-aging-from-<lo>-days`);
# `tests/test_vocab_catalog.py` holds the two together.
AGING_BANDS: tuple[tuple[int, int | None], ...] = (
    (0, 7),
    (7, 14),
    (14, 30),
    (30, 60),
    (60, 90),
    (90, None),
)

# Below this many closed roles the observed duration is too thin for a median.
MIN_DURATION_SAMPLE = 5

DURATION_KEY = "median_observed_listing_duration_days"


def _median(vals: Sequence[float]) -> float | None:
    """Linear-interpolated median; None on empty input."""
    s = sorted(vals)
    n = len(s)
    if n == 0:
        return None
    mid = (n - 1) / 2
    lo = int(mid)
    if mid == lo:  # whole index (odd n) -> the middle element
        return float(s[lo])
    return (s[lo] + s[lo + 1]) / 2  # even n -> mean of the two middle elements


def aging_histogram(days_open: Iterable[float]) -> list[dict]:
    """Bucket still-open ages (in days) into the fixed AGING_BANDS, zero-filled."""
    counts = [0] * len(AGING_BANDS)
    for d in days_open:
        for i, (lo, hi) in enumerate(AGING_BANDS):
            if d >= lo and (hi is None or d < hi):
                counts[i] += 1
                break
    return [
        {"lo": lo, "hi": hi, "count": counts[i]}
        for i, (lo, hi) in enumerate(AGING_BANDS)
    ]


def build_velocity(
    open_rows: Sequence[tuple],
    event_rows: Iterable[tuple],
    duration_rows: Sequence[tuple],
    open_total: int,
    days: int,
    *,
    company_limit: int = 15,
    open_employer_dated: int = 0,
    closed_employer_dated: int = 0,
) -> dict:
    """Assemble the velocity payload from pre-fetched primitives.

    `open_rows`: `(company, days_open)` for currently-open roles (age measured from
        the effective/lineage first_seen).
    `event_rows`: `(company, event_type, count)` for the window: roles first
        seen in it, and lifecycle events in it. `opened` counts only
        genuinely-new roles; a repost/duplicate re-listing arrives as a
        synthetic `reposted` type, so it never inflates opened or net.
        `changed` surfaces as "updated". A role a company's first read found
        arrives as `first_scan`: the board was already listing it, so it is
        counted apart and never in opened or net.
    `duration_rows`: `(company, observed_days)` for roles that closed in the window
        (one sample per lineage — only a terminal, fully-closed member contributes).
        Observed availability, not a hire: see the module docstring.
    `open_employer_dated` / `closed_employer_dated`: how many of `open_rows` /
        `duration_rows` carry an employer date (`analytics.age_basis`). The ages
        and durations stay on our first-sighting clock; the shares say how much
        of each sample the employer also dated.
    Companies are ranked by opened count (then open count) and capped.
    """
    ages_by_co: dict[str, list[float]] = {}
    for company, d in open_rows:
        ages_by_co.setdefault(company, []).append(float(d))

    opened: dict[str, int] = {}
    updated: dict[str, int] = {}
    closed: dict[str, int] = {}
    reposted: dict[str, int] = {}
    first_scan: dict[str, int] = {}
    bucket = {
        "opened": opened, "changed": updated, "closed": closed, "reposted": reposted,
        "first_scan": first_scan,
    }
    for company, event_type, n in event_rows:
        target = bucket.get(event_type)
        if target is not None:
            target[company] = target.get(company, 0) + int(n)

    duration_by_co: dict[str, list[float]] = {}
    for company, observed in duration_rows:
        duration_by_co.setdefault(company, []).append(float(observed))

    all_durations = [d for vs in duration_by_co.values() for d in vs]
    all_ages = [a for vs in ages_by_co.values() for a in vs]
    tot_opened = sum(opened.values())
    tot_closed = sum(closed.values())

    companies = (
        set(ages_by_co) | set(opened) | set(updated) | set(closed)
        | set(reposted) | set(duration_by_co)
    )
    by_company = sorted(
        (
            {
                "company": c,
                "open": len(ages_by_co.get(c, [])),
                "opened": opened.get(c, 0),
                "updated": updated.get(c, 0),
                "closed": closed.get(c, 0),
                "reposted": reposted.get(c, 0),
                "median_days_open": _median(ages_by_co.get(c, [])),
                DURATION_KEY: _median(duration_by_co[c]) if c in duration_by_co else None,
            }
            for c in companies
        ),
        key=lambda d: (d["opened"], d["open"]),
        reverse=True,
    )[:company_limit]

    return {
        "days": days,
        "kpis": {
            "open_total": open_total,
            "opened": tot_opened,
            "updated": sum(updated.values()),
            "closed": tot_closed,
            "reposted": sum(reposted.values()),
            "first_scan": sum(first_scan.values()),
            "net": tot_opened - tot_closed,
            "median_days_open": _median(all_ages),
            "employer_dated_share": employer_dated_share(open_employer_dated, len(all_ages)),
            DURATION_KEY: (
                _median(all_durations) if len(all_durations) >= MIN_DURATION_SAMPLE else None
            ),
            "closed_sample": len(all_durations),
            "closed_employer_dated_share": employer_dated_share(
                closed_employer_dated, len(all_durations)
            ),
        },
        "aging": aging_histogram(all_ages),
        # How long the postings that came down stayed up, on the same bands, so
        # Pace's two distributions are one height.
        "posted": aging_histogram(all_durations),
        "by_company": by_company,
    }
