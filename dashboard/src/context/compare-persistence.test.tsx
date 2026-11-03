import { act, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../api";
import { COMPARE_CAP, JobWorkspaceProvider, useJobActions, useJobWorkspace } from "./JobWorkspace";

/* The compare selection is durable.
 *
 * Held in `useState` alone, a reload would drop the roles and the rail count
 * while the star beside the same row survived — two star-like gestures
 * teaching two rules.
 *
 * What is worth pinning is not "it calls the endpoint" but the four ways a
 * write-behind cache can lie: an echo landing out of order, a hydrate landing
 * after the user has already picked, a response the client refuses to believe,
 * and a failure it hides. Each of those renders a wrong count, the same
 * defect a non-durable selection has, only intermittent.
 */

vi.mock("../api", () => ({
  api: {
    markJobViewed: vi.fn().mockResolvedValue({}),
    compareSelection: vi.fn(),
    setCompareSelection: vi.fn(),
  },
}));


let verbs: ReturnType<typeof useJobActions>;

function Probe() {
  const { compareIds, compareHydrated, compareSyncFailed } = useJobWorkspace();
  verbs = useJobActions();
  return (
    <>
      <span data-testid="ids">{[...compareIds].join(",")}</span>
      <span data-testid="hydrated">{String(compareHydrated)}</span>
      <span data-testid="unsaved">{String(compareSyncFailed)}</span>
    </>
  );
}

const ids = () => screen.getByTestId("ids").textContent;

function mount() {
  return render(
    <MemoryRouter>
      <JobWorkspaceProvider>
        <Probe />
      </JobWorkspaceProvider>
    </MemoryRouter>,
  );
}

/** A promise the test decides when to settle. */
function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(api.compareSelection).mockResolvedValue({ job_ids: [] });
  // The honest default: the store echoes what it stored.
  vi.mocked(api.setCompareSelection).mockImplementation(async (jobIds: number[]) => ({
    job_ids: jobIds,
  }));
});

describe("the compare selection survives the tab", () => {
  it("restores what was stored, which is the whole point", async () => {
    vi.mocked(api.compareSelection).mockResolvedValue({ job_ids: [7, 3] });
    mount();

    await waitFor(() => expect(ids()).toBe("7,3"));
    // Order is contract: the beacon docks level with the role picked last.
    expect(screen.getByTestId("hydrated").textContent).toBe("true");
  });

  it("reports hydration separately from emptiness", async () => {
    const read = deferred<{ job_ids: number[] }>();
    vi.mocked(api.compareSelection).mockReturnValue(read.promise);
    mount();

    // Empty and unread look identical and mean opposite things.
    expect(ids()).toBe("");
    expect(screen.getByTestId("hydrated").textContent).toBe("false");

    await act(async () => read.resolve({ job_ids: [1, 2] }));
    await waitFor(() => expect(screen.getByTestId("hydrated").textContent).toBe("true"));
    expect(ids()).toBe("1,2");
  });

  it("persists a toggle without waiting for the round trip", async () => {
    mount();
    await waitFor(() => expect(screen.getByTestId("hydrated").textContent).toBe("true"));

    await act(async () => verbs.toggleCompare(4));

    // On screen immediately — the gesture is hover-speed.
    expect(ids()).toBe("4");
    expect(vi.mocked(api.setCompareSelection)).toHaveBeenCalledWith([4]);
  });

  it("sends the whole selection, so a failed write is repaired by the next one", async () => {
    mount();
    await waitFor(() => expect(screen.getByTestId("hydrated").textContent).toBe("true"));

    await act(async () => verbs.toggleCompare(1));
    await act(async () => verbs.toggleCompare(2));

    expect(vi.mocked(api.setCompareSelection).mock.calls.map(([arg]) => arg)).toEqual([[1], [1, 2]]);
  });
});

describe("what a write-behind cache gets wrong", () => {
  it("does not let a hydrate overwrite a selection the user already made", async () => {
    const read = deferred<{ job_ids: number[] }>();
    vi.mocked(api.compareSelection).mockReturnValue(read.promise);
    mount();

    // The user is faster than the read — which is the normal case on a warm tab.
    await act(async () => verbs.toggleCompare(9));
    expect(ids()).toBe("9");

    await act(async () => read.resolve({ job_ids: [1, 2, 3] }));
    await waitFor(() => expect(screen.getByTestId("hydrated").textContent).toBe("true"));

    expect(ids(), "the stored set clobbered a newer choice the user had made").toBe("9");
  });

  it("adopts the store's answer when it differs from what was asked", async () => {
    // The cap and the existence check live in the store; the client is not the
    // authority on what was kept.
    vi.mocked(api.setCompareSelection).mockResolvedValue({ job_ids: [1, 2] });
    mount();
    await waitFor(() => expect(screen.getByTestId("hydrated").textContent).toBe("true"));

    await act(async () => verbs.setCompare([1, 2, 404]));

    await waitFor(() => expect(ids()).toBe("1,2"));
  });

  it("does not let a superseded echo walk the selection backwards", async () => {
    const first = deferred<{ job_ids: number[] }>();
    const second = deferred<{ job_ids: number[] }>();
    vi.mocked(api.setCompareSelection)
      .mockReturnValueOnce(first.promise)
      .mockReturnValueOnce(second.promise);
    mount();
    await waitFor(() => expect(screen.getByTestId("hydrated").textContent).toBe("true"));

    await act(async () => verbs.toggleCompare(1));
    await act(async () => verbs.toggleCompare(2));
    expect(ids()).toBe("1,2");

    // The older write answers while a newer one is already queued. Adopting it
    // would drop role 2 from a selection the user can see, with nothing to
    // explain it. Asserted HERE, before the newer echo lands: the end state is
    // right either way, so only the intermediate one can catch this.
    await act(async () => first.resolve({ job_ids: [1] }));
    expect(ids(), "a superseded echo walked the selection backwards").toBe("1,2");

    await act(async () => second.resolve({ job_ids: [1, 2] }));
    await waitFor(() => expect(ids()).toBe("1,2"));
  });

  it("keeps the selection and says so when the write fails", async () => {
    vi.mocked(api.setCompareSelection).mockRejectedValue(new Error("offline"));
    mount();
    await waitFor(() => expect(screen.getByTestId("hydrated").textContent).toBe("true"));

    await act(async () => verbs.toggleCompare(5));

    // Discarding the user's picks here would make them vanish, the defect a
    // durable selection exists to prevent, only harder to explain. It is kept AND
    // declared unsaved, so the beacon can say the reload will not bring it back.
    expect(ids()).toBe("5");
    await waitFor(() => expect(screen.getByTestId("unsaved").textContent).toBe("true"));
  });

  it("stops claiming unsaved once a write lands", async () => {
    vi.mocked(api.setCompareSelection).mockRejectedValueOnce(new Error("offline"));
    mount();
    await waitFor(() => expect(screen.getByTestId("hydrated").textContent).toBe("true"));

    await act(async () => verbs.toggleCompare(5));
    await waitFor(() => expect(screen.getByTestId("unsaved").textContent).toBe("true"));

    // Replace-all: the next write carries the whole selection, so a recovered
    // connection repairs the stored set without a retry queue.
    await act(async () => verbs.toggleCompare(6));

    await waitFor(() => expect(screen.getByTestId("unsaved").textContent).toBe("false"));
    expect(ids()).toBe("5,6");
    expect(vi.mocked(api.setCompareSelection)).toHaveBeenLastCalledWith([5, 6]);
  });

  it("stays quiet when the initial read fails, and still reports itself hydrated", async () => {
    vi.mocked(api.compareSelection).mockRejectedValue(new Error("offline"));
    mount();

    await waitFor(() => expect(screen.getByTestId("hydrated").textContent).toBe("true"));
    expect(ids()).toBe("");
    // A background read may fail quietly; a screen stuck
    // on a spinner forever is the worse outcome, and nothing is unsaved yet.
    expect(screen.getByTestId("unsaved").textContent).toBe("false");
  });
});

describe("the cap and the verbs", () => {
  it("refuses the role past the cap, and writes nothing for the refusal", async () => {
    mount();
    await waitFor(() => expect(screen.getByTestId("hydrated").textContent).toBe("true"));

    const full = Array.from({ length: COMPARE_CAP }, (_, i) => i + 1);
    await act(async () => verbs.setCompare(full));
    vi.mocked(api.setCompareSelection).mockClear();

    await act(async () => verbs.toggleCompare(COMPARE_CAP + 1));

    expect(ids()).toBe(full.join(","));
    expect(vi.mocked(api.setCompareSelection)).not.toHaveBeenCalled();
  });

  it("clamps a selection stored under a larger cap instead of rendering it", async () => {
    // A stored selection can outlive a change to the cap. The store clamps
    // too, but the screen is what has three columns: a read that answers more
    // roles must not paint more.
    vi.mocked(api.compareSelection).mockResolvedValue({ job_ids: [1, 2, 3, 4, 5] });
    mount();

    await waitFor(() => expect(screen.getByTestId("hydrated").textContent).toBe("true"));
    expect(ids()).toBe(Array.from({ length: COMPARE_CAP }, (_, i) => i + 1).join(","));
  });

  it("clears through the store, not just on screen", async () => {
    mount();
    await waitFor(() => expect(screen.getByTestId("hydrated").textContent).toBe("true"));
    await act(async () => verbs.setCompare([1, 2]));

    await act(async () => verbs.clearCompare());

    expect(ids()).toBe("");
    expect(vi.mocked(api.setCompareSelection)).toHaveBeenLastCalledWith([]);
  });

  it("drops roles that are gone, and leaves the rest alone", async () => {
    mount();
    await waitFor(() => expect(screen.getByTestId("hydrated").textContent).toBe("true"));
    await act(async () => verbs.setCompare([1, 2, 3]));

    await act(async () => verbs.dropCompare([2]));

    expect(ids()).toBe("1,3");
    expect(vi.mocked(api.setCompareSelection)).toHaveBeenLastCalledWith([1, 3]);
  });

  it("writes nothing when there is nothing to drop", async () => {
    mount();
    await waitFor(() => expect(screen.getByTestId("hydrated").textContent).toBe("true"));
    await act(async () => verbs.setCompare([1, 2]));
    vi.mocked(api.setCompareSelection).mockClear();

    await act(async () => verbs.dropCompare([99]));

    expect(ids()).toBe("1,2");
    expect(vi.mocked(api.setCompareSelection)).not.toHaveBeenCalled();
  });
});
