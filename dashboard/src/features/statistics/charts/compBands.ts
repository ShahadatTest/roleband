import { compare as copyCompare } from "../../../copy/format";
import type { DisclosedBand, DisclosedBands } from "../../../api";
import { companyName, fmtComp } from "../../../format";
import { levelLabel } from "./levelLabel";
import {
  insightsCompBands1MoreRoleStatesA,
  insightsCompBands1MoreRoleStatesBase,
  insightsCompBandsLevelSummary,
  insightsCompBandsMoreRolesStateARange,
  insightsCompBandsMoreRolesStateBasePay,
  insightsCompBandsEmployerAtLevel,
  insightsCompBandsTo,
} from "../../../copy/gen/insights";

/**
 * Posted pay bands, by level.
 *
 * Deliberately NOT a distribution. An employer publishes a band per
 * (company, level) and hangs many reqs off it, so a dot-per-role plot would
 * assert a per-role salary sample that does not exist. The unit is the band
 * itself.
 *
 * A row per level: every band a faint span, the level's median band outlined,
 * and colour kept for the employer a reader picks, since colour cycled across
 * every employer would name no one.
 */

export interface LevelBands {
  level: string;
  bands: DisclosedBand[];
  employers: number;
  reqs: number;
  /** Median floor and ceiling, one vote per band; null for a level with none. */
  low: number | null;
  high: number | null;
}

function median(xs: number[]): number | null {
  if (!xs.length) return null;
  const s = [...xs].sort((a, b) => a - b);
  const mid = (s.length - 1) / 2;
  return (s[Math.floor(mid)] + s[Math.ceil(mid)]) / 2;
}

/** Bands grouped by level, in the order the API ranks them (seniority). */
export function bandsByLevel(bands: readonly DisclosedBand[]): LevelBands[] {
  const by = new Map<string, DisclosedBand[]>();
  for (const b of bands) by.set(b.level_band, [...(by.get(b.level_band) ?? []), b]);
  return [...by].map(([level, bs]) => ({
    level,
    bands: bs,
    employers: new Set(bs.map((b) => b.company)).size,
    reqs: bs.reduce((n, b) => n + b.reqs, 0),
    low: median(bs.map((b) => b.low)),
    high: median(bs.map((b) => b.high)),
  }));
}

const STEPS = [25_000, 50_000, 100_000, 200_000, 250_000, 500_000];

/** One dollar scale for every row: rounded ends and three to six ticks. */
export function bandScale(bands: readonly DisclosedBand[]): { min: number; max: number; ticks: number[] } {
  if (!bands.length) return { min: 0, max: 1, ticks: [] };
  const lo = Math.min(...bands.map((b) => b.low));
  const hi = Math.max(...bands.map((b) => b.high));
  const step = STEPS.find((s) => (hi - lo) / s <= 6) ?? 1_000_000;
  const min = Math.floor(lo / step) * step;
  const max = Math.max(min + step, Math.ceil(hi / step) * step);
  const ticks: number[] = [];
  for (let t = min; t <= max; t += step) ticks.push(t);
  return { min, max, ticks };
}

/** Employers with a band, most open roles on their bands first. */
export function bandEmployers(bands: readonly DisclosedBand[]): { value: string; label: string; count: number }[] {
  const reqs = new Map<string, number>();
  for (const b of bands) reqs.set(b.company, (reqs.get(b.company) ?? 0) + b.reqs);
  return [...reqs]
    .map(([company, count]) => ({ value: company, label: companyName(company), count }))
    .sort((a, b) => b.count - a.count || copyCompare(a.label, b.label));
}

/** One level's row, said in words for a screen reader. */
export function levelSummary(row: LevelBands, picked: readonly DisclosedBand[], employer: string | null): string {
  const label = levelLabel(row.level);
  const summary = insightsCompBandsLevelSummary({
    label,
    bands: row.bands.length,
    employers: row.employers,
    low: fmtComp(row.low),
    high: fmtComp(row.high),
  });
  if (!employer) return summary;
  const ranges = picked.map((b) => insightsCompBandsTo({ low: fmtComp(b.low), high: fmtComp(b.high) })).join(", ");
  return insightsCompBandsEmployerAtLevel({ summary, employer: companyName(employer), published: picked.length ? "some" : "none", ranges });
}

/** What the yearly base-pay dollar scale left out, and why; "" when nothing. */
export function exclusionNote(excluded: DisclosedBands["excluded"]): string {
  const notes: string[] = [];
  const { unclear } = excluded;
  if (unclear === 1) {
    notes.push(insightsCompBands1MoreRoleStatesA());
  } else if (unclear) {
    notes.push(insightsCompBandsMoreRolesStateARange({ unclear: unclear }));
  }
  const elsewhere = excluded.not_usd + excluded.not_yearly;
  if (elsewhere === 1) {
    notes.push(insightsCompBands1MoreRoleStatesBase());
  } else if (elsewhere) {
    notes.push(insightsCompBandsMoreRolesStateBasePay({ elsewhere: elsewhere }));
  }
  return notes.join(" ");
}
