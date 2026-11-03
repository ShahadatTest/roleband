import { expect, isGuardedApiRequest, test } from "./fixtures";

/**
 * The guard that refuses unmocked API calls, held against planted cases.
 *
 * `context.route("**\/api/**")` cannot tell an API call from a source module
 * under `src/api/`: on the dev-server path a guard on the glob alone throws on
 * `/src/api/index.ts` and fails nearly every test, while CI, which serves a
 * build with no `/src/...` URLs, never sees it. That is why the cases below
 * assert the DECISION rather than observing the suite go green. A suite that
 * passes in one of the two serving modes is not evidence about the other.
 *
 * Both directions are planted. A guard that stopped guarding would pass a test
 * that only checked the module case, and that is the failure mode that costs
 * something: a test silently talking to a real API.
 */

const APP = "http://127.0.0.1:5173";

test.describe("the unmocked-API guard", () => {
  test("refuses a real API call on the app's own origin", () => {
    expect(isGuardedApiRequest(`${APP}/api/jobs?page=1`, APP)).toBe(true);
    expect(isGuardedApiRequest(`${APP}/api/scope/catalog`, APP)).toBe(true);
    // The compare-selection default is registered as its own route; the guard
    // must still classify it as ours, or that default would never be reached.
    expect(isGuardedApiRequest(`${APP}/api/compare-selection`, APP)).toBe(true);
  });

  test("ignores a dev-server module that merely lives under src/api", () => {
    // The module request a glob-only guard refuses, and the cache-busted form
    // Vite sends after an edit.
    expect(isGuardedApiRequest(`${APP}/src/api/index.ts`, APP)).toBe(false);
    expect(isGuardedApiRequest(`${APP}/src/api/index.ts?t=1726900000000`, APP)).toBe(false);
    expect(isGuardedApiRequest(`${APP}/src/api/jobs.ts`, APP)).toBe(false);
    // Vite's own prefixes, which this rule covers without enumerating them.
    expect(isGuardedApiRequest(`${APP}/@fs/repo/dashboard/src/api/ops.ts`, APP)).toBe(false);
    expect(isGuardedApiRequest(`${APP}/node_modules/.vite/deps/api/chunk.js`, APP)).toBe(false);
  });

  test("still refuses a third-party host with /api/ in its path", () => {
    // Cross-origin is the case the guard exists for: a live API reached by
    // accident. Path shape must not excuse it.
    expect(isGuardedApiRequest("https://example.com/v1/api/track", APP)).toBe(true);
    expect(isGuardedApiRequest("https://api.example.com/api/collect", APP)).toBe(true);
    // Same host, different port is a different origin, so it is not ours.
    expect(isGuardedApiRequest("http://127.0.0.1:8010/src/api/index.ts", APP)).toBe(true);
  });

  test("refuses everything when the app origin is unknown", () => {
    // `baseURL` unset means we cannot tell ours from theirs. The safe answer is
    // a loud failure, never a request that escapes.
    expect(isGuardedApiRequest(`${APP}/src/api/index.ts`, null)).toBe(true);
    expect(isGuardedApiRequest(`${APP}/api/jobs`, null)).toBe(true);
  });
});
