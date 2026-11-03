import type { StatisticsOverview } from "../../api";
import {
  insightsAgingFrom0Days,
  insightsAgingFrom14Days,
  insightsAgingFrom30Days,
  insightsAgingFrom60Days,
  insightsAgingFrom7Days,
  insightsAgingFrom90Days,
  insightsBriefLargestGroup,
  insightsBriefOpen,
  insightsBriefOpened,
  insightsBriefTopSkill,
  insightsClusterUnlabeled,
} from "../../copy/gen/insights";
import { roleName, skillName } from "../../copy/vocab";

/* Names the Statistics screens give what the API sends as slugs. */

/** A cluster by its three strongest skills ("Python · Kubernetes · AWS"), else
 *  its role group, else unlabeled: the rule of the server's English
 *  `semantic/cluster._label`, said in the reader's language. */
export function clusterLabel(cluster: { terms?: readonly string[]; top_terms?: readonly { term: string }[]; family_hint: string | null }): string {
  const terms = cluster.terms ?? (cluster.top_terms ?? []).map((t) => t.term);
  if (terms.length > 0) return terms.slice(0, 3).map(skillName).join(" · ");
  return cluster.family_hint ? roleName(cluster.family_hint) : insightsClusterUnlabeled();
}

/** A fixed age band by its lower bound in days (`velocity.AGING_BANDS`). */
const AGING: Record<number, () => string> = {
  0: insightsAgingFrom0Days,
  7: insightsAgingFrom7Days,
  14: insightsAgingFrom14Days,
  30: insightsAgingFrom30Days,
  60: insightsAgingFrom60Days,
  90: insightsAgingFrom90Days,
};

export const agingBandName = (lo: number): string => AGING[lo]?.() ?? String(lo);

/** The Overview's one line: its facts said as sentences, each only when it is
 *  there. The largest group is said only in the advanced view, which lists
 *  the groups. */
export function overviewBrief(
  data: Pick<StatisticsOverview, "days" | "kpis" | "top_skills" | "top_clusters">,
  advanced = false,
): string {
  const k = data.kpis;
  const parts = [
    insightsBriefOpen({ open: k.open_total, companies: k.companies }),
    insightsBriefOpened({ allTime: data.days <= 0 ? "yes" : "no", opened: k.new_count, days: data.days, closed: k.closed_count }),
  ];
  const skill = data.top_skills[0];
  if (skill) parts.push(insightsBriefTopSkill({ skill: skillName(skill.term), count: skill.job_count }));
  const group = data.top_clusters[0];
  if (advanced && group) parts.push(insightsBriefLargestGroup({ group: clusterLabel(group), size: group.size }));
  return parts.join(" ");
}
