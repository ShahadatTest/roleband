import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import type { Job } from "../../api";
import { activate } from "../../copy/activate";
import { msg } from "../../test/msg";
import { jobFixture } from "../../test/fixtures";
import { ATTRIBUTES, attributeDiffers, type Attr } from "./attributes";

/* The comparison model. `diff` is what decides whether a row is tinted as a
 * disagreement, so the failure mode that matters is a key too COARSE to tell
 * two values apart — the row then reads "these roles agree" while the cells
 * beside it visibly do not. Each case here is a pair a reader can distinguish. */

const job = (over: Partial<Job>): Job => ({ ...jobFixture, ...over });
const attr = (key: string): Attr => {
  const found = ATTRIBUTES.find((a) => a.key === key);
  if (!found) throw new Error(`no attribute ${key}`);
  return found;
};

describe("comparison attributes", () => {
  it("declares each row once, under a unique key", () => {
    const keys = ATTRIBUTES.map((a) => a.key);
    expect(new Set(keys).size).toBe(keys.length);
    expect(ATTRIBUTES.every((a) => a.label.trim().length > 0)).toBe(true);
  });

  it("a row is tinted only when the roles actually disagree", () => {
    const a = job({ id: 1, level_band: "staff" });
    const b = job({ id: 2, level_band: "staff" });
    expect(attributeDiffers(attr("band"), [a, b])).toBe(false);
    expect(attributeDiffers(attr("band"), [a, job({ id: 3, level_band: "principal" })])).toBe(true);
    // One role cannot disagree with itself, and neither can an empty set.
    expect(attributeDiffers(attr("band"), [a])).toBe(false);
    expect(attributeDiffers(attr("band"), [])).toBe(false);
  });

  it("states nothing the column head above it already states", () => {
    /* Company and Title head every column, so as rows they would carry no
       information the reader had not just read. Named keys rather than a
       count: a row can be added, but not one of these two. */
    expect(ATTRIBUTES.map((a) => a.key)).not.toContain("company");
    expect(ATTRIBUTES.map((a) => a.key)).not.toContain("title");
    expect(ATTRIBUTES[0].label).toBe("Level");
  });

  it.each([
    ["locations", { locations: ["San Francisco, CA"] }, { locations: ["London, UK"] }],
    ["regions", { location_groups: ["silicon_valley"] }, { location_groups: ["uk"] }],
    ["comp", { comp_median: 735000 }, { comp_median: 512000 }],
    ["band", { level_band: "staff" }, { level_band: "principal" }],
    ["listed", { listed_days: 1 }, { listed_days: 90 }],
    ["reposts", { repost_count: 0 }, { repost_count: 4 }],
    ["status", { status: "open" }, { status: "closed" }],
    ["workplace", { workplace_type: "hybrid" }, { workplace_type: "remote" }],
  ])("%s: values of equal SHAPE but different content still read as a difference", (key, one, two) => {
    // A length- or presence-based key would pass "same shape" and miss this.
    expect(attributeDiffers(attr(key), [job(one), job(two)])).toBe(true);
    expect(attributeDiffers(attr(key), [job(one), job(one)])).toBe(false);
  });

  it("an ordered multi-value list is compared by its values, not by its size", () => {
    const two = job({ locations: ["Zurich, CH", "Munich, DE"] });
    const other = job({ locations: ["Austin, TX", "Seattle, WA"] });
    expect(attributeDiffers(attr("locations"), [two, other])).toBe(true);
  });

  it("a missing comp median is one value, not a wildcard that matches anything", () => {
    const none = job({ comp_median: null });
    const some = job({ comp_median: 735000 });
    expect(attributeDiffers(attr("comp"), [none, some])).toBe(true);
    expect(attributeDiffers(attr("comp"), [none, job({ comp_median: null })])).toBe(false);
  });

  describe("the status row", () => {
    afterEach(() => activate("en"));
    const shown = (status: string) => render(<>{attr("status").render(job({ status }))}</>).container;

    it("says a posting's status in the reader's words, as the role page does", async () => {
      expect(shown("closed")).toHaveTextContent(msg("role-job-status-closed"));
      await activate("es");
      const spanish = shown("open");
      expect(spanish).toHaveTextContent(msg("role-job-status-open"));
      expect(msg("role-job-status-open")).not.toBe("open");
      expect(spanish.textContent).not.toBe("open");
    });

    it("shows a status it has no word for as the code, marked as not RoleBand's words", () => {
      shown("paused");
      expect(screen.getByText("paused")).toHaveAttribute("data-copy", "content");
    });
  });

  it("every attribute renders something for a role with nothing filled in", () => {
    const bare = job({ locations: [], location_groups: [], comp_low: null, comp_high: null, comp_median: null, listed_days: null, listed_since: null });
    for (const a of ATTRIBUTES) {
      expect(() => a.render(bare), a.key).not.toThrow();
      expect(typeof a.diff(bare), a.key).toBe("string");
    }
  });
});
