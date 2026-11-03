"""The v1 slots and the one row model each accepts.

A plugin publishes rows into a slot; the host validates every row with the
model here, again on its own side, because a plugin can bypass the SDK. The
models are strict on purpose: a bool is not an amount, a string is not a
count, and an unknown key is an error. Widening a model later is compatible
with every plugin already written; narrowing one is not, so v1 starts narrow.

Lengths match the core columns each field lands in. What the core adds (the
band, the provider, `ingested_at`) is not a field here: a plugin cannot set it.
"""

from __future__ import annotations

import json
import re
from datetime import date
from typing import Annotated, Any, Literal

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    StrictStr,
    field_validator,
    model_validator,
)

PAY_LEVELS = "pay.levels"
PAY_OBSERVATIONS = "pay.observations"
COMPANY_FACTS = "company.facts"
COMPANY_BENEFITS = "company.benefits"

#: Every slot a v1 manifest may declare.
V1_SLOTS = frozenset({PAY_LEVELS, PAY_OBSERVATIONS, COMPANY_FACTS, COMPANY_BENEFITS})

#: Named for v2 and refused in v1, with a message that says so.
V2_RESERVED_SLOTS = frozenset({"listing.source", "notifications"})

#: The company fields a `company.facts` provider may claim: only
#: headcount. A company's identity (name, ticker, public or
#: private, city, website, founding year, logo, colour) is always RoleBand's
#: own.
FACT_FIELDS = ("headcount",)

#: The taxonomy families a `pay.levels` row may name (the core's role groups,
#: `tracker.taxonomy.roles`; the core's tests hold the two equal). The host
#: refuses any other, and so does `FakeHost` unless a test passes its own.
TAXONOMY_FAMILIES = (
    "business_operations_strategy",
    "customer_success",
    "data_engineering",
    "data_science",
    "design_ux",
    "developer_relations",
    "engineering_management",
    "finance_accounting",
    "hardware_engineering",
    "infrastructure_sre",
    "it_support",
    "legal_policy",
    "marketing_communications",
    "ml_ai_research",
    "operations_facilities",
    "people_recruiting",
    "product_management",
    "program_management",
    "sales_business_development",
    "security_engineering",
    "software_engineering",
    "solutions_sales_eng",
    "technical_program_management",
    "technical_writing",
)

#: Slots where a clean run retires, per company published complete, the rows
#: it did not repeat. The others are history and keep every row.
RETIRING_SLOTS = frozenset({PAY_LEVELS, COMPANY_BENEFITS})

#: The fields that name a stored row among one plugin's rows in a slot, as
#: the core's unique key does: rows that share them are one row. `company` is
#: the company a row was published for; an observation's key spans companies.
#: Under a key a retiring slot keeps the latest row and history the first.
#: `company.facts` has none: every claim is kept.
ROW_KEYS: dict[str, tuple[str, ...]] = {
    PAY_LEVELS: ("company", "family", "label", "country"),
    PAY_OBSERVATIONS: ("dedup_key",),
    COMPANY_BENEFITS: ("company", "name", "country"),
}

#: A company the core knows, as a plugin names it: the core's slug.
COMPANY_SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")

#: Rows in one publish call. A larger snapshot is several calls, each but the
#: last `complete=False` (`JobContext.publish`).
MAX_ROWS_PER_PUBLISH = 5000

Money = Annotated[StrictInt, Field(ge=0, le=100_000_000)]
Label = Annotated[StrictStr, Field(min_length=1, max_length=48)]
HttpsUrl = Annotated[StrictStr, Field(max_length=2000, pattern=r"^https://[^\s/]+(/\S*)?$")]

_DETAIL_BYTES = 8192


class _Row(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class PayLevel(_Row):
    """One rung of one company's ladder in one family (`pay.levels`).

    `label` is the company's own word for the rung, verbatim (`L5`, `ICT4`).
    A missing amount is unknown, never zero: send `None`.

    `country` (ISO 3166-1 alpha-2) is the country the figures are for. The
    same rung for two countries is two rows. The core prices a posting only
    from rows for the one country it is in, so a rung with no country prices
    no posting: send it.
    """

    family: Annotated[StrictStr, Field(pattern=r"^[a-z][a-z0-9_]{0,47}$")]
    vendor_family: Label | None = None
    label: Label
    aliases: tuple[Label, ...] = Field(default=(), max_length=16)
    tc: Money | None = None
    base: Money | None = None
    stock: Money | None = None
    bonus: Money | None = None
    currency: Annotated[StrictStr, Field(pattern=r"^[A-Z]{3}$")]
    country: Annotated[StrictStr, Field(pattern=r"^[A-Z]{2}$")] | None = None
    source_url: HttpsUrl | None = None
    as_of: date

    @model_validator(mode="after")
    def _some_amount(self) -> PayLevel:
        if all(v is None for v in (self.tc, self.base, self.stock, self.bonus)):
            raise ValueError("a pay level needs at least one of tc, base, stock or bonus")
        return self


class PayObservation(_Row):
    """One reported pay submission (`pay.observations`).

    `dedup_key` is the plugin's deterministic natural key, so publishing the
    same snapshot twice stores it once. It is unique across every company the
    plugin publishes for: a key reused for another company is the same
    observation, and only the first one sent is kept.

    A component the submission does not state is unknown, never zero: send
    `None`. Amounts are in `currency` and for `country` (ISO 3166-1 alpha-2),
    the market the submission was paid in; a submission with no country, or
    for another market, is kept and never compared with US pay. `family` is a
    taxonomy family when the plugin knows one.
    """

    source_level: Label
    function: Label | None = None
    family: Annotated[StrictStr, Field(pattern=r"^[a-z][a-z0-9_]{0,47}$")] | None = None
    location: Annotated[StrictStr, Field(min_length=1, max_length=64)] | None = None
    yoe: Annotated[StrictInt, Field(ge=0, le=60)] | None = None
    total: Money | None = None
    base: Money | None = None
    equity: Money | None = None
    bonus: Money | None = None
    currency: Annotated[StrictStr, Field(pattern=r"^[A-Z]{3}$")]
    country: Annotated[StrictStr, Field(pattern=r"^[A-Z]{2}$")] | None = None
    snapshot_date: date
    dedup_key: Annotated[StrictStr, Field(min_length=1, max_length=200)]

    @model_validator(mode="after")
    def _some_amount(self) -> PayObservation:
        if all(v is None for v in (self.total, self.base, self.equity, self.bonus)):
            raise ValueError("a pay observation needs at least one of total, base, equity or bonus")
        return self


_FACT_CHECKS: dict[str, tuple[type, Any]] = {
    "headcount": (int, lambda v: 0 <= v <= 10_000_000),
}


class FactClaim(_Row):
    """One claim about one company field (`company.facts`).

    `value=None` claims the field is unknown. The core keeps every claim
    (`company_fact` is append-only) and resolves a winner itself.
    """

    field: Literal["headcount"]
    value: StrictBool | StrictInt | StrictStr | None
    observed_at: AwareDatetime

    @model_validator(mode="after")
    def _value_fits_field(self) -> FactClaim:
        if self.value is None:
            return self
        kind, check = _FACT_CHECKS[self.field]
        # bool is an int subclass: a headcount of True is not a headcount.
        if type(self.value) is not kind or (check is not None and not check(self.value)):
            raise ValueError(f"{self.value!r} is not a valid {self.field}")
        return self


class Benefit(_Row):
    """One perk at one company (`company.benefits`).

    `country` (ISO 3166-1 alpha-2) is where the policy applies. The same perk
    for two countries is two rows. A perk with no country is shown as applying
    somewhere unrecorded, never as company-wide: send it when the source says.
    """

    name: Annotated[StrictStr, Field(min_length=1, max_length=128)]
    category: Label
    value_usd: Money | None = None
    value_text: Annotated[StrictStr, Field(max_length=200)] | None = None
    description: Annotated[StrictStr, Field(max_length=2000)] | None = None
    detail: dict[str, Any] = Field(default_factory=dict)
    perk_id: StrictInt | None = None
    country: Annotated[StrictStr, Field(pattern=r"^[A-Z]{2}$")] | None = None

    @field_validator("detail")
    @classmethod
    def _small_json(cls, v: dict[str, Any]) -> dict[str, Any]:
        try:
            size = len(json.dumps(v, allow_nan=False).encode())
        except (TypeError, ValueError) as exc:
            raise ValueError(f"detail must be plain JSON: {exc}") from None
        if size > _DETAIL_BYTES:
            raise ValueError(f"detail is {size} bytes; the limit is {_DETAIL_BYTES}")
        return v


#: The row model of each v1 slot.
SLOT_ROWS: dict[str, type[_Row]] = {
    PAY_LEVELS: PayLevel,
    PAY_OBSERVATIONS: PayObservation,
    COMPANY_FACTS: FactClaim,
    COMPANY_BENEFITS: Benefit,
}


def row_model(slot: str) -> type[_Row]:
    """The row model for `slot`. A v2 or unknown slot raises `ValueError`."""
    if slot in SLOT_ROWS:
        return SLOT_ROWS[slot]
    if slot in V2_RESERVED_SLOTS:
        raise ValueError(f"slot {slot!r} is reserved for v2 and refused in this SDK")
    raise ValueError(f"unknown slot {slot!r}; v1 slots are {sorted(V1_SLOTS)}")
