import { afterEach, expect, it, vi } from "vitest";
import type { ScopeSelection } from "./scopeDraftModel";
import type { AnswerRoles } from "./walk/walkModel";
import { forgetSetupStash, keepSetupStash, readSetupStash } from "./setupStash";

/* What comes back from the tab is untrusted: it outlives the code that wrote
   it, and the walk opens on it. A part of another shape must read as nothing
   kept, never as a half-filled draft. */

const KEY = "roleband.setup.v1";

const DRAFT: ScopeSelection = {
  roles: new Set(["engineering_management"]),
  bands: new Set(["staff"]),
  tracks: new Set(["management"]),
  locations: new Set(["city_london", "united_states"]),
  domains: new Set(["ai_ml", "health_bio"]),
  excluded: new Set(["gambling"]),
  excepted: new Set(["city_new_york"]),
  answers: new Map<string, AnswerRoles>([["management", "any"], ["ic", new Set(["software_engineering"])]]),
  includeUnstatedLevel: true,
  experienceStage: "staff",
  targetStage: null,
};

afterEach(() => vi.restoreAllMocks());

it("keeps a draft, the floor and the companies choice for the tab, and gives them back whole", () => {
  keepSetupStash({ draft: DRAFT });
  keepSetupStash({ floor: { amount: 180000, currency: "GBP" } });
  keepSetupStash({ companies: "listed" });
  expect(readSetupStash()).toEqual({ draft: DRAFT, floor: { amount: 180000, currency: "GBP" }, companies: "listed" });

  // A floor removed is kept as no floor, which Start writes as a clear.
  keepSetupStash({ floor: null });
  expect(readSetupStash().floor).toBeNull();

  forgetSetupStash();
  expect(readSetupStash()).toEqual({});
  expect(window.sessionStorage.getItem(KEY)).toBeNull();
});

it("reads a stored part of another shape as nothing kept, and keeps the parts that do fit", () => {
  window.sessionStorage.setItem(KEY, JSON.stringify({
    draft: { roles: ["a"], tracks: "management" },
    floor: { amount: "lots", currency: "USD" },
    companies: "listed",
  }));
  expect(readSetupStash()).toEqual({ companies: "listed" });

  window.sessionStorage.setItem(KEY, JSON.stringify({ draft: { answers: [["ic", 3]] } }));
  expect(readSetupStash()).toEqual({});

  window.sessionStorage.setItem(KEY, "{not json");
  expect(readSetupStash()).toEqual({});
  window.sessionStorage.setItem(KEY, "[1,2]");
  expect(readSetupStash()).toEqual({});
});

it("a draft with an answer of another shape is not kept", () => {
  keepSetupStash({ draft: DRAFT });
  const stored = JSON.parse(window.sessionStorage.getItem(KEY) ?? "{}");
  stored.draft.answers = [["ic", [1, 2]]];
  window.sessionStorage.setItem(KEY, JSON.stringify(stored));
  expect(readSetupStash().draft).toBeUndefined();
});

it("storage that fails reads as nothing kept and drops a write without throwing", () => {
  vi.spyOn(window.sessionStorage, "getItem").mockImplementation(() => { throw new Error("blocked"); });
  vi.spyOn(window.sessionStorage, "setItem").mockImplementation(() => { throw new Error("quota"); });
  expect(readSetupStash()).toEqual({});
  expect(() => keepSetupStash({ draft: DRAFT })).not.toThrow();
  expect(() => forgetSetupStash()).not.toThrow();
});
