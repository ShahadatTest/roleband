"""Build the atlas's estimated pay file from a reviewed capture of estimated pay rows.

    .venv/bin/python -m scripts.build_estimated_pay --capture <JSON> --check

Capture: {source: <the rows' source>, families: {their family:
our taxonomy family}, rows: [CompanyCompLevel field dictionaries]}. No request or DB
write. A frozen capture makes every shipped row reproducible.
"""

import argparse
import json
from pathlib import Path

from scripts.data import OUT_HELP, build_target
from tracker.company_discovery import named_companies
from tracker.levels.atlas import ESTIMATED_PAY, estimated_pay_text
from tracker.pay_store.estimated_pay import build


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture", type=Path, required=True)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--out", type=Path, help=OUT_HELP)
    args = parser.parse_args(argv)
    target = build_target("atlas", ESTIMATED_PAY.file, args.out, args.check)
    captured = json.loads(args.capture.read_text(encoding="utf-8"))
    missing = [key for key in ("source", "families", "rows") if key not in captured]
    if missing:
        parser.error(f"capture lacks {', '.join(missing)}: it must name its source and family spellings")
    built = build(captured["rows"], named_companies(),
                  source=captured["source"], families=captured["families"])
    text = estimated_pay_text(built.rows)
    print(f"rows {len(built.rows):,}; companies {len({r['company'] for r in built.rows})}; "
          f"equity {sum(r['equity_usd'] is not None for r in built.rows):,}; "
          f"cash bonus {sum(r['cash_bonus_usd'] is not None for r in built.rows):,}")
    print("left out:", dict(sorted(built.dropped.items())))
    if args.check:
        unchanged = target.exists() and target.read_text(encoding="utf-8") == text
        print("unchanged" if unchanged else f"{target.name} would change")
        return 0 if unchanged else 1
    target.write_text(text, encoding="utf-8")
    print(f"wrote {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
