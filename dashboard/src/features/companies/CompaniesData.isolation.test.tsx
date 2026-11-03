import { act, render, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { CompanyDirectoryStatus, CompanyDiscoveryState } from "../../api";
import { api } from "../../api";
import { statsFixture, statusFixture } from "../../test/fixtures";
import { AppProviders } from "../../context/AppProviders";
import { ToastProvider } from "../../ui/Toast";
import { CompaniesDataProvider, useCompanies, useCompaniesSync, useCompanyDirectory } from "./CompaniesData";

/* The register's render isolation.
 *
 * `useSyncStatus()` returns a value that is REPLACED every poll, every 3 seconds
 * while a scrape runs. One context object carrying the whole screen and that
 * value would hand every register row a new value on each tick, for state almost
 * none of them read. Every register row reads this context to build its
 * view's props, so the re-render reaches every row.
 *
 * These are render COUNTS, and that is deliberate: a `useMemo` on a provider
 * value that subscribes to the poll would look like a fix and still produce a
 * new identity every 3s. What holds is the poll-derived pair in its own context,
 * keyed on `syncRunning`, a BOOLEAN a tick does not usually change. A
 * structural assertion could not tell those two apart; a render count can.
 */

vi.mock("../../api", () => ({
  api: {
    companyDiscovery: vi.fn(),
    companyOpenCounts: vi.fn(),
    companyDirectoryStatus: vi.fn(),
    syncTargets: vi.fn(),
    setCompanySelection: vi.fn(),
    addCompany: vi.fn(),
    updateCompany: vi.fn(),
    sync: vi.fn(),
    cancelSync: vi.fn(),
    status: vi.fn(),
    stats: vi.fn(),
    markJobViewed: vi.fn(),
    compareSelection: vi.fn().mockResolvedValue({ job_ids: [] }),
    setCompareSelection: vi.fn((jobIds: number[]) => Promise.resolve({ job_ids: jobIds })),
  },
}));


const state: CompanyDiscoveryState = {
  sectors: [
    {
      slug: "faang",
      
      
      company_count: 1,
      ready_count: 0,
      selected_count: 1,
    },
  ],
  companies: [
    {
      slug: "google",
      display: "Google",
      careers_url: "https://example.com/careers",
      sectors: ["faang"],
      aliases: [],
      connector_state: "live",
      parked_reason: null,
      selectable: true,
      tracked: true,
      enabled: true,
      visible: true,
      builtin: true,
      curated: true, directory: false,
      wall: null,
      consented: false,
      status: "active",
    },
  ],
};

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

/* `running: true` is the case that matters: the poll is at its 3s cadence
   during a scrape, which is exactly when the register is being watched. */
let running = true;

/** No set followed, so nothing polls the directory unless a test says so. */
const noSet: CompanyDirectoryStatus = {
  size: 0, following: false, since: null, checked: 0, to_check: 0, with_roles: 0, waiting_for_power: false,
};

beforeEach(() => {
  vi.clearAllMocks();
  running = true;
  vi.mocked(api.companyDiscovery).mockResolvedValue(state);
  vi.mocked(api.companyDirectoryStatus).mockResolvedValue(noSet);
  vi.mocked(api.companyOpenCounts).mockResolvedValue({ counts: { google: 3 }, not_counted: {}, unplaced: {}, unsorted: {}, last_read: {} });
  vi.mocked(api.syncTargets).mockResolvedValue({ companies: [], freshness_max_hours: 26 });
  vi.mocked(api.stats).mockResolvedValue(statsFixture);
  // A NEW object each call, which is what a real poll returns.
  vi.mocked(api.status).mockImplementation(async () => ({
    ...statusFixture,
    running,
    manual_queued: [],
  }));
  vi.useFakeTimers({ shouldAdvanceTime: true });
});

afterEach(() => {
  vi.useRealTimers();
});

async function settle() {
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
    await Promise.resolve();
  });
}

describe("the register's context value", () => {
  /* A provider that re-renders for a reason its consumers cannot see must not
     notify them. Without a memoized value with stable verbs, ANY provider render
     would hand every register cell a new value, and there is no `React.memo`
     in this tree, so the re-render would reach every one.

     These assert the value's IDENTITY rather than a render count, because that
     is the thing the consumers subscribe to; a count is downstream of it. The
     rerender passes NEW elements on purpose: an identical `children` element
     lets React bail out of the subtree and the test would prove nothing. */
  const mount = (Consumer: () => null) =>
    render(
      <MemoryRouter>
        <AppProviders>
          <ToastProvider>
            <CompaniesDataProvider>
              <Consumer />
            </CompaniesDataProvider>
          </ToastProvider>
        </AppProviders>
      </MemoryRouter>,
    );

  it("is the same object when the provider re-renders with nothing moved", async () => {
    const seen: unknown[] = [];
    const Watcher = () => {
      seen.push(useCompanies());
      return null;
    };
    const view = mount(Watcher);
    await settle();
    await waitFor(() => expect(seen.length).toBeGreaterThan(1));

    const before = seen.length;
    await act(async () => {
      view.rerender(
        <MemoryRouter>
          <AppProviders>
            <ToastProvider>
              <CompaniesDataProvider>
                <Watcher />
              </CompaniesDataProvider>
            </ToastProvider>
          </AppProviders>
        </MemoryRouter>,
      );
    });

    expect(seen.length).toBeGreaterThan(before);
    expect(
      seen[seen.length - 1],
      "the provider handed out a new context value for a render in which none of " +
        "its inputs moved — every register cell re-renders on it.",
    ).toBe(seen[before - 1]);
  });

  it("is a new object when busy moves, so the row that is writing hears about it", async () => {
    /* The other half, and the reason a memo here is not free: `busy` is inside
       this value, so a write starting MUST produce a new identity. A memo with a
       dependency left out to flatten the count would fail here. */
    // The write is held open, or React batches the whole start-and-finish into
    // one render and no consumer is ever handed the busy state at all.
    vi.mocked(api.updateCompany).mockImplementation(() => new Promise(() => {}));
    const seen: { busy: ReadonlySet<string> }[] = [];
    let toggle: (() => void) | null = null;
    const Watcher = () => {
      const value = useCompanies();
      seen.push({ busy: value.busy });
      const company = value.resource.data?.companies[0];
      toggle = company ? () => void value.toggleVisible(company) : null;
      return null;
    };
    mount(Watcher);
    await settle();
    await waitFor(() => expect(toggle).not.toBeNull());

    const before = seen.length;
    await act(async () => { toggle?.(); });

    expect(seen.length).toBeGreaterThan(before);
    expect(
      seen[seen.length - 1].busy.has("google"),
      "a write is in flight and no consumer was handed a value that says the " +
        "row is busy — `aria-busy` can never appear.",
    ).toBe(true);
  });
});

describe("register render isolation", () => {
  it("a status poll does not re-render the surfaces that read only roster data", async () => {
    const data = probe(useCompanies);

    render(
      <MemoryRouter>
        <AppProviders>
          <ToastProvider>
            <CompaniesDataProvider>
              <data.Probe />
            </CompaniesDataProvider>
          </ToastProvider>
        </AppProviders>
      </MemoryRouter>,
    );
    await settle();

    const before = data.renders.count;
    const pollsBefore = vi.mocked(api.status).mock.calls.length;
    expect(pollsBefore).toBeGreaterThan(0);

    // Three idle ticks. `running` never changes, so nothing the register
    // actually displays has moved — only the identity of the status object.
    for (let i = 0; i < 3; i += 1) {
      await act(async () => {
        vi.advanceTimersByTime(60_000);
        await Promise.resolve();
        await Promise.resolve();
      });
    }
    await waitFor(() =>
      expect(vi.mocked(api.status).mock.calls.length).toBeGreaterThan(pollsBefore),
    );

    expect(
      data.renders.count,
      "every register consumer re-rendered on a status tick that changed nothing " +
        "they read. The provider's value is rebuilt from a poll-derived object, " +
        "so the whole screen is subscribed to a 3s clock.",
    ).toBe(before);
  });
  it("a poll that does not flip syncRunning does not re-render the sync consumers either", async () => {
    const sync = probe(useCompaniesSync);

    render(
      <MemoryRouter>
        <AppProviders>
          <ToastProvider>
            <CompaniesDataProvider>
              <sync.Probe />
            </CompaniesDataProvider>
          </ToastProvider>
        </AppProviders>
      </MemoryRouter>,
    );
    await settle();

    const before = sync.renders.count;
    const pollsBefore = vi.mocked(api.status).mock.calls.length;

    for (let i = 0; i < 3; i += 1) {
      await act(async () => {
        vi.advanceTimersByTime(60_000);
        await Promise.resolve();
        await Promise.resolve();
      });
    }
    await waitFor(() =>
      expect(vi.mocked(api.status).mock.calls.length).toBeGreaterThan(pollsBefore),
    );

    /* The rows that DO read run state are the majority of the register, so
       moving the pair into its own context buys nothing if that context still
       churns. `running` is unchanged across these ticks, so the boolean has not
       moved and neither should they. Key the memo on `status` instead of on
       `syncRunning` and this is the assertion that fails. */
    expect(
      sync.renders.count,
      "the sync context handed out a new value for a poll that changed no state " +
        "it exposes — it is keyed on the status OBJECT, not on syncRunning.",
    ).toBe(before);
  });

  it("a directory status poll reaches the set's card and no register row", async () => {
    /* The set's first pass is running, so its status is polled every 15 s.
       Each answer is a new object with more companies read and the same
       number hiring, so no roster re-read is due and nothing a row draws
       has moved. */
    let checked = 100;
    vi.mocked(api.companyDirectoryStatus).mockImplementation(async () => {
      checked += 50;
      return {
        ...noSet, size: 10_000, following: true, since: "2026-09-24T12:00:00Z",
        checked, to_check: 10_000, with_roles: 2,
      };
    });
    const data = probe(useCompanies);
    const seen: (CompanyDirectoryStatus | null)[] = [];
    const DirectoryProbe = () => {
      seen.push(useCompanyDirectory().status);
      return null;
    };

    render(
      <MemoryRouter>
        <AppProviders>
          <ToastProvider>
            <CompaniesDataProvider>
              <data.Probe />
              <DirectoryProbe />
            </CompaniesDataProvider>
          </ToastProvider>
        </AppProviders>
      </MemoryRouter>,
    );
    await settle();
    await waitFor(() => expect(seen[seen.length - 1]?.checked).toBe(150));

    const before = data.renders.count;
    await act(async () => {
      vi.advanceTimersByTime(15_000);
      await Promise.resolve();
      await Promise.resolve();
    });
    // The poll landed and the card was handed the new count: the control
    // that shows this test watched a real poll.
    await waitFor(() => expect(seen[seen.length - 1]?.checked).toBe(200));

    expect(
      data.renders.count,
      "every register consumer re-rendered on a directory poll. The status, or a " +
        "verb that closes over it, is in the register's value, so each 15 s answer " +
        "reaches every row.",
    ).toBe(before);
  });
});
