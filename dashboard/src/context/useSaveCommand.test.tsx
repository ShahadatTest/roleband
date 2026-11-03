import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useJobActions } from "./JobWorkspace";
import { useMissionActions } from "./MissionState";
import { useSaveCommand } from "./useSaveCommand";

/* The save command's obligation: a write the server
 * confirmed refreshes the counts and is announced; a superseded or failed one
 * announces nothing. The write ordering underneath is the real
 * `useRoleSaves`; only the two announcements are watched. */

vi.mock("./JobWorkspace", () => ({ useJobActions: vi.fn() }));
vi.mock("./MissionState", () => ({ useMissionActions: vi.fn() }));

let refreshStats: ReturnType<typeof vi.fn>;
let savedChanged: ReturnType<typeof vi.fn>;

beforeEach(() => {
  refreshStats = vi.fn();
  savedChanged = vi.fn();
  vi.mocked(useMissionActions).mockReturnValue({ refreshStats } as never);
  vi.mocked(useJobActions).mockReturnValue({ savedChanged } as never);
});

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<T>((res, rej) => { resolve = res; reject = rej; });
  return { promise, resolve, reject };
}

describe("useSaveCommand", () => {
  it("refreshes the counts and announces a save the server confirmed", async () => {
    const { result } = renderHook(() => useSaveCommand());
    const shown: boolean[] = [];
    let outcome: unknown;
    await act(async () => {
      outcome = await result.current({
        jobId: 702, was: false, next: true,
        show: (on) => shown.push(on),
        send: () => Promise.resolve({ job_id: 702, is_favorite: true }),
      });
    });
    expect(outcome).toEqual({ jobId: 702, saved: true, outcome: "saved" });
    expect(shown).toEqual([true]);
    expect(refreshStats).toHaveBeenCalledTimes(1);
    expect(savedChanged).toHaveBeenCalledExactlyOnceWith({ jobId: 702, saved: true });
  });

  it("announces only the newest write when an older one fails behind it", async () => {
    const { result } = renderHook(() => useSaveCommand());
    const first = deferred<unknown>();
    const shown: boolean[] = [];
    let save!: Promise<unknown>;
    let unsave!: Promise<unknown>;
    act(() => {
      save = result.current({ jobId: 7, was: false, next: true, show: (on) => shown.push(on), send: () => first.promise });
      unsave = result.current({ jobId: 7, was: true, next: false, show: (on) => shown.push(on), send: () => Promise.resolve(null) });
    });
    await act(async () => first.reject(new Error("offline")));
    await expect(save).resolves.toEqual({ jobId: 7, saved: true, outcome: "superseded" });
    await expect(unsave).resolves.toEqual({ jobId: 7, saved: false, outcome: "saved" });
    // The superseded failure repainted nothing and told no one; the newest
    // write decided, once.
    expect(shown).toEqual([true, false]);
    expect(refreshStats).toHaveBeenCalledTimes(1);
    expect(savedChanged).toHaveBeenCalledExactlyOnceWith({ jobId: 7, saved: false });
  });

  it("rejects a failed newest write and announces nothing", async () => {
    const { result } = renderHook(() => useSaveCommand());
    const shown: boolean[] = [];
    let failed!: Promise<unknown>;
    act(() => {
      failed = result.current({
        jobId: 9, was: false, next: true,
        show: (on) => shown.push(on),
        send: () => Promise.reject(new Error("offline")),
      });
    });
    await act(async () => { await expect(failed).rejects.toThrow("offline"); });
    // Painted saved, then back to what the server holds.
    expect(shown).toEqual([true, false]);
    expect(refreshStats).not.toHaveBeenCalled();
    expect(savedChanged).not.toHaveBeenCalled();
  });
});
