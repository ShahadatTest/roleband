import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach, vi } from "vitest";
import { resetMemorySweep } from "../hooks/filterMemory";
import { resetRoleSaves } from "../hooks/useRoleSaves";
import { resetWriteQueues } from "../hooks/useWriteQueue";
import { forgetKeptAnswers } from "../api/keptAnswers";
import { forgetProfileDraft } from "../features/scope/profileDraftStash";
import { setCompanyNames } from "../format";

// jsdom has no matchMedia; motion/react consults it for reduced-motion.
if (typeof window !== "undefined" && !window.matchMedia) {
  window.matchMedia = (query: string) =>
    ({
      matches: false,
      media: query,
      onchange: null,
      addListener: () => {},
      removeListener: () => {},
      addEventListener: () => {},
      removeEventListener: () => {},
      dispatchEvent: () => false,
    }) as MediaQueryList;
}

// Node >= 22 ships an experimental `localStorage` global that shadows jsdom's
// Storage with a stub (no clear(), silent no-op writes without
// --localstorage-file). Components persist UI state through
// window.localStorage and setup's answers through window.sessionStorage, so
// give tests a real in-memory Storage for each.
function memoryStorage(): Storage {
  const store = new Map<string, string>();
  return {
    getItem: (key) => store.get(key) ?? null,
    setItem: (key, value) => void store.set(key, String(value)),
    removeItem: (key) => void store.delete(key),
    clear: () => store.clear(),
    key: (index) => [...store.keys()][index] ?? null,
    get length() {
      return store.size;
    },
  };
}
if (typeof window !== "undefined") {
  Object.defineProperty(window, "localStorage", { value: memoryStorage(), configurable: true });
  Object.defineProperty(window, "sessionStorage", { value: memoryStorage(), configurable: true });
}

// cleanup() unmounts, and an unmounting Profile draft stashes itself for the
// next visit (useScopeDraft); forgotten after, in the same hook, so no test
// starts with another's draft.
afterEach(() => {
  cleanup();
  forgetProfileDraft();
  // The tracked-name table is module state, set before render.
  setCompanyNames({});
});

/* Storage is shared by every test in a file, and with filter memory
 * (hooks/filterMemory) a screen WRITES to it as soon as a filter moves — so a
 * spec that narrowed a register hands the next one a pre-filtered screen. That
 * failure reads as a bug in the component under test, which is the worst kind
 * to chase. Clear it between tests; a spec that wants a remembered state seeds
 * it itself. */
afterEach(() => {
  try {
    window.localStorage.clear();
    window.sessionStorage.clear();
  } catch {
    /* A jsdom without storage is not a test failure. */
  }
  // The stale-version sweep runs once per page life, which inside one spec
  // file means once per FILE — so a test that seeds an old-version key would
  // find it never swept.
  resetMemorySweep();
});

// The write queue's promise tails are module state on purpose — they outlive a
// component because the subject they order does. Inside one test file that
// means they outlive the TEST, so a spec that leaves a write pending would hand
// the next one a tail that never settles.
afterEach(() => {
  resetWriteQueues();
  resetRoleSaves();
  // Kept answers are module state too; a test that mocks the client never
  // writes through the transport, so nothing else forgets them.
  forgetKeptAnswers();
});

/* The app shell calls the typed client through `api/shell` (`shellApi`), the
 * startup endpoints only, so a screen's methods stay out of the startup chunk.
 * Tests double the client by mocking `../api` and its one `api` object; this stands
 * that object, mocked or real, in for `shellApi`, read at call time, so a
 * test's `vi.mocked(api.status)` is what the shell's poll calls. Without it a
 * provider rendered under `vi.mock("../api")` would reach the real transport
 * and swallow the failure, and the test would stop meaning anything. */
vi.mock("../api/shell", async () => {
  const client = await import("../api");
  return {
    shellApi: new Proxy({}, { get: (_target, key) => (client.api as Record<PropertyKey, unknown>)[key] }),
  };
});
