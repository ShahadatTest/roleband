import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { Segmented } from "./Segmented";

/* Contracts for the segmented control, in the same two halves as Button's:
 * what the component emits, and what its stylesheet promises. The second
 * half is the point — a recipe written per screen forgets states. */

const css = readFileSync(
  join(dirname(fileURLToPath(import.meta.url)), "Segmented.css"),
  "utf8",
).replace(/\/\*[\s\S]*?\*\//g, "");

function block(selector: string): string {
  const i = css.indexOf(selector);
  expect(i, `${selector} is declared`).toBeGreaterThan(-1);
  return css.slice(i, css.indexOf("}", i));
}

const OPTIONS = [
  { value: "open", label: "Open" },
  { value: "closed", label: "Closed" },
  { value: "", label: "All" },
] as const;

describe("Segmented", () => {
  it("is a named group of buttons whose chosen one is announced by aria-pressed", () => {
    render(<Segmented label="Status" value="closed" onChange={() => {}} options={OPTIONS} />);
    const group = screen.getByRole("group", { name: "Status" });
    const buttons = screen.getAllByRole("button");
    expect(group).toContainElement(buttons[0]);
    expect(buttons.map((b) => b.getAttribute("aria-pressed"))).toEqual(["false", "true", "false"]);
    // No class carries the state: the paint keys off the attribute.
    for (const b of buttons) expect(b.className).not.toMatch(/\bon\b|active|selected/);
  });

  it("reports a new choice and stays silent on the current one", () => {
    const onChange = vi.fn();
    render(<Segmented label="Status" value="open" onChange={onChange} options={OPTIONS} />);
    fireEvent.click(screen.getByRole("button", { name: "Closed" }));
    expect(onChange).toHaveBeenCalledWith("closed");
    fireEvent.click(screen.getByRole("button", { name: "Open" }));
    expect(onChange).toHaveBeenCalledTimes(1);
  });

  it("renders type=button, so it cannot submit an enclosing form", () => {
    render(<Segmented label="Status" value="open" onChange={() => {}} options={OPTIONS} />);
    for (const b of screen.getAllByRole("button")) expect(b).toHaveAttribute("type", "button");
  });

  it("honours a disabled option", () => {
    const onChange = vi.fn();
    render(
      <Segmented
        label="Status"
        value="open"
        onChange={onChange}
        options={[...OPTIONS.slice(0, 2), { value: "", label: "All", disabled: true }]}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "All" }));
    expect(onChange).not.toHaveBeenCalled();
  });

  describe("stylesheet contracts", () => {
    it("takes the sm rank of the control scale, never a literal height", () => {
      const btn = block(".ui-seg-btn {");
      expect(btn).toMatch(/min-height:\s*var\(--app-control-sm\)/);
      expect(btn).toMatch(/padding:\s*0 var\(--app-control-sm-pad\)/);
      expect(btn).toMatch(/border-radius:\s*var\(--app-radius-sm\)/);
      expect(btn).toMatch(/font-size:\s*var\(--app-type-meta\)/);
      expect(btn).not.toMatch(/\d+px/);
    });

    it("speaks in the control voice, not a row name's", () => {
      // `--app-weight-ui` is the token whose stated job is "controls, tabs,
      // buttons — text you act on". `--app-weight-name` is a heavier voice
      // than four exclusive options need.
      expect(block(".ui-seg-btn {")).toMatch(/font-weight:\s*var\(--app-weight-ui\)/);
    });

    it("declares its whole state set", () => {
      for (const rule of [
        ".ui-seg-btn:not(:disabled):hover",
        ".ui-seg-btn:not(:disabled):active",
        ".ui-seg-btn:disabled",
        ".ui-seg-btn:focus-visible",
        '.ui-seg-btn[aria-pressed="true"]',
      ]) {
        expect(css, `declares ${rule}`).toContain(rule);
      }
    });

    it("keys the chosen state off the attribute, not a class", () => {
      expect(css).toContain('.ui-seg-btn[aria-pressed="true"]');
      expect(css).not.toMatch(/\.ui-seg-btn\.(on|active|selected)/);
    });

    it("paints --app-* only", () => {
      const consumed = [...css.matchAll(/var\((--[a-z0-9-]+)/g)].map((m) => m[1]);
      expect(consumed.filter((t) => !t.startsWith("--app-"))).toEqual([]);
    });
  });
});
