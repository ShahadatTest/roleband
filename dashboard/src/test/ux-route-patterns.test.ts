import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

/**
 * A UX route pattern must be anchored to the app's own origin.
 *
 * A pattern written as star-star-slash-`api/jobs?**` reads like "our jobs
 * endpoint" and is not. Playwright resolves a pattern that does not start with
 * `*` against `baseURL`; one that DOES start with `**` matches any origin and
 * any path depth — including the dev server's own source modules. `src/api/`
 * is a real directory, so in dev mode that jobs pattern
 * matches `/src/api/jobs.ts` (glob `?` is one character), and the equivalent
 * notifications pattern matches `/src/api/notifications.ts`. Such a mock answers
 * a module request with JSON, the browser refuses it on MIME type, and the app
 * never boots on the dev-server path.
 *
 * CI serves a build, where no `/src/...` URL exists, so the suite being green
 * there is evidence about one serving mode only. That is why this gate reads the SOURCE instead of
 * waiting for a run to go red.
 *
 * Write `"/api/jobs?**"`. It resolves against `baseURL`, so it cannot reach
 * another origin and cannot reach a path that merely contains `/api/`.
 */

const UX_DIR = join(__dirname, "..", "..", "tests", "ux");
/** `**` followed by a slash and `api/` — the shape that matches any origin. */
const UNANCHORED = /["'`]\*\*\/api\//g;

function uxFiles(): string[] {
  return readdirSync(UX_DIR).filter((name) => name.endsWith(".ts"));
}

describe("UX route patterns", () => {
  it("covers a directory that actually holds specs", () => {
    // A path that stopped resolving would make every assertion below vacuous,
    // which is the failure mode this repo keeps finding in its own gates.
    const files = uxFiles();
    expect(files.length).toBeGreaterThan(20);
    expect(files).toContain("fixtures.ts");
    expect(files).toContain("boardHarness.ts");
  });

  it("anchors every API mock to the app origin", () => {
    const offenders: string[] = [];
    for (const name of uxFiles()) {
      const source = readFileSync(join(UX_DIR, name), "utf8");
      for (const line of source.split("\n")) {
        // The explanatory comments in fixtures.ts and this file's twin are
        // prose about the hazard, not patterns handed to Playwright.
        if (/^\s*(\*|\/\/)/.test(line)) continue;
        if (UNANCHORED.test(line)) offenders.push(`${name}: ${line.trim().slice(0, 100)}`);
        UNANCHORED.lastIndex = 0;
      }
    }
    expect(offenders).toEqual([]);
  });

  it("fails on a planted unanchored pattern", () => {
    // The gate above is worth nothing unless it can see the thing it forbids.
    const planted = '  await mockGet(page, "**/api/jobs?**", handler);';
    expect(UNANCHORED.test(planted)).toBe(true);
    UNANCHORED.lastIndex = 0;
    const anchored = '  await mockGet(page, "/api/jobs?**", handler);';
    expect(UNANCHORED.test(anchored)).toBe(false);
    UNANCHORED.lastIndex = 0;
  });

  it("does not object to a non-API wildcard", () => {
    // Only the `/api/` collision is at stake; a spec routing some other
    // wildcard is none of this gate's business.
    expect(UNANCHORED.test('page.route("**/*.woff2", handler)')).toBe(false);
    UNANCHORED.lastIndex = 0;
  });
});
