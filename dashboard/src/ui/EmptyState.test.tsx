import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { EmptyState } from "./EmptyState";

/* The variant split exists because the primitive's page furniture — an 88px
 * radar, a dashed frame, a centred `--app-type-name` heading — is sized for a
 * screen's whole content column. An empty can sit INSIDE a furnished
 * container (a register body under its own column head, a 260px selector
 * rail), where that card is a regression rather than a fix. */
describe("EmptyState", () => {
  it("gives the page variant the radar motif, and hides it from assistive tech", () => {
    const { container } = render(<EmptyState title="No saved roles yet" />);

    expect(screen.getByText("No saved roles yet")).toBeInTheDocument();
    const art = container.querySelector(".empty-art");
    expect(art).toHaveAttribute("aria-hidden", "true");
    expect(art?.querySelectorAll(".ring")).toHaveLength(3);
  });

  it("drops the motif and the frame for the inline variant", () => {
    const { container } = render(<EmptyState variant="inline" title="Nothing needs review." />);

    expect(screen.getByText("Nothing needs review.")).toBeInTheDocument();
    expect(container.querySelector(".empty-art")).toBeNull();
    expect(container.querySelector(".empty")).toBeNull();
    expect(container.querySelector(".ui-empty-inline")).not.toBeNull();
  });

  it("renders the way out in every variant — an empty state without one is the bug", () => {
    for (const variant of ["page", "inline", "preview"] as const) {
      const { unmount } = render(
        <EmptyState variant={variant} title="Nothing here">
          <button type="button">Show all companies</button>
        </EmptyState>,
      );
      expect(screen.getByRole("button", { name: "Show all companies" })).toBeInTheDocument();
      unmount();
    }
  });

  it("omits the body entirely when there is nothing to say", () => {
    const { container } = render(<EmptyState variant="inline" title="Nothing here" />);
    expect(container.querySelector(".ui-empty-inline-body")).toBeNull();
  });

  describe("preview", () => {
    it("draws a chart ghost that assistive tech skips and that carries no readable value", () => {
      const { container } = render(
        <EmptyState
          variant="preview"
          title="No stock prices yet"
          actions={<a href="/settings/plugins">Add your key</a>}
        >
          Stock prices come from the price feed.
        </EmptyState>,
      );

      const ghost = container.querySelector(".ui-empty-ghost-chart");
      expect(ghost).toHaveAttribute("aria-hidden", "true");
      // A picture of a chart, never its numbers: no axis label or price is text.
      expect(ghost?.textContent).toBe("");
      expect(ghost?.querySelector("text")).toBeNull();
      expect(container.querySelector(".ui-empty-ghost-rows")).toBeNull();
      // The copy and the way out stay outside the hidden ghost.
      expect(screen.getByText("No stock prices yet")).toBeVisible();
      expect(screen.getByRole("link", { name: "Add your key" })).toHaveAttribute("href", "/settings/plugins");
      expect(ghost?.contains(screen.getByRole("link", { name: "Add your key" }))).toBe(false);
    });

    it("gives each chart ghost on a page its own fill, so neither borrows the other's gradient", () => {
      const { container } = render(
        <>
          <EmptyState variant="preview" title="No pay-transparency history yet." />
          <EmptyState variant="preview" title="No posted base salary range recorded yet." />
        </>,
      );

      const gradients = [...container.querySelectorAll(".ui-empty-ghost-chart linearGradient")];
      expect(gradients).toHaveLength(2);
      const ids = gradients.map((gradient) => gradient.id);
      expect(new Set(ids).size).toBe(2);
      container.querySelectorAll(".ui-empty-ghost-chart").forEach((ghost, index) => {
        expect(ghost.querySelector("path[fill]")).toHaveAttribute("fill", `url(#${ids[index]})`);
      });
    });

    it("draws table rows instead of a chart for the rows art", () => {
      const { container } = render(<EmptyState variant="preview" art="rows" title="No comp bands yet" />);

      expect(container.querySelector(".ui-empty-ghost-rows")).toHaveAttribute("aria-hidden", "true");
      expect(container.querySelector(".ui-empty-ghost-chart")).toBeNull();
    });
  });
});
