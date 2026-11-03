import { msg } from "../../test/msg";
import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { JobDetail } from "../../api";
import { api } from "../../api";
import { useJobActions, useJobWorkspace } from "../../context/JobWorkspace";
import { jobDetailFixture } from "../../test/fixtures";
import { CompareScreen } from "./CompareScreen";

vi.mock("../../api", async () => {
  const actual = await vi.importActual<typeof import("../../api")>("../../api");
  return {
    ...actual,
    api: { ...actual.api, job: vi.fn(), setFavorite: vi.fn(), dismissJob: vi.fn(), undismissJob: vi.fn() },
  };
});

vi.mock("../../context/JobWorkspace", () => ({ useJobWorkspace: vi.fn(), useJobActions: vi.fn() }));
type Raised = { text: string; tone?: string; action?: { label: string; onClick: () => void } };
const toasts = vi.hoisted(() => ({ toast: vi.fn((_raised: unknown) => ""), dismiss: vi.fn() }));
vi.mock("../../ui", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../../ui")>()),
  useToast: () => toasts,
}));
// The column verbs refresh the shell's counts after a save; the screen under
// test has no mission provider and the count is not what these cases pin.
vi.mock("../../context/MissionState", () => ({ useMissionActions: () => ({ refreshStats: vi.fn() }) }));

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((onResolve) => { resolve = onResolve; });
  return { promise, resolve };
}

// What `api.job` resolves to: the detail route's full response.
const job = (id: number, title: string, description?: string): JobDetail =>
  jobDetailFixture({
    id,
    req_id: `req-${id}`,
    title,
    ...(description === undefined ? {} : { description_text: description }),
  });

let compareIds = new Set([1, 2]);
let verbs: Record<string, ReturnType<typeof vi.fn>>;

beforeEach(() => {
  vi.clearAllMocks();
  compareIds = new Set([1, 2]);
  // The selection and the verbs come from two contexts, so the screen does
  // not re-render when someone else's compare state changes.
  // `compareHydrated` is the stored selection having been read at least once;
  // these cases are all about what happens after that, so they start hydrated.
  vi.mocked(useJobWorkspace).mockImplementation(
    () => ({ compareIds, compareHydrated: true }) as never,
  );
  // One verbs object per case, as the real provider gives one for the app's
  // life — a case that asserts on a verb reads the same function the screen got.
  verbs = {
    toggleCompare: vi.fn(),
    setCompare: vi.fn(),
    clearCompare: vi.fn(),
    dropCompare: vi.fn(),
    openJob: vi.fn(),
    openCompare: vi.fn(),
    savedChanged: vi.fn(),
  };
  vi.mocked(useJobActions).mockImplementation(() => verbs as never);
});

/* Hoisted, not built inline: `useCompareController` keys its request on the Set
   IDENTITY, so a mock returning a fresh Set each render restarts the fetch every
   render. That is an unbounded loop that can exhaust the worker's memory, and
   vitest then reports the file as passing with its tests absent from the
   count. */
const NOTHING_SELECTED = new Set<number>();

it("holds the empty state until the stored selection has been read", async () => {
  vi.mocked(useJobWorkspace).mockImplementation(
    () => ({ compareIds: NOTHING_SELECTED, compareHydrated: false }) as never,
  );
  render(<MemoryRouter><CompareScreen /></MemoryRouter>);

  // Someone arriving with four roles selected must not be told they have none.
  expect(screen.queryByText("Pick at least two")).toBeNull();
  expect(await screen.findByRole("status")).toHaveTextContent(msg("compare-screen-loading"));
});

it("says the selection is empty once the read has landed and it really is", () => {
  vi.mocked(useJobWorkspace).mockImplementation(
    () => ({ compareIds: NOTHING_SELECTED, compareHydrated: true }) as never,
  );
  render(<MemoryRouter><CompareScreen /></MemoryRouter>);

  expect(screen.getByText("Pick at least two")).toBeInTheDocument();
});

it("ignores a comparison response superseded by a newer selection", async () => {
  const old = deferred<void>();
  const current = deferred<void>();
  vi.mocked(api.job).mockImplementation((id: number) =>
    (id < 3 ? old.promise : current.promise).then(() => job(id, id < 3 ? "Superseded role" : "Current role")),
  );
  const view = render(<MemoryRouter><CompareScreen /></MemoryRouter>);

  compareIds = new Set([3, 4]);
  view.rerender(<MemoryRouter><CompareScreen /></MemoryRouter>);
  await act(async () => current.resolve());
  expect((await screen.findAllByText("Current role")).length).toBeGreaterThan(0);

  await act(async () => old.resolve());
  expect(screen.queryByText("Superseded role")).toBeNull();
  expect(screen.getAllByText("Current role").length).toBeGreaterThan(0);
});

it("renders a retryable error when a comparison request fails", async () => {
  vi.mocked(api.job).mockRejectedValue(new Error("offline"));
  render(<MemoryRouter><CompareScreen /></MemoryRouter>);

  expect(await screen.findByRole("alert")).toHaveTextContent(msg("compare-screen-load-failed"));
  expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();
});

/* The descriptions as aligned columns, not pairwise panels against a
   baseline: each role's description sits under its role, sections lined up
   across the columns, and what only some postings say is what shows first. */

const SHARED = "Own the roadmap for the platform team.";
const withDescription = (id: number, title: string, own: string) =>
  job(id, title, `${SHARED}\n${own}`);

function renderThree() {
  compareIds = new Set([1, 2, 3]);
  const jobs = [
    withDescription(1, "Staff PM, API", "First only: partner with the API org."),
    withDescription(2, "Principal PM, Platform", "Second only: own the ingest pipeline."),
    withDescription(3, "Director, Payments", "Third only: run the payments council."),
  ];
  vi.mocked(api.job).mockImplementation((id: number) => Promise.resolve(jobs.find((j) => j.id === id)!));
  return render(<MemoryRouter><CompareScreen /></MemoryRouter>);
}

it("lays the three descriptions out under their roles, differences first", async () => {
  renderThree();

  // Every role's own passage is on screen at once — no baseline, no fold —
  // and the passage all three share is folded behind one line per column.
  expect(await screen.findByText(/First only/)).toBeInTheDocument();
  expect(screen.getByText(/Second only/)).toBeInTheDocument();
  expect(screen.getByText(/Third only/)).toBeInTheDocument();
  expect(screen.queryByText(SHARED)).toBeNull();
  expect(screen.getAllByText("1 shared passage hidden")).toHaveLength(3);
  // What is unique is marked; the reader is told what the mark means.
  expect(screen.getByText(/Second only/)).toHaveClass("cmp-passage--unique");
  expect(screen.getByText("Amber passages are not in every posting.")).toBeInTheDocument();

  await userEvent.setup().click(screen.getByRole("button", { name: "Show full descriptions" }));
  expect(screen.getAllByText(SHARED)).toHaveLength(3);
  expect(screen.getAllByText(SHARED)[0]).not.toHaveClass("cmp-passage--unique");
});

it("keeps each posting in its own order under its role, and says when a role has none", async () => {
  compareIds = new Set([1, 2]);
  const a: JobDetail = { ...job(1, "A"), description_sections: [
    { key: "summary", title: "Summary", content: "Same summary." },
    { key: "quals", title: "Qualifications", content: "Ten years." },
  ] };
  // The route sends [] for a posting with no sections; the key is never absent.
  const b: JobDetail = { ...job(2, "B"), description_sections: [], description_text: null };
  vi.mocked(api.job).mockImplementation((id: number) => Promise.resolve(id === 1 ? a : b));
  render(<MemoryRouter><CompareScreen /></MemoryRouter>);

  // One row, one cell per role: A's sections in A's order, B's cell honest
  // about having nothing — never a row of empties per section.
  // The comparison's sections sit one level under its h1.
  const headings = await screen.findAllByRole("heading", { level: 2 });
  expect(headings.map((h) => h.textContent)).toEqual(["Summary", "Qualifications"]);
  expect(screen.getByText("No description for this role.")).toBeInTheDocument();
  // Against an empty column nothing is shared, so nothing is marked or
  // filtered — the passages read plain and the legend says why.
  expect(screen.getByText("Same summary.")).not.toHaveClass("cmp-passage--unique");
  expect(screen.getByText("These postings share no passages.")).toBeInTheDocument();
});

it("compresses the facts the roles agree on into one Same cell, and a run into one line", async () => {
  renderThree();
  await screen.findByText(/First only/);

  // Every fixture agrees on level, status and reposts (and more): the value
  // is said once with a Same mark, not three times.
  expect(screen.getAllByText("Same").length).toBeGreaterThan(0);
  // Status is stored lowercase and read as a word (CSS capitalizes it).
  expect(screen.queryAllByText("open")).toHaveLength(0);
  const show = screen.getByRole("button", { name: /Show \d+ matching fields/ });
  await userEvent.setup().click(show);
  expect(screen.getByText("open")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: /Hide \d+ matching fields/ })).toHaveAttribute("aria-expanded", "true");
});

it("carries the row's verbs on each column: Save writes the star, Not for me hides and leaves", async () => {
  renderThree();
  await screen.findByText(/First only/);
  vi.mocked(api.setFavorite).mockResolvedValue({ job_id: 2, is_favorite: true } as never);
  vi.mocked(api.dismissJob).mockResolvedValue({} as never);
  const user = userEvent.setup();

  const stars = screen.getAllByRole("button", { name: /Save|Unsave/ });
  expect(stars).toHaveLength(3);
  await user.click(stars[1]);
  expect(api.setFavorite).toHaveBeenCalledWith(2, true);

  await user.click(screen.getByRole("button", { name: "Not for me: Director, Payments" }));
  expect(api.dismissJob).toHaveBeenCalledWith(3);
  expect(verbs.toggleCompare).toHaveBeenCalledWith(3);
});

it("declines to mark or filter when the postings share nothing: every passage would be amber", async () => {
  compareIds = new Set([1, 2]);
  vi.mocked(api.job).mockImplementation((id: number) => Promise.resolve(job(id, `Role ${id}`, `Only in ${id}.`)));
  render(<MemoryRouter><CompareScreen /></MemoryRouter>);

  expect(await screen.findByText("Only in 1.")).toBeInTheDocument();
  expect(screen.getByText("Only in 1.")).not.toHaveClass("cmp-passage--unique");
  expect(screen.getByText("These postings share no passages.")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /Show (full descriptions|differences only)/ })).toBeNull();
});

/* Save then Unsave while the first write waits. Writes must reach the server
   in click order: a DELETE landing before its PUT would leave the role saved
   while the star says otherwise. `server` applies writes in the order they
   land, as the database does. */
function serverOfWrites() {
  const server = { saved: new Map<number, boolean>(), pending: [] as { id: number; on: boolean; settle: () => void; fail: () => void }[] };
  vi.mocked(api.setFavorite).mockImplementation((id: number, on: boolean) => new Promise((resolve, reject) => {
    server.pending.push({
      id, on,
      settle: () => { server.saved.set(id, on); resolve({ job_id: id, is_favorite: on } as never); },
      fail: () => reject(new Error("offline")),
    });
  }));
  return server;
}

it("sends a role's saves one at a time, so the server keeps the last click", async () => {
  renderThree();
  await screen.findByText(/First only/);
  const server = serverOfWrites();
  const user = userEvent.setup();
  const star = () => screen.getAllByRole("button", { name: /Save|Unsave/ })[1];

  await user.click(star()); // Save
  await user.click(star()); // Unsave, while the first is in the air
  expect(server.pending.map((w) => w.on)).toEqual([true]);

  await act(async () => server.pending[0].settle());
  expect(server.pending.map((w) => w.on)).toEqual([true, false]);
  await act(async () => server.pending[1].settle());

  expect(server.saved.get(2)).toBe(false);
  expect(star()).toHaveAccessibleName(/^Save/);
});

it("an older write failing never undoes a newer one", async () => {
  renderThree();
  await screen.findByText(/First only/);
  const server = serverOfWrites();
  const user = userEvent.setup();
  const star = () => screen.getAllByRole("button", { name: /Save|Unsave/ })[1];

  await user.click(star()); // Save: will fail
  await user.click(star()); // Unsave
  await user.click(star()); // Save again
  await act(async () => server.pending[0].fail());
  expect(star()).toHaveAttribute("aria-pressed", "true"); // the newest click still stands
  await act(async () => server.pending[1].settle());
  await act(async () => server.pending[2].settle());

  expect(server.saved.get(2)).toBe(true);
  expect(star()).toHaveAttribute("aria-pressed", "true");
});

it("the newest write failing shows what the server holds, and says so", async () => {
  renderThree();
  await screen.findByText(/First only/);
  const server = serverOfWrites();
  const user = userEvent.setup();
  const star = () => screen.getAllByRole("button", { name: /Save|Unsave/ })[1];

  await user.click(star()); // Save: lands
  await user.click(star()); // Unsave: fails
  await act(async () => server.pending[0].settle());
  await act(async () => server.pending[1].fail());

  expect(server.saved.get(2)).toBe(true);
  expect(star()).toHaveAttribute("aria-pressed", "true");
});

it("an Undo that fails takes the role back out of the comparison and offers Undo again", async () => {
  // An Undo that puts the role back in the comparison and sends the restore
  // without waiting would show it restored while the radar still hid it, with
  // an unhandled rejection and nothing to retry.
  renderThree();
  await screen.findByText(/First only/);
  vi.mocked(api.dismissJob).mockResolvedValue({} as never);
  vi.mocked(api.undismissJob).mockRejectedValueOnce(new Error("offline")).mockResolvedValueOnce({} as never);
  toasts.toast.mockClear();
  const user = userEvent.setup();

  await user.click(screen.getByRole("button", { name: "Not for me: Director, Payments" }));
  const raised = () => toasts.toast.mock.calls.map(([t]) => t as Raised);
  const hidden = raised().find((t) => t.action?.label === "Undo")!;
  verbs.toggleCompare.mockClear();

  await act(async () => hidden.action!.onClick());
  expect(verbs.toggleCompare.mock.calls).toEqual([[3], [3]]); // back in, then out again
  const failed = raised().find((t) => t.tone === "error")!;
  expect(failed.text).toBe("Couldn't restore Director, Payments");

  verbs.toggleCompare.mockClear();
  await act(async () => failed.action!.onClick());
  expect(verbs.toggleCompare.mock.calls).toEqual([[3]]);
  expect(api.undismissJob).toHaveBeenCalledTimes(2);
});

describe("Add another", () => {
  it("is offered below the cap and goes back to the list the cover opened over", async () => {
    vi.mocked(api.job).mockImplementation((id: number) => Promise.resolve(job(id, `Role ${id}`)));
    const onBack = vi.fn();
    render(<MemoryRouter><CompareScreen asOverlay onBack={onBack} /></MemoryRouter>);
    await screen.findAllByText("Role 2");
    await userEvent.setup().click(screen.getByRole("button", { name: "Add another" }));
    expect(onBack).toHaveBeenCalledTimes(1);
    expect(verbs.clearCompare).not.toHaveBeenCalled();
  });

  it("is not offered once the comparison is full", async () => {
    const three = new Set([1, 2, 3]);
    // Three is the cap: the provider says the selection is full.
    vi.mocked(useJobWorkspace).mockImplementation(
      () => ({ compareIds: three, compareHydrated: true, compareFull: true }) as never,
    );
    vi.mocked(api.job).mockImplementation((id: number) => Promise.resolve(job(id, `Role ${id}`)));
    render(<MemoryRouter><CompareScreen asOverlay /></MemoryRouter>);
    await screen.findAllByText("Role 3");
    expect(screen.queryByRole("button", { name: "Add another" })).toBeNull();
  });
});
