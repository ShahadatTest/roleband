import { expect, test } from "./fixtures";
import {
  facetsFixture,
  jobFixture,
  jobListFixture,
  notificationsFixture,
  statsFixture,
  statusFixture,
} from "../../src/test/fixtures";

/* Role-requirements panel on the opportunity detail route: placement before the
   description, evidence disclosure with the employer quote, and the truth
   contract (empty = nothing catalogued found, never "no skills needed"). */

const requirementsFixture = {
  state: "ready",
  extractor_version: "2.0.0",
  skills: [
    {
      concept_id: 1,
      slug: "python",
      display: "Python",
      facet: "technology",
      category: "language",
      importance_band: "core",
      importance_score: 85,
      confidence: "high",
      modality: "required",
      proficiency: "proficient",
      evidence: [
        {
          section_key: "minimum_qualifications",
          section_title: "Minimum Qualifications",
          quote: "Strong Python experience building distributed services.",
          start_offset: 0,
          end_offset: 56,
          modality: "required",
        },
      ],
    },
    {
      concept_id: 2,
      slug: "terraform",
      display: "Terraform",
      facet: "technology",
      category: "infra",
      importance_band: "supporting",
      importance_score: 40,
      confidence: "high",
      modality: "preferred",
      proficiency: "unspecified",
      evidence: [
        {
          section_key: "preferred_qualifications",
          section_title: "Preferred Qualifications",
          quote: "Terraform experience is a plus.",
          start_offset: 0,
          end_offset: 31,
          modality: "preferred",
        },
      ],
    },
    {
      concept_id: 3,
      slug: "mentorship",
      display: "Mentorship",
      facet: "behavioral_competency",
      category: "leadership",
      importance_band: "important",
      importance_score: 60,
      confidence: "high",
      modality: "used_in_role",
      proficiency: "unspecified",
      evidence: [
        {
          section_key: "responsibilities",
          section_title: "What you'll do",
          quote: "Mentor senior engineers across the platform group.",
          start_offset: 0,
          end_offset: 50,
          modality: "used_in_role",
        },
      ],
    },
    {
      concept_id: 4,
      slug: "healthcare",
      display: "Healthcare",
      facet: "industry",
      category: "industry",
      importance_band: "important",
      importance_score: 60,
      confidence: "high",
      modality: "preferred",
      proficiency: "unspecified",
      evidence: [
        {
          section_key: "preferred_qualifications",
          section_title: "Preferred Qualifications",
          quote: "Experience in the healthcare industry.",
          start_offset: 0,
          end_offset: 38,
          modality: "preferred",
        },
      ],
    },
  ],
  qualifications: [
    {
      id: 1,
      kind: "experience",
      display: "8+ years of software engineering experience.",
      modality: "required",
      years: 8,
      years_stated: [8],
      evidence: [
        {
          section_key: "minimum_qualifications",
          section_title: "Minimum Qualifications",
          quote: "8+ years of software engineering experience.",
          start_offset: 0,
          end_offset: 45,
          modality: "required",
        },
      ],
    },
    {
      // A preferred line asking for MORE than the requirement: it carries its
      // own figure and never becomes the headline.
      id: 2,
      kind: "experience",
      display: "12+ years building developer platforms, including 4+ years leading platform teams.",
      modality: "preferred",
      years: 12,
      years_stated: [12, 4],
      evidence: [
        {
          section_key: "preferred_qualifications",
          section_title: "Preferred Qualifications",
          quote: "12+ years building developer platforms, including 4+ years leading platform teams.",
          start_offset: 0,
          end_offset: 84,
          modality: "preferred",
        },
      ],
    },
  ],
  required_years: 8,
};

const jobWithRequirements = {
  ...jobFixture,
  description_sections: [
    {
      key: "minimum_qualifications",
      title: "Minimum Qualifications",
      content:
        "Strong Python experience building distributed services.\n8+ years of software engineering experience.",
    },
  ],
  requirements: requirementsFixture,
};

const jobEmptyRequirements = {
  ...jobFixture,
  id: 202,
  title: "Principal Engineer, Platform",
  requirements: { state: "ready", extractor_version: "2.0.0", skills: [], qualifications: [], required_years: null },
};

test.beforeEach(async ({ page }) => {
  await page.route("/api/profile", (route) =>
    route.fulfill({ json: { profile: null, scope_configured: true } }),
  );
  await page.route("/api/stats", (route) => route.fulfill({ json: statsFixture }));
  await page.route("/api/status", (route) => route.fulfill({ json: statusFixture }));
  await page.route("/api/facets", (route) => route.fulfill({ json: facetsFixture }));
  await page.route("/api/notifications**", (route) => route.fulfill({ json: notificationsFixture }));
  await page.route("/api/jobs/101", (route) => route.fulfill({ json: jobWithRequirements }));
  await page.route("/api/jobs/202", (route) => route.fulfill({ json: jobEmptyRequirements }));
  await page.route("/api/jobs/*/similar**", (route) =>
    route.fulfill({ json: { scope: "cross", items: [] } }),
  );
  await page.route("/api/jobs/*/view", (route) => route.fulfill({ json: { viewed: true } }));
  await page.route("/api/jobs/*/lineage", (route) => route.fulfill({ json: { items: [] } }));
  await page.route("/api/jobs/*/twins", (route) =>
    route.fulfill({ json: { job_id: 101, size: 0, direct_count: 0, members: [] } }),
  );
  await page.route("/api/jobs/*/place-set", (route) =>
    route.fulfill({ json: { job_id: 101, place_set: null, rejected: false, rejected_at: null } }),
  );
  await page.route("/api/jobs?**", (route) => route.fulfill({ json: jobListFixture }));
});

test("requirements panel renders before the description with grouped content", async ({ page }) => {
  await page.goto("/company/openai/job/101");
  const panel = page.getByRole("region", { name: "Role requirements" });
  await expect(panel.getByText("What this role asks for")).toBeVisible();

  // Panel sits above the job description in the main column.
  //
  // Both boxes are awaited before they are measured: `boundingBox()` answers
  // null for an element that has no box, and a `!` assertion would turn that
  // into a TypeError that names neither box. A box that never arrives fails as
  // itself, by name. The page is opened at its company-scoped URL: a short
  // /job/:id rewrites itself once the job loads and remounts the detail, which
  // can detach a box between the wait and the measurement.
  const sections = page.locator(".jd-sections");
  await expect(panel).toBeVisible();
  await expect(sections).toBeVisible();
  const panelBox = await panel.boundingBox();
  const descBox = await sections.boundingBox();
  expect(panelBox, "the requirements panel has no layout box").not.toBeNull();
  expect(descBox, "the job description has no layout box").not.toBeNull();
  expect(panelBox!.y).toBeLessThan(descBox!.y);

  // Hard skill in the ledger; behavioural stays in Ways of working.
  await expect(panel.getByRole("button", { name: /Python, core required skill/ })).toBeVisible();
  await expect(panel.getByText("Ways of working")).toBeVisible();
  await expect(panel.getByText("Mentorship")).toBeVisible();

  // Industry vertical sits in its own group, never as a ledger skill.
  await expect(panel.getByText("Industry", { exact: true })).toBeVisible();
  await expect(panel.getByText("Healthcare")).toBeVisible();
  await expect(
    panel.getByRole("button", { name: /Healthcare, .*skill/ }),
  ).toHaveCount(0);

  // Supporting chip carries its modality as text (scoped to the chip so it does
  // not collide with the industry chip's own modality label).
  await expect(panel.getByText(/Terraform\s*·\s*Preferred/)).toBeVisible();

  // Qualifications ledger is separate from skills.
  await expect(panel.getByText("Qualifications")).toBeVisible();
  await expect(panel.getByText("8+ years of software engineering experience.")).toBeVisible();
});

test("years: the required headline heads the panel, each experience line carries its numbers", async ({ page }) => {
  await page.goto("/company/openai/job/101");
  const panel = page.getByRole("region", { name: "Role requirements" });
  // The headline is the REQUIRED line's 8, not the preferred line's 12.
  await expect(panel.getByText("8+ years required", { exact: true })).toBeVisible();
  await expect(panel.getByText(/12\+ years required/)).toHaveCount(0);

  const figures = panel.getByRole("definition").filter({ hasText: /^\d[\d+ ·]*years?$/ });
  await expect(figures).toHaveText(["8+ years", "12+ · 4+ years"]);
  await expect(figures.nth(1).locator("strong")).toHaveText("12+");

  // Desktop: a column right of the line. Below 860px there is no room for a
  // third column, so the figure sits under its line, never squeezing the prose.
  const line = panel.getByText("12+ years building developer platforms, including 4+ years leading platform teams.");
  const lineBox = await line.boundingBox();
  const figureBox = await figures.nth(1).boundingBox();
  expect(lineBox, "the qualification line has no layout box").not.toBeNull();
  expect(figureBox, "the years figure has no layout box").not.toBeNull();
  if (page.viewportSize()!.width > 860) {
    expect(figureBox!.x).toBeGreaterThanOrEqual(lineBox!.x + lineBox!.width - 1);
  } else {
    expect(figureBox!.y).toBeGreaterThanOrEqual(lineBox!.y + lineBox!.height - 1);
    expect(Math.abs(figureBox!.x - lineBox!.x)).toBeLessThan(2);
  }
});

test("clicking a skill row discloses the employer quote and jumps to the source", async ({ page }) => {
  await page.goto("/job/101");
  const row = page.getByRole("button", { name: /Python, core required skill/ });
  await expect(row).toHaveAttribute("aria-expanded", "false");
  await row.click();
  await expect(row).toHaveAttribute("aria-expanded", "true");
  await expect(
    page.getByText("“Strong Python experience building distributed services.”"),
  ).toBeVisible();
  await expect(page.getByText("Minimum Qualifications", { exact: true }).first()).toBeVisible();
  await page.getByRole("button", { name: "Show in description" }).click();
  await expect(page.locator(".jd-section-minimum_qualifications")).toBeInViewport();
});

/* Over a role page, the jump moves the cover the reader is looking at. The
   page underneath is another role with the same section keys, and it comes
   first in the document, so a lookup that is not scoped to its own cover
   scrolls the hidden page and nothing visible moves. */
test("over a role page, Show in description scrolls the role on top", async ({ page }) => {
  const filler = Array.from({ length: 30 }, (_, i) => `Paragraph ${i + 1} about the team and its mission.`).join("\n");
  const similar = { ...jobWithRequirements, id: 303, title: "Staff Engineer, Ingest", score: 0.8 };
  const over = {
    ...similar,
    description_sections: [{ key: "about", title: "About the team", content: filler }, ...jobWithRequirements.description_sections],
  };
  await page.route("/api/jobs/303", (route) => route.fulfill({ json: over }));
  await page.route("/api/jobs/101/similar**", (route) => {
    const scope = new URL(route.request().url()).searchParams.get("scope");
    return route.fulfill({ json: { scope, items: scope === "cross" ? [similar] : [] } });
  });
  await page.goto("/company/openai/job/101");
  await page.getByRole("link", { name: /Staff Engineer, Ingest/ }).click();
  const dialog = page.getByRole("dialog", { name: "Role: Staff Engineer, Ingest" });
  await dialog.getByRole("button", { name: /Python, core required skill/ }).click();
  const target = dialog.locator(".jd-section-minimum_qualifications");
  await expect(target).not.toBeInViewport();
  await dialog.getByRole("button", { name: "Show in description" }).click();
  await expect(target).toBeInViewport();
});

test("empty requirements state never claims the role needs no skills", async ({ page }) => {
  await page.goto("/job/202");
  const panel = page.getByRole("region", { name: "Role requirements" });
  await expect(panel.getByText(/No explicit skill requirements found/)).toBeVisible();
  await expect(panel.getByText(/not that the role needs no skills/)).toBeVisible();
});
