import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";
import { api } from "../../api";
import { scopeCatalogFixture } from "../../test/fixtures";
import { ScopeDraftProvider, primeScopeCatalog, useScopeDraft } from "./useScopeDraft";

/* The welcome asks the walk's catalog early; the walk's first load takes it
   rather than asking again, so setup opens on its first question. */

vi.mock("../../api", () => ({
  api: {
    profileSuggestions: vi.fn(async () => ({ suggestions: [] })),
    scopeCatalog: vi.fn(),
    companies: vi.fn(async () => ({ companies: [] })),
    profile: vi.fn(),
    scopeRules: vi.fn(async () => ({ rules: [] })),
  },
}));
vi.mock("../../context/MissionState", () => ({ useMissionActions: () => ({ refreshStats: vi.fn() }) }));

const load = vi.mocked(api.scopeCatalog);

function Loaded() {
  const { catalog } = useScopeDraft();
  return <p>{catalog ? "catalog loaded" : "waiting"}</p>;
}

beforeEach(() => {
  vi.clearAllMocks();
  load.mockResolvedValue(scopeCatalogFixture({}));
});

it("the walk's first load takes the catalog the welcome asked for", async () => {
  primeScopeCatalog();
  primeScopeCatalog();
  expect(load).toHaveBeenCalledTimes(1);
  render(<MemoryRouter><ScopeDraftProvider initialSelection="empty"><Loaded /></ScopeDraftProvider></MemoryRouter>);
  expect(await screen.findByText("catalog loaded")).toBeInTheDocument();
  expect(load).toHaveBeenCalledTimes(1);
});

it("without it, the walk asks for its own", async () => {
  render(<MemoryRouter><ScopeDraftProvider initialSelection="empty"><Loaded /></ScopeDraftProvider></MemoryRouter>);
  expect(await screen.findByText("catalog loaded")).toBeInTheDocument();
  expect(load).toHaveBeenCalledTimes(1);
});
