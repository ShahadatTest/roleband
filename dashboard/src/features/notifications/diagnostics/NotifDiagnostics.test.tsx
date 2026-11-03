import { render as rtlRender, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactElement } from "react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi, beforeEach } from "vitest";
import { notifDetailText, notifSummaryText, parseDiagnostics } from "./NotifDiagnostics";
import { NotificationScreen } from "../NotificationScreen";
import type { Notification, NotificationList } from "../../../api";

// The center reads its filters from the URL, so every render needs a router.
const render = (ui: ReactElement) => rtlRender(<MemoryRouter>{ui}</MemoryRouter>);

/** One degraded source: Apple's search healthy, its detail endpoint 401, one drift alert. */
const DIAGNOSTICS = {
  run_id: 20,
  run_status: "ok",
  started_at: "2026-07-14T14:00:00+00:00",
  finished_at: "2026-07-14T14:08:00+00:00",
  duration_seconds: 480,
  totals: { jobs_seen: 749, jobs_new: 10, jobs_closed: 5, sources_ok: 1, sources_total: 2 },
  sources: [
    { source: "apple", scanned: 2442, kept: 389, new: 4, closed: 1, errors: [], drift_count: 1, duration_seconds: 244 },
    { source: "google", scanned: 553, kept: 191, new: 6, closed: 4, errors: [], drift_count: 0, duration_seconds: 61 },
  ],
  drift: [
    {
      source: "apple:apple",
      message: "detail access blocked after CSRF refresh; hydration disabled for run",
      context: { status: 401, req: "200672287-0836" },
    },
  ],
  errors: [],
  notes: null,
};

const warningNotif: Notification = {
  id: 11,
  created_at: "2026-07-14T14:08:35Z",
  priority: "normal",
  category: "sync_warning",
  title: "Sync completed with warnings",
  body: "Finished at 2026-07-14 14:08 UTC after 8m 0s. Affected source: apple. 749 found / 10 created",
  job_id: null,
  company: null,
  run_id: 20,
  source_type: "run",
  read_at: null,
  dismissed_at: null,
  meta: { sync_state: "warning", diagnostics: DIAGNOSTICS },
};

const plainNotif: Notification = {
  id: 1,
  created_at: "2026-07-14T00:00:00Z",
  priority: "high",
  category: "comp_up",
  title: "Comp up at OpenAI",
  body: "Staff PM",
  job_id: 7,
  company: "openai",
  run_id: 1,
  source_type: "event",
  read_at: null,
  dismissed_at: null,
  meta: {},
};

describe("parseDiagnostics", () => {
  it("returns null when the notification carries no diagnostics block", () => {
    expect(parseDiagnostics({})).toBeNull();
    expect(parseDiagnostics({ sync_state: "success" })).toBeNull();
    expect(parseDiagnostics(undefined)).toBeNull();
  });

  it("survives malformed meta rather than crashing the notification list", () => {
    // meta is untyped JSONB; a malformed or partial row must not take the page down.
    expect(parseDiagnostics({ diagnostics: "nope" })).toBeNull();
    expect(parseDiagnostics({ diagnostics: [] })).toBeNull();

    const partial = parseDiagnostics({ diagnostics: { sources: [{ source: "apple" }], drift: [null, 3] } });
    expect(partial).not.toBeNull();
    expect(partial!.run_id).toBeNull();
    expect(partial!.sources[0]).toMatchObject({ source: "apple", scanned: 0, kept: 0 });
    expect(partial!.drift).toEqual([]);
  });

  it("keeps the drift context that makes an alert debuggable", () => {
    const d = parseDiagnostics(warningNotif.meta)!;
    expect(d.drift[0].context).toEqual({ status: 401, req: "200672287-0836" });
    expect(d.sources.map((s) => s.source)).toEqual(["apple", "google"]);
  });
});

describe("copy text", () => {
  it("summary text is the short form: title, body, and provenance", () => {
    const text = notifSummaryText(warningNotif);
    expect(text).toContain("Sync completed with warnings");
    expect(text).toContain("Affected source: apple");
    expect(text).toContain("sync_warning");
    // The short form must NOT drag in the whole diagnostics payload.
    expect(text).not.toContain("200672287-0836");
  });

  it("detail text carries the status code, req id, and per-source table", () => {
    const text = notifDetailText(warningNotif);
    expect(text).toContain("Sync completed with warnings");
    expect(text).toContain("Run #20");
    expect(text).toContain("status=401");
    expect(text).toContain("req=200672287-0836");
    expect(text).toContain("hydration disabled for run");
    expect(text).toContain("apple | 2442 | 389");
    expect(text).toContain("1 drift");
  });

  it("detail text degrades to the summary when there are no diagnostics", () => {
    expect(notifDetailText(plainNotif)).toBe(notifSummaryText(plainNotif));
  });
});

const listFixture = (): NotificationList => ({
  total: 2,
  limit: 100,
  offset: 0,
  unread_count: 2,
  high_unread_count: 1, category_counts: {},
  items: [warningNotif, plainNotif],
});

const openJob = vi.fn();

vi.mock("../../../context/JobWorkspace", () => ({ useJobActions: () => ({ openJob }) }));
vi.mock("../../../context/MissionState", () => ({ useMissionActions: () => ({ refreshStats: vi.fn() }) }));
vi.mock("../../../context/SyncState", () => ({ useSyncEpoch: () => ({ notificationVersion: 0 }) }));

vi.mock("../../../api", () => ({
  api: {
    notifications: vi.fn(async () => listFixture()),
    markNotificationRead: vi.fn(async () => ({})),
    dismissNotification: vi.fn(async () => ({})),
    markAllNotificationsRead: vi.fn(async () => ({ updated: 0, undoable: true, ids: [] })),
  },
}));

describe("NotificationScreen diagnostics disclosure", () => {
  const writeText = vi.fn(async (_text: string) => {});

  /**
   * userEvent.setup() installs its own clipboard stub, so ours has to land after
   * it or it gets clobbered. jsdom also exposes navigator.clipboard as getter-only.
   */
  const setupUser = () => {
    const user = userEvent.setup();
    Object.defineProperty(navigator, "clipboard", {
      value: { writeText },
      configurable: true,
      writable: true,
    });
    return user;
  };

  /** jsdom does not implement document.execCommand at all, so define it rather than spy. */
  const stubExecCommand = (result: boolean) => {
    const exec = vi.fn(() => result);
    Object.defineProperty(document, "execCommand", { value: exec, configurable: true, writable: true });
    return exec;
  };

  beforeEach(() => {
    writeText.mockClear();
    openJob.mockClear();
  });

  it("hides diagnostics until the user asks for them", async () => {
    render(<NotificationScreen />);
    await screen.findByText("Sync completed with warnings");

    const toggle = screen.getByRole("button", { name: "Show details" });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByText(/hydration disabled for run/)).not.toBeInTheDocument();

    // A notification with nothing to expand gets no disclosure control.
    expect(screen.getAllByRole("button", { name: /Show details/ })).toHaveLength(1);
  });

  it("expands into the per-source table and the drift status code", async () => {
    const user = setupUser();
    render(<NotificationScreen />);
    await screen.findByText("Sync completed with warnings");

    await user.click(screen.getByRole("button", { name: "Show details" }));

    expect(await screen.findByText(/hydration disabled for run/)).toBeInTheDocument();
    expect(screen.getByText(/status=401 req=200672287-0836/)).toBeInTheDocument();
    // The per-source table names the healthy sources too, so the user can see
    // that Apple alone was degraded and the run was otherwise fine.
    expect(screen.getByRole("row", { name: /apple 2442 389/ })).toBeInTheDocument();
    expect(screen.getByRole("row", { name: /google 553 191/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Hide details" })).toHaveAttribute("aria-expanded", "true");
  });

  it("copies the short text from the collapsed row", async () => {
    const user = setupUser();
    render(<NotificationScreen />);
    await screen.findByText("Sync completed with warnings");

    await user.click(screen.getAllByRole("button", { name: "Copy notification text" })[0]);

    await waitFor(() => expect(writeText).toHaveBeenCalledTimes(1));
    const copied = writeText.mock.calls[0][0];
    expect(copied).toContain("Sync completed with warnings");
    expect(copied).not.toContain("200672287-0836");
  });

  it("copies the full diagnostics from the expanded panel", async () => {
    const user = setupUser();
    render(<NotificationScreen />);
    await screen.findByText("Sync completed with warnings");

    await user.click(screen.getByRole("button", { name: "Show details" }));
    await user.click(screen.getByRole("button", { name: "Copy full details" }));

    await waitFor(() => expect(writeText).toHaveBeenCalledTimes(1));
    const copied = writeText.mock.calls[0][0];
    expect(copied).toContain("status=401");
    expect(copied).toContain("apple | 2442 | 389");
  });

  it("says so when the browser blocks the clipboard instead of claiming success", async () => {
    const user = setupUser();
    // Chrome denies clipboard writes to non-user-activated / non-secure contexts,
    // and the execCommand fallback can be denied too. Claiming "Copied" over a
    // clipboard that never received the text is worse than admitting the failure.
    writeText.mockRejectedValueOnce(new Error("NotAllowedError"));
    const exec = stubExecCommand(false);

    render(<NotificationScreen />);
    await screen.findByText("Sync completed with warnings");
    await user.click(screen.getByRole("button", { name: "Show details" }));
    await user.click(screen.getByRole("button", { name: "Copy summary" }));

    expect(exec).toHaveBeenCalledWith("copy");
    expect(await screen.findByText("Copy blocked")).toBeInTheDocument();
    expect(screen.queryByText("Copied")).not.toBeInTheDocument();
  });

  it("falls back to execCommand when the async clipboard API is unavailable", async () => {
    const user = setupUser();
    writeText.mockRejectedValueOnce(new Error("NotAllowedError"));
    const exec = stubExecCommand(true);

    render(<NotificationScreen />);
    await screen.findByText("Sync completed with warnings");
    await user.click(screen.getByRole("button", { name: "Show details" }));
    await user.click(screen.getByRole("button", { name: "Copy full details" }));

    expect(exec).toHaveBeenCalledWith("copy");
    expect(await screen.findByText("Copied")).toBeInTheDocument();
  });

  it("clicking a run notification expands it instead of navigating nowhere", async () => {
    const user = setupUser();
    render(<NotificationScreen />);
    const row = await screen.findByText("Sync completed with warnings");

    await user.click(row);

    expect(await screen.findByText(/hydration disabled for run/)).toBeInTheDocument();
    expect(openJob).not.toHaveBeenCalled();
  });

  it("clicking a job notification opens the job with its company for the URL", async () => {
    const user = setupUser();
    render(<NotificationScreen />);
    const row = await screen.findByText("Comp up at OpenAI");

    await user.click(row);

    // The company slug rides along so the click lands on the company-scoped
    // position URL (/company/openai/job/7).
    await waitFor(() => expect(openJob).toHaveBeenCalledWith(7, "openai"));
  });
});
