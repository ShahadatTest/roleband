"""Every other company RoleBand can scan.

`COMPANY_DISCOVERY` is the product's recommendation: a short list per sector,
each one a decision. This is the rest of the market RoleBand can read, thousands
of live boards on the families it already collects (Greenhouse, Ashby, Lever,
Workable, SmartRecruiters), none of them a decision. It exists so
a user can FIND any of them by name and follow the whole set in one switch; it
is never shown as a list.

**Data, rebuilt by a reviewed change.** `company_directory.json` is written by
`scripts.discover_board_tokens --directory`, which keeps only boards that
answered live at build time.
Nothing at runtime writes it. A board that has closed since is an ordinary dead
board at follow time, and the monthly rebuild drops it.

**A name is the board's, or it is marked.** Greenhouse, Workable and
SmartRecruiters state whose board it is; Ashby and Lever do not, and their
names are read off the board address (`named_by="address"`), which the product
says rather than presenting a guess as a fact.

**Slugs never collide with a company we already have.** The builder reserves
every `COMPANY_DISCOVERY`, `CATALOG` and built-in slug and every board we
already collect, so a directory row is never a second copy of one of those;
`tests/test_company_directory.py` holds the file to that.
"""

from __future__ import annotations

import functools
import json
from dataclasses import dataclass
from pathlib import Path

DIRECTORY_PATH = Path(__file__).with_name("company_directory.json")

#: `tracked_company.source` for a directory company the user followed by name.
FOLLOWED_BY_NAME = "directory"
#: ... and for one the whole-set follow brought in because it had roles.
FOLLOWED_WITH_SET = "directory-set"
DIRECTORY_SOURCES = frozenset({FOLLOWED_BY_NAME, FOLLOWED_WITH_SET})


@dataclass(frozen=True)
class DirectoryCompany:
    slug: str
    display: str
    #: "board" when the board states this name, "address" when it was read off
    #: the board's address because the family states none.
    named_by: str
    adapter: str
    board_token: str
    board_region: str | None
    #: Position in the file: most-linked boards first. The background scan's
    #: first pass follows it, so the likeliest finds arrive first.
    rank: int


@functools.cache
def directory() -> dict[str, DirectoryCompany]:
    """Every directory company by slug, in rank order. Empty when unbuilt."""
    try:
        raw = json.loads(DIRECTORY_PATH.read_text())
    except FileNotFoundError:
        return {}
    return {
        row["slug"]: DirectoryCompany(
            slug=row["slug"], display=row["display"], named_by=row["named_by"],
            adapter=row["adapter"], board_token=row["board_token"],
            board_region=row.get("board_region"), rank=rank,
        )
        for rank, row in enumerate(raw["companies"])
    }


def directory_company(slug: str) -> DirectoryCompany | None:
    return directory().get(slug)


def directory_size() -> int:
    return len(directory())


def _fold(text: str) -> str:
    return "".join(ch for ch in text.casefold() if ch.isalnum())


def search_directory(query: str, limit: int = 20) -> tuple[list[DirectoryCompany], int]:
    """`(best matches, how many matched)` for a name typed by the user.

    Matched on the name with case, spaces and punctuation set aside ("space x"
    finds SpaceX), and on the board address. A name that STARTS with the query
    outranks one that merely contains it; ties keep directory rank, so the
    likeliest employer comes first. Under two characters matches nothing: a
    single letter would match most of the directory and mean none.
    """
    needle = _fold(query)
    if len(needle) < 2:
        return [], 0
    starts: list[DirectoryCompany] = []
    contains: list[DirectoryCompany] = []
    for company in directory().values():
        name = _fold(company.display)
        if name.startswith(needle):
            starts.append(company)
        elif needle in name or needle in _fold(company.board_token):
            contains.append(company)
    hits = starts + contains
    return hits[:limit], len(hits)
