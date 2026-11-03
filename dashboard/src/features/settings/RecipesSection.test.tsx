import { msg } from "../../test/msg";
import { ApiError } from "../../api/transport";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { api } from "../../api";
import { list } from "../../copy/format";
import { setCompanyNames } from "../../format";
import {
  recipeCheckFixture,
  recipeDetailFixture,
  recipeDocumentFixture,
  recipeRevisionFixture,
  recipeSummaryFixture,
  trackedCompanyFixture,
} from "../../test/fixtures";
import { RecipesSection } from "./RecipesSection";

vi.mock("../../api", () => ({
  api: {
    recipes: vi.fn(),
    recipe: vi.fn(),
    saveRecipeDraft: vi.fn(),
    previewRecipe: vi.fn(),
    checkRecipeVersion: vi.fn(),
    useRecipeVersion: vi.fn(),
    scanCompanyWithRecipe: vi.fn(),
    companies: vi.fn(),
  },
}));

const COMPANIES = {
  companies: [
    trackedCompanyFixture(),
    // Scanned by a built-in reader: never offered to a recipe.
    trackedCompanyFixture({ slug: "stripe", display: "Stripe", adapter: "greenhouse", status: "active" }),
  ],
};

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(api.recipes).mockResolvedValue([recipeSummaryFixture()]);
  vi.mocked(api.recipe).mockResolvedValue(recipeDetailFixture());
  vi.mocked(api.companies).mockResolvedValue(COMPANIES);
  vi.mocked(api.previewRecipe).mockResolvedValue(recipeCheckFixture());
  vi.mocked(api.saveRecipeDraft).mockResolvedValue({ slug: "valve-jobs", revision_id: 8, version: 2 });
  vi.mocked(api.checkRecipeVersion).mockResolvedValue(recipeCheckFixture({ passed: true, list_complete: true, found: 12 }));
  vi.mocked(api.useRecipeVersion).mockResolvedValue(recipeSummaryFixture());
  vi.mocked(api.scanCompanyWithRecipe).mockResolvedValue({
    company: "valve", recipe: "valve-jobs", binding_id: 3, revision_id: 7, closure_capability: "none",
  });
});

const editor = () => screen.getByLabelText("Recipe (JSON)");
const write = (text: string) => fireEvent.change(editor(), { target: { value: text } });

it("lists each recipe with its version in use, whether it was checked, and what it scans", async () => {
  render(<RecipesSection />);
  expect(await screen.findByText("valve-jobs")).toBeVisible();
  expect(screen.getByText("version 1 in use · checked · scans valve")).toBeVisible();
});

it("names the companies and sites of a recipe as one list in the reader's words", async () => {
  setCompanyNames({ valve: "Valve Corporation", "riot-games": "Riot Games" });
  const companies = ["valve", "riot-games"];
  const domains = ["www.valvesoftware.com", "jobs.valvesoftware.com"];
  vi.mocked(api.recipes).mockResolvedValue([recipeSummaryFixture({ companies, domains })]);
  vi.mocked(api.recipe).mockResolvedValue(recipeDetailFixture({ companies }));
  render(<RecipesSection />);

  const scans = list(["Valve Corporation", "Riot Games"]);
  expect(await screen.findByText(list(domains))).toBeVisible();
  const facts = screen.getByText(msg("settings-recipes-section-scans-no-company", { choice: "yes", join: scans }), { exact: false });
  expect(facts).toBeVisible();
  expect(facts).not.toHaveTextContent(/valve,|riot-games/);

  await userEvent.click(screen.getByRole("button", { name: msg("settings-recipes-section-open") }));
  expect(await screen.findByText(msg("settings-recipes-section-no-company-is-scanned-with", { choice: "yes", join: scans })))
    .toBeVisible();
});

it("says so when there are no recipes yet, as an empty list and not a notice", async () => {
  vi.mocked(api.recipes).mockResolvedValue([]);
  render(<RecipesSection />);
  const none = await screen.findByText(msg("settings-recipes-section-no-recipes-yet-write-one"));
  expect(none).toBeVisible();
  // An empty list is ui/EmptyState; a CardMessage is an event.
  expect(none.closest(".settings-message")).toBeNull();
  expect(screen.queryByRole("note")).toBeNull();
});

it("refuses to send text that is not one JSON object", async () => {
  render(<RecipesSection />);
  write("{ not json");
  await userEvent.click(screen.getByRole("button", { name: "Preview" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Not valid JSON");
  write("[1, 2]");
  await userEvent.click(screen.getByRole("button", { name: "Save draft" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("A recipe is one JSON object.");
  expect(api.previewRecipe).not.toHaveBeenCalled();
  expect(api.saveRecipeDraft).not.toHaveBeenCalled();
});

it("previews what the recipe reads without saving anything", async () => {
  render(<RecipesSection />);
  write(JSON.stringify(recipeDocumentFixture));
  await userEvent.click(screen.getByRole("button", { name: "Preview" }));

  const result = await screen.findByLabelText("Preview result");
  expect(within(result).getByText("Game Designer")).toBeVisible();
  expect(within(result).getByText("Bellevue, WA · 101")).toBeVisible();
  expect(within(result).getByText("no place stated · 102")).toBeVisible();
  expect(api.previewRecipe).toHaveBeenCalledWith(recipeDocumentFixture);
  expect(api.saveRecipeDraft).not.toHaveBeenCalled();
});

it("names every problem the recipe has, and a page that asks not to be read", async () => {
  vi.mocked(api.previewRecipe).mockResolvedValue(recipeCheckFixture({
    problems: ["semantic: raw XPath is not permitted anywhere in a recipe"],
    jobs: [], found: 0, robots: { allowed: false },
  }));
  render(<RecipesSection />);
  await userEvent.click(screen.getByRole("button", { name: "Preview" }));
  const result = await screen.findByLabelText("Preview result");
  expect(within(result).getByText(/raw XPath is not permitted/)).toBeVisible();
  expect(within(result).getByText(/asks not to be read automatically/)).toBeVisible();
});

it("does not call a page empty when the preview was refused before reading it", async () => {
  vi.mocked(api.previewRecipe).mockResolvedValue(recipeCheckFixture({
    errors: ["robots.txt does not allow the start URL for our user agent"],
    jobs: [], found: 0, robots: { allowed: false },
  }));
  render(<RecipesSection />);
  write(JSON.stringify(recipeDocumentFixture));
  await userEvent.click(screen.getByRole("button", { name: "Preview" }));
  const result = await screen.findByLabelText("Preview result");
  expect(within(result).getByText(/asks not to be read automatically/)).toBeVisible();
  expect(within(result).queryByText("No roles found on the first pages.")).toBeNull();
});

it("saves a draft version and opens it", async () => {
  render(<RecipesSection />);
  write(JSON.stringify(recipeDocumentFixture));
  await userEvent.click(screen.getByRole("button", { name: "Save draft" }));

  await waitFor(() => expect(api.saveRecipeDraft).toHaveBeenCalledWith(recipeDocumentFixture));
  expect(await screen.findByText("Saved version 2 of valve-jobs.")).toBeVisible();
  await waitFor(() => expect(api.recipe).toHaveBeenCalledWith("valve-jobs"));
  expect(await screen.findByLabelText("Versions")).toBeVisible();
});

it("checks one version's whole page and reports what it read", async () => {
  render(<RecipesSection />);
  await userEvent.click(await screen.findByRole("button", { name: "Open" }));
  await userEvent.click(await screen.findByRole("button", { name: "Check the whole page" }));

  await waitFor(() => expect(api.checkRecipeVersion).toHaveBeenCalledWith("valve-jobs", 7));
  expect(await screen.findByText("Checked: read the whole page, 12 roles over 1 pages.")).toBeVisible();
});

it("offers to switch only to a version that is not already in use", async () => {
  vi.mocked(api.recipe).mockResolvedValue(recipeDetailFixture({
    revisions: [recipeRevisionFixture({ id: 9, version: 2, validated_at: null }), recipeRevisionFixture()],
  }));
  render(<RecipesSection />);
  await userEvent.click(await screen.findByRole("button", { name: "Open" }));
  const versions = await screen.findByLabelText("Versions");
  expect(within(versions).getAllByRole("button", { name: "Use this version" })).toHaveLength(1);
  expect(within(versions).getByText(/^not checked · saved/)).toBeVisible();

  await userEvent.click(within(versions).getByRole("button", { name: "Use this version" }));
  await waitFor(() => expect(api.useRecipeVersion).toHaveBeenCalledWith("valve-jobs", 9));
});

it("scans only a company no built-in reader covers, and says what closes and when", async () => {
  render(<RecipesSection />);
  await userEvent.click(await screen.findByRole("button", { name: "Open" }));
  const company = await screen.findByRole("combobox", { name: "Company" });
  expect(within(company).getAllByRole("option").map((o) => o.textContent)).toEqual(["Choose a company", "Valve"]);
  const scan = screen.getByRole("button", { name: "Scan with it" });
  expect(scan).toBeDisabled();

  await userEvent.selectOptions(company, "valve");
  await userEvent.click(scan);
  await waitFor(() => expect(api.scanCompanyWithRecipe).toHaveBeenCalledWith("valve", "valve-jobs"));
  expect(await screen.findByText(/Its missing roles close only once a checked version/)).toBeVisible();
});

it("keeps a failed scan's message to that recipe, said from its code", async () => {
  vi.mocked(api.scanCompanyWithRecipe).mockRejectedValue(
    new ApiError("recipe 'valve-jobs' has no activated revision", 404, "recipe-not-found"),
  );
  render(<RecipesSection />);
  await userEvent.click(await screen.findByRole("button", { name: "Open" }));
  await userEvent.selectOptions(await screen.findByRole("combobox", { name: "Company" }), "valve");
  await userEvent.click(screen.getByRole("button", { name: "Scan with it" }));
  expect(await screen.findByRole("alert")).toHaveTextContent(msg("error-recipe-not-found"));
  expect(screen.getByRole("alert")).not.toHaveTextContent("activated revision");
});

it("has one primary action: saving", async () => {
  const { container } = render(<RecipesSection />);
  await userEvent.click(await screen.findByRole("button", { name: "Open" }));
  await screen.findByLabelText("Versions");
  const primaries = container.querySelectorAll(".ui-btn-primary");
  expect([...primaries].map((b) => b.textContent)).toEqual(["Save draft"]);
});
