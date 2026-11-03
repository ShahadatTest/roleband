import {
  insightsSkillCloud,
  insightsSkillCollaboration,
  insightsSkillData,
  insightsSkillFramework,
  insightsSkillIndustry,
  insightsSkillInfra,
  insightsSkillLanguage,
  insightsSkillLeadership,
  insightsSkillMlAi,
  insightsSkillProcess,
  insightsSkillSecurity,
} from "./gen/insights";

/** Display names for skill categories, one map for every Insights tab, so no
 *  tab can drift and print a raw slug ("PROCESS"). The categories are `backend/tracker/skills/catalog.yaml`'s; `skills.test.ts`
 *  fails on one without a name here. */
export const SKILL_CATEGORY: Readonly<Record<string, string>> = {
  get language() { return insightsSkillLanguage(); },
  get framework() { return insightsSkillFramework(); },
  get cloud() { return insightsSkillCloud(); },
  get data() { return insightsSkillData(); },
  get ml_ai() { return insightsSkillMlAi(); },
  get infra() { return insightsSkillInfra(); },
  get security() { return insightsSkillSecurity(); },
  get process() { return insightsSkillProcess(); },
  get leadership() { return insightsSkillLeadership(); },
  get collaboration() { return insightsSkillCollaboration(); },
  get industry() { return insightsSkillIndustry(); },
};

export function skillCategory(slug: string | null | undefined): string | null {
  if (!slug) return null;
  return SKILL_CATEGORY[slug] ?? slug;
}
