import { afterEach, describe, expect, it } from "vitest";
import type { DisclosureRates, DisclosureTrendPoint, DisclosureTrendSeries } from "../../../api";
import { activate } from "../../../copy/activate";
import { msg } from "../../../test/msg";
import {
  bandTrendSummary,
  buildBandTrendOption,
  buildDisclosureRateOption,
  buildDisclosureRateTrendOption,
  disclosureRateRows,
  disclosureRateSummary,
  disclosureTrendSummary,
  unratedCount,
} from "./disclosure";

const rates = (over: Partial<DisclosureRates> = {}): DisclosureRates => ({
  overall: { open: 100, checked: 80, disclosed: 40, rate: 0.5 },
  by_company: [
    { company: "google", open: 50, checked: 50, disclosed: 40, rate: 0.8 },
    { company: "meta", open: 30, checked: 30, disclosed: 0, rate: 0 },
    // Nothing checked yet -> no rate can be stated for this employer.
    { company: "openai", open: 20, checked: 0, disclosed: 0, rate: null },
  ],
  by_level: [
    { level_band: "senior", open: 60, checked: 50, disclosed: 30, rate: 0.6 },
    { level_band: "staff", open: 40, checked: 30, disclosed: 10, rate: 0.3333 },
  ],
  ...over,
});

const point = (over: Partial<DisclosureTrendPoint> = {}): DisclosureTrendPoint => ({
  date: "2026-07-20",
  open: 100,
  checked: 80,
  disclosed: 40,
  rate: 0.5,
  bands: 4,
  reqs: 30,
  low_p50: 200_000,
  high_p50: 300_000,
  ...over,
});

const series = (over: Partial<DisclosureTrendSeries> = {}): DisclosureTrendSeries => ({
  key: "",
  
  checked: 80,
  disclosed: 40,
  points: [point()],
  ...over,
});

const opt = (o: unknown) => o as Record<string, any>;

describe("disclosureRateRows", () => {
  it("drops groups with no rate instead of drawing them at zero", () => {
    // "We have not checked openai yet" and "openai publishes nothing" are
    // different findings; a 0% bar would assert the second from the first.
    const rows = disclosureRateRows(rates(), "company");

    expect(rows.map((r) => r.key)).toEqual(["meta", "google"]);
    expect(unratedCount(rates(), "company")).toBe(1);
    // A checked employer that genuinely discloses nothing IS drawn at 0%.
    expect(rows.find((r) => r.key === "meta")!.rate).toBe(0);
  });

  it("ranks the lowest rate first and applies display names", () => {
    const rows = disclosureRateRows(
      rates({
        by_company: [
          { company: "google", open: 10, checked: 10, disclosed: 9, rate: 0.9 },
          { company: "apple", open: 5, checked: 5, disclosed: 1, rate: 0.2 },
          { company: "meta", open: 10, checked: 10, disclosed: 2, rate: 0.2 },
        ],
      }),
      "company",
    );
    // Equal rates: the employer with more checked roles first.
    expect(rows.map((r) => r.label)).toEqual(["Meta", "Apple", "Google"]);
  });

  it("puts the first row on top and every tooltip on its own bar", () => {
    const rows = disclosureRateRows(
      rates({
        by_company: [
          { company: "google", open: 10, checked: 10, disclosed: 9, rate: 0.9 },
          { company: "meta", open: 10, checked: 10, disclosed: 0, rate: 0 },
          { company: "apple", open: 10, checked: 10, disclosed: 5, rate: 0.5 },
        ],
      }),
      "company",
    );
    const option = opt(buildDisclosureRateOption(rows));
    const labels: string[] = option.yAxis.data;
    // ECharts draws category 0 at the bottom: the lowest rate is the last.
    expect(labels[labels.length - 1]).toBe("Meta");
    labels.forEach((label, dataIndex) => {
      const box = document.createElement("div");
      box.innerHTML = option.tooltip.formatter({ dataIndex });
      expect(box.querySelector("strong")?.textContent).toBe(label);
    });
  });

  it("labels level bands and names the unclassified bucket", () => {
    const rows = disclosureRateRows(
      rates({
        by_level: [{ level_band: "", open: 5, checked: 5, disclosed: 1, rate: 0.2 }],
      }),
      "level",
    );
    expect(rows[0].label).toBe("Unclassified");
  });

  it("names the roles whose level we cannot place as such, never as a rung", () => {
    const rows = disclosureRateRows(
      rates({
        by_level: [
          { level_band: "principal", open: 5, checked: 5, disclosed: 4, rate: 0.8 },
          { level_band: "unstated", open: 9, checked: 6, disclosed: 3, rate: 0.5 },
        ],
      }),
      "level",
    );
    expect(rows.map((r) => r.label)).toEqual(["Level not placed", "Principal"]);
  });
});

describe("buildDisclosureRateOption", () => {
  it("scales the axis 0-100%, never to the leading employer", () => {
    // Auto-scaling a share makes 12% look like a full bar.
    const option = opt(buildDisclosureRateOption(disclosureRateRows(rates(), "company")));

    expect(option.xAxis.min).toBe(0);
    expect(option.xAxis.max).toBe(100);
  });

  it("plots percentages, and pairs each bar with its raw counts", () => {
    const option = opt(buildDisclosureRateOption(disclosureRateRows(rates(), "company")));
    const bar = option.series[0];

    // Categories are reversed so the lowest rate sits on top.
    expect(option.yAxis.data).toEqual(["Google", "Meta"]);
    expect(bar.data).toEqual([80, 0]);
    expect(bar.label.formatter({ dataIndex: 0 })).toBe("80% · 40/50");
  });

  it("tooltips the denominator, not just the share", () => {
    const option = opt(buildDisclosureRateOption(disclosureRateRows(rates(), "company")));
    expect(option.tooltip.formatter({ dataIndex: 0 })).toContain("40 of 50 checked open roles");
  });
});

describe("disclosureRateSummary", () => {
  it("states each group's share and counts, and flags the unrated ones", () => {
    const rows = disclosureRateRows(rates(), "company");
    const text = disclosureRateSummary(rows, 1);

    expect(text).toContain("Google: 80%, 40 of 50 roles");
    expect(text).toMatch(/1 more group has no role checked yet/);
  });

  it("omits the unrated note when every group has a rate", () => {
    expect(disclosureRateSummary(disclosureRateRows(rates(), "level"), 0)).not.toMatch(
      /no role checked/,
    );
  });

  it("handles a window where nothing has been checked", () => {
    expect(disclosureRateSummary([], 0)).toMatch(/no open roles have been checked/i);
  });
});

describe("buildDisclosureRateTrendOption", () => {
  it("plots the rate as a percentage on a fixed 0-100 axis", () => {
    const option = opt(
      buildDisclosureRateTrendOption("overall", ["2026-07-20", "2026-07-21"], [
        series({ points: [point({ rate: 0.5 }), point({ date: "2026-07-21", rate: 0.62 })] }),
      ]),
    );

    expect(option.yAxis.min).toBe(0);
    expect(option.yAxis.max).toBe(100);
    expect(option.series[0].data).toEqual([50, 62]);
    expect(option.series[0].type).toBe("line");
  });

  it("leaves a gap on a day with nothing checked rather than dropping to zero", () => {
    const option = opt(
      buildDisclosureRateTrendOption("overall", ["2026-07-20", "2026-07-21"], [
        series({
          points: [point({ rate: null, checked: 0 }), point({ date: "2026-07-21", rate: 0.5 })],
        }),
      ]),
    );

    expect(option.series[0].data).toEqual([null, 50]);
    // connectNulls would draw straight through the unknown day as if measured.
    expect(option.series[0].connectNulls).toBe(false);
  });

  it("shows a legend only when there is more than one grouping", () => {
    const one = opt(buildDisclosureRateTrendOption("overall", ["2026-07-20"], [series()]));
    const many = opt(
      buildDisclosureRateTrendOption("company", ["2026-07-20"], [
        series({ key: "google" }),
        series({ key: "meta" }),
      ]),
    );

    expect(one.legend.show).toBe(false);
    expect(many.series.map((s: any) => s.name)).toEqual(["Google", "Meta"]);
  });

  it("names and dashes the fixed cohort beside the market line", () => {
    const option = opt(
      buildDisclosureRateTrendOption("overall", ["2026-07-20"], [
        series(),
        series({ key: "cohort", }),
      ]),
    );

    expect(option.legend.show).not.toBe(false);
    expect(option.series.map((s: any) => [s.name, s.lineStyle.type])).toEqual([
      ["Market", "solid"],
      ["Same companies", "dashed"],
    ]);
  });
});

describe("disclosureTrendSummary", () => {
  it("reports the latest share with its denominator and where it started", () => {
    const text = disclosureTrendSummary("overall", ["2026-07-20", "2026-07-21"], [
      series({
        points: [point({ rate: 0.4 }), point({ date: "2026-07-21", rate: 0.62, checked: 90 })],
      }),
    ]);

    expect(text).toContain("Market: 62% of 90 checked roles post a range (from 40%)");
  });

  it("says so when a grouping has no checked roles at all", () => {
    const text = disclosureTrendSummary("company", ["2026-07-20"], [
      series({ key: "openai", points: [point({ rate: null, checked: 0 })] }),
    ]);
    expect(text).toContain("OpenAI: no roles checked yet");
  });

  it("handles empty history", () => {
    expect(disclosureTrendSummary("overall", [], [])).toMatch(/no pay-transparency history/i);
  });

  describe("in another language", () => {
    afterEach(() => activate("en"));

    it("names the grouping in the reader's words, never an English noun", async () => {
      await activate("es");
      // The sentence up to its per-series lines, as the reader's language says it for that grouping.
      const opening = (dim: "level" | "company") =>
        msg("insights-disclosure-share-of-open-roles-stating", { dim, span: "day", first: "2026-07-20", last: "2026-07-20", lines: "|" }).split("|")[0];
      const byLevel = disclosureTrendSummary("level", ["2026-07-20"], [series({ key: "staff" })]);
      expect(byLevel.startsWith(opening("level"))).toBe(true);
      expect(byLevel).not.toMatch(/seniority|level/);
      const byCompany = disclosureTrendSummary("company", ["2026-07-20"], [series({ key: "openai" })]);
      expect(byCompany.startsWith(opening("company"))).toBe(true);
      expect(byCompany).not.toMatch(/employer|company/);
      expect(opening("level")).not.toBe(opening("company"));
    });
  });
});

describe("buildBandTrendOption", () => {
  it("draws the floor-to-ceiling span from the floor, not from zero", () => {
    const option = opt(
      buildBandTrendOption(["2026-07-20"], series({ points: [point()] })),
    );
    const byName = Object.fromEntries(option.series.map((s: any) => [s.name, s]));

    expect(byName["floor-offset"].data).toEqual([200_000]);
    expect(byName["span"].data).toEqual([100_000]); // the WIDTH, stacked on the floor
    expect(byName["floor-offset"].lineStyle.opacity).toBe(0);
    expect(byName["floor-offset"].silent).toBe(true);
  });

  it("plots the floor and ceiling as their own readable lines", () => {
    const option = opt(
      buildBandTrendOption(["2026-07-20", "2026-07-21"], series({
        points: [point(), point({ date: "2026-07-21", low_p50: 210_000, high_p50: 320_000 })],
      })),
    );
    const byName = Object.fromEntries(option.series.map((s: any) => [s.name, s]));

    expect(byName["Median floor"].data).toEqual([200_000, 210_000]);
    expect(byName["Median ceiling"].data).toEqual([300_000, 320_000]);
    expect(option.legend.data).toEqual(["Median ceiling", "Median floor"]);
  });

  it("keeps a day with no posted band as a hole in the span", () => {
    const option = opt(
      buildBandTrendOption(["2026-07-20", "2026-07-21"], series({
        points: [point({ low_p50: null, high_p50: null, bands: 0 }), point({ date: "2026-07-21" })],
      })),
    );
    const span = option.series.find((s: any) => s.name === "span");
    expect(span.data).toEqual([null, 100_000]);
  });

  it("does not force the money axis through zero", () => {
    // A band trend is read for its movement; anchoring at $0 flattens it.
    const option = opt(buildBandTrendOption(["2026-07-20"], series()));
    expect(option.yAxis.scale).toBe(true);
    expect(option.yAxis.min).toBeUndefined();
  });
});

describe("bandTrendSummary", () => {
  it("states the band, how many distinct bands it came from, and the unit", () => {
    const text = bandTrendSummary("base", series({ points: [point({ bands: 4, reqs: 30 })] }));

    expect(text).toContain("across 4 distinct ranges covering 30 open roles");
    expect(text).toContain("$200K to $300K");
    expect(text).toMatch(/one reading per distinct range, not per role/i);
  });

  it("handles history with no posted band", () => {
    expect(
      bandTrendSummary("base", series({ points: [point({ low_p50: null, high_p50: null })] })),
    ).toMatch(/no posted range/i);
    expect(bandTrendSummary("base", undefined)).toMatch(/no posted range/i);
  });

  it("names the pay basis from the catalog, never as the API's slug", async () => {
    expect(bandTrendSummary("base", series())).toContain(msg("vocab-pay-basis-base"));
    await activate("zh-Hans");
    try {
      const text = bandTrendSummary("base", series());
      expect(text).toContain(msg("vocab-pay-basis-base"));
      expect(text).not.toMatch(/base/);
    } finally {
      await activate("en");
    }
  });
});
