import { msg } from "../test/msg";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { SyncButton } from "./SyncButton";
import { AppProviders } from "../context/AppProviders";
import { api, type SyncTargets, type SystemStatus } from "../api";
import { referenceFixture, statusFixture } from "../test/fixtures";
import { ToastProvider } from "../ui/Toast";

function status(overrides: Partial<SystemStatus>): SystemStatus {
  return {
    ...statusFixture,
    db: "ok",
    last_success_at: "2026-07-13T05:00:00Z",
    last_success_age_hours: 2,
    last_run_status: "ok",
    last_run_started_at: "2026-07-13T04:00:00Z",
    last_run_finished_at: "2026-07-13T04:10:00Z",
    last_run_new: 0,
    last_run_seen: 40,
    running: false,
    manual_sync_running: false,
    manual_queued: [],
    manual_blocked: [],
    stuck_running: 0,
    stale: false,
    freshness_max_hours: 26,
    ...overrides,
  };
}

// Two clean sources and one that failed the last full run — enough to tell the
// "failed last run" preset from a plain select-all.
function targets(): SyncTargets {
  return {
    freshness_max_hours: 26,
    companies: [
      {
        slug: "google", display: "Google", adapter: "google", last_sync_at: "2026-07-13T04:00:00Z",
        age_hours: 2, stale: false, last_full_scan_at: "2026-07-13T04:00:00Z", automatic: true, last_outcome: "ok", retryable: false, coverage: null,
      },
      {
        slug: "meta", display: "Meta", adapter: "meta", last_sync_at: "2026-07-13T04:00:00Z",
        age_hours: 2, stale: false, last_full_scan_at: "2026-07-13T04:00:00Z", automatic: true, last_outcome: "ok", retryable: false, coverage: null,
      },
      {
        slug: "nvidia", display: "Nvidia", adapter: "greenhouse", last_sync_at: "2026-07-10T04:00:00Z",
        age_hours: 74, stale: true, last_full_scan_at: null, automatic: true, last_outcome: "failed", retryable: true, coverage: null,
      },
    ],
  };
}

function renderButton({ toasts = false }: { toasts?: boolean } = {}) {
  vi.spyOn(api, "stats").mockResolvedValue({
    open_total: 0, new_today: 0, reposted_today: 0, closed_today: 0, saved_total: 0, review_pending: 0, notif_unread: 0, notif_high_unread: 0, by_company: {},
  });
  const button = (
    <AppProviders>
      <SyncButton />
    </AppProviders>
  );
  return render(<MemoryRouter>{toasts ? <ToastProvider>{button}</ToastProvider> : button}</MemoryRouter>);
}

afterEach(() => vi.restoreAllMocks());

describe("SyncButton", () => {
  it("renders an idle, enabled Sync control when nothing is running", async () => {
    vi.spyOn(api, "status").mockResolvedValue(status({ running: false }));
    renderButton();
    const button = await screen.findByRole("button", { name: "Scan now" });
    await waitFor(() => expect(button).toBeEnabled());
    expect(button).toHaveTextContent("Scan now");
  });

  it("triggers a sync and enters the syncing state on click", async () => {
    vi.spyOn(api, "status").mockResolvedValue(status({ running: false }));
    const syncSpy = vi.spyOn(api, "sync").mockResolvedValue({ status: "started", companies: [], queued: [] });
    renderButton();

    const button = await screen.findByRole("button", { name: "Scan now" });
    await waitFor(() => expect(button).toBeEnabled());
    await userEvent.click(button);

    expect(syncSpy).toHaveBeenCalledTimes(1);
    // Optimistic: the control shows in-progress immediately, before the backend
    // has even written the "running" marker.
    const busy = await screen.findByRole("button", { name: "Stop scan" });
    expect(busy).toBeEnabled();
    expect(busy).toHaveAttribute("aria-busy", "true");
    expect(busy).toHaveTextContent("Stop scan");
  });

  it("says so when the trigger never landed", async () => {
    /* `triggerSync` swallows its own error so it can retire the optimistic
       bridge, so awaiting it tells this control nothing: the button would
       flash back to "Scan now" and the reader would never learn the scan had
       not started. The header owns the run, so this is where a run that never
       began has to report. */
    vi.spyOn(api, "status").mockResolvedValue(status({ running: false }));
    vi.spyOn(api, "sync").mockRejectedValue(new Error("offline"));
    renderButton();

    const button = await screen.findByRole("button", { name: "Scan now" });
    await waitFor(() => expect(button).toBeEnabled());
    await userEvent.click(button);

    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Scan now" })).toHaveTextContent("Couldn't start"));
  });

  it("a start that never landed does not silence the next run's result", async () => {
    let current = status({ running: false });
    vi.spyOn(api, "status").mockImplementation(async () => current);
    vi.spyOn(api, "sync")
      .mockRejectedValueOnce(new Error("offline"))
      .mockResolvedValue({ status: "started", companies: [], queued: [] });
    renderButton();

    const button = await screen.findByRole("button", { name: "Scan now" });
    await waitFor(() => expect(button).toBeEnabled());
    await userEvent.click(button);
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Scan now" })).toHaveTextContent("Couldn't start"));

    current = status({ running: true, manual_sync_running: true });
    await userEvent.click(screen.getByRole("button", { name: "Scan now" }));
    await screen.findByRole("button", { name: "Stop scan" });
    current = status({ running: false, last_run_new: 2 });
    expect(await screen.findByText("+2 new", {}, { timeout: 6_000 })).toBeInTheDocument();
  });

  it("says it is updating estimates after the scan, and reports the result only once they moved", async () => {
    // Sync is done when the estimates it moved are written,
    // not when the scan ends. The re-estimate runs after the pipeline, so the
    // button holds "Updating estimates…" until `/api/status` says none are left.
    const moving = status({ running: false, last_run_new: 3,
      reference: referenceFixture({ target_fp: "b2".repeat(32), pending_jobs: 380 }) });
    const done = status({ running: false, last_run_new: 3, reference: referenceFixture() });
    // Moving for the first read, then done: the finish can only arrive on a
    // timed fast poll, since a cadence change does not read again at once.
    vi.spyOn(api, "status").mockResolvedValueOnce(moving).mockResolvedValue(done);
    renderButton();

    const busy = await screen.findByRole("button", { name: msg("shell-scan-updating-estimates-aria") });
    expect(busy).toHaveTextContent(msg("shell-scan-updating-estimates"));
    expect(busy).toBeDisabled();
    expect(busy).toHaveAttribute("aria-busy", "true");
    expect(screen.queryByText("+3 new")).toBeNull();
    // The poll stays fast while estimates move, so the result lands promptly.
    expect(await screen.findByText("+3 new", {}, { timeout: 6_000 })).toBeInTheDocument();
  });

  it("reflects an in-progress run reported by /api/status", async () => {
    vi.spyOn(api, "status").mockResolvedValue(status({ running: true }));
    renderButton();
    const busy = await screen.findByRole("button", { name: "Scan in progress" });
    expect(busy).toBeDisabled();
    expect(busy).toHaveAttribute("aria-busy", "true");
    expect(busy).toHaveTextContent("Scanning…");
  });

  it("shows the climbing seen-count while a run is in progress", async () => {
    // The backend publishes last_run_seen incrementally after each company, so a
    // long full scrape reads as live progress instead of a frozen spinner.
    vi.spyOn(api, "status").mockResolvedValue(status({ running: true, last_run_seen: 340 }));
    renderButton();
    const busy = await screen.findByRole("button", { name: "Scan in progress" });
    await waitFor(() => expect(busy).toHaveTextContent("340 found"));
  });

  it("hides the seen-count until the first company lands (seen === 0)", async () => {
    vi.spyOn(api, "status").mockResolvedValue(status({ running: true, last_run_seen: 0 }));
    renderButton();
    const busy = await screen.findByRole("button", { name: "Scan in progress" });
    expect(busy).not.toHaveTextContent("found");
  });

  it("does not re-trigger while a run is already in progress", async () => {
    vi.spyOn(api, "status").mockResolvedValue(status({ running: true }));
    const syncSpy = vi.spyOn(api, "sync").mockResolvedValue({
      status: "already_running", run_id: 9, started_at: "2026-07-13T04:00:00Z", companies: [], queued: [],
    });
    renderButton();
    const busy = await screen.findByRole("button", { name: "Scan in progress" });
    fireEvent.click(busy); // disabled control: onClick must not fire
    expect(syncSpy).not.toHaveBeenCalled();
  });

  it("syncs only the picked companies and labels the run by its size", async () => {
    vi.spyOn(api, "status").mockResolvedValue(status({ running: false }));
    vi.spyOn(api, "syncTargets").mockResolvedValue(targets());
    const syncSpy = vi
      .spyOn(api, "sync")
      .mockResolvedValue({ status: "started", companies: ["meta"], queued: ["meta"] });
    renderButton();

    await userEvent.click(
      await screen.findByRole("button", { name: "Choose companies to scan" }),
    );
    await userEvent.click(await screen.findByRole("checkbox", { name: "Meta" }));
    await userEvent.click(screen.getByRole("button", { name: "Scan 1 company" }));

    expect(syncSpy).toHaveBeenCalledWith(["meta"]);
    // The live control says how much the run covers, so a 1-company sync is not
    // mistaken for a 40-minute full scrape.
    const busy = await screen.findByRole("button", { name: "Stop scan" });
    expect(busy).toHaveTextContent("1 company");
  });

  it("sends no subset when every company is picked, so the run is a real full sync", async () => {
    // An all-selected targeted run would be recorded `scope=targeted` and would
    // never clear the stale badge — the opposite of what the user just asked for.
    vi.spyOn(api, "status").mockResolvedValue(status({ running: false }));
    vi.spyOn(api, "syncTargets").mockResolvedValue(targets());
    const syncSpy = vi.spyOn(api, "sync").mockResolvedValue({ status: "started", companies: [], queued: [] });
    renderButton();

    await userEvent.click(
      await screen.findByRole("button", { name: "Choose companies to scan" }),
    );
    await userEvent.click(
      await screen.findByRole("checkbox", { name: "Select all shown companies" }),
    );
    await userEvent.click(screen.getByRole("button", { name: "Scan all companies" }));

    expect(syncSpy).toHaveBeenCalledWith([]);
  });

  it("preselects the sources that failed the last run", async () => {
    vi.spyOn(api, "status").mockResolvedValue(status({ running: false }));
    vi.spyOn(api, "syncTargets").mockResolvedValue(targets());
    const syncSpy = vi.spyOn(api, "sync").mockResolvedValue({ status: "started", companies: [], queued: [] });
    renderButton();

    await userEvent.click(
      await screen.findByRole("button", { name: "Choose companies to scan" }),
    );
    await userEvent.click(await screen.findByRole("button", { name: "Couldn't scan (1)" }));
    await userEvent.click(screen.getByRole("button", { name: "Scan 1 company" }));

    expect(syncSpy).toHaveBeenCalledWith(["nvidia"]);
  });

  // -- picking while a run is live --------------------------------------------- //
  //
  // The companies picked join the live run and are read next; there is still
  // one run at a time.

  it("adds the picked companies to a live run and says they are read next", async () => {
    vi.spyOn(api, "status").mockResolvedValue(status({ running: true }));
    vi.spyOn(api, "syncTargets").mockResolvedValue(targets());
    const syncSpy = vi.spyOn(api, "sync").mockResolvedValue({
      status: "already_running", run_id: 9, started_at: "2026-07-13T04:00:00Z", companies: [], queued: ["meta"],
    });
    renderButton({ toasts: true });

    const caret = await screen.findByRole("button", { name: msg("shell-scan-choose-aria") });
    expect(caret).toHaveAttribute("title", msg("shell-scan-add-title"));
    await userEvent.click(caret);
    expect(await screen.findByText(msg("scan-sync-scope-popover-joins-running"))).toBeInTheDocument();
    await userEvent.click(await screen.findByRole("checkbox", { name: "Meta" }));
    await userEvent.click(screen.getByRole("button", { name: "Scan 1 company" }));

    expect(syncSpy).toHaveBeenCalledWith(["meta"]);
    expect(await screen.findByText(msg("scan-sync-scope-popover-joined", { count: 1 }))).toBeInTheDocument();
    // The live run reads every company: one more at its front does not make it a one-company run.
    expect(screen.getByRole("button", { name: "Scan in progress" })).not.toHaveTextContent(
      msg("shell-scan-company-count", { count: 1 }),
    );
  });

  it("names every company rather than asking a live run for a full scan", async () => {
    // A full-scan request during a live run queues nothing: the companies
    // picked would not move to the front.
    vi.spyOn(api, "status").mockResolvedValue(status({ running: true }));
    vi.spyOn(api, "syncTargets").mockResolvedValue(targets());
    const syncSpy = vi.spyOn(api, "sync").mockResolvedValue({
      status: "already_running", run_id: 9, started_at: "2026-07-13T04:00:00Z", companies: [],
      queued: ["google", "meta", "nvidia"],
    });
    renderButton();

    await userEvent.click(await screen.findByRole("button", { name: msg("shell-scan-choose-aria") }));
    await userEvent.click(await screen.findByRole("checkbox", { name: "Select all shown companies" }));
    expect(screen.queryByRole("button", { name: "Scan all companies" })).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Scan 3 companies" }));

    expect(syncSpy).toHaveBeenCalledWith(["google", "meta", "nvidia"]);
  });

  it("widens a targeted run by the companies that join it", async () => {
    let current = status({ running: false });
    vi.spyOn(api, "status").mockImplementation(async () => current);
    vi.spyOn(api, "syncTargets").mockResolvedValue(targets());
    vi.spyOn(api, "sync")
      .mockResolvedValueOnce({ status: "started", companies: ["meta"], queued: ["meta"] })
      .mockResolvedValueOnce({
        status: "already_running", run_id: 9, started_at: "2026-07-13T04:00:00Z", companies: [], queued: ["nvidia"],
      });
    renderButton();

    await userEvent.click(await screen.findByRole("button", { name: msg("shell-scan-choose-aria") }));
    await userEvent.click(await screen.findByRole("checkbox", { name: "Meta" }));
    current = status({ running: true, manual_sync_running: true, manual_queued: ["meta"] });
    await userEvent.click(screen.getByRole("button", { name: "Scan 1 company" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Stop scan" })).toHaveTextContent(
      msg("shell-scan-company-count", { count: 1 }),
    ));

    await userEvent.click(await screen.findByRole("button", { name: msg("shell-scan-choose-aria") }));
    await userEvent.click(await screen.findByRole("checkbox", { name: "Nvidia" }));
    await userEvent.click(screen.getByRole("button", { name: "Scan 1 company" }));

    await waitFor(() => expect(screen.getByRole("button", { name: "Stop scan" })).toHaveTextContent(
      msg("shell-scan-company-count", { count: 2 }),
    ));
  });

  // -- queued is not running --------------------------------------------------- //
  //
  // A manual sync waits for the scheduler's next tick, and can wait hours behind
  // a provider backoff. A waiting sync shows no spinner and no elapsed clock:
  // a clock would count from the LAST run's start and report live work that
  // finished long ago. These are what a waiting sync is allowed to say.

  it("says queued, not syncing, while work is only waiting for the scheduler", async () => {
    vi.spyOn(api, "status").mockResolvedValue(
      status({ running: false, manual_queued: ["mistral", "openai"] }),
    );
    renderButton();

    const queued = await screen.findByRole("button", { name: "Stop queued scan" });
    // The label is the action ("Stop sync"); the STATE is the readout beside it.
    // What must never appear is the claim that a scrape is under way.
    expect(queued).toHaveTextContent("2 queued");
    expect(queued).not.toHaveTextContent("Scanning");
    expect(queued).toHaveAttribute("aria-busy", "false");
  });

  it("shows no elapsed clock or found-count for queued work", async () => {
    // Neither readout may describe the previous run: that reports live
    // progress for a run that has already finished.
    vi.spyOn(api, "status").mockResolvedValue(
      status({
        running: false,
        manual_queued: ["mistral"],
        last_run_started_at: "2026-07-13T04:00:00Z",
        last_run_seen: 4,
      }),
    );
    renderButton();

    const queued = await screen.findByRole("button", { name: "Stop queued scan" });
    expect(queued).not.toHaveTextContent("found");
    expect(queued).not.toHaveTextContent(/\d+m \d+s/);
    expect(queued).toHaveTextContent("1 queued");
  });

  it("names when a blocked queue can actually start", async () => {
    vi.spyOn(api, "status").mockResolvedValue(
      status({
        running: false,
        manual_queued: ["mistral", "openai"],
        manual_blocked: [
          { provider: "ashby", reason: "backoff", until: "2026-07-13T21:18:00Z", companies: 2 },
        ],
      }),
    );
    renderButton();

    const queued = await screen.findByRole("button", { name: "Stop queued scan" });
    await waitFor(() => expect(queued).toHaveTextContent(/2 queued · waiting until/));
  });

  it("reports an open-ended block by its reason, with no invented end time", async () => {
    vi.spyOn(api, "status").mockResolvedValue(
      status({
        running: false,
        manual_queued: ["meta"],
        manual_blocked: [
          { provider: "meta", reason: "policy_denied", until: null, companies: 1 },
        ],
      }),
    );
    renderButton();

    const queued = await screen.findByRole("button", { name: "Stop queued scan" });
    // Said by its reason's code, never the raw enum ("policy denied").
    await waitFor(() => expect(queued).toHaveTextContent(msg("shell-scan-queued-blocked", { count: 1, reason: "policy_denied" })));
    expect(queued).not.toHaveTextContent(/policy denied|waiting until/);
  });

  it("says why the background service holds a queued scan, before any provider block", async () => {
    const held = (reason: string) => ({
      key: "scan", job: "scan", state: "waiting" as const, reason, since: "2026-07-13T05:00:00Z",
      next_at: null, run_id: null, progress: null, waiting: null, queued: 1,
    });
    vi.spyOn(api, "status").mockResolvedValue(
      status({
        running: false,
        manual_queued: ["meta"],
        manual_blocked: [{ provider: "meta", reason: "backoff", until: "2026-07-13T21:18:00Z", companies: 1 }],
        jobs: [held("preflight_failed")],
      }),
    );
    renderButton();

    const queued = await screen.findByRole("button", { name: "Stop queued scan" });
    await waitFor(() => expect(queued).toHaveTextContent(msg("shell-scan-waiting", { count: 1, reason: "preflight_failed" })));
    expect(queued).not.toHaveTextContent(/waiting until/);
  });

  it("says so when the background service is not running at all", async () => {
    vi.spyOn(api, "status").mockResolvedValue(
      status({
        running: false,
        manual_queued: ["meta"],
        jobs: [{
          key: "scan", job: "scan", state: "idle", reason: "supervisor_stale", since: "2026-07-13T05:00:00Z",
          next_at: null, run_id: null, progress: null, waiting: null, queued: 1,
        }],
        supervisor: { state: "stale", since: "2026-07-13T05:00:00Z", reason: null },
      }),
    );
    renderButton();

    const queued = await screen.findByRole("button", { name: "Stop queued scan" });
    await waitFor(() => expect(queued).toHaveTextContent(msg("shell-scan-waiting", { count: 1, reason: "supervisor_stale" })));
  });

  it("does not start a second sync while work is queued", async () => {
    // Queued work owns the control: clicking cancels the queue rather than
    // stacking another request behind it, and the scope picker is not offered.
    vi.spyOn(api, "status").mockResolvedValue(
      status({ running: false, manual_queued: ["mistral"] }),
    );
    const syncSpy = vi.spyOn(api, "sync").mockResolvedValue({
      status: "already_running", run_id: 9, started_at: "2026-07-13T04:00:00Z", companies: [], queued: [],
    });
    const cancelSpy = vi
      .spyOn(api, "cancelSync")
      .mockResolvedValue({ status: "cancelled", pid: null, run_id: null, dequeued: ["mistral"] });
    renderButton();

    const queued = await screen.findByRole("button", { name: "Stop queued scan" });
    fireEvent.click(queued);

    await waitFor(() => expect(cancelSpy).toHaveBeenCalledTimes(1));
    expect(syncSpy).not.toHaveBeenCalled();
    expect(screen.queryByRole("button", { name: "Choose companies to scan" })).toBeNull();
  });

  it("can cancel a queued sync that has not started", async () => {
    // Stop must stay reachable: the queue is exactly when a user changes their
    // mind, and there is no process to kill yet.
    vi.spyOn(api, "status").mockResolvedValue(
      status({ running: false, manual_sync_running: false, manual_queued: ["mistral"] }),
    );
    const cancelSpy = vi
      .spyOn(api, "cancelSync")
      .mockResolvedValue({ status: "cancelled", pid: null, run_id: null, dequeued: ["mistral"] });
    renderButton();

    await userEvent.click(await screen.findByRole("button", { name: "Stop queued scan" }));

    await waitFor(() => expect(cancelSpy).toHaveBeenCalledTimes(1));
  });

  it("stops a manual sync from the same control", async () => {
    vi.spyOn(api, "status").mockResolvedValue(status({ running: true, manual_sync_running: true }));
    const cancelSpy = vi.spyOn(api, "cancelSync").mockResolvedValue({ status: "cancelled", pid: 123, run_id: 9, dequeued: [] });
    const syncSpy = vi.spyOn(api, "sync").mockResolvedValue({
      status: "already_running", run_id: 9, started_at: "2026-07-13T04:00:00Z", companies: [], queued: [],
    });
    renderButton();

    const stop = await screen.findByRole("button", { name: "Stop scan" });
    expect(stop).toBeEnabled();
    await userEvent.click(stop);

    await waitFor(() => expect(cancelSpy).toHaveBeenCalledTimes(1));
    expect(syncSpy).not.toHaveBeenCalled();
  });

  it("a stopped run reads Stopped once it is gone, never its result", async () => {
    // The run's end is a pending -> idle edge like any other, and that edge
    // would report the run's count over the stop that ended it.
    let current = status({ running: true, manual_sync_running: true, last_run_new: 4 });
    vi.spyOn(api, "status").mockImplementation(async () => current);
    vi.spyOn(api, "cancelSync").mockImplementation(async () => {
      current = status({ running: false, last_run_new: 4 });
      return { status: "cancelled", pid: 123, run_id: 9, dequeued: [] };
    });
    renderButton();

    await userEvent.click(await screen.findByRole("button", { name: "Stop scan" }));

    const idle = await screen.findByRole("button", { name: "Scan now" });
    await waitFor(() => expect(idle).toHaveTextContent("Stopped"));
    expect(screen.queryByText("+4 new")).toBeNull();
  });

  it("a stopped run still reported for another poll reads Stopped when it goes", async () => {
    let current = status({ running: true, manual_sync_running: true, last_run_new: 4 });
    vi.spyOn(api, "status").mockImplementation(async () => current);
    const cancelSpy = vi.spyOn(api, "cancelSync")
      .mockResolvedValue({ status: "cancelled", pid: 123, run_id: 9, dequeued: [] });
    renderButton();

    await userEvent.click(await screen.findByRole("button", { name: "Stop scan" }));
    await waitFor(() => expect(cancelSpy).toHaveBeenCalledTimes(1));
    current = status({ running: false, last_run_new: 4 });

    const idle = await screen.findByRole("button", { name: "Scan now" }, { timeout: 6_000 });
    await waitFor(() => expect(idle).toHaveTextContent("Stopped"));
    expect(screen.queryByText("+4 new")).toBeNull();
  });

  it("a stop that did not land says so on the control, and the run goes on", async () => {
    const unhandled: unknown[] = [];
    const onRejection = (reason: unknown) => { unhandled.push(reason); };
    process.on("unhandledRejection", onRejection);
    try {
      vi.spyOn(api, "status").mockResolvedValue(status({ running: true, manual_sync_running: true }));
      vi.spyOn(api, "cancelSync").mockRejectedValue(new Error("offline"));
      renderButton();

      await userEvent.click(await screen.findByRole("button", { name: "Stop scan" }));

      const stop = await screen.findByRole("button", { name: "Stop scan" });
      await waitFor(() => expect(stop).toHaveTextContent(msg("shell-scan-could-not-stop")));
      expect(stop).toBeEnabled();
      await new Promise((r) => setTimeout(r, 20));
      expect(unhandled).toEqual([]);
    } finally {
      process.off("unhandledRejection", onRejection);
    }
  });

  it("a new run never shows the last run's result on its stop control", async () => {
    let current = status({ running: true, manual_sync_running: true, last_run_new: 0 });
    vi.spyOn(api, "status").mockImplementation(async () => current);
    vi.spyOn(api, "sync").mockResolvedValue({ status: "started", companies: [], queued: [] });
    renderButton();
    await screen.findByRole("button", { name: "Stop scan" });
    current = status({ running: false, last_run_new: 2 });
    expect(await screen.findByText("+2 new", {}, { timeout: 6_000 })).toBeInTheDocument();

    current = status({ running: true, manual_sync_running: true });
    await userEvent.click(screen.getByRole("button", { name: "Scan now" }));

    await waitFor(() => expect(screen.getByRole("button", { name: "Stop scan" })).toHaveTextContent("Stop scan"));
    expect(screen.queryByText("+2 new")).toBeNull();
  });
});
