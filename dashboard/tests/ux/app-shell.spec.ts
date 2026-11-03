/* The shell's own failure modes — the ones that are not any screen's fault.

   Every screen is a lazy chunk, which makes every screen a NETWORK
   dependency. `<Suspense>` covers a pending import and nothing else, so
   without a boundary a rejected chunk throws past the root and leaves a blank
   document: a two-second connection blip costs the whole application, and
   `React.lazy` caches the rejection so even a manual retry re-throws the same
   error. */

import { expect, mockGet, test, type Page } from "./fixtures";
import { msg } from "../../src/test/msg";
import { installBoardRoutes } from "./boardHarness";
import { installEveryRoute } from "./routesHarness";
import { overviewFixture, statsFixture, statusFixture } from "../../src/test/fixtures";

test.beforeEach(async ({ page }) => {
  await installBoardRoutes(page);
});

/** Kill the Saved screen's chunk, open Saved, and return the failure it shows
 *  with a switch that lets the chunk through again. */
async function openSavedWithADeadChunk(page: Page) {
  /* Kill the Saved screen's chunk, BEFORE the first navigation.
     Matched by MODULE NAME, which holds in both forms this suite can run
     against: `/src/features/saved/SavedScreen.tsx` from a dev server, and
     `SavedScreen-<hash>.js` from a build (rollup names each chunk after the
     module it loads — routeRegistry's header relies on that).

     The ordering is the part that matters. A BUILT shell carries
     `<link rel="modulepreload">` for its route chunks, so the browser fetches
     SavedScreen during the initial load, before a route installed after
     `goto` exists. Installed late, the abort never fires, the click finds the
     module already resident, and the failure under test does not happen.
     Installed first, the preload is what gets aborted, which poisons the
     module map as the retry test explains and makes the later import reject
     without issuing a request of its own. */
  let failing = true;
  await page.route(/SavedScreen/, (route) =>
    failing ? route.abort("failed") : route.continue(),
  );

  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Radar", level: 1 })).toBeVisible();
  await page.getByRole("link", { name: "Saved", exact: true }).click();
  const alert = page.getByRole("alert");
  /* The failure must have happened before a caller lets the chunk through,
     or the import can race the switch and load, and there is nothing to retry. */
  await expect(alert.getByRole("button", { name: "Try again" })).toBeVisible();
  return { alert, letThrough: () => { failing = false; } };
}

test("a route chunk that fails to load is reported, not a blank page", async ({ page }) => {
  // Both engines: chrome intact, the failure stated, a way out offered.
  const { alert } = await openSavedWithADeadChunk(page);
  await expect(page.getByRole("navigation", { name: "Primary" })).toBeVisible();
  await expect(alert).toContainText(/couldn't load|could not load/i);
  await expect(alert.getByRole("button", { name: "Try again" })).toBeVisible();
});

test("trying again after a dead route chunk recovers the screen", async ({ page }) => {
  /* And retry genuinely recovers. It recovers by RELOADING, because nothing
     short of a new document can: the browser's module map holds the failed
     fetch for the page's lifetime, so a fresh React.lazy importing the same
     specifier issues no request at all (measured — see App.tsx).

     Chromium only, and the reason is the harness rather than the app: Once the
     suite serves a BUILD, WebKit keeps the aborted module fetch
     across a same-context reload: the reloaded document re-requests nothing and
     renders the boundary again. Measured, with a control that separates the two
     explanations — removing the interception entirely before the retry does NOT
     recover, while a plain navigation to /favorites in the same browser renders
     the Saved heading normally. So the application recovers on WebKit and the
     abort is what does not clear; asserting otherwise would be asserting a
     Playwright behaviour. The half that matters — a dead chunk is a stated,
     recoverable failure and not a blank page — is asserted above on BOTH
     engines. */
  test.skip(
    test.info().project.name === "mobile",
    "WebKit holds an aborted module fetch across the reload; the app recovers, the interception does not.",
  );
  const { alert, letThrough } = await openSavedWithADeadChunk(page);
  letThrough();
  await alert.getByRole("button", { name: "Try again" }).click();
  await expect(page.getByRole("heading", { name: "Saved", level: 1 })).toBeVisible();
});

test("a dead chunk does not poison the routes either side of it", async ({ page }) => {
  await page.route(/SavedScreen/, (route) => route.abort("failed"));
  await page.goto("/");
  await page.getByRole("link", { name: "Saved", exact: true }).click();
  await expect(page.getByRole("alert")).toBeVisible();

  // Navigating away must clear the boundary — otherwise one bad chunk blanks
  // every route reached afterwards, which is worse than one blank page.
  await page.getByRole("link", { name: "Radar", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Radar", level: 1 })).toBeVisible();
  await expect(page.getByRole("alert")).toHaveCount(0);
});

test("a tab opened once the first screen has drawn already has its code", async ({ page }) => {
  /* A screen whose code is fetched on the click asks for its data only once
     the code has arrived. The other screens are fetched one after another
     once the first has drawn, Compare last, so its module arriving means
     every tab is in hand. Matched by module name, which holds for a dev server
     and a build alike. */
  await installEveryRoute(page);
  const lastScreen = page.waitForResponse(/CompareRoute/);
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Radar", level: 1 })).toBeVisible();
  await lastScreen;

  const fetchedOnClick: string[] = [];
  page.on("request", (request) => {
    if (/StatisticsRoute/.test(request.url())) fetchedOnClick.push(request.url());
  });
  await page.getByRole("link", { name: "Insights", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Insights", level: 1 })).toBeVisible();
  expect(fetchedOnClick).toEqual([]);
});

/* Landmarks, the skip link, and the palette's announced selection — the three
   things a keyboard or screen-reader user needs before any screen's content
   matters. */
test("a browser that blocks site data still opens the app", async ({ page }) => {
  /* Blocked site data, as Safari and Firefox apply it: touching localStorage
     throws instead of returning nothing. The theme, the filter memory and the
     language all read it while the shell first renders. */
  await page.addInitScript(() => {
    Object.defineProperty(window, "localStorage", {
      configurable: true,
      get() { throw new DOMException("The operation is insecure.", "SecurityError"); },
    });
  });
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Radar", level: 1 })).toBeVisible();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await page.getByRole("button", { name: "Toggle theme" }).click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
});

test("every route offers exactly one main landmark", async ({ page }) => {
  await page.route("/api/statistics/overview**", (route) => route.fulfill({ json: overviewFixture }));
  await page.route("/api/company-profiles**", (route) => route.fulfill({ json: {
    items: [], attribution: null,
  } }));
  // A screen that renders `<div class="main">` is styled like a page and
  // invisible to landmark navigation. This one is not keyboard-specific, so it
  // runs on both projects — a phone user with a screen reader navigates by
  // landmark too.
  for (const path of ["/", "/favorites", "/statistics", "/company", "/notifications"]) {
    await page.goto(path);
    await expect(page.getByRole("main"), path).toHaveCount(1);
  }
});

/* The window never scrolls; a screen scrolls inside its own `main`. A
   visually hidden label (`.sr-only`, absolutely positioned) far down a screen is
   the case that broke it: with no positioned box between it and the root, it was
   laid out against the window, grew the document past it, and a wheel at the end
   of the page carried on into the document and slid the whole frame up, rail and
   top bar with it. The pay table's column heads on a company profile carry such a
   label. Each route gets one three windows down, so the check does not depend on
   how long a fixture happens to make the page. */
test("a hidden label far down a screen cannot make the window scroll", async ({ page, isMobile }) => {
  await installEveryRoute(page);
  for (const path of ["/", "/favorites", "/statistics", "/company", "/review", "/notifications", "/settings"]) {
    await page.goto(path);
    const main = page.getByRole("main");
    await expect(main, path).toBeVisible();
    await main.evaluate((node) => {
      const content = node.lastElementChild ?? node;
      const filler = document.createElement("div");
      filler.style.height = `${3 * window.innerHeight}px`;
      const label = document.createElement("span");
      label.className = "sr-only";
      label.id = "deep-label";
      label.textContent = "Total compensation";
      content.append(filler, label);
    });

    // The premise: the screen now overflows its own scroller.
    const room = await main.evaluate((node) => node.scrollHeight - node.clientHeight);
    expect(room, path).toBeGreaterThan(0);

    const size = await page.evaluate(() => ({
      document: document.scrollingElement!.scrollHeight,
      window: window.innerHeight,
    }));
    expect(size.document, path).toBeLessThanOrEqual(size.window);

    // Reaching the label (focus, find-in-page) scrolls the screen, not the frame.
    await page.locator("#deep-label").evaluate((node) => node.scrollIntoView());
    if (!isMobile) {
      await main.hover();
      for (let i = 0; i < 6; i += 1) await page.mouse.wheel(0, 2000);
    }
    const after = await main.evaluate((node) => ({
      windowY: window.scrollY,
      frameTop: Math.round(document.querySelector(".app")!.getBoundingClientRect().top),
      frameScroll: document.querySelector(".app")!.scrollTop,
      mainScrolled: node.scrollTop > 0,
    }));
    expect(after, path).toEqual({ windowY: 0, frameTop: 0, frameScroll: 0, mainScrolled: true });
  }
});

test("the skip link is the first tab stop and jumps past the chrome", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name === "mobile", "Skipping the chrome is a Tab-key flow; a phone has no Tab key.");
  await page.goto("/");
  /* The skip link is the first tab stop, and it sits off-screen until it is
     reached. Asserting on the BOX rather than on `toBeHidden`: it has to stay
     focusable, so it can never be `display:none` or `visibility:hidden`, and
     Playwright counts an off-screen box as visible. Where it is, is the claim. */
  const skip = page.getByRole("link", { name: "Skip to content" });
  const parked = await skip.boundingBox();
  expect(parked!.y + parked!.height).toBeLessThanOrEqual(0);

  await page.keyboard.press("Tab");
  await expect(skip).toBeFocused();
  await expect.poll(async () => (await skip.boundingBox())!.y).toBeGreaterThanOrEqual(0);

  await page.keyboard.press("Enter");
  await expect(page.locator("#main-content")).toBeFocused();
});

test("the command palette announces the highlighted command, not just paints it", async ({
  page,
}) => {
  await page.goto("/");
  // The shell listens for the shortcut once it has rendered, which
  // waits on the company names: a key pressed at page load can land
  // before the listener exists (the palette.spec readiness rule).
  await expect(page.getByRole("article").first()).toBeVisible({ timeout: 15_000 });
  await page.keyboard.press("ControlOrMeta+k");

  const input = page.getByRole("combobox", { name: "Command query" });
  await expect(input).toBeVisible();

  // The listbox owns its options directly — a wrapper element between them
  // breaks the pattern a screen reader relies on to count and report them.
  const listbox = page.getByRole("listbox", { name: "Commands" });
  const optionCount = await listbox.getByRole("option").count();
  expect(optionCount).toBeGreaterThan(0);

  // Focus stays in the input, so the SELECTION has to travel through
  // aria-activedescendant or arrow keys are silent.
  const first = await input.getAttribute("aria-activedescendant");
  expect(first).toBeTruthy();
  await page.keyboard.press("ArrowDown");
  await expect
    .poll(() => input.getAttribute("aria-activedescendant"))
    .not.toBe(first);

  // And whatever it points at is a real option that says it is selected.
  const activeId = await input.getAttribute("aria-activedescendant");
  const active = page.locator(`#${activeId}`);
  await expect(active).toHaveAttribute("role", "option");
  await expect(active).toHaveAttribute("aria-selected", "true");
});

test("closing the palette gives focus back to where it was", async ({ page }) => {
  await page.goto("/");
  const search = page.getByRole("searchbox", { name: "Search titles and descriptions" });
  await search.click();
  await expect(search).toBeFocused();

  await page.keyboard.press("ControlOrMeta+k");
  await expect(page.getByRole("combobox", { name: "Command query" })).toBeFocused();

  // Focus dropped on <body> would lose the user's place in the page.
  await page.keyboard.press("Escape");
  await expect(search).toBeFocused();
});

/* The bottom dock on a phone.
 *
 * The rail becomes a fixed dock under 860px. Ten destinations at the 44px
 * touch minimum need 440px, more than a phone's dock has after its padding, so
 * dividing the width ten ways with `flex: 1` shrinks every target below the
 * minimum and lets labels run wider than the boxes holding them.
 *
 * A screenshot of overlapping 11px labels reads as dense rather than broken,
 * so these assertions measure the computed boxes.
 */
test("the mobile dock keeps legal touch targets and labels inside their boxes", async ({
  page,
}, testInfo) => {
  test.skip(testInfo.project.name !== "mobile", "phone-width layout");

  await page.goto("/");
  const items = page.locator(".nav-rail .rail-item");
  // `count()` does not wait: read it once the dock has drawn.
  await expect(items.first()).toBeVisible();
  const count = await items.count();
  expect(count, "the dock rendered no destinations at all").toBeGreaterThan(5);

  for (let i = 0; i < count; i += 1) {
    const item = items.nth(i);
    const name = (await item.getAttribute("aria-label")) ?? `item ${i}`;
    const box = await item.boundingBox();
    expect(box, `${name} has no box`).not.toBeNull();
    // WCAG 2.5.5 / platform touch minimum.
    expect(
      Math.round(box!.width),
      `${name} is a ${Math.round(box!.width)}px-wide touch target`,
    ).toBeGreaterThanOrEqual(44);

    /* The failure is a label PAINTING outside its item and over the next one,
       so the property is containment of the rendered box, not whether the text
       is clipped. Clipping is the answer (an ellipsis plus the icon and the item's
       aria-label), and asserting `scrollWidth <= clientWidth` would forbid it
       and demand the overflow back. */
    const label = item.locator(".rail-label");
    const labelBox = await label.boundingBox();
    expect(labelBox, `${name} has no label box`).not.toBeNull();
    expect(
      Math.round(labelBox!.x),
      `${name}'s label starts left of its own item`,
    ).toBeGreaterThanOrEqual(Math.round(box!.x) - 1);
    expect(
      Math.round(labelBox!.x + labelBox!.width),
      `${name}'s label paints past its item and onto the next`,
    ).toBeLessThanOrEqual(Math.round(box!.x + box!.width) + 1);
  }
});

/* The same failure one level up, which the assertions above cannot see: they
 * measure a label against ITS OWN item, so they hold perfectly while the items
 * themselves are stacked on top of each other.
 *
 * The dock is `overflow-x: auto` so ten destinations can scroll. Groups that
 * divide the dock's width between them whatever they hold (`flex: 5 1 0` and
 * `flex: 2 1 0`) always sum to exactly the dock's width, so the scroll never
 * engages and a group overflowing visibly paints its items over the other
 * group's. The overlap shrinks as the viewport widens, so a desktop check
 * cannot find it.
 *
 * The invariant is that the dock's destinations do not overlap each other. It
 * is deliberately NOT `scrollWidth <= clientWidth`: the dock is supposed to
 * overflow and scroll, and asserting containment in the viewport would demand
 * the squeeze back. */
test("the mobile dock's destinations do not overlap each other", async ({
  page,
}, testInfo) => {
  test.skip(testInfo.project.name !== "mobile", "phone-width layout");

  await page.goto("/");
  const items = page.locator(".nav-rail .rail-item");
  // `count()` does not wait: read it once the dock has drawn.
  await expect(items.first()).toBeVisible();
  const count = await items.count();
  expect(count, "the dock rendered no destinations at all").toBeGreaterThan(5);

  const boxes: { name: string; x: number; right: number }[] = [];
  for (let i = 0; i < count; i += 1) {
    const item = items.nth(i);
    const name = (await item.getAttribute("aria-label")) ?? `item ${i}`;
    const box = await item.boundingBox();
    expect(box, `${name} has no box`).not.toBeNull();
    boxes.push({ name, x: box!.x, right: box!.x + box!.width });
  }

  /* Source order is not paint order once a group overflows, so compare every
     pair rather than each item against its predecessor. */
  boxes.sort((a, b) => a.x - b.x);
  for (let i = 1; i < boxes.length; i += 1) {
    const prev = boxes[i - 1];
    const cur = boxes[i];
    expect(
      Math.round(cur.x),
      `${prev.name} and ${cur.name} overlap by ${Math.round(prev.right - cur.x)}px in the dock`,
    ).toBeGreaterThanOrEqual(Math.round(prev.right) - 1);
  }
});

/* The rail's count badges, on both sides of the cap.
 *
 * `review_pending` counts pending duplicate/twin links, which every scrape
 * refills, so a `99+` badge would never settle: a call to action that is
 * always on. Past the cap the badge stops claiming to be a count and hands the
 * exact one to the item.
 *
 * The geometry is measured rather than taken from the class, because that is
 * the half a class assertion cannot see: `.rail-badge` is sized in three
 * places (collapsed, expanded, and the dock's own block), so a dot rule that
 * loses on specificity leaves a full-size pill with no digits in it — which
 * looks deliberate and says less than `99+` would. */
test("a rail count past the cap becomes a dot that still carries the exact number", async ({
  page,
}) => {
  await mockGet(page, "/api/stats", (route) =>
    route.fulfill({ json: { ...statsFixture, review_pending: 342, notif_unread: 7 } }));

  await page.goto("/");

  const review = page.getByRole("link", { name: "Duplicates, 342 pending" });
  await expect(review).toHaveAttribute("title", "Duplicates, 342 pending");
  await expect(review).toHaveAttribute("data-tip", "Duplicates, 342 pending");
  await expect(review).not.toContainText("99+");

  const dot = review.locator(".rail-badge");
  await expect(dot).toHaveText("");
  const dotBox = await dot.boundingBox();
  expect(dotBox, "the dot did not render at all").not.toBeNull();
  expect(
    Math.round(dotBox!.width),
    `a ${Math.round(dotBox!.width)}px badge with no digits in it is not a dot`,
  ).toBeLessThanOrEqual(12);

  // Below the cap nothing changes: a count a user can act on stays a count.
  const notifications = page.getByRole("link", { name: "Notifications, 7 unread" });
  const pill = notifications.locator(".rail-badge");
  await expect(pill).toHaveText("7");
  const pillBox = await pill.boundingBox();
  expect(Math.round(pillBox!.width)).toBeGreaterThan(Math.round(dotBox!.width));
});

/* The bell paints the SAME number as the rail's Notifications badge, in the
 * same viewport, so a cap applied to one and not the other would put two
 * spellings of one count on screen at once. */
test("the bell caps the same count the same way", async ({ page, isMobile }) => {
  test.skip(isMobile, "the bell lives in the desktop topbar");

  await mockGet(page, "/api/stats", (route) =>
    route.fulfill({ json: { ...statsFixture, notif_unread: 128 } }));

  await page.goto("/");

  const bell = page.getByRole("button", { name: "Notifications, 128 unread" });
  await expect(bell).toBeVisible();
  await expect(bell.locator(".bell-badge")).toHaveText("");
  const box = await bell.locator(".bell-badge").boundingBox();
  expect(Math.round(box!.width)).toBeLessThanOrEqual(15);
});

/* The top bar's counts are readable in every shape and state. Two of
 * the four chips are <button>s, and a button's user-agent colour is black: a
 * chip that does not inherit its ink paints its count black on the dark glass.
 * Pinned in the browser, because a stylesheet gate cannot see what a
 * UA default paints over. */
test("every count in the top bar wears the bar's ink, chosen or not, and its unit is not below the whisper floor", async ({ page, isMobile }) => {
  test.skip(isMobile, "The compact bar hides the reposted and open-roles chips.");
  await mockGet(page, "/api/stats", (route) =>
    route.fulfill({ json: { ...statsFixture, open_total: 2004, new_today: 873, reposted_today: 49, saved_total: 4 } }));
  await page.setViewportSize({ width: 1440, height: 800 });
  await page.goto("/");
  await expect(page.locator(".job-row").first()).toBeVisible();

  const read = () =>
    page.locator(".top-stats .stat-chip").evaluateAll((chips) =>
      chips.map((chip) => ({
        label: chip.getAttribute("aria-label"),
        pressed: chip.getAttribute("aria-pressed") ?? chip.getAttribute("aria-current"),
        n: getComputedStyle(chip.querySelector(".n")!).color,
        unitPx: parseFloat(getComputedStyle(chip.querySelector(".l")!).fontSize),
        numeralWeight: Number(getComputedStyle(chip.querySelector(".n")!).fontWeight),
      })),
    );
  const at_rest = await read();
  expect(at_rest.map((c) => c.label)).toEqual([
    msg("shell-stat-open-aria", { count: 2004 }),
    msg("shell-stat-new-aria", { count: 873 }),
    msg("shell-stat-reposted-aria", { count: 49 }),
    msg("shell-stat-saved-aria", { count: 4 }),
  ]);
  // No chip paints its number in the UA's black; the reposted button reads
  // exactly like the saved link beside it.
  for (const c of at_rest) expect(c.n, c.label!).not.toBe("rgb(0, 0, 0)");
  expect(at_rest[2].n).toBe(at_rest[3].n);
  for (const c of at_rest) {
    expect(c.unitPx, c.label!).toBeGreaterThanOrEqual(9);
    expect(c.numeralWeight, c.label!).toBeLessThanOrEqual(600);
  }

  // Choosing the reposted lens: the pressed chip changes ink, and the ink it
  // changes to is the accent every other chosen chip wears.
  await page.getByRole("button", { name: "49 reposted today" }).click();
  await expect(page.getByRole("button", { name: "49 reposted today" })).toHaveAttribute("aria-pressed", "true");
  const chosen = await read();
  expect(chosen[2].n).not.toBe(at_rest[2].n);
  expect(chosen[2].n).not.toBe("rgb(0, 0, 0)");
  await page.getByRole("link", { name: msg("shell-stat-open-aria", { count: 2004 }) }).click();
  await expect(page.getByRole("link", { name: msg("shell-stat-open-aria", { count: 2004 }) })).toHaveAttribute("aria-current", "page");
  expect((await read())[0].n).toBe(chosen[2].n);
});

test("a running matching-model switch shows in the top bar and leads to Settings > AI", async ({ page }) => {
  await mockGet(page, "/api/status", (route) => route.fulfill({ json: { ...statusFixture, matching_switch: "converting" } }));
  await page.goto("/");
  const chip = page.getByRole("link", { name: msg("shell-model-switch-aria", { phase: "converting" }) });
  await expect(chip).toBeVisible();
  await expect(chip).toContainText(msg("shell-model-switch", { phase: "converting" }));
  // The bar's ink, as every other chip wears it.
  const ink = await chip.locator(".l").evaluate((el) => getComputedStyle(el).color);
  expect(ink).not.toBe("rgb(0, 0, 0)");
  await chip.click();
  await expect(page).toHaveURL(/\/settings\/intelligence$/);
});
