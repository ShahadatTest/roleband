import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { createRef } from "react";
import { Kbd } from "./Kbd";
import { SearchField } from "./SearchField";

const css = readFileSync(
  join(dirname(fileURLToPath(import.meta.url)), "SearchField.css"),
  "utf8",
).replace(/\/\*[\s\S]*?\*\//g, "");

function block(selector: string): string {
  const i = css.indexOf(selector);
  expect(i, `${selector} is declared`).toBeGreaterThan(-1);
  return css.slice(i, css.indexOf("}", i));
}

describe("SearchField", () => {
  it("is a named searchbox whose value round-trips as a string", () => {
    const onChange = vi.fn();
    render(<SearchField label="Search companies" value="" onChange={onChange} placeholder="Find a company" />);
    const box = screen.getByRole("searchbox", { name: "Search companies" });
    expect(box).toHaveAttribute("placeholder", "Find a company");
    fireEvent.change(box, { target: { value: "amz" } });
    expect(onChange).toHaveBeenCalledWith("amz");
  });

  it("forwards its ref to the input, so a screen can focus it from a shortcut", () => {
    const ref = createRef<HTMLInputElement>();
    render(<SearchField ref={ref} label="Search opportunities" value="" onChange={() => {}} />);
    expect(ref.current).toBe(screen.getByRole("searchbox"));
  });

  it("keeps a trailing key hint out of the accessible name", () => {
    render(<SearchField label="Search opportunities" value="" onChange={() => {}} trailing={<Kbd>/</Kbd>} />);
    expect(screen.getByRole("searchbox", { name: "Search opportunities" })).toBeInTheDocument();
    expect(screen.getByText("/").closest(".ui-search-trailing")).toHaveAttribute("aria-hidden", "true");
  });

  it("defaults to md and takes sm / lg from the control scale", () => {
    const { rerender } = render(<SearchField label="s" value="" onChange={() => {}} />);
    expect(screen.getByRole("searchbox").closest("label")!.className).toContain("ui-search-md");
    rerender(<SearchField label="s" value="" onChange={() => {}} size="lg" />);
    expect(screen.getByRole("searchbox").closest("label")!.className).toContain("ui-search-lg");
  });

  describe("stylesheet contracts", () => {
    it("sizes every rank from the scale, never a literal height", () => {
      expect(block(".ui-search-sm {")).toMatch(/min-height:\s*var\(--app-control-sm\)/);
      expect(block(".ui-search-md {")).toMatch(/min-height:\s*var\(--app-control-md\)/);
      expect(block(".ui-search-lg {")).toMatch(/min-height:\s*var\(--app-control-lg\)/);
      for (const s of ["sm", "md", "lg"]) expect(block(`.ui-search-${s} {`)).not.toMatch(/\d+px/);
    });

    it("sets md type at the control rank's role — body, what Button md sets — never above the row it filters", () => {
      // At `name` the search box would outrank the job titles beneath it.
      const button = readFileSync(join(dirname(fileURLToPath(import.meta.url)), "Button.css"), "utf8");
      const buttonMd = button.slice(button.indexOf(".ui-btn-md {"));
      const buttonRole = buttonMd.slice(0, buttonMd.indexOf("}")).match(/font-size:\s*var\((--app-type-[a-z]+)\)/)![1];
      expect(buttonRole).toBe("--app-type-body");
      expect(block(".ui-search-md {")).toMatch(/font-size:\s*var\(--app-type-body\)/);
    });

    it("draws the app's one ring on the wrapper and silences the input's own", () => {
      expect(css).toContain(".ui-search:focus-within");
      expect(block(".ui-search:focus-within")).toMatch(/outline:\s*var\(--app-ring-width\) solid var\(--app-action\)/);
      expect(block(".ui-search:focus-within")).not.toMatch(/box-shadow/);
      expect(block(".ui-search-input {")).toMatch(/outline:\s*none/);
    });

    it("paints --app-* only", () => {
      const consumed = [...css.matchAll(/var\((--[a-z0-9-]+)/g)].map((m) => m[1]);
      expect(consumed.filter((t) => !t.startsWith("--app-"))).toEqual([]);
    });
  });
});
