import { act, render, renderHook, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Notification } from "../../../api";
import { SyncProgressPanel } from "./SyncProgressPanel";
import { fmtElapsed, isSyncRunning, isSyncStale, parseSyncProgress, syncProgressSummary, useSyncClock } from "./model";

const progressMeta = (over: Record<string, unknown> = {}) => ({
  sync_state: "running",
  progress: {
    phase: "collecting",
    percent: 25,
    companies_total: 8,
    companies_collected: 4,
    companies_recorded: 0,
    companies_scraping: 4,
    companies_failed: 0,
    opportunities_detected: 312,
    opportunities_recorded: 0,
    opportunities_pending: 312,
    ...over,
  },
});

const notif = (meta: Record<string, unknown>): Notification =>
  ({
    id: 1,
    created_at: "2026-07-23T14:10:51Z",
    priority: "normal",
    category: "sync_started",
    title: "Sync started",
    body: "8 sources queued",
    job_id: null,
    run_id: 1,
    source_type: "run",
    read_at: null,
    dismissed_at: null,
    company: null,
    meta,
  }) as unknown as Notification;

describe("parseSyncProgress", () => {
  it("parses a live progress block", () => {
    const p = parseSyncProgress(progressMeta());
    expect(p).not.toBeNull();
    expect(p!.phase).toBe("collecting");
    expect(p!.companiesTotal).toBe(8);
    expect(p!.companiesScraping).toBe(4);
    expect(p!.opportunitiesDetected).toBe(312);
  });

  it("returns null for rows written before the feature", () => {
    expect(parseSyncProgress({ sync_state: "running" })).toBeNull();
    expect(parseSyncProgress({})).toBeNull();
    expect(parseSyncProgress(null)).toBeNull();
    expect(parseSyncProgress(undefined)).toBeNull();
  });

  it("rejects non-object progress values", () => {
    expect(parseSyncProgress({ progress: "running" })).toBeNull();
    expect(parseSyncProgress({ progress: [1, 2] })).toBeNull();
  });

  it("falls back to collecting for an unknown phase", () => {
    expect(parseSyncProgress(progressMeta({ phase: "teleporting" }))!.phase).toBe("collecting");
  });

  it("clamps hostile numbers", () => {
    const p = parseSyncProgress(
      progressMeta({ percent: 900, companies_total: -4, opportunities_detected: NaN }),
    )!;
    expect(p.percent).toBe(100);
    expect(p.companiesTotal).toBe(0);
    expect(p.opportunitiesDetected).toBe(0);
  });

  it("coerces missing counters to zero rather than NaN", () => {
    const p = parseSyncProgress({ progress: { phase: "persisting" } })!;
    expect(p.companiesTotal).toBe(0);
    expect(p.opportunitiesRecorded).toBe(0);
    expect(Number.isNaN(p.percent)).toBe(false);
  });
});

describe("isSyncRunning", () => {
  it("is true only for a running sync_started row", () => {
    expect(isSyncRunning(notif(progressMeta()))).toBe(true);
  });

  it("is false once the run finishes", () => {
    expect(isSyncRunning(notif({ sync_state: "done" }))).toBe(false);
  });

  it("is false for other categories", () => {
    const n = { ...notif(progressMeta()), category: "sync_success" } as Notification;
    expect(isSyncRunning(n)).toBe(false);
  });
});

describe("syncProgressSummary", () => {
  it("leads with found count while collecting", () => {
    expect(syncProgressSummary(parseSyncProgress(progressMeta())!)).toBe(
      "4/8 companies scanned · 312 roles found",
    );
  });

  it("keeps counting roles found after scanning ends, never a recorded ratio", () => {
    const p = parseSyncProgress(
      progressMeta({
        phase: "persisting",
        companies_collected: 8,
        companies_recorded: 3,
        opportunities_recorded: 120,
      }),
    )!;
    expect(syncProgressSummary(p)).toBe("8/8 companies scanned · 312 roles found");
  });

  it("counts a single role as one", () => {
    expect(syncProgressSummary(parseSyncProgress(progressMeta({ opportunities_detected: 1 }))!)).toBe(
      "4/8 companies scanned · 1 role found",
    );
  });
});

describe("SyncProgressPanel", () => {
  it("shows all four user-visible counters", () => {
    render(<SyncProgressPanel progress={parseSyncProgress(progressMeta())!} />);
    expect(screen.getByText("Companies scanned")).toBeInTheDocument();
    expect(screen.getByText("of 8")).toBeInTheDocument();
    expect(screen.getByText("Still scanning")).toBeInTheDocument();
    expect(screen.getByText("Roles found")).toBeInTheDocument();
    expect(screen.getByText("312")).toBeInTheDocument();
    expect(screen.getByText("From finished companies")).toBeInTheDocument();
  });

  it("exposes an accessible progressbar", () => {
    render(<SyncProgressPanel progress={parseSyncProgress(progressMeta())!} />);
    const bar = screen.getByRole("progressbar");
    expect(bar).toHaveAttribute("aria-valuenow", "25");
    expect(bar).toHaveAttribute("aria-valuemin", "0");
    expect(bar).toHaveAttribute("aria-valuemax", "100");
  });

  it("tells the person found roles are already reaching the radar during the scan", () => {
    render(<SyncProgressPanel progress={parseSyncProgress(progressMeta())!} />);
    expect(screen.getByText("Roles reach your radar as each company is scanned.")).toBeInTheDocument();
    expect(screen.queryByText(/stays at zero|record/i)).not.toBeInTheDocument();
  });

  it("drops that explanation once persisting starts", () => {
    render(
      <SyncProgressPanel progress={parseSyncProgress(progressMeta({ phase: "persisting" }))!} />,
    );
    expect(screen.queryByText(/reach your radar/)).not.toBeInTheDocument();
    expect(screen.getByText("Adding the last roles")).toBeInTheDocument();
  });

  it("surfaces failed sources", () => {
    render(
      <SyncProgressPanel progress={parseSyncProgress(progressMeta({ companies_failed: 2 }))!} />,
    );
    expect(screen.getByText(/2 companies failed/)).toBeInTheDocument();
  });

  it("stays silent when nothing failed", () => {
    render(<SyncProgressPanel progress={parseSyncProgress(progressMeta())!} />);
    expect(screen.queryByText(/failed/)).not.toBeInTheDocument();
  });

  it("shows pending only while a backlog exists", () => {
    render(<SyncProgressPanel progress={parseSyncProgress(progressMeta())!} />);
    expect(screen.getByText("312 still scanning")).toBeInTheDocument();
  });
});

/* ---------------------------------------------------------------------------
 * Per-company roster. A row may carry no `companies` key at all, which is why
 * every block above describes the panel's aggregate-only rendering path and
 * must keep passing untouched.
 * ------------------------------------------------------------------------ */

const company = (over: Record<string, unknown> = {}) => ({
  slug: "google",
  state: "queued",
  outcome: null,
  since_ms: null,
  detected: 0,
  scanned: 0,
  recorded: 0,
  ...over,
});

const rosterMeta = (companies: Record<string, unknown>[], over: Record<string, unknown> = {}) =>
  progressMeta({
    companies,
    concurrency_limit: 5,
    snapshot_at_ms: 1_785_000_000_000,
    companies_queued: 2,
    companies_degraded: 0,
    ...over,
  });

describe("parseSyncProgress: roster", () => {
  it("defaults to an empty roster when the block is absent", () => {
    const p = parseSyncProgress(progressMeta())!;
    expect(p.companies).toEqual([]);
    expect(p.snapshotAtMs).toBeNull();
  });

  it("maps each company onto camelCase fields", () => {
    const p = parseSyncProgress(
      rosterMeta([company({ slug: "apple", state: "collected", outcome: "ok", detected: 12, scanned: 300 })]),
    )!;
    expect(p.companies).toEqual([
      {
        slug: "apple",
        state: "collected",
        outcome: "ok",
        sinceMs: null,
        detected: 12,
        scanned: 300,
        recorded: 0,
      },
    ]);
  });

  it("drops entries with no usable slug", () => {
    const p = parseSyncProgress(rosterMeta([company(), { state: "queued" }, company({ slug: "" })]))!;
    expect(p.companies.map((c) => c.slug)).toEqual(["google"]);
  });

  it("falls back to queued for an unknown state and null for an unknown outcome", () => {
    const p = parseSyncProgress(rosterMeta([company({ state: "teleporting", outcome: "vibes" })]))!;
    expect(p.companies[0].state).toBe("queued");
    expect(p.companies[0].outcome).toBeNull();
  });

  it("rejects a non-numeric start timestamp rather than starting a clock", () => {
    const p = parseSyncProgress(rosterMeta([company({ since_ms: "soon" })]))!;
    expect(p.companies[0].sinceMs).toBeNull();
  });

  it("ignores a non-array roster", () => {
    expect(parseSyncProgress(progressMeta({ companies: "lots" }))!.companies).toEqual([]);
  });

  it("clamps a hostile concurrency limit into the configurable range", () => {
    expect(parseSyncProgress(progressMeta({ concurrency_limit: 900 }))!.concurrencyLimit).toBe(10);
    expect(parseSyncProgress(progressMeta({ concurrency_limit: 0 }))!.concurrencyLimit).toBe(5);
    expect(parseSyncProgress(progressMeta())!.concurrencyLimit).toBe(5);
  });
});

describe("fmtElapsed", () => {
  it("reads in seconds below a minute so short sources feel live", () => {
    expect(fmtElapsed(0)).toBe("0s");
    expect(fmtElapsed(59_000)).toBe("59s");
  });

  it("pads seconds once minutes appear", () => {
    expect(fmtElapsed(60_000)).toBe("1m 00s");
    expect(fmtElapsed(184_000)).toBe("3m 04s");
  });

  it("rolls over to hours", () => {
    expect(fmtElapsed(3_660_000)).toBe("1h 01m");
  });

  it("never renders negative time", () => {
    expect(fmtElapsed(-5_000)).toBe("0s");
  });
});

describe("useSyncClock", () => {
  const BASE = 1_785_000_000_000;

  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(BASE);
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("ticks between snapshots, so clocks do not jump by the publish interval", () => {
    const { result } = renderHook(() => useSyncClock(BASE, true));
    act(() => {
      vi.advanceTimersByTime(3000);
    });
    expect(result.current.nowMs).toBe(BASE + 3000);
  });

  it("stops ticking once the run is no longer live", () => {
    const { result } = renderHook(() => useSyncClock(BASE, false));
    act(() => {
      vi.advanceTimersByTime(5000);
    });
    expect(result.current.nowMs).toBe(BASE);
  });

  it("estimates a server clock running ahead of ours", () => {
    const { result } = renderHook(() => useSyncClock(BASE + 20_000, true));
    expect(result.current.skewMs).toBe(20_000);
    expect(result.current.staleMs).toBe(0);
  });

  it("never lets a weaker sample rewind an established estimate", () => {
    const { result, rerender } = renderHook(({ at }) => useSyncClock(at, true), {
      initialProps: { at: BASE + 20_000 },
    });
    expect(result.current.skewMs).toBe(20_000);
    // A later poll carrying an older snapshot is a weaker lower bound on skew.
    // Honouring it would drag every rendered elapsed clock backwards.
    rerender({ at: BASE + 12_000 });
    expect(result.current.skewMs).toBe(20_000);
  });

  it("distrusts an absurd server clock instead of propagating it", () => {
    const { result } = renderHook(() => useSyncClock(BASE + 5 * 86_400_000, true));
    expect(result.current.skewMs).toBe(0);
  });

  it("reports staleness once the run stops publishing", () => {
    const { result } = renderHook(() => useSyncClock(BASE, true));
    expect(isSyncStale(result.current)).toBe(false);
    act(() => {
      vi.advanceTimersByTime(120_000);
    });
    expect(isSyncStale(result.current)).toBe(true);
  });
});

describe("SyncProgressPanel with a roster", () => {
  const roster = [
    company({ slug: "amazon", state: "scraping", since_ms: 1_784_999_820_000 }),
    company({ slug: "google", state: "collected", outcome: "ok", detected: 64, scanned: 900 }),
    company({ slug: "netflix", state: "queued" }),
  ];

  it("drops the aggregate tiles the roster already states", () => {
    // Every one of them is a third copy: sources scanned and found are in the row
    // summary above, scraping is the stream, recorded/pending are the tank.
    render(<SyncProgressPanel progress={parseSyncProgress(rosterMeta(roster))!} />);
    expect(screen.queryByText("Companies scanned")).not.toBeInTheDocument();
    expect(screen.queryByText("From finished companies")).not.toBeInTheDocument();
    // The scan box names its two volumes with the tiles' words; only it may.
    for (const word of ["Still scanning", "Roles found"]) {
      for (const node of screen.queryAllByText(word)) expect(node.closest("svg")).not.toBeNull();
    }
  });

  it("keeps the completion bar, which nothing else expresses as one number", () => {
    render(<SyncProgressPanel progress={parseSyncProgress(rosterMeta(roster))!} />);
    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "25");
  });

  it("drops the paragraph the per-company view replaces", () => {
    render(<SyncProgressPanel progress={parseSyncProgress(rosterMeta(roster))!} />);
    expect(screen.queryByText(/reach your radar/)).not.toBeInTheDocument();
  });
});
