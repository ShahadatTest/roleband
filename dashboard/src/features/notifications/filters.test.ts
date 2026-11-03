import { describe, expect, it } from "vitest";
import {
  CATEGORIES,
  RESET_LENS_PARAMS,
  ROLE_CATEGORIES,
  SYNC_CATEGORIES,
  categoryLabel,
  countActiveNotificationFilters,
  facetEntries,
  splitCategories,
} from "./filters";

describe("notification filter semantics", () => {
  it("counts one per lens off its default and one per chosen category", () => {
    expect(countActiveNotificationFilters({ status: "all", priority: "", categories: [] })).toBe(0);
    expect(countActiveNotificationFilters({ status: "unread", priority: "", categories: [] })).toBe(1);
    expect(
      countActiveNotificationFilters({ status: "unread", priority: "high", categories: ["a", "b"] }),
    ).toBe(4);
  });

  /* The query is the context the count is measured in, not a narrowing of
     it: the Board's `q: queryContext`. It is also what keeps the folded opener
     honest: this number is the "Filters · N" badge, and counting a typed query
     would claim an active filter while the panel behind the opener held
     nothing. */
  it("does not count the search query, whatever its shape", () => {
    expect(countActiveNotificationFilters({ status: "all", priority: "", categories: [] })).toBe(0);
    // The signature is the proof: a query has no way in. The reset scope
    // agrees — only lens params are deleted.
    expect([...RESET_LENS_PARAMS]).toEqual(["status", "priority", "category"]);
    expect([...RESET_LENS_PARAMS]).not.toContain("q");
  });

  it("splits a mixed selection into its two facet groups without dropping either half", () => {
    const { sync, role } = splitCategories(["closed", "sync_failed", "daily_digest", "sync_warning"]);
    expect(sync).toEqual(["sync_failed", "sync_warning"]);
    expect(role).toEqual(["closed", "daily_digest"]);
    // Every declared category lands in exactly one group.
    const all = CATEGORIES.map(([id]) => id);
    const split = splitCategories(all);
    expect([...split.sync, ...split.role].sort()).toEqual([...all].sort());
    expect(split.sync).toEqual(SYNC_CATEGORIES.map(([id]) => id));
    expect(split.role).toEqual(ROLE_CATEGORIES.map(([id]) => id));
  });

  it("labels a known category from the taxonomy and de-slugs an unknown one", () => {
    expect(categoryLabel("daily_digest")).toBe("For you");
    expect(categoryLabel("pursuit_due")).toBe("Reminders");
    // A followed company RoleBand cannot scan cleanly. Operational, so
    // it filters with the scan group, not with the roles.
    expect(categoryLabel("coverage")).toBe("Coverage");
    expect(splitCategories(["coverage", "closed"])).toEqual({ sync: ["coverage"], role: ["closed"] });
    // A scan that only ran out of RoleBand's own time files with the
    // scans under its own name, so "Scan problems" counts only problems.
    expect(categoryLabel("sync_unfinished")).toBe("Ran out of time");
    expect(splitCategories(["sync_unfinished"])).toEqual({ sync: ["sync_unfinished"], role: [] });
    expect(facetEntries(SYNC_CATEGORIES, { sync_unfinished: 4, sync_warning: 1 })
      .filter((e) => e.count > 0)
      .map((e) => [e.display, e.count])).toEqual([["Scan problems", 1], ["Ran out of time", 4]]);
    // A stored category outside the taxonomy falls through to the de-slugger
    // rather than crashing, so every stored row still renders.
    expect(categoryLabel("high_comp_match")).toBe("high comp match");
  });

  /* The taxonomy, asserted as a set so a category cannot join it unnoticed.
     Per-role match news is the digest's, and the backend writes none of
     `scraper_health`/`sync_success`/`duplicate_listing`. */
  it("no longer offers a facet for a category the backend stopped writing", () => {
    const all = CATEGORIES.map(([id]) => id);
    for (const retired of [
      "new_match",
      "high_comp_match",
      "scraper_health",
      "sync_success",
      "duplicate_listing",
    ]) {
      expect(all).not.toContain(retired);
    }
    expect(all).toContain("daily_digest");
    expect(all).toContain("pursuit_due");
  });

  it("gives every facet entry a count, zero when the server did not report one", () => {
    const entries = facetEntries(SYNC_CATEGORIES, { sync_failed: 3 });
    expect(entries.find((e) => e.slug === "sync_failed")).toEqual({
      slug: "sync_failed",
      display: "Scan failed",
      count: 3,
    });
    expect(entries.every((e) => typeof e.count === "number")).toBe(true);
    expect(entries.find((e) => e.slug === "sync_warning")?.count).toBe(0);
    expect(facetEntries(SYNC_CATEGORIES, undefined).every((e) => e.count === 0)).toBe(true);
  });
});
