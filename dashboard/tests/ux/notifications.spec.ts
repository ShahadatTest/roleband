import { installJobDetailRoutes } from "./boardHarness";
import { expect, test } from "./fixtures";
import { detail } from "./boardHarness";
import { installSettingsRoutes } from "./settingsHarness";
import { expectMeasuredToolbar } from "./measuredToolbar";
import type { Page } from "@playwright/test";
import { facetsFixture, jobFixture, jobListFixture, statsFixture, statusFixture } from "../../src/test/fixtures";

// The notification lenses (status, priority, category) live in the query
// string, so a filtered inbox is shareable and survives reload. These specs
// pin that the URL drives the fetch and the controls, and that an unknown
// value falls back. The register stands beside the list at rail widths
// (>= 1360, ui/FilterRail RAIL_QUERY) and folds into the toolbar's Filters
// panel below them — the desktop project runs at rail width, the mobile
// project exercises the folded home.

const items = [
  {
    id: 1, created_at: "2026-07-13T00:00:00Z", priority: "high", category: "sync_failed",
    title: "Scan failed", body: "Apple adapter error", job_id: null, company: null, run_id: 7,
    source_type: "run", read_at: null, dismissed_at: null, meta: {},
  },
  {
    // A job-linked notification carries the company slug (already read, so the
    // click doesn't need a mark-read round-trip).
    id: 2, created_at: "2026-07-13T00:01:00Z", priority: "high", category: "high_comp_match",
    title: "High comp match at OpenAI", body: "Staff PM", job_id: 101, company: "openai", run_id: 1,
    source_type: "event", read_at: "2026-07-13T01:00:00Z", dismissed_at: null, meta: {},
  },
];
const notifList = {
  total: 2, limit: 20, offset: 0, unread_count: 2, high_unread_count: 1,
  category_counts: { sync_failed: 1, high_comp_match: 1 }, items,
};

/** The register's home: the rail at desktop, the toolbar's panel on mobile. */
async function openFilters(page: Page, isMobile: boolean) {
  if (isMobile) await page.getByRole("button", { name: /^Filters/ }).click();
  return page.locator(".notif-filters");
}

// Route notifications with a per-test URL sink so assertions can inspect the query.
async function routeNotifications(page: Page, sink?: string[]) {
  await page.route("/api/notifications?**", (route) => {
    sink?.push(route.request().url());
    return route.fulfill({ json: notifList });
  });
}

test.beforeEach(async ({ page, isMobile }) => {
  await installJobDetailRoutes(page);
  await page.route("/api/profile", (route) => route.fulfill({ json: {
    profile: null, scope_configured: true,
  } }));
  if (!isMobile) await page.setViewportSize({ width: 1600, height: 900 });
  await page.route("/api/stats", (route) => route.fulfill({ json: statsFixture }));
  await page.route("/api/status", (route) => route.fulfill({ json: statusFixture }));
  await page.route("/api/facets", (route) => route.fulfill({ json: facetsFixture }));
  await page.route("/api/jobs/101", (route) => route.fulfill({ json: jobFixture }));
  await page.route("/api/jobs/*/similar**", (route) => route.fulfill({ json: { scope: "cross", items: [] } }));
  await page.route("/api/jobs?**", (route) => route.fulfill({ json: jobListFixture }));
});

test("notification toolbar measurements track CSS-only reflow in both themes", async ({ page }) => {
  await routeNotifications(page);
  for (const theme of ["light", "dark"]) {
    await page.goto("/notifications");
    await expect(page.getByRole("searchbox", { name: "Search notifications" })).toBeVisible();
    await page.locator("html").evaluate((node, value) => node.setAttribute("data-theme", value), theme);
    await expectMeasuredToolbar(page, ".notif-center", ".notif-toolbar", "--notif-toolbar-h");
  }
});

test("a deep link applies the status and category filters", async ({ page, isMobile }) => {
  const requests: string[] = [];
  await routeNotifications(page, requests);

  await page.goto("/notifications?status=unread&category=sync_failed");

  // The fetch carried both filters (a filter the UI ignored would be silently wrong).
  await expect
    .poll(() =>
      requests.some((u) => {
        const p = new URL(u).searchParams;
        return p.get("status") === "unread" && p.get("category") === "sync_failed";
      }),
    )
    .toBe(true);

  // ...and the controls reflect them. Scope to the register: a notification row
  // in the list can share the "Scan failed" text. The status switch is a
  // ui/Segmented (`aria-pressed`, the one announced convention) and a category
  // is a checkbox row in its facet group, shown at rest because it is chosen.
  const filters = await openFilters(page, isMobile);
  await expect(filters.locator(".notif-status").getByRole("button", { name: "Unread" })).toHaveAttribute("aria-pressed", "true");
  await expect(filters.getByRole("checkbox", { name: "Scan failed", exact: true })).toBeChecked();
  await expect(filters.getByRole("button", { name: "Scans · 1" })).toBeVisible();
});

test("a priority lens and several categories travel in the URL", async ({ page, isMobile }) => {
  const requests: string[] = [];
  await routeNotifications(page, requests);
  await page.goto("/notifications?priority=high&category=sync_failed&category=daily_digest");
  await expect
    .poll(() =>
      requests.some((u) => {
        const p = new URL(u).searchParams;
        return p.get("priority") === "high" && p.getAll("category").join(",") === "sync_failed,daily_digest";
      }),
    )
    .toBe(true);
  const filters = await openFilters(page, isMobile);
  await expect(filters.locator(".notif-priority").getByRole("button", { name: "High" })).toHaveAttribute("aria-pressed", "true");
  await expect(filters.getByRole("checkbox", { name: "For you", exact: true })).toBeChecked();
});

test("toggling a filter writes it into the URL", async ({ page, isMobile }) => {
  await routeNotifications(page);
  await page.goto("/notifications");
  await expect(page).toHaveURL(/\/notifications$/);

  const filters = await openFilters(page, isMobile);
  await filters.locator(".notif-status").getByRole("button", { name: "Unread" }).click();
  await expect(page).toHaveURL(/status=unread/);

  // A group at rest is one headline; open it to reach an unchosen row.
  await filters.getByRole("button", { name: "Scans", exact: true }).click();
  await filters.getByRole("checkbox", { name: "Scan failed", exact: true }).click();
  await expect(page).toHaveURL(/category=sync_failed/);

  // Reset all takes every lens back in one step. It lives in the toolbar band,
  // not inside the register — the Board's placement, so the same words mean
  // the same scope on both screens. On mobile the panel
  // is covering it, so close the panel first.
  if (isMobile) await page.keyboard.press("Escape");
  await page.locator(".notif-toolbar").getByRole("button", { name: "Reset all" }).click();
  await expect(page).toHaveURL(/\/notifications$/);
});

/* A query narrows the list but is not a filter, so it survives Reset all and
 * never reaches the folded opener's count: the Board's `q: queryContext`,
 * stated once. */
test("Reset all clears the lenses and leaves the query standing", async ({ page }) => {
  const requests: string[] = [];
  await routeNotifications(page, requests);
  await page.goto("/notifications?status=unread&category=sync_failed");
  await page.getByRole("searchbox", { name: "Search notifications" }).fill("openai");
  await expect.poll(() => new URL(requests[requests.length - 1]).searchParams.get("q")).toBe("openai");

  await page.locator(".notif-toolbar").getByRole("button", { name: "Reset all" }).click();
  await expect(page).toHaveURL(/\/notifications$/);
  await expect(page.getByRole("searchbox", { name: "Search notifications" })).toHaveValue("openai");
  await expect
    .poll(() => {
      const p = new URL(requests[requests.length - 1]).searchParams;
      return `${p.get("q")}@${p.get("status")}@${p.getAll("category").length}`;
    })
    .toBe("openai@all@0");
  // A query alone is not an active filter, so the undo is gone and the folded
  // opener wears no count.
  await expect(page.locator(".notif-toolbar").getByRole("button", { name: "Reset all" })).toHaveCount(0);
});

test("filters survive a reload", async ({ page, isMobile }) => {
  await routeNotifications(page);
  await page.goto("/notifications?status=unread&category=sync_failed");
  let filters = await openFilters(page, isMobile);
  await expect(filters.locator(".notif-status").getByRole("button", { name: "Unread" })).toHaveAttribute("aria-pressed", "true");

  await page.reload();
  await expect(page).toHaveURL(/status=unread/);
  filters = await openFilters(page, isMobile);
  await expect(filters.getByRole("checkbox", { name: "Scan failed", exact: true })).toBeChecked();
});

/* Filter memory. The address carries these lenses through a RELOAD, but not
   through a visit by the nav rail or the bell, which lands on a bare
   `/notifications`. The same mechanism the Board's
   register uses, on a screen whose filters live in the query string
   (routing/useRememberedParams). */
test("the lenses come back on a bare address, and a reset comes back too", async ({
  page, isMobile,
}) => {
  const requests: string[] = [];
  await routeNotifications(page, requests);
  const sent = () => new URL(requests[requests.length - 1]).searchParams;
  await page.goto("/notifications");
  const filters = await openFilters(page, isMobile);
  await filters.locator(".notif-status").getByRole("button", { name: "Unread" }).click();
  await filters.getByRole("button", { name: "Scans", exact: true }).click();
  await filters.getByRole("checkbox", { name: "Scan failed", exact: true }).click();
  await expect(page).toHaveURL(/category=sync_failed/);
  /* Wait for the LIST to carry it, not just the address. The URL moves with
     the history entry; the screen has not finished the render that records
     the choice until the request for it goes out, and `goto` an instant later
     would tear the page down in between. */
  await expect.poll(() => sent().getAll("category")).toEqual(["sync_failed"]);
  if (isMobile) await page.keyboard.press("Escape");

  // Away, and back the way the bell brings you: no query at all.
  await page.goto("/");
  await page.goto("/notifications");
  await expect(page).toHaveURL(/status=unread/);
  await expect(page).toHaveURL(/category=sync_failed/);
  await expect
    .poll(() => new URL(requests[requests.length - 1]).searchParams.get("status"))
    .toBe("unread");
  // And the group the reader opened is open, which is the other half. Its
  // head wears the count now, so match the name by its stem.
  const back = await openFilters(page, isMobile);
  await expect(back.getByRole("button", { name: /^Scans/ }))
    .toHaveAttribute("aria-expanded", "true");
  if (isMobile) await page.keyboard.press("Escape");

  // Reset all is a choice too: come back and the inbox is still unfiltered.
  await page.locator(".notif-toolbar").getByRole("button", { name: "Reset all" }).click();
  await expect(page).toHaveURL(/\/notifications$/);
  await expect.poll(() => `${sent().get("status")}@${sent().getAll("category").length}`).toBe("all@0");
  await page.goto("/");
  await page.goto("/notifications");
  await expect(page).toHaveURL(/\/notifications$/);
});

test("a link that names a lens outranks what was remembered", async ({ page, isMobile }) => {
  const requests: string[] = [];
  await routeNotifications(page, requests);
  await page.goto("/notifications");
  const filters = await openFilters(page, isMobile);
  await filters.locator(".notif-status").getByRole("button", { name: "Unread" }).click();
  await expect(page).toHaveURL(/status=unread/);
  await expect
    .poll(() => new URL(requests[requests.length - 1]).searchParams.get("status"))
    .toBe("unread");
  if (isMobile) await page.keyboard.press("Escape");

  // An address that speaks for itself is a choice made just now; memory is one
  // made last night, and it does not get merged in beside it.
  await page.goto("/notifications?priority=high");
  await expect(page).toHaveURL(/priority=high/);
  await expect(page).not.toHaveURL(/status=unread/);
});

test("the verb is a ghost at the toolbar end and its toast undoes it", async ({ page }) => {
  await routeNotifications(page);
  let unreadPosted: unknown = null;
  // `undoable` gates the Undo action: above the server's bulk-unread bound the
  // ids come back empty and no Undo is offered, because a partial restore
  // reported as success is worse than none.
  await page.route("/api/notifications/read_all", (route) =>
    route.fulfill({ json: { updated: 2, undoable: true, ids: [1, 2] } }));
  await page.route("/api/notifications/unread", (route) => {
    unreadPosted = route.request().postDataJSON();
    return route.fulfill({ json: { updated: 2 } });
  });
  await page.goto("/notifications");

  const verb = page.getByRole("button", { name: "Mark all read" });
  await expect(verb).toBeVisible();
  await expect(verb).toHaveClass(/ui-btn-ghost/);
  await expect(page.locator(".page-hero").getByRole("button")).toHaveCount(0);
  // The screen carries no count line at all: the bar is search, filters, verb.
  await expect(page.locator(".notif-toolbar .results-count")).toHaveCount(0);
  // A COUNT, which is what "no count line" means — not the bare word. Rows carry
  // an sr-only "unread" for assistive tech, and matching the bare
  // word here would forbid that too, which is a different claim than this one.
  await expect(page.getByText(/\d+\s*(unread|high priority)/)).toHaveCount(0);

  await verb.click();
  await page.getByRole("button", { name: "Undo" }).click();
  await expect.poll(() => unreadPosted).toEqual({ ids: [1, 2] });
});

test("search asks the server and the pager walks the offset", async ({ page }) => {
  const requests: string[] = [];
  await page.route("/api/notifications?**", (route) => {
    const url = new URL(route.request().url());
    requests.push(url.toString());
    const offset = Number(url.searchParams.get("offset") ?? 0);
    return route.fulfill({ json: { ...notifList, total: 45, offset } });
  });
  await page.goto("/notifications");
  await expect(page.getByText("Page 1 of 3")).toBeVisible();

  await page.getByRole("button", { name: "Next" }).click();
  await expect(page.getByText("Page 2 of 3")).toBeVisible();
  await expect.poll(() => new URL(requests[requests.length - 1]).searchParams.get("offset")).toBe("20");

  await page.getByRole("searchbox", { name: "Search notifications" }).fill("google");
  await expect.poll(() => {
    const p = new URL(requests[requests.length - 1]).searchParams;
    return `${p.get("q")}@${p.get("offset")}`;
  }).toBe("google@0");
  await expect(page.getByText("Page 1 of 3")).toBeVisible();
});

test("an unknown status falls back to All", async ({ page, isMobile }) => {
  await routeNotifications(page);
  await page.goto("/notifications?status=bogus");

  const statusSeg = (await openFilters(page, isMobile)).locator(".notif-status");
  await expect(statusSeg.getByRole("button", { name: "All" })).toHaveAttribute("aria-pressed", "true");
  await expect(statusSeg.getByRole("button", { name: "Unread" })).toHaveAttribute("aria-pressed", "false");
});

test("clicking a job notification opens the company-scoped position URL", async ({ page }) => {
  await routeNotifications(page);
  await page.goto("/notifications");

  // The notification carries the job's company, so the click lands on the nested
  // position URL rather than a bare /job/:id.
  await page.getByRole("button", { name: /High comp match at OpenAI/ }).click();
  await expect(page).toHaveURL(/\/company\/openai\/job\/101$/);
  await expect(detail(page)).toBeVisible();
});

// Marking read is incidental to opening. An UNREAD role whose read POST never
// answers still opens at once; the click never waits on the write.
test("an unread job notification opens even while its read mark never answers", async ({ page }) => {
  const unread = { ...items[1], read_at: null };
  await page.route("/api/notifications?**", (route) =>
    route.fulfill({ json: { ...notifList, items: [items[0], unread] } }),
  );
  const pending: unknown[] = [];
  await page.route("/api/notifications/2/read", (route) => {
    pending.push(route); // never fulfilled: the write hangs
  });
  await page.goto("/notifications");

  await page.getByRole("button", { name: /High comp match at OpenAI/ }).click();
  await expect(page).toHaveURL(/\/company\/openai\/job\/101$/);
  await expect(detail(page)).toBeVisible();
  expect(pending).toHaveLength(1);
});

// The panel cannot rely on a translucent ground plus backdrop-filter to stay
// readable. It lives inside `.topbar`, which has a backdrop-filter of its own
// and therefore forms a backdrop root, so a blur never reaches the page
// behind the panel: content would show through sharp and the texts collide.
test("the notifications panel is opaque enough to read over page content", async ({ page, isMobile }) => {
  test.skip(isMobile, "the bell lives in the desktop topbar");
  await installSettingsRoutes(page);
  await routeNotifications(page);
  await page.goto("/settings/companies");
  await page.getByRole("button", { name: "Notifications" }).click();

  const panel = page.locator(".notif-popover");
  await expect(panel).toBeVisible();

  const alpha = await panel.evaluate((el) => {
    const bg = getComputedStyle(el).backgroundColor;
    const parts = bg.match(/[\d.]+/g)!.map(Number);
    return parts.length > 3 ? parts[3] : 1;
  });
  expect(alpha).toBe(1);
});


/* The folded register is patterns/FilterSurface over ui/Overlay on every
 * screen, so the panel closes by Escape, and a viewport that grows into rail
 * mode and shrinks again does not find the panel open when nobody asked
 * for it. */
test("the folded filter panel closes by Escape, and does not survive a trip through rail mode", async ({ page, isMobile }) => {
  // A touch tap does not focus a button, so focus-return is a pointer-and-
  // keyboard contract; and the trip through rail mode is a desktop resize.
  test.skip(isMobile, "desktop pointer + keyboard contract");
  await routeNotifications(page);
  await page.setViewportSize({ width: 1200, height: 800 });
  await page.goto("/notifications");
  const opener = page.getByRole("button", { name: /^Filters/ });
  await opener.click();
  const panel = page.getByRole("dialog", { name: "Filters" });
  await expect(panel).toBeVisible();
  await expect(panel).toHaveAttribute("aria-modal", "true");

  await page.keyboard.press("Escape");
  await expect(panel).toHaveCount(0);
  await expect(opener).toBeFocused();

  await opener.click();
  await expect(panel).toBeVisible();
  await page.setViewportSize({ width: 1400, height: 800 });
  await expect(page.getByRole("complementary", { name: "Filters" })).toBeVisible();
  await expect(panel).toHaveCount(0);
  await page.setViewportSize({ width: 1200, height: 800 });
  await expect(opener).toBeVisible();
  await expect(panel).toHaveCount(0);
  await expect(opener).toHaveAttribute("aria-expanded", "false");
});

// A followed company's careers page gone from its address: Hex moved to
// another careers platform. The notice is where the person answers, so
// it finds the new page, moves the company there on one click, and is gone.
test("a careers page gone from its address is found and moved to from its notice", async ({ page }) => {
  const gone = {
    id: 9, created_at: "2026-10-04T16:06:01Z", priority: "normal", category: "coverage",
    title: "Hex Technologies's careers page is gone · 2 days",
    body: "Its careers page is no longer at its last address.",
    job_id: null, company: null, run_id: null, source_type: "binding", read_at: null, dismissed_at: null,
    meta: { company: "hex-technologies", display: "Hex Technologies", cause: "board_missing", held_open: 3 },
  };
  let moved = false;
  let putBody: unknown = null;
  await page.route("/api/notifications?**", (route) => route.fulfill({ json: {
    total: moved ? 0 : 1, limit: 20, offset: 0, unread_count: moved ? 0 : 1, high_unread_count: 0,
    category_counts: moved ? {} : { coverage: 1 }, items: moved ? [] : [gone],
  } }));
  await page.route("/api/companies/hex-technologies/board/find", (route) => route.fulfill({ json: {
    candidate: { adapter: "ashby", board_token: "hex", board_region: null, roles: 36, shared: 30, found_by: "name" },
  } }));
  await page.route("/api/companies/hex-technologies/board", (route) => {
    putBody = route.request().postDataJSON();
    moved = true;
    return route.fulfill({ json: {
      slug: "hex-technologies", display: "Hex Technologies", adapter: "ashby", board_token: "hex",
      careers_url: null, status: "active", enabled: true, visible: true, source: "directory-set",
      builtin: false, job_count: 3, role_catalog_status: "pending", role_catalog_scanned_at: null,
      role_catalog_error: null,
    } });
  });
  await page.goto("/notifications");

  const answers = page.getByRole("group", { name: "Hex Technologies's careers page" });
  await answers.getByRole("button", { name: "Find new careers page" }).click();
  await expect(answers.getByText(
    "Found it: 36 roles, 30 of them roles seen at Hex Technologies before.",
  )).toBeVisible();
  await answers.getByRole("button", { name: "Use this careers page" }).click();

  await expect.poll(() => putBody).toEqual({ adapter: "ashby", board_token: "hex", board_region: null });
  await expect(page.getByText("Now reading Hex Technologies's new careers page")).toBeVisible();
  await expect(page.getByText("Hex Technologies's careers page is gone · 2 days")).toHaveCount(0);
});
