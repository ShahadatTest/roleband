/* The board as a page: one-scroll layout, the pinned column head, the pager in
   page flow, row focus and read state, the nav rail, and list-level failure.
   Nothing here filters, sorts or searches — those own their own files. */

import { expect, test } from "./fixtures";
import type { Page } from "@playwright/test";
import { jobFixture, jobListFixture, statusFixture } from "../../src/test/fixtures";
import { deepList, detail, installBoardRoutes, twoJobList } from "./boardHarness";

test.beforeEach(async ({ page }) => {
  await installBoardRoutes(page);
});

/** Scroll the PAGE (the one scroller) and report the docked chrome, in
 * scrollport coordinates. */
async function pageGeometry(page: Page, to: number) {
  return page.evaluate((scrollTo) => {
    const main = document.querySelector(".main") as HTMLElement;
    main.scrollTop = scrollTo;
    const mtop = main.getBoundingClientRect().top;
    const box = (selector: string) => {
      const el = document.querySelector(selector);
      if (!el) return null;
      const b = el.getBoundingClientRect();
      return { top: Math.round(b.top - mtop), bottom: Math.round(b.bottom - mtop) };
    };
    const headEl = document.querySelector(".list-head") as HTMLElement;
    // The narrow layout drops the column head entirely (rows become cards) and
    // the shared arm unfreezes the toolbar — nothing to assert there.
    const headRendered = getComputedStyle(headEl).display !== "none";
    const bar = box(".board-toolbar")!;
    const head = box(".list-head")!;
    // Only `.main` (plus, as an overflow-valve, the register) may scroll: any
    // other box with a live vertical scroll range is an inner scroll window.
    const innerScrollers = [...document.querySelectorAll(".board-main *")]
      .filter(
        (el) =>
          el.scrollHeight > el.clientHeight + 2 &&
          /(auto|scroll)/.test(getComputedStyle(el).overflowY) &&
          !(el as HTMLElement).classList.contains("rail-shell-rail"),
      )
      .map((el) => (el as HTMLElement).className);
    return {
      scrolled: Math.round(main.scrollTop),
      headRendered,
      hero: box(".page-hero")!,
      bar,
      head,
      rail: box(".rail-shell-rail"),
      // The docked band and the pinned head must meet FLUSH: both are opaque,
      // so a seam between them is the only place a row pixel could show.
      seamBarToHead: head.top - bar.bottom,
      innerScrollers,
      airAboveSearch: Math.round(
        document.querySelector(".board-search-box")!.getBoundingClientRect().top -
          document.querySelector(".board-toolbar")!.getBoundingClientRect().top,
      ),
    };
  }, to);
}

test("one page scroll: the hero leaves, and the page rests against the search bar", async ({
  page,
}) => {
  // The settings behavior, verbatim: scroll anywhere, the whole page moves;
  // the h1 slides away like content; the search toolbar docks at the top and
  // the column head and register pin under it. Nothing scrolls independently.
  await page.setViewportSize({ width: 1600, height: 800 });
  await page.route("/api/jobs?**", (route) =>
    route.fulfill({
      json: route.request().url().includes("location_group=silicon_valley")
        ? { ...jobListFixture, total: 1, items: [{ ...jobFixture, id: 9001, title: "Valley Group PM" }] }
        : deepList,
    })
  );
  await page.goto("/");
  await expect(page.locator(".job-row").first()).toBeVisible();

  const g = await pageGeometry(page, 600);
  expect(g.scrolled).toBeGreaterThan(0);
  // Gone: the hero is entirely above the scrollport, like any page content.
  expect(g.hero.bottom).toBeLessThanOrEqual(0);
  // Docked: the toolbar rests on the scrollport's own edge, and the head and
  // the register pin flush beneath it — both bands opaque, zero seam.
  expect(g.bar.top).toBe(0);
  expect(g.seamBarToHead).toBe(0);
  expect(g.rail).not.toBeNull();
  expect(g.rail!.top).toBe(g.head.top);
  // The settings air: space-2 between the band's edge and the search control,
  // from the SHARED .app-toolbar recipe — the consistency guarantee.
  expect(g.airAboveSearch).toBeGreaterThanOrEqual(8);
  expect(g.airAboveSearch).toBeLessThanOrEqual(12);
  // No inner scroll windows anywhere in the board.
  expect(g.innerScrollers).toEqual([]);

  // Docked means USABLE from where you are: narrow the board from the pinned
  // register with the page deep-scrolled, no scrolling back. A FACET: Open/
  // Closed are the list's own tabs, not the register's, and those
  // deliberately scroll away with the hero rather than freezing a second
  // band over the column head.
  const rail = page.getByRole("complementary", { name: "Filters" });
  // Two clicks from the pinned rail — open the group, choose the value — and
  // neither of them scrolls back up (groups rest closed).
  await rail.getByRole("button", { name: "Location", exact: true }).click();
  await rail.getByRole("checkbox", { name: "Silicon Valley" }).check();
  await expect(page.getByText("Valley Group PM")).toBeVisible();
});

test("the column head pins at the toolbar's measured height, at both register homes", async ({
  page,
}) => {
  // The offset is the docked band's real box height — the shared arithmetic
  // by default, corrected by measurement where the bar wraps — so the head
  // must land exactly on the toolbar's underside at any width: a stale number
  // either hides the columns behind the band or opens a seam of live rows.
  await page.route("/api/jobs?**", (route) => route.fulfill({ json: deepList }));

  for (const width of [1600, 1000]) {
    await page.setViewportSize({ width, height: 700 });
    await page.goto("/");
    await expect(page.locator(".job-row").first()).toBeVisible();

    const held = await pageGeometry(page, 600);
    expect(held.scrolled, `${width}px`).toBeGreaterThan(0);
    if (!held.headRendered) continue;

    expect(held.bar.top, `${width}px`).toBe(0);
    expect(held.seamBarToHead, `${width}px`).toBe(0);
    // The register is present in exactly one home.
    expect(held.rail !== null, `${width}px rail`).toBe(width >= 1360);
  }
});

test("rows slide under an opaque band, and the ledger carries no frame to break", async ({
  page,
}) => {
  // What makes sticky-over-the-list legal: the list has no floating
  // card — no Gaussian shadow for a rectangular band to relocate, no rounded
  // corner to saw off, no glass for rows to read through. The pinned head is
  // plain opaque canvas; rows are ledger rows on the page's own ground.
  await page.setViewportSize({ width: 1600, height: 700 });
  await page.route("/api/jobs?**", (route) => route.fulfill({ json: deepList }));
  await page.goto("/");
  await expect(page.locator(".job-row").first()).toBeVisible();

  const sampled = await page.evaluate(() => {
    const main = document.querySelector(".main") as HTMLElement;
    main.scrollTop = 600;
    const headEl = document.querySelector(".list-head") as HTMLElement;
    if (getComputedStyle(headEl).display === "none") return null;
    const head = headEl.getBoundingClientRect();
    // Sample across the pinned head's band. A pixel that hits a row rather
    // than the head is a leak through the band.
    const rowPixels: string[] = [];
    for (let dy = 1; dy < 10; dy += 2) {
      for (const fx of [0.05, 0.3, 0.6, 0.95]) {
        const x = head.left + head.width * fx;
        const el = document.elementFromPoint(Math.round(x) + 0.5, Math.round(head.top + dy) + 0.5);
        const name = el ? String((el as HTMLElement).className ?? "") : "";
        if (/job-row|jr-|job-title|\bchip\b/.test(name)) rowPixels.push(`${fx},${dy}:${name}`);
      }
    }
    return { rowPixels, scrolled: Math.round(main.scrollTop) };
  });

  if (sampled === null) return;
  expect(sampled.scrolled).toBeGreaterThan(0);
  expect(sampled.rowPixels).toEqual([]);

  // Opaque band; frameless ledger. Alpha is read only from a FOUR-component
  // colour — the blue channel of `rgb(10, 10, 11)` is not an alpha, and
  // reading it as one passes an opaque band for the wrong reason.
  const paint = await page.evaluate(() => {
    const head = getComputedStyle(document.querySelector(".list-head")!);
    const list = getComputedStyle(document.querySelector(".job-list")!);
    const alpha = (colour: string) => {
      const parts = colour.match(/[\d.]+/g) ?? [];
      return parts.length === 4 ? Number(parts[3]) : 1;
    };
    return {
      bandAlpha: alpha(head.backgroundColor),
      bandBackdrop: head.backdropFilter,
      listShadow: list.boxShadow,
      listRadius: Math.round(parseFloat(list.borderTopLeftRadius)),
      listFill: list.backgroundColor,
      // The list is page flow, not a scrollport: nothing clips or scrolls it.
      listOverflow: list.overflowY,
    };
  });
  expect(paint.bandAlpha).toBe(1);
  expect(paint.bandBackdrop).toBe("none");
  expect(paint.listShadow).toBe("none");
  expect(paint.listRadius).toBe(0);
  expect(paint.listFill).toBe("rgba(0, 0, 0, 0)");
  expect(paint.listOverflow).toBe("visible");
});

test("a full page of roles lives in the page flow, pager included", async ({ page }) => {
  // No inner scroll window rations the rows: the request asks for the page
  // size (20), every row is laid out in full, and the pager is page content
  // reached by the same one scroll as everything else.
  const jobRequests: string[] = [];
  await page.setViewportSize({ width: 1600, height: 800 });
  await page.route("/api/jobs?**", (route) => {
    jobRequests.push(route.request().url());
    return route.fulfill({
      json: {
        ...jobListFixture,
        total: 216,
        items: Array.from({ length: 20 }, (_, i) => ({
          ...jobFixture,
          id: 2000 + i,
          title: `Role ${i} Group Product Manager`,
        })),
      },
    });
  });
  await page.goto("/");
  await expect(page.locator(".job-row").first()).toBeVisible();

  expect(new URL(jobRequests[0]).searchParams.get("limit")).toBe("20");
  await expect(page.locator(".job-row")).toHaveCount(20);

  const flow = await page.evaluate(() => {
    const main = document.querySelector(".main") as HTMLElement;
    main.scrollTop = main.scrollHeight;
    const mainBox = main.getBoundingClientRect();
    const pager = document.querySelector(".pager")!.getBoundingClientRect();
    const rows = [...document.querySelectorAll(".job-row")];
    const clipped = rows.filter((r) => {
      const el = r as HTMLElement;
      return el.scrollHeight > el.clientHeight + 2;
    }).length;
    const sticky = [...document.querySelectorAll(".board-main *")]
      .filter((el) => getComputedStyle(el).position === "sticky")
      .map((el) => (el as HTMLElement).className.split(" ")[0])
      .sort();
    return {
      pagerVisible: pager.top >= mainBox.top && pager.bottom <= mainBox.bottom + 1,
      pagerText: document.querySelector(".pager span")?.textContent,
      clipped,
      sticky,
      overflowsX: main.scrollWidth > main.clientWidth,
    };
  });
  // Scrolled to the end, the pager stands after row 20 like any page content.
  expect(flow.pagerVisible).toBe(true);
  expect(flow.pagerText).toContain("Page 1 of 11");
  expect(flow.clipped).toBe(0);
  // The full pinned set, and nothing else: the docked toolbar, the register,
  // the column head.
  expect(flow.sticky).toEqual(["board-toolbar", "list-head", "rail-shell-rail"]);
  expect(flow.overflowsX).toBe(false);
});

/* The row is a two-line grid, and the city gets the room it needs.
 * A one-line row is too narrow for the city at the widths this screen is used
 * at, so it truncates ("San Francisc…") while the age column has room to
 * spare; the numeral belongs on the title's line, not centred in the seam
 * between the title and its facts; and the row verbs stay hidden at rest. These
 * are statements about the rendered page, so a sheet-level gate cannot make
 * them; the row grammar gate holds the declarations, this holds the pixels. */
test("the row is two aligned lines, the city is not truncated, and the verbs rest hidden", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name === "mobile", "Rows are cards on touch layouts, and every verb shows at rest there.");
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.route("/api/jobs?**", (route) =>
    route.fulfill({
      json: {
        ...jobListFixture,
        total: 3,
        items: [
          {
            ...jobFixture,
            id: 3001,
            title: "Manager Applied AI Architecture, Financial Services",
            locations: ["New York City, NY; San Francisco, CA | New York City, NY"],
            location_groups: ["new_york"],
            is_favorite: true,
            days_open: 30,
          },
          { ...jobFixture, id: 3002, locations: ["Seattle, Washington, USA"], location_groups: ["pacific_northwest"] },
          { ...jobFixture, id: 3003, locations: ["London, UK"], location_groups: ["united_kingdom"] },
        ],
      },
    }),
  );
  await page.goto("/");
  await expect(page.locator(".job-row")).toHaveCount(3);

  const rows = await page.locator(".job-row").evaluateAll((els) =>
    els.map((row) => {
      const box = (sel: string) => {
        const el = row.querySelector(sel) as HTMLElement | null;
        if (!el) return null;
        const b = el.getBoundingClientRect();
        return { top: Math.round(b.top), bottom: Math.round(b.bottom), truncated: el.scrollWidth > el.clientWidth };
      };
      const actions = [...row.querySelectorAll(".jr-actions .ui-btn")].map((b) => ({
        pressed: b.getAttribute("aria-pressed") === "true",
        opacity: Number(getComputedStyle(b).opacity),
      }));
      return {
        city: (row.querySelector(".job-location") as HTMLElement).innerText,
        title: box(".job-title")!,
        loc: box(".job-location")!,
        comp: box(".comp")!,
        // A fact, not the line's box: the line carries a 3px pad/margin pair
        // for the company chip's focus ring, so its box sits 3px proud.
        meta: box(".job-meta .job-band")!,
        group: box(".job-loc-group")!,
        age: box(".jr-age")!,
        // Minus the hairline: every row but the first carries a 1px border-top.
        height: Math.round(row.getBoundingClientRect().height - parseFloat(getComputedStyle(row).borderTopWidth)),
        actions,
      };
    }),
  );

  // The multi-city posting shows one city and a count; nothing in any city
  // cell is cut off at this width.
  // (The screen-reader tail "more: …" is part of the cell's text but not of
  // what a sighted reader sees.)
  expect(rows[0].city).toMatch(/^New York City, NY \+1/);
  for (const row of rows) expect(row.loc.truncated, row.city).toBe(false);

  // Line one: title, city and numeral start on the same line. Line two: facts,
  // region and age. Every row the same height.
  for (const row of rows) {
    expect(Math.abs(row.loc.top - row.title.top)).toBeLessThanOrEqual(1);
    expect(Math.abs(row.comp.top - row.title.top)).toBeLessThanOrEqual(1);
    expect(Math.abs(row.group.top - row.meta.top)).toBeLessThanOrEqual(1);
    expect(Math.abs(row.age.top - row.meta.top)).toBeLessThanOrEqual(1);
    expect(row.age.top).toBeGreaterThanOrEqual(row.comp.bottom - 1);
  }
  expect(new Set(rows.map((r) => r.height)).size, `row heights ${rows.map((r) => r.height).join(", ")}`).toBe(1);
  expect(await page.locator(".list-head .col-age").count()).toBe(0);

  // At rest the verbs are invisible and the saved star is not.
  expect(rows[0].actions.map((a) => a.opacity)).toEqual([0, 0, 1]);
  expect(rows[0].actions[2].pressed).toBe(true);
  expect(rows[1].actions.map((a) => a.opacity)).toEqual([0, 0, 0]);
  // Under the pointer, and under focus, the row's verbs appear.
  await page.locator(".job-row").nth(1).hover();
  await expect(page.locator(".job-row").nth(1).locator(".jr-actions .ui-btn").first()).toHaveCSS("opacity", "1");
  await page.locator(".job-row").nth(2).locator(".jr-actions .ui-btn").first().focus();
  await expect(page.locator(".job-row").nth(2).locator(".jr-actions .ui-btn").last()).toHaveCSS("opacity", "1");
});

/* The standing-posting sign sits with the row's other state chips
 * on the facts line. At the narrowest desktop width, beside a stacked-postings
 * chip and a twin chip, it must keep the row two lines and every row one
 * height, and must not cut the facts or itself. */
test("a possible standing posting wears its sign on the facts line without growing the row", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name === "mobile", "Rows are cards on touch layouts.");
  const standing = { level: "possible", met: ["long_open", "relisted"], criteria_total: 3, listings: 3 };
  for (const width of [1280, 1440]) {
    await page.setViewportSize({ width, height: 900 });
    await page.route("/api/jobs?**", (route) =>
      route.fulfill({
        json: {
          ...jobListFixture,
          total: 2,
          items: [
            { ...jobFixture, id: 3101, lineage_size: 3, twin_count: 2, posting_reality: standing },
            // The same chips without the sign, so the comparison isolates it.
            {
              ...jobFixture, id: 3102, lineage_size: 3, twin_count: 2,
              posting_reality: { ...standing, level: "none", met: ["long_open"] },
            },
          ],
        },
      }),
    );
    await page.goto("/");
    await expect(page.locator(".job-row")).toHaveCount(2);
    await expect(page.locator(".job-row").first().getByText("May be always open")).toBeVisible();
    await expect(page.locator(".job-row").nth(1).getByText("May be always open")).toHaveCount(0);

    const rows = await page.locator(".job-row").evaluateAll((els) =>
      els.map((row) => {
        const rect = (sel: string) => (row.querySelector(sel) as HTMLElement | null)?.getBoundingClientRect() ?? null;
        const sign = [...row.querySelectorAll(".ui-badge")].find((b) => b.textContent === "May be always open") as
          | HTMLElement
          | undefined;
        return {
          height: Math.round(row.getBoundingClientRect().height - parseFloat(getComputedStyle(row).borderTopWidth)),
          band: rect(".job-meta .job-band"),
          sign: sign ? { top: sign.getBoundingClientRect().top, cut: sign.scrollWidth > sign.clientWidth } : null,
          bandCut: (() => {
            const el = row.querySelector(".job-meta .job-band") as HTMLElement | null;
            return el ? el.scrollWidth > el.clientWidth : null;
          })(),
        };
      }),
    );
    expect(rows[0].sign, `width ${width}`).not.toBeNull();
    expect(Math.abs(rows[0].sign!.top - rows[0].band!.top), `width ${width}: sign on the facts line`).toBeLessThanOrEqual(4);
    expect(rows[0].sign!.cut, `width ${width}: sign text cut`).toBe(false);
    expect(rows[0].bandCut, `width ${width}: band fact cut`).toBe(false);
    expect(rows[0].height, `width ${width}: row heights ${rows.map((r) => r.height).join(", ")}`).toBe(rows[1].height);
    await page.unroute("/api/jobs?**");
  }
});

/* A focused row wears ONE focus treatment. Clicking a row focuses
 * it; Escape closes the detail and flips the browser into keyboard modality,
 * so :focus-visible then matches on the row that still holds focus. The app
 * scope's generic ring would land OUTSIDE the full-bleed row as a stray
 * square box. The row wears the app's one ring drawn INSIDE it, not the gold
 * left edge, which is the mark of a row picked for Compare. */
test("a row left focused by click-then-Escape wears the one ring, inside the row", async ({ page }) => {
  await page.goto("/");
  const row = page.getByRole("article").filter({ hasText: "Staff Product Manager, API" });
  await row.getByText("Staff Product Manager, API").click();
  await expect(detail(page)).toBeVisible();

  await page.keyboard.press("Escape");
  await expect(detail(page)).toHaveCount(0);
  // Focus returns to the row after the cover has gone; read the paint once it has.
  await expect(row).toBeFocused();

  const paint = await row.evaluate((el) => ({
    focused: document.activeElement === el,
    focusVisible: el.matches(":focus-visible"),
    outlineStyle: getComputedStyle(el).outlineStyle,
    outlineWidth: getComputedStyle(el).outlineWidth,
    outlineOffset: getComputedStyle(el).outlineOffset,
    boxShadow: getComputedStyle(el).boxShadow,
  }));
  // The focus IS shown (a keyboard user who pressed Escape must see where
  // they are), by the one ring inside the row, and not by the Compare edge.
  expect(paint.focused).toBe(true);
  expect(paint.focusVisible).toBe(true);
  expect(paint.outlineStyle).toBe("solid");
  expect(parseFloat(paint.outlineWidth)).toBeGreaterThanOrEqual(2);
  expect(parseFloat(paint.outlineOffset)).toBeLessThan(0);
  expect(paint.boxShadow).not.toContain("inset");
});

/* ---- read state, list failure, the nav rail ------------------------------- */

test("opening an opportunity recedes its row — ink and weight, no fill — and leaves the word for assistive tech", async ({ page }) => {
  const viewRequests: string[] = [];
  await page.route("/api/jobs/*/view", (route) => {
    viewRequests.push(route.request().url());
    return route.fulfill({ json: { job_id: 101, viewed_at: "2026-07-15T18:30:00Z" } });
  });

  await page.goto("/");
  const row = page.getByRole("article").filter({ hasText: "Staff Product Manager, API" });
  await expect(row).not.toHaveClass(/is-viewed/);
  // The sighted signal is the PAINTED recession: title and
  // numeral step down one ink and one weight, together, and the ground does
  // not change: a fill is too faint against the ground to read, and is the
  // advance channel besides.
  // Read the computed values so a class that toggles while the sheet stops
  // honouring it still fails here.
  const paint = () =>
    row.evaluate((el) => {
      const cs = (sel: string) => getComputedStyle(el.querySelector(sel)!);
      return {
        title: { color: cs(".job-title").color, weight: Number(cs(".job-title").fontWeight) },
        comp: { color: cs(".comp").color, weight: Number(cs(".comp").fontWeight) },
        ground: getComputedStyle(el).backgroundColor,
      };
    });
  const fresh = await paint();
  expect(fresh.title.color).toBe(fresh.comp.color);

  await row.getByText("Staff Product Manager, API").click();
  await expect(detail(page)).toBeVisible();
  await page.getByRole("button", { name: "Back" }).click();

  await expect(row).toHaveClass(/is-viewed/);
  await page.mouse.move(0, 0); // off the row: the hover ground must not leak into the reading
  // Background transitions keep their interpolated color for a frame after
  // pointer leave, especially in WebKit. Assert the settled ground; a permanent
  // viewed fill still fails this contract instead of racing the transition.
  await expect.poll(async () => (await paint()).ground).toBe(fresh.ground);
  const read = await paint();
  expect(read.title.color).not.toBe(fresh.title.color);
  expect(read.title.color).toBe(read.comp.color); // the pair steps together
  expect(read.title.weight).toBeLessThan(fresh.title.weight);
  expect(read.comp.weight).toBeLessThan(fresh.comp.weight);
  expect(read.ground).toBe(fresh.ground);
  // The word is screen-reader-only (the receded row is the sighted signal),
  // so assert both halves. `toBeVisible` would NOT catch a regression here:
  // Playwright counts the 1x1 clipped sr-only span as visible, so it passes
  // whichever way this renders. Measuring the painted box is what discriminates.
  const label = row.getByText("viewed");
  await expect(label).toHaveClass(/sr-only/);
  expect((await label.boundingBox())!.height).toBeLessThanOrEqual(1);
  await expect.poll(() => viewRequests.some((url) => url.endsWith("/api/jobs/101/view"))).toBe(true);
});

test("a failed opportunity request is visible and can be retried", async ({ page }) => {
  let attempts = 0;
  let available = false;
  await page.route("/api/jobs?**", (route) => {
    attempts += 1;
    if (!available) {
      return route.fulfill({
        status: 503,
        contentType: "application/json",
        body: JSON.stringify({ detail: "Database unavailable" }),
      });
    }
    return route.fulfill({ json: twoJobList });
  });

  await page.goto("/");

  await expect(page.getByRole("alert")).toContainText("Couldn't load your radar");
  available = true;
  await page.getByRole("button", { name: "Try again" }).click();

  await expect(page.getByText("Staff Product Manager, API")).toBeVisible();
  expect(attempts).toBeGreaterThanOrEqual(2);
});

test("desktop navigation starts compact and expands from the rail control", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name === "mobile", "Mobile uses bottom navigation.");

  await page.goto("/");

  const app = page.locator(".app");
  const rail = page.getByRole("navigation", { name: "Primary" });
  const opportunities = page.getByRole("link", { name: "Radar" });

  await expect(app).not.toHaveClass(/nav-expanded/);
  await expect(rail).toHaveClass(/collapsed/);
  await expect(rail).toHaveCSS("width", "72px");
  await expect(page.locator(".brand-copy")).toBeHidden();

  await opportunities.hover();
  await expect
    .poll(() => opportunities.evaluate((node) => getComputedStyle(node, "::after").opacity))
    .toBe("1");

  await page.getByRole("button", { name: "Expand navigation" }).click();

  await expect(app).toHaveClass(/nav-expanded/);
  await expect(rail).toHaveClass(/expanded/);
  await expect(rail).toHaveCSS("width", "204px");
  await expect(page.locator(".brand-copy")).toBeVisible();
});

test("while a plugin answers pay, a row at a company it has not read leaves the cell empty and says why on hover", async ({
  page,
}) => {
  await page.route("/api/status", (route) => route.fulfill({ json: { ...statusFixture, capabilities: [
    { slot: "pay.levels", providers: ["example-ladder"], builtin: false },
  ] } }));
  await page.route("/api/pay-coverage", (route) =>
    route.fulfill({ json: { plugin: "example-ladder", plugin_name: "Example ladder data", companies: ["anthropic"] } }));
  const none = { comp_low: null, comp_high: null, comp_median: null, comp_base_low: null, comp_base_high: null,
                 comp_base_median: null };
  await page.route("/api/jobs?**", (route) => route.fulfill({ json: {
    ...jobListFixture,
    total: 2,
    items: [
      { ...jobFixture, ...none, id: 4001, company: "openai", title: "Unread Company Role" },
      { ...jobFixture, id: 4002, company: "anthropic", title: "Read Company Role" },
    ],
  } }));
  await page.goto("/");
  const unread = page.locator('[data-job-id="4001"]');
  // Visible text is none: the only words are the screen reader's.
  await expect(unread.locator(".comp")).toHaveText(/^Base salary not known .*a company it hasn't read yet shows no estimate/);
  expect(await unread.locator(".comp").evaluate((el) => [...el.childNodes]
    .filter((n) => !(n instanceof HTMLElement && n.classList.contains("sr-only"))).map((n) => n.textContent).join(""))).toBe("");
  await expect(unread.locator(".comp")).toHaveAttribute("title", /a company it hasn't read yet shows no estimate/);
  await expect(page.locator('[data-job-id="4002"] .comp')).toHaveText(/^\$400K /);
});

test("while ours answers pay, no screen asks which companies a plugin has read", async ({ page }) => {
  const asked: string[] = [];
  await page.route("/api/pay-coverage", (route) => {
    asked.push(route.request().url());
    return route.fulfill({ json: { plugin: null, plugin_name: null, companies: [] } });
  });
  await page.goto("/");
  await expect(page.locator(".job-row").first()).toBeVisible();
  expect(asked).toEqual([]);
});

for (const width of [1440, 2000]) {
  test(`the toolbar ends where the rows end at ${width}px`, async ({ page }) => {
    // Fail-first: from 1100px the rows keep a 76px ledger margin for beacons
    // and the toolbar did not, so the screen had two right edges.
    await page.setViewportSize({ width, height: 900 });
    await page.goto("/");
    const lastRow = page.getByRole("article").last();
    await expect(lastRow).toBeVisible();
    const rowRight = await lastRow.evaluate((el) => el.getBoundingClientRect().right);
    const toolbarRight = await page.locator(".board-toolbar-end").evaluate((el) => el.getBoundingClientRect().right);
    expect(Math.abs(toolbarRight - rowRight), `toolbar ${toolbarRight} vs row ${rowRight}`).toBeLessThanOrEqual(1);
  });
}
