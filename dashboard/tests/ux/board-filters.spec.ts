/* The register and the lenses: what narrows the list and how that narrowing is
   worn. Includes the rail's two homes (pinned rail, and Filters · N below rail
   widths) because which home is showing changes how a filter is reached. */

import type { Locator, Page } from "@playwright/test";
import { expect, test } from "./fixtures";
import { facetsFixture, jobFixture, jobListFixture, statsFixture } from "../../src/test/fixtures";
import { deepList, installBoardRoutes, twoJobList } from "./boardHarness";
import { msg } from "../../src/test/msg";

/** Open the situational drawer, whatever state it is in.
 *
 *  A plain click is a TOGGLE, and with filter memory the door may already be
 *  open on arrival, because this reader opened it before or because something
 *  inside it is narrowing the list. A test that clicks it blind shuts it and
 *  then hunts for a group that is not rendered. */
async function openMoreFilters(scope: Page | Locator) {
  const door = scope.getByRole("button", { name: /^More filters/ });
  if ((await door.getAttribute("aria-expanded")) !== "true") await door.click();
}

test.beforeEach(async ({ page }) => {
  await installBoardRoutes(page);
});

test("the register wears its state on the rail: checked rows, counts, reset", async ({
  page,
}) => {
  const jobRequests: string[] = [];
  const UNFILTERED_TOTAL = 40;
  await page.route("/api/jobs?**", (route) => {
    jobRequests.push(route.request().url());
    // Any facet narrows the list to one row; the 1-row baseline request (no
    // facet) answers with the unfiltered count, which must differ.
    const p = new URL(route.request().url()).searchParams;
    const narrowed = p.has("company") || p.has("location_group");
    return route.fulfill({
      json: narrowed
        ? { ...jobListFixture, total: 1, items: jobListFixture.items.slice(0, 1) }
        : { ...jobListFixture, total: UNFILTERED_TOTAL },
    });
  });
  await page.setViewportSize({ width: 1600, height: 800 });
  // A deep link arrives with the company already chosen — the register must
  // SHOW that, which is the whole reason it exists: a bar button can only say
  // "Company · 1" and hide which one behind a popover.
  await page.goto("/?company=amazon");

  const rail = page.getByRole("complementary", { name: "Filters" });
  await expect(rail).toBeVisible();
  /* Every group rests CLOSED, and a closed group still
     shows what it is DOING: the chosen company is checked and on screen with
     nothing clicked, under a head that carries the count. That is the
     register's non-negotiable, and it is what makes collapsing safe. */
  await expect(rail.getByRole("checkbox", { name: "Amazon" })).toBeChecked();
  await expect(rail.getByRole("button", { name: "Company · 1" })).toHaveAttribute(
    "aria-expanded",
    "false"
  );
  await expect
    .poll(() => jobRequests.some((url) => new URL(url).searchParams.get("company") === "amazon"))
    .toBe(true);

  // Composing a second facet from the rail: one click opens the group, the
  // next chooses a value.
  await rail.getByRole("button", { name: "Location", exact: true }).click();
  await rail.getByRole("checkbox", { name: "Silicon Valley" }).check();
  await expect.poll(() => jobRequests.some((url) => {
    const params = new URL(url).searchParams;
    return params.get("company") === "amazon" && params.get("location_group") === "silicon_valley";
  })).toBe(true);

  // The count states the narrowing as a fraction, and the undo sits beside
  // it in the toolbar, NOT in the register, where a head row would push
  // every group down when it appeared.
  const count = page.locator(".results-count");
  await expect(count).toHaveText(/^1 of 40 roles · Reset all$/);
  await expect(rail.getByRole("button", { name: "Reset all" })).toHaveCount(0);
  const groupTop = async () =>
    (await rail.getByRole("group", { name: "Filter by company" }).boundingBox())!.y;
  const topWhileNarrowed = await groupTop();

  // Reset all clears both — and with nothing chosen, the collapsed Company
  // group shows no rows at all again, the fraction becomes the plain count,
  // and the register has not moved a pixel in either direction.
  await count.getByRole("button", { name: "Reset all" }).click();
  await expect.poll(() => {
    const last = new URL(jobRequests[jobRequests.length - 1]).searchParams;
    return last.get("company") === null && last.get("location_group") === null;
  }).toBe(true);
  await expect(rail.getByRole("checkbox", { name: "Amazon" })).toHaveCount(0);
  await expect(count).toHaveText(/^40 roles$/);
  expect(await groupTop()).toBe(topWhileNarrowed);
});

test("a failed unfiltered total can be retried without changing the active company lens", async ({ page }) => {
  let baselineAttempts = 0;
  let available = false;
  const requests: string[] = [];
  await page.route("/api/jobs?**", (route) => {
    const params = new URL(route.request().url()).searchParams;
    requests.push(route.request().url());
    if (params.get("limit") === "1") {
      baselineAttempts += 1;
      return available
        ? route.fulfill({ json: { ...jobListFixture, total: 219 } })
        : route.fulfill({ status: 503, json: { detail: "Unfiltered count temporarily unavailable" } });
    }
    return route.fulfill({ json: { ...jobListFixture, items: [{ ...jobFixture, company: "google" }] } });
  });
  await page.goto("/?company=google");
  await expect(page.getByRole("status").filter({ hasText: msg("radar-total-failed") })).toBeVisible();
  await expect(page.locator(".results-count")).not.toContainText("of 0");
  // Development StrictMode can abort/restart the initial request. Recovery
  // depends on the explicit action, not which transport attempt arrived first.
  const failedAttempts = baselineAttempts;
  available = true;
  await page.getByRole("button", { name: msg("radar-total-retry-aria") }).click();
  await expect(page.locator(".results-count")).toHaveText("1 of 219 roles · Reset all");
  await expect(page).toHaveURL(/company=google/);
  expect(baselineAttempts).toBe(failedAttempts + 1);
  const lists = requests.map((url) => new URL(url).searchParams).filter((params) => params.get("limit") !== "1");
  expect(lists.every((params) => params.get("company") === "google")).toBe(true);
  await expect(page.getByRole("button", { name: msg("radar-total-retry-aria") })).toHaveCount(0);
});

test("the register pins with the page scrolled, and never traps the wheel", async ({ page }) => {
  await page.route("/api/jobs?**", (route) => route.fulfill({ json: deepList }));
  await page.setViewportSize({ width: 1600, height: 700 });
  await page.goto("/");
  await expect(page.locator(".job-row").first()).toBeVisible();

  const g = await page.evaluate(() => {
    const main = document.querySelector(".main") as HTMLElement;
    const rail = document.querySelector(".rail-shell-rail") as HTMLElement;
    const mtop = () => main.getBoundingClientRect().top;
    const railTop = () => Math.round(rail.getBoundingClientRect().top - mtop());
    const barBottom = () =>
      Math.round(document.querySelector(".board-toolbar")!.getBoundingClientRect().bottom - mtop());
    main.scrollTop = 300;
    const midway = { rail: railTop(), barBottom: barBottom() };
    main.scrollTop = 600;
    const deep = { rail: railTop(), barBottom: barBottom() };
    return {
      midway,
      deep,
      // The overflow-valve must CHAIN into the page, never trap the gesture:
      // one scroll everywhere is the whole point.
      overscroll: getComputedStyle(rail).overscrollBehaviorY,
      valveMax: getComputedStyle(rail).maxHeight,
    };
  });

  // Pinned at the docked toolbar's underside, at every scroll depth.
  expect(g.midway.rail).toBe(g.midway.barBottom);
  expect(g.deep.rail).toBe(g.deep.barBottom);
  expect(g.overscroll).toBe("auto");
  expect(g.valveMax).not.toBe("none");
});

test("below rail widths the same register lives behind Filters · N", async ({ page }) => {
  const jobRequests: string[] = [];
  await page.route("/api/jobs?**", (route) => {
    jobRequests.push(route.request().url());
    return route.fulfill({ json: jobListFixture });
  });
  await page.setViewportSize({ width: 1200, height: 800 });
  await page.goto("/?company=amazon");

  // No rail — but the active count is still on screen, on the opener.
  await expect(page.getByRole("complementary", { name: "Filters" })).toHaveCount(0);
  const opener = page.getByRole("button", { name: "Filters · 1" });
  await expect(opener).toBeVisible();

  await opener.click();
  const panel = page.getByRole("dialog", { name: "Filters" });
  await expect(panel).toBeVisible();
  // The panel is the SAME register, with the same defaults: closed groups that
  // still wear their state, in either home.
  await expect(panel.getByRole("checkbox", { name: "Amazon" })).toBeChecked();
  await expect(panel.getByRole("button", { name: "Company · 1" })).toHaveAttribute(
    "aria-expanded",
    "false",
  );
  await panel.getByRole("button", { name: "Company · 1" }).click();
  await panel.getByRole("checkbox", { name: "OpenAI" }).check();
  await expect.poll(() => jobRequests.some((url) => {
    const companies = new URL(url).searchParams.getAll("company");
    return companies.includes("amazon") && companies.includes("openai");
  })).toBe(true);

  await page.keyboard.press("Escape");
  await expect(panel).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Filters · 2" })).toBeVisible();
});

test("new signals starter filter composes with board filters and can be cleared", async ({ page }) => {
  const jobRequests: string[] = [];
  await page.route("/api/jobs?**", (route) => {
    jobRequests.push(route.request().url());
    return route.fulfill({ json: jobListFixture });
  });

  await page.goto("/");
  await page.getByRole("button", { name: "1 new in the last 2 days" }).click();

  // The lens lands beside the count as a pressed chip — visible state, not a
  // silent hand on the list.
  const lensChip = page.getByRole("button", { name: msg("radar-new-today"), exact: true });
  await expect(lensChip).toBeVisible();
  await expect(lensChip).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByRole("button", { name: "1 new in the last 2 days" })).toHaveAttribute("aria-pressed", "true");
  await expect.poll(() => jobRequests.some((url) => new URL(url).searchParams.get("new_today_only") === "true")).toBe(true);

  // Composes with a facet chosen from the register: open the panel, open the
  // group, choose the row.
  await page.getByRole("button", { name: /^Filters/ }).click();
  await page.getByRole("button", { name: "Company", exact: true }).click();
  await page.getByRole("checkbox", { name: "OpenAI" }).check();
  await expect.poll(() => jobRequests.some((url) => {
    const params = new URL(url).searchParams;
    return params.get("new_today_only") === "true" && params.get("company") === "openai";
  })).toBe(true);

  await page.keyboard.press("Escape");
  await lensChip.click();
  await expect(page.getByRole("button", { name: msg("radar-new-today"), exact: true })).toHaveCount(0);
  await expect.poll(() => jobRequests.some((url) => new URL(url).searchParams.get("new_today_only") === "false")).toBe(true);
});

test("the Mac panel's new-roles address opens the board on New, then leaves the address", async ({ page }) => {
  const jobRequests: string[] = [];
  await page.route("/api/jobs?**", (route) => {
    jobRequests.push(route.request().url());
    return route.fulfill({ json: jobListFixture });
  });

  await page.goto("/?lens=new");

  const lensChip = page.getByRole("button", { name: msg("radar-new-today"), exact: true });
  await expect(lensChip).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByRole("button", { name: "1 new in the last 2 days" })).toHaveAttribute("aria-pressed", "true");
  await expect.poll(() => jobRequests.some((url) => new URL(url).searchParams.get("new_today_only") === "true")).toBe(true);
  await expect(page).toHaveURL((url) => url.pathname === "/" && url.search === "");

  // The lens lives in the page, not the address: a reload is the open board.
  await page.reload();
  await expect(page.getByRole("button", { name: msg("radar-new-today"), exact: true })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "1 new in the last 2 days" })).toHaveAttribute("aria-pressed", "false");
});

/* The top bar's counts are ONE choice, like tabs: open roles, new,
   reposted, saved. Whichever was clicked last is the one lit, and it is what
   the page shows. A lens kept beside the route rather than in it fails three
   ways: "open roles" leaves a lens on, so the board keeps filtering under a
   chip that says it is not; "saved" leaves "new" lit on the Saved
   screen; and the lens comes back the next time the board opens, from any
   door. */
test("the top-bar counts are one choice: whatever you click is what you see", async ({
  page, isMobile,
}) => {
  test.skip(isMobile, "the compact header hides the open-roles and saved counts");
  const lists: URLSearchParams[] = [];
  await page.route("/api/jobs?**", (route) => {
    const url = new URL(route.request().url());
    if (url.searchParams.get("limit") !== "1" && url.searchParams.get("favorites_only") !== "true") {
      lists.push(url.searchParams);
    }
    return route.fulfill({ json: twoJobList });
  });
  await page.route("/api/stats", (route) => route.fulfill({ json: { ...statsFixture, reposted_today: 2 } }));
  await page.setViewportSize({ width: 1600, height: 900 });
  await page.goto("/");

  const bar = page.getByRole("banner", { name: "Application navigation" });
  const openRoles = bar.getByRole("link", { name: /open roles?$/ });
  const newToday = bar.getByRole("button", { name: "1 new in the last 2 days" });
  const reposted = bar.getByRole("button", { name: "2 reposted today" });
  const saved = bar.getByRole("link", { name: /saved roles$/ });
  const lensChip = page.getByRole("button", { name: msg("radar-new-today"), exact: true });
  const last = () => lists.at(-1);
  const lensesSent = () => `${last()?.get("new_today_only")}/${last()?.get("repost_today_only")}`;

  // The plain board: open roles is the one lit.
  await expect(openRoles).toHaveAttribute("aria-current", "page");
  await expect(newToday).toHaveAttribute("aria-pressed", "false");

  // New: it lights, and open roles goes dark, since the board now shows
  // a subset of the open roles.
  await newToday.click();
  await expect.poll(lensesSent).toBe("true/false");
  await expect(newToday).toHaveAttribute("aria-pressed", "true");
  await expect(openRoles).not.toHaveAttribute("aria-current", "page");

  // Open roles: the lens comes off, on the list and on the chip.
  await openRoles.click();
  await expect.poll(lensesSent).toBe("false/false");
  await expect(lensChip).toHaveCount(0);
  await expect(newToday).toHaveAttribute("aria-pressed", "false");
  await expect(openRoles).toHaveAttribute("aria-current", "page");

  // Reposted and new replace each other; a second click on the chip
  // already chosen keeps it chosen, never flips back to something unclicked.
  await reposted.click();
  await expect.poll(lensesSent).toBe("false/true");
  await reposted.click();
  await expect(reposted).toHaveAttribute("aria-pressed", "true");
  await newToday.click();
  await expect.poll(lensesSent).toBe("true/false");
  await expect(reposted).toHaveAttribute("aria-pressed", "false");
  await newToday.click();
  await expect(newToday).toHaveAttribute("aria-pressed", "true");
  await expect(openRoles).not.toHaveAttribute("aria-current", "page");

  // A role opened from the board is a cover OVER it, not a departure: close
  // it and the board is still the one that was chosen, lens and all.
  await page.getByRole("article").filter({ hasText: "Staff Product Manager, API" })
    .getByText("Staff Product Manager, API").click();
  const cover = page.getByRole("dialog", { name: /^Role:/ });
  await expect(cover).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(cover).toHaveCount(0);
  await expect(newToday).toHaveAttribute("aria-pressed", "true");
  await expect(lensChip).toBeVisible();
  expect(lensesSent()).toBe("true/false");

  // Saved: only saved is lit there.
  await saved.click();
  await expect(page).toHaveURL(/\/favorites$/);
  await expect(saved).toHaveAttribute("aria-current", "page");
  await expect(newToday).toHaveAttribute("aria-pressed", "false");
  await expect(openRoles).not.toHaveAttribute("aria-current", "page");

  // And the lens does not wait for the board's next visit: back through the
  // rail, it is the plain board again.
  const before = lists.length;
  await page.getByRole("navigation", { name: "Primary" }).getByRole("link", { name: "Radar" }).click();
  await expect.poll(() => lists.length).toBeGreaterThan(before);
  expect(lensesSent()).toBe("false/false");
  await expect(lensChip).toHaveCount(0);
  await expect(openRoles).toHaveAttribute("aria-current", "page");
});

test("discloses-pay filter reaches the API, is worn as state, and clears in place", async ({ page }) => {
  const jobRequests: string[] = [];
  await page.route("/api/jobs?**", (route) => {
    jobRequests.push(route.request().url());
    return route.fulfill({ json: jobListFixture });
  });

  await page.goto("/");
  await page.getByRole("button", { name: /^Filters/ }).click();
  // Situational, so it lives behind the drawer; and it is ONE boolean, so it
  // is a switch rather than an "Any / Discloses pay" track.
  await openMoreFilters(page);
  const pay = page.getByRole("checkbox", { name: "Posts a range" });
  await pay.check();

  await expect
    .poll(() => jobRequests.some((url) => new URL(url).searchParams.get("discloses_pay") === "true"))
    .toBe(true);
  await expect(pay).toBeChecked();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("button", { name: "Filters · 1" })).toBeVisible();

  // Clearing happens where the state lives — and the drawer has opened itself,
  // because a count on a closed door hides what is narrowing the list.
  await page.getByRole("button", { name: "Filters · 1" }).click();
  await expect(page.getByRole("button", { name: "More filters · 1" })).toHaveAttribute(
    "aria-expanded",
    "true",
  );
  await page.getByRole("checkbox", { name: "Posts a range" }).uncheck();

  await expect
    .poll(() => jobRequests.some((url) => new URL(url).searchParams.get("discloses_pay") === "false"))
    .toBe(true);
});

test("every position family, including sales, can be selected directly", async ({ page }) => {
  const jobRequests: string[] = [];
  await page.route("/api/jobs?**", (route) => {
    jobRequests.push(route.request().url());
    return route.fulfill({ json: jobListFixture });
  });

  await page.goto("/");
  // Below rail widths the register lives behind the toolbar's Filters opener;
  // every group is present there, position type included.
  await page.getByRole("button", { name: "Filters", exact: true }).click();
  await expect(page.getByRole("dialog", { name: "Filters" })).toBeVisible();
  await openMoreFilters(page);
  await page.getByRole("button", { name: "Discipline", exact: true }).click();
  await page.getByRole("checkbox", { name: "Sales & Business Development", exact: true }).click();

  await expect
    .poll(() => jobRequests.some((url) => new URL(url).searchParams.getAll("family").includes("sales_business_development")))
    .toBe(true);
});

test("dismissing a role hides it, and the pill in the margin is a one-click way back", async ({ page }) => {
  let feedbackPut: Record<string, unknown> | null = null;
  let undone = 0;
  await page.route("/api/jobs/101/feedback", (route) => {
    if (route.request().method() === "DELETE") {
      undone += 1;
      return route.fulfill({ json: { job_id: 101, is_dismissed: false } });
    }
    feedbackPut = route.request().postDataJSON();
    return route.fulfill({ json: {
      job_id: 101,
      is_dismissed: true,
      reason: null,
      company: "openai",
      department: "Product",
      team: "API",
    } });
  });

  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/");
  const row = page.getByRole("article").filter({ hasText: "Staff Product Manager, API" });
  await expect(row).toBeVisible();

  // "Not for me" removes the row without opening it.
  await row.getByRole("button", { name: "Not for me" }).click();
  await expect(row).toHaveCount(0);
  await expect.poll(() => feedbackPut).toEqual({ verdict: "dismissed", reason: null });

  // Where the row was, a zero-height seam; level with it in the margin, the
  // way-back pill, which is the undo. Nothing else on the page changed: no
  // strip, no callout, no scar.
  const seam = page.locator(".job-seam[data-seam-for=\"101\"]");
  await expect(seam).toHaveCount(1);
  await expect(seam).toHaveCSS("height", "0px");
  const beacon = page.getByRole("button", { name: msg("jobs-dismissed-aria", { title: "Staff Product Manager, API" }) });
  await expect(beacon).toBeVisible();
  await expect(beacon.locator("xpath=ancestor::*[contains(@class,'job-beacon')]")).not.toHaveAttribute("data-docked");

  // The reveal names the role — and offers NO rule: that decision lives in
  // the Not-for-me lens. On a pointer it opens on hover and the pill's
  // click IS the undo; on the phone (no hover) the tap opens it and Undo is
  // its primary.
  const touch = test.info().project.name === "mobile";
  if (touch) await beacon.click(); else await beacon.hover();
  const reveal = page.getByRole("dialog", { name: "Not for me" });
  await expect(reveal).toContainText("Staff Product Manager, API");
  await expect(reveal.getByRole("button", { name: /exclude/ })).toHaveCount(0);

  // Reaching the reveal without a pointer. The pill's Enter runs the undo, so
  // ArrowDown is the keyboard's only way in (MarginBeacon) — and it is the
  // branch no other spec drives. Pointer project only: the tap above is how
  // the phone already got here.
  if (!touch) {
    await page.mouse.move(0, 0);
    await expect(reveal).toHaveCount(0);
    await beacon.focus();
    await page.keyboard.press("ArrowDown");
    await expect(reveal).toContainText("Staff Product Manager, API");
    // Opened by key it TAKES focus (a hover-opened one must not), so the Undo
    // inside is a Tab away rather than behind a hover the keyboard cannot do.
    await expect(reveal).toBeFocused();
    await page.keyboard.press("Tab");
    await expect(reveal.getByRole("button", { name: msg("common-undo") })).toBeFocused();
  }

  // One click is the undo: the row is back, the pill is gone.
  if (touch) await reveal.getByRole("button", { name: msg("common-undo") }).click(); else await beacon.click();
  await expect.poll(() => undone).toBe(1);
  await expect(row).toBeVisible();
  await expect(beacon).toHaveCount(0);
  await expect(seam).toHaveCount(0);
});

test("the way back leaves on its own, and a second dismissal moves it rather than stacking", async ({ page }) => {
  await page.route("/api/jobs/*/feedback", (route) => {
    const id = Number(route.request().url().match(/jobs\/(\d+)\/feedback/)![1]);
    return route.fulfill({ json: { job_id: id, is_dismissed: true, reason: null, company: "openai", department: null, team: null } });
  });
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/");
  // Installed after load, so the app's own boot timers ran for real; from
  // here the way back's clock is ours to advance.
  await page.clock.install();
  const first = page.getByRole("article").filter({ hasText: "Staff Product Manager, API" });
  const second = page.getByRole("article").filter({ hasText: "Principal Engineer, Platform" });
  await expect(first).toBeVisible();

  await first.getByRole("button", { name: "Not for me" }).click();
  await expect(page.getByRole("button", { name: msg("jobs-dismissed-aria", { title: "Staff Product Manager, API" }) })).toBeVisible();
  await page.clock.runFor(5000);
  await second.getByRole("button", { name: "Not for me" }).click();
  // The pill is the SECOND role's now; the first waits in the lens. That was
  // the last row on the page, so the list is empty and the pill DOCKS — the
  // way back survives an emptied list.
  const pill = page.getByRole("button", { name: msg("jobs-dismissed-aria", { title: "Principal Engineer, Platform" }) });
  await expect(pill).toBeVisible();
  await expect(pill.locator("xpath=ancestor::*[contains(@class,'job-beacon')]")).toHaveAttribute("data-docked", "true");
  await expect(page.getByRole("button", { name: /Marked Staff Product Manager/ })).toHaveCount(0);
  // The second click gave it a full clock: alive at 7s, gone after 8s.
  await page.clock.runFor(7000);
  await expect(page.getByRole("button", { name: /Marked Principal/ })).toBeVisible();
  await page.clock.runFor(1500);
  await expect(page.getByRole("button", { name: /Not for me\. Undo/ })).toHaveCount(0);
  await expect(page.locator(".job-seam")).toHaveCount(0);
});

/* The MODE: which population the board is showing. Open roles is
   the board itself — the top bar's own count links to it — and Closed and
   Not-for-me sit at the FOOT of `More filters`, because a reader goes there on
   purpose and comes back. They are exclusive by construction (one control,
   three positions), they count as one filter, and `?show=` carries them so the
   view is shareable and the top bar's plain `/` can undo them. */
test("Not for me, reached from the drawer, restores a role and grows a standing rule", async ({
  page,
}) => {
  // The LIST requests only; the baseline asks for one row and is not one.
  const lists: URLSearchParams[] = [];
  let rulePost: Record<string, unknown> | null = null;
  await page.route("/api/jobs?**", (route) => {
    const url = new URL(route.request().url());
    const counting = url.searchParams.get("limit") === "1";
    if (!counting) lists.push(url.searchParams);
    if (url.searchParams.get("dismissed_only") === "true") {
      return route.fulfill({ json: counting
        ? { ...twoJobList, total: 12, items: [] }
        : { ...twoJobList, total: 1, items: [{ ...jobFixture, is_dismissed: true }] } });
    }
    return route.fulfill({ json: twoJobList });
  });
  await page.route("/api/scope/rules", (route) => {
    rulePost = route.request().postDataJSON();
    return route.fulfill({ json: {
      rule: { id: 1, company: "openai", kind: "team", value: "API", created_at: "2026-08-06T00:00:00Z" },
      created: true,
      in_scope_changed: 4,
    } });
  });

  // Both homes of the register: the pinned rail, and the folded panel below it.
  for (const width of [1600, 1200]) {
    await page.setViewportSize({ width, height: 900 });
    await page.goto("/");
    // Nothing about the other populations is on the page until it is asked for.
    await expect(page.getByRole("tablist", { name: "Which roles" })).toHaveCount(0);
    await expect(page.getByRole("group", { name: "Showing" })).toHaveCount(0);

    if (width < 1360) await page.getByRole("button", { name: /^Filters/ }).click();
    await openMoreFilters(page);
    await page.getByRole("group", { name: "Showing" }).getByRole("button", { name: "Not for me" }).click();

    await expect.poll(() => lists.at(-1)?.get("dismissed_only"), { message: `${width}px` }).toBe("true");
    // A role you marked is yours whatever the market did with the posting.
    expect(lists.at(-1)!.get("status")).toBe("");
    // Shareable: the view is in the address, so the link survives a reload.
    await expect(page).toHaveURL(/show=not-for-me/);
    if (width < 1360) await page.keyboard.press("Escape");
    // It IS a filter now, and it counts as exactly one.
    await expect(page.getByRole("button", { name: "Filters · 1" })).toBeVisible();
  }

  // The count names the lens in the reader's words, and the row offers restore.
  await expect(page.getByText("1 role you marked Not for me")).toBeVisible();
  const row = page.getByRole("article").filter({ hasText: "Staff Product Manager, API" });
  await expect(row.getByRole("button", { name: msg("jobs-restore") })).toBeVisible();

  // The employer's own vocabulary is offered HERE, verbatim, under the row —
  // and confirming is the ONLY path that ever writes a rule.
  await expect(row.getByRole("button", { name: /all of “Product”/ })).toBeVisible();
  await row.getByRole("button", { name: /all of “API”/ }).click();
  await expect.poll(() => rulePost).toEqual({ company: "openai", kind: "team", value: "API" });
  await expect(
    page.getByRole("status").filter({ hasText: "left your radar" })
  ).toContainText(msg("radar-exclude-done", { count: 4, value: "API" }));

  // The way out is the top bar's own count of open roles.
  const before = lists.length;
  await page.getByRole("link", { name: /open roles?$/ }).click();
  await expect(page).not.toHaveURL(/show=/);
  await expect.poll(() => lists.at(-1)?.get("status")).toBe("open");

  /* And it SETTLES there. The URL and the filters mirror each other in both
     directions, and a mirror that guards neither flips the board
     open/closed/open/closed on one click and leaves the losing response's
     empty list on screen. Polling the last request cannot see it (the last
     request is right either way), so this counts the requests and reads the
     rows that actually rendered. */
  expect(lists.length - before).toBeLessThanOrEqual(2);
  await expect(page.getByRole("article")).toHaveCount(twoJobList.items.length);
  expect(lists.at(-1)!.get("dismissed_only")).toBe("false");
});

test("the empty pile teaches the control, and its way out switches the whole mode", async ({ page }) => {
  // BoardModeTabs is on the list, at full width, so no group can overflow the
  // rail. This pins the EMPTY state, and a second claim: see the way out below.
  const lists: URLSearchParams[] = [];
  await page.route("/api/jobs?**", (route) => {
    const url = new URL(route.request().url());
    const counting = url.searchParams.get("limit") === "1";
    if (!counting) lists.push(url.searchParams);
    if (url.searchParams.get("dismissed_only") === "true") {
      return route.fulfill({ json: { ...twoJobList, total: 0, items: [] } });
    }
    return route.fulfill({ json: twoJobList });
  });
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/?show=not-for-me");

  // An empty PILE says so and names the control that fills it — it does not
  // blame a filter, because no filter is holding anything back here.
  await expect(page.getByText("Nothing marked “Not for me”")).toBeVisible();
  await page.locator(".empty, .ui-empty-inline").getByRole("button", { name: msg("radar-show-all") }).click();
  await expect(page.getByRole("article").filter({ hasText: "Staff Product Manager, API" })).toBeVisible();

  // ...and the way out switches the whole MODE. Clearing `dismissed_only`
  // alone would leave the pile's empty `status` behind, so the list would
  // show open and closed roles together under a tab bar still reading Open.
  await expect.poll(() => lists.at(-1)?.get("status")).toBe("open");
  expect(lists.at(-1)!.get("dismissed_only")).toBe("false");
  // ...and the address follows, so the way out is also shareable.
  await expect(page).not.toHaveURL(/show=/);
});

test("Reset all clears the filters and leaves you where you are", async ({ page }) => {
  /* It clears every FILTER and lens; the mode is which list you are looking
     at, and the way back to the open board is the top bar's own count of open
     roles. Clearing both here would also race: `setSearchParams` does not
     queue its functional form, so the company deletion recomputes from params
     that still carry `?show=` and puts it straight back. */
  const lists: URLSearchParams[] = [];
  await page.route("/api/jobs?**", (route) => {
    const url = new URL(route.request().url());
    if (url.searchParams.get("limit") !== "1") lists.push(url.searchParams);
    return route.fulfill({ json: twoJobList });
  });

  await page.setViewportSize({ width: 1600, height: 800 });
  await page.goto("/?company=amazon&show=closed");
  await expect.poll(() => lists.at(-1)?.get("status")).toBe("closed");
  // A departure from the open board opens the drawer that holds it.
  await expect(page.getByRole("button", { name: /^More filters · / })).toHaveAttribute(
    "aria-expanded",
    "true",
  );

  await page.getByRole("button", { name: "Reset all" }).click();
  await expect.poll(() => lists.at(-1)?.getAll("company")).toEqual([]);
  // Still on the closed list, and the address still says so — the two never
  // disagree, which is the whole reason the mode has ONE writer.
  expect(lists.at(-1)!.get("status")).toBe("closed");
  await expect(page).toHaveURL(/show=closed/);
  await expect(page.getByRole("group", { name: "Showing" }).getByRole("button", { name: "Closed" }))
    .toHaveAttribute("aria-pressed", "true");
});

/* The company filter has ONE writer, the URL, like the mode. The board stays
   mounted when the address changes, so a filter seeded from `?company=` once
   at mount and mirrored back (filters -> URL) would still hold the company
   when the top bar's "open roles" link reaches `/`, write `?company=` straight
   back, and land on the same filtered list the link was clicked from. */
test("open roles reaches the unfiltered board from a company's roles, and settles there", async ({
  page, isMobile,
}) => {
  test.skip(isMobile, "the compact header hides the open-roles count");
  const lists: URLSearchParams[] = [];
  await page.route("/api/jobs?**", (route) => {
    const url = new URL(route.request().url());
    if (url.searchParams.get("limit") !== "1") lists.push(url.searchParams);
    return route.fulfill({ json: twoJobList });
  });
  await page.setViewportSize({ width: 1600, height: 900 });
  await page.goto("/?company=amazon");
  await expect.poll(() => lists.at(-1)?.getAll("company")).toEqual(["amazon"]);
  const rail = page.getByRole("complementary", { name: "Filters" });
  await expect(rail.getByRole("checkbox", { name: "Amazon" })).toBeChecked();

  const before = lists.length;
  await page.getByRole("banner", { name: "Application navigation" })
    .getByRole("link", { name: /open roles?$/ }).click();
  await expect.poll(() => lists.at(-1)?.getAll("company")).toEqual([]);
  // Nothing is chosen any more, so the closed group has no row to show.
  await expect(rail.getByRole("checkbox", { name: "Amazon" })).toHaveCount(0);

  /* And it STAYS there. A mirror's write-back lands after the click, so
     the last request alone cannot see a bounce that is still coming: wait
     past it, then read the address, the last request and the count. */
  await page.waitForTimeout(750);
  expect(new URL(page.url()).searchParams.getAll("company")).toEqual([]);
  expect(lists.at(-1)!.getAll("company")).toEqual([]);
  expect(lists.length - before).toBeLessThanOrEqual(2);
  await expect(page.getByRole("article")).toHaveCount(twoJobList.items.length);
});

test("the register's company choice goes through the address, beside the params already there", async ({
  page,
}) => {
  const lists: URLSearchParams[] = [];
  await page.route("/api/jobs?**", (route) => {
    const url = new URL(route.request().url());
    if (url.searchParams.get("limit") !== "1") lists.push(url.searchParams);
    return route.fulfill({ json: twoJobList });
  });
  await page.setViewportSize({ width: 1600, height: 900 });
  await page.goto("/?show=closed");
  const rail = page.getByRole("complementary", { name: "Filters" });

  // A choice in the register goes to the URL first and lands from there, so
  // the list, the checkbox and the address can never disagree. The other
  // params ride along untouched.
  await rail.getByRole("button", { name: "Company", exact: true }).click();
  await rail.getByRole("checkbox", { name: "Amazon" }).check();
  await rail.getByRole("checkbox", { name: "OpenAI" }).check();
  await expect.poll(() => lists.at(-1)?.getAll("company")).toEqual(["amazon", "openai"]);
  await expect(page).toHaveURL(/company=amazon&company=openai/);
  await expect(page).toHaveURL(/show=closed/);
  expect(lists.at(-1)!.get("status")).toBe("closed");

  await rail.getByRole("checkbox", { name: "Amazon" }).uncheck();
  await expect.poll(() => lists.at(-1)?.getAll("company")).toEqual(["openai"]);
  await expect(page).not.toHaveURL(/company=amazon/);
  await expect(rail.getByRole("checkbox", { name: "OpenAI" })).toBeChecked();
});

test("the Unread lens drops read roles from the list while the reader hunts", async ({ page }) => {
  // One row the reader has opened, one they have not: the lens must tell
  // them apart, and the list must lose exactly the read one.
  const [first, second] = twoJobList.items;
  const list = {
    ...twoJobList,
    items: [{ ...first, viewed_at: "2026-07-15T18:30:00Z" }, { ...second, viewed_at: null }],
  };
  const unread = list.items.filter((j) => j.viewed_at == null);
  const seen: (string | null)[] = [];
  await page.route("/api/jobs?**", (route) => {
    const url = new URL(route.request().url());
    const viewed = url.searchParams.get("viewed");
    seen.push(viewed);
    if (viewed === "unread") {
      return route.fulfill({ json: { ...list, total: unread.length, items: unread } });
    }
    return route.fulfill({ json: list });
  });

  await page.goto("/");
  await expect(page.getByRole("article")).toHaveCount(list.items.length);
  // No lens by default: the request carries no `viewed` at all.
  expect(seen.at(-1)).toBeNull();

  await page.getByRole("button", { name: /^Filters/ }).click();
  const dialog = page.getByRole("dialog", { name: "Filters" });
  // One switch, and it leads the register — above every facet group.
  const lens = dialog.getByRole("checkbox", { name: "Unread only" });
  const leads = await dialog.evaluate((panel) => {
    const box = panel.querySelector<HTMLElement>('input[aria-label="Unread only"], .ui-switch input');
    const group = panel.querySelector<HTMLElement>("[role=group]");
    if (!box || !group) return null;
    return Boolean(box.compareDocumentPosition(group) & Node.DOCUMENT_POSITION_FOLLOWING);
  });
  expect(leads).toBe(true);
  await lens.check();

  await expect.poll(() => seen.at(-1)).toBe("unread");
  await page.keyboard.press("Escape");
  await expect(page.getByRole("article")).toHaveCount(unread.length);
  await expect(page.getByRole("button", { name: "Filters · 1" })).toBeVisible();
  await expect(page.locator(".results-count")).toHaveText(new RegExp(`${unread.length} of ${list.items.length} roles`));
});

/* The register has TWO homes — the pinned rail at >=1360px and the Filters
   panel below it — and a failed facets fetch must be recoverable from BOTH.
   BoardFilters has an error branch with retry; handed `facetsError` only in
   the folded mount, the register at rail widths renders an EMPTY <aside> with
   nothing to click and no way back. */
test("a failed facets fetch is recoverable from the pinned rail, not just the panel", async ({
  page,
}) => {
  // Fails until the test says otherwise. Attempt-counting would not do: React
  // StrictMode double-mounts in dev, so a "fail once" mock is satisfied by the
  // second mount and the empty rail never appears.
  let failing = true;
  await page.route("/api/facets", (route) =>
    failing
      ? route.fulfill({ status: 500, json: { detail: "facets exploded" } })
      : route.fulfill({ json: facetsFixture })
  );
  await page.setViewportSize({ width: 1600, height: 800 });
  await page.goto("/");

  // The rail is present and NOT empty: it states the failure and offers the
  // way back. Asserting on the accessible name, not a class.
  const rail = page.getByRole("complementary", { name: "Filters" });
  await expect(rail).toContainText(/couldn't load|could not load/i);
  const retry = rail.getByRole("button", { name: "Try again" });
  await expect(retry).toBeVisible();

  // And retry actually re-fetches and paints the register.
  failing = false;
  await retry.click();
  await expect(rail.getByRole("button", { name: /^Company/ })).toBeVisible();
});

/* ------------------------------------------------------------------------- *
 * Filter memory. Two claims, and they are separate: WHAT the reader narrowed
 * by comes back, and WHICH groups they opened comes back. `?company=` and
 * `?show=` are the only filter state in the address, so without memory a
 * reload would keep two filters and a visit from the nav rail none.
 * ------------------------------------------------------------------------- */

test("the register remembers how you narrowed it, through a reload and a fresh visit", async ({
  page,
}) => {
  const lists: URLSearchParams[] = [];
  await page.route("/api/jobs?**", (route) => {
    const url = new URL(route.request().url());
    // The baseline asks for one row; Saved asks for favourites. Neither is
    // the board's list.
    if (url.searchParams.get("limit") !== "1" && url.searchParams.get("favorites_only") !== "true") {
      lists.push(url.searchParams);
    }
    return route.fulfill({ json: twoJobList });
  });
  await page.setViewportSize({ width: 1600, height: 900 });
  await page.goto("/");

  const rail = page.getByRole("complementary", { name: "Filters" });
  await rail.getByRole("button", { name: "Location", exact: true }).click();
  await rail.getByRole("checkbox", { name: "Silicon Valley" }).check();
  await rail.getByRole("button", { name: "More filters" }).click();
  await rail.getByRole("checkbox", { name: "Posts a range" }).check();
  await expect.poll(() => lists.at(-1)?.get("discloses_pay")).toBe("true");

  // A reload. Neither of these was ever in the address.
  await page.reload();
  await expect.poll(() => lists.at(-1)?.getAll("location_group")).toEqual(["silicon_valley"]);
  expect(lists.at(-1)!.get("discloses_pay")).toBe("true");
  await expect(rail.getByRole("checkbox", { name: "Silicon Valley" })).toBeChecked();

  // ...and a fresh visit from another screen, which lands on a bare `/`.
  await page.goto("/favorites");
  await page.goto("/");
  await expect.poll(() => lists.at(-1)?.getAll("location_group")).toEqual(["silicon_valley"]);
  expect(lists.at(-1)!.get("discloses_pay")).toBe("true");

  /* Reset all is a choice too, and it is remembered as one: coming back to a
     list still narrowed by what you just cleared would be the worst of both. */
  await page.locator(".results-count").getByRole("button", { name: "Reset all" }).click();
  await expect.poll(() => lists.at(-1)?.getAll("location_group")).toEqual([]);
  await page.goto("/");
  await expect.poll(() => lists.at(-1)?.get("discloses_pay")).toBe("false");
  expect(lists.at(-1)!.getAll("location_group")).toEqual([]);
});

test("a remembered company reaches the ADDRESS, so `/` still means the whole board", async ({
  page, isMobile,
}) => {
  test.skip(isMobile, "the compact header hides the open-roles count");
  const lists: URLSearchParams[] = [];
  await page.route("/api/jobs?**", (route) => {
    const url = new URL(route.request().url());
    if (url.searchParams.get("limit") !== "1") lists.push(url.searchParams);
    return route.fulfill({ json: twoJobList });
  });
  await page.setViewportSize({ width: 1600, height: 900 });
  await page.goto("/");
  const rail = page.getByRole("complementary", { name: "Filters" });
  await rail.getByRole("button", { name: "Company", exact: true }).click();
  await rail.getByRole("checkbox", { name: "Amazon" }).check();
  await expect(page).toHaveURL(/company=amazon/);
  // The address moves with the history entry; the choice is not recorded until
  // the render that asks for it lands, so settle on the request.
  await expect.poll(() => lists.at(-1)?.getAll("company")).toEqual(["amazon"]);

  /* Back to a bare `/`, and the company comes with it — INTO the address,
     not just into the register. The top bar's "N open roles" links to `/` and
     is the documented way back to the unfiltered board; a company
     that lived only in the rail would make that link a no-op. */
  await page.goto("/");
  await expect(page).toHaveURL(/company=amazon/);
  await expect(rail.getByRole("checkbox", { name: "Amazon" })).toBeChecked();

  const before = lists.length;
  await page.getByRole("banner", { name: "Application navigation" })
    .getByRole("link", { name: /open roles?$/ }).click();
  await expect.poll(() => lists.at(-1)?.getAll("company")).toEqual([]);
  await expect(page).not.toHaveURL(/company=/);
  // And it settles: no mirror writes the remembered company back.
  await page.waitForTimeout(750);
  expect(new URL(page.url()).searchParams.getAll("company")).toEqual([]);
  expect(lists.length - before).toBeLessThanOrEqual(2);
});

test("a group you open stays open; one you never touched stays shut", async ({ page }) => {
  await page.route("/api/jobs?**", (route) => route.fulfill({ json: twoJobList }));
  await page.setViewportSize({ width: 1600, height: 900 });
  await page.goto("/");
  const rail = page.getByRole("complementary", { name: "Filters" });
  const company = rail.getByRole("button", { name: "Company", exact: true });
  const location = rail.getByRole("button", { name: "Location", exact: true });

  await expect(company).toHaveAttribute("aria-expanded", "false");
  await company.click();
  await expect(rail.getByRole("checkbox", { name: "OpenAI" })).toBeVisible();

  await page.goto("/");
  await expect(company).toHaveAttribute("aria-expanded", "true");
  await expect(rail.getByRole("checkbox", { name: "OpenAI" })).toBeVisible();
  // Untouched is not the same as closed: Location is still at the default,
  // which is what lets that default change later without overruling anyone.
  await expect(location).toHaveAttribute("aria-expanded", "false");

  // Closing is a choice too, and it is kept.
  await company.click();
  await page.goto("/");
  await expect(company).toHaveAttribute("aria-expanded", "false");
  await expect(rail.getByRole("checkbox", { name: "OpenAI" })).toHaveCount(0);
});
