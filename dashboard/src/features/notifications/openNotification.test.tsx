/* Opening a role notification navigates first.
 *
 * Awaiting mark-read and the feed re-read before opening the role would let a
 * write or read that never answers leave the row inert, and one that answers
 * after the reader moved on navigate late. Marking read is incidental to
 * opening, so it runs after the navigation, in the background, and says so
 * when it fails. Real screen and controller; the api
 * is mocked at the boundary and `openJob` is the navigation seam. */
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api, type Notification, type NotificationList } from "../../api";
import { ApiError } from "../../api/transport";
import { ToastProvider } from "../../ui/Toast";
import { NotificationScreen, PAGE_SIZE } from "./NotificationScreen";

const nav = vi.hoisted(() => ({ openJob: vi.fn() }));
vi.mock("../../context/JobWorkspace", () => ({ useJobActions: () => ({ openJob: nav.openJob }) }));
vi.mock("../../context/MissionState", () => ({ useMissionActions: () => ({ refreshStats: vi.fn() }) }));
vi.mock("../../context/SyncState", () => ({ useSyncEpoch: () => ({ notificationVersion: 0 }) }));
vi.mock("../../api", () => ({
  api: {
    notifications: vi.fn(),
    markNotificationRead: vi.fn(),
    markAllNotificationsRead: vi.fn(),
    markNotificationsUnread: vi.fn(),
    dismissNotification: vi.fn(),
    restoreNotification: vi.fn(),
  },
}));

const never = <T,>() => new Promise<T>(() => {});

const row = (over: Partial<Notification> & { id: number }): Notification => ({
  created_at: "2026-07-13T00:00:00Z", priority: "high", category: "pursuit_due",
  title: `Notification ${over.id}`, body: null, job_id: null, company: null, run_id: null,
  source_type: "pursuit", read_at: null, dismissed_at: null, meta: {}, ...over,
});
const feed = (): NotificationList => ({
  total: 2, limit: PAGE_SIZE, offset: 0, unread_count: 1, high_unread_count: 1,
  category_counts: { pursuit_due: 2 },
  items: [
    row({ id: 1, title: "Follow up with OpenAI", job_id: 101, company: "openai" }),
    row({ id: 2, title: "Already read at Google", job_id: 202, company: "google", read_at: "2026-07-13T01:00:00Z" }),
  ],
});

const mount = () =>
  render(
    <ToastProvider>
      <MemoryRouter initialEntries={["/notifications"]}>
        <NotificationScreen />
      </MemoryRouter>
    </ToastProvider>,
  );

describe("opening a role notification", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(api.notifications).mockImplementation(async () => feed());
  });

  it("opens the role at once while the read mark never answers", async () => {
    vi.mocked(api.markNotificationRead).mockImplementation(() => never());
    const user = userEvent.setup();
    mount();
    await user.click(await screen.findByText("Follow up with OpenAI"));
    expect(nav.openJob).toHaveBeenCalledWith(101, "openai");
    expect(api.markNotificationRead).toHaveBeenCalledWith(1, true);
  });

  it("opens the role at once while the feed re-read never answers", async () => {
    vi.mocked(api.markNotificationRead).mockImplementation(async (id) => row({ id, read_at: "2026-07-13T02:00:00Z" }));
    const user = userEvent.setup();
    mount();
    await screen.findByText("Follow up with OpenAI");
    vi.mocked(api.notifications).mockImplementation(() => never());
    await user.click(screen.getByText("Follow up with OpenAI"));
    expect(nav.openJob).toHaveBeenCalledWith(101, "openai");
  });

  it("still opens the role when the read mark fails, and says so", async () => {
    vi.mocked(api.markNotificationRead).mockRejectedValue(new ApiError("notification not found", 404));
    const user = userEvent.setup();
    mount();
    await user.click(await screen.findByText("Follow up with OpenAI"));
    expect(nav.openJob).toHaveBeenCalledWith(101, "openai");
    expect(await screen.findByText("Couldn't mark it read")).toBeInTheDocument();
  });

  it("navigates once, never again when a slow read mark answers later", async () => {
    let resolve!: (v: Notification) => void;
    vi.mocked(api.markNotificationRead).mockImplementation(() => new Promise((r) => { resolve = r; }));
    const user = userEvent.setup();
    const view = mount();
    await user.click(await screen.findByText("Follow up with OpenAI"));
    expect(nav.openJob).toHaveBeenCalledTimes(1);
    view.unmount(); // the reader went elsewhere
    await act(async () => { resolve(row({ id: 1, read_at: "2026-07-13T02:00:00Z" })); });
    expect(nav.openJob).toHaveBeenCalledTimes(1);
  });

  it("opens a role already read with no write", async () => {
    const user = userEvent.setup();
    mount();
    await user.click(await screen.findByText("Already read at Google"));
    await waitFor(() => expect(nav.openJob).toHaveBeenCalledWith(202, "google"));
    expect(api.markNotificationRead).not.toHaveBeenCalled();
  });
});
