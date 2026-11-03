import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { IntelligenceFit } from "../../api";
import { msg } from "../../test/msg";
import { intelligenceFitFixture } from "../../test/fixtures";
import { FitField } from "./FitField";
import { fitBandName } from "./serverText";

// The field draws each band at the lower edge the server cut its count at.
// Edges unlike the shipped ones (.70, .40, .30) make a copy of the old
// constants visible: their lines would sit in another proportion.
const moved: IntelligenceFit = {
  ...intelligenceFitFixture,
  bins: [
    { fit: 0.1, count: 3 },
    { fit: 0.36, count: 40 },
    { fit: 0.5, count: 25 },
    { fit: 0.72, count: 4 },
  ],
  bands: [
    { key: "strong", count: 4, lower_edge: 0.7 },
    { key: "good", count: 25, lower_edge: 0.4 },
    { key: "some", count: 40, lower_edge: 0.3 },
    { key: "weak", count: 3, lower_edge: null },
  ],
};

function draw(fit: IntelligenceFit) {
  const { container } = render(<FitField fit={fit} topCount={3} selected={null} onSelect={vi.fn()} />);
  const lines = [...container.querySelectorAll("line.fit-grid")].map((line) => Number(line.getAttribute("y1")));
  const zones = [...container.querySelectorAll("rect.fit-band-zone")].map((rect) => ({
    top: Number(rect.getAttribute("y")) - 1,
    bottom: Number(rect.getAttribute("y")) + Number(rect.getAttribute("height")) + 1,
  }));
  // The silhouette's left side, one point per bin, lowest fit first.
  const cx = Number(container.querySelector("path.fit-shape")?.getAttribute("d")?.match(/^M([\d.]+),/)?.[1]);
  const left = [...(container.querySelector("path.fit-shape")?.getAttribute("d") ?? "").matchAll(/L([\d.]+),([\d.]+)/g)]
    .map((m) => ({ x: Number(m[1]), y: Number(m[2]) }))
    .filter((point) => point.x < cx);
  return { lines, zones, left };
}

describe("FitField", () => {
  it("draws a line at each band's lower edge, in the payload's proportions", () => {
    const { lines } = draw(moved);
    // Weak is open below: three edges, three lines, highest fit at the top.
    expect(lines).toHaveLength(3);
    expect(lines[0]).toBeLessThan(lines[1]);
    expect(lines[1]).toBeLessThan(lines[2]);
    // Fit maps to height linearly, so the gaps keep the edges' ratio:
    // (.70 - .40) / (.40 - .30) = 3.
    expect((lines[1] - lines[0]) / (lines[2] - lines[1])).toBeCloseTo(3, 6);
  });

  it("spans each band between its own edge and the one above", () => {
    const { lines, zones } = draw(moved);
    expect(zones).toHaveLength(4);
    expect(zones[0].bottom).toBeCloseTo(lines[0], 6);
    expect(zones[1].top).toBeCloseTo(lines[0], 6);
    expect(zones[1].bottom).toBeCloseTo(lines[1], 6);
    expect(zones[2].top).toBeCloseTo(lines[1], 6);
    expect(zones[2].bottom).toBeCloseTo(lines[2], 6);
    expect(zones[3].top).toBeCloseTo(lines[2], 6);
    // Good spans .70 to .40 and some .40 to .30: three times the height.
    const height = (i: number) => zones[i].bottom - zones[i].top;
    expect(height(1) / height(2)).toBeCloseTo(3, 6);
    for (const band of moved.bands) {
      expect(
        screen.getByRole("button", { name: msg("ai-fit-field-roles", { label: fitBandName(band.key), count: String(band.count) }) }),
      ).toBeInTheDocument();
    }
  });

  it("draws each bin across the width the server binned it at", () => {
    // Bins .10 wide: the bin at .30 spans .30 to .40, so its point sits at .35,
    // a quarter of the way from the .30 line to the .50 one.
    const wide: IntelligenceFit = {
      ...moved,
      bin_width: 0.1,
      bins: [
        { fit: 0.3, count: 5 },
        { fit: 0.5, count: 5 },
      ],
      bands: [
        { key: "strong", count: 0, lower_edge: 0.7 },
        { key: "good", count: 5, lower_edge: 0.5 },
        { key: "some", count: 5, lower_edge: 0.3 },
        { key: "weak", count: 0, lower_edge: null },
      ],
    };
    const { lines, left } = draw(wide);
    expect(left).toHaveLength(2);
    expect((lines[2] - left[0].y) / (lines[2] - lines[1])).toBeCloseTo(0.25, 2);
    expect((lines[1] - left[1].y) / (lines[1] - lines[0])).toBeCloseTo(0.25, 2);
  });

  it("reaches past the outermost edges wherever the payload puts them", () => {
    // Every role sits below all three edges (.90, .80, .75): the field still
    // draws each line inside the frame, with strong and weak given a height.
    const high: IntelligenceFit = {
      ...moved,
      bins: [{ fit: 0.5, count: 72 }],
      bands: [
        { key: "strong", count: 0, lower_edge: 0.9 },
        { key: "good", count: 0, lower_edge: 0.8 },
        { key: "some", count: 0, lower_edge: 0.75 },
        { key: "weak", count: 72, lower_edge: null },
      ],
    };
    const { lines, zones } = draw(high);
    expect((lines[1] - lines[0]) / (lines[2] - lines[1])).toBeCloseTo(2, 6);
    for (const y of lines) {
      expect(y).toBeGreaterThan(0);
      expect(y).toBeLessThan(300);
    }
    expect(zones[0].bottom - zones[0].top).toBeGreaterThan(0);
    expect(zones[3].bottom - zones[3].top).toBeGreaterThan(0);
  });
});
