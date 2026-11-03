import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import type { ReactElement } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api, type Job, type JobList } from "../../api";
import { ToastProvider } from "../../ui/Toast";
import { jobFixture } from "../../test/fixtures";
import { SavedScreen } from "./SavedScreen";
import { msg } from "../../test/msg";

/* Saved's contracts. The screen has exactly one mutation — unsaving a role —
 * and it is optimistic, so the interesting cases are the ones where the
 * optimism is wrong: the request fails, or the reader changes their mind. */

vi.mock("../../api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../../api")>()),
  api: { jobs: vi.fn(), setFavorite: vi.fn() },
}));

const appState = {
  openJob: vi.fn(),
  viewedIds: new Set<number>(),
  compareIds: new Set<number>(),
  toggleCompare: vi.fn(),
  compareFull: false,
  setCompare: vi.fn(),
  refreshStats: vi.fn(),
  favVersion: 0,
};
vi.mock("../../context/JobWorkspace", () => ({ useJobWorkspace: () => appState, useJobActions: () => appState }));
vi.mock("../../context/MissionState", () => ({ useMissionActions: () => appState }));


function job(over: Partial<Job> & { id: number }): Job {
  return { ...jobFixture, is_favorite: true, req_id: `req-${over.id}`, ...over };
}

/* `total` defaults to the page's own length, which is the honest shape for a
   set that fits. It stays OVERRIDABLE so a fixture can state a truncated set
   (more saved roles than the 200-row page asks for), the case where the page
   and the set disagree. */
function list(items: Job[], over: Partial<JobList> = {}): JobList {
  return { items, total: items.length, limit: 200, offset: 0, ...over } as JobList;
}

const saved = [
  job({ id: 1, title: "Staff Product Manager, API" }),
  job({ id: 2, title: "Principal Engineering Manager" }),
];

const withProviders = (ui: ReactElement) => (
  <ToastProvider>
    <MemoryRouter>{ui}</MemoryRouter>
  </ToastProvider>
);

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(api.jobs).mockResolvedValue(list(saved));
  vi.mocked(api.setFavorite).mockImplementation(async (id, on) => ({ job_id: id, is_favorite: on }));
});

describe("Saved", () => {
  it("asks for the saved set in one page, and asks for closed roles too", async () => {
    render(withProviders(<SavedScreen />));
    await screen.findByText("Staff Product Manager, API");
    expect(vi.mocked(api.jobs).mock.calls[0][0]).toMatchObject({
      favorites_only: true,
      status: "",
      limit: 200,
    });
    expect(screen.getByText("2")).toBeInTheDocument();
  });

  /* A save made anywhere (Job detail, Compare, the Board) bumps `favVersion`.
     Saved re-reads in place: a reload from scratch would swap the rows for a
     skeleton and lose the reader's place. */
  it("re-reads the set in place after a save made elsewhere, keeping the rows on screen", async () => {
    const { rerender } = render(withProviders(<SavedScreen />));
    await screen.findByText("Staff Product Manager, API");
    const reads = vi.mocked(api.jobs).mock.calls.length;

    appState.favVersion = 1;
    rerender(withProviders(<SavedScreen />));
    expect(screen.getByText("Staff Product Manager, API")).toBeInTheDocument();
    await waitFor(() => expect(vi.mocked(api.jobs).mock.calls.length).toBe(reads + 1));
    expect(screen.getByText("Principal Engineering Manager")).toBeInTheDocument();
    appState.favVersion = 0;
  });

  /* The page asks for 200 rows. Past that the reader's saved set is LARGER
     than the page, and printing `items.length` alone would state our own cap
     as their total: "200 saved roles" for 213, with no pager and no other way
     to learn the difference. The count must come from the server's `total`. */
  it("says how many saved roles there are when the page cannot hold them all", async () => {
    vi.mocked(api.jobs).mockResolvedValue(list(saved, { total: 213, limit: 200 }));
    render(withProviders(<SavedScreen />));
    await screen.findByText("Staff Product Manager, API");

    const count = document.querySelector(".results-count")!;
    expect(count.textContent).toContain("of");
    expect(count.textContent).toContain("213");
  });

  /* The other half of the same rule, and the one that fails if the fraction is
     made unconditional: a set that FITS is a count, never "2 of 2". */
  it("states a set that fits as a plain count, with no denominator", async () => {
    render(withProviders(<SavedScreen />));
    await screen.findByText("Staff Product Manager, API");

    expect(document.querySelector(".results-count")!.textContent).not.toContain("of");
  });

  /* The intent above is only worth as much as the wire it reaches. `/api/jobs`
     reads an ABSENT status as "open", so an empty string dropped in
     serialization renders only the open saved roles while the topbar badge
     counts all of them. Driving the REAL client over a stubbed fetch is what
     makes this fail for that bug; the mocked-api test above pins the call
     site only. */
  it("carries the empty status onto the wire, so a saved role that closed still shows", async () => {
    const real = await vi.importActual<typeof import("../../api")>("../../api");
    const closed = job({ id: 3, title: "Director, Platform Infrastructure", status: "closed" });
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      statusText: "OK",
      json: async () => list([...saved, closed]),
    });
    vi.stubGlobal("fetch", fetchMock);
    vi.mocked(api.jobs).mockImplementation(real.api.jobs);

    try {
      render(withProviders(<SavedScreen />));
      await screen.findByText("Director, Platform Infrastructure");

      const url = new URL(fetchMock.mock.calls[0][0] as string, "https://roleband.test");
      expect(url.searchParams.has("status")).toBe(true);
      expect(url.searchParams.get("status")).toBe("");
      // `viewed` is a Literal on the wire: an empty one is a 422, so the
      // request must carry status= and nothing else that is empty.
      expect(url.searchParams.has("viewed")).toBe(false);
      expect(screen.getByText("3")).toBeInTheDocument();
    } finally {
      vi.unstubAllGlobals();
    }
  });

  /* A failed fetch must not fall through to the empty state, or an outage
     reads as "you have saved nothing". */
  it("a failed load says so and offers a retry, never 'Nothing saved yet'", async () => {
    vi.mocked(api.jobs).mockRejectedValueOnce(new Error("offline"));
    render(withProviders(<SavedScreen />));

    expect(await screen.findByRole("alert")).toHaveTextContent(msg("saved-screen-load-failed"));
    expect(screen.queryByText("Nothing saved yet")).toBeNull();

    vi.mocked(api.jobs).mockResolvedValue(list(saved));
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByText("Staff Product Manager, API")).toBeInTheDocument();
  });

  it("unsaving drops the row at once and the toast puts it back", async () => {
    render(withProviders(<SavedScreen />));
    await screen.findByText("Staff Product Manager, API");

    await userEvent.click(screen.getAllByRole("button", { name: msg("jobs-save"), pressed: true })[0]);
    // Optimistic: gone before the server answers, and the count follows it.
    expect(screen.queryByText("Staff Product Manager, API")).toBeNull();
    expect(screen.getByText("Principal Engineering Manager")).toBeInTheDocument();
    await waitFor(() => expect(api.setFavorite).toHaveBeenCalledWith(1, false));

    vi.mocked(api.jobs).mockResolvedValue(list(saved));
    await userEvent.click(await screen.findByRole("button", { name: "Undo" }));
    await waitFor(() => expect(api.setFavorite).toHaveBeenCalledWith(1, true));
    expect(await screen.findByText("Staff Product Manager, API")).toBeInTheDocument();
  });

  it("a rejected unsave restores the row rather than leaving the lie on screen", async () => {
    // Hold the rejection so the optimistic gap is observable: an awaited click
    // would settle it and repaint before the assertion could run, which would
    // make "the row went away first" untestable rather than untrue.
    let reject!: (e: Error) => void;
    vi.mocked(api.setFavorite).mockReturnValueOnce(new Promise((_, no) => { reject = no; }));
    render(withProviders(<SavedScreen />));
    await screen.findByText("Staff Product Manager, API");

    await userEvent.click(screen.getAllByRole("button", { name: msg("jobs-save"), pressed: true })[0]);
    expect(screen.queryByText("Staff Product Manager, API")).toBeNull();

    // The reload is the rollback: truth comes back from the server, not from a
    // remembered copy that a concurrent change could have made stale.
    await act(async () => { reject(new Error("offline")); });
    expect(await screen.findByText("Staff Product Manager, API")).toBeInTheDocument();
    // A removal that never happened has nothing to undo.
    expect(screen.queryByRole("button", { name: "Undo" })).toBeNull();
  });

  it("offers no Compare saved verb: picking rows raises the beacon, which is the one way in", async () => {
    // Such a button would set a selection and go nowhere, and with a cap of
    // three it could only be honest for three saved roles. One verb, one contract: the row toggle + the beacon.
    vi.mocked(api.jobs).mockResolvedValue(list(saved));
    render(withProviders(<SavedScreen />));
    await screen.findByText("Principal Engineering Manager");
    expect(screen.queryByRole("button", { name: /Compare saved/ })).toBeNull();
    expect(screen.getAllByRole("button", { name: msg("jobs-compare") }).length).toBe(saved.length);
  });
});
