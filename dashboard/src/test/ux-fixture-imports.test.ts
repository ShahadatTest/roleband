import { ESLint } from "eslint";
import { expect, it } from "vitest";

it("browser specs cannot import a test runner that bypasses the API guard", async () => {
  const lint = new ESLint();
  // lintText evaluates only the supplied source, using an existing spec's config.
  const options = { filePath: "tests/ux/a11y.spec.ts" };
  const [bypass] = await lint.lintText('import { test as unguarded } from "@playwright/test";', options);
  expect(bypass.messages.some((message) => message.ruleId === "no-restricted-imports")).toBe(true);
  const [guarded] = await lint.lintText('import { test } from "./fixtures";\nimport type { Page } from "@playwright/test";', options);
  expect(guarded.messages).toEqual([]);
});
