"""Errors the API answers with a code, not prose (docs/copy.md).

The dashboard says every error in the reader's language from its catalog
(`dashboard/src/copy/en/errors.ftl`, one `error-<code>` message per code), so
a router never sends English for a person to read. It raises

    raise api_error(404, ErrorCode.JOB_NOT_FOUND, "job not found")

which answers `{"detail": {"code": "job-not-found", "params": {}, "message": "job not found"}}`.
`message` is English for logs and the MCP server; `params` carries what a
message needs (slugs, never display names: the client names them). The codes
reach the dashboard through `openapi.json` (`ErrorDetail`), where a test fails
on a code with no catalog message.
"""

from __future__ import annotations

from enum import StrEnum

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field

from tracker.api.schemas.text_class import text


class ErrorCode(StrEnum):
    # Something the request named does not exist.
    JOB_NOT_FOUND = "job-not-found"
    COMPANY_NOT_FOUND = "company-not-found"
    COMPANY_PROFILE_NOT_FOUND = "company-profile-not-found"
    LOCAL_MODEL_NOT_FOUND = "local-model-not-found"
    CLOUD_MODEL_NOT_FOUND = "cloud-model-not-found"
    NOTIFICATION_NOT_FOUND = "notification-not-found"
    LINK_NOT_FOUND = "link-not-found"
    SUGGESTION_NOT_FOUND = "suggestion-not-found"
    RECIPE_NOT_FOUND = "recipe-not-found"
    RULE_NOT_FOUND = "rule-not-found"
    CLUSTER_NOT_FOUND = "cluster-not-found"
    FIT_BAND_NOT_FOUND = "fit-band-not-found"
    SCHEDULE_NOT_FOUND = "schedule-not-found"
    PAGE_NOT_FOUND = "page-not-found"
    PLUGIN_NOT_FOUND = "plugin-not-found"
    # The request itself is malformed: a client defect, said generically.
    INVALID_INPUT = "invalid-input"
    # What the person asked for cannot be done, and why.
    CAREERS_PAGE_REFUSED = "careers-page-refused"
    CAREERS_PAGE_UNREACHABLE = "careers-page-unreachable"
    COMPANY_CONFLICT = "company-conflict"
    COMPANY_REFUSED = "company-refused"
    CONSENT_REQUIRED = "consent-required"
    SCOPE_REFUSED = "scope-refused"
    SCHEDULE_REFUSED = "schedule-refused"
    SCHEDULING_UNAVAILABLE = "scheduling-unavailable"
    DISCOVERY_UNSUPPORTED = "discovery-unsupported"
    MANUAL_SCAN_QUEUED = "manual-scan-queued"
    SWITCH_RUNNING = "switch-running"
    SWITCH_NOT_STARTED = "switch-not-started"
    NO_SWITCH_RUNNING = "no-switch-running"
    SWITCH_NOT_STOPPED = "switch-not-stopped"
    PRICE_KEY_REFUSED = "price-key-refused"
    SWITCH_NOT_MANAGED = "switch-not-managed"
    SERVER_NOT_MANAGED = "server-not-managed"
    MODEL_UNREACHABLE = "model-unreachable"
    LOCAL_MODELS_OFF = "local-models-off"
    AI_EGRESS_OFF = "ai-egress-off"
    NO_LOCAL_MODEL = "no-local-model"
    #: The saved model connections no longer validate; a write would replace them.
    MODEL_PROFILES_UNREADABLE = "model-profiles-unreadable"
    # Plugins: what the install allows, and what the user saw.
    PLUGIN_NOT_RUNNABLE = "plugin-not-runnable"
    PLUGIN_RUNNING = "plugin-running"
    PLUGIN_APPROVAL_STALE = "plugin-approval-stale"
    PLUGIN_STILL_ENABLED = "plugin-still-enabled"
    PLUGIN_CONFIRM_MISMATCH = "plugin-confirm-mismatch"
    PLUGIN_ESTIMATES_MOVING = "plugin-estimates-moving"
    #: A pin on a field a selected plugin answers: pins are ours.
    FIELD_ANSWERED_BY_PLUGIN = "field-answered-by-plugin"
    LINK_TO_ITSELF = "link-to-itself"
    ALREADY_LINKED = "already-linked"
    VERDICT_DECIDED = "verdict-decided"
    PAIR_REFUSED = "pair-refused"
    NOT_A_MEMBER = "not-a-member"
    SUGGESTION_DECIDED = "suggestion-decided"
    LAST_WORLD = "last-world"
    RECIPE_INVALID = "recipe-invalid"
    RECIPE_CONFLICT = "recipe-conflict"
    # The consent screen showed an older scope of a group being shared.
    USAGE_CATALOGUE_CHANGED = "usage-catalogue-changed"


class ErrorDetail(BaseModel):
    """The `detail` of every error the API answers on purpose."""

    model_config = ConfigDict(extra="forbid")

    code: ErrorCode
    params: dict[str, str | int | list[str]]
    #: English, for logs and the MCP server. Never shown to a person.
    message: str = Field(json_schema_extra=text("diagnostic"))


def api_error(status: int, code: ErrorCode, message: str, **params: str | int | list[str]) -> HTTPException:
    """The HTTPException a router raises: a code, its parameters, and English for logs."""
    detail = ErrorDetail(code=code, params=params, message=message).model_dump(mode="json")
    return HTTPException(status_code=status, detail=detail)
