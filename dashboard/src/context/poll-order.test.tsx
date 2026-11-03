import { act, render, screen } from "@testing-library/react";
import { StrictMode } from "react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api, type Stats, type SystemStatus } from "../api";
import { statsFixture, statusFixture } from "../test/fixtures";
import { MissionStateProvider, useMissionActions, useMissionStats } from "./MissionState";
import {
  SyncStateProvider, useReferenceVersion, useSourceSwitch, useStatusPoll, useSyncActions, useSyncEpoch, useSyncStatus,
  type SyncTrigger,
} from "./SyncState";

/* The shared reads answer in the order they STARTED, never the order they
 * finished. Feature screens get this from `useAsyncResource`; the two
 * app-wide providers hold it themselves. Without it a save's stats refresh can
 * be overwritten by an older poll that comes back later, and an older
 * "running" status revives a finished run and fires its completion a second
 * time. The real providers and router are mounted; only the API
 * promises are controlled. */

vi.mock("../api", () => ({
  api: { stats: vi.fn(), status: vi.fn(), sync: vi.fn(), cancelSync: vi.fn() },
}));

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((res, rej) => { resolve = res; reject = rej; });
  return { promise, resolve, reject };
}

type Pending<T> = ReturnType<typeof deferred<T>>;

function controlled<T>(fn: unknown): Pending<T>[] {
  const requests: Pending<T>[] = [];
  vi.mocked(fn as () => Promise<T>).mockImplementation(() => {
    const request = deferred<T>();
    requests.push(request);
    return request.promise;
  });
  return requests;
}

function Readout() {
  const stats = useMissionStats();
  const { status, statusFailed } = useSyncStatus();
  const { notificationVersion, referenceVersion, pricesVersion } = useSyncEpoch();
  return (
    <>
      <output data-testid="saved">{String(stats?.saved_total)}</output>
      <output data-testid="running">{String(status?.running)}</output>
      <output data-testid="failed">{String(statusFailed)}</output>
      <output data-testid="epoch">{notificationVersion}</output>
      <output data-testid="reference">{referenceVersion}</output>
      <output data-testid="prices">{pricesVersion}</output>
    </>
  );
}

let actions: { refreshStats: () => void; triggerSync: (c?: string[]) => Promise<SyncTrigger> };
function Verbs() {
  const { refreshStats } = useMissionActions();
  const { triggerSync } = useSyncActions();
  actions = { refreshStats, triggerSync };
  return null;
}

function mount({ strict = false } = {}) {
  const app = (
    <MemoryRouter>
      <MissionStateProvider>
        <SyncStateProvider>
          <Readout />
          <Verbs />
        </SyncStateProvider>
      </MissionStateProvider>
    </MemoryRouter>
  );
  return render(strict ? <StrictMode>{app}</StrictMode> : app);
}

const text = (id: string) => screen.getByTestId(id).textContent;

async function flush() {
  await act(async () => {
    for (let i = 0; i < 5; i += 1) await Promise.resolve();
  });
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.useFakeTimers();
});
afterEach(() => vi.useRealTimers());

describe("the header counts", () => {
  it("keep a newer answer when an older one arrives after it", async () => {
    const stats = controlled<Stats>(api.stats);
    controlled<SystemStatus>(api.status);
    mount();
    act(() => actions.refreshStats()); // a save's refresh, after the mount's read
    expect(stats).toHaveLength(2);
    await act(async () => stats[1].resolve({ ...statsFixture, saved_total: 1 }));
    expect(text("saved")).toBe("1");
    await act(async () => stats[0].resolve({ ...statsFixture, saved_total: 0 }));
    expect(text("saved")).toBe("1");
  });

  it("still take an answer that is the newest one asked for (the control)", async () => {
    const stats = controlled<Stats>(api.stats);
    controlled<SystemStatus>(api.status);
    mount();
    await act(async () => stats[0].resolve({ ...statsFixture, saved_total: 3 }));
    expect(text("saved")).toBe("3");
  });
});

describe("the sync status", () => {
  it("never revives a finished run from an older answer, and completes it once", async () => {
    vi.mocked(api.stats).mockResolvedValue(statsFixture);
    const status = controlled<SystemStatus>(api.status);
    mount();
    await act(async () => status[0].resolve({ ...statusFixture, running: true, manual_queued: [] }));
    expect(text("running")).toBe("true");
    // The live cadence keeps the clock: the answer that started it is not
    // asked for again at once.
    expect(status).toHaveLength(1);
    act(() => vi.advanceTimersByTime(3_000));
    expect(status).toHaveLength(2);
    act(() => vi.advanceTimersByTime(3_000));
    expect(status).toHaveLength(3);
    await act(async () => status[2].resolve({ ...statusFixture, running: false, manual_queued: [] }));
    expect([text("running"), text("epoch")]).toEqual(["false", "1"]);
    const statsCalls = vi.mocked(api.stats).mock.calls.length;

    await act(async () => status[1].resolve({ ...statusFixture, running: true, manual_queued: [] }));
    expect(text("running")).toBe("false");
    expect(vi.mocked(api.stats).mock.calls.length).toBe(statsCalls);
    // The idle tick also brings the counts' own poll; measured after it.
    act(() => vi.advanceTimersByTime(60_000));
    const polled = vi.mocked(api.stats).mock.calls.length;
    await act(async () => status[3].resolve({ ...statusFixture, running: false, manual_queued: [] }));
    expect([text("running"), text("epoch")]).toEqual(["false", "1"]);
    expect(vi.mocked(api.stats).mock.calls.length).toBe(polled); // no second completion refresh
  });

  it("is not marked failed by an older read that failed after a newer one answered", async () => {
    vi.mocked(api.stats).mockResolvedValue(statsFixture);
    const status = controlled<SystemStatus>(api.status);
    vi.mocked(api.sync).mockResolvedValue({ status: "started", companies: [] } as never);
    mount();
    let triggered!: Promise<SyncTrigger>;
    act(() => { triggered = actions.triggerSync(); });
    await flush();
    // Out: the mount's read and the trigger's own read, which is the newest.
    expect(status).toHaveLength(2);
    await act(async () => status[1].resolve({ ...statusFixture, running: false, manual_queued: [] }));
    await act(async () => { await triggered; });
    await act(async () => status[0].reject(new Error("timed out")));
    expect(text("failed")).toBe("false");
  });

  it("is read at once under StrictMode, whose practice unmount retires the first read", async () => {
    vi.mocked(api.stats).mockResolvedValue(statsFixture);
    vi.mocked(api.status).mockResolvedValue({ ...statusFixture, running: true, manual_queued: [] });
    mount({ strict: true });
    await flush();
    expect(text("running")).toBe("true");
  });

  it("does nothing with an answer that arrives after the app unmounted", async () => {
    vi.mocked(api.stats).mockResolvedValue(statsFixture);
    const status = controlled<SystemStatus>(api.status);
    const view = mount();
    await act(async () => status[0].resolve({ ...statusFixture, running: true, manual_queued: [] }));
    act(() => vi.advanceTimersByTime(3_000));
    const statsCalls = vi.mocked(api.stats).mock.calls.length;
    view.unmount();
    await act(async () => status[1].resolve({ ...statusFixture, running: false, manual_queued: [] }));
    expect(vi.mocked(api.stats).mock.calls.length).toBe(statsCalls);
  });
});


describe("the reference epoch (plugin plan §6.8)", () => {
  it("advances when a poll sees a new reference change, never on the first read", async () => {
    vi.mocked(api.stats).mockResolvedValue(statsFixture);
    const status = controlled<SystemStatus>(api.status);
    mount();
    await act(async () => status[0].resolve(statusFixture));
    expect(text("reference")).toBe("0"); // loading the app is not a change

    act(() => vi.advanceTimersByTime(60_000));
    await act(async () => status[1].resolve(statusFixture));
    expect(text("reference")).toBe("0"); // the same change seen again

    act(() => vi.advanceTimersByTime(60_000));
    await act(async () => status[2].resolve({
      ...statusFixture,
      reference: { ...statusFixture.reference, last_change_id: 5 },
    }));
    expect(text("reference")).toBe("1");
    expect(text("epoch")).toBe("0"); // estimates moving is not a finished scan
  });
});


describe("one switch moment for every surface", () => {
  const moved = (id: number): SystemStatus => ({
    ...statusFixture,
    reference: { ...statusFixture.reference, last_change_id: id },
  });

  function Follower({ refresh, poll }: { refresh: () => Promise<void>; poll: { now?: () => Promise<void> } }) {
    useSourceSwitch(refresh);
    poll.now = useStatusPoll();
    return <output data-testid="version">{useReferenceVersion()}</output>;
  }

  it("a surface re-reads in place once per applied switch, never on mount or on a poll that saw none", async () => {
    vi.mocked(api.stats).mockResolvedValue(statsFixture);
    const status = controlled<SystemStatus>(api.status);
    const refresh = vi.fn(async () => {});
    const poll: { now?: () => Promise<void> } = {};
    render(
      <MemoryRouter>
        <MissionStateProvider>
          <SyncStateProvider>
            <Follower refresh={refresh} poll={poll} />
          </SyncStateProvider>
        </MissionStateProvider>
      </MemoryRouter>,
    );
    await act(async () => status[0].resolve(moved(4)));
    act(() => vi.advanceTimersByTime(60_000));
    await act(async () => status[1].resolve(moved(4)));
    expect(refresh).not.toHaveBeenCalled();

    // A plugin decision polls at once, not at the next idle tick.
    await act(async () => { void poll.now?.(); });
    expect(status).toHaveLength(3);
    await act(async () => status[2].resolve(moved(5)));
    expect(refresh).toHaveBeenCalledTimes(1);
    expect(refresh).toHaveBeenCalledWith({ preserveData: true });
    expect(screen.getByTestId("version").textContent).toBe("1");
  });

  it("outside the provider (a component test) it follows nothing and polls nothing", async () => {
    const refresh = vi.fn(async () => {});
    const poll: { now?: () => Promise<void> } = {};
    render(<Follower refresh={refresh} poll={poll} />);
    await act(async () => { await poll.now?.(); });
    expect(refresh).not.toHaveBeenCalled();
    expect(api.status).not.toHaveBeenCalled();
    expect(screen.getByTestId("version").textContent).toBe("0");
  });
});


describe("the supervised jobs", () => {
  const job = (key: string, state: "running" | "idle") => ({
    key, job: key, state, reason: null, since: "2026-07-13T05:00:00Z", next_at: null,
    run_id: state === "running" ? 7 : null, progress: null, waiting: null, queued: 0,
  });

  it("poll fast while any job runs, and the end of a prices run advances the prices epoch once", async () => {
    vi.mocked(api.stats).mockResolvedValue(statsFixture);
    const status = controlled<SystemStatus>(api.status);
    mount();
    await act(async () => status[0].resolve({ ...statusFixture, jobs: [job("prices", "running")] }));
    expect(status).toHaveLength(1);
    act(() => vi.advanceTimersByTime(3_000));
    expect(status).toHaveLength(2); // a running job polls on the live cadence
    expect(text("prices")).toBe("0");
    await act(async () => status[1].resolve({ ...statusFixture, jobs: [job("prices", "idle")] }));
    expect(text("prices")).toBe("1");
    // A prices run is not a scan's completion.
    expect(text("epoch")).toBe("0");
    act(() => vi.advanceTimersByTime(3_000));
    expect(status).toHaveLength(2); // back on the idle cadence
    act(() => vi.advanceTimersByTime(57_000));
    expect(status).toHaveLength(3);
  });

  it("leave the prices epoch alone when another job ends", async () => {
    vi.mocked(api.stats).mockResolvedValue(statsFixture);
    const status = controlled<SystemStatus>(api.status);
    mount();
    await act(async () => status[0].resolve({ ...statusFixture, jobs: [job("directory", "running")] }));
    act(() => vi.advanceTimersByTime(3_000));
    await act(async () => status[1].resolve({ ...statusFixture, jobs: [job("directory", "idle")] }));
    expect(text("prices")).toBe("0");
  });
});


describe("a page no one is looking at", () => {
  let visibility: DocumentVisibilityState = "visible";
  beforeEach(() => {
    visibility = "visible";
    Object.defineProperty(document, "visibilityState", { configurable: true, get: () => visibility });
  });
  afterEach(() => {
    Object.defineProperty(document, "visibilityState", { configurable: true, get: () => "visible" });
  });
  const show = (state: DocumentVisibilityState) =>
    act(() => {
      visibility = state;
      document.dispatchEvent(new Event("visibilitychange"));
    });

  it("polls neither the status nor the counts while hidden, and reads both once on return", async () => {
    vi.mocked(api.stats).mockResolvedValue(statsFixture);
    vi.mocked(api.status).mockResolvedValue({ ...statusFixture, running: true, manual_queued: [] });
    mount();
    await flush();
    const status = vi.mocked(api.status).mock.calls.length;
    const stats = vi.mocked(api.stats).mock.calls.length;

    show("hidden");
    act(() => vi.advanceTimersByTime(10 * 60_000));
    await flush();
    expect(vi.mocked(api.status).mock.calls.length).toBe(status);
    expect(vi.mocked(api.stats).mock.calls.length).toBe(stats);

    show("visible");
    await flush();
    expect(vi.mocked(api.status).mock.calls.length).toBe(status + 1);
    expect(vi.mocked(api.stats).mock.calls.length).toBeGreaterThanOrEqual(stats + 1);
    // And the live cadence resumes.
    act(() => vi.advanceTimersByTime(3_000));
    expect(vi.mocked(api.status).mock.calls.length).toBe(status + 2);
  });

  it("reads at once when shown again, however short the absence", async () => {
    vi.mocked(api.stats).mockResolvedValue(statsFixture);
    vi.mocked(api.status).mockResolvedValue({ ...statusFixture, running: false, manual_queued: [] });
    mount();
    await flush();
    const status = vi.mocked(api.status).mock.calls.length;

    show("hidden");
    act(() => vi.advanceTimersByTime(1_000));
    show("visible");
    await flush();
    expect(vi.mocked(api.status).mock.calls.length).toBe(status + 1);
  });
});
