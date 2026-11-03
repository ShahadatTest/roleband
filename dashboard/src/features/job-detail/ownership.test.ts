import { existsSync, readFileSync } from "node:fs";
import { dirname, join, relative, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const src = join(dirname(fileURLToPath(import.meta.url)), "..", "..");
const read = (path: string) => readFileSync(join(src, path), "utf8");

/** The panels the screen composes. Each lives with it; none is shared. */
const PANELS = [
  "JobCompPanel.tsx",
  "JobDescription.tsx",
  "JobRequirementsPanel.tsx",
  "LineageStack.tsx",
  "LineageDiff.tsx",
  "TwinDeck.tsx",
];

describe("Job detail ownership", () => {
  /* The route keeps real work -- URL canonicalization and the back decision --
     so this is not the thin-route claim Board makes. What it must not own is
     the DATA: a fetch here would put the screen's loading and error states
     outside the feature that renders them. */
  it("the route renders the feature and fetches nothing itself", () => {
    const route = read("routes/JobRoute.tsx");
    expect(route).toContain('from "../features/job-detail/JobDetail"');
    expect(route).toContain("<JobDetail");
    expect(route).not.toMatch(/\bapi\.\w|useAsyncResource/);
  });

  it("the screen and its panels left the legacy tier behind", () => {
    for (const file of ["JobDetail.tsx", "job-detail.css", ...PANELS]) {
      expect(existsSync(join(src, "components", file)), `components/${file}`).toBe(false);
      expect(existsSync(join(src, "features/job-detail", file)), file).toBe(true);
    }
  });

  /* The layer rule is owned in the abstract by the lint zones; this pins the
     direction that would silently reappear -- a panel reaching back into
     components/, or sideways into a sibling feature.
     Resolved rather than pattern-matched, because from INSIDE the feature a
     sibling is spelled `../saved/`, not `features/saved/`: matching only the
     second spelling would pass a real sibling import. */
  it("nothing in the feature imports the legacy tier or a sibling feature", () => {
    const here = join(src, "features/job-detail");
    for (const file of ["JobDetail.tsx", ...PANELS]) {
      const source = read(`features/job-detail/${file}`);
      for (const [, spec] of source.matchAll(/(?:from|import)\s+["'](\.[^"']*)["']/g)) {
        const target = relative(src, resolve(here, spec)).split(sep).join("/");
        expect(target.startsWith("components/"), `${file} -> ${spec}`).toBe(false);
        expect(
          /^features\//.test(target) && !target.startsWith("features/job-detail/"),
          `${file} -> ${spec}`,
        ).toBe(false);
      }
    }
  });

  it("the screen declares the shared row sheet it borrows from patterns/", () => {
    expect(read("features/job-detail/JobDetail.tsx")).toContain('patterns/jobs/job-row.css"');
  });
});
