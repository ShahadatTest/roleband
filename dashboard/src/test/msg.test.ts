import { describe, expect, it } from "vitest";
import { msg } from "./msg";

describe("msg()", () => {
  it("says what the screen says, parameters included", () => {
    expect(msg("shell-nav-radar")).toBe("Radar");
    expect(msg("spike-role-count", { count: 1 })).toBe("1 role");
    expect(msg("spike-role-count", { count: 3 })).not.toBe(msg("spike-role-count", { count: 4 }));
  });
});
