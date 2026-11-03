import { StrictMode, type ReactNode } from "react";
import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api, type DismissResult } from "../../api";
import { facetsFixture, jobFixture, jobListFixture } from "../../test/fixtures";
import { readEntry, writeEntry } from "../../hooks/filterMemory";
import { DISMISS_TTL_MS, useBoardController } from "./useBoardController";
import { BOARD_MEMORY_SCOPE, RESET_FILTERS } from "./filters";
import { msg } from "../../test/msg";

const app = vi.hoisted(() => ({
  search: "", newSignalsOnly: false, repostsOnly: false, favVersion: 0, refreshStats: vi.fn(),
}));
vi.mock("../../context/MissionState", () => ({
  useMissionState: () => app,
  useBoardQuery: () => app,
  useMissionActions: () => app,
}));
const epoch = vi.hoisted(() => ({ notificationVersion: 0, referenceVersion: 0, runVersion: 0 }));
vi.mock("../../context/SyncState", () => ({ useSyncEpoch: () => epoch }));
vi.mock("../../context/JobWorkspace", () => ({ useJobWorkspace: () => app, useJobActions: () => app }));
const toasts = vi.hoisted(() => ({ toast: vi.fn(), dismiss: vi.fn() }));
vi.mock("../../ui", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../../ui")>()),
  useToast: () => toasts,
}));

const direct = {
  ...jobListFixture, query_kind: "exact_title" as const, related_total: 55,
  related_items: [{ ...jobFixture, id: 202, title: "Senior Platform Product Manager" }],
};
const lens = { companyParam: [] as string[], onCompanyParamChange: vi.fn(), mode: "open" as const, onModeChange: vi.fn() };
/** How many times the LIST was fetched. `api.jobs` also serves two counting
 *  voices that ask for one row and render a number — the unfiltered baseline
 *  and the three mode tabs — so a raw call count does not mean
 *  "the list reloaded". */
const listCalls = () =>
  vi.mocked(api.jobs).mock.calls
    .filter(([params]) => params.limit !== 1).length;
/** The params of the last LIST fetch — the baseline's one-row count never names a company. */
const lastList = () =>
  vi.mocked(api.jobs).mock.calls
    .filter(([params]) => params.limit !== 1).slice(-1)[0]?.[0];
/** The real serializer, captured before `beforeEach` spies over it: an empty
 *  status is lost BELOW `api.jobs`, so a test that mocks the method cannot see it. */
const realJobs = api.jobs;
const dismissal: DismissResult = {
  job_id: jobFixture.id, is_dismissed: true, reason: null,
  company: jobFixture.company, department: "Product", team: "API",
};
function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: Error) => void;
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}
beforeEach(() => {
  Object.assign(app, { search: "", newSignalsOnly: false, repostsOnly: false, favVersion: 0 });
  epoch.referenceVersion = 0;
  epoch.runVersion = 0;
  app.refreshStats.mockClear();
  lens.onCompanyParamChange.mockClear();
  lens.onModeChange.mockClear();
  vi.spyOn(api, "facets").mockResolvedValue(facetsFixture);
  vi.spyOn(api, "jobs").mockResolvedValue(direct);
});
afterEach(() => vi.restoreAllMocks());

describe("Board controller behavior", () => {
  it("pages related results, but filter, sort and external-lens edits collapse them", async () => {
    app.search = "Staff Product Manager, API";
    const { result, rerender } = renderHook((props) => useBoardController(props), { initialProps: lens });
    await waitFor(() => expect(result.current.filters.q).toBe(app.search));
    await waitFor(() => expect(result.current.list).toEqual(direct));
    expect(result.current.pageableTotal).toBe(0);
    act(() => result.current.update({ include_related: true, offset: 20 }));
    await waitFor(() => expect(result.current.expanded).toBe(true));
    expect(result.current.pageableTotal).toBe(55);
    // The list read carries its abort signal, so a superseded request stops costing.
    expect(api.jobs).toHaveBeenLastCalledWith(
      expect.objectContaining({ include_related: true, offset: 20 }), expect.any(AbortSignal),
    );

    // A control writes the URL itself, and holds the value locally while the
    // location lands — so the box it checked stays checked.
    act(() => result.current.updateFilters({ company: ["amazon"], offset: 0 }));
    expect(lens.onCompanyParamChange).toHaveBeenLastCalledWith(["amazon"]);
    expect(result.current.filters).toMatchObject({ company: ["amazon"], include_related: false, offset: 0 });
    // The address arriving is then nothing new: no second write, no refetch.
    const landed = listCalls();
    rerender({ ...lens, companyParam: ["amazon"] });
    expect(lens.onCompanyParamChange).toHaveBeenCalledTimes(1);
    await waitFor(() => expect(lastList()?.company).toEqual(["amazon"]));
    expect(listCalls()).toBe(landed);
    act(() => result.current.update({ include_related: true, offset: 40 }));
    act(() => result.current.onSort("company"));
    expect(result.current.filters).toMatchObject({ sort: "company", order: "desc", include_related: false, offset: 0 });
    act(() => result.current.onSort("company"));
    expect(result.current.filters.order).toBe("asc");
    act(() => result.current.update({ include_related: true, offset: 20 }));
    app.newSignalsOnly = true;
    rerender({ ...lens, companyParam: ["amazon"] });
    expect(result.current.filters).toMatchObject({ include_related: false, offset: 0 });
    await waitFor(() => expect(api.jobs).toHaveBeenLastCalledWith(expect.objectContaining({
      company: ["amazon"], new_today_only: true, include_related: false, offset: 0,
    }), expect.any(AbortSignal)));
  });

  /* The top bar's "open roles" is a link to `/`, and the board stays MOUNTED
     while the address drops `?company=`. A filters -> URL mirror would still
     hold the company and write it straight back,
     so the link would reach the list it was clicked from. */
  it("keeps a page turned before the search box first settles: an unchanged query resets nothing", async () => {
    const { result } = renderHook((props) => useBoardController(props), { initialProps: lens });
    await waitFor(() => expect(result.current.list).toEqual(direct));
    // Inside the search box's debounce window after mount, with nothing typed.
    act(() => result.current.update({ offset: 20 }));
    await act(() => new Promise((resolve) => setTimeout(resolve, 400)));
    expect(result.current.filters.offset).toBe(20);
    expect(lastList()).toMatchObject({ offset: 20 });
  });

  it("follows the URL when the company leaves it, and never writes it back", async () => {
    const { result, rerender } = renderHook((props) => useBoardController(props), {
      initialProps: { ...lens, companyParam: ["amazon"] },
    });
    await waitFor(() => expect(lastList()?.company).toEqual(["amazon"]));
    const before = listCalls();

    rerender({ ...lens, companyParam: [] });
    expect(result.current.filters.company).toEqual([]);
    await waitFor(() => expect(lastList()?.company).toEqual([]));
    expect(listCalls() - before).toBe(1);
    // Nothing on the board answered the URL by writing a company.
    expect(lens.onCompanyParamChange).not.toHaveBeenCalled();
  });

  it("Reset all clears the company with the same single URL write as everything else", async () => {
    const { result } = renderHook((props) => useBoardController(props), {
      initialProps: { ...lens, companyParam: ["amazon"] },
    });
    await waitFor(() => expect(result.current.filters.company).toEqual(["amazon"]));
    act(() => result.current.update({ level_band: ["L7"] }));
    act(() => result.current.update(RESET_FILTERS));
    expect(lens.onCompanyParamChange).toHaveBeenCalledTimes(1);
    expect(lens.onCompanyParamChange).toHaveBeenLastCalledWith([]);
    expect(result.current.filters).toMatchObject({ level_band: [], company: [] });
  });

  /* `/api/jobs` reads an ABSENT `status` as "open" and an explicit
     `status=` as "no status condition", so the register's All option
     (BoardFilters STATUS `["", "All"]`) has to reach the wire as an empty
     param or it silently means Open. */
  it("puts the register's 'All' status on the wire, so the board stops meaning 'Open'", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true, status: 200, statusText: "OK", json: async () => jobListFixture,
    });
    vi.stubGlobal("fetch", fetchMock);
    vi.spyOn(api, "jobs").mockImplementation(realJobs);
    const sent = (): URLSearchParams[] => fetchMock.mock.calls
      .map((call) => new URL(String(call[0]), "https://roleband.test").searchParams);
    const last = () => sent()[fetchMock.mock.calls.length - 1];

    try {
      const { result } = renderHook(() => useBoardController(lens));
      await waitFor(() => expect(fetchMock).toHaveBeenCalled());
      // The default board names its status outright; only "All" is the empty one.
      expect(sent()[0].get("status")).toBe("open");

      act(() => result.current.updateFilters({ status: "" }));
      await waitFor(() => expect(last().has("status")).toBe(true));
      expect(last().get("status")).toBe("");

      // No other empty filter may ride along: `viewed` is a Literal on the
      // wire and DEFAULT_FILTERS carries `viewed: ""`, so `viewed=` is a 422.
      for (const params of sent()) expect(params.has("viewed")).toBe(false);
    } finally {
      vi.unstubAllGlobals();
    }
  });

  it.each(["exact", "related"])("rolls a failed %s favorite back without disturbing the other section", async (section) => {
    const pending = deferred<{ job_id: number; is_favorite: boolean }>();
    const save = vi.spyOn(api, "setFavorite").mockReturnValue(pending.promise);
    const { result } = renderHook(() => useBoardController(lens));
    await waitFor(() => expect(result.current.list).toEqual(direct));
    const job = section === "exact" ? direct.items[0] : direct.related_items[0];
    act(() => result.current.toggleFav(job));
    // Sent through the role's write queue, a microtask after the click.
    await waitFor(() => expect(save).toHaveBeenCalledWith(job.id, true));
    const rows = () => [...result.current.list!.items, ...result.current.list!.related_items!];
    expect(rows().filter((row) => row.is_favorite).map((row) => row.id)).toEqual([job.id]);
    await act(async () => pending.reject(new Error("Save failed")));
    expect(result.current.list).toEqual(direct);
    expect(app.refreshStats).not.toHaveBeenCalled();
  });

  it("removes the last exact row without hiding related results, and refetches a failed dismissal", async () => {
    const pending = deferred<DismissResult>();
    vi.spyOn(api, "dismissJob").mockReturnValue(pending.promise);
    const { result } = renderHook(() => useBoardController(lens));
    await waitFor(() => expect(result.current.list).toEqual(direct));
    act(() => result.current.dismiss(jobFixture));
    expect(result.current.list).toMatchObject({ items: [], total: 0, related_total: 55, related_items: direct.related_items });
    expect(result.current.dismissal).toBeNull();
    await act(async () => pending.reject(new Error("Dismiss failed")));
    await waitFor(() => expect(result.current.list).toEqual(direct));
    expect(listCalls()).toBe(2);
    expect(result.current.dismissal).toBeNull();
  });

  /* The way back: ONE dismissal at a time, for DISMISS_TTL_MS. It
     records WHERE the row was — before the row that followed it, in its
     section — so the list can seam it and the pill can be level with it. A
     second dismissal REPLACES the first (the pill moves; it never stacks),
     Undo takes it away at once, and the clock takes it away on its own. */
  it("keeps one way back, replaces it on the next dismissal, and Undo clears it", async () => {
    vi.spyOn(api, "dismissJob").mockResolvedValue(dismissal);
    vi.spyOn(api, "undismissJob").mockResolvedValue(undefined as never);
    const { result } = renderHook(() => useBoardController(lens), {
      wrapper: ({ children }: { children: ReactNode }) => <StrictMode>{children}</StrictMode>,
    });
    await waitFor(() => expect(result.current.list).toEqual(direct));
    // The only exact row: it was last in its section.
    await act(async () => result.current.dismiss(jobFixture));
    expect(result.current.dismissal).toEqual({ job: jobFixture, section: "items", beforeId: null });
    // A related row: the way back is now THAT row's — the first is gone from
    // the margin (it waits in the Not-for-me lens), not stacked under it.
    const [first] = direct.related_items;
    await act(async () => result.current.dismiss(first));
    expect(result.current.dismissal).toMatchObject({ job: first, section: "related_items", beforeId: null });
    await act(async () => result.current.undoDismiss(first));
    expect(result.current.dismissal).toBeNull();
    expect(api.undismissJob).toHaveBeenCalledWith(first.id);
    expect(api.undismissJob).not.toHaveBeenCalledWith(jobFixture.id);
  });

  it("keeps the way back when Undo fails, says so, and brings the role back on a second try", async () => {
    // Clearing the pill before the request, with a rejection going nowhere,
    // would leave the role hidden with no way back.
    vi.spyOn(api, "dismissJob").mockResolvedValue(dismissal);
    const undo = vi.spyOn(api, "undismissJob")
      .mockRejectedValueOnce(new Error("offline"))
      .mockResolvedValueOnce(undefined as never);
    toasts.toast.mockClear();
    const { result } = renderHook(() => useBoardController(lens));
    await waitFor(() => expect(result.current.list).toEqual(direct));
    await act(async () => result.current.dismiss(jobFixture));

    await act(async () => result.current.undoDismiss(jobFixture));
    expect(result.current.dismissal).toEqual({ job: jobFixture, section: "items", beforeId: null });
    expect(toasts.toast).toHaveBeenCalledWith(
      expect.objectContaining({ text: msg("radar-restore-failed", { title: jobFixture.title }), tone: "error" }),
    );
    expect(listCalls()).toBe(1);

    await act(async () => result.current.undoDismiss(jobFixture));
    expect(result.current.dismissal).toBeNull();
    expect(undo).toHaveBeenCalledTimes(2);
    await waitFor(() => expect(listCalls()).toBe(2));
  });

  it("takes the way back away on its own after DISMISS_TTL_MS, and a new dismissal restarts the clock", async () => {
    vi.useFakeTimers();
    try {
      vi.spyOn(api, "dismissJob").mockResolvedValue(dismissal);
      const { result } = renderHook(() => useBoardController(lens));
      await act(async () => { await vi.runOnlyPendingTimersAsync(); });
      await act(async () => { await vi.advanceTimersByTimeAsync(300); });
      expect(result.current.list).toEqual(direct);

      await act(async () => result.current.dismiss(jobFixture));
      expect(result.current.dismissal?.job).toEqual(jobFixture);
      await act(async () => { await vi.advanceTimersByTimeAsync(DISMISS_TTL_MS - 1000); });
      expect(result.current.dismissal?.job).toEqual(jobFixture);

      // Dismissing another role with 1s left gives THAT one the full clock.
      const [first] = direct.related_items;
      await act(async () => result.current.dismiss(first));
      await act(async () => { await vi.advanceTimersByTimeAsync(DISMISS_TTL_MS - 1000); });
      expect(result.current.dismissal?.job).toEqual(first);
      await act(async () => { await vi.advanceTimersByTimeAsync(1000); });
      expect(result.current.dismissal).toBeNull();
    } finally {
      vi.useRealTimers();
    }
  });

  /* Filter memory. Everything the register narrows by comes back
     as the reader left it — across a reload, and across leaving the screen,
     which the address alone never covered because the nav rail lands on `/`. */
  it("asks for the remembered filters on the FIRST request, not on a second one", async () => {
    writeEntry(BOARD_MEMORY_SCOPE, { level_band: ["staff"], viewed: "unread", base_min: 200000 });
    const { result } = renderHook(() => useBoardController(lens));
    await waitFor(() => expect(result.current.list).toEqual(direct));
    // One list request, already narrowed. Restoring from an effect instead
    // would show the unfiltered board first and then replace it.
    expect(listCalls()).toBe(1);
    expect(lastList()).toMatchObject({ level_band: ["staff"], viewed: "unread", base_min: 200000 });
  });

  it("writes a remembered company into the address, once, so `/` still means unfiltered", async () => {
    writeEntry(BOARD_MEMORY_SCOPE, { company: ["openai"] });
    const { result, rerender } = renderHook((props) => useBoardController(props), {
      initialProps: lens,
    });
    await waitFor(() => expect(result.current.filters.company).toEqual(["openai"]));
    // The register shows it AND the address says it: the top bar's "N open
    // roles" link to `/` is the way back to the unfiltered board,
    // and it can only work if the company it is clearing is actually there.
    expect(lens.onCompanyParamChange).toHaveBeenCalledTimes(1);
    expect(lens.onCompanyParamChange).toHaveBeenLastCalledWith(["openai"]);

    // ...and the address is still the only writer: the link lands as an empty
    // param and the company goes, memory or no memory.
    rerender({ ...lens, companyParam: ["openai"] });
    rerender({ ...lens, companyParam: [] });
    expect(result.current.filters.company).toEqual([]);
    expect(lens.onCompanyParamChange).toHaveBeenCalledTimes(1);
  });

  it("lets a link's company outrank the remembered one, and leaves memory alone", async () => {
    writeEntry(BOARD_MEMORY_SCOPE, { company: ["openai"] });
    const { result } = renderHook((props) => useBoardController(props), {
      initialProps: { ...lens, companyParam: ["amazon"] },
    });
    await waitFor(() => expect(lastList()?.company).toEqual(["amazon"]));
    // Nothing was written to the address: it already said what it wanted.
    expect(lens.onCompanyParamChange).not.toHaveBeenCalled();
    expect(result.current.filters.company).toEqual(["amazon"]);
  });

  it("remembers what Reset all left behind, so a reset survives the trip", async () => {
    writeEntry(BOARD_MEMORY_SCOPE, { level_band: ["staff"], discloses_pay: true });
    const { result } = renderHook(() => useBoardController(lens));
    await waitFor(() => expect(result.current.filters.level_band).toEqual(["staff"]));
    act(() => result.current.update(RESET_FILTERS));
    await waitFor(() =>
      expect(readEntry(BOARD_MEMORY_SCOPE)).toMatchObject({ level_band: [], discloses_pay: false }),
    );
  });

  it("never lets memory choose which population the board shows", async () => {
    // The mode is the one thing in `More filters` that is not remembered: open
    // roles is the board, and the top bar's count is the link back to it.
    writeEntry(BOARD_MEMORY_SCOPE, { status: "closed", dismissed_only: true, viewed: "unread" });
    const { result } = renderHook(() => useBoardController(lens));
    await waitFor(() => expect(result.current.filters.viewed).toBe("unread"));
    expect(result.current.filters).toMatchObject({ status: "open", dismissed_only: false });
    expect(result.current.mode).toBe("open");
  });

  it("does not record a dismissal that completes after unmount", async () => {
    const pending = deferred<DismissResult>();
    vi.spyOn(api, "dismissJob").mockReturnValue(pending.promise);
    const { result, unmount } = renderHook(() => useBoardController(lens));
    await waitFor(() => expect(result.current.list).toEqual(direct));
    act(() => result.current.dismiss(jobFixture));
    unmount();
    await act(async () => pending.resolve(dismissal));
    expect(result.current.dismissal).toBeNull();
  });
});


describe("Board controller and the reference set", () => {
  it("re-reads the page in place when estimates moved, keeping the rows on screen", async () => {
    const { result, rerender } = renderHook((props) => useBoardController(props), { initialProps: lens });
    await waitFor(() => expect(result.current.list).toEqual(direct));
    const before = listCalls();
    epoch.referenceVersion = 1;
    rerender(lens);
    await waitFor(() => expect(listCalls()).toBe(before + 1));
    expect(result.current.list).toEqual(direct);
  });
});

describe("Best fit that has nothing to rank by", () => {
  it("is said when the list comes back without an intent ranking, and not when it has one", async () => {
    // Fail-first: the Board never read `ranked_by`, so the sort kept saying
    // Best fit over a newest-first list.
    vi.spyOn(api, "jobs").mockResolvedValue({ ...jobListFixture });
    const { result, rerender } = renderHook((props) => useBoardController(props), { initialProps: lens });
    act(() => result.current.update({ sort: "relevance" }));
    await waitFor(() => expect(result.current.list).not.toBeNull());
    await waitFor(() => expect(result.current.bestFitUnranked).toBe(true));

    vi.spyOn(api, "jobs").mockResolvedValue({ ...jobListFixture, ranked_by: "intent" });
    act(() => result.current.update({ offset: 0, limit: 21 }));
    rerender(lens);
    await waitFor(() => expect(result.current.bestFitUnranked).toBe(false));
  });

  it("is never said for another sort", async () => {
    vi.spyOn(api, "jobs").mockResolvedValue({ ...jobListFixture });
    const { result } = renderHook((props) => useBoardController(props), { initialProps: lens });
    act(() => result.current.update({ sort: "first_seen" }));
    await waitFor(() => expect(result.current.list).not.toBeNull());
    expect(result.current.bestFitUnranked).toBe(false);
  });
});


describe("Board controller and a save made anywhere", () => {
  it("re-reads the page in place: the rows never leave, and one read goes out with the same filters", async () => {
    const { result, rerender } = renderHook((props) => useBoardController(props), { initialProps: lens });
    await waitFor(() => expect(result.current.list).toEqual(direct));
    const before = listCalls();
    const filters = lastList();
    app.favVersion = 1;
    rerender(lens);
    // The same render that saw the save still holds the rows: no skeleton.
    expect(result.current.list).toEqual(direct);
    await waitFor(() => expect(listCalls()).toBe(before + 1));
    expect(lastList()).toEqual(filters);
    expect(result.current.list).toEqual(direct);
  });
});


describe("Board reads", () => {
  it("a query already in the box at mount is in the first request, and nothing unfiltered goes first", async () => {
    app.search = "platform";
    const { result } = renderHook((props) => useBoardController(props), { initialProps: lens });
    await waitFor(() => expect(result.current.list).toEqual(direct));
    await act(async () => { await new Promise((r) => setTimeout(r, 300)); });

    expect(listCalls()).toBe(1);
    expect(lastList()).toMatchObject({ q: "platform", sort: "relevance" });
  });

  it("a finished scan offers the changed list and moves no row until it is taken", async () => {
    const first = { ...jobListFixture, total: 2, items: [jobFixture, { ...jobFixture, id: 2, title: "Second" }] };
    const after = { ...first, total: 3, items: [{ ...jobFixture, id: 3, title: "Third" }, ...first.items] };
    vi.mocked(api.jobs).mockResolvedValue(first);
    const { result, rerender } = renderHook((props) => useBoardController(props), { initialProps: lens });
    await waitFor(() => expect(result.current.list).toEqual(first));
    const facetReads = vi.mocked(api.facets).mock.calls.length;

    vi.mocked(api.jobs).mockResolvedValue(after);
    epoch.runVersion = 1;
    rerender({ ...lens });
    await waitFor(() => expect(result.current.fresh).toEqual({ more: 1 }));
    expect(result.current.list).toEqual(first);
    expect(vi.mocked(api.facets).mock.calls.length).toBe(facetReads + 1);

    act(() => result.current.showFresh());
    expect(result.current.list).toEqual(after);
    expect(result.current.fresh).toBeNull();
  });

  it("a finished scan that changed nothing on this list offers nothing", async () => {
    vi.mocked(api.jobs).mockResolvedValue(jobListFixture);
    const { result, rerender } = renderHook((props) => useBoardController(props), { initialProps: lens });
    await waitFor(() => expect(result.current.list).toEqual(jobListFixture));
    const reads = vi.mocked(api.jobs).mock.calls.length;

    epoch.runVersion = 1;
    rerender({ ...lens });
    await waitFor(() => expect(vi.mocked(api.jobs).mock.calls.length).toBeGreaterThan(reads));
    await act(async () => { await Promise.resolve(); });
    expect(result.current.fresh).toBeNull();
  });

  it("an edit to the filters withdraws an offered update", async () => {
    const first = { ...jobListFixture, total: 1 };
    vi.mocked(api.jobs).mockResolvedValue(first);
    const { result, rerender } = renderHook((props) => useBoardController(props), { initialProps: lens });
    await waitFor(() => expect(result.current.list).toEqual(first));
    vi.mocked(api.jobs).mockResolvedValue({ ...first, total: 4, items: [{ ...jobFixture, id: 9 }] });
    epoch.runVersion = 1;
    rerender({ ...lens });
    await waitFor(() => expect(result.current.fresh).not.toBeNull());

    act(() => result.current.updateFilters({ workplace_type: ["remote"] }));
    expect(result.current.fresh).toBeNull();
  });
});
