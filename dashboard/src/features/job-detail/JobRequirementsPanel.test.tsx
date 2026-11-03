import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { JobRequirements, JobSkill } from "../../api";
import { activate } from "../../copy/activate";
import { msg } from "../../test/msg";
import { JobRequirementsPanel } from "./JobRequirementsPanel";

/** A skill by the name its catalog slug reads as ("Python" is `python`):
 *  the panel names it from the catalog, so the name is not sent. */
function skill({ display, ...over }: Partial<JobSkill> & { concept_id: number; display: string }): JobSkill {
  return {
    slug: display.toLowerCase(),
    facet: "technology",
    category: "language",
    importance_band: "core",
    importance_score: 85,
    confidence: "high",
    modality: "required",
    proficiency: "unspecified",
    evidence: [
      {
        section_key: "minimum_qualifications",
        section_title: "Minimum Qualifications",
        quote: `Experience with ${display}.`,
        start_offset: 0,
        end_offset: 10,
        modality: "required",
      },
    ],
    ...over,
  };
}

function reqs(skills: JobSkill[], qualifications: JobRequirements["qualifications"] = []): JobRequirements {
  return { state: "ready", extractor_version: "2.0.0", skills, qualifications, required_years: null };
}

describe("JobRequirementsPanel", () => {
  it("renders nothing without a requirements payload (older API)", () => {
    const { container } = render(<JobRequirementsPanel requirements={undefined} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("shows pending state distinctly from empty", () => {
    render(
      <JobRequirementsPanel
        requirements={{ state: "pending", extractor_version: null, skills: [], qualifications: [], required_years: null }}
      />,
    );
    expect(screen.getByText(/analyzing requirements/i)).toBeInTheDocument();
  });

  it("empty ready state says no catalogued requirement found, not 'no skills needed'", () => {
    render(<JobRequirementsPanel requirements={reqs([])} />);
    expect(screen.getByText(/no explicit skill requirements found/i)).toBeInTheDocument();
    expect(screen.getByText(/not that the role needs no skills/i)).toBeInTheDocument();
  });

  it("ranks core skills in the ledger with band text and accessible meter", () => {
    render(
      <JobRequirementsPanel
        requirements={reqs([
          skill({ concept_id: 1, display: "Python", importance_band: "core", importance_score: 85 }),
          skill({
            concept_id: 2,
            display: "AWS",
            importance_band: "important",
            importance_score: 60,
            modality: "preferred",
          }),
        ])}
      />,
    );
    const row = screen.getByRole("button", { name: /python, core required skill, 1 source/i });
    expect(row).toBeInTheDocument();
    // Meter must carry a text summary, never a bare percentage.
    expect(
      screen.getByRole("img", { name: /python: core requirement, required, 1 source/i }),
    ).toBeInTheDocument();
    expect(screen.getByText("Core")).toBeInTheDocument();
    expect(screen.getByText("Important")).toBeInTheDocument();
  });

  it("click expands one evidence drawer with employer quote, source and modality", async () => {
    const user = userEvent.setup();
    const onShowSection = vi.fn();
    render(
      <JobRequirementsPanel
        requirements={reqs([skill({ concept_id: 1, display: "Python" })])}
        onShowSection={onShowSection}
      />,
    );
    const row = screen.getByRole("button", { name: /python/i });
    expect(row).toHaveAttribute("aria-expanded", "false");
    await user.click(row);
    expect(row).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText(/“Experience with Python.”/)).toBeInTheDocument();
    expect(screen.getByText("Minimum Qualifications")).toBeInTheDocument();
    expect(screen.getByText(/· Required/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /show in description/i }));
    expect(onShowSection).toHaveBeenCalledWith("minimum_qualifications");
  });

  it("offers no jump to the description where the panel has no description to show", async () => {
    const user = userEvent.setup();
    render(<JobRequirementsPanel requirements={reqs([skill({ concept_id: 1, display: "Python" })])} />);
    await user.click(screen.getByRole("button", { name: /python/i }));
    expect(screen.getByText(/“Experience with Python.”/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /show in description/i })).not.toBeInTheDocument();
  });

  it("collapses supporting skills after six with an explicit Show N more", async () => {
    const user = userEvent.setup();
    const names = ["Python", "Rust", "Java", "Kafka", "Docker", "Kubernetes", "Terraform", "Scala", "Redis"];
    const supporting = Array.from({ length: 9 }, (_, i) =>
      skill({
        concept_id: 10 + i,
        display: names[i],
        importance_band: "supporting",
        importance_score: 40,
        modality: "used_in_role",
      }),
    );
    render(<JobRequirementsPanel requirements={reqs(supporting)} />);
    expect(screen.getByText("Python")).toBeInTheDocument();
    expect(screen.queryByText("Redis")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Show 3 more" }));
    expect(screen.getByText("Redis")).toBeInTheDocument();
  });

  it("keeps behavioural competencies out of the skill ranking, in Ways of working", async () => {
    const user = userEvent.setup();
    render(
      <JobRequirementsPanel
        requirements={reqs([
          skill({ concept_id: 1, display: "Python" }),
          skill({
            concept_id: 2,
            display: "Mentorship",
            facet: "behavioral_competency",
            category: "leadership",
            importance_band: "core",
          }),
        ])}
      />,
    );
    expect(screen.getByText("Ways of working")).toBeInTheDocument();
    // Not a ledger row: no meter for behavioural items.
    expect(screen.queryByRole("button", { name: /mentorship, core/i })).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Show evidence" }));
    expect(screen.getByText(/“Experience with Mentorship.”/)).toBeInTheDocument();
  });

  it("renders an industry vertical in its own group, never as a ledger skill", () => {
    render(
      <JobRequirementsPanel
        requirements={reqs([
          skill({ concept_id: 1, display: "Python" }),
          skill({
            concept_id: 2,
            display: "Healthcare",
            slug: "healthcare",
            facet: "industry",
            category: "industry",
            importance_band: "core",
            modality: "required",
          }),
        ])}
      />,
    );
    // Distinct "Industry" group holds the vertical.
    expect(screen.getByText("Industry")).toBeInTheDocument();
    expect(screen.getByText("Healthcare")).toBeInTheDocument();
    // An industry is a chip, never a ledger row: no importance meter/band button.
    expect(screen.queryByRole("button", { name: /healthcare, core/i })).not.toBeInTheDocument();
    // Python still ranks as a skill; the two are not mixed.
    expect(screen.getByRole("button", { name: /python, core/i })).toBeInTheDocument();
  });

  it("renders qualifications as a separate ledger with Required/Preferred labels", () => {
    render(
      <JobRequirementsPanel
        requirements={reqs(
          [],
          [
            {
              id: 1,
              kind: "experience",
              display: "8+ years of software engineering experience.",
              modality: "required",
              years: 8,
              years_stated: [8],
              evidence: [],
            },
            {
              id: 2,
              kind: "education",
              display: "BS in Computer Science or equivalent.",
              modality: "preferred",
              years: null,
              years_stated: [],
              evidence: [],
            },
          ],
        )}
      />,
    );
    expect(screen.getByText("Qualifications")).toBeInTheDocument();
    expect(screen.getByText("Required")).toBeInTheDocument();
    expect(screen.getByText("Preferred")).toBeInTheDocument();
    expect(screen.getByText(/8\+ years of software engineering/)).toBeInTheDocument();
  });

  describe("years of experience", () => {
    function qual(
      over: Partial<JobRequirements["qualifications"][number]> & { id: number; display: string },
    ): JobRequirements["qualifications"][number] {
      return { kind: "experience", modality: "required", years: null, years_stated: [], evidence: [], ...over };
    }

    // Shapes stored postings carry: a nested line (MaintainX), a preferred line
    // asking for MORE than the requirement, a degree line, a line whose display
    // was cut before its numbers, and Google's glued line that states each twice.
    const nested = qual({
      id: 1,
      display:
        "10+ years in software engineering with 5+ years in engineering leadership, including 2+ years managing managers across multiple teams.",
      years: 10,
      years_stated: [10, 5, 2],
    });
    const preferredMore = qual({
      id: 2,
      display: "12+ years building developer platforms.",
      modality: "preferred",
      years: 12,
      years_stated: [12],
    });
    const degree = qual({ id: 3, kind: "education", display: "BS in Computer Science or equivalent." });

    function withYears(quals: JobRequirements["qualifications"], required_years: number | null): JobRequirements {
      return { ...reqs([], quals), required_years };
    }

    const figures = () =>
      screen
        .getAllByRole("definition")
        .map((d) => d.textContent ?? "")
        .filter((t) => /^\d.*years?$/.test(t));

    it("heads the panel with the years the posting requires, never the preferred ones", () => {
      render(<JobRequirementsPanel requirements={withYears([nested, preferredMore, degree], 10)} />);
      const panel = screen.getByRole("region", { name: "Role requirements" });
      expect(within(panel).getByText("10+ years required")).toBeInTheDocument();
      // The preferred line asks for more; it is shown on its own row, never as the headline.
      expect(screen.queryByText(/12\+ years required/)).not.toBeInTheDocument();
    });

    it("states no headline when no required line states years", () => {
      render(<JobRequirementsPanel requirements={withYears([preferredMore, degree], null)} />);
      expect(screen.queryByText(/years? required/)).not.toBeInTheDocument();
      // The preferred line still shows its own figure.
      expect(figures()).toEqual(["12+ years"]);
    });

    it("gives each experience line every number it states, in order, its headline strong", () => {
      render(<JobRequirementsPanel requirements={withYears([nested, preferredMore, degree], 10)} />);
      // One figure per experience line; the degree line has none.
      expect(figures()).toEqual(["10+ · 5+ · 2+ years", "12+ years"]);
      const figure = screen.getAllByRole("definition").find((d) => d.textContent === "10+ · 5+ · 2+ years")!;
      expect(within(figure).getByText("10+").tagName).toBe("STRONG");
      expect(figure.querySelectorAll("strong")).toHaveLength(1);
    });

    it("marks the headline by value, not by position, and states a repeated number once", () => {
      const ladder = qual({
        id: 4,
        display: "Master's degree and 3+ years of experience, or Bachelor's degree and 5+ years.",
        years: 5,
        years_stated: [3, 5],
      });
      const glued = qual({
        id: 5,
        display: "Master's degree in a technology field.7 years of experience working cross-functionally.",
        modality: "preferred",
        years: 7,
        years_stated: [7, 7, 5, 5],
      });
      render(<JobRequirementsPanel requirements={withYears([ladder, glued], 5)} />);
      expect(figures()).toEqual(["3+ · 5+ years", "7+ · 5+ years"]);
      const ladderFigure = screen.getAllByRole("definition").find((d) => d.textContent === "3+ · 5+ years")!;
      expect(ladderFigure.querySelector("strong")?.textContent).toBe("5+");
    });

    it("shows years a display cut before them, and a headline-only row's headline", () => {
      const cut = qual({
        id: 6,
        display:
          "Experience leading technical programs across cloud infrastructure, distributed storage, networking, security and developer tooling organizations at scale, in…",
        years: 8,
        years_stated: [8],
      });
      const headlineOnly = qual({ id: 7, display: "Eight years in product management.", years: 8, years_stated: [] });
      render(<JobRequirementsPanel requirements={withYears([cut, headlineOnly], 8)} />);
      expect(figures()).toEqual(["8+ years", "8+ years"]);
    });

    it("lists a line once when it matches two kinds, keeping its years", () => {
      // Google prints degree and years on one line; the extractor stores it as
      // an education row AND an experience row, education first here.
      const google =
        "Bachelor's degree or equivalent practical experience.10 years of experience in product management or related technical role.";
      const rows = [
        qual({ id: 11, kind: "education", display: google }),
        qual({ id: 12, display: google, years: 10, years_stated: [10] }),
        // Negative control: the same words under Preferred are another line.
        qual({ id: 13, kind: "education", display: google, modality: "preferred" }),
        degree,
      ];
      render(<JobRequirementsPanel requirements={withYears(rows, 10)} />);
      const lines = screen.getAllByText(google);
      expect(lines).toHaveLength(2);
      // The Required line kept the experience row's years; Preferred has none.
      expect(lines[0].closest("div")).toHaveTextContent(/^Required.*10\+ years$/);
      expect(lines[1].closest("div")).toHaveTextContent(/^Preferred/);
      expect(figures()).toEqual(["10+ years"]);
      // The merged line keeps its first place: before the degree line.
      const order = screen.getAllByRole("definition").map((d) => d.textContent);
      expect(order.indexOf(google)).toBeLessThan(order.indexOf("BS in Computer Science or equivalent."));
    });

    it("says one year in the singular", () => {
      const one = qual({ id: 8, display: "1+ year of people management.", years: 1, years_stated: [1] });
      render(<JobRequirementsPanel requirements={withYears([one], 1)} />);
      expect(screen.getByText("1+ year required")).toBeInTheDocument();
      expect(figures()).toEqual(["1+ year"]);
    });
  });

  it("states the truth contract in the info tip: posting evidence, not candidate match", () => {
    render(<JobRequirementsPanel requirements={reqs([skill({ concept_id: 1, display: "Python" })])} />);
    expect(screen.getByText(/says nothing about your own skills/i)).toBeInTheDocument();
  });
});

describe("a skill row read aloud", () => {
  afterEach(() => activate("en"));

  it("says how the posting asks for a skill in the words its sentence needs, in Spanish", async () => {
    await activate("es");
    render(
      <JobRequirementsPanel
        requirements={reqs([skill({ concept_id: 1, display: "Python", importance_band: "core", modality: "used_in_role" })])}
      />,
    );
    const spoken = {
      count: 1,
      display: msg("vocab-skill-python"),
      bandLabel: msg("role-job-requirements-panel-importance-inline", { band: "core" }),
      modality: msg("role-job-requirements-panel-modality-inline", { modality: "used_in_role" }),
      sources: 1,
    };
    const row = screen.getByRole("button", { name: msg("role-job-requirements-panel-skill-sources-show-evidence", spoken) });
    expect(within(row).getByRole("img", { name: msg("role-job-requirements-panel-requirement-sources", spoken) })).toBeInTheDocument();
    // The visible label stays the label; only the sentence takes the inline form.
    expect(within(row).getByText(msg("role-job-requirements-panel-important", { choice: "yes" }))).toBeInTheDocument();
    expect(row.getAttribute("aria-label")).not.toMatch(/used in role|core/);
  });
});
