import { existsSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const src = join(dirname(fileURLToPath(import.meta.url)), "..", "..");
const read = (path: string) => readFileSync(join(src, path), "utf8");

/* Saved ownership. Saved and Compare are feature roots the shell mounts
 * directly; neither reads a URL param, so a `routes/` file would translate
 * nothing. */
describe("Saved ownership", () => {
  it("the screen renders and the controller owns the request", () => {
    const screen = read("features/saved/SavedScreen.tsx");
    expect(screen).toContain('from "./useSavedController"');
    expect(screen).not.toMatch(/api\.|\.then\(|useState|useEffect/);
    const controller = read("features/saved/useSavedController.ts");
    // Tolerant of formatting: a wrapped `api\n  .setFavorite(` is the same
    // ownership claim as a single line, and the gate is about who calls the
    // API, not about where prettier put the newline.
    expect(controller).toMatch(/api\s*\.\s*jobs\(/);
    expect(controller).toMatch(/api\s*\.\s*setFavorite\(/);
  });

  it("consumes the shared job patterns rather than its own row", () => {
    const screen = read("features/saved/SavedScreen.tsx");
    expect(screen).toContain('patterns/jobs/JobCard"');
    expect(screen).toContain('patterns/jobs/JobList"');
    // The page geometry it renders is declared, not inherited from whichever
    // route happened to load first.
    expect(screen).toContain('patterns/jobs/job-page.css"');
  });

  /* Saved renders `.board-main` and imports only job-page.css, so every rule
     that class gives it must live there. A rule in the Board's own sheet would
     reach Saved only because tabs.tsx loads the Board eagerly. */
  it("every .board-main rule Saved relies on lives in the sheet Saved imports", () => {
    const shared = read("patterns/jobs/job-page.css");
    const board = read("features/opportunities/board-shell.css");
    // The whole page takes the hero's measure, not the hero alone,
    // so Saved's count and list share its edges.
    expect(shared).toMatch(/\.board-main > \* \{[^}]*max-width:\s*1460px/);
    // The Board's remaining arms all require a Board-only child, so none of
    // them can silently apply to Saved.
    for (const [, selector] of board.matchAll(/([^{}]*\.board-main[^{}]*)\{/g)) {
      const arms = selector.split(",").filter((one) => one.includes(".board-main"));
      for (const arm of arms) {
        expect(arm, `${arm.trim()} in board-shell.css also matches Saved`).toMatch(
          /\.board-(toolbar|shell)|\.search-interp/,
        );
      }
    }
  });

  it("the shell mounts the feature root; no legacy route survives", () => {
    expect(existsSync(join(src, "routes", "FavoritesRoute.tsx"))).toBe(false);
    expect(read("routeRegistry.tsx")).toContain("./features/saved/SavedScreen");
  });
});
