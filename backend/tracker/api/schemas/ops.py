"""Response contracts for the operational surface.

Health, the freshness/supervision status the watchdog and the header badge
poll, the run log, the manual sync trigger, picker and cancel, and the
connector schedule Settings reads and moves.

Every shape here except two JSONB columns is built by our code, so every model
forbids unknown keys: a key the serializer adds without its model is a 500 a
test catches, never output that silently fails to arrive.

**A shape whose keys differ by branch is a union, never optional keys.** Five
serializers return different key SETS depending on what happened: a disabled
post-pass carries no freshness fields, only a stale binding names its last
reconcile, a started sync reports what it queued while an attached one names
the run, and a cancel that stopped nothing names no run. Each branch is its own
model and the field or route answers their union, so "this key is absent here"
is a type a client narrows on, not a `null` it has to guess about. Where a
string literal tells the branches apart (`status`, `reason`) the union is
discriminated on it. A route that answers a union answers a named `RootModel`
of it, which serializes as the branch itself and is what the route table
counts as modelled.

Literal types only for vocabularies our code owns: the scheduler's provider
states and overdue reasons, the sync and cancel statuses, and `SourceOutcome`,
which `/api/sync/targets` derives at request time. Strings read back from the
database stay `str`: no CHECK constraint bounds a run status, a derivation
status or a stored provider outcome, and a historical row
keeps whatever its writer wrote.

`per_source` and `drift_alerts` are served exactly as stored. A typed model would
re-emit their keys in its own declaration order instead of JSONB's, and the
stored key set is pinned where it is written (`tests/test_pipeline_lifecycle.py`).

Fields are declared in the order the handlers build them, so every response
keeps its key order byte for byte.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, RootModel

from tracker.api.schemas.base import Built
from tracker.api.schemas.notifications import NotificationSay
from tracker.api.schemas.plugins import CapabilityView, ReferenceView
from tracker.api.schemas.text_class import text
from tracker.connectors.recipes.outcome import SourceOutcome
from tracker.db.queries.binding_attention import Cause


class HealthResponse(Built):
    """`GET /api/health`: the database answered. Anything else is a 500."""

    status: Literal["ok"]


# --------------------------------------------------------------------------- #
# /api/status
# --------------------------------------------------------------------------- #


class DerivationEnabled(Built):
    """An enabled post-pass. `last_*` and `age_hours` are null for a pass that
    has never run, which is also what makes it stale."""

    name: str = Field(json_schema_extra=text("code"))
    enabled: Literal[True]
    last_ok_at: datetime | None
    last_run_at: datetime | None
    last_status: str | None
    age_hours: float | None
    stale: bool


class DerivationDisabled(Built):
    """A post-pass switched off by settings: no freshness to report, never stale."""

    name: str = Field(json_schema_extra=text("code"))
    enabled: Literal[False]
    stale: Literal[False]


# Not discriminated: a boolean discriminator reaches OpenAPI as the string keys
# "True"/"False", and the generated client then types `enabled` as a string.
# Both branches forbid unknown keys, so the plain union still admits exactly one.
DerivationFreshness = DerivationEnabled | DerivationDisabled


class OverdueBinding(Built):
    """A binding with no authoritative reconcile at all: never scheduled, or
    scheduled and never reconciled."""

    company: str
    reason: Literal["not_scheduled", "never_reconciled"] = Field(json_schema_extra=text("code"))


class StaleBinding(Built):
    """A binding whose last authoritative reconcile is older than the window."""

    company: str
    reason: Literal["authoritative_stale"] = Field(json_schema_extra=text("code"))
    last_reconcile_at: datetime


Overdue = Annotated[OverdueBinding | StaleBinding, Field(discriminator="reason")]


class UnreadBinding(Built):
    """A required binding whose board was not read in full inside the window
    (`read_stale`), or never (`never_read`, `last_read_at` null). A full read
    is an `ok`, `empty` or `lossy` reconcile, authoritative or not; these are
    what make the status stale."""

    company: str
    reason: Literal["never_read", "read_stale"] = Field(json_schema_extra=text("code"))
    last_read_at: datetime | None


class ExcludedBinding(Built):
    """A binding the roster does not require fresh: behind a paused or
    policy-denied provider, one automatic work never collects (a walled
    company without consent, a user-directed source the user has not asked
    for; `schedule_status.waits_for_user`), or a company whose
    careers page is gone from its address, which Coverage tells."""

    company: str
    provider: str
    reason: Literal["policy_denied", "paused", "walled", "user_directed", "board_missing"] = Field(
        json_schema_extra=text("code")
    )


class ManualSyncBlock(Built):
    """A provider holding queued manual requests back, and how many companies
    wait on it. `until` is the backoff's end, and null for a block with no
    scheduled end."""

    provider: str
    reason: Literal["policy_denied", "paused", "backoff"] = Field(json_schema_extra=text("code"))
    until: datetime | None
    companies: int


class ProviderPressure(Built):
    """A provider that is not simply ready: paused, denied, or cooling down."""

    provider: str
    state: str
    cooldown_until: datetime | None
    last_outcome: str | None


class SchedulerStatus(Built):
    """Per-binding authoritative freshness and provider-safe due work."""

    enabled: bool
    seeded: bool
    required: int
    ever_read: int
    fresh: int
    overdue: list[Overdue]
    unread: list[UnreadBinding]
    excluded: list[ExcludedBinding]
    last_complete_at: datetime | None
    #: The oldest full read among required companies ever read (a full
    #: read, not an authoritative one).
    oldest_scan_at: datetime | None
    next_due_at: datetime | None
    providers: list[ProviderPressure]


class BindingAttentionItem(Built):
    """One followed company without a full scan for `coverage_stale_after_days` (3 days), or
    whose board proved it lists nothing, read from its scan runs.

    `cause` is a vocabulary `db/queries/binding_attention.py` owns, served as
    its own `Cause` alias; `cause_outcome` is read back from an unconstrained
    column and stays a string. `last_full_scan_at` is `None` for a company no
    scan ever read in full, and `days_since_full_scan` then counts from when
    its binding was made. `automatic` is false for a company scanned only when
    the user asks (a user-directed source) or not at all (walled, no consent): the bell never
    rings for those. `empty_since` is set only while the newest reconcile
    proved the board empty."""

    company: str
    display: str = Field(json_schema_extra=text("content"))
    provider: str
    connector_kind: str
    automatic: bool
    last_full_scan_at: datetime | None
    days_since_full_scan: float | None
    never_scanned: bool
    stale: bool
    last_attempted_at: datetime | None
    held_open: int
    cause: Cause
    cause_outcome: str | None
    cause_at: datetime | None
    cause_message: str | None = Field(json_schema_extra=text("diagnostic"))
    empty_since: datetime | None
    days_empty: float | None
    listed_before: int | None


class BindingAttention(Built):
    """Counts over every followed company; `items` lists at most the first 50
    flagged ones. `outage` is true when the stale, automatically scanned ones
    are many enough to be our outage rather than theirs: the bell then rings
    once for all of them."""

    followed: int
    automatic: int
    flagged: int
    stale: int
    empty: int
    outage: bool
    held_open: int
    items: list[BindingAttentionItem]


class JobProgress(Built):
    done: int
    total: int | None


class JobWaiting(Built):
    """Work a job left for later, and when it can start (the prices job's budget)."""

    count: int
    until: datetime | None


class JobView(Built):
    """One supervised job, as the supervisor last published it. `reason` is a
    plain code the dashboard words; parameters travel in their own fields."""

    key: str = Field(json_schema_extra=text("identifier"))
    job: str = Field(json_schema_extra=text("identifier"))
    state: Literal["idle", "waiting", "queued", "starting", "running", "stopping", "stopped", "disabled"] = Field(
        json_schema_extra=text("code")
    )
    reason: str | None = Field(json_schema_extra=text("code"))
    since: datetime
    next_at: datetime | None
    run_id: int | None
    progress: JobProgress | None
    waiting: JobWaiting | None
    #: Requests asked for and not yet started.
    queued: int


class SupervisorView(Built):
    """The background supervisor: `stale` once its heartbeat is over 90 s old,
    `absent` when none has ever run on this database. `reason` says why landed
    code waits (`schema_pending`, `dependencies_pending`, `build_failed`)."""

    state: Literal["running", "stale", "absent", "maintenance"] = Field(json_schema_extra=text("code"))
    since: datetime | None
    reason: str | None = Field(default=None, json_schema_extra=text("code"))


class LauncherHold(Built):
    kind: Literal["attention", "waiting"] = Field(json_schema_extra=text("code"))
    reason: str = Field(json_schema_extra=text("code"))


class LauncherPresentation(Built):
    observed_at: datetime
    activity: Literal["idle", "scanning", "updating"] = Field(json_schema_extra=text("code"))
    activity_since: datetime | None
    hold: LauncherHold | None
    attention: list[Literal["coverage", "stuck_scan"]] = Field(json_schema_extra=text("code"))
    queued: Literal["scan", "update"] | None = Field(json_schema_extra=text("code"))
    coverage_at: datetime | None
    last_scan_at: datetime | None
    last_scan_outcome: str | None = Field(json_schema_extra=text("code"))
    model: Literal["ready", "preparing", "missing", "unused"] = Field(json_schema_extra=text("code"))


class LauncherIdentity(Built):
    product: Literal["roleband"] = Field(json_schema_extra=text("code"))
    instance: str = Field(json_schema_extra=text("identifier"))
    api_origin: str = Field(json_schema_extra=text("identifier"))
    version: str = Field(json_schema_extra=text("identifier"))
    format: Literal[1]


class PreparationStatus(Built):
    database: Literal["waiting", "creating", "ready", "failed"] = Field(json_schema_extra=text("code"))
    model: Literal["waiting", "downloading", "verifying", "ready", "unused", "failed"] = Field(json_schema_extra=text("code"))
    service: Literal["starting", "ready", "failed"] = Field(json_schema_extra=text("code"))
    downloaded_bytes: int = Field(ge=0)
    total_bytes: int = Field(ge=0)
    tier: Literal["fp32", "int8"] | None = Field(json_schema_extra=text("code"))
    reason: str | None = Field(json_schema_extra=text("code"))
    format: Literal[1]


class LauncherHealthResponse(Built):
    status: Literal["ok"] = Field(json_schema_extra=text("code"))
    launcher: LauncherIdentity
    preparation: PreparationStatus | None

class LauncherScanCompany(Built):
    name: str = Field(json_schema_extra=text("content"))
    since: datetime


class LauncherScan(Built):
    """The menu-bar scan picture. Live fields are null unless a scan is executing; `last_*`
    describe the newest finished run, and `last_new_roles` counts its roles the New board
    lists. `phase` says where a live scan is: reading companies (`collecting`), adding the
    last roles it read (`persisting`), or the passes after the scan (`finishing`), which
    can outlast the reading. `scheduling` says how scans start on their own: on the schedule plan, on each
    company's own timer, or not at all. `next_scan_at` is never earlier than the read and
    is null while scheduling is off; `paused_until` is set only while the plan is paused."""

    phase: Literal["collecting", "persisting", "finishing"] | None = Field(json_schema_extra=text("code"))
    percent: int | None = Field(ge=0, le=100)
    companies_total: int | None = Field(ge=0)
    #: Companies being read now, longest first, at most five.
    in_flight: list[LauncherScanCompany]
    #: Roles found at companies whose scan has not ended yet, and roles already written.
    roles_pending: int | None = Field(ge=0)
    roles_recorded: int | None = Field(ge=0)
    last_companies: int | None = Field(ge=0)
    last_new_roles: int | None = Field(ge=0)
    last_postings: int | None = Field(ge=0)
    last_stopped: bool
    next_scan_at: datetime | None
    scheduling: Literal["plan", "timers", "off"] = Field(json_schema_extra=text("code"))
    paused_until: datetime | None


class LauncherStatus(LauncherIdentity):
    status: LauncherPresentation
    scan: LauncherScan | None = None


class ReleaseNotesResponse(Built):
    launcher: LauncherIdentity | None
    version: str = Field(json_schema_extra=text("identifier"))
    notes: str | None = Field(json_schema_extra=text("content"))


class SystemStatusResponse(Built):
    """`GET /api/status`: freshness and supervision for the watchdog and badge.

    `running` means a pipeline is executing right now and nothing else; queued
    manual work reports as `manual_queued` / `manual_blocked`. Once the roster
    is seeded, `last_success_at` and `stale` come from `scheduler`; before that,
    from the newest full refreshing run. `last_scan_at` is the newest refreshing
    run of any scope: when a scan last read anything, not how fresh the
    oldest read is."""

    db: Literal["ok", "error"]
    preparation: PreparationStatus | None = None
    launcher: LauncherStatus | None
    last_success_at: datetime | None
    last_success_age_hours: float | None
    last_scan_at: datetime | None
    last_scan_age_hours: float | None
    last_run_status: str | None
    last_run_started_at: datetime | None
    last_run_finished_at: datetime | None
    last_run_new: int | None
    last_run_seen: int | None
    running: bool
    manual_sync_running: bool
    manual_queued: list[str]
    manual_blocked: list[ManualSyncBlock]
    stuck_running: int
    stale: bool
    freshness_max_hours: int
    derivations: list[DerivationFreshness]
    derivations_stale: list[str]
    scheduler: SchedulerStatus
    bindings_attention: BindingAttention
    #: Per slot, who answers now: the active plugins and the core's own data.
    capabilities: list[CapabilityView]
    #: The reference set the stored estimates match, and what is still moving;
    #: a new `last_change_id` refetches every pay surface.
    reference: ReferenceView
    #: Plugin jobs running now; Sync shows done only when this is 0 and
    #: `reference.pending_jobs` is too.
    plugins_running: int
    #: The matching model's background job: its weights downloading, or the
    #: corpus re-embedding onto it; `none` when neither runs.
    matching_switch: Literal["downloading", "converting", "none"] = Field(default="none", json_schema_extra=text("code"))
    #: Every supervised job: what it is doing, or why it waits.
    jobs: list[JobView] = Field(default_factory=list)
    supervisor: SupervisorView = Field(default_factory=lambda: SupervisorView(state="absent", since=None))


# --------------------------------------------------------------------------- #
# /api/runs
# --------------------------------------------------------------------------- #


class RunRow(Built):
    """One scrape run. `per_source` maps a company to its stored source record."""

    id: int
    started_at: datetime
    finished_at: datetime | None
    status: str
    jobs_seen: int
    jobs_new: int
    jobs_closed: int
    per_source: dict[str, dict[str, Any]]
    drift_alerts: list[dict[str, Any]]
    notes: str | None = Field(json_schema_extra=text("diagnostic"))


class RunListResponse(Built):
    """`GET /api/runs`: the newest runs first."""

    items: list[RunRow]


# --------------------------------------------------------------------------- #
# /api/sync, /api/sync/targets, /api/sync/cancel
# --------------------------------------------------------------------------- #


class SyncStarted(Built):
    """Reconciliation queued and one dispatcher pass started. `companies` echoes
    the requested subset (empty = the roster); `queued` is what was queued."""

    status: Literal["started"]
    companies: list[str]
    queued: list[str]


class SyncAlreadyRunning(Built):
    """A run was already live, so nothing was spawned. `companies` is empty:
    the live run was not scoped by this request. `queued` is what the request
    asked for by name: the live run reads each next, or the scan after it does."""

    status: Literal["already_running"]
    run_id: int
    started_at: datetime
    companies: list[str]
    queued: list[str] = []


class SyncResponse(RootModel[Annotated[SyncStarted | SyncAlreadyRunning, Field(discriminator="status")]]):
    """`POST /api/sync`: work queued and a dispatcher started, or attached to
    the run already live."""


class SyncTargetCoverage(Built):
    """Why a followed company has not been scanned in full lately, for its row
    on Settings > Companies. The same facts as
    `/api/status.bindings_attention`, keyed by company; absent (`null`) when
    it was scanned in full within `coverage_stale_after_days` and its board lists roles.

    `rings` is the Coverage notification's own decision
    (`notifications/coverage.py::rings`), and `title` / `body` are that
    notification's words (`events.classify_coverage`), so the bell and the row
    cannot disagree about whether a company is broken or say it differently.
    `say` is that notification's words as catalog keys, which the client says
    in the reader's language; `title` / `body` are its English."""

    cause: Cause
    held_open: int
    days_since_full_scan: float | None
    rings: bool
    title: str = Field(json_schema_extra=text("record"))
    body: str = Field(json_schema_extra=text("record"))
    say: NotificationSay


class SyncTarget(Built):
    """One company a targeted sync may cover. `last_sync_at` is the last
    attempt, not the last success; `last_full_scan_at` the last scan that read
    the whole board; `last_outcome` and `retryable` come from the
    newest full run that recorded sources, and are null / false for a company
    that run never touched."""

    slug: str
    display: str = Field(json_schema_extra=text("content"))
    adapter: str
    last_sync_at: datetime | None
    age_hours: float | None
    stale: bool
    last_full_scan_at: datetime | None
    automatic: bool
    last_outcome: SourceOutcome | None
    retryable: bool
    coverage: SyncTargetCoverage | None


class SyncTargetsResponse(Built):
    """`GET /api/sync/targets`: the scrapeable roster, by slug."""

    companies: list[SyncTarget]
    freshness_max_hours: int


class SyncNotCancelled(Built):
    """No manual process to stop and nothing queued. `pid` is a recorded PID
    that turned out not to be a sync, when there was one."""

    status: Literal["not_running", "error"]
    pid: int | None
    dequeued: list[str]


class SyncCancelled(Built):
    """A manual process was stopped, queued manual work was dequeued, or both.
    `run_id` is the live run executing in the stopped process's group, now marked
    `error`; null when no process was signalled or it had no live run."""

    status: Literal["cancelled"]
    pid: int | None
    run_id: int | None
    dequeued: list[str]


class SyncCancelResponse(RootModel[Annotated[SyncNotCancelled | SyncCancelled, Field(discriminator="status")]]):
    """`POST /api/sync/cancel`: nothing to stop, or what was stopped."""


# --------------------------------------------------------------------------- #
# /api/schedule
# --------------------------------------------------------------------------- #

#: A minute of the local day, as `sync_schedule_state`'s CHECK constraints bound it.
AnchorMinute = Annotated[int, Field(ge=0, le=1439)]


class ScheduleProviderPayload(Built):
    """One provider the scheduled roster uses. `state` is the stored pressure
    state (`ready` when the provider has no row) or `policy_denied` when
    settings refuse it, whatever is stored."""

    provider: str
    state: str
    cooldown_until: datetime | None
    last_started_at: datetime | None
    last_finished_at: datetime | None
    last_outcome: str | None
    binding_count: int


class ScheduleBindingPayload(Built):
    """One stable binding of an enabled company, with its persisted deadlines.

    An `unscheduled` binding has no schedule row: its cadences, deadlines and
    anchors are null, its counters 0. `eligible_*_at` is the deadline pushed
    past a provider cooldown, and null where nothing may run: no row, discovery
    off, or the provider paused or denied. `status` takes the first that holds
    of `policy_denied`/`paused`, `cooldown`, `manual`, `scheduled`."""

    binding_id: int
    company: str
    provider: str
    closure_capability: str
    scheduled: bool
    discovery_enabled: bool
    discovery_cadence_seconds: int | None
    reconcile_cadence_seconds: int | None
    last_discovery_at: datetime | None
    last_reconcile_at: datetime | None
    next_discovery_at: datetime | None
    next_reconcile_at: datetime | None
    discovery_anchor_minute: AnchorMinute | None
    reconcile_anchor_minute: AnchorMinute | None
    schedule_timezone: str | None
    eligible_discovery_at: datetime | None
    eligible_reconcile_at: datetime | None
    manual_requested_at: datetime | None
    last_outcome: str | None
    last_new_count: int
    consecutive_empty_discoveries: int
    provider_state: str
    cooldown_until: datetime | None
    status: Literal["scheduled", "manual", "cooldown", "paused", "policy_denied", "unscheduled"]
    #: Why no automatic scan collects this company, or null if one may
    #: (`schedule_status.waits_for_user`, the scheduler's own rule): `walled`
    #: (no consent) or `user_directed` (only a scan the user starts).
    waits_for_user: Literal["walled", "user_directed"] | None


class ScheduleWindow(Built):
    """One usually-on window, in minutes of the local day; `end_minute` may be
    1440 (midnight)."""

    start_minute: Annotated[int, Field(ge=0, le=1440)]
    end_minute: Annotated[int, Field(ge=0, le=1440)]


class ScheduleUsualHours(Built):
    """When the computer is usually on, learned from scheduler ticks.

    `learning` until `observed_days` reaches `needed_days`; the windows are null
    then, and null for a day class (weekdays, weekends) never observed. `today`
    is the windows for today's date in `timezone`. `on_now`: a tick saw the
    machine awake within the last half hour."""

    timezone: str
    observed_days: int
    needed_days: int
    learning: bool
    today: list[ScheduleWindow] | None
    weekdays: list[ScheduleWindow] | None
    weekends: list[ScheduleWindow] | None
    on_now: bool


class SchedulePlanLastRun(Built):
    """The newest run that holds the plan's clock. `manual` = a Scan now that
    read the whole roster, which counts as a full read."""

    kind: Literal["full", "quick"]
    manual: bool
    started_at: datetime
    finished_at: datetime | None
    companies: int
    outcome: str | None


class ScheduleUpcomingRun(Built):
    """One projected plan run. `seconds` is the median of measured runs of the
    kind, or the built-in guess while `estimated`. `on_wake`: the repeat falls
    when the computer is usually off, so it is drawn at the next usual start.
    `running`: in progress now, `at` is when it began. `ready_by`: the day's
    full scan, started to be finished by the ready-by time."""

    at: datetime
    kind: Literal["full", "quick"]
    seconds: int
    estimated: bool
    on_wake: bool
    running: bool
    ready_by: bool


class ScheduleReadyBy(Built):
    """Today's ready-by time: the user's own (`set`) or the usual start the plan
    learned (`usual`)."""

    minute: AnchorMinute
    source: Literal["set", "usual"]


class SchedulePlanPayload(Built):
    """The schedule plan: a full read when the computer comes on and
    a quick check every `repeat_hours` while it is on. `roster` = companies a
    full read takes, `quick_roster` = those a quick check takes, `pinned` =
    companies that keep a time the user set."""

    enabled: bool
    repeat_hours: int
    #: Quick scans at fixed clock times from this local minute (null = a
    #: repeat after the last scan).
    repeat_anchor_minute: AnchorMinute | None
    repeat_choices: list[int]
    full_after_hours: int
    roster: int
    quick_roster: int
    pinned: int
    #: The user's ready-by minute (null = by the usual start), today's
    #: effective one, the scan days (Monday = 0), an active pause, mains only,
    #: and why nothing planned runs right now (`paused`, `day_off`, `mains`).
    ready_by_minute: AnchorMinute | None
    ready_by_today: ScheduleReadyBy | None
    days: list[Annotated[int, Field(ge=0, le=6)]]
    paused_until: datetime | None
    mains_only: bool
    waiting: Literal["paused", "day_off", "mains"] | None
    last_run: SchedulePlanLastRun | None
    last_full_at: datetime | None
    upcoming: list[ScheduleUpcomingRun]
    usual: ScheduleUsualHours


class SchedulePayload(Built):
    """`GET /api/schedule`, and `PATCH /api/schedule/{binding_id}` after the
    move: the dispatcher settings, bindings by company, providers by key, and
    the schedule plan."""

    generated_at: datetime
    enabled: bool
    tick_seconds: int
    max_parallel_providers: int
    authoritative_stale_hours: int
    bindings: list[ScheduleBindingPayload]
    providers: list[ScheduleProviderPayload]
    plan: SchedulePlanPayload


class SchedulePlanUpdate(BaseModel):
    """`PUT /api/schedule/plan` body: only the keys sent change.

    `ready_by_minute: null` clears the user's own time (back to the usual
    start); `repeat_anchor_minute: null` puts the quick scans back on a repeat
    after the last scan. `pause`: `1h`, `3h`, `tomorrow` (the next usual start, 08:00 while
    learning) or `resume`. `days`: at least one weekday, Monday = 0."""

    model_config = ConfigDict(extra="forbid")

    repeat_hours: Literal[2, 3, 6, 12] | None = None
    repeat_anchor_minute: AnchorMinute | None = None
    ready_by_minute: AnchorMinute | None = None
    days: list[Annotated[int, Field(ge=0, le=6)]] | None = Field(default=None, min_length=1)
    pause: Literal["1h", "3h", "tomorrow", "resume"] | None = None
    mains_only: bool | None = None


class ScheduleTimeUpdate(BaseModel):
    """`PATCH /api/schedule/{binding_id}` body: anchor one deadline to a
    wall-clock minute in `timezone`. An unknown zone is a 422 from the route."""

    mode: Literal["discovery", "reconcile"]
    local_minute: AnchorMinute
    timezone: str = Field(min_length=1, max_length=64)
