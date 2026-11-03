import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Abbr } from "./Abbr";

describe("Abbr", () => {
  it("shows the short form, gives the full words on hover, and speaks only the full words", () => {
    render(<table><thead><tr><th><Abbr short="TC" full="Total compensation" /></th></tr></thead></table>);
    const head = screen.getByRole("columnheader");
    expect(head).toHaveAccessibleName("Total compensation");
    expect(head.querySelector("abbr")).toHaveAttribute("title", "Total compensation");
    expect(head.querySelector('[aria-hidden="true"]')).toHaveTextContent(/^TC$/);
    expect(head).not.toHaveAccessibleName(/TC/);
  });
});
