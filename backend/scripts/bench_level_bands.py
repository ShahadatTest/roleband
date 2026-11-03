"""Level bench: what the leveling model decides over the stored corpus.

Every rule or rung change ships its moved-postings report.
This is how it is measured, read-only:

    # on main, then on the branch:
    .venv/bin/python -m scripts.bench_level_bands snapshot /tmp/main.json
    .venv/bin/python -m scripts.bench_level_bands compare /tmp/main.json --expect google
    # what each basis decides, per company (live inventory and jobs)
    .venv/bin/python -m scripts.bench_level_bands coverage
    # re-measure the pay-grade table from stored ranges (yearly: ranges move)
    .venv/bin/python -m scripts.bench_level_bands pay-grades --company google
    # rebuild the band-level rows of every other company (yearly)
    .venv/bin/python -m scripts.bench_level_bands pay-bands --write
    # refresh the committed title snapshot the coverage gate reads
    .venv/bin/python -m scripts.bench_level_bands title-snapshot
    # the measures every change reports: Board evidence, postings dropped on level
    .venv/bin/python -m scripts.bench_level_bands baseline
    # pay-table rungs our dataset cannot place yet: what to add to the atlas next
    .venv/bin/python -m scripts.bench_level_bands rung-gaps
    # does an evidence method agree with the levels companies state? (exit 1 if not)
    .venv/bin/python -m scripts.bench_level_bands evidence-check <groups.csv> --band aligned_band
    # does the page-read rule keep read_level's order? (exit 1 if not)
    .venv/bin/python -m scripts.bench_level_bands read-agreement

`compare` exits 1 when a company outside `--expect` moves or a planted control
reads differently: a move nobody intended is a failure, not a footnote. Every
title is read with its family classified by the code under test, the way
`annotate` reads it; jobs also carry their stated range.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path

from tracker.enrich.classify import classify_family
from tracker.enrich.level_mapper import (
    _level_text,
    full_read_can_state,
    is_level_guess,
    level_date,
    read_level,
    title_states_band,
)
from tracker.levels.atlas import PRINTED, read_rows
from tracker.levels.ladder import band_for, lineage, prints_rungs_in_text
from tracker.levels.pay_grades import PAY_BANDS, PAY_GRADES
from tracker.levels.titles import PROFILES, match_title
from tracker.schema import LEVEL_BAND_ORDER, LevelBasis, RawJob, SourceDisclosedComp, parse_band
from tracker.taxonomy.stated_level import PRINTING_COMPANIES, stated_level
from tracker.taxonomy.title_parse import head_with_seniority

#: The committed title snapshot the coverage gate reads (CI has no corpus).
TITLE_SNAPSHOT = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "level_title_snapshot.json"

#: What a company's own vocabulary decided (the coverage measure).
DECIDED = frozenset({LevelBasis.STATED, LevelBasis.COMPANY, LevelBasis.PAY_GRADE})


@dataclass(frozen=True)
class Control:
    """A posting whose reading is known. Planted in every compare: if one
    moves, the change moved something nobody intended."""

    company: str
    title: str
    band: str
    basis: str
    family: str | None = None  # None = classified, as `annotate` does
    raw_level: str | None = None
    pay: tuple[int, int] | None = None


CONTROLS: tuple[Control, ...] = (
    # Early-stage words are whole words.
    Control("google", "Staff Software Engineer, Internet Egress", "staff", "company"),
    Control("amazon", "Research Intern, PhD", "intern", "generic"),
    # The first full-time rung: Junior and Associate read Entry, an
    # intern never does.
    Control("acme", "Junior Data Analyst", "entry", "generic"),
    Control("acme", "Associate Product Manager", "entry", "generic"),
    Control("acme", "New Grad Software Engineer", "entry", "generic"),
    Control("acme", "Associate Director, Strategy", "director_plus", "generic"),
    # An "Associate" before a senior office, or in a contractor tag, names no
    # first rung; one before a counsel or business-partner role does.
    Control("acme", "Associate General Counsel, Privacy", "mid", "none"),
    Control("acme", "Associate Partner", "mid", "none"),
    Control("tiktok", "Creator Project Specialist (Third-Party Associate)", "mid", "none"),
    Control("acme", "Associate Corporate Counsel, Legal", "entry", "generic"),
    Control("acme", "Associate HR Business Partner", "entry", "generic"),
    # A duration or a count is no rung numeral; a numeral after the role is.
    Control("acme", "B2B Event Marketing Manager (6-Month Contract)", "mid", "none"),
    Control("acme", "Software Engineer (7+ years of experience)", "mid", "none"),
    Control("netflix", "Software Engineer 5 - Ads Eventing", "senior", "unmapped"),
    # Rung words are whole words: a false friend names no rung.
    Control("acme", "Staffing Manager", "mid", "none"),
    Control("acme", "Directory Services Administrator", "mid", "none"),
    Control("microsoft", "Active Directory Engineer", "senior", "stated", raw_level="IC4"),
    # Company vocabulary.
    Control("amazon", "Sr. Software Development Engineer", "senior", "company"),
    Control("amazon", "Solutions Architect II", "mid", "company"),
    Control("google", "Software Engineer III, Infrastructure", "mid", "company"),
    Control("google", "Senior Software Engineering Manager, Search", "principal", "company"),
    Control("google", "Principal Engineer, Cloud", "principal", "company"),
    # A bare title states nothing; its stated range can.
    Control("acme", "Software Engineer", "mid", "none"),
    Control("google", "Product Manager, Google Analytics", "mid", "pay_grade", pay=(138_000, 197_000)),
    # A printed rung outranks the title, except a director's.
    Control("microsoft", "Product Manager II", "mid", "stated", raw_level="IC3"),
    Control("microsoft", "Director, Silicon Design", "director_plus", "generic", raw_level="M5"),
    # A rung printed in a board field reads as printed; an unsettled one does not.
    Control("waymo", "Strategic Sourcing Manager - Contract Manufacturing", "staff", "stated", raw_level="6"),
    Control("reddit", "Senior Client Account Manager", "senior", "generic", raw_level="IC5"),
    # A manager rank or role we cannot place keeps its guessed band, unmapped.
    Control("acme", "Senior Manager, Data Science", "staff", "unmapped"),
    Control("acme", "Engineering Manager, Platform", "staff", "unmapped"),
)


def _raw(company: str, title: str, *, department=None, team=None, raw_level=None,
         pay: tuple[int, int] | None = None, posted: datetime | None = None) -> RawJob:
    stated = None
    if pay is not None:
        stated = SourceDisclosedComp(base_min=pay[0], base_max=pay[1], currency="USD",
                                     pay_basis="base", pay_period="year")
    return RawJob(company=company, req_id="bench", title=title, url="", department=department,
                  team=team, raw_level=raw_level, source_disclosed_comp=stated, posted_at=posted)


def control_failures(controls: tuple[Control, ...] = CONTROLS) -> list[str]:
    """Every control whose reading is not the one it was planted with."""
    failures = []
    for c in controls:
        raw = _raw(c.company, c.title, raw_level=c.raw_level, pay=c.pay,
                   posted=datetime(2026, 6, 1, tzinfo=UTC))
        reading = read_level(raw, c.family or classify_family(raw))
        if (reading.band.value, reading.basis.value) != (c.band, c.basis):
            failures.append(f"{c.company} {c.title!r}: {reading.band.value}/{reading.basis.value}, "
                            f"planted {c.band}/{c.basis}")
    return failures


# --- the coverage gate's measure ------------------------------------------ #


def decided_share(company: str, entries: list[list]) -> float:
    """Of the titles that name a rung (basis not `none`), weighted by count,
    the share the company's own vocabulary decided. `entries` are
    [title, family, count]."""
    named = decided = 0
    for title, family, count in entries:
        basis = read_level(_raw(company, title), family).basis
        if basis is LevelBasis.NONE:
            continue
        named += count
        decided += count * (basis in DECIDED)
    return decided / named if named else 0.0


# --- the corpus ------------------------------------------------------------ #

# The description only where the pass reads it: an employer that prints a rung,
# on a row with no stored `raw_level` (`workflows.relevel`).
_JOBS = """select id, company, title, department, team, raw_level, disclosed_base_min,
 disclosed_base_max, disclosed_currency, disclosed_pay_basis, disclosed_pay_period,
 first_posted_at, posted_at, first_seen, status,
 case when raw_level is null and company = any(:printing) then description_text end as description
 from jobs"""
_INVENTORY = """select id, company, title, department, team, raw_level,
 (gone_at is null) as live from posting_inventory"""


async def _corpus() -> tuple[list, list]:
    from sqlalchemy import text

    from tracker.db.session import session_scope

    async with session_scope() as session:
        jobs = (await session.execute(text(_JOBS), {"printing": sorted(PRINTING_COMPANIES)})).all()
        inventory = (await session.execute(text(_INVENTORY))).all()
        await session.rollback()
    return jobs, inventory


def _job_raw(r) -> RawJob:
    pay = None
    if (r.disclosed_base_min and r.disclosed_base_max and r.disclosed_currency == "USD"
            and r.disclosed_pay_basis == "base" and r.disclosed_pay_period == "year"):
        pay = (r.disclosed_base_min, r.disclosed_base_max)
    raw = _raw(r.company, r.title, department=r.department, team=r.team,
               raw_level=r.raw_level or stated_level(r.company, r.description), pay=pay,
               posted=r.posted_at)
    # The stored dates, as relevel reads them: one `level_date`.
    raw.held_first_posted_at, raw.held_first_seen = r.first_posted_at, r.first_seen
    return raw


def _inventory_raw(r) -> RawJob:
    return _raw(r.company, r.title, department=r.department, team=r.team, raw_level=r.raw_level)


def readings(jobs: list, inventory: list) -> dict[str, list]:
    """key -> [company, band, confidence, basis, family, title, live]."""
    out = {}
    for table, rows, build in (("jobs", jobs, _job_raw), ("inv", inventory, _inventory_raw)):
        for r in rows:
            raw = build(r)
            family = classify_family(raw)
            reading = read_level(raw, family)
            live = r.live if table == "inv" else r.status == "open"
            out[f"{table}:{r.id}"] = [r.company, reading.band.value, reading.confidence.value,
                                      reading.basis.value, family, r.title, live]
    return out


# --- commands --------------------------------------------------------------- #


def cmd_snapshot(path: str) -> int:
    jobs, inventory = asyncio.run(_corpus())
    Path(path).write_text(json.dumps(readings(jobs, inventory)))
    print(f"wrote {len(jobs) + len(inventory)} readings to {path}")
    return 0


def cmd_compare(path: str, expect: set[str], expect_moves: frozenset[tuple[str, str]] = frozenset()) -> int:
    """`expect` names companies allowed to move; `expect_moves` names band
    moves allowed at any company (`junior:entry`), for a change to a generic
    word that moves postings at hundreds of companies. A move that
    neither allows fails the compare."""
    before = json.loads(Path(path).read_text())
    jobs, inventory = asyncio.run(_corpus())
    after = readings(jobs, inventory)
    moves: Counter = Counter()
    samples: dict[tuple, list[str]] = defaultdict(list)
    for key, old in before.items():
        new = after.get(key)
        if new is None or new[1] == old[1]:
            continue
        move = (key.split(":")[0], new[0], old[1], new[1], new[3])
        moves[move] += 1
        if len(samples[move]) < 3:
            samples[move].append(new[5][:60])
    by_company: Counter = Counter()
    by_pair: Counter = Counter()
    outside: set[str] = set()
    for move, count in moves.items():
        by_company[move[1]] += count
        by_pair[(move[2], move[3])] += count
        if (move[2], move[3]) not in expect_moves:
            outside.add(move[1])
    print(f"band moves: {sum(moves.values())} of {len(before)} readings; by company {dict(by_company)}")
    print("by band move: " + ", ".join(f"{a} -> {b}: {n}" for (a, b), n in by_pair.most_common()))
    for move, count in moves.most_common():
        print(f"  {count:5d} {move[0]:4s} {move[1]}: {move[2]} -> {move[3]} ({move[4]})  {samples[move]}")
    unexpected = sorted(outside - expect)
    failures = control_failures()
    for failure in failures:
        print(f"CONTROL MOVED: {failure}")
    if unexpected:
        print(f"UNEXPECTED: companies outside --expect moved, by a move outside --expect-moves: {unexpected}")
    return 1 if unexpected or failures else 0


def cmd_coverage(companies: list[str] | None) -> int:
    jobs, inventory = asyncio.run(_corpus())
    out = readings(jobs, inventory)
    table: dict[tuple[str, str], Counter] = defaultdict(Counter)
    for key, (company, _band, _conf, basis, _family, _title, live) in out.items():
        kind = key.split(":")[0]
        if kind == "inv" and not live:
            continue
        table[(company, kind)][basis] += 1
    wanted = set(companies) if companies else {slug for slug, p in PROFILES.items() if p.calibrated}
    for (company, kind), counts in sorted(table.items()):
        if company not in wanted:
            continue
        named = sum(n for b, n in counts.items() if b != "none")
        decided = sum(counts[b.value] for b in DECIDED)
        share = decided / named if named else 0.0
        print(f"{company:18s} {kind:4s} {sum(counts.values()):6d}  decided/named {share:6.1%}  {dict(counts)}")
    return 0


_RUNG_ROWS = """select r.company_slug, r.family, r.level_label, r.band, r.tc_median,
 (select count(*) from jobs j where j.company = r.company_slug and j.status = 'open') as open_roles
 from company_comp_level r where r.provider <> 'manual' and r.retired_at is null"""


async def _rung_rows() -> list:
    from sqlalchemy import text

    from tracker.db.session import session_scope

    async with session_scope() as session:
        return list((await session.execute(text(_RUNG_ROWS))).all())


def cmd_rung_gaps(companies: list[str] | None) -> int:
    """Pay-table rungs our dataset cannot place: each rests on its
    source's reading, and is what to add to the atlas next. Companies with
    the most open roles first; read-only."""
    from tracker.levels.words import atlas_band

    gaps: dict[str, list] = defaultdict(list)
    placed = total = 0
    open_roles: dict[str, int] = {}
    for company, family, label, band, tc, roles in asyncio.run(_rung_rows()):
        if companies and company not in companies:
            continue
        total += 1
        open_roles[company] = roles
        if atlas_band(company, label) is not None:
            placed += 1
        else:
            gaps[company].append((family, label, band, tc))
    print(f"{placed} of {total} pay-table rungs placed by our dataset; {total - placed} rest on their source")
    for company in sorted(gaps, key=lambda c: (-open_roles.get(c, 0), c)):
        rows = sorted(gaps[company], key=lambda r: (r[0], r[3] or 0))
        print(f"\n{company}: {len(rows)} rungs, {open_roles.get(company, 0)} open roles")
        for family, label, band, tc in rows:
            print(f"  {family:28s} {label:40s} {band or '-':14s} {tc or ''}")
    return 0


def cmd_pay_grades(company: str, year: int) -> int:
    """Candidate rows: per (family, range), anchors are postings whose
    title-only reading is basis company by a family-ladder rule; a row needs
    2+ anchors with 80%+ on one rung. Prints rows, dissent,
    unmapped ranges and the difference from `PAY_GRADES`."""
    jobs, _ = asyncio.run(_corpus())
    groups: dict[tuple, dict] = defaultdict(lambda: {"anchors": Counter(), "rows": []})
    for r in jobs:
        # A child company (google-deepmind) posts its parent's ranges.
        if company not in lineage(r.company):
            continue
        raw = _job_raw(r)
        if level_date(raw).year != year:
            continue
        if raw.source_disclosed_comp is None:
            continue
        pay = (raw.source_disclosed_comp.base_min, raw.source_disclosed_comp.base_max)
        raw.source_disclosed_comp = None  # anchors are read from the title alone
        family = classify_family(raw)
        reading = read_level(raw, family)
        head = _level_text(head_with_seniority(r.title), r.company)
        match = match_title(r.company, head, family)
        anchored = (reading.basis is LevelBasis.COMPANY and match is not None and match.ladder is not None
                    and band_for(r.company, match.rule.rung, match.ladder) is reading.band)
        group = groups[(family, *pay)]
        group["rows"].append((r.id, r.title, match.rule.rung if anchored else None))
        if anchored:
            group["anchors"][(match.rule.rung, head.strip())] += 1
    measured = {}
    for key, group in sorted(groups.items(), key=lambda kv: (str(kv[0][0]), kv[0][1], kv[0][2])):
        rungs: Counter = Counter()
        for (rung, _), n in group["anchors"].items():
            rungs[rung] += n
        total = sum(rungs.values())
        if total < 2:
            continue
        top, n = rungs.most_common(1)[0]
        if n * 5 < total * 4:
            print(f"UNMAPPED {key}: anchors disagree {dict(rungs)}")
            continue
        anchor = max(((h, c) for (rung, h), c in group["anchors"].items() if rung == top), key=lambda x: x[1])[0]
        measured[key] = top
        print(f"ROW {key[0]} {key[1]}-{key[2]} -> {top}  anchor {anchor!r} x{n} of {len(group['rows'])}")
        for rid, title, rung in group["rows"]:
            if rung is not None and rung != top:
                print(f"    dissent job {rid}: {title[:60]!r} reads {rung}")
    committed = {(g.family, g.base_min, g.base_max): g.rung for g in PAY_GRADES
                 if g.company == company and g.year == year}
    for key in sorted(set(measured) | set(committed), key=str):
        if measured.get(key) != committed.get(key):
            print(f"DIFF {key}: measured {measured.get(key)}, committed {committed.get(key)}")
    return 0


def band_rows(jobs: list, year: int) -> tuple[list[dict], list[str]]:
    """Band-level pay rows for every company outside a rung table.

    Per (company, family, exact range, year), the anchors are postings whose
    title alone, read without the range, states a band confirmed (a printed
    rung, the company's words or a generic rung word). A row needs 2+ anchors
    with four of every five on one band. Returns (rows, report lines).
    """
    ruled = {g.company for g in PAY_GRADES}
    groups: dict[tuple, Counter] = defaultdict(Counter)
    titles: dict[tuple, Counter] = defaultdict(Counter)
    for r in jobs:
        if ruled & set(lineage(r.company)):
            continue
        raw = _job_raw(r)
        if level_date(raw).year != year:
            continue
        if raw.source_disclosed_comp is None:
            continue
        pay = (raw.source_disclosed_comp.base_min, raw.source_disclosed_comp.base_max)
        raw.source_disclosed_comp = None
        family = classify_family(raw)
        if family is None:
            continue
        reading = read_level(raw, family)
        if title_states_band(r.title, reading, raw.raw_level, r.company):
            key = (r.company, family, *pay)
            groups[key][reading.band.value] += 1
            # The anchor as the test re-reads it: the title, and the printed rung
            # in brackets when that is what stated the band.
            printed = f" [{raw.raw_level}]" if reading.basis is LevelBasis.STATED else ""
            titles[key][(reading.band.value, f"{r.title.strip()}{printed}")] += 1
    rows, report = [], []
    for key, bands in sorted(groups.items()):
        total = sum(bands.values())
        band, n = bands.most_common(1)[0]
        if total < 2:
            continue
        if n * 5 < total * 4:
            report.append(f"UNMAPPED {key}: anchors disagree {dict(bands)}")
            continue
        company, family, low, high = key
        anchor = max(((t, c) for (b, t), c in titles[key].items() if b == band), key=lambda tc: tc[1])[0]
        rows.append({"company": company, "family": family, "base_min": low, "base_max": high,
                     "year": year, "band": band, "anchor": anchor, "anchors": n})
    return rows, report


def cmd_pay_bands(year: int, write: bool, out: Path | None = None) -> int:
    from scripts.data import build_target
    from tracker.levels.atlas import PAY_BANDS, pay_bands_text

    target = build_target("atlas", PAY_BANDS.file, out) if write else None
    jobs, _ = asyncio.run(_corpus())
    rows, report = band_rows(jobs, year)
    for line in report:
        print(line)
    print(f"{len(rows)} band rows; by company {dict(Counter(row['company'] for row in rows).most_common())}")
    if target is not None:
        # The atlas's canonical form, so a rebuild diffs as data.
        target.write_text(pay_bands_text(rows), encoding="utf-8")
        print(f"wrote {target}")
    return 0


async def _baseline_rows() -> tuple[list, list]:
    """(Board rows by level basis, live inventory rows the saved scope drops
    only on level). Read-only."""
    from sqlalchemy import exists, select, text

    from tracker.db.inventory_store import at_followed_company
    from tracker.db.models import Job, PostingInventory
    from tracker.db.queries.scope import job_scope_expr, load_scope_exclusions
    from tracker.db.session import session_scope
    from tracker.levels import all_band_slugs
    from tracker.scope.projection import saved_scope

    async with session_scope() as session:
        board = (await session.execute(text(
            "select company, title, level_band, level_confidence, coalesce(level_basis, 'generic') as level_basis"
            " from jobs where status = 'open' and in_scope"
        ))).all()
        axes, keywords = await saved_scope(session)
        exclusions = await load_scope_exclusions(session)
        saved = job_scope_expr(*axes, exclusions, **keywords, model=PostingInventory)
        roles, _bands, tracks, places, domains = axes
        level_free = job_scope_expr(
            roles, all_band_slugs(), tracks, places, domains, exclusions,
            **{**keywords, "include_unstated_level": True}, model=PostingInventory,
        )
        read = exists().where(Job.dedupe_key == PostingInventory.dedupe_key, Job.description_text.is_not(None))
        drops = (await session.execute(
            select(
                PostingInventory.company, PostingInventory.title, PostingInventory.raw_level,
                PostingInventory.family, PostingInventory.posted_at, PostingInventory.level_band,
                PostingInventory.level_confidence, PostingInventory.level_basis, read.label("read"),
            ).where(PostingInventory.gone_at.is_(None), at_followed_company(), level_free, ~saved)
        )).all()
        await session.rollback()
    return board, drops


def cmd_baseline() -> int:
    """The level measures every change reports: Board rows by
    whether the posting states its level (a printed rung, the company's words,
    a stated range, or a rung word naming the band), we guessed it from a
    role word, or nothing states it; and live postings the saved scope drops ONLY on
    level, split by whether we read them, whether the level is our guess, and
    whether a full read could state it (`level_awaits_read`'s rule)."""
    from tracker.enrich.level_mapper import LevelReading
    from tracker.schema import LevelConfidence

    def reading_of(r) -> LevelReading:
        return LevelReading(parse_band(r.level_band), LevelConfidence(r.level_confidence), LevelBasis(r.level_basis))

    board, drops = asyncio.run(_baseline_rows())
    kinds: Counter = Counter()
    for r in board:
        reading = reading_of(r)
        if reading.basis is LevelBasis.NONE:
            kinds["not stated"] += 1
        elif is_level_guess(r.title, reading, r.company):
            kinds["level not mapped (a role word or manager rank)"] += 1
        else:
            kinds["stated by the posting"] += 1
    total = len(board)
    shares = ", ".join(f"{k} {n} ({n / max(total, 1):.1%})" for k, n in kinds.most_common())
    print(f"Board (open, in scope): {total}; {shares}; "
          f"by basis {dict(Counter(r.level_basis for r in board).most_common())}")
    split: Counter = Counter()
    awaiting: Counter = Counter()
    for r in drops:
        if r.read:
            split["read"] += 1
            continue
        if not is_level_guess(r.title, reading_of(r), r.company):
            split["unread, level stated"] += 1
            continue
        raw = RawJob(company=r.company, req_id="b", title=r.title, url="", raw_level=r.raw_level, posted_at=r.posted_at)
        if full_read_can_state(raw, r.family):
            split["unread, level not placed, a read can place it"] += 1
            awaiting[r.company] += 1
        else:
            split["unread, level not placed, a read cannot place it"] += 1
    print(f"Dropped only on level (live, followed): {len(drops)}; {dict(split)}")
    print(f"  a read can state it, by company: {dict(awaiting.most_common(15))}")
    return 0


# --- evidence check: does a method agree with what companies state? -------- #

#: The bar an evidence source must pass to place postings (the bar exact
#: ranges clear leave-one-out), and the least anchored groups that may
#: claim it.
EVIDENCE_BAR = 0.94
EVIDENCE_MIN_ANCHORED = 10


@dataclass
class EvidenceReport:
    """How a method's proposed bands agree with the bands companies state."""

    anchored: int = 0  # groups whose titles state their own band
    agree: int = 0
    unanchored: int = 0  # groups no title of which states a band: proposals, not evidence
    off_by: Counter = None  # band distance of each disagreement
    directors_lowered: int = 0  # stated director+, proposed below it
    by_company: dict = None  # company -> [anchored, agree]
    misses: list = None  # (company, family, title, stated, proposed)

    def __post_init__(self) -> None:
        self.off_by = self.off_by if self.off_by is not None else Counter()
        self.by_company = self.by_company if self.by_company is not None else {}
        self.misses = self.misses if self.misses is not None else []

    @property
    def share(self) -> float:
        return self.agree / self.anchored if self.anchored else 0.0

    @property
    def passes(self) -> bool:
        return (self.anchored >= EVIDENCE_MIN_ANCHORED and self.share >= EVIDENCE_BAR
                and self.directors_lowered == 0)


def evidence_agreement(rows: list[dict], band_column: str) -> EvidenceReport:
    """Each row is a title group a method proposes a band for (company,
    family, `titles` `;`-separated or `title`, and `band_column`). Every title
    is read by the code under test; a group whose titles state their own band
    (`title_states_band`: a printed rung, the company's words, a generic rung word)
    is a validation case, scored against the band they state. A group whose
    titles state none is counted apart: there the method is the only claim,
    which is exactly what it has to earn here first."""
    report = EvidenceReport()
    for row in rows:
        company, family = row["company"], row.get("family") or None
        proposed = row[band_column]
        titles = [t.strip() for t in (row.get("titles") or row.get("title") or "").split(";") if t.strip()]
        stated: Counter = Counter()
        for title in titles:
            reading = read_level(_raw(company, title), family)
            if title_states_band(title, reading, None, company):
                stated[reading.band.value] += 1
        if not stated:
            report.unanchored += 1
            continue
        truth = stated.most_common(1)[0][0]
        report.anchored += 1
        counts = report.by_company.setdefault(company, [0, 0])
        counts[0] += 1
        if proposed == truth:
            report.agree += 1
            counts[1] += 1
            continue
        report.off_by[abs(LEVEL_BAND_ORDER[proposed] - LEVEL_BAND_ORDER[truth])] += 1
        if truth == "director_plus":
            report.directors_lowered += 1
        report.misses.append((company, family, titles[0], truth, proposed))
    return report


def cmd_evidence_check(path: str, band_column: str) -> int:
    """Score an evidence file against the levels companies state.
    Exit 1 unless it passes: 94%+ of at least 10 anchored groups, no director
    pulled down. A method that fails may inform a reviewer, never place."""
    import csv

    with open(path, newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    report = evidence_agreement(rows, band_column)
    print(f"{path}: {len(rows)} groups; anchored by their own titles {report.anchored}, "
          f"agree {report.agree} ({report.share:.0%}); unanchored {report.unanchored}")
    print(f"  off by: {dict(sorted(report.off_by.items()))}; director titles lowered: {report.directors_lowered}")
    for company, (n, ok) in sorted(report.by_company.items(), key=lambda kv: -kv[1][0]):
        print(f"  {company:20s} {ok}/{n}")
    for company, _family, title, truth, proposed in report.misses[:15]:
        print(f"  miss {company}: {title[:50]!r} states {truth}, proposed {proposed}")
    verdict = "PASS" if report.passes else "FAIL"
    print(f"{verdict}: bar {EVIDENCE_BAR:.0%} over at least {EVIDENCE_MIN_ANCHORED} anchored groups, no director lowered")
    return 0 if report.passes else 1


# --- read agreement: does the page-read rule keep read_level's order? ------ #

# `full_read_can_state` restates `read_level`'s precedence by hand, to say
# whether reading a posting in full could state its level; collection holds a
# guessed posting for that read (`level_awaits_read`). The two copies are kept
# rather than rewriting `read_level` as one ordered list of rules, so this is
# what holds them together: it asks `read_level` itself what a read could
# change.

#: The date planted postings are read for: a year whose ranges are measured.
_READ_DATE = datetime(2026, 6, 1, tzinfo=UTC)


def read_inputs(job: RawJob, family: str | None) -> Iterator[RawJob]:
    """The posting as a full read could leave it, one input at a time: each
    rung code its company prints in the text (only where none is held; a held
    one is already read), and a stated base range at each of the company's
    measured grades for the posting's family and year."""
    slugs = set(lineage(job.company))
    if job.raw_level is None and prints_rungs_in_text(job.company):
        for row in read_rows(PRINTED):
            if row["company"] in slugs:
                yield replace(job, raw_level=row["code"])
    if family is None:
        return
    year = level_date(job).year
    for grade in (*PAY_GRADES, *PAY_BANDS):
        if grade.company in slugs and grade.family == family and grade.year == year:
            pay = SourceDisclosedComp(base_min=grade.base_min, base_max=grade.base_max,
                                      currency="USD", pay_basis="base", pay_period="year")
            yield replace(job, source_disclosed_comp=pay)


def read_could_move(job: RawJob, family: str | None) -> bool:
    """Whether anything a full read can add changes the band or basis
    `read_level` gives the posting."""
    base = read_level(job, family)
    for alternative in read_inputs(job, family):
        moved = read_level(alternative, family)
        if moved.band is not base.band or moved.basis is not base.basis:
            return True
    return False


@dataclass
class ReadAgreement:
    """Where the page-read rule and `read_level` part, over guessed postings."""

    considered: int = 0  # postings whose level is our guess: where the rule decides
    #: company -> postings the rule never reads though a read would place them.
    skipped: Counter = field(default_factory=Counter)
    #: company -> postings the rule reads (and holds) though no read can place them.
    wasted: Counter = field(default_factory=Counter)
    samples: list = field(default_factory=list)  # (kind, company, title)

    @property
    def agrees(self) -> bool:
        return not self.skipped and not self.wasted


def read_agreement(
    postings: Iterable[tuple[RawJob, str | None]],
    can_state: Callable[[RawJob, str | None], bool] = full_read_can_state,
) -> ReadAgreement:
    """Each (posting, family) whose level is a guess, judged two ways: the rule
    (`can_state`) and what `read_level` does with what a read adds."""
    report = ReadAgreement()
    for job, family in postings:
        if not is_level_guess(job.title, read_level(job, family), job.company):
            continue
        report.considered += 1
        moves = read_could_move(job, family)
        if moves is can_state(job, family):
            continue
        kind = "skipped" if moves else "wasted"
        getattr(report, kind)[job.company] += 1
        if len(report.samples) < 20:
            report.samples.append((kind, job.company, job.title))
    return report


@dataclass(frozen=True)
class ReadControl:
    """A guessed posting whose answer is known: can a full read state its level?"""

    company: str
    title: str
    can_state: bool


READ_CONTROLS: tuple[ReadControl, ...] = (
    # Microsoft prints its rung in the posting text. Its design
    # family has no measured range, so only the printed rung can place this one:
    # a rule that lost its printed-rung step reads it as unplaceable.
    ReadControl("microsoft", "Product Designer", True),
    # The same company where a measured range could place it too.
    ReadControl("microsoft", "Product Manager", True),
    # Google's measured ranges decide a title naming no rung.
    ReadControl("google", "Product Manager, Google Analytics", True),
    # No printed rung and no measured range: nothing a read adds places it.
    ReadControl("acme", "Engineering Manager, Platform", False),
    ReadControl("acme", "Software Engineer", False),
)


def read_control_failures(controls: tuple[ReadControl, ...] = READ_CONTROLS) -> list[str]:
    """Every planted posting the check misjudges, and the check's own negative
    control: a rule answering the opposite must disagree on every planted
    posting, or the check could not fail."""
    failures = []
    postings = []
    for c in controls:
        raw = _raw(c.company, c.title, posted=_READ_DATE)
        family = classify_family(raw)
        postings.append((raw, family))
        if not is_level_guess(c.title, read_level(raw, family), c.company):
            failures.append(f"{c.company} {c.title!r}: not a guess, so never judged")
        elif read_could_move(raw, family) is not c.can_state:
            failures.append(f"{c.company} {c.title!r}: a read could place it is "
                            f"{not c.can_state}, planted {c.can_state}")
        elif full_read_can_state(raw, family) is not c.can_state:
            failures.append(f"{c.company} {c.title!r}: the rule says {not c.can_state}, planted {c.can_state}")
    inverted = read_agreement(postings, lambda job, family: not full_read_can_state(job, family))
    caught = sum(inverted.skipped.values()) + sum(inverted.wasted.values())
    if caught != len(controls):
        failures.append(f"an inverted rule disagrees on {caught} of {len(controls)} controls: "
                        f"the check cannot fail")
    return failures


def snapshot_postings(snapshot: dict) -> list[tuple[RawJob, str | None]]:
    """The committed title snapshot as postings, each at its family and dated
    the day the snapshot was taken (so its year's ranges are the ones read)."""
    taken = datetime.fromisoformat(snapshot["taken"]).replace(tzinfo=UTC)
    return [
        (_raw(company, title, posted=taken), family)
        for company, entries in snapshot["titles"].items()
        for title, family, _count in entries
    ]


def cmd_read_agreement() -> int:
    """Over the open stored postings whose level is a guess: does
    `full_read_can_state` say a read could state the level exactly where
    something a read adds moves `read_level`? Exit 1 on any disagreement, or
    a planted control misjudged."""
    jobs, _ = asyncio.run(_corpus())
    postings = []
    for r in jobs:
        if r.status != "open":
            continue
        raw = _job_raw(r)
        postings.append((raw, classify_family(raw)))
    report = read_agreement(postings)
    skipped, wasted = sum(report.skipped.values()), sum(report.wasted.values())
    print(f"open postings: {len(postings)}; level a guess: {report.considered}")
    print(f"  never read though a read would place it: {skipped} {dict(report.skipped.most_common(8))}")
    print(f"  read though nothing a read adds places it: {wasted} {dict(report.wasted.most_common(8))}")
    for kind, company, title in report.samples:
        print(f"  {kind} {company}: {title[:70]!r}")
    failures = read_control_failures()
    for failure in failures:
        print(f"CONTROL: {failure}")
    verdict = "PASS" if report.agrees and not failures else "FAIL"
    print(f"{verdict}: the page-read rule and read_level agree on every guessed posting; "
          f"{len(READ_CONTROLS)} controls")
    return 0 if verdict == "PASS" else 1


def cmd_title_snapshot() -> int:
    """Rewrite the coverage gate's fixture: every live inventory title that
    names a rung at a calibrated company, [title, family, count]. Floors are
    kept; the gate tells you to raise one."""
    _, inventory = asyncio.run(_corpus())
    calibrated = sorted(slug for slug, p in PROFILES.items() if p.calibrated)
    counts: dict[str, Counter] = {slug: Counter() for slug in calibrated}
    for r in inventory:
        if not r.live or r.company not in counts:
            continue
        raw = _inventory_raw(r)
        family = classify_family(raw)
        if read_level(raw, family).basis is LevelBasis.NONE:
            continue
        counts[r.company][(r.title, family)] += 1
    old = json.loads(TITLE_SNAPSHOT.read_text()) if TITLE_SNAPSHOT.exists() else {}
    snapshot = {
        "_doc": old.get("_doc", ""),
        "taken": datetime.now(UTC).date().isoformat(),
        "floors": old.get("floors", {}),
        "titles": {slug: sorted([t, f, n] for (t, f), n in c.items()) for slug, c in counts.items()},
    }
    lines = ["{"]
    lines.append(f'  "_doc": {json.dumps(snapshot["_doc"])},')
    lines.append(f'  "taken": {json.dumps(snapshot["taken"])},')
    lines.append(f'  "floors": {json.dumps(snapshot["floors"], sort_keys=True)},')
    lines.append('  "titles": {')
    slugs = list(snapshot["titles"])
    for i, slug in enumerate(slugs):
        entries = snapshot["titles"][slug]
        lines.append(f'    {json.dumps(slug)}: [')
        lines.extend(f"      {json.dumps(e)}{',' if j < len(entries) - 1 else ''}" for j, e in enumerate(entries))
        lines.append(f"    ]{',' if i < len(slugs) - 1 else ''}")
    lines.append("  }")
    lines.append("}")
    TITLE_SNAPSHOT.write_text("\n".join(lines) + "\n")
    for slug, entries in snapshot["titles"].items():
        print(f"{slug}: {len(entries)} titles, decided/named {decided_share(slug, entries):.1%}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("snapshot")
    p.add_argument("path")
    p = sub.add_parser("compare")
    p.add_argument("path")
    p.add_argument("--expect", default="", help="comma-separated companies allowed to move")
    p.add_argument("--expect-moves", default="", help="comma-separated old:new band moves allowed at any company")
    p = sub.add_parser("coverage")
    p.add_argument("--company", action="append")
    p = sub.add_parser("pay-grades")
    p.add_argument("--company", default="google")
    p.add_argument("--year", type=int, default=datetime.now(UTC).year)
    p = sub.add_parser("pay-bands")
    p.add_argument("--year", type=int, default=datetime.now(UTC).year)
    p.add_argument("--write", action="store_true", help="rewrite the atlas's pay_bands.csv")
    p.add_argument("--out", type=Path, help="a roleband-data checkout to write into; needed once the app's copy is pinned")
    sub.add_parser("title-snapshot")
    sub.add_parser("baseline")
    p = sub.add_parser("evidence-check")
    p.add_argument("path", help="CSV of title groups: company, family, titles (;-separated), a band column")
    p.add_argument("--band", default="aligned_band", help="the column holding the proposed band")
    sub.add_parser("controls")
    p = sub.add_parser("rung-gaps")
    p.add_argument("--company", action="append")
    sub.add_parser("read-agreement")
    args = parser.parse_args()
    if args.cmd == "snapshot":
        return cmd_snapshot(args.path)
    if args.cmd == "compare":
        pairs = (m.partition(":") for m in args.expect_moves.split(","))
        moves = frozenset((old, new) for old, _, new in pairs if old and new)
        return cmd_compare(args.path, {c for c in args.expect.split(",") if c}, moves)
    if args.cmd == "coverage":
        return cmd_coverage(args.company)
    if args.cmd == "pay-grades":
        return cmd_pay_grades(args.company, args.year)
    if args.cmd == "pay-bands":
        return cmd_pay_bands(args.year, args.write, args.out)
    if args.cmd == "title-snapshot":
        return cmd_title_snapshot()
    if args.cmd == "baseline":
        return cmd_baseline()
    if args.cmd == "evidence-check":
        return cmd_evidence_check(args.path, args.band)
    if args.cmd == "rung-gaps":
        return cmd_rung_gaps(args.company)
    if args.cmd == "read-agreement":
        return cmd_read_agreement()
    failures = control_failures()
    print("\n".join(failures) or f"{len(CONTROLS)} controls read as planted")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
