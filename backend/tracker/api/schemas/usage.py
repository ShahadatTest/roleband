"""Response contracts for usage sharing (docs/architecture.md).

`GET /api/usage` and the routes that change it answer `UsageState`: per consent
group its status, its CURRENT fingerprint (the consent screen echoes it back,
so a screen built for an older scope is refused) and the browser capabilities
the dashboard may turn on when the group is shared. The PostHog host and
project token are served because the dashboard's own SDK needs them; the token
is PostHog's public, write-only key.

`preview` is the exact body the next send would post; `sent` lists what left in
the last 30 days. Both carry only catalogue values (codes), never text.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from tracker.api.schemas.base import Built
from tracker.api.schemas.text_class import text as text_class

UsageGroupName = Literal["usage", "crashes", "questions"]
UsageStatusName = Literal["undecided", "shared", "stale", "declined"]
UsageSwitchName = Literal["ROLEBAND_NO_USAGE_STATS", "DO_NOT_TRACK", "CI"]


class UsageGroupState(Built):
    group: UsageGroupName
    status: UsageStatusName
    fingerprint: str = Field(json_schema_extra=text_class("identifier"))
    browser_scope: list[str] = Field(json_schema_extra=text_class("code"))
    decided_at: datetime | None


class UsageState(Built):
    groups: list[UsageGroupState]
    #: The environment switch that turns sharing off on this machine, if any.
    blocked_by: UsageSwitchName | None
    install_id: str | None = Field(json_schema_extra=text_class("identifier"))
    host: str = Field(json_schema_extra=text_class("identifier"))
    project_key: str = Field(json_schema_extra=text_class("identifier"))
    last_sent_at: datetime | None
    pending_events: int


class UsageConsentPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answers: dict[UsageGroupName, bool]
    #: The exact words the screen showed, stored as agreed.
    text: str = Field(json_schema_extra=text_class("record"))
    locale: str = Field(json_schema_extra=text_class("code"))
    fingerprints: dict[UsageGroupName, str]


class UsagePreview(Built):
    #: The JSON PostHog would receive: `{"api_key", "batch": [...]}`.
    body: dict[str, Any]
    left_out: int


class UsageSentEvent(Built):
    name: str = Field(json_schema_extra=text_class("code"))
    group: UsageGroupName
    day: date | None
    count: int
    props: dict[str, Any]
    sent_at: datetime


class UsageSent(Built):
    events: list[UsageSentEvent]
