import { readdirSync, readFileSync, statSync } from "node:fs";
import { dirname, join, relative, sep } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

/* Screen contracts for the Review feature. Same shape as
 * intelligence-scope.test.ts: the stylesheet reaches into no other screen's
 * token scope, sizes all type from the ramp, and the route actually mounts the
 * marker the shared layer keys on. The list of permitted foreign tokens is
 * empty: even the fixed console's rail clearance reads --app-nav-width from
 * the promoted system.
 */

const here = dirname(fileURLToPath(import.meta.url));
const css = readFileSync(join(here, "review.css"), "utf8");
const strip = (source: string) => source.replace(/\/\*[\s\S]*?\*\//g, "");

describe("review screen contracts", () => {
  it("consumes only the app system or its own plumbing", () => {
    const source = strip(css);
    expect(source).not.toMatch(/--settings-|--ledger-|--profile-/);
    const declared = new Set(
      [...source.matchAll(/^\s*(--[\w-]+)\s*:/gm)].map((m) => m[1]),
    );
    const consumed = [...source.matchAll(/var\((--[\w-]+)/g)].map((m) => m[1]);
    expect(consumed.length).toBeGreaterThan(0);
    const foreign = consumed.filter(
      (token) => !token.startsWith("--app-") && !declared.has(token),
    );
    expect(foreign).toEqual([]);
    expect([...declared].filter((token) => token.startsWith("--app-"))).toEqual([]);
  });

  it("clears the nav rail through the shell's own width token, not a literal", () => {
    // The console is position:fixed, so its left offset is arithmetic rather
    // than layout, and the rail has TWO widths that .app.nav-expanded swaps
    // between at runtime. Reading --app-nav-width through the cascade is what
    // makes the console slide with the rail; a pixel literal (or a private
    // copy of the number) would strand it under the expanded rail while every
    // other test stays green: the console is still on screen, just wrong.
    const rule = strip(css).match(/\.review-decision-console\s*\{([^}]*)\}/);
    expect(rule, ".review-decision-console rule not found").toBeTruthy();
    expect(rule![1]).toContain("position: fixed");
    expect(rule![1]).toMatch(/left:\s*calc\(var\(--app-nav-width\)/);
  });

  it("reads the same width token the shell grid lays the rail out with", () => {
    // Two readers in two sheets, one name. If the shell's column stops
    // consuming --app-nav-width (a literal, a rename, a second private token),
    // the console's arithmetic silently describes a rail that is not there,
    // and nothing else in the app would notice. The second assertion is
    // the live half: the expanded state must override the TOKEN, because that
    // is what carries 204 down the cascade to a position:fixed element that
    // the grid does not lay out.
    const shell = readFileSync(join(here, "..", "..", "shell.css"), "utf8");
    const app = strip(shell).match(/^\.app\s*\{([^}]*)\}/m);
    expect(app, ".app rule not found in shell.css").toBeTruthy();
    expect(app![1]).toMatch(/grid-template-columns:\s*var\(--app-nav-width\)/);
    expect(strip(shell)).toMatch(
      /\.app\.nav-expanded\s*\{\s*--app-nav-width:\s*var\(--app-nav-width-expanded\)/,
    );
  });

  it("keeps the width a single declaration no sheet may privately copy", () => {
    // The number lives in ONE place and its runtime override in ONE other,
    // and nothing anywhere re-declares it. A private copy is the failure this
    // whole pair of readers exists to prevent: it goes stale and refuses to
    // move when the rail expands, while every test that only checks the
    // console's arithmetic stays green.
    const src = join(here, "..", "..");
    const sheets = (dir: string, acc: string[] = []): string[] => {
      for (const name of readdirSync(dir)) {
        const path = join(dir, name);
        if (statSync(path).isDirectory()) sheets(path, acc);
        else if (name.endsWith(".css")) acc.push(path);
      }
      return acc;
    };
    const declarers: string[] = [];
    for (const file of sheets(src)) {
      const source = strip(readFileSync(file, "utf8"));
      const rel = relative(src, file).split(sep).join("/");
      for (const [] of source.matchAll(/--app-nav-width\s*:/g)) declarers.push(rel);
      // --nav-w would be a second name for the same width: no sheet may use it.
      expect(source, `${rel} names --nav-w`).not.toContain("--nav-w");
    }
    // tokens.css states the 72; shell.css swaps it on `.app.nav-expanded`. Two
    // lines app-wide, and the expanded one is deliberately an override of the
    // TOKEN rather than a restatement of the column.
    expect(declarers.sort()).toEqual(["design/tokens.css", "shell.css"]);
  });

  it("sizes every rule from the scale — no raw px font-size", () => {
    const literals = [...strip(css).matchAll(/font-size:\s*([\d.]+px)/g)].map((m) => m[1]);
    expect(literals).toEqual([]);
    expect([...css.matchAll(/font-size:\s*var\(--app-type-/g)].length).toBeGreaterThan(30);
  });

  it("the route mounts the promoted-system marker", () => {
    // Without the marker, surfaces.css and overlays.css are inert on this
    // screen and every shared class silently keeps legacy paint.
    const route = readFileSync(join(here, "..", "..", "routes", "ReviewRoute.tsx"), "utf8");
    expect(route).toContain('data-design-system="app"');
    expect(route).toContain("review-main");
  });
});
