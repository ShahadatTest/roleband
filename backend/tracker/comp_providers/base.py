"""Compensation provider interface + shared value types.

Providers are pluggable and degradable: each returns a `CompEstimate` or None,
and the resolver aggregates whatever succeeds, so the stored-row, built-in and
static tiers and any plugin's rows plug in without touching the pipeline.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date

from tracker.blueprint import BLUEPRINT
from tracker.schema import LevelBand

#: The provider value of the core's own dataset.
BUILTIN = "builtin"
#: The country every figure of RoleBand's own data is for: its dataset, its
#: seed pay and its own stored rows are US pay. They answer a US posting only.
OUR_PAY_COUNTRY = "US"
#: And the currency those figures are in. A rung a plugin publishes carries
#: its own; nothing converts between them, so a reader compares within one.
OUR_PAY_CURRENCY = "USD"


def company_name(slug: str) -> str:
    """The company as a reader names it: its built-in display name, else its slug in words."""
    blueprint = BLUEPRINT.get(slug)
    return blueprint.display if blueprint else slug.replace("-", " ").title()


@dataclass
class CompContext:
    """Everything a provider needs to look up comp for a posting."""

    company: str
    band: LevelBand
    family: str | None
    location_group: str | None
    #: The one country the posting's pay is for (`taxonomy.locations.pay_country`);
    #: None when it names several or none, and then nothing answers: a figure is
    #: for one country and is never shown for a posting in another.
    country: str | None
    title: str


@dataclass
class CompEstimate:
    median: int | None
    low: int | None
    high: int | None
    currency: str
    source: str  # human-readable provenance, e.g. "Google L6 estimated median (software_engineering)"
    detail: dict
    #: The base range, its own estimate; None = unknown.
    base_median: int | None = None
    base_low: int | None = None
    base_high: int | None = None
    #: Who published the answering data: a plugin id, a core-written source,
    #: or `builtin` for the core's own dataset.
    provider: str | None = None
    as_of: date | None = None

    @property
    def component(self) -> str | None:
        """total | base: the widest component this estimate answers."""
        if self.median is not None:
            return "total"
        if self.base_median is not None:
            return "base"
        return None


class CompProvider(ABC):
    name: str = "base"

    @abstractmethod
    async def lookup(self, ctx: CompContext) -> CompEstimate | None:
        raise NotImplementedError

    async def aclose(self) -> None:
        """Release any resources (HTTP clients, caches). Optional."""
        return None
