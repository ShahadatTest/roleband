"""The one rule for writing a posting's stated pay band.

Three writers state a band: the connector, from the detail read
(`db/repo._apply_fields`): a structured salary field, or the source's own pay
block scanned by the text scanner; the text pass, from the posting's words;
and the posting-page pass, from the page's own markup
(`intelligence_runtime/disclosed_comp`). A fourth, `correct_pay_periods`,
rewrites a stored band when the period rule shows it wrong.

Four things have to mean the same whoever wrote the row, or a reader cannot
tell which answer it is looking at. Every writer applies them:

**Precedence.** A band has one owner, `jobs.disclosed_source`. A writer may
replace a band its own source owns, or one owned by a weaker source. Stronger
first: a structured field beats the posting's text, which beats its page. The
page ranks last although its figures sit in markup: it is read once, while the
text states no pay, and never again while the posting has a band
(`workflows/posting_pages.owed_page_clause`), so it fills that gap and never
stands over what the text, read on every change, now says.

**Clearing.** A writer clears only a band it owns, and only when its own
source can say there is no pay. A read that failed states nothing and leaves
the band alone: silence is not a denial. A connector that reads a structured
salary field never clears: a listing with no pay field and a listing whose
employer withdrew a band arrive identically as `source_disclosed_comp is
None`, the same conflation `source_facts` names a line above it in
`_apply_fields`. A connector that scans the posting's text where its source
prints pay looked at the thing that would carry the figure, as the text and
page passes do, so a complete read of it that found none clears its own band
(`RawJob.pay_looked`).

**The place key.** Every writer records the place the band was chosen for.
A posting can state one band per city, so a listing that moves the posting to
another city owes a fresh read even though no text changed.

**The stamp.** Every writer records when it wrote and which reader produced
the figure. A writer never stamps another reader's version: the text parser's
version on a connector's structured field would make the stale gate reason
about a reader that never saw the row.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from tracker.enrich.classify import first_place

#: Strongest first. A writer may replace a band at or below its own rank.
PRECEDENCE: dict[str, int] = {"connector": 3, "text": 2, "page": 1}

#: Stamped by the connector, whether it read a structured field or scanned
#: its source's pay block: never the text pass's version, so the stale gate
#: can never mistake a connector band for one the text pass read.
CONNECTOR_READER_VERSION = "connector_field/1"

#: Every column a stated band owns. Clearing writes None to all of them.
BAND_COLUMNS = (
    "disclosed_base_min",
    "disclosed_base_max",
    "disclosed_currency",
    "disclosed_pay_basis",
    "disclosed_pay_period",
    "disclosed_snippet",
    "disclosed_confidence",
    "disclosed_bonus_pct",
)


def pay_place_key(locations: Any) -> str:
    """The place the band selector reads (`first_place`): its city and metro
    slugs, sorted and joined. Never the raw string, so a spelling of the same
    city is no change; "" for a first place that names no city."""
    return ",".join(sorted(first_place(locations or [])))


def may_write(current_source: str | None, writer: str) -> bool:
    """Whether `writer` may replace the band `current_source` owns.

    An unowned band (nothing stored, or a row from before sources were
    recorded) is free for anyone. A weaker source never overwrites a stronger
    one, so a prose reading cannot bury a figure the employer published in a
    field.
    """
    if current_source is None:
        return True
    return PRECEDENCE.get(writer, 0) >= PRECEDENCE.get(current_source, 0)


@dataclass(frozen=True)
class BandChange:
    """What a write did, for the caller that records history."""

    before: dict[str, Any]
    after: dict[str, Any]

    @property
    def moved(self) -> bool:
        """Did the stated figures change? Only the bounds count as a move: a
        re-read that settles a basis or a period restates the same pay."""
        return (self.before.get("disclosed_base_min"), self.before.get("disclosed_base_max")) != (
            self.after.get("disclosed_base_min"),
            self.after.get("disclosed_base_max"),
        )

    @property
    def had_band(self) -> bool:
        """Was there a band to move from? A first reading is not a move."""
        return _has_bounds(self.before)

    @property
    def gained(self) -> bool:
        """Did a posting with no band gain one? The first reading."""
        return not self.had_band and _has_bounds(self.after)

    def event_detail(self) -> dict[str, Any]:
        """The `disclosed_base` lifecycle detail, in the shape the feed reads:
        each side's bounds with the currency and period they are stated in."""
        return {"from": _event_side(self.before), "to": _event_side(self.after)}


def _event_side(band: dict[str, Any]) -> dict[str, Any]:
    return {
        "min": band.get("disclosed_base_min"),
        "max": band.get("disclosed_base_max"),
        "currency": band.get("disclosed_currency"),
        "period": band.get("disclosed_pay_period"),
    }


def _has_bounds(band: dict[str, Any]) -> bool:
    return any(band.get(c) is not None for c in ("disclosed_base_min", "disclosed_base_max"))


def band_snapshot(job: Any) -> dict[str, Any]:
    """The band columns as they stand, one side of a `BandChange`."""
    return {column: getattr(job, column, None) for column in BAND_COLUMNS}


def apply_band(
    job: Any,
    values: dict[str, Any] | None,
    *,
    source: str,
    version: str,
    now: Any,
    place_key: str,
) -> BandChange | None:
    """Write `values` as `source`'s band, or clear this source's band.

    `values` None means "this source states no pay". Returns what changed, or
    None when precedence refused the write: the caller records history only
    for a write that happened.
    """
    owner = getattr(job, "disclosed_source", None)
    if not may_write(owner, source):
        return None
    # A source's silence speaks only for that source, so even a stronger
    # source's "no pay" leaves another owner's band alone.
    if values is None and owner not in (None, source):
        return None
    before = band_snapshot(job)
    if values is None:
        for column in BAND_COLUMNS:
            setattr(job, column, None)
        job.disclosed_source = None
    else:
        for column in BAND_COLUMNS:
            setattr(job, column, values.get(column))
        job.disclosed_source = source
    # Stamped on a clear as much as a write: both are this reader's answer
    # about this posting at this place.
    job.structured_at = now
    job.structured_prompt_version = version
    job.disclosed_place_key = place_key
    return BandChange(before=before, after=band_snapshot(job))
