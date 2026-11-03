import { act, fireEvent, render as rtlRender, screen, waitFor, within } from "@testing-library/react";
import type { ReactElement, ReactNode } from "react";
import { MemoryRouter, useLocation } from "react-router-dom";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type {
  DecidedReviewItem, DuplicateReviewItem, DuplicateReviewList, DuplicateReviewSummaryList, JobDetailRow, TwinReviewList,
} from "../../api";
import { api } from "../../api";
import { ApiError } from "../../api/transport";
import { activate } from "../../copy/activate";
import { msg } from "../../test/msg";
import {
  descriptionDiffFixture,
  duplicateProposalFixture,
  duplicateVerdictFixture,
  jobDetailFixture,
  jobDetailRowFixture,
  relationshipAssessmentFixture,
  twinProposalFixture,
  twinVerdictFixture,
} from "../../test/fixtures";
import { ToastProvider } from "../../ui/Toast";
import { ReviewScreen } from "./ReviewScreen";
import { setCompanyNames } from "../../format";

// The posting panels render CompanyChip, which navigates -> needs a Router.
// A queue verdict confirms with a toast -> needs the provider (inert without it).
const Wrap = ({ children }: { children: ReactNode }) => (
  <MemoryRouter>
    <ToastProvider>{children}</ToastProvider>
  </MemoryRouter>
);
const render = (ui: ReactElement) => rtlRender(ui, { wrapper: Wrap });

/* A role opens as a cover over the queue through the app's job opener. */
const { openJob } = vi.hoisted(() => ({ openJob: vi.fn() }));
vi.mock("../../context/JobWorkspace", () => ({ useJobActions: () => ({ openJob }) }));

vi.mock("../../api", () => ({
  api: {
    lineageReview: vi.fn(), lineageReviewHistory: vi.fn(), reviewLineageLink: vi.fn(),
    twinReview: vi.fn(), twinReviewHistory: vi.fn(), reviewTwinLink: vi.fn(),
    analyzeLineageLink: vi.fn(), analyzeTwinLink: vi.fn(), job: vi.fn(),
  },
}));

const mockList = (d: DuplicateReviewList) => {
  vi.mocked(api.lineageReview).mockResolvedValue(d);
  vi.mocked(api.twinReview).mockResolvedValue({ total: 0, limit: 50, offset: 0, items: [] });
};

const mockHistory = (d: DuplicateReviewSummaryList = { total: 0, limit: 20, offset: 0, items: [] }) => {
  vi.mocked(api.lineageReviewHistory).mockResolvedValue(d);
  vi.mocked(api.twinReviewHistory).mockResolvedValue({ total: 0, limit: 20, offset: 0, items: [] });
};

/* The pair the queue tests start from: a suspected duplicate, complete as
   `GET /api/lineage/review` sends it. */
function duplicatePair(): DuplicateReviewItem {
  return {
    link: duplicateProposalFixture({ reasons: ["cosine 0.90 in review band"] }),
    prior: jobDetailRowFixture({ id: 1, req_id: "A", title: "Staff SWE" }),
    job: jobDetailRowFixture({ id: 2, req_id: "B", title: "Staff SWE, Core" }),
    diff: { title: { from: "Staff SWE", to: "Staff SWE, Core" } },
  };
}

function list(): DuplicateReviewList {
  return { total: 1, limit: 50, offset: 0, items: [duplicatePair()] };
}

/* A posting as the Decided list sends it (`detail=false`): the row, without
   its description or stated pay. */
function listRow(overrides: Partial<JobDetailRow> = {}): DecidedReviewItem["job"] {
  const row: DecidedReviewItem["job"] & Partial<JobDetailRow> = jobDetailRowFixture(overrides);
  delete row.description_text;
  delete row.description_html;
  delete row.description_sections;
  delete row.disclosed_comp;
  return row;
}

/* A queue item as the Decided list sends it once decided. */
function decided(item: DuplicateReviewItem): DuplicateReviewSummaryList["items"][number] {
  return { link: item.link, prior: listRow(item.prior), job: listRow(item.job), diff: item.diff };
}

/* A promise the test settles, for a response that lands late. */
function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((settle) => {
    resolve = settle;
  });
  return { promise, resolve };
}


/* One pair of a queue a run of verdicts works through, its posting ids and
   requisitions drawn from its proposal id. */
function queuePair(id: number, title: string, score: number): DuplicateReviewItem {
  return {
    link: duplicateProposalFixture({ id, job_id: id * 10 + 1, prior_job_id: id * 10, score }),
    prior: jobDetailRowFixture({ id: id * 10, req_id: `P${id}`, title }),
    job: jobDetailRowFixture({ id: id * 10 + 1, req_id: `J${id}`, title: `${title}, II` }),
    diff: {},
  };
}
const queueOf = (...items: DuplicateReviewItem[]): DuplicateReviewList => ({ total: items.length, limit: 50, offset: 0, items });

/* The same pair proposed by the twin detector, as `GET /api/twins/review` sends it. */
function twinList(): TwinReviewList {
  const { job, prior, diff } = duplicatePair();
  return {
    total: 1,
    limit: 50,
    offset: 0,
    items: [{ link: twinProposalFixture({ id: 19 }), job, prior, diff, description_diff: descriptionDiffFixture }],
  };
}

describe("ReviewScreen", () => {
  beforeEach(() => vi.clearAllMocks());

  it("shows the pair, evidence, and marks a duplicate with the d key", async () => {
    mockList(list());
    mockHistory();
    vi.mocked(api.reviewLineageLink).mockResolvedValue(duplicateVerdictFixture());
    const user = userEvent.setup();
    render(<ReviewScreen />);

    expect(await screen.findByText("1 pair left in the queue")).toBeInTheDocument();
    expect(screen.getAllByText("Earlier posting")).toHaveLength(2);
    const ledger = screen.getByRole("region", { name: "Side by side" });
    expect(within(ledger).getByRole("row", { name: /TitleDifferent Staff SWE Staff SWE, Core/ })).toBeInTheDocument();
    expect(screen.getByLabelText("System similarity 90%")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "About system similarity" })).toBeInTheDocument();
    // The reasons in the reader's words, never the detector's English.
    expect(screen.getByText(msg("duplicates-reason-descriptions-alike", { pct: 90 }))).toBeInTheDocument();
    expect(screen.queryByText("cosine 0.90 in review band")).toBeNull();

    vi.mocked(api.lineageReview).mockResolvedValue({ total: 0, limit: 50, offset: 0, items: [] });
    await user.keyboard("d");
    expect(api.reviewLineageLink).toHaveBeenCalledWith(7, "confirmed");
    // Optimistically advances to the empty state.
    await waitFor(() => expect(screen.getByText(/Queue clear/)).toBeInTheDocument());
    // The queue asks only about pairs on the radar, so clear is
    // said of those, never of every pending pair.
    expect(screen.getByText(/Every close pair on your radar has a decision/)).toBeInTheDocument();
  });

  /* A verdict key is a bare letter. With Cmd or Ctrl it is the browser's or
     the OS's shortcut (Cmd+D bookmarks the page), and while a dialog is open
     over the queue (the `?` sheet, say) the keyboard belongs to that dialog:
     neither may record a verdict on the pair behind it. */
  it("records no verdict for a key held with a modifier, or pressed while a dialog is open", async () => {
    mockList(list());
    mockHistory();
    const user = userEvent.setup();
    render(<ReviewScreen />);
    expect(await screen.findByText("1 pair left in the queue")).toBeInTheDocument();

    await user.keyboard("{Meta>}d{/Meta}");
    await user.keyboard("{Control>}t{/Control}");
    await user.keyboard("{Alt>}n{/Alt}");
    expect(api.reviewLineageLink).not.toHaveBeenCalled();

    const dialog = document.createElement("div");
    dialog.setAttribute("role", "dialog");
    dialog.setAttribute("aria-modal", "true");
    dialog.tabIndex = -1;
    document.body.appendChild(dialog);
    dialog.focus();
    await user.keyboard("d");
    expect(api.reviewLineageLink).not.toHaveBeenCalled();
    dialog.remove();

    // Typing into a field is typing, never a verdict.
    const field = document.createElement("textarea");
    document.body.appendChild(field);
    field.focus();
    await user.keyboard("dtn");
    expect(api.reviewLineageLink).not.toHaveBeenCalled();
    field.remove();

    vi.mocked(api.reviewLineageLink).mockResolvedValue(duplicateVerdictFixture());
    vi.mocked(api.lineageReview).mockResolvedValue({ total: 0, limit: 50, offset: 0, items: [] });
    await user.keyboard("d");
    expect(api.reviewLineageLink).toHaveBeenCalledWith(7, "confirmed");
  });

  it("collapses long matching runs and gives each posting its role and its careers page, told apart", async () => {
    const data = list();
    const disclosed = {
      disclosed: true, currency: "USD", pay_basis: "base", pay_period: "year",
      // The object exists only once the pay pass has run, so it always says when.
      snippet: null, confidence: "high", bonus_pct: null, checked_at: "2026-07-15T00:00:00Z",
      from_pay_field: false,
    } as const;
    data.items[0].prior = jobDetailRowFixture({
      id: 1,
      req_id: "REQ-A",
      title: "Staff Software Engineer",
      url: "https://example.test/jobs/a",
      first_seen: "2026-07-13T00:00:00Z",
      last_seen: "2026-07-15T00:00:00Z",
      days_open: 2,
      disclosed_comp: { ...disclosed, base_min: 167000, base_max: 296000 },
    });
    data.items[0].job = jobDetailRowFixture({
      id: 2,
      req_id: "REQ-B",
      title: "Staff Software Engineer",
      url: "https://example.test/jobs/b",
      first_seen: "2026-07-14T00:00:00Z",
      last_seen: "2026-07-15T00:00:00Z",
      days_open: 1,
      disclosed_comp: { ...disclosed, base_min: 197000, base_max: 354000 },
    });
    mockList(data);
    mockHistory();
    render(<ReviewScreen />);

    const ledger = await screen.findByRole("region", { name: "Side by side" });
    expect(within(ledger).queryByRole("row", { name: /Level\s*Same\s*Staff/ })).not.toBeInTheDocument();
    const reveal = within(ledger).getByRole("button", { name: "Show 8 matching fields" });
    expect(reveal).toHaveAttribute("aria-expanded", "false");
    expect(within(ledger).getByRole("row", { name: /8\s*fields Same/ })).toBeInTheDocument();

    await userEvent.click(reveal);
    const levelRow = within(ledger).getByRole("row", { name: /Level\s*Same\s*Staff/ });
    expect(within(levelRow).getAllByText("Staff")).toHaveLength(1);
    expect(within(ledger).getByRole("button", { name: "Hide 8 matching fields" })).toHaveAttribute("aria-expanded", "true");

    // The careers page leaves the app in a new tab, with the external glyph.
    const earlierSite = within(ledger).getByRole("link", { name: msg("duplicates-comparison-ledger-careers-page-of", { side: "earlier" }) });
    expect(earlierSite).toHaveAttribute("href", "https://example.test/jobs/a");
    expect(earlierSite).toHaveAttribute("target", "_blank");
    expect(earlierSite.querySelector("svg")).not.toBeNull();
    expect(within(ledger).getByRole("link", { name: msg("duplicates-comparison-ledger-careers-page-of", { side: "newer" }) }))
      .toHaveAttribute("href", "https://example.test/jobs/b");
    // The role stays in the app: same tab, opened over the queue, no external glyph.
    const newerRole = within(ledger).getByRole("link", { name: msg("duplicates-comparison-ledger-role-details-of", { side: "newer" }) });
    expect(newerRole).toHaveAttribute("href", "/company/openai/job/2");
    expect(newerRole).not.toHaveAttribute("target");
    expect(newerRole.querySelector("svg")).toBeNull();
    expect(within(ledger).getByRole("link", { name: msg("duplicates-comparison-ledger-role-details-of", { side: "earlier" }) }))
      .toHaveAttribute("href", "/company/openai/job/1");
    await userEvent.click(newerRole);
    expect(openJob).toHaveBeenCalledWith(2, "openai");
    // The two words differ, and the row is not compared: the addresses always do.
    expect(msg("duplicates-comparison-ledger-role-details")).not.toBe(msg("duplicates-comparison-ledger-careers-page"));
    const links = within(ledger).getByRole("row", { name: new RegExp(`^${msg("duplicates-comparison-ledger-links")}`) });
    expect(within(links).queryByText(msg("duplicates-comparison-ledger-different"))).toBeNull();
    // A requisition ID differs in every pair, so it is no evidence and has no row.
    expect(within(ledger).queryByText("REQ-B")).toBeNull();
    // The role wording, never an internal id; and each link's name starts with
    // the words it shows (WCAG 2.5.3), so a voice user can say what they see.
    expect(within(ledger).queryByText(/Job #/)).toBeNull();
    for (const link of within(ledger).getAllByRole("link")) {
      const shown = link.textContent?.trim() ?? "";
      expect(shown).not.toBe("");
      expect(link.getAttribute("aria-label") ?? shown).toContain(shown);
    }
  });

  it("shows local-model advice without applying a verdict", async () => {
    mockList(list());
    mockHistory();
    vi.mocked(api.analyzeLineageLink).mockResolvedValue(relationshipAssessmentFixture({
      assessment: {
        recommendation: "confirmed",
        confidence: 0.91,
        summary: "Same title, location, and responsibilities; the newer record is a relist.",
        matching_evidence: ["Identical responsibilities"],
        differences: ["New requisition identifier"],
      },
    }));
    render(<ReviewScreen />);

    const console = await screen.findByRole("region", { name: "Make a decision" });
    const actions = within(console).getAllByRole("button");
    expect(actions[0]).toHaveAccessibleName(/Different roles/);
    expect(actions[actions.length - 1]).toHaveAccessibleName("Ask the model");
    expect(within(console).queryByText("System normalization")).not.toBeInTheDocument();
    await userEvent.click(within(console).getByRole("button", { name: "Ask the model" }));

    const advice = await screen.findByRole("region", { name: "Local model assessment" });
    expect(advice).toHaveTextContent("Likely the same role");
    expect(advice.closest(".review-decision-console")).toHaveClass("has-ai-response");
    expect(advice.querySelector("p")).toHaveTextContent("Same title, location, and responsibilities; the newer record is a relist.");
    expect(screen.getByText("91%")).toBeInTheDocument();
    expect(api.reviewLineageLink).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: /Same role/ })).toBeEnabled();
  });

  it("offers the same first-slot AI advisory for a twin proposal", async () => {
    const twin = twinList();
    vi.mocked(api.lineageReview).mockResolvedValue({ total: 0, limit: 50, offset: 0, items: [] });
    vi.mocked(api.twinReview).mockResolvedValue(twin);
    mockHistory();
    vi.mocked(api.analyzeTwinLink).mockResolvedValue(relationshipAssessmentFixture({
      assessment: {
        recommendation: "uncertain",
        confidence: 0.62,
        summary: "The openings are close, but the description differences may be meaningful.",
        matching_evidence: [],
        differences: ["Different scope"],
      },
    }));
    render(<ReviewScreen />);

    await userEvent.click(await screen.findByRole("button", { name: "Ask the model" }));
    expect(api.analyzeTwinLink).toHaveBeenCalledWith(19);
    expect(await screen.findByRole("region", { name: "Local model assessment" })).toHaveTextContent("Uncertain");
  });

  it("rejects via the button", async () => {
    mockList(list());
    mockHistory();
    vi.mocked(api.reviewLineageLink).mockResolvedValue(
      duplicateVerdictFixture({ status: "rejected", lineages: 0, decision: "different" }),
    );
    const user = userEvent.setup();
    render(<ReviewScreen />);
    await screen.findByText("1 pair left in the queue");
    await user.click(screen.getByRole("button", { name: /Different roles/ }));
    expect(api.reviewLineageLink).toHaveBeenCalledWith(7, "rejected");
  });

  /* The queue count is the BACKLOG, not the page. Counting what was fetched
   * (50 from each endpoint) would sit at 100 whatever the backlog, and a
   * verdict would drop it to 99 only for the reload to fetch another full
   * page and put it back. */
  it("states the whole backlog and keeps the number moving after a verdict", async () => {
    const pending = (id: number, jobId: number, priorId: number): DuplicateReviewItem => ({
      link: duplicateProposalFixture({ id, job_id: jobId, prior_job_id: priorId }),
      prior: jobDetailRowFixture({ id: priorId, req_id: `A${priorId}`, title: "Staff SWE" }),
      job: jobDetailRowFixture({ id: jobId, req_id: `B${jobId}`, title: "Staff SWE, Core" }),
      diff: {},
    });
    // A page far smaller than the set behind it.
    vi.mocked(api.lineageReview).mockResolvedValue({
      total: 275, limit: 50, offset: 0, items: [pending(7, 2, 1), pending(8, 4, 3)],
    });
    vi.mocked(api.twinReview).mockResolvedValue({
      total: 201, limit: 50, offset: 0, items: [],
    });
    mockHistory();
    vi.mocked(api.reviewLineageLink).mockResolvedValue(
      duplicateVerdictFixture({ status: "rejected", lineages: 0, decision: "different" }),
    );
    const user = userEvent.setup();
    render(<ReviewScreen />);

    expect(await screen.findByText("476 pairs left in the queue")).toBeInTheDocument();

    // The reload after the verdict returns another full page; the count must
    // follow the server's own count down, not spring back to the page size.
    vi.mocked(api.lineageReview).mockResolvedValue({
      total: 274, limit: 50, offset: 0, items: [pending(8, 4, 3)],
    });
    await user.click(screen.getByRole("button", { name: /Different roles/ }));

    expect(await screen.findByText("475 pairs left in the queue")).toBeInTheDocument();
    // Two reads of the queue (each load also asks how many automatic matches wait).
    const queueReads = () =>
      vi.mocked(api.lineageReview).mock.calls.filter(
        ([params]) => params?.confidence === "suspected",
      ).length;
    await waitFor(() => expect(queueReads()).toBe(2));
    expect(screen.getByText("475 pairs left in the queue")).toBeInTheDocument();
  });

  it("confirms a queue verdict with a toast whose Undo returns the pair to the queue", async () => {
    mockList(list());
    mockHistory();
    vi.mocked(api.reviewLineageLink).mockResolvedValue(duplicateVerdictFixture());
    const user = userEvent.setup();
    render(<ReviewScreen />);
    await screen.findByText("1 pair left in the queue");

    // The verdict lands, the pair leaves the queue, the toast offers the way back.
    vi.mocked(api.lineageReview).mockResolvedValue({ total: 0, limit: 50, offset: 0, items: [] });
    await user.click(screen.getByRole("button", { name: /Same role/ }));
    expect(api.reviewLineageLink).toHaveBeenCalledWith(7, "confirmed");
    const toast = await screen.findByRole("status");
    expect(toast).toHaveTextContent("Marked as same role");
    expect(await screen.findByText(/Queue clear/)).toBeInTheDocument();

    // Undo sends the `pending` verdict and the queue is reloaded with the pair back.
    vi.mocked(api.reviewLineageLink).mockResolvedValue(
      duplicateVerdictFixture({ status: "pending", reviewed_at: null, lineages: 0, decision: null }),
    );
    mockList(list());
    await user.click(within(toast).getByRole("button", { name: "Undo" }));
    expect(api.reviewLineageLink).toHaveBeenLastCalledWith(7, "pending");
    expect(await screen.findByText("1 pair left in the queue")).toBeInTheDocument();
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("says so when Undo keeps a decision made later on the same postings", async () => {
    mockList(list());
    mockHistory();
    vi.mocked(api.reviewLineageLink).mockResolvedValue(duplicateVerdictFixture());
    const user = userEvent.setup();
    render(<ReviewScreen />);
    await screen.findByText("1 pair left in the queue");
    await user.click(screen.getByRole("button", { name: /Same role/ }));
    const toast = await screen.findByRole("status");

    // The server put the pair back but kept a twin decided since.
    vi.mocked(api.reviewLineageLink).mockResolvedValue(
      duplicateVerdictFixture({
        status: "pending", reviewed_at: null, lineages: 0, decision: null, kept: [{ link: "twin", id: 31 }],
      }),
    );
    await user.click(within(toast).getByRole("button", { name: "Undo" }));
    expect(api.reviewLineageLink).toHaveBeenLastCalledWith(7, "pending");
    expect(await screen.findByRole("status")).toHaveTextContent(
      "Undone. Your later decision on these postings stays.",
    );
    expect(screen.queryByRole("button", { name: "Undo" })).not.toBeInTheDocument();
  });

  it("undoes a twin-proposal verdict through the twin endpoint", async () => {
    const twin = twinList();
    vi.mocked(api.lineageReview).mockResolvedValue({ total: 0, limit: 50, offset: 0, items: [] });
    vi.mocked(api.twinReview).mockResolvedValue(twin);
    mockHistory();
    vi.mocked(api.reviewTwinLink).mockResolvedValue(twinVerdictFixture({ lineages: 0 }));
    const user = userEvent.setup();
    render(<ReviewScreen />);
    await screen.findByText("1 pair left in the queue");

    await user.click(screen.getByRole("button", { name: /Related roles/ }));
    expect(api.reviewTwinLink).toHaveBeenCalledWith(19, "confirmed");
    const toast = await screen.findByRole("status");
    expect(toast).toHaveTextContent("Marked as related roles");
    await user.click(within(toast).getByRole("button", { name: "Undo" }));
    expect(api.reviewTwinLink).toHaveBeenLastCalledWith(19, "pending");
    expect(api.reviewLineageLink).not.toHaveBeenCalled();
  });

  it("reports a verdict that failed to land as an error with nothing to undo, and brings the pair back", async () => {
    mockList(list());
    mockHistory();
    vi.mocked(api.reviewLineageLink).mockRejectedValue(
      new ApiError("boom", 409, "verdict-decided"),
    );
    const user = userEvent.setup();
    render(<ReviewScreen />);
    await screen.findByText("1 pair left in the queue");

    await user.click(screen.getByRole("button", { name: /Same role/ }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(`Couldn't record the verdict: ${msg("error-verdict-decided")}`);
    expect(alert).not.toHaveTextContent("boom");
    expect(within(alert).queryByRole("button", { name: "Undo" })).not.toBeInTheDocument();
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    // The reload restores the truth: the verdict did not land, so the pair is still to decide.
    expect(await screen.findByText("1 pair left in the queue")).toBeInTheDocument();
  });

  it("atomically converts a duplicate proposal when marked as a twin", async () => {
    mockList(list());
    mockHistory();
    vi.mocked(api.reviewLineageLink).mockResolvedValue(
      duplicateVerdictFixture({ status: "rejected", decision: "twin", twin_link_id: 19, lineages: 0 }),
    );
    render(<ReviewScreen />);

    await userEvent.click(await screen.findByRole("button", { name: /Related roles/ }));

    expect(api.reviewLineageLink).toHaveBeenCalledWith(7, "twin");
  });

  /* A pair the detector matched on its own counts toward role age before
     anyone looks at it. Its own tab lists those, weakest first, decided with
     the same keys. */
  it("lists pairs matched automatically, weakest first, and decides them with the same controls", async () => {
    const auto = (): DuplicateReviewList => ({
      total: 1, limit: 50, offset: 0,
      items: [{ ...duplicatePair(), link: duplicateProposalFixture({ id: 31, confidence: "auto", score: 0.83 }) }],
    });
    let autoLeft = auto();
    vi.mocked(api.lineageReview).mockImplementation(
      async (params) => (params?.confidence === "auto" ? autoLeft : list()),
    );
    vi.mocked(api.twinReview).mockResolvedValue({ total: 0, limit: 50, offset: 0, items: [] });
    mockHistory();
    vi.mocked(api.reviewLineageLink).mockResolvedValue(duplicateVerdictFixture());
    const user = userEvent.setup();
    render(<ReviewScreen />);

    // The default queue is unchanged: possible matches only.
    expect(await screen.findByText("1 pair left in the queue")).toBeInTheDocument();
    const tab = screen.getByRole("tab", { name: /Matched automatically/ });
    expect(tab).toHaveTextContent("1");

    await user.click(tab);
    expect(await screen.findByText("1 pair matched automatically, not yet checked")).toBeInTheDocument();
    expect(api.lineageReview).toHaveBeenCalledWith(
      expect.objectContaining({ status: "pending", confidence: "auto", order: "weakest" }),
    );
    expect(screen.getByLabelText("System similarity 83%")).toBeInTheDocument();

    autoLeft = { total: 0, limit: 50, offset: 0, items: [] };
    await user.click(screen.getByRole("button", { name: /Different roles/ }));
    expect(api.reviewLineageLink).toHaveBeenCalledWith(31, "rejected");
    await waitFor(() => expect(screen.getByText("Nothing to check")).toBeInTheDocument());
  });

  /* A twin matched automatically (same title, one department) is
     checked in the same tab as auto duplicates, weakest first, and decided on
     its own endpoint. */
  it("lists twins matched automatically beside duplicates, weakest first", async () => {
    const empty = { total: 0, limit: 50, offset: 0, items: [] };
    vi.mocked(api.lineageReview).mockImplementation(
      async (params) =>
        params?.confidence === "auto"
          ? { total: 1, limit: 50, offset: 0, items: [{ ...duplicatePair(), link: duplicateProposalFixture({ id: 31, confidence: "auto", score: 0.97 }) }] }
          : list(),
    );
    // A different pair from the duplicate's: one pair is counted once.
    const { job, prior, diff } = duplicatePair();
    const autoTwin = {
      link: twinProposalFixture({ id: 77, confidence: "auto", score: 0.91, job_id: 801, prior_job_id: 800 }),
      job: { ...job, id: 801 },
      prior: { ...prior, id: 800 },
      diff,
      description_diff: descriptionDiffFixture,
    };
    vi.mocked(api.twinReview).mockImplementation(
      async (params) =>
        params?.confidence === "auto" ? { total: 1, limit: 50, offset: 0, items: [autoTwin] } : empty,
    );
    mockHistory();
    vi.mocked(api.reviewTwinLink).mockResolvedValue(twinVerdictFixture());
    const user = userEvent.setup();
    render(<ReviewScreen />);

    const tab = await screen.findByRole("tab", { name: /Matched automatically/ });
    await waitFor(() => expect(tab).toHaveTextContent("2"));
    await user.click(tab);
    expect(await screen.findByText("2 pairs matched automatically, not yet checked")).toBeInTheDocument();
    // The twin's 91% is weaker than the duplicate's 97%: it leads.
    expect(screen.getByLabelText("System similarity 91%")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /Different roles/ }));
    expect(api.reviewTwinLink).toHaveBeenCalledWith(77, "rejected");
  });

  /* A fresh install: no scan has found a pair, so nothing waits in either
     list and nothing was decided. Calling that a cleared queue, with a way
     into an empty Decided list, tells a newcomer nothing; the screen says
     what it is for instead. */
  it("says what the screen is for while no pair has been found", async () => {
    mockList({ total: 0, limit: 50, offset: 0, items: [] });
    mockHistory();
    render(<ReviewScreen />);

    expect(await screen.findByText(msg("duplicates-review-screen-none-found"))).toBeInTheDocument();
    expect(screen.getByText(msg("duplicates-review-screen-none-found-why"))).toBeInTheDocument();
    expect(screen.getByText(msg("duplicates-review-screen-none-found-yet"))).toBeInTheDocument();
    expect(screen.queryByText(msg("duplicates-review-screen-queue-clear"))).toBeNull();
    expect(screen.queryByRole("button", { name: msg("duplicates-review-screen-open-decided") })).toBeNull();

    // The automatic list is just as empty, and says the same.
    await userEvent.setup().click(screen.getByRole("tab", { name: /Matched automatically/ }));
    expect(await screen.findByText(msg("duplicates-review-screen-none-found"))).toBeInTheDocument();
    expect(screen.queryByText(msg("duplicates-review-screen-nothing-to-check"))).toBeNull();
  });

  it("calls an empty queue clear once a pair has been decided, its way out on a row of its own", async () => {
    mockList({ total: 0, limit: 50, offset: 0, items: [] });
    mockHistory({ total: 1, limit: 20, offset: 0, items: [decided(duplicatePair())] });
    const user = userEvent.setup();
    render(<ReviewScreen />);

    expect(await screen.findByText(msg("duplicates-review-screen-queue-clear"))).toBeInTheDocument();
    expect(screen.queryByText(msg("duplicates-review-screen-none-found"))).toBeNull();
    const open = screen.getByRole("button", { name: msg("duplicates-review-screen-open-decided") });
    // The button sits under the sentence, not inside its line.
    const sentence = screen.getByText(msg("duplicates-review-screen-every-close-pair-on-your"));
    expect(sentence.contains(open)).toBe(false);
    expect(open.closest(".empty-actions")).not.toBeNull();

    await user.click(open);
    expect(screen.getByRole("tab", { name: /Decided/ })).toHaveAttribute("aria-selected", "true");
  });

  it("calls the queue clear while pairs matched automatically still wait", async () => {
    vi.mocked(api.lineageReview).mockImplementation(async (q) =>
      q?.confidence === "auto"
        ? { total: 3, limit: 1, offset: 0, items: [] }
        : { total: 0, limit: 50, offset: 0, items: [] },
    );
    vi.mocked(api.twinReview).mockResolvedValue({ total: 0, limit: 50, offset: 0, items: [] });
    mockHistory();
    render(<ReviewScreen />);

    expect(await screen.findByText(msg("duplicates-review-screen-queue-clear"))).toBeInTheDocument();
    expect(screen.queryByText(msg("duplicates-review-screen-none-found"))).toBeNull();
  });

  /* Which empty state is true depends on Decided, read beside the queue. An
     empty queue that lands first must not flash "Queue clear" at a newcomer. */
  it("holds the empty state until Decided has been read", async () => {
    mockList({ total: 0, limit: 50, offset: 0, items: [] });
    const lineage = deferred<DuplicateReviewSummaryList>();
    vi.mocked(api.lineageReviewHistory).mockReturnValue(lineage.promise);
    vi.mocked(api.twinReviewHistory).mockResolvedValue({ total: 0, limit: 20, offset: 0, items: [] });
    render(<ReviewScreen />);

    await waitFor(() => expect(api.lineageReview).toHaveBeenCalled());
    await act(async () => {});
    expect(screen.queryByText(msg("duplicates-review-screen-queue-clear"))).toBeNull();
    expect(screen.queryByText(msg("duplicates-review-screen-none-found"))).toBeNull();

    await act(async () => lineage.resolve({ total: 0, limit: 20, offset: 0, items: [] }));
    expect(await screen.findByText(msg("duplicates-review-screen-none-found"))).toBeInTheDocument();
  });

  it("falls back to the queue clear when Decided fails to load", async () => {
    mockList({ total: 0, limit: 50, offset: 0, items: [] });
    vi.mocked(api.lineageReviewHistory).mockRejectedValue(new Error("offline"));
    vi.mocked(api.twinReviewHistory).mockResolvedValue({ total: 0, limit: 20, offset: 0, items: [] });
    render(<ReviewScreen />);

    expect(await screen.findByText(msg("duplicates-review-screen-queue-clear"))).toBeInTheDocument();
  });

  it("shows reviewed pairs with the decision and system score", async () => {
    mockList({ total: 0, limit: 50, offset: 0, items: [] });
    mockHistory({
      total: 1,
      limit: 20,
      offset: 0,
      items: [decided({
        ...duplicatePair(),
        link: {
          ...duplicatePair().link,
          status: "rejected",
          decision: "different",
          score: 0.972,
          reviewed_at: "2026-07-15T15:00:00Z",
        },
      })],
    });
    render(<ReviewScreen />);

    await userEvent.click(await screen.findByRole("tab", { name: /Decided/ }));
    const history = await screen.findByRole("region", { name: "Decided" });
    expect(history).toHaveTextContent("Different");
    expect(history).toHaveTextContent("Staff SWE");
    expect(history).toHaveTextContent("Staff SWE, Core");
    // The score is said as the queue says it: a percentage, not a raw fraction.
    expect(history).toHaveTextContent("97%");
    expect(history).not.toHaveTextContent("0.972");
  });

  // A reload must not land on the queue with the archive's filter and search
  // gone. The tab, the filter and the search are the address.
  it("opens the tab, filter and search the address names, and writes each change back to it", async () => {
    mockList(list());
    const decidedAs = (title: string, decision: "twin" | "different", id: number) => decided({
      ...duplicatePair(),
      prior: jobDetailRowFixture({ id: id * 10, req_id: `P${id}`, title }),
      job: jobDetailRowFixture({ id: id * 10 + 1, req_id: `J${id}`, title: `${title}, II` }),
      link: { ...duplicatePair().link, id, status: "rejected", decision, score: 0.9, reviewed_at: "2026-07-15T15:00:00Z" },
    });
    mockHistory({
      total: 3, limit: 20, offset: 0,
      items: [decidedAs("Staff PM", "twin", 1), decidedAs("Staff Designer", "twin", 2), decidedAs("Staff PM Ads", "different", 3)],
    });
    let search = "";
    const Probe = () => {
      search = useLocation().search;
      return null;
    };
    rtlRender(
      <MemoryRouter initialEntries={["/review?view=history&decision=twin&q=PM"]}>
        <ToastProvider><ReviewScreen /><Probe /></ToastProvider>
      </MemoryRouter>,
    );

    expect(await screen.findByRole("tab", { name: /Decided/ })).toHaveAttribute("aria-selected", "true");
    const history = await screen.findByRole("region", { name: "Decided" });
    expect(within(history).getByRole("button", { name: "Related roles" })).toHaveAttribute("aria-pressed", "true");
    expect(within(history).getByRole("searchbox", { name: "Search decisions" })).toHaveValue("PM");
    await waitFor(() => expect(history.getElementsByClassName("review-history-summary")).toHaveLength(1));
    expect(history).toHaveTextContent("Staff PM");
    expect(history).not.toHaveTextContent("Staff Designer");

    await userEvent.click(within(history).getByRole("button", { name: "All decisions" }));
    await userEvent.type(within(history).getByRole("searchbox", { name: "Search decisions" }), " Ads");
    expect(new URLSearchParams(search).get("q")).toBe("PM Ads");
    expect(new URLSearchParams(search).has("decision")).toBe(false);

    await userEvent.click(screen.getByRole("tab", { name: /Queue/ }));
    expect(new URLSearchParams(search).has("view")).toBe(false);
  });

  // The router hands each write the params of its LAST render, so a filter
  // click and a keystroke before the screen re-renders could each write over
  // the other and lose the filter.
  it("keeps the filter and the search when both change before the screen re-renders", async () => {
    mockList(list());
    mockHistory({ total: 0, limit: 20, offset: 0, items: [] });
    let search = "";
    const Probe = () => {
      search = useLocation().search;
      return null;
    };
    rtlRender(
      <MemoryRouter initialEntries={["/review?view=history"]}>
        <ToastProvider><ReviewScreen /><Probe /></ToastProvider>
      </MemoryRouter>,
    );
    const history = await screen.findByRole("region", { name: "Decided" });
    const filter = within(history).getByRole("button", { name: "Different roles" });
    const box = within(history).getByRole("searchbox", { name: "Search decisions" });

    act(() => {
      fireEvent.click(filter);
      fireEvent.change(box, { target: { value: "REQ-OLD" } });
    });

    await waitFor(() => expect(new URLSearchParams(search).get("q")).toBe("REQ-OLD"));
    expect(new URLSearchParams(search).get("decision")).toBe("different");
  });

  // The archive names the company, not its slug ("palo-alto-networks"), so a
  // search by the name finds it.
  it("names a decided pair's company as the company does, and finds it by that name", async () => {
    setCompanyNames({ "palo-alto-networks": "Palo Alto Networks" });
    mockList({ total: 0, limit: 50, offset: 0, items: [] });
    mockHistory({
      total: 1, limit: 20, offset: 0,
      items: [decided({
        ...duplicatePair(),
        prior: jobDetailRowFixture({ id: 1, req_id: "A", title: "Director, Audit Data", company: "palo-alto-networks" }),
        job: jobDetailRowFixture({ id: 2, req_id: "B", title: "Director, Audit Data II", company: "palo-alto-networks" }),
        link: { ...duplicatePair().link, status: "rejected", decision: "different", reviewed_at: "2026-07-15T15:00:00Z" },
      })],
    });
    render(<ReviewScreen />);

    await userEvent.click(await screen.findByRole("tab", { name: /Decided/ }));
    const history = await screen.findByRole("region", { name: "Decided" });
    expect(history).toHaveTextContent("Palo Alto Networks ·");
    expect(history).not.toHaveTextContent("palo-alto-networks");
    await userEvent.type(within(history).getByRole("searchbox", { name: "Search decisions" }), "Palo Alto");
    expect(history.getElementsByClassName("review-history-summary")).toHaveLength(1);
  });

  it("deduplicates converted pair artifacts without losing the detector score", async () => {
    mockList({ total: 0, limit: 50, offset: 0, items: [] });
    const original = decided({
      ...duplicatePair(),
      link: { ...duplicatePair().link, status: "rejected", decision: "twin" as const, score: 0.981, reviewed_at: "2026-07-15T15:00:00Z" },
    });
    vi.mocked(api.lineageReviewHistory).mockResolvedValue({ total: 1, limit: 20, offset: 0, items: [original] });
    vi.mocked(api.twinReviewHistory).mockResolvedValue({
      total: 1,
      limit: 20,
      offset: 0,
      items: [{
        link: twinProposalFixture({
          id: 19, job_id: original.link.job_id, prior_job_id: original.link.prior_job_id,
          status: "confirmed", decision: "twin", score: null, reviewed_at: original.link.reviewed_at,
        }),
        job: original.job,
        prior: original.prior,
        diff: original.diff,
      }],
    });
    render(<ReviewScreen />);

    await userEvent.click(await screen.findByRole("tab", { name: /Decided 1/ }));
    const history = screen.getByRole("region", { name: "Decided" });
    expect(history.getElementsByClassName("review-history-summary")).toHaveLength(1);
    expect(history).toHaveTextContent("98%");
  });

  /* The Decided list is the summary form, so a row reads its two postings whole
     only when it opens: the ledger and the description comparison come from
     that read, and the decision bar is there before it lands. */
  it("expands a past decision and lets the reviewer reclassify it", async () => {
    mockList({ total: 0, limit: 50, offset: 0, items: [] });
    const reviewed = decided({
      ...duplicatePair(),
      link: { ...duplicatePair().link, status: "rejected", decision: "different" as const, reviewed_at: "2026-07-15T15:00:00Z" },
    });
    mockHistory({ total: 1, limit: 20, offset: 0, items: [reviewed] });
    const postings = deferred<void>();
    vi.mocked(api.job).mockImplementation(async (id: number) => {
      await postings.promise;
      return jobDetailFixture({
        id,
        req_id: id === 1 ? "A" : "B",
        title: id === 1 ? "Staff SWE" : "Staff SWE, Core",
        description_sections: [{ key: "about", title: "About", content: id === 1 ? "Own the payments API." : "Own the core API." }],
      });
    });
    vi.mocked(api.reviewLineageLink).mockResolvedValue(
      duplicateVerdictFixture({ status: "rejected", decision: "twin", twin_link_id: 19, lineages: 0 }),
    );
    render(<ReviewScreen />);

    await userEvent.click(await screen.findByRole("tab", { name: /Decided/ }));
    expect(api.job).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: /Staff SWE.*Staff SWE, Core/ }));

    const editor = screen.getByRole("region", { name: "Change decision" });
    expect(editor).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Side by side" })).not.toBeInTheDocument();
    expect(api.job).toHaveBeenCalledWith(1, expect.any(AbortSignal));
    expect(api.job).toHaveBeenCalledWith(2, expect.any(AbortSignal));
    postings.resolve();
    const comparison = await screen.findByRole("region", { name: "Side by side" });
    expect(screen.getByRole("region", { name: "Description comparison" })).toHaveTextContent("Own the core API.");
    expect(within(comparison).getByRole("link", { name: msg("duplicates-comparison-ledger-role-details-of", { side: "earlier" }) }))
      .toHaveAttribute("href", "/company/openai/job/1");
    expect(document.getElementsByClassName("review-panel")).toHaveLength(0);
    expect(within(editor).getByRole("button", { name: /Different roles/ })).toBeDisabled();
    await userEvent.click(within(editor).getByRole("button", { name: /Related roles/ }));
    expect(api.reviewLineageLink).toHaveBeenCalledWith(7, "twin");
    // The row stays in place with its controls, so there is no toast to undo from.
    await waitFor(() => expect(api.lineageReviewHistory).toHaveBeenCalledTimes(2));
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("shows full descriptions and marks passages that differ", async () => {
    const data = list();
    data.items[0].prior.description_sections = [{
      key: "basic_qualifications",
      title: "Basic qualifications",
      content: "- Shared requirement\n- 5+ years in security compliance",
    }];
    data.items[0].job.description_sections = [{
      key: "basic_qualifications",
      title: "Basic qualifications",
      content: "• SHARED REQUIREMENT\n- Experience with security compliance",
    }];
    mockList(data);
    mockHistory();
    const user = userEvent.setup();
    render(<ReviewScreen />);

    const comparison = await screen.findByRole("region", { name: "Description comparison" });
    expect(comparison).toHaveTextContent("Shared requirement");
    expect(comparison).toHaveTextContent("5+ years in security compliance");
    expect(comparison).toHaveTextContent("Experience with security compliance");
    expect(screen.getAllByText("Changed passage")).toHaveLength(2);

    await user.click(screen.getByRole("button", { name: "Show differences only" }));
    expect(screen.getByRole("button", { name: "Show full descriptions" })).toHaveAttribute("aria-pressed", "true");
    expect(comparison).not.toHaveTextContent("Shared requirement");
  });

  /* The model's advice belongs to the pair it was asked about. Undo puts the
     decided pair back in front of the one the advice is about, so the advice
     must not appear above the other pair's ledger. */
  describe("the model's advice", () => {
    const pairA = () => queuePair(7, "Staff PM, Ads", 0.95);
    const pairB = () => queuePair(8, "Staff PM, Search", 0.9);
    const sameRole = relationshipAssessmentFixture({
      assessment: {
        recommendation: "confirmed",
        confidence: 0.92,
        summary: "The same opening listed twice.",
        matching_evidence: [],
        differences: [],
      },
    });

    async function decideAThenAskAboutB(analysis: Promise<typeof sameRole>) {
      vi.mocked(api.lineageReview).mockResolvedValue(queueOf(pairA(), pairB()));
      vi.mocked(api.twinReview).mockResolvedValue({ total: 0, limit: 50, offset: 0, items: [] });
      mockHistory();
      vi.mocked(api.reviewLineageLink).mockResolvedValue(duplicateVerdictFixture());
      vi.mocked(api.analyzeLineageLink).mockReturnValue(analysis);
      const user = userEvent.setup();
      render(<ReviewScreen />);
      expect(await screen.findByText("2 pairs left in the queue")).toBeInTheDocument();

      vi.mocked(api.lineageReview).mockResolvedValue(queueOf(pairB()));
      await user.keyboard("d");
      expect(api.reviewLineageLink).toHaveBeenCalledWith(7, "confirmed");
      const toast = await screen.findByRole("status");
      await screen.findByRole("row", { name: /Staff PM, Search/ });
      await user.click(screen.getByRole("button", { name: "Ask the model" }));
      expect(api.analyzeLineageLink).toHaveBeenCalledWith(8);
      // Undo brings A back in front of B.
      vi.mocked(api.lineageReview).mockResolvedValue(queueOf(pairA(), pairB()));
      vi.mocked(api.reviewLineageLink).mockResolvedValue(
        duplicateVerdictFixture({ status: "pending", reviewed_at: null, lineages: 0, decision: null }),
      );
      return { user, toast };
    }

    it("is not shown on the pair Undo brings back", async () => {
      const { user, toast } = await decideAThenAskAboutB(Promise.resolve(sameRole));
      // Positive control: the advice is on screen above B.
      expect(await screen.findByRole("region", { name: "Local model assessment" })).toHaveTextContent(
        "The same opening listed twice.",
      );

      await user.click(within(toast).getByRole("button", { name: "Undo" }));
      expect(api.reviewLineageLink).toHaveBeenLastCalledWith(7, "pending");
      await screen.findByRole("row", { name: /Staff PM, Ads/ });
      expect(screen.queryByRole("region", { name: "Local model assessment" })).not.toBeInTheDocument();
      expect(screen.queryByText("The same opening listed twice.")).not.toBeInTheDocument();
    });

    it("drops an answer that lands after Undo has put another pair in front", async () => {
      const analysis = deferred<typeof sameRole>();
      const { user, toast } = await decideAThenAskAboutB(analysis.promise);

      await user.click(within(toast).getByRole("button", { name: "Undo" }));
      await screen.findByRole("row", { name: /Staff PM, Ads/ });
      await act(async () => analysis.resolve(sameRole));

      await waitFor(() => expect(screen.getByRole("button", { name: "Ask the model" })).toBeEnabled());
      expect(screen.getByRole("row", { name: /Staff PM, Ads/ })).toBeInTheDocument();
      expect(screen.queryByRole("region", { name: "Local model assessment" })).not.toBeInTheDocument();
    });
  });

  /* A verdict waits for the verdict alone. The Decided list is read again only
     while it is on screen, and a read issued before a verdict landed cannot put
     the pair it decided back in front. */
  it("reads no history for a verdict made with Decided closed, and takes the next key once the verdict lands", async () => {
    const pairA = queuePair(7, "Staff PM, Ads", 0.95);
    const pairB = queuePair(8, "Staff PM, Search", 0.9);
    const pairC = queuePair(9, "Staff PM, Maps", 0.85);
    vi.mocked(api.lineageReview).mockResolvedValue(queueOf(pairA, pairB, pairC));
    vi.mocked(api.twinReview).mockResolvedValue({ total: 0, limit: 50, offset: 0, items: [] });
    mockHistory();
    vi.mocked(api.reviewLineageLink).mockResolvedValue(duplicateVerdictFixture());
    const user = userEvent.setup();
    render(<ReviewScreen />);
    expect(await screen.findByText("3 pairs left in the queue")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole("tab", { name: /Decided/ })).toHaveTextContent("0"));
    expect(api.lineageReviewHistory).toHaveBeenCalledTimes(1);
    expect(api.twinReviewHistory).toHaveBeenCalledTimes(1);

    // The queue reads after each verdict hang until the test settles them.
    const afterA = deferred<DuplicateReviewList>();
    const afterB = deferred<DuplicateReviewList>();
    vi.mocked(api.lineageReview).mockImplementation((params) =>
      params?.confidence === "suspected"
        ? vi.mocked(api.reviewLineageLink).mock.calls.length === 1 ? afterA.promise : afterB.promise
        : Promise.resolve(queueOf()),
    );

    await user.keyboard("d");
    expect(api.reviewLineageLink).toHaveBeenLastCalledWith(7, "confirmed");
    await screen.findByRole("row", { name: /Staff PM, Search/ });
    // The verdict has landed and its queue read has not: the next key is taken.
    const verdictB = deferred<ReturnType<typeof duplicateVerdictFixture>>();
    vi.mocked(api.reviewLineageLink).mockReturnValueOnce(verdictB.promise);
    await user.keyboard("d");
    expect(api.reviewLineageLink).toHaveBeenLastCalledWith(8, "confirmed");
    await screen.findByRole("row", { name: /Staff PM, Maps/ });

    // The read issued after A landed lists B, which is still being decided: it
    // may not put B back in front.
    await act(async () => afterA.resolve(queueOf(pairB, pairC)));
    expect(screen.getByRole("row", { name: /Staff PM, Maps/ })).toBeInTheDocument();
    expect(screen.queryByRole("row", { name: /Staff PM, Search/ })).not.toBeInTheDocument();
    await act(async () => verdictB.resolve(duplicateVerdictFixture({ id: 8 })));
    await act(async () => afterB.resolve(queueOf(pairC)));
    expect(await screen.findByText("1 pair left in the queue")).toBeInTheDocument();

    // No history read for either verdict; the badge counts them.
    expect(api.lineageReviewHistory).toHaveBeenCalledTimes(1);
    expect(api.twinReviewHistory).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("tab", { name: /Decided/ })).toHaveTextContent("2");

    // Opening Decided reads it, once.
    mockHistory({ total: 2, limit: 20, offset: 0, items: [decided(pairB), decided(pairA)] });
    await user.click(screen.getByRole("tab", { name: /Decided/ }));
    const history = await screen.findByRole("region", { name: "Decided" });
    await waitFor(() => expect(history.getElementsByClassName("review-history-summary")).toHaveLength(2));
    expect(api.lineageReviewHistory).toHaveBeenCalledTimes(2);
    expect(api.twinReviewHistory).toHaveBeenCalledTimes(2);
  });
});

describe("the review screens in the reader's language", () => {
  beforeEach(() => vi.clearAllMocks());
  afterEach(() => activate("en"));

  it("says which check proposed a pair, and the verdict, in Spanish words, never the code", async () => {
    await activate("es");
    mockList(list());
    mockHistory();
    vi.mocked(api.reviewLineageLink).mockResolvedValue(duplicateVerdictFixture());
    const user = userEvent.setup();
    render(<ReviewScreen />);

    const similarity = await screen.findByRole("group", { name: new RegExp(msg("duplicates-review-screen-system-similarity")) });
    const detail = within(similarity).getByRole("tooltip");
    expect(detail).toHaveTextContent(msg("duplicates-proposed-as", { kind: "duplicate" }));
    expect(detail).not.toHaveTextContent(/duplicate/);

    vi.mocked(api.lineageReview).mockResolvedValue({ total: 0, limit: 50, offset: 0, items: [] });
    await user.keyboard("d");
    expect(await screen.findByRole("status")).toHaveTextContent(msg("duplicates-review-screen-marked-as", { decision: "duplicate" }));
  });

  it("tells a decided pair's story in Spanish: what proposed it, how often it changed, its score as the queue says it", async () => {
    await activate("es");
    mockList({ total: 0, limit: 50, offset: 0, items: [] });
    const pair = duplicatePair();
    vi.mocked(api.lineageReviewHistory).mockResolvedValue({ total: 0, limit: 20, offset: 0, items: [] });
    vi.mocked(api.twinReviewHistory).mockResolvedValue({
      total: 1,
      limit: 20,
      offset: 0,
      items: [{
        link: twinProposalFixture({
          id: 19, status: "confirmed", decision: "twin", score: 0.972, decision_changes: 2, reviewed_at: "2026-07-15T15:00:00Z",
        }),
        prior: listRow(pair.prior),
        job: listRow(pair.job),
        diff: pair.diff,
      }],
    });
    vi.mocked(api.job).mockImplementation(async (id: number) => jobDetailFixture({ id }));
    const user = userEvent.setup();
    render(<ReviewScreen />);

    await user.click(await screen.findByRole("tab", { name: new RegExp(msg("duplicates-review-history-decided")) }));
    const history = await screen.findByRole("region", { name: msg("duplicates-review-history-decided-2") });
    expect(history).toHaveTextContent("97%");
    expect(history).not.toHaveTextContent("0.972");

    await user.click(within(history).getByRole("button", { name: /Staff SWE.*Staff SWE, Core/ }));
    expect(history).toHaveTextContent(msg("duplicates-proposed-as", { kind: "twin" }));
    expect(history).toHaveTextContent(msg("duplicates-review-history-revised", { count: 2 }));
    expect(history).not.toHaveTextContent(/\btwin\b|2×/);
  });
});
