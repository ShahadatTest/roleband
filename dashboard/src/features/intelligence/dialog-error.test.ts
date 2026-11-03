import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { ApiError } from "../../api/transport";
import { errorText } from "../../api/errorText";
import { failed } from "./dialog-error";

/* A failed request is said in the reader's words for its code, never as the
 * API's English developer text. */

describe("a failed dialog action", () => {
  it("carries the localised message for a coded API error, not its English text", () => {
    const error = new ApiError("model endpoint did not answer: ECONNREFUSED", 502, "model-unreachable");
    const shown = failed("Couldn't test the connection", error);
    expect(shown.detail).toBe(errorText(error));
    expect(shown.detail).not.toContain("ECONNREFUSED");
  });

  it("says the generic line for a crash, never its stack text", () => {
    expect(failed("Couldn't save", new TypeError("x is undefined")).detail).toBe(errorText(new TypeError("x")));
  });
});

/** Every source file under `dir`, tests aside. */
function sources(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) return name === "gen" ? [] : sources(path);
    return /\.(ts|tsx)$/.test(name) && !/\.test\./.test(name) ? [path] : [];
  });
}

describe("screens report failures through errorText", () => {
  it("no screen shows a caught error's own message", () => {
    const root = join(__dirname, "../..");
    const offenders = sources(root)
      // Crash reporting reads the message on purpose (`diagnostics/clientErrors.ts`).
      .filter((path) => !path.includes("diagnostics"))
      .filter((path) => /\(\w+ as Error\)\.message/.test(readFileSync(path, "utf8")));
    expect(offenders).toEqual([]);
  });
});
