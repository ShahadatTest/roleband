/* The Companies register: the large-set-selection pattern under
   its own tab. Most of these assert that ACTING does not move anything — the
   register's whole claim is that you can track a company without losing your
   place, so stability under toggle is the contract, not a nicety. */

import { expect, mockGet, test } from "./fixtures";
import { companyDiscovery, companyOpenCounts, installSettingsRoutes } from "./settingsHarness";
import { msg } from "../../src/test/msg";
import type { SyncTarget } from "../../src/api";

test.beforeEach(async ({ page }) => {
  await installSettingsRoutes(page);
});

test("first scan status does not turn a company's age into a failed scan duration", async ({ page }) => {
  const target: SyncTarget = {
    slug: "google", display: "Google", adapter: "greenhouse", automatic: true,
    last_sync_at: null, last_full_scan_at: null, age_hours: null, stale: true,
    last_outcome: null, retryable: false,
    coverage: {
      cause: "unknown", held_open: 0, days_since_full_scan: 81.4, rings: true,
      title: "Waiting to scan Google", body: "No scan has reached its careers page.",
      say: {
        title: { k: "notif-coverage-waiting-title", p: { company: "Google" } },
        body: [{ k: "notif-coverage-unknown", p: {} }],
      },
    },
  };
  await mockGet(page, "/api/sync/targets", (route) => route.fulfill({
    json: { companies: [target], freshness_max_hours: 26 },
  }));
  await page.goto("/settings/companies");
  const faang = page.getByRole("region", { name: "FAANG", exact: true });
  const google = faang.getByRole("checkbox", { name: "Google", exact: true });
  await expect(google).toHaveAccessibleDescription(new RegExp(
    `^${msg("companies-company-register-rows-following-not-scanned-yet")}`,
  ));
  await expect(faang).not.toContainText("81d");

  target.last_sync_at = new Date().toISOString();
  target.last_outcome = "failed";
  target.coverage = {
    ...target.coverage!, cause: "unreachable", title: "Couldn't scan Google",
    body: "Its careers page isn't answering.",
    say: {
      title: { k: "notif-coverage-scan-title", p: { company: "Google", days: 0 } },
      body: [{ k: "notif-coverage-unreachable", p: {} }],
    },
  };
  await page.reload();
  await expect(google).toHaveAccessibleDescription(new RegExp(
    `^${msg("companies-company-register-rows-coverage-problem", { cause: "unreachable" })}`,
  ));
  await expect(faang).not.toContainText("81d");
  await expect(faang.getByTitle("Couldn't scan Google. Its careers page isn't answering."))
    .toHaveClass(/is-warn/);
});

test("the Companies tab tracks a company on the spot, and can undo it", async ({ page }) => {
  const writes: unknown[] = [];
  const followed = new Set(companyDiscovery.companies.filter((c) => c.enabled).map((c) => c.slug));
  await page.route("/api/companies/selection", async (route) => {
    const write = route.request().postDataJSON();
    writes.push(write);
    for (const slug of write.follow) followed.add(slug);
    for (const slug of write.unfollow) followed.delete(slug);
    const enabled = [...followed];
    await route.fulfill({
      json: {
        ...companyDiscovery,
        companies: companyDiscovery.companies.map((company) => ({
          ...company,
          enabled: enabled.includes(company.slug),
          tracked: enabled.includes(company.slug) || company.tracked,
        })),
      },
    });
  });
  await page.goto("/settings/companies");

  await expect(page.getByRole("region", { name: "Companies", exact: true })).toBeVisible();
  // One register: tracking is a ROW state, so a company sits in its sector
  // whether you track it or not.
  const faang = page.getByRole("region", { name: "FAANG", exact: true });
  await expect(faang.getByRole("checkbox", { name: "Google" })).toBeChecked();
  const apple = faang.getByRole("checkbox", { name: "Apple" });
  await expect(apple).not.toBeChecked();

  await apple.click();

  await expect.poll(() => writes).toEqual([{ follow: ["apple"], unfollow: [], consents: [] }]);
  await expect(page.getByText("Following Apple.")).toBeVisible();
  await expect(faang.getByRole("checkbox", { name: "Apple" })).toBeChecked();
  // Nothing to save, so there is no save bar to sit on top of the board.
  await expect(page.getByRole("button", { name: /save/i })).toHaveCount(0);

  await page.getByRole("button", { name: "Undo" }).click();
  await expect.poll(() => writes.length).toBe(2);
  expect(writes[1]).toEqual({ follow: [], unfollow: ["apple"], consents: [] });
  await expect(faang.getByRole("checkbox", { name: "Apple" })).not.toBeChecked();
});

// Many catalog entries have no connector. They stay trackable (the intent is
// recorded) but must read as a different kind of row, not sit
// behind a disclosure the catalog has to be excavated from.
test("the Companies tab shows the whole catalog, marking what cannot be read", async ({ page }) => {
  await page.goto("/settings/companies");

  // No accordion, no "Show N more": Snowflake is simply on the page.
  const ai = page.getByRole("region", { name: "AI", exact: true });
  await expect(ai.getByRole("checkbox", { name: "Snowflake" })).toBeVisible();
  await expect(ai).toContainText("Planned");
  await expect(page.getByRole("button", { name: /Show \d+ more/ })).toHaveCount(0);
  await expect(page.getByRole("button", { name: /Toggle .* companies/ })).toHaveCount(0);

  // A sector no connector reaches is a different fact from one you merely have
  // not picked — the section states it rather than showing "0/1".
  await expect(page.getByRole("region", { name: "Robotics, autonomy & defense", exact: true }))
    .toContainText("none covered");
  await expect(page.getByRole("region", { name: "FAANG", exact: true }))
    .toContainText("2 covered");
  // ...and its select-all says why it cannot act, in the name it is read by.
  const robotics = page.getByRole("region", { name: "Robotics, autonomy & defense", exact: true });
  await expect(robotics.getByRole("button", { name: "Nothing to follow", exact: true })).toBeDisabled();
  await expect(robotics.getByRole("button", { name: /^Follow all/ })).toHaveCount(0);

  // The planned tail can be put away, and the sector says what it withheld.
  await page.getByRole("checkbox", { name: "Show planned" }).click();
  await expect(page.getByRole("checkbox", { name: "Snowflake" })).toHaveCount(0);
  await expect(page.getByRole("region", { name: "AI", exact: true })).toHaveCount(0);
  // Gone from the register, still on the map: the catalog never looks smaller
  // than it is.
  const sectors = page.getByRole("navigation", { name: "Sectors" });
  await expect(sectors.getByRole("button", { name: /AI/ })).toBeDisabled();
});

/* Filter memory, on a third surface: the same mechanism the
   Board's register and the Notifications lenses use (hooks/useFilterMemory).
   These two are standing CHOICES about what the register is for; the search
   box is not one, and deliberately does not come back with them. */
test("the register's two lenses are still set the way you left them", async ({ page }) => {
  await page.goto("/settings/companies");
  await expect(page.getByRole("checkbox", { name: "Snowflake" })).toBeVisible();

  await page.getByRole("checkbox", { name: "Show planned" }).click();
  await page.getByRole("checkbox", { name: "Following only" }).click();
  await expect(page.getByRole("checkbox", { name: "Snowflake" })).toHaveCount(0);
  await page.getByRole("searchbox", { name: "Search companies" }).fill("goog");

  // Away and back — a fresh load, and neither lens was ever in the address.
  await page.goto("/settings");
  await page.goto("/settings/companies");
  await expect(page.getByRole("checkbox", { name: "Following only" })).toBeChecked();
  await expect(page.getByRole("checkbox", { name: "Show planned" })).not.toBeChecked();
  await expect(page.getByRole("checkbox", { name: "Snowflake" })).toHaveCount(0);
  /* A QUERY is the context a count is measured in, not a standing narrowing of
     it — and a screen that reopened with words already typed into its search
     field reads as broken rather than as helpful. */
  await expect(page.getByRole("searchbox", { name: "Search companies" })).toHaveValue("");
});

test("a row's company name survives its secondary-sector chip", async ({ page }) => {
  // The register's whole promise is a scannable company column, and the name is
  // the row's single primary string. With a `flex: none` + `nowrap` annotation
  // beside it, the ONLY shrinkable item left is the name, which carries
  // `overflow: hidden`, so its automatic minimum size is zero: it collapses to
  // 0px while the "also <sector>" chip stays fully legible.
  //
  // Asserted as PIXELS, not as text presence: the node keeps its textContent
  // either way, so every DOM-level assertion passes while the screen shows
  // nothing. Only a rendered width can fail here.
  await page.setViewportSize({ width: 1280, height: 800 });
  await page.goto("/settings/companies");

  const gaming = page.getByRole("region", { name: "Gaming", exact: true });
  const row = gaming.locator(".ledger-row", { hasText: "NVIDIA" });
  const name = row.locator(".ledger-name > span").first();
  const chip = row.getByText("also Semiconductors & compute");

  await expect(chip).toBeVisible();

  const nameBox = await name.boundingBox();
  expect(nameBox).not.toBeNull();
  expect(nameBox!.width).toBeGreaterThan(0);

  // Not merely non-zero: the name is the LAST thing to truncate, so at this
  // width it renders in full while the chip is the one that gives up space.
  const [nameRendered, nameContent, chipRendered, chipContent] = await Promise.all([
    name.evaluate((el) => Math.round(el.getBoundingClientRect().width)),
    name.evaluate((el) => el.scrollWidth),
    chip.evaluate((el) => Math.round(el.getBoundingClientRect().width)),
    chip.evaluate((el) => el.scrollWidth),
  ]);
  expect(nameRendered).toBeGreaterThanOrEqual(nameContent);
  expect(chipRendered).toBeLessThan(chipContent);
});

// Content must vanish UNDER the sticky headers, not reappear above them.
// `position: sticky; top: 0` pins to the scroll container's CONTENT edge, so
// any top padding on the container is a strip the header cannot cover, and
// rows stay visible inside it as they scroll past. The ledger hands that
// padding to the page header instead, making the scrollport edge and the
// sticky edge the same line.
test("rows disappear under the sticky headers instead of showing above them", async ({ page }) => {
  // Short viewport so the fixture's small register can actually be scrolled
  // FAR ENOUGH to pin the header: the failure only exists once rows travel
  // under it. At a normal height this fixture cannot scroll that far at all.
  await page.setViewportSize({ width: 1280, height: 240 });
  await page.goto("/settings/companies");
  await expect(page.getByRole("region", { name: "FAANG", exact: true })).toBeVisible();

  const probe = await page.evaluate(() => {
    const scope = document.querySelector(".settings-design-system") as HTMLElement;
    const rect = (selector: string) => document.querySelector(selector)!.getBoundingClientRect();
    // Scroll as far as this fixture allows, so the header is genuinely pinned
    // and rows are travelling under it. Scroll to the maximum rather than a
    // computed offset — the fixture's register is small, and a fixed number
    // would silently under-scroll and prove nothing.
    scope.scrollTop = scope.scrollHeight;
    const port = scope.getBoundingClientRect();
    // The frozen block is three tiers deep now — toolbar, column header, then
    // the sector heads — and its TOP EDGE is the toolbar, not the column
    // header. Rows must disappear under the whole block, so the band that has
    // to stay clear runs from the scrollport edge to the top of the toolbar,
    // and the two tiers must be flush: any seam between them is a strip of
    // rows showing through the middle of a frozen header.
    const toolbar = rect(".ledger-toolbar");
    const head = rect(".ledger-colhead");
    // Any row pixel rendered between the top of the scrollport and the top of
    // the frozen block is a row that escaped. Measure PIXELS IN THAT BAND,
    // not "row rect extends above the block": a row straddling the scrollport
    // edge sits BEHIND the pinned opaque band, which is the covered state
    // this test exists to require, and a rect comparison with ±1px tolerances
    // counts it whenever max-scroll leaves a row on the edge. The real failure
    // (container padding pushing the sticky edge down) opens a genuine band
    // (gap > 0) and still fails here by name.
    const escaped = [...document.querySelectorAll(".ledger-sector .ledger-row")].filter((r) => {
      const b = r.getBoundingClientRect();
      const bandPixels = Math.min(b.bottom, toolbar.top) - Math.max(b.top, port.top);
      return bandPixels > 1;
    }).length;
    return {
      gap: Math.round(toolbar.top - port.top),
      seam: Math.round(head.top - toolbar.bottom),
      escaped,
      scrolled: Math.round(scope.scrollTop),
    };
  });

  // Guard the guard: if nothing scrolled, the assertions below prove nothing.
  expect(probe.scrolled).toBeGreaterThan(0);
  expect(probe.gap).toBe(0);
  expect(probe.seam).toBe(0);
  expect(probe.escaped).toBe(0);
});

// The page header — the "Settings" h1 and the Companies/Intelligence/
// Integrations/Schedule tab bar — is navigation you have finished using by the
// time you are reading rows, so it scrolls away. The toolbar is not: search and
// the two switches are how a long register is USED, and losing them a screen
// down means scrolling to the top to narrow, then back down to read the result.
test("scrolling the register keeps the search line and drops only the page header", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1280, height: 400 });
  await page.goto("/settings/companies");
  await expect(page.getByRole("region", { name: "FAANG", exact: true })).toBeVisible();

  const search = page.getByRole("searchbox", { name: "Search companies" });
  await expect(search).toBeVisible();

  const geometry = await page.evaluate(() => {
    const scope = document.querySelector(".settings-design-system") as HTMLElement;
    scope.scrollTop = scope.scrollHeight;
    const port = scope.getBoundingClientRect();
    const box = (selector: string) => {
      const el = document.querySelector(selector);
      if (!el) return null;
      const b = el.getBoundingClientRect();
      return { top: Math.round(b.top - port.top), bottom: Math.round(b.bottom - port.top) };
    };
    return {
      port: Math.round(port.height),
      scrolled: Math.round(scope.scrollTop),
      h1: box(".page-hero h1"),
      tabbar: box(".settings-tabbar"),
      search: box(".ledger-search input"),
      addButton: box(".ledger-toolbar .ui-btn-strong"),
    };
  });

  expect(geometry.scrolled).toBeGreaterThan(0);
  // Gone: both are entirely above the scrollport.
  expect(geometry.h1!.bottom).toBeLessThanOrEqual(0);
  expect(geometry.tabbar!.bottom).toBeLessThanOrEqual(0);
  // Held: the whole line, not just the input; the counts and the switches
  // come with it.
  expect(geometry.search!.top).toBeGreaterThanOrEqual(0);
  expect(geometry.search!.bottom).toBeLessThan(geometry.port);
  expect(geometry.addButton!.top).toBeGreaterThanOrEqual(0);
  expect(geometry.addButton!.bottom).toBeLessThan(geometry.port);

  // Held means USABLE from where you are, not merely painted: narrow the
  // register from the bottom of it without scrolling back up.
  await search.fill("Apple");
  await expect(page.getByRole("region", { name: "FAANG", exact: true })).toBeVisible();
  await expect(page.getByRole("checkbox", { name: "Google" })).toHaveCount(0);
  await expect(page.getByRole("checkbox", { name: "Apple" })).toBeVisible();
});

// WCAG 2.5.8 Target Size (Minimum): 24x24 CSS px. Row actions sit too close
// together for the spacing exception, so each must clear 24px itself. The
// switch keeps its 28x16 LOOK: the label wrapping it is the target, so a 34px
// row is not coarsened.
test("every control in the register meets the 24px minimum target", async ({ page }) => {
  await page.goto("/settings/companies");
  await expect(page.getByRole("region", { name: "FAANG", exact: true })).toBeVisible();

  const undersized = await page.evaluate(() => {
    // Measure the TARGET, not the painted control. A 28x16 switch is the right
    // size for a 34px row; what has to clear 24px is the area that responds to
    // a click, which for the switch is the label wrapping it. Growing the
    // control itself to hit the number turns the track into an ellipse.
    const selectors = [
      // Both switch shapes: the bare register-row target and the labelled
      // toolbar row, one class since ui/Switch.
      ".ui-switch",
      ".ledger-actions .ui-btn",
      ".ledger-sector-act",
      ".ledger-toolbar .ui-btn",
      ".ledger-index button",
      ".ledger-attention-act",
    ];
    return [...document.querySelectorAll(selectors.join(","))]
      .map((el) => {
        const b = el.getBoundingClientRect();
        return { what: el.className.toString().split(" ")[0], w: Math.round(b.width), h: Math.round(b.height) };
      })
      .filter((t) => t.w > 0 && (t.w < 24 || t.h < 24));
  });

  expect(undersized).toEqual([]);

  // The switch must read as a PILL, and the target must come from the wrapper
  // rather than from inflating the control. Growing the input vertically with
  // a transparent border and `background-clip: padding-box` paints the track
  // on a 28x24 area, where `border-radius: 999px` clamps to half-width by
  // half-height: a literal ellipse.
  const shape = await page.evaluate(() => {
    const sw = document.querySelector(".ledger-row .ui-switch-track") as HTMLElement;
    const cs = getComputedStyle(sw);
    const b = sw.getBoundingClientRect();
    return {
      w: Math.round(b.width),
      h: Math.round(b.height),
      borders: [cs.borderTopWidth, cs.borderRightWidth, cs.borderBottomWidth, cs.borderLeftWidth],
      clip: cs.backgroundClip,
      radius: Math.min(parseFloat(cs.borderTopLeftRadius), Math.min(b.width, b.height) / 2),
    };
  });
  expect(shape.w).toBeGreaterThan(shape.h);
  expect(shape.radius).toBe(shape.h / 2);
  // No inflating the control to reach the target number.
  expect(shape.borders).toEqual(["0px", "0px", "0px", "0px"]);
  expect(shape.clip).toBe("border-box");
});

// WCAG 1.4.10 Reflow: usable at a 320px viewport without scrolling sideways.
// A single-line row cannot: its fixed tracks alone nearly fill the width, so
// the name column collapses, every name truncates to a letter and the register
// scrolls sideways. Below 520px the row becomes two lines.
test("the register reflows at 320px instead of scrolling sideways", async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 800 });
  await page.goto("/settings/companies");
  await expect(page.getByRole("region", { name: "FAANG", exact: true })).toBeVisible();

  const reflow = await page.evaluate(() => {
    const scope = document.querySelector(".settings-design-system") as HTMLElement;
    const inAScroller = (el: Element) => {
      let n: Element | null = el;
      while (n && n !== scope) {
        const x = getComputedStyle(n).overflowX;
        if (x === "auto" || x === "scroll") return true;
        n = n.parentElement;
      }
      return false;
    };
    const right = scope.getBoundingClientRect().right;
    const names = [...document.querySelectorAll(".ledger-name > span:first-child")];
    return {
      scopeOverflows: scope.scrollWidth > scope.clientWidth,
      pageOverflows: document.documentElement.scrollWidth > document.documentElement.clientWidth,
      // Anything sticking out that is NOT inside a deliberate scroller.
      escapees: [...scope.querySelectorAll("*")].filter((el) => {
        const b = el.getBoundingClientRect();
        return b.width > 0 && b.right > right + 1 && !inAScroller(el);
      }).length,
      truncated: names.filter((n) => n.scrollWidth > n.clientWidth + 1).length,
      names: names.length,
    };
  });

  expect(reflow.pageOverflows).toBe(false);
  expect(reflow.scopeOverflows).toBe(false);
  expect(reflow.escapees).toBe(0);
  // Names WRAP at this width rather than ellipsing — a truncated company name
  // is content loss, which is the thing reflow exists to prevent.
  expect(reflow.names).toBeGreaterThan(0);
  expect(reflow.truncated).toBe(0);
});

// Toggling is not a request to rearrange the page. Ranking tracked-first
// straight off live selection would re-sort the sector the instant a switch
// flips, teleporting the company you just touched to the top, and a
// confirmation banner rendered in flow above the register would push
// everything down on top of that.
test("toggling a company leaves the list order and the page position alone", async ({ page }) => {
  const followed = new Set(companyDiscovery.companies.filter((c) => c.enabled).map((c) => c.slug));
  await page.route("/api/companies/selection", async (route) => {
    const write = route.request().postDataJSON();
    for (const slug of write.follow) followed.add(slug);
    for (const slug of write.unfollow) followed.delete(slug);
    const enabled = [...followed];
    await route.fulfill({
      json: {
        ...companyDiscovery,
        companies: companyDiscovery.companies.map((company) => ({
          ...company,
          enabled: enabled.includes(company.slug),
          tracked: enabled.includes(company.slug) || company.tracked,
        })),
      },
    });
  });
  await page.goto("/settings/companies");

  // A sector of untracked rows: tracking one of the LAST ones is what a
  // tracked-first sort would fling to the top.
  const cloud = page.getByRole("region", { name: "Cloud, data & devtools", exact: true });
  await expect(cloud).toBeVisible();

  const snapshot = () =>
    page.evaluate(() => {
      const scope = document.querySelector(".settings-design-system") as HTMLElement;
      const sec = [...document.querySelectorAll(".ledger-sector")].find(
        (s) => s.getAttribute("aria-label") === "Cloud, data & devtools",
      )!;
      const target = [...sec.querySelectorAll(".ledger-row")].find((r) =>
        r.querySelector(".ledger-name span")?.textContent === "Vercel",
      )!;
      return {
        order: [...sec.querySelectorAll(".ledger-row")].map(
          (r) => r.querySelector(".ledger-name span")?.textContent ?? "",
        ),
        rowY: Math.round(target.getBoundingClientRect().top),
        registerY: Math.round(document.querySelector(".ledger-register")!.getBoundingClientRect().top),
        scrollTop: Math.round(scope.scrollTop),
      };
    });

  // Bring the target into view BEFORE the baseline: Playwright scrolls an
  // element into view to click it, and that scroll would otherwise land
  // between the two snapshots and be mistaken for the bug.
  // The row, not its checkbox: an off-screen row skips layout (content-visibility),
  // and WebKit does not scroll to a control inside one.
  const vercel = cloud.getByRole("checkbox", { name: "Vercel" });
  await cloud.locator(".ledger-row").filter({ has: page.getByRole("checkbox", { name: "Vercel" }) }).scrollIntoViewIfNeeded();
  await expect(vercel).toBeInViewport();

  const before = await snapshot();
  expect(before.order).toContain("Vercel");
  // It must not already be first, or the assertion proves nothing.
  expect(before.order.indexOf("Vercel")).toBeGreaterThan(0);

  await vercel.click();
  await expect(vercel).toBeChecked();
  await expect(page.getByText("Following Vercel.")).toBeVisible();

  const after = await snapshot();
  expect(after.order).toEqual(before.order);
  expect(after.rowY).toBe(before.rowY);
  expect(after.registerY).toBe(before.registerY);
  expect(after.scrollTop).toBe(before.scrollTop);
});

// The confirmation is an overlay, not a block in the document flow.
test("the tracking confirmation floats instead of displacing the register", async ({ page }) => {
  const followed = new Set(companyDiscovery.companies.filter((c) => c.enabled).map((c) => c.slug));
  await page.route("/api/companies/selection", async (route) => {
    const write = route.request().postDataJSON();
    for (const slug of write.follow) followed.add(slug);
    for (const slug of write.unfollow) followed.delete(slug);
    const enabled = [...followed];
    await route.fulfill({
      json: {
        ...companyDiscovery,
        companies: companyDiscovery.companies.map((c) => ({
          ...c,
          enabled: enabled.includes(c.slug),
          tracked: enabled.includes(c.slug) || c.tracked,
        })),
      },
    });
  });
  await page.goto("/settings/companies");

  await page.getByRole("region", { name: "FAANG", exact: true })
    .getByRole("checkbox", { name: "Apple" })
    .click();

  const toast = page.getByText("Following Apple.");
  await expect(toast).toBeVisible();
  // Undo has to remain reachable: the layer ignores pointer events, the toast
  // takes them back.
  await expect(page.getByRole("button", { name: "Undo" })).toBeVisible();

  const layer = await page.evaluate(() => {
    const el = document.querySelector(".ui-toast-host") as HTMLElement;
    return { position: getComputedStyle(el).position, pointerEvents: getComputedStyle(el).pointerEvents };
  });
  expect(layer.position).toBe("fixed");
  expect(layer.pointerEvents).toBe("none");

  // Floating is only useful if the action stays reachable. On phone widths the
  // app's nav becomes a fixed bottom bar that ranks above this layer, and the
  // toast has to clear it — a click here fails outright if it does not.
  await page.getByRole("button", { name: "Undo" }).click();
  await expect(
    page.getByRole("region", { name: "FAANG", exact: true }).getByRole("checkbox", { name: "Apple" }),
  ).not.toBeChecked();
});

// Selection must not change the METRICS of a row. Expressing "tracked" as
// font-weight would widen the company name and shove everything after it (the
// "also <sector>" tag) along by the same amount, so every toggle would
// twitch. Selection is ink; weight is constant in both states.
test("toggling a company does not move anything in its row", async ({ page }) => {
  const followed = new Set(companyDiscovery.companies.filter((c) => c.enabled).map((c) => c.slug));
  await page.route("/api/companies/selection", async (route) => {
    const write = route.request().postDataJSON();
    for (const slug of write.follow) followed.add(slug);
    for (const slug of write.unfollow) followed.delete(slug);
    const enabled = [...followed];
    await route.fulfill({
      json: {
        ...companyDiscovery,
        companies: companyDiscovery.companies.map((company) => ({
          ...company,
          enabled: enabled.includes(company.slug),
          tracked: enabled.includes(company.slug) || company.tracked,
        })),
      },
    });
  });
  await page.goto("/settings/companies");

  const faang = page.getByRole("region", { name: "FAANG", exact: true });
  const apple = faang.getByRole("checkbox", { name: "Apple" });
  await expect(apple).not.toBeChecked();

  const name = faang.locator(".ledger-name > span").filter({ hasText: "Apple" }).first();
  const measure = () =>
    name.evaluate((el) => ({
      // Intrinsic text width: this is what a weight change moves.
      width: el.scrollWidth,
      weight: getComputedStyle(el).fontWeight,
    }));

  const before = await measure();
  await apple.click();
  await expect(apple).toBeChecked();
  const after = await measure();

  expect(after.weight).toBe(before.weight);
  expect(after.width).toBe(before.width);
});

// The same rule on the sector index: marking a sector current must not bold
// it and shift its own tracked/total count.
test("making a sector current does not move its count", async ({ page }) => {
  await page.goto("/settings/companies");
  const sectors = page.getByRole("navigation", { name: "Sectors" });
  const robotics = sectors.getByRole("button", { name: /Robotics/ });
  const count = robotics.locator("b");

  // Within its own row: on a phone the index is a strip that scrolls to the
  // current sector, so the page position moves by design; the failure is a
  // bold label pushing the count along its row.
  const xOf = () => count.evaluate((el) =>
    Math.round(el.getBoundingClientRect().x - el.closest("button")!.getBoundingClientRect().x));
  const before = await xOf();
  await robotics.click();
  await expect(robotics).toHaveAttribute("aria-current", "true");

  expect(await xOf()).toBe(before);
});

// A heading has to point DOWNWARD at its own rows. Flush against the previous
// sector's last row it reads as part of that block instead.
test("a sector heading is separated from the block above it", async ({ page }) => {
  await page.goto("/settings/companies");
  await expect(page.getByRole("region", { name: "FAANG", exact: true })).toBeVisible();

  const geometry = await page.evaluate(() => {
    const sections = [...document.querySelectorAll(".ledger-sector")];
    const next = sections[1];
    const previous = next.previousElementSibling as HTMLElement;
    const previousRows = previous.querySelectorAll(".ledger-row");
    const lastRow = previousRows[previousRows.length - 1].getBoundingClientRect();
    const head = next.querySelector(".ledger-sector-head")!.getBoundingClientRect();
    const ownFirstRow = next.querySelector(".ledger-row")!.getBoundingClientRect();
    return {
      gapAbove: head.top - lastRow.bottom,
      gapBelow: ownFirstRow.top - head.bottom,
    };
  });

  // Separated from the block above...
  expect(geometry.gapAbove).toBeGreaterThanOrEqual(16);
  // ...and still attached to the rows it introduces. This is the assertion that
  // actually encodes "which section does this heading belong to".
  expect(geometry.gapBelow).toBeLessThan(geometry.gapAbove);
});

test("the Companies tab is usable while open-role counts are still loading", async ({ page }) => {
  // The counts aggregate scans `jobs`. Bundled into the roster payload it
  // would hold the whole screen blank behind it, so it is its own request
  // and only a tracked card's count waits for it.
  let release: (() => void) | undefined;
  const held = new Promise<void>((resolve) => {
    release = resolve;
  });
  await page.route("/api/companies/open-counts", async (route) => {
    await held;
    await route.fulfill({ json: companyOpenCounts });
  });

  await page.goto("/settings/companies");

  // Register, sections, and the tracking controls are live before any count.
  await expect(page.getByRole("region", { name: "Companies", exact: true })).toBeVisible();
  await expect(page.getByRole("region", { name: "FAANG", exact: true })).toBeVisible();
  await expect(page.getByRole("checkbox", { name: "Apple" })).toBeEnabled();
  await expect(page.getByText("Loading companies…")).toHaveCount(0);
  // Only tracked rows carry a count, so only Google says it is busy.
  await expect(page.getByRole("status", { name: "Open roles loading" })).toHaveCount(1);

  release?.();

  // The sector summary also totals "12 open", so target the row's own cell:
  // the point of this test is that the ROW filled in, not the header.
  await expect(
    page.getByRole("region", { name: "FAANG", exact: true }).locator(".ledger-count"),
  ).toHaveText("12 open");
  await expect(page.getByRole("status", { name: "Open roles loading" })).toHaveCount(0);
});

// A frozen band has one job beyond staying put: HIDING what passes behind it.
// The column header shares the `.ledger-row` class to borrow the grid, so
// `.ledger-row:hover` (0-2-0) beats `.ledger-colhead` (0-1-0), and `background`
// is a shorthand: a hover rule written with it swaps the header's opaque
// canvas + ambient ground for a translucent wash and resets `background-image`
// to `none`, and rows travelling underneath show straight through.
//
// Asserted for every band: the shared class is the trap, and any `.ledger-row`
// state rule written with the shorthand opens it.
test("the frozen bands stay opaque under the pointer", async ({ page, isMobile }) => {
  test.skip(isMobile, "the toolbar and column header do not freeze below 760px");
  await page.setViewportSize({ width: 1400, height: 700 });
  await page.goto("/settings/companies");
  await expect(page.getByRole("region", { name: "FAANG", exact: true })).toBeVisible();

  // Scroll far enough that rows are genuinely travelling behind the bands —
  // an opaque header over nothing proves nothing.
  await page.evaluate(() => {
    const scope = document.querySelector(".settings-design-system") as HTMLElement;
    scope.scrollTop = scope.scrollHeight;
  });

  for (const selector of [".ledger-toolbar", ".ledger-colhead", ".ledger-sector-head"]) {
    const band = page.locator(selector).first();
    await band.hover({ position: { x: 40, y: 8 }, force: true });
    const paint = await band.evaluate((el) => {
      const style = getComputedStyle(el);
      return { color: style.backgroundColor, image: style.backgroundImage, hovered: el.matches(":hover") };
    });
    // Guard the guard: if the pointer never landed, opacity proves nothing.
    expect(paint.hovered, `${selector} was not hovered`).toBe(true);
    // A ground that is a wash rather than a cover: rgba() with alpha < 1. Take
    // the alpha only from a FOUR-component colour — the blue channel of an
    // `rgb(20, 20, 11)` is not an alpha, and reading it as one fails this
    // assertion on a perfectly opaque band.
    const parts = paint.color.match(/[\d.]+/g) ?? [];
    const alpha = parts.length === 4 ? Number(parts[3]) : 1;
    expect(alpha, `${selector} background-color is translucent while hovered`).toBe(1);
    expect(paint.image, `${selector} lost its ambient layer while hovered`).not.toBe("none");
  }
});

// SECTORS and COMPANY/CONNECTOR/OPEN are two columns' headers on ONE line. The
// register's 32px band centres its labels; an index label left as a bare line
// box at the top of its column sits above it, and the two columns visibly
// begin on different lines.
//
// Pixels, not classes: this is pure layout, so jsdom cannot host it and no DOM
// assertion can catch it.
test("the register's two columns start on the same line", async ({ page, isMobile }) => {
  test.skip(isMobile, "the index stacks above the register below 980px");
  await page.setViewportSize({ width: 1400, height: 900 });
  await page.goto("/settings/companies");
  await expect(page.getByRole("region", { name: "FAANG", exact: true })).toBeVisible();

  const probe = await page.evaluate(() => {
    // Measure the TEXT, not the box: two boxes can share an edge while their
    // words sit on different lines.
    const midOf = (el: Element) => {
      const range = document.createRange();
      range.selectNodeContents(el);
      const box = range.getBoundingClientRect();
      return (box.top + box.bottom) / 2;
    };
    const top = (selector: string) =>
      document.querySelector(selector)!.getBoundingClientRect().top;
    const company = [...document.querySelectorAll(".ledger-colhead > span")].find(
      (el) => el.textContent?.trim() === "Company",
    )!;
    return {
      headerDelta: midOf(company) - midOf(document.querySelector(".ledger-index-label")!),
      firstRowDelta: top(".ledger-sector-head") - top(".ledger-index button"),
    };
  });

  // Sub-pixel, because the register's header hairline eats into its own band:
  // centring the index label over the full 32px instead of the 31px left would
  // land half a pixel out, which is the same class of error as the 2px sticky
  // overlap the tier tokens exist to prevent.
  expect(Math.abs(probe.headerDelta)).toBeLessThan(0.5);
  expect(Math.abs(probe.firstRowDelta)).toBeLessThan(0.5);
});

// No summary rail: it would restate numbers the board already shows and take
// width the register spends on content. The sector index navigates instead:
// it sits BESIDE the register and scrolls to a section rather than opening
// one.
test("the Companies tab navigates by a sector index, not a summary rail", async ({ page, isMobile }) => {
  test.skip(isMobile, "the index stacks above the register below 980px");
  await page.setViewportSize({ width: 1400, height: 900 });
  await page.goto("/settings/companies");

  await expect(page.getByRole("complementary", { name: "Companies summary" })).toHaveCount(0);
  await expect(page.getByRole("complementary", { name: "Your radar" })).toHaveCount(0);

  const sectors = page.getByRole("navigation", { name: "Sectors" });
  const register = page.getByRole("region", { name: "FAANG", exact: true });
  await expect(sectors).toBeVisible();

  // Beside the register, not above it, and narrow.
  const indexBox = await sectors.boundingBox();
  const registerBox = await register.boundingBox();
  expect((indexBox?.x ?? 0) + (indexBox?.width ?? 0)).toBeLessThanOrEqual((registerBox?.x ?? 0) + 1);
  expect(indexBox?.width ?? 999).toBeLessThan(240);

  // A jump link scrolls to its section rather than filtering the board down to
  // it — every other sector is still there afterwards.
  await sectors.getByRole("button", { name: /Robotics/ }).click();
  await expect(sectors.getByRole("button", { name: /Robotics/ })).toHaveAttribute(
    "aria-current",
    "true",
  );
  await expect(page.getByRole("region", { name: "FAANG", exact: true })).toBeVisible();
  await expect(page.getByRole("checkbox", { name: "Snowflake" })).toBeVisible();
});

/* Every other company RoleBand can scan, too many to list. A search asks the server, the hits sit under "Other companies", and
   following one is the same roster write as any row. */
test("a search reaches a company in no sector, and following it is one write", async ({ page }) => {
  const asked: string[] = [];
  await page.route("/api/companies/directory?**", async (route) => {
    asked.push(new URL(route.request().url()).searchParams.get("q") ?? "");
    await route.fulfill({
      json: {
        size: 10214,
        match_count: 1,
        matches: [{ slug: "spacex", display: "SpaceX", named_by: "board", tracked: false, enabled: false }],
      },
    });
  });
  const writes: { follow: string[]; unfollow: string[] }[] = [];
  await page.route("/api/companies/selection", async (route) => {
    const body = route.request().postDataJSON();
    writes.push(body);
    await route.fulfill({
      json: {
        ...companyDiscovery,
        companies: [
          ...companyDiscovery.companies,
          {
            slug: "spacex", display: "SpaceX", careers_url: null, sectors: [], aliases: [],
            connector_state: "active", parked_reason: null, selectable: true,
            tracked: true, enabled: true, visible: true, builtin: false, curated: false,
            directory: true, wall: null, consented: false, status: "active",
          },
        ],
      },
    });
  });
  await page.goto("/settings/companies");

  await page.getByRole("searchbox", { name: "Search companies" }).fill("space");
  const other = page.getByRole("region", { name: "Other companies", exact: true });
  const spacex = other.getByRole("checkbox", { name: "SpaceX" });
  await expect(spacex).not.toBeChecked();
  expect(asked).toEqual(["space"]);

  await spacex.click();
  await expect.poll(() => writes.length).toBe(1);
  expect(writes[0]).toEqual({ follow: ["spacex"], unfollow: [], consents: [] });
  await expect(page.getByText("Following SpaceX.")).toBeVisible();
  await expect(other.getByRole("checkbox", { name: "SpaceX" })).toBeChecked();
});

/* The whole set, followed as one thing: a card at the end of the
   list beside Add by link, one confirmation, then the scan's progress in the
   card. */
test("every other company is followed in one decision, and the scan shows its progress", async ({ page }) => {
  let status = { size: 10214, following: false, since: null as string | null, checked: 0, to_check: 10214, with_roles: 0, waiting_for_power: false };
  await page.route("/api/companies/directory/status", (route) => route.fulfill({ json: status }));
  const follows: unknown[] = [];
  await page.route("/api/companies/directory/follow", async (route) => {
    follows.push(route.request().postDataJSON());
    status = { ...status, following: true, since: "2026-09-24T12:00:00Z", checked: 3200, with_roles: 4 };
    await route.fulfill({ json: status });
  });
  await page.goto("/settings/companies");

  await expect(page.getByRole("region", { name: "Other companies", exact: true })).toHaveCount(0);
  const addMore = page.getByRole("region", { name: "Add more companies" });
  const other = addMore.getByRole("group", { name: "The wider market" });
  await expect(other.getByText("About 10,000 companies on the same job sites")).toBeVisible();
  await expect(addMore.getByRole("button", { name: "Add by link" })).toBeVisible();

  // The index leads there.
  await page.getByRole("navigation", { name: "Sectors" }).getByRole("button", { name: "Add more companies" }).click();
  await expect(addMore.getByRole("heading", { name: "Add more companies" })).toBeFocused();

  await other.getByRole("button", { name: "Find the ones hiring for you" }).click();
  const dialog = page.getByRole("dialog", { name: "Scan about 10,000 more companies?" });
  await expect(dialog.getByRole("button", { name: "Cancel" })).toBeFocused();
  await dialog.getByRole("button", { name: "Start scanning" }).click();

  await expect.poll(() => follows).toEqual([{ following: true }]);
  const bar = other.getByRole("progressbar", { name: "Companies scanned" });
  await expect(bar).toHaveAttribute("aria-valuenow", "3200");
  await expect(other).toContainText("3,200 scanned of about 10,000");
  await expect(other).toContainText("4 hiring for you so far");
  const stop = other.getByRole("button", { name: "Stop scanning the wider market" });
  await expect(stop).toBeVisible();

  // Both cards end on a real button, and the two share one line: same height,
  // same top. A link-styled Stop has no border and a text-height box.
  const add = addMore.getByRole("button", { name: "Add by link" });
  const [stopBox, addBox] = [await stop.boundingBox(), await add.boundingBox()];
  expect(stopBox && addBox).toBeTruthy();
  expect(Math.abs(stopBox!.height - addBox!.height)).toBeLessThanOrEqual(1);
  // Side by side (wide) they share a line; stacked (phone) each ends its own card.
  if ((page.viewportSize()?.width ?? 0) >= 900) {
    expect(Math.abs(stopBox!.y - addBox!.y)).toBeLessThanOrEqual(1);
  }
  const border = await stop.evaluate((el) => getComputedStyle(el).borderTopWidth);
  expect(parseFloat(border)).toBeGreaterThan(0);
  await expect(addMore).not.toContainText("RoleBand");
});

/* The volume bar answers to the register's own width, not the window's: the
   settings chrome and the sector index both take from the register, so the
   same window can leave it more or less room. */
test("the volume bar shows exactly while the register has room for it", async ({ page, isMobile }) => {
  test.skip(isMobile, "a phone width drops the bar under every rule");
  const row = page.locator(".ledger-row:has(.ledger-name)").first();
  await page.goto("/settings/companies");
  await expect(row).toBeVisible();
  const seen: boolean[] = [];
  for (const width of [1500, 1200, 1150, 1000]) {
    await page.setViewportSize({ width, height: 900 });
    const { register, bar } = await row.evaluate((el) => {
      const cell = el.querySelector(".ledger-bar-cell");
      return {
        register: el.closest(".ledger-register")!.getBoundingClientRect().width,
        bar: cell ? getComputedStyle(cell).display !== "none" : false,
      };
    });
    expect(bar, `register ${register}px at a ${width}px window`).toBe(register > 786);
    seen.push(bar);
  }
  // Both sides of the threshold were exercised.
  expect(seen).toContain(true);
  expect(seen).toContain(false);
});
