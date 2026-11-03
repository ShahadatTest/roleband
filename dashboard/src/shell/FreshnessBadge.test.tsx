import { msg } from "../test/msg";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { FreshnessBadge } from "./FreshnessBadge";
import { AppProviders } from "../context/AppProviders";
import { api, type SystemStatus } from "../api";
import { launcherFixture, statusFixture } from "../test/fixtures";
import { formatWhen } from "../format";

function status(overrides: Partial<SystemStatus>): SystemStatus {
  return {
    ...statusFixture,
    db: "ok",
    last_success_at: "2026-07-12T06:00:00Z",
    last_success_age_hours: 2,
    last_scan_at: "2026-07-12T06:00:00Z",
    last_scan_age_hours: 2,
    last_run_status: "ok",
    last_run_started_at: "2026-07-12T05:00:00Z",
    last_run_finished_at: "2026-07-12T05:10:00Z",
    last_run_new: 3,
    last_run_seen: 40,
    running: false,
    manual_sync_running: false,
    manual_queued: [],
    manual_blocked: [],
    stuck_running: 0,
    stale: false,
    freshness_max_hours: 26,
    ...overrides,
  };
}

function renderBadge() {
  vi.spyOn(api, "stats").mockResolvedValue({
    open_total: 0, new_today: 0, reposted_today: 0, closed_today: 0, saved_total: 0, review_pending: 0, notif_unread: 0, notif_high_unread: 0, by_company: {},
  });
  return render(
    <MemoryRouter>
      <AppProviders>
        <FreshnessBadge />
      </AppProviders>
    </MemoryRouter>,
  );
}

afterEach(() => vi.restoreAllMocks());

describe("FreshnessBadge", () => {
  it("keeps a service hold visible when estimates are pending", async () => {
    vi.spyOn(api, "status").mockResolvedValue(status({
      launcher: launcherFixture({ hold: { kind: "attention", reason: "supervisor_stale" }, queued: "update" }),
      reference: { ...statusFixture.reference, target_fp: "waiting", pending_jobs: 12 },
    }));
    renderBadge();
    const badge = await screen.findByRole("status", { name: msg("shell-freshness-aria", { state: msg("launcher-needs-attention") }) });
    expect(badge).toHaveClass("stale");
    expect(badge).toHaveAttribute("title", expect.stringContaining(msg("launcher-reason-supervisor")));
  });
  it("shows the last check time when idle with recent scan history", async () => {
    vi.spyOn(api, "status").mockResolvedValue(status({ last_success_age_hours: 2, stale: false }));
    renderBadge();
    const badge = await screen.findByRole("status", { name: /Last scan/ });
    await waitFor(() => expect(badge).toHaveTextContent(msg("shell-freshness-checked", { age: msg("format-age-hours", { count: 2 }) })));
    expect(badge).toHaveClass("fresh");
  });

  it("turns red when scans have stopped: the newest one is older than the window", async () => {
    vi.spyOn(api, "status").mockResolvedValue(status({
      last_success_age_hours: 40, last_scan_age_hours: 40, stale: true,
    }));
    renderBadge();
    const badge = await screen.findByRole("status", { name: /Last scan/ });
    await waitFor(() => expect(badge).toHaveTextContent(msg("shell-freshness-checked", { age: msg("format-age-days", { count: 2 }) })));
    expect(badge).toHaveClass("stale");
  });

  // A company whose page cannot be read stays behind for days while every
  // other company is scanned on time. It must not age the whole badge to
  // "8d ago" in red, nor empty it to "No data yet" over a full Board.
  it("dates the newest scan and counts the companies behind when some are", async () => {
    vi.spyOn(api, "status").mockResolvedValue(status({
      last_success_at: "2026-07-04T06:00:00Z",
      last_success_age_hours: 192,
      last_scan_age_hours: 0.25,
      stale: true,
      scheduler: {
        ...statusFixture.scheduler,
        last_complete_at: null,
        oldest_scan_at: "2026-07-04T06:00:00Z",
        overdue: [
          { company: "openai", reason: "authoritative_stale", last_reconcile_at: "2026-07-04T06:00:00Z" },
          { company: "anthropic", reason: "never_reconciled" },
          { company: "fortinet", reason: "authoritative_stale", last_reconcile_at: "2026-07-01T06:00:00Z" },
        ],
        unread: [
          { company: "openai", reason: "read_stale", last_read_at: "2026-07-04T06:00:00Z" },
          { company: "anthropic", reason: "never_read", last_read_at: null },
        ],
      },
    }));
    renderBadge();
    const badge = await screen.findByRole("status", { name: /Last scan/ });
    await waitFor(() => expect(badge).toHaveTextContent(msg("shell-freshness-behind", {
      age: msg("format-age-minutes", { count: 15 }), count: 2,
    })));
    expect(badge).toHaveClass("behind");
    expect(badge).not.toHaveClass("stale");
    expect(badge).not.toHaveTextContent(msg("format-age-days", { count: 8 }));
    expect(badge).not.toHaveTextContent(/not scanned|no data/i);
    expect(badge.getAttribute("title")).toContain(msg("shell-freshness-oldest", { when: formatWhen("2026-07-04T06:00:00Z") }));
    // Fortinet is overdue for closure but its board was read last night: the
    // tooltip names what makes the data stale, nothing else.
    expect(badge.getAttribute("title")?.endsWith(msg("shell-freshness-waiting", { companies: "OpenAI and Anthropic" }))).toBe(true);
    expect(badge.getAttribute("title")).not.toMatch(/Fortinet/);
  });

  // A board that lists one posting fewer than it declares makes every nightly
  // read `lossy`, and none may close. Read last night, it must not show
  // "Stale · 9d ago" over a full Board.
  it("stays fresh over a company read last night that cannot close", async () => {
    vi.spyOn(api, "status").mockResolvedValue(status({
      last_success_at: "2026-07-12T00:00:00Z",
      last_success_age_hours: 20,
      last_scan_age_hours: 20,
      stale: false,
      scheduler: {
        ...statusFixture.scheduler,
        last_complete_at: null,
        oldest_scan_at: "2026-07-12T00:00:00Z",
        overdue: [
          { company: "fortinet", reason: "authoritative_stale", last_reconcile_at: "2026-07-03T06:00:00Z" },
        ],
        unread: [],
      },
    }));
    renderBadge();
    const badge = await screen.findByRole("status", { name: /Last scan/ });
    await waitFor(() => expect(badge).toHaveTextContent(msg("shell-freshness-checked", { age: msg("format-age-hours", { count: 20 }) })));
    expect(badge).toHaveClass("fresh");
    expect(badge.getAttribute("title")).not.toMatch(/Fortinet|Waiting/);
    expect(badge.getAttribute("title")).toBe(msg("shell-freshness-oldest", { when: formatWhen("2026-07-12T00:00:00Z") }));
  });

  it("says nothing was scanned only when no company was ever read", async () => {
    vi.spyOn(api, "status").mockResolvedValue(status({
      last_success_at: null, last_success_age_hours: null, stale: true,
    }));
    renderBadge();
    const badge = await screen.findByRole("status", { name: /Last scan/ });
    await waitFor(() => expect(badge).toHaveTextContent(msg("shell-freshness-never")));
    expect(badge).toHaveClass("unknown");
  });

  it.each([null, 0, 50])("shows only scanning during any active scan, even with age %s", async (age) => {
    vi.spyOn(api, "status").mockResolvedValue(status({
      running: true,
      last_success_at: age === null ? null : statusFixture.last_success_at,
      last_success_age_hours: age,
      stale: true,
      last_run_seen: 36815,
    }));
    renderBadge();
    const badge = await screen.findByRole("status", { name: /Last scan/ });
    await waitFor(() => expect(badge.querySelector("strong")).toHaveTextContent(msg("shell-scan-scanning")));
    expect(badge.querySelector("strong")?.textContent).toBe(msg("shell-scan-scanning"));
    expect(badge).not.toHaveClass("stale");
    expect(badge.getAttribute("title")).toContain(age === null
      ? msg("shell-freshness-never")
      : msg("shell-freshness-oldest", { when: formatWhen(statusFixture.last_success_at!) }));
  });

  it("does not claim a queued scan is running", async () => {
    vi.spyOn(api, "status").mockResolvedValue(status({
      running: false,
      last_success_at: null,
      last_success_age_hours: null,
      manual_queued: ["openai"],
      manual_blocked: [{ provider: "ashby", reason: "paused", until: null, companies: 1 }],
      stale: true,
    }));
    renderBadge();
    const badge = await screen.findByRole("status", { name: /Last scan/ });
    await waitFor(() => expect(badge).toHaveTextContent(msg("shell-freshness-never")));
    expect(badge).not.toHaveTextContent(msg("shell-scan-scanning"));
  });

  it("shows minutes after a scan without calling recently checked data stale", async () => {
    vi.spyOn(api, "status").mockResolvedValue(status({
      last_success_age_hours: 0.25, last_scan_age_hours: 0.25, stale: true,
    }));
    renderBadge();
    const badge = await screen.findByRole("status", { name: /Last scan/ });
    await waitFor(() => expect(badge).toHaveTextContent(msg("shell-freshness-checked", {
      age: msg("format-age-minutes", { count: 15 }),
    })));
    expect(badge).not.toHaveClass("stale");
  });

  it("claims no scan while the first status is still loading", async () => {
    vi.spyOn(api, "status").mockReturnValue(new Promise(() => {}));
    renderBadge();
    const badge = await screen.findByRole("status", { name: msg("shell-freshness-loading-aria") });
    expect(badge).not.toHaveTextContent(/Scanning/);
    // Nor that nothing was ever scanned: that is not known yet either.
    expect(badge).not.toHaveAttribute("title");
    expect(badge).toHaveClass("unknown");
  });

  it("degrades to an offline label when the status endpoint fails", async () => {
    vi.spyOn(api, "status").mockRejectedValue(new Error("network"));
    renderBadge();
    const badge = await screen.findByRole("status", { name: /Last scan/ });
    await waitFor(() => expect(badge).toHaveTextContent(msg("shell-freshness-offline")));
    expect(badge).toHaveClass("unknown");
  });
});
