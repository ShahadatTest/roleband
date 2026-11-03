import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import { flag, readEntry, slugs, writeEntry, type MemoryShape } from "./filterMemory";
import { useDisclosureMemory, useRememberedState } from "./useFilterMemory";

interface Lenses {
  company: string[];
  unreadOnly: boolean;
  page: number;
}

const defaults: Lenses = { company: [], unreadOnly: false, page: 0 };
/** `page` has no decoder: paging belongs to the list it was counted on. */
const shape: MemoryShape<Lenses> = { company: slugs, unreadOnly: flag };

const remembered = (override?: Partial<Lenses>) =>
  renderHook(() => useRememberedState<Lenses>({ scope: "spec", defaults, shape, override }));

beforeEach(() => localStorage.clear());

describe("remembered filter state", () => {
  it("starts from the defaults when nothing has been chosen yet", () => {
    const { result } = remembered();
    expect(result.current[0]).toEqual(defaults);
    // And writes nothing: an untouched screen must not leave a trace that a
    // later version would then have to interpret.
    expect(readEntry("spec")).toBeNull();
  });

  it("stores a choice and hands it back to the next mount", () => {
    const first = remembered();
    act(() => first.result.current[1]((prev) => ({ ...prev, company: ["openai"], unreadOnly: true })));
    first.unmount();

    const { result } = remembered();
    expect(result.current[0]).toMatchObject({ company: ["openai"], unreadOnly: true });
    expect(result.current[2].restored).toEqual({ company: ["openai"], unreadOnly: true });
  });

  it("keeps out of memory everything the shape does not name — and off the disk", () => {
    const { result } = remembered();
    // Turning the page is not a filter edit, so it does not even reach
    // storage: the shaped payload is unchanged, so there is nothing to write.
    act(() => result.current[1]((prev) => ({ ...prev, page: 40 })));
    expect(readEntry("spec")).toBeNull();

    // A real edit writes the shaped keys, and only those.
    act(() => result.current[1]((prev) => ({ ...prev, unreadOnly: true })));
    expect(readEntry("spec")).toEqual({ company: [], unreadOnly: true });
    expect(result.current[0].page).toBe(40);
  });

  it("lets a caller's override outrank memory, without overwriting it unasked", () => {
    writeEntry("spec", { company: ["openai"] });
    // The Board's case: an address that names a company is a link the reader
    // followed just now; memory is what they chose last night.
    const { result } = remembered({ company: ["amazon"] });
    expect(result.current[0].company).toEqual(["amazon"]);
    // `restored` still reports what memory actually held, which is what lets
    // the Board tell "the address said nothing" from "the address said this".
    expect(result.current[2].restored.company).toEqual(["openai"]);
    // Following a link is not choosing: nothing is written until the reader
    // edits something here.
    expect(readEntry("spec")).toEqual({ company: ["openai"] });
    act(() => result.current[1]((prev) => ({ ...prev, unreadOnly: true })));
    // ...and then the whole surface goes down, override included, because by
    // now it is what they are looking at.
    expect(readEntry("spec")).toEqual({ company: ["amazon"], unreadOnly: true });
  });

  it("restores nothing out of a blob whose values are the wrong type", () => {
    writeEntry("spec", { company: "openai", unreadOnly: "yes" });
    const { result } = remembered();
    expect(result.current[0]).toEqual(defaults);
  });

  it("forgets on demand without touching the live value", () => {
    const { result } = remembered();
    act(() => result.current[1]((prev) => ({ ...prev, unreadOnly: true })));
    expect(readEntry("spec")).toMatchObject({ unreadOnly: true });
    act(() => result.current[2].forget());
    expect(readEntry("spec")).toBeNull();
    expect(result.current[0].unreadOnly).toBe(true);
  });
});

describe("remembered disclosures", () => {
  it("answers a group's own default until the reader touches it", () => {
    const { result } = renderHook(() => useDisclosureMemory("spec"));
    expect(result.current.isOpen("Company", false)).toBe(false);
    // Tri-state, and this is the half that matters: an untouched group takes
    // whatever default the register hands it, so changing a default later
    // does not overrule readers who already made that group's choice.
    expect(result.current.isOpen("Company", true)).toBe(true);
  });

  it("keeps an explicit close, which is not the same as untouched", () => {
    const first = renderHook(() => useDisclosureMemory("spec"));
    act(() => first.result.current.setOpen("Company", false));
    first.unmount();

    const { result } = renderHook(() => useDisclosureMemory("spec"));
    expect(result.current.isOpen("Company", true)).toBe(false);
    expect(result.current.isOpen("Location", true)).toBe(true);
  });

  it("survives the mount that opened it, per group and per scope", () => {
    const first = renderHook(() => useDisclosureMemory("spec"));
    act(() => first.result.current.setOpen("Company", true));
    first.unmount();

    const { result } = renderHook(() => useDisclosureMemory("spec"));
    expect(result.current.isOpen("Company", false)).toBe(true);
    expect(result.current.isOpen("Location", false)).toBe(false);
    // A different screen's register is a different scope, not a shared map.
    const other = renderHook(() => useDisclosureMemory("elsewhere"));
    expect(other.result.current.isOpen("Company", false)).toBe(false);
  });

  it("stores disclosures beside the chosen values, never inside them", () => {
    // Two keys, on purpose: "Reset all" clears the filters and must not fold
    // the reader's rail back up on the way past.
    const { result } = renderHook(() => useDisclosureMemory("spec"));
    act(() => result.current.setOpen("Company", true));
    expect(readEntry("spec:open")).toEqual({ Company: true });
    expect(readEntry("spec")).toBeNull();
  });
});
