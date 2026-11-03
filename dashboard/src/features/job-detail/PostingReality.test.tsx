import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { JobDetail } from "../../api";
import { PostingReality } from "./PostingReality";

type Reality = NonNullable<JobDetail["posting_reality"]>;

const reality = (over: Partial<Reality> = {}): Reality => ({
  level: "possible",
  met: ["long_open", "relisted"],
  criteria_total: 3,
  listings: 3,
  ...over,
});

describe("PostingReality", () => {
  it("names each sign that fired, and how many of how many", () => {
    render(<PostingReality reality={reality()} />);
    const region = screen.getByRole("region", { name: "May be an always-open posting" });
    // The figure lives in Details; repeating it here would show two ages
    // side by side.
    expect(region).toHaveTextContent("Listed for a long time");
    expect(region).not.toHaveTextContent("150");
    expect(region).toHaveTextContent("Listed 3 times");
    expect(region).not.toHaveTextContent("date moved");
    expect(region).toHaveTextContent("2 of 3 signs");
    expect(region).toHaveTextContent("not a verdict on the company");
  });

  it("words the re-dating sign as what was observed", () => {
    render(<PostingReality reality={reality({ met: ["relisted", "redated"] })} />);
    expect(screen.getByRole("region", { name: "May be an always-open posting" })).toHaveTextContent(
      "Its date moved later while it stayed listed",
    );
  });

  it("says nothing below two signs or for a closed posting", () => {
    const { container, rerender } = render(<PostingReality reality={reality({ level: "none", met: ["long_open"] })} />);
    expect(container).toBeEmptyDOMElement();
    rerender(<PostingReality reality={null} />);
    expect(container).toBeEmptyDOMElement();
  });
});
