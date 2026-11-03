import { readdirSync, readFileSync, statSync } from "node:fs";
import { dirname, join, relative } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const HERE = dirname(fileURLToPath(import.meta.url));
const tokensCss = readFileSync(join(HERE, "tokens.css"), "utf8");
/* Every material, FROM DISK: with a hand-written list, a new material would
 * skip WCAG entirely and nothing would say so.
 *
 * The filename IS the contract: `<name>-material.css` pairs with
 * `body[data-material="<name>"]`, and the pairing is asserted below rather than
 * assumed, so a file that does not follow it fails by name instead of being
 * silently skipped. */
const MATERIALS = readdirSync(join(HERE, "materials"))
  .filter((file) => file.endsWith("-material.css"))
  .sort()
  .map((file) => ({
    name: file.replace(/-material\.css$/, ""),
    file,
    css: readFileSync(join(HERE, "materials", file), "utf8"),
  }));

/* WCAG contrast gate over the real token files — the ONE system and its
 * materials. Parses the light and dark
 * blocks of :root and of the register material, materializes each palette the
 * way the cascade does (register = root overlaid by the material), composites
 * translucent surfaces over the canvas, and asserts the ratios AA requires
 * for normal-size text (4.5:1) on every ground of EVERY material.
 *
 * Iterating materials is not optional: a gate that only checked the default
 * palette would silently drop the guarantee on the two densest screens.
 *
 * A token named `text-faint` reads as an invitation to set quiet TEXT, so it
 * is the third TEXT step and is gated like the two above it. The non-text tier
 * is a token nobody will mistake for text: --app-decor, gated at 1.4.11's 3:1
 * for graphical objects, and the structural gate at the bottom of this file is
 * what stops it drifting into text — it fails by name when a rule paints text
 * with it.
 */

type RGBA = { r: number; g: number; b: number; a: number };

function parseColor(value: string): RGBA | null {
  const hex = value.match(/^#([0-9a-f]{6})$/i);
  if (hex) {
    const n = parseInt(hex[1], 16);
    return { r: (n >> 16) & 255, g: (n >> 8) & 255, b: n & 255, a: 1 };
  }
  const rgba = value.match(/^rgba?\(\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)\s*(?:,\s*([\d.]+)\s*)?\)$/i);
  if (rgba) {
    return { r: Number(rgba[1]), g: Number(rgba[2]), b: Number(rgba[3]), a: rgba[4] === undefined ? 1 : Number(rgba[4]) };
  }
  return null;
}

/** `prefix` because the shell chrome declares `--tb-*` / `--rail-*` rather than
 *  `--app-*`, which is the default. */
function tokensIn(block: string, prefix = "app"): Map<string, RGBA> {
  const out = new Map<string, RGBA>();
  for (const m of block.matchAll(new RegExp(`(--${prefix}-[\\w-]+)\\s*:\\s*([^;]+);`, "g"))) {
    const color = parseColor(m[2].trim());
    if (color) out.set(m[1], color);
  }
  return out;
}

function block(source: string, selectorStart: string): string {
  const at = source.indexOf(selectorStart);
  if (at === -1) throw new Error(`selector not found: ${selectorStart}`);
  const open = source.indexOf("{", at);
  const close = source.indexOf("}", open);
  return source.slice(open + 1, close);
}

const composite = (top: RGBA, base: RGBA): RGBA => ({
  r: top.r * top.a + base.r * (1 - top.a),
  g: top.g * top.a + base.g * (1 - top.a),
  b: top.b * top.a + base.b * (1 - top.a),
  a: 1,
});

function luminance({ r, g, b }: RGBA): number {
  const [lr, lg, lb] = [r, g, b]
    .map((v) => v / 255)
    .map((v) => (v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4)));
  return 0.2126 * lr + 0.7152 * lg + 0.0722 * lb;
}

function ratio(fg: RGBA, bg: RGBA): number {
  const [hi, lo] = [luminance(fg), luminance(bg)].sort((a, b) => b - a);
  return (hi + 0.05) / (lo + 0.05);
}

const rootLight = tokensIn(block(tokensCss, ":root {"));
const rootDark = tokensIn(block(tokensCss, ':root[data-theme="dark"] {'));
/* Missing blocks parse to EMPTY here rather than throwing. A throw at module
   level is not a strict gate, it is a worse one: vitest reports a suite that
   fails to collect as "no tests" and a green-looking zero, so a material added
   without its dark block would take the whole contrast file off the board
   instead of failing in it. Empty maps let the named assertions below do the
   reporting.

   The material's token block is `body[data-material="<name>"]`, optionally
   scoped to the elements that wear it (`... :is(.settings-content, ...)`, so
   the tokens skip the app chrome). The
   scope is one `:is()` and nothing else, so a block for some other element
   (`... .settings-design-system {`) is never read as the palette. */
const materialBlock = (css: string, prefix: string, name: string): string => {
  const selector = `${prefix}body[data-material="${name}"]`;
  const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const at = css.search(new RegExp(`${escaped}(?: :is\\([^)]*\\))? \\{`));
  return at === -1 ? "" : block(css.slice(at), selector);
};

const materials = MATERIALS.map((material) => ({
  ...material,
  light: tokensIn(materialBlock(material.css, "", material.name)),
  dark: tokensIn(materialBlock(material.css, ':root[data-theme="dark"] ', material.name)),
}));

/* Materialized exactly as the cascade resolves them: the material's base block
 * applies in dark too unless its dark block restates the token (a hole the
 * completeness test below keeps closed). */
type Palette = readonly [string, typeof rootLight];

const PALETTES: Palette[] = [
  ["default light", rootLight],
  ["default dark", rootDark],
  ...materials.flatMap((m) => [
    [`${m.name} light`, new Map([...rootLight, ...m.light])] as const,
    [`${m.name} dark`, new Map([...rootDark, ...m.light, ...m.dark])] as const,
  ]),
];

const TEXT_TOKENS = [
  "--app-text",
  "--app-text-muted",
  "--app-text-faint",
  "--app-action-text",
  "--app-positive",
  "--app-warning",
  "--app-danger",
  "--app-information",
] as const;

describe.each(PALETTES)("%s", (_name, tokens) => {
  const canvas = tokens.get("--app-canvas")!;
  const grounds = {
    canvas,
    surface: composite(tokens.get("--app-surface")!, canvas),
    raised: composite(tokens.get("--app-surface-raised")!, canvas),
  };

  it.each(TEXT_TOKENS.map((token) => [token]))("%s holds 4.5:1 on every ground", (token) => {
    const color = tokens.get(token);
    expect(color, `${token} missing from palette`).toBeTruthy();
    for (const [ground, bg] of Object.entries(grounds)) {
      expect(
        ratio(color!, bg),
        `${token} on ${ground}`,
      ).toBeGreaterThanOrEqual(4.5);
    }
  });

  it("action ink holds 4.5:1 on the filled action button", () => {
    expect(ratio(tokens.get("--app-action-ink")!, tokens.get("--app-action")!))
      .toBeGreaterThanOrEqual(4.5);
  });

  // The bell's count pill: dark theme turns the danger FILL light, so the ink
  // must flip dark with it; a hard-coded white ink fails contrast there.
  it("danger ink holds 4.5:1 on the filled danger surface", () => {
    expect(ratio(tokens.get("--app-danger-ink")!, tokens.get("--app-danger")!))
      .toBeGreaterThanOrEqual(4.5);
  });

  // WCAG 1.4.11: a graphical object still has to be SEEN, just not read. This
  // is the whole exemption decor gets — 3:1, on every ground, not a pass.
  it("decor clears 3:1 on every ground as a graphical object", () => {
    const decor = tokens.get("--app-decor");
    expect(decor, "--app-decor missing from palette").toBeTruthy();
    for (const [ground, bg] of Object.entries(grounds)) {
      expect(ratio(decor!, bg), `--app-decor on ${ground}`).toBeGreaterThanOrEqual(3);
    }
  });

  // WCAG 1.4.11 again: a select or a filter is found by its edge, so the edge
  // is a graphical object that has to be seen on every ground.
  it("a control's boundary clears 3:1 on every ground", () => {
    const edge = tokens.get("--app-border-control");
    expect(edge, "--app-border-control missing from palette").toBeTruthy();
    for (const [ground, bg] of Object.entries(grounds)) {
      expect(ratio(edge!, bg), `--app-border-control on ${ground}`).toBeGreaterThanOrEqual(3);
    }
  });

  // Hover tints the row under the pointer, and the row's quietest text stays
  // on it: the tint is only as dark as every text step allows.
  it.each(TEXT_TOKENS.map((token) => [token]))("%s holds 4.5:1 on a hovered row", (token) => {
    const hover = tokens.get("--app-surface-hover")!;
    for (const [ground, bg] of Object.entries({ canvas, surface: grounds.surface })) {
      expect(ratio(tokens.get(token)!, composite(hover, bg)), `${token} on hovered ${ground}`).toBeGreaterThanOrEqual(4.5);
    }
  });

  // A segmented control lays its chosen option, gold name on the gold wash,
  // inside a sunken track: the darkest ground the chosen name ever sits on.
  it("the chosen name holds 4.5:1 on its wash inside a sunken track", () => {
    const track = composite(tokens.get("--app-surface-sunken")!, canvas);
    const wash = composite(tokens.get("--app-action-soft")!, track);
    expect(ratio(tokens.get("--app-action-text")!, wash)).toBeGreaterThanOrEqual(4.5);
  });

  // An off switch is a knob on a bare track: the knob must stand out from it.
  it("an off switch's knob holds 3:1 on its track", () => {
    const knob = composite(tokens.get("--app-surface")!, canvas);
    expect(ratio(knob, tokens.get("--app-border-control")!)).toBeGreaterThanOrEqual(3);
  });

  // A chosen chip trades the neutral control edge for gold; the gold must
  // bound it at least as well, or choosing would blur the control.
  it("a chosen control's edge holds 3:1 on every ground", () => {
    for (const [name, bg] of Object.entries(grounds)) {
      const edge = composite(tokens.get("--app-action-edge")!, bg);
      expect(ratio(edge, bg), name).toBeGreaterThanOrEqual(3);
    }
  });

  // Decor is the quieter tier, so it must not outrank the text step above it —
  // otherwise the ramp inverts and "faint" stops meaning anything.
  it("stays quieter than the faint text step above it", () => {
    for (const bg of Object.values(grounds)) {
      expect(ratio(tokens.get("--app-decor")!, bg))
        .toBeLessThan(ratio(tokens.get("--app-text-faint")!, bg));
    }
  });
});

describe("register material", () => {
  it("restates no app token: a material is never a second palette", () => {
    // A material that restates the action set, a surface, a hairline or a
    // tempo makes its screens differ from the rest (ink controls where every
    // other screen's are gold, a faster switch, paper dialogs where every
    // other dialog is glass). Read from the raw sheet, not the colour parser, so a timing or
    // a var() restatement is caught as well as a colour.
    const restated = MATERIALS.flatMap((m) =>
      [...m.css.replace(/\/\*[\s\S]*?\*\//g, "").matchAll(/(--app-[\w-]+)\s*:/g)].map((x) => `${m.name}: ${x[1]}`),
    );
    expect(restated, "a material restates an app token").toEqual([]);
  });
});

/* ---- Light structure -----------------------------------------------------
 * A pale page has no glow to separate things, so light must draw its
 * boundaries: a hairline that can be seen, a panel visibly lighter than the
 * page under it, a lift under each panel, and page light without a tint. The
 * floors sit just under the current values; the earlier light palette
 * (hairline 1.25:1, panel 1.09:1, a warm and a green haze) fails every one.
 */
describe("light theme draws its structure", () => {
  const canvas = rootLight.get("--app-canvas")!;
  const panel = composite(rootLight.get("--app-surface")!, canvas);
  const raised = rootLight.get("--app-surface-raised")!;

  it("a hairline is visible on the page and on a panel", () => {
    const border = rootLight.get("--app-border")!;
    for (const [ground, bg] of Object.entries({ canvas, panel, raised })) {
      expect(ratio(composite(border, bg), bg), `--app-border on ${ground}`).toBeGreaterThanOrEqual(1.4);
    }
  });

  it("a strong edge holds 2:1 on a panel", () => {
    const strong = rootLight.get("--app-border-strong")!;
    expect(ratio(composite(strong, panel), panel)).toBeGreaterThanOrEqual(2);
  });

  it("a panel is visibly lighter than the page it lies on", () => {
    expect(ratio(panel, canvas)).toBeGreaterThanOrEqual(1.12);
  });

  it("the page light carries no tint", () => {
    for (const name of ["--app-ambient-warm", "--app-ambient-cool"]) {
      const { r, g, b } = rootLight.get(name)!;
      expect([g, b], `${name} is tinted`).toEqual([r, r]);
    }
  });

  it("a hovered row shows, and a selected one sits one step quieter", () => {
    const hover = rootLight.get("--app-surface-hover")!;
    const selected = rootLight.get("--app-selected")!;
    for (const [ground, bg] of Object.entries({ canvas, panel })) {
      const hovered = ratio(composite(hover, bg), bg);
      const picked = ratio(composite(selected, bg), bg);
      expect(hovered, `hover on ${ground}`).toBeGreaterThanOrEqual(1.12);
      expect(picked, `selected on ${ground}`).toBeGreaterThanOrEqual(1.08);
      expect(picked, `selected on ${ground}`).toBeLessThan(hovered);
    }
  });

  const PANELS: [string, string][] = [
    ["design/overlays.css", ".panel {"],
    ["ui/Card.css", ".settings-card {"],
    ["design/settings.css", ".settings-section {"],
    ["features/intelligence/IntelligenceSection.css", ".intel-card {"],
    ["features/companies/CompaniesSection.css", ".ledger-add-card {"],
  ];
  it.each(PANELS)("%s %s lifts off the page", (sheet, selector) => {
    const css = readFileSync(join(HERE, "..", sheet), "utf8").replace(/\/\*[\s\S]*?\*\//g, "");
    expect(block(css, selector)).toMatch(/box-shadow:\s*var\(--app-shadow\)/);
  });
});

/* ---- The type ramp -------------------------------------------------------
 * The ramp is declared once, so its contract lives with the declaration.
 */
describe("type ramp", () => {
  /** Smallest size the scale is allowed to reach. Below this, text on a dense
   *  register stops being readable. */
  const FLOOR_PX = 11;

  it("declares the scale, and nothing in it is below the floor", () => {
    const sizes = [...tokensCss.matchAll(/--app-type-([\w-]+):\s*([\d.]+)px/g)].map((m) => ({
      role: m[1],
      px: Number(m[2]),
    }));
    expect(sizes.length).toBeGreaterThanOrEqual(10);
    // `whisper` is the one deliberate resident below the reading floor:
    // recognition labels — uppercase,
    // tracked shapes you identify rather than read. Its own floor is 10px:
    // at 9px a bold uppercase label on a light page loses its counters. The
    // "whisper is recognition text" gate below enforces the pairing that
    // justifies the exemption. Everything else keeps the reading floor.
    for (const { role, px } of sizes) {
      const floor = role === "whisper" ? 10 : FLOOR_PX;
      expect(px, `--app-type-${role} is below the ${floor}px floor`).toBeGreaterThanOrEqual(
        floor,
      );
    }

    // Whole pixels only: a 0.5px difference is not hierarchy anyone can see,
    // it is noise that reads as drift.
    for (const { role, px } of sizes) {
      expect(Number.isInteger(px), `--app-type-${role} (${px}px) is not a whole pixel`).toBe(
        true,
      );
    }

    const byRole = Object.fromEntries(sizes.map((s2) => [s2.role, s2.px]));

    // The name role is primary row content: nothing subordinate may outrank
    // it, and only headings may exceed it. The floor exists to stop the
    // primary row content shrinking toward chrome sizes, not to pin a size.
    expect(byRole.name).toBeGreaterThanOrEqual(15);
    // A block title shares the name's size and outranks it by place, weight
    // and space: a sixth step inside 12-16px is one no reader can tell apart.
    expect(byRole.title).toBe(byRole.name);
    const band = new Set(sizes.filter((s2) => s2.px >= 12 && s2.px <= 16).map((s2) => s2.px));
    expect(band.size, "distinct sizes between 12 and 16px").toBeLessThanOrEqual(4);
    for (const role of ["body", "meta", "label", "viz", "micro", "whisper"]) {
      expect(byRole[role], `${role} must not outrank the name role`).toBeLessThan(byRole.name);
    }

    // The instrument tiers sit in a fixed order: micro is a secondary fact at
    // the chrome floor, under the fact floor; whisper is a label under the
    // drawing's own numerals.
    expect(byRole.micro).toBe(byRole.label);
    expect(byRole.micro).toBeLessThan(byRole.meta);
    expect(byRole.viz).toBeLessThan(byRole.micro);
    expect(byRole.whisper).toBeLessThan(byRole.viz);

    // The screen's own title outranks the cards on it, or every card
    // outranks its own page.
    expect(byRole.page).toBeGreaterThan(byRole.screen);
    expect(byRole.screen).toBeGreaterThan(byRole.title);

    // ...and it must outrank them DECISIVELY. Rank alone is not hierarchy: a
    // ramp whose every step is ~1.2 passes every ordering assertion and still
    // reads flat, because it has no dominant note — each tier reads as its
    // neighbour's sibling.
    expect(
      byRole.page / byRole.screen,
      "the h1 must clear the card heading by a visible step, not a rank",
    ).toBeGreaterThanOrEqual(1.2);

    // The page title is a label on a control surface, not a landing-page hero:
    // a poster-size title draws the eye off the working screen.
    expect(byRole.page, "the h1 is chrome, not a hero").toBeLessThanOrEqual(24);

    // Two floors that mean different things: anything carrying a FACT stops at
    // `meta`, and chrome stops at `label`. `viz` is lower than both and is
    // legal only inside an instrument SVG that has a text alternative.
    expect(byRole.meta, "the fact floor").toBeGreaterThanOrEqual(13);
    expect(byRole.label, "the chrome floor").toBeGreaterThanOrEqual(12);
    expect(byRole.viz).toBeLessThan(byRole.label);
  });
});

/* ---- The structural half of the contract -------------------------------- *
 *
 * A sub-AA token is only safe while nothing paints text with it, and CSS cannot
 * say that about itself. `color` and `fill` are the two properties that put a
 * token on glyph shapes a reader might read, so every use of decor through one
 * of them is named here or the gate fails.
 *
 * The allowlist is a frozen artifact, like the route table and the ratchet
 * baseline: adding a row is a deliberate edit that says "this selector's
 * subject is a glyph, not a sentence". Dead rows fail too — the same check the
 * doorway gate runs, and for the same reason: an allowlist nobody prunes stops
 * describing the code and starts excusing it.
 */
/* Every stylesheet that consumes the --app-* scope, FROM DISK, so a new sheet
 * is policed by default: the h1/display rank, the decor-never-paints-text
 * contract and the whisper recipe would all stop at a hand list's edge.
 *
 * `TAB_STYLESHEETS` in geometry.test.ts shares only the path FORMAT: it is
 * deliberately narrow (the Settings tabs plus CompanyIcon), not a second copy
 * of this list, and must not be conflated with one.
 *
 * EXEMPT is the escape hatch and is meant to stay near-empty, spelled the way
 * `dead-rules`'s is: a sheet here is a sheet nothing checks, so it states why. */
const EXEMPT: Record<string, string> = {
  "design/tokens.css":
    "defines the scope rather than spending it — every --app-decor and " +
    "--app-type-display line in it is the declaration these gates police the " +
    "USES of",
};

function stylesheets(dir: string, acc: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) stylesheets(path, acc);
    else if (name.endsWith(".css")) acc.push(relative(join(HERE, ".."), path));
  }
  return acc;
}

const SCOPE_STYLESHEETS = stylesheets(join(HERE, ".."))
  .filter((sheet) => !(sheet in EXEMPT))
  .sort();

describe("the scope stylesheet sweep", () => {
  /* A derived list fails in two directions a hand-written one cannot, and both
     leave every gate below iterating nothing and passing — the failure mode
     that makes a derived list feel safe when it is not (the same reason the
     material registry asserts its own naming contract rather than trusting
     it). One: the walk finds no sheets, because the tree moved. Two: EXEMPT
     names a file that is gone, so it has stopped exempting anything and is now
     only a claim nobody checks. */
  it("reaches the tree, and every exemption is live and states why", () => {
    expect(
      SCOPE_STYLESHEETS.length,
      "the walk found almost no stylesheets, so the gates below read nothing",
    ).toBeGreaterThan(40);
    const onDisk = stylesheets(join(HERE, ".."));
    for (const [sheet, why] of Object.entries(EXEMPT)) {
      expect(onDisk, `EXEMPT names ${sheet}, which is not on disk`).toContain(sheet);
      expect(why.trim().length, `EXEMPT["${sheet}"] states no reason`).toBeGreaterThan(20);
    }
  });
});

/** Properties that can paint a glyph a reader might read. */
const TEXT_PAINTING = ["color", "fill"];

/** Selectors whose subject is a glyph, so decor is legal on it. */
const DECOR_GLYPH_SELECTORS = [
  ".info-tip-trigger", // the ⓘ mark itself
  ".stage-decoder-toggle-chevron", // disclosure chevron
  ".schedule-local-time svg", // clock glyph beside the timezone
  ".dial-numeral", // the dial's own scale; the agenda is its text alternative
  ".notif-icon", // category icon (role="img" + aria-label); the category is also a Badge beside it
  ".intel-cap.is-future .intel-cap-mark", // aria-hidden mark; state is in text beside it
  ".intel-order-route svg",
  ".intel-order-evidence svg",
  ".review-history-connector", // aria-hidden pair-connector arrow icon
  ".review-history-chevron", // aria-hidden disclosure chevron icon
  ".palette-item svg", // command icons; each item names itself in text
  ".ui-btn-icon", // icon-only button primitive; its label is the aria-label
];

function rulesPainting(css: string, token: string): { selector: string; property: string }[] {
  const lines = css.replace(/\/\*[\s\S]*?\*\//g, "").split("\n");
  const found: { selector: string; property: string }[] = [];
  lines.forEach((line, i) => {
    for (const m of line.matchAll(new RegExp(`([a-z-]+)\\s*:\\s*[^;{]*var\\(\\s*${token}\\b`, "g"))) {
      if (!TEXT_PAINTING.includes(m[1])) continue;
      let selector = line.includes("{") ? line.split("{")[0].trim() : null;
      for (let j = i; selector === null && j >= 0; j--) {
        const text = lines[j].trim();
        if (text.endsWith("{") && !text.startsWith("@")) selector = text.slice(0, -1).trim();
      }
      found.push({ selector: selector ?? "<unknown>", property: m[1] });
    }
  });
  return found;
}

/* `display` is a NUMERAL rank, and an h1 is not a numeral.
 *
 * The ramp comments `page` as "the screen's own h1" and the assertion above
 * caps it at 24 because "the h1 is chrome, not a hero". An h1 at `display`
 * (30) is not a rounding error against that ceiling; it is a different rank,
 * and a screen whose tabs mix the two resizes its title on every tab switch.
 *
 * Every other consumer of `display` is a figure: the schedule dial's dispatch
 * time, the sync stream total, Job detail's comp price. So the rank keeps its
 * numerals and gives up its titles, and a rule may
 * only pair `h1` with `display` when its selector says the h1 IS a figure.
 * Named in the selector rather than inferred, because a hero numeral and a
 * hero title are indistinguishable to a stylesheet.
 */
describe("the display rank is for numerals", () => {
  const src = join(HERE, "..");
  const H1_DISPLAY = /([^{}]*\bh1\b[^{}]*)\{([^{}]*)\}/g;

  it("no h1 wears the display rank unless the selector calls it a figure", () => {
    const offenders: string[] = [];
    for (const file of SCOPE_STYLESHEETS) {
      const css = readFileSync(join(src, file), "utf8").replace(/\/\*[\s\S]*?\*\//g, "");
      for (const [, selector, body] of css.matchAll(H1_DISPLAY)) {
        if (!/var\(\s*--app-type-display\b/.test(body)) continue;
        if (/\bfigure\b/.test(selector)) continue;
        offenders.push(`${file}  ${selector.trim().slice(0, 70)}`);
      }
    }
    expect(
      offenders,
      `an h1 is the screen's title and takes --app-type-page. --app-type-display ` +
        `is the instrument-hero rank and every other use of it is a tabular ` +
        `numeral. A headline that really is a figure says so in its class ` +
        `(\`.cockpit-figure\`). Found:\n  ${offenders.join("\n  ")}`,
    ).toEqual([]);
  });

  it("the figure rank is still claimed by name, so the rule above guards a live case", () => {
    // The cockpit figures are panel h2s under "Insights"; the rank is reached
    // only through the class.
    const stats = readFileSync(join(src, "features/statistics/statistics.css"), "utf8");
    expect(stats).toMatch(/h2\.cockpit-figure[^{]*\{[^}]*--app-type-display/);
  });
});

describe("--app-decor never paints text", () => {
  const src = join(HERE, "..");
  const uses = SCOPE_STYLESHEETS.flatMap((file) =>
    rulesPainting(readFileSync(join(src, file), "utf8"), "--app-decor").map((use) => ({
      ...use,
      file,
    })),
  );

  it("paints color/fill only on selectors declared to be glyphs", () => {
    const offenders = uses
      .filter((use) => !DECOR_GLYPH_SELECTORS.includes(use.selector))
      .map((use) => `${use.file}: ${use.selector} { ${use.property} }`);
    expect(
      offenders,
      "decor is sub-AA — these must use --app-text-faint, or join DECOR_GLYPH_SELECTORS",
    ).toEqual([]);
  });

  it("lists no glyph selector that stopped using it", () => {
    const live = new Set(uses.map((use) => use.selector));
    expect(DECOR_GLYPH_SELECTORS.filter((selector) => !live.has(selector))).toEqual([]);
  });
});

/* ---- whisper is recognition text, not reading text ----------------------- *
 *
 * `--app-type-whisper` lives below the reading floor, and the exemption is
 * justified only by what it may paint: uppercase, tracked shapes a reader
 * IDENTIFIES rather than reads. CSS cannot say that about itself either, so
 * the pairing is enforced structurally: every rule block that sets whisper
 * must set `text-transform: uppercase` and a `letter-spacing` in the same
 * block. Sentence-case copy at 9px is exactly the regression this stops.
 */
describe("whisper is recognition text", () => {
  const src = join(HERE, "..");
  // surfaces.css is not a screen sheet, but it is where the shared kicker
  // (`.eyebrow`), table heads and source captions whisper from, the sweep's
  // biggest single consumer. It arrives with the disk walk; appending it a
  // second time would double-count its rules against the floor below.
  const whisperSheets = SCOPE_STYLESHEETS;
  const offenders: { file: string; selector: string; why: string }[] = [];
  let rules = 0;
  for (const file of whisperSheets) {
    const css = readFileSync(join(src, file), "utf8").replace(/\/\*[\s\S]*?\*\//g, "");
    for (const m of css.matchAll(/([^{}]+)\{([^}]*)\}/g)) {
      const [, selector, body] = m;
      if (!/font-size\s*:\s*var\(--app-type-whisper\b/.test(body)) continue;
      rules += 1;
      // The contract is ONE recipe: a whisper rule sets uppercase and takes
      // its weight and tracking from the two recipe tokens. Tracking that
      // merely EXISTS is not enough, and a literal, however close, is a
      // second recipe.
      const upper = /text-transform\s*:\s*uppercase/.test(body);
      const weight = /font-weight\s*:\s*var\(--app-type-whisper-weight\)/.test(body);
      const track = /letter-spacing\s*:\s*var\(--app-type-whisper-track\)/.test(body);
      // Control text is READ, so it never whispers: no whisper rule may name
      // an interactive element.
      const control = /\bbutton\b|\bsummary\b|\[role=|\.filter-title\b|\.filter-head\b/.test(selector);
      if (control) offenders.push({ file, selector: selector.trim(), why: "whisper on a control" });
      else if (!upper) offenders.push({ file, selector: selector.trim(), why: "no uppercase" });
      else if (!weight)
        offenders.push({ file, selector: selector.trim(), why: "weight is not the recipe token" });
      else if (!track)
        offenders.push({ file, selector: selector.trim(), why: "tracking is not the recipe token" });
    }
  }

  it("every whisper rule is uppercase at the one recipe (weight + tracking tokens)", () => {
    expect(offenders).toEqual([]);
    // The sweep reached the app: fewer than this means a screen fell back to
    // the chrome floor for its recognition labels.
    expect(rules).toBeGreaterThanOrEqual(55);
  });

  it("the recipe tokens themselves meet the contract: weight >= 650, tracking >= 0.09em", () => {
    const weight = tokensCss.match(/--app-type-whisper-weight:\s*(\d+)/);
    const track = tokensCss.match(/--app-type-whisper-track:\s*0?\.(\d+)em/);
    expect(weight && Number(weight[1])).toBeGreaterThanOrEqual(650);
    expect(track && Number(`0.${track[1]}`)).toBeGreaterThanOrEqual(0.09);
  });
});

describe("the material registry", () => {
  /* The list is read from disk, so the only way a material can go unchecked is
     by not matching the naming contract. This asserts the contract instead of
     trusting it: a file whose selector does not match its filename would parse
     to an EMPTY token map, which every contrast assertion below passes
     vacuously — the failure mode that makes a derived list feel safe when it is
     not. */
  it("pairs every material file with the body selector its name implies", () => {
    expect(materials.length, "no materials found in design/materials/").toBeGreaterThan(0);
    for (const material of materials) {
      expect(
        material.css.includes(`body[data-material="${material.name}"]`),
        `${material.file} declares no body[data-material="${material.name}"] block, so it ` +
          `parses to an empty palette and every contrast assertion passes vacuously`,
      ).toBe(true);
    }
  });
});

/* The shell chrome.
 *
 * `--tb-*` (topbar) and `--rail-*` (nav rail) are a SECOND colour vocabulary,
 * declared in `shell.css` rather than `tokens.css`, deliberately: the rail is
 * dark in both themes and the topbar sits on translucent glass, so neither
 * takes the app palette. The two surfaces present on EVERY screen are checked
 * here because the material check above reads only tokens.css and the
 * materials, and these are tokens somewhere else.
 *
 * The topbar's ground is `--app-surface-glass` composited over `--app-canvas`,
 * which is what the browser actually paints; the rail's is its own opaque
 * `--rail-canvas`.
 */
const shellCss = readFileSync(join(HERE, "..", "shell.css"), "utf8");

const tbLight = tokensIn(block(shellCss, ".topbar {"), "tb");
const tbDark = tokensIn(block(shellCss, '[data-theme="dark"] .topbar {'), "tb");
const railTokens = tokensIn(block(shellCss, ".nav-rail {"), "rail");

const CHROME_TEXT = ["text", "text-muted", "text-faint", "accent-text", "good", "warn", "danger"];

const CHROME: {
  label: string;
  tokens: Map<string, RGBA>;
  ground: RGBA;
  names: string[];
}[] = [
  {
    label: "topbar light",
    tokens: tbLight,
    ground: composite(rootLight.get("--app-surface-glass")!, rootLight.get("--app-canvas")!),
    names: CHROME_TEXT.map((n) => `--tb-${n}`),
  },
  {
    label: "topbar dark",
    tokens: new Map([...tbLight, ...tbDark]),
    ground: composite(rootDark.get("--app-surface-glass")!, rootDark.get("--app-canvas")!),
    names: CHROME_TEXT.map((n) => `--tb-${n}`),
  },
  {
    label: "nav rail",
    tokens: railTokens,
    ground: railTokens.get("--rail-canvas")!,
    names: ["--rail-text", "--rail-strong", "--rail-muted", "--rail-faint", "--rail-accent-text"],
  },
];

describe("shell chrome holds the same contrast floor as the app", () => {
  it("parsed a palette for each chrome surface", () => {
    // Without this the loops below iterate nothing and pass, which is how a
    // renamed selector would turn this file into decoration.
    for (const surface of CHROME) {
      expect(surface.tokens.size, `${surface.label} parsed no tokens`).toBeGreaterThan(4);
    }
  });

  for (const surface of CHROME) {
    for (const name of surface.names) {
      it(`${surface.label}: ${name} holds 4.5:1 on its own ground`, () => {
        const fg = surface.tokens.get(name);
        expect(fg, `${name} is not declared for ${surface.label}`).toBeDefined();
        const r = ratio(fg!, surface.ground);
        expect(
          Number(r.toFixed(2)),
          `${name} is ${r.toFixed(2)}:1 on ${surface.label} — below the 4.5:1 AA floor ` +
            `for normal text. The chrome is on every screen; it does not get a lower bar ` +
            `than the screens it frames.`,
        ).toBeGreaterThanOrEqual(4.5);
      });
    }
  }
});

describe("native UI follows the page's theme, not the OS's", () => {
  // The browser draws a select's popup and the scrollbars itself; the only
  // way it learns the theme is color-scheme on the same block as the tokens.
  const THEME_BLOCKS: [string, string, "light" | "dark"][] = [
    ["light root", ":root {", "light"],
    ["dark root", ':root[data-theme="dark"] {', "dark"],
    ["dark root with no theme set", ':root:not([data-theme="light"]):not([data-theme="dark"]) {', "dark"],
  ];

  for (const [label, selector, scheme] of THEME_BLOCKS) {
    it(`the ${label} declares color-scheme: ${scheme}`, () => {
      expect(block(tokensCss, selector)).toMatch(new RegExp(`(^|[;{\\s])color-scheme:\\s*${scheme}\\s*;`));
    });
  }
});

/* ---- The light accent ------------------------------------------------------
 * Light's gold is a fill on a pale page, so it needs saturation the dark
 * theme's pale gold does not: at the old 0.57 it read as khaki, the same voice
 * as a disabled control. It stays a gold, apart from the warning orange, and
 * the topbar's copy of it moves with it.
 */
function hueSat({ r, g, b }: RGBA): { hue: number; sat: number } {
  const [rn, gn, bn] = [r, g, b].map((v) => v / 255);
  const max = Math.max(rn, gn, bn);
  const min = Math.min(rn, gn, bn);
  const light = (max + min) / 2;
  const delta = max - min;
  if (delta === 0) return { hue: 0, sat: 0 };
  const sat = delta / (1 - Math.abs(2 * light - 1));
  const raw = max === rn ? ((gn - bn) / delta) % 6 : max === gn ? (bn - rn) / delta + 2 : (rn - gn) / delta + 4;
  return { hue: (raw * 60 + 360) % 360, sat };
}

describe("light accent", () => {
  const action = rootLight.get("--app-action")!;

  it("is a saturated gold", () => {
    expect(hueSat(action).sat).toBeGreaterThanOrEqual(0.7);
  });

  it("stays apart from the warning orange", () => {
    const gap = hueSat(action).hue - hueSat(rootLight.get("--app-warning")!).hue;
    expect(gap).toBeGreaterThanOrEqual(8);
  });

  it.each([
    ["--tb-accent", "--app-action"],
    ["--tb-accent-soft", "--app-action-soft"],
    ["--tb-accent-line", "--app-action-line"],
    ["--tb-accent-text", "--app-action-text"],
  ])("the topbar's %s equals %s", (copy, source) => {
    expect(tbLight.get(copy)).toEqual(rootLight.get(source));
  });
});

/* ---- Control edges ---------------------------------------------------------
 * WCAG 1.4.11 asks 3:1 for what identifies a control. A text field, a plain
 * button and an off switch have no fill to be seen by, so their edge (or the
 * track) is that boundary, and --app-border-control is the token gated at 3:1
 * on every ground above. Hover may strengthen an edge, never weaken it under
 * that floor.
 */
const CONTROL_EDGES: [string, string, RegExp][] = [
  ["ui/Button.css", ".ui-btn-ghost {", /border:\s*1px solid var\(--app-border-control\)/],
  ["ui/SearchField.css", ".ui-search {", /border:\s*1px solid var\(--app-border-control\)/],
  ["ui/Select.css", ".ui-select > select {", /border:\s*1px solid var\(--app-border-control\)/],
  ["ui/FilterChip.css", ".ui-chip {", /border:\s*1px solid var\(--app-border-control\)/],
  ["ui/FilterRail.css", ".filter-search-row {", /border:\s*1px solid var\(--app-border-control\)/],
  ["ui/Switch.css", ".ui-switch-track {", /background-color:\s*var\(--app-border-control\)/],
  ["design/materials/register-material.css", ".ledger-form textarea {", /border:\s*1px solid var\(--app-border-control\)/],
  ["features/opportunities/board-shell.css", ".range-row input {", /border:\s*1px solid var\(--app-border-control\)/],
  ["features/settings/ScheduleSection.css", ".schedule-inspector-time {", /border:\s*1px solid var\(--app-border-control\)/],
];

/* Rules that restate a control's edge colour, on hover or in a smaller size.
   Each must name a token at least as strong as the control edge. */
const EDGE_RESTATEMENTS: [string, string][] = [
  ["ui/Button.css", '.ui-btn-ghost:not(:disabled):not([aria-disabled="true"]):hover {'],
  ["ui/Button.css", ".ui-btn-ghost.ui-btn-strong {"],
  ["ui/Select.css", ".ui-select > select:hover:not(:disabled) {"],
  ["ui/FilterChip.css", ".ui-chip:not(:disabled):hover {"],
  ["ui/FilterSelect.css", ".ui-filterselect-trigger:hover {"],
  ["ui/SearchField.css", ".ui-search-sm {"],
];
const STRONG_EDGES = /var\(--app-(border-control|text-faint|text-muted|text)\)/;

const sheet = (path: string) =>
  readFileSync(join(HERE, "..", path), "utf8").replace(/\/\*[\s\S]*?\*\//g, "");

describe("control edges hold 3:1", () => {
  it.each(CONTROL_EDGES)("%s %s draws the control edge", (path, selector, edge) => {
    expect(block(sheet(path), selector)).toMatch(edge);
  });

  it.each(EDGE_RESTATEMENTS)("%s %s never weakens the edge", (path, selector) => {
    const body = block(sheet(path), selector);
    const restated = body.match(/border(?:-color)?:[^;]*/);
    if (restated) expect(restated[0]).toMatch(STRONG_EDGES);
  });

  it("a chosen control is bounded by the chosen edge, not the softer accent line", () => {
    expect(block(tokensCss, ":root {")).toMatch(/--app-chosen-line:\s*var\(--app-action-edge\)/);
  });

  it("the edge tokens a restatement may use are all at least the control edge's 3:1", () => {
    for (const [name, palette] of [["light", rootLight], ["dark", rootDark]] as const) {
      const canvas = palette.get("--app-canvas")!;
      for (const token of ["--app-border-control", "--app-text-faint", "--app-text-muted", "--app-text"]) {
        expect(ratio(palette.get(token)!, canvas), `${token} in ${name}`).toBeGreaterThanOrEqual(3);
      }
    }
  });
});
