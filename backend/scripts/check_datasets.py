"""Check the published datasets: the level atlas and the benefits dataset.

One command for a person, an agent or a data repository's CI. Each problem is
one line naming the file and, where there is one, the line and column; the
exit code is 1 when there is any.

    0  every file keeps its statement
    1  a problem, printed one per line

Usage (from `backend/`):

    .venv/bin/python -m scripts.check_datasets                 # the app's copy
    .venv/bin/python -m scripts.check_datasets --root ../../roleband-data

`--root` checks a data checkout laid out as the data repository is: the
atlas in `atlas/`, the benefits dataset in `benefits/`. The rules are the
app's: the tables it states, the rules its loaders keep, and the company slugs
it names, so a data change is checked against the code that will read it.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from tracker.company_discovery import named_companies
from tracker.levels import atlas
from tracker.profiles import benefits_builtin

#: The data repository's folder for each dataset.
LAYOUT = {"atlas": atlas.ATLAS_DIR, "benefits": benefits_builtin.DATASET}


def check(root: Path | None = None) -> list[str]:
    """Every problem, each prefixed with its dataset's folder."""
    folders = {name: (root / name if root else path) for name, path in LAYOUT.items()}
    out = [f"{name}/: missing" for name, folder in folders.items() if not folder.is_dir()]
    if out:
        return out
    out += [f"atlas/{p}" for p in atlas.problems(folders["atlas"])]
    out += [f"benefits/{p}" for p in benefits_builtin.problems(folders["benefits"], set(named_companies()))]
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--root", type=Path, help="a data checkout with atlas/ and benefits/")
    args = parser.parse_args(argv)
    found = check(args.root)
    for line in found:
        print(line)
    where = args.root or "the app's copy"
    print(f"check_datasets: {where}: {len(found)} problem{'s' if len(found) != 1 else ''}", file=sys.stderr)
    return 1 if found else 0


if __name__ == "__main__":
    raise SystemExit(main())
