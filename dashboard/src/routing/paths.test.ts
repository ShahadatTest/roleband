import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { positionKey, positionPath } from "./paths";

/** Every source file under `dir`, tests and generated code aside. */
function sources(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) return name === "gen" ? [] : sources(path);
    return /\.(ts|tsx)$/.test(name) && !/\.test\./.test(name) ? [path] : [];
  });
}

describe("a role's address", () => {
  it("is under its company", () => {
    expect(positionPath("open ai", 7)).toBe("/company/open%20ai/job/7");
  });

  it("is never the short /job/:id where the company is known", () => {
    // The short route only resolves to the company path once the job loads,
    // and then rewrites the address the reader sees. Only a fallback beside
    // positionPath, for a role whose company is not known, may still write it.
    const offenders = sources(join(__dirname, ".."))
      .flatMap((path) => readFileSync(path, "utf8").split("\n").map((line) => [path, line] as const))
      .filter(([, line]) => line.includes("`/job/${") && !line.includes("positionPath("))
      .map(([path, line]) => `${path}: ${line.trim()}`);
    expect(offenders).toEqual([]);
  });
});

describe("a role's boundary key", () => {
  it("is the same for every URL that names the role", () => {
    const key = positionKey("/company/openai/job/202");
    expect(key).not.toBeNull();
    expect(positionKey("/job/202")).toBe(key);
    expect(positionKey("/company/not-openai/job/202")).toBe(key);
    expect(positionKey("/company/openai/job/202/")).toBe(key);
  });

  it("tells roles apart, and names nothing else", () => {
    expect(positionKey("/company/openai/job/101")).not.toBe(positionKey("/company/openai/job/202"));
    for (const path of ["/", "/company", "/company/openai", "/company/openai/job", "/job", "/compare", "/settings/job/202", "/company/openai/job/202/extra"]) {
      expect(positionKey(path), path).toBeNull();
    }
  });
});
