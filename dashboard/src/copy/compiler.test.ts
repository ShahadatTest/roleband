// The compiler against Fluent (docs/copy.md): the compiled
// functions say exactly what Fluent's own runtime says, for every message, in
// every real locale, over counts that exercise each plural category. A few
// outputs are also pinned as literal text, so the two implementations cannot
// agree on a wrong answer (rule T4, src/test/msg.ts).
import { execFileSync } from "node:child_process";
import { join } from "node:path";
import { FluentBundle, FluentResource } from "@fluent/bundle";
import { afterAll, describe, expect, it } from "vitest";
import { SITE_WALL_SENTENCE } from "../features/companies/followCopy";
import { activate } from "./activate";
import { setActive } from "./runtime";
import { LOCALES } from "./gen/index";
import quarantined from "./translation-quarantine.json";
import { samples } from "../../scripts/copy/review.mjs";
import { readLocale } from "../../scripts/copy/catalog.mjs";
import { MESSAGES } from "./gen/registry";
import * as shell from "./gen/shell";
import * as spike from "./gen/spike";

const dir = join(__dirname);
// The catalogs are this test's INPUT (the oracle's resources), not a source scan:
// every assertion executes compiled messages.
const CATALOGS = import.meta.glob("./*/*.ftl", { query: "?raw", import: "default", eager: true }) as Record<string, string>;
const catalog = (code: string) =>
  Object.entries(CATALOGS)
    .filter(([path]) => path.startsWith(`./${code}/`))
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([, text]) => text);
const COUNTS = [0, 1, 2, 3, 4, 5, 11, 21, 22, 25, 101, 1000, 1000000, 1.5];
const compiled = MESSAGES as unknown as Record<string, (a?: Record<string, unknown>) => string>;

function bundle(code: string): FluentBundle {
  const b = new FluentBundle(code, { useIsolating: false });
  for (const text of catalog(code)) {
    const errors = b.addResource(new FluentResource(text));
    if (errors.length) throw errors[0];
  }
  return b;
}
const english = bundle("en");
// A value for every variable the catalogs use, so no message is skipped for a
// missing argument; `count` is set per case.
const TEXT_ARGS = Object.fromEntries(
  [...new Set(Object.values(CATALOGS).flatMap((text) => [...text.matchAll(/\$([A-Za-z][A-Za-z0-9_]*)/g)].map((m) => m[1])))].map((v) => [v, `‹${v}›`]),
);
const ungroup = (s: string | null) =>
  s?.replace(/(\d)[\s\u00a0\u202f,.](?=\d{3}(?!\d))/g, "$1").replace(/(\d),(\d)/g, "$1.$2") ?? null;
const ids = catalog("en").flatMap((text) => [...text.matchAll(/^([a-z][a-z0-9-]*) =/gm)].map((m) => m[1]));
const englishSources = new Map(readLocale(dir, "en").messages.map((m) => [m.id, m]));

function fluentSays(b: FluentBundle, id: string, args: Record<string, unknown>): string | null {
  const msg = b.getMessage(id);
  if (!msg?.value) return null;
  const errors: Error[] = [];
  const out = b.formatPattern(msg.value, args as never, errors);
  return errors.length ? null : out;
}

afterAll(() => activate("en"));


describe.each(LOCALES.filter((l) => l.status !== "pseudo").map((l) => l.code))("compiled copy matches @fluent/bundle (%s)", (code) => {
  it("for every message and count, falling back to English where the locale is partial", async () => {
    await activate(code, { region: code });
    const own = bundle(code);
    expect(ids.length).toBeGreaterThan(25);
    for (const id of ids) {
      const source = englishSources.get(id)!;
      for (const args of [...COUNTS.map(count => ({ ...TEXT_ARGS, count })), ...samples(source)]) {
        const rejected = (quarantined as Record<string, Record<string,string>>)[code]?.[id];
        const translated = rejected ? null : fluentSays(own, id, args);
        // A fallback is English text with English plural rules; only its digit
        // grouping follows the region, so grouping is compared apart.
        const expected = translated ?? ungroup(fluentSays(english, id, args));
        const got = compiled[id](args);
        expect(translated === null ? ungroup(got) : got, `${code} ${id} args=${JSON.stringify(args)}`).toBe(expected);
      }
    }
  });
});

describe("Spanish and Chinese, pinned as text", () => {
  it("Spanish counts agree with the masculine term; consent stays English", async () => {
    await activate("es", { region: "es-ES" });
    // `many` (exact millions) takes "de": "1.000.000 de puestos".
    expect([1, 2, 1000000, 2000000].map((count) => spike.spikeRoleCount({ count }))).toEqual([
      "1 puesto", "2 puestos", "1.000.000 de puestos", "2.000.000 de puestos",
    ]);
    expect(spike.spikeSavedClosed({ company: "Stripe" })).toBe("Stripe cerró un puesto que guardaste");
    expect(shell.shellNavSaved()).toBe("Guardados");
    // Consent wording is never machine translated: English in every language.
    expect(spike.spikeConsentWall()).toBe(SITE_WALL_SENTENCE);
  });

  it("Chinese has one form for every count", async () => {
    await activate("zh-Hans", { region: "zh-CN" });
    expect([1, 2, 1000].map((count) => spike.spikeRoleCount({ count }))).toEqual(["1 个职位", "2 个职位", "1,000 个职位"]);
    expect(shell.shellNavRadar()).toBe("雷达");
  });

  it("an English fallback keeps English plural rules while its digits follow the region", () => {
    // A partial table (here, an empty one) leaves every message to English.
    setActive({ table: [], language: "es", tableLanguage: "es", region: "es-ES" });
    expect(spike.spikeSavedClosedCount({ count: 21, company: "Stripe" })).toBe("Stripe closed 21 roles you saved");
    expect(spike.spikeSavedClosedCount({ count: 10000, company: "Stripe" })).toBe("Stripe closed 10.000 roles you saved");
    expect(spike.spikeSavedClosedCount({ count: 1.5, company: "Stripe" })).toBe("Stripe closed 1,5 roles you saved");
  });

  it("switching back restores English without a reload", async () => {
    await activate("es", { region: "es-ES" });
    expect(shell.shellNavSaved()).toBe("Guardados");
    await activate("en");
    expect(shell.shellNavSaved()).toBe("Saved");
    expect(spike.spikeRoleCount({ count: 1000 })).toBe("1,000 roles");
  });
});

describe("pseudo locales", () => {
  it("en-XA brackets every message and leaves parameter values alone", async () => {
    await activate("en-XA");
    expect(spike.spikeSavedClosed({ company: "Stripe" })).toMatch(/^⟦Stripe çļöšéð à ŕöļé ýöû šàṽéð·+⟧$/);
    await activate("keys");
    expect(shell.shellNavRadar()).toBe("⟦shell-nav-radar⟧");
  });
});

describe("consent stays one string by construction", () => {
  it("renders the agreed sentence with no invisible characters", async () => {
    await activate("en");
    expect(spike.spikeConsentWall()).toBe(SITE_WALL_SENTENCE);
    expect(spike.spikeConsentWall()).not.toMatch(/[⁦-⁩‎‏؜]/);
  });
});

describe("generated files", () => {
  it("are current with the catalogs, and the backend's committed twin of the rules is too", () => {
    expect(() =>
      execFileSync(process.execPath, [join(dir, "..", "..", "scripts", "gen-copy.mjs"), "--check"], { stdio: "pipe" }),
    ).not.toThrow();
  });

  it("are not committed: their ids are positions, so two sessions adding messages merged wrong", () => {
    const tracked = execFileSync("git", ["ls-files", "--", join(dir, "gen")], { cwd: dir, encoding: "utf8" });
    expect(tracked).toBe("");
    const ignored = execFileSync("git", ["check-ignore", "-q", join(dir, "gen", "registry.ts")], { cwd: dir, stdio: "pipe" });
    expect(ignored.toString()).toBe("");
  });
});
