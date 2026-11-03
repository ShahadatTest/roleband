"""Base pay per company x family x band from our own dataset.

Our per-level pay, for every named company at every level it posts at. This
module is that computation; the built-in pay builder (`enrich.builtin_pay`)
serves it. `scripts.bench_level_pay` compares it with any provider's stored
per-level baseline and lists what it cannot answer, and
`scripts.atlas_completeness` scores it as the `level_base` section.

Three kinds of evidence, kept apart because they measure different things:

- **filed**: government filings (`atlas/title_pay.csv`), one cell per company x
  title x state x year. The title is read HERE, at use time, by the same reader
  a posting goes through (`classify_family`, `read_level`), so a reader change
  needs no rebuild. A title the reader
  cannot place (basis `none` or `unmapped`: "Software Engineer", "Engineering
  Manager") answers no band, exactly as it passes no level gate, with these
  filing-only rules: an exact code at the title head names a rung of the
  applicable family ladder, without changing posting readings; a cell whose filings
  are 90%+ at wage level I reads entry, and at a flat firm (an entry hire plus
  one rung) a plain title reads that one rung. Postings never read these rules. The figure is
  the median of the cells' medians weighted by filings, over the latest filing
  year the key has; an older year is history. A filing states the offered base
  FROM, which sits at or below the posted range's middle.
- **posted**: ranges the company posts at one rung or band (`pay_grades.csv`,
  `pay_bands.csv`), latest year; each end is the median of the
  ranges' ends weighted by their anchoring postings, so the range most
  postings carry decides over a range a few postings carry.
  Direct stored US annual USD base cells (`posted_pay.csv`) retain title,
  department, team and printed code, read at use time without the range.
  Confirmed independently stated levels price pay even with one
  posting; unplaced/dual titles price nothing. Direct evidence replaces the
  same key's mapping anchors to avoid counting postings twice; newer mapping
  evidence survives an older direct cell. Range-to-level mapping stays under
  the two-anchor rule (`levels.pay_grades`). Each figure carries ranges and posting count.
- **estimated**: estimated pay points (`estimated_pay.csv`). The atlas alone places
  each original rung label, in its family ladder. A filed or posted base wins;
  estimated base fills remaining keys. Annualised equity and estimated cash bonus
  remain separate points. The collected points carry no sample counts and do
  not tell a zero component from a missing one, so neither is invented. No company policy
  is inferred; cash at a no-annual-bonus firm may be sign-on and cannot price annual bonus.

No n floor: every figure carries its count. No fallback to another family,
year or parent company, and no live source lookup: a key with no captured
evidence is absent.

Pure: reads the atlas files; cached per process.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from functools import cache

from tracker.enrich.classify import classify_family
from tracker.enrich.estimated_pay import EstimatedPay, estimated_bases
from tracker.enrich.level_mapper import read_level, title_states_band
from tracker.levels.atlas import ESTIMATED_PAY, POSTED_PAY, TITLE_PAY, read_rows
from tracker.levels.ladder import band_for, reading_ladder
from tracker.levels.pay_grades import PAY_BANDS, PAY_GRADES, PayGrade
from tracker.schema import UNPLACED_BASES, LevelBand, RawJob

Key = tuple[str, str, LevelBand]  # company, taxonomy family, band


@dataclass(frozen=True)
class FiledBase:
    year: int  # the latest filing year the key has; the figure reads only it
    filings: int
    titles: int  # distinct filed titles behind the figure
    base: int  # filings-weighted median of the cells' median offered base


@dataclass(frozen=True)
class PostedBase:
    year: int
    ranges: int  # distinct posted ranges behind the figure
    base_min: int  # anchor-weighted median of the ranges' lower ends
    base_max: int  # anchor-weighted median of the ranges' upper ends
    postings: int = 0  # distinct posting evidence, not the number of different ranges

    @property
    def mid(self) -> int:
        return (self.base_min + self.base_max) // 2


@dataclass(frozen=True)
class LevelBase:
    company: str
    family: str
    band: LevelBand
    filed: FiledBase | None
    posted: PostedBase | None
    estimated: EstimatedPay | None = None

    @property
    def base(self) -> int:
        """Filed offer, else posted midpoint, else estimated point; never mixed."""
        if self.filed is not None:
            return self.filed.base
        if self.posted is not None:
            return self.posted.mid
        if self.estimated is not None:
            return self.estimated.base
        raise ValueError("no base evidence")


def weighted_median(points: Iterable[tuple[int, int]]) -> int:
    """The value at half the total weight of (weight, value) points: the lower
    middle on an exact tie, so the answer is always a value some cell holds."""
    ordered = sorted(points, key=lambda p: p[1])
    total = sum(w for w, _ in ordered)
    if total <= 0:
        raise ValueError("no weight")
    seen = 0
    for weight, value in ordered:
        seen += weight
        if seen * 2 >= total:
            return value
    raise AssertionError("unreachable")


#: A plain filed title reads entry when this share of its filings are at wage level I.
#: On filings whose titles state a level, level I tracks entry closely; levels II-IV
#: agree with the title's band too rarely to clear the evidence bar, so they place nothing.
WAGE_LEVEL_I_SHARE = 0.9
_WAGE_LEVELS = ("level_i", "level_ii", "level_iii", "level_iv")


@cache
def _filed_family(company: str, title: str) -> str | None:
    """The family a filed title classifies into. A filing carries no department or
    team, so company and title are the whole input; the same pair recurs across
    states and years, and both the reader and the filing-only rules ask for it."""
    return classify_family(RawJob(company=company, req_id="", title=title, url=""))


@cache
def _read_title(company: str, title: str) -> tuple[str, LevelBand] | None:
    """(family, band) the reader places this filed title at, or None."""
    family = _filed_family(company, title)
    if family is None:
        return None
    reading = read_level(RawJob(company=company, req_id="", title=title, url=""), family)
    if reading.basis in UNPLACED_BASES:
        return None
    return family, reading.band


@cache
def _flat_rung(company: str, family: str) -> LevelBand | None:
    """The one rung of a flat ladder (an optional entry hire plus exactly one other rung),
    which a plain title is by definition."""
    ladder = reading_ladder(company, family)
    if ladder is None:
        return None
    above = [r for r in ladder.rungs if r.band not in (LevelBand.INTERN, LevelBand.ENTRY)]
    return above[0].band if len(above) == 1 else None


def _place_filing(row: dict[str, str]) -> tuple[str, LevelBand] | None:
    """(family, band) for one filed cell: the title reader first; a title it cannot place
    (a plain "Software Engineer") reads entry when its filings are at wage level I, else the
    flat ladder's one rung. A literal atlas code at the head
    reads its applicable family rung. Filings only: postings never read this."""
    placed = _read_title(row["company"], row["title"])
    if placed is not None:
        return placed
    family = _filed_family(row["company"], row["title"])
    if family is None:
        return None
    # Filed titles can start with a literal atlas code (PMTS software ...),
    # even when the posting reader has no calibrated title profile for it.
    # Codes only: a role/rank word such as Manager is not an acronym. The
    # applicable family ladder owns the band; no source band or word guess.
    parts = row["title"].split()
    ladder = reading_ladder(row["company"], family)
    dual = len(parts) > 1 and parts[1].casefold() in {"and", "or", "/", "&", "+"}
    if parts and ladder is not None and not dual:
        for rung in ladder.rungs:
            if rung.code.isupper() and parts[0].casefold() == rung.code.casefold():
                return family, rung.band
    levels = [int(row.get(k) or 0) for k in _WAGE_LEVELS]
    if sum(levels) and levels[0] >= WAGE_LEVEL_I_SHARE * sum(levels):
        return family, LevelBand.ENTRY
    flat = _flat_rung(row["company"], family)
    return (family, flat) if flat is not None else None


def filed_bases(rows: Iterable[dict[str, str]]) -> dict[Key, FiledBase]:
    """`title_pay.csv` rows -> the filed figure per key."""
    cells: dict[Key, list[tuple[int, str, int, int]]] = defaultdict(list)
    for row in rows:
        placed = _place_filing(row)
        if placed is None:
            continue
        family, band = placed
        cells[(row["company"], family, band)].append(
            (int(row["year"]), row["title"], int(row["n"]), int(row["base_p50"]))
        )
    found: dict[Key, FiledBase] = {}
    for key, points in cells.items():
        year = max(p[0] for p in points)
        latest = [p for p in points if p[0] == year]
        found[key] = FiledBase(
            year=year,
            filings=sum(p[2] for p in latest),
            titles=len({p[1] for p in latest}),
            base=weighted_median((p[2], p[3]) for p in latest),
        )
    return found


def _grade_band(grade: PayGrade) -> LevelBand | None:
    if grade.band is not None:
        return grade.band
    if grade.rung is None:
        return None
    return band_for(grade.company, grade.rung, reading_ladder(grade.company, grade.family))


def posted_bases(grades: Iterable[PayGrade]) -> dict[Key, PostedBase]:
    """Measured posted ranges -> the posted figure per key."""
    ranges: dict[Key, list[PayGrade]] = defaultdict(list)
    for grade in grades:
        band = _grade_band(grade)
        if band is not None:
            ranges[(grade.company, grade.family, band)].append(grade)
    found: dict[Key, PostedBase] = {}
    for key, measured in ranges.items():
        year = max(g.year for g in measured)
        latest = [g for g in measured if g.year == year]
        found[key] = PostedBase(
            year=year,
            ranges=len({(g.base_min, g.base_max) for g in latest}),
            base_min=weighted_median((g.anchors, g.base_min) for g in latest),
            base_max=weighted_median((g.anchors, g.base_max) for g in latest),
            postings=sum(g.anchors for g in latest),
        )
    return found


def posted_title_grades(rows: Iterable[dict[str, str]]) -> list[PayGrade]:
    """Independently stated titles price pay, including single postings.

    Re-read title context without a range. Dual levels, role-word guesses,
    unconfirmed titles and pay-derived readings price nothing. The existing
    range mappings are not changed by these cells.
    """
    grades = []
    for row in rows:
        raw = RawJob(company=row["company"], req_id="", title=row["title"], url="",
                     department=row["department"] or None, team=row["team"] or None,
                     raw_level=row["raw_level"] or None)
        family = classify_family(raw)
        reading = read_level(raw, family)
        if family is None or not title_states_band(raw.title, reading, raw.raw_level, raw.company):
            continue
        grades.append(PayGrade(raw.company, family, int(row["base_min"]), int(row["base_max"]),
                               int(row["year"]), None, raw.title, int(row["n"]), reading.band))
    return grades


@cache
def level_bases() -> dict[Key, LevelBase]:
    """Every key our dataset answers: filed, posted or estimated."""
    filed = filed_bases(read_rows(TITLE_PAY))
    posted = posted_bases((*PAY_GRADES, *PAY_BANDS))
    # The direct corpus contains the mapping table's anchors too: replace per
    # key rather than double-count the same postings in both sources. An older
    # direct year never displaces newer measured ranges.
    direct = posted_bases(posted_title_grades(read_rows(POSTED_PAY)))
    posted.update({k: v for k, v in direct.items() if k not in posted or v.year >= posted[k].year})
    estimated = estimated_bases(read_rows(ESTIMATED_PAY))
    return {
        key: LevelBase(*key, filed=filed.get(key), posted=posted.get(key), estimated=estimated.get(key))
        for key in sorted(filed.keys() | posted.keys() | estimated.keys(), key=lambda k: (k[0], k[1], k[2].value))
    }


def level_base(company: str, family: str, band: LevelBand) -> LevelBase | None:
    return level_bases().get((company, family, band))


def answers(company: str) -> bool:
    """Does our dataset price this company's levels: a figure at two or more
    bands of one family? One band alone is a point, not a ladder of pay."""
    bands: dict[str, set[LevelBand]] = defaultdict(set)
    for slug, family, band in level_bases():
        if slug == company:
            bands[family].add(band)
    return any(len(found) >= 2 for found in bands.values())
