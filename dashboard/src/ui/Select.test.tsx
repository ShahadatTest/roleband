import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { Select } from "./Select";

/* ui/Select. The behaviour half: the pointer mark's lifecycle,
 * which is what decides whether the focus ring paints. The sheet half: the
 * ring rule must exclude the mark, and the text inset and the chevron inset
 * must be one token. jsdom cannot evaluate :focus-visible, so the two halves
 * together are the contract; Playwright measures the painted result.
 */

const OPTIONS = [
  { value: "relevance", label: "Best match" },
  { value: "first_seen", label: "Newest" },
] as const;

const sheet = readFileSync(join(dirname(fileURLToPath(import.meta.url)), "Select.css"), "utf8")
  .replace(/\/\*[\s\S]*?\*\//g, "");

describe("ui/Select", () => {
  it("is a labelled native select that emits the chosen value", async () => {
    const onChange = vi.fn();
    render(<Select label="Sort by" value="relevance" onChange={onChange} options={OPTIONS} />);
    const select = screen.getByRole("combobox", { name: "Sort by" });
    await userEvent.selectOptions(select, "first_seen");
    expect(onChange).toHaveBeenCalledWith("first_seen");
  });

  it("marks pointer focus, and a key press or a blur clears the mark", async () => {
    render(<Select label="Sort by" value="relevance" onChange={() => {}} options={OPTIONS} />);
    const select = screen.getByRole("combobox", { name: "Sort by" });
    expect(select).not.toHaveAttribute("data-pointer");

    fireEvent.pointerDown(select);
    expect(select).toHaveAttribute("data-pointer");
    // Escape dismisses the popup the pointer opened — the mark must survive
    // it, or the ring appears the instant a click-and-leave ends.
    fireEvent.keyDown(select, { key: "Escape" });
    expect(select).toHaveAttribute("data-pointer");
    fireEvent.keyDown(select, { key: "ArrowDown" });
    expect(select).not.toHaveAttribute("data-pointer");

    // A blur that moves focus ends pointer mode...
    fireEvent.pointerDown(select);
    select.focus();
    expect(select).toHaveAttribute("data-pointer");
    const elsewhere = document.createElement("button");
    document.body.appendChild(elsewhere);
    elsewhere.focus(); // fires blur on the select, and focus really moved
    await new Promise((r) => setTimeout(r, 0));
    expect(document.activeElement).toBe(elsewhere);
    expect(select).not.toHaveAttribute("data-pointer");
    elsewhere.remove();
  });

  it("keeps the mark through the popup's own blur (macOS Chrome: the popup is a window)", async () => {
    render(<Select label="Sort by" value="relevance" onChange={() => {}} options={OPTIONS} />);
    const select = screen.getByRole("combobox", { name: "Sort by" });
    fireEvent.pointerDown(select);
    select.focus();
    // The popup opening blurs the element while it stays activeElement.
    fireEvent.blur(select);
    await new Promise((r) => setTimeout(r, 0));
    expect(document.activeElement).toBe(select);
    expect(select).toHaveAttribute("data-pointer");
    fireEvent.focus(select); // the popup closing
    expect(select).toHaveAttribute("data-pointer");
  });

  it("the sheet rings keyboard focus only, and insets text and chevron by one token", () => {
    const ring = sheet.match(/\.ui-select > select:focus-visible:not\(\[data-pointer\]\) \{([^}]*)\}/);
    expect(ring, "ring rule excludes pointer focus").not.toBeNull();
    expect(ring![1]).toMatch(/outline:\s*var\(--app-ring-width\) solid var\(--app-action\)/);
    expect(ring![1]).not.toMatch(/box-shadow/);
    expect(sheet).not.toMatch(/select:focus-visible \{/);

    const box = sheet.match(/\.ui-select > select \{([^}]*)\}/)![1];
    expect(box).toMatch(/appearance:\s*none/);
    expect(box).toMatch(/padding:\s*0 calc\(var\(--app-control-md-pad\) \* 2 \+ 14px\) 0 var\(--app-control-md-pad\)/);
    const glyph = sheet.match(/\.ui-select > svg \{([^}]*)\}/)![1];
    // + the select's 1px border: the text is measured from inside it, the
    // glyph from the wrapper's edge.
    expect(glyph).toMatch(/right:\s*calc\(var\(--app-control-md-pad\) \+ 1px\)/);
    expect(glyph).toMatch(/pointer-events:\s*none/);
  });
});
