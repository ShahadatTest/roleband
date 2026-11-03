import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { ParsedQuery } from "../../api";
import { SearchInterpretation } from "./SearchInterpretation";

const emptyParsed: ParsedQuery = {
  company: [],
  level_band: [],
  family: [],
  workplace_type: [],
  location_group: [],
  comp_min: null,
  comp_max: null,
  remainder: "",
};

describe("SearchInterpretation", () => {
  it("renders a chip per recognized structured filter", () => {
    const parsed: ParsedQuery = {
      ...emptyParsed,
      company: ["openai"],
      level_band: ["staff"],
      family: ["product_management"],
      comp_min: 400000,
      remainder: "pm",
    };
    render(<SearchInterpretation parsed={parsed} />);

    expect(screen.getByText("Interpreted as")).toBeInTheDocument();
    expect(screen.getByText("OpenAI")).toBeInTheDocument();
    expect(screen.getByText("Staff")).toBeInTheDocument();
    expect(screen.getByText("Product Management")).toBeInTheDocument();
    // comp_min only → "+" suffix, not a range.
    expect(screen.getByText("$400K+")).toBeInTheDocument();
  });

  it("renders a min–max range chip when both comp bounds are parsed", () => {
    const parsed: ParsedQuery = { ...emptyParsed, comp_min: 300000, comp_max: 500000 };
    render(<SearchInterpretation parsed={parsed} />);
    expect(screen.getByText("$300K–$500K")).toBeInTheDocument();
  });

  it("names the money a query states as Base, the column it bounds, spelled out on hover", () => {
    const parsed: ParsedQuery = { ...emptyParsed, comp_min: 400000 };
    render(<SearchInterpretation parsed={parsed} />);
    const short = screen.getByText("Base");
    expect(short.closest("abbr")).toHaveAttribute("title", "Base salary");
    expect(screen.getByText("Base salary")).toHaveClass("sr-only");
  });

  it("shows nothing for a plain keyword query with no structured filters", () => {
    const parsed: ParsedQuery = { ...emptyParsed, remainder: "kubernetes" };
    const { container } = render(<SearchInterpretation parsed={parsed} />);
    expect(container).toBeEmptyDOMElement();
    expect(screen.queryByText("Interpreted as")).not.toBeInTheDocument();
  });

  it("shows nothing when no query was parsed (legacy path)", () => {
    const { container } = render(<SearchInterpretation parsed={null} />);
    expect(container).toBeEmptyDOMElement();
  });
});
