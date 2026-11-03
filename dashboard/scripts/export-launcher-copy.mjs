import { readFileSync, writeFileSync, mkdirSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { readLocale } from "./copy/catalog.mjs";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "../src/copy");
const out = resolve(root, "../../../launcher/macos/Sources/LauncherCore/Resources");
const check = process.argv.includes("--check");
const englishOnly = new Set(JSON.parse(readFileSync(resolve(root, "locales.json"), "utf8")).englishOnly);
const english = readLocale(root, "en").messages.filter(m => m.id.startsWith("launcher-"));
for (const locale of ["en", "es", "zh-Hans"]) {
  const local = new Map(readLocale(root, locale).messages.map(m => [m.id, m]));
  const messages = english.map(m => englishOnly.has(m.id) ? m : local.get(m.id) ?? m);
  // Native copy holds text and named values only; the app fills `{name}` itself.
  const element = (m, e) => {
    if (e.type === "TextElement") return e.value;
    if (e.type === "Placeable" && e.expression.type === "VariableReference") return `{${e.expression.id.name}}`;
    throw new Error(`${m.id}: native copy accepts text and plain variables only`);
  };
  const entries = messages.map(m => [m.id.slice("launcher-".length), m.pattern.elements.map(e => element(m, e)).join("")]);
  const content = JSON.stringify(Object.fromEntries(entries), null, 2) + "\n";
  const path = resolve(out, `copy.${locale}.json`);
  if (check) {
    if (readFileSync(path, "utf8") !== content) throw new Error(`Stale native copy: ${locale}`);
  } else {
    mkdirSync(out, { recursive: true });
    writeFileSync(path, content);
  }
}
