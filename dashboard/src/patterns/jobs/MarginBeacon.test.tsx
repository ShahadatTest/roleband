import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { jobFixture } from "../../test/fixtures";
import { RevealRole } from "./MarginBeacon";

/* The reveal row's comp and its qualifier (the grammar: the comp LAST,
 * qualified, because a bare numeral beside a title reads as a salary). Both
 * beacons render this row; the dismiss beacon renders it from a LIST row,
 * which carries the estimate and the `discloses_pay` flag but no posted band.
 * The qualifier must describe the number it sits beside, and that number is
 * always the app's estimate. */

const estimate = {
  comp_low: 1098952,
  comp_high: 1486817,
  comp_median: 1292885,
  comp_provenance: "Openai L6 reported median (software_engineering)",
};

const compOf = (container: HTMLElement) => container.querySelector(".job-reveal-comp");

describe("RevealRole's comp", () => {
  it("is called an estimate on a posting that discloses pay, because the range is still the lookup", () => {
    const { container } = render(<RevealRole job={{ ...jobFixture, ...estimate, discloses_pay: true }} />);
    expect(compOf(container)).toHaveTextContent(/^est\. \$1\.10M–\$1\.49M$/);
    expect(container).not.toHaveTextContent(/disclosed/i);
  });

  it("is called an estimate on a posting that does not", () => {
    const { container } = render(<RevealRole job={{ ...jobFixture, ...estimate, discloses_pay: false }} />);
    expect(compOf(container)).toHaveTextContent(/^est\. \$1\.10M–\$1\.49M$/);
  });

  it("leaves the line, qualifier and all, when there is no number", () => {
    const { container } = render(
      <RevealRole job={{ ...jobFixture, comp_low: null, comp_high: null, comp_median: null,
        comp_base_low: null, comp_base_median: null, comp_base_high: null, discloses_pay: true }} />,
    );
    expect(compOf(container)).toBeNull();
    expect(container).not.toHaveTextContent(/est\.|disclosed/);
  });
});
