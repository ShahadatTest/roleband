"""Our per-level base pay against the stored per-level baseline.

Read-only. What `tracker.enrich.level_pay` computes, how it agrees with the
per-level baseline the registry admits now (a plugin's rows, or the ones it
adopts), and what it cannot answer yet:

    # agreement with the base the job page reads (select_baselines)
    .venv/bin/python -m scripts.bench_level_pay compare
    # the levels each named company posts at (live inventory, a placed level)
    # and whether our dataset has a figure there: the switch waits on this
    .venv/bin/python -m scripts.bench_level_pay coverage
    # one company's table, beside the stored baseline
    .venv/bin/python -m scripts.bench_level_pay show google

With no pay plugin on there is no stored baseline, and `compare` says so.
A ratio is ours / the stored base. The filed figure is the offered base FROM
(at or below a posted range's middle), so agreement sits a little under 1.0.
`inversions` counts a higher band whose figure
is below a lower band's in the same company and family: a misread title, a
thin cell, or a family whose senior titles file at another rate.
"""

from __future__ import annotations

import argparse
import asyncio
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from statistics import median, quantiles

from tracker.company_discovery import named_companies
from tracker.enrich.level_pay import Key, LevelBase, level_bases
from tracker.schema import LEVEL_BAND_ORDER, LevelBand

#: (company, taxonomy family, band) -> the baseline row the job page reads.
Baselines = Mapping[tuple[str, str | None, str], Mapping[str, int | None]]


@dataclass(frozen=True)
class Agreement:
    key: Key
    ours: int
    theirs: int
    evidence: int  # filings, or anchoring postings where no filing answers

    @property
    def ratio(self) -> float:
        return self.ours / self.theirs


def figure(base: LevelBase) -> tuple[int, int] | None:
    """(base, evidence count): the filed figure, else the posted range's middle."""
    if base.filed is not None:
        return base.filed.base, base.filed.filings
    if base.posted is not None:
        return base.posted.mid, base.posted.postings or base.posted.ranges
    if base.estimated is not None:
        return base.estimated.base, 0  # The collector has no submission count; never invent one.
    return None


def agreements(shadow: Mapping[Key, LevelBase], baselines: Baselines, named: Iterable[str]) -> list[Agreement]:
    """Every named key with both our figure and a stored base."""
    companies = set(named)
    found = []
    for key, base in shadow.items():
        company, family, band = key
        ours = figure(base)
        row = baselines.get((company, family, band.value))
        theirs = row.get("base_amount") if row else None
        # A copied aggregate agreeing with its origin is not independent validation.
        independent = base.filed is not None or base.posted is not None
        if company in companies and independent and ours is not None and theirs:
            found.append(Agreement(key, ours[0], int(theirs), ours[1]))
    return found


def inversions(shadow: Mapping[Key, LevelBase]) -> list[tuple[Key, Key]]:
    """(lower key, higher key) pairs, adjacent among the bands a company x
    family has, where the higher band's figure is below the lower one's."""
    by_family: dict[tuple[str, str], list[tuple[LevelBand, int]]] = defaultdict(list)
    for (company, family, band), base in shadow.items():
        value = figure(base)
        if value is not None:
            by_family[(company, family)].append((band, value[0]))
    found = []
    for (company, family), points in by_family.items():
        points.sort(key=lambda p: LEVEL_BAND_ORDER[p[0].value])
        for (low, low_pay), (high, high_pay) in zip(points, points[1:], strict=False):
            if high_pay < low_pay:
                found.append(((company, family, low), (company, family, high)))
    return found


def coverage(shadow: Mapping[Key, LevelBase], live: Iterable[tuple[str, str, str, int]], named: Iterable[str]):
    """company -> (keys posted, keys answered, postings, postings answered,
    the unanswered keys by postings). `live` is (company, family, band, postings)."""
    companies = set(named)
    table: dict[str, list] = defaultdict(lambda: [0, 0, 0, 0, Counter()])
    for company, family, band, postings in live:
        if company not in companies:
            continue
        row = table[company]
        row[0] += 1
        row[2] += postings
        if (company, family, LevelBand(band)) in shadow:
            row[1] += 1
            row[3] += postings
        else:
            row[4][f"{family}/{band}"] += postings
    return table


async def _baselines() -> Baselines:
    from sqlalchemy import select

    from tracker.db.models import CompanyCompLevel
    from tracker.db.queries.reference_pay import admit_levels, level_scope
    from tracker.db.session import session_scope
    from tracker.plugins.registry import reader_providers

    async with session_scope() as session:
        providers = await reader_providers(session)
        rows = (await session.execute(select(
            CompanyCompLevel.company_slug, CompanyCompLevel.family, CompanyCompLevel.band,
            CompanyCompLevel.level_label, CompanyCompLevel.base_amount, CompanyCompLevel.stock_amount,
            CompanyCompLevel.bonus_amount, CompanyCompLevel.provider,
        ).where(CompanyCompLevel.band.isnot(None), CompanyCompLevel.base_amount.isnot(None),
                *level_scope(providers)))).all()
        rows = admit_levels(providers, rows)
    return job_baselines(rows)


def job_baselines(rows) -> Baselines:
    """The same US-row screen and rung selection as the job API."""
    from tracker.analytics.comp_market import us_rows
    from tracker.analytics.comp_package import select_baselines

    return select_baselines(us_rows(rows))


async def _live() -> list[tuple[str, str, str, int]]:
    """Live postings at a placed level, per company x family x band; interns
    are left out (no pay reference prices them)."""
    from sqlalchemy import func, select

    from tracker.db.models import PostingInventory
    from tracker.db.session import session_scope
    from tracker.schema import UNPLACED_BASIS_VALUES

    inv = PostingInventory
    async with session_scope() as session:
        rows = (await session.execute(
            select(inv.company, inv.family, inv.level_band, func.count())
            .where(
                inv.gone_at.is_(None), inv.family.isnot(None),
                inv.level_basis.notin_(UNPLACED_BASIS_VALUES), inv.level_band != LevelBand.INTERN.value,
            )
            .group_by(inv.company, inv.family, inv.level_band)
        )).all()
    return [(c, f, b, int(n)) for c, f, b, n in rows]


def _cmd_compare(_: argparse.Namespace) -> int:
    shadow = level_bases()
    found = agreements(shadow, asyncio.run(_baselines()), named_companies())
    if not found:
        print("no key has both figures")
        return 1
    ratios = [a.ratio for a in found]
    print(f"keys ours {len(shadow):,}  compared {len(found)}  companies {len({a.key[0] for a in found})}")
    print(f"median ratio {median(ratios):.3f}  deciles " + " ".join(f"{q:.2f}" for q in quantiles(ratios, n=10)))
    for label, test in (("evidence 1", lambda n: n == 1), ("evidence 2-4", lambda n: 2 <= n < 5),
                        ("evidence 5+", lambda n: n >= 5)):
        part = [a.ratio for a in found if test(a.evidence)]
        if part:
            print(f"  {label:13} {len(part):4}  median {median(part):.3f}")
    by_family: dict[str, list[float]] = defaultdict(list)
    for a in found:
        by_family[a.key[1]].append(a.ratio)
    print("by family (5+ keys):")
    for family, part in sorted(by_family.items(), key=lambda kv: -len(kv[1])):
        if len(part) >= 5:
            print(f"  {family:30} {len(part):4}  median {median(part):.3f}")
    print("furthest apart, evidence 5+ (ours / stored):")
    strong = sorted((a for a in found if a.evidence >= 5), key=lambda a: abs(a.ratio - 1), reverse=True)
    for a in strong[:15]:
        company, family, band = a.key
        print(f"  {company:22} {family:28} {band.value:13} {a.ours:>9,} / {a.theirs:>9,} = {a.ratio:.2f}  n={a.evidence}")
    flips = inversions(shadow)
    print(f"inversions {len(flips)} of {len({(k[0], k[1]) for k in shadow})} company x family ladders")
    return 0


def _cmd_coverage(args: argparse.Namespace) -> int:
    shadow = level_bases()
    table = coverage(shadow, asyncio.run(_live()), named_companies())
    keys = sum(r[0] for r in table.values())
    answered = sum(r[1] for r in table.values())
    postings = sum(r[2] for r in table.values())
    priced = sum(r[3] for r in table.values())
    print(f"named companies posting at a placed level: {len(table)}")
    print(f"company x family x band posted {keys:,}, answered {answered:,} ({answered / max(keys, 1):.0%})")
    print(f"postings {postings:,}, at an answered key {priced:,} ({priced / max(postings, 1):.0%})")
    print("most postings at an unanswered level:")
    rows = sorted(table.items(), key=lambda kv: -(kv[1][2] - kv[1][3]))
    for company, (k, a, p, pa, missing) in rows[: args.top]:
        if p == pa:
            break
        gaps = ", ".join(f"{key} {n}" for key, n in missing.most_common(4))
        print(f"  {company:22} keys {a:3}/{k:<3} postings {pa:5}/{p:<5}  {gaps}")
    return 0


def _cmd_show(args: argparse.Namespace) -> int:
    baselines = asyncio.run(_baselines())
    rows = [b for (c, _, _), b in level_bases().items() if c == args.company]
    if not rows:
        print(f"no figure for {args.company}")
        return 1
    print(f"{'family':28} {'band':13} {'filed':>9} {'n':>5} {'year':>4}  {'posted':>17}  "
          f"{'estimated':>10} {'equity':>10} {'cash bonus':>10} {'stored':>10}")
    for b in sorted(rows, key=lambda b: (b.family, LEVEL_BAND_ORDER[b.band.value])):
        f = b.filed
        filed = (f"{f.base:,}", str(f.filings), str(f.year)) if f else ("", "", "")
        posted = f"{b.posted.base_min:,}-{b.posted.base_max:,}" if b.posted else ""
        r = b.estimated
        points = tuple(f"{v:,}" if v is not None else "" for v in
                       (r.base, r.equity, r.cash_bonus)) if r else ("", "", "")
        theirs = (baselines.get((b.company, b.family, b.band.value)) or {}).get("base_amount")
        print(f"{b.family:28} {b.band.value:13} {filed[0]:>9} {filed[1]:>5} {filed[2]:>4}  {posted:>17}  "
              f"{points[0]:>10} {points[1]:>10} {points[2]:>10} "
              f"{f'{theirs:,}' if theirs else '':>10}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("compare").set_defaults(run=_cmd_compare)
    p = sub.add_parser("coverage")
    p.add_argument("--top", type=int, default=25)
    p.set_defaults(run=_cmd_coverage)
    p = sub.add_parser("show")
    p.add_argument("company")
    p.set_defaults(run=_cmd_show)
    args = parser.parse_args(argv)
    return args.run(args)


if __name__ == "__main__":
    raise SystemExit(main())
