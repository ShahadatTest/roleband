"""Pure formatting helpers for notification titles/bodies (labels, money, time)."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from functools import cache

from tracker.company_catalog import CATALOG
from tracker.company_discovery import COMPANY_DISCOVERY
from tracker.config import COMPANIES


@cache
def _known_names() -> dict[str, str]:
    """Every company RoleBand knows by slug, named as its register row would be.

    The order is the one `tracked_company.display` is written in: a catalog
    company takes the catalog's name (`company_store.resolve_company`), a
    built-in its blueprint's (`ensure_builtins`), and any other listed company
    its discovery entry's. Built once: these tables are code.
    """
    names = {slug: company.display for slug, company in COMPANY_DISCOVERY.items()}
    names.update({slug: cfg["display"] for slug, cfg in COMPANIES.items()})
    names.update({slug: entry["display"] for slug, entry in CATALOG.items()})
    return names


def _company_label(slug: str) -> str:
    """A company's name when the register gave none: the last resort.

    Callers pass the register's own names first (`tracked_company.display`,
    the name the user follows the company by); this answers only for
    a slug the register lacks. A slug no table knows is spelled out with its
    hyphens as spaces, so "jane-street" can never reach a sentence.
    """
    known = _known_names().get(slug)
    if known:
        return known
    return " ".join(word.capitalize() for word in slug.replace("_", "-").split("-") if word) or slug


def company_namer(names: Mapping[str, str] | None) -> Callable[[str], str]:
    """`slug -> name`: the register's name for it, else `_company_label`."""
    known = names or {}

    def label(slug: str) -> str:
        return known.get(slug) or _company_label(slug)

    return label


_PER = {"month": " a month", "hour": " an hour"}


def _figure(n: float, period: str) -> str:
    if period != "year":
        return f"{n:,.2f}".removesuffix(".00")
    if n >= 1_000_000:
        return f"{n / 1_000_000:.2f}M".replace(".00M", "M")
    return f"{round(n / 1000)}k"


def _money(
    low: float | None, high: float | None = None, *, currency: str | None = None, period: str = "year"
) -> str:
    """English for a stated amount or range in its own currency and period:
    `$150k-$200k`, `80k-95k GBP`, `$45-$60 an hour`. Nothing is converted or
    annualised; only a yearly figure is written in thousands."""
    values = list(dict.fromkeys(v for v in (low, high) if v is not None))
    if not values:
        return "unknown comp"
    code = (currency or "USD").upper()
    figures = [_figure(v, period) for v in values]
    text = "-".join(f"${f}" for f in figures) if code == "USD" else f"{'-'.join(figures)} {code}"
    return text + _PER.get(period, "")


def _fmt_time(dt: datetime | None) -> str:
    if dt is None:
        return "unknown time"
    return dt.astimezone(UTC).strftime("%Y-%m-%d %H:%M UTC")


def _fmt_duration(seconds: float | None) -> str:
    from tracker.notifications import say as S
    return S.english(S.duration(seconds))


def _source_summary(sources: list[str]) -> str:
    from tracker.notifications import say as S
    return S.english(S.sources(sources))


def _affected_summary(
    error_sources: list[str], drift: list[dict], label: Callable[[str], str] = _company_label
) -> str:
    """Name the sources at fault. '1 drift alerts' tells the user nothing.

    Empty does NOT mean "all of them" here, so `_source_summary`'s fallback
    does not apply. The two callers read an empty list oppositely: a scan
    STARTED with no subset really is scanning every enabled source, while
    nothing being at fault means the fault was not a source's (a failed
    post-pass, for one).

    Companies are named by `label`, the name the user knows them by, never the
    slug ("meta" read as a word, "google-deepmind" as a code).
    """
    from tracker.notifications import say as S
    return S.english(S.affected(affected_slugs(error_sources, drift), label))


def affected_slugs(error_sources: list[str], drift: list[dict]) -> list[str]:
    """The companies at fault, error sources first, then each drifting one once."""
    slugs: list[str] = list(error_sources)
    for row in drift:
        # Alerts are `{adapter}:{company}`; the company is the part after the
        # colon; the part before it names the adapter, never the company.
        source = row["source"].split(":", 1)[-1]
        if source not in slugs:
            slugs.append(source)
    return slugs
