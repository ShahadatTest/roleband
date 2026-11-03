"""Response and request contracts for Settings > Plugins and the reference set.

Every shape is built by code, so every one forbids unknown keys. A plugin's
own strings (its name, attribution, a run's message) are third-party text:
`content`, shown as written and never translated. States, slots and outcomes
are codes the dashboard turns into words. Held by `tests/test_api_plugins.py`.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from tracker.api.schemas.base import Built
from tracker.api.schemas.text_class import text

PluginState = Literal["needs_approval", "enabled", "disabled", "removed"]
#: A v1 slot (`plugins.slots.SLOTS`; `tests/test_api_plugins.py` holds them equal).
PluginSlot = Literal["pay.levels", "pay.observations", "company.facts", "company.benefits"]
#: How often a plugin's jobs run (`plugins.schedule.SCHEDULES`).
PluginSchedule = Literal["manual", "daily", "weekly", "monthly"]
RunOutcome = Literal["running", "clean", "partial", "bounded", "stopped", "error"]


class PluginJobView(Built):
    name: str = Field(json_schema_extra=text("code"))
    #: What it runs on: the user's schedule, else the manifest's.
    schedule: PluginSchedule
    #: What the plugin's author declared.
    manifest_schedule: PluginSchedule
    budget_seconds: int


class PluginRunView(Built):
    id: int
    job: str = Field(json_schema_extra=text("code"))
    trigger: str = Field(json_schema_extra=text("code"))
    outcome: RunOutcome
    started_at: datetime
    ended_at: datetime | None
    progress_done: int | None
    progress_total: int | None
    #: Rows published per slot.
    published: dict[str, int]
    #: The host's or the plugin's own words about the end: diagnostic.
    message: str | None = Field(json_schema_extra=text("diagnostic"))
    #: What the run did, in the plugin's own words (`ctx.summary`).
    summary: str | None = Field(json_schema_extra=text("content"))
    #: A clean run that ended with its pass unfinished; the next run continues it.
    continues: bool


class PluginReportView(Built):
    """A number the plugin asked the user to see beside it (`ctx.report`)."""

    key: str = Field(json_schema_extra=text("code"))
    value: int
    #: The plugin's own words for what `value` counts, shown after it as written.
    label: str = Field(json_schema_extra=text("content"))
    reported_at: datetime


class PluginReadingLeft(Built):
    """How far the plugin's pass under way has to go, at the pace its own runs
    kept: measured, never declared by the plugin."""

    #: Units (companies, for a company job) the pass has still to go through.
    units: int
    seconds_per_unit: float
    #: About how long until the pass is through, waits between runs included.
    seconds: float


class PayCoverage(Built):
    """`GET /api/pay-coverage`: who answers pay app-wide and, when a
    plugin does, the companies it has read, as of the applied set. Every list
    that shows pay says "not covered" for a company outside it."""

    plugin: str | None = Field(json_schema_extra=text("identifier"))
    plugin_name: str | None = Field(json_schema_extra=text("content"))
    companies: list[str] = Field(json_schema_extra=text("identifier"))


class PluginView(Built):
    """One installed plugin as the Plugins tab lists it."""

    id: str = Field(json_schema_extra=text("identifier"))
    name: str = Field(json_schema_extra=text("content"))
    version: str = Field(json_schema_extra=text("identifier"))
    state: PluginState
    #: The user's switch, apart from approval: a plugin whose approval lapsed
    #: (`needs_approval`) may still be on, and is turned off without approving.
    enabled: bool
    slots: list[PluginSlot]
    #: Slots the registry reads this plugin's rows for now.
    active_slots: list[PluginSlot]
    jobs: list[PluginJobView]
    hosts: list[str]
    attribution: str | None = Field(json_schema_extra=text("content"))
    #: What the plugin does, in its own words (manifest `description`);
    #: null for a plugin that does not say.
    description: str | None = Field(json_schema_extra=text("content"))
    licence: str | None = Field(json_schema_extra=text("content"))
    repository: str | None = Field(json_schema_extra=text("identifier"))
    installed_at: datetime
    approved_at: datetime | None
    enabled_at: datetime | None
    running: bool
    last_run: PluginRunView | None
    last_clean_at: datetime | None
    #: Companies whose rows are read, per slot: each published whole at least once.
    coverage: dict[str, int]
    #: The followed companies a plugin is given to read: what `coverage` is out of.
    companies: int
    #: Null while no pass is under way, or none has measured a pace.
    reading_left: PluginReadingLeft | None
    #: The kinds of data Remove data deletes for it (`SlotSpec.removable`).
    removable_slots: list[PluginSlot]
    #: The stored estimates still read its rows: Remove data waits.
    estimates_read: bool
    #: When the user allowed it past its sites' robots rules; null = it follows them.
    robots_consent_at: datetime | None
    #: Allowed sites whose robots file changed since: their disallowed pages are
    #: skipped until the user looks again.
    robots_lapsed: list[str] = Field(json_schema_extra=text("identifier"))
    #: Numbers the plugin reported, in key order.
    reports: list[PluginReportView]
    #: The user's schedule for every job; null = each job's own.
    schedule: PluginSchedule | None
    #: The schedules the user may choose from, in order.
    schedules: list[PluginSchedule]
    #: Automatic runs held; the plugin stays on and answers.
    paused: bool
    paused_at: datetime | None
    #: When the next automatic run is due; null when none is scheduled to count
    #: from (manual, paused, off, or never updated: then at the next sync).
    next_update_at: datetime | None


class PluginApprovalJob(Built):
    name: str = Field(json_schema_extra=text("code"))
    schedule: str = Field(json_schema_extra=text("code"))
    budget_seconds: int
    needs: list[str]


class PluginApproval(Built):
    """Everything approving lets the plugin do; stored as shown."""

    plugin: str = Field(json_schema_extra=text("identifier"))
    name: str = Field(json_schema_extra=text("content"))
    version: str = Field(json_schema_extra=text("identifier"))
    repository: str = Field(json_schema_extra=text("identifier"))
    licence: str = Field(json_schema_extra=text("content"))
    attribution: str = Field(json_schema_extra=text("content"))
    slots: list[PluginSlot]
    fact_fields: list[str]
    #: The trust its company facts get, capped by the core; null without facts.
    fact_rank: int | None
    hosts: list[str]
    identity: str | None = Field(json_schema_extra=text("code"))
    jobs: list[PluginApprovalJob]


class PluginDetail(PluginView):
    runs: list[PluginRunView]
    approval: PluginApproval
    #: What an approval must name: the install as it is now.
    fingerprint: str = Field(json_schema_extra=text("identifier"))


class ReferenceChangeView(Built):
    id: int
    at: datetime
    jobs: int
    moved: int
    gained: int
    lost: int
    companies: int


class ReferenceView(Built):
    """Which reference set the stored estimates match, and what is still moving."""

    applied_fp: str | None = Field(json_schema_extra=text("identifier"))
    target_fp: str | None = Field(json_schema_extra=text("identifier"))
    pending_jobs: int
    #: Watched by the dashboard: a new id refetches every pay surface.
    last_change_id: int | None
    last_change: ReferenceChangeView | None


class CapabilityView(Built):
    slot: PluginSlot
    #: Active plugins answering this slot, first answers first.
    providers: list[str]
    #: The core's own data answers what no plugin does.
    builtin: bool


class PluginsResponse(Built):
    """`GET /api/plugins`."""

    #: Plugins are shown (`ROLEBAND_PLUGINS`). Off, `plugins` is empty and
    #: Settings says they are coming.
    available: bool
    plugins: list[PluginView]
    reference: ReferenceView
    capabilities: list[CapabilityView]


class PluginApprove(Built):
    """`POST /api/plugins/{id}/approve`: the fingerprint the user was shown, and
    their choice about its sites' robots rules: {host: sha256} of the
    files they allowed it past, or null (it follows them)."""

    fingerprint: str
    robots: dict[str, str] | None = None


class PluginRobotsSite(Built):
    """One declared site's robots file as the approval shows it."""

    host: str = Field(json_schema_extra=text("identifier"))
    #: rules: it disallows something for RoleBand; none: nothing (or no file);
    #: refused: the site would not show it (never consented past); failed: unreachable.
    state: Literal["rules", "none", "refused", "failed"]
    #: Names the file a consent is for; null when refused or failed.
    sha256: str | None = Field(json_schema_extra=text("identifier"))
    #: The patterns it disallows for RoleBand, as the site wrote them.
    disallow: list[str] = Field(json_schema_extra=text("content"))


class PluginRobots(Built):
    """`GET /api/plugins/{id}/robots`: each declared site's rules, read now, and
    the user's current choice."""

    sites: list[PluginRobotsSite]
    consent: dict[str, str] | None
    consent_at: datetime | None


class PluginRobotsSet(Built):
    """`PUT /api/plugins/{id}/robots`: allow it past the files shown, or null to stop."""

    robots: dict[str, str] | None


class PluginRefresh(Built):
    """`POST /api/plugins/{id}/refresh`: one job; the first scheduled one if omitted."""

    job: str | None = None


class PluginScheduleSet(Built):
    """`PUT /api/plugins/{id}/schedule`: how often its jobs run; null = the plugin's own."""

    schedule: PluginSchedule | None


class PluginRemoveData(Built):
    """`POST /api/plugins/{id}/remove-data`: the plugin's id, typed."""

    confirm: str


class PluginActionResponse(Built):
    """After approve, enable, disable, pause, resume, a schedule change or uninstall."""

    plugin: PluginView
    #: A detached re-estimate was started: estimates follow the change.
    reestimate_started: bool
    #: Runner PIDs signalled to stop (disable, pause, uninstall).
    stopped: list[int]


class PluginRefreshResponse(Built):
    started: bool
    job: str | None = Field(json_schema_extra=text("code"))
    #: Why it did not start now: a maintenance wake, already running.
    waiting: str | None = Field(json_schema_extra=text("code"))


class PluginRemoveDataResponse(Built):
    #: Rows deleted per table.
    deleted: dict[str, int]
    reestimate_started: bool
