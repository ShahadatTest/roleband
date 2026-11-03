/* One role its employer lists once per place: the Board row says how
   many places, Job detail names the others and links to each, and "Different
   roles" splits a posting out with an Undo. Every request is mocked; the
   harness guard throws on any that is not. */

import { expect, mockApi, mockGet, test } from "./fixtures";
import { jobFixture } from "../../src/test/fixtures";
import { detail, installBoardRoutes, jobFixture2, twoJobList } from "./boardHarness";

const london = { ...jobFixture, locations: ["London, United Kingdom"], place_count: 3 };
const bristol = { ...jobFixture2, title: jobFixture.title, locations: ["Bristol, United Kingdom"], place_count: 3 };
const leeds = { ...jobFixture, id: 404, locations: ["Leeds, United Kingdom"], place_count: 3 };

const inSet = {
  job_id: 101,
  place_set: {
    id: 4,
    size: 3,
    places: ["London, UK", "Bristol, UK", "Leeds, UK"],
    employer_label: null,
    rule_version: "place_set/v1",
    members: [
      { job: london, is_this: true, relation: "place", same_place: false, stated_pay: null },
      { job: bristol, is_this: false, relation: "place", same_place: false, stated_pay: null },
      { job: leeds, is_this: false, relation: "place", same_place: false, stated_pay: null },
    ],
  },
  rejected: false,
  rejected_at: null,
};
const split = { job_id: 101, place_set: null, rejected: true, rejected_at: "2026-10-03T12:00:00Z" };

test.beforeEach(async ({ page }) => {
  await installBoardRoutes(page);
  await mockGet(page, "/api/jobs/101", (route) => route.fulfill({ json: london }));
  await mockGet(page, "/api/jobs/101/place-set", (route) => route.fulfill({ json: inSet }));
});

test("the Board row says how many places the role is listed in", async ({ page }) => {
  await mockGet(page, "/api/jobs?**", (route) =>
    route.fulfill({ json: { ...twoJobList, items: [london, { ...jobFixture2, place_count: null }] } }),
  );
  await page.goto("/");
  const rows = page.locator(".job-row");
  await expect(rows.filter({ hasText: jobFixture.title }).getByText("Listed in 3 places")).toBeVisible();
  await expect(rows.filter({ hasText: jobFixture2.title }).getByText(/Listed in/)).toHaveCount(0);
});

test("Job detail names the other places and opens each one's posting", async ({ page }) => {
  await page.goto("/job/101");
  const section = detail(page).getByRole("region", { name: "Also listed in" });
  await expect(section.getByText("Also listed in 2 other places")).toBeVisible();
  await expect(section.getByRole("link")).toHaveText(["Bristol, United Kingdom", "Leeds, United Kingdom"]);
  await expect(section.getByRole("link", { name: "Bristol, United Kingdom" })).toHaveAttribute(
    "href",
    `/company/${jobFixture2.company}/job/202`,
  );
  await expect(section).toContainText("same description at each place");
  // The split is a link, so the page keeps "View & apply" as its one primary.
  await expect(section.getByRole("button", { name: "Different roles" })).not.toHaveClass(/ui-btn-primary/);

  await section.getByRole("link", { name: "Bristol, United Kingdom" }).click();
  await expect(page).toHaveURL(/\/job\/202$/);
});

test("Different roles splits the posting out, and Undo brings it back", async ({ page }) => {
  const sent: string[] = [];
  await mockApi(page, "POST", "/api/jobs/101/place-set/review", async (route) => {
    const decision = route.request().postDataJSON().decision as string;
    sent.push(decision);
    await route.fulfill({ json: decision === "different" ? split : inSet });
  });
  await page.goto("/job/101");
  const panel = detail(page);
  await panel.getByRole("button", { name: "Different roles" }).click();

  await expect(panel.getByRole("region", { name: "Also listed in" })).toHaveCount(0);
  await expect(panel.getByText(/You marked this posting as a different role/)).toBeVisible();
  const toast = page.getByRole("status").filter({ hasText: "Marked as a different role" });
  await expect(toast).toBeVisible();

  await toast.getByRole("button", { name: "Undo" }).click();
  await expect(panel.getByRole("region", { name: "Also listed in" })).toBeVisible();
  expect(sent).toEqual(["different", "pending"]);
});

test("a posting in no place set shows no section", async ({ page }) => {
  await mockGet(page, "/api/jobs/101/place-set", (route) =>
    route.fulfill({ json: { job_id: 101, place_set: null, rejected: false, rejected_at: null } }),
  );
  await page.goto("/job/101");
  await expect(detail(page).getByRole("heading", { name: jobFixture.title })).toBeVisible();
  await expect(detail(page).getByRole("region", { name: "Also listed in" })).toHaveCount(0);
  await expect(detail(page).getByText(/other place/)).toHaveCount(0);
});
