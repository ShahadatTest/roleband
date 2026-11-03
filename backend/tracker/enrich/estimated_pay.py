"""Estimated pay, read through our atlas; never employer-stated.

No external band is trusted. A family ladder limits the rungs it can price;
without one, the company ladder/printed mapping decides. No guessed rung,
cross-family borrowing, sample count, distribution or company-policy inference.
"""

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from types import SimpleNamespace

from tracker.analytics.comp_package import choose_rung_row
from tracker.levels.ladder import printed_key, reading_ladder
from tracker.levels.model import BONUS_NONE, BONUS_PCT_OF_BASE
from tracker.levels.pay import policy_for
from tracker.levels.words import atlas_band
from tracker.schema import LevelBand

Key = tuple[str, str, LevelBand]


def estimated_band(company: str, family: str, label: str) -> LevelBand | None:
    """An exact atlas spelling/code; a family ladder never borrows another ladder's rung."""
    ladder = reading_ladder(company, family)
    if ladder is None:
        return atlas_band(company, label)
    wanted = printed_key(label)
    head = wanted.split()[0] if wanted else ""
    for rung in ladder.rungs:
        if any(printed_key(s) == wanted for s in rung.spellings):
            return rung.band
        # A qualified code (L7 Product Manager) names the same rung; a word
        # at the head (Senior Product Manager) is not an exact alias.
        if any(ch.isdigit() for ch in head) and printed_key(rung.code) == head:
            return rung.band
    return None


@dataclass(frozen=True)
class EstimatedPay:
    rung: str
    base: int
    equity: int | None
    cash_bonus: int | None

    def annual_bonus(self, company: str) -> int | None:
        """At a no-bonus firm, estimated cash can be sign-on, never annual bonus."""
        rule = policy_for(company).bonus_rule
        if rule == BONUS_NONE:
            return 0
        return self.cash_bonus if rule == BONUS_PCT_OF_BASE else None


def estimated_bases(rows: Iterable[dict[str, str]]) -> dict[Key, EstimatedPay]:
    """One observed row per key, by the pay-label selection rule (`choose_rung_row`).

    Components stay together; no averaging of medians, extrema or made-up
    weights.
    """
    groups: dict[Key, list] = defaultdict(list)
    for row in rows:
        band = estimated_band(row["company"], row["family"], row["rung"])
        if band is None or band is LevelBand.INTERN:
            continue
        value = EstimatedPay(
            row["rung"], int(row["base_usd"]),
            int(row["equity_usd"]) if row["equity_usd"] else None,
            int(row["cash_bonus_usd"]) if row["cash_bonus_usd"] else None,
        )
        groups[(row["company"], row["family"], band)].append(SimpleNamespace(
            family=row["family"], level_label=row["rung"], base_amount=value.base, value=value,
        ))
    return {key: choose_rung_row(key[0], key[2].value, candidates).value
            for key, candidates in groups.items()}
