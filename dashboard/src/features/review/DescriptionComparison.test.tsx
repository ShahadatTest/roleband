import { render, screen } from "@testing-library/react";
import { expect, it } from "vitest";
import { jobFixture } from "../../test/fixtures";
import { DescriptionComparison } from "./DescriptionComparison";

const posting = (content: string) => ({
  ...jobFixture,
  description_sections: [{ key: "basic_qualifications", title: "Basic qualifications", content }],
});

it("counts differing passages with a verb that agrees", () => {
  // One line only the earlier posting has: one differing passage, and the
  // verb agrees with a count of one ("1 passage differs").
  const { rerender } = render(
    <DescriptionComparison prior={posting("- Shared requirement\n- 5+ years in security")} job={posting("- Shared requirement")} />,
  );
  const region = screen.getByRole("region", { name: "Description comparison" });
  expect(region).toHaveTextContent("1 passage differs.");

  rerender(
    <DescriptionComparison
      prior={posting("- Shared requirement\n- 5+ years in security")}
      job={posting("- Shared requirement\n- Experience with compliance")}
    />,
  );
  expect(region).toHaveTextContent("2 passages differ.");
});

it("shows the employer's passages as theirs, marked as text RoleBand did not write", () => {
  render(<DescriptionComparison prior={posting("- Shared requirement\n- 5+ years in security")} job={posting("- Shared requirement")} />);
  for (const text of [/Shared requirement/, /5\+ years in security/]) {
    for (const passage of screen.getAllByText(text)) {
      expect(passage).toHaveAttribute("data-copy", "content");
      expect(passage).toHaveAttribute("translate", "no");
    }
  }
});
