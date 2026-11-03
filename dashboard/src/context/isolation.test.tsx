import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, useNavigate } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../api";
import { statsFixture, statusFixture } from "../test/fixtures";
import { AppProviders } from "./AppProviders";
import { useJobActions, useJobWorkspace } from "./JobWorkspace";
import { useBoardQuery, useMissionActions, useMissionState, useMissionStats } from "./MissionState";
import { useSyncActions, useSyncEpoch, useSyncStatus } from "./SyncState";

/* Render isolation of the shared contexts.
 *
 * One context object holding the compare selection, the board query, the
 * header stats AND the /api/status poll re-renders every dense surface on
 * screen — the board's rows, the compare grid, the register — on each tick of
 * a poll that runs every 3 seconds while a sync is live, for state none of
 * them read.
 *
 * These are render COUNTS, not structure assertions: a split that type-checks
 * but leaves the subscriptions joined would pass every other test in the repo.
 *
 * Each domain is split again, by CADENCE and by value-vs-verb. Splitting
 * by topic alone was not enough: the shell reads stats and lenses but no query,
 * and still re-rendered on every keystroke; the notifications controller reads
 * an epoch that moves once per completed run, and still re-rendered every 3
 * seconds. A stable verb sharing an object with a churning value is a
 * subscription to the value. */

vi.mock("../api", () => ({
  api: {
    stats: vi.fn(),
    status: vi.fn(),
    sync: vi.fn(),
    cancelSync: vi.fn(),
    markJobViewed: vi.fn(),
    // JobWorkspace reads the stored compare selection on mount and writes it
    // back on every change.
    compareSelection: vi.fn().mockResolvedValue({ job_ids: [] }),
    setCompareSelection: vi.fn((jobIds: number[]) => Promise.resolve({ job_ids: jobIds })),
  },
}));


/** A probe that renders only what its own context gives it, and counts. */
function probe(useCtx: () => unknown) {
  const renders = { count: 0 };
  const Probe = () => {
    renders.count += 1;
    useCtx();
    return null;
  };
  return { renders, Probe };
}

let running = false;

beforeEach(() => {
  vi.clearAllMocks();
  running = false;
  vi.mocked(api.stats).mockResolvedValue(statsFixture);
  vi.mocked(api.status).mockImplementation(async () => ({ ...statusFixture, running, manual_queued: [] }));
  vi.mocked(api.markJobViewed).mockImplementation(async (id) => ({ job_id: id, viewed_at: "2026-10-08T12:00:00Z" }));
  vi.useFakeTimers({ shouldAdvanceTime: true });
});

afterEach(() => {
  vi.useRealTimers();
});

/** Let the mounted providers finish their first stats/status reads. */
async function settle() {
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });
}

describe("context isolation", () => {
  it("a status poll does not render the surfaces that never read status", async () => {
    const job = probe(useJobWorkspace);
    const mission = probe(() => [useMissionStats(), useMissionState()]);
    const sync = probe(useSyncStatus);

    render(
      <MemoryRouter>
        <AppProviders>
          <job.Probe />
          <mission.Probe />
          <sync.Probe />
        </AppProviders>
      </MemoryRouter>,
    );
    await settle();

    const before = { job: job.renders.count, mission: mission.renders.count, sync: sync.renders.count };
    expect(vi.mocked(api.status).mock.calls.length).toBeGreaterThan(0);

    // Three idle ticks: the status object is replaced each time, so the sync
    // context's value changes and its subscribers must re-render...
    const pollsBefore = vi.mocked(api.status).mock.calls.length;
    for (let i = 0; i < 3; i += 1) {
      await act(async () => {
        vi.advanceTimersByTime(60_000);
        await Promise.resolve();
        await Promise.resolve();
      });
    }
    await waitFor(() => expect(vi.mocked(api.status).mock.calls.length).toBeGreaterThan(pollsBefore));

    // ...and the two that do not read status must not have moved at all. This
    // is the assertion the split exists for.
    expect(job.renders.count, "job workspace re-rendered on a status tick").toBe(before.job);
    expect(mission.renders.count, "mission state re-rendered on a status tick").toBe(before.mission);
    expect(sync.renders.count).toBeGreaterThan(before.sync);
  });

  it("a compare change does not render the freshness/sync surfaces", async () => {
    const sync = probe(useSyncStatus);
    const mission = probe(() => [useMissionStats(), useMissionState()]);
    let toggle!: (id: number) => void;
    const Selector = () => {
      toggle = useJobActions().toggleCompare;
      return <span data-testid="n">{useJobWorkspace().compareIds.size}</span>;
    };

    render(
      <MemoryRouter>
        <AppProviders>
          <Selector />
          <sync.Probe />
          <mission.Probe />
        </AppProviders>
      </MemoryRouter>,
    );
    await settle();
    const before = { sync: sync.renders.count, mission: mission.renders.count };

    await act(async () => toggle(1));
    expect(screen.getByTestId("n").textContent).toBe("1");
    await act(async () => toggle(2));
    expect(screen.getByTestId("n").textContent).toBe("2");

    expect(sync.renders.count, "sync surfaces re-rendered on a compare change").toBe(before.sync);
    expect(mission.renders.count, "mission state re-rendered on a compare change").toBe(before.mission);
  });

  it("typing the board query does not render the job rows or the sync surfaces", async () => {
    const job = probe(useJobWorkspace);
    const sync = probe(useSyncStatus);
    const Search = () => {
      const { search } = useBoardQuery();
      const { setSearch } = useMissionActions();
      return <input aria-label="q" value={search} onChange={(e) => setSearch(e.target.value)} />;
    };

    render(
      <MemoryRouter>
        <AppProviders>
          <Search />
          <job.Probe />
          <sync.Probe />
        </AppProviders>
      </MemoryRouter>,
    );
    await settle();
    const before = { job: job.renders.count, sync: sync.renders.count };

    await userEvent.type(screen.getByLabelText("q"), "staff");
    expect(screen.getByLabelText("q")).toHaveValue("staff");

    // Five keystrokes, and the dense job surfaces do not move.
    expect(job.renders.count, "job workspace re-rendered while typing a query").toBe(before.job);
    expect(sync.renders.count, "sync surfaces re-rendered while typing a query").toBe(before.sync);
  });

  it("still polls status on one timer, and the cadence still tightens for a live run", async () => {
    // The split must not have quietly duplicated or dropped the poller — the
    // whole reason it is centralized is that the badge and the button share it.
    render(
      <MemoryRouter>
        <AppProviders>
          <div />
        </AppProviders>
      </MemoryRouter>,
    );
    await settle();
    const idleCalls = vi.mocked(api.status).mock.calls.length;

    await act(async () => {
      vi.advanceTimersByTime(60_000);
      await Promise.resolve();
    });
    const afterIdleTick = vi.mocked(api.status).mock.calls.length;
    expect(afterIdleTick).toBe(idleCalls + 1); // one poller, not two

    // A live run tightens the cadence to 3s.
    running = true;
    await act(async () => {
      vi.advanceTimersByTime(60_000);
      await Promise.resolve();
      await Promise.resolve();
    });
    const beforeFast = vi.mocked(api.status).mock.calls.length;
    await act(async () => {
      vi.advanceTimersByTime(9_000);
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(vi.mocked(api.status).mock.calls.length).toBeGreaterThan(beforeFast + 1);
  });
});

/* Every case below stays GREEN under a three-context split that joins the
 * subscriptions inside a domain rather than across domains, which the probes
 * above cannot see because they read whole domains. */
describe("context isolation — cadence, not just topic", () => {
  it("a keystroke does not render the shell's stats/lens surfaces", async () => {
    // The app shell reads stats and the lenses and no query at all, so it has
    // no business re-rendering per character.
    const shell = probe(() => [useMissionStats(), useMissionState()]);
    const Search = () => {
      const { search } = useBoardQuery();
      const { setSearch } = useMissionActions();
      return <input aria-label="q" value={search} onChange={(e) => setSearch(e.target.value)} />;
    };
    render(
      <MemoryRouter>
        <AppProviders>
          <Search />
          <shell.Probe />
        </AppProviders>
      </MemoryRouter>,
    );
    await settle();
    const before = shell.renders.count;

    await userEvent.type(screen.getByLabelText("q"), "principal");
    expect(screen.getByLabelText("q")).toHaveValue("principal");
    expect(shell.renders.count, "the shell re-rendered while someone typed").toBe(before);
  });

  it("a status poll does not render the surfaces that only read the sync EPOCH", async () => {
    // notificationVersion advances once per completed run. The notifications
    // controller and the header bell read it and nothing else from sync, so a
    // 3s poll must not re-render them.
    const epoch = probe(useSyncEpoch);
    const status = probe(useSyncStatus);
    render(
      <MemoryRouter>
        <AppProviders>
          <epoch.Probe />
          <status.Probe />
        </AppProviders>
      </MemoryRouter>,
    );
    await settle();
    const before = { epoch: epoch.renders.count, status: status.renders.count };

    for (let i = 0; i < 3; i += 1) {
      await act(async () => {
        vi.advanceTimersByTime(60_000);
        await Promise.resolve();
        await Promise.resolve();
      });
    }
    expect(status.renders.count).toBeGreaterThan(before.status);
    expect(epoch.renders.count, "an epoch reader re-rendered on a status poll").toBe(before.epoch);
  });

  it("a stats refresh does not render the board's query or the job rows", async () => {
    // refreshStats is a verb: a screen that only calls it must not be
    // subscribed to the value it refreshes.
    const query = probe(useBoardQuery);
    const job = probe(useJobWorkspace);
    let refresh!: () => void;
    const Caller = () => {
      refresh = useMissionActions().refreshStats;
      return null;
    };
    render(
      <MemoryRouter>
        <AppProviders>
          <Caller />
          <query.Probe />
          <job.Probe />
        </AppProviders>
      </MemoryRouter>,
    );
    await settle();
    const before = { query: query.renders.count, job: job.renders.count };

    vi.mocked(api.stats).mockResolvedValue({ ...statsFixture, open_total: 999 });
    await act(async () => {
      refresh();
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(vi.mocked(api.stats).mock.calls.length).toBeGreaterThan(1);
    expect(query.renders.count, "the board query re-rendered on a stats refresh").toBe(before.query);
    expect(job.renders.count, "the job rows re-rendered on a stats refresh").toBe(before.job);
  });

  /* The counts poll answers every minute, and on most minutes nothing has
   * changed. Each answer is a new object, so without a comparison every reader
   * of the counts, the whole shell among them, would render for nothing. */
  async function tick() {
    await act(async () => {
      vi.advanceTimersByTime(60_000);
      await Promise.resolve();
      await Promise.resolve();
    });
  }
  const fresh = (patch: Partial<typeof statsFixture> = {}) =>
    vi.mocked(api.stats).mockImplementation(async () => ({
      ...statsFixture, by_company: { ...statsFixture.by_company }, ...patch,
    }));

  it("a counts poll with the same numbers renders nothing that reads them", async () => {
    fresh();
    const counts = probe(useMissionStats);
    render(<MemoryRouter><AppProviders><counts.Probe /></AppProviders></MemoryRouter>);
    await settle();
    const before = { renders: counts.renders.count, polls: vi.mocked(api.stats).mock.calls.length };

    await tick();
    await tick();
    expect(vi.mocked(api.stats).mock.calls.length).toBeGreaterThan(before.polls);
    expect(counts.renders.count, "a counts reader rendered for an unchanged answer").toBe(before.renders);
  });

  it("a counts poll with a new number renders its readers (the control)", async () => {
    fresh();
    const counts = probe(useMissionStats);
    render(<MemoryRouter><AppProviders><counts.Probe /></AppProviders></MemoryRouter>);
    await settle();
    const before = counts.renders.count;

    fresh({ by_company: { ...statsFixture.by_company, stripe: 4 } });
    await tick();
    expect(counts.renders.count).toBeGreaterThan(before);
  });

  it("a new count does not render the board, which reads only the lenses", async () => {
    fresh();
    const lenses = probe(useMissionState);
    const counts = probe(useMissionStats);
    render(<MemoryRouter><AppProviders><lenses.Probe /><counts.Probe /></AppProviders></MemoryRouter>);
    await settle();
    const before = { lenses: lenses.renders.count, counts: counts.renders.count };

    fresh({ open_total: statsFixture.open_total + 1 });
    await tick();
    expect(counts.renders.count).toBeGreaterThan(before.counts);
    expect(lenses.renders.count, "a lens reader rendered on a new count").toBe(before.lenses);
  });

  it("the verbs never change identity, so a verb-only consumer never re-renders", async () => {
    // The general form of all of the above. A route that only knows how to OPEN
    // a job must not re-render because someone ticked a compare checkbox.
    const seen = { job: new Set<unknown>(), mission: new Set<unknown>(), sync: new Set<unknown>() };
    let toggle!: (id: number) => void;
    let go!: (to: string) => void;
    const Watcher = () => {
      seen.job.add(useJobActions());
      seen.mission.add(useMissionActions());
      seen.sync.add(useSyncActions());
      toggle = useJobActions().toggleCompare;
      go = useNavigate();
      const { setSearch } = useMissionActions();
      return <button onClick={() => setSearch("x")}>go</button>;
    };
    render(
      <MemoryRouter>
        <AppProviders>
          <Watcher />
        </AppProviders>
      </MemoryRouter>,
    );
    await settle();
    await act(async () => toggle(1));
    await userEvent.click(screen.getByRole("button", { name: "go" }));
    for (let i = 0; i < 2; i += 1) {
      await act(async () => {
        vi.advanceTimersByTime(60_000);
        await Promise.resolve();
        await Promise.resolve();
      });
    }
    // NAVIGATION is the case that matters and the one a naive test misses:
    // react-router v7 does not keep one `navigate` identity across navigations,
    // so a verb closing over it directly re-creates the whole actions object on
    // every route change. `openJob`, `showNewSignals` and `showReposts` all
    // navigate; each reads the current `navigate` through a ref instead.
    await act(async () => go("/favorites"));
    await act(async () => go("/compare"));

    // One object each, for the life of the app.
    expect(seen.job.size, "job verbs changed identity").toBe(1);
    expect(seen.mission.size, "mission verbs changed identity").toBe(1);
    expect(seen.sync.size, "sync verbs changed identity").toBe(1);
  });
});
