import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

/* The focused row wears ONE focus treatment: its own.
 *
 * shell.css states the ring app-wide, unscoped, as a plain selector list, and
 * the arm that reaches a row (`.job-row` carries `tabindex`) is
 * `[tabindex]:focus-visible` at 0-2-0. That TIES a bare
 * `.job-row:focus-visible`, which is worse than losing to it, not better — a
 * tie is decided by load order between an always-loaded sheet and a lazy
 * route chunk, and neither file's author can see that from where they sit.
 * So the row's doubled-class override is what makes this a rule rather than
 * an accident, and both halves are asserted below.
 *
 * A sheet test rather than a DOM one because jsdom does not resolve the
 * cascade; the browser half is `board-shell.spec.ts`, which measures the
 * painted outline after click-then-Escape.
 */

const here = dirname(fileURLToPath(import.meta.url));
const board = readFileSync(join(here, "job-row.css"), "utf8");
const shell = readFileSync(join(here, "..", "..", "shell.css"), "utf8");

/** a-b-c specificity of one compound selector, `:is()` resolved by its most
 *  specific argument — enough for the selectors these two sheets use. */
function specificity(selector: string): [number, number, number] {
  let rest = selector;
  let a = 0, b = 0, c = 0;
  for (const inner of rest.matchAll(/:is\(([^)]*)\)/g)) {
    const best = inner[1].split(",").map((s) => specificity(s.trim())).sort((x, y) =>
      y[0] - x[0] || y[1] - x[1] || y[2] - x[2])[0];
    a += best[0]; b += best[1]; c += best[2];
  }
  rest = rest.replace(/:is\([^)]*\)/g, " ");
  a += (rest.match(/#[\w-]+/g) ?? []).length;
  b += (rest.match(/\.[\w-]+/g) ?? []).length;
  b += (rest.match(/\[[^\]]+\]/g) ?? []).length;
  b += (rest.match(/:(?!:)[\w-]+(?:\([^)]*\))?/g) ?? []).length;
  c += (rest.match(/(?:^|[\s>+~])([a-z][\w-]*)/g) ?? []).length;
  return [a, b, c];
}

const rank = (s: string) => { const [a, b, c] = specificity(s); return a * 10000 + b * 100 + c; };

describe("the board row's focus treatment", () => {
  const scopeRing = "[tabindex]:focus-visible";

  it("the app really does carry a generic ring a row cannot simply out-specify", () => {
    // If this stops being true the override below is dead weight, not a fix.
    expect(shell).toContain(`${scopeRing} {`);
    expect(rank(scopeRing)).toBeGreaterThanOrEqual(rank(".job-row:focus-visible"));
  });

  it("the row's own rule outranks it, so the row wears one treatment and not two", () => {
    const winner = "[data-design-system=\"app\"] .job-row.job-row:focus-visible";
    expect(board).toContain(winner);
    expect(rank(winner)).toBeGreaterThan(rank(scopeRing));

    // ...and what it declares is the app's one ring drawn INSIDE the row,
    // never a gold left edge: that edge is the mark of a row picked for
    // Compare.
    const at = board.indexOf(winner);
    const body = board.slice(board.indexOf("{", at) + 1, board.indexOf("}", at));
    expect(body).toMatch(/outline:\s*var\(--app-ring-width\) solid var\(--app-action\)/);
    expect(body).toMatch(/outline-offset:\s*calc\(-1 \* var\(--app-ring-offset\)\)/);
    expect(body).not.toMatch(/box-shadow/);
  });
});
