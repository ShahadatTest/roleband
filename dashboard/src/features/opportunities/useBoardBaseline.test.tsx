import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { api, DEFAULT_FILTERS, type JobList } from "../../api";
import { jobListFixture } from "../../test/fixtures";
import { useBoardBaseline } from "./useBoardBaseline";

const props = (q = "platform") => ({
  filters: { ...DEFAULT_FILTERS, q, company: ["google"] },
  lenses: { newSignalsOnly: false, repostsOnly: false }, list: null as JobList | null, version: "0",
});
function deferred() {
  let resolve!: (value: JobList) => void;
  let reject!: (reason: Error) => void;
  const promise = new Promise<JobList>((done, fail) => { resolve = done; reject = fail; });
  return { promise, resolve, reject };
}
afterEach(() => vi.restoreAllMocks());

describe("Board baseline resource", () => {
  it("reuses the exact unfiltered total (including zero) without a baseline request", async () => {
    const jobs = vi.spyOn(api, "jobs");
    const input = { ...props(), filters: { ...DEFAULT_FILTERS, q: "platform" }, list: { ...jobListFixture, total: 0 } };
    const { result, rerender } = renderHook(useBoardBaseline, { initialProps: input });
    expect(result.current.total).toBeNull();
    rerender({ ...input, filters: { ...input.filters, company: ["google"] } });
    await waitFor(() => expect(result.current.total).toBe(0));
    expect(jobs).not.toHaveBeenCalled();
  });

  it.each([
    ["the Closed pile", { status: "closed", dismissed_only: false }],
    ["the Not-for-me lens", { status: "", dismissed_only: true }],
  ])("measures nothing in %s with no narrowing filter: the list's own total is the population", async (_name, mode) => {
    const jobs = vi.spyOn(api, "jobs");
    const input = { ...props(), filters: { ...DEFAULT_FILTERS, ...mode }, list: { ...jobListFixture, total: 34 } };
    renderHook(useBoardBaseline, { initialProps: input });
    await act(async () => { await Promise.resolve(); });
    expect(jobs).not.toHaveBeenCalled();
  });

  it("measures the Closed pile once a narrowing filter is on", async () => {
    const jobs = vi.spyOn(api, "jobs").mockResolvedValue({ ...jobListFixture, total: 34 });
    const input = { ...props(), filters: { ...DEFAULT_FILTERS, status: "closed", company: ["google"] } };
    renderHook(useBoardBaseline, { initialProps: input });
    await waitFor(() => expect(jobs).toHaveBeenCalledTimes(1));
  });

  it("keeps one pending measurement while only facets or pagination change", async () => {
    const pending = deferred();
    const jobs = vi.spyOn(api, "jobs").mockReturnValue(pending.promise);
    const { result, rerender } = renderHook(useBoardBaseline, { initialProps: props() });
    rerender({ ...props(), filters: { ...props().filters, company: ["amazon"], offset: 40, include_related: true } });
    expect(jobs).toHaveBeenCalledTimes(1);
    expect(jobs.mock.calls[0][0]).toEqual({ ...DEFAULT_FILTERS, q: "platform", limit: 1 });
    expect(jobs.mock.calls[0][1]?.aborted).toBe(false);
    await act(async () => pending.resolve({ ...jobListFixture, total: 219 }));
    expect(result.current.total).toBe(219);
  });

  it("aborts old query requests and ignores late responses even if transport ignores abort", async () => {
    const first = deferred(), second = deferred();
    const jobs = vi.spyOn(api, "jobs").mockReturnValue(deferred().promise)
      .mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise);
    const { result, rerender, unmount } = renderHook(useBoardBaseline, { initialProps: props("first") });
    rerender(props("second"));
    expect(jobs.mock.calls[0][1]?.aborted).toBe(true);
    await act(async () => first.resolve({ ...jobListFixture, total: 1000 }));
    expect(result.current.total).toBeNull();
    expect(jobs).toHaveBeenCalledTimes(2);
    await act(async () => second.resolve({ ...jobListFixture, total: 7 }));
    expect(result.current.total).toBe(7);
    expect(jobs).toHaveBeenCalledTimes(2);
    unmount();
    expect(jobs.mock.calls[1][1]?.aborted).toBe(true);
  });

  it("keeps the current failure and retry when an aborted query rejects later", async () => {
    const first = deferred(), second = deferred();
    const currentFailure = new Error("Current query is offline");
    const jobs = vi.spyOn(api, "jobs").mockReturnValue(deferred().promise)
      .mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise);
    const { result, rerender } = renderHook(useBoardBaseline, { initialProps: props("first") });
    rerender(props("second"));
    await act(async () => second.reject(currentFailure));
    expect(result.current.error).toBe(currentFailure);
    await act(async () => first.reject(new Error("Old query failed later")));
    expect(result.current.error).toBe(currentFailure);
    expect(result.current.total).toBeNull();
    expect(jobs).toHaveBeenCalledTimes(2);

    jobs.mockResolvedValueOnce({ ...jobListFixture, total: 35 });
    act(() => result.current.retry());
    await waitFor(() => expect(result.current.total).toBe(35));
    expect(result.current.error).toBeNull();
    expect(jobs).toHaveBeenCalledTimes(3);
  });

  it("does not grow a history cache and invalidates on confirmed data changes", async () => {
    const jobs = vi.spyOn(api, "jobs").mockResolvedValue({ ...jobListFixture, total: 21 });
    const { result, rerender } = renderHook(useBoardBaseline, { initialProps: props("first") });
    await waitFor(() => expect(result.current.total).toBe(21));
    rerender(props("second"));
    await waitFor(() => expect(result.current.total).toBe(21));
    rerender(props("first"));
    await waitFor(() => expect(jobs).toHaveBeenCalledTimes(3));
    await waitFor(() => expect(result.current.total).toBe(21));
    rerender({ ...props("first"), version: "1" });
    await waitFor(() => expect(jobs).toHaveBeenCalledTimes(4));
  });

  it("leaves a failed denominator unknown and retries explicitly, without an automatic loop", async () => {
    const jobs = vi.spyOn(api, "jobs").mockRejectedValueOnce(new Error("Offline"))
      .mockResolvedValueOnce({ ...jobListFixture, total: 35 });
    const { result, rerender } = renderHook(useBoardBaseline, { initialProps: props() });
    await waitFor(() => expect(result.current.error?.message).toBe("Offline"));
    expect(result.current.total).toBeNull();
    rerender(props());
    expect(jobs).toHaveBeenCalledTimes(1);
    act(() => result.current.retry());
    await waitFor(() => expect(result.current.total).toBe(35));
    expect(result.current.error).toBeNull();
    expect(jobs).toHaveBeenCalledTimes(2);
  });

  it("aborts a pending request on unmount", () => {
    const jobs = vi.spyOn(api, "jobs").mockReturnValue(deferred().promise);
    const { unmount } = renderHook(useBoardBaseline, { initialProps: props() });
    const signal = jobs.mock.calls[0][1]!;
    expect(signal.aborted).toBe(false);
    unmount();
    expect(signal.aborted).toBe(true);
  });
});
