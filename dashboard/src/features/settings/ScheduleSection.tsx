import { timestamp as copyTimestamp, date, list, weekday } from "../../copy/format";
import { useMemo, useState } from "react";
import { Content } from "../../ui/Content";
import type { SchedulePlan, SchedulePlanUpdate, ScheduleBinding, ScheduleUpcomingRun, SyncSchedule } from "../../api";
import { api } from "../../api";
import { errorText } from "../../api/errorText";
import { companyName, formatWhen } from "../../format";
import { useAsyncResource } from "../../hooks/useAsyncResource";
import { useWriteQueue } from "../../hooks/useWriteQueue";
import { AsyncBoundary, Badge, FilterChip, Icon, InfoTip, Popover, Segmented, Sheet, Switch } from "../../ui";
import { InspectorTime } from "./InspectorTime";
import { startForReadyBy } from "./usePlanDrag";
import { ScheduleChronograph } from "./ScheduleChronograph";
import { durationText, hasUsualStart, learnedSentence } from "./charts/plan";
import {
  eventFilterFor,
  formatMinute,
  reconciliationWindow,
  scheduleChartSummary,
  scheduleClusters,
  stackText,
} from "./charts/schedule";
import "./ScheduleSection.css";
import { Button } from "../../ui/Button";
import {
  settingsChronographDialAuthoritativeCycle,
  settingsChronographDialFullScan,
  settingsChronographDialQuickScan,
  settingsChronographInspectorScheduled,
  settingsPlanRunInspectorFullScanDoneBy,
  settingsPlanRunInspectorQuickScanEvery,
  settingsCompany,
  settingsScheduleSection1Hour,
  settingsScheduleSection3Hours,
  settingsScheduleSectionACompanyWithATime,
  settingsScheduleSectionAFullScanReadsA,
  settingsScheduleSectionAQuickScanEveryHours,
  settingsScheduleSectionAdaptsTo81224h,
  settingsScheduleSectionAfterTwoHoursOrMore,
  settingsScheduleSectionAllPersistedDeadlines2,
  settingsScheduleSectionBindingsProjectedThrough,
  settingsScheduleSectionClearReadyBy,
  settingsScheduleSectionCompanies,
  settingsScheduleSectionCompaniesKeepATimeYou,
  settingsScheduleSectionCoolingDown,
  settingsScheduleSectionCoolingDownUntil,
  settingsScheduleSectionCouldnTSaveThatChange,
  settingsScheduleSectionDays,
  settingsScheduleSectionDaysAWeek,
  settingsScheduleSectionDeadlinesLink,
  settingsScheduleSectionDiscovery,
  settingsScheduleSectionDiscoveryCadence,
  settingsScheduleSectionDiscoveryCanAddOrUpdate,
  settingsScheduleSectionDragAMarkAroundThe,
  settingsScheduleSectionEditing,
  settingsScheduleSectionEmpty,
  settingsScheduleSectionEvery,
  settingsScheduleSectionEveryCompanySScans,
  settingsScheduleSectionEveryCompanySScans2,
  settingsScheduleSectionFirstScanOfTheDay,
  settingsScheduleSectionFullScanAt,
  settingsScheduleSectionFullScanDoneBy,
  settingsScheduleSectionHowItIsScanned,
  settingsScheduleSectionHowScanningWorks,
  settingsScheduleSectionHowScanningWorks2,
  settingsScheduleSectionHowScanningWorks3,
  settingsScheduleSectionHowSchedulingSafetyWorks,
  settingsScheduleSectionItsOwnTime,
  settingsScheduleSectionLastFullScan,
  settingsScheduleSectionLastQuickScan,
  settingsScheduleSectionLoadFailed,
  settingsScheduleSectionLoading,
  settingsScheduleSectionLooksForNewAndChanged,
  settingsScheduleSectionManualPriority,
  settingsScheduleSectionMarksComingDueTogetherDispatch,
  settingsScheduleSectionMax,
  settingsScheduleSectionMoreSeeAllDeadlines,
  settingsScheduleSectionNeedAttention,
  settingsScheduleSectionNeedsYourOk,
  settingsScheduleSectionNextScans,
  settingsScheduleSectionNextScans2,
  settingsScheduleSectionNoTimeSet,
  settingsScheduleSectionNoTimeSetDuration,
  settingsScheduleSectionNonAuthoritative,
  settingsScheduleSectionNotAvailable,
  settingsScheduleSectionNotScheduled,
  settingsScheduleSectionNotYet,
  settingsScheduleSectionNothingRunsAndMissedScans,
  settingsScheduleSectionNow,
  settingsScheduleSectionOneBindingPerProviderIn,
  settingsScheduleSectionOnlyAfterYouAllowIt,
  settingsScheduleSectionOnlyThisCycleCanClose,
  settingsScheduleSectionOnlyWhenPluggedIn,
  settingsScheduleSectionOnlyWhenYouPressScan,
  settingsScheduleSectionOnlyWhenYouScan,
  settingsScheduleSectionOuterOrbitIsReconciliationInner,
  settingsScheduleSectionOuterOrbitIsTheFull,
  settingsScheduleSectionPassProvider,
  settingsScheduleSectionPause,
  settingsScheduleSectionPauseScans,
  settingsScheduleSectionPaused,
  settingsScheduleSectionPausedUntil,
  settingsScheduleSectionPersistedDeadlines,
  settingsScheduleSectionPlanRoster,
  settingsScheduleSectionPlanRosterExcepted,
  settingsScheduleSectionPlanRosterPinned,
  settingsScheduleSectionPlanRosterPinnedExcepted,
  settingsScheduleSectionPlanSettings,
  settingsScheduleSectionPlannedScans,
  settingsScheduleSectionPolicyDenied,
  settingsScheduleSectionPower,
  settingsScheduleSectionPowerNote,
  settingsScheduleSectionProbesACompanySBoard,
  settingsScheduleSectionProviderPolicyDeniesScheduledCollection,
  settingsScheduleSectionProviderPressure,
  settingsScheduleSectionProviderSchedulingIsPaused,
  settingsScheduleSectionProviderState,
  settingsScheduleSectionQuickScanAt,
  settingsScheduleSectionReadsEveryCompanySWhole,
  settingsScheduleSectionReconciliation,
  settingsScheduleSectionReconciliationOnly,
  settingsScheduleSectionResume,
  settingsScheduleSectionRunTitle,
  settingsScheduleSectionScanAtATimeYouSet,
  settingsScheduleSectionScanClock,
  settingsScheduleSectionScanDays,
  settingsScheduleSectionSettingScanTimes,
  settingsScheduleSectionSchedule,
  settingsScheduleSectionSchedulerPolicy,
  settingsScheduleSectionStartsAbout,
  settingsScheduleSectionStartsAboutDuration,
  settingsScheduleSectionTheAuthoritativeCycleOnlyThis,
  settingsScheduleSectionTheCycle,
  settingsScheduleSectionThenWhileItIsOn,
  settingsScheduleSectionTimersRoster,
  settingsScheduleSectionTimersRosterExcepted,
  settingsScheduleSectionTimersRosterExceptedReconcileOnly,
  settingsScheduleSectionTimersRosterReconcileOnly,
  settingsScheduleSectionTimesYouSet,
  settingsScheduleSectionTimesYouSet2,
  settingsScheduleSectionTitleDueNow,
  settingsScheduleSectionUnscheduled,
  settingsScheduleSectionUntil,
  settingsScheduleSectionUntilTomorrow,
  settingsScheduleSectionUpcoming,
  settingsScheduleSectionUpcomingScans,
  settingsScheduleSectionWhatTheColumnsMean,
  settingsScheduleSectionWhenRolebandScans,
  settingsScheduleSectionWhenTheComputerIsOff,
  settingsScheduleHours,
  settingsScheduleDays,
} from "../../copy/gen/settings";
import { Msg } from "../../ui/Msg";

const AGENDA_LIMIT = 7;

const formatNext = (iso: string | null) => (iso ? formatWhen(iso) : settingsScheduleSectionNotScheduled());

const formatTime = (iso: string) =>
  copyTimestamp(new Date(iso), {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });

const formatDay = (iso: string) => date(iso, "weekday");

const formatCadence = (seconds: number | null) => {
  if (!seconds) return "—";
  const hours = seconds / 3600;
  return hours <= 24 ? settingsScheduleHours({ hours }) : settingsScheduleDays({ days: hours / 24 });
};

const bindingTone = (binding: ScheduleBinding) =>
  binding.status === "scheduled" && binding.waits_for_user ? "neutral" as const : toneFor(binding.status);

const bindingIcon = (binding: ScheduleBinding) =>
  binding.status === "scheduled" && binding.waits_for_user ? "person" as const : statusIcon(binding.status);

/** How the plan scans one company, in the sheet. Null when the
    status badge already says it (a provider paused, denied or cooling down). */
const planScanText = (binding: ScheduleBinding): string | null => {
  if (!["scheduled", "manual"].includes(binding.status)) return null;
  if (binding.waits_for_user === "user_directed") return settingsScheduleSectionOnlyWhenYouPressScan();
  if (binding.waits_for_user === "walled") return settingsScheduleSectionOnlyAfterYouAllowIt();
  const own = [
    binding.reconcile_anchor_minute !== null ? settingsScheduleSectionFullScanAt({ reconcile_anchor_minute: String(formatMinute(binding.reconcile_anchor_minute)) }) : null,
    binding.discovery_anchor_minute !== null ? settingsScheduleSectionQuickScanAt({ discovery_anchor_minute: String(formatMinute(binding.discovery_anchor_minute)) }) : null,
  ].filter((text): text is string => text !== null);
  if (own.length > 0) return settingsScheduleSectionItsOwnTime({ times: list(own) });
  return settingsScheduleSectionPlannedScans({ scans: binding.discovery_enabled ? "all" : "full" });
};

/** The line under the dial with the plan on: every company, how many each
    full scan reads, then the companies at a time you set and the ones that
    need attention, each only when there are some. */
const planRosterText = (companies: number, roster: number, pinned: number, excepted: number) => {
  if (pinned > 0 && excepted > 0) {
    return settingsScheduleSectionPlanRosterPinnedExcepted({ companies, roster, pinned, excepted });
  }
  if (pinned > 0) return settingsScheduleSectionPlanRosterPinned({ companies, roster, pinned });
  if (excepted > 0) return settingsScheduleSectionPlanRosterExcepted({ companies, roster, excepted });
  return settingsScheduleSectionPlanRoster({ companies, roster });
};

/** The same line under the per-company timers: every company, how many are
    scheduled, then the ones that need attention and the ones with no
    discovery pass, each only when there are some. */
const timersRosterText = (companies: number, scheduled: number, excepted: number, reconcileOnly: number) => {
  if (excepted > 0 && reconcileOnly > 0) {
    return settingsScheduleSectionTimersRosterExceptedReconcileOnly({ companies, scheduled, excepted, reconcileOnly });
  }
  if (excepted > 0) return settingsScheduleSectionTimersRosterExcepted({ companies, scheduled, excepted });
  if (reconcileOnly > 0) return settingsScheduleSectionTimersRosterReconcileOnly({ companies, scheduled, reconcileOnly });
  return settingsScheduleSectionTimersRoster({ companies, scheduled });
};

/** The authoritative cycle's row title: a cycle of one deadline is that
    company's, so it carries the company's name. */
const cycleTitle = (count: number, only: { company: string } | null) =>
  count === 1 && only ? companyName(only.company) : settingsChronographDialAuthoritativeCycle();

/** The line under the full scan's done-by time: when it starts and over how
    many companies, or that no time is set, and how long it takes once a full
    scan is planned. */
const readyByText = (plan: SchedulePlan, full: ScheduleUpcomingRun | undefined) => {
  const ready = plan.ready_by_today;
  const companies = plan.roster;
  if (!ready) {
    return full
      ? settingsScheduleSectionNoTimeSetDuration({ companies, duration: durationText(full) })
      : settingsScheduleSectionNoTimeSet({ companies });
  }
  const time = formatMinute(startForReadyBy(ready.minute, full?.seconds ?? 2700));
  return full
    ? settingsScheduleSectionStartsAboutDuration({ source: ready.source, time, companies, duration: durationText(full) })
    : settingsScheduleSectionStartsAbout({ source: ready.source, time, companies });
};

const toneFor = (status: ScheduleBinding["status"]) => {
  if (status === "policy_denied" || status === "paused") return "danger" as const;
  if (status === "cooldown" || status === "unscheduled") return "warning" as const;
  if (status === "manual") return "accent" as const;
  return "success" as const;
};

const statusIcon = (status: ScheduleBinding["status"]) => {
  if (status === "policy_denied") return "alert";
  if (status === "paused") return "pause";
  if (status === "cooldown") return "clock";
  if (status === "unscheduled") return "eyeOff";
  if (status === "manual") return "pin";
  return "check";
};

const statusLabel = (binding: ScheduleBinding) => {
  // The scheduler's own reason: a company no timer takes is not
  // "Scheduled", whatever its row says.
  if (binding.status === "scheduled" && binding.waits_for_user === "user_directed") {
    return settingsScheduleSectionOnlyWhenYouScan();
  }
  if (binding.status === "scheduled" && binding.waits_for_user === "walled") return settingsScheduleSectionNeedsYourOk();
  if (binding.status === "policy_denied") return settingsScheduleSectionPolicyDenied();
  if (binding.status === "cooldown") return settingsScheduleSectionCoolingDown();
  if (binding.status === "unscheduled") return settingsScheduleSectionUnscheduled();
  if (binding.status === "manual") return settingsScheduleSectionManualPriority();
  if (binding.status === "paused") return settingsScheduleSectionPaused();
  return settingsChronographInspectorScheduled();
};

const exceptionText = (binding: ScheduleBinding) => {
  if (binding.status === "policy_denied") return settingsScheduleSectionProviderPolicyDeniesScheduledCollection();
  if (binding.status === "paused") return settingsScheduleSectionProviderSchedulingIsPaused();
  if (binding.status === "cooldown" && binding.cooldown_until) {
    return settingsScheduleSectionCoolingDownUntil({ cooldown_until: String(formatTime(binding.cooldown_until)) });
  }
  return null;
};

// Everything explanatory lives here rather than in the dial the user opens
// daily: the two pass definitions, how the cycle serializes, and how to edit.
function ScheduleHelp({ maxParallel, plan }: { maxParallel: number; plan: SchedulePlan | null }) {
  const [open, setOpen] = useState(false);
  const [anchor, setAnchor] = useState<HTMLButtonElement | null>(null);

  return (
    <>
      <Button
        type="button"
        ref={setAnchor}
        variant="icon"
        size="sm"
        aria-label={settingsScheduleSectionHowScanningWorks2()}
        aria-expanded={open}
        onClick={() => setOpen((current) => !current)}
      >
        <Icon name="help" size={16} />
      </Button>
      <Popover
        isOpen={open}
        onClose={() => setOpen(false)}
        anchor={anchor}
        align="end"
        label={settingsScheduleSectionHowScanningWorks3()}
        className="schedule-help app-overlay"
      >
        <h3>{settingsScheduleSectionHowScanningWorks()}</h3>
        {plan ? (
          <>
            <dl>
              <dt className="reconcile">{settingsChronographDialFullScan()}</dt>
              <dd>
                {settingsScheduleSectionReadsEveryCompanySWhole()}
              </dd>
              <dt className="discovery">{settingsChronographDialQuickScan()}</dt>
              <dd>
                <Msg of={settingsScheduleSectionLooksForNewAndChanged} elems={{ repeat_hours: plan.repeat_hours }} />
              </dd>
              <dt>{settingsScheduleSectionWhenTheComputerIsOff()}</dt>
              <dd>
                {settingsScheduleSectionNothingRunsAndMissedScans()}
              </dd>
              <dt>{settingsScheduleSectionTimesYouSet()}</dt>
              <dd>
                {settingsScheduleSectionACompanyWithATime()}
              </dd>
            </dl>
            <p>
              {settingsScheduleSectionOuterOrbitIsTheFull()}
            </p>
          </>
        ) : (
          <>
            <dl>
              <dt className="discovery">{settingsScheduleSectionDiscovery()}</dt>
              <dd>
                {settingsScheduleSectionProbesACompanySBoard()}
              </dd>
              <dt className="reconcile">{settingsScheduleSectionReconciliation()}</dt>
              <dd>
                {settingsScheduleSectionTheAuthoritativeCycleOnlyThis()}
              </dd>
              <dt>{settingsScheduleSectionTheCycle()}</dt>
              <dd>
                <Msg of={settingsScheduleSectionMarksComingDueTogetherDispatch} elems={{ maxParallel: maxParallel }} />
              </dd>
              <dt>{settingsScheduleSectionEditing()}</dt>
              <dd>
                {settingsScheduleSectionDragAMarkAroundThe()}
              </dd>
            </dl>
            <p>
              {settingsScheduleSectionOuterOrbitIsReconciliationInner()}
            </p>
          </>
        )}
      </Popover>
    </>
  );
}

// One deadline, stacked: the clock time carries the row (it is what differs
// between bindings), the day sits under it, and the cadence is a single token
// rather than a sentence — the column header already names which pass it is.
// A binding with no deadline has no cadence to advertise either.
function DeadlineCell({ at, cadenceSeconds }: { at: string | null; cadenceSeconds: number | null }) {
  if (!at) return <span className="muted">{formatNext(at)}</span>;
  const cadence = formatCadence(cadenceSeconds);
  return (
    <span className="schedule-ledger-when">
      <b>
        {formatTime(at)}
        {cadence !== "—" && (
          <em className="schedule-ledger-every" role="img" aria-label={settingsScheduleSectionEvery({ cadence: String(cadence) })}>{cadence}</em>
        )}
      </b>
      <small>{formatDay(at)}</small>
    </span>
  );
}

type RepeatHours = 2 | 3 | 6 | 12;

/* The plan's settings, in the column beside the dial: when the computer is usually on (learned,
   never asked), what the first scan is and when it should be done by, how often
   it repeats, which days it runs, whether it waits for mains power, a pause, and
   what happens to a scan the computer was off for. Each control saves one key,
   and every one waits while any schedule write is out (`busy`). */
const WEEKDAYS = [0, 1, 2, 3, 4, 5, 6] as const;
const PAUSES = [
  { value: "1h", get label() { return settingsScheduleSection1Hour(); } },
  { value: "3h", get label() { return settingsScheduleSection3Hours(); } },
  { value: "tomorrow", get label() { return settingsScheduleSectionUntilTomorrow(); } },
] as const;

function PlanSettings({
  plan,
  busy,
  onPlan,
}: {
  plan: SchedulePlan;
  busy: boolean;
  onPlan: (update: SchedulePlanUpdate) => Promise<void>;
}) {
  const [error, setError] = useState<string | null>(null);
  const choices = plan.repeat_choices.filter(
    (hours): hours is RepeatHours => [2, 3, 6, 12].includes(hours),
  );
  const full = plan.upcoming.find((run) => run.kind === "full");
  const save = (update: SchedulePlanUpdate) => {
    setError(null);
    return onPlan(update)
      .catch((caught) => setError(errorText(caught, settingsScheduleSectionCouldnTSaveThatChange())));
  };
  const ready = plan.ready_by_today;
  const days = new Set(plan.days);

  return (
    <>
    <dl className="schedule-plan-settings" aria-label={settingsScheduleSectionPlanSettings()}>
      {/* One row, one control: the learned hours are a fact, not a setting,
          so they are in the note at the end; what they decide (the default
          done-by time) is said here. */}
      <div>
        <dt>{settingsScheduleSectionFirstScanOfTheDay()}</dt>
        <dd>
          {/* The field is named by its own aria-label ("Full scan done by");
              the visible words beside it read as the same sentence. */}
          <div className="schedule-plan-ready">
            <span aria-hidden="true">{settingsScheduleSectionFullScanDoneBy()}</span>
            <InspectorTime
              label={settingsPlanRunInspectorFullScanDoneBy()}
              minute={ready?.minute ?? null}
              step={600}
              locked={false}
              saving={busy}
              onCommit={(minute) => void save({ ready_by_minute: minute })}
            />
          </div>
          <small>{readyByText(plan, full)}</small>
          {plan.ready_by_minute !== null && (
            <Button variant="link" disabled={busy} onClick={() => void save({ ready_by_minute: null })}>
              {settingsScheduleSectionClearReadyBy({ fallback: hasUsualStart(plan) ? "usual" : "none" })}
            </Button>
          )}
        </dd>
      </div>
      <div>
        <dt>{settingsScheduleSectionThenWhileItIsOn()}</dt>
        <dd>
          <Segmented
            label={settingsPlanRunInspectorQuickScanEvery()}
            value={String(plan.repeat_hours)}
            options={choices.map((hours) => ({
              value: String(hours),
              label: settingsScheduleHours({ hours }),
              disabled: busy,
            }))}
            onChange={(value) => void save({ repeat_hours: Number(value) as RepeatHours })}
          />
          <small><Msg of={settingsScheduleSectionAQuickScanEveryHours} elems={{ repeat_hours: plan.repeat_hours }} /></small>
        </dd>
      </div>
      <div>
        <dt>{settingsScheduleSectionDays()}</dt>
        <dd>
          <div className="schedule-plan-days" role="group" aria-label={settingsScheduleSectionScanDays()}>
            {WEEKDAYS.map((day) => (
              <FilterChip
                key={day}
                selected={days.has(day)}
                aria-pressed={days.has(day)}
                // The last day cannot be switched off: a plan with no days is
                // no plan, and the server refuses it.
                disabled={busy || (days.has(day) && days.size === 1)}
                onClick={() => {
                  const next = new Set(days);
                  if (next.has(day)) next.delete(day);
                  else next.add(day);
                  void save({ days: [...next].sort() });
                }}
              >
                {weekday(day)}
              </FilterChip>
            ))}
          </div>
          <small>{settingsScheduleSectionDaysAWeek({ count: days.size })}</small>
        </dd>
      </div>
      <div>
        <dt>{settingsScheduleSectionPower()}</dt>
        <dd>
          <Switch
            checked={plan.mains_only}
            disabled={busy}
            onChange={(next) => void save({ mains_only: next })}
          >
            {settingsScheduleSectionOnlyWhenPluggedIn()}
          </Switch>
          <small>
            {settingsScheduleSectionPowerNote({ power: plan.waiting === "mains" ? "waiting" : plan.mains_only ? "mains" : "any" })}
          </small>
        </dd>
      </div>
      <div>
        <dt>{settingsScheduleSectionPause()}</dt>
        <dd>
          {plan.paused_until ? (
            <div className="schedule-plan-pause">
              <span>{settingsScheduleSectionPausedUntil()} <b>{formatWhen(plan.paused_until)}</b></span>
              <Button variant="ghost" size="sm" disabled={busy} onClick={() => void save({ pause: "resume" })}>
                {settingsScheduleSectionResume()}
              </Button>
            </div>
          ) : (
            <div className="schedule-plan-pause" role="group" aria-label={settingsScheduleSectionPauseScans()}>
              {PAUSES.map((pause) => (
                <Button
                  key={pause.value}
                  variant="ghost"
                  size="sm"
                  disabled={busy}
                  onClick={() => void save({ pause: pause.value })}
                >
                  {pause.label}
                </Button>
              ))}
            </div>
          )}
        </dd>
      </div>
    </dl>
    {error && <p className="schedule-plan-error" role="alert">{error}</p>}
    <p className="schedule-plan-learned">
      <Msg of={settingsScheduleSectionAfterTwoHoursOrMore} elems={{ learned: learnedSentence(plan) }} />
    </p>
    </>
  );
}

/** How many of the plan's runs the column lists: enough to see the day's
    rhythm, few enough that the settings above stay the point of the column. */
const PLAN_RUN_LIMIT = 4;

function ScheduleStudio({
  schedule,
  busy,
  onMove,
  onPlan,
}: {
  schedule: SyncSchedule;
  /** A schedule write is out, from any control on the screen. */
  busy: boolean;
  onMove: (move: {
    bindingId: number;
    mode: "discovery" | "reconcile";
    localMinute: number;
    timezone: string;
  }) => Promise<void>;
  onPlan: (update: SchedulePlanUpdate) => Promise<void>;
}) {
  const [deadlinesOpen, setDeadlinesOpen] = useState(false);
  // Under the plan the dial's company marks are the deadlines the
  // user pinned, and there is no authoritative cycle: the planned full scan is
  // the cycle, drawn as the run it is.
  const plan = schedule.plan.enabled ? schedule.plan : null;
  const clusters = useMemo(() => scheduleClusters(schedule, eventFilterFor(schedule)), [schedule]);
  const cycle = useMemo(() => (plan ? null : reconciliationWindow(schedule)), [plan, schedule]);
  const summary = scheduleChartSummary(schedule);

  const active = schedule.bindings.filter((binding) =>
    ["scheduled", "manual", "cooldown"].includes(binding.status),
  );
  const discoveryCadence = active
    .filter((binding) => binding.discovery_enabled && binding.discovery_cadence_seconds)
    .map((binding) => binding.discovery_cadence_seconds as number)
    .sort((a, b) => a - b)[0] ?? null;
  const reconcileCadence = active
    .map((binding) => binding.reconcile_cadence_seconds)
    .filter((cadence): cadence is number => cadence !== null)
    .sort((a, b) => a - b)[0] ?? null;
  const reconcileOnly = schedule.bindings.filter((binding) => !binding.discovery_enabled).length;
  const exceptions = schedule.bindings
    .map((binding) => ({ binding, text: exceptionText(binding) }))
    .filter((entry): entry is { binding: ScheduleBinding; text: string } => entry.text !== null);
  // A company with no schedule row yet is new, not broken: the scheduler's next
  // run gives it one, so it is counted calmly rather than listed as a problem.
  const waiting = schedule.bindings.filter((binding) => binding.status === "unscheduled").length;

  const agenda = useMemo(() => {
    type CycleEvent = (typeof clusters)[number]["events"][number];
    const rows: Array<
      | {
        kind: "window"; at: string; count: number; end: string; overdue: boolean;
        /** The sole event, when the cycle holds exactly one. */
        only: CycleEvent | null;
      }
      | { kind: "cluster"; at: string; cluster: (typeof clusters)[number] }
    > = [];
    if (cycle) {
      const byId = new Map(clusters.flatMap((cluster) =>
        cluster.events.map((event) => [event.id, event] as const)));
      rows.push({
        kind: "window",
        at: cycle.start,
        count: cycle.count,
        end: cycle.end,
        overdue: Date.parse(cycle.start) <= Date.parse(schedule.generated_at),
        only: cycle.count === 1 ? byId.get(cycle.eventIds[0]) ?? null : null,
      });
    }
    // A reconciliation the authoritative-cycle row already covers must not also
    // appear as its own agenda row; ones dispatching later still get theirs.
    const cycleIds = new Set(cycle?.eventIds ?? []);
    for (const cluster of clusters) {
      if (cluster.mode === "reconcile"
        && cluster.events.every((event) => cycleIds.has(event.id))) continue;
      rows.push({ kind: "cluster", at: cluster.at, cluster });
    }
    return rows.sort((a, b) => Date.parse(a.at) - Date.parse(b.at));
  }, [clusters, cycle, schedule.generated_at]);

  const [pinnedOpen, setPinnedOpen] = useState(false);
  const waitingNote = waiting > 0 ? (
    <p className="schedule-waiting" role="status">{settingsScheduleSectionSettingScanTimes({ count: waiting })}</p>
  ) : null;
  const exceptionNote = exceptions.length > 0 ? (
    <div className="schedule-exceptions" role="note">
      <b>{settingsScheduleSectionNeedAttention({ count: exceptions.length })}</b>
      <span>
        {exceptions.map(({ binding, text }, i) => <span key={binding.company}>
          {i > 0 && " · "}<Content text={companyName(binding.company)} />{": "}{text}
        </span>)}
      </span>
    </div>
  ) : null;

  const localTimezone = Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
  const localDate = date(schedule.generated_at, "weekday");

  return (
    <>
      <div className="schedule-visual">
        <div className="schedule-visual-head">
          <h2>{settingsScheduleSectionScanClock()}</h2>
          <div className="schedule-head-aside">
            <span className="schedule-local-time">
              <Icon name="clock" size={18} />
              <Content text={localTimezone} /> · {localDate}
            </span>
            <ScheduleHelp maxParallel={schedule.max_parallel_providers} plan={plan} />
          </div>
        </div>

        <div className="schedule-clock-editor">
          <ScheduleChronograph
            schedule={schedule}
            clusters={clusters}
            window={cycle}
            summary={summary}
            busy={busy}
            onMove={onMove}
            onPlan={onPlan}
          />

          {plan ? (
            <aside className="schedule-clock-queue schedule-plan-panel" aria-label={settingsScheduleSectionWhenRolebandScans()}>
              {waitingNote}
              {exceptionNote}
              <PlanSettings plan={plan} busy={busy} onPlan={onPlan} />
              <div className="schedule-clock-queue-head">
                <span className="section-title">{settingsScheduleSectionNextScans()}</span>
              </div>
              <div className="schedule-upcoming-list" role="list" aria-label={settingsScheduleSectionNextScans2()}>
                {plan.upcoming.slice(0, PLAN_RUN_LIMIT).map((run, index) => (
                  <div
                    key={`plan-run-${index}`}
                    role="listitem"
                    className={`schedule-upcoming-row${run.kind === "full" ? " reconciliation" : ""}${index === 0 ? " next" : ""}`}
                  >
                    <time>
                      {run.running || Date.parse(run.at) <= Date.parse(schedule.generated_at)
                        ? settingsScheduleSectionNow()
                        : formatTime(run.at)}
                    </time>
                    <span className="schedule-upcoming-marker" aria-hidden="true" />
                    <span>
                      <strong>
                        {settingsScheduleSectionRunTitle({
                          state: run.running ? "running" : run.ready_by ? "ready" : run.on_wake ? "wake" : "planned",
                          kind: run.kind,
                          time: formatTime(new Date(Date.parse(run.at) + run.seconds * 1000).toISOString()),
                        })}
                      </strong>
                      <small>
                        {settingsScheduleSectionCompanies({
                          companies: run.kind === "full" ? plan.roster : plan.quick_roster,
                          duration: durationText(run),
                        })}
                      </small>
                    </span>
                  </div>
                ))}
              </div>
              {clusters.length > 0 && (
                <div className="schedule-plan-pinned">
                  <Button
                    variant="link"
                    aria-expanded={pinnedOpen}
                    onClick={() => setPinnedOpen((open) => !open)}
                  >
                    {settingsScheduleSectionCompaniesKeepATimeYou({ count: plan.pinned })}
                  </Button>
                  {pinnedOpen && (
                    <div className="schedule-upcoming-list" role="list" aria-label={settingsScheduleSectionTimesYouSet2()}>
                      {clusters.map((cluster) => (
                        <div
                          key={cluster.id}
                          role="listitem"
                          className={`schedule-upcoming-row${cluster.mode === "reconcile" ? " reconciliation" : ""}`}
                        >
                          <time>{formatTime(cluster.at)}</time>
                          <span className="schedule-upcoming-marker" aria-hidden="true" />
                          <span>
                            <strong>
                              {cluster.events.length > 1
                                ? stackText(cluster.events.length, cluster.mode, true)
                                : companyName(cluster.events[0].company)}
                            </strong>
                            <small>
                              {cluster.events.length > 1
                                ? <Content text={list(cluster.events.map((event) => companyName(event.company)))} />
                                : settingsScheduleSectionScanAtATimeYouSet({ mode: cluster.mode })}
                            </small>
                          </span>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )}
            </aside>
          ) : (
            <aside className="schedule-clock-queue" aria-label={settingsScheduleSectionUpcomingScans()}>
              {waitingNote}
              {exceptionNote}
              <div className="schedule-clock-queue-head">
                <h3 className="section-title">{settingsScheduleSectionUpcoming()}</h3>
              </div>
              <div className="schedule-upcoming-list">
                {agenda.slice(0, AGENDA_LIMIT).map((entry, index) => entry.kind === "window" ? (
                  <div
                    key="reconciliation-window"
                    className={`schedule-upcoming-row reconciliation${index === 0 ? " next" : ""}`}
                  >
                    <time>{entry.overdue ? settingsScheduleSectionNow() : formatTime(entry.at)}</time>
                    <span className="schedule-upcoming-marker" aria-hidden="true" />
                    <span>
                      {/* A one-binding cycle is that connector, and this row
                          replaces the one that would have named it — so name it
                          here rather than hiding a company behind an abstraction. */}
                      <strong>
                        {entry.overdue
                          ? settingsScheduleSectionTitleDueNow({ title: cycleTitle(entry.count, entry.only) })
                          : cycleTitle(entry.count, entry.only)}
                      </strong>
                      <small>
                        <Msg of={settingsScheduleSectionBindingsProjectedThrough} args={{ count: entry.count }} elems={{ end: formatTime(entry.end) }} />
                      </small>
                    </span>
                  </div>
                ) : (
                  <div
                    key={entry.cluster.id}
                    className={`schedule-upcoming-row${entry.cluster.mode === "reconcile" ? " reconciliation" : ""}${index === 0 ? " next" : ""}`}
                  >
                    <time>{formatTime(entry.at)}</time>
                    <span className="schedule-upcoming-marker" aria-hidden="true" />
                    <span>
                      <strong>
                        {entry.cluster.events.length > 1
                          ? stackText(entry.cluster.events.length, entry.cluster.mode, false)
                          : companyName(entry.cluster.events[0].company)}
                      </strong>
                      <small>
                        {entry.cluster.events.length > 1
                          ? <Content text={list(entry.cluster.events.map((event) => companyName(event.company)))} />
                          : settingsScheduleSectionPassProvider({ mode: entry.cluster.mode, provider: entry.cluster.events[0].provider })}
                      </small>
                    </span>
                  </div>
                ))}
                {agenda.length > AGENDA_LIMIT && (
                  <div className="schedule-upcoming-more">
                    {settingsScheduleSectionMoreSeeAllDeadlines({ count: agenda.length - AGENDA_LIMIT })}
                  </div>
                )}
              </div>
            </aside>
          )}
        </div>
      </div>

      {/* Under the plan its settings live in the column beside the dial. */}
      {!plan && (
        <div className="schedule-policy-strip" role="group" aria-label={settingsScheduleSectionSchedulerPolicy()}>
          <div>
            <span>{settingsScheduleSectionDiscoveryCadence()}</span>
            <b>{formatCadence(discoveryCadence)}</b>
            <small>{settingsScheduleSectionAdaptsTo81224h()}</small>
          </div>
          <div>
            <span>{settingsScheduleSectionReconciliation()}</span>
            <b>{formatCadence(reconcileCadence)}</b>
            <small>{settingsScheduleSectionOnlyThisCycleCanClose()}</small>
          </div>
          <div>
            <span>{settingsScheduleSectionProviderPressure()}</span>
            <b><Msg of={settingsScheduleSectionMax} elems={{ max_parallel_providers: schedule.max_parallel_providers }} /></b>
            <small>{settingsScheduleSectionOneBindingPerProviderIn()}</small>
          </div>
        </div>
      )}

      <div className="schedule-foot-line">
        <span>
          {plan
            ? planRosterText(schedule.bindings.length, plan.roster, plan.pinned, exceptions.length)
            : timersRosterText(schedule.bindings.length, active.length, exceptions.length, reconcileOnly)}
        </span>
        <Button variant="link" onClick={() => setDeadlinesOpen(true)}>
          {settingsScheduleSectionDeadlinesLink({ schedule: plan ? "plan" : "timers" })}
        </Button>
      </div>

      {plan ? (
        <Sheet
          isOpen={deadlinesOpen}
          onClose={() => setDeadlinesOpen(false)}
          label={settingsScheduleSectionEveryCompanySScans2()}
          className="schedule-deadlines-sheet app-overlay"
        >
          <div className="schedule-ledger-head">
            <h2>{settingsScheduleSectionEveryCompanySScans()}</h2>
            <InfoTip label={settingsScheduleSectionWhatTheColumnsMean()}>
              {settingsScheduleSectionAFullScanReadsA()}
            </InfoTip>
          </div>
          <div className="schedule-ledger">
            <table>
              <thead>
                <tr>
                  <th>{settingsCompany()}</th>
                  <th>{settingsScheduleSectionLastFullScan()}</th>
                  <th>{settingsScheduleSectionLastQuickScan()}</th>
                  <th>{settingsScheduleSectionHowItIsScanned()}</th>
                </tr>
              </thead>
              <tbody>
                {schedule.bindings.map((binding) => {
                  const how = planScanText(binding);
                  return (
                    <tr key={binding.binding_id}>
                      <td>
                        <strong>{companyName(binding.company)}</strong>
                        {binding.provider.toLowerCase() !== binding.company.toLowerCase() && (
                          <small>{binding.provider}</small>
                        )}
                      </td>
                      <td>
                        {binding.last_reconcile_at
                          ? formatWhen(binding.last_reconcile_at)
                          : <span className="muted">{settingsScheduleSectionNotYet()}</span>}
                      </td>
                      <td>
                        {!binding.discovery_enabled
                          ? <span className="muted">{settingsScheduleSectionNotAvailable()}</span>
                          : binding.last_discovery_at
                            ? formatWhen(binding.last_discovery_at)
                            : <span className="muted">{settingsScheduleSectionNotYet()}</span>}
                      </td>
                      <td>
                        {how ?? (
                          <Badge tone={bindingTone(binding)} variant="soft" size="sm">
                            <Icon name={bindingIcon(binding)} size={14} />
                            {statusLabel(binding)}
                          </Badge>
                        )}
                        {binding.cooldown_until && (
                          <small><Msg of={settingsScheduleSectionUntil} elems={{ cooldown_until: formatWhen(binding.cooldown_until) }} /></small>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </Sheet>
      ) : (
        <Sheet
          isOpen={deadlinesOpen}
          onClose={() => setDeadlinesOpen(false)}
          label={settingsScheduleSectionAllPersistedDeadlines2()}
          className="schedule-deadlines-sheet app-overlay"
        >
          <div className="schedule-ledger-head">
            <h2>{settingsScheduleSectionPersistedDeadlines()}</h2>
            <InfoTip label={settingsScheduleSectionHowSchedulingSafetyWorks()}>
              {settingsScheduleSectionDiscoveryCanAddOrUpdate()}
            </InfoTip>
          </div>
          <div className="schedule-ledger">
            <table>
              <thead>
                <tr>
                  <th>{settingsCompany()}</th>
                  <th>{settingsScheduleSectionDiscovery()}</th>
                  <th>{settingsScheduleSectionReconciliation()}</th>
                  <th>{settingsScheduleSectionProviderState()}</th>
                </tr>
              </thead>
              <tbody>
                {schedule.bindings.map((binding) => (
                  <tr key={binding.binding_id}>
                    <td>
                      <strong>{companyName(binding.company)}</strong>
                      {/* The provider earns its line only when it names a distinct
                          board. Repeating the company slug back at the company
                          is not a second fact. */}
                      {binding.provider.toLowerCase() !== binding.company.toLowerCase() && (
                        <small>{binding.provider}</small>
                      )}
                    </td>
                    <td>
                      {binding.discovery_enabled ? (
                        <DeadlineCell
                          at={binding.eligible_discovery_at}
                          cadenceSeconds={binding.discovery_cadence_seconds}
                        />
                      ) : (
                        <span className="muted">{settingsScheduleSectionReconciliationOnly()}</span>
                      )}
                    </td>
                    <td>
                      <DeadlineCell
                        at={binding.eligible_reconcile_at}
                        cadenceSeconds={binding.reconcile_cadence_seconds}
                      />
                      {/* Only the exception is worth a word: nearly every binding is
                          closure-capable, so saying so on every row says nothing. */}
                      {binding.closure_capability !== "authoritative" && (
                        <small>{settingsScheduleSectionNonAuthoritative()}</small>
                      )}
                    </td>
                    <td>
                      <Badge tone={bindingTone(binding)} variant="soft" size="sm">
                        <Icon name={bindingIcon(binding)} size={14} />
                        {statusLabel(binding)}
                      </Badge>
                      {binding.cooldown_until && (
                        <small><Msg of={settingsScheduleSectionUntil} elems={{ cooldown_until: formatWhen(binding.cooldown_until) }} /></small>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Sheet>
      )}
    </>
  );
}

export function ScheduleSection() {
  const resource = useAsyncResource<SyncSchedule>(() => api.schedule(), []);
  /* One order for every write the screen makes. A plan PUT and a company's
     PATCH each answer with the whole schedule, so with two in the air the
     screen keeps whichever answer lands last, which need not hold the later
     edit. Both are `exclusive`: each is sent once every write before it has
     answered and been adopted. `writing` is the one busy state every control
     that writes reads, so none of them sends while one is out. */
  const { exclusive, writing } = useWriteQueue("schedule");
  const moveSchedule = ({
    bindingId,
    mode,
    localMinute,
    timezone,
  }: {
    bindingId: number;
    mode: "discovery" | "reconcile";
    localMinute: number;
    timezone: string;
  }) => exclusive([], async () => {
    const updated = await api.updateSchedule(bindingId, {
      mode,
      local_minute: localMinute,
      timezone,
    });
    resource.mutate(() => updated);
  });
  const changePlan = (update: SchedulePlanUpdate) => exclusive([], async () => {
    const updated = await api.updateSchedulePlan(update);
    resource.mutate(() => updated);
  });

  return (
    <section className="settings-card schedule-section" aria-label={settingsScheduleSectionSchedule()}>
      <AsyncBoundary
        resource={resource}
        loading={settingsScheduleSectionLoading()}
        failed={settingsScheduleSectionLoadFailed()}
        emptyTitle={settingsScheduleSectionEmpty()}
        isEmpty={(schedule) => schedule.bindings.length === 0}
      >
        {(schedule) => (
          <ScheduleStudio schedule={schedule} busy={writing} onMove={moveSchedule} onPlan={changePlan} />
        )}
      </AsyncBoundary>
    </section>
  );
}
