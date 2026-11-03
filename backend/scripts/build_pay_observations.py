"""Build the raw pay observation store: one row per data point.

    .venv/bin/python -m scripts.build_pay_observations              # all sources
    .venv/bin/python -m scripts.build_pay_observations --no-db      # filings only
    .venv/bin/python -m scripts.build_pay_observations --dir <sources>

The pay pipeline: first collect every pay data point we may keep, as raw
observations; normalise them into ladders and per-rung statistics after; build
what users see on top of that. This is the first step. It interprets
nothing: a row says who stated what pay for which title, where and when. Family,
rung and band are read later, by the code of that day, so a better reader never
needs a rebuild.

Sources, each a kind of evidence (never a site):

| `source` | Evidence | `pay_kind` |
|---|---|---|
| `dol_lca` | an H-1B labour condition application: the base wage the employer offers for the title | `offered_base` |
| `dol_perm` | a permanent labour certification: same | `offered_base` |
| `posting` | a range the employer printed on its own posting (`jobs.disclosed_*`) | `posted_base_range`, `posted_total_range`, `posted_range_unclear` |

**History.** Every row says when its pay was stated, so a reader can weigh a
figure from an earlier year below a recent one (older pay is kept for
reference, never presented as this year's). `stated_on` is when the employer
stated it: a filing's received date (a PERM decision comes many months later,
so `decided_on`, the agency's date, does not date the pay), or the day we first
read a posting; `last_confirmed` is the last day a posting still showed it;
`vintage` is the year of `stated_on`. Nothing is adjusted here: an adjustment
for pay growth is a normalisation, measured from these rows.

Pay is annualised (`unit` keeps the stated one: Hour x 2080, Week x 52,
Bi-Weekly x 26, Month x 12). `company` is our slug where the employer is one
we track (`pay_sources/dol_employers.json` for filings), empty otherwise: an
unmatched filing is still a data point about the wider market.

Output, git-ignored (`data/` is): `<dir>/observations.csv` and
`<dir>/observations.json` (counts and the sha256 of every input), and
`<dir>/facts.csv` + `facts.json`: what employers state that is not a salary
(UK bonus shares, SEC stock-compensation expense, headcount, vesting terms;
`tracker.pay_store.facts`). Rows are
individual cases, so the store stays out of the repository; what
ships is the project's aggregates, built from it later.

Read-only against the database.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import hashlib
import json
import sys
from collections import Counter
from collections.abc import Iterator
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from tracker.pay_store import facts as pay_facts
from tracker.pay_store.observations import (
    COLUMNS,
    Observation,
    load_employers,
    observe_filings,
    postings,
)
from tracker.platform.paths import DATA_DIR

SOURCES_DIR = DATA_DIR / "level-atlas-sources"
PAY_SOURCES = Path(__file__).with_name("pay_sources")
EMPLOYERS = PAY_SOURCES / "dol_employers.json"
UK_EMPLOYERS = PAY_SOURCES / "uk_gpg_employers.json"
SEC_COMPANIES = PAY_SOURCES / "sec_companies.json"


def filing_rows(dol_dir: Path) -> Iterator[tuple[str, dict[str, str]]]:
    for path in sorted(dol_dir.glob("*_fy*_q*.csv")):
        source = "dol_" + path.name.split("_", 1)[0]
        with path.open(newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                yield source, row


def filings(dol_dir: Path, employers: dict[str, str]) -> tuple[list[Observation], Counter]:
    """One observation per case number across the quarterly files, and why
    the rows that became none were dropped (`pay_store.observations`)."""
    return observe_filings(filing_rows(dol_dir), employers)


async def _posting_rows() -> list[dict]:
    from sqlalchemy import select

    from tracker.db.models import Job
    from tracker.db.session import session_scope

    cols = (Job.id, Job.company, Job.title, Job.locations, Job.location_cities, Job.location_groups,
            Job.disclosed_base_min, Job.disclosed_base_max, Job.disclosed_currency,
            Job.disclosed_pay_period, Job.disclosed_pay_basis, Job.first_seen, Job.last_seen)
    async with session_scope() as session:
        result = await session.execute(select(*cols).where(Job.disclosed_base_min.is_not(None)))
        return [dict(row._mapping) for row in result]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write(
    observations: list[Observation], out_dir: Path, inputs: list[Path], dropped: Counter | None = None
) -> None:
    observations = sorted(observations, key=lambda o: (o.source, o.company, o.stated_on, o.obs_id))
    out_dir.mkdir(parents=True, exist_ok=True)
    with (out_dir / "observations.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS, lineterminator="\n")
        writer.writeheader()
        for o in observations:
            writer.writerow({k: ("" if v is None else v) for k, v in asdict(o).items()})
    by_source = Counter(o.source for o in observations)
    matched = Counter(o.source for o in observations if o.company)
    by_reason: dict[str, dict[str, int]] = {}
    for (source, reason), count in sorted((dropped or Counter()).items()):
        by_reason.setdefault(source, {})[reason] = count
    manifest = {
        "built_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "rows": len(observations),
        "by_source": dict(sorted(by_source.items())),
        "matched_to_a_company": dict(sorted(matched.items())),
        # Rows that became no data point, per source and reason.
        "dropped": by_reason,
        "by_vintage": {
            source: dict(sorted(Counter(o.vintage for o in observations if o.source == source).items()))
            for source in sorted(by_source)
        },
        "companies": len({o.company for o in observations if o.company}),
        "inputs": {p.name: _sha256(p) for p in inputs},
    }
    (out_dir / "observations.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2))


def write_facts(facts: list[pay_facts.Fact], out_dir: Path, inputs: list[Path]) -> None:
    facts = sorted(facts, key=lambda f: (f.source, f.company, f.fact, f.period_end, f.fact_id))
    out_dir.mkdir(parents=True, exist_ok=True)
    with (out_dir / "facts.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=pay_facts.FACT_COLUMNS, lineterminator="\n")
        writer.writeheader()
        for f in facts:
            writer.writerow(asdict(f))
    manifest = {
        "built_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "rows": len(facts),
        "by_fact": dict(sorted(Counter(f"{f.source}:{f.fact}" for f in facts).items())),
        "companies": len({f.company for f in facts}),
        "inputs": len(inputs),
    }
    (out_dir / "facts.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dir", type=Path, default=SOURCES_DIR, help="pay sources directory (git-ignored)")
    parser.add_argument("--no-db", action="store_true", help="skip our own postings (no database read)")
    args = parser.parse_args(argv)
    dol_dir = args.dir / "dol"
    observations, dropped = filings(dol_dir, load_employers(EMPLOYERS))
    if not args.no_db:
        posted, posting_dropped = postings(asyncio.run(_posting_rows()))
        observations += posted
        dropped += posting_dropped
    write(observations, args.dir, sorted(dol_dir.glob("*_fy*_q*.csv")) + [EMPLOYERS], dropped)
    uk = pay_facts.uk_gpg(args.dir / "uk_gpg", pay_facts.names(UK_EMPLOYERS))
    write_facts(uk + pay_facts.sec(args.dir / "sec"), args.dir,
                pay_facts.inputs(args.dir, [UK_EMPLOYERS, SEC_COMPANIES]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
