import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import type { ReactElement } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api, type Notification, type NotificationList } from "../../api";
import { ToastProvider } from "../../ui/Toast";
import { NotificationScreen, PAGE_SIZE } from "./NotificationScreen";

/* Behaviour contracts for the normalized center:
 * the screen verb's rank and its undo, search as a server query, the offset
 * pager, and the filters as one register. The api is mocked at the boundary;
 * every assertion is about what the user sees or what the server was asked. */

const withProviders = (ui: ReactElement, initial = "/notifications") => (
  <ToastProvider>
    <MemoryRouter initialEntries={[initial]}>{ui}</MemoryRouter>
  </ToastProvider>
);

function item(over: Partial<Notification> & { id: number }): Notification {
  return {
    created_at: "2026-07-13T00:00:00Z",
    priority: "normal",
    category: "new_match",
    title: `Notification ${over.id}`,
    body: null,
    job_id: null,
    company: null,
    run_id: null,
    source_type: "event",
    read_at: null,
    dismissed_at: null,
    meta: {},
    ...over,
  };
}

function list(over: Partial<NotificationList> = {}): NotificationList {
  return {
    total: 2,
    limit: PAGE_SIZE,
    offset: 0,
    unread_count: 2,
    high_unread_count: 1,
    category_counts: { new_match: 1, sync_failed: 1 },
    items: [
      item({ id: 1, priority: "high", category: "sync_failed", title: "Scan failed", run_id: 7, source_type: "run" }),
      item({ id: 2, title: "New match at OpenAI", job_id: 101, company: "openai" }),
    ],
    ...over,
  };
}


vi.mock("../../context/JobWorkspace", () => ({ useJobActions: () => ({ openJob: vi.fn() }) }));
vi.mock("../../context/MissionState", () => ({ useMissionActions: () => ({ refreshStats: vi.fn() }) }));
vi.mock("../../context/SyncState", () => ({ useSyncEpoch: () => ({ notificationVersion: 0 }) }));

vi.mock("../../api", () => ({
  api: {
    notifications: vi.fn(),
    markAllNotificationsRead: vi.fn(),
    markNotificationsUnread: vi.fn(),
    markNotificationRead: vi.fn(),
    dismissNotification: vi.fn(),
    restoreNotification: vi.fn(),
  },
}));

/** The last request the center made. */
const lastParams = () => {
  const calls = vi.mocked(api.notifications).mock.calls;
  return calls[calls.length - 1]?.[0];
};

describe("NotificationScreen — the screen verb", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(api.notifications).mockImplementation(async () => list());
  });

  it("is a ghost at the toolbar end, never a gold fill, and needs something unread", async () => {
    render(withProviders(<NotificationScreen />));
    const verb = await screen.findByRole("button", { name: "Mark all read" });
    expect(verb.className).toContain("ui-btn-ghost");
    // The toolbar rank: the band's action, not one more label in it.
    expect(verb.className).toContain("ui-btn-strong");
    expect(verb.className).not.toContain("ui-btn-primary");
    expect(verb.closest(".notif-toolbar")).not.toBeNull();
    expect(verb.closest(".page-hero")).toBeNull();
    expect(verb).toBeEnabled();
  });

  it("is disabled when nothing is unread", async () => {
    vi.mocked(api.notifications).mockImplementation(async () => list({ unread_count: 0, high_unread_count: 0 }));
    render(withProviders(<NotificationScreen />));
    expect(await screen.findByRole("button", { name: "Mark all read" })).toBeDisabled();
  });

  /* A disabled control names its reason where
     a reader can see it, and a screen reader hears it as the control's
     description. A disabled button takes no focus, so a hover `title` reaches
     neither a keyboard nor a touch reader. */
  it("says why it is disabled, on screen and as its description", async () => {
    vi.mocked(api.notifications).mockImplementation(async () => list({ unread_count: 0, high_unread_count: 0 }));
    render(withProviders(<NotificationScreen />));
    const verb = await screen.findByRole("button", { name: "Mark all read" });
    expect(verb).toHaveAccessibleDescription("Nothing unread");
    expect(screen.getByText("Nothing unread")).toBeVisible();
  });

  it("carries no reason while there is something to mark", async () => {
    render(withProviders(<NotificationScreen />));
    const verb = await screen.findByRole("button", { name: "Mark all read" });
    expect(verb).toBeEnabled();
    expect(verb).toHaveAccessibleDescription("");
    expect(screen.queryByText("Nothing unread")).not.toBeInTheDocument();
  });

  it("offers Undo in a toast, and Undo posts the server's ids back", async () => {
    vi.mocked(api.markAllNotificationsRead).mockResolvedValue({ updated: 2, undoable: true, ids: [1, 2] });
    vi.mocked(api.markNotificationsUnread).mockResolvedValue({ updated: 2 });
    render(withProviders(<NotificationScreen />));

    await userEvent.click(await screen.findByRole("button", { name: "Mark all read" }));
    expect(api.markAllNotificationsRead).toHaveBeenCalledTimes(1);
    expect(await screen.findByText("Marked 2 notifications read")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Undo" }));
    expect(api.markNotificationsUnread).toHaveBeenCalledWith([1, 2]);
  });

  it("offers no Undo when the clear was too large for the server to restore", async () => {
    /* Above the bulk-unread bound the server returns no ids at all, because a
       partial restore reported as success is worse than no undo. The toast must
       then say what happened and stop there: an Undo button here would post an
       over-length body, which the server refuses with a 422. */
    vi.mocked(api.markAllNotificationsRead).mockResolvedValue({
      updated: 900,
      undoable: false,
      ids: [],
    });
    render(withProviders(<NotificationScreen />));

    await userEvent.click(await screen.findByRole("button", { name: "Mark all read" }));
    expect(await screen.findByText("Marked 900 notifications read")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Undo" })).not.toBeInTheDocument();
    expect(api.markNotificationsUnread).not.toHaveBeenCalled();
  });

  it("puts the header on the shared hero with the title only, and carries no count anywhere", async () => {
    render(withProviders(<NotificationScreen />));
    await screen.findByRole("button", { name: "Mark all read" });
    const hero = document.querySelector(".page-hero")!;
    expect(hero.querySelector("h1")?.textContent).toBe("Notifications");
    expect(hero.querySelector("button")).toBeNull();
    expect(hero.querySelector("p")).toBeNull();
    expect(document.querySelector(".notif-toolbar .results-count")).toBeNull();
    expect(screen.queryByText(/notifications ·/)).toBeNull();
    /* A COUNT, which is what this test forbids — not the bare word. Rows carry
       an sr-only "unread" for assistive tech, and a plain
       /unread/ here would forbid that too, which is a different claim than the
       one this test is named for. */
    expect(screen.queryByText(/\d+\s*unread/)).toBeNull();
    expect(screen.queryByText(/high priority/)).toBeNull();
  });
});

describe("NotificationScreen — search", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(api.notifications).mockImplementation(async () => list());
  });

  it("asks the server after the debounce, from the first page, and not per keystroke", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      render(withProviders(<NotificationScreen />));
      await screen.findByRole("button", { name: "Mark all read" });
      const before = vi.mocked(api.notifications).mock.calls.length;

      const field = screen.getByRole("searchbox", { name: "Search notifications" });
      await userEvent.type(field, "goo", { advanceTimers: (ms) => vi.advanceTimersByTime(ms) });
      expect(vi.mocked(api.notifications).mock.calls.length).toBe(before);

      await act(async () => {
        vi.advanceTimersByTime(300);
      });
      await waitFor(() => expect(lastParams()).toMatchObject({ q: "goo", offset: 0 }));
      expect(vi.mocked(api.notifications).mock.calls.length).toBe(before + 1);
    } finally {
      vi.useRealTimers();
    }
  });
});

describe("NotificationScreen — paging", () => {
  beforeEach(() => vi.clearAllMocks());

  it("pages by offset and shows the pager only past one page", async () => {
    vi.mocked(api.notifications).mockImplementation(async (p) =>
      list({ total: 45, offset: p?.offset ?? 0 }),
    );
    render(withProviders(<NotificationScreen />));
    expect(await screen.findByText("Page 1 of 3")).toBeInTheDocument();
    expect(lastParams()).toMatchObject({ limit: PAGE_SIZE, offset: 0 });

    await userEvent.click(screen.getByRole("button", { name: /Next/ }));
    expect(await screen.findByText("Page 2 of 3")).toBeInTheDocument();
    expect(lastParams()).toMatchObject({ offset: PAGE_SIZE });
    expect(screen.getByRole("button", { name: /Prev/ })).toBeEnabled();
  });

  it("hides the pager when everything fits on one page", async () => {
    vi.mocked(api.notifications).mockImplementation(async () => list({ total: 2 }));
    render(withProviders(<NotificationScreen />));
    await screen.findByRole("button", { name: "Mark all read" });
    expect(screen.queryByText(/Page 1 of/)).toBeNull();
  });

  it("starts over on the first page when a lens changes", async () => {
    vi.mocked(api.notifications).mockImplementation(async (p) =>
      list({ total: 45, offset: p?.offset ?? 0 }),
    );
    render(withProviders(<NotificationScreen />));
    await userEvent.click(await screen.findByRole("button", { name: /Next/ }));
    await userEvent.click(await screen.findByRole("button", { name: /Next/ }));
    expect(await screen.findByText("Page 3 of 3")).toBeInTheDocument();

    // jsdom has no matchMedia: the register is in its folded home.
    await userEvent.click(screen.getByRole("button", { name: "Filters" }));
    await userEvent.click(screen.getByRole("button", { name: "Unread" }));
    await waitFor(() => expect(lastParams()).toMatchObject({ status: "unread", offset: 0 }));
    expect(await screen.findByText("Page 1 of 3")).toBeInTheDocument();
  });

  it("steps back when the last row of the last page is dismissed", async () => {
    let total = 21;
    vi.mocked(api.notifications).mockImplementation(async (p) => {
      const offset = p?.offset ?? 0;
      const count = Math.max(0, Math.min(PAGE_SIZE, total - offset));
      return list({
        total,
        offset,
        items: Array.from({ length: count }, (_, i) => item({ id: offset + i + 1 })),
      });
    });
    vi.mocked(api.dismissNotification).mockImplementation(async () => {
      total = 20;
      return item({ id: 21, dismissed_at: "2026-07-13T01:00:00Z" });
    });
    render(withProviders(<NotificationScreen />));
    await userEvent.click(await screen.findByRole("button", { name: /Next/ }));
    expect(await screen.findByText("Page 2 of 2")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Dismiss" }));
    await waitFor(() => expect(lastParams()).toMatchObject({ offset: 0 }));
    expect(screen.queryByText(/Page 2 of/)).toBeNull();
  });

  it("keeps a failed dismissal visible, reports it and can retry successfully", async () => {
    const notification = item({ id: 21, title: "A role worth pursuing" });
    vi.mocked(api.notifications).mockResolvedValue(list({ total: 1, items: [notification] }));
    let reject!: (error: Error) => void;
    vi.mocked(api.dismissNotification).mockReturnValueOnce(new Promise((_, no) => { reject = no; }));
    render(withProviders(<NotificationScreen />));
    await screen.findByText(notification.title);

    await userEvent.click(within(screen.getByRole("article")).getByRole("button", { name: "Dismiss" }));
    expect(api.dismissNotification).toHaveBeenCalledWith(21);
    expect(screen.getByText(notification.title)).toBeInTheDocument();
    await act(async () => { reject(new Error("offline")); });
    expect(await screen.findByText("Couldn't dismiss that notification")).toBeInTheDocument();
    expect(screen.getByText(notification.title)).toBeInTheDocument();
    await waitFor(() => expect(api.notifications).toHaveBeenCalledTimes(2));

    vi.mocked(api.dismissNotification).mockResolvedValueOnce({ ...notification, dismissed_at: "2026-09-08T12:00:00Z" });
    vi.mocked(api.notifications).mockResolvedValueOnce(list({ total: 0, items: [], unread_count: 0 }));
    await userEvent.click(within(screen.getByRole("article")).getByRole("button", { name: "Dismiss" }));
    await waitFor(() => expect(screen.queryByText(notification.title)).toBeNull());
    expect(api.dismissNotification).toHaveBeenCalledTimes(2);
  });

});

describe("NotificationScreen — the row's destructive verb", () => {
  beforeEach(() => vi.clearAllMocks());

  it("names the notification it removed and puts it back on Undo", async () => {
    /* The row verb is as careful as the bulk one beside it ("Mark all read"
       toasts with Undo). The toast has to name the row, because by the time it
       is read the row is gone from the list. */
    const notification = item({ id: 21, title: "A role worth pursuing" });
    const populated = list({ total: 1, unread_count: 1, items: [notification] });
    const emptied = list({ total: 0, unread_count: 0, items: [] });
    vi.mocked(api.notifications).mockResolvedValue(populated);
    vi.mocked(api.dismissNotification).mockResolvedValue({ ...notification, dismissed_at: "2026-09-08T12:00:00Z" });
    vi.mocked(api.restoreNotification).mockResolvedValue(notification);
    render(withProviders(<NotificationScreen />));
    await screen.findByText(notification.title);

    vi.mocked(api.notifications).mockResolvedValue(emptied);
    await userEvent.click(within(screen.getByRole("article")).getByRole("button", { name: "Dismiss" }));
    await waitFor(() => expect(screen.queryByText(notification.title)).toBeNull());
    expect(
      await screen.findByText("\u201cA role worth pursuing\u201d removed from your notifications"),
    ).toBeInTheDocument();

    vi.mocked(api.notifications).mockResolvedValue(populated);
    await userEvent.click(screen.getByRole("button", { name: "Undo" }));
    expect(api.restoreNotification).toHaveBeenCalledWith(21);
    expect(await screen.findByText(notification.title)).toBeInTheDocument();
  });

  it("offers no way back it cannot honour: a failed restore says so", async () => {
    const notification = item({ id: 21, title: "A role worth pursuing" });
    vi.mocked(api.notifications).mockResolvedValue(list({ total: 1, items: [notification] }));
    vi.mocked(api.dismissNotification).mockResolvedValue({ ...notification, dismissed_at: "2026-09-08T12:00:00Z" });
    vi.mocked(api.restoreNotification).mockRejectedValue(new Error("offline"));
    render(withProviders(<NotificationScreen />));
    await screen.findByText(notification.title);

    await userEvent.click(within(screen.getByRole("article")).getByRole("button", { name: "Dismiss" }));
    await userEvent.click(await screen.findByRole("button", { name: "Undo" }));

    expect(await screen.findByText("Couldn't undo that")).toBeInTheDocument();
  });
});

describe("NotificationScreen — the register", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(api.notifications).mockImplementation(async () => list());
  });

  it("carries the URL's lenses into the request and the controls, one value or many", async () => {
    render(
      withProviders(<NotificationScreen />, "/notifications?status=unread&priority=high&category=sync_failed&category=closed"),
    );
    await screen.findByRole("button", { name: "Mark all read" });
    expect(lastParams()).toMatchObject({ status: "unread", priority: "high", category: ["sync_failed", "closed"] });

    await userEvent.click(screen.getByRole("button", { name: /Filters · 4/ }));
    expect(screen.getByRole("button", { name: "Unread" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "High" })).toHaveAttribute("aria-pressed", "true");
    // A group at rest shows its chosen rows and wears its count on the headline.
    expect(screen.getByRole("checkbox", { name: "Scan failed" })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "Closed" })).toBeChecked();
    expect(screen.queryByRole("checkbox", { name: "Scanning" })).toBeNull();
    expect(screen.getByRole("button", { name: "Scans · 1" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Roles · 1" })).toBeInTheDocument();
  });

  it("shows each category's count from the server, and a category toggle keeps the other group", async () => {
    vi.mocked(api.notifications).mockImplementation(async () =>
      list({ category_counts: { sync_failed: 3, closed: 8 } }),
    );
    render(withProviders(<NotificationScreen />, "/notifications?category=closed"));
    await screen.findByRole("button", { name: "Mark all read" });
    await userEvent.click(screen.getByRole("button", { name: /Filters/ }));
    await userEvent.click(screen.getByRole("button", { name: "Scans" }));
    const failed = screen.getByRole("checkbox", { name: "Scan failed" });
    expect(failed.closest(".check-row")?.querySelector(".cnt")?.textContent).toBe("3");

    await userEvent.click(failed);
    await waitFor(() =>
      expect(lastParams()).toMatchObject({ category: expect.arrayContaining(["closed", "sync_failed"]) }),
    );
  });

  /* The undo sits in the toolbar band, not inside the panel, and its scope
     is the Board's: every filter and lens, never the query. Two screens must
     not use the same words for two different scopes. */
  it("Reset all stands in the toolbar and takes back every lens, leaving the query", async () => {
    render(withProviders(<NotificationScreen />, "/notifications?status=unread&category=closed"));
    await screen.findByRole("button", { name: "Mark all read" });
    await userEvent.type(screen.getByRole("searchbox", { name: "Search notifications" }), "x");
    await waitFor(() => expect(lastParams()).toMatchObject({ q: "x" }));

    const reset = screen.getByRole("button", { name: "Reset all" });
    expect(reset.closest(".notif-toolbar")).not.toBeNull();
    expect(reset.closest(".notif-filters")).toBeNull();

    await userEvent.click(reset);
    await waitFor(() => expect(lastParams()).toMatchObject({ status: "all", category: [], q: "x" }));
    expect(screen.getByRole("searchbox", { name: "Search notifications" })).toHaveValue("x");
    expect(screen.queryByRole("button", { name: "Reset all" })).toBeNull();
  });

  it("a query alone is not a filter: no undo, no count on the folded opener", async () => {
    render(withProviders(<NotificationScreen />));
    await screen.findByRole("button", { name: "Mark all read" });
    await userEvent.type(screen.getByRole("searchbox", { name: "Search notifications" }), "openai");
    await waitFor(() => expect(lastParams()).toMatchObject({ q: "openai" }));
    expect(screen.queryByRole("button", { name: "Reset all" })).toBeNull();
    expect(screen.getByRole("button", { name: "Filters" })).toBeInTheDocument();
  });

  it("a query that matches nothing still says so — narrowing is wider than the register", async () => {
    vi.mocked(api.notifications).mockImplementation(async (params) =>
      params?.q ? list({ total: 0, items: [], unread_count: 0, high_unread_count: 0 }) : list(),
    );
    render(withProviders(<NotificationScreen />));
    await screen.findByRole("button", { name: "Mark all read" });
    await userEvent.type(screen.getByRole("searchbox", { name: "Search notifications" }), "zzz");
    expect(await screen.findByText("Nothing matches")).toBeInTheDocument();
  });

  it("names the unread state in words, not only in colour", async () => {
    /* `.notif-row.unread` is a tint plus an inset bar, and that bar's HUE also
       carries priority/state — so colour alone would carry read/unread AND
       something else. The Board marks viewed roles with an sr-only word; this
       asserts the notification feed matches, and that a READ row stays silent, which is
       what stops the word becoming decoration on every row. */
    vi.mocked(api.notifications).mockImplementation(async () =>
      list({
        unread_count: 1,
        high_unread_count: 0,
        items: [
          item({ id: 1, title: "Still unread", read_at: null }),
          item({ id: 2, title: "Already read", read_at: "2026-07-13T01:00:00Z" }),
        ],
      }),
    );
    render(withProviders(<NotificationScreen />));

    const unread = (await screen.findByText("Still unread")).closest("article");
    const read = screen.getByText("Already read").closest("article");
    expect(unread).not.toBeNull();
    expect(read).not.toBeNull();
    expect(
      within(unread as HTMLElement).getByText("unread"),
      "an unread row signals its state by colour alone",
    ).toBeInTheDocument();
    expect(
      within(read as HTMLElement).queryByText("unread"),
      "a read row claims to be unread",
    ).toBeNull();
  });
});
