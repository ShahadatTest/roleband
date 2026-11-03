import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../../api";
import { facetsFixture } from "../../test/fixtures";
import { companyPickerOptions } from "./companyPicker";
import { SkillsView } from "./SkillsView";

vi.mock("../../api", async () => {
  const actual = await vi.importActual<typeof import("../../api")>("../../api");
  return { ...actual, api: { ...actual.api, skillsTop: vi.fn() } };
});

/** The picker's options as the Insights screen hands them down. */
const companies = companyPickerOptions(facetsFixture, "all", null);


/* A skill by its catalog slug; the view names it ("cuda" reads "CUDA / GPU"). */
const skill = (term: string, job_count: number, category = "language", share = 0.2, market_share = 0.1) => ({
  term,
  category,
  job_count,
  share,
  market_share,
  lift: Math.round((share / market_share) * 100) / 100,
  distinctiveness: 2,
});

/** `/api/skills/top` as the route answers. */
const response = (items: ReturnType<typeof skill>[], over: Record<string, unknown> = {}) => ({
  items, competencies: [], roles: 50, market_roles: 3000, narrowed: true, ...over,
});

beforeEach(() => {
  vi.clearAllMocks();
});

describe("SkillsView", () => {
  it("shows the skills for the company that was asked for last, not the one that answered last", async () => {
    /* The failure this guards: a bare `.then(setSkills)` keyed on the two
       filters, with no cancellation and no generation. Pick a slow company,
       then a fast one, and the slow response lands LAST and paints its skills
       under the new heading: both responses valid, nothing logged, the reader
       simply reading the wrong company's data.

       Resolution order here is deliberately inverted against request order; a
       hand-rolled `.then` cannot pass this test. */
    const deferred: ((items: unknown) => void)[] = [];
    vi.mocked(api.skillsTop).mockImplementation(
      (q) =>
        new Promise((resolve) => {
          /* Three DISTINCT answers, one per request. If two requests shared
             an answer, the assertion below could hold even against the broken
             implementation. Every request answers differently, so only the
             newest winning can satisfy it. */
          const company = q?.company?.[0];
          const items =
            company === "openai"
              ? [skill("STALE-openai", 90)]
              : company === "amazon"
                ? [skill("amazon-only-skill", 10)]
                : [skill("STALE-unfiltered", 50)];
          deferred.push(() => resolve(response(items)));
        }),
    );

    const user = userEvent.setup();
    render(<SkillsView companies={companies} />);

    // One searchable picker, never a chip per company: no company is
    // a button until the picker is opened.
    expect(screen.queryByRole("button", { name: "OpenAI" })).toBeNull();
    await user.click(await screen.findByRole("button", { name: /^Filter by/ }));
    await user.click(await screen.findByRole("option", { name: /OpenAI/ }));
    await user.click(screen.getByRole("button", { name: /^Filter by/ }));
    await user.click(await screen.findByRole("option", { name: /Amazon/ }));

    // Three requests are in flight (initial, google, nvidia). Answer them
    // BACKWARDS, so the newest resolves first and the stale google response is
    // the last thing the component sees.
    await waitFor(() => expect(deferred.length).toBeGreaterThanOrEqual(3));
    for (const resolveIt of [...deferred].reverse()) resolveIt(null);

    await screen.findByRole("row", { name: /amazon-only-skill/ });
    // The whole point: the late loser must not overwrite the winner.
    await new Promise((r) => setTimeout(r, 20));
    expect(screen.queryAllByText(/STALE-openai/)).toHaveLength(0);
    expect(screen.getByRole("row", { name: /amazon-only-skill/ })).toBeInTheDocument();
  });

  it("states a failed load and offers a way back, instead of a spinner that never resolves", async () => {
    vi.mocked(api.skillsTop).mockRejectedValue(new Error("skills exploded"));
    render(<SkillsView />);

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(/couldn't load/i);
    expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();
  });

  it("ranks the whole market by share and says how to see what sets roles apart", async () => {
    vi.mocked(api.skillsTop).mockResolvedValue(response(
      [skill("machine_learning", 634, "ml_ai", 0.2, 0.2), skill("python", 328, "language", 0.11, 0.11)],
      { narrowed: false, roles: 3099, market_roles: 3099, competencies: [skill("roadmap", 1435, "process", 0.46, 0.46)] },
    ));
    render(<SkillsView />);
    expect(await screen.findByRole("heading", { level: 2, name: "Machine Learning leads" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Skills, most named first" })).toBeInTheDocument();
    expect(screen.queryByRole("img", { name: "What sets these roles apart" })).toBeNull();
    expect(screen.getByText(/Pick a company, a discipline or a side/)).toBeInTheDocument();
    expect(screen.queryByRole("columnheader", { name: "Lift" })).toBeNull();
    // A competency is listed apart, never in the ranking.
    const expected = screen.getByRole("heading", { name: /Expected of the role/ }).closest(".panel") as HTMLElement;
    expect(expected).toHaveTextContent("Roadmapping 46%");
    expect(screen.getAllByRole("row").map((r) => r.textContent)).not.toContainEqual(expect.stringContaining("Roadmapping"));
  });

  it("leads a narrowed view with what sets it apart, against the market", async () => {
    vi.mocked(api.skillsTop).mockResolvedValue(response(
      [skill("cuda", 18, "ml_ai", 0.24, 0.0094), skill("cpp", 15, "language", 0.2, 0.031)],
      { roles: 75 },
    ));
    render(<SkillsView scope={{ side: "all", families: ["hardware_engineering"] }} />);
    expect(await screen.findByRole("heading", { level: 2, name: "CUDA / GPU sets these roles apart" })).toBeInTheDocument();
    expect(screen.getByText(/24% of these roles name it, against 1% of the market/)).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Lift" })).toBeInTheDocument();
    expect(screen.getByRole("row", { name: /CUDA \/ GPU/ })).toHaveTextContent("×26");
    expect(api.skillsTop).toHaveBeenCalledWith(
      { company: undefined, limit: 30 }, expect.anything(), { side: "all", families: ["hardware_engineering"] },
    );
  });
});
