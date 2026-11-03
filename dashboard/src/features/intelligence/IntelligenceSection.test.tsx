import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { IntelligenceStatus, IntelligenceTestResult, MatchingStopResult } from "../../api";
import { api } from "../../api";
import { ApiError } from "../../api/transport";
import { activate } from "../../copy/activate";
import { msg } from "../../test/msg";
import {
  agentAccessFixture,
  cloudModelProfileFixture,
  cloudModelTestResultFixture,
  intelligenceFitFixture,
  localModelProfileFixture,
  localModelTestResultFixture,
  localServerStatusFixture,
} from "../../test/fixtures";
import { IntelligenceTab } from "./IntelligenceSection";

vi.mock("../../api", () => ({
  DEFAULT_FILTERS: { sort: "relevance", limit: 25, offset: 0 },
  api: {
    intelligence: vi.fn(),
    intelligenceFit: vi.fn(),
    intelligenceFitBand: vi.fn(),
    saveIntentStatement: vi.fn(),
    jobs: vi.fn(),
    stats: vi.fn(),
    agentAccess: vi.fn(),
    setAgentAccess: vi.fn(),
    setMatchingTier: vi.fn(),
    stopMatchingSwitch: vi.fn(),
    resumeMatchingSwitch: vi.fn(),
    setIntelligenceEnabled: vi.fn(),
    setAiEgressEnabled: vi.fn(),
    testIntelligence: vi.fn(),
    localLLMProfiles: vi.fn(),
    updateLocalLLMProfile: vi.fn(),
    deleteLocalLLMProfile: vi.fn(),
    selectLocalLLMProfile: vi.fn(),
    testLocalLLMProfile: vi.fn(),
    localServerStatus: vi.fn(),
    setLocalLLMEnabled: vi.fn(),
    controlLocalServer: vi.fn(),
    cloudLLMProfiles: vi.fn(),
    testCloudLLMProfile: vi.fn(),
    addCloudLLMProfile: vi.fn(),
    updateCloudLLMProfile: vi.fn(),
    deleteCloudLLMProfile: vi.fn(),
  },
}));

const mocked = vi.mocked(api);

const fit = intelligenceFitFixture;

const status = {
  matching: {
    status: "ready",
    tier: "fp32",
    model_id: "lightonai/DenseOn",
    downloaded_bytes: 600153516,
    total_bytes: 600153516,
    chosen_by: "auto",
    detected_ram_bytes: 48 * 1024 ** 3,
    ram_threshold_bytes: 16 * 1024 ** 3,
    tiers: [
      { tier: "fp32", total_bytes: 600153516, recommended: true, installed: true, switch_seconds: null },
      { tier: "int8", total_bytes: 153490318, recommended: false, installed: true, switch_seconds: null },
    ],
    reembedding: false,
    corpus_embedded: 4548,
    corpus_total: 4548,
    stale_count: 0,
    other_tier_count: 0,
    job_phase: "none",
    estimate_seconds: null,
  },
  enabled: true,
  provider: "apple_fm",
  availability: { state: "available", ok: true, detail: null },
  model_id: "apple-fm-on-device",
  prompt_version: "v5",
  routing: { egress_enabled: false, tiers: [] },
} satisfies IntelligenceStatus;

/** What a stop answers: what it ended, then the state it went back to. */
const stoppedBack: MatchingStopResult = { stopped: true, outcome: "stopped", ...status };

function primeHappyPath() {
  mocked.intelligence.mockResolvedValue(status);
  mocked.intelligenceFit.mockResolvedValue(fit);
  mocked.intelligenceFitBand.mockResolvedValue({ band: "weak", items: [] } as never);
  mocked.jobs.mockResolvedValue({
    total: 1410,
    ranked_by: "intent",
    items: [
      { id: 1, company: "anthropic", title: "Manager of Applied AI Architecture", locations: ["San Francisco, CA"], level_band: "principal" },
      { id: 2, company: "anthropic", title: "Engineering Manager, Research Data Platform", locations: ["San Francisco, CA"], level_band: "staff" },
    ],
  } as never);
  mocked.stats.mockResolvedValue({ open_total: 1410, saved_total: 2 } as never);
  mocked.agentAccess.mockResolvedValue({
    ...agentAccessFixture,
    codex_command: "codex mcp add roleband -- python -m tracker.mcp.server",
  });
  mocked.localLLMProfiles.mockResolvedValue({
    enabled: false,
    active_profile_id: "p1",
    profiles: [{ ...localModelProfileFixture, id: "p1", name: "Qwen3.5 (9B-4bit)", model: "Qwen3.5-9B-MLX-4bit" }],
  });
  mocked.localServerStatus.mockResolvedValue({
    ...localServerStatusFixture,
    enabled: false,
    profile_id: "p1",
    model: "Qwen3.5-9B-MLX-4bit",
    state: "server_unreachable",
    reachable: false,
  });
  mocked.cloudLLMProfiles.mockResolvedValue({ profiles: [] });
}

function mount() {
  return render(
    <MemoryRouter>
      <IntelligenceTab />
    </MemoryRouter>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  primeHappyPath();
});

describe("ranking card", () => {
  it("puts the selected roles on top of a rising field, with the model as one line", async () => {
    mount();

    // The instrument states its base and the user's own words.
    expect(await screen.findByText(/1,410 open roles, ranked by how well they fit/)).toBeInTheDocument();
    expect(screen.getByText("leadership in AI/frontier tech")).toBeInTheDocument();

    // The field is described for assistive tech with the band counts.
    expect(await screen.findByRole("group", { name: /Strong 62.*Weak 492/ })).toBeInTheDocument();

    // The selected roles are a ranked list linking to the roles themselves.
    expect(await screen.findByText("Preview")).toBeInTheDocument();
    expect(screen.getByText(/your best fits/)).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "Manager of Applied AI Architecture" }),
    ).toHaveAttribute("href", expect.stringMatching(/^\/company\/[^/]+\/job\/1$/));

    // The model is one line, named for a person — never the quantization.
    expect(screen.getByText("Big model")).toBeInTheDocument();
    expect(screen.queryByText(/Exact|Compact|fp32|int8/)).toBeNull();
    expect(screen.getByRole("button", { name: "Switch to the small model" })).toBeEnabled();
    // The status word is what is RUNNING, not how it was picked...
    expect(screen.getByText(/· Current/)).toBeInTheDocument();
    // ...and auto-chosen means no "Choose automatically" escape hatch, which is
    // the only signal distinguishing a pinned tier from an automatic one.
    expect(screen.queryByRole("button", { name: "Choose automatically" })).toBeNull();
  });

  it("each band of the field is a control: clicking previews that band's roles, clicking again goes back", async () => {
    mocked.intelligenceFitBand.mockResolvedValue({
      band: "weak",
      items: [
        { id: 9, company: "meta", title: "Regional Retail Ops Lead", locations: ["Austin, TX"], level_band: "senior" },
      ],
    } as never);
    mount();

    // The bands announce themselves as pressable, with their counts.
    const weak = await screen.findByRole("button", { name: "Weak: 492 roles" });
    expect(weak).toHaveAttribute("aria-pressed", "false");

    await userEvent.click(weak);
    expect(mocked.intelligenceFitBand).toHaveBeenCalledWith("weak", 3);
    expect(weak).toHaveAttribute("aria-pressed", "true");

    // The preview swaps to the band's own sample and names the pool it drew from.
    expect(await screen.findByText(/the strongest of Weak · 492 roles/)).toBeInTheDocument();
    // The role's own address: a short /job/:id would redirect and remount the role.
    expect(screen.getByRole("link", { name: "Regional Retail Ops Lead" })).toHaveAttribute(
      "href",
      "/company/meta/job/9",
    );
    expect(screen.queryByRole("link", { name: "Manager of Applied AI Architecture" })).toBeNull();
    // "+491 more": the band's count minus the one shown, not the board total.
    expect(screen.getByText(/\+491 more/)).toBeInTheDocument();

    // Clicking the selected band again returns to the best matches.
    await userEvent.click(weak);
    expect(await screen.findByText(/your best fits/)).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "Manager of Applied AI Architecture" }),
    ).toBeInTheDocument();
  });

  it("a failed read of the best fits is said with Try again, never shown as an empty list", async () => {
    mocked.jobs.mockRejectedValueOnce(new ApiError("unavailable", 503));
    mount();
    expect(await screen.findByText("Couldn't load your best fits")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Manager of Applied AI Architecture" })).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: /Try again/ }));
    expect(await screen.findByRole("link", { name: "Manager of Applied AI Architecture" })).toBeInTheDocument();
  });

  it("a failed band sample is said, and reselecting the band reads it again", async () => {
    mocked.intelligenceFitBand.mockRejectedValueOnce(new ApiError("unavailable", 503));
    mount();
    const weak = await screen.findByRole("button", { name: "Weak: 492 roles" });
    await userEvent.click(weak);
    expect(await screen.findByText("Couldn't load the roles in this grade")).toBeInTheDocument();
    expect(screen.queryByText(/Nothing lands in/)).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: /Try again/ }));
    await waitFor(() => expect(mocked.intelligenceFitBand).toHaveBeenCalledTimes(2));
    expect(screen.queryByText("Couldn't load the roles in this grade")).toBeNull();
  });

  describe("the aim sentence", () => {
    it("is edited on the ranking card, saves alone, and re-ranks the card", async () => {
      const next = "Staff infrastructure leadership";
      mocked.saveIntentStatement.mockResolvedValue({ intent_statement: next });
      mount();
      const card = await screen.findByRole("region", { name: "Fit ranking" });
      expect(within(card).getByText(/ranked by how well they fit/)).toBeInTheDocument();
      // The sentence is edited here, with no hand-off to another screen.
      expect(within(card).queryByRole("link", { name: /Direction/ })).toBeNull();

      await userEvent.click(within(card).getByRole("button", { name: "Edit your aim" }));
      const input = within(card).getByLabelText("Your aim, in one sentence");
      expect(input).toHaveValue(fit.intent_statement);
      expect(input).toHaveFocus();
      expect(within(card).getByText(/It never hides a role/)).toBeInTheDocument();
      // Nothing to save until the text changes.
      expect(within(card).getByRole("button", { name: "Save" })).toBeDisabled();

      mocked.intelligenceFit.mockResolvedValue({ ...fit, intent_statement: next });
      await userEvent.clear(input);
      await userEvent.type(input, `  ${next} `);
      await userEvent.click(within(card).getByRole("button", { name: "Save" }));

      expect(mocked.saveIntentStatement).toHaveBeenCalledWith(next);
      expect(await within(card).findByText(next)).toBeInTheDocument();
      // A new sentence re-ranks every role: the field and preview are re-read.
      expect(mocked.intelligenceFit).toHaveBeenCalledTimes(2);
      expect(mocked.jobs).toHaveBeenCalledTimes(2);
      expect(within(card).queryByLabelText("Your aim, in one sentence")).toBeNull();
      expect(within(card).getByRole("button", { name: "Edit your aim" })).toHaveFocus();
    });

    it("a failed save keeps the editor open with the text, and says why", async () => {
      mocked.saveIntentStatement.mockRejectedValue(
        new ApiError("embedding model is not ready", 502, "model-unreachable"),
      );
      mount();
      const card = await screen.findByRole("region", { name: "Fit ranking" });
      await userEvent.click(await within(card).findByRole("button", { name: "Edit your aim" }));
      const input = within(card).getByLabelText("Your aim, in one sentence");
      await userEvent.type(input, " and platforms");
      await userEvent.click(within(card).getByRole("button", { name: "Save" }));

      // The reason in the reader's words for its code, never the API's English.
      const alert = await within(card).findByRole("alert");
      expect(alert).toHaveTextContent(`Couldn't save your aim. ${msg("error-model-unreachable")}`);
      expect(alert).not.toHaveTextContent("embedding model is not ready");
      expect(input).toHaveValue(`${fit.intent_statement} and platforms`);
      expect(mocked.intelligenceFit).toHaveBeenCalledTimes(1);
    });

    it("Escape and Cancel leave without saving", async () => {
      mount();
      const card = await screen.findByRole("region", { name: "Fit ranking" });
      await userEvent.click(await within(card).findByRole("button", { name: "Edit your aim" }));
      await userEvent.type(within(card).getByLabelText("Your aim, in one sentence"), " edited{Escape}");
      expect(within(card).queryByLabelText("Your aim, in one sentence")).toBeNull();

      await userEvent.click(within(card).getByRole("button", { name: "Edit your aim" }));
      await userEvent.type(within(card).getByLabelText("Your aim, in one sentence"), " edited");
      await userEvent.click(within(card).getByRole("button", { name: "Cancel" }));
      expect(within(card).getByText(fit.intent_statement!)).toBeInTheDocument();
      expect(mocked.saveIntentStatement).not.toHaveBeenCalled();
    });

    it("with no sentence and no feedback, the card offers to add one", async () => {
      mocked.intelligenceFit.mockResolvedValue({
        ...fit, ranked: false, intent_statement: null, bins: [], bands: [],
      });
      mount();
      const card = await screen.findByRole("region", { name: "Fit ranking" });
      expect(await within(card).findByText("1,410 open roles, sorted by date")).toBeInTheDocument();
      await userEvent.click(within(card).getByRole("button", { name: "Add your aim" }));
      expect(within(card).getByLabelText("Your aim, in one sentence")).toHaveValue("");
    });
  });

  it("an empty band says so instead of showing someone else's roles", async () => {
    mocked.intelligenceFitBand.mockResolvedValue({ band: "strong", items: [] } as never);
    mount();

    await userEvent.click(await screen.findByRole("button", { name: "Strong: 62 roles" }));
    expect(await screen.findByText(/nothing lands in Strong right now/)).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Manager of Applied AI Architecture" })).toBeNull();
  });

  it("never switches on one click: the confirm states the trade, the cost and the way back", async () => {
    mocked.intelligenceFit.mockResolvedValue(fit);
    mount();

    await userEvent.click(
      await screen.findByRole("button", { name: "Switch to the small model" }),
    );
    const dialog = await screen.findByRole("dialog", { name: "Ranking model switch" });

    // The dialog's accessible name is a heading the user can actually see —
    // assistive tech and the screen must not be told two different things.
    expect(
      within(dialog).getByRole("heading", { name: "Ranking model switch" }),
    ).toBeInTheDocument();

    // The routing slip states the direction; the hero states the exact cost.
    expect(within(dialog).getByText("Big model")).toBeInTheDocument();
    expect(within(dialog).getByText("Small model")).toBeInTheDocument();
    expect(within(dialog).getByText("4,548 roles")).toBeInTheDocument();

    // The recommendation reads in two tiers. The lead is the decision, and its
    // two thoughts — the verdict, then the one reason to switch anyway — are
    // separate lines, never one wrapped sentence.
    expect(within(dialog).getByText("The big model produces better results.")).toBeInTheDocument();
    expect(
      within(dialog).getByText("Switch only if you want to free RAM."),
    ).toBeInTheDocument();
    // ...and the evidence sits under it as a comparison of two real readings,
    // each figure labelled, so the gap between them is visible rather than
    // buried in a sentence.
    // Each figure is asserted through ITS OWN label, so swapping the two
    // numbers — the one mistake that would invert the recommendation — fails
    // here rather than reading as a pair of correct-looking figures.
    const builtFor = within(dialog).getByText("Small model is built for").closest("div");
    expect(builtFor).toHaveTextContent("16 GB");
    const yourComputer = within(dialog).getByText("Your computer has").closest("div");
    expect(yourComputer).toHaveTextContent("48 GB");
    expect(within(dialog).queryByText(/disk|storage/i)).toBeNull();
    // We never talk down our own product.
    expect(within(dialog).queryByText(/worse|inferior|slower ranking/i)).toBeNull();

    // The three guarantees the user must be able to learn before committing.
    expect(within(dialog).getByText(/Keep the computer awake/)).toBeInTheDocument();
    expect(within(dialog).getByText(/Keep working while it runs/)).toBeInTheDocument();
    expect(within(dialog).getByText(/Stop anytime, restart anytime. Nothing is lost/)).toBeInTheDocument();

    // Nothing has happened yet.
    expect(mocked.setMatchingTier).not.toHaveBeenCalled();
    await userEvent.click(within(dialog).getByRole("button", { name: "Start the switch" }));
    expect(mocked.setMatchingTier).toHaveBeenCalledWith("int8");
  });

  it("shows no duration when this computer has never been measured", async () => {
    mount();
    await userEvent.click(
      await screen.findByRole("button", { name: "Switch to the small model" }),
    );
    const dialog = await screen.findByRole("dialog");
    // estimate_seconds is null in the fixture: we may not invent a figure, so
    // the exact role count becomes the hero instead.
    expect(within(dialog).queryByText(/minutes|min\b|hr\b/)).toBeNull();
    expect(within(dialog).getByText("4,548 roles")).toBeInTheDocument();
  });

  it("a switch in progress shows progress, a measured time left, and one way out", async () => {
    mocked.intelligence.mockResolvedValue({
      ...status,
      matching: {
        ...status.matching,
        tier: "int8",
        chosen_by: "user",
        reembedding: true,
        job_phase: "converting",
        corpus_embedded: 1212,
        corpus_total: 4548,
        stale_count: 3336,
        estimate_seconds: 780,
      },
    });
    mount();

    expect(await screen.findByText("Switching to the small model")).toBeInTheDocument();
    expect(screen.getByRole("progressbar", { name: "Switching progress" })).toBeInTheDocument();
    expect(screen.getByText(/1,212 of 4,548 roles updated · about 13 min left/)).toBeInTheDocument();

    // Stop means stop AND go back — there is deliberately no bare stop, since
    // that would leave the nightly pass to finish the cancelled switch.
    const stop = screen.getByRole("button", { name: "Stop and go back to the big model" });
    mocked.stopMatchingSwitch.mockResolvedValue(stoppedBack);
    await userEvent.click(stop);
    expect(mocked.stopMatchingSwitch).toHaveBeenCalled();
  });

  it("does not let an older poll overwrite a completed stop response", async () => {
    const converting = {
      ...status,
      matching: {
        ...status.matching,
        tier: "int8" as const,
        chosen_by: "user" as const,
        reembedding: true,
        job_phase: "converting" as const,
        corpus_embedded: 3200,
        stale_count: 1348,
      },
    };
    let resolvePoll!: (value: IntelligenceStatus) => void;
    const stalePoll = new Promise<IntelligenceStatus>((resolve) => {
      resolvePoll = resolve;
    });
    mocked.intelligence
      .mockResolvedValueOnce(converting)
      .mockImplementationOnce(() => stalePoll);
    mocked.stopMatchingSwitch.mockResolvedValue(stoppedBack);

    let poll!: () => void;
    const interval = vi.spyOn(window, "setInterval").mockImplementation((handler) => {
      poll = handler;
      return 1 as unknown as ReturnType<typeof setInterval>;
    });
    const clearInterval = vi.spyOn(window, "clearInterval").mockImplementation(() => {});
    try {
      mount();
      const stop = await screen.findByRole("button", {
        name: "Stop and go back to the big model",
      });

      // This GET began before the stop mutation and returns after it. Its
      // converting payload is older than the POST response and must be ignored.
      poll();
      expect(mocked.intelligence).toHaveBeenCalledTimes(2);
      await userEvent.click(stop);
      expect(await screen.findByText("Big model")).toBeInTheDocument();

      await act(async () => resolvePoll(converting));

      expect(screen.getByText("Big model")).toBeInTheDocument();
      expect(screen.queryByText("Switching to the small model")).toBeNull();
    } finally {
      interval.mockRestore();
      clearInterval.mockRestore();
    }
  });

  it("clears the request-busy state when a switch fails", async () => {
    mocked.setMatchingTier.mockRejectedValueOnce(new ApiError("switch could not start", 409, "switch-not-started"));
    mount();
    const card = await screen.findByRole("region", { name: "Fit ranking" });

    await userEvent.click(await screen.findByRole("button", { name: "Switch to the small model" }));
    await userEvent.click(
      within(screen.getByRole("dialog")).getByRole("button", { name: "Start the switch" }),
    );

    expect(await screen.findByRole("alert")).toHaveTextContent(msg("error-switch-not-started"));
    expect(card).not.toHaveClass("is-busy");
  });

  it("a switch that stopped halfway says so instead of looking finished", async () => {
    mocked.intelligence.mockResolvedValue({
      ...status,
      matching: {
        ...status.matching,
        tier: "int8",
        chosen_by: "user",
        reembedding: false,
        job_phase: "none",
        corpus_total: 4548,
        stale_count: 2698,
        other_tier_count: 2698,
        estimate_seconds: 660,
      },
    });
    mount();

    expect(await screen.findByText("The switch to the small model is paused.")).toBeInTheDocument();
    expect(screen.getByText(/The rest finishes tonight on its own/)).toBeInTheDocument();
    expect(screen.getByText("1,850 of 4,548 roles updated")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Finish now, about 11 min/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Go back to the big model" })).toBeInTheDocument();
  });

  it("roles a first scan has not ranked yet are counted, not shown as a paused switch", async () => {
    mocked.intelligence.mockResolvedValue({
      ...status,
      matching: {
        ...status.matching,
        tier: "fp32",
        chosen_by: "auto",
        reembedding: false,
        job_phase: "none",
        corpus_embedded: 800,
        corpus_total: 2600,
        stale_count: 1800,
        other_tier_count: 0,
      },
    });
    mount();

    expect(await screen.findByText("800 roles ranked")).toBeInTheDocument();
    expect(screen.queryByText(/is paused/)).toBeNull();
    expect(screen.queryByRole("button", { name: /Finish now/ })).toBeNull();
    expect(screen.queryByRole("button", { name: "Go back to the small model" })).toBeNull();
  });

  it("a failed download is the one warning state, and offers the way back", async () => {
    mocked.intelligence.mockResolvedValue({
      ...status,
      matching: { ...status.matching, status: "missing", tier: "int8", chosen_by: "user" },
    });
    mount();

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("The small model couldn't be downloaded.");
    expect(alert).toHaveTextContent("Check your internet connection and try again.");
    expect(screen.getByRole("button", { name: "Use the big model" })).toBeInTheDocument();
  });

  it("can stop and go back while the model is still arriving", async () => {
    mocked.intelligence.mockResolvedValue({
      ...status,
      matching: {
        ...status.matching,
        tier: "int8",
        chosen_by: "user",
        status: "downloading",
        job_phase: "downloading",
        downloaded_bytes: 380 * 1024 ** 2,
        total_bytes: 572 * 1024 ** 2,
      },
    });
    mocked.stopMatchingSwitch.mockResolvedValue(stoppedBack);
    mount();

    expect(await screen.findByText(/downloading, 380 of 572 MB/)).toBeInTheDocument();
    expect(screen.getByText(/Roles are listed newest first until this finishes/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Switch to/ })).toBeNull();
    await userEvent.click(
      screen.getByRole("button", { name: "Stop and go back to the big model" }),
    );
    expect(mocked.stopMatchingSwitch).toHaveBeenCalledOnce();
    expect(await screen.findByText("Big model")).toBeInTheDocument();
  });

  it("a user-pinned tier offers the way back to automatic", async () => {
    mocked.intelligence.mockResolvedValue({
      ...status,
      matching: { ...status.matching, chosen_by: "user" },
    });
    mocked.setMatchingTier.mockResolvedValue(status);
    mount();

    await userEvent.click(await screen.findByRole("button", { name: "Choose automatically" }));
    expect(mocked.setMatchingTier).toHaveBeenCalledWith(null);
  });
});

describe("assistants card", () => {
  it("keeps setup unreachable until the gate is on, then writes stay a second choice", async () => {
    mocked.setAgentAccess.mockResolvedValue({
      enabled: true,
      allow_writes: false,
      codex_command: "codex mcp add roleband",
      claude_json: {},
    } as never);
    mount();

    const card = await screen.findByRole("region", { name: "MCP server" });
    // Three tiles: the two named clients plus the open door — MCP is a
    // protocol, so the card may not imply only two products can speak it.
    const setup = within(card).getAllByRole("button", { name: "Set up" });
    expect(setup).toHaveLength(3);
    expect(within(card).getByText("Other app")).toBeInTheDocument();
    expect(within(card).getByText(/Any client that speaks MCP/)).toBeInTheDocument();
    for (const button of setup) expect(button).toBeDisabled();
    // The write grant gates nothing while nothing may connect: it is absent,
    // not present-but-greyed.
    expect(
      within(card).queryByLabelText("Allow assistant apps to update your progress"),
    ).toBeNull();

    await userEvent.click(within(card).getByLabelText("Allow assistant apps to connect"));
    expect(mocked.setAgentAccess).toHaveBeenCalledWith(true, false);
    await waitFor(() => {
      expect(within(card).getAllByRole("button", { name: "Set up" })[0]).toBeEnabled();
    });
    expect(within(card).getByLabelText("Allow assistant apps to update your progress")).toBeEnabled();
  });

  it("states what will be seen before anything can connect", async () => {
    mount();
    const card = await screen.findByRole("region", { name: "MCP server" });
    expect(within(card).getByText("What will be shared")).toBeInTheDocument();
    expect(within(card).getByText("What will not be shared")).toBeInTheDocument();
    expect(within(card).getByText(/full posting/)).toBeInTheDocument();
    expect(within(card).getByText(/profile and intent statement/)).toBeInTheDocument();
    // A "never sees" list may not carry an exception inside it.
    expect(within(card).queryByText(/Anything at all, unless/)).toBeNull();
    // The lists say WHAT is visible, not how much of it: no live tally sits
    // among the shared items, and the card asks for no stats to build one.
    expect(within(card).queryByText(/Counts:/)).toBeNull();
    expect(mocked.stats).not.toHaveBeenCalled();
  });
});

describe("capabilities card", () => {
  it("labels each capability with where it runs and offers no dead Start button", async () => {
    mocked.localServerStatus.mockResolvedValue({
      ...localServerStatusFixture,
      enabled: false,
      installed: false,
      binary: null,
      managed: false,
      state: "server_unreachable",
      reachable: false,
    });
    mount();

    const card = await screen.findByRole("region", { name: "Extended capabilities" });
    expect(await within(card).findByText(/not installed/)).toBeInTheDocument();
    expect(within(card).queryByRole("button", { name: /Start|Stop/ })).toBeNull();
    // The cloud row is future-tense until a service exists — and it is the
    // only row wearing the cloud label.
    expect(within(card).getByText("Online model services")).toBeInTheDocument();
    expect(within(card).getAllByText("Cloud-connected")).toHaveLength(1);
    // The gate is a standing permission: answerable BEFORE a service exists,
    // like the MCP connect gate, and it writes the same egress flag the
    // connected-service row toggles.
    const gate = within(card).getByLabelText("Send postings to online services");
    expect(gate).toBeEnabled();
    expect(gate).not.toBeChecked();
    mocked.setAiEgressEnabled.mockResolvedValue({
      ...status,
      routing: { egress_enabled: true, tiers: [] },
    } as never);
    await userEvent.click(gate);
    const consent = screen.getByRole("dialog", { name: msg("ai-egress-title") });
    expect(within(consent).getByText(msg("ai-egress-empty"))).toBeInTheDocument();
    expect(mocked.setAiEgressEnabled).not.toHaveBeenCalled();
    await userEvent.click(within(consent).getByRole("button", { name: msg("ai-egress-allow") }));
    expect(mocked.setAiEgressEnabled).toHaveBeenCalledWith(true);
  });

  it("will not start a server for a capability that is switched off", async () => {
    mount();
    const card = await screen.findByRole("region", { name: "Extended capabilities" });

    // The fixture: capability off, managed server installed and stopped. Starting it would launch a server nothing is
    // allowed to use.
    expect(within(card).getByLabelText("Use your own model")).not.toBeChecked();
    expect(await within(card).findByRole("button", { name: /Start/ })).toBeDisabled();
    expect(mocked.controlLocalServer).not.toHaveBeenCalled();
  });

  it("still offers Stop for a server already running, whatever the switch says", async () => {
    mocked.localServerStatus.mockResolvedValue({ ...localServerStatusFixture, enabled: false });
    mount();
    const card = await screen.findByRole("region", { name: "Extended capabilities" });

    // Turning the row off must never strand a process the user cannot reach.
    expect(within(card).getByLabelText("Use your own model")).not.toBeChecked();
    expect(await within(card).findByRole("button", { name: /Stop/ })).toBeEnabled();
  });

  it("arms the cloud dialog's delete too — the two dialogs cannot disagree about it", async () => {
    mocked.cloudLLMProfiles.mockResolvedValue({ profiles: [cloudModelProfileFixture] });
    mocked.deleteCloudLLMProfile.mockResolvedValue({ profiles: [] });
    mount();

    const card = await screen.findByRole("region", { name: "Extended capabilities" });
    await userEvent.click(within(card).getByRole("button", { name: "Configure OpenAI API" }));
    const dialog = screen.getByRole("dialog", { name: "Configure OpenAI API" });

    await userEvent.click(within(dialog).getByRole("button", { name: "Delete" }));
    expect(mocked.deleteCloudLLMProfile).not.toHaveBeenCalled();

    await userEvent.click(
      within(dialog).getByRole("button", { name: "Confirm delete OpenAI API" }),
    );
    expect(mocked.deleteCloudLLMProfile).toHaveBeenCalledWith("c1");
  });

  // One connected service, its own switch ON. Only the permission above it
  // varies, so the permission alone must decide whether the vendor is reached.
  const oneService = (enabled: boolean) => ({ profiles: [{ ...cloudModelProfileFixture, enabled }] });
  const withEgress = (on: boolean) => ({ ...status, routing: { egress_enabled: on, tiers: [] } });

  it("requires confirmation naming every saved destination before allowing posting text out", async () => {
    mocked.cloudLLMProfiles.mockResolvedValue({ profiles: [
      { ...cloudModelProfileFixture, enabled: true },
      { ...cloudModelProfileFixture, id: "c2", name: "Research service", base_url: "https://models.example.org/api" },
    ] });
    mocked.setAiEgressEnabled.mockResolvedValue(withEgress(true));
    mount();

    await screen.findByLabelText(msg("ai-capabilities-card-use", { name: cloudModelProfileFixture.name }));
    const gate = screen.getByLabelText(msg("ai-capabilities-card-send-postings-to-online-services"));
    await userEvent.click(gate);
    const dialog = screen.getByRole("dialog", { name: msg("ai-egress-title") });
    expect(within(dialog).getByText(msg("ai-egress-detail"))).toBeInTheDocument();
    expect(within(dialog).getByText(cloudModelProfileFixture.name)).toBeInTheDocument();
    expect(within(dialog).getByText(cloudModelProfileFixture.base_url)).toBeInTheDocument();
    expect(within(dialog).getByText("Research service")).toBeInTheDocument();
    expect(within(dialog).getByText("https://models.example.org/api")).toBeInTheDocument();
    expect(gate).not.toBeChecked();
    expect(mocked.setAiEgressEnabled).not.toHaveBeenCalled();
    expect(mocked.testCloudLLMProfile).not.toHaveBeenCalled();

    await userEvent.click(within(dialog).getByRole("button", { name: msg("ai-egress-allow") }));
    expect(mocked.setAiEgressEnabled).toHaveBeenCalledExactlyOnceWith(true);
    await waitFor(() => expect(gate).toBeChecked());
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it.each(["cancel", "escape"])("%s leaves posting egress off without reaching a service", async (action) => {
    mocked.cloudLLMProfiles.mockResolvedValue(oneService(true));
    mount();
    await screen.findByLabelText(msg("ai-capabilities-card-use", { name: cloudModelProfileFixture.name }));
    const gate = screen.getByLabelText(msg("ai-capabilities-card-send-postings-to-online-services"));
    await userEvent.click(gate);
    const dialog = screen.getByRole("dialog", { name: msg("ai-egress-title") });
    if (action === "cancel") {
      await userEvent.click(within(dialog).getByRole("button", { name: msg("ai-aim-line-cancel") }));
    } else {
      await userEvent.keyboard("{Escape}");
    }
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(gate).not.toBeChecked();
    expect(mocked.setAiEgressEnabled).not.toHaveBeenCalled();
    expect(mocked.testCloudLLMProfile).not.toHaveBeenCalled();
  });

  it("turns posting egress off with one click", async () => {
    mocked.cloudLLMProfiles.mockResolvedValue(oneService(true));
    mocked.intelligence.mockResolvedValue(withEgress(true));
    mocked.setAiEgressEnabled.mockResolvedValue(withEgress(false));
    mount();
    await screen.findByLabelText(msg("ai-capabilities-card-use", { name: cloudModelProfileFixture.name }));
    const gate = screen.getByLabelText(msg("ai-capabilities-card-send-postings-to-online-services"));
    await waitFor(() => expect(gate).toBeChecked());
    await userEvent.click(gate);
    expect(mocked.setAiEgressEnabled).toHaveBeenCalledExactlyOnceWith(false);
    expect(screen.queryByRole("dialog")).toBeNull();
    await waitFor(() => expect(gate).not.toBeChecked());
  });

  it("keeps permission off until destinations load, including a failed read", async () => {
    let reject!: (reason: Error) => void;
    mocked.cloudLLMProfiles.mockReturnValue(new Promise((_, fail) => { reject = fail; }));
    mount();
    const gate = await screen.findByLabelText(msg("ai-capabilities-card-send-postings-to-online-services"));
    expect(gate).toBeDisabled();
    await act(async () => { reject(new Error("unavailable")); });
    expect(gate).toBeDisabled();
    await userEvent.click(gate);
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(mocked.setAiEgressEnabled).not.toHaveBeenCalled();
  });

  it("waits for the permission write and leaves a failed confirmation open for retry", async () => {
    let reject!: (reason: Error) => void;
    mocked.cloudLLMProfiles.mockResolvedValue(oneService(true));
    mocked.setAiEgressEnabled.mockReturnValueOnce(new Promise((_, fail) => { reject = fail; }));
    mount();
    await screen.findByLabelText(msg("ai-capabilities-card-use", { name: cloudModelProfileFixture.name }));
    const gate = screen.getByLabelText(msg("ai-capabilities-card-send-postings-to-online-services"));
    await userEvent.click(gate);
    const dialog = screen.getByRole("dialog", { name: msg("ai-egress-title") });
    const allow = within(dialog).getByRole("button", { name: msg("ai-egress-allow") });
    await userEvent.click(allow);
    expect(allow).toBeDisabled();
    expect(within(dialog).getByRole("button", { name: msg("ai-aim-line-cancel") })).toBeDisabled();
    await userEvent.keyboard("{Escape}");
    await userEvent.click(allow);
    expect(dialog).toBeInTheDocument();
    expect(gate).not.toBeChecked();
    expect(mocked.setAiEgressEnabled).toHaveBeenCalledExactlyOnceWith(true);

    await act(async () => { reject(new Error("unavailable")); });
    expect(within(dialog).getByRole("alert")).toBeInTheDocument();
    expect(gate).not.toBeChecked();
    mocked.setAiEgressEnabled.mockResolvedValue(withEgress(true));
    await userEvent.click(allow);
    await waitFor(() => expect(gate).toBeChecked());
    expect(mocked.setAiEgressEnabled.mock.calls).toEqual([[true], [true]]);
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("will not reach a vendor for a service the permission above it forbids", async () => {
    mocked.cloudLLMProfiles.mockResolvedValue(oneService(true));
    mocked.intelligence.mockResolvedValue(withEgress(false));
    mount();

    const card = await screen.findByRole("region", { name: "Extended capabilities" });
    // The service's own switch is on; the permission is not. The row says so
    // rather than reporting a service that cannot run as usable.
    expect(within(card).getByLabelText("Use OpenAI API")).toBeChecked();
    expect(within(card).getByText(/blocked · online services are switched off/)).toBeInTheDocument();

    const test = within(card).getByRole("button", { name: "Test OpenAI API" });
    expect(test).toBeDisabled();
    expect(test).toHaveAttribute("title", expect.stringContaining("Allow sending postings"));
    await userEvent.click(test);
    expect(mocked.testCloudLLMProfile).not.toHaveBeenCalled();
  });

  it("will not reach a vendor for a service switched off, permission or not", async () => {
    mocked.cloudLLMProfiles.mockResolvedValue(oneService(false));
    mocked.intelligence.mockResolvedValue(withEgress(true));
    mount();

    const card = await screen.findByRole("region", { name: "Extended capabilities" });
    expect(within(card).getByLabelText("Send postings to online services")).toBeChecked();
    expect(within(card).getByLabelText("Use OpenAI API")).not.toBeChecked();

    const test = within(card).getByRole("button", { name: "Test OpenAI API" });
    expect(test).toBeDisabled();
    expect(test).toHaveAttribute("title", "Turn OpenAI API on to use it");
    await userEvent.click(test);
    expect(mocked.testCloudLLMProfile).not.toHaveBeenCalled();
  });

  it("tests a service only once both switches agree", async () => {
    mocked.cloudLLMProfiles.mockResolvedValue(oneService(true));
    mocked.intelligence.mockResolvedValue(withEgress(true));
    mocked.testCloudLLMProfile.mockResolvedValue(cloudModelTestResultFixture);
    mount();

    const card = await screen.findByRole("region", { name: "Extended capabilities" });
    const test = within(card).getByRole("button", { name: "Test OpenAI API" });
    expect(test).toBeEnabled();
    expect(test).not.toHaveAttribute("title");

    await userEvent.click(test);
    expect(mocked.testCloudLLMProfile).toHaveBeenCalledWith("c1");
    expect(await within(card).findByText(/connection ready · 240 ms/)).toBeInTheDocument();
  });

  it("does not count a service the permission blocks as one that is on", async () => {
    mocked.cloudLLMProfiles.mockResolvedValue(oneService(true));
    mocked.intelligence.mockResolvedValue(withEgress(false));
    mount();

    // The built-in model is on in the fixture; the local model is not; the
    // cloud service is switched on but cannot run. Counting its preference
    // alone would read "2 of 3 on · all on this computer", a tally and a claim
    // that contradict.
    const card = await screen.findByRole("region", { name: "Extended capabilities" });
    await waitFor(() => expect(card).toHaveTextContent("1 of 3 on"));
    expect(card).toHaveTextContent("all on this computer");
  });

  it("counts a service as on, and drops the local-only claim, once both switches agree", async () => {
    mocked.cloudLLMProfiles.mockResolvedValue(oneService(true));
    mocked.intelligence.mockResolvedValue(withEgress(true));
    mount();

    const card = await screen.findByRole("region", { name: "Extended capabilities" });
    await waitFor(() => expect(card).toHaveTextContent("2 of 3 on"));
    expect(card).not.toHaveTextContent("all on this computer");
  });

  it("keeps setup reachable while every switch is off — it is the only way back on", async () => {
    mocked.cloudLLMProfiles.mockResolvedValue(oneService(false));
    mocked.intelligence.mockResolvedValue(withEgress(false));
    mount();

    const card = await screen.findByRole("region", { name: "Extended capabilities" });
    // Nothing is on...
    expect(within(card).getByLabelText("Use your own model")).not.toBeChecked();
    expect(within(card).getByLabelText("Send postings to online services")).not.toBeChecked();
    expect(within(card).getByLabelText("Use OpenAI API")).not.toBeChecked();
    // ...and every path to changing that is still open. Gating configuration
    // behind the switch it configures is a row that can never be turned on:
    // "Use your own model" is itself disabled until a connection is saved, and
    // the gear is the only place to save one.
    expect(within(card).getByRole("button", { name: "Configure your own model" })).toBeEnabled();
    expect(within(card).getByRole("button", { name: "Configure OpenAI API" })).toBeEnabled();
    expect(within(card).getByRole("button", { name: "Add" })).toBeEnabled();
  });

  it("a saved service appears beneath the permission switch", async () => {
    mocked.cloudLLMProfiles.mockResolvedValue({ profiles: [cloudModelProfileFixture] });
    mount();

    const card = await screen.findByRole("region", { name: "Extended capabilities" });
    expect(
      await within(card).findByLabelText("Send postings to online services"),
    ).not.toBeChecked();
    expect(within(card).getByLabelText("Use OpenAI API")).toBeInTheDocument();
  });

  it("loads the selected local profile into the draft before saving it", async () => {
    const first = { ...localModelProfileFixture, id: "p1", name: "Local Ornith", model: "ornith-model" };
    const second = { ...first, id: "p2", name: "Local Qwen", model: "qwen-model" };
    const firstState = { enabled: true, active_profile_id: "p1", profiles: [first, second] };
    const secondState = { ...firstState, active_profile_id: "p2" };
    mocked.localLLMProfiles.mockResolvedValue(firstState);
    mocked.selectLocalLLMProfile.mockResolvedValue(secondState);
    mocked.updateLocalLLMProfile.mockResolvedValue(second);
    mount();

    const card = await screen.findByRole("region", { name: "Extended capabilities" });
    await userEvent.click(within(card).getByRole("button", { name: "Configure your own model" }));
    const dialog = screen.getByRole("dialog", { name: "Configure your own model" });
    expect(within(dialog).getByLabelText("Name")).toHaveValue("Local Ornith");

    await userEvent.click(within(dialog).getByLabelText("Use Local Qwen"));
    await waitFor(() => expect(within(dialog).getByLabelText("Name")).toHaveValue("Local Qwen"));
    expect(within(dialog).getByLabelText("Model ID")).toHaveValue("qwen-model");
    await userEvent.click(within(dialog).getByRole("button", { name: "Save" }));

    expect(mocked.updateLocalLLMProfile).toHaveBeenCalledWith(
      "p2",
      expect.objectContaining({ name: "Local Qwen", model: "qwen-model" }),
    );
  });

  it("never deletes a saved connection on one click, and names it on the second", async () => {
    mocked.deleteLocalLLMProfile.mockResolvedValue({ enabled: false, active_profile_id: null, profiles: [] });
    mount();

    const card = await screen.findByRole("region", { name: "Extended capabilities" });
    await userEvent.click(within(card).getByRole("button", { name: "Configure your own model" }));
    const dialog = screen.getByRole("dialog", { name: "Configure your own model" });

    // First click arms only. A saved connection is not recoverable from the
    // row that lost it, and this button sits in the same strip as Save.
    await userEvent.click(within(dialog).getByRole("button", { name: "Delete" }));
    expect(mocked.deleteLocalLLMProfile).not.toHaveBeenCalled();

    // The armed button names the connection it is about to remove.
    const armed = within(dialog).getByRole("button", {
      name: "Confirm delete Qwen3.5 (9B-4bit)",
    });
    await userEvent.click(armed);
    expect(mocked.deleteLocalLLMProfile).toHaveBeenCalledWith("p1");
  });

  it("blames the action that actually failed, not whichever one is spelled in the markup", async () => {
    mocked.testLocalLLMProfile.mockRejectedValue(
      new ApiError("Could not reach the local model: All connection attempts failed", 502, "model-unreachable"),
    );
    mount();

    const card = await screen.findByRole("region", { name: "Extended capabilities" });
    await userEvent.click(within(card).getByRole("button", { name: "Configure your own model" }));
    const dialog = screen.getByRole("dialog", { name: "Configure your own model" });

    await userEvent.click(within(dialog).getByRole("button", { name: "Test connection" }));

    // Save, delete and test all write one `error` slot. A failed probe must
    // not report "Could not save", a claim about an action nobody took.
    const alert = await within(dialog).findByRole("alert");
    expect(alert).toHaveTextContent("Couldn't reach the model");
    expect(alert).not.toHaveTextContent("Couldn't save");
    expect(alert).toHaveTextContent(msg("error-model-unreachable"));
    expect(alert).not.toHaveTextContent("All connection attempts failed");
  });

  it("tests the unsaved local-model draft shown in the dialog", async () => {
    mocked.testLocalLLMProfile.mockResolvedValue({ ...localModelTestResultFixture, profile_id: "p1" });
    mount();

    const card = await screen.findByRole("region", { name: "Extended capabilities" });
    await userEvent.click(within(card).getByRole("button", { name: "Configure your own model" }));
    const dialog = screen.getByRole("dialog", { name: "Configure your own model" });
    await userEvent.clear(within(dialog).getByLabelText("Model ID"));
    await userEvent.type(within(dialog).getByLabelText("Model ID"), "draft-model");
    await userEvent.click(within(dialog).getByRole("button", { name: "Test connection" }));

    expect(mocked.testLocalLLMProfile).toHaveBeenCalledWith(
      "p1",
      expect.objectContaining({ model: "draft-model" }),
    );
    expect(await within(dialog).findByText("Connection succeeded")).toBeInTheDocument();
  });

  it("does not count an enabled preference with no local profile as a live capability", async () => {
    mocked.localLLMProfiles.mockResolvedValue({ enabled: true, active_profile_id: null, profiles: [] });
    mocked.localServerStatus.mockResolvedValue({
      ...localServerStatusFixture,
      installed: false, binary: null, managed: false, profile_id: null, provider: null, model: null,
      base_url: null, state: "not_configured", reachable: false, detail: "No local model connection is saved.",
    });
    mount();

    const card = await screen.findByRole("region", { name: "Extended capabilities" });
    expect(card).toHaveTextContent("1 of 2 on");
    expect(within(card).getByLabelText("Use your own model")).not.toBeChecked();
    expect(within(card).getByLabelText("Use your own model")).toBeDisabled();
  });
});

describe("the AI screen in the reader's language", () => {
  afterEach(() => activate("en"));

  /* A built-in model's test that found a euro band: what the example states,
     what the model read, and the line from the posting it read it in. */
  const found = {
    ok: true,
    prefiltered: false,
    grounded: true,
    rejected_ungrounded: false,
    answered_by: "apple_fm",
    availability: status.availability,
    expected: { base_min: 150_000, base_max: 190_000, currency: "EUR" },
    extracted: {
      base_min: 150_000, base_max: 190_000, bonus_pct: null, confidence: "high", currency: "EUR", disclosed: true,
      pay_basis: "base", pay_period: "year", source_snippet: "150.000 € a 190.000 € al año",
    },
    input_tokens: null,
    latency_ms: 420,
    left_device: false,
    model_id: "apple-fm-on-device",
    origin: "on_device",
    output_tokens: null,
    prompt_version: "v5",
    raw: {},
    route_attempts: [],
    route_reason: null,
    truncated: false,
    used_sample: true,
  } satisfies IntelligenceTestResult;

  const capabilities = () => screen.findByRole("region", { name: msg("ai-capabilities-card-extended-capabilities-2") });

  it("counts the roles added today inside one sentence, whether one or many", async () => {
    mocked.intelligenceFit.mockResolvedValue({ ...fit, embedded_today: 1 });
    mount();
    const card = await screen.findByRole("region", { name: msg("ai-intelligence-section-fit-ranking-2") });
    await waitFor(() => expect(card).toHaveTextContent(msg("ai-intelligence-section-new-roles-added-today", { count: 1, n: "1" })));
    expect(card).not.toHaveTextContent("1 new roles");
  });

  it("says the built-in model is ready, and what its test found, in Spanish words and the posting's currency", async () => {
    await activate("es");
    mocked.testIntelligence.mockResolvedValue(found);
    mount();
    const card = await capabilities();
    await waitFor(() =>
      expect(card).toHaveTextContent(msg("ai-capabilities-card-experimental-we-are-still-testing", { value: msg("ai-capabilities-card-ready") })));
    expect(card).not.toHaveTextContent(/\bready\b/);

    await userEvent.click(within(card).getByRole("button", { name: msg("ai-capabilities-card-test-apple-intelligence") }));
    const result = await within(card).findByRole("status");
    expect(result).toHaveTextContent(msg("ai-capabilities-card-found-pay", { band: "", basis: "base", period: "year" }).trim());
    expect(result).not.toHaveTextContent(/· base · year/);
    expect(result).toHaveTextContent("€");
    expect(result).not.toHaveTextContent(/\$|EUR/);
  });

  it("names the model that could not be downloaded in the reader's words, even before one was chosen", async () => {
    await activate("es");
    // No model chosen yet: the server names no tier, so the line has none to name.
    const unpinned = {
      ...status.matching, status: "missing", tier: null, chosen_by: "auto", detected_ram_bytes: null, job_phase: "none", reembedding: false,
    } as IntelligenceStatus["matching"];
    mocked.intelligence.mockResolvedValue({ ...status, matching: unpinned });
    mount();
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(msg("ai-matching-model-could-not-be-downloaded"));
    expect(alert).not.toHaveTextContent(/\bmodel\b/);
  });

  it("keeps the count of capabilities inside the sentence that counts them", async () => {
    await activate("zh-Hans");
    mount();
    const card = await capabilities();
    // One of two on (the built-in model), and nothing that is on leaves this
    // computer: the whole line is the one message, the count where it puts it.
    const tally = msg("ai-capabilities-card-of-on", { choice: "yes", on: "1", capCount: 2 });
    await waitFor(() => expect(card.querySelector(".intel-head .intel-aside")?.textContent).toBe(tally));
  });
});
