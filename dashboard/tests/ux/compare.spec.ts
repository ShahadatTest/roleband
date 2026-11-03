/* The comparison screen.
 *
 * Three claims, all about what a reader meets on arrival:
 *  - the selection holds THREE roles, and a fourth row says so instead of
 *    silently doing nothing;
 *  - the attribute grid starts at the first real difference, not at two rows
 *    restating the column head above them;
 *  - the descriptions arrive folded, one line per role, and open on the
 *    passages that differ against a baseline the reader names.
 *
 * Height is the reason all three exist, so height is measured here: at the cap,
 * everything above the descriptions has to fit a laptop viewport.
 */

import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "./fixtures";
import { comparison, installBoardRoutes } from "./boardHarness";
import { mockGet, watchReads } from "./fixtures";
import { expectOnTop, pointAndClick, strangersOver } from "./paint";
import { jobFixture, jobListFixture } from "../../src/test/fixtures";
import { msg } from "../../src/test/msg";

const SHARED = "Partner with engineering on the platform roadmap.";

/* Four roles that agree on level and status and disagree on pay, place and
   age — so the ledger has both shapes to show: a Same cell, and tinted rows. */
const role = (id: number, title: string, company: string, own: string, facts: Partial<typeof jobFixture>) => ({
  ...jobFixture,
  id,
  company,
  req_id: `req-${id}`,
  title,
  url: `https://example.test/jobs/${id}`,
  description_text: `${SHARED}\n${own}`,
  ...facts,
});

const ROLES = [
  role(701, "Staff Product Manager, API", "openai", "Only here: own the public API surface.",
    { comp_low: 650000, comp_high: 820000, comp_median: 735000, locations: ["San Francisco, CA"], workplace_type: "hybrid", listed_days: 48 }),
  role(702, "Principal Engineer, Platform", "google", "Only here: run the ingest pipeline.",
    { comp_low: 228000, comp_high: 308000, comp_median: 268000, locations: ["Mountain View, CA"], workplace_type: "onsite", listed_days: 17 }),
  role(703, "Director, Payments", "amazon", "Only here: chair the payments council.",
    { comp_low: 256000, comp_high: 384000, comp_median: 320000, locations: ["Seattle, WA"], workplace_type: "remote", listed_days: 0 }),
  role(704, "Head of Product, Search", "apple", "Only here: lead search relevance.", {}),
];

test.beforeEach(async ({ page }) => {
  await installBoardRoutes(page);
  for (const job of ROLES) {
    await mockGet(page, `/api/jobs/${job.id}`, (route) => route.fulfill({ json: job }));
  }
  await mockGet(page, "/api/jobs?**", (route) =>
    route.fulfill({ json: { ...jobListFixture, total: ROLES.length, items: ROLES } }));
});

const row = (page: import("./fixtures").Page, title: string) =>
  page.getByRole("article").filter({ hasText: title });

async function selectThree(page: import("./fixtures").Page) {
  for (const job of ROLES.slice(0, 3)) {
    await row(page, job.title).getByRole("button", { name: msg("jobs-compare") }).click();
  }
}

test("the comparison holds three roles, and the fourth row says why it cannot join", async ({ page }) => {
  await page.goto("/");
  await selectThree(page);

  const fourth = row(page, "Head of Product, Search").getByRole("button", { name: msg("jobs-compare") });
  await expect(fourth).toBeDisabled();
  await expect(fourth).toHaveAttribute("title", msg("jobs-compare-full-cap", { cap: 3 }));
  // The count never claims a fourth role, and the pill says the selection is full.
  await expect(page.getByRole("button", { name: /in compare/ })).toHaveAccessibleName(msg("jobs-compare-beacon-aria-full", { count: 3 }));
});

test("the grid starts at the first real difference, and the descriptions arrive as columns under their roles", async ({ page }) => {
  await page.goto("/");
  await selectThree(page);
  await page.goto("/compare");
  const cover = comparison(page);
  await expect(cover).toContainText("Comparing 3 roles");

  // The column head carries the company chip and the title, so neither is
  // a row. The first row of the grid is the first thing the head does not say.
  const grid = page.locator(".compare-grid");
  await expect(grid.locator(".cmp-label").first()).toHaveText("Level");
  await expect(grid.getByText("Company", { exact: true })).toHaveCount(0);
  await expect(grid.getByText("Title", { exact: true })).toHaveCount(0);

  // Agreement is compressed: three identical levels are ONE Same cell.
  await expect(grid.locator(".cmp-same").first()).toContainText("Same");
  await expect(grid.locator(".cmp-same").first()).toContainText("Staff");

  // Three descriptions, one under each role; what only some
  // postings say is on screen, what all three share is folded per column.
  await expect(grid.locator(".cmp-prose")).toHaveCount(3);
  for (const role of ROLES.slice(0, 3)) {
    // `...facts` spreads last, so the builder's own description_text is widened
    // back to the fixture's `string | null` and tsconfig.ux rejects the split.
    await expect(cover.getByText(role.description_text!.split("\n")[1])).toBeVisible();
  }
  await expect(cover.getByText(SHARED)).toHaveCount(0);
  await expect(cover.getByText("1 shared passage hidden")).toHaveCount(3);
});

test("the three description cells sit on one row, and the whole posting is one click away", async ({ page, isMobile }) => {
  test.skip(isMobile, "alignment is a claim about the three-column layout");
  await page.goto("/");
  await selectThree(page);
  await page.goto("/compare");
  const cells = page.locator(".cmp-prose");
  await expect(cells).toHaveCount(3);
  // Aligned by the grid row: the section starts at the same y in every column,
  // once each column's content has landed (they load one by one).
  const spread = async () => {
    const tops = await Promise.all([0, 1, 2].map(async (i) => (await cells.nth(i).boundingBox())!.y));
    return Math.max(...tops) - Math.min(...tops);
  };
  await expect.poll(spread).toBeLessThan(1);
  // Three columns side by side, each with reading room.
  const widths = await Promise.all([0, 1, 2].map(async (i) => (await cells.nth(i).boundingBox())!.width));
  for (const w of widths) expect(w).toBeGreaterThan(300);

  await comparison(page).getByRole("button", { name: "Show full descriptions" }).click();
  await expect(comparison(page).getByText(SHARED)).toHaveCount(3);
});

test("each column carries Save and Not for me; Not for me leaves the comparison with a way back", async ({ page }) => {
  let favorite: [number, boolean] | null = null;
  await page.route("/api/jobs/*/favorite", async (route) => {
    const id = Number(new URL(route.request().url()).pathname.split("/")[3]);
    // PUT saves, DELETE unsaves — the verb is the payload (api.setFavorite).
    favorite = [id, route.request().method() === "PUT"];
    await route.fulfill({ json: { job_id: id, is_favorite: favorite[1] } });
  });
  const dismissed: number[] = [];
  await page.route("/api/jobs/*/feedback", async (route) => {
    const id = Number(new URL(route.request().url()).pathname.split("/")[3]);
    if (route.request().method() === "DELETE") dismissed.splice(dismissed.indexOf(id), 1);
    else dismissed.push(id);
    await route.fulfill({ json: { job_id: id, is_dismissed: route.request().method() !== "DELETE" } });
  });
  await page.goto("/");
  await selectThree(page);
  await page.goto("/compare");
  const cover = comparison(page);

  await cover.getByRole("button", { name: /^Save$/ }).nth(1).click();
  await expect.poll(() => favorite).toEqual([702, true]);

  await cover.getByRole("button", { name: "Not for me: Director, Payments" }).click();
  await expect.poll(() => dismissed).toEqual([703]);
  await expect(cover).toContainText("Comparing 2 roles");
  await page.getByRole("button", { name: "Undo" }).click();
  await expect.poll(() => dismissed).toEqual([]);
  await expect(cover).toContainText("Comparing 3 roles");
});

/* A role opened from a column is a cover over the comparison, which stays
   mounted under it. A save made in that cover saves a role the comparison is
   drawing, so on the way back the column says so, and the header's counts are
   read again. A save announced only to the lists keyed on the saved version
   would leave the column with the star it was drawn with until the comparison
   was opened again. */
test("a role saved in the cover over the comparison is saved in its column on the way back", async ({ page }) => {
  let favorite: [number, boolean] | null = null;
  await page.route("/api/jobs/*/favorite", async (route) => {
    const id = Number(new URL(route.request().url()).pathname.split("/")[3]);
    favorite = [id, route.request().method() === "PUT"];
    await route.fulfill({ json: { job_id: id, is_favorite: favorite[1] } });
  });
  const stats = watchReads(page, "GET", "/api/stats");
  await page.goto("/");
  await selectThree(page);
  await page.goto("/compare");
  const cover = comparison(page);
  await expect(cover.getByRole("button", { name: "Save", exact: true })).toHaveCount(3);

  await cover.getByRole("link", { name: "Principal Engineer, Platform" }).click();
  const role = page.getByRole("dialog", { name: "Role: Principal Engineer, Platform" });
  const before = stats.answered;
  await role.getByRole("button", { name: "Save", exact: true }).click();
  await expect.poll(() => favorite).toEqual([702, true]);
  await expect.poll(() => stats.answered).toBeGreaterThan(before);
  await role.getByRole("button", { name: "Back" }).click();
  await expect(role).toBeHidden();

  // The comparison was not opened again: the same screen, its column patched.
  const saved = cover.getByRole("button", { name: msg("jobs-save"), pressed: true });
  await expect(saved).toHaveCount(1);
  await expect(saved).toHaveAttribute("aria-pressed", "true");
  await expect(cover.getByRole("button", { name: msg("jobs-save"), pressed: false })).toHaveCount(2);
});

/* A role opened from a column covers the comparison, which stays mounted
   underneath with a scroll box of its own. Opening the role leaves that box
   where the reader had it, so Back returns to the same place. */
test("opening a role from a column keeps the comparison where the reader left it", async ({ page }) => {
  await page.goto("/");
  await selectThree(page);
  await page.goto("/compare");
  const cover = comparison(page);
  await cover.getByRole("button", { name: "Show full descriptions" }).click();
  const scroller = page.locator(".compare-cover .cover-scroll");
  const link = cover.getByRole("link", { name: "Principal Engineer, Platform" });
  await scroller.evaluate((el) => el.scrollBy({ top: 120, behavior: "instant" }));
  await link.scrollIntoViewIfNeeded();
  const before = await scroller.evaluate((el) => el.scrollTop);
  expect(before, "the comparison is too short to scroll").toBeGreaterThan(0);

  await link.click();
  const role = page.getByRole("dialog", { name: "Role: Principal Engineer, Platform" });
  await expect(role.getByRole("heading", { name: "Principal Engineer, Platform" })).toBeVisible();
  expect(await scroller.evaluate((el) => el.scrollTop)).toBe(before);
  await role.getByRole("button", { name: "Back" }).click();
  await expect(role).toBeHidden();
  expect(await scroller.evaluate((el) => el.scrollTop)).toBe(before);
});

/* The confirmation belongs to THIS screen. Removing a role toasts
   with the way back, and the way back puts the role back into the comparison —
   so on the Radar it is an offer to undo an edit to a list that is not on the
   page, under a report about a screen the reader has left.

   Taken through the COVER, which is the sharp case: the list the roles were
   picked on is still mounted underneath and history still names it, so a rule
   that read the screen THROUGH to that background would have assigned this
   toast to the board before it was ever raised, and Back would keep it. */
test("the way back does not follow the reader off the screen that offered it", async ({ page, isMobile }) => {
  await page.goto("/");
  await selectThree(page);

  const pill = page.getByRole("button", { name: /Compare 3 roles$/ });
  await pill.click();
  // No hover on a phone: the tap opens the roster, whose primary is the way on.
  if (isMobile) {
    await page.getByRole("dialog", { name: "In compare" })
      .getByRole("button", { name: "Compare 3 roles" }).click();
  }
  await expect(page).toHaveURL(/\/compare$/);
  const cover = comparison(page);

  await cover.getByRole("button", { name: "Remove Director, Payments" }).click();
  const toast = page.getByRole("status").filter({ hasText: "Removed Director, Payments from compare" });
  await expect(toast).toBeVisible();
  // Painted, not merely present: `toBeVisible()` passes while a cover buries it.
  await expectOnTop(toast.getByRole("button", { name: "Undo" }), "Undo");

  // Back pops history rather than reloading, so nothing but the rule under test
  // can take the toast away.
  await cover.getByRole("button", { name: "Back" }).click();
  await expect(page.getByRole("heading", { name: "Radar", level: 1 })).toBeVisible();
  await expect(page.getByRole("button", { name: "Undo" })).toHaveCount(0);
  await expect(page.getByText("Removed Director, Payments from compare")).toHaveCount(0);

  // Gone rather than hidden: re-opening the comparison does not bring it back.
  await page.getByRole("button", { name: /Compare 2 roles$/ }).click();
  if (isMobile) {
    await page.getByRole("dialog", { name: "In compare" })
      .getByRole("button", { name: "Compare 2 roles" }).click();
  }
  await expect(comparison(page)).toContainText("Comparing 2 roles");
  await expect(page.getByRole("button", { name: "Undo" })).toHaveCount(0);
});

/* Removing a role from the comparison is reversible (it raises Undo), so its
   button is an icon button like its neighbours and hovers like them, never in
   danger red, the colour the app keeps for what cannot be undone
   (uninstalling a plugin, deleting data). */
test("Remove hovers like the icon buttons beside it: undoable is not danger", async ({ page, isMobile }) => {
  test.skip(isMobile, "no hover on a phone");
  await page.goto("/");
  await selectThree(page);
  await page.goto("/compare");
  const title = ROLES[0].title;
  const removeName = msg("compare-screen-remove-from-comparison", { title });
  const notForMeName = msg("compare-screen-not-for-me", { title });
  await expect(page.getByRole("button", { name: removeName })).toBeVisible();
  const paint = async (name: string) => {
    const button = page.getByRole("button", { name, exact: true });
    await button.hover();
    await page.waitForTimeout(250);
    const style = await button.evaluate((el) => {
      const cs = getComputedStyle(el);
      return { color: cs.color, background: cs.backgroundColor, border: cs.borderTopColor };
    });
    await page.mouse.move(0, 0);
    return style;
  };
  const remove = await paint(removeName);
  const notForMe = await paint(notForMeName);
  expect(remove).toEqual(notForMe);
});

/* Open the comparison OVER the list: the modal cover is the shell that can
   bury a toast. By URL the comparison is the page and the way back always
   paints, so a spec that arrives by `goto("/compare")` proves nothing about
   this. Asserting the dialog is what keeps that from drifting. */
async function openOverTheList(page: import("./fixtures").Page, isMobile: boolean) {
  await page.getByRole("button", { name: /Compare 3 roles$/ }).click();
  if (isMobile) {
    await page.getByRole("dialog", { name: "In compare" })
      .getByRole("button", { name: "Compare 3 roles" }).click();
  }
  const cover = page.getByRole("dialog", { name: "Comparison", exact: true });
  await expect(cover).toHaveAttribute("aria-modal", "true");
  // The cover is the whole screen. The roster that opened it (a popover, hover-
  // opened on desktop and tapped open on a phone) must not survive above it.
  await expect.poll(() => strangersOver(cover)).toEqual([]);
  return cover;
}

/* The way back raised INSIDE the cover is the thing painted where it sits, and a
   pointer there takes it. The cover borrows focus handling from the Overlay,
   and a cover promoted to the dialog layer with it would render the toast
   host under an opaque full-viewport surface: in the DOM, announced, and never
   on screen. `toBeVisible()` passes either way, so this asserts the hit test. */
test("inside the cover, the way back is painted on top and a pointer takes it", async ({ page, isMobile }) => {
  await page.goto("/");
  await selectThree(page);
  const cover = await openOverTheList(page, isMobile);

  await cover.getByRole("button", { name: "Remove Director, Payments" }).click();
  await expect(cover).toContainText("Comparing 2 roles");
  const toast = page.getByRole("status").filter({ hasText: "Removed Director, Payments from compare" });
  const undo = toast.getByRole("button", { name: "Undo" });

  await expectOnTop(undo, "Undo");
  await pointAndClick(page, undo);
  await expect(cover).toContainText("Comparing 3 roles");
  await expect(toast).toHaveCount(0);
});

/* And a keyboard reaches it. Opened over a list the cover traps focus, and the
   toast host is app chrome outside the dialog — so a painted Undo that Tab
   cannot reach is still no way back. The ring runs cover -> toast -> cover:
   never on into the list mounted underneath, which is where DOM order goes.
   Taken on "Not for me", which is two writes behind one Undo. */
test("inside the cover, Tab reaches the way back and comes round to the cover", async ({ page, isMobile }, testInfo) => {
  test.skip(testInfo.project.name === "mobile", "Tab order is a keyboard flow; a phone has no Tab key.");
  const dismissed: number[] = [];
  await page.route("/api/jobs/*/feedback", async (route) => {
    const id = Number(new URL(route.request().url()).pathname.split("/")[3]);
    if (route.request().method() === "DELETE") dismissed.splice(dismissed.indexOf(id), 1);
    else dismissed.push(id);
    await route.fulfill({ json: { job_id: id, is_dismissed: route.request().method() !== "DELETE" } });
  });
  await page.goto("/");
  await selectThree(page);
  const cover = await openOverTheList(page, isMobile);
  const back = cover.getByRole("button", { name: "Back" });

  await cover.getByRole("button", { name: "Not for me: Director, Payments" }).click();
  await expect.poll(() => dismissed).toEqual([703]);
  const toast = page.getByRole("status").filter({ hasText: "Not for me · Director, Payments" });
  const undo = toast.getByRole("button", { name: "Undo" });
  const close = toast.getByRole("button", { name: "Dismiss" });
  await expectOnTop(undo, "Undo");

  // Backwards off the cover's first control: the ring's last is the toast's.
  await back.focus();
  await page.keyboard.press("Shift+Tab");
  await expect(close).toBeFocused();
  await page.keyboard.press("Shift+Tab");
  await expect(undo).toBeFocused();

  // Forwards out of the toast lands on the cover again, not on the list.
  await page.keyboard.press("Tab");
  await expect(close).toBeFocused();
  await page.keyboard.press("Tab");
  await expect(back).toBeFocused();

  // And forwards off the cover's LAST control, into the toast.
  await cover.evaluate((el) => {
    const all = el.querySelectorAll<HTMLElement>(
      'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
    );
    all[all.length - 1].focus();
  });
  await page.keyboard.press("Tab");
  await expect(undo).toBeFocused();

  await page.keyboard.press("Enter");
  await expect.poll(() => dismissed).toEqual([]);
  await expect(cover).toContainText("Comparing 3 roles");

  // Pressing Undo removed the control that held focus, and the toast host sits
  // BEFORE the cover's portal in the document, so an unguarded Shift+Tab walks
  // backwards from it into the list mounted underneath, behind a modal dialog.
  // The cover takes a stray Tab back into its ring.
  await page.keyboard.press("Shift+Tab");
  const landed = await page.evaluate(() =>
    Boolean(document.activeElement?.closest('[role="dialog"][aria-label="Comparison"], [data-above-cover]')));
  expect(landed, "Shift+Tab after Undo left the cover").toBe(true);
});

async function openPalette(page: import("./fixtures").Page) {
  await page.keyboard.press("ControlOrMeta+k");
  const palette = page.getByRole("dialog", { name: "Command palette" });
  await expect(palette).toBeVisible();
  return palette;
}

/* One press of Escape is one surface: the one on top. If every surface that
   closes on Escape listened at the window for itself, one press with the
   palette open over the comparison would close the palette AND step the cover
   back: a reader who opened the palette and thought better of it would lose
   the comparison underneath as well. */
test("over the cover, Escape closes the palette and leaves the comparison open", async ({ page, isMobile }) => {
  await page.goto("/");
  await selectThree(page);
  const cover = await openOverTheList(page, isMobile);

  const palette = await openPalette(page);
  await page.keyboard.press("Escape");
  await expect(palette).toBeHidden();

  // Stepping back is `history.go(-1)`, which lands a task AFTER the key press,
  // so a cover checked the instant the palette hides can still be on its way
  // out. Using it is what proves it stayed.
  await cover.getByRole("button", { name: "Remove Director, Payments" }).click({ timeout: 5_000 });
  await expect(cover).toContainText("Comparing 2 roles");
  await expect(page).toHaveURL(/\/compare$/);

  // The next Escape is the cover's, and it is one step: back to the list.
  await page.keyboard.press("Escape");
  await expect(cover).toHaveCount(0);
  await expect(page).toHaveURL(/\/$/);
  await expect(page.getByRole("heading", { name: "Radar", level: 1 })).toBeVisible();
});

/* Reached by URL the comparison is the page, and a second hand-rolled Escape
   listener there, rather than the Overlay's, would take the same double step
   by another route. Stepping back from here is a push to `/`, so it is
   immediate. */
test("reached by URL, Escape over the comparison closes the palette and nothing else", async ({ page }) => {
  await page.goto("/");
  await selectThree(page);
  await page.goto("/compare");
  const cover = page.getByRole("main", { name: "Comparison", exact: true });
  await expect(cover).toContainText("Comparing 3 roles");

  const palette = await openPalette(page);
  await page.keyboard.press("Escape");
  await expect(palette).toBeHidden();
  await expect(page).toHaveURL(/\/compare$/);
  await expect(cover).toContainText("Comparing 3 roles");

  await page.keyboard.press("Escape");
  await expect(page).toHaveURL(/\/$/);
  await expect(page.getByRole("heading", { name: "Radar", level: 1 })).toBeVisible();
});

/* The palette's "Clear compare selection" and the same act inside the
   comparison share one recipe: both capture the set and offer Undo, even from
   a screen where nothing visible changes, so the two cannot drift apart. */
test("clearing the selection from the palette says so, and Undo puts both roles back", async ({ page }) => {
  await page.goto("/");
  const pair = ROLES.slice(0, 2);
  for (const job of pair) {
    await row(page, job.title).getByRole("button", { name: msg("jobs-compare") }).click();
  }

  const palette = await openPalette(page);
  await page.keyboard.type("clear compare");
  await palette.getByRole("option", { name: "Clear compare selection (2)" }).click();
  await expect(palette).toBeHidden();

  const toast = page.getByRole("status").filter({ hasText: "Cleared 2 roles from compare" });
  await expect(toast).toBeVisible();
  for (const job of pair) {
    await expect(row(page, job.title).getByRole("button", { name: msg("jobs-compare") }))
      .toHaveAttribute("aria-pressed", "false");
  }

  await toast.getByRole("button", { name: "Undo" }).click();
  for (const job of pair) {
    await expect(row(page, job.title).getByRole("button", { name: msg("jobs-compare") }))
      .toHaveAttribute("aria-pressed", "true");
  }
});


test("the comparison cover names only elements with a role, and steps its outline", async ({ page, isMobile }) => {
  await page.goto("/");
  await selectThree(page);
  await page.getByRole("button", { name: /Compare 3 roles$/ }).click();
  if (isMobile) {
    await page.getByRole("dialog", { name: "In compare" }).getByRole("button", { name: "Compare 3 roles" }).click();
  }
  const cover = comparison(page);
  await expect(cover).toBeVisible();
  const { violations, incomplete } = await new AxeBuilder({ page }).analyze();
  const found = [...violations, ...incomplete]
    .filter((v) => v.id === "heading-order" || v.id === "aria-prohibited-attr")
    .map((v) => `${v.id}: ${v.nodes.map((n) => n.html.slice(0, 120)).join(" | ")}`);
  expect(found, found.join("\n")).toEqual([]);
});

test("a description reads at a measure on a wide screen, however wide its column", async ({ page, isMobile }) => {
  test.skip(isMobile, "the measure is a claim about a wide column");
  // Three columns at 2000px are narrower than the measure; at 3440 each is wider.
  await page.setViewportSize({ width: 3440, height: 1300 });
  await page.goto("/");
  await selectThree(page);
  await page.goto("/compare");
  await comparison(page).getByRole("button", { name: "Show full descriptions" }).click();
  const measures = await page.locator(".cmp-passage").evaluateAll((ps) =>
    ps.map((p) => {
      const probe = document.createElement("span");
      probe.style.font = getComputedStyle(p).font;
      probe.style.position = "absolute";
      probe.textContent = "0".repeat(75);
      document.body.append(probe);
      const cap = probe.getBoundingClientRect().width;
      probe.remove();
      return { width: p.getBoundingClientRect().width, cap, column: p.closest(".cmp-prose")!.getBoundingClientRect().width };
    }));
  expect(measures.length).toBeGreaterThan(0);
  expect(Math.min(...measures.map((m) => m.column))).toBeGreaterThan(Math.max(...measures.map((m) => m.cap)));
  for (const m of measures) expect(m.width).toBeLessThanOrEqual(m.cap + 1);
});

/* The phone form: one role per screen, beside a label column that stays. */
test("on a phone, each role fills the screen beside the labels and the cover snaps to it", async ({ page, isMobile }) => {
  test.skip(!isMobile, "the snap is the phone form; a wide screen shows every column at once");
  await page.goto("/");
  await selectThree(page);
  await page.goto("/compare");
  const scroller = page.locator(".compare-cover .cover-scroll");
  const heads = page.locator(".cmp-head");
  await expect(heads).toHaveCount(3);
  const view = (await scroller.boundingBox())!;
  const label = (await page.locator(".cmp-label").first().boundingBox())!;

  // One role on screen: the first head starts at the label column's edge and
  // ends at the screen's; the next one starts past it.
  const geometry = async () => Promise.all([0, 1, 2].map(async (i) => (await heads.nth(i).boundingBox())!));
  let [first, second] = await geometry();
  expect(Math.abs(first.x - (label.x + label.width))).toBeLessThan(1);
  expect(Math.abs(first.x + first.width - (view.x + view.width))).toBeLessThan(1);
  expect(second.x).toBeGreaterThanOrEqual(view.x + view.width - 1);
  expect(first.width).toBeGreaterThan(200);

  // A swipe that stops a third of the way lands on a whole column, never between.
  await scroller.evaluate((el) => el.scrollBy({ left: el.clientWidth * 0.7, behavior: "instant" }));
  await expect.poll(async () => {
    [, second] = await geometry();
    return Math.round(second.x - (label.x + label.width));
  }).toBe(0);

  // The label column stays where it was while the columns pass under it.
  const labelNow = (await page.locator(".cmp-label").first().boundingBox())!;
  expect(Math.abs(labelNow.x - label.x)).toBeLessThan(1);
  // A fact every role shares still says so on the second role.
  const same = page.locator(".cmp-same .cmp-span-body").first();
  const body = (await same.boundingBox())!;
  expect(body.x).toBeGreaterThan(label.x + label.width + 4);
  expect(body.x + body.width).toBeLessThanOrEqual(view.x + view.width + 1);
  await expect(same).toBeInViewport();

  // Deep in the descriptions, the heads stay at the top of the cover.
  await scroller.evaluate((el) => el.scrollBy({ top: el.scrollHeight, behavior: "instant" }));
  const pinned = (await heads.nth(1).boundingBox())!;
  const top = (await scroller.boundingBox())!.y;
  expect(Math.abs(pinned.y - top)).toBeLessThan(1);
  await expect(heads.nth(1).getByRole("button", { name: /Remove/ })).toBeInViewport();
});
