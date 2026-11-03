"""The built-in pay rows: our own dataset as a pay source, served in memory.

One row per (company, taxonomy family, band, component), with its estimated
value and country. Built here, in the
enrich layer, from the atlas files `level_pay` reads; never an atlas CSV export
and never a `company_comp_level` row (no foreign key to `company_profile`, no
unique-key clash with a plugin).

Components, and what a missing one means:
- **base**: `level_pay.level_bases()`, filed offer > posted midpoint > estimated
  point, never mixed. Every value is an estimate for the matched level.
- **bonus**: only where the company's policy states a target
  (`levels.pay.bonus_ratio_for`): the target share of the rung's base, `0` for
  a company that pays no annual bonus. An unverified policy is NO row, never 0.
- **equity**: not built (the atlas has no per-rung equity). A job's package
  never reads `grant_term`.
A total exists only when all three answer, so none does while equity is unbuilt.

`Settings.builtin_pay_enabled` switches the source. `BuiltinPayProvider`
answers a base-only estimate, and the reference set includes it (and its
fingerprint) only when the setting is on; switching it is one re-estimate with
its moved report.

Cached on disk by fingerprint (`builtin-pay-<fp>.json` under
`Settings.cache_dir()`): building reads every filing (seconds); a changed atlas
file or reader is a new fingerprint and a new build.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import tempfile
from dataclasses import asdict, dataclass
from functools import cache
from pathlib import Path

from tracker.comp_providers.base import (
    BUILTIN,
    OUR_PAY_COUNTRY,
    CompContext,
    CompEstimate,
    CompProvider,
)
from tracker.config import get_settings
from tracker.enrich.inventory import classifier_fingerprint
from tracker.enrich.level_pay import LevelBase, level_bases
from tracker.levels.pay import bonus_ratio_for

logger = logging.getLogger(__name__)

#: The estimate is a point; the band around it is stated, not measured (as the
#: table provider's is).
_SPREAD = 0.15

_TRACKER = Path(__file__).resolve().parents[1]
#: What a build reads besides the classifier (already in `classifier_fingerprint`):
#: this module, the base computation and every pay file behind it.
BUILD_SOURCES = (
    "enrich/builtin_pay.py",
    "enrich/level_pay.py",
    "enrich/estimated_pay.py",
    "levels/pay.py",
    "levels/pay_grades.py",
    "levels/atlas/title_pay.csv",
    "levels/atlas/posted_pay.csv",
    "levels/atlas/pay_grades.csv",
    "levels/atlas/pay_bands.csv",
    "levels/atlas/estimated_pay.csv",
    "levels/atlas/company_facts.csv",
    "levels/atlas/rungs.csv",
)

COMPONENTS = ("base", "bonus", "equity")


@dataclass(frozen=True)
class BuiltinPayRow:
    company: str
    family: str  # our taxonomy family, never a source's own ladder name
    band: str
    component: str  # base | bonus | equity
    value: int
    country: str = "US"


@cache
def build_fingerprint() -> str:
    digest = hashlib.sha256(classifier_fingerprint().encode())
    for entry in BUILD_SOURCES:
        digest.update(entry.encode())
        digest.update((_TRACKER / entry).read_bytes())
    return digest.hexdigest()


def _base_row(lb: LevelBase) -> BuiltinPayRow:
    return BuiltinPayRow(lb.company, lb.family, lb.band.value, "base", lb.base)


def _bonus_row(lb: LevelBase, base: int) -> BuiltinPayRow | None:
    ratio = bonus_ratio_for(lb.company, lb.band)
    if ratio is None:
        return None
    return BuiltinPayRow(lb.company, lb.family, lb.band.value, "bonus", round(base * ratio))


def build_rows() -> list[BuiltinPayRow]:
    """Every built-in row, deterministic in order. Pure over the atlas files."""
    rows: list[BuiltinPayRow] = []
    for lb in level_bases().values():
        base = _base_row(lb)
        rows.append(base)
        bonus = _bonus_row(lb, base.value)
        if bonus is not None:
            rows.append(bonus)
    return rows


def _cache_path(fingerprint: str) -> Path:
    return get_settings().cache_dir() / f"builtin-pay-{fingerprint}.json"


def cached_rows() -> list[BuiltinPayRow]:
    """The rows for the current fingerprint: from the cache, else built and cached."""
    fingerprint = build_fingerprint()
    path = _cache_path(fingerprint)
    try:
        return [BuiltinPayRow(**row) for row in json.loads(path.read_text())["rows"]]
    except (OSError, ValueError, KeyError, TypeError):
        pass
    rows = build_rows()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".builtin-pay-")
        with os.fdopen(fd, "w") as out:
            json.dump({"fingerprint": fingerprint, "rows": [asdict(r) for r in rows]}, out)
        os.replace(tmp, path)
    except OSError:
        logger.warning("builtin pay: could not write the cache at %s", path, exc_info=True)
    return rows


Index = dict[tuple[str, str, str], dict[str, BuiltinPayRow]]


def index_rows(rows: list[BuiltinPayRow]) -> Index:
    """(company, family, band) -> component -> row."""
    out: Index = {}
    for row in rows:
        out.setdefault((row.company, row.family, row.band), {})[row.component] = row
    return out


class BuiltinPayProvider(CompProvider):
    """Our dataset as an estimate: the parts it answers, labelled, never a total
    it cannot measure. Used only while `builtin_pay_enabled` is on."""

    name = "builtin_pay"

    def __init__(self, index: Index) -> None:
        self._index = index

    async def lookup(self, ctx: CompContext) -> CompEstimate | None:
        if ctx.family is None or ctx.country != OUR_PAY_COUNTRY:
            return None
        parts = self._index.get((ctx.company, ctx.family, ctx.band.value))
        if not parts or "base" not in parts:
            return None
        base = parts["base"]
        total = None
        if all(c in parts for c in COMPONENTS):
            total = sum(parts[c].value for c in COMPONENTS)
        return CompEstimate(
            median=total,
            low=int(total * (1 - _SPREAD)) if total else None,
            high=int(total * (1 + _SPREAD)) if total else None,
            currency="USD",
            source="RoleBand estimated base",
            detail={"provider": self.name, "components": sorted(parts)},
            base_median=base.value,
            base_low=int(base.value * (1 - _SPREAD)),
            base_high=int(base.value * (1 + _SPREAD)),
            provider=BUILTIN,
        )
