import { readdirSync, readFileSync, statSync } from "node:fs";
import { dirname, join, relative } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

/* The doorway gate.
 *
 * The overlay primitives (ui/Dialog, ui/Popover, ui/Sheet) paint from
 * `--app-*`; there is one vocabulary and no scope to cross. `app-overlay` is
 * the one app-wide class a portalled overlay passes, on any route, including
 * routes with no Settings marker (the bell popover): a class marks a surface
 * as ours, while a route marker only marks where the surface was opened from.
 * What is asserted: every overlay passes the class, each primitive states its
 * own chrome, and a wearer only REFINES it.
 *
 * The class cannot be enforced by the CSS that consumes it, which is the whole
 * reason for this file: a selector that depends on a className is only as good
 * as the test that the className is still passed.
 */

const HERE = dirname(fileURLToPath(import.meta.url));
const SRC = join(HERE, "..");
const read = (rel: string) => readFileSync(join(SRC, rel), "utf8");

/* Every file that renders a portalled overlay, found on disk rather than listed.
 *
 * A hand list fails silently both ways: a row whose file renders no overlay
 * loops over nothing and passes, and an overlay no row names is never held to
 * the rule. Derived, a new overlay is bound the moment it is written, and a
 * file that stops rendering one stops being checked without anyone pruning a
 * row. */
function tsxUnder(dir: string, out: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) tsxUnder(path, out);
    else if (name.endsWith(".tsx") && !name.includes(".test.")) out.push(relative(SRC, path));
  }
  return out;
}

/** `ui/` is where the shells are DEFINED; it is not a wearer of them.
 *
 * A walk over a directory that does not exist throws at module scope, and
 * vitest then reports a suite with NO TESTS rather than a failure: the gate
 * does not go red, it disappears. So the walk is checked by a named wearer
 * below: deriving from disk stops a list going stale, and naming one entry
 * stops the WALK going stale. */
const OVERLAY_WEARERS = [...tsxUnder(join(SRC, "features")), ...tsxUnder(join(SRC, "shell"))]
  .filter((rel) => /<(Dialog|Popover|Sheet)[\s>]/.test(read(rel)))
  .sort();

const SHELLS = ["Dialog", "Popover", "Sheet"] as const;
const MARKERS = ["app-overlay"] as const;

/** The opening tag starting at `at`, brace-aware so `label={a ? b : c}` is one prop. */
function openingTag(source: string, at: number): string {
  let depth = 0;
  for (let i = at; i < source.length; i++) {
    const ch = source[i];
    if (ch === "{") depth += 1;
    else if (ch === "}") depth -= 1;
    else if (ch === ">" && depth === 0) return source.slice(at, i + 1);
  }
  return source.slice(at);
}

function overlaysIn(rel: string): { shell: string; tag: string }[] {
  const source = read(rel);
  const found: { shell: string; tag: string }[] = [];
  for (const shell of SHELLS) {
    const pattern = new RegExp(`<${shell}[\\s\\n>]`, "g");
    for (const match of source.matchAll(pattern)) {
      found.push({ shell, tag: openingTag(source, match.index!) });
    }
  }
  return found;
}

describe("settings doorway", () => {
  it("walks the shell tier, so app chrome wearing an overlay is covered", () => {
    /* One named wearer per walked tier. A directory the walk stops visiting is
       invisible in an aggregate — every file it holds simply stops being
       checked — and a directory it cannot FIND takes the whole suite
       down as "no tests". Both failures are silent in the totals
       line; this one is not. */
    expect(
      OVERLAY_WEARERS,
      "shell/KeyboardShortcuts.tsx renders a ui/Sheet. If it is missing here, " +
        "the walk no longer reaches src/shell/ and every overlay in the app " +
        "chrome is unchecked.",
    ).toContain("shell/KeyboardShortcuts.tsx");
  });

  it("finds the overlays it claims to guard", () => {
    // A regex that silently matches nothing would make every assertion below
    // vacuously true.
    expect(OVERLAY_WEARERS.length, "the scan found no overlay wearers").toBeGreaterThanOrEqual(9);
    const total = OVERLAY_WEARERS.flatMap((file) => overlaysIn(file)).length;
    expect(total).toBeGreaterThanOrEqual(11);
  });

  it.each(OVERLAY_WEARERS)("%s: every overlay opts into a scope", (file) => {
    {
      const overlays = overlaysIn(file);
      for (const { shell, tag } of overlays) {
        const marked = MARKERS.some((marker) => tag.includes(marker));
        expect(
          marked,
          `<${shell}> in ${file} renders a portalled overlay without the doorway class. ` +
            `Add className="app-overlay", or its chrome misses the promoted skin.\n${tag}`,
        ).toBe(true);
      }
    }
  });

  it("each overlay primitive paints its OWN chrome, from the app scope", () => {
    // The primitives paint from --app-* directly: a shell must not depend on
    // a class for the box it draws.
    for (const [file, subject] of [
      ["ui/Dialog.css", ".ui-dialog"],
      ["ui/Popover.css", ".ui-popover-inner"],
      ["ui/Sheet.css", ".ui-sheet"],
    ] as const) {
      const css = read(file);
      for (const property of ["background", "border", "box-shadow", "color", "font-family"]) {
        expect(css, `${file} does not set ${property} on ${subject} itself`)
          .toMatch(new RegExp(`${property}:`));
      }
      // Painted from the promoted scope, never the legacy names. (The ratchet
      // counts legacy tokens app-wide; this says WHERE they must not be.)
      expect(css, `${file} still paints from the legacy scope`)
        .not.toMatch(/var\(--(bg|surface|border|text|accent|shadow|radius|ease|t-(fast|med|slow))[a-z-]*\)/);
    }
  });

  it("the register's dialogs are the app's dialog", () => {
    // No material paints a dialog: every dialog (the same `.ledger-form` on
    // Plugins included) is ui/Dialog's glass at the overlay radius, so one form
    // never renders as two different dialogs by tab.
    const material = read("design/materials/register-material.css").replace(/\/\*[\s\S]*?\*\//g, "");
    expect(material).not.toMatch(/\.ui-dialog/);

    // No body-marker prefix on the app-overlay chrome: an overlay is styled by
    // what it is, not by the route it opened over.
    expect(read("design/settings.css")).not.toMatch(
      /data-settings-design-system[^\n]*\.app-overlay/,
    );
  });

  it("Badge's tone table is declared once, in Badge's own sheet", () => {
    // Badge reads --app-* itself, so a copy of its tones under a scope marker
    // can only drift: the same badge would differ between screens.
    const badgeCss = read("ui/Badge.css");
    const tones = [...badgeCss.matchAll(/\.ui-badge-(\w+)\s*\{[^}]*--ui-badge-color:/g)].map(
      (m) => m[1],
    );
    expect(tones.length).toBeGreaterThanOrEqual(5);
    for (const [name, css] of [
      ["settings.css", read("design/settings.css")],
      ["design/overlays.css", read("design/overlays.css")],
      ["design/surfaces.css", read("design/surfaces.css")],
    ] as const) {
      expect(css, `${name} restates Badge's channels`).not.toMatch(/--ui-badge-[a-z]+\s*:/);
    }
  });

  it("styles no doorway class that no component passes", () => {
    // A class styled here but never rendered is a seal that silently is not
    // one (`.settings-company-dialog` was such a class). Comments are stripped
    // first: only real rules can leak.
    const strip = (source: string) => source.replace(/\/\*[\s\S]*?\*\//g, "");
    const appOverlayRules = strip(read("design/overlays.css"));
    const materialRules = strip(read("design/materials/register-material.css"));
    // app-overlay is app-wide opt-in, so ANY overlay wearer may pass it.
    const componentSource = OVERLAY_WEARERS.map(read).join("\n");
    const styled = [
      ...appOverlayRules.matchAll(/\.(app-overlay[\w-]*)/g),
      ...materialRules.matchAll(/\.(app-overlay[\w-]*)/g),
    ].map((m) => m[1]);
    for (const cls of new Set(styled)) {
      expect(componentSource, `settings CSS styles .${cls}, which no component passes`).toContain(
        cls,
      );
    }
    expect(strip(read("design/settings.css"))).not.toContain(
      "settings-company-dialog",
    );
  });

  // No "keeps the marker off app chrome" arm: the promoted skin is the app's
  // one system, not a Settings palette chrome must not take. Chrome passes
  // app-overlay deliberately, listed above.
});
