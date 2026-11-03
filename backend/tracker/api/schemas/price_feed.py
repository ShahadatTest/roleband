"""Response and request contracts for Settings > Plugins > Stock prices.

The key is write-only: the request carries it, no response ever does. Every
shape here is built by code, so every one forbids unknown keys (the rule
`schemas/scope.py` explains). Held by `tests/test_price_feed_settings.py`.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import Field, field_validator

from tracker.api.schemas.base import Built
from tracker.api.schemas.text_class import text


class PriceFeedState(Built):
    #: A key is set, here or in the environment.
    configured: bool
    #: Where the key in use comes from; null when there is none.
    origin: Literal["settings", "environment"] | None = Field(json_schema_extra=text("code"))
    #: Companies with a live price.
    priced: int
    #: The newest close among them (a market date).
    as_of: date | None
    #: When the pipeline's price pass last ran.
    last_run_at: datetime | None
    #: Why the feed refused the last run, if it did.
    refused: Literal["rate_limited", "unauthorized"] | None = Field(json_schema_extra=text("code"))
    #: Tickers due that the last run left for later (the budget, a refusal).
    waiting: int = 0
    #: When the next batch can start: the budget's next slot, a 429's wait, or
    #: the next ticker due.
    next_at: datetime | None = None
    #: What the new key's first request came to, on a save; null otherwise.
    key_check: Literal["ok", "no_data", "rate_limited", "timeout", "offline", "error", "unchecked"] | None = Field(
        default=None, json_schema_extra=text("code")
    )


class PriceFeedKey(Built):
    """The key to save. Trimmed; blank is refused (clear it with DELETE)."""

    api_key: str = Field(min_length=1, max_length=256, json_schema_extra=text("identifier"))

    @field_validator("api_key")
    @classmethod
    def trimmed(cls, value: str) -> str:
        value = value.strip()
        if not value or any(c.isspace() for c in value):
            raise ValueError("a key is one word with no spaces")
        return value
