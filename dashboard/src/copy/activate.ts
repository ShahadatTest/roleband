/* Loading and persistence share one intent revision. A late loader or account
 * read cannot replace a more recent choice. Account writes serialize across
 * remounts; the table is loaded before saving, so loading failure saves nothing. */
import { matchLanguage } from "./format";
import { LOCALES, LOADERS } from "./gen/index";
import { STORAGE_KEY, choice, setActive, canonicalTag, beginIntent, intentRevision, type Choice } from "./runtime";
export { LOCALES };
export const isPseudo = (code: string): boolean => LOCALES.find((l) => l.code === code)?.status === "pseudo";

async function prepare(next: Choice) {
  const code = isPseudo(next.language) ? next.language : canonicalTag(next.language);
  const known = LOCALES.find((l) => l.code === code);
  const real = known !== undefined && known.status !== "pseudo";
  const region = next.region === null ? null : canonicalTag(next.region);
  const table = known && code !== "en" ? (await LOADERS[code]()).default : null;
  return { table, language: known ? code : "en", tableLanguage: real ? code : "en", region, dir: known?.dir ?? "ltr" };
}
function commit(next: Awaited<ReturnType<typeof prepare>>, revision: number): void {
  if (revision !== intentRevision()) return;
  document.documentElement.lang = next.tableLanguage;
  document.documentElement.dir = next.dir;
  try { localStorage.setItem(STORAGE_KEY, JSON.stringify({ language: next.language, region: next.region })); }
  catch { /* device storage may be unavailable */ }
  setActive(next);
}
export async function activate(code: string, opts: { region?: string | null; revision?: number } = {}): Promise<void> {
  const revision = opts.revision ?? beginIntent();
  if (revision !== intentRevision()) return;
  commit(await prepare({ language: code, region: opts.region ?? null }), revision);
}
let writes: Promise<unknown> = Promise.resolve();
export async function saveChoice(next: Choice, save: (next: Choice) => Promise<unknown>): Promise<void> {
  const revision = beginIntent();
  const loaded = await prepare(next);
  if (revision !== intentRevision()) return;
  // Serialize actual writes, not obsolete imports. A slow old import must
  // never hold the newest choice behind a request it will not send.
  const task = writes.catch(() => undefined).then(async () => {
    if (revision !== intentRevision()) return;
    if (!isPseudo(loaded.language)) await save({ language: loaded.language, region: loaded.region });
    commit(loaded, revision);
  });
  writes = task;
  await task;
}
export async function adopt(saved: Choice, revision = intentRevision()): Promise<void> {
  const now = choice();
  if (revision !== intentRevision() || isPseudo(now.language)) return;
  if (saved.language === now.language && saved.region === now.region) return;
  await activate(saved.language, { region: saved.region, revision });
}

/** Match browser preferences to real catalogs, retaining script distinctions. */
export const negotiate = (tags: readonly string[]): string =>
  matchLanguage(tags, LOCALES.filter(l => l.status !== "pseudo").map(l => l.code));
