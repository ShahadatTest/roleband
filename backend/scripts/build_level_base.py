"""Build the atlas's per-level base pay (`atlas/level_base.csv`).

    .venv/bin/python -m scripts.build_level_base            # write atlas/level_base.csv
    .venv/bin/python -m scripts.build_level_base --check    # exit 1 if the file is stale, write nothing

One row per company x taxonomy family x band that `enrich.level_pay.level_bases`
answers: the base our own evidence gives (filed offer, else posted range, else
an estimated point; never mixed), and annualised stock where we hold it
(or 0 where the policy grants none). The computation stays in
code; this file is its published result, the dataset's per-level pay, so the
company profile reads a file instead of rebuilding from every filing. Rebuild
after any atlas pay file or the title reader changes; `tests/test_level_base.py`
fails on a stale file and names this command.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from scripts.data import OUT_HELP, build_target
from tracker.enrich.level_pay import LevelBase, level_bases
from tracker.levels.atlas import LEVEL_BASE, level_base_text
from tracker.levels.model import EQUITY_NONE
from tracker.levels.pay import policy_for
from tracker.schema import LevelBand

_ORDER = [band.value for band in LevelBand]


def row(lb: LevelBase) -> dict[str, object]:
    return {"company": lb.company, "family": lb.family, "band": lb.band.value,
            "base_usd": lb.base, "stock_usd": stock(lb)}


def stock(lb: LevelBase) -> int | None:
    """Annualised equity, zero where the company grants none, otherwise unknown."""
    if policy_for(lb.company).equity_rule == EQUITY_NONE:
        return 0
    return lb.estimated.equity if lb.estimated is not None else None


def build_text() -> str:
    rows = sorted((row(lb) for lb in level_bases().values()),
                  key=lambda r: (r["company"], r["family"], _ORDER.index(str(r["band"]))))
    return level_base_text(rows)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true", help="exit 1 if the file is stale; write nothing")
    parser.add_argument("--out", type=Path, help=OUT_HELP)
    args = parser.parse_args(argv)
    target = build_target("atlas", LEVEL_BASE.file, args.out, args.check)
    text = build_text()
    current = target.read_text(encoding="utf-8") if target.exists() else ""
    if args.check:
        stale = current != text
        print(f"{target.name}: {'stale, run scripts.build_level_base' if stale else 'current'}")
        return 1 if stale else 0
    target.write_text(text, encoding="utf-8")
    print(f"{target}: {text.count(chr(10)) - 1} rows")
    return 0


if __name__ == "__main__":
    sys.exit(main())
