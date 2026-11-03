import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { SkillsOverlap } from "../../api";
import { api } from "../../api";
import { facetsFixture } from "../../test/fixtures";
import { companyPickerOptions } from "./companyPicker";
import { OverlapPanel } from "./OverlapPanel";

vi.mock("../../api", () => ({ api: { skillsOverlap: vi.fn() } }));

const mockOverlap = (data: SkillsOverlap) =>
  vi.mocked(api.skillsOverlap).mockResolvedValue(data);

describe("OverlapPanel", () => {
  beforeEach(() => vi.clearAllMocks());

  it("renders a similarity matrix with diagonal skill counts and shared-pair cells", async () => {
    mockOverlap({
      min_jobs: 2,
      companies: [
        { company: "google", skill_count: 40, open: 100 },
        { company: "openai", skill_count: 18, open: 50 },
      ],
      pairs: [
        {
          a: "google",
          b: "openai",
          shared: 12,
          union: 46,
          similarity: 0.26,
          top_shared: ["machine_learning", "distributed_systems"],
        },
      ],
    });

    render(<OverlapPanel />);

    expect(await screen.findByRole("img", { name: "Cross-company skill overlap heatmap" })).toBeInTheDocument();

    // Diagonal cells show each company's own distinct-skill count.
    expect(await screen.findByTitle("40 skills")).toHaveTextContent("40");
    expect(screen.getByTitle("18 skills")).toHaveTextContent("18");

    // Off-diagonal cell shows similarity ×100 and exposes shared skills on hover.
    const cell = screen.getByTitle(/Google and OpenAI: 26% alike, 12 of 46 skills shared/);
    expect(cell).toHaveTextContent("26");
    expect(cell.getAttribute("title")).toContain("Machine Learning");
  });

  it("leaves no-overlap cells blank rather than showing a zero", async () => {
    mockOverlap({
      min_jobs: 2,
      companies: [
        { company: "google", skill_count: 40, open: 100 },
        { company: "apple", skill_count: 21, open: 90 },
      ],
      pairs: [], // no shared skills between the two
    });

    render(<OverlapPanel />);

    const cell = await screen.findByTitle(/Google & Apple: no shared skills/);
    expect(cell.textContent).toBe("");
  });

  it("shows a not-enough-data message with fewer than two companies", async () => {
    mockOverlap({ min_jobs: 2, companies: [], pairs: [] });
    render(<OverlapPanel />);
    expect(await screen.findByText(/Not enough companies/i)).toBeInTheDocument();
  });

  it("compares the companies the reader picks, and keeps the picker when too few are left", async () => {
    // The matrix is not fixed to the ten with the most open roles.
    const user = (await import("@testing-library/user-event")).default.setup();
    mockOverlap({ min_jobs: 2, companies: [{ company: "google", skill_count: 9, open: 12 }], pairs: [] });
    render(<OverlapPanel companies={companyPickerOptions(facetsFixture, "all", null)} />);
    expect(await screen.findByText(/Pick two or more/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /^Filter by/ }));
    await user.click(await screen.findByRole("option", { name: /OpenAI/ }));
    await vi.waitFor(() =>
      expect(api.skillsOverlap).toHaveBeenLastCalledWith(2, 12, expect.anything(), undefined, ["openai"]),
    );
  });
});
