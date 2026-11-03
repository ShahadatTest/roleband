/* The curated list.

   A user starts on the curated list; the toolbar's Follow all, beside the
   count it acts on, widens it to every company listed in the sectors — after
   asking, because following many companies at once changes the radar and
   every scan. Curated list only is the way back. The harness has Google and
   Apple curated, eleven other scannable companies, and a planned (Snowflake)
   and a parked (Tesla) company neither action may touch. */

import { expect, test } from "./fixtures";
import { companyDiscovery, installSettingsRoutes } from "./settingsHarness";

const OTHERS = [
  "nvidia", "datadog", "github", "gitlab", "hashicorp", "mongodb", "confluent", "vercel", "docker",
  "elastic", "grafana",
];

test.beforeEach(async ({ page }) => {
  await installSettingsRoutes(page);
});

async function recordSelection(page: import("@playwright/test").Page) {
  // Each entry is what is followed once a write has landed.
  const writes: string[][] = [];
  const followed = new Set(companyDiscovery.companies.filter((c) => c.enabled).map((c) => c.slug));
  await page.route("/api/companies/selection", async (route) => {
    const write = route.request().postDataJSON();
    for (const slug of write.follow) followed.add(slug);
    for (const slug of write.unfollow) followed.delete(slug);
    const enabled = [...followed];
    writes.push(enabled);
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
  return writes;
}

test("Follow all sits in the toolbar and asks before following every listed company", async ({ page }) => {
  const writes = await recordSelection(page);
  await page.goto("/settings/companies");

  await expect(page.getByRole("checkbox", { name: /Include other companies/ })).toHaveCount(0);
  const followAll = page.getByRole("button", { name: "Follow all", exact: true });
  // In the toolbar with the count it acts on, above the list: never the
  // end-of-list place where companies not on it are added.
  const index = await page.getByRole("navigation", { name: "Sectors" }).boundingBox();
  const act = await followAll.boundingBox();
  expect(index && act).toBeTruthy();
  expect(act!.y + act!.height).toBeLessThanOrEqual(index!.y);

  await followAll.click();
  // Apple is curated but unfollowed in this harness: all means all.
  const ask = page.getByRole("dialog", { name: "Follow the whole list?" });
  await expect(ask).toBeVisible();
  await expect(ask.locator("p")).toHaveText([
    "Your radar starts with a curated list of well-known companies, so your first roles come from employers you know.",
    "More companies bring more roles, and each scan takes longer.",
    "You can unfollow any company in Settings › Followed companies.",
  ]);
  // No paragraph ends on a word alone on its line.
  const lastLines = await ask.locator("p").evaluateAll((paragraphs) => paragraphs.map((p) => {
    const words: { top: number; word: string }[] = [];
    const texts = document.createTreeWalker(p, NodeFilter.SHOW_TEXT);
    for (let text = texts.nextNode(); text; text = texts.nextNode()) {
      for (const match of (text.textContent ?? "").matchAll(/\S+/g)) {
        const range = document.createRange();
        range.setStart(text, match.index);
        range.setEnd(text, match.index + match[0].length);
        words.push({ top: Math.round(range.getBoundingClientRect().top), word: match[0] });
      }
    }
    const last = words[words.length - 1].top;
    return words.filter((entry) => entry.top === last).map((entry) => entry.word).join(" ");
  }));
  for (const line of lastLines) expect(line.split(" ").length, line).toBeGreaterThan(1);
  // A settings path and a hyphenated word each stay on one line, at a phone's width too.
  for (const width of [1280, 390]) {
    await page.setViewportSize({ width, height: 844 });
    for (const name of ["Settings › Followed companies", "well-known"]) {
      const lines = await ask.getByText(name, { exact: true }).evaluate((node) => node.getClientRects().length);
      expect(lines, `${name} at ${width}`).toBe(1);
    }
  }
  await page.setViewportSize({ width: 1280, height: 720 });
  const keep = ask.getByRole("button", { name: "Keep curated list" });
  await expect(keep).toBeFocused();

  // Enter on the freshly opened dialog is the safe answer.
  await page.keyboard.press("Enter");
  await expect(ask).toBeHidden();
  expect(writes).toEqual([]);

  await followAll.click();
  await ask.getByRole("button", { name: "Follow all 12" }).click();
  await expect.poll(() => writes.length).toBe(1);
  expect([...writes[0]].sort()).toEqual(["apple", "google", ...OTHERS].sort());
  await expect(page.getByText("Following 12 more companies.")).toBeVisible();
  // Everything listed is followed: the same place now offers the way back.
  await expect(page.getByRole("button", { name: "Curated list only" })).toBeVisible();
  await expect(followAll).toHaveCount(0);
});

test("a sector's Follow all asks when it adds several companies", async ({ page }) => {
  const writes = await recordSelection(page);
  await page.goto("/settings/companies");

  await page.getByRole("button", { name: "Follow all Cloud, data & devtools companies" }).click();
  const ask = page.getByRole("dialog", { name: "Follow all 10 companies in Cloud, data & devtools?" });
  await expect(ask).toBeVisible();
  await ask.getByRole("button", { name: "Cancel" }).click();
  await expect(ask).toBeHidden();
  expect(writes).toEqual([]);
});

test("at phone width, Follow all stays in reach and the two ways to add stack", async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 });
  await page.route("/api/companies/directory/status", (route) => route.fulfill({
    json: { size: 10214, following: false, since: null, checked: 0, to_check: 10214, with_roles: 0, waiting_for_power: false },
  }));
  await page.goto("/settings/companies");

  await expect(page.getByRole("button", { name: "Follow all", exact: true })).toBeVisible();
  const addMore = page.getByRole("region", { name: "Add more companies" });
  await addMore.scrollIntoViewIfNeeded();
  const set = await addMore.getByRole("group", { name: "The wider market" }).boundingBox();
  const link = await addMore.getByRole("button", { name: "Add by link" }).boundingBox();
  expect(set && link).toBeTruthy();
  expect(link!.y).toBeGreaterThan(set!.y + set!.height - 1);
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow).toBeLessThanOrEqual(0);
});
