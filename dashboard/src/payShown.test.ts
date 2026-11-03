import { describe, expect, it } from "vitest";
import { baseShown, payPoint, payShown } from "./payShown";
import { msg } from "./test/msg";

describe("the pay a posting shows (plugin plan P2)", () => {
  const none = { comp_low: null, comp_high: null, comp_median: null };

  it("shows a total when one is estimated, and never its base beside it", () => {
    const shown = payShown({ comp_low: 340000, comp_high: 460000, comp_median: 400000, comp_base_median: 200000 });
    expect(shown).toEqual({ text: "$340K–$460K", base: false });
  });

  it("shows an estimated base, labelled, when no total is known", () => {
    const shown = payShown({ ...none, comp_base_low: 170000, comp_base_high: 230000, comp_base_median: 200000 });
    expect(shown.base).toBe(true);
    expect(shown.text).toBe(msg("shared-pay-est-base", { range: "$170K–$230K" }));
    expect(shown.hint).toBe(msg("shared-pay-est-base-hint"));
  });

  it("shows nothing when nothing is estimated", () => {
    expect(payShown(none)).toEqual({ text: "—", base: false });
  });

  describe("while a plugin answers pay", () => {
    const cover = { plugin: "ladder", name: "Example ladder data", companies: new Set(["acme"]) };

    it("says a company it has not read is not covered, never a bare dash", () => {
      const shown = payShown({ ...none, company: "globex" }, cover);
      expect(shown.text).toBe(msg("shared-pay-not-covered", { plugin: "Example ladder data" }));
      expect(shown.notCovered).toBe(true);
      expect(shown.hint).toBe(msg("shared-pay-not-covered-hint", { plugin: "Example ladder data" }));
    });

    it("a company it has read but gave no figure for is a dash: read, and nothing to say", () => {
      expect(payShown({ ...none, company: "acme" }, cover)).toEqual({ text: "—", base: false });
    });

    it("a figure always shows, and ours answering says nothing of coverage", () => {
      expect(payShown({ comp_low: 1, comp_high: 3, comp_median: 2, company: "globex" }, cover).notCovered)
        .toBeUndefined();
      expect(payShown({ ...none, company: "globex" }, null)).toEqual({ text: "—", base: false });
    });
  });
});


describe("the pay a compact row shows: one figure", () => {
  const none = { comp_low: null, comp_high: null, comp_median: null };

  it("is the median for a total, never a range", () => {
    expect(payPoint({ comp_low: 340000, comp_high: 460000, comp_median: 400000 })).toEqual({ text: "$400K", base: false });
  });

  it("labels a base that stands alone as a base estimate", () => {
    const shown = payPoint({ ...none, comp_base_low: 170000, comp_base_high: 230000, comp_base_median: 200000 });
    expect(shown.base).toBe(true);
    expect(shown.text).toBe(msg("shared-pay-est-base", { range: "$200K" }));
  });

  it("says nothing is estimated with a dash, and a company the plugin has not read as such", () => {
    expect(payPoint(none)).toEqual({ text: "—", base: false });
    const cover = { plugin: "ladder", name: "Example ladder data", companies: new Set(["acme"]) };
    expect(payPoint({ ...none, company: "globex" }, cover).notCovered).toBe(true);
  });
});


describe("the base a role list's Base column shows", () => {
  const cover = { plugin: "ladder", name: "Example ladder data", companies: new Set(["anthropic"]) };
  const posted = (min: number | null, max: number | null) =>
    ({ min, max, currency: "USD", period: "year" as const });

  it("says why a company the pay plugin has not read shows no base", () => {
    const shown = baseShown({ company: "openai", comp_base_median: null, posted_base: null }, cover);
    expect(shown.text).toBe("");
    expect(shown.hint).toBe(msg("shared-pay-not-covered-hint", { plugin: "Example ladder data" }));
  });

  it("still shows a posted range at a company the plugin has not read: the posting is a fact", () => {
    expect(baseShown({ company: "openai", comp_base_median: null, posted_base: posted(150_000, 200_000) }, cover).text)
      .toBe("$150K+");
  });

  it("reads a range with only one bound as that one figure", () => {
    expect(baseShown({ posted_base: posted(null, 160_000) }).text).toBe("$160K");
  });

  it("writes no plus for a range whose two ends read as the same figure", () => {
    const shown = baseShown({ posted_base: posted(199_600, 200_400) });
    expect(shown.text).toBe("$200K");
    expect(shown.hint).toBe(msg("shared-base-posted-point-hint", { amount: "$200K", unit: "" }));
  });
});
