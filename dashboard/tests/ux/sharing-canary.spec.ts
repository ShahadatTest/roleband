import { gunzipSync } from "node:zlib";
import { expect, test } from "./fixtures";
import type { Page } from "./fixtures";
import type { Request } from "@playwright/test";
import {
  facetsFixture, jobFixture, notificationsFixture, statsFixture, statusFixture, usageStateFixture,
} from "../../src/test/fixtures";
import type { JobList } from "../../src/api";

/* The main browser-side guard of usage sharing (docs/architecture.md):
   with EVERY kind shared, PostHog's real library runs over a board full of
   canary data (an employer, a title, a city, a search typed into the box, an
   error naming an address), and every request it makes is caught and decoded.
   None may carry a canary, and no session replay leaves at all: RoleBand
   records no sessions even when the PostHog project says replay is on.

   Proof of life alongside: page views and the error were sent, so a green run
   is not a library that never started. */

const COMPANY = "zyxwv-robotics";
const CANARIES = ["Zyxwv", "zyxwv", "Qwertyville", "Gloriously Secret Platform", "ada-private-search"];

const canaryJobs: JobList = {
  total: 2,
  limit: 25,
  offset: 0,
  items: [
    { ...jobFixture, id: 9101, company: COMPANY, title: "Principal Gloriously Secret Platform PM", locations: ["Qwertyville, CA"] },
    { ...jobFixture, id: 9102, company: COMPANY, title: "Director, Zyxwv Robotics Payments", locations: ["Qwertyville, CA"] },
  ],
};

/** Replay events carry their DOM as gzipped strings inside the JSON: unpack
 *  every one, so a canary cannot hide in a compressed snapshot. */
function unpackSnapshots(value: unknown): unknown {
  if (typeof value === "string" && value.charCodeAt(0) === 0x1f && value.charCodeAt(1) === 0x8b) {
    try {
      return unpackSnapshots(JSON.parse(gunzipSync(Buffer.from(value, "latin1")).toString("utf8")));
    } catch {
      return value;
    }
  }
  if (Array.isArray(value)) return value.map(unpackSnapshots);
  if (value && typeof value === "object") {
    return Object.fromEntries(Object.entries(value).map(([key, inner]) => [key, unpackSnapshots(inner)]));
  }
  return value;
}

function decode(request: Request): string {
  const buffer = request.postDataBuffer();
  if (!buffer) return request.url();
  let text = buffer[0] === 0x1f && buffer[1] === 0x8b ? gunzipSync(buffer).toString("utf8") : buffer.toString("utf8");
  if (text.startsWith("data=")) {
    text = Buffer.from(decodeURIComponent(text.slice(5)), "base64").toString("utf8");
  }
  try {
    text = JSON.stringify(unpackSnapshots(JSON.parse(text)));
  } catch {
    /* not JSON: searched as it came */
  }
  return `${request.url()}\n${text}`;
}

async function posthogServer(page: Page) {
  const sent: string[] = [];
  // Every PostHog host: events go to eu.i.posthog.com, the project's config to
  // eu-assets.i.posthog.com. Nothing reaches the real service.
  await page.route(/^https:\/\/[^/]*posthog\.com\//, async (route) => {
    sent.push(decode(route.request()));
    // Answer as a project with replay switched on would: the app's own config
    // must keep the library from recording anyway.
    const enabled = { sessionRecording: { endpoint: "/s/" }, supportedCompression: ["gzip-js"], featureFlags: {} };
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ status: 1, ...enabled }) });
  });
  return sent;
}

/* PostHog's library drops events from a browser it takes for a bot, and a
   headless Chrome says so in its user agent. The app keeps that filter; the
   spec presents itself as the desktop Chrome a user runs. */
test.use({
  userAgent:
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
});

test.beforeEach(async ({ page }) => {
  await page.route("/api/**", async (route) => {
    await route.abort("blockedbyclient");
    throw new Error(`Unmocked sharing-canary API request: ${route.request().method()} ${route.request().url()}`);
  });
  await page.route("/api/companies/names", (route) => route.fulfill({ json: { names: { [COMPANY]: "Zyxwv Robotics" } } }));
  await page.route("/api/compare-selection", (route) => route.fulfill({ json: { job_ids: [] } }));
  await page.route("/api/settings/locale", (route) => route.fulfill({ json: { language: "en", region: null } }));
  await page.route("/api/stats", (route) => route.fulfill({ json: statsFixture }));
  await page.route("/api/status", (route) => route.fulfill({ json: statusFixture }));
  await page.route("/api/companies/directory/status", (route) => route.fulfill({ json: { size: 0, following: false, since: null, checked: 0, to_check: 0, with_roles: 0, waiting_for_power: false } }));
  await page.route("/api/facets", (route) => route.fulfill({ json: facetsFixture }));
  await page.route("/api/notifications**", (route) => route.fulfill({ json: notificationsFixture }));
  await page.route("/api/jobs?**", (route) => route.fulfill({ json: canaryJobs }));
  await page.route("/api/profile", (route) => route.fulfill({ json: { profile: null, scope_configured: true, intent_statement: "" } }));
  await page.route("/api/usage", (route) => route.fulfill({
    json: usageStateFixture("shared", { project_key: "phc_test", host: "https://eu.i.posthog.com" }),
  }));
});

test("with everything shared, nothing the user sees or types leaves", async ({ page }) => {
  test.slow();
  // The bot check also reads `navigator.webdriver` and the HeadlessChrome brand
  // in `navigator.userAgentData`, both of which automation sets.
  await page.addInitScript(() => {
    Object.defineProperty(navigator, "webdriver", { get: () => false });
    Object.defineProperty(navigator, "userAgentData", {
      get: () => ({ brands: [{ brand: "Google Chrome", version: "129" }], mobile: false, platform: "macOS" }),
    });
  });
  const sent = await posthogServer(page);
  const elsewhere: string[] = [];
  page.on("request", (request) => {
    const url = new URL(request.url());
    if (url.hostname !== "127.0.0.1" && url.hostname !== "localhost" && !/^eu(-assets)?\.i\.posthog\.com$/.test(url.hostname)) {
      elsewhere.push(request.url());
    }
  });

  // The session starts on an address that names the employer: the library
  // copies a session's first address into every later event.
  await page.goto(`/?company=${COMPANY}`);
  await expect(page.getByText("Principal Gloriously Secret Platform PM")).toBeVisible();
  // The SDK loads separately from the board. Every privacy probe must run
  // after capture starts, or a missing listener can look like safe redaction.
  await expect.poll(() => sent.join("\n"), { timeout: 30_000 }).toContain("$pageview");
  const search = page.getByRole("searchbox").first();
  if (await search.count()) await search.fill("ada-private-search for Zyxwv");
  await page.getByText("Director, Zyxwv Robotics Payments").hover();
  // A click autocapture records, on something that opens nothing.
  await page.getByRole("heading").first().click();
  await page.evaluate(() => {
    setTimeout(() => {
      throw new Error("Could not open https://boards.example.com/zyxwv-robotics for 'Zyxwv Robotics'");
    });
  });

  // Proof of life: the injected error reached the capture path too.
  await expect.poll(() => sent.join("\n"), { timeout: 30_000 }).toContain("$exception");

  const all = sent.join("\n");
  // No session recording, though the project answered that replay is on.
  expect(all).not.toContain("$snapshot");
  expect(sent.filter((request) => new URL(request.split("\n")[0]).pathname.startsWith("/s/"))).toEqual([]);
  for (const canary of CANARIES) {
    const at = all.indexOf(canary);
    expect(at, `${canary} left the machine: ...${all.slice(Math.max(0, at - 300), at + 120)}...`).toBe(-1);
  }
  expect(all).not.toContain("/jobs/9101");
  expect(elsewhere).toEqual([]);
});

test("with nothing shared, PostHog's library is never loaded and nothing is sent", async ({ page }) => {
  const sent = await posthogServer(page);
  await page.route("/api/usage", (route) => route.fulfill({ json: usageStateFixture("declined") }));
  const chunks: string[] = [];
  page.on("request", (request) => {
    if (request.url().includes("module.full.no-external")) chunks.push(request.url());
  });
  await page.goto("/");
  await expect(page.getByText("Principal Gloriously Secret Platform PM")).toBeVisible();
  await page.waitForTimeout(1500);
  expect(chunks).toEqual([]);
  expect(sent).toEqual([]);
});
