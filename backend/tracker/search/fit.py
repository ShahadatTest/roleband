"""Fit: how the board's roles score against the standing intent vector.

The one expression `1 - cosine_distance` lives here, with the quantization the
settings instrument draws and the two statements that read it, so a histogram
bin or a band boundary is testable without an HTTP request. The band preview and
the band count are the same claim made twice, the pair that must not drift.

Bands are a PRESENTATIONAL quantization for the settings visual only; the board
itself never renders the score (`src/api/intelligence.ts` rule). Their edges are
multiples of the bin width so band counts are exact sums of bins, and they are
fixed constants, not learned.

Not deduplicated, deliberately: `search/best_match.py` orders by the DISTANCE
(`cosine_distance(...).label("intent_distance")`), not by `1 - distance`. The row
order is the same but the projected column is not, and it reaches the client.
`notifications/digest.py` DOES use this expression, and a compile-comparison test
holds the two to being the same SQL.
"""

from __future__ import annotations

from sqlalchemy import func, select

from tracker.db.models import Job
from tracker.db.queries.jobs import apply_job_filters

#: Histogram resolution. Band edges below are multiples of it, so no bin ever
#: straddles two bands.
FIT_BIN_WIDTH = 0.02

#: Lower fit edge per band, highest first; "weak" is everything below the last.
#: The names are the dashboard's, by key; the middle word here is
#: what the notification digest and the server's logs say.
FIT_BAND_EDGES: tuple[tuple[str, str, float], ...] = (
    ("strong", "Strong", 0.60),
    ("good", "Good", 0.50),
    ("some", "Fair", 0.42),
)

#: Every band a caller may ask for, including the implicit tail.
BAND_KEYS = frozenset({key for key, _label, _edge in FIT_BAND_EDGES} | {"weak"})


def fit_expr(intent_vec: list[float]):
    """Fit = 1 - cosine distance. Embeddings are normalized, so this is cosine
    similarity: 1.0 is the same direction as the intent vector, 0.0 orthogonal."""
    return 1 - Job.embedding.cosine_distance(intent_vec)


def fit_bands(by_bin: list[tuple[int, int]]) -> list[dict]:
    """Quantize bin counts into the four presentational bands, highest first.

    Band edges are exact bin boundaries (multiples of the bin width), so the
    band counts are sums of bins with nothing split or double-counted; the
    four counts always sum to the histogram total. Each band carries its lower
    edge (`band_bounds`; None for weak, open below), which is where the
    dashboard draws it.
    """
    edges = [int(round(edge / FIT_BIN_WIDTH)) for _, _, edge in FIT_BAND_EDGES]
    bands: list[dict] = []
    prev_lo: int | None = None
    for (key, _label, _edge), lo in zip(FIT_BAND_EDGES, edges, strict=True):
        count = sum(c for b, c in by_bin if b >= lo and (prev_lo is None or b < prev_lo))
        bands.append({"key": key, "count": count, "lower_edge": band_bounds(key)[0]})
        prev_lo = lo
    bands.append({
        "key": "weak",
        "count": sum(c for b, c in by_bin if b < edges[-1]),
        "lower_edge": band_bounds("weak")[0],
    })
    return bands


def histogram_stmt(params: dict, intent_vec: list[float]):
    """Bin counts of fit = 1 - cosine distance over the board's browse base.

    Only embedded rows can be binned; the endpoint reports the remainder as
    `unranked` instead of silently shrinking the denominator.
    """
    fit = fit_expr(intent_vec)
    bucket = func.floor(fit / FIT_BIN_WIDTH).label("bin")
    stmt = apply_job_filters(select(bucket, func.count()), params)
    return stmt.where(Job.embedding.isnot(None)).group_by(bucket)


def band_bounds(band: str) -> tuple[float | None, float | None]:
    """[lo, hi) fit range of one presentational band; None = unbounded side.

    Derived from `FIT_BAND_EDGES` so the range can never drift from the
    quantization the histogram draws — a band preview showing roles the band
    count doesn't include would be the settings screen lying about itself.
    """
    keys = [key for key, _label, _edge in FIT_BAND_EDGES]
    if band == "weak":
        return None, FIT_BAND_EDGES[-1][2]
    i = keys.index(band)
    hi = None if i == 0 else FIT_BAND_EDGES[i - 1][2]
    return FIT_BAND_EDGES[i][2], hi


def band_stmt(params: dict, intent_vec: list[float], band: str, limit: int):
    """The strongest rows of one band — best fit first, stable id tiebreak."""
    fit = fit_expr(intent_vec)
    stmt = apply_job_filters(select(Job), params).where(Job.embedding.isnot(None))
    lo, hi = band_bounds(band)
    if lo is not None:
        stmt = stmt.where(fit >= lo)
    if hi is not None:
        stmt = stmt.where(fit < hi)
    return stmt.order_by(fit.desc(), Job.id.desc()).limit(limit)

