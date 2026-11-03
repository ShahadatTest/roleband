import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { api } from "../../api";
import { activate } from "../../copy/activate";
import { profileStateFixture, profileSuggestionFixture, scopeCatalogFixture } from "../../test/fixtures";
import { msg } from "../../test/msg";
import { ScopeDraftProvider } from "./useScopeDraft";
import { SuggestionInbox, basisClauses } from "./ProfileSuggestions";

vi.mock("../../api", () => ({
  api: {
    scopeCatalog: vi.fn(),
    profile: vi.fn(),
    profileSuggestions: vi.fn(),
    acceptProfileSuggestion: vi.fn(),
    dismissProfileSuggestion: vi.fn(),
  },
}));

vi.mock("../../context/MissionState", () => ({
  useMissionActions: () => ({ refreshStats: vi.fn() }),
}));

const suggestions = vi.mocked(api.profileSuggestions);
const accept = vi.mocked(api.acceptProfileSuggestion);
const dismiss = vi.mocked(api.dismissProfileSuggestion);

const offSuggestion = profileSuggestionFixture;

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(api.scopeCatalog).mockResolvedValue(scopeCatalogFixture({
    settings: {
      enabled_role_groups: [], enabled_seniority_bands: [],
      enabled_role_tracks: [], enabled_location_groups: [],
      enabled_domain_groups: ["ai_ml", "advertising"],
      excluded_domain_groups: [], excluded_location_groups: [],
      include_unstated_level: true, role_answers: [],
    },
  }));
  vi.mocked(api.profile).mockResolvedValue(profileStateFixture());
  suggestions.mockResolvedValue({ suggestions: [offSuggestion] });
});

const renderInbox = () => render(
  <ScopeDraftProvider>
    <SuggestionInbox />
  </ScopeDraftProvider>,
);

it("renders the proposal with its evidence in plain language", async () => {
  renderInbox();
  expect(await screen.findByText("Turn off Advertising?")).toBeInTheDocument();
  // The basis is the user's own history, spelled out — not a bare score.
  expect(
    screen.getByText("Because you marked 2 roles there Not for me: wrong world, and 1 more marked Not for me without a reason."),
  ).toBeInTheDocument();
});

it("counts roles in the reader's language, never in English inside a translated sentence", async () => {
  await activate("es");
  try {
    const off = basisClauses({ ...offSuggestion, basis: { ...offSuggestion.basis, dismissed_wrong_domain: 2 } });
    expect(off[0]).toBe(msg("profile-suggestions-you-marked-there-not-for", { dismissed_wrong_domain: msg("shared-count-role", { count: 2 }) }));
    const on = basisClauses({ ...offSuggestion, kind: "world_on", basis: { ...offSuggestion.basis, pursued: 0, favorited: 3, sectors: [], intent_matched: false } });
    expect(on).toEqual([msg("profile-suggestions-you-saved-there", { favorited: msg("shared-count-role", { count: 3 }) })]);
    expect([...off, ...on].join(" ")).not.toMatch(/\broles?\b/);
  } finally {
    await activate("en");
  }
});

it("says each count in the glossary's words, singular and plural", () => {
  const basis = { ...offSuggestion.basis, dismissed_wrong_domain: 1, dismissed_other: 2 };
  // Both forms spelled out, never "s" appended; "pass" and "pursue" are not the person's words.
  expect(basisClauses({ ...offSuggestion, basis })).toEqual([
    "you marked 1 role there Not for me: wrong world",
    "2 more marked Not for me without a reason",
  ]);
  const on = {
    ...offSuggestion, kind: "world_on" as const,
    basis: { ...offSuggestion.basis, pursued: 1, favorited: 3, sectors: ["fintech", "ai"], intent_matched: true },
  };
  expect(basisClauses(on)).toEqual([
    "1 role there is in progress",
    "you saved 3 roles there",
    "2 followed company sectors point there",
    "your aim names it",
  ]);
  expect(basisClauses({ ...on, basis: { ...on.basis, pursued: 2, sectors: ["ai"] } }).slice(0, 3)).toEqual([
    "2 roles there are in progress",
    "you saved 3 roles there",
    "1 followed company sector points there",
  ]);
});

it("accept applies via the API, reports the scope effect, and clears the card", async () => {
  accept.mockResolvedValue({
    suggestion: { ...offSuggestion, status: "accepted" },
    enabled_domain_groups: ["ai_ml"],
    excluded_domain_groups: [],
    in_scope_changed: 12,
    promoted: 0,
    promotion_pending: false,
  });
  renderInbox();
  await userEvent.click(
    await screen.findByRole("button", { name: /Accept: turn off Advertising/ }),
  );
  await waitFor(() => expect(accept).toHaveBeenCalledWith(7));
  expect(screen.queryByText("Turn off Advertising?")).not.toBeInTheDocument();
  expect(screen.getByRole("status")).toHaveTextContent(
    "Advertising turned off · 12 roles on your radar updated",
  );
});

it("dismiss resolves without touching scope and clears the card", async () => {
  dismiss.mockResolvedValue({ suggestion: { ...offSuggestion, status: "dismissed" } });
  renderInbox();
  await userEvent.click(
    await screen.findByRole("button", { name: /Dismiss suggestion about Advertising/ }),
  );
  await waitFor(() => expect(dismiss).toHaveBeenCalledWith(7));
  expect(screen.queryByText("Turn off Advertising?")).not.toBeInTheDocument();
});

it("renders nothing at all when the inbox is empty", async () => {
  suggestions.mockResolvedValue({ suggestions: [] });
  const { container } = renderInbox();
  await waitFor(() => expect(suggestions).toHaveBeenCalled());
  expect(container.querySelector(".profile-suggestions")).toBeNull();
});

it("says a failed load, with a way to try again, instead of an empty inbox", async () => {
  // Fail-first: the failure was read as "no suggestions" and nothing rendered.
  suggestions.mockRejectedValueOnce(new Error("socket hang up"));
  renderInbox();
  const alert = await screen.findByRole("alert");
  expect(alert).toHaveTextContent(msg("profile-suggestions-could-not-load"));
  expect(alert).not.toHaveTextContent("socket hang up");

  await userEvent.click(screen.getByRole("button", { name: msg("common-try-again") }));
  expect(await screen.findByText("Turn off Advertising?")).toBeInTheDocument();
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  expect(suggestions).toHaveBeenCalledTimes(2);
});

it("an inbox with nothing to confirm renders nothing, and says no error", async () => {
  suggestions.mockResolvedValue({ suggestions: [] });
  const { container } = renderInbox();
  await waitFor(() => expect(suggestions).toHaveBeenCalled());
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  expect(container.querySelector(".profile-suggestions")).toBeNull();
});
