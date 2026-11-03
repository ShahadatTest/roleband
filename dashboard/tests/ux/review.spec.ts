import { expect, test } from "./fixtures";
import {
  duplicateProposalFixture,
  duplicateVerdictFixture,
  facetsFixture,
  jobDetailFixture,
  jobDetailRowFixture,
  jobListFixture,
  notificationsFixture,
  relationshipAssessmentFixture,
  statsFixture,
  statusFixture,
} from "../../src/test/fixtures";

const longSharedDescription = Array.from(
  { length: 48 },
  (_, index) => `- Shared responsibility ${index + 1}`,
).join("\n");

test.beforeEach(async ({ page }) => {
  await page.route("/api/stats", (route) => route.fulfill({ json: statsFixture }));
  await page.route("/api/status", (route) => route.fulfill({ json: statusFixture }));
  await page.route("/api/facets", (route) => route.fulfill({ json: facetsFixture }));
  await page.route("/api/notifications**", (route) => route.fulfill({ json: notificationsFixture }));
  await page.route("/api/jobs?**", (route) => route.fulfill({ json: jobListFixture }));
  await page.route("/api/twins/review?**", (route) =>
    route.fulfill({ json: { total: 0, limit: 50, offset: 0, items: [] } }),
  );
  await page.route("/api/lineage/review?**", (route) => {
    const history = new URL(route.request().url()).searchParams.get("status") === "reviewed";
    return route.fulfill({ json: history ? {
      total: 1, limit: 20, offset: 0, items: [{
        link: duplicateProposalFixture({ id: 6, job_id: 100, prior_job_id: 99, relation: "duplicate", method: "title+embedding", status: "rejected", score: 0.972, gap_days: 0, decision: "different", reviewed_at: "2026-07-15T15:00:00Z" }),
        prior: jobDetailRowFixture({ id: 99, req_id: "REQ-OLD", title: "Staff Software Engineer, Platform", url: "https://example.test/jobs/99" }),
        job: jobDetailRowFixture({ id: 100, req_id: "REQ-NEW", title: "Staff Software Engineer, Payments", url: "https://example.test/jobs/100" }),
        diff: { title: { from: "Staff Software Engineer, Platform", to: "Staff Software Engineer, Payments" } },
      }],
    } : {
      total: 1,
      limit: 50,
      offset: 0,
      items: [{
        link: duplicateProposalFixture({
          id: 7, job_id: 102, prior_job_id: 101, relation: "duplicate", score: 0.94, gap_days: 0,
          reasons: ["concurrent identical-title postings"],
        }),
        prior: jobDetailRowFixture({
          id: 101, req_id: "REQ-A", title: "Staff Software Engineer", url: "https://example.test/jobs/101",
          description_sections: [{ key: "qualifications", title: "Qualifications", content: `${longSharedDescription}\n- Five years of platform experience` }],
        }),
        job: jobDetailRowFixture({
          id: 102, req_id: "REQ-B", title: "Staff Software Engineer", url: "https://example.test/jobs/102",
          description_sections: [{ key: "qualifications", title: "Qualifications", content: `${longSharedDescription}\n- Experience with platform systems` }],
        }),
        diff: {},
      }],
    }});
  });
});

/* The number the reviewer reads is the BACKLOG, not the page.
 *
 * The queue asks each endpoint for one page of rows. Counting what came back
 * states the page as the backlog, and it never moves: a verdict drops it by
 * one only for the reload to fetch another full page and put it back. This
 * fixture is a small page in front of a large set, the only arrangement that
 * can tell the two numbers apart.
 *
 * The rail is asserted in the same test on purpose. Its badge comes from
 * `/api/stats`, a different query against the same two tables, so the screen
 * and the chrome are two independent statements of one fact and the defect
 * class to guard is them disagreeing. */
test("the queue states the backlog behind its page, and the rail says the same number", async ({
  page,
}) => {
  const pending = (id: number, jobId: number, priorId: number) => ({
    link: duplicateProposalFixture({ id, job_id: jobId, prior_job_id: priorId, relation: "duplicate", score: 0.94, gap_days: 0 }),
    prior: jobDetailRowFixture({ id: priorId, req_id: `REQ-${priorId}`, title: "Staff Software Engineer" }),
    job: jobDetailRowFixture({ id: jobId, req_id: `REQ-${jobId}`, title: "Staff Software Engineer" }),
    diff: {},
  });
  const reviewed = { total: 0, limit: 20, offset: 0, items: [] };
  const isHistory = (url: string) => new URL(url).searchParams.get("status") === "reviewed";

  await page.route("/api/stats", (route) =>
    route.fulfill({ json: { ...statsFixture, review_pending: 476 } }));
  await page.route("/api/lineage/review?**", (route) =>
    route.fulfill({
      json: isHistory(route.request().url())
        ? reviewed
        : { total: 275, limit: 50, offset: 0, items: [pending(7, 102, 101), pending(8, 104, 103)] },
    }));
  await page.route("/api/twins/review?**", (route) =>
    route.fulfill({
      json: isHistory(route.request().url())
        ? reviewed
        : { total: 201, limit: 50, offset: 0, items: [] },
    }));

  await page.goto("/review");

  await expect(page.getByText("476 pairs left in the queue")).toBeVisible();
  // The two rows it actually holds must not be mistaken for the whole set.
  await expect(page.getByText(/^2 pairs left/)).toHaveCount(0);
  // The tab badge is the same count, not a second opinion.
  await expect(page.getByRole("tab", { name: /^Queue/ })).toContainText("476");
  await expect(
    page.getByRole("link", { name: "Duplicates, 476 pending" }),
  ).toHaveAttribute("title", "Duplicates, 476 pending");
});

test("local duplicate advice stays separate from the human verdict", async ({ page }) => {
  let verdictWritten = false;
  await page.route("/api/lineage/links/7/analyze", (route) => route.fulfill({
    json: relationshipAssessmentFixture({
      assessment: {
        recommendation: "confirmed",
        confidence: 0.95,
        summary: "The two records describe the same opening: their responsibilities, seniority, location, and compensation all align, while the different requisition identifiers appear to reflect the same role being relisted.",
        matching_evidence: ["Identical responsibilities"],
        differences: ["Different requisition identifiers"],
      },
    }),
  }));
  await page.route("/api/lineage/links/7/review", async (route) => {
    verdictWritten = true;
    await route.fulfill({ json: duplicateVerdictFixture() });
  });

  await page.goto("/review");
  const console = page.getByRole("region", { name: "Make a decision" });
  const defaultConsoleBox = await console.boundingBox();
  const actions = console.getByRole("button");
  await expect(actions.first()).toHaveAccessibleName(/Different roles/);
  await expect(actions.last()).toHaveAccessibleName("Ask the model");
  await expect(console).not.toContainText("System normalization");
  await expect(page.getByLabel("System similarity 94%")).toBeVisible();
  await page.getByRole("button", { name: "About system similarity" }).click();
  await expect(page.getByRole("tooltip")).toContainText("Proposed as the same role");
  await expect(page.getByRole("tooltip")).not.toContainText("candidate");
  // Why the pair was proposed, in the reader's words: never the method's name.
  await expect(page.getByRole("tooltip")).toContainText("Descriptions 90% alike");
  await expect(page.getByRole("tooltip")).not.toContainText(/method|embedding/i);
  await page.getByRole("button", { name: "Ask the model" }).click();

  const assessment = page.getByRole("region", { name: "Local model assessment" });
  await expect(assessment).toContainText("Likely the same role");
  await expect(assessment).toContainText("different requisition identifiers");
  await expect(assessment).toContainText("95%");
  const confirm = page.getByRole("button", { name: /Same role/ });
  await expect(confirm).toBeEnabled();
  const adviceBox = await assessment.boundingBox();
  const confirmBox = await confirm.boundingBox();
  expect(confirmBox?.y).toBeGreaterThan(adviceBox?.y ?? 0);
  expect(await console.evaluate((element) => getComputedStyle(element).position)).toBe("fixed");
  expect(await console.getAttribute("class")).toContain("has-ai-response");
  expect(adviceBox?.height).toBeGreaterThan(40);
  expect(await assessment.locator("p").evaluate((element) => element.scrollWidth <= element.clientWidth)).toBe(true);
  expect((await console.boundingBox())?.height).toBeGreaterThan(defaultConsoleBox?.height ?? 0);
  expect(verdictWritten).toBe(false);
  await page.getByRole("tab", { name: /Decided/ }).click();
  await expect(page.getByRole("region", { name: "Decided" })).toContainText("Different");
  await expect(page.getByRole("region", { name: "Decided" })).toContainText("97%");
  await expect(page.getByRole("region", { name: "Decided" })).not.toContainText("0.972");
});

test("description comparison reveals and filters detected passage differences", async ({ page }) => {
  await page.goto("/review");

  const ledger = page.getByRole("region", { name: "Side by side" });
  await expect(ledger.getByRole("row", { name: /Title\s+Same\s+Staff Software Engineer/ })).toBeVisible();
  await expect(ledger.locator("tr.row-title td[colspan='2']")).toHaveCount(1);
  await expect(ledger.locator("tr.row-requisition")).toHaveCount(0);
  await expect(ledger.getByRole("button", { name: "Show 12 matching fields" })).toBeVisible();
  await expect(ledger.getByRole("row", { name: /Level\s*Same\s*Staff/ })).toHaveCount(0);
  await ledger.getByRole("button", { name: "Show 12 matching fields" }).click();
  await expect(ledger.getByRole("row", { name: /Level\s*Same\s*Staff/ })).toBeVisible();
  await expect(ledger.getByRole("link", { name: "Careers page, earlier posting" })).toHaveAttribute("href", "https://example.test/jobs/101");
  await expect(ledger.getByRole("link", { name: "Careers page, newer posting" })).toHaveAttribute("target", "_blank");
  await expect(ledger.getByRole("link", { name: "Role details, earlier posting" })).toHaveAttribute("href", "/company/openai/job/101");
  await expect(ledger.getByRole("link", { name: "Role details, newer posting" })).not.toHaveAttribute("target", /./);

  const toolbarBox = await page.locator(".review-toolbar").boundingBox();
  const consoleBox = await page.getByRole("region", { name: "Make a decision" }).boundingBox();
  expect(toolbarBox?.height).toBeLessThanOrEqual(60);
  expect(consoleBox?.height).toBeLessThanOrEqual(80);

  const comparison = page.getByRole("region", { name: "Description comparison", exact: true });
  await expect(comparison).toContainText("Five years of platform experience");
  await expect(comparison).toContainText("Experience with platform systems");
  await expect(comparison.getByText("Changed passage")).toHaveCount(2);

  await page.getByRole("button", { name: "Show differences only" }).click();
  await expect(comparison).not.toContainText("Shared responsibility 1");
  await expect(page.getByRole("button", { name: "Show full descriptions" })).toHaveAttribute("aria-pressed", "true");

  const reviewMain = page.locator("main.review-main");
  await reviewMain.evaluate((element) => element.scrollTo({ top: element.scrollHeight }));
  await expect(page.getByRole("region", { name: "Make a decision" })).toBeInViewport();
  await expect(page.getByRole("button", { name: /Same role/ })).toBeInViewport();
});

test("decision history is a full workspace and past choices can be expanded and changed", async ({ page }) => {
  // The Decided list is the summary form: an expanded row reads its two postings whole.
  await page.route("/api/jobs/99", (route) => route.fulfill({
    json: jobDetailFixture({ id: 99, req_id: "REQ-OLD", title: "Staff Software Engineer, Platform", url: "https://example.test/jobs/99" }),
  }));
  await page.route("/api/jobs/100", (route) => route.fulfill({
    json: jobDetailFixture({ id: 100, req_id: "REQ-NEW", title: "Staff Software Engineer, Payments", url: "https://example.test/jobs/100" }),
  }));
  let revisedTo: string | null = null;
  await page.route("/api/lineage/links/6/review", async (route) => {
    revisedTo = (await route.request().postDataJSON()).verdict;
    await route.fulfill({ json: duplicateVerdictFixture({ id: 6, status: "rejected", decision: "twin", twin_link_id: 22, lineages: 0 }) });
  });
  await page.goto("/review");
  await page.getByRole("tab", { name: /Decided/ }).click();

  const history = page.getByRole("region", { name: "Decided" });
  await expect(history).toBeInViewport();
  await expect(page.getByRole("region", { name: "Candidate position pair" })).toHaveCount(0);
  const mainBox = await page.locator("main.review-main").boundingBox();
  const historyBox = await history.boundingBox();
  expect(historyBox?.width).toBeGreaterThan((mainBox?.width ?? 0) * 0.85);

  await history.getByRole("button", { name: /REQ-OLD/ }).click();
  const editor = history.getByRole("region", { name: "Change decision" });
  const comparison = history.getByRole("region", { name: "Side by side" });
  await expect(comparison.getByRole("link", { name: "Role details, earlier posting" })).toHaveAttribute("href", "/company/openai/job/99");
  await expect(history.locator(".review-panel")).toHaveCount(0);
  await expect(editor.getByRole("button", { name: /Different roles/ })).toBeDisabled();
  await editor.getByRole("button", { name: /Related roles/ }).click();
  await expect.poll(() => revisedTo).toBe("twin");
});

// A reload must not land on the queue with the archive's filter and search
// gone. The tab, the filter and the search are the address.
test("a reload keeps the Decided tab, its filter and its search", async ({ page }) => {
  await page.goto("/review");
  const entries = await page.evaluate(() => window.history.length);
  await page.getByRole("tab", { name: /Decided/ }).click();
  const history = page.getByRole("region", { name: "Decided" });
  await history.getByRole("button", { name: "Different roles" }).click();
  await history.getByRole("searchbox", { name: "Search decisions" }).fill("REQ-OLD");
  await expect(page).toHaveURL(/\/review\?view=history&decision=different&q=REQ-OLD$/);
  // Each change replaced the entry, so Back leaves the screen instead of
  // stepping back through every keystroke.
  expect(await page.evaluate(() => window.history.length)).toBe(entries);

  await page.reload();
  const reloaded = page.getByRole("region", { name: "Decided" });
  await expect(page.getByRole("tab", { name: /Decided/ })).toHaveAttribute("aria-selected", "true");
  await expect(reloaded.getByRole("button", { name: "Different roles" })).toHaveAttribute("aria-pressed", "true");
  await expect(reloaded.getByRole("searchbox", { name: "Search decisions" })).toHaveValue("REQ-OLD");
  await expect(reloaded).toContainText("Staff Software Engineer, Platform");
});

// The names are read before the first render; otherwise every company outside
// a short built-in list prints as its slug ("palo-alto-networks").
test("a decided pair names its company as the company does", async ({ page }) => {
  await page.route("/api/companies/names", (route) =>
    route.fulfill({ json: { names: { "palo-alto-networks": "Palo Alto Networks" } } }));
  await page.route("/api/lineage/review?**", (route) => {
    const history = new URL(route.request().url()).searchParams.get("status") === "reviewed";
    return route.fulfill({ json: history ? {
      total: 1, limit: 20, offset: 0, items: [{
        link: duplicateProposalFixture({ id: 6, job_id: 100, prior_job_id: 99, status: "rejected", decision: "different", reviewed_at: "2026-07-15T15:00:00Z" }),
        prior: jobDetailRowFixture({ id: 99, req_id: "REQ-OLD", title: "Director, Cloud Security", company: "palo-alto-networks" }),
        job: jobDetailRowFixture({ id: 100, req_id: "REQ-NEW", title: "Director, Cloud Security II", company: "palo-alto-networks" }),
        diff: {},
      }],
    } : { total: 0, limit: 50, offset: 0, items: [] } });
  });
  await page.goto("/review?view=history");

  const history = page.getByRole("region", { name: "Decided" });
  await expect(history).toContainText("Palo Alto Networks ·");
  await expect(history).not.toContainText("palo-alto-networks");
});

// The names are worth a short wait, never the app: a read that never answers
// still lets the page render, with the built-in names and slugs.
test("a names read that never answers does not hold the app back", async ({ page }) => {
  await page.route("/api/companies/names", () => { /* never answered */ });
  await page.goto("/review");
  await expect(page.getByRole("tab", { name: /Decided/ })).toBeVisible();
});

test("a description reads at a measure on a wide screen, however wide its column", async ({ page, isMobile }) => {
  test.skip(isMobile, "the measure is a claim about a wide column");
  await page.setViewportSize({ width: 2000, height: 1100 });
  await page.goto("/review");
  const comparison = page.getByRole("region", { name: "Description comparison", exact: true });
  await expect(comparison).toContainText("Five years of platform experience");
  const measures = await comparison.locator(".review-description-section p").evaluateAll((ps) =>
    ps.map((p) => {
      const probe = document.createElement("span");
      probe.style.font = getComputedStyle(p).font;
      probe.style.position = "absolute";
      probe.textContent = "0".repeat(75);
      document.body.append(probe);
      const cap = probe.getBoundingClientRect().width;
      probe.remove();
      return { width: p.getBoundingClientRect().width, cap, column: p.closest(".review-description-column")!.getBoundingClientRect().width };
    }));
  // The column is wider than the measure here, so the cap is what holds the line.
  expect(Math.max(...measures.map((m) => m.column))).toBeGreaterThan(Math.max(...measures.map((m) => m.cap)));
  for (const m of measures) expect(m.width).toBeLessThanOrEqual(m.cap + 1);
});
