import { existsSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const src = join(dirname(fileURLToPath(import.meta.url)), "..", "..");
const read = (path: string) => readFileSync(join(src, path), "utf8");

describe("Opportunities ownership", () => {
  it("the route only translates its company lens and renders the feature", () => {
    const route = read("routes/BoardRoute.tsx");
    expect(route).toContain('from "../features/opportunities/BoardScreen"');
    expect(route).toContain('useSearchParamList("company")');
    expect(route).toContain("<BoardScreen");
    expect(route).not.toMatch(/api\.|useState|useEffect|<main|<Job/);
    expect(read("features/opportunities/BoardScreen.tsx")).not.toMatch(/api\.|\.then\(/);
  });

  it("Board and Saved import the same row/list owners, with no legacy implementations", () => {
    for (const consumer of ["features/opportunities/BoardScreen.tsx", "features/saved/SavedScreen.tsx"]) {
      expect(read(consumer)).toContain('patterns/jobs/JobCard"');
      expect(read(consumer)).toContain('patterns/jobs/JobList"');
      expect(read(consumer)).toContain('patterns/jobs/job-page.css"');
    }
    for (const legacy of ["BoardFilters.tsx", "BoardToolbar.tsx", "JobCard.tsx", "JobList.tsx", "CompanyHoverCard.tsx", "SearchInterpretation.tsx", "board.css"]) {
      expect(existsSync(join(src, "components", legacy)), legacy).toBe(false);
    }
    // eslint owns the general layer rule; these pin that the shared row patterns import no screen.
    for (const pattern of ["jobs/JobCard.tsx", "jobs/JobList.tsx", "jobs/JobControls.tsx", "companies/CompanyChip.tsx"]) {
      expect(read(`patterns/${pattern}`)).not.toMatch(/from ["'][^"']*(?:components|features|routes)\//);
    }
  });

  it("shared CSS consumers declare their dependency without an eager Board route import", () => {
    expect(read("patterns/jobs/JobCard.tsx")).toContain('import "./job-row.css"');
    expect(read("patterns/jobs/JobList.tsx")).toContain('import "./job-row.css"');
    expect(read("patterns/companies/CompanyChip.tsx")).toContain('import "./company-chip.css"');
    expect(read("features/company-profiles/CompanyLogo.tsx")).toContain('patterns/companies/company-logo.css"');
    expect(read("features/company-profiles/StockPricePanel.tsx")).toContain('patterns/companies/company-chip.css"');
  });
});
