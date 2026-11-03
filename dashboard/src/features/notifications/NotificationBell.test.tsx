/* The topbar bell opens a role first, then marks it read.
 *
 * A read mark can fail (a reminder the reconcile deleted while the popover was
 * open answers 404, so does a row another tab dismissed, and the API refuses
 * while it restarts) or never answer. Awaiting it before opening the role
 * would open nothing and leave an unhandled rejection, or leave the row
 * inert. Real bell and Popover; the api is mocked
 * at the boundary and `openJob` is the navigation seam. */
import { msg } from "../../test/msg";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api, type Notification, type NotificationList } from "../../api";
import { activate } from "../../copy/activate";
import { ApiError } from "../../api/transport";
import { ToastProvider } from "../../ui/Toast";
import { NotificationBell } from "./NotificationBell";

const nav = vi.hoisted(() => ({ openJob: vi.fn(), refreshStats: vi.fn() }));
const counts = vi.hoisted(() => ({ notif_unread: 1, notif_high_unread: 0 }));
vi.mock("../../context/JobWorkspace", () => ({ useJobActions: () => ({ openJob: nav.openJob }) }));
vi.mock("../../context/MissionState", () => ({
  useMissionStats: () => ({ ...counts }),
  useMissionActions: () => ({ refreshStats: nav.refreshStats }),
}));
vi.mock("../../context/SyncState", () => ({ useSyncEpoch: () => ({ notificationVersion: 0 }) }));
vi.mock("../../api", () => ({ api: { notifications: vi.fn(), markNotificationRead: vi.fn() } }));

const never = <T,>() => new Promise<T>(() => {});

const row = (over: Partial<Notification> & { id: number }): Notification => ({
  created_at: "2026-07-13T00:00:00Z", priority: "high", category: "pursuit_due",
  title: `Notification ${over.id}`, body: null, job_id: null, company: null, run_id: null,
  source_type: "pursuit", read_at: null, dismissed_at: null, meta: {}, ...over,
});
const feed = (): NotificationList => ({
  total: 3, limit: 15, offset: 0, unread_count: 2, high_unread_count: 1, category_counts: {},
  items: [
    row({ id: 1, title: "Follow up with OpenAI", job_id: 101, company: "openai" }),
    row({ id: 2, title: "Already read at Google", job_id: 202, company: "google", read_at: "2026-07-13T01:00:00Z" }),
    row({ id: 3, title: "Scan finished", category: "sync_done", source_type: "run" }),
  ],
});

const unhandled: unknown[] = [];
const onRejection = (reason: unknown) => { unhandled.push(reason); };

const openBell = async () => {
  const user = userEvent.setup();
  render(
    <ToastProvider>
      <MemoryRouter><NotificationBell /></MemoryRouter>
    </ToastProvider>,
  );
  await user.click(screen.getByRole("button", { name: /^Notifications/ }));
  return user;
};

describe("NotificationBell", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    Object.assign(counts, { notif_unread: 1, notif_high_unread: 0 });
    unhandled.length = 0;
    process.on("unhandledRejection", onRejection);
    vi.mocked(api.notifications).mockImplementation(async () => feed());
  });
  afterEach(() => { process.off("unhandledRejection", onRejection); });

  it("turns red from the header counts, and reads no rows until it opens", async () => {
    // The counts follow every read and dismissal on any screen; a red state
    // kept from the bell's own last read would outlive "Mark all read".
    counts.notif_high_unread = 1;
    const view = render(
      <ToastProvider>
        <MemoryRouter><NotificationBell /></MemoryRouter>
      </ToastProvider>,
    );
    const bell = screen.getByRole("button", { name: /^Notifications/ });
    expect(bell).toHaveClass("has-high");
    expect(api.notifications).not.toHaveBeenCalled();

    counts.notif_high_unread = 0;
    view.rerender(
      <ToastProvider>
        <MemoryRouter><NotificationBell /></MemoryRouter>
      </ToastProvider>,
    );
    expect(bell).not.toHaveClass("has-high");
  });

  it("opens the role and closes the panel while the read mark never answers", async () => {
    vi.mocked(api.markNotificationRead).mockImplementation(() => never());
    const user = await openBell();
    await user.click(await screen.findByRole("button", { name: /Follow up with OpenAI/ }));
    expect(nav.openJob).toHaveBeenCalledWith(101, "openai");
    await waitFor(() => expect(document.querySelector(".notif-popover")).toBeNull());
    expect(api.markNotificationRead).toHaveBeenCalledWith(1, true);
  });

  it("opens the role when the read mark fails, says so, and leaves no unhandled rejection", async () => {
    vi.mocked(api.markNotificationRead).mockRejectedValue(new ApiError("notification not found", 404));
    const user = await openBell();
    await user.click(await screen.findByRole("button", { name: /Follow up with OpenAI/ }));
    expect(nav.openJob).toHaveBeenCalledWith(101, "openai");
    expect(await screen.findByText(msg("shell-notif-mark-read-failed"))).toBeInTheDocument();
    await new Promise((r) => setTimeout(r, 20));
    expect(unhandled).toEqual([]);
  });

  it("says its list could not be read, not that there is nothing in it", async () => {
    vi.mocked(api.notifications).mockRejectedValue(new Error("offline"));
    await openBell();
    expect(await screen.findByRole("alert")).toHaveTextContent(msg("shell-bell-load-failed"));
    expect(screen.queryByText(msg("shell-bell-empty"))).toBeNull();
  });

  it("says there is nothing yet when a read finds nothing", async () => {
    // The control for the test above: the empty line is for a list that was read.
    vi.mocked(api.notifications).mockResolvedValue({ ...feed(), total: 0, unread_count: 0, high_unread_count: 0, items: [] });
    await openBell();
    expect(await screen.findByText(msg("shell-bell-empty"))).toBeInTheDocument();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("marks a role read once it opened it", async () => {
    vi.mocked(api.markNotificationRead).mockImplementation(async (id) => row({ id, read_at: "2026-07-13T02:00:00Z" }));
    const user = await openBell();
    await user.click(await screen.findByRole("button", { name: /Follow up with OpenAI/ }));
    await waitFor(() => expect(nav.refreshStats).toHaveBeenCalled());
    expect(api.markNotificationRead).toHaveBeenCalledWith(1, true);
  });

  it("says unread in words, not only in colour, and only on unread rows", async () => {
    // Fail-first: unread was the `unread` class alone, which a screen reader never hears.
    await openBell();
    const word = msg("shell-bell-row-unread");
    const unreadRow = await screen.findByRole("button", { name: /Follow up with OpenAI/ });
    const readRow = screen.getByRole("button", { name: /Already read at Google/ });
    expect(unreadRow).toHaveAccessibleName(expect.stringContaining(word));
    expect(readRow).not.toHaveAccessibleName(expect.stringContaining(word));
  });

  it("opens a role already read with no write", async () => {
    const user = await openBell();
    await user.click(await screen.findByRole("button", { name: /Already read at Google/ }));
    expect(nav.openJob).toHaveBeenCalledWith(202, "google");
    expect(api.markNotificationRead).not.toHaveBeenCalled();
  });

  it("says a notification in the reader's language once its words arrive", async () => {
    await activate("en-XA");
    try {
      const said = row({
        id: 4, category: "closed", title: "OpenAI closed a role you saved", body: "Research Manager",
        meta: { say: { title: { k: "notif-closed", p: { company: "OpenAI" } }, body: ["Research Manager"] } },
      });
      vi.mocked(api.notifications).mockImplementation(async () => ({ ...feed(), items: [said] }));
      const user = userEvent.setup();
      render(
        <ToastProvider>
          <MemoryRouter><NotificationBell /></MemoryRouter>
        </ToastProvider>,
      );
      await user.click(document.querySelector<HTMLButtonElement>(".bell-btn")!);
      // The stored English is not what an en-XA reader is left with.
      expect(await screen.findByText(/^⟦OpenAI çļöšéð/)).toBeInTheDocument();
      expect(screen.queryByText("OpenAI closed a role you saved")).not.toBeInTheDocument();
      expect(screen.getByText("Research Manager")).toBeInTheDocument();
    } finally {
      await activate("en");
    }
  });

  it("marks a notification with nowhere to go read and keeps the panel open", async () => {
    vi.mocked(api.markNotificationRead).mockImplementation(async (id) => row({ id, read_at: "2026-07-13T02:00:00Z" }));
    const user = await openBell();
    await user.click(await screen.findByRole("button", { name: /Scan finished/ }));
    await waitFor(() => expect(api.markNotificationRead).toHaveBeenCalledWith(3, true));
    expect(nav.openJob).not.toHaveBeenCalled();
    expect(document.querySelector(".notif-popover")).not.toBeNull();
  });
});
