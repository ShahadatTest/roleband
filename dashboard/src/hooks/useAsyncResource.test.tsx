import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { keepAnswer, keptAnswer, writesSettled } from "../api/keptAnswers";
import { api } from "../api";
import { postJSON } from "../api/transport";
import { useAsyncResource } from "./useAsyncResource";

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((onResolve, onReject) => {
    resolve = onResolve;
    reject = onReject;
  });
  return { promise, resolve, reject };
}

describe("useAsyncResource", () => {
  it("ignores a stale response after its request inputs change", async () => {
    const oldRequest = deferred<string>();
    const currentRequest = deferred<string>();
    const load = vi.fn((days: number) => days === 30 ? oldRequest.promise : currentRequest.promise);

    const { result, rerender } = renderHook(
      ({ days }) => useAsyncResource(() => load(days), [days]),
      { initialProps: { days: 30 } },
    );
    rerender({ days: 7 });

    await act(async () => currentRequest.resolve("last 7 days"));
    expect(result.current.data).toBe("last 7 days");

    await act(async () => oldRequest.resolve("last 30 days"));
    expect(result.current.data).toBe("last 7 days");
  });

  it("hides previously loaded data in the render where request inputs change", async () => {
    const currentRequest = deferred<string>();
    const load = vi.fn((days: number) => days === 30
      ? Promise.resolve("last 30 days")
      : currentRequest.promise);
    const { result, rerender } = renderHook(
      ({ days }) => useAsyncResource(() => load(days), [days]),
      { initialProps: { days: 30 } },
    );
    await waitFor(() => expect(result.current.data).toBe("last 30 days"));

    rerender({ days: 7 });

    expect(result.current.data).toBeNull();
    expect(result.current.loading).toBe(true);
  });

  it("exposes a rejected request and retries it on demand", async () => {
    const load = vi.fn()
      .mockRejectedValueOnce(new Error("offline"))
      .mockResolvedValueOnce("recovered");

    const { result } = renderHook(() => useAsyncResource(load, []));

    await waitFor(() => expect(result.current.error).toEqual(new Error("offline")));
    expect(result.current.loading).toBe(false);

    act(() => result.current.retry());
    expect(result.current.loading).toBe(true);
    await waitFor(() => expect(result.current.data).toBe("recovered"));
    expect(result.current.error).toBeNull();
    expect(load).toHaveBeenCalledTimes(2);
  });
});

/* Request ordering. What the per-effect `active` flag
 * could not do: two starts against the SAME inputs — a poll and a row action,
 * a refresh and a retry — race, and nothing in the deps tells them apart. */
describe("useAsyncResource — latest request wins across every start", () => {
  it("a slow refresh cannot overwrite the faster refresh that followed it", async () => {
    const first = deferred<string>();
    const second = deferred<string>();
    const load = vi.fn()
      .mockResolvedValueOnce("initial")
      .mockReturnValueOnce(first.promise)
      .mockReturnValueOnce(second.promise);

    const { result } = renderHook(() => useAsyncResource(load, []));
    await waitFor(() => expect(result.current.data).toBe("initial"));

    act(() => void result.current.refresh({ preserveData: true }));
    act(() => void result.current.refresh({ preserveData: true }));

    // The SECOND refresh answers first, then the first one straggles in.
    await act(async () => second.resolve("newer"));
    expect(result.current.data).toBe("newer");
    await act(async () => first.resolve("older"));
    expect(result.current.data).toBe("newer");
  });

  it("a refresh that resolves after the inputs changed is discarded", async () => {
    const stale = deferred<string>();
    const load = vi.fn((days: number) =>
      days === 30 ? Promise.resolve("30d") : Promise.resolve("7d"),
    );
    const { result, rerender } = renderHook(
      ({ days }) => useAsyncResource(() => (days === 30 ? stale.promise : load(days)), [days]),
      { initialProps: { days: 30 } },
    );
    act(() => void result.current.refresh({ preserveData: true }));
    rerender({ days: 7 });
    await waitFor(() => expect(result.current.data).toBe("7d"));

    await act(async () => stale.resolve("30d refreshed"));
    expect(result.current.data).toBe("7d");
  });

  it("a preserve-data refresh keeps the rows mounted while it runs", async () => {
    const pending = deferred<string>();
    const load = vi.fn().mockResolvedValueOnce("rows").mockReturnValueOnce(pending.promise);
    const { result } = renderHook(() => useAsyncResource(load, []));
    await waitFor(() => expect(result.current.data).toBe("rows"));

    act(() => void result.current.refresh({ preserveData: true }));
    // The whole point: no spinner, no blank, and the state says why.
    expect(result.current.data).toBe("rows");
    expect(result.current.loading).toBe(false);
    expect(result.current.refreshing).toBe(true);

    await act(async () => pending.resolve("fresh rows"));
    expect(result.current.data).toBe("fresh rows");
    expect(result.current.refreshing).toBe(false);
  });

  it("a failed background refresh reports itself without blanking good data", async () => {
    const load = vi.fn().mockResolvedValueOnce("rows").mockRejectedValueOnce(new Error("offline"));
    const { result } = renderHook(() => useAsyncResource(load, []));
    await waitFor(() => expect(result.current.data).toBe("rows"));

    await act(async () => { await result.current.refresh({ preserveData: true }); });
    // Quiet, not silent: the rows survive and the failure is inspectable.
    expect(result.current.data).toBe("rows");
    expect(result.current.error).toBeNull();
    expect(result.current.refreshError).toEqual(new Error("offline"));

    // A later success clears the health flag rather than leaving it stuck on.
    load.mockResolvedValueOnce("rows again");
    await act(async () => { await result.current.refresh({ preserveData: true }); });
    expect(result.current.refreshError).toBeNull();
  });

  it("a refresh WITHOUT preserveData is a visible reload, and its failure is the real error", async () => {
    const load = vi.fn().mockResolvedValueOnce("rows").mockRejectedValueOnce(new Error("gone"));
    const { result } = renderHook(() => useAsyncResource(load, []));
    await waitFor(() => expect(result.current.data).toBe("rows"));

    await act(async () => { await result.current.refresh(); });
    expect(result.current.data).toBeNull();
    expect(result.current.error).toEqual(new Error("gone"));
    expect(result.current.refreshError).toBeNull();
  });

  it("hands the request an abort signal and trips it when the inputs change", async () => {
    const signals: AbortSignal[] = [];
    const { rerender } = renderHook(
      ({ days }) => useAsyncResource((signal) => { signals.push(signal); return Promise.resolve(days); }, [days]),
      { initialProps: { days: 30 } },
    );
    rerender({ days: 7 });
    await waitFor(() => expect(signals.length).toBe(2));
    expect(signals[0].aborted).toBe(true);
    expect(signals[1].aborted).toBe(false);
  });

  it("writes nothing after unmount, and aborts the request it leaves behind", async () => {
    const pending = deferred<string>();
    let signal!: AbortSignal;
    const { result, unmount } = renderHook(() =>
      useAsyncResource((s) => { signal = s; return pending.promise; }, []),
    );
    expect(result.current.loading).toBe(true);
    unmount();
    expect(signal.aborted).toBe(true);

    // Resolving a request nobody is waiting for must not warn or throw.
    await act(async () => pending.resolve("too late"));
    expect(result.current.data).toBeNull();
  });

  it("a request that throws synchronously is a failed request, not a crash", async () => {
    const { result } = renderHook(() =>
      useAsyncResource(() => { throw new Error("bad url"); }, []),
    );
    await waitFor(() => expect(result.current.error).toEqual(new Error("bad url")));
    expect(result.current.loading).toBe(false);
  });
});

/* A read opened again paints its last answer at once, then asks again. What it
 * must never do: paint another query's answer, or an answer a write may have
 * made untrue. */
describe("useAsyncResource — kept answers", () => {
  afterEach(() => vi.unstubAllGlobals());

  type Seen = { data: unknown; loading: boolean; refreshing: boolean };

  /** Mount a read, let it answer, and leave the screen. */
  async function visit(answer: string, keep = "panel", days = 30) {
    const { result, unmount } = renderHook(() =>
      useAsyncResource(() => Promise.resolve(answer), [days], { keep }));
    await waitFor(() => expect(result.current.data).toBe(answer));
    unmount();
  }

  /** Mount a read whose request waits, recording every render. */
  function open(options?: { keep?: string }, days = 30) {
    const pending = deferred<string>();
    const seen: Seen[] = [];
    const view = renderHook(() => {
      const resource = useAsyncResource(() => pending.promise, [days], options);
      seen.push({ data: resource.data, loading: resource.loading, refreshing: resource.refreshing });
      return resource;
    });
    return { ...view, pending, seen };
  }

  function answerWrites() {
    vi.stubGlobal("fetch", vi.fn(async () => new Response("{}", { status: 200 })));
  }

  it("paints the kept answer in the first render, then refreshes it", async () => {
    await visit("monday");
    const { result, pending, seen } = open({ keep: "panel" });

    expect(seen[0]).toEqual({ data: "monday", loading: false, refreshing: true });
    expect(seen.every((render) => render.data === "monday")).toBe(true);

    await act(async () => pending.resolve("tuesday"));
    expect(result.current.data).toBe("tuesday");
    expect(result.current.refreshing).toBe(false);
  });

  it("files the fresh answer, so the next visit paints that one", async () => {
    await visit("monday");
    const second = open({ keep: "panel" });
    await act(async () => second.pending.resolve("tuesday"));
    second.unmount();

    expect(open({ keep: "panel" }).seen[0].data).toBe("tuesday");
  });

  it("never paints the kept answer of other inputs", async () => {
    await visit("thirty days", "panel", 30);
    expect(open({ keep: "panel" }, 7).seen[0]).toEqual({ data: null, loading: true, refreshing: false });
  });

  it("paints no kept answer for an unkept read or another name", async () => {
    await visit("monday", "panel");
    expect(open().seen[0]).toEqual({ data: null, loading: true, refreshing: false });
    expect(open({ keep: "other" }).seen[0]).toEqual({ data: null, loading: true, refreshing: false });
  });

  it("swaps to this query's kept answer in the render where the inputs change", async () => {
    await visit("seven days", "panel", 7);
    const pending = deferred<string>();
    const seen: Seen[] = [];
    const { result, rerender } = renderHook(
      ({ days }) => {
        const resource = useAsyncResource(() => (days === 30 ? Promise.resolve("thirty days") : pending.promise), [days], { keep: "panel" });
        seen.push({ data: resource.data, loading: resource.loading, refreshing: resource.refreshing });
        return resource;
      },
      { initialProps: { days: 30 } },
    );
    await waitFor(() => expect(result.current.data).toBe("thirty days"));
    const before = seen.length;

    rerender({ days: 7 });
    expect(seen[before]).toEqual({ data: "seven days", loading: false, refreshing: true });
    expect(seen.slice(before).every((render) => render.data === "seven days")).toBe(true);
  });

  it("forgets every kept answer when a write settles", async () => {
    answerWrites();
    await visit("before the write");
    await postJSON("/api/jobs/1/save");

    expect(open({ keep: "panel" }).seen[0]).toEqual({ data: null, loading: true, refreshing: false });
  });

  it("forgets them when a write fails too", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response("{}", { status: 500 })));
    await visit("before the write");
    await expect(postJSON("/api/jobs/1/save")).rejects.toThrow();

    expect(open({ keep: "panel" }).seen[0].data).toBeNull();
  });

  it("keeps them across a role's viewed mark, which no kept read shows", async () => {
    answerWrites();
    await visit("before the role was opened");
    await api.markJobViewed(101);

    expect(open({ keep: "panel" }).seen[0].data).toBe("before the role was opened");
  });

  it.each([
    ["a follow", () => api.setCompanySelection({ follow: ["nvidia"], unfollow: [] })],
    ["a save", () => api.setFavorite(101, true)],
    ["a dismissal", () => api.dismissJob(101)],
    ["a settings change", () => api.saveLocale({ language: "en" })],
  ])("still forgets them after %s", async (_name, write) => {
    answerWrites();
    await visit("before the change");
    await write();

    expect(open({ keep: "panel" }).seen[0].data).toBeNull();
  });

  it("does not keep an answer from a read that was running when a write settled", async () => {
    answerWrites();
    const running = open({ keep: "panel" });
    await postJSON("/api/jobs/1/save");
    await act(async () => running.pending.resolve("maybe from before the write"));
    expect(running.result.current.data).toBe("maybe from before the write");
    running.unmount();

    expect(open({ keep: "panel" }).seen[0].data).toBeNull();
  });

  it("keeps showing the kept answer when its refresh fails, and says why", async () => {
    await visit("monday");
    const { result, pending } = open({ keep: "panel" });
    await act(async () => pending.reject(new Error("offline")));

    expect(result.current.data).toBe("monday");
    expect(result.current.error).toBeNull();
    expect(result.current.refreshError).toEqual(new Error("offline"));
    expect(result.current.refreshing).toBe(false);
  });

  it("retry reloads from scratch, never from the kept answer", async () => {
    await visit("monday");
    const { result, pending } = open({ keep: "panel" });
    await act(async () => pending.resolve("tuesday"));

    act(() => result.current.retry());
    expect(result.current.data).toBeNull();
    expect(result.current.loading).toBe(true);
  });

  it("keeps nothing when a dependency is a function", async () => {
    const format = (value: string) => value;
    const { result, unmount } = renderHook(() =>
      useAsyncResource(() => Promise.resolve("monday"), [format], { keep: "panel" }));
    await waitFor(() => expect(result.current.data).toBe("monday"));
    unmount();

    const again = renderHook(() =>
      useAsyncResource(() => new Promise<string>(() => {}), [format], { keep: "panel" }));
    expect(again.result.current.loading).toBe(true);
  });

  it("drops the oldest answer past its limit, and a re-kept one counts as newest", () => {
    const since = writesSettled();
    keepAnswer("first", 1, since);
    keepAnswer("second", 2, since);
    for (let index = 0; index < 38; index += 1) keepAnswer(`filler ${index}`, index, since);
    keepAnswer("first", 1, since);
    keepAnswer("one too many", 41, since);

    expect(keptAnswer("first")).toEqual({ value: 1 });
    expect(keptAnswer("second")).toBeUndefined();
    expect(keptAnswer("one too many")).toEqual({ value: 41 });
  });
});
