import { usageStateFixture } from "../../src/test/fixtures";
import { test as base, expect } from "@playwright/test";
import type { Page, Request } from "@playwright/test";

export { expect };
export type { Page } from "@playwright/test";

/**
 * Is this request one the unmocked-API guard should refuse?
 *
 * The glob below (`** slash api slash **`) is a coarse pre-filter, and it
 * cannot tell an API
 * call from a source file that happens to live under `src/api/`. Vite's dev
 * server serves every module at its own URL, and `src/api/` is a real
 * directory (the typed client, split by domain), so the glob matches
 * `/src/api/index.ts` and a guard on it alone throws on a MODULE FETCH: every
 * test fails on the dev-server path, invisibly to CI, which serves the built
 * artifact, where no `/src/...` URL exists.
 *
 * The rule is narrower than "ignore Vite's prefixes": our API is served at
 * `/api/...` on the app's own origin and nowhere else, so anything same-origin
 * outside that prefix is an app asset and none of this guard's business. An
 * allowlist of `/@vite`, `/@id`, `/@fs`, `/node_modules/` would have to grow
 * every time the dev server invents a prefix; this does not.
 *
 * Cross-origin stays fully guarded, including a third-party host with `/api/`
 * somewhere in its path: the guard exists so no unexpected request reaches a
 * live API, and that is exactly one. Unknown cases therefore resolve to
 * GUARDED — the failure direction is a loud test, never a leaked request.
 */
export function isGuardedApiRequest(requestUrl: string, appOrigin: string | null): boolean {
  const url = new URL(requestUrl);
  if (appOrigin !== null && url.origin === appOrigin) {
    return url.pathname.startsWith("/api/");
  }
  return true;
}

/** Page mocks take precedence over this context-wide backstop, including in
 * popups. Abort before failing so no unexpected request can reach a live API. */
export const test = base.extend<{ apiGuard: void }>({
  apiGuard: [async ({ context, baseURL }, use) => {
    const appOrigin = baseURL ? new URL(baseURL).origin : null;
    await context.route("/api/**", async (route) => {
      const request = route.request();
      if (!isGuardedApiRequest(request.url(), appOrigin)) {
        // An app asset the glob caught by accident. Send it to the server.
        return route.continue();
      }
      await route.abort("blockedbyclient");
      throw new Error(`Unmocked API request: ${request.method()} ${request.url()}`);
    });
    /* Every route in the app reads the compare selection on mount,
       so without a default here the guard above fires in every spec that never
       mentions Compare. Registered AFTER the catch-all deliberately: routes
       match most-recently-added first, so this one wins over it — and a page
       route still wins over both, which is how boardHarness installs the
       stateful store the persistence specs need. */
    await context.route("/api/compare-selection", (route) =>
      route.request().method() === "GET"
        ? route.fulfill({ json: { job_ids: [] } })
        : route.fallback());
    /* The same for the company names every page reads before its first render.
       Empty, so the built-in table names the fixtures' companies as
       it always has; a spec about names routes its own. */
    await context.route("/api/companies/names", (route) =>
      route.request().method() === "GET"
        ? route.fulfill({ json: { names: {} } })
        : route.fallback());
    /* Every screen that shows a posting's pay reads who answers it:
       ours here, so no "not covered" appears; a spec about a plugin answering
       pay routes its own. */
    await context.route("/api/pay-coverage", (route) =>
      route.request().method() === "GET"
        ? route.fulfill({ json: { plugin: null, plugin_name: null, companies: [] } })
        : route.fallback());
    /* A board whose list ends, or that is empty, reads whether the person
       follows every company to say what to change: not here; a spec about
       following every company routes its own. */
    await context.route("/api/companies/directory/status", (route) =>
      route.request().method() === "GET"
        ? route.fulfill({ json: { size: 0, following: false, since: null, checked: 0, to_check: 0, with_roles: 0, waiting_for_power: false } })
        : route.fallback());
    /* An approval reads each declared site's robots rules: none here,
       so no consent is offered; a spec about the rules routes its own. */
    await context.route("/api/plugins/*/robots", (route) =>
      route.request().method() === "GET"
        ? route.fulfill({ json: { sites: [], consent: null, consent_at: null } })
        : route.fallback());
    /* And the language every page activates before its first render
       (docs/copy.md). English and the system region,
       so a spec sees the copy it always has; a spec about languages routes its
       own. */
    await context.route("/api/settings/locale", (route) =>
      route.request().method() === "GET"
        ? route.fulfill({ json: { language: "en", region: null } })
        : route.fallback());
    /* No spec reaches PostHog (docs/architecture.md): the library only
       loads when a spec shares, and a spec that does routes these hosts itself
       (a page route wins over this one). */
    await context.route(/^https:\/\/[^/]*posthog\.com\//, async (route) => {
      await route.abort("blockedbyclient");
      throw new Error(`Unmocked PostHog request: ${route.request().method()} ${route.request().url()}`);
    });
    /* And usage sharing, which the shell and the welcome walk read
       (docs/architecture.md). Every group declined, so no spec is asked
       the question; a spec about sharing routes its own. */
    await context.route("/api/usage", (route) =>
      route.request().method() === "GET"
        ? route.fulfill({ json: usageStateFixture("declined") })
        : route.fallback());
    await use();
  }, { auto: true }],
});

/** A read fixture must not accidentally acknowledge a write to the same URL. */
export function mockApi(
  page: Page,
  methods: string | readonly string[],
  url: Parameters<Page["route"]>[0],
  handler: Parameters<Page["route"]>[1],
) {
  return page.route(url, (route, request) =>
    (typeof methods === "string" ? [methods] : methods).includes(request.method())
      ? handler(route, request)
      : route.fallback());
}

export const mockGet = (
  page: Page, url: Parameters<Page["route"]>[0], handler: Parameters<Page["route"]>[1],
) => mockApi(page, "GET", url, handler);

/**
 * Reads of one API path as the page saw them, for a spec that says "read once".
 *
 * Count the reads the page was ANSWERED, never the hits on a route handler.
 * The dev server runs React StrictMode, which mounts every effect twice;
 * `useAsyncResource` aborts the first request on the simulated unmount, but by
 * then it has reached the route, so a handler counts two reads where the build
 * makes one (`net::ERR_ABORTED`, then the re-issue from
 * `invokePassiveEffectMountInDEV`). `answered` is the same number in both
 * serving modes. `started` counts every request, abandoned or not: use it for
 * "not read yet", where zero is zero in both modes and an in-flight read must
 * not hide behind its unfinished response.
 */
export function watchReads(page: Page, method: string, path: string) {
  const counts = { started: 0, answered: 0 };
  const mine = (request: Request) =>
    request.method() === method && new URL(request.url()).pathname === path;
  page.on("request", (request) => { if (mine(request)) counts.started += 1; });
  page.on("requestfinished", (request) => { if (mine(request)) counts.answered += 1; });
  return counts;
}
