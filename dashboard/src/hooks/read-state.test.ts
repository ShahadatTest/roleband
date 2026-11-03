import { readFileSync, readdirSync, statSync } from "node:fs";
import { dirname, join, relative } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const SRC = join(dirname(fileURLToPath(import.meta.url)), "..");

/* One read-state vocabulary.
 *
 * A screen that invents its own `list / loading / error / attempt` invents
 * slightly different ordering, retry and failure rules. The shapes are the bug, not the duplication: a
 * hand-rolled triple has no generation, so whichever response arrives last
 * wins, and "last" is not "newest" when a poll races a row action.
 *
 * So: a migrated feature does not declare request state. It calls
 * `useAsyncResource`, which owns loading, error, retry, refresh and ordering.
 */

const EMPTY = String.raw`(?:\[\]|\{\}|""|''|new (?:Map|Set)\(\))`;
/** `.catch(() => setRows([]))`, `.catch(() => [])`, and a keyed write of an
 *  empty value in the catch (`setByKey((prev) => ({ ...prev, [k]: [] }))`). */
/* A bare `{}` after the arrow is an empty function body (a fire-and-forget
 * write that reports elsewhere), not an empty value, so the direct return
 * names lists, strings and collections only. */
const RETURNED = String.raw`(?:\[\]|""|''|new (?:Map|Set)\(\))`;
const SWALLOWED = new RegExp(
  String.raw`\.catch\(\s*\(?\w*\)?\s*=>\s*(?:\{[^}]*?)?(?:set\w+\(\s*(?:\(?\w*\)?\s*=>\s*\(\{[^)]*:\s*${EMPTY}\s*\}\)|${EMPTY})\s*\)|${RETURNED}\s*\))`,
);

function sourceFiles(dir: string, acc: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) sourceFiles(path, acc);
    else if (/\.tsx?$/.test(name) && !/\.test\.tsx?$/.test(name)) acc.push(path);
  }
  return acc;
}

/** A local loading flag, a local Error box, a hand-rolled retry counter, or a
 *  failure caught into an empty value: an empty list reads as "nothing here",
 *  which is a claim about the data the failed request never made. */
const TRIPLE = [
  { name: "a local loading flag", pattern: /\b(?:const|let)\s*\[\s*loading\s*,|setLoading\s*\(/ },
  { name: "a local Error box", pattern: /useState<\s*Error\s*\|\s*null\s*>|useState<\s*Error\s*>/ },
  { name: "a hand-rolled retry counter", pattern: /\bsetAttempt\s*\(/ },
  { name: "a failure swallowed into an empty value", pattern: SWALLOWED },
];

/* The one exception, named rather than wildcarded. `useBoardBaseline` is not a
 * request — it is a cache keyed by query CONTEXT and seeded from the board list
 * itself: an unnarrowed response IS the unfiltered total, so the common case
 * makes no request at all (a pinned contract). `useAsyncResource`
 * always fires and cannot be seeded from outside, so migrating it would trade a
 * measured optimisation for uniformity. Its `attempt` is a retry trigger, not an
 * ordering mechanism. `useBoardBaseline.test.tsx` exercises supersession,
 * key-scoped results, late failures and retry through the real hook. */
const EXEMPT = new Map([
  ["features/opportunities/useBoardBaseline.ts", "a hand-rolled retry counter"],
  // The read-state owner itself: its retry counter is the one this gate points at.
  ["hooks/useAsyncResource.ts", "a hand-rolled retry counter"],
]);

describe("read-state ownership", () => {
  it("no source file keeps its own request state or swallows a failed read", () => {
    const offenders: string[] = [];
    for (const file of sourceFiles(SRC)) {
      const source = readFileSync(file, "utf8");
      const rel = relative(SRC, file);
      for (const { name, pattern } of TRIPLE) {
        if (!pattern.test(source)) continue;
        if (EXEMPT.get(rel) === name) continue;
        offenders.push(`${rel}: ${name}`);
      }
    }
    expect(
      offenders,
      "A feature declaring its own loading/error/attempt has no request " +
        "generation, so a slow response can overwrite a newer one. Use " +
        "hooks/useAsyncResource — it owns loading, error, retry, refresh and ordering.",
    ).toEqual([]);
  });

  it.each([
    [".catch(() => setTop([]))", true],
    [".catch(() => [])", true],
    [".catch(() => { if (!cancelled) setBandJobs((prev) => ({ ...prev, [band]: [] })); })", true],
    [".catch((e) => setError(errorText(e)))", false],
    [".catch(() => null)", false],
    [".catch(() => {})", false],
  ])("the swallowed-failure shape matches %s: %s (negative control included)", (line, swallowed) => {
    expect(SWALLOWED.test(line)).toBe(swallowed);
  });

  it("the resource is what the migrated controllers actually call", () => {
    // A gate that only forbids is satisfiable by deleting the feature. Name the
    // migrated controllers, so the absence above means adoption.
    for (const controller of [
      "features/saved/useSavedController.ts",
      "features/notifications/useNotificationsController.ts",
      "features/opportunities/useBoardController.ts",
      "features/compare/useCompareController.ts",
      "features/company-profiles/CompanyProfilesView.tsx",
    ]) {
      expect(readFileSync(join(SRC, controller), "utf8"), controller).toContain("useAsyncResource");
    }
  });

  // Mutation recovery is rendered in SavedScreen.test.tsx,
  // useBoardController.test.tsx and NotificationScreen.test.tsx. Controller
  // source spellings cannot establish whether a rejected write recovers.
});
