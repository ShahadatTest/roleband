"""Closed filter vocabularies for the agent tools, resolved honestly.

`search_opportunities` filters on three closed vocabularies: role families,
location groups and companies. An agent does not know our slugs, so it passes
what a person would say ("ML", "London", "Google"). Matched verbatim, such a
value matches nothing, the tool answers zero results, and the agent reports
that to a person as a fact about the market ("there are no ML roles").

The rules, each against a way the tool could lie:

- **Match exactly, after normalising spelling only.** Case, surrounding space
  and runs of space, hyphen or slash are not meaning, so "Product Management",
  "product-management" and "product_management" are one value. Nothing fuzzier:
  a guessed match would narrow to rows the agent did not ask for, which is the
  same lie in the other direction.
- **Name every value that matched nothing**, with the filter it was given for.
- **A filter whose every value was unknown is DROPPED and named**, so the search
  widens instead of answering zero. A filter with at least one known value
  keeps its known values and narrows on them.
- A KNOWN value that matches no posting still narrows to zero: that zero is a
  true answer about the radar, not about our vocabulary.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field

_SEPARATORS = re.compile(r"[\s\-/]+")


def normalize(value: str) -> str:
    """The spelling-only key a value is compared by."""
    return _SEPARATORS.sub("_", value.strip().casefold()).strip("_")


def vocabulary(pairs: Iterable[tuple[str, str | None]]) -> dict[str, str]:
    """Map every accepted spelling (slug or display name) to its slug."""
    out: dict[str, str] = {}
    for slug, display in pairs:
        out[normalize(slug)] = slug
        if display:
            out.setdefault(normalize(display), slug)
    return out


@dataclass
class Resolution:
    """What a set of filters resolved to, and what was not understood."""

    kept: dict[str, list[str]] = field(default_factory=dict)
    ignored: list[dict] = field(default_factory=list)
    dropped_filters: list[str] = field(default_factory=list)

    def resolve(self, name: str, values: Sequence[str] | None, vocab: Mapping[str, str]) -> None:
        if not values:
            return
        kept: list[str] = []
        for value in values:
            slug = vocab.get(normalize(value)) if isinstance(value, str) else None
            if slug is None:
                self.ignored.append({"filter": name, "value": value, "reason": f"not a known {name} value"})
            elif slug not in kept:
                kept.append(slug)
        if kept:
            self.kept[name] = kept
        else:
            self.dropped_filters.append(name)
