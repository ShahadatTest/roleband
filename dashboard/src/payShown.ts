/* The pay a posting shows: its estimated total, else its
   estimated base, labelled "Est. base", never one read as the other. A role
   list's Base column shows `baseShown`, base salary alone. Its own module so
   the words load with the screens that show pay, never the shell. */
import { roleJobCompPanelHr, roleJobCompPanelMo } from "./copy/gen/role";
import {
  sharedBaseEstimateHint,
  sharedBasePostedHint,
  sharedBasePostedPointHint,
  sharedPayEstBase,
  sharedPayEstBaseHint,
  sharedPayNotCovered,
  sharedPayNotCoveredHint,
} from "./copy/gen/shared";
import { fmtComp, fmtCompIn, fmtRange } from "./money";
import type { PayCover } from "./payCoverage";

export interface PayFields {
  company?: string;
  comp_low: number | null;
  comp_high: number | null;
  comp_median: number | null;
  comp_base_low?: number | null;
  comp_base_high?: number | null;
  comp_base_median?: number | null;
}

export interface PayShown {
  text: string;
  /** Only the base is estimated: label it, and never rank it against a total. */
  base: boolean;
  /** The reason a base stands alone, for a title attribute. */
  hint?: string;
  /** A plugin answers pay and has not read this company. */
  notCovered?: boolean;
}

/** `cover`: the plugin answering pay (`usePayCoverage`). A posting with no figure
 *  at a company it has not read says so, never a bare dash. */
export function payShown(job: PayFields, cover?: PayCover | null): PayShown {
  if (job.comp_median != null) return { text: fmtRange(job.comp_low, job.comp_high, job.comp_median), base: false };
  if (job.comp_base_median != null) {
    const range = fmtRange(job.comp_base_low ?? null, job.comp_base_high ?? null, job.comp_base_median);
    return { text: sharedPayEstBase({ range }), base: true, hint: sharedPayEstBaseHint() };
  }
  if (cover && job.company && !cover.companies.has(job.company)) {
    return { text: sharedPayNotCovered({ plugin: cover.name }), base: false, notCovered: true,
             hint: sharedPayNotCoveredHint({ plugin: cover.name }) };
  }
  return { text: "—", base: false };
}

export interface PostedBase {
  min: number | null;
  max: number | null;
  currency: string;
  period: "year" | "hour" | "month";
}

export interface BaseFields {
  company?: string;
  comp_currency?: string;
  comp_base_median?: number | null;
  posted_base?: PostedBase | null;
}

export interface BaseShown {
  /** One figure, or "" when no base salary is known: the cell holds no words. */
  text: string;
  /** Where the figure comes from, or why there is none, for a title attribute. */
  hint?: string;
}

const POSTED_UNIT: Record<PostedBase["period"], () => string> = {
  year: () => "",
  month: () => " " + roleJobCompPanelMo(),
  hour: () => " " + roleJobCompPanelHr(),
};

/** The base salary a role list's Base column shows, the figure
 *  `sort=base_pay` and `base_min`/`base_max` read: the posting's own base
 *  range from its low end, "+" when it is a range, in its own currency and
 *  period; else the estimated base as one figure; else nothing. Never a
 *  total: the column holds one kind of number. */
export function baseShown(job: BaseFields, cover?: PayCover | null): BaseShown {
  const posted = job.posted_base;
  const low = posted ? (posted.min ?? posted.max) : null;
  if (posted && low != null) {
    const high = posted.max ?? low;
    const unit = POSTED_UNIT[posted.period]();
    const money = (n: number) => fmtCompIn(n, posted.currency);
    // Compared as written: two ends that round to one figure are one figure.
    return money(high) !== money(low)
      ? { text: `${money(low)}+${unit}`, hint: sharedBasePostedHint({ low: money(low), high: money(high), unit }) }
      : { text: `${money(low)}${unit}`, hint: sharedBasePostedPointHint({ amount: money(low), unit }) };
  }
  if (job.comp_base_median != null) {
    return { text: fmtCompIn(job.comp_base_median, job.comp_currency ?? "USD"), hint: sharedBaseEstimateHint() };
  }
  if (cover && job.company && !cover.companies.has(job.company)) {
    return { text: "", hint: sharedPayNotCoveredHint({ plugin: cover.name }) };
  }
  return { text: "" };
}

/** `payShown` as one figure for a compact row (Statistics' lists, a cluster's
 *  members, similar roles): the median, never a range, with the same rules for
 *  a base that stands alone and a company the plugin has not read. */
export function payPoint(job: PayFields, cover?: PayCover | null): PayShown {
  if (job.comp_median != null) return { text: fmtComp(job.comp_median), base: false };
  if (job.comp_base_median != null) {
    return { text: sharedPayEstBase({ range: fmtComp(job.comp_base_median) }), base: true, hint: sharedPayEstBaseHint() };
  }
  return payShown(job, cover);
}
