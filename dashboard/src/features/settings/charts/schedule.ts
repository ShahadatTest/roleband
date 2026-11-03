import { compare as copyCompare } from "../../../copy/format";
import type { ScheduleBinding, SyncSchedule } from "../../../api";
import {
  settingsSchedule24HourChronographDiscoveryProbes,
  settingsSchedule24HourScanClockPlanned,
  settingsSchedule24HourScanClockPlannedNext,
  settingsScheduleCancelTheQueuedManualScan,
  settingsScheduleModeName,
  settingsScheduleProviderPolicyDeniesScheduledCollection,
  settingsScheduleProviderSchedulingIsPaused,
  settingsScheduleScanScheduleIsNotSet,
  settingsScheduleStack,
} from "../../../copy/gen/settings";

// Pure schedule geometry for the synchronization chronograph. No chart-library
// options here: the dial is hand-rolled SVG owned by ScheduleChronograph.

export type ScheduleMode = "discovery" | "reconcile";

export interface ScheduleEvent {
  bindingId: number;
  id: string;
  company: string;
  provider: string;
  mode: ScheduleMode;
  at: string;
  effectiveAt?: string | null;
  overdue: boolean;
  status: ScheduleBinding["status"];
}

export interface ScheduleCluster {
  id: string;
  mode: ScheduleMode;
  /** Display time: overdue events are pinned (reconcile -> window start,
   * discovery -> generated_at) so stale deadlines collapse into one mark. */
  at: string;
  overdue: boolean;
  events: ScheduleEvent[];
}

export interface ReconciliationWindow {
  start: string;
  end: string;
  count: number;
  /** Ids of the events dispatching in this cycle, so callers can avoid
   * listing them a second time beside the window that already covers them. */
  eventIds: string[];
}

const ACTIVE = new Set<ScheduleBinding["status"]>(["scheduled", "manual", "cooldown"]);

/** Which of a binding's two deadlines the dial draws. */
export type EventFilter = (binding: ScheduleBinding, mode: ScheduleMode) => boolean;

/** A deadline the user set on the clock. With the schedule plan on
    these are the only per-company deadlines the dispatcher still serves, so
    they are the only company marks the dial draws. */
const pinnedOnly: EventFilter = (binding, mode) =>
  (mode === "discovery" ? binding.discovery_anchor_minute : binding.reconcile_anchor_minute) !== null;

const everyEvent: EventFilter = () => true;

/** The filter the dial uses for this schedule: pinned deadlines under the plan,
    every deadline under the per-company timers. */
export const eventFilterFor = (schedule: SyncSchedule): EventFilter =>
  schedule.plan.enabled ? pinnedOnly : everyEvent;

export function scheduleEvents(schedule: SyncSchedule, only: EventFilter = everyEvent): ScheduleEvent[] {
  return schedule.bindings
    .flatMap((binding) => {
      if (!ACTIVE.has(binding.status)) return [];
      const rows: ScheduleEvent[] = [];
      if (binding.discovery_enabled && binding.next_discovery_at && only(binding, "discovery")) {
        rows.push({
          bindingId: binding.binding_id,
          id: `${binding.binding_id}:discovery`,
          company: binding.company,
          provider: binding.provider,
          mode: "discovery",
          at: binding.next_discovery_at,
          effectiveAt: binding.eligible_discovery_at,
          overdue: Date.parse(binding.next_discovery_at) <= Date.parse(schedule.generated_at),
          status: binding.status,
        });
      }
      if (binding.next_reconcile_at && only(binding, "reconcile")) {
        rows.push({
          bindingId: binding.binding_id,
          id: `${binding.binding_id}:reconcile`,
          company: binding.company,
          provider: binding.provider,
          mode: "reconcile",
          at: binding.next_reconcile_at,
          effectiveAt: binding.eligible_reconcile_at,
          overdue: Date.parse(binding.next_reconcile_at) <= Date.parse(schedule.generated_at),
          status: binding.status,
        });
      }
      return rows;
    })
    .sort((a, b) => Date.parse(a.at) - Date.parse(b.at));
}

/** How long the cycle may idle and still be the same run. Zero would make
 *  every night pass read as N unrelated cycles: deadlines set 30-40min apart run
 *  back to back with the scheduler waiting a couple of ticks between them,
 *  which is one pass by any operator's reading. Three ticks is the largest
 *  gap that keeps hour-apart deadlines apart — the spacing steady state
 *  actually produces — so this cannot chain the whole day into one arc. */
const CYCLE_SETTLE_TICKS = 3;

/** Backstop for the failure this function exists to prevent: no chain of
 *  settle gaps may grow a cycle past a quarter of the dial. It bounds the
 *  chaining only — a genuinely simultaneous backlog serializes for as long as
 *  it serializes, and that length is real. */
const MAX_CYCLE_MS = 6 * 3_600_000;

// The authoritative cycle is the burst of reconciliations that runs as one
// pass — NOT the span from the first deadline to the last. Spanning to the
// last deadline is only small while everything is overdue and collapses onto
// one instant; in steady state the deadlines spread across the day, so that
// definition projects a ~24h window which paints the whole dial and asserts
// the cycle is permanently running. A reconciliation joins only if it comes
// due before the work already in the burst finishes, or within a settle gap
// of it — long enough for a night pass, short enough that a spread schedule
// still breaks into separate cycles.
export function reconciliationWindow(schedule: SyncSchedule): ReconciliationWindow | null {
  const reconciliations = scheduleEvents(schedule)
    .filter((event) => event.mode === "reconcile");
  if (reconciliations.length === 0) return null;

  const tickMs = schedule.tick_seconds * 1000;
  const maxParallel = Math.max(1, schedule.max_parallel_providers);
  const now = Date.parse(schedule.generated_at);
  // An overdue deadline means "dispatch at the next opportunity", so a stale
  // backlog is one cycle however far apart the missed deadlines were.
  const dueAt = (event: ScheduleEvent) => Math.max(Date.parse(event.at), now);
  const start = dueAt(reconciliations[0]);
  const burst: ScheduleEvent[] = [];
  let end = start;

  for (const event of reconciliations) {
    const at = dueAt(event);
    if (burst.length > 0) {
      if (at > end + CYCLE_SETTLE_TICKS * tickMs) break;
      // Bound the projected end, not this deadline: admitting an event and
      // then letting its own tick run past the cap defeats the cap.
      if (at + tickMs - start > MAX_CYCLE_MS) break;
    }
    burst.push(event);
    // Serialization: one binding per provider per shard, and at most
    // max_parallel_providers shards at a time (projected, scoped to the burst
    // rather than to every reconciliation on the clock).
    const providerCounts = new Map<string, number>();
    for (const member of burst) {
      providerCounts.set(member.provider, (providerCounts.get(member.provider) ?? 0) + 1);
    }
    const slots = Math.max(
      Math.max(...providerCounts.values()),
      Math.ceil(burst.length / maxParallel),
    );
    end = Math.max(at + tickMs, start + slots * tickMs);
  }

  return {
    start: new Date(start).toISOString(),
    end: new Date(end).toISOString(),
    count: burst.length,
    eventIds: burst.map((event) => event.id),
  };
}

export function scheduleClusters(
  schedule: SyncSchedule,
  only: EventFilter = everyEvent,
): ScheduleCluster[] {
  const events = scheduleEvents(schedule, only);
  // The authoritative cycle is the timers' burst; under the plan an overdue
  // pinned deadline is simply due now.
  const window = only === everyEvent ? reconciliationWindow(schedule) : null;
  const tickMs = schedule.tick_seconds * 1000;
  const displayAt = (event: ScheduleEvent) => {
    if (!event.overdue) return event.at;
    if (event.mode === "reconcile" && window) return window.start;
    return schedule.generated_at;
  };

  const buckets = new Map<string, ScheduleEvent[]>();
  for (const event of events) {
    const key = `${event.mode}:${Math.round(Date.parse(displayAt(event)) / tickMs)}`;
    const bucket = buckets.get(key) ?? [];
    bucket.push(event);
    buckets.set(key, bucket);
  }

  return [...buckets.values()]
    .map((bucket) => {
      const ordered = [...bucket].sort((a, b) => copyCompare(a.company, b.company));
      const at = bucket
        .map(displayAt)
        .sort((a, b) => Date.parse(a) - Date.parse(b))[0];
      return {
        id: `${ordered[0].mode}:${ordered.map((event) => event.bindingId).join("-")}`,
        mode: ordered[0].mode,
        at,
        overdue: ordered.some((event) => event.overdue),
        events: ordered,
      };
    })
    .sort((a, b) => Date.parse(a.at) - Date.parse(b.at));
}

export function scheduleChartSummary(schedule: SyncSchedule): string {
  const plan = schedule.plan;
  if (plan.enabled) {
    // The screen reader's account of the dial says what the dial draws under
    // the plan: its runs and the companies with a time of their own.
    const runs = plan.upcoming.length;
    const next = plan.upcoming[0];
    if (!next) return settingsSchedule24HourScanClockPlanned({ runs, pinned: plan.pinned });
    return settingsSchedule24HourScanClockPlannedNext({
      runs,
      kind: next.kind,
      companies: next.kind === "full" ? plan.roster : plan.quick_roster,
      pinned: plan.pinned,
    });
  }
  const enabled = schedule.bindings.filter((binding) => ACTIVE.has(binding.status));
  const probes = enabled.filter((binding) => binding.eligible_discovery_at).length;
  const reconciliations = enabled.filter((binding) => binding.eligible_reconcile_at).length;
  const excluded = schedule.bindings.length - enabled.length;
  return settingsSchedule24HourChronographDiscoveryProbes({ probes: probes, reconciliations: reconciliations, excluded: excluded });
}

/* Three readings of a schedule row, shared by the dial and its inspector.
   They live here rather than in the component that drew them because each is a
   pure statement about the data: the clock face's own text, the two modes'
   names, and whether a mark may be moved at all. */

export const formatMinute = (minute: number) => {
  // A drag reports fractional minutes; a clock face never says 09:37.4.
  const whole = ((Math.round(minute) % (24 * 60)) + 24 * 60) % (24 * 60);
  return `${String(Math.floor(whole / 60)).padStart(2, "0")}:${String(whole % 60).padStart(2, "0")}`;
};

/** How many deadlines a stack holds and what they are called. Under the
    schedule plan a pinned reconciliation is a full scan and a pinned discovery
    probe a quick scan, the plan's own words; the timers keep theirs. */
export const stackText = (count: number, mode: ScheduleMode, planned: boolean) =>
  settingsScheduleStack({ count, schedule: planned ? "plan" : "timers", mode });

/** One deadline's name. Under the schedule plan a company's own
    time is a full or quick scan, the plan's words; the timers keep theirs. */
export const modeLabel = (mode: ScheduleMode, planned = false) =>
  settingsScheduleModeName({ schedule: planned ? "plan" : "timers", mode });

/** Why this event's time cannot be edited, or null when it can. The order is
    the order a reader needs it: the provider's policy outranks our pause,
    which outranks a schedule that was never set up, and a queued manual scan
    holds only the reconciliation it would satisfy. */
export const editableReason = (
  event: ScheduleEvent,
  binding: ScheduleBinding,
): string | null => {
  if (binding.status === "policy_denied") return settingsScheduleProviderPolicyDeniesScheduledCollection();
  if (binding.status === "paused") return settingsScheduleProviderSchedulingIsPaused();
  if (binding.status === "unscheduled") return settingsScheduleScanScheduleIsNotSet();
  if (event.mode === "reconcile" && binding.manual_requested_at) {
    return settingsScheduleCancelTheQueuedManualScan();
  }
  return null;
};

// A cluster moves one connector at a time, and the one that moves is the first
// in the list that is actually movable — a locked mark cannot be the lead, or
// dragging the stack would silently do nothing. -1 = every member is locked.
export const leadIndexOf = (
  events: ScheduleEvent[],
  bindings: Map<number, ScheduleBinding>,
) => events.findIndex((event) => {
  const binding = bindings.get(event.bindingId);
  return binding !== undefined && editableReason(event, binding) === null;
});

/** The one event a drag on this mark carries: itself for a lone mark, the lead
    for a stack, so repeated drags peel a cluster apart one connector at a
    time. Null when every member is locked. */
export const leadEvent = (
  events: ScheduleEvent[],
  bindings: Map<number, ScheduleBinding>,
): ScheduleEvent | null => {
  const lead = leadIndexOf(events, bindings);
  return lead < 0 ? null : events[lead];
};
