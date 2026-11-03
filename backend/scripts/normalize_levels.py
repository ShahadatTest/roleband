"""Read the raw pay store into level evidence per company.

    .venv/bin/python -m scripts.normalize_levels                       # every tracked company
    .venv/bin/python -m scripts.normalize_levels servicenow atlassian  # review sheets for these

The objective is seniority: which titles a company uses for which rung, so the
Board shows each opportunity at its real level. Pay is the cross-check, and it
is a good one even when it is old: within one company and one year, a higher
rung pays more, and inflation moves every rung of that year together. So rungs
are ordered by pay WITHIN a vintage, never across vintages.

Steps, all over `observations.csv` (`scripts.build_pay_observations`):

1. **Pay growth by vintage**, measured from the filings themselves: the same
   employer, title and state, filed in consecutive years, median ratio. Chained
   into an index that states a past year's pay in this year's terms
   (`growth_index.json`). An adjusted figure is labelled as adjusted; the
   stated one is always kept beside it.
2. **Recency weight**: a stated figure loses half its weight per year of age
   (`weight`), so the reference year dominates and two years back still counts.
3. **Level evidence**: every title read by the app's own `annotate` (family,
   track, band and how the band was read), plus the level words the title
   itself carries (`level_words`: "senior staff", "ii", "smts", "l5"). One row
   per company x family x track x band x basis x level words: n per vintage,
   the latest vintage's median, the adjusted median, sample titles
   (`level_evidence.csv`).
4. **Managers** (`manager_alignment.csv`): each manager title group beside the
   engineer band it is paid like, per vintage, and a recency-weighted verdict.
   A reviewer's hint only, never a band source (`manager_alignment`).
5. **Checks**: inside each company x family x track and each vintage, a higher
   band whose median sits below a lower band's (n >= 5 each) is an inversion:
   the reader, the ladder or the title words disagree with the pay
   (`inversions.csv`). These are the review list.

Review sheets, one per company asked for: `normalized/review/<company>.md`.
Read-only; writes only under the git-ignored sources directory.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
import statistics
import sys
from collections import defaultdict
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from tracker.platform.paths import DATA_DIR
from tracker.schema import LevelBand

SOURCES_DIR = DATA_DIR / "level-atlas-sources"
#: Weight halves for every year a figure is older than the reference year.
HALF_LIFE_YEARS = 1.0
#: Least cells a year-over-year growth ratio needs before it is trusted.
MIN_GROWTH_CELLS = 200
#: Least observations on each side of an inversion.
MIN_N = 5

BAND_ORDER = {band.value: i for i, band in enumerate(LevelBand)}

# The words a title uses to say its level, as they are written. Longest first,
# so "senior staff" is one marker and not "senior" + "staff".
_LEVEL_PHRASES = (
    "member of technical staff", "senior principal", "senior staff", "senior director", "senior manager",
    "vice president", "managing director", "associate director", "principal", "distinguished", "fellow",
    "senior", "staff", "lead", "associate", "junior", "intern", "chief", "head", "director", "manager",
    "partner", "entry",
)
_ABBREV = {"sr": "senior", "jr": "junior", "sr.": "senior", "jr.": "junior", "vp": "vice president",
           "svp": "senior vice president", "avp": "assistant vice president"}
_CODES = re.compile(r"^(?:[lpeti]c?\d{1,2}|ic\d{1,2}|e\d{1,2}|l\d{1,2}|p\d{1,2}|[sp]?mts|cl\d{1,2})$")
_ROMAN = {"i", "ii", "iii", "iv", "v", "vi"}


def level_words(title: str) -> str:
    """The level markers a title carries, in title order, `|`-separated."""
    text = " " + re.sub(r"[^a-z0-9.+ ]", " ", title.lower()) + " "
    for short, long in _ABBREV.items():
        text = text.replace(f" {short} ", f" {long} ")
    found: list[tuple[int, str]] = []
    taken = [False] * len(text)
    for phrase in _LEVEL_PHRASES:
        for m in re.finditer(rf"(?<= ){re.escape(phrase)}(?= )", text):
            if not any(taken[m.start():m.end()]):
                found.append((m.start(), phrase))
                for i in range(m.start(), m.end()):
                    taken[i] = True
    tokens = text.split()
    pos = 0
    for i, tok in enumerate(tokens):
        pos = text.index(f" {tok} ", pos) + 1
        clean = tok.strip(".")
        if _CODES.match(clean) or (clean in _ROMAN and i > 0) or (clean.isdigit() and len(clean) == 1 and i > 0):
            found.append((pos, clean))
        pos += len(tok)
    return "|".join(word for _, word in sorted(found))


# --- growth and weight ------------------------------------------------------ #


def growth_index(rows: Iterable[dict], reference_year: int) -> dict[str, dict]:
    """Per vintage: the factor that states its pay in `reference_year` terms.

    Cells are (employer, title, state) with filings in two consecutive
    vintages; the ratio of their medians, median over cells, is that year's
    growth. A year whose link has too few cells gets no index (its pay is then
    shown as stated only)."""
    cells: dict[tuple[str, str, str], dict[str, list[int]]] = defaultdict(lambda: defaultdict(list))
    for r in rows:
        if r["source"] != "dol_lca" or not r["vintage"]:
            continue
        key = (r["employer"].upper(), r["title"].lower(), r["location"].rsplit(", ", 1)[-1])
        cells[key][r["vintage"]].append(int(r["pay_low"]))
    links: dict[int, tuple[float, int]] = {}
    years = sorted({int(v) for c in cells.values() for v in c})
    for year in years:
        ratios = []
        for by in cells.values():
            a, b = by.get(str(year)), by.get(str(year + 1))
            if a and b:
                ratios.append(statistics.median(b) / statistics.median(a))
        if len(ratios) >= MIN_GROWTH_CELLS:
            links[year] = (statistics.median(ratios), len(ratios))
    out: dict[str, dict] = {str(reference_year): {"index": 1.0, "cells": None, "growth_to_next": None}}
    factor = 1.0
    for year in range(reference_year - 1, min(years, default=reference_year) - 1, -1):
        if year not in links:
            break
        ratio, n = links[year]
        factor *= ratio
        out[str(year)] = {"index": round(factor, 4), "cells": n, "growth_to_next": round(ratio - 1, 4)}
    return dict(sorted(out.items()))


def weight(vintage: str, reference_year: int) -> float:
    age = max(0, reference_year - int(vintage)) if vintage else 99
    return round(0.5 ** (age / HALF_LIFE_YEARS), 4)


# --- evidence ------------------------------------------------------------------ #


@dataclass
class Cell:
    company: str
    family: str
    track: str
    band: str
    basis: str
    level_words: str
    pay: dict[str, list[int]] = field(default_factory=lambda: defaultdict(list))
    titles: dict[str, int] = field(default_factory=lambda: defaultdict(int))

    @property
    def n(self) -> int:
        return sum(len(v) for v in self.pay.values())


def read_title(company: str, title: str) -> tuple[str, str, str, str]:
    """(family, track, band, basis) as the app reads the title today."""
    from tracker.enrich.enricher import annotate
    from tracker.schema import RawJob

    ann = annotate(RawJob(company=company, req_id="obs", title=title, url=""))
    return (ann.family or "unclassified", ann.track.value, ann.band.value if ann.band else "none", ann.basis.value)


def evidence(rows: Iterable[dict], reader=read_title) -> dict[tuple, Cell]:
    cells: dict[tuple, Cell] = {}
    seen: dict[tuple[str, str], tuple[str, str, str, str]] = {}
    for r in rows:
        if not r["company"] or r["pay_kind"] not in ("offered_base", "posted_base_range"):
            continue
        # Dollars only: the store keeps a posting's own currency,
        # and a filing, or a store written before that, states none.
        if (r.get("currency") or "USD").upper() != "USD":
            continue
        key_t = (r["company"], r["title"])
        if key_t not in seen:
            seen[key_t] = reader(*key_t)
        family, track, band, basis = seen[key_t]
        words = level_words(r["title"])
        key = (r["company"], family, track, band, basis, words)
        cell = cells.get(key)
        if cell is None:
            cell = cells[key] = Cell(*key)
        cell.pay[r["vintage"]].append(int(r["pay_low"]))
        cell.titles[r["title"]] += 1
    return cells


def latest(cell: Cell, min_n: int = MIN_N) -> tuple[str, int, int] | None:
    """(vintage, median, n) of the newest vintage with at least `min_n` points."""
    for vintage in sorted(cell.pay, reverse=True):
        pays = cell.pay[vintage]
        if len(pays) >= min_n:
            return vintage, round(statistics.median(pays)), len(pays)
    return None


def adjusted_median(cell: Cell, index: dict[str, dict]) -> int | None:
    """The median of every point stated in reference-year terms; None when a
    vintage present has no index (it cannot be stated in this year's terms)."""
    values: list[float] = []
    for vintage, pays in cell.pay.items():
        factor = index.get(vintage, {}).get("index")
        if factor is None:
            return None
        values.extend(p * factor for p in pays)
    return round(statistics.median(values)) if values else None


def inversions(cells: Iterable[Cell], min_n: int = MIN_N) -> list[dict]:
    """Within a company x family x track and ONE vintage: a higher band whose
    median is below a lower band's. Unstated bands (basis none) are not a rung."""
    groups: dict[tuple[str, str, str, str], list[tuple[int, Cell, int, int]]] = defaultdict(list)
    for c in cells:
        if c.basis == "none" or c.band not in BAND_ORDER:
            continue
        for vintage, pays in c.pay.items():
            if len(pays) >= min_n:
                groups[(c.company, c.family, c.track, vintage)].append(
                    (BAND_ORDER[c.band], c, round(statistics.median(pays)), len(pays)))
    out = []
    for (company, family, track, vintage), members in sorted(groups.items()):
        for rank_lo, lo, pay_lo, n_lo in members:
            for rank_hi, hi, pay_hi, n_hi in members:
                if rank_hi > rank_lo and pay_hi < pay_lo:
                    out.append({
                        "company": company, "family": family, "track": track, "vintage": vintage,
                        "higher_band": hi.band, "higher_words": hi.level_words, "higher_median": pay_hi, "higher_n": n_hi,
                        "lower_band": lo.band, "lower_words": lo.level_words, "lower_median": pay_lo, "lower_n": n_lo,
                    })
    return out


# --- manager rungs ---------------------------------------------------------------- #

#: The individual-contributor families a manager of engineers is paid alongside.
IC_FAMILIES = frozenset({"software_engineering", "ml_ai_research", "data_engineering", "infrastructure_sre",
                         "security_engineering"})
#: The families whose manager titles are aligned.
MANAGER_FAMILIES = IC_FAMILIES | {"engineering_management"}
#: Least points on each side of one vintage's comparison.
MIN_ALIGN_N = 3


def manager_alignment(cells: Iterable[Cell], reference_year: int, min_n: int = MIN_ALIGN_N) -> list[dict]:
    """Each manager title group, placed beside the engineer band it is paid like.

    The atlas rule for managers (Apple, Nvidia, Google: "managers band with the
    IC rung they are paid alongside"), measured: inside one company and one
    vintage, the IC band (stated levels only, pooled across the engineering
    families) whose median is nearest the managers' median, on a log scale. One
    row per manager group and vintage, and the group's verdict: the band with
    the most recency-weighted points of evidence (`votes`).

    A HINT for the reviewer, never a band source: against manager groups whose
    level the company states itself, the aligned band often disagrees, by up to
    three bands, and Director titles align below director. Managers are paid on
    their own curve, not the engineer band beside them. A phrase row needs
    evidence that names the rung."""
    cells = list(cells)
    ic: dict[tuple[str, str], dict[str, list[int]]] = defaultdict(lambda: defaultdict(list))
    for c in cells:
        if c.track == "technical" and c.family in IC_FAMILIES and c.basis != "none" and c.band in BAND_ORDER:
            for vintage, pays in c.pay.items():
                ic[(c.company, vintage)][c.band].extend(pays)
    out = []
    for c in cells:
        if c.track != "management" or c.family not in MANAGER_FAMILIES:
            continue
        votes: dict[str, float] = defaultdict(float)
        per_vintage = []
        for vintage, pays in sorted(c.pay.items()):
            bands = {b: p for b, p in ic.get((c.company, vintage), {}).items() if len(p) >= min_n}
            if len(pays) < min_n or len(bands) < 2:
                continue
            mgr = statistics.median(pays)
            medians = {b: statistics.median(p) for b, p in bands.items()}
            nearest = min(medians, key=lambda b: abs(math.log(mgr / medians[b])))
            votes[nearest] += len(pays) * weight(vintage, reference_year)
            per_vintage.append(f"{vintage}: ${round(mgr) // 1000}k n{len(pays)} ~ {nearest} ${round(medians[nearest]) // 1000}k")
        if not per_vintage:
            continue
        verdict = max(votes, key=lambda b: votes[b])
        out.append({
            "company": c.company, "family": c.family, "band_read": c.band, "basis_read": c.basis,
            "level_words": c.level_words, "titles": " ; ".join(t for t, _ in sorted(c.titles.items(), key=lambda kv: -kv[1])[:3]),
            "aligned_band": verdict, "agreement": round(votes[verdict] / sum(votes.values()), 2),
            "evidence": " | ".join(per_vintage),
        })
    return sorted(out, key=lambda r: (r["company"], r["family"], r["level_words"]))


# --- output --------------------------------------------------------------------- #

EVIDENCE_COLUMNS = ["company", "family", "track", "band", "basis", "level_words", "n", "n_by_vintage",
                    "latest_vintage", "latest_median", "latest_n", "adjusted_median", "weighted_n", "top_titles"]


def evidence_rows(cells: Iterable[Cell], index: dict[str, dict], reference_year: int) -> Iterator[dict]:
    order = sorted(cells, key=lambda c: (c.company, c.family, c.track, BAND_ORDER.get(c.band, 99), c.level_words))
    for c in order:
        last = latest(c, 1)
        top = sorted(c.titles.items(), key=lambda kv: -kv[1])[:3]
        yield {
            "company": c.company, "family": c.family, "track": c.track, "band": c.band, "basis": c.basis,
            "level_words": c.level_words, "n": c.n,
            "n_by_vintage": "|".join(f"{v}:{len(p)}" for v, p in sorted(c.pay.items())),
            "latest_vintage": last[0] if last else "", "latest_median": last[1] if last else "",
            "latest_n": last[2] if last else "", "adjusted_median": adjusted_median(c, index) or "",
            "weighted_n": round(sum(len(p) * weight(v, reference_year) for v, p in c.pay.items()), 1),
            "top_titles": " ; ".join(f"{t} ({k})" for t, k in top),
        }


def review_sheet(company: str, rows: list[dict], flagged: list[dict], index: dict[str, dict]) -> str:
    lines = [f"# {company}: level evidence", "",
             "Stated pay is the employer's offered or posted BASE. `latest` is the newest vintage with",
             "n >= 1; `adjusted` states every vintage in this year's terms with the measured growth index",
             f"({', '.join(f'{v}: x{d['index']}' for v, d in index.items())}). Weighted n halves per year of age.", ""]
    for (family, track), group in _group(rows):
        if sum(int(r["n"]) for r in group) < MIN_N:
            continue
        lines += [f"## {family} / {track}", "",
                  "| band | read by | level words | n by vintage | latest median (vintage, n) | adjusted | weighted n | titles |",
                  "|---|---|---|---|---|---|---|---|"]
        for r in group:
            if int(r["n"]) < 2:
                continue
            latest_text = f"${int(r['latest_median']) // 1000}k ({r['latest_vintage']}, {r['latest_n']})" if r["latest_median"] else ""
            adj = f"${int(r['adjusted_median']) // 1000}k" if r["adjusted_median"] else ""
            lines.append(f"| {r['band']} | {r['basis']} | {r['level_words'] or '(none)'} | {r['n_by_vintage']} | "
                         f"{latest_text} | {adj} | {r['weighted_n']} | {r['top_titles']} |")
        lines.append("")
    mine = [f for f in flagged if f["company"] == company]
    if mine:
        lines += ["## Pay disagrees with the band (same vintage, n >= 5 each)", ""]
        lines += [f"- {f['family']}/{f['track']} {f['vintage']}: {f['higher_band']} ({f['higher_words'] or 'no words'}) "
                  f"${f['higher_median'] // 1000}k n {f['higher_n']} < {f['lower_band']} ({f['lower_words'] or 'no words'}) "
                  f"${f['lower_median'] // 1000}k n {f['lower_n']}" for f in mine]
        lines.append("")
    return "\n".join(lines)


def _alignment_section(company: str, aligned: list[dict]) -> str:
    mine = [a for a in aligned if a["company"] == company]
    if not mine:
        return ""
    lines = ["## Managers beside the engineer band they are paid like (same vintage, n >= 3 each)", "",
             "| family | level words | read today | aligned band (agreement) | evidence | titles |", "|---|---|---|---|---|---|"]
    lines += [f"| {a['family']} | {a['level_words'] or '(none)'} | {a['band_read']} ({a['basis_read']}) | "
              f"{a['aligned_band']} ({a['agreement']}) | {a['evidence']} | {a['titles']} |" for a in mine]
    return "\n".join(lines) + "\n"


def _group(rows: list[dict]) -> Iterator[tuple[tuple[str, str], list[dict]]]:
    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for r in rows:
        groups[(r["family"], r["track"])].append(r)
    yield from sorted(groups.items(), key=lambda kv: -sum(int(r["n"]) for r in kv[1]))


def _write_csv(path: Path, columns: list[str], rows: Iterable[dict]) -> int:
    n = 0
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
            n += 1
    return n


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("companies", nargs="*", help="write review sheets for these companies")
    parser.add_argument("--dir", type=Path, default=SOURCES_DIR)
    parser.add_argument("--year", type=int, default=date.today().year, help="the reference year")
    args = parser.parse_args(argv)
    with (args.dir / "observations.csv").open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    out = args.dir / "normalized"
    out.mkdir(parents=True, exist_ok=True)
    index = growth_index(rows, args.year)
    (out / "growth_index.json").write_text(json.dumps({
        "reference_year": args.year, "half_life_years": HALF_LIFE_YEARS,
        "method": "median ratio of (employer, title, state) LCA medians in consecutive vintages, chained",
        "vintages": index}, indent=2) + "\n", encoding="utf-8")
    cells = evidence(rows)
    ev = list(evidence_rows(cells.values(), index, args.year))
    flagged = inversions(cells.values())
    n_ev = _write_csv(out / "level_evidence.csv", EVIDENCE_COLUMNS, ev)
    n_inv = _write_csv(out / "inversions.csv", list(flagged[0]) if flagged else ["company"], flagged)
    aligned = manager_alignment(cells.values(), args.year)
    n_mgr = _write_csv(out / "manager_alignment.csv", list(aligned[0]) if aligned else ["company"], aligned)
    review = out / "review"
    review.mkdir(exist_ok=True)
    for company in args.companies:
        mine = [r for r in ev if r["company"] == company]
        sheet = review_sheet(company, mine, flagged, index) + _alignment_section(company, aligned)
        (review / f"{company}.md").write_text(sheet, encoding="utf-8")
    print(json.dumps({"growth_index": index, "evidence_rows": n_ev, "inversions": n_inv, "manager_groups": n_mgr,
                      "companies": len({c.company for c in cells.values()}),
                      "review_sheets": args.companies}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())

