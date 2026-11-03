import { describe, expect, it } from "vitest";
import { NAV_TABS } from "./navigation";
import { PositionRoute, ROUTE_COMPONENTS, WelcomeRoute } from "./routeRegistry";

/* Does every route chunk actually LOAD?
 *
 * `route-registry.test.ts` reads `routeRegistry.tsx` as text and compares
 * `Object.keys(ROUTE_COMPONENTS)` against `NAV_TABS`. That catches a missing
 * entry and a chunk nothing can reach, and it cannot catch any of these:
 *
 *   - a loader whose `.then(m => ({ default: m.X }))` names an export that was
 *     renamed, so the chunk resolves to `{ default: undefined }`;
 *   - a module that throws while EVALUATING (a bad import, a top-level call);
 *   - a path that does not exist.
 *
 * All three render a blank screen with every gate green, and a route no
 * Playwright spec visits has nothing else that executes its loader. Awaiting a
 * `React.lazy`'s payload is the cheapest way to run every one of them.
 */

/* React keeps the loader on the lazy object's payload and offers no public API
   for it. While the payload is Uninitialized (`_status === -1`) `_result` IS the
   ctor; after React has initialised it, `_result` becomes the promise. Reading
   it here never initialises anything, so it stays the ctor. */
const UNINITIALIZED = -1;
type LazyPayload = {
  _payload: { _status: number; _result: () => Promise<{ default: unknown }> };
};

const payloadOf = (component: unknown) => (component as unknown as LazyPayload)._payload;
/* A screen fetched ahead of its route (`preloadable` in the registry) is a
   plain component that carries its own loader. */
type Preloadable = { load: () => Promise<{ default: unknown }> };
const isPreloadable = (component: unknown): component is Preloadable =>
  typeof (component as Partial<Preloadable>).load === "function";
const load = (component: unknown) => (isPreloadable(component) ? component.load : payloadOf(component)._result);

const ENTRIES: [string, unknown][] = [
  ...Object.entries(ROUTE_COMPONENTS),
  ["welcome", WelcomeRoute],
  ["position", PositionRoute],
];

describe("route loaders", () => {
  it("covers every tab plus the two routes outside the table", () => {
    // Guards the guard: if the shape below stops matching React's internals the
    // loop would silently test nothing, so the COUNT is asserted first.
    expect(ENTRIES).toHaveLength(NAV_TABS.length + 2);
    for (const [name, component] of ENTRIES) {
      // If React's internals ever change shape, this fails loudly here rather
      // than letting every case below pass without loading anything.
      if (!isPreloadable(component)) {
        expect(payloadOf(component)._status, `${name} is not an uninitialised lazy`).toBe(
          UNINITIALIZED,
        );
      }
      expect(typeof load(component), `${name} exposes no loader`).toBe("function");
    }
  });

  for (const [name, component] of ENTRIES) {
    it(`${name} resolves to a component`, async () => {
      const module = await load(component)();
      expect(module, `${name} loaded nothing`).toBeTruthy();
      expect(
        typeof module.default,
        `${name} resolved to { default: ${typeof module.default} } — the loader's ` +
          `.then() probably names an export that no longer exists`,
      ).toBe("function");
    });
  }
});
