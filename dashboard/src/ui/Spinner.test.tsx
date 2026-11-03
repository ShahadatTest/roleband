import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Spinner } from "./Spinner";

describe("Spinner", () => {
  it("announces what is loading rather than being a silent decoration", () => {
    render(<Spinner label="Open roles loading" />);

    const spinner = screen.getByRole("status", { name: "Open roles loading" });
    expect(spinner).toHaveClass("ui-spinner");
    // Nothing to read visually — the label is the whole accessible content.
    expect(spinner).toBeEmptyDOMElement();
  });

  it("carries the size and caller class without dropping the base class", () => {
    render(<Spinner label="Saving" size="sm" className="in-cell" />);

    const spinner = screen.getByRole("status", { name: "Saving" });
    expect(spinner).toHaveClass("ui-spinner", "sm", "in-cell");
  });

  it("defaults to the medium size", () => {
    render(<Spinner label="Working" />);

    expect(screen.getByRole("status", { name: "Working" })).not.toHaveClass("sm");
  });
});
