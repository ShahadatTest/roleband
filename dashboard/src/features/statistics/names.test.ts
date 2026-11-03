// What the Statistics screens name from slugs: a cluster by its
// skills, an age band by its lower bound, and the Overview's one-line brief.
import { afterEach, describe, expect, it } from "vitest";
import { activate } from "../../copy/activate";
import { agingBandName, clusterLabel, overviewBrief } from "./names";

afterEach(() => activate("en"));

describe("clusterLabel", () => {
  it("names a cluster by its three strongest skills, then its family, then says it has none", () => {
    expect(clusterLabel({ terms: ["python", "sql", "kubernetes", "aws"], family_hint: "data_science" })).toBe("Python · SQL · Kubernetes");
    expect(clusterLabel({ top_terms: [{ term: "rust" }], family_hint: null })).toBe("Rust");
    expect(clusterLabel({ terms: [], family_hint: "product_management" })).toBe("Product Management");
    expect(clusterLabel({ terms: [], family_hint: null })).toBe("Unlabeled cluster");
  });
});

describe("agingBandName", () => {
  it("names each fixed band by its lower bound", () => {
    expect([0, 7, 14, 30, 60, 90].map(agingBandName)).toEqual([
      "< 1 week", "1–2 weeks", "2–4 weeks", "1–2 months", "2–3 months", "3 months+",
    ]);
  });
});

describe("overviewBrief", () => {
  const kpis = { open_total: 3192, companies: 41, new_count: 120, closed_count: 30, first_scan_count: 0, saved_total: 0 };

  it("says the facts the server's brief said, with the region's digits", async () => {
    await activate("en", { region: "en-US" });
    const data = {
      days: 30, kpis: { ...kpis, first_scan_count: 12 },
      top_skills: [{ term: "python", category: "language", job_count: 1435 }],
      top_clusters: [{ id: 1, family_hint: null, terms: ["python", "sql"], size: 88 }],
    };
    // The roles already listed at a company's first scan are when the
    // radar first looked, not the market: neither view says them.
    expect(overviewBrief(data)).toBe(
      "3,192 open roles across 41 companies. 120 opened in 30d, 30 closed. "
      + "Top skill: Python (1,435 roles).",
    );
    // The groups are an advanced tab, so only the advanced view names one.
    expect(overviewBrief(data, true)).toBe(
      "3,192 open roles across 41 companies. 120 opened in 30d, 30 closed. "
      + "Top skill: Python (1,435 roles). Largest group: Python · SQL (88).",
    );
  });

  it("leaves out a fact that is not there, and says all-time for no window", () => {
    expect(overviewBrief({ days: 0, kpis, top_skills: [], top_clusters: [] })).toBe(
      "3,192 open roles across 41 companies. 120 opened all-time, 30 closed.",
    );
  });
});
