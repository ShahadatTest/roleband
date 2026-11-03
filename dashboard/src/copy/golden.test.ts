// The compiler, held to literal text on its own fixture catalog
// (`src/copy/__golden__/`), apart from the product catalog it compiles: a defect
// the compiler and the `msg()` helper shared would agree with itself everywhere
// else (rule T4, src/test/msg.ts). One case per construct the subset allows, and the
// constructs it refuses.
import { existsSync, mkdtempSync, rmSync, writeFileSync, mkdirSync, cpSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { CopyError, build, metadata, write } from "../../scripts/gen-copy.mjs";
import { setActive } from "./runtime";

const ROOT = join(__dirname, "__golden__");
const OUT = join(__dirname, "..", "..", "node_modules", ".cache", "copy-golden");
const RUNTIME = join(__dirname, "runtime");

type Fn = (a?: Record<string, unknown>) => string;
let en: Record<string, Fn>;
let es: (Fn | undefined)[];
let xa: (Fn | undefined)[];

beforeAll(async () => {
  rmSync(OUT, { recursive: true, force: true });
  write(build({ root: ROOT, gen: OUT, runtime: RUNTIME }).files);
  en = await import(/* @vite-ignore */ join(OUT, "golden.ts"));
  es = (await import(/* @vite-ignore */ join(OUT, "locales", "es.ts"))).default;
  xa = (await import(/* @vite-ignore */ join(OUT, "locales", "en-XA.ts"))).default;
});
afterAll(() => setActive({ table: null, language: "en", tableLanguage: "en", region: null }));

const english = () => setActive({ table: null, language: "en", tableLanguage: "en", region: "en-US" });
const spanish = () => setActive({ table: es, language: "es", tableLanguage: "es", region: "es-ES" });

describe("English", () => {
  it("says each construct as written", () => {
    english();
    expect(en.plain()).toBe("Saved");
    expect([0, 1, 2, 1000].map((count) => en.exactBeforeCategory({ count }))).toEqual([
      "Nothing yet", "One posting", "2 postings", "1,000 postings",
    ]);
    expect(en.byString({ stage: "applied" })).toBe("You applied");
    expect(en.byString({ stage: "anything" })).toBe("You are considering it");
    expect(en.twoValues({ company: "Stripe", count: 3 })).toBe("Stripe has 3 open");
    expect([en.withAttributes(), en.withAttributesPlaceholder(), en.withAttributesAriaLabel()]).toEqual([
      "Search", "Search titles and descriptions", "Search roles",
    ]);
    expect(en.escaped()).toBe("Braces stay literal: {name} and “quotes”.");
  });
});

describe("Spanish", () => {
  it("selects the exact number first, then the plural category, with gender from the term", () => {
    spanish();
    // Spanish has a third category, `many`, for millions: "1.000.000 de ofertas".
    expect([0, 1, 2, 1000, 1000000].map((count) => en.exactBeforeCategory({ count }))).toEqual([
      "Nada todavía", "1 oferta", "2 ofertas", "1000 ofertas", "1.000.000 de ofertas",
    ]);
    expect(en.byString({ stage: "applied" })).toBe("Te postulaste");
    expect(en.byString({ stage: "considering" })).toBe("La estás considerando");
    expect(en.withAttributesPlaceholder()).toBe("Buscar en títulos y descripciones");
    expect(en.escaped()).toBe("Las llaves se quedan: {name} y «comillas».");
  });
});

describe("the pseudo locale", () => {
  it("accents the catalog's words, never a value, and brackets the whole message", () => {
    setActive({ table: xa, language: "en-XA", tableLanguage: "en", region: "en-US" });
    expect(en.twoValues({ company: "Stripe", count: 3 })).toMatch(/^⟦Stripe ĥàš 3 öþéñ·+⟧$/);
  });
});

describe("metadata", () => {
  it("reads kind, width and a quoted note from the comment", () => {
    expect(metadata('kind=label width=148px note="Keep it, verbatim"')).toEqual({ kind: "label", width: "148px", note: "Keep it, verbatim" });
  });
});

describe("what the subset refuses, with file and line", () => {
  const cases: [string, RegExp][] = [
    ["broken = { -thing(num: $count) }\n", /golden\.ftl:\d+: E0014/],
    ["ref = { plain }\n", /never includes another message/],
    ["fn = { NUMBER($count) }\n", /NUMBER\(\) is not in the subset/],
    ["missing = { -nothing }\n", /unknown term -nothing/],
  ];
  it.each(cases)("%s", (line, why) => {
    const root = mkdtempSync(join(tmpdir(), "copy-golden-"));
    try {
      cpSync(ROOT, root, { recursive: true });
      mkdirSync(join(root, "en"), { recursive: true });
      writeFileSync(join(root, "en", "golden.ftl"), `-thing = thing\nplain = Saved\n${line}`);
      writeFileSync(join(root, "es", "golden.ftl"), "");
      expect(() => build({ root, gen: join(root, "gen"), runtime: RUNTIME })).toThrow(CopyError);
      expect(() => build({ root, gen: join(root, "gen"), runtime: RUNTIME })).toThrow(why);
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });

  it("a complete locale missing a message fails the build", () => {
    const root = mkdtempSync(join(tmpdir(), "copy-golden-"));
    try {
      cpSync(ROOT, root, { recursive: true });
      writeFileSync(join(root, "es", "golden.ftl"), "plain = Guardado\n");
      expect(() => build({ root, gen: join(root, "gen"), runtime: RUNTIME })).toThrow(/es is complete but \d+ messages are missing/);
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });});

describe("message ids", () => {
  it("numbers a shell file's messages first, so a lazy file's new message never renumbers them", () => {
    const root = mkdtempSync(join(tmpdir(), "copy-golden-"));
    try {
      mkdirSync(join(root, "en"));
      mkdirSync(join(root, "es"));
      writeFileSync(join(root, "locales.json"), JSON.stringify({ locales: [{ code: "en", status: "complete", fallback: [] }] }));
      writeFileSync(join(root, "en", "zz-shell.ftl"), "### eager: the shell imports this file\n\nzz-one = One\nzz-two = Two\n");
      writeFileSync(join(root, "en", "aa-lazy.ftl"), "aa-one = A\n");
      const before = build({ root, gen: join(root, "gen"), runtime: RUNTIME }).ids;
      expect(before).toEqual(["zz-one", "zz-two", "aa-one"]);
      writeFileSync(join(root, "en", "aa-lazy.ftl"), "aa-one = A\naa-two = B\nab-new = C\n");
      const after = build({ root, gen: join(root, "gen"), runtime: RUNTIME }).ids;
      expect(after.slice(0, 2)).toEqual(["zz-one", "zz-two"]);
      expect(after).toEqual(["zz-one", "zz-two", "aa-one", "aa-two", "ab-new"]);
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });
});

describe("a keyed file", () => {
  it("exports every message by its key, and only a file that asks for it does", () => {
    const root = mkdtempSync(join(tmpdir(), "copy-golden-"));
    try {
      mkdirSync(join(root, "en"));
      writeFileSync(join(root, "locales.json"), JSON.stringify({ locales: [{ code: "en", status: "complete", fallback: [] }] }));
      writeFileSync(join(root, "en", "kk.ftl"), "### keyed: looked up by slug\n\nkk-alpha = Alpha\nkk-beta = { $n } beta\n    .title = Beta\n");
      writeFileSync(join(root, "en", "pp.ftl"), "pp-plain = Plain\n");
      const { files } = build({ root, gen: join(root, "gen"), runtime: RUNTIME });
      const keyed = files.get(join(root, "gen", "kk.ts"))!;
      expect(keyed).toMatch(/export const byKey: Record<string, \(a\?: any\) => string> = \{\n {2}"kk-alpha": kkAlpha,\n {2}"kk-beta": kkBeta,\n\};/);
      // An attribute is a property of its message, never a key of its own.
      expect(keyed).not.toContain('"kk-beta.title"');
      expect(files.get(join(root, "gen", "pp.ts"))).not.toContain("byKey");
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });
});

describe("a locale table", () => {
  it("names the parameter only when the message reads one, whatever its words say", () => {
    const root = mkdtempSync(join(tmpdir(), "copy-golden-"));
    try {
      mkdirSync(join(root, "en"));
      mkdirSync(join(root, "es"));
      writeFileSync(join(root, "locales.json"), JSON.stringify({ locales: [
        { code: "en", status: "complete", fallback: [] }, { code: "es", status: "beta", fallback: ["en"] },
      ] }));
      writeFileSync(join(root, "en", "tt.ftl"), "tt-plain = Its page answered.\ntt-count = { $count } roles\ntt-only-default = { $count ->\n    [one] Company\n   *[other] Companies\n}\n");
      // "…a." in the words once read as a use of the parameter `a`.
      writeFileSync(join(root, "es", "tt.ftl"), "tt-plain = Respondió a.\ntt-count = { $count } puestos\ntt-only-default = { $count ->\n   *[other] Empresas\n}\n");
      const table = build({ root, gen: join(root, "gen"), runtime: RUNTIME }).files.get(join(root, "gen", "locales", "es.ts"))!;
      expect(table).toContain('(_a: any): string => "Respondió a."');
      expect(table).toMatch(/\(a: any\): string => F\(a\.count\)/);
      // A select left with only its default (Chinese has no plurals) reads nothing.
      expect(table).toContain('(_a: any): string => ("Empresas")');
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });
});

describe("the generated folder", () => {
  it("removes the table of a locale taken out of locales.json, and only what it no longer makes", () => {
    const gen = mkdtempSync(join(tmpdir(), "copy-gen-"));
    try {
      const { files } = build({ root: ROOT, gen, runtime: RUNTIME });
      write(files, { gen });
      const left = join(gen, "locales", "ru.ts");
      writeFileSync(left, "export default [];\n");
      // --check names it and changes nothing.
      expect(write(files, { check: true, gen })).toEqual([left]);
      expect(existsSync(left)).toBe(true);
      // A write removes it and keeps every table the build makes.
      expect(write(files, { gen })).toEqual([left]);
      expect(existsSync(left)).toBe(false);
      expect(existsSync(join(gen, "locales", "es.ts"))).toBe(true);
      expect(existsSync(join(gen, "golden.ts"))).toBe(true);
      expect(write(files, { check: true, gen })).toEqual([]);
    } finally {
      rmSync(gen, { recursive: true, force: true });
    }
  });
});
