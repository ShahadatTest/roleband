import { describe, expect, it } from "vitest";
import type { SyncSchedule } from "../../../api";
import { schedulePlanFixture } from "../../../test/fixtures";
import { msg } from "../../../test/msg";
import {
  modeLabel,
  reconciliationWindow,
  scheduleChartSummary,
  scheduleClusters,
  scheduleEvents,
  stackText,
} from "./schedule";

const schedule: SyncSchedule = {
  generated_at: "2026-07-28T14:30:00Z",
  enabled: true,
  tick_seconds: 600,
  max_parallel_providers: 2,
  authoritative_stale_hours: 30,
  // The per-company timers: the dial these tests were written for.
  plan: schedulePlanFixture({ enabled: false }),
  providers: [
    {
      provider: "greenhouse",
      state: "ready",
      cooldown_until: null,
      last_started_at: null,
      last_finished_at: null,
      last_outcome: "ok",
      binding_count: 2,
    },
    {
      provider: "meta",
      state: "policy_denied",
      cooldown_until: null,
      last_started_at: null,
      last_finished_at: null,
      last_outcome: null,
      binding_count: 1,
    },
  ],
  bindings: [
    {
      binding_id: 1,
      company: "openai",
      provider: "greenhouse",
      closure_capability: "authoritative",
      scheduled: true,
      discovery_enabled: true,
      discovery_cadence_seconds: 21_600,
      reconcile_cadence_seconds: 86_400,
      last_discovery_at: "2026-07-28T08:00:00Z",
      last_reconcile_at: "2026-07-27T20:00:00Z",
      next_discovery_at: "2026-07-28T16:00:00Z",
      next_reconcile_at: "2026-07-28T20:00:00Z",
      discovery_anchor_minute: null,
      reconcile_anchor_minute: null,
      schedule_timezone: null,
      eligible_discovery_at: "2026-07-28T16:00:00Z",
      eligible_reconcile_at: "2026-07-28T20:00:00Z",
      manual_requested_at: null,
      last_outcome: "ok",
      last_new_count: 1,
      consecutive_empty_discoveries: 0,
      provider_state: "ready",
      cooldown_until: null,
      status: "scheduled",
      waits_for_user: null,
    },
    {
      binding_id: 2,
      company: "anthropic",
      provider: "greenhouse",
      closure_capability: "authoritative",
      scheduled: true,
      discovery_enabled: true,
      discovery_cadence_seconds: 28_800,
      reconcile_cadence_seconds: 86_400,
      last_discovery_at: null,
      last_reconcile_at: null,
      next_discovery_at: "2026-07-28T17:00:00Z",
      next_reconcile_at: "2026-07-28T21:00:00Z",
      discovery_anchor_minute: null,
      reconcile_anchor_minute: null,
      schedule_timezone: null,
      eligible_discovery_at: "2026-07-28T17:00:00Z",
      eligible_reconcile_at: "2026-07-28T21:00:00Z",
      manual_requested_at: null,
      last_outcome: null,
      last_new_count: 0,
      consecutive_empty_discoveries: 3,
      provider_state: "ready",
      cooldown_until: null,
      status: "scheduled",
      waits_for_user: null,
    },
    {
      binding_id: 3,
      company: "meta",
      provider: "meta",
      closure_capability: "authoritative",
      scheduled: true,
      discovery_enabled: false,
      discovery_cadence_seconds: 21_600,
      reconcile_cadence_seconds: 86_400,
      last_discovery_at: null,
      last_reconcile_at: null,
      next_discovery_at: "2026-07-28T18:00:00Z",
      next_reconcile_at: "2026-07-28T22:00:00Z",
      discovery_anchor_minute: null,
      reconcile_anchor_minute: null,
      schedule_timezone: null,
      eligible_discovery_at: null,
      eligible_reconcile_at: null,
      manual_requested_at: null,
      last_outcome: null,
      last_new_count: 0,
      consecutive_empty_discoveries: 0,
      provider_state: "policy_denied",
      cooldown_until: null,
      status: "policy_denied",
      waits_for_user: null,
    },
  ],
};

describe("synchronization chronograph geometry", () => {
  it("extracts marks for active bindings only, in dispatch order", () => {
    const events = scheduleEvents(schedule);

    expect(events.map((event) => event.id)).toEqual([
      "1:discovery",
      "2:discovery",
      "1:reconcile",
      "2:reconcile",
    ]);
    expect(events.some((event) => event.company === "meta")).toBe(false);
    expect(events.every((event) => !event.overdue)).toBe(true);
  });

  it("clusters same-tick marks into one countable mark per orbit", () => {
    const collided = {
      ...schedule,
      bindings: schedule.bindings.map((binding) => binding.binding_id === 2
        ? { ...binding, next_reconcile_at: schedule.bindings[0].next_reconcile_at }
        : binding),
    };
    const clusters = scheduleClusters(collided);
    const reconcile = clusters.filter((cluster) => cluster.mode === "reconcile");

    expect(reconcile).toHaveLength(1);
    expect(reconcile[0].events.map((event) => event.company)).toEqual(["anthropic", "openai"]);
    expect(clusters.filter((cluster) => cluster.mode === "discovery")).toHaveLength(2);
  });

  it("pins overdue reconciliations to the window start so stale deadlines collapse", () => {
    const overdue = {
      ...schedule,
      generated_at: "2026-07-28T23:00:00Z",
    };
    const clusters = scheduleClusters(overdue);
    const window = reconciliationWindow(overdue);
    const due = clusters.find((cluster) => cluster.mode === "reconcile");

    expect(window).not.toBeNull();
    expect(due?.overdue).toBe(true);
    expect(due?.events).toHaveLength(2);
    expect(due?.at).toBe(window?.start);
  });

  it("projects the cycle end from provider serialization, not wall time", () => {
    // Both bindings share a provider and come due together: one binding per
    // provider per shard means they run back to back, so the cycle is two
    // ticks long even though both deadlines are the same instant.
    const together = {
      ...schedule,
      bindings: schedule.bindings.map((binding) => binding.binding_id === 2
        ? { ...binding, next_reconcile_at: "2026-07-28T20:00:00Z" }
        : binding),
    };
    const window = reconciliationWindow(together);

    expect(window).toMatchObject({
      start: "2026-07-28T20:00:00.000Z",
      end: "2026-07-28T20:20:00.000Z",
      count: 2,
    });
  });

  it("scopes the cycle to the burst that dispatches together, not first-to-last", () => {
    // Steady state: deadlines spread across the day. Spanning to the last
    // deadline would project a ~23h window — an arc covering the whole dial,
    // claiming the authoritative cycle never stops.
    const spread = {
      ...schedule,
      bindings: schedule.bindings.map((binding) => binding.binding_id === 2
        ? { ...binding, next_reconcile_at: "2026-07-29T19:00:00Z" }
        : binding),
    };
    const window = reconciliationWindow(spread);
    const spanHours =
      (Date.parse(window?.end ?? "") - Date.parse(window?.start ?? "")) / 3_600_000;

    expect(window?.start).toBe("2026-07-28T20:00:00.000Z");
    expect(window?.count).toBe(1);
    expect(window?.eventIds).toEqual(["1:reconcile"]);
    expect(spanHours).toBeLessThan(1);
  });

  // Build a run of reconciliations at the given ISO instants, one binding
  // each, on distinct providers so serialization never masks the gaps.
  const withReconciles = (times: string[]): SyncSchedule => ({
    ...schedule,
    bindings: times.map((at, index) => ({
      ...schedule.bindings[0],
      binding_id: 100 + index,
      company: `co-${index}`,
      provider: `prov-${index}`,
      discovery_enabled: false,
      next_discovery_at: null,
      eligible_discovery_at: null,
      next_reconcile_at: at,
      eligible_reconcile_at: at,
    })),
  });

  it("holds a night pass in one cycle across the gaps the scheduler idles", () => {
    // 40 minutes apart: each runs a tick, the scheduler waits two, the next
    // goes. Requiring them to share a tick would split one pass into three
    // cycles, each one binding long, and a one-binding cycle draws no arc at all.
    const pass = withReconciles([
      "2026-07-28T20:00:00Z",
      "2026-07-28T20:40:00Z",
      "2026-07-28T21:20:00Z",
    ]);
    const window = reconciliationWindow(pass);

    expect(window?.count).toBe(3);
    expect(window).toMatchObject({
      start: "2026-07-28T20:00:00.000Z",
      end: "2026-07-28T21:30:00.000Z",
    });
  });

  it("still breaks the cycle at the hour-apart spacing steady state produces", () => {
    // One tick of work then a 50-minute wait is not one run. This is the
    // boundary that keeps the settle gap from chaining the whole day.
    const spread = withReconciles([
      "2026-07-28T20:00:00Z",
      "2026-07-28T21:00:00Z",
      "2026-07-28T22:00:00Z",
    ]);
    const window = reconciliationWindow(spread);

    expect(window?.count).toBe(1);
    expect(window?.end).toBe("2026-07-28T20:10:00.000Z");
  });

  it("never lets a chain of deadlines claim more than a quarter of the dial", () => {
    // 40 minutes apart for a full day: each link is inside the settle gap, so
    // only the hard cap stops this painting the clock — the exact failure the
    // burst rule exists to prevent.
    const chained = withReconciles(
      Array.from({ length: 36 }, (_, i) =>
        new Date(Date.parse("2026-07-28T20:00:00Z") + i * 40 * 60_000).toISOString()),
    );
    const window = reconciliationWindow(chained);
    const spanHours =
      (Date.parse(window?.end ?? "") - Date.parse(window?.start ?? "")) / 3_600_000;

    expect(spanHours).toBeLessThanOrEqual(6);
    expect(window?.count).toBeLessThan(36);
  });

  it("keeps a simultaneous backlog in one cycle and names its members", () => {
    const overdue = { ...schedule, generated_at: "2026-07-28T23:00:00Z" };
    const window = reconciliationWindow(overdue);

    expect(window?.count).toBe(2);
    expect(window?.eventIds).toEqual(["1:reconcile", "2:reconcile"]);
    expect(Date.parse(window?.end ?? "")).toBeGreaterThan(Date.parse(window?.start ?? ""));
  });

  it("describes exclusions instead of counting denied connectors as scheduled", () => {
    expect(scheduleChartSummary(schedule)).toContain("1 excluded or unscheduled");
  });
});

/* The words for a deadline follow its own mode, and both schedules use the
   same words for it: a full scan is a full scan under the plan and the timers. */
describe("deadline names", () => {
  const pairs = [
    { mode: "reconcile", planned: true, schedule: "plan" },
    { mode: "discovery", planned: true, schedule: "plan" },
    { mode: "reconcile", planned: false, schedule: "timers" },
    { mode: "discovery", planned: false, schedule: "timers" },
  ] as const;

  it("names one deadline by its mode, in the same words under the plan and the timers", () => {
    const names = pairs.map(({ mode, planned, schedule: which }) => {
      const name = modeLabel(mode, planned);
      expect(name).toBe(msg("settings-schedule-mode-name", { schedule: which, mode }));
      return name;
    });
    expect(new Set(names).size).toBe(2);
    expect(names[0]).toBe(names[2]);
    expect(names[1]).toBe(names[3]);
  });

  it("counts a stack and names it the way its single deadline is named", () => {
    const stacks = pairs.map(({ mode, planned, schedule: which }) => {
      const stack = stackText(3, mode, planned);
      expect(stack).toBe(msg("settings-schedule-stack", { count: 3, schedule: which, mode }));
      return stack;
    });
    expect(new Set(stacks).size).toBe(2);
    expect(stacks[0]).toBe(stacks[2]);
    expect(stacks[1]).toBe(stacks[3]);
  });
});

describe("the dial's account under the plan", () => {
  const planned = (upcoming: SyncSchedule["plan"]["upcoming"]): SyncSchedule => ({
    ...schedule,
    plan: schedulePlanFixture({ pinned: 2, upcoming }),
  });
  const next = (kind: "full" | "quick") => ({
    at: "2026-07-28T16:00:00Z", kind, seconds: 600, estimated: false, on_wake: false, running: false, ready_by: false,
  });

  it("names the next scan's kind and the companies that kind reads", () => {
    const full = scheduleChartSummary(planned([next("full"), next("quick")]));
    const quick = scheduleChartSummary(planned([next("quick"), next("full")]));
    expect(full).toBe(msg("settings-schedule-24-hour-scan-clock-planned-next", { runs: 2, kind: "full", companies: 1112, pinned: 2 }));
    expect(quick).toBe(msg("settings-schedule-24-hour-scan-clock-planned-next", { runs: 2, kind: "quick", companies: 944, pinned: 2 }));
    expect(full).not.toBe(quick);
  });

  it("says nothing about a next scan when none is planned", () => {
    expect(scheduleChartSummary(planned([]))).toBe(msg("settings-schedule-24-hour-scan-clock-planned", { runs: 0, pinned: 2 }));
  });
});
