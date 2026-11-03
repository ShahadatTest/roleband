import { calendarDay } from "../copy/format";

/* What a notification says, in the reader's language (
 * docs/copy.md).
 *
 * The server stores English `title` and `body` and, beside them, `meta.say`:
 * the same sentences as message keys with their parameters
 * (`backend/tracker/notifications/say.py`). A row whose keys this build knows,
 * with every parameter each needs, is said from the catalog; anything else (a
 * row written before `say`, a key a newer server sends) shows the stored
 * English, which is never wrong, only English.
 *
 *   say   = {k: key, p: {name: value}}
 *   value = string | number | say | {date: "YYYY-MM-DD"}
 *
 * The body is its sentences joined by a space; a string sentence is
 * third-party text (a role's title), shown as written.
 *
 * Every key the server can send is in `backend/tests/fixtures/notification_keys.json`
 * with its parameters; `notificationText.test.ts` holds this table to that
 * file and renders every server sample back to its stored English. */

import { NOTIFICATION_MESSAGES } from "../copy/gen/notification-contract";
const MESSAGES = NOTIFICATION_MESSAGES as unknown as Record<string, readonly [(a: Record<string, string | number>) => string, readonly string[]]>;
/** The keys this build can say, with their parameters, for the contract test. */
export const SAID_KEYS: Readonly<Record<string, readonly string[]>> = Object.fromEntries(
  Object.entries(MESSAGES).map(([key, [, params]]) => [key, params]),
);

const isRecord = (v: unknown): v is Record<string, unknown> => !!v && typeof v === "object" && !Array.isArray(v);

/** One parameter as the message takes it, or null when it cannot be said. */
function value(v: unknown, depth: number): string | number | null {
  if (typeof v === "string" || (typeof v === "number" && Number.isFinite(v))) return v;
  if (isRecord(v) && typeof v.date === "string" && /^\d{4}-\d{2}-\d{2}$/.test(v.date)) {
    const day = new Date(`${v.date}T00:00:00Z`);
    if (!Number.isFinite(day.getTime()) || day.toISOString().slice(0,10) !== v.date) return null;
    return calendarDay(v.date);
  }
  return say(v, depth + 1);
}

/** One `say`, from the catalog; null when its key or a parameter is unknown. */
export function say(s: unknown, depth = 0): string | null {
  if (depth > 16) return null;
  if (!isRecord(s) || typeof s.k !== "string" || !isRecord(s.p)) return null;
  const entry = Object.prototype.hasOwnProperty.call(MESSAGES, s.k) ? MESSAGES[s.k] : undefined;
  if (!entry) return null;
  const [message, params] = entry;
  const args: Record<string, string | number> = {};
  for (const name of params) {
    const said = value(s.p[name], depth);
    if (said === null) return null;
    args[name] = said;
  }
  return (message as (a: Record<string, string | number>) => string)(args);
}

interface Stored {
  title: string;
  body?: string | null;
  meta?: Record<string, unknown> | null;
}

export interface NotificationWords {
  title: string;
  body: string | null;
  /** The body is third-party text only (a role's title): show it as written
   *  (`ui/Content`). Never true for stored English, which is RoleBand's. */
  bodyIsContent: boolean;
}

/** A notification's title and body in the reader's language, else as stored. */
export function notificationText(n: Stored): NotificationWords {
  const stored = { title: n.title, body: n.body || null, bodyIsContent: false };
  const said = n.meta?.say;
  if (!isRecord(said)) return stored;
  const title = say(said.title);
  if (title === null) return stored;
  if (said.body !== null && !Array.isArray(said.body)) return stored;
  if (said.body === null) return { title, body: null, bodyIsContent: false };
  const sentences = said.body.map((s) => (typeof s === "string" ? s : say(s)));
  if (sentences.some((s) => s === null)) return stored;
  const bodyIsContent = said.body.length > 0 && said.body.every((s) => typeof s === "string");
  return { title, body: sentences.join(" ") || null, bodyIsContent };
}
