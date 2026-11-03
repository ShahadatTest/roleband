// The Mac app's own sentences speak about the person's work, never about the app by name:
// the person is already in it. Names stay where they name something (a button, a title).
import { join } from "node:path";
import { expect, it } from "vitest";
import { readLocale } from "../../scripts/copy/catalog.mjs";

const COPY = join(__dirname);
const NAMING_KINDS = new Set(["label", "button", "heading", "link", "aria"]);

it.each(["en", "es", "zh-Hans"])("no %s launcher sentence names the app", (locale) => {
  const english = new Map(readLocale(COPY, "en").messages.map((m: { id: string; meta: { kind?: string } }) => [m.id, m]));
  const offenders = readLocale(COPY, locale).messages
    .filter((m: { id: string; file: string }) => /(^|\/)launcher[^/]*\.ftl$/.test(m.file))
    .filter((m: { id: string }) => !NAMING_KINDS.has(english.get(m.id)?.meta.kind ?? ""))
    .filter((m: { src: string; pattern: { span: { start: number; end: number } } }) =>
      m.src.slice(m.pattern.span.start, m.pattern.span.end).includes("RoleBand"))
    .map((m: { id: string }) => m.id);
  expect(offenders).toEqual([]);
});
