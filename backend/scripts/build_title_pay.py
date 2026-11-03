"""Build the atlas's filed-pay table from the raw pay store.

    .venv/bin/python -m scripts.build_title_pay             # write atlas/title_pay.csv
    .venv/bin/python -m scripts.build_title_pay --check     # say what would change, write nothing

One cell per company x title x US state x year over the store's government
filings (`observations.csv`, `scripts.build_pay_observations`), for the
named companies only (built-ins, the catalog, the discovery list); every other
company in the app is left out. The shape and its reasons
are `tracker.pay_store.title_pay`. Rebuild after the store is rebuilt (a new
quarter of filings), then run `pytest tests/test_level_atlas.py`.
"""

from __future__ import annotations

import argparse
import csv
import sys
from collections import Counter
from collections.abc import Iterator
from pathlib import Path

from scripts.data import OUT_HELP, build_target
from tracker.company_discovery import named_companies
from tracker.levels.atlas import TITLE_PAY, title_pay_text
from tracker.pay_store.title_pay import build
from tracker.platform.paths import DATA_DIR

SOURCES_DIR = DATA_DIR / "level-atlas-sources"
#: The date the dataset starts for every company.
AS_OF = "2026-10-01"


def _rows(path: Path) -> Iterator[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        yield from csv.DictReader(handle)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dir", type=Path, default=SOURCES_DIR, help="pay sources directory (git-ignored)")
    parser.add_argument("--as-of", default=AS_OF, help="the dataset's start date (YYYY-MM-DD)")
    parser.add_argument("--check", action="store_true", help="write nothing; exit 1 if the file would change")
    parser.add_argument("--out", type=Path, help=OUT_HELP)
    args = parser.parse_args(argv)
    target = build_target("atlas", TITLE_PAY.file, args.out, args.check)

    store = args.dir / "observations.csv"
    if not store.exists():
        print(f"no store at {store}: run scripts.build_pay_observations first", file=sys.stderr)
        return 2
    named = named_companies()
    built = build(_rows(store), named, args.as_of)
    text = title_pay_text(built.rows)

    sizes = Counter("1" if r["n"] == 1 else "2-4" if r["n"] < 5 else "5+" for r in built.rows)
    companies = {r["company"] for r in built.rows}
    print(f"cells {len(built.rows):,}  filings {sum(r['n'] for r in built.rows):,}  "
          f"companies {len(companies)} of {len(named)} named  bytes {len(text.encode()):,}")
    print("cells by filings:", ", ".join(f"{k}: {sizes[k]:,}" for k in ("1", "2-4", "5+")))
    print("left out:", ", ".join(f"{k}: {v:,}" for k, v in sorted(built.dropped.items())) or "none")
    print("named, no filings:", " ".join(sorted(named - companies)) or "none")

    current = target.read_text(encoding="utf-8") if target.exists() else ""
    if args.check:
        print("unchanged" if text == current else f"{target.name} would change")
        return 0 if text == current else 1
    target.write_text(text, encoding="utf-8")
    print(f"wrote {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
