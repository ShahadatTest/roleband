"""Response and request contracts for Settings > Data retention.

Every shape here is built by code, so every one forbids unknown keys (the rule
`schemas/scope.py` explains). Held to the settings store and the inventory
counts by `tests/test_data_retention.py`.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import StrictInt

from tracker.api.schemas.base import Built


class RetentionChoice(Built):
    """One option of the Select, with what a run under it would remove now."""

    days: int
    due: int


class RetentionRemoval(Built):
    """The last run that removed anything."""

    at: datetime
    removed: int
    #: The run stopped at its batch bound with more still due.
    more: bool


class RetentionState(Built):
    #: The saved window; null is Never.
    days: int | None
    default_days: int
    choices: list[RetentionChoice]
    #: Every posting RoleBand keeps.
    stored: int
    #: Of those: not listed any more, at a company still followed.
    no_longer_listed: int
    #: Of those: at a company not followed, or not tracked any more.
    stopped_following: int
    #: Removed under the saved window as scans run; 0 for Never.
    due: int
    last_removed: RetentionRemoval | None


class RetentionUpdate(Built):
    """The Select's value: one of `choices`, or null for Never. Strict, so the
    string "60" is refused rather than coerced."""

    days: StrictInt | None
