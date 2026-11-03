import { msg } from "../../test/msg";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import type { ReactElement } from "react";
import { describe, expect, it, vi } from "vitest";
import { NOTIF_ICON, NotifIcon, notifIconMeta } from "./notifIcons";
import { NotificationScreen } from "./NotificationScreen";
import { api, type NotificationList } from "../../api";

// The center reads its filters from the URL, so it needs a router in scope.
const withRouter = (ui: ReactElement) => <MemoryRouter>{ui}</MemoryRouter>;

describe("notifIconMeta", () => {
  it("maps each known category to a distinct icon + label", () => {
    expect(notifIconMeta("comp_up")).toEqual({ icon: "trendUp", label: "Posted range went up" });
    expect(notifIconMeta("daily_digest")).toEqual({ icon: "sparkle", label: "New roles for you" });
    expect(notifIconMeta("pursuit_due")).toEqual({ icon: "clock", label: "Reminder" });
    expect(notifIconMeta("sync_started")).toEqual({ icon: "activity", label: "Scanning" });
    expect(notifIconMeta("sync_warning")).toEqual({ icon: "alertCircle", label: "Scan finished with problems" });
    // Out of RoleBand's own time is not a problem, so it never wears that label.
    expect(notifIconMeta("sync_unfinished")).toEqual({ icon: "pause", label: "Scan ran out of time" });
    expect(notifIconMeta("changed")).toEqual({ icon: "edit", label: "Saved role changed" });
    expect(notifIconMeta("coverage")).toEqual({
      icon: "eyeOff",
      label: "Coverage problem at a company you follow",
    });

    // Every mapped category resolves to a non-empty icon name and a distinct one
    // per category (the whole point: no two kinds share a glyph).
    const icons = Object.values(NOTIF_ICON).map((m) => m.icon);
    expect(new Set(icons).size).toBe(icons.length);
    expect(icons.every(Boolean)).toBe(true);
  });

  it("names a scan the person stopped as stopped, whatever it is filed under", () => {
    // The backend files a stopped scan under sync_unfinished, or sync_warning
    // when a company it read had a problem: neither "ran out of time" nor
    // "finished" is true of it.
    const stopped = { stopped_by_user: true };
    expect(notifIconMeta("sync_unfinished", stopped)).toEqual({ icon: "pause", label: "Scan stopped" });
    expect(notifIconMeta("sync_warning", stopped)).toEqual({ icon: "alertCircle", label: "Scan stopped" });
    expect(notifIconMeta("sync_unfinished", {})).toEqual({ icon: "pause", label: "Scan ran out of time" });
  });

  it("falls back to a plain bell for unknown categories, never the raw category", () => {
    expect(notifIconMeta("some_future_kind")).toEqual({ icon: "bell", label: msg("shell-notif-other") });
  });
});

describe("NotifIcon", () => {
  it("renders the category label as an accessible image", () => {
    render(<NotifIcon category="comp_up" />);
    const el = screen.getByRole("img", { name: "Posted range went up" });
    expect(el).toHaveAttribute("title", "Posted range went up");
  });
});

const listFixture = (): NotificationList => ({
  total: 5,
  limit: 100,
  offset: 0,
  unread_count: 5,
  high_unread_count: 1, category_counts: {},
  items: [
    { id: 10, created_at: "2026-07-13T00:03:00Z", priority: "normal", category: "sync_started", title: "Sync started", body: "3 sources queued", job_id: null, run_id: 7, source_type: "run", read_at: null, dismissed_at: null, company: null, meta: { sync_state: "running" } },
    { id: 11, created_at: "2026-07-13T00:02:00Z", priority: "normal", category: "sync_warning", title: "Sync completed with warnings", body: "Apple drift alert", job_id: null, run_id: 7, source_type: "run", read_at: null, dismissed_at: null, company: null, meta: { sync_state: "warning" } },
    { id: 1, created_at: "2026-07-13T00:00:00Z", priority: "high", category: "comp_up", title: "Comp up at OpenAI", body: "Staff PM", job_id: 1, run_id: 1, source_type: "event", read_at: null, dismissed_at: null, company: null, meta: {} },
    { id: 2, created_at: "2026-07-13T00:00:00Z", priority: "normal", category: "daily_digest", title: "4 new matches today", body: "Strong fit: Staff PM at Google", job_id: null, run_id: null, source_type: "digest", read_at: null, dismissed_at: null, company: null, meta: { day: "2026-07-13", count: 4, ranked: true, companies: ["google"], top: [{ job_id: 9, company: "google", title: "Staff PM, Ads", fit: 0.71, fit_band: "Strong" }] } },
    { id: 3, created_at: "2026-07-13T00:00:00Z", priority: "low", category: "changed", title: "Role changed at Apple", body: "IC5", job_id: 3, run_id: 1, source_type: "event", read_at: null, dismissed_at: null, company: null, meta: {} },
  ],
});

const appState = vi.hoisted(() => ({ notificationVersion: 0 }));

vi.mock("../../context/JobWorkspace", () => ({ useJobActions: () => ({ openJob: vi.fn() }) }));
vi.mock("../../context/MissionState", () => ({ useMissionActions: () => ({ refreshStats: vi.fn() }) }));
vi.mock("../../context/SyncState", () => ({
  useSyncEpoch: () => ({ notificationVersion: appState.notificationVersion }),
}));

vi.mock("../../api", () => ({
  api: { notifications: vi.fn(async () => listFixture()) },
}));

describe("NotificationScreen icons", () => {
  it("renders a distinct icon per notification category, not a single dot", async () => {
    render(withRouter(<NotificationScreen />));

    await waitFor(() => {
      expect(screen.getByRole("img", { name: "Posted range went up" })).toBeInTheDocument();
    });
    expect(screen.getByRole("img", { name: "Scanning" })).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "Scan finished with problems" })).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "New roles for you" })).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "Saved role changed" })).toBeInTheDocument();

    // Every category is also a facet row in the register. jsdom has no
    // matchMedia, so the register is in its folded home behind the toolbar's
    // Filters opener, and a group at rest shows only its chosen rows.
    await userEvent.click(screen.getByRole("button", { name: "Filters" }));
    await userEvent.click(screen.getByRole("button", { name: "Scans" }));
    expect(screen.getByRole("checkbox", { name: "Scanning" })).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: "Scan problems" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Roles" }));
    expect(screen.getByRole("checkbox", { name: "For you" })).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: "Reminders" })).toBeInTheDocument();
  });

  it("reloads the terminal sync result when the shared completion revision advances", async () => {
    const running: NotificationList = {
      ...listFixture(),
      items: [
        {
          id: 10,
          created_at: "2026-07-14T02:07:00Z",
          priority: "normal",
          category: "sync_started",
          title: "Sync started",
          body: "7 sources queued",
          job_id: null,
          company: null,
          run_id: 18,
          source_type: "run",
          read_at: null,
          dismissed_at: null,
          meta: { sync_state: "running" },
        },
      ],
    };
    const completed: NotificationList = {
      ...running,
      items: [
        {
          ...running.items[0],
          id: 11,
          category: "sync_success",
          title: "Sync completed",
          body: "Finished after 8m 11s. 743 found / 0 created / 743 updated",
          meta: { sync_state: "success" },
        },
      ],
    };
    const notifications = vi.mocked(api.notifications);
    notifications.mockClear();
    notifications.mockImplementation(async () =>
      appState.notificationVersion === 0 ? running : completed,
    );
    appState.notificationVersion = 0;

    const { rerender } = render(withRouter(<NotificationScreen />));
    expect(await screen.findByText("Sync started")).toBeInTheDocument();
    expect(screen.queryByText("Sync completed")).not.toBeInTheDocument();

    appState.notificationVersion = 1;
    rerender(withRouter(<NotificationScreen />));
    // Re-read in place: the rows stay until the new page lands.
    expect(screen.getByText("Sync started")).toBeInTheDocument();

    expect(await screen.findByText("Sync completed")).toBeInTheDocument();
    expect(screen.getByText(/8m 11s/)).toBeInTheDocument();
    expect(notifications).toHaveBeenCalledTimes(2);
  });
});
