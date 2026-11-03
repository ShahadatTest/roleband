import { describe, expect, it } from "vitest";
import type { SystemStatus } from "../../api";
import { statusFixture } from "../../test/fixtures";
import { firstScan, nothingFitsYet } from "./firstScan";

const NOW = Date.parse("2026-11-02T10:00:00Z");
const minutesAgo = (minutes: number) => new Date(NOW - minutes * 60_000).toISOString();

/** A fresh install mid-way through its first scan: 12 of 150 companies read,
    and `last_success_at` already set by the first of them. */
function install(over: Partial<SystemStatus> = {}, scheduler: Partial<SystemStatus["scheduler"]> = {}): SystemStatus {
  return {
    ...statusFixture,
    last_success_at: minutesAgo(1),
    running: true,
    last_run_started_at: minutesAgo(4),
    manual_queued: [],
    manual_blocked: [],
    jobs: [],
    ...over,
    scheduler: { ...statusFixture.scheduler, required: 150, ever_read: 12, unread: [], ...scheduler },
  };
}

describe("firstScan", () => {
  it("is still the first scan after one company has set last_success_at", () => {
    const scan = firstScan(install(), false, NOW);
    expect(scan).toMatchObject({ phase: "running", count: { read: 12, total: 150 } });
  });

  it("ends when every required company has been read once", () => {
    expect(firstScan(install({}, { ever_read: 150 }), false, NOW)).toEqual({ phase: "done" });
    expect(firstScan(install({}, { ever_read: 149 }), false, NOW).phase).toBe("running");
  });

  it("estimates from the pace once enough companies are read", () => {
    // 12 read in 4 minutes: 138 left at 3 a minute is 46 minutes.
    expect(firstScan(install(), false, NOW)).toMatchObject({ back: { when: "minutes", minutes: 46 } });
  });

  it("gives no number before the pace means anything", () => {
    expect(firstScan(install({}, { ever_read: 4 }), false, NOW)).toMatchObject({ back: { when: "soon" } });
    expect(firstScan(install({ last_run_started_at: new Date(NOW - 20_000).toISOString() }), false, NOW))
      .toMatchObject({ back: { when: "soon" } });
    expect(firstScan(install({ last_run_started_at: null }), false, NOW)).toMatchObject({ back: { when: "soon" } });
  });

  it("says almost done under a minute and an hour or so past sixty", () => {
    expect(firstScan(install({}, { ever_read: 149 }), false, NOW)).toMatchObject({ back: { when: "almost" } });
    expect(firstScan(install({ last_run_started_at: minutesAgo(10) }, { ever_read: 5 }), false, NOW))
      .toMatchObject({ back: { when: "hour" } });
  });

  it("counts the optimistic bridge after Scan now as running", () => {
    expect(firstScan(install({ running: false }), true, NOW).phase).toBe("running");
  });

  it("names the scan job's hold, before any queue state", () => {
    const held = install({
      running: false,
      jobs: [{ ...jobRow, state: "queued", reason: "waiting_for_mains" }],
    });
    expect(firstScan(held, false, NOW)).toEqual({
      phase: "held", count: { read: 12, total: 150 }, hold: { reason: "waiting_for_mains", until: null },
    });
  });

  it("names a provider's backoff with when it ends", () => {
    const until = "2026-11-02T14:20:00Z";
    const held = install({
      running: false, manual_queued: ["stripe"],
      manual_blocked: [{ provider: "greenhouse", reason: "backoff", until, companies: 1 }],
    });
    expect(firstScan(held, false, NOW)).toMatchObject({ phase: "held", hold: { reason: "backoff", until } });
  });

  it("is about to start when no run has started, or one is lined up", () => {
    expect(firstScan(install({ running: false, last_run_started_at: null }, { ever_read: 0 }), false, NOW).phase)
      .toBe("starting");
    expect(firstScan(install({ running: false, jobs: [{ ...jobRow, state: "queued" }] }), false, NOW).phase)
      .toBe("starting");
    expect(firstScan(install({ running: false, manual_queued: ["stripe"] }), false, NOW).phase).toBe("starting");
  });

  it("is stopped when a run ended part-way and nothing is lined up", () => {
    expect(firstScan(install({ running: false }), false, NOW)).toEqual({
      phase: "stopped", count: { read: 12, total: 150 },
    });
    expect(firstScan(install({ running: false, jobs: [{ ...jobRow, state: "idle" }] }), false, NOW).phase)
      .toBe("stopped");
  });

  it("has nothing to scan when no company is required", () => {
    expect(firstScan(install({}, { required: 0, ever_read: 0 }), false, NOW)).toEqual({ phase: "none" });
  });

  it("before the roster is seeded, goes by the last full run", () => {
    const unseeded = { seeded: false, required: 0, ever_read: 0 };
    expect(firstScan(install({ last_success_at: null }, unseeded), false, NOW))
      .toEqual({ phase: "running", count: null, back: { when: "soon" } });
    expect(firstScan(install({ last_success_at: null, running: false }, unseeded), false, NOW))
      .toEqual({ phase: "starting" });
    expect(firstScan(install({}, unseeded), false, NOW)).toEqual({ phase: "done" });
  });
});

describe("nothingFitsYet", () => {
  it("starts at a third of the roster", () => {
    expect(nothingFitsYet({ read: 49, total: 150 })).toBe(false);
    expect(nothingFitsYet({ read: 50, total: 150 })).toBe(true);
    expect(nothingFitsYet(null)).toBe(false);
  });
});

const jobRow: NonNullable<SystemStatus["jobs"]>[number] = {
  key: "scan", job: "scan", state: "idle", reason: null, since: minutesAgo(30), next_at: null,
  run_id: null, progress: null, waiting: null, queued: 0,
};
