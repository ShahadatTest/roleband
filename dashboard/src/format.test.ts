import { msg } from "./test/msg";
import { shellBellUnread, shellRailPending as pending } from "./copy/gen/shell";
import { describe, expect, it } from "vitest";
import { COUNTRY_LABEL } from "./locations.gen";
import { COUNT_BADGE_MAX, LOC_LABEL, companyName, countBadge, fmtComp, fmtRange, formatWhen, freshnessLabel, relDays, setCompanyNames } from "./format";

describe("format helpers", () => {
  it("formats compensation values without hiding unknown values", () => {
    expect(fmtComp(null)).toBe("—");
    expect(fmtComp(950)).toBe("$950");
    expect(fmtComp(650000)).toBe("$650K");
    expect(fmtComp(1250000)).toBe("$1.25M");
    expect(fmtComp(1000000)).toBe("$1M");
  });

  it("prefers explicit ranges, then median, then unknown", () => {
    expect(fmtRange(650000, 820000, 735000)).toBe("$650K–$820K");
    expect(fmtRange(null, null, 735000)).toBe("$735K");
    expect(fmtRange(null, null, null)).toBe("—");
  });

  /* The rule the `99+` badge broke: a badge either states a real count or
     stops claiming to be one. `99+` did neither — it was a number-shaped
     string that stayed put while the queue moved. */
  it("shows a real count up to the cap", () => {
    expect(countBadge(1, pending).text).toBe("1");
    expect(countBadge(COUNT_BADGE_MAX, pending).text).toBe("99");
    expect(countBadge(COUNT_BADGE_MAX, pending).dot).toBe(false);
  });

  it("drops to a dot past the cap instead of a saturated number", () => {
    const over = countBadge(COUNT_BADGE_MAX + 1, pending);
    expect(over.dot).toBe(true);
    expect(over.text).toBeNull();
    // The specific regression: nothing renders "99+" any more.
    expect(over.text).not.toBe("99+");
  });

  it("keeps the exact count reachable at every size", () => {
    // The dot's whole cost is the magnitude, so the number has to survive in
    // the string the caller hangs on the tooltip and the accessible name.
    expect(countBadge(342, pending).label).toBe("342 pending");
    expect(countBadge(7, shellBellUnread).label).toBe("7 unread");
    // Grouped by the region inside the message; the digits are the assertion.
    expect(countBadge(1204, pending).label).toMatch(/^1\D?204 pending$/);
  });

  it("labels day counts in user-facing language", () => {
    expect(relDays(null)).toBe("—");
    expect(relDays(0)).toBe("today");
    expect(relDays(1)).toBe("1 day");
    expect(relDays(12)).toBe("12 days");
  });

  it("falls back to raw company slugs for unknown providers", () => {
    expect(companyName("openai")).toBe("OpenAI");
    // amazon was missing from the old hardcoded map and rendered as its raw slug.
    expect(companyName("amazon")).toBe("Amazon");
    expect(companyName("new-provider")).toBe("new-provider");
    // A directory company can be called anything; `Object.name` is "Object".
    expect(companyName("constructor")).toBe("constructor");
    expect(companyName("toString")).toBe("toString");
  });

  // The built-in table names a few companies; every other one would print as
  // its slug without the tracked names.
  it("names a company as the tracked roster does, before the built-ins and the slug", () => {
    expect(companyName("pwc")).toBe("pwc");
    setCompanyNames({ pwc: "PwC", "palo-alto-networks": "Palo Alto Networks", openai: "OpenAI" });
    expect(companyName("pwc")).toBe("PwC");
    expect(companyName("palo-alto-networks")).toBe("Palo Alto Networks");
    expect(companyName("openai")).toBe("OpenAI");
    // A slug the roster does not name still falls back, built-in first.
    expect(companyName("amazon")).toBe("Amazon");
    expect(companyName("new-provider")).toBe("new-provider");
    expect(companyName("constructor")).toBe("constructor");
  });

  it("keeps scan activity separate from idle data age", () => {
    const idle = (scan: number | null, oldest: number | null, stale: boolean, unread: unknown[] = []) => ({
      running: false, last_scan_age_hours: scan, last_success_age_hours: oldest, stale,
      freshness_max_hours: 26, scheduler: { unread },
    });
    expect(freshnessLabel(null)).toEqual({ text: "—", tone: "unknown" });
    expect(freshnessLabel(idle(null, null, true))).toEqual({ text: msg("shell-freshness-never"), tone: "unknown" });
    for (const age of [null, 0.01, 50]) {
      expect(freshnessLabel({ ...idle(age, age, true), running: true })).toEqual({
        text: msg("shell-scan-scanning"), tone: "unknown",
      });
    }
    expect(freshnessLabel(idle(3, 3, false))).toEqual({
      text: msg("shell-freshness-checked", { age: msg("format-age-hours", { count: 3 }) }), tone: "fresh",
    });
    expect(freshnessLabel(idle(50, 50, true))).toEqual({
      text: msg("shell-freshness-checked", { age: msg("format-age-days", { count: 2 }) }), tone: "stale",
    });
    // One company unread for three days beside a scan 15 minutes ago.
    expect(freshnessLabel(idle(0.25, 75, true, [{ company: "shopify" }]))).toEqual({
      text: msg("shell-freshness-behind", { age: msg("format-age-minutes", { count: 15 }), count: 1 }),
      tone: "behind",
    });
    // Scans stopped: red however few companies are behind.
    expect(freshnessLabel(idle(30, 75, true, [{ company: "shopify" }])).tone).toBe("stale");
    // A status from before the field existed reads the oldest scan's age.
    expect(freshnessLabel(idle(null, 3, false)).text)
      .toBe(msg("shell-freshness-checked", { age: msg("format-age-hours", { count: 3 }) }));
    expect(freshnessLabel(idle(0.25, 0.25, false)).text)
      .toBe(msg("shell-freshness-checked", { age: msg("format-age-minutes", { count: 15 }) }));
    expect(freshnessLabel(idle(0.001, 0.001, false)).text)
      .toBe(msg("shell-freshness-checked", { age: msg("format-age-just-now") }));
  });
});


describe("LOC_LABEL", () => {
  // The map this replaced was hand-copied and had already drifted: 17 of 19
  // groups, so `europe` and `london` rendered as raw slugs to users. With 196
  // countries a hand-maintained copy is not a risk, it is a certainty.
  it("labels every generated country without a hand-written entry", () => {
    for (const slug of Object.keys(COUNTRY_LABEL)) {
      expect(LOC_LABEL[slug], slug).toBeTruthy();
      expect(LOC_LABEL[slug], slug).not.toBe(slug);
    }
  });

  it("labels the groups that are RoleBand's own, not ISO countries", () => {
    // Metros and regions have no country row, so they are the only entries
    // still written by hand — and the ones most likely to be forgotten.
    for (const slug of ["silicon_valley", "london", "europe", "gulf", "south_asia", "oceania"]) {
      expect(LOC_LABEL[slug], slug).toBeTruthy();
      expect(LOC_LABEL[slug], slug).not.toBe(slug);
    }
  });

  it("keeps the short form where a badge needs it", () => {
    // The generated name is "United Kingdom"; a badge wants "UK".
    expect(LOC_LABEL.uk).toBe("UK");
    expect(LOC_LABEL.uae).toBe("United Arab Emirates");
  });
});


describe("one grammar for a moment: the settings registers and the freshness tooltip (R14)", () => {
  it("formats a moment with the weekday by default, without it on request", () => {
    const iso = "2026-10-04T09:05:00Z";
    const at = new Date(iso);
    expect(formatWhen(iso)).toBe(
      at.toLocaleString(undefined, { weekday: "short", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }),
    );
    expect(formatWhen(iso, { weekday: false })).toBe(
      at.toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }),
    );
    expect(formatWhen(iso)).not.toBe(formatWhen(iso, { weekday: false }));
  });
});
