// Notifications said from the catalog. The server writes each
// sentence twice: as English (`title`, `body`) and as message keys
// (`meta.say`). The samples are the classifiers' real output, one per wording
// branch (`backend/scripts/export_notification_samples.py`); rendering each
// from the catalog must give back exactly the English the server stored, so a
// sentence reworded on one side only fails here.
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";
import { activate } from "../copy/activate";
import samples from "./notification-samples.json";
import { calendarDay } from "../copy/format";
import { SAID_KEYS, notificationText, say } from "./notificationText";

const REGISTRY = resolve(__dirname, "../../../backend/tests/fixtures/notification_keys.json");

afterEach(() => activate("en"));

// A reader west of UTC, set before any formatter is built: a day written as an
// instant would print the 27th here.
const zone = process.env.TZ;
beforeAll(() => {
  process.env.TZ = "America/Los_Angeles";
});
afterAll(() => {
  process.env.TZ = zone;
});

/** Every calendar day a `say` carries, nested ones included. */
function daysIn(value: unknown): string[] {
  if (!value || typeof value !== "object") return [];
  if (Array.isArray(value)) return value.flatMap(daysIn);
  const v = value as Record<string, unknown>;
  if (typeof v.date === "string") return [v.date];
  return Object.values(v).flatMap(daysIn);
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
/** The server's "28 Sep" (`events._day`) for a day. */
const serverDay = (iso: string): string => `${Number(iso.slice(8))} ${MONTHS[Number(iso.slice(5, 7)) - 1]}`;

describe("the server's samples", () => {
  it("cover a real spread of branches", () => {
    expect(samples.length).toBeGreaterThan(40);
  });

  it.each(samples.map((s) => [s.case, s] as const))("%s renders to its stored English", async (_case, sample) => {
    // Counts stay under 1,000, so no region groups digits the server did not.
    await activate("en", { region: "en-GB" });
    const n = { title: sample.title, body: sample.body, meta: { say: sample.say } };
    // Said from the catalog, never the stored fallback: every key resolves.
    expect(say(sample.say.title)).not.toBeNull();
    for (const sentence of sample.say.body ?? []) if (typeof sentence !== "string") expect(say(sentence)).not.toBeNull();
    // A day is the one value written by the reader's region on purpose: the
    // server's "28 Sep" is that day as the region writes it ("28 Sept" in
    // British English since ICU 72).
    let body = sample.body;
    for (const iso of daysIn(sample.say)) {
      expect(body).toContain(serverDay(iso));
      body = body.replace(serverDay(iso), calendarDay(iso));
    }
    // A body that is only third-party text (a role's title) is marked as such.
    const content = sample.say.body !== null && sample.say.body.every((s) => typeof s === "string");
    expect(notificationText(n)).toEqual({ title: sample.title, body, bodyIsContent: content });
  });
});

describe("the keys", () => {
  it("are the server's registry, each with its parameters", () => {
    const registry = JSON.parse(readFileSync(REGISTRY, "utf8")) as Record<string, string[]>;
    expect(Object.keys(registry).length).toBeGreaterThan(50);
    const ours = Object.fromEntries(Object.entries(SAID_KEYS).map(([k, p]) => [k, [...p].sort()]));
    expect(ours).toEqual(registry);
  });
});

describe("what is not said from the catalog", () => {
  const stored = { title: "OpenAI closed a role you saved", body: "Research Manager" };
  const closed = { k: "notif-closed", p: { company: "OpenAI" } };

  it("is the stored English for a row written before keys", () => {
    const asStored = { ...stored, bodyIsContent: false };
    expect(notificationText({ ...stored, meta: {} })).toEqual(asStored);
    expect(notificationText({ ...stored, meta: null })).toEqual(asStored);
  });

  it("is the stored English for a key this build does not know", () => {
    const n = { ...stored, meta: { say: { title: { k: "notif-from-a-newer-server", p: {} }, body: ["Research Manager"] } } };
    expect(notificationText(n)).toEqual({ ...stored, bodyIsContent: false });
  });

  it("is the stored English when a parameter is missing, never a blank", () => {
    const n = { ...stored, meta: { say: { title: { k: "notif-closed", p: {} }, body: ["Research Manager"] } } };
    expect(notificationText(n)).toEqual({ ...stored, bodyIsContent: false });
  });

  it("is the stored English when one sentence of the body cannot be said", () => {
    const n = { ...stored, meta: { say: { title: closed, body: ["Research Manager", { k: "notif-nope", p: {} }] } } };
    expect(notificationText(n)).toEqual({ ...stored, bodyIsContent: false });
  });
});

describe("what is said from the catalog", () => {
  it("follows the active language, not the stored English", async () => {
    await activate("en-XA");
    const n = {
      title: "OpenAI closed a role you saved",
      body: "Research Manager",
      meta: { say: { title: { k: "notif-closed", p: { company: "OpenAI" } }, body: ["Research Manager"] } },
    };
    const { title, body } = notificationText(n);
    expect(title).toMatch(/^⟦OpenAI çļöšéð à ŕöļé ýöû šàṽéð/);
    // A role's title is third-party text: shown as written in every language.
    expect(body).toBe("Research Manager");
  });

  it("writes a day by the reader's region and never shifts it by their zone", async () => {
    const since = { k: "notif-coverage-outage-since", p: { day: { date: "2026-09-28" } } };
    await activate("en", { region: "en-US" });
    expect(say(since)).toContain("since Sep 28,");
    await activate("en", { region: "en-GB" });
    expect(say(since)).toMatch(/since 28 Sept?,/);
  });

  it("says a nested phrase inside its sentence", async () => {
    await activate("en", { region: "en-GB" });
    const stopped = { k: "notif-stopped-after", p: { companies: { k: "notif-companies", p: { count: 1 } } } };
    expect(say(stopped)).toBe("You stopped it after it scanned 1 company.");
  });
});

it.each(["constructor", "__proto__", "toString"])("prototype key %s falls back safely", (key) => {
  expect(say({k:key,p:{}})).toBeNull();
});
it("a malformed body keeps the entire stored record", async () => {
  await activate("es");
  const stored = {title:"stored English",body:"stored body"};
  const meta={say:{title:{k:"notif-closed",p:{company:"Acme"}},body:{}}};
  expect(notificationText({...stored,meta})).toEqual({...stored,bodyIsContent:false});
  expect(say({k:"notif-coverage-not-scanned-since",p:{company:"Acme",day:{date:"2026-02-30"}}})).toBeNull();
  const cyclic: {k:string;p:Record<string,unknown>} = {k:"notif-digest-fit",p:{band:"Good"}};
  cyclic.p.lead=cyclic;
  expect(say(cyclic)).toBeNull();
});
