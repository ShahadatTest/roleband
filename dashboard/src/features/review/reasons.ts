import {
  duplicatesReasonDepartmentUnknown,
  duplicatesReasonDescriptionsAlike,
  duplicatesReasonListedAtOnce,
  duplicatesReasonPassagesDiffer,
  duplicatesReasonSameDepartment,
  duplicatesReasonSameTitle,
  duplicatesReasonTitlesAlike,
} from "../../copy/gen/duplicates";

/* Why a detector paired two postings, in the reader's words. The API sends
 * each reason as a code and its figures (backend `lineage/reasons.py`); the
 * detector's own English stays a diagnostic. A code this build does not know
 * is left unsaid rather than shown raw. */

export interface ReasonSaid {
  code: string;
  params: Record<string, number>;
}

const WORDS: Record<string, (p: Record<string, number>) => string | null> = {
  same_title: () => duplicatesReasonSameTitle(),
  titles_alike: (p) => (p.pct == null ? null : duplicatesReasonTitlesAlike({ pct: p.pct })),
  descriptions_alike: (p) => (p.pct == null ? null : duplicatesReasonDescriptionsAlike({ pct: p.pct })),
  listed_at_once: () => duplicatesReasonListedAtOnce(),
  same_department: () => duplicatesReasonSameDepartment(),
  department_unknown: () => duplicatesReasonDepartmentUnknown(),
  passages_differ: (p) =>
    p.earlier == null || p.later == null ? null : duplicatesReasonPassagesDiffer({ earlier: p.earlier, later: p.later }),
};

export function reasonsText(said: readonly ReasonSaid[]): string[] {
  return said.flatMap((reason) => {
    const say = Object.prototype.hasOwnProperty.call(WORDS, reason.code) ? WORDS[reason.code] : undefined;
    const text = say?.(reason.params);
    return text ? [text] : [];
  });
}
