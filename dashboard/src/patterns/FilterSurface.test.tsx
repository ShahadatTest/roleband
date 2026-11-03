import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it } from "vitest";
import { FilterSurface } from "./FilterSurface";

/* The FilterSurface contracts:
 * the same keyboard and modal behaviour for every register, and a folded
 * home that cannot outlive the rail. jsdom has no matchMedia, so the sheet
 * query reads false and the anchored arm is what renders. */

function Harness({ railMode = false, count = 0 }: { railMode?: boolean; count?: number }) {
  return (
    <div>
      <button>Before</button>
      <FilterSurface railMode={railMode} activeCount={count}>
        <button>First filter</button>
        <button>Last filter</button>
      </FilterSurface>
    </div>
  );
}

function Resizable() {
  const [rail, setRail] = useState(false);
  return (
    <div>
      <button onClick={() => setRail((v) => !v)}>Toggle rail</button>
      <FilterSurface railMode={rail} activeCount={0}>
        <button>A filter</button>
      </FilterSurface>
    </div>
  );
}

describe("patterns/FilterSurface", () => {
  it("wears the count on the opener and opens a labelled modal panel", async () => {
    render(<Harness count={3} />);
    const opener = screen.getByRole("button", { name: "Filters · 3" });
    expect(opener).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByRole("dialog")).toBeNull();
    await userEvent.click(opener);
    const panel = screen.getByRole("dialog", { name: "Filters" });
    expect(panel).toHaveAttribute("aria-modal", "true");
    expect(panel).toHaveClass("filter-pop");
    expect(opener).toHaveAttribute("aria-expanded", "true");
  });

  it("Escape closes it and focus returns to the opener", async () => {
    render(<Harness />);
    const opener = screen.getByRole("button", { name: "Filters" });
    await userEvent.click(opener);
    const panel = screen.getByRole("dialog", { name: "Filters" });
    expect(panel.contains(document.activeElement)).toBe(true);
    await userEvent.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(document.activeElement).toBe(opener);
  });

  it("the scrim closes it", async () => {
    render(<Harness />);
    await userEvent.click(screen.getByRole("button", { name: "Filters" }));
    await userEvent.click(screen.getByRole("button", { name: "Close Filters" }));
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("Tab cycles inside the panel instead of escaping to the page", async () => {
    render(<Harness />);
    await userEvent.click(screen.getByRole("button", { name: "Filters" }));
    const first = screen.getByRole("button", { name: "First filter" });
    const last = screen.getByRole("button", { name: "Last filter" });
    last.focus();
    await userEvent.tab();
    expect(document.activeElement).toBe(first);
    await userEvent.tab({ shift: true });
    expect(document.activeElement).toBe(last);
  });

  it("locks the page scroll while open and releases it on close", async () => {
    render(<Harness />);
    await userEvent.click(screen.getByRole("button", { name: "Filters" }));
    expect(document.body.style.overflow).toBe("hidden");
    await userEvent.keyboard("{Escape}");
    expect(document.body.style.overflow).not.toBe("hidden");
  });

  it("closes when the rail appears, and stays closed when the viewport folds again", async () => {
    render(<Resizable />);
    await userEvent.click(screen.getByRole("button", { name: "Filters" }));
    expect(screen.getByRole("dialog", { name: "Filters" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Toggle rail" }));
    // Rail mode: no opener, no panel — the register has its own column.
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(screen.queryByRole("button", { name: "Filters" })).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Toggle rail" }));
    // Folded again: the opener is back, and the panel did NOT reopen itself.
    expect(screen.getByRole("button", { name: "Filters" })).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByRole("dialog")).toBeNull();
  });
});
