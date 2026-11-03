/* The words of the usage-sharing consent, and the record an answer carries
   (docs/architecture.md).

   The screen renders these strings and the record stores the same strings,
   joined: what the user saw and what was agreed to are one value by
   construction, as the walled-company consent does it (followCopy.ts). The
   consent sentences are pinned (src/copy/pinned.en.json), so a change to one
   is deliberate, never a side effect. Resolved at render: nothing here is evaluated at module scope. */

import type { UsageConsent, UsageGroup, UsageState } from "../../api";
import {
  privacyConsentChange,
  privacyConsentIntro,
  privacyConsentTitle,
  privacyGroupCrashes,
  privacyGroupCrashesDetail,
  privacyGroupQuestions,
  privacyGroupQuestionsDetail,
  privacyGroupUsage,
  privacyGroupUsageDetail,
  privacyNever,
} from "../../copy/gen/privacy";

/** The order every screen lists the groups in. */
export const GROUPS: readonly UsageGroup[] = ["usage", "crashes", "questions"];

export interface GroupWords {
  group: UsageGroup;
  label: string;
  detail: string;
}

export function groupWords(group: UsageGroup): GroupWords {
  switch (group) {
    case "usage":
      return { group, label: privacyGroupUsage(), detail: privacyGroupUsageDetail() };
    case "crashes":
      return { group, label: privacyGroupCrashes(), detail: privacyGroupCrashesDetail() };
    case "questions":
      return { group, label: privacyGroupQuestions(), detail: privacyGroupQuestionsDetail() };
  }
}

export interface ConsentWords {
  title: string;
  /** Absent where the screen does not show them (a Settings switch row). */
  intro?: string;
  groups: GroupWords[];
  /** What is never sent, whatever is shared. */
  never: string;
  change?: string;
}

/** What the consent screen shows when it asks about `groups`. */
export function consentWords(groups: readonly UsageGroup[] = GROUPS): ConsentWords {
  return {
    title: privacyConsentTitle(),
    intro: privacyConsentIntro(),
    groups: GROUPS.filter((group) => groups.includes(group)).map(groupWords),
    never: privacyNever(),
    change: privacyConsentChange(),
  };
}

/** The record of `words`: every string shown, in order, one paragraph each. */
export function consentText(words: ConsentWords): string {
  return [
    words.title,
    ...(words.intro ? [words.intro] : []),
    ...words.groups.map((group) => `${group.label}: ${group.detail}`),
    words.never,
    ...(words.change ? [words.change] : []),
  ].join("\n\n");
}

/** The language the words were shown in: always English. Consent wording is
 *  never machine translated (AGENTS.md), so every string the record carries is
 *  on `englishOnly` in src/copy/locales.json and shows in English in any
 *  language. */
const consentLocale = (): string => "en";

/** Groups a screen still has to ask about: never answered, or widened since. */
export function groupsToAsk(state: UsageState): UsageGroup[] {
  return state.groups
    .filter((group) => group.status === "undecided" || group.status === "stale")
    .map((group) => group.group);
}

/** The PUT body for answering `answers`, with the words shown and the
 *  fingerprints the screen was built from (a stale one is refused with 409). */
export function consentPayload(
  state: UsageState,
  answers: Partial<Record<UsageGroup, boolean>>,
  words: ConsentWords,
): UsageConsent {
  const answered = GROUPS.filter((group) => answers[group] !== undefined);
  const fingerprints: Partial<Record<UsageGroup, string>> = {};
  for (const group of state.groups) {
    if (answered.includes(group.group)) fingerprints[group.group] = group.fingerprint;
  }
  return {
    answers: Object.fromEntries(answered.map((group) => [group, answers[group] === true])),
    text: consentText(words),
    locale: consentLocale(),
    fingerprints,
  };
}
