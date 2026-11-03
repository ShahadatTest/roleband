/* Search, sort and rank — everything that decides the ORDER and the MEMBERSHIP
   of the list from a query rather than from a filter. The exact-title section
   and its related disclosure live here: they are a search result shape. */

import { expect, test } from "./fixtures";
import type { Page } from "@playwright/test";
import { jobFixture, jobListFixture } from "../../src/test/fixtures";
import { appleJobFixture, installBoardRoutes, jobFixture2, twoJobList } from "./boardHarness";
import { msg } from "../../src/test/msg";

test.beforeEach(async ({ page }) => {
  await installBoardRoutes(page);
});

test("search updates the jobs query instead of filtering stale client state", async ({ page }) => {
  const jobRequests: string[] = [];
  await page.route("/api/jobs?**", (route) => {
    jobRequests.push(route.request().url());
    return route.fulfill({ json: jobListFixture });
  });

  await page.goto("/");
  await page.getByPlaceholder(msg("radar-search-placeholder")).fill("api product");

  await expect
    .poll(() => jobRequests.some((url) => new URL(url).searchParams.get("q") === "api product"))
    .toBe(true);
});

test("sorting by a column sends sort + order to the server and resets to page one", async ({ page }) => {
  const jobRequests: string[] = [];
  await page.route("/api/jobs?**", (route) => {
    jobRequests.push(route.request().url());
    // 60 results over pageSize 20 => 3 pages, so a pager renders.
    return route.fulfill({ json: { ...twoJobList, total: 60 } });
  });

  await page.goto("/");
  const params = () => new URL(jobRequests[jobRequests.length - 1]).searchParams;

  // Advance to page 2 so we can prove sorting resets pagination.
  await page.getByRole("button", { name: /Next/ }).click();
  await expect.poll(() => params().get("offset")).toBe("20");

  // Pick "Location" from the sort control: server gets the new field...
  await page.getByRole("combobox", { name: "Sort by" }).selectOption("location");
  await expect.poll(() => params().get("sort")).toBe("location");
  // ...and pagination resets to the first page.
  await expect.poll(() => params().get("offset")).toBe("0");

  // Toggling direction flips order and again resets to the first page.
  await page.getByRole("button", { name: msg("radar-order-reverse") }).click();
  await expect.poll(() => params().get("order")).toBe("asc");
  await expect.poll(() => params().get("offset")).toBe("0");
  // The selected sort stays reflected in the UI.
  await expect(page.getByRole("combobox", { name: "Sort by" })).toHaveValue("location");
});

test("Best match is offered without a query and ranks by intent server-side", async ({ page }) => {
  // Queryless Best matches: sort=relevance with no q ranks
  // by the standing intent vector. The order toggle disappears — the backend
  // ignores asc/desc on this path.
  const jobRequests: string[] = [];
  await page.route("/api/jobs?**", (route) => {
    jobRequests.push(route.request().url());
    return route.fulfill({ json: { ...twoJobList, ranked_by: "intent" } });
  });

  await page.goto("/");
  const params = () => new URL(jobRequests[jobRequests.length - 1]).searchParams;

  await page.getByRole("combobox", { name: "Sort by" }).selectOption("relevance");
  await expect.poll(() => params().get("sort")).toBe("relevance");
  expect(params().get("q")).toBeNull();
  await expect(page.getByRole("button", { name: msg("radar-order-reverse") })).toBeHidden();
  // The board still lists the same filtered set — ranking, not a gate.
  await expect(page.getByRole("combobox", { name: "Sort by" })).toHaveValue("relevance");
});

test("clicking a column header sorts by that column and toggles direction", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name === "mobile", "Column headers collapse to cards on mobile; use the sort dropdown.");
  const jobRequests: string[] = [];
  await page.route("/api/jobs?**", (route) => {
    jobRequests.push(route.request().url());
    return route.fulfill({ json: twoJobList });
  });

  await page.goto("/");
  const params = () => new URL(jobRequests[jobRequests.length - 1]).searchParams;
  const compLabel = msg("jobs-sort-label-abbr", { short: msg("jobs-head-pay"), full: msg("shared-base-salary-full") });

  // First click on the Base header sorts by base salary, descending.
  await page.getByRole("button", { name: msg("jobs-sort-by", { label: compLabel }) }).click();
  await expect.poll(() => params().get("sort")).toBe("base_pay");
  await expect.poll(() => params().get("order")).toBe("desc");
  await expect.poll(() => params().get("offset")).toBe("0");

  // Clicking the same (now active) header flips to ascending.
  await page.getByRole("button", { name: /^Sort by Base \(Base salary\)/ }).click();
  await expect.poll(() => params().get("order")).toBe("asc");

  // The active column header exposes its sort state to assistive tech: the
  // app's one "currently on" convention plus the direction in the NAME
  // (aria-sort is invalid on a button and readers may drop it silently).
  const activeHeader = page.getByRole("button", { name: msg("jobs-sort-by-ascending", { label: compLabel }) });
  await expect(activeHeader).toBeVisible();
  await expect(activeHeader).toHaveAttribute("aria-pressed", "true");
});

/* Best-match candidate ceiling. The ranked pool is bounded, so a very broad
   query can only rank a slice of what it matches. Showing the slice size as
   the result count would make a bound we impose read as a small market. */
test("a truncated best-match ranking says how many roles it could not rank", async ({ page }) => {
  await page.route("/api/jobs?**", (route) =>
    route.fulfill({
      json: { ...twoJobList, total: 2000, matched: 5400, ranking_truncated: true },
    })
  );
  await page.goto("/");

  const note = page.getByRole("note").filter({ hasText: /showing the best/i });
  await expect(note).toBeVisible();
  // Both numbers must appear: the slice alone is the misleading figure, and the
  // match count alone gives no sense of what is reachable.
  await expect(note).toContainText("2,000");
  await expect(note).toContainText("5,400");
});

test("an untruncated best-match ranking shows no slice warning", async ({ page }) => {
  await page.route("/api/jobs?**", (route) =>
    route.fulfill({
      json: { ...twoJobList, total: 2, matched: 2, ranking_truncated: false },
    })
  );
  await page.goto("/");

  await expect(page.getByText(/showing the best/i)).toHaveCount(0);
});

test("the Sort select rings for the keyboard and never for the mouse", async ({ page }) => {
  await page.goto("/");
  const sort = page.getByRole("combobox", { name: "Sort by" });
  const paint = () =>
    sort.evaluate((el) => ({ focused: document.activeElement === el, ring: getComputedStyle(el).outlineStyle }));

  // Click, choose nothing, leave: focus stays on a native select (there is
  // no close event to release it), so the control must not paint the ring
  // for pointer focus at all, or the halo sticks.
  await sort.click();
  await page.keyboard.press("Escape");
  await page.mouse.move(8, 400);
  // The ring transitions over --app-duration-fast, and a sample taken inside
  // that window reads a half-painted halo. Wait it out so "none" means none,
  // not "not yet".
  await page.waitForTimeout(400);
  expect(await paint()).toEqual({ focused: true, ring: "none" });

  // Arrive by keyboard and the ring is the whole point (2.4.7).
  await page.keyboard.press("Shift+Tab");
  await page.keyboard.press("Tab");
  await expect.poll(async () => (await paint()).focused).toBe(true);
  await expect.poll(async () => (await paint()).ring).not.toBe("none");
});

// --- The intent-ranked board: default order, in-list signals, dismissal -----

const intentRankedList = {
  ...twoJobList,
  ranked_by: "intent",
  items: [
    { ...jobFixture, why_world: "ai_ml", relevance: 0.83 },
    { ...jobFixture2, why_world: null, relevance: 0.41 },
  ],
};

test("the board asks for relevance by default and stays unbannered when the server ranks", async ({ page }) => {
  const jobRequests: string[] = [];
  await page.route("/api/jobs?**", (route) => {
    jobRequests.push(route.request().url());
    const sort = new URL(route.request().url()).searchParams.get("sort");
    return route.fulfill({ json: sort === "relevance" ? intentRankedList : twoJobList });
  });

  await page.goto("/");
  // Wait for the board's mount request to exist before reading it. Without this
  // the first poll tick could run on an empty array, and `new URL(undefined)`
  // throws, which expect.poll does not retry past: an intermittent failure
  // that has nothing to do with sort.
  await expect.poll(() => jobRequests.length).toBeGreaterThan(0);
  const paramsOf = (url: string) => new URL(url).searchParams;
  const first = () => paramsOf(jobRequests[0]);
  const latest = () => paramsOf(jobRequests[jobRequests.length - 1]);

  // Default-sort logic: the very FIRST request is the ranked one. Assert that
  // literally, on jobRequests[0] — polling the latest request would also accept
  // a board that asked for something else on mount and corrected itself after.
  expect(first().get("sort")).toBe("relevance");
  expect(first().get("q")).toBeNull();

  // No announcement strip: it would break the page's visual line, and the
  // loop lives in onboarding. Even a server that intent-ranked this response
  // draws no banner...
  await expect(page.getByText("Staff Product Manager, API").first()).toBeVisible();
  await expect(page.getByText("Ranked by your direction")).toHaveCount(0);

  // ...the in-list signals carry it instead: the why-chip world as a display
  // name (never the score), and the Sort control naming the order.
  await expect(page.getByText("AI & Machine Learning").first()).toBeVisible();
  await expect(page.getByText(/0\.83|83%/)).toHaveCount(0);
  // exact: the column-header buttons are "Sort by Location" etc.
  await expect(page.getByLabel("Sort by", { exact: true })).toHaveValue("relevance");

  // Newest stays one interaction away, through the same Sort control.
  await page.getByLabel("Sort by", { exact: true }).selectOption("first_seen");
  await expect.poll(() => latest().get("sort")).toBe("first_seen");
});

test("dismissing feeds the loop: the next fetch re-requests the ranked list", async ({ page }) => {
  const jobRequests: string[] = [];
  await page.route("/api/jobs?**", (route) => {
    jobRequests.push(route.request().url());
    return route.fulfill({ json: intentRankedList });
  });
  let feedbackVerdict: unknown = null;
  await page.route("/api/jobs/101/feedback", (route) => {
    if (route.request().method() === "DELETE") return route.fulfill({ json: { ok: true } });
    feedbackVerdict = route.request().postDataJSON();
    return route.fulfill({ json: { job_id: 101, is_dismissed: true, team: null, department: null, company: "google" } });
  });

  await page.goto("/");
  await expect(page.getByText("Staff Product Manager, API").first()).toBeVisible();
  const before = jobRequests.length;

  // Dismiss: optimistic removal + the way-back beacon in the margin;
  // the negative signal lands.
  await page.getByRole("button", { name: /Not for me/ }).first().click();
  await expect.poll(() => feedbackVerdict).toEqual({ verdict: "dismissed", reason: null });

  // Undo re-fetches the SAME ranked list — the re-rank happens server-side on
  // the next fetch, which is exactly what this asserts.
  // On a pointer the pill's click IS the undo; on the phone the tap opens the
  // reveal and Undo is its primary (the same split board-filters.spec asserts).
  const pill = page.getByRole("button", { name: /^Marked .*Not for me\. Undo$/ });
  if (test.info().project.name === "mobile") {
    await pill.click();
    await page.getByRole("dialog", { name: msg("shared-not-for-me") }).getByRole("button", { name: msg("common-undo") }).click();
  } else {
    await pill.click();
  }
  // The pill leaving and the row coming back are what tie the re-fetch below
  // to THIS undo: a board re-requests on plenty of other occasions, so the
  // count alone would be satisfied by a request the undo never caused.
  await expect(pill).toHaveCount(0);
  await expect(page.getByText("Staff Product Manager, API").first()).toBeVisible();
  await expect.poll(() => jobRequests.length).toBeGreaterThan(before);
  await expect.poll(() => new URL(jobRequests[jobRequests.length - 1]).searchParams.get("sort")).toBe("relevance");
});

/* ————————————— Exact/related presentation ————————————— */

// A direct exact-title response: one exact row, related rows behind the
// explicit disclosure.
const exactRow = {
  ...jobFixture,
  id: 401,
  title: "Applied Science Manager, Prime Video Personalization & Discovery",
  match_class: "exact",
  matched_via: ["exact", "keyword", "fuzzy"],
};

const relatedClose = {
  ...jobFixture,
  id: 402,
  title: "Applied Science Manager, Prime Video - Content Localization",
  match_class: "close",
  matched_via: ["keyword"],
};

const relatedPm = {
  ...jobFixture,
  id: 403,
  title: "Senior Product Manager, Prime Video Personalization & Discovery",
  match_class: "related",
  matched_via: ["keyword", "fuzzy"],
};

function exactListResponse(includeRelated: boolean) {
  return {
    total: 1,
    matched: 12,
    limit: 25,
    offset: 0,
    query_kind: "exact_title",
    related_total: 2,
    items: [exactRow],
    related_items: includeRelated ? [relatedClose, relatedPm] : [],
    ranking_truncated: false,
  };
}

async function searchExact(page: Page, jobRequests: string[]) {
  await page.route("/api/jobs?**", (route) => {
    const url = route.request().url();
    jobRequests.push(url);
    const params = new URL(url).searchParams;
    if (params.get("q")) {
      return route.fulfill({ json: exactListResponse(params.get("include_related") === "true") });
    }
    return route.fulfill({ json: twoJobList });
  });
  await page.goto("/");
  await page.getByPlaceholder(msg("radar-search-placeholder")).fill("Applied Science Manager, Prime Video Personalization & Discovery");
}

test("an exact-title query shows the exact section and a countable disclosure, no related rows before the click", async ({ page }) => {
  const jobRequests: string[] = [];
  await searchExact(page, jobRequests);

  await expect(page.getByRole("heading", { name: msg("radar-exact-head", { count: 1 }) })).toBeVisible();
  await expect(page.getByText("Applied Science Manager, Prime Video Personalization & Discovery")).toBeVisible();
  await expect(page.getByText(msg("jobs-match-exact"), { exact: true })).toBeVisible();

  // The disclosure is a real button whose accessible name carries the count.
  const toggle = page.getByRole("button", { name: msg("radar-show-other", { count: 2 }) });
  await expect(toggle).toBeVisible();
  // No related rows and no related header before the click.
  await expect(page.getByText("Applied Science Manager, Prime Video - Content Localization")).toHaveCount(0);
  await expect(page.getByRole("heading", { name: /^Other matches/ })).toHaveCount(0);
});

test("expanding re-requests with include_related=true; the exact row stays first and labels stay qualitative", async ({ page }) => {
  const jobRequests: string[] = [];
  await searchExact(page, jobRequests);

  await page.getByRole("button", { name: msg("radar-show-other", { count: 2 }) }).click();
  await expect
    .poll(() => jobRequests.some((u) => new URL(u).searchParams.get("include_related") === "true"))
    .toBe(true);

  await expect(page.getByRole("heading", { name: msg("radar-other-head", { count: 2 }) })).toBeVisible();
  // Exact section stays visible above the related page.
  await expect(page.getByRole("heading", { name: msg("radar-exact-head", { count: 1 }) })).toBeVisible();
  const rows = page.getByRole("article");
  await expect(rows.first()).toContainText(
    "Applied Science Manager, Prime Video Personalization & Discovery"
  );

  // The family-conflict Product Manager row renders "Related", never an
  // exact/close claim; the same-shape row renders "Close title".
  const pmRow = page.getByRole("article").filter({ hasText: "Senior Product Manager" });
  await expect(pmRow.getByText(msg("jobs-match-partial"), { exact: true })).toBeVisible();
  await expect(pmRow.getByText(msg("jobs-match-exact"))).toHaveCount(0);
  await expect(pmRow.getByText(msg("jobs-match-close"))).toHaveCount(0);
  const closeRow = page.getByRole("article").filter({ hasText: "Content Localization" });
  await expect(closeRow.getByText(msg("jobs-match-close"))).toBeVisible();
});

test("editing the query or a filter collapses the related expansion", async ({ page }) => {
  const jobRequests: string[] = [];
  await searchExact(page, jobRequests);
  await page.getByRole("button", { name: msg("radar-show-other", { count: 2 }) }).click();
  await expect(page.getByRole("heading", { name: /^Other matches/ })).toBeVisible();

  // Query edit: the next request must NOT carry the expansion.
  await page.getByPlaceholder(msg("radar-search-placeholder")).fill("Applied Science Manager");
  await expect
    .poll(() => {
      const last = new URL(jobRequests[jobRequests.length - 1]).searchParams;
      return last.get("q") === "Applied Science Manager" && last.get("include_related");
    })
    .toBe("false");

  // Expand again, then change an explicit filter: same collapse.
  await page.getByRole("button", { name: msg("radar-show-other", { count: 2 }) }).click();
  await expect(page.getByRole("heading", { name: /^Other matches/ })).toBeVisible();
  await page.getByRole("button", { name: /^Filters/ }).click();
  // Every group rests CLOSED: open it, then pick the row.
  await page.getByRole("button", { name: "Company", exact: true }).click();
  await page.getByRole("checkbox", { name: "OpenAI" }).check();
  await expect
    .poll(() => {
      const last = new URL(jobRequests[jobRequests.length - 1]).searchParams;
      return last.get("company") === "openai" && last.get("include_related");
    })
    .toBe("false");
});

test("zero related roles means no disclosure, and a plain query keeps the ordinary list", async ({ page }) => {
  await page.route("/api/jobs?**", (route) => {
    const params = new URL(route.request().url()).searchParams;
    if (params.get("q") === "unique title") {
      return route.fulfill({
        json: { ...exactListResponse(false), related_total: 0 },
      });
    }
    if (params.get("q")) {
      return route.fulfill({
        json: {
          ...twoJobList,
          query_kind: "exploratory",
          related_total: 0,
          related_items: [],
          items: twoJobList.items.map((j) => ({ ...j, match_class: "related", matched_via: ["keyword"] })),
        },
      });
    }
    return route.fulfill({ json: twoJobList });
  });
  await page.goto("/");

  // related_total=0 → exact header, but no disclosure button at all.
  await page.getByPlaceholder(msg("radar-search-placeholder")).fill("unique title");
  await expect(page.getByRole("heading", { name: msg("radar-exact-head", { count: 1 }) })).toBeVisible();
  await expect(page.getByRole("button", { name: /other match/i })).toHaveCount(0);

  // Exploratory response → no exact shell, the ordinary list shape.
  await page.getByPlaceholder(msg("radar-search-placeholder")).fill("manager roles");
  await expect(page.getByText("Principal Engineer, Platform")).toBeVisible();
  await expect(page.getByRole("heading", { name: /Exact match/ })).toHaveCount(0);
});

test("the exact section and disclosure stay usable at mobile width", async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 });
  const jobRequests: string[] = [];
  await searchExact(page, jobRequests);

  // The primary row is not displaced off-screen by the header or disclosure.
  await expect(page.getByRole("heading", { name: msg("radar-exact-head", { count: 1 }) })).toBeInViewport();
  await expect(
    page.getByText("Applied Science Manager, Prime Video Personalization & Discovery")
  ).toBeInViewport();
  await expect(page.getByRole("button", { name: msg("radar-show-other", { count: 2 }) })).toBeInViewport();
});

test("dismissing rows respects the section split: related survives losing the exact row", async ({ page }) => {
  const jobRequests: string[] = [];
  await page.route("/api/jobs/*/feedback", (route) =>
    route.fulfill({ json: { job_id: 401, company: "openai", team: null, department: null } })
  );
  await searchExact(page, jobRequests);
  await page.getByRole("button", { name: msg("radar-show-other", { count: 2 }) }).click();
  await expect(page.getByRole("heading", { name: msg("radar-other-head", { count: 2 }) })).toBeVisible();

  // Dismiss a RELATED row: the related count decrements, the exact row stays.
  const pmRow = page.getByRole("article").filter({ hasText: "Senior Product Manager" });
  await pmRow.getByRole("button", { name: /Not for me/ }).click();
  await expect(page.getByRole("heading", { name: msg("radar-other-head", { count: 1 }) })).toBeVisible();
  await expect(page.getByRole("heading", { name: msg("radar-exact-head", { count: 1 }) })).toBeVisible();

  // Dismiss the EXACT row: the still-populated related section must survive —
  // this page must NOT collapse into the empty state.
  const exactArticle = page.getByRole("article").filter({ hasText: "Personalization & Discovery" });
  await exactArticle.getByRole("button", { name: /Not for me/ }).click();
  await expect(page.getByText("Nothing matches your filters")).toHaveCount(0);
  await expect(page.getByRole("heading", { name: /^Other matches/ })).toBeVisible();
  await expect(page.getByText("Applied Science Manager, Prime Video - Content Localization")).toBeVisible();
});

test("the pager pages the related section only, and a collapsed direct response has no pager", async ({ page }) => {
  const requests: string[] = [];
  await page.route("/api/jobs?**", (route) => {
    requests.push(route.request().url());
    const params = new URL(route.request().url()).searchParams;
    if (params.get("q")) {
      return route.fulfill({
        json: {
          ...exactListResponse(params.get("include_related") === "true"),
          related_total: 60, // 3 pages at limit 20
        },
      });
    }
    return route.fulfill({ json: twoJobList });
  });
  await page.goto("/");
  await page.getByPlaceholder(msg("radar-search-placeholder")).fill("Applied Science Manager, Prime Video Personalization & Discovery");

  // Collapsed: 1 exact row, nothing to page.
  await expect(page.getByRole("heading", { name: msg("radar-exact-head", { count: 1 }) })).toBeVisible();
  await expect(page.getByRole("button", { name: /Next/ })).toHaveCount(0);

  // Expanded: the pager appears with the RELATED count as its authority.
  await page.getByRole("button", { name: msg("radar-show-other", { count: 60 }) }).click();
  await expect(page.getByText("Page 1 of 3")).toBeVisible();
  await page.getByRole("button", { name: "Next", exact: true }).click();
  await expect(page.getByText("Page 2 of 3")).toBeVisible();
  await expect(page.getByRole("heading", { name: msg("radar-exact-head", { count: 1 }) })).toBeVisible();
  await expect.poll(() => requests.some((url) => {
    const params = new URL(url).searchParams;
    return params.get("offset") === "20" && params.get("include_related") === "true";
  })).toBe(true);
  await page.getByRole("button", { name: "Prev", exact: true }).click();
  await expect(page.getByText("Page 1 of 3")).toBeVisible();
});

test("a truncated direct response names the related section, not the exact count", async ({ page }) => {
  await page.route("/api/jobs?**", (route) => {
    const params = new URL(route.request().url()).searchParams;
    if (params.get("q")) {
      return route.fulfill({
        json: {
          ...exactListResponse(false),
          matched: 4000,
          related_total: 1997,
          ranking_truncated: true,
        },
      });
    }
    return route.fulfill({ json: twoJobList });
  });
  await page.goto("/");
  await page.getByPlaceholder(msg("radar-search-placeholder")).fill("Applied Science Manager, Prime Video Personalization & Discovery");

  const note = page.getByRole("note");
  await expect(note).toContainText("Other matches shows the best 1,997 of 4,000");
  // Never the false sentence that counts the exact row as the slice:
  // "Showing the top 1 of 4,000".
  await expect(note).not.toContainText("best 1 of");
});

test("the header lens toggle collapses an open related expansion", async ({ page }) => {
  const jobRequests: string[] = [];
  await searchExact(page, jobRequests);
  await page.getByRole("button", { name: msg("radar-show-other", { count: 2 }) }).click();
  await expect
    .poll(() => new URL(jobRequests[jobRequests.length - 1]).searchParams.get("include_related"))
    .toBe("true");

  // The New-signals lens lives OUTSIDE the filter bar; it must reset the
  // expansion exactly like a filter edit would.
  await page.getByRole("button", { name: "1 new in the last 2 days" }).click();
  await expect
    .poll(() => {
      const last = new URL(jobRequests[jobRequests.length - 1]).searchParams;
      return last.get("new_today_only") === "true" && last.get("include_related");
    })
    .toBe("false");
});

/* Best fit shows the roles at a level we place first, and heads the rest:
   roles whose posting names no level, or a level in the company's
   own terms we have not mapped. The server sends where the second group
   starts (`placed_total`, an index of the whole list); a column sort does not. */
const groupedList = {
  ...twoJobList,
  total: 3,
  ranked_by: "intent",
  placed_total: 1,
  items: [
    jobFixture,
    { ...jobFixture2, title: "Senior Manager, Data Science", level_band: "staff", level_basis: "unmapped" },
    { ...appleJobFixture, title: "Manager, Data Science", level_band: "mid", level_confidence: "unconfirmed", level_basis: "none" },
  ],
};

/** The list's own children, in order: a row by its title, the group head by its class. */
const listOrder = (page: Page) =>
  page.locator(".job-list").first().evaluate((list) =>
    Array.from(list.children).flatMap((child) =>
      child.classList.contains("level-group-head") ? ["HEAD"]
        : child.querySelector(".job-title") ? [child.querySelector(".job-title")!.textContent ?? ""] : []));

test("Best fit heads the roles whose level we cannot place, exactly where they start", async ({ page }) => {
  await page.route("/api/jobs?**", (route) => route.fulfill({ json: groupedList }));
  await page.goto("/");
  await page.getByRole("combobox", { name: "Sort by" }).selectOption("relevance");

  const head = page.getByRole("heading", { name: /Level not placed/ });
  await expect(head).toBeVisible();
  await expect(head).toContainText("2 roles");
  await expect.poll(() => listOrder(page)).toEqual([
    "Staff Product Manager, API", "HEAD", "Senior Manager, Data Science", "Manager, Data Science",
  ]);
  // Each says why: a level we have not mapped is never "not stated".
  const rows = page.locator(".job-row");
  await expect(rows.nth(1).locator(".job-band")).toHaveText("level not mapped");
  await expect(rows.nth(2).locator(".job-band")).toHaveText("level not stated");
});

test("a column sort keeps its own order and draws no group head", async ({ page }) => {
  await page.route("/api/jobs?**", (route) => {
    const sort = new URL(route.request().url()).searchParams.get("sort");
    const { placed_total: _placed, ranked_by: _ranked, ...plain } = groupedList;
    return route.fulfill({ json: sort === "relevance" ? groupedList : plain });
  });
  await page.goto("/");
  await page.getByRole("combobox", { name: "Sort by" }).selectOption("relevance");
  await expect(page.getByRole("heading", { name: /Level not placed/ })).toBeVisible();

  await page.getByRole("combobox", { name: "Sort by" }).selectOption("location");
  await expect(page.getByRole("heading", { name: /Level not placed/ })).toBeHidden();
});
