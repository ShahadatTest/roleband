import { readFileSync, readdirSync, statSync } from "node:fs";
import { dirname, join, relative } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { NAV_TABS } from "./navigation";
import { ROUTE_COMPONENTS } from "./routeRegistry";

const SRC = dirname(fileURLToPath(import.meta.url));
const read = (rel: string) => readFileSync(join(SRC, rel), "utf8");

/* Navigation metadata and route components are two files. As one file, a
 * visit to any route would evaluate the whole product: the rail, the
 * breadcrumb and the palette need labels, importing labels would import
 * elements, and importing elements every feature and its CSS.
 *
 * Splitting them creates a new failure the compiler cannot see — a tab whose
 * loader is missing renders a blank page, and a loader no tab reaches is a
 * chunk built for nobody. This file is the join. */
describe("route registry", () => {
  it("every tab has a loader and every loader has a tab", () => {
    expect(Object.keys(ROUTE_COMPONENTS).sort()).toEqual(NAV_TABS.map((t) => t.path).sort());
  });

  it("navigation metadata reaches no screen, directly or otherwise", () => {
    const source = read("navigation.ts");
    // The whole point of the split. `navTabs` (slug/label constants) and the
    // Icon TYPE are leaves; anything else is a screen arriving through the back
    // door, and the shell budget would follow it.
    const imports = [...source.matchAll(/from\s+"([^"]+)"/g)].map((m) => m[1]);
    expect(imports.sort()).toEqual(["./copy/gen/shell", "./navTabs", "./ui/Icon"]);
    // Labels come from the copy catalog (docs/copy.md).
    // The generated module is a leaf too: it reaches the runtime and nothing else.
    const labels = read("copy/gen/shell.ts");
    expect([...labels.matchAll(/from\s+"([^"]+)"/g)].map((m) => m[1])).toEqual(["../runtime"]);
    expect(read("copy/runtime.ts")).not.toMatch(/\bfrom\s+"/);
    expect(source).not.toMatch(/\bimport\s*\(/);
    // No JSX: a .ts file cannot hold an element, and keeping the extension is
    // what makes that structural rather than a matter of discipline.
    expect(source).not.toMatch(/<[A-Z]/);
  });

  it("the chrome reads metadata only, so it costs nothing to render a label", () => {
    for (const consumer of ["shell/NavRail.tsx", "shell/CommandPalette.tsx", "App.tsx"]) {
      expect(read(consumer), consumer).toContain('from "./navigation"'.replace("./", consumer.includes("/") ? "../" : "./"));
    }
    for (const consumer of ["shell/NavRail.tsx", "shell/CommandPalette.tsx"]) {
      expect(read(consumer), consumer).not.toContain("routeRegistry");
    }
  });

  it("every screen enters through a lazy loader, never a static import", () => {
    const registry = read("routeRegistry.tsx");
    // `lazy(() => import(...))`, or `preloadable(() => import(...))` for a
    // screen fetched ahead, for each entry — a static import here would put
    // the screen straight back in the shell with nothing failing.
    const lazyCount = [...registry.matchAll(/(?:lazy|preloadable)\(\(\)\s*=>/g)].length;
    expect(lazyCount).toBe(Object.keys(ROUTE_COMPONENTS).length + 3); // + Welcome + the two covers (position, compare)
    expect(registry).not.toMatch(/^import\s+\{[^}]*\}\s+from\s+"\.\/(routes|features|components)\//m);
  });

  /* The shell must stay small, and a static import of a screen anywhere in it
     undoes that silently — the app still works, the chunk just moves back into
     the shell.

     "Screen" is derived from the registry's own dynamic imports rather than
     from a path shape, because a path shape gets this wrong: NotificationBell
     lives under features/notifications and is topbar CHROME, rendered on every
     route, so the shell is exactly where it belongs. */
  it("nothing in the shell statically imports a screen", () => {
    const screens = new Set(
      [...read("routeRegistry.tsx").matchAll(/import\("([^"]+)"\)/g)].map((m) => m[1]),
    );
    expect(screens.size).toBeGreaterThan(8); // the regex found the loaders, not nothing
    for (const file of ["App.tsx", "main.tsx", "navigation.ts"]) {
      const source = read(file);
      for (const [, spec] of source.matchAll(/^import\s[^;]*?from\s+"([^"]+)"/gm)) {
        expect(
          screens.has(spec),
          `${file} statically imports the screen ${spec}; it belongs in routeRegistry.tsx as a lazy entry`,
        ).toBe(false);
      }
    }
  });

  it("no module still imports the merged route table", () => {
    const files: string[] = [];
    const walk = (dir: string) => {
      for (const name of readdirSync(dir)) {
        const path = join(dir, name);
        if (statSync(path).isDirectory()) walk(path);
        else if (/\.tsx?$/.test(name)) files.push(path);
      }
    };
    walk(SRC);
    const stragglers = files.filter((f) => /from\s+"[./]*tabs"/.test(readFileSync(f, "utf8")));
    expect(stragglers.map((f) => relative(SRC, f))).toEqual([]);
  });
});
