import { afterEach, describe, expect, it, vi } from "vitest";
import { DEFAULT_THEME, readTheme, writeTheme } from "./theme";

/* The shell reads the theme in its first render, so storage that throws must
   never reach it: a browser that blocks site data would get a blank page. */

const blocked = () => {
  const denied = () => { throw new DOMException("The operation is insecure.", "SecurityError"); };
  vi.spyOn(Storage.prototype, "getItem").mockImplementation(denied);
  vi.spyOn(Storage.prototype, "setItem").mockImplementation(denied);
};

afterEach(() => {
  vi.restoreAllMocks();
  localStorage.clear();
});

describe("the saved theme", () => {
  it("comes back as it was saved", () => {
    writeTheme("light");
    expect(readTheme()).toBe("light");
    writeTheme("dark");
    expect(readTheme()).toBe("dark");
  });

  it("is the default when nothing, or something unknown, was saved", () => {
    expect(readTheme()).toBe(DEFAULT_THEME);
    localStorage.setItem("theme", "sepia");
    expect(readTheme()).toBe(DEFAULT_THEME);
  });

  it("is the default, and a save is dropped, when storage refuses access", () => {
    blocked();
    expect(readTheme()).toBe(DEFAULT_THEME);
    expect(() => writeTheme("light")).not.toThrow();
  });
});
