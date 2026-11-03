import { describe, expect, it } from "vitest";
import { brandInk, contrast, luminance, parseHex } from "./brandColor";

// The surfaces brandInk targets. Duplicated here on purpose: if someone edits the
// constant in brandColor.ts, these tests should fail rather than silently follow.
const LIGHT = "#ffffff";
const DARK = "#141416";
const MIN = 3;

describe("parseHex", () => {
  it("accepts 6-digit, 3-digit, and bare forms", () => {
    expect(parseHex("#4285F4")).toEqual([66, 133, 244]);
    expect(parseHex("4285F4")).toEqual([66, 133, 244]);
    expect(parseHex("#fff")).toEqual([255, 255, 255]);
  });

  it("rejects malformed input instead of coercing it", () => {
    for (const bad of ["", "#12345", "#gggggg", "rgb(1,2,3)", "#1234567"]) {
      expect(parseHex(bad)).toBeNull();
    }
  });
});

describe("luminance", () => {
  it("linearises channels — the midpoint is not 0.5", () => {
    // sRGB #808080 is ~0.216 relative luminance. A version that skipped
    // gamma-decoding would return ~0.5, which is the classic bug this guards.
    expect(luminance([128, 128, 128])).toBeCloseTo(0.216, 2);
  });

  it("weights green above red above blue", () => {
    const [r, g, b] = [
      luminance([255, 0, 0]),
      luminance([0, 255, 0]),
      luminance([0, 0, 255]),
    ];
    expect(g).toBeGreaterThan(r);
    expect(r).toBeGreaterThan(b);
  });
});

describe("contrast", () => {
  it("spans the full WCAG range", () => {
    expect(contrast("#000000", "#ffffff")).toBeCloseTo(21, 1);
    expect(contrast("#ffffff", "#ffffff")).toBeCloseTo(1, 5);
  });

  it("is symmetric", () => {
    expect(contrast("#4285F4", DARK)).toBeCloseTo(contrast(DARK, "#4285F4"), 6);
  });
});

describe("brandInk", () => {
  // Real hexes straight out of Simple Icons, including the ones that motivated
  // this helper.
  const BRANDS = {
    apple: "#000000",
    anthropic: "#191919",
    github: "#181717",
    google: "#4285F4",
    netflix: "#E50914",
    nvidia: "#76B900",
    spotify: "#1ED760",
    snowflake: "#29B5E8",
    stripe: "#635BFF",
  };

  it("clears the 3:1 non-text floor for every brand on both themes", () => {
    for (const [name, hex] of Object.entries(BRANDS)) {
      for (const [theme, surface] of [
        ["light", LIGHT],
        ["dark", DARK],
      ] as const) {
        const got = contrast(brandInk(hex, theme), surface);
        expect(got, `${name} on ${theme}`).toBeGreaterThanOrEqual(MIN);
      }
    }
  });

  it("lifts near-black brands on dark, where they would otherwise vanish", () => {
    // The whole reason this function exists: Apple/Anthropic/GitHub sit within a
    // few points of the dark card and are invisible untreated.
    for (const hex of [BRANDS.apple, BRANDS.anthropic, BRANDS.github]) {
      expect(contrast(hex, DARK)).toBeLessThan(MIN);
      expect(brandInk(hex, "dark")).not.toBe(hex);
      expect(contrast(brandInk(hex, "dark"), DARK)).toBeGreaterThanOrEqual(MIN);
    }
  });

  it("leaves already-legible brands byte-identical", () => {
    // Fidelity matters: a helper that "corrected" every colour would quietly
    // restyle brands that were fine.
    expect(brandInk(BRANDS.google, "dark")).toBe("#4285f4");
    expect(brandInk(BRANDS.nvidia, "dark")).toBe("#76b900");
    expect(brandInk(BRANDS.netflix, "light")).toBe("#e50914");
  });

  it("preserves hue when it does adjust", () => {
    // Spotify green fails on white and must come back still green — not grey,
    // not black.
    const out = parseHex(brandInk(BRANDS.spotify, "light"))!;
    const [r, g, b] = out;
    expect(g).toBeGreaterThan(r);
    expect(g).toBeGreaterThan(b);
  });

  it("adjusts in the correct direction per theme", () => {
    // Dark theme must lighten, light theme must darken. A sign error here would
    // still pass a naive "did it change?" assertion.
    const onDark = parseHex(brandInk(BRANDS.apple, "dark"))!;
    expect(onDark[0]).toBeGreaterThan(0);

    const before = parseHex(BRANDS.spotify)!;
    const after = parseHex(brandInk(BRANDS.spotify, "light"))!;
    expect(luminance(after)).toBeLessThan(luminance(before));
  });

  it("degrades to currentColor on unparseable input rather than throwing", () => {
    expect(brandInk("not-a-colour", "dark")).toBe("currentColor");
  });
});
