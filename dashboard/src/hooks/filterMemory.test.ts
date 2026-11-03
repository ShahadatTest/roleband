import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  MEMORY_VERSION,
  amount,
  decodeParams,
  decodeShape,
  encodeShape,
  flag,
  forgetEntry,
  oneOf,
  readEntry,
  slugs,
  text,
  writeEntry,
  type MemoryShape,
} from "./filterMemory";

/* What comes back off disk is DATA, not state. These are the contracts that
 * make restoring a stored blob safe: a shape is a whitelist as well as a
 * validator, every decoder refuses what it cannot vouch for, and no storage
 * failure of any kind may reach the screen. */

const key = "spec";

beforeEach(() => localStorage.clear());
afterEach(() => vi.restoreAllMocks());

describe("the filter memory store", () => {
  it("round-trips a value under a versioned, namespaced key", () => {
    writeEntry(key, { company: ["openai"] });
    expect(readEntry(key)).toEqual({ company: ["openai"] });
    expect(localStorage.getItem(`roleband.filters.v${MEMORY_VERSION}:${key}`)).toBe(
      JSON.stringify({ company: ["openai"] }),
    );
    forgetEntry(key);
    expect(readEntry(key)).toBeNull();
  });

  it("reads an unparseable blob as nothing remembered, never as a throw", () => {
    // Hand-edited storage, a truncated write, a shape from another app. One
    // bad blob must not be a permanently broken screen.
    localStorage.setItem(`roleband.filters.v${MEMORY_VERSION}:${key}`, "{not json");
    expect(readEntry(key)).toBeNull();
  });

  it("survives storage whose methods throw — Safari's private window", () => {
    const boom = () => {
      throw new Error("QuotaExceededError");
    };
    vi.spyOn(window.localStorage, "getItem").mockImplementation(boom);
    vi.spyOn(window.localStorage, "setItem").mockImplementation(boom);
    vi.spyOn(window.localStorage, "removeItem").mockImplementation(boom);
    expect(() => writeEntry(key, { a: 1 })).not.toThrow();
    expect(readEntry(key)).toBeNull();
    expect(() => forgetEntry(key)).not.toThrow();
  });

  it("survives storage that throws on the PROPERTY — blocked site data", () => {
    // Reading `window.localStorage` itself raises a SecurityError when site
    // data is blocked, which is before any method could be called.
    const real = Object.getOwnPropertyDescriptor(window, "localStorage");
    Object.defineProperty(window, "localStorage", {
      configurable: true,
      get() {
        throw new Error("SecurityError");
      },
    });
    try {
      expect(() => writeEntry(key, { a: 1 })).not.toThrow();
      expect(readEntry(key)).toBeNull();
      expect(() => forgetEntry(key)).not.toThrow();
    } finally {
      Object.defineProperty(window, "localStorage", real!);
    }
  });

  it("sweeps entries written under an older version, and leaves everything else alone", () => {
    localStorage.setItem("roleband.filters.v0:board", '{"company":["stale"]}');
    localStorage.setItem("theme", "dark");
    // The sweep runs once per page life, on first use — which is this read.
    readEntry("board");
    expect(localStorage.getItem("roleband.filters.v0:board")).toBeNull();
    expect(localStorage.getItem("theme")).toBe("dark");
  });
});

describe("the decoders", () => {
  it("keeps only the strings out of a slug list, and bounds what it keeps", () => {
    expect(slugs(["openai", "amazon"])).toEqual(["openai", "amazon"]);
    // A mixed array is a partial loss, not a total one: the good slugs still
    // narrow the list the reader left it narrowed to.
    expect(slugs(["openai", 7, null, "", "amazon"])).toEqual(["openai", "amazon"]);
    expect(slugs("openai")).toBeUndefined();
    expect(slugs({ 0: "openai" })).toBeUndefined();
    expect(slugs(Array.from({ length: 500 }, (_, i) => `co_${i}`))).toHaveLength(200);
    expect(slugs(["x".repeat(500)])).toEqual([]);
  });

  it("refuses a number that cannot reach the wire, and keeps an explicit null", () => {
    expect(amount(200000)).toBe(200000);
    expect(amount(null)).toBeNull();
    // `Infinity` and `NaN` survive a hand edit and serialize to garbage.
    expect(amount(Number.POSITIVE_INFINITY)).toBeUndefined();
    expect(amount(Number.NaN)).toBeUndefined();
    expect(amount("200000")).toBeUndefined();
  });

  it("answers only for a value still in the vocabulary", () => {
    const viewed = oneOf(["", "unread", "read"] as const);
    expect(viewed("unread")).toBe("unread");
    expect(viewed("")).toBe("");
    // A value retired since the write. This is the only decoder that can tell.
    expect(viewed("not-for-me")).toBeUndefined();
  });

  it("takes a boolean as itself and nothing else as one", () => {
    expect(flag(true)).toBe(true);
    expect(flag(false)).toBe(false);
    expect(flag("true")).toBeUndefined();
    expect(flag(1)).toBeUndefined();
    expect(text("relevance")).toBe("relevance");
    expect(text(7)).toBeUndefined();
  });
});

interface Sample {
  company: string[];
  discloses_pay: boolean;
  comp_min: number | null;
  q: string;
}

const shape: MemoryShape<Sample> = { company: slugs, discloses_pay: flag, comp_min: amount };

describe("the shape", () => {
  it("is the whitelist as well as the validator", () => {
    // `q` has no decoder, so it is neither restorable nor storable — which is
    // how a screen keeps its search box out of memory without a second list.
    const stored = { company: ["openai"], discloses_pay: true, comp_min: 200000, q: "staff" };
    expect(decodeShape(shape, stored)).toEqual({
      company: ["openai"],
      discloses_pay: true,
      comp_min: 200000,
    });
    expect(
      encodeShape(shape, { company: ["openai"], discloses_pay: false, comp_min: null, q: "staff" }),
    ).toEqual({ company: ["openai"], discloses_pay: false, comp_min: null });
  });

  it("lets a caller's default show through wherever the blob is wrong", () => {
    // Every key present, every one of the wrong type: the result is empty, so
    // `{...defaults, ...restored}` is exactly `defaults`.
    expect(decodeShape(shape, { company: "openai", discloses_pay: "yes", comp_min: "x" })).toEqual({});
    expect(decodeShape(shape, null)).toEqual({});
    expect(decodeShape(shape, ["company"])).toEqual({});
    // A key the blob does not carry is absent rather than undefined, or the
    // spread above would overwrite the default with nothing.
    expect("company" in decodeShape(shape, { discloses_pay: true })).toBe(false);
  });
});

describe("a remembered query string", () => {
  it("keeps every value of the keys it was asked for, and nothing else", () => {
    const stored = { status: ["unread"], category: ["sync_failed", "closed"], q: ["staff"] };
    expect(decodeParams(stored, ["status", "priority", "category"])).toEqual({
      status: ["unread"],
      category: ["sync_failed", "closed"],
    });
    // An empty list is not a remembered lens: it would write `?category=` and
    // mean something the screen never chose.
    expect(decodeParams({ status: [] }, ["status"])).toEqual({});
    expect(decodeParams("status=unread", ["status"])).toEqual({});
  });
});
