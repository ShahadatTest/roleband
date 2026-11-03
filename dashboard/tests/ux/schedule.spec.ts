/* The Orbit Clock: one dial, its marks, its stacks, and the exact-time control
   behind a mark. Preserved-but-native: its contract is the dial's behaviour
   rather than the design system's.

   The dial draws the schedule plan's runs, and the company marks are the
   times a user set; the harness pins OpenAI's and
   Anthropic's, so the editing contract below still holds companies. Every
   schedule route carries `?tz=`, so every pattern here allows a query. */

import { expect, test } from "./fixtures";
import { installSettingsRoutes, syncSchedule } from "./settingsHarness";

test.beforeEach(async ({ page }) => {
  await installSettingsRoutes(page);
});

test("Schedule draws the plan's runs on one clock and lists them beside it", async ({ page }) => {
  await page.goto("/settings/schedule");

  await expect(page.getByRole("tab", { name: "Schedule" })).toHaveAttribute("aria-selected", "true");
  const region = page.getByRole("region", { name: "Schedule" });
  await expect(region.getByRole("img", { name: /scan clock/i })).toBeVisible();

  // A quick scan on the inner orbit this afternoon, tomorrow's full scan on the
  // outer one when the computer comes on.
  const runs = region.locator('[data-testid="plan-run"]');
  await expect(runs).toHaveCount(2);
  await expect(runs.nth(0)).toHaveAttribute("data-kind", "quick");
  await expect(runs.nth(1)).toHaveAttribute("data-kind", "full");

  // Beside the dial: the plan's settings, its next runs, and the companies
  // that keep a time of their own folded into one line.
  const panel = region.getByRole("complementary", { name: "When scans run" });
  await expect(panel.getByLabel("Full scan done by")).toBeVisible();
  await expect(panel.getByText("Your computer is usually on")).toHaveCount(0);
  const next = panel.getByRole("list", { name: "Next scans" });
  await expect(next.getByText("Full scan · when you turn it on")).toBeVisible();
  await expect(next.getByText("1,112 companies · 41 min")).toBeVisible();
  await panel.getByRole("button", { name: "2 companies keep a time you set" }).click();
  const pinned = panel.getByRole("list", { name: "Times you set" });
  await expect(pinned.getByText("OpenAI", { exact: true })).toBeVisible();
  await expect(pinned.getByText("Anthropic", { exact: true })).toBeVisible();
  // No timer burst under the plan: the planned full scan is the cycle.
  await expect(region.locator('[data-testid="reconciliation-window"]')).toHaveCount(0);
  await expect(region.getByText(/Meta: its site doesn't allow scheduled scans/))
    .toBeVisible();

  await expect(panel.getByText(/your computer is on 09:00 to 18:00 on weekdays/)).toBeVisible();
  await expect(panel.getByRole("button", { name: "6h" })).toHaveAttribute("aria-pressed", "true");
  await expect(region.getByLabel("Scheduler policy")).toHaveCount(0);

  await region.getByRole("button", { name: "Every company's scans" }).click();
  const sheet = page.getByRole("dialog", { name: "Every company's scans" });
  await expect(sheet.getByText("Policy denied")).toBeVisible();
  await expect(sheet.getByText("Its own time: full scan at 20:00")).toBeVisible();
});

test("pausing and choosing days are saved, and the dial says it is paused", async ({ page }) => {
  const writes: unknown[] = [];
  const paused = {
    ...syncSchedule,
    plan: { ...syncSchedule.plan, paused_until: "2026-07-28T17:30:00Z", waiting: "paused" },
  };
  await page.route("/api/schedule/plan?**", async (route) => {
    const body = route.request().postDataJSON();
    writes.push(body);
    await route.fulfill({ json: body.pause ? paused : { ...syncSchedule, plan: { ...syncSchedule.plan, days: body.days } } });
  });
  await page.goto("/settings/schedule");
  const panel = page.getByRole("region", { name: "Schedule" })
    .getByRole("complementary", { name: "When scans run" });

  await panel.getByRole("group", { name: "Scan days" }).getByRole("button", { name: "Sun" }).click();
  await expect.poll(() => writes.length).toBe(1);
  expect(writes[0]).toEqual({ days: [0, 1, 2, 3, 4, 5] });
  await expect(panel.getByText("6 days a week")).toBeVisible();

  await panel.getByRole("group", { name: "Pause scans" }).getByRole("button", { name: "Until tomorrow" }).click();
  await expect.poll(() => writes.length).toBe(2);
  expect(writes[1]).toEqual({ pause: "tomorrow" });
  await expect(panel.getByText(/Paused until/)).toBeVisible();
  await expect(panel.getByRole("button", { name: "Resume" })).toBeVisible();
});

/* The plan's runs are the marks under the plan, with the dial's drag-and-drop
   and its click-for-the-number. A real mouse drag, because pointer capture is
   what keeps it alive past the 18px mark. */
test("dragging a quick scan moves the quick scans, and a click shows a scan's numbers", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name === "mobile", "drag path is desktop; mobile edits via the inspector");
  const writes: Array<Record<string, unknown>> = [];
  await page.route("/api/schedule/plan?**", async (route) => {
    writes.push(route.request().postDataJSON());
    await route.fulfill({ json: syncSchedule });
  });
  await page.goto("/settings/schedule");

  const quick = page.getByRole("button", { name: /^Move quick scan, at \d{2}:\d{2}$/ });
  const box = await quick.boundingBox();
  expect(box).not.toBeNull();
  if (!box) return;
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
  await page.mouse.down();
  await page.mouse.move(box.x + 60, box.y + 90, { steps: 8 });
  await page.mouse.up();
  await expect.poll(() => writes.length).toBe(1);
  expect(Object.keys(writes[0])).toEqual(["repeat_anchor_minute"]);
  expect(Number(writes[0].repeat_anchor_minute) % 10).toBe(0);
  expect(await page.evaluate(() => String(getSelection()))).toBe("");

  await page.getByRole("button", { name: /^Move full scan/ }).click();
  const inspector = page.getByRole("dialog", { name: "Scan inspector" });
  await expect(inspector.getByText("1,112")).toBeVisible();
  await expect(inspector.getByLabel("Full scan done by")).toBeVisible();
});

/* Smoothness, measured in the browser: the drag must not jump or lag a
   frame behind. Walking the pointer along the inner orbit, the dragged quick scan must sit under it after every frame: within a
   few pixels, never snapped 10 minutes away and never flicked back to its old
   place. */
test("a dragged scan stays under the pointer along the orbit", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name === "mobile", "drag path is desktop");
  await page.route("/api/schedule/plan?**", (route) => route.fulfill({ json: syncSchedule }));
  await page.goto("/settings/schedule");
  const stage = await page.locator(".schedule-clock-stage").boundingBox();
  const handle = page.getByRole("button", { name: /^Move quick scan, at/ });
  const start = await handle.boundingBox();
  expect(stage && start).toBeTruthy();
  if (!stage || !start) return;
  const cx = stage.x + stage.width / 2;
  const cy = stage.y + stage.height / 2;
  const radius = Math.hypot(start.x + start.width / 2 - cx, start.y + start.height / 2 - cy);
  const angle0 = Math.atan2(start.x + start.width / 2 - cx, -(start.y + start.height / 2 - cy));

  await page.mouse.move(start.x + start.width / 2, start.y + start.height / 2);
  await page.mouse.down();
  const misses: number[] = [];
  for (let step = 1; step <= 12; step += 1) {
    const angle = angle0 + step * 0.05; // ~11.5 minutes a step, off the 10-minute grid
    const x = cx + radius * Math.sin(angle);
    const y = cy - radius * Math.cos(angle);
    await page.mouse.move(x, y);
    await page.evaluate(() => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve))));
    const box = await handle.boundingBox();
    if (box) misses.push(Math.round(Math.hypot(box.x + box.width / 2 - x, box.y + box.height / 2 - y)));
  }
  await page.mouse.up();
  expect(misses.length).toBe(12);
  expect(Math.max(...misses), `pixels off the pointer per frame: ${misses.join(", ")}`).toBeLessThanOrEqual(8);
});

test("the whole clock fits the window it opens in, close under its title", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name === "mobile", "the stacked layout keeps the band above the ring");
  // 1730x842 is a 2000px-wide screen at 115% zoom, where the ring's foot can
  // fall below the fold under an empty band; 1366x720 is a short laptop.
  for (const viewport of [{ width: 1730, height: 842 }, { width: 1366, height: 720 }]) {
    await page.setViewportSize(viewport);
    await page.goto("/settings/schedule");
    const region = page.getByRole("region", { name: "Schedule" });
    await expect(region.locator('[data-testid="plan-run"]').first()).toBeVisible();
    const geometry = await page.evaluate(() => {
      const ticks = [...document.querySelectorAll(".dial-tick")].map((tick) => tick.getBoundingClientRect());
      const title = [...document.querySelectorAll("h2")].find((h) => h.textContent === "Scan clock");
      const plan = document.querySelector('aside[aria-label="When scans run"]');
      return {
        ringTop: Math.min(...ticks.map((box) => box.top)),
        ringBottom: Math.max(...ticks.map((box) => box.bottom)),
        titleBottom: title?.getBoundingClientRect().bottom ?? Number.NaN,
        planTop: plan?.getBoundingClientRect().top ?? Number.NaN,
      };
    });
    const size = `${viewport.width}x${viewport.height}`;
    expect(geometry.ringBottom, `ring's foot at ${size}`).toBeLessThanOrEqual(viewport.height);
    expect(geometry.ringTop - geometry.titleBottom, `title to ring at ${size}`).toBeLessThanOrEqual(32);
    expect(Math.abs(geometry.planTop - geometry.ringTop), `plan column vs ring at ${size}`).toBeLessThanOrEqual(4);
  }
});

test("choosing how often it repeats is saved and the clock redraws from the answer", async ({ page }) => {
  const writes: Array<{ url: string; body: unknown }> = [];
  const threeHourly = {
    ...syncSchedule,
    plan: {
      ...syncSchedule.plan,
      repeat_hours: 3,
      upcoming: [
        { at: "2026-07-28T15:00:00Z", kind: "quick", seconds: 600, estimated: false, on_wake: false, running: false, ready_by: false },
        { at: "2026-07-28T18:00:00Z", kind: "quick", seconds: 600, estimated: false, on_wake: false, running: false, ready_by: false },
        { at: "2026-07-29T09:00:00Z", kind: "full", seconds: 2460, estimated: false, on_wake: true, running: false, ready_by: false },
      ],
    },
  };
  await page.route("/api/schedule/plan?**", async (route) => {
    writes.push({ url: route.request().url(), body: route.request().postDataJSON() });
    await route.fulfill({ json: threeHourly });
  });
  await page.goto("/settings/schedule");
  const region = page.getByRole("region", { name: "Schedule" });
  await expect(region.locator('[data-testid="plan-run"]')).toHaveCount(2);

  await region.getByRole("group", { name: "Quick scan every" }).getByRole("button", { name: "3h" }).click();

  await expect.poll(() => writes.length).toBe(1);
  expect(writes[0].body).toEqual({ repeat_hours: 3 });
  expect(writes[0].url).toMatch(/\/api\/schedule\/plan\?tz=/);
  await expect(region.locator('[data-testid="plan-run"]')).toHaveCount(3);
  await expect(region.getByText("a quick scan every 3 hours")).toBeVisible();
});

test("Orbit Clock direct controls persist a company schedule time", async ({ page }, testInfo) => {
  let update: { url: string; body: Record<string, unknown> } | undefined;
  await page.route("/api/schedule/*?**", async (route) => {
    update = {
      url: route.request().url(),
      body: route.request().postDataJSON(),
    };
    await route.fulfill({ json: syncSchedule });
  });
  await page.goto("/settings/schedule");

  if (testInfo.project.name === "mobile") {
    await page.getByRole("button", { name: /Move OpenAI full scan/i }).click();
    const exactTime = page.getByLabel("OpenAI full scan time");
    await expect(exactTime).toBeVisible();
    await exactTime.fill("20:30");
    // The field commits when the edit is finished, not while it is being made.
    await exactTime.blur();
  } else {
    const handle = page.getByRole("button", {
      name: /Move OpenAI full scan/i,
    });
    await expect(handle).toBeVisible();
    const box = await handle.boundingBox();
    expect(box).not.toBeNull();
    if (!box) return;

    await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
    await page.mouse.down();
    await page.mouse.move(box.x + 80, box.y - 40, { steps: 8 });
    await page.mouse.up();
  }

  await expect.poll(() => update).toBeTruthy();
  expect(update?.url).toMatch(/\/api\/schedule\/1\?tz=/);
  expect(update?.body).toMatchObject({
    mode: "reconcile",
    timezone: expect.any(String),
  });
  if (testInfo.project.name === "mobile") {
    expect(update?.body.local_minute).toBe(20 * 60 + 30);
  } else {
    expect(Number(update?.body.local_minute) % 10).toBe(0);
  }
});

/* The test above sets the field with `fill()`, which writes the whole value in
   one shot — the one way to edit a time input that never passes through an
   intermediate state. Typing does, and that is the path the dial advertises
   ("click it for an exact time").

   A time input fires `change` for every segment edit that leaves the value
   complete, so committing on `change` persists the first keystroke of the
   edit. Chrome renders the instant in a 12-hour presentation ("08:00 PM" at
   UTC), so a single "1" typed into the hour is already a complete "01:00 PM":
   13:00 would reach the server, a time the user never asked for and never
   sees, because the controlled value re-renders straight back to the
   persisted time. The save then disables the field, focus drops, and the
   remaining keystrokes go nowhere. */
/* These tests read an ABSOLUTE local clock time off the screen and type into
   a segmented control, so they depend on where the machine is and what
   language it speaks. Both are pinned rather than inherited: the fixture's
   reconciliation is a UTC INSTANT and the dial renders it in local time
   (22:00 at UTC+2, 20:00 at UTC), and "type 0230PM" only reaches 14:30
   through an AM/PM field, which exists in the en-US presentation and not in
   a 24-hour one. UTC makes the expectation below a property of the fixture
   rather than of a desk. */
test.describe("the typed exact-time control", () => {
  test.use({ timezoneId: "UTC", locale: "en-US" });

  test("the exact-time field commits the time typed, once, and no keystroke of it",
  async ({ page }, testInfo) => {
    test.skip(
      testInfo.project.name === "mobile",
      "The segmented, typed time editor is a desktop control; the mobile engine renders a picker.",
    );
    const writes: Array<Record<string, unknown>> = [];
    await page.route("/api/schedule/*?**", async (route) => {
      writes.push(route.request().postDataJSON());
      await route.fulfill({ json: syncSchedule });
    });
    await page.goto("/settings/schedule");

    await page.getByRole("button", { name: /Move OpenAI full scan/i }).click();
    const exactTime = page.getByLabel("OpenAI full scan time");
    await expect(exactTime).toBeVisible();
    await expect(exactTime).toHaveValue("20:00");

    await exactTime.click();
    await page.keyboard.type("0230PM");

    // Mid-edit the field holds what was typed and the caret has not been taken
    // away, or the edit cannot be finished. Nothing is written yet.
    await expect(exactTime).toHaveValue("14:30");
    await expect(exactTime).toBeFocused();
    expect(writes).toEqual([]);

    // Enter commits without giving up the caret, and commits exactly once.
    await page.keyboard.press("Enter");
    await expect.poll(() => writes.length).toBe(1);
    expect(writes[0]).toMatchObject({ mode: "reconcile", local_minute: 14 * 60 + 30 });
    await expect(exactTime).toBeFocused();

    // Leaving a field nobody edited is not a reschedule.
    await exactTime.blur();
    await page.waitForTimeout(200);
    expect(writes).toHaveLength(1);
  });

/* Abandoning an edit needs no key of its own — the field has no Escape handler
   of its own to hold, and the ratchet would count one if it did. Closing the
   inspector unmounts the field, and React fires no blur on unmount, so the
   pending value goes with it. That is the discard path, so it is tested rather
   than assumed. */
test("closing the inspector discards a time that was typed but never committed",
  async ({ page }, testInfo) => {
    test.skip(
      testInfo.project.name === "mobile",
      "The segmented, typed time editor is a desktop control; the mobile engine renders a picker.",
    );
    const writes: Array<Record<string, unknown>> = [];
    await page.route("/api/schedule/*?**", async (route) => {
      writes.push(route.request().postDataJSON());
      await route.fulfill({ json: syncSchedule });
    });
    await page.goto("/settings/schedule");

    await page.getByRole("button", { name: /Move OpenAI full scan/i }).click();
    const exactTime = page.getByLabel("OpenAI full scan time");
    await exactTime.click();
    await page.keyboard.type("0230PM");
    await expect(exactTime).toHaveValue("14:30");

    await page.keyboard.press("Escape");
    await expect(exactTime).toBeHidden();
    await page.waitForTimeout(200);
    expect(writes).toEqual([]);

    // And the mark still reads the persisted time, not the abandoned one.
    await expect(page.getByRole("button", {
      name: /Move OpenAI full scan, currently 20:00/i,
    })).toBeVisible();
  });
});

// Two pinned full scans on one tick, so the dial draws them as a single
// stack (under the plan, "2 full scans").
// Members order by company, which puts Anthropic (binding 2) at the head.
const stackedSchedule = {
  ...syncSchedule,
  bindings: syncSchedule.bindings.map((binding) => binding.binding_id === 2
    ? {
      ...binding,
      next_reconcile_at: "2026-07-28T20:00:00Z",
      eligible_reconcile_at: "2026-07-28T20:00:00Z",
    }
    : binding),
};

// The per-company timers are still the dial when the plan is switched off
// (`sync_schedule_plan_enabled`), and their burst is still drawn as a band.
const timerSchedule = { ...stackedSchedule, plan: { ...syncSchedule.plan, enabled: false } };

test("under the timers the cycle band is drawn once the burst outgrows its own marks", async ({ page }) => {
  await page.route("/api/schedule?**", (route) => route.fulfill({ json: timerSchedule }));
  await page.goto("/settings/schedule");
  const region = page.getByRole("region", { name: "Schedule" });

  // Two concentric arcs — a segment of the orbit, so it keeps the dial's
  // curvature rather than cutting a chord across it — closed at each end by a
  // half-round of the band's own half-thickness (2.75) instead of a flat
  // radial cut. Large-arc-flag 0 on the two long arcs: the window must span
  // under half the dial; spanning to the last deadline instead of the burst
  // paints a ~24h ring.
  await expect(region.locator('[data-testid="reconciliation-window"] .dial-window'))
    .toHaveAttribute(
      "d",
      /^M [\d.]+ [\d.]+ A 218\.75 218\.75 0 0 1 [\d.]+ [\d.]+ A 2\.75 2\.75 0 0 1 [\d.]+ [\d.]+ A 213\.25 213\.25 0 0 0 [\d.]+ [\d.]+ A 2\.75 2\.75 0 0 1 [\d.]+ [\d.]+ Z$/,
    );
  // No radial lead tick across the bright end: the gradient alone carries
  // "certain at the start".
  await expect(region.locator('[data-testid="reconciliation-window"] .dial-window-lead'))
    .toHaveCount(0);
  await expect(region.getByRole("complementary", { name: /Upcoming scans/i })
    .getByText(/2 scans · projected through/i)).toBeVisible();
  await expect(region.getByLabel("Schedule clock legend")
    .getByText("Full scan window")).toBeVisible();
});

test("a stack opens as one combined view of the companies sharing the tick", async ({ page }) => {
  await page.route("/api/schedule?**", (route) => route.fulfill({ json: stackedSchedule }));
  await page.goto("/settings/schedule");

  // Under the plan a stack of pinned full scans says so in the plan's words.
  await page.getByRole("button", { name: /2 full scans at .*open to see all/i }).click();

  const inspector = page.getByRole("dialog", { name: /scan schedule inspector/i });
  await expect(inspector).toContainText(/2 share \d{2}:\d{2}/);
  await expect(inspector.getByText("Anthropic", { exact: true })).toBeVisible();
  await expect(inspector.getByText("OpenAI", { exact: true })).toBeVisible();
  // Both are settable from here — the stack is not a dead end.
  await expect(inspector.getByLabel("Anthropic full scan time")).toBeEnabled();
  await expect(inspector.getByLabel("OpenAI full scan time")).toBeEnabled();
});

test("dragging a stack peels off exactly one connector", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name === "mobile", "drag path is desktop; mobile edits via the inspector");
  const updates: string[] = [];
  await page.route("/api/schedule?**", (route) => route.fulfill({ json: stackedSchedule }));
  await page.route("/api/schedule/*?**", async (route) => {
    updates.push(route.request().url());
    await route.fulfill({ json: stackedSchedule });
  });
  await page.goto("/settings/schedule");

  const stack = page.getByRole("button", {
    name: /2 full scans at .*drag to move Anthropic out/i,
  });
  const box = await stack.boundingBox();
  expect(box).not.toBeNull();
  if (!box) return;
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
  await page.mouse.down();
  await page.mouse.move(box.x + 90, box.y + 60, { steps: 8 });
  await page.mouse.up();

  // One drag, one connector: the lead moves and the rest of the stack does not.
  await expect.poll(() => updates.length).toBe(1);
  expect(updates[0]).toMatch(/\/api\/schedule\/2\?tz=/);
  // A drag that starts on a mark must not leave a highlight behind either.
  expect(await page.evaluate(() => String(getSelection()))).toBe("");
});

test("clicking a mark opens the exact-time control the dial promises", async ({ page }) => {
  await page.goto("/settings/schedule");

  // The readout tells the user to click a mark for an exact time. Cancelling
  // pointerdown to stop text selection would eat that click on desktop.
  await page.getByRole("button", { name: /Move OpenAI full scan/i }).click();
  await expect(page.getByLabel("OpenAI full scan time")).toBeVisible();
});

test("the clock resists text selection while the agenda beside it stays copyable", async ({ page }) => {
  await page.goto("/settings/schedule");

  // A drag that misses a mark must not highlight the dial's numerals/labels.
  const dial = page.locator(".schedule-clock-main");
  const box = await dial.boundingBox();
  expect(box).not.toBeNull();
  if (!box) return;
  await page.mouse.move(box.x + 12, box.y + 12);
  await page.mouse.down();
  await page.mouse.move(box.x + box.width - 12, box.y + box.height - 12, { steps: 10 });
  await page.mouse.up();
  expect(await page.evaluate(() => String(getSelection()))).toBe("");

  // Selection is only suppressed on the dial: the agenda is ordinary text.
  await page.getByRole("list", { name: "Next scans" })
    .getByText("1,112 companies · 41 min").click({ clickCount: 3 });
  expect(await page.evaluate(() => String(getSelection()))).toContain("1,112 companies");
});
