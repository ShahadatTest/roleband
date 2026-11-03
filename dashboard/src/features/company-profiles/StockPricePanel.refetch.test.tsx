import { act, render } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { api, type CompanyPrices, type SystemStatus } from "../../api";
import { statsFixture, statusFixture } from "../../test/fixtures";
import { MissionStateProvider } from "../../context/MissionState";
import { SyncStateProvider } from "../../context/SyncState";
import { StockPricePanel } from "./StockPricePanel";

/* An open profile shows what the prices job just stored: the end of its run
 * (the shared status poll's prices job, running then idle) re-reads the chart,
 * and nothing else does. */

vi.mock("../../api", async (original) => ({
  ...(await original<typeof import("../../api")>()),
  api: { stats: vi.fn(), status: vi.fn(), companyPrices: vi.fn() },
}));
vi.mock("../../ui/EChart", () => ({ EChart: () => null }));

const prices: CompanyPrices = {
  slug: "acme", currency: "USD", range: "3m", latest: null, bars: [],
  attribution: null, feed_configured: true,
};

const job = (state: "running" | "idle") => ({
  key: "prices", job: "prices", state, reason: null, since: "2026-07-13T05:00:00Z", next_at: null,
  run_id: state === "running" ? 3 : null, progress: null, waiting: null, queued: 0,
});

beforeEach(() => {
  vi.useFakeTimers();
  vi.mocked(api.stats).mockResolvedValue(statsFixture);
  vi.mocked(api.companyPrices).mockResolvedValue(prices);
});
afterEach(() => vi.useRealTimers());

async function flush() {
  await act(async () => {
    for (let i = 0; i < 10; i += 1) await Promise.resolve();
  });
}

it("re-reads the chart when a prices run ends, and not on every poll", async () => {
  // The mount reads, then the live cadence polls every 3 s: running at the
  // mount and on the first tick, idle on the second.
  const answers: SystemStatus[] = [
    { ...statusFixture, jobs: [job("running")] },
    { ...statusFixture, jobs: [job("running")] },
    { ...statusFixture, jobs: [job("idle")] },
  ];
  vi.mocked(api.status).mockImplementation(async () => answers.shift() ?? { ...statusFixture, jobs: [job("idle")] });
  render(
    <MemoryRouter>
      <MissionStateProvider>
        <SyncStateProvider>
          <StockPricePanel slug="acme" ticker="ACME" />
        </SyncStateProvider>
      </MissionStateProvider>
    </MemoryRouter>,
  );
  await flush();
  const reads = vi.mocked(api.companyPrices).mock.calls.length;
  expect(reads).toBeGreaterThanOrEqual(1);
  await act(async () => vi.advanceTimersByTime(3_000)); // still running: no re-read
  await flush();
  expect(vi.mocked(api.companyPrices).mock.calls.length).toBe(reads);
  await act(async () => vi.advanceTimersByTime(3_000)); // the run ended
  await flush();
  expect(vi.mocked(api.companyPrices).mock.calls.length).toBe(reads + 1);
});
