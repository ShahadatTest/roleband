import { cpSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { BASELINE, COPY, checkCatalog, checkSource, glossary, recordTranslated, textProblems } from "../../scripts/copy-check.mjs";
import { extractFile } from "../../scripts/copy/extract.mjs";

/* The product language, enforced (docs/copy.md).
 *
 * Reads the catalog with the Fluent parser and every literal not yet migrated
 * with the TypeScript compiler (`scripts/copy/extract.mjs`): a regex over
 * one-line JSX text and a list of props misses multi-line text and props it
 * does not list.
 *
 * Today's literal problems are NAMED in `copy-check-baseline.json` (rule, file,
 * text): a new one fails here, and one that is fixed must leave the list in the
 * same change. The habit counts there may only fall, and when they fall the
 * baseline is lowered with them (`npm run copy:check -- --freeze`). */

const baseline: { counts: Record<string, Record<string, number>>; literals: string[] } = JSON.parse(readFileSync(BASELINE, "utf8"));
const source = checkSource();

describe("the catalog", () => {
  it("has no blocking problem in any language", () => {
    const { blocking, messages } = checkCatalog();
    expect(messages).toBeGreaterThan(30);
    expect(blocking, blocking.join("\n")).toEqual([]);
  });
});

describe("literals not yet migrated", () => {
  const now = source.literals;

  it("add no banned, retired or mis-punctuated string", () => {
    const fresh = now.filter((l) => !baseline.literals.includes(l));
    expect(fresh, `new problems in user-visible copy:\n${fresh.join("\n")}`).toEqual([]);
  });

  it("drop a fixed problem from the baseline in the same change", () => {
    const fixed = baseline.literals.filter((l) => !now.includes(l));
    expect(fixed, `fixed, so remove from copy-check-baseline.json:\n${fixed.join("\n")}`).toEqual([]);
  });

  it("hold the habits the copy system retires to their counts, per folder, which only fall", () => {
    // Per folder and at most, not exact: sessions moving copy in different folders
    // never edit the same baseline line, and a landing lowers it with --freeze.
    const risen: string[] = [];
    for (const [where, measured] of Object.entries(source.counts)) {
      for (const [marker, value] of Object.entries(measured)) {
        const limit = baseline.counts[where]?.[marker] ?? 0;
        if (value > limit) risen.push(`${where} ${marker}: ${value} > ${limit}`);
      }
    }
    expect(risen, risen.join("\n")).toEqual([]);
  });
});

describe("the rules catch what they claim (fail-first)", () => {
  const en = glossary("en");
  const es = glossary("es");
  const rulesOf = (text: string, rules = en, withTerms = false) => textProblems(text, rules, { withTerms }).map(([rule]) => rule);

  it("a new source check sees a changed file instead of reusing a stale inventory", () => {
    const root = mkdtempSync(join(tmpdir(), "copy-source-"));
    try {
      const file = join(root, "Panel.tsx");
      writeFileSync(file, 'export const panel = <p>Loading...</p>;');
      const broken = checkSource(root);
      expect(broken.literals.some((line) => line.includes("Loading..."))).toBe(true);
      expect(Object.values(broken.counts).reduce((sum, counts) => sum + (counts["literal-copy"] ?? 0), 0)).toBe(1);
      writeFileSync(file, "export const panel = null;");
      const fixed = checkSource(root);
      expect(fixed.literals).toEqual([]);
      expect(Object.values(fixed.counts).some((counts) => counts["literal-copy"])).toBe(false);
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });

  it("vocabulary, with inflections, hyphens and the old gate's phrases", () => {
    for (const bad of ["Still scraping", "re-sync now", "Filter by position type", "your best matches", "New signals today", "Clear the new-signals lens", "Your starter set of companies"]) {
      expect(rulesOf(bad), bad).toContain("vocabulary");
    }
    for (const good of ["Compare 3 roles", "Keep curated list", "Apple Intelligence answers", "Scan now"]) {
      expect(rulesOf(good), good).toEqual([]);
    }
    expect(rulesOf("Open the listing", en, true)).toContain("vocabulary");
  });

  it("mechanics and register", () => {
    expect(rulesOf("Couldn't save — try again.")).toContain("mechanics");
    expect(rulesOf("Could not save it.")).toContain("mechanics");
    expect(rulesOf("Loading...")).toContain("mechanics");
    expect(rulesOf("Guárdalo si usted quiere", es)).toContain("register");
    expect(rulesOf("Guardaste el puesto.", es)).toEqual([]);
  });

  it("the catalog rules block, in a copy of the catalog", () => {
    const root = mkdtempSync(join(tmpdir(), "copy-check-"));
    try {
      cpSync(COPY, root, { recursive: true, filter: (src) => !src.includes(`${join(COPY, "gen")}`) });
      const add = (path: string, text: string) => writeFileSync(join(root, path), readFileSync(join(root, path), "utf8") + text);
      add("en/settings.ftl", [
        "# kind=label\nprobe-label = Saved roles.\n",
        "# kind=error\nprobe-error = Couldn't save it.\n",
        "# kind=label\nprobe-case = Followed Companies\n",
        "# kind=label\nprobe-dup = Language\n",
        "probe-kindless = Something\n",
        "# kind=label\nprobe-role = { -role(num: \"one\") }\n",
      ].join(""));
      add("es/settings.ftl", "probe-role = cargo\n");
      const esPath = join(root, "es/settings.ftl");
      writeFileSync(esPath, readFileSync(esPath, "utf8").replace("settings-language-label = Idioma", "settings-language-label = Su idioma, usted"));
      writeFileSync(join(root, "pinned.en.json"), JSON.stringify({ "spike-consent-wall": "Something else entirely." }));
      const { blocking } = checkCatalog(root);
      const has = (text: string) => expect(blocking.some((b) => b.includes(text)), `${text}\n${blocking.join("\n")}`).toBe(true);
      has("probe-label: kind: label has no full stop");
      has("probe-error: next-step");
      has('probe-case: kind: label is sentence case ("Companies")');
      has("probe-dup: duplicate: says the same as settings-language-label");
      has("probe-kindless: no kind");
      has("probe-role: parity: English uses the term -role");
      has("settings-language-label: register: usted");
      has("pinned.en.json: spike-consent-wall changed");
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });

  it("a message moved as-is reports its wording instead of blocking, and still needs a kind", () => {
    const root = mkdtempSync(join(tmpdir(), "copy-check-"));
    try {
      cpSync(COPY, root, { recursive: true, filter: (src) => !src.includes(`${join(COPY, "gen")}`) });
      const add = (path: string, text: string) => writeFileSync(join(root, path), readFileSync(join(root, path), "utf8") + text);
      // A text the code held, with problems: the snapshot proves where it came from.
      const found = "Sync now — scraper.";
      const asFound = join(root, "as-found.json");
      writeFileSync(asFound, JSON.stringify(["Syncnowscraper", "Something", "openrole"]));
      add("en/settings.ftl", [
        `# kind=label wording=as-is\nprobe-asis = ${found}\n`,
        `# kind=label\nprobe-reviewed = ${found}\n`,
        "# wording=as-is\nprobe-asis-kindless = Something\n",
        "# kind=label wording=as-is\nprobe-asis-new = Something we just wrote\n",
        "# kind=label wording=as-is\nprobe-asis-plural = { $n ->\n    [one] { $n } open role\n   *[other] { $n } open roles\n}\n",
      ].join(""));
      const before = checkCatalog(COPY).asIs;
      const { blocking, reports, asIs } = checkCatalog(root, asFound);
      const blocks = (id: string) => blocking.filter((b) => b.includes(`${id}:`));
      expect(blocks("probe-asis")).toEqual([]);
      expect(reports.some((r) => r.includes("probe-asis (as-is): vocabulary: sync"))).toBe(true);
      expect(reports.some((r) => r.includes("probe-asis (as-is): mechanics"))).toBe(true);
      expect(blocks("probe-reviewed").length).toBeGreaterThanOrEqual(3);
      expect(blocks("probe-asis-kindless").some((b) => b.includes("no kind"))).toBe(true);
      // New wording cannot hide behind the marker; a hand-built plural's other form can.
      expect(blocks("probe-asis-new").some((b) => b.includes("as-is: \"Something we just wrote\" is not text the code held"))).toBe(true);
      expect(blocks("probe-asis-plural")).toEqual([]);
      expect(asIs - before).toBe(4);
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });
});

/* A translation says what its English said when it was translated
 * (`<locale>/translated-from.json`). When the English changes, the
 * translation is stale until someone checks it against the new English and
 * names it: a report while the language is beta, a failure once complete. */
// Each test here runs the whole catalog check on a scratch copy several times,
// so its run time grows with the catalog and the runner's speed. Vitest's 5 s
// default is not a budget for that: a test fails on what it reports, not on
// how long a full check of a growing catalog takes.
describe("translations follow their English (fail-first)", { timeout: 30_000 }, () => {
  const scratch = () => {
    const root = mkdtempSync(join(tmpdir(), "copy-from-"));
    cpSync(COPY, root, { recursive: true, filter: (src) => !src.includes(`${join(COPY, "gen")}`) });
    return root;
  };
  const edit = (root: string, path: string, from: string, to: string) => {
    const text = readFileSync(join(root, path), "utf8");
    expect(text).toContain(from);
    writeFileSync(join(root, path), text.replace(from, to));
  };
  const lines = (list: string[], id: string, rule: string) => list.filter((l) => l.includes(` ${id}: ${rule}:`));

  it("every Spanish and Chinese translation records its English, and none is stale", () => {
    const { reports, blocking } = checkCatalog();
    const off = [...reports, ...blocking].filter((l) => /: (stale|untracked):|no longer translates/.test(l));
    expect(off, off.slice(0, 5).join("\n")).toEqual([]);
  });

  it("an English change makes each translation stale; reflowing it or its comment does not", () => {
    const root = scratch();
    try {
      edit(root, "en/settings.ftl", "# kind=label\nsettings-language-label = Language", "# kind=label wording=as-is\nsettings-language-label =\n    Language");
      expect(checkCatalog(root).reports.filter((l) => /: (stale|untracked):/.test(l))).toEqual([]);

      edit(root, "en/settings.ftl", "settings-language-label =\n    Language", "settings-language-label = Display language");
      const { reports, blocking } = checkCatalog(root);
      expect(lines(reports, "settings-language-label", "stale").map((l) => l.split(" ")[0])).toEqual(["es/settings.ftl", "zh-Hans/settings.ftl"]);
      expect(lines(blocking, "settings-language-label", "stale")).toEqual([]);

      // Complete: a stale translation fails.
      const manifest = join(root, "locales.json");
      const declared = JSON.parse(readFileSync(manifest, "utf8"));
      declared.locales.find((l: {code:string})=>l.code==="es").status="complete";
      writeFileSync(manifest,JSON.stringify(declared));
      expect(lines(checkCatalog(root).blocking, "settings-language-label", "stale")).toHaveLength(1);
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });

  it("recording keeps a stale translation stale unless it is named, and tracks a new one", () => {
    const root = scratch();
    try {
      edit(root, "en/settings.ftl", "settings-language-label = Language", "settings-language-label = Display language");
      writeFileSync(join(root, "en/settings.ftl"), readFileSync(join(root, "en/settings.ftl"), "utf8") + "# kind=label\nprobe-new = Something new\n");
      writeFileSync(join(root, "es/settings.ftl"), readFileSync(join(root, "es/settings.ftl"), "utf8") + "probe-new = Algo nuevo\nprobe-gone = Ya no existe\n");
      // A translation of a message English does not have is not recorded.
      expect(() => recordTranslated(root, "es", ["probe-gone"])).toThrow(/does not translate probe-gone/);
      writeFileSync(join(root, "es/settings.ftl"), readFileSync(join(root, "es/settings.ftl"), "utf8").replace("probe-gone = Ya no existe\n", ""));
      expect(lines(checkCatalog(root).reports, "probe-new", "untracked")).toHaveLength(1);

      expect(recordTranslated(root, "es").recorded).toEqual(["probe-new"]);
      let reports = checkCatalog(root).reports;
      expect(lines(reports, "probe-new", "untracked")).toEqual([]);
      expect(lines(reports, "settings-language-label", "stale")).toHaveLength(2);

      expect(recordTranslated(root, "es", ["settings-language-label"]).recorded).toEqual(["settings-language-label"]);
      reports = checkCatalog(root).reports;
      expect(lines(reports, "settings-language-label", "stale").map((l) => l.split(" ")[0])).toEqual(["zh-Hans/settings.ftl"]);

      // A message English drops leaves the record with it.
      edit(root, "en/settings.ftl", "# kind=label\nprobe-new = Something new\n", "");
      edit(root, "es/settings.ftl", "probe-new = Algo nuevo\n", "");
      expect(checkCatalog(root).reports.some((l) => l.startsWith("es: translated-from.json records 1 messages"))).toBe(true);
      expect(recordTranslated(root, "es").dropped).toEqual(["probe-new"]);
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });

  it("Chinese punctuation ends a sentence, and Chinese words are counted as words", () => {
    const root = scratch();
    try {
      writeFileSync(join(root, "en/settings.ftl"), readFileSync(join(root, "en/settings.ftl"), "utf8") + [
        "# kind=sentence\nprobe-sentence = It is saved.\n",
        "# kind=error\nprobe-error = Couldn't save it. Try again.\n",
        "# kind=label\nprobe-label-stop = Saved\n",
        "# kind=label\nprobe-label-long = Use a model\n",
      ].join(""));
      writeFileSync(join(root, "zh-Hans/settings.ftl"), readFileSync(join(root, "zh-Hans/settings.ftl"), "utf8") + [
        "probe-sentence = 已保存。\n",
        "probe-error = 无法保存。请重试。\n",
        "probe-label-stop = 已保存。\n",
        "probe-label-long = 使用你自己在本机运行的模型\n",
      ].join(""));
      const { reports } = checkCatalog(root);
      expect(lines(reports, "probe-sentence", "kind")).toEqual([]);
      expect(lines(reports, "probe-error", "next-step")).toEqual([]);
      expect(lines(reports, "probe-label-stop", "kind").map((l) => l.split("kind: ")[1])).toEqual(["label has no full stop"]);
      expect(lines(reports, "probe-label-long", "kind").map((l) => l.split("kind: ")[1])).toEqual(["label is at most 4 words"]);
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });
});

describe("what the extractor counts as copy (fail-first)", () => {
  const texts = (src: string) => extractFile("features/probe/Probe.tsx", src).strings.map((x) => x.text);
  it("counts words written beside a value, a single-word plural and a lone JSX word", () => {
    expect(texts("export const f = (n: number) => `${n} companies`;")).toContain("{n} companies");
    expect(texts("export const f = (n: number) => (n === 1 ? \"role\" : \"roles\");")).toEqual(expect.arrayContaining(["role", "roles"]));
    expect(texts("export const C = () => <span>found</span>;")).toContain("found");
  });
  it("counts one word handed to a prop a screen shows, which alone reads like a slug", () => {
    expect(texts('export const k = { label: "New", value: 3, sub: "today" };')).toContain("today");
    expect(texts('export const C = () => <Panel label="clusters" />;')).toContain("clusters");
    expect(texts('export const C = (x?: string) => <Panel title={x ?? "overlap"} />;')).toContain("overlap");
    expect(texts('export const o = { visualMap: { text: [more(), "less"] } };')).toContain("less");
    expect(texts('export const r = { label: "min–max" };')).toContain("min–max");
  });
  it("leaves a one-word code value alone, beside a display prop or in a prop nobody reads", () => {
    expect(texts('export const s = { type: "line", mode: "today", key: "alike" };')).toEqual([]);
    expect(texts('export const C = () => <Panel tone="good" variant="ghost" />;')).toEqual([]);
    expect(texts('export const o = { data: ["less", "more"] };')).toEqual([]);
    // Notation with no word in it: a percentile is not copy to translate.
    expect(texts('export const k = { sub: "p90" };')).toEqual([]);
    expect(texts('export const k = { label: /* not copy */ "today" };')).toEqual([]);
  });
  it("leaves code alone: a class list, a CSS value, a key cap, a lookup Set, and anything marked not copy", () => {
    expect(texts("export const f = (on: boolean) => `chip-row is-${on}`;")).toEqual([]);
    expect(texts("export const f = (x: number) => `${x}px`;")).toEqual([]);
    expect(texts("export const C = () => <Kbd>esc</Kbd>;")).toEqual([]);
    expect(texts("const S = new Set([\"United Kingdom\", \"Netherlands\"]); export const f = (x: string) => S.has(x);")).toEqual([]);
    expect(texts("export const f = (n: number) => /* not copy: CSS */ `${n} columns wide`;")).toEqual([]);
    // The marker is what excludes it: the same template unmarked counts.
    expect(texts("export const f = (n: number) => `${n} columns wide`;")).toContain("{n} columns wide");
  });
  it("counts a lone word a ternary hands to JSX, a phrase shaped like a class list, a hand-built plural's words and a word placed in a message's slot", () => {
    expect(texts('export const C = ({ s }: { s: boolean }) => <span>{s ? "stated" : "estimated"}</span>;')).toEqual(["stated", "estimated"]);
    expect(texts('export const C = ({ r }: { r: string }) => <b>{r === "original" ? "original" : r}</b>;')).toEqual(["original"]);
    expect(texts('export const T = { mix: { tag: "employee-selected mix" } };')).toEqual(["employee-selected mix"]);
    expect(texts('export const C = () => <Panel label="employee-selected mix" />;')).toEqual(["employee-selected mix"]);
    expect(texts('export const f = (n: number) => count(n, "question", "questions");')).toEqual(["question", "questions"]);
    expect(texts('import { m } from "../../copy/gen/x"; export const C = () => <Msg of={m} elems={{ unit: "yearly" }} />;')).toEqual(["yearly"]);
  });
  it("leaves their code twins alone: a comparison, a key, a class holder, code shown as code, a pair that is no plural, and a marked line", () => {
    expect(texts('export const C = ({ s }: { s: string }) => <span className={s === "open" ? "is-open" : "is-shut"}>{s}</span>;')).toEqual([]);
    expect(texts('export const T = { "employee-selected": 1, cls: "rail-badge rail-badge-dot", badgeClass: "stat-chip good" };')).toEqual([]);
    expect(texts('export const C = ({ f }: { f: boolean }) => <code>{f ? "--max-list" : "dry-run"}</code>;')).toEqual([]);
    expect(texts('export const C = ({ k }: { k: boolean }) => <Kbd>{k ? "esc" : "tab"}</Kbd>;')).toEqual([]);
    expect(texts('export const f = (a: string) => pick(a, "left", "right");')).toEqual([]);
    expect(texts('export const C = () => <Panel data-testid={id("row", "rows")} data-state="employee-selected mix" />;')).toEqual([]);
    expect(texts('export const C = ({ s }: { s: boolean }) => <span>{/* not copy */ s ? "stated" : "estimated"}</span>;')).toEqual([]);
  });
});

describe("the habits only the syntax tree shows (fail-first)", () => {
  const habits = (src: string) => extractFile("features/probe/Probe.tsx", src).habits.map((h) => `${h.habit} ${h.text}`);
  const head = 'import { allShown, of, aboutIt } from "../../copy/gen/scan";\n';

  it("counts punctuation written beside a message, a bare space handed to a slot, and catalog text recased by code", () => {
    expect(habits(head + "export const C = ({ n }: { n: number }) => <span><Msg of={allShown} elems={{ n }} />{of({ n })})</span>;")).toEqual(["split-sentence )"]);
    expect(habits(head + "export const C = () => <p>(<Msg of={allShown} elems={{ n: 1 }} /></p>;")).toEqual(["split-sentence ("]);
    expect(habits(head + 'export const C = () => <p><Msg of={aboutIt} elems={{ value: " " }} /></p>;')).toEqual(['message-spacer " "']);
    expect(habits(head + 'export const f = () => aboutIt({ value: " " });')).toEqual(['message-spacer " "']);
    expect(habits(head + "export const f = (bandLabel: string) => aboutIt({ band: String(bandLabel.toLowerCase()) });")).toEqual(["recased-copy bandLabel.toLowerCase()"]);
    expect(habits(head + "export const f = () => aboutIt().toUpperCase();")).toEqual(["recased-copy aboutIt().toUpperCase()"]);
    expect(habits("const BAND_LABEL: Record<string, string> = {};\nexport const f = (b: string) => (BAND_LABEL[b] ?? b).toLowerCase();")).toEqual(["recased-copy (BAND_LABEL[b] ?? b).toLowerCase()"]);
    expect(habits("export const f = (fact: { label: string }) => fact.label.toLowerCase();")).toEqual(["recased-copy fact.label.toLowerCase()"]);
  });

  it("leaves their code twins alone: punctuation beside a value, a separator, a space in a plain object, and recasing to compare or search", () => {
    expect(habits(head + "export const C = ({ n }: { n: number }) => <span>({n})</span>;")).toEqual([]);
    expect(habits(head + "export const C = () => <span>{allShown()} · {of()}</span>;")).toEqual([]);
    expect(habits('export const o = { value: " " };')).toEqual([]);
    expect(habits(head + 'export const f = (g: (a: object) => string) => g({ value: " " });')).toEqual([]);
    expect(habits("export const f = (label: string, q: string) => label.toLowerCase().includes(q);")).toEqual([]);
    expect(habits("export const f = (title: string, q: string) => title.toLowerCase() === q;")).toEqual([]);
    expect(habits(head + "export const f = (q: string) => q.includes(aboutIt().toLowerCase());")).toEqual([]);
    expect(habits("export const f = (slug: string, e: { key: string }) => [slug.toLowerCase(), e.key.toLowerCase()];")).toEqual([]);
    expect(habits("export const f = (label: string) => /* not copy */ label.toLowerCase();")).toEqual([]);
  });

  it("counts each habit for its folder, where the ratchet holds it", () => {
    const root = mkdtempSync(join(tmpdir(), "copy-habit-"));
    try {
      mkdirSync(join(root, "features", "probe"), { recursive: true });
      writeFileSync(join(root, "features", "probe", "Probe.tsx"), head + 'export const f = (label: string) => aboutIt({ label: String(label.toLowerCase()), value: " " });\n');
      expect(checkSource(root).counts["features/probe"]).toEqual({ "message-spacer": 1, "recased-copy": 1 });
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });
});
