import { existsSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const src = join(dirname(fileURLToPath(import.meta.url)), "..", "..");
const read = (path: string) => readFileSync(join(src, path), "utf8");

describe("Compare ownership", () => {
  it("the screen renders, the controller requests, the model compares", () => {
    const screen = read("features/compare/CompareScreen.tsx");
    expect(screen).toContain('from "./useCompareController"');
    expect(screen).toContain('from "./attributes"');
    // No remote work in the screen: requests, promises and toasts belong to
    // the controller. `useState` is NOT on that list: whether a run of
    // agreeing rows is open and whether the descriptions show differences only
    // are view state with no store behind them, and pushing them into the
    // controller would make it hold facts no request depends on.
    expect(screen).not.toMatch(/api\.|\.then\(|useAsyncResource|toast\(/);
    const controller = read("features/compare/useCompareController.ts");
    expect(controller).toContain("api.job(");
    expect(controller).toContain("useAsyncResource");
    // The comparison model is data, not markup with logic hidden in it.
    expect(read("features/compare/attributes.tsx")).not.toMatch(/api\.|use[A-Z]/);
  });

  it("owns its sheet and states its grid in it, not in style attributes", () => {
    const screen = read("features/compare/CompareScreen.tsx");
    expect(screen).toContain('import "./compare.css"');
    expect(existsSync(join(src, "routes", "compare.css"))).toBe(false);
    // The only inline style left is the one that cannot be static: how many
    // roles are being compared. The tracks themselves are the sheet's, which
    // is what lets the phone form redraw them.
    const inline = [...screen.matchAll(/style=\{\{/g)];
    expect(inline).toHaveLength(1);
    expect(screen).toMatch(/style=\{\{ "--cmp-columns": jobs\.length \}/);
    expect(screen).not.toMatch(/gridTemplateColumns/);
    expect(read("features/compare/compare.css")).toMatch(/grid-template-columns:[^;]*repeat\(var\(--cmp-columns\)/);
  });

  it("reads descriptions through the shared passage model, not through Review", () => {
    /* Rendering Review's DescriptionComparison would be a feature importing
       a feature. The passage model (what makes two passages the same) lives
       in patterns/jobs and both screens read it; Compare's columns are its
       own, so there is no cross-feature edge. */
    expect(read("features/compare/descriptions.ts")).toContain('from "../../patterns/jobs/descriptionPassages"');
    expect(read("features/review/DescriptionComparison.tsx")).toContain('from "../../patterns/jobs/descriptionPassages"');
    expect(read("features/compare/CompareScreen.tsx")).not.toContain("../review/");
    expect(read("features/compare/descriptions.ts")).not.toContain("../review/");
  });

  it("the shell mounts the feature root through its cover route", () => {
    /* Compare is a cover, not a tab: the registry names a route
       module (the same shape as the position overlay), and THAT module is the
       only importer of the feature root, so the screen decides nothing about
       history or which slot it renders in. */
    expect(read("routeRegistry.tsx")).toContain("./routes/CompareRoute");
    expect(read("routeRegistry.tsx")).not.toContain("./features/compare/CompareScreen");
    expect(read("routes/CompareRoute.tsx")).toContain('from "../features/compare/CompareScreen"');
  });
});
