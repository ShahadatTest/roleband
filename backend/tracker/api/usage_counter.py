"""Counts each successful mutation by its stable action name (docs/architecture.md).

A raw ASGI middleware, mounted inside `LoopbackBoundary` (so a refused request
is never counted) and around the router. After the response it reads the route
the router matched (`scope["route"].path`, the TEMPLATE, `/api/jobs/{job_id}/
favorite`, never the requested path with its ids) and the status it answered,
and a 2xx adds one to that route's action in the in-process tally
(`usage_stats.tally`). Nothing is written in the request: the tally is drained
to the outbox every minute, and only while the user shares usage.

An unhandled exception in any request, a read included, is scrubbed into the
tally (only while crash reports are shared) and re-raised untouched, so the
response is the 500 it always was. Only unsafe methods are counted as actions.

Every unsafe route is either in `ACTIONS` or in `NOT_COUNTED` with its reason;
`tests/test_usage_counter.py` fails a route that is in neither, so a new
endpoint is a decision, not a silent gap.
"""

from __future__ import annotations

from collections.abc import Mapping

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from tracker.api.boundary import SAFE_METHODS
from tracker.usage_stats.scrub import scrub
from tracker.usage_stats.tally import TALLY, ApiTally

#: (method, route template) -> the action `daily_action` reports.
ACTIONS: Mapping[tuple[str, str], str] = {
    ("DELETE", "/api/company-profiles/{slug}/manual/{field}"): "company_profile_field_cleared",
    ("DELETE", "/api/intelligence/cloud-models/{profile_id}"): "cloud_model_removed",
    ("DELETE", "/api/intelligence/local-models/{profile_id}"): "local_model_removed",
    ("DELETE", "/api/jobs/{job_id}/favorite"): "unsave_job",
    ("DELETE", "/api/jobs/{job_id}/feedback"): "undismiss_job",
    ("DELETE", "/api/lineage/links/{link_id}"): "lineage_link_removed",
    ("DELETE", "/api/profile/pay-floor"): "pay_floor_cleared",
    ("DELETE", "/api/scope/rules/{rule_id}"): "scope_rule_removed",
    ("PATCH", "/api/companies/{slug}"): "company_updated",
    ("PATCH", "/api/company-profiles/{slug}"): "company_profile_edited",
    ("PATCH", "/api/schedule/{binding_id}"): "company_schedule_changed",
    ("POST", "/api/companies"): "add_company",
    ("POST", "/api/companies/{company}/recipe"): "recipe_started",
    ("POST", "/api/companies/{slug}/board/find"): "board_search",
    ("POST", "/api/connector-recipes"): "recipe_created",
    ("POST", "/api/connector-recipes/{slug}/activate"): "recipe_activated",
    ("POST", "/api/connector-recipes/{slug}/revisions/{revision_id}/validate"): "recipe_validated",
    ("POST", "/api/connectors/preview"): "connector_previewed",
    ("DELETE", "/api/plugins/{plugin_id}"): "plugin_uninstalled",
    ("POST", "/api/plugins/{plugin_id}/approve"): "plugin_approved",
    ("POST", "/api/plugins/{plugin_id}/disable"): "plugin_disabled",
    ("POST", "/api/plugins/{plugin_id}/enable"): "plugin_enabled",
    ("POST", "/api/plugins/{plugin_id}/pause"): "plugin_paused",
    ("POST", "/api/plugins/{plugin_id}/refresh"): "plugin_refreshed",
    ("POST", "/api/plugins/{plugin_id}/remove-data"): "plugin_data_removed",
    ("POST", "/api/plugins/{plugin_id}/resume"): "plugin_resumed",
    ("PUT", "/api/plugins/{plugin_id}/schedule"): "plugin_schedule_set",
    ("POST", "/api/intelligence/cloud-models"): "cloud_model_added",
    ("POST", "/api/intelligence/cloud-models/{profile_id}/test"): "cloud_model_tested",
    ("POST", "/api/intelligence/local-models"): "local_model_added",
    ("POST", "/api/intelligence/local-models/server"): "local_server_controlled",
    ("POST", "/api/intelligence/local-models/{profile_id}/test"): "local_model_tested",
    ("POST", "/api/intelligence/matching/resume"): "matching_resumed",
    ("POST", "/api/intelligence/matching/stop"): "matching_stopped",
    ("POST", "/api/intelligence/test"): "intelligence_tested",
    ("POST", "/api/jobs/{job_id}/place-set/review"): "place_set_reviewed",
    ("POST", "/api/jobs/{job_id}/posting-page"): "posting_page_opened",
    ("POST", "/api/jobs/{job_id}/view"): "job_opened",
    ("POST", "/api/lineage/links/{link_id}/analyze"): "lineage_link_analyzed",
    ("POST", "/api/lineage/links/{link_id}/review"): "lineage_link_reviewed",
    ("POST", "/api/notifications/read_all"): "notifications_read_all",
    ("POST", "/api/notifications/unread"): "notifications_marked_unread",
    ("POST", "/api/notifications/{notification_id}/dismiss"): "notification_dismissed",
    ("POST", "/api/notifications/{notification_id}/read"): "notification_read",
    ("POST", "/api/notifications/{notification_id}/restore"): "notification_restored",
    ("POST", "/api/notifications/{notification_id}/unread"): "notification_unread",
    ("POST", "/api/profile/suggestions/{suggestion_id}/accept"): "suggestion_accepted",
    ("POST", "/api/profile/suggestions/{suggestion_id}/dismiss"): "suggestion_dismissed",
    ("POST", "/api/scope/preview"): "scope_previewed",
    ("POST", "/api/scope/refresh"): "scope_refreshed",
    ("POST", "/api/scope/rules"): "scope_rule_added",
    ("POST", "/api/sync"): "sync_started",
    ("POST", "/api/sync/cancel"): "sync_cancelled",
    ("POST", "/api/twins/links"): "twin_link_added",
    ("POST", "/api/twins/links/{link_id}/analyze"): "twin_link_analyzed",
    ("POST", "/api/twins/links/{link_id}/review"): "twin_link_reviewed",
    ("PUT", "/api/companies/directory/follow"): "follow_all",
    ("PUT", "/api/companies/selection"): "company_selection_saved",
    ("PUT", "/api/companies/{slug}/board"): "company_board_set",
    ("PUT", "/api/compare-selection"): "compare_set",
    ("PUT", "/api/intelligence"): "apple_intelligence_set",
    ("PUT", "/api/intelligence/agents"): "agent_access_set",
    ("PUT", "/api/intelligence/cloud-models/{profile_id}"): "cloud_model_edited",
    ("PUT", "/api/intelligence/egress"): "ai_egress_set",
    ("PUT", "/api/intelligence/local-models/active/select"): "local_model_selected",
    ("PUT", "/api/intelligence/local-models/enabled"): "local_models_toggled",
    ("PUT", "/api/intelligence/local-models/{profile_id}"): "local_model_edited",
    ("PUT", "/api/intelligence/matching/tier"): "matching_tier_set",
    ("PUT", "/api/jobs/{job_id}/favorite"): "save_job",
    ("PUT", "/api/jobs/{job_id}/feedback"): "dismiss_job",
    ("PUT", "/api/jobs/{job_id}/pursuit"): "pursuit_stage_set",
    ("PUT", "/api/profile/pay-floor"): "pay_floor_set",
    ("PUT", "/api/schedule/plan"): "schedule_plan_set",
    ("PUT", "/api/settings"): "settings_saved",
    ("PUT", "/api/settings/intent"): "intent_saved",
    ("PUT", "/api/settings/locale"): "locale_set",
    ("PUT", "/api/settings/retention"): "retention_set",
    # The price key itself never leaves; only that one was saved or removed.
    ("PUT", "/api/settings/price-feed"): "price_key_saved",
    ("DELETE", "/api/settings/price-feed"): "price_key_removed",
}

#: Unsafe routes deliberately not counted, each with its reason.
NOT_COUNTED: Mapping[tuple[str, str], str] = {
    ("POST", "/api/companies/{company}/recipe-rebind"): "source identity review is recorded in the local audit",
    ("POST", "/api/companies/{company}/recipe-rebind/{binding_id}/decisions"): "source identity decisions stay in the local audit",
    ("POST", "/api/companies/{company}/recipe-rebind/{binding_id}/rollback"): "source rollback is recorded in the local audit",
    ("POST", "/api/companies/{company}/recipe-rebind/{binding_id}/activate"): "reviewed source activation stays in the local audit",
    ("PUT", "/api/usage/consent"): "usage sharing's own control: the consent is recorded, not counted",
    ("PUT", "/api/plugins/{plugin_id}/robots"): (
        "a consent the user gives a plugin past its sites' robots rules: recorded on its install, "
        "not counted"),
    ("POST", "/api/usage/install-id/reset"): "usage sharing's own control: a reset must not leave a trace",
    ("POST", "/api/settings/price-feed/refresh"): (
        "asks now for what the prices job does on its own; the key saved and removed are the counted "
        "choices, and a new action would widen the catalogue and re-ask every sharer"),
}


class UsageCounter:
    """ASGI middleware: tally successful mutations and unhandled crashes."""

    def __init__(self, app: ASGIApp, *, tally: ApiTally = TALLY) -> None:
        self.app = app
        self.tally = tally

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        status = 0

        async def send_status(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = int(message["status"])
            await send(message)

        try:
            await self.app(scope, receive, send_status)
        except Exception as exc:
            self.tally.crash(scrub(exc))
            raise
        if scope["method"] not in SAFE_METHODS and 200 <= status < 300:
            route = scope.get("route")
            template = getattr(route, "path", None)
            action = ACTIONS.get((scope["method"], template)) if template else None
            if action is not None:
                self.tally.count(action)
