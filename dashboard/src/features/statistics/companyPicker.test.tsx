import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Facets } from "../../api";
import { api } from "../../api";
import { facetsFixture, trackedCompanyFixture } from "../../test/fixtures";
import { msg } from "../../test/msg";
import { companyPickerOptions, otherCompanies } from "./companyPicker";
import { StatisticsView } from "./StatisticsView";
import { writeInsightsView } from "./insightsView";

/* The Skills and Overlap company pickers on the real Insights screen, the API
 * mocked at its boundary. The routes AND a picked company with the scope's
 * side, so a picker that offers, or keeps, a company off that side asks for
 * a slice that is empty by construction. */

vi.mock("../../api", async () => {
  const actual = await vi.importActual<typeof import("../../api")>("../../api");
  return {
    ...actual,
    api: { ...actual.api, facets: vi.fn(), companies: vi.fn(), skillsTop: vi.fn(), skillsOverlap: vi.fn() },
  };
});

/* Two companies the reader follows (OpenAI from the curated list, Stripe
 * followed by name from the directory) and one the whole-set follow brought
 * in (Acme): only Acme is on the Other companies side. */
const facets: Facets = {
  ...facetsFixture,
  companies: { openai: { display: "OpenAI" }, stripe: { display: "Stripe" }, acme: { display: "Acme" } },
  counts: { ...facetsFixture.counts, company: { openai: 30, stripe: 20, acme: 10 } },
};
const roster = {
  companies: [
    trackedCompanyFixture({ slug: "openai", display: "OpenAI", source: "builtin" }),
    trackedCompanyFixture({ slug: "stripe", display: "Stripe", source: "directory" }),
    trackedCompanyFixture({ slug: "acme", display: "Acme", source: "directory-set" }),
  ],
};

const skills = { items: [], competencies: [], roles: 0, market_roles: 0, narrowed: true };
const overlap = {
  min_jobs: 2,
  companies: [
    { company: "openai", skill_count: 9, open: 30 },
    { company: "stripe", skill_count: 8, open: 20 },
  ],
  pairs: [],
};

function renderAt(route: string) {
  return render(
    <MemoryRouter initialEntries={[route]}>
      <Routes>
        <Route path="/statistics/:tab" element={<StatisticsView onOpen={vi.fn()} />} />
      </Routes>
    </MemoryRouter>,
  );
}

const skillsPicker = (label = msg("insights-skills-view-any-company")) =>
  screen.findByRole("button", { name: msg("shared-filter-select-filter-by", { label: label.toLowerCase() }) });
const overlapPicker = () =>
  screen.findByRole("button", {
    name: msg("shared-filter-select-filter-by", {
      label: msg("insights-overlap-panel-companies-picked", { picker: "default", picked: 0 }).toLowerCase(),
    }),
  });

/** The companies a picker offers, by name, once it is open. */
async function offered(user: ReturnType<typeof userEvent.setup>, trigger: HTMLElement): Promise<string[]> {
  await user.click(trigger);
  const list = await screen.findByRole("listbox");
  await vi.waitFor(() => expect(within(list).queryAllByRole("option").length).toBeGreaterThan(0));
  const names = within(list).getAllByRole("option").map((o) => o.textContent ?? "");
  await user.keyboard("{Escape}");
  return names;
}

beforeEach(() => {
  vi.clearAllMocks();
  // Overlap is listed by the advanced view.
  writeInsightsView("advanced");
  vi.mocked(api.facets).mockResolvedValue(facets);
  vi.mocked(api.companies).mockResolvedValue(roster);
  vi.mocked(api.skillsTop).mockResolvedValue(skills);
  vi.mocked(api.skillsOverlap).mockResolvedValue(overlap);
});

describe("companyPickerOptions", () => {
  const other = otherCompanies(roster);

  it("puts only the companies the whole-set follow brought in on the Other side", () => {
    expect([...other]).toEqual(["acme"]);
    expect(companyPickerOptions(facets, "other", other).map((o) => o.value)).toEqual(["acme"]);
    expect(companyPickerOptions(facets, "yours", other).map((o) => o.value)).toEqual(["openai", "stripe"]);
    expect(companyPickerOptions(facets, "all", null).map((o) => o.value)).toEqual(["openai", "stripe", "acme"]);
  });

  it("offers nothing on a narrowed side until it knows which companies are on it", () => {
    expect(companyPickerOptions(facets, "other", null)).toEqual([]);
    expect(companyPickerOptions(facets, "yours", null)).toEqual([]);
    expect(companyPickerOptions(null, "all", null)).toEqual([]);
  });

  it("leaves out a company with nothing open, and breaks a tie by name", () => {
    const tied: Facets = {
      ...facets,
      companies: { ...facets.companies, zeta: { display: "Zeta" }, beta: { display: "Beta" } },
      counts: { ...facets.counts, company: { openai: 30, zeta: 20, beta: 20, stripe: 0, acme: 10 } },
    };
    expect(companyPickerOptions(tied, "all", null).map((o) => o.label)).toEqual(["OpenAI", "Beta", "Zeta", "Acme"]);
  });
});

describe("Insights company pickers", () => {
  it("offer only the companies on the scope's side", async () => {
    const user = userEvent.setup();
    renderAt("/statistics/skills?side=other");
    const others = await offered(user, await skillsPicker());
    expect(others.some((name) => name.includes("Acme"))).toBe(true);
    expect(others.some((name) => name.includes("OpenAI") || name.includes("Stripe"))).toBe(false);

    await user.click(screen.getByRole("button", { name: msg("insights-your-companies") }));
    const yours = await offered(user, await skillsPicker());
    // A company followed by name from the directory is the reader's own.
    expect(yours.some((name) => name.includes("OpenAI"))).toBe(true);
    expect(yours.some((name) => name.includes("Stripe"))).toBe(true);
    expect(yours.some((name) => name.includes("Acme"))).toBe(false);

    await user.click(screen.getByRole("tab", { name: msg("shell-tab-insights-overlap") }));
    const overlapYours = await offered(user, await overlapPicker());
    expect(overlapYours.some((name) => name.includes("Acme"))).toBe(false);
    expect(overlapYours.some((name) => name.includes("Stripe"))).toBe(true);
  });

  it("drop a picked company when the side changes, on Skills", async () => {
    const user = userEvent.setup();
    renderAt("/statistics/skills");
    await user.click(await skillsPicker());
    await user.click(await screen.findByRole("option", { name: /Stripe/ }));
    await vi.waitFor(() =>
      expect(api.skillsTop).toHaveBeenLastCalledWith({ company: ["stripe"], limit: 30 }, expect.anything(), { side: "all", families: [] }),
    );

    await user.click(screen.getByRole("button", { name: msg("insights-other-companies") }));
    await vi.waitFor(() =>
      expect(api.skillsTop).toHaveBeenLastCalledWith({ company: undefined, limit: 30 }, expect.anything(), { side: "other", families: [] }),
    );
    // Stripe with Other companies is never asked for, not even for a frame.
    expect(api.skillsTop).not.toHaveBeenCalledWith({ company: ["stripe"], limit: 30 }, expect.anything(), { side: "other", families: [] });
    expect(await skillsPicker()).toBeInTheDocument();
  });

  it("drop the picked companies when the side changes, on Overlap", async () => {
    const user = userEvent.setup();
    renderAt("/statistics/overlap");
    await user.click(await overlapPicker());
    await user.click(await screen.findByRole("option", { name: /Acme/ }));
    await vi.waitFor(() =>
      expect(api.skillsOverlap).toHaveBeenLastCalledWith(2, 12, expect.anything(), { side: "all", families: [] }, ["acme"]),
    );
    await user.keyboard("{Escape}");

    await user.click(screen.getByRole("button", { name: msg("insights-your-companies") }));
    await vi.waitFor(() =>
      expect(api.skillsOverlap).toHaveBeenLastCalledWith(2, 10, expect.anything(), { side: "yours", families: [] }, []),
    );
    expect(api.skillsOverlap).not.toHaveBeenCalledWith(2, 12, expect.anything(), { side: "yours", families: [] }, ["acme"]);
  });

  it("read the filter options once for the whole screen", async () => {
    const user = userEvent.setup();
    renderAt("/statistics/skills");
    await offered(user, await skillsPicker());
    await user.click(screen.getByRole("tab", { name: msg("shell-tab-insights-overlap") }));
    await offered(user, await overlapPicker());
    expect(api.facets).toHaveBeenCalledTimes(1);
  });
});
