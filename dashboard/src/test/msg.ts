import { MESSAGES } from "../copy/gen/registry";

/* What a message says now, for a test's expectation (docs/copy.md, section
 * 3). Selectors stay user-visible without restating the words, so a copy
 * edit stops breaking tests while a behaviour change still does.
 *
 * Rules that keep it a behaviour contract:
 * T1 the key is a literal at the call (ESLint), never derived from the
 *    component's own state-to-message mapping;
 * T2 the parameters are part of the assertion;
 * T3 no two keys on one surface say the same thing (copy:check);
 * T4 literal English survives in the compiler's golden test, the pinned
 *    wording and one English smoke check per route;
 * T5 fixture data (company names, titles, cities) stays literal. */
type Messages = typeof MESSAGES;
export type MessageKey = keyof Messages;

export function msg<K extends MessageKey>(key: K, ...args: Parameters<Messages[K]>): string {
  return (MESSAGES[key] as (...a: unknown[]) => string)(...args);
}
