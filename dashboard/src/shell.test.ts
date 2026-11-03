import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

/* The INK pairs in shell.css: a token painted as text ON a filled
 * accent/danger surface, where the ground is the token rather than the
 * canvas. Dark theme turns the danger fill LIGHT, so a literal white ink on it
 * fails contrast.
 *
 * design/tokens.test.ts measures the promoted pairs (--app-action-ink on
 * --app-action, --app-danger-ink on --app-danger, in all three theme scopes).
 * What tokens.test does NOT cover is the other half, which is not about a
 * ratio: the RULE has to keep consuming the ink token instead of reintroducing
 * a literal. That is a fact about shell.css, so it lives here.
 */

function block(source: string, selectorStart: string): string {
  const at = source.indexOf(selectorStart);
  if (at === -1) throw new Error(`selector not found: ${selectorStart}`);
  const open = source.indexOf("{", at);
  const close = source.indexOf("}", open);
  return source.slice(open + 1, close);
}

describe("filled badges consume the ink token", () => {
  // A filled badge in the header furniture paints small bold text on a
  // filled pill, so it may not reintroduce a literal foreground (the
  // token-pair ratios are gated in design/tokens.test.ts).
  const shellCss = readFileSync(
    join(dirname(fileURLToPath(import.meta.url)), "shell.css"),
    "utf8",
  );
  it.each([
    [".bell-badge", "--app-danger-ink"],
  ])("%s paints var(%s)", (selector, ink) => {
    const rule = block(shellCss, `${selector} {`);
    expect(rule).toContain(`color: var(${ink})`);
    expect(rule).not.toMatch(/color:\s*#[0-9a-f]{3,8}/i);
  });
});
