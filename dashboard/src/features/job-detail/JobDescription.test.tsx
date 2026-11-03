import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { JobDescription } from "./JobDescription";

describe("JobDescription", () => {
  it("renders source sections, qualifications as lists, and pay as its own region", () => {
    render(
      <JobDescription
        sections={[
          { key: "summary", title: "Summary", content: "Lead the platform." },
          {
            key: "minimum_qualifications",
            title: "Minimum Qualifications",
            content: "10+ years in product\nExperience with AI systems",
          },
          {
            key: "pay_and_benefits",
            title: "Pay & Benefits",
            content: "Base pay range: $250,800 to $376,300 per year.",
          },
        ]}
      />,
    );

    expect(screen.getByRole("heading", { name: "Summary" })).toBeVisible();
    const qualifications = screen.getByRole("heading", { name: "Minimum Qualifications" })
      .closest("section")!;
    expect(within(qualifications).getAllByRole("listitem")).toHaveLength(2);
    expect(screen.getByText(/\$250,800 to \$376,300/)).toBeVisible();
    expect(screen.getByRole("heading", { name: "Pay & Benefits" }).closest("section"))
      .toHaveClass("jd-section-pay_and_benefits");
  });

  it("falls back to legacy plain text when sections are absent", () => {
    render(<JobDescription fallback="Legacy complete description." />);
    expect(screen.getByText("Legacy complete description.")).toBeVisible();
  });
});
