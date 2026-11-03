"""Reviewed capture of collected per-level statistics; no network or DB write.

Only aggregates reach the atlas. Original vocabulary stays; our atlas decides
its level at use time. Source/URL/band/sample-count columns never travel.

The capture names the source its rows came from and how that source spells our
taxonomy families (`families`, its spelling -> ours), so the core carries no
source's vocabulary of its own.
"""

from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from types import SimpleNamespace

from tracker.analytics.comp_market import us_rows
from tracker.comp_providers.base import OUR_PAY_CURRENCY


@dataclass
class Built:
    rows: list[dict]
    dropped: Counter[str]


def _positive(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else None


def build(
    rows: Iterable[Mapping],
    named: frozenset[str] | set[str],
    *,
    source: str,
    families: Mapping[str, str],
) -> Built:
    """Keep named, US-screened positive-base aggregates and their known components.

    A collected zero may be an absent component defaulted to zero, so it
    cannot prove zero equity/bonus. Export it as unknown, never a company policy.
    The US floor/family screen is a guard, not proof of submission geography.
    """
    dropped: Counter[str] = Counter()
    candidates = []
    for row in rows:
        if row["company_slug"] not in named:
            dropped["company not named"] += 1
        elif row.get("source") != source:
            dropped["another source"] += 1
        elif row["family"] not in families:
            dropped["no exact taxonomy family"] += 1
        elif not row.get("level_label"):
            dropped["no rung label"] += 1
        elif _positive(row.get("base_usd")) is None:
            dropped["no positive base component"] += 1
        else:
            # A stored external band cannot exempt a row from the US floor.
            # `us_rows` reads a stored rung's shape; this capture is our own
            # dataset, which is dollars, so it says so rather than being
            # assumed to be.
            candidates.append(SimpleNamespace(**{
                **row, "band": None,
                "base_amount": _positive(row.get("base_usd")),
                "currency": OUR_PAY_CURRENCY,
            }))
    kept = us_rows(candidates)
    dropped["worldwide or below US floor"] += len(candidates) - len(kept)
    cells = {}
    for kept_row in kept:
        key = (kept_row.company_slug, families[kept_row.family], kept_row.level_label)
        if key in cells:
            raise ValueError(f"duplicate collected key: {key}")
        cells[key] = {
            "company": key[0], "family": key[1], "rung": key[2], "base_usd": kept_row.base_usd,
            "equity_usd": _positive(getattr(kept_row, "stock_usd", None)),
            "cash_bonus_usd": _positive(getattr(kept_row, "bonus_usd", None)),
        }
    return Built([cells[k] for k in sorted(cells)], +dropped)
