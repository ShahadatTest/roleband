import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { Button } from "./Button";

/* Contracts for THE app button (docs/ui.md). Two halves: what the
 * component emits, and what the stylesheet promises about it. The second half
 * exists because hand-rolled buttons omit states, and a variant that forgets
 * one here would just move the problem into the thing meant to end it.
 */

const css = readFileSync(
  join(dirname(fileURLToPath(import.meta.url)), "Button.css"),
  "utf8",
).replace(/\/\*[\s\S]*?\*\//g, "");

const VARIANTS = ["primary", "ghost", "icon", "link", "danger"] as const;

describe("Button", () => {
  it("defaults to the ghost rank at md — the safe choice when nobody chose", () => {
    render(<Button>Cancel</Button>);
    const el = screen.getByRole("button", { name: "Cancel" });
    expect(el.className).toContain("ui-btn-ghost");
    expect(el.className).toContain("ui-btn-md");
  });

  it("defaults type to button, so a button inside a form cannot submit it", () => {
    // The default <button> type is "submit". Every hand-rolled button in the
    // app had to remember type="button"; this one cannot forget.
    render(<Button>Save draft</Button>);
    expect(screen.getByRole("button", { name: "Save draft" })).toHaveAttribute("type", "button");
  });

  it("still allows an explicit submit button", () => {
    render(<Button type="submit">Submit</Button>);
    expect(screen.getByRole("button", { name: "Submit" })).toHaveAttribute("type", "submit");
  });

  it.each(VARIANTS)("emits the %s variant class", (variant) => {
    render(<Button variant={variant}>Act</Button>);
    expect(screen.getByRole("button", { name: "Act" }).className).toContain(`ui-btn-${variant}`);
  });

  it("gives link no size class — it is text, and inherits its line", () => {
    render(<Button variant="link" size="lg">Retry</Button>);
    const el = screen.getByRole("button", { name: "Retry" });
    expect(el.className).toContain("ui-btn-link");
    expect(el.className).not.toMatch(/ui-btn-(sm|md|lg)/);
  });

  it("carries the caller's className without dropping its own", () => {
    render(<Button className="prof-thing">Act</Button>);
    const el = screen.getByRole("button", { name: "Act" });
    expect(el.className).toContain("ui-btn-ghost");
    expect(el.className).toContain("prof-thing");
  });

  it("forwards disabled and does not fire while disabled", () => {
    const onClick = vi.fn();
    render(<Button disabled onClick={onClick}>Act</Button>);
    const el = screen.getByRole("button", { name: "Act" });
    expect(el).toBeDisabled();
    fireEvent.click(el);
    expect(onClick).not.toHaveBeenCalled();
  });
});

describe("Button stylesheet contracts", () => {
  const block = (selector: string) => {
    const m = css.match(
      new RegExp(`${selector.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}[^{}]*\\{([^}]*)\\}`),
    );
    return m ? m[1] : "";
  };

  it.each(VARIANTS)("%s declares a hover and a pressed state", (variant) => {
    // Every variant declares :active; a missing pressed state is the common gap.
    expect(css).toMatch(new RegExp(`\\.ui-btn-${variant}[^{]*:hover`));
    expect(css).toMatch(new RegExp(`\\.ui-btn-${variant}[^{]*:active|\\.ui-btn-${variant}\\[aria-pressed`));
  });

  it("owns its focus ring rather than inheriting the legacy one", () => {
    // shell.css paints a global ring on every focusable element, sized and
    // offset without knowing what it is drawing around. A primitive usable
    // anywhere has to state its own.
    expect(block(".ui-btn:focus-visible")).toMatch(/outline:\s*var\(--app-ring-width\) solid var\(--app-action\)/);
  });

  it("states a disabled treatment for every rank", () => {
    expect(block(".ui-btn:disabled")).toMatch(/opacity/);
    // link cannot use opacity alone — an underlined ghost of a verb still
    // reads as a link, so it drops the underline and goes faint.
    expect(block(".ui-btn-link:disabled")).toMatch(/--app-text-faint/);
  });

  it("sizes only from the control scale — no literal geometry", () => {
    for (const size of ["sm", "md", "lg"]) {
      expect(block(`.ui-btn-${size}`)).toMatch(
        new RegExp(`min-height:\\s*var\\(--app-control-${size}\\)`),
      );
    }
    expect(css).not.toMatch(/min-height:\s*\d+px/);
    expect(css).not.toMatch(/font-size:\s*\d+px/);
    expect(css).not.toMatch(/padding:\s*0 \d+px/);
  });

  it("keeps the icon rank square in a flex row, not just on paper", () => {
    // An icon button's home is an action row, so its parent is nearly always
    // flex — and `width` there is a hint a flex parent may shrink.
    for (const size of ["sm", "md", "lg"]) {
      const rule = block(`.ui-btn-icon.ui-btn-${size}`);
      expect(rule).toMatch(new RegExp(`width:\\s*var\\(--app-control-${size}\\)`));
      expect(rule).toMatch(/flex:\s*none/);
    }
  });

  it("consumes only the promoted vocabulary", () => {
    const consumed = [...css.matchAll(/var\((--[\w-]+)/g)].map((m) => m[1]);
    expect(consumed.length).toBeGreaterThan(10);
    expect(consumed.filter((t) => !t.startsWith("--app-"))).toEqual([]);
  });

  it("keeps ONE convention for a control that is currently on", () => {
    // The ARIA state carries "on", never a state class.
    expect(css).toMatch(/\.ui-btn-icon\[aria-expanded="true"\]/);
    expect(css).toMatch(/\.ui-btn-icon\[aria-pressed="true"\]/);
    expect(css).not.toMatch(/\.ui-btn[\w-]*\.is-on\b/);
  });
});
