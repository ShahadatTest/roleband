/* What a drag selects.

   The behaviour half of the selection system; src/design/selection.test.ts is
   the source half, and neither is sufficient alone. That one can see that the
   rule is still stated once and nowhere else; it cannot see whether the rule
   works. This one drags a real pointer across real chrome and reads
   `getSelection()`.

   The negative controls in the second block are the point of the file. A
   blanket `body { user-select: none }` passes every assertion in the first
   block perfectly while making the product uncopyable — a job description, a
   comp figure, a requisition id — which is a quieter and worse bug than the
   one this system fixes, because nothing visibly breaks. A benchmark that
   cannot fail measures nothing (docs/testing.md); these are how this one can.

   Two measurement traps:

   - Sweeping a whole-row click target ends in a NAVIGATION. `mouse.up` fires
     the row's click, the Job detail cover opens, and the selection read
     afterwards belongs to a different screen. The selection is therefore read
     MID-DRAG, before the release, and a capture-phase blocker keeps the
     release from navigating anyway.
   - A mouse drag inside an `<input>` registers no selection in headless
     chromium, with or without any `user-select`. A field is checked through
     `selectionStart`/`selectionEnd`, never a drag. */

import { expect, test } from "./fixtures";
import { installBoardRoutes } from "./boardHarness";
import type { Page } from "@playwright/test";

test.beforeEach(async ({ page }) => {
  await installBoardRoutes(page);
});

/** What Cmd+A then Cmd+C yields for a subtree. `selectAllChildren` honours
 *  `user-select` exactly as a keyboard select-all does, and identically in both
 *  engines — with no pointer, no navigation and no flake. It is the only way to
 *  ask the question for text inside an ANCHOR: dragging a link starts a
 *  link-drag rather than a selection, so a sweep over one reports "" whatever
 *  the rules say, including on a plain anchor with no rules at all. */
async function copyOf(page: Page, selector: string): Promise<string> {
  return page.evaluate((sel) => {
    const root = document.querySelector(sel);
    if (!root) throw new Error(`no element for ${sel}`);
    const selection = window.getSelection();
    if (!selection) return "";
    selection.removeAllRanges();
    selection.selectAllChildren(root);
    const text = selection.toString().replace(/\s+/g, " ").trim();
    selection.removeAllRanges();
    return text;
  }, selector);
}

/** Drag across an element the way a reader does, and report what got selected. */
async function sweep(page: Page, selector: string): Promise<string> {
  await page.evaluate(() => {
    const w = window as unknown as { __selGuard?: boolean };
    if (w.__selGuard) return;
    w.__selGuard = true;
    document.addEventListener("click", (e) => { e.preventDefault(); e.stopPropagation(); }, true);
  });
  const box = await page.locator(selector).first().boundingBox();
  if (!box) throw new Error(`no box for ${selector}`);
  await page.evaluate(() => window.getSelection()?.removeAllRanges());
  const y = box.y + Math.min(box.height / 2, 300);
  await page.mouse.move(box.x + 2, y);
  await page.mouse.down();
  const width = Math.min(box.width - 4, 1100);
  for (let i = 1; i <= 12; i += 1) {
    await page.mouse.move(box.x + 2 + width * (i / 12), y, { steps: 2 });
  }
  const text = await page.evaluate(() =>
    (window.getSelection()?.toString() ?? "").replace(/\s+/g, " ").trim(),
  );
  await page.mouse.up();
  return text;
}

test.describe("chrome is not prose", () => {
  test.skip(({ isMobile }) => isMobile, "drag-to-select is a pointer gesture; touch selects by long-press");

  test("a drag across the shell's instruments selects nothing", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByRole("heading", { name: "Radar", level: 1 })).toBeVisible();

    // Without the rules the top bar hands back its title, shortcut hint and
    // counts ("Radar ⌘ K 1501 open ...") ahead of any role.
    expect(await sweep(page, "header.topbar")).toBe("");
    expect(await sweep(page, "nav.nav-rail")).toBe("");
  });

  test("a drag across a list's own chrome selects nothing", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByRole("heading", { name: "Radar", level: 1 })).toBeVisible();

    expect(await sweep(page, ".board-toolbar")).toBe("");
    expect(await sweep(page, ".results-count")).toBe("");
    expect(await sweep(page, ".list-head")).toBe("");
  });

  test("a filter register's group names are labels, not headings", async ({ page }) => {
    /* "Comp from", "Posted within" and "Comp up to" would stay selectable
       because `ui/FilterRail`'s FilterGroup
       renders a bare <h3>, and the element rule leaves headings alone — a
       section title is content a reader may quote. Inside a control surface it
       is not a title at all; it is the name of the control under it. Same
       component, same bug, on the Notifications register ("Status",
       "Priority"). Asserted by computed style rather than a sweep because a
       collapsed group has no box to drag across. */
    // The register is PINNED only on a wide viewport; narrower, it folds into
    // a drawer and renders no groups at all, and this test would pass against
    // nothing.
    await page.setViewportSize({ width: 1600, height: 900 });
    await page.goto("/");
    await expect(page.getByRole("complementary", { name: "Filters" })).toBeVisible();

    /* The FilterGroup headings live behind "More filters": the always-tier is FacetGroups, whose name sits in a button. Open the
       door, or this measures nothing; the guard below is what says so. */
    const door = page.getByRole("button", { name: /^More filters/ });
    if ((await door.getAttribute("aria-expanded")) === "false") await door.click();
    await expect(page.locator(".board-filters .filter-drawer h3").first()).toBeVisible();

    /* Only headings that carry their OWN text. A FacetGroup's head is an <h3>
       whose name lives in a `.filter-title` button — already unselectable by
       role — so asserting on the wrapper would fail for a group that has no
       leak to fix. */
    const leaks = await page.locator(".board-filters h3").evaluateAll((nodes) =>
      nodes
        .map((el) => {
          const own = [...el.childNodes]
            .filter((n) => n.nodeType === 3)
            .map((n) => n.textContent?.trim() ?? "")
            .join(" ")
            .trim();
          const style = getComputedStyle(el) as CSSStyleDeclaration & { webkitUserSelect?: string };
          const pick = style.userSelect ?? style.webkitUserSelect ?? "";
          return { own, pick };
        })
        .filter((row) => row.own !== ""),
    );
    expect(leaks.length, "the board rail renders FilterGroup headings").toBeGreaterThan(0);
    expect(
      leaks.filter((row) => row.pick !== "none").map((row) => row.own),
      "a register's group name is the name of the control under it, not a section title",
    ).toEqual([]);
  });

  test("a control's label stays out of a selection that passes through it", async ({ page }) => {
    await page.goto("/");
    const title = page.getByRole("heading", { name: "Staff Product Manager, API" });
    await expect(title).toBeVisible();

    /* The row is the mixed case the whole design turns on: the title is
       content, the company chip and the level badge are controls standing
       beside it. Sweeping the row must reach the title and stop at the chip. */
    const selected = await sweep(page, "article.job-row");
    expect(selected).not.toContain("openai");
  });
});

test.describe("content is still the user's", () => {
  test.skip(({ isMobile }) => isMobile, "drag-to-select is a pointer gesture; touch selects by long-press");

  /* These four fail if anyone ever reaches for a blanket `user-select: none`,
     which is the cheapest way to make every assertion above pass. */

  test("a job title can be selected by dragging across it", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByRole("heading", { name: "Staff Product Manager, API" })).toBeVisible();
    expect(await sweep(page, "article.job-row h2.job-title")).toContain("Product Manager");
  });

  test("the description on Job detail can be selected", async ({ page }) => {
    await page.goto("/company/openai/job/101");
    await expect(page.getByRole("heading", { name: "Staff Product Manager, API" }).first()).toBeVisible();
    const body = page.locator(".jd-sections p, .jd-sections li, .jd-fallback").first();
    await expect(body).toBeVisible();
    expect(await sweep(page, ".jd-sections p, .jd-sections li, .jd-fallback")).toContain("product strategy");
  });

  test("a comp figure can be selected — the number people paste elsewhere", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByRole("heading", { name: "Staff Product Manager, API" })).toBeVisible();
    expect(await sweep(page, "article.job-row .jr-comp .comp")).toMatch(/\d/);
  });


  test("a search field's own value stays selectable inside chrome", async ({ page }) => {
    /* The field sits INSIDE the board toolbar, which is marked chrome — the
       one place the region rule could plausibly take something the user owns.
       Read through the field's own selection API, never a drag (see header). */
    await page.goto("/");
    const search = page.getByRole("searchbox").first();
    await search.fill("platform reliability");
    await search.click({ clickCount: 3 });
    const picked = await search.evaluate((el: HTMLInputElement) =>
      el.value.slice(el.selectionStart ?? 0, el.selectionEnd ?? 0),
    );
    expect(picked).toBe("platform reliability");
  });
});

test("a job title inside a whole-row link is still a job title", async ({ page }) => {
  /* `patterns/jobs/JobLinkRow` is a whole-row click target, so the row wears
     `data-selection="chrome"`, which must not take the TITLE inside it out of
     a select-all (Job detail's "More like this", Statistics panels, the
     Intelligence preview). A row being a control does not make its subject a
     label, and every chrome assertion above stays green when it does.

     Asserted through a select-all and not a drag, because no drag can answer
     it: a pointer drag across a link starts a link-drag in both engines, so a
     sweep reports "" even on a plain anchor carrying no rules whatever. */
  await page.route("/api/jobs/101/similar**", (route) => {
    const scope = new URL(route.request().url()).searchParams.get("scope");
    return route.fulfill({ json: { scope, items: scope === "within" ? [] : [
      { id: 909, title: "Group Product Manager, Payments", company: "stripe", score: 0.8,
        level_band: "staff", locations: ["New York, NY"], comp_median: 700000 },
    ] } });
  });
  await page.goto("/company/openai/job/101");
  const row = page.locator("a.job-link .mj-title").first();
  await expect(row).toBeVisible();
  expect(await copyOf(page, "a.job-link")).toContain("Group Product Manager, Payments");
});

test("selecting the whole board copies the roles and none of the instruments", async ({ page }) => {
  /* Stated as the gesture people actually use to take a page: without the
     selection rules a select-all on the board hands back
     `Radar ⌘ K 1501 open 1185 new 72 reposted 3 saved Fresh · 15h ago` ahead of
     a single role. Engine-independent and pointer-free (see `copyOf`). */
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Staff Product Manager, API" })).toBeVisible();

  const shell = await copyOf(page, "#root");
  expect(shell).toContain("Staff Product Manager, API");   // the roles survive
  expect(shell).not.toContain("⌘ K");                      // the palette hint does not
  expect(shell).not.toMatch(/\bopen\b\s*$/);               // nor a top-bar count's unit
  expect(shell).not.toContain("Page 1 of");                // nor the pager
  expect(shell).not.toContain("LOCATION");                 // nor the column heads
});

test("no control on the board or Job detail carries selectable text", async ({ page }) => {
  /* The inventory half, name-blind on purpose: a name-matching gate waves
     through a control whose name does not say "button" (docs/ui.md).
     Ratcheted at zero: a new control role the rule does not list, or an
     escape hatch used on a control, fails here with its selector printed.

     Anchors are not in the set. `a[href]` stays selectable by design so a link
     in running prose can be copied; the anchor shapes that are CONTROLS wear
     one of six classes and are covered by the rule in shell.css. */
  const scan = () => {
    const CONTROLS = [
      "button", "summary", "label", "select",
      '[role="button"]', '[role="tab"]', '[role="option"]', '[role="switch"]',
    ].join(",");
    const name = (el: Element) => {
      const cls = typeof el.className === "string" ? el.className.trim().split(/\s+/).slice(0, 2).join(".") : "";
      return cls ? `${el.tagName.toLowerCase()}.${cls}` : el.tagName.toLowerCase();
    };
    const found: string[] = [];
    document.querySelectorAll("*").forEach((el) => {
      const ownText = [...el.childNodes].some((n) => n.nodeType === 3 && n.textContent?.trim());
      if (!ownText) return;
      const style = getComputedStyle(el) as CSSStyleDeclaration & { webkitUserSelect?: string };
      /* BOTH spellings. WebKit does not expose `userSelect` on a computed
         style at all — it answers `undefined` — so a scan reading only the
         unprefixed name reports every control in the app as selectable on the
         mobile project. */
      if (style.userSelect === "none" || style.webkitUserSelect === "none") return;
      if (style.display === "none" || style.visibility === "hidden") return;
      const control = el.closest(CONTROLS);
      if (control) found.push(`${name(control)} > ${name(el)}`);
    });
    return [...new Set(found)];
  };

  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Staff Product Manager, API" })).toBeVisible();
  expect(await page.evaluate(scan), "the board").toEqual([]);

  await page.goto("/company/openai/job/101");
  await expect(page.getByRole("heading", { name: "Staff Product Manager, API" }).first()).toBeVisible();
  expect(await page.evaluate(scan), "job detail").toEqual([]);
});
