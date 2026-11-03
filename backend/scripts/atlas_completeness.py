"""How complete the atlas is for the named companies.

    .venv/bin/python -m scripts.atlas_completeness            # the scoreboard
    .venv/bin/python -m scripts.atlas_completeness --gaps     # and every gap by name
    .venv/bin/python -m scripts.atlas_completeness --write    # rewrite the committed gap list

`--write` after a batch fills gaps: the committed list only shrinks, and the
test names any company that joins a gap. Sections: `tracker.levels.completeness`
reads the atlas files; `level_base` (our own per-level base, in shadow) needs the
level reader, which sits a layer above the atlas, so it is joined here
(`tracker.enrich.level_pay.answers`).
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Iterable
from pathlib import Path

from tracker.company_discovery import named_companies
from tracker.enrich.level_pay import answers
from tracker.levels.completeness import SECTIONS, gaps
from tracker.levels.pay import PAY_POLICIES

GAPS_FILE = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "atlas_gaps.json"
#: Every scored section, in print order.
SCOREBOARD = (*SECTIONS, "level_base")


def scoreboard_gaps(named: Iterable[str]) -> dict[str, list[str]]:
    """section -> the named companies it does not answer, sorted, every section."""
    companies = set(named)
    found = gaps(companies)
    found["level_base"] = [c for c in sorted(companies) if not answers(c)]
    return found


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--gaps", action="store_true", help="list every gap by company")
    parser.add_argument("--write", action="store_true", help=f"rewrite {GAPS_FILE.name}")
    args = parser.parse_args(argv)
    named = named_companies()
    found = scoreboard_gaps(named)
    print(f"{len(named)} named companies")
    for section in SCOREBOARD:
        missing = found[section]
        searched = sum(1 for c in named if section in getattr(PAY_POLICIES.get(c), "unknown", ()))
        known = f"  ({len(named) - len(missing) - searched} known, {searched} unknown)" if searched else ""
        print(f"  {section:15} answered {len(named) - len(missing):3}   missing {len(missing):3}{known}")
        if args.gaps and missing:
            print("    " + ", ".join(missing))
    if args.write:
        GAPS_FILE.write_text(json.dumps(found, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"wrote {GAPS_FILE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
