import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import type { SyncSchedule } from "../../api";
import { activate } from "../../copy/activate";
import { list } from "../../copy/format";
import { msg } from "../../test/msg";
import { schedulePlanFixture } from "../../test/fixtures";
import { api } from "../../api";
import { ApiError } from "../../api/transport";
import { ScheduleSection } from "./ScheduleSection";
import { readyByForStart, startForReadyBy } from "./usePlanDrag";

vi.mock("../../api", () => ({
  api: { schedule: vi.fn(), updateSchedule: vi.fn(), updateSchedulePlan: vi.fn() },
}));

const fixture: SyncSchedule = {
  generated_at: "2026-07-28T14:30:00Z",
  enabled: true,
  tick_seconds: 600,
  max_parallel_providers: 2,
  authoritative_stale_hours: 30,
  // The per-company timers: the dial these tests were written for.
  plan: schedulePlanFixture({ enabled: false }),
  providers: [
    {
      provider: "greenhouse",
      state: "ready",
      cooldown_until: null,
      last_started_at: null,
      last_finished_at: null,
      last_outcome: "ok",
      binding_count: 1,
    },
    {
      provider: "meta",
      state: "policy_denied",
      cooldown_until: null,
      last_started_at: null,
      last_finished_at: null,
      last_outcome: null,
      binding_count: 1,
    },
  ],
  bindings: [
    {
      binding_id: 1,
      company: "openai",
      provider: "greenhouse",
      closure_capability: "authoritative",
      scheduled: true,
      discovery_enabled: true,
      discovery_cadence_seconds: 21_600,
      reconcile_cadence_seconds: 86_400,
      last_discovery_at: null,
      last_reconcile_at: null,
      next_discovery_at: "2026-07-28T16:00:00Z",
      next_reconcile_at: "2026-07-28T20:00:00Z",
      discovery_anchor_minute: null,
      reconcile_anchor_minute: null,
      schedule_timezone: null,
      eligible_discovery_at: "2026-07-28T16:00:00Z",
      eligible_reconcile_at: "2026-07-28T20:00:00Z",
      manual_requested_at: null,
      last_outcome: "ok",
      last_new_count: 1,
      consecutive_empty_discoveries: 0,
      provider_state: "ready",
      cooldown_until: null,
      status: "scheduled",
      waits_for_user: null,
    },
    {
      binding_id: 2,
      company: "meta",
      provider: "meta",
      closure_capability: "authoritative",
      scheduled: true,
      discovery_enabled: false,
      discovery_cadence_seconds: 21_600,
      reconcile_cadence_seconds: 86_400,
      last_discovery_at: null,
      last_reconcile_at: null,
      next_discovery_at: "2026-07-28T17:00:00Z",
      next_reconcile_at: "2026-07-28T22:00:00Z",
      discovery_anchor_minute: null,
      reconcile_anchor_minute: null,
      schedule_timezone: null,
      eligible_discovery_at: null,
      eligible_reconcile_at: null,
      manual_requested_at: null,
      last_outcome: null,
      last_new_count: 0,
      consecutive_empty_discoveries: 0,
      provider_state: "policy_denied",
      cooldown_until: null,
      status: "policy_denied",
      waits_for_user: null,
    },
  ],
};

// Three connectors whose reconciliations land on the same tick, so the dial
// draws them as one cluster. scheduleClusters orders members by company, so
// Anthropic heads the list the inspector shows — and is the lead a drag peels
// off. The two must agree: the lead is defined as the first row the user sees.
const stackedFixture = (): SyncSchedule => ({
  ...fixture,
  bindings: [
    fixture.bindings[0],
    {
      ...fixture.bindings[1],
      status: "scheduled" as const,
      provider_state: "ready",
      next_reconcile_at: "2026-07-28T20:00:00Z",
      eligible_reconcile_at: "2026-07-28T20:00:00Z",
    },
    {
      ...fixture.bindings[0],
      binding_id: 3,
      company: "anthropic",
      discovery_enabled: false,
      next_discovery_at: null,
      eligible_discovery_at: null,
    },
  ],
});

describe("ScheduleSection", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(api.schedule).mockResolvedValue(fixture);
    vi.mocked(api.updateSchedule).mockResolvedValue(fixture);
  });

  it("names the connector instead of drawing a cycle band around a single mark", async () => {
    render(<ScheduleSection />);

    expect(await screen.findByRole("img", { name: /scan clock/i }))
      .toBeInTheDocument();
    expect(screen.getByText(/1 excluded or unscheduled compan/i)).toBeInTheDocument();

    // One binding dispatching alone is its own mark: same instant, same
    // connector, one tick long. A band there would only restate the mark, at
    // a length it would have to invent.
    expect(document.querySelector('[data-testid="reconciliation-window"]')).toBeNull();
    const legend = screen.getByLabelText("Schedule clock legend");
    expect(within(legend).queryByText("Full scan window")).not.toBeInTheDocument();

    // ...and the agenda row that stands in for it names the company rather
    // than hiding it behind the abstraction.
    const agenda = screen.getByRole("complementary", { name: /upcoming scans/i });
    expect(within(agenda).queryByText("Full scan window")).not.toBeInTheDocument();
    const cycleRow = within(agenda)
      .getByText(/Full scan · projected through/i)
      .closest(".schedule-upcoming-row");
    expect(cycleRow).toHaveTextContent("OpenAI");
  });

  it("draws the cycle band only when the burst spans more than its own marks", async () => {
    // Three reconciliations on one tick: the marks all sit on one instant, so
    // only the band can show that the work serializes across a window.
    vi.mocked(api.schedule).mockResolvedValue(stackedFixture());
    render(<ScheduleSection />);

    await screen.findByRole("img", { name: /scan clock/i });
    const band = document.querySelector('[data-testid="reconciliation-window"] .dial-window');
    expect(band).not.toBeNull();
    // Two concentric arcs — a segment of the orbit, not a stroked chord — and
    // each end closed by a half-round rather than a flat radial cut. The cap
    // radius is the band's own half-thickness (WINDOW_BAND = 2.75), so the
    // shape ends the way a round-capped stroke would without getting thicker;
    // a straight `L` between the two arcs is the flat-cut regression.
    const d = band?.getAttribute("d") ?? "";
    expect(d).toMatch(
      /^M [\d.]+ [\d.]+ A 218\.75 218\.75 0 0 1 [\d.]+ [\d.]+ A 2\.75 2\.75 0 0 1 [\d.]+ [\d.]+ A 213\.25 213\.25 0 0 0 [\d.]+ [\d.]+ A 2\.75 2\.75 0 0 1 [\d.]+ [\d.]+ Z$/,
    );
    expect(d).not.toContain("L");

    // The halo under it is capped on the same rule at its own thickness, so
    // the glow tapers with the track instead of ending in a blunt edge of its
    // own, and it is blurred without the crisp source merged back on top.
    const halo = document.querySelector('[data-testid="reconciliation-window"] .dial-window-glow');
    expect(halo?.getAttribute("d")).toContain("A 8.00 8.00 0 0 1");
    expect(halo?.getAttribute("filter")).toBe("url(#schedule-cycle-halo)");
    const haloFilter = document.querySelector("#schedule-cycle-halo");
    expect(haloFilter?.querySelector("feMerge")).toBeNull();

    const agenda = screen.getByRole("complementary", { name: /upcoming scans/i });
    expect(within(agenda).getByText(/Full scan window/)).toBeInTheDocument();
    expect(within(agenda).getByText(/3 scans · projected through/i)).toBeInTheDocument();
    expect(within(screen.getByLabelText("Schedule clock legend"))
      .getByText("Full scan window")).toBeInTheDocument();
  });

  it("calls a Workday company what it is, not Scheduled, under the timers too", async () => {
    vi.mocked(api.schedule).mockResolvedValue({
      ...fixture,
      bindings: [{ ...fixture.bindings[0], waits_for_user: "user_directed" }, fixture.bindings[1]],
    });
    render(<ScheduleSection />);
    fireEvent.click(await screen.findByRole("button", { name: "All persisted deadlines" }));
    const sheet = await screen.findByRole("dialog", { name: "All persisted deadlines" });
    const openai = within(sheet).getByText("OpenAI").closest("tr") as HTMLElement;
    expect(openai).toHaveTextContent("Only when you scan");
    expect(openai).not.toHaveTextContent("Scheduled");
  });

  it("surfaces policy denial as an exception and keeps the ledger one click away", async () => {
    render(<ScheduleSection />);

    const strip = await screen.findByText(/needs attention/i);
    expect(strip.parentElement).toHaveTextContent(
      /Meta: its site doesn't allow scheduled scans/,
    );

    fireEvent.click(screen.getByRole("button", { name: /all persisted deadlines/i }));
    const sheet = await screen.findByRole("dialog", { name: /all persisted deadlines/i });
    expect(sheet).toHaveTextContent("Policy denied");
    const metaRow = within(sheet).getByText("Meta").closest("tr");
    expect(metaRow).toHaveTextContent("Not scheduled");
  });

  /* A followed company with no schedule row yet is new: the scheduler's next
     run gives it one. Listing it under "needs attention" would make every
     fresh install open on a wall of problems. */
  const newCompany = (company: string, binding_id: number): SyncSchedule["bindings"][number] => ({
    ...fixture.bindings[0], binding_id, company, scheduled: false,
    next_discovery_at: null, next_reconcile_at: null, eligible_discovery_at: null, eligible_reconcile_at: null,
    status: "unscheduled",
  });

  it("counts new companies calmly and keeps the attention note for real problems", async () => {
    vi.mocked(api.schedule).mockResolvedValue({
      ...fixture,
      bindings: [...fixture.bindings, newCompany("stripe", 3), newCompany("figma", 4)],
    });
    render(<ScheduleSection />);

    const strip = await screen.findByText(msg("settings-schedule-section-need-attention", { count: 1 }));
    expect(strip.parentElement).toHaveTextContent(/Meta: its site doesn't allow scheduled scans/);
    expect(strip.parentElement).not.toHaveTextContent(/Stripe|Figma/);
    expect(screen.getByText(msg("settings-schedule-section-setting-scan-times", { count: 2 }))).toHaveAttribute("role", "status");
  });

  it("a fresh install whose companies are all new raises no attention, with the plan on or off", async () => {
    const bindings = [newCompany("accenture", 1), newCompany("adyen", 2), newCompany("airbnb", 3)];
    for (const schedule of [{ ...fixture, bindings }, { ...planned({ pinned: 0 }), bindings }]) {
      vi.mocked(api.schedule).mockResolvedValue(schedule);
      const { unmount } = render(<ScheduleSection />);
      expect(await screen.findByText(msg("settings-schedule-section-setting-scan-times", { count: 3 }))).toBeInTheDocument();
      expect(screen.queryByText(/needs? attention/i)).toBeNull();
      expect(document.querySelector(".schedule-exceptions")).toBeNull();
      unmount();
    }
  });

  it("persists an exact reconciliation time from the marker inspector", async () => {
    render(<ScheduleSection />);
    const marker = await screen.findByRole("button", {
      name: /move openai full scan/i,
    });

    fireEvent.click(marker);
    const input = await screen.findByLabelText(/OpenAI full scan time/i);
    // Editing is not committing. A time input reaches a complete value on every
    // segment edit, so a write on `change` was a write per keystroke; the field
    // commits when the edit is finished (blur, or Enter).
    fireEvent.change(input, { target: { value: "20:30" } });
    await act(async () => {});
    expect(api.updateSchedule).not.toHaveBeenCalled();
    fireEvent.blur(input);

    await waitFor(() => {
      expect(api.updateSchedule).toHaveBeenCalledWith(1, {
        mode: "reconcile",
        local_minute: 20 * 60 + 30,
        timezone: expect.any(String),
      });
    });
  });

  it("releases the mark's selection when the inspector closes", async () => {
    // An open inspector paints a 4px ring and a glow, keyed on the mark's own
    // `aria-expanded`: the dial's statement that this mark is the
    // one in hand. Once the inspector closes, a lit mark would claim a
    // selection that does not exist.
    render(<ScheduleSection />);
    const marker = await screen.findByRole("button", {
      name: /move openai full scan/i,
    });

    fireEvent.click(marker);
    await screen.findByLabelText(/OpenAI full scan time/i);
    expect(marker).toHaveAttribute("aria-expanded", "true");

    fireEvent.keyDown(document, { key: "Escape" });
    await waitFor(() =>
      expect(screen.queryByLabelText(/OpenAI full scan time/i)).toBeNull());
    expect(marker).toHaveAttribute("aria-expanded", "false");
  });

  it("spends the ledger's ink on the deadline, not on restating the column", async () => {
    // A binding whose reconciliation cannot close roles — the one case the
    // capability is worth naming.
    const withException: SyncSchedule = {
      ...fixture,
      bindings: fixture.bindings.map((binding) => binding.binding_id === 1
        ? { ...binding, closure_capability: "non_authoritative" as const }
        : binding),
    };
    vi.mocked(api.schedule).mockResolvedValue(withException);
    render(<ScheduleSection />);

    fireEvent.click(await screen.findByRole("button", { name: /all persisted deadlines/i }));
    const sheet = await screen.findByRole("dialog", { name: /all persisted deadlines/i });

    // No phrase the column header already implies.
    expect(sheet).not.toHaveTextContent(/cadence/i);
    expect(sheet).not.toHaveTextContent(/probe disabled/i);
    expect(sheet).not.toHaveTextContent(/closure-capable/i);

    // Cadence is a single token beside the time it governs.
    const openaiRow = within(sheet).getByText("OpenAI").closest("tr") as HTMLElement;
    expect(within(openaiRow).getByLabelText("every 6h")).toHaveTextContent("6h");
    expect(within(openaiRow).getByLabelText("every 24h")).toHaveTextContent("24h");
    // The exception is named; it is the only row that carries a subline.
    expect(openaiRow).toHaveTextContent("can't close roles");

    // A binding with no deadline advertises no cadence for it either.
    const metaRow = within(sheet).getByText("Meta").closest("tr") as HTMLElement;
    expect(metaRow).toHaveTextContent("Not scheduled");
    expect(within(metaRow).queryByLabelText(/^every /)).not.toBeInTheDocument();
    expect(metaRow).not.toHaveTextContent("can't close roles");
  });

  it("stacks each deadline as clock-over-day and drops a provider that restates the company",
    async () => {
      render(<ScheduleSection />);

      fireEvent.click(await screen.findByRole("button", { name: /all persisted deadlines/i }));
      const sheet = await screen.findByRole("dialog", { name: /all persisted deadlines/i });

      const openaiRow = within(sheet).getByText("OpenAI").closest("tr") as HTMLElement;
      const [openaiConnector, discovery, reconcile] = Array.from(openaiRow.querySelectorAll("td"));

      // Clock time leads its own line; the day sits on a second one.
      for (const cell of [discovery, reconcile]) {
        expect(cell.querySelector("b")).toHaveTextContent(/^\d{2}:\d{2}/);
        expect(cell.querySelector(".schedule-ledger-when small"))
          .toHaveTextContent(/^\w{3}, \w{3} \d{1,2}$/);
      }
      // ...and never as one run-on string.
      expect(discovery.textContent).not.toMatch(/\d{2}:\d{2}\s*\w{3},/);

      // A board distinct from the company is a real second fact, so it keeps its line.
      expect(openaiConnector.querySelector("small")).toHaveTextContent("greenhouse");

      // A provider named after the company says nothing new when repeated.
      const metaConnector = (within(sheet).getByText("Meta").closest("tr") as HTMLElement)
        .querySelector("td") as HTMLElement;
      expect(metaConnector).toHaveTextContent("Meta");
      expect(metaConnector.querySelector("small")).toBeNull();
    });

  it("labels a mark as time then company, with no next-day marker", async () => {
    render(<ScheduleSection />);
    const dial = await screen.findByRole("img", { name: /scan clock/i });

    const label = [...dial.querySelectorAll("text.dial-label")]
      .find((node) => node.textContent?.includes("OpenAI"));
    expect(label).toBeDefined();

    // Two parts, so the time can carry the weight and the company recede.
    const [time, who] = [...label!.querySelectorAll("tspan")];
    expect(time).toHaveTextContent(/^\d{2}:\d{2}$/);
    expect(who).toHaveTextContent("OpenAI");

    // "+1" would show on nearly every label: it distinguishes nothing and reads
    // as a timezone offset beside a clock time. The header carries zone and date.
    for (const node of dial.querySelectorAll("text.dial-label")) {
      expect(node.textContent).not.toMatch(/\+1/);
    }
    expect(screen.getByText(/Europe\/|UTC/)).toBeInTheDocument();
  });

  it("keeps the pass definitions in help rather than on the everyday dial", async () => {
    render(<ScheduleSection />);
    await screen.findByRole("img", { name: /scan clock/i });

    expect(screen.queryByText(/never closes one/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/close a role that has disappeared/i)).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /how scanning works/i }));

    const help = await screen.findByRole("dialog", { name: /how scanning works/i });
    expect(help).toHaveTextContent(/add or update a role, but never closes one/i);
    expect(help).toHaveTextContent(/Only a full scan can close a role that has disappeared/);
    expect(help).toHaveTextContent(/snap to 10 minutes/i);
  });

  it("drops provider plumbing from the marker inspector", async () => {
    render(<ScheduleSection />);
    const marker = await screen.findByRole("button", {
      name: /move openai full scan/i,
    });

    fireEvent.click(marker);
    const inspector = await screen.findByRole("dialog", { name: /scan schedule inspector/i });

    expect(inspector).toHaveTextContent("OpenAI");
    expect(inspector).not.toHaveTextContent(/greenhouse/i);
    expect(within(inspector).queryByText("Provider")).not.toBeInTheDocument();
  });

  it("heads a mark's inspector with its own pass and lists the company's other pass after it", async () => {
    const pass = (mode: "reconcile" | "discovery") => msg("settings-chronograph-inspector-pass", { mode });
    const terms = async (mode: "reconcile" | "discovery") => {
      const scan = msg("settings-schedule-mode-name", { schedule: "timers", mode });
      const view = render(<ScheduleSection />);
      fireEvent.click(await screen.findByRole("button", { name: new RegExp(`^Move OpenAI ${scan},`) }));
      const inspector = await screen.findByRole("dialog", { name: msg("settings-chronograph-inspector-scan-schedule-inspector") });
      const rows = within(inspector).getAllByRole("term").map((term) => [term.textContent, term.nextElementSibling?.textContent]);
      view.unmount();
      return rows;
    };

    const reconcile = await terms("reconcile");
    expect(reconcile[0]).toEqual([pass("reconcile"), msg("settings-chronograph-inspector-every", { unit: "day", count: 1 })]);
    expect(reconcile[reconcile.length - 1][0]).toBe(pass("discovery"));
    const discovery = await terms("discovery");
    expect(discovery[0]).toEqual([pass("discovery"), msg("settings-chronograph-inspector-every", { unit: "hour", count: 6 })]);
    expect(discovery[discovery.length - 1][0]).toBe(pass("reconcile"));
  });

  it("sums up the timers under the dial, adding what needs attention and what has no discovery pass", async () => {
    render(<ScheduleSection />);
    expect(await screen.findByText(msg("settings-schedule-section-timers-roster-excepted-reconcile-only", {
      companies: 2, scheduled: 1, excepted: 1, reconcileOnly: 1,
    }))).toBeInTheDocument();
  });

  it("sums up the timers without the parts that have nothing to count", async () => {
    vi.mocked(api.schedule).mockResolvedValue({ ...fixture, bindings: [fixture.bindings[0]] });
    render(<ScheduleSection />);
    expect(await screen.findByText(msg("settings-schedule-section-timers-roster", { companies: 1, scheduled: 1 })))
      .toBeInTheDocument();
  });

  it("opens a stack into one combined view of every company sharing the tick", async () => {
    vi.mocked(api.schedule).mockResolvedValue(stackedFixture());
    render(<ScheduleSection />);

    const stack = await screen.findByRole("button", { name: /3 full scans at .*open to see all/i });
    fireEvent.click(stack);

    // The whole stack is named and listed — not scattered back onto the dial.
    const inspector = await screen.findByRole("dialog", { name: /scan schedule inspector/i });
    expect(inspector).toHaveTextContent(/3 share \d{2}:\d{2}/);
    for (const company of ["OpenAI", "Meta", "Anthropic"]) {
      expect(within(inspector).getByText(company)).toBeInTheDocument();
    }
    // ...and every one of them is individually settable from right here.
    for (const company of ["OpenAI", "Meta", "Anthropic"]) {
      expect(within(inspector).getByLabelText(new RegExp(`${company} full scan time`, "i")))
        .toBeEnabled();
    }
    // The dial keeps the stack whole rather than fanning it into loose marks.
    expect(screen.queryByRole("button", { name: /^move openai full scan/i }))
      .not.toBeInTheDocument();
  });

  it("names the one company a drag will peel off, and it is the first row listed", async () => {
    vi.mocked(api.schedule).mockResolvedValue(stackedFixture());
    render(<ScheduleSection />);

    const stack = await screen.findByRole("button", { name: /3 full scans at/i });
    expect(stack).toHaveAccessibleName(/drag to move Anthropic out/i);

    fireEvent.click(stack);
    const inspector = await screen.findByRole("dialog", { name: /scan schedule inspector/i });
    expect(inspector).toHaveTextContent(/drag the mark to move Anthropic out first/i);
    expect(screen.getByRole("status")).toHaveTextContent(/drag the mark to move Anthropic out/i);

    // The company the handle names is the one heading the list, not an
    // internal ordering the user cannot see.
    const listed = within(inspector).getAllByRole("article")
      .map((row) => row.querySelector("header strong")?.textContent);
    expect(listed).toEqual(["Anthropic", "Meta", "OpenAI"]);
  });

  it("splits the stack mid-drag so the dial never implies all of it is moving", async () => {
    vi.mocked(api.schedule).mockResolvedValue(stackedFixture());
    render(<ScheduleSection />);

    const stack = await screen.findByRole("button", { name: /3 full scans at/i });
    stack.setPointerCapture = () => {};
    stack.releasePointerCapture = () => {};
    fireEvent.pointerDown(stack, { pointerId: 1, clientX: 100, clientY: 100 });
    fireEvent.pointerMove(stack, { pointerId: 1, clientX: 260, clientY: 40 });

    // The grabbed handle is now Anthropic alone (on the next animation frame:
    // a drag renders once per frame)...
    await waitFor(() =>
      expect(stack).toHaveAccessibleName(/move anthropic full scan/i));
    // ...and the two it left behind are drawn separately, and cannot be grabbed
    // while the first is still in flight.
    expect(screen.getByRole("button", { name: /2 full scans still at \d{2}:\d{2}/i }))
      .toBeDisabled();
    expect(screen.getByRole("status")).toHaveTextContent(/Anthropic · full scan/i);
  });

  it("skips a locked member when choosing what a drag on the stack moves", async () => {
    // Anthropic still heads the stack, but a queued manual sync locks its
    // reconciliation — so a drag must peel off the next one instead of
    // grabbing a mark that cannot move.
    const stacked = stackedFixture();
    vi.mocked(api.schedule).mockResolvedValue({
      ...stacked,
      bindings: stacked.bindings.map((binding) => binding.binding_id === 3
        ? { ...binding, manual_requested_at: "2026-07-28T14:00:00Z" }
        : binding),
    });
    render(<ScheduleSection />);

    const stack = await screen.findByRole("button", { name: /3 full scans at/i });
    expect(stack).not.toHaveAccessibleName(/drag to move Anthropic out/i);
    expect(stack).toHaveAccessibleName(/drag to move Meta out/i);
  });

  it("locks a policy-denied marker instead of offering an editable time", async () => {
    const cooldownFixture: SyncSchedule = {
      ...fixture,
      bindings: fixture.bindings.map((binding) => binding.binding_id === 2
        ? { ...binding, status: "scheduled" as const, provider_state: "ready", manual_requested_at: "2026-07-28T14:00:00Z" }
        : binding),
    };
    vi.mocked(api.schedule).mockResolvedValue(cooldownFixture);
    render(<ScheduleSection />);

    const marker = await screen.findByRole("button", {
      name: /move meta full scan/i,
    });
    fireEvent.click(marker);

    const input = await screen.findByLabelText(/Meta full scan time/i);
    expect(input).toBeDisabled();
    expect(screen.getByText(/cancel the queued manual scan/i)).toBeInTheDocument();
  });
});

/* The schedule plan: the same clock, drawing the plan's runs instead
   of a thousand company marks. OpenAI keeps a time the user set; Anthropic does
   not, so under the plan it has no mark of its own. */
const planned = (overrides: Partial<SyncSchedule["plan"]> = {}): SyncSchedule => ({
  ...fixture,
  bindings: [
    { ...fixture.bindings[0], reconcile_anchor_minute: 20 * 60, schedule_timezone: "UTC" },
    {
      ...fixture.bindings[0],
      binding_id: 3,
      company: "anthropic",
      next_reconcile_at: "2026-07-28T21:00:00Z",
      eligible_reconcile_at: "2026-07-28T21:00:00Z",
    },
    fixture.bindings[1],
  ],
  plan: schedulePlanFixture({
    pinned: 1,
    upcoming: [
      { at: "2026-07-28T15:00:00Z", kind: "quick", seconds: 600, estimated: false, on_wake: false, running: false, ready_by: false },
      { at: "2026-07-29T09:00:00Z", kind: "full", seconds: 2460, estimated: false, on_wake: true, running: false, ready_by: false },
    ],
    ...overrides,
  }),
});


describe("ScheduleSection under the schedule plan", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(api.schedule).mockResolvedValue(planned());
    vi.mocked(api.updateSchedule).mockResolvedValue(planned());
  });

  it("draws the plan's runs on their orbits and keeps marks only for pinned companies", async () => {
    render(<ScheduleSection />);
    await screen.findByRole("img", { name: /scan clock/i });

    const runs = [...document.querySelectorAll('[data-testid="plan-run"]')];
    expect(runs.map((run) => run.getAttribute("data-kind"))).toEqual(["quick", "full"]);
    expect(runs[1]).toHaveClass("wake");

    // A company's own time is named in the plan's words, the same words the timers use.
    expect(screen.getByRole("button", { name: /^Move OpenAI full scan, currently/i }))
      .toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /authoritative reconciliation/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Anthropic/i })).not.toBeInTheDocument();
    // The timers' burst is not drawn: the planned full scan is the cycle.
    expect(document.querySelector('[data-testid="reconciliation-window"]')).toBeNull();
    // The screen reader's account of the dial tells the plan, not the timers.
    expect(screen.getByText(
      "24-hour scan clock: 2 planned scans, the next a quick scan of 944 companies, and 1 company at a time you set.",
    )).toBeInTheDocument();
  });

  it("says what runs next, over how many companies, and how long each run takes", async () => {
    render(<ScheduleSection />);
    await screen.findByRole("img", { name: /scan clock/i });

    expect(screen.getByText("Next scan")).toBeInTheDocument();
    expect(screen.getByText("Quick scan · 944 companies")).toBeInTheDocument();

    const next = screen.getByRole("list", { name: "Next scans" });
    const wake = within(next).getByText("Full scan · when you turn it on").closest(".schedule-upcoming-row");
    expect(wake).toHaveTextContent("1,112 companies · 41 min");
    const quick = within(next).getByText("Quick scan").closest(".schedule-upcoming-row");
    expect(quick).toHaveTextContent("944 companies · 10 min");
    // A pinned company keeps its own row, folded under one line until asked for.
    expect(screen.queryByText("Full scan at a time you set")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "1 company keeps a time you set" }));
    const pinned = screen.getByRole("list", { name: "Times you set" });
    expect(within(pinned).getByText("Full scan at a time you set")).toBeInTheDocument();
  });

  it("puts the plan's settings beside the dial, as the wireframe drew them", async () => {
    render(<ScheduleSection />);
    await screen.findByRole("img", { name: /scan clock/i });

    const panel = screen.getByRole("complementary", { name: "When scans run" });
    const settings = within(panel).getByLabelText("Plan settings");
    // Every row is a control; the learned hours and the missed-scan rule are a
    // note under them, not rows of their own.
    expect(within(settings).getByText("First scan of the day")).toBeInTheDocument();
    expect(within(settings).getByLabelText("Full scan done by")).toBeInTheDocument();
    expect(within(settings).getByText(/1,112 companies · 41 min/)).toBeInTheDocument();
    expect(within(settings).getByRole("group", { name: "Quick scan every" })).toBeInTheDocument();
    expect(within(settings).queryByText("Your computer is usually on")).not.toBeInTheDocument();
    expect(within(settings).queryByText("If it was off")).not.toBeInTheDocument();
    expect(within(panel).getByText(/one full scan runs when you are back; missed scans are not repeated/))
      .toBeInTheDocument();
    // The timers' column and their cadence strip are not shown under the plan.
    expect(screen.queryByRole("complementary", { name: /upcoming scans/i })).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Scheduler policy")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "1 company keeps a time you set" }))
      .toHaveAttribute("aria-expanded", "false");
  });

  it("sums up the plan under the dial with the companies at a time you set and the ones that need attention", async () => {
    render(<ScheduleSection />);
    expect(await screen.findByText(msg("settings-schedule-section-plan-roster-pinned-excepted", {
      companies: 3, roster: 1112, pinned: 1, excepted: 1,
    }))).toBeInTheDocument();
    expect(screen.getByText(msg("settings-schedule-section-days-a-week", { count: 7 }))).toBeInTheDocument();
  });

  it("sums up the plan without the parts that have nothing to count", async () => {
    vi.mocked(api.schedule).mockResolvedValue({ ...planned({ pinned: 0 }), bindings: [fixture.bindings[0]] });
    render(<ScheduleSection />);
    expect(await screen.findByText(msg("settings-schedule-section-plan-roster", { companies: 1, roster: 1112 })))
      .toBeInTheDocument();
  });

  it("tints the hours the computer is usually off instead of a fixed night", async () => {
    render(<ScheduleSection />);
    await screen.findByRole("img", { name: /scan clock/i });

    expect(document.querySelectorAll('[data-testid="usually-off"]')).toHaveLength(1);
    expect(screen.queryByText("NIGHT")).not.toBeInTheDocument();
    const legend = screen.getByLabelText("Schedule clock legend");
    for (const key of ["Full scan", "Quick scan", "Usually off", "A time you set"]) {
      expect(within(legend).getByText(key)).toBeInTheDocument();
    }
    expect(within(legend).queryByText("Reconciliation orbit")).not.toBeInTheDocument();

    expect(screen.getByText(/your computer is on 09:00 to 18:00 on weekdays and usually off at weekends/))
      .toBeInTheDocument();
    expect(screen.queryByText("Discovery cadence")).not.toBeInTheDocument();
  });

  it("keys no off hours for a computer that is on all day", async () => {
    const allDay = [{ start_minute: 0, end_minute: 24 * 60 }];
    vi.mocked(api.schedule).mockResolvedValue(planned({
      usual: { ...schedulePlanFixture().usual, today: allDay, weekdays: allDay, weekends: allDay },
    }));
    render(<ScheduleSection />);
    await screen.findByRole("img", { name: /scan clock/i });

    expect(document.querySelector('[data-testid="usually-off"]')).toBeNull();
    expect(screen.queryByText("NIGHT")).not.toBeInTheDocument();
    expect(within(screen.getByLabelText("Schedule clock legend")).queryByText("Usually off"))
      .not.toBeInTheDocument();
    expect(screen.getByText(/your computer is on all day every day/)).toBeInTheDocument();
    // On all day: there is no usual start to be done by, and the field says so.
    expect(screen.getByLabelText("Full scan done by")).toHaveValue("");
    expect(screen.getByText(/No time set: it runs when you turn the computer on/)).toBeInTheDocument();
  });

  it("offers no drag hint when no company has a time of its own to drag", async () => {
    const unpinned = planned();
    vi.mocked(api.schedule).mockResolvedValue({
      ...unpinned,
      bindings: unpinned.bindings.map((binding) => ({ ...binding, reconcile_anchor_minute: null })),
    });
    render(<ScheduleSection />);
    await screen.findByRole("img", { name: /scan clock/i });

    expect(screen.queryByText(/Drag a mark to reschedule/)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /a time you set/ })).not.toBeInTheDocument();
    expect(within(screen.getByLabelText("Schedule clock legend")).queryByText("A time you set"))
      .not.toBeInTheDocument();
  });

  it("while it is still learning the hours, says so and keeps the night tint", async () => {
    vi.mocked(api.schedule).mockResolvedValue(planned({
      usual: { ...schedulePlanFixture().usual, learning: true, observed_days: 3, today: null, weekdays: null, weekends: null },
    }));
    render(<ScheduleSection />);
    await screen.findByRole("img", { name: /scan clock/i });

    expect(screen.getByText(/Still learning when your computer is on: 3 of 5 days seen/)).toBeInTheDocument();
    expect(document.querySelector('[data-testid="usually-off"]')).toBeNull();
    expect(screen.getByText("NIGHT")).toBeInTheDocument();
  });

  it("changes how often it repeats, and shows the stored answer", async () => {
    vi.mocked(api.updateSchedulePlan).mockResolvedValue(planned({ repeat_hours: 3 }));
    render(<ScheduleSection />);
    await screen.findByRole("img", { name: /scan clock/i });

    const repeat = screen.getByRole("group", { name: "Quick scan every" });
    expect(within(repeat).getByRole("button", { name: "6h" })).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(within(repeat).getByRole("button", { name: "3h" }));

    await waitFor(() => expect(api.updateSchedulePlan).toHaveBeenCalledWith({ repeat_hours: 3 }));
    await waitFor(() =>
      expect(within(repeat).getByRole("button", { name: "3h" })).toHaveAttribute("aria-pressed", "true"));
    expect(screen.getByText("a quick scan every 3 hours")).toBeInTheDocument();
  });

  it("says so when the repeat could not be changed, and keeps the old one", async () => {
    vi.mocked(api.updateSchedulePlan).mockRejectedValue(new Error("offline"));
    render(<ScheduleSection />);
    await screen.findByRole("img", { name: /scan clock/i });

    const repeat = screen.getByRole("group", { name: "Quick scan every" });
    fireEvent.click(within(repeat).getByRole("button", { name: "12h" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Couldn't save that change");
    expect(within(repeat).getByRole("button", { name: "6h" })).toHaveAttribute("aria-pressed", "true");
  });

  it("names the server's reason when a plan setting could not be saved", async () => {
    vi.mocked(api.updateSchedulePlan).mockRejectedValue(new ApiError("down", 0, "offline"));
    render(<ScheduleSection />);
    await screen.findByRole("img", { name: /scan clock/i });
    const repeat = screen.getByRole("group", { name: "Quick scan every" });
    fireEvent.click(within(repeat).getByRole("button", { name: "12h" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(msg("error-offline"));
  });

  it("from the run inspector, a setting that fails says the setting failed, not that a scan did not move", async () => {
    vi.mocked(api.updateSchedulePlan).mockRejectedValue(new Error("boom"));
    render(<ScheduleSection />);
    fireEvent.click(await screen.findByRole("button", { name: /^Move quick scan/ }));
    const inspector = await screen.findByRole("dialog", { name: "Scan inspector" });
    const every = within(inspector).getByRole("group", { name: "Quick scan every" });
    fireEvent.click(within(every).getByRole("button", { name: "12h" }));
    expect(await within(inspector).findByText(msg("settings-schedule-section-couldn-t-save-that-change"))).toBeInTheDocument();
    expect(within(inspector).queryByText(msg("settings-use-dial-drag-couldn-t-move-that-scan"))).not.toBeInTheDocument();
  });

  it("calls a stack of pinned companies by the plan's words, not the timers'", async () => {
    const base = planned({ pinned: 2 });
    vi.mocked(api.schedule).mockResolvedValue({
      ...base,
      bindings: base.bindings.map((binding) => binding.company === "anthropic"
        ? {
          ...binding,
          reconcile_anchor_minute: 20 * 60,
          next_reconcile_at: "2026-07-28T20:00:00Z",
          eligible_reconcile_at: "2026-07-28T20:00:00Z",
        }
        : binding),
    });
    render(<ScheduleSection />);

    expect(await screen.findByRole("button", { name: /^2 full scans at .*open to see all/i }))
      .toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "2 companies keep a time you set" }));
    const times = screen.getByRole("list", { name: "Times you set" });
    expect(within(times).getByText("2 full scans")).toBeInTheDocument();
    // The stack's companies, as one list in the reader's words.
    expect(within(times).getByText(list(["Anthropic", "OpenAI"]))).toBeInTheDocument();
    expect(screen.queryByText(/reconciliations|discovery probes/)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /reconciliations/i })).not.toBeInTheDocument();
  });

  it("names a run in progress as scanning now", async () => {
    vi.mocked(api.schedule).mockResolvedValue(planned({
      upcoming: [
        { at: "2026-07-28T14:10:00Z", kind: "full", seconds: 2460, estimated: true, on_wake: false, running: true, ready_by: false },
      ],
    }));
    render(<ScheduleSection />);
    await screen.findByRole("img", { name: /scan clock/i });

    expect(screen.getByText("Scanning now")).toBeInTheDocument();
    const next = screen.getByRole("list", { name: "Next scans" });
    const row = within(next).getByText("Full scan · scanning").closest(".schedule-upcoming-row");
    expect(row).toHaveTextContent("now");
    expect(row).toHaveTextContent("about 41 min");
    expect(document.querySelector('[data-testid="plan-run"]')).toHaveClass("running");
  });

  it("keeps the inspector on the full scan when a save moves it ahead of the quick ones", async () => {
    const run = (at: string, kind: "full" | "quick", seconds: number) =>
      ({ at, kind, seconds, estimated: false, on_wake: false, running: false, ready_by: false });
    const before = planned({ upcoming: [
      run("2026-07-28T15:00:00Z", "quick", 600), run("2026-07-28T21:00:00Z", "quick", 600),
      run("2026-07-29T03:00:00Z", "quick", 600), run("2026-07-29T09:00:00Z", "full", 2460),
    ] });
    const after = planned({ ready_by_minute: 14 * 60, ready_by_today: { minute: 14 * 60, source: "set" }, upcoming: [
      run("2026-07-28T13:19:00Z", "full", 2460), run("2026-07-28T15:00:00Z", "quick", 600),
      run("2026-07-28T21:00:00Z", "quick", 600), run("2026-07-29T03:00:00Z", "quick", 600),
    ] });
    vi.mocked(api.schedule).mockResolvedValueOnce(before).mockResolvedValue(after);
    vi.mocked(api.updateSchedulePlan).mockResolvedValue(after);
    render(<ScheduleSection />);

    fireEvent.click(await screen.findByRole("button", { name: /^Move full scan/ }));
    const inspector = await screen.findByRole("dialog", { name: "Scan inspector" });
    const field = within(inspector).getByLabelText("Full scan done by");
    fireEvent.change(field, { target: { value: "14:00" } });
    fireEvent.blur(field);
    await waitFor(() => expect(api.updateSchedulePlan).toHaveBeenCalled());

    // The answer puts the full scan first: the list it was fourth in is reordered.
    await waitFor(() => expect(
      screen.getByRole("list", { name: "Next scans" }).querySelector(".schedule-upcoming-row"),
    ).toHaveTextContent(/Full scan/));
    const still = screen.getByRole("dialog", { name: "Scan inspector" });
    expect(within(still).getByLabelText("Full scan done by")).toBeInTheDocument();
    expect(within(still).queryByLabelText("Quick scan time")).not.toBeInTheDocument();
  });

  it("names a pinned mark's exact-time field in the plan's words", async () => {
    render(<ScheduleSection />);
    fireEvent.click(await screen.findByRole("button", { name: /^Move OpenAI full scan/i }));
    expect(await screen.findByLabelText("OpenAI full scan time")).toBeInTheDocument();
  });

  it("shows the usual start as the done-by time and saves a time of your own", async () => {
    vi.mocked(api.schedule).mockResolvedValue(planned({ ready_by_today: { minute: 510, source: "usual" } }));
    vi.mocked(api.updateSchedulePlan).mockResolvedValue(planned({
      ready_by_minute: 450, ready_by_today: { minute: 450, source: "set" },
    }));
    render(<ScheduleSection />);
    const settings = await screen.findByLabelText("Plan settings");

    const field = within(settings).getByLabelText("Full scan done by");
    expect(field).toHaveValue("08:30");
    expect(within(settings).getByText(/^Your usual start, learned\. Starts about 07:39/)).toBeInTheDocument();
    expect(within(settings).queryByRole("button", { name: "Use my usual start" })).not.toBeInTheDocument();

    fireEvent.change(field, { target: { value: "07:30" } });
    fireEvent.blur(field);
    await waitFor(() => expect(api.updateSchedulePlan).toHaveBeenCalledWith({ ready_by_minute: 450 }));
    await waitFor(() => expect(within(settings).getByLabelText("Full scan done by")).toHaveValue("07:30"));
    expect(within(settings).queryByText(/Your usual start, learned/)).not.toBeInTheDocument();
    fireEvent.click(within(settings).getByRole("button", { name: "Use my usual start" }));
    await waitFor(() => expect(api.updateSchedulePlan).toHaveBeenLastCalledWith({ ready_by_minute: null }));
  });

  it("turns a scan day off, and never the last one", async () => {
    vi.mocked(api.updateSchedulePlan).mockResolvedValue(planned({ days: [0, 1, 2, 3, 4, 6] }));
    render(<ScheduleSection />);
    const days = await screen.findByRole("group", { name: "Scan days" });
    expect(within(days).getByRole("button", { name: "Sat" })).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(within(days).getByRole("button", { name: "Sat" }));
    await waitFor(() => expect(api.updateSchedulePlan).toHaveBeenCalledWith({ days: [0, 1, 2, 3, 4, 6] }));
    await waitFor(() =>
      expect(within(days).getByRole("button", { name: "Sat" })).toHaveAttribute("aria-pressed", "false"));
    expect(screen.getByText("6 days a week")).toBeInTheDocument();
  });

  it("keeps the last scan day switched on", async () => {
    vi.mocked(api.schedule).mockResolvedValue(planned({ days: [2] }));
    render(<ScheduleSection />);
    const days = await screen.findByRole("group", { name: "Scan days" });
    expect(within(days).getByRole("button", { name: "Wed" })).toBeDisabled();
    expect(within(days).getByRole("button", { name: "Thu" })).toBeEnabled();
    // One day is singular: never "1 days a week".
    expect(screen.getByText("1 day a week")).toBeInTheDocument();
  });

  it("waits for mains power when asked, and says so while on battery", async () => {
    vi.mocked(api.updateSchedulePlan).mockResolvedValue(planned({ mains_only: true, waiting: "mains" }));
    render(<ScheduleSection />);
    const toggle = await screen.findByRole("checkbox", { name: /Only when plugged in/ });
    expect(toggle).not.toBeChecked();
    fireEvent.click(toggle);
    await waitFor(() => expect(api.updateSchedulePlan).toHaveBeenCalledWith({ mains_only: true }));
    expect(await screen.findByText("On battery now: the next scan waits for power.")).toBeInTheDocument();
    expect(screen.getByText("Waiting for power")).toBeInTheDocument();
  });

  it("pauses for a while, shows until when, and resumes", async () => {
    vi.mocked(api.updateSchedulePlan).mockResolvedValueOnce(planned({
      paused_until: "2026-07-28T17:30:00Z", waiting: "paused",
    })).mockResolvedValueOnce(planned());
    render(<ScheduleSection />);
    const pause = await screen.findByRole("group", { name: "Pause scans" });
    fireEvent.click(within(pause).getByRole("button", { name: "3 hours" }));
    await waitFor(() => expect(api.updateSchedulePlan).toHaveBeenCalledWith({ pause: "3h" }));

    expect(await screen.findByText(/Paused until/)).toBeInTheDocument();
    expect(screen.getByText("Paused")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Resume" }));
    await waitFor(() => expect(api.updateSchedulePlan).toHaveBeenLastCalledWith({ pause: "resume" }));
    await waitFor(() => expect(screen.getByRole("group", { name: "Pause scans" })).toBeInTheDocument());
  });

  it("says a day off in the centre of the dial", async () => {
    vi.mocked(api.schedule).mockResolvedValue(planned({ waiting: "day_off", days: [0, 1] }));
    render(<ScheduleSection />);
    expect(await screen.findByText("Day off")).toBeInTheDocument();
    expect(screen.getByText("no scans today")).toBeInTheDocument();
  });

  it("labels the day's full scan with when it will be ready", async () => {
    vi.mocked(api.schedule).mockResolvedValue(planned({
      upcoming: [
        { at: "2026-07-28T15:00:00Z", kind: "full", seconds: 2400, estimated: false, on_wake: false, running: false, ready_by: true },
      ],
    }));
    render(<ScheduleSection />);
    const next = await screen.findByRole("list", { name: "Next scans" });
    expect(within(next).getByText(/^Full scan · ready by \d{2}:40$/)).toBeInTheDocument();
  });

  it("lists every company with its last scans and how the plan scans it", async () => {
    const base = planned();
    vi.mocked(api.schedule).mockResolvedValue({
      ...base,
      bindings: [
        ...base.bindings,
        {
          ...base.bindings[1], binding_id: 9, company: "adobe", provider: "workday",
          reconcile_anchor_minute: null, waits_for_user: "user_directed",
        },
      ],
    });
    render(<ScheduleSection />);
    fireEvent.click(await screen.findByRole("button", { name: "Every company's scans" }));
    const sheet = await screen.findByRole("dialog", { name: "Every company's scans" });
    for (const column of ["Last full scan", "Last quick scan", "How it is scanned"]) {
      expect(within(sheet).getByRole("columnheader", { name: column })).toBeInTheDocument();
    }
    const row = (company: string | RegExp) => within(sheet).getByText(company).closest("tr") as HTMLElement;
    expect(row(/^adobe$/i)).toHaveTextContent("Only when you press Scan now");
    expect(row("OpenAI")).toHaveTextContent("Its own time: full scan at 20:00");
    expect(row("Anthropic")).toHaveTextContent("Every planned scan");
    expect(row("Meta")).toHaveTextContent("Policy denied");
    expect(within(sheet).queryByText("Scheduled")).not.toBeInTheDocument();
  });

  it("joins a company's own times as one list", async () => {
    const base = planned();
    vi.mocked(api.schedule).mockResolvedValue({
      ...base,
      bindings: [{ ...base.bindings[0], discovery_anchor_minute: 6 * 60 }, ...base.bindings.slice(1)],
    });
    render(<ScheduleSection />);
    fireEvent.click(await screen.findByRole("button", { name: msg("settings-schedule-section-deadlines-link", { schedule: "plan" }) }));
    const sheet = await screen.findByRole("dialog", { name: msg("settings-schedule-section-every-company-s-scans-2") });
    expect(within(sheet).getByText("OpenAI").closest("tr")).toHaveTextContent(msg("settings-schedule-section-its-own-time", {
      times: list([
        msg("settings-schedule-section-full-scan-at", { reconcile_anchor_minute: "20:00" }),
        msg("settings-schedule-section-quick-scan-at", { discovery_anchor_minute: "06:00" }),
      ]),
    }));
  });
});

/* The plan's runs are the dial's marks: drag one to move it, click it for its
   numbers. jsdom has no layout,
   so the stage's centre is (0, 0): a pointer at (100, 0) is 06:00 and one at
   (0, 100) is 12:00. */
describe("dragging and clicking the plan's runs", () => {
  beforeAll(() => {
    Element.prototype.setPointerCapture = function setPointerCapture() {};
    Element.prototype.releasePointerCapture = function releasePointerCapture() {};
  });
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(api.schedule).mockResolvedValue(planned());
    vi.mocked(api.updateSchedulePlan).mockResolvedValue(planned());
  });

  const drag = (handle: HTMLElement, x: number, y: number) => {
    fireEvent.pointerDown(handle, { pointerId: 1, clientX: 0, clientY: -100 });
    fireEvent.pointerMove(handle, { pointerId: 1, clientX: x, clientY: y });
    fireEvent.pointerUp(handle, { pointerId: 1, clientX: x, clientY: y });
  };

  it("puts a handle on every planned scan", async () => {
    render(<ScheduleSection />);
    await screen.findByRole("img", { name: /scan clock/i });
    expect(screen.getByRole("button", { name: /^Move quick scan, at \d{2}:\d{2}$/ })).toBeEnabled();
    expect(screen.getByRole("button", { name: /^Move full scan, when you turn it on, about \d{2}:\d{2}$/ }))
      .toBeEnabled();
  });

  it("drags a quick scan and every quick scan follows to fixed clock times", async () => {
    render(<ScheduleSection />);
    drag(await screen.findByRole("button", { name: /^Move quick scan/ }), 100, 0);
    await waitFor(() => expect(api.updateSchedulePlan).toHaveBeenCalledWith({ repeat_anchor_minute: 6 * 60 }));
    expect(await screen.findByText("Quick scans moved: one at 06:00.")).toBeInTheDocument();
  });

  it("drags the full scan and its done-by time follows its measured length", async () => {
    render(<ScheduleSection />);
    drag(await screen.findByRole("button", { name: /^Move full scan/ }), 0, 100);
    // Starts 12:00, takes 41 min, plus a tick's margin: done by 12:51, to the
    // minute, so the saved scan starts exactly where it was dropped.
    await waitFor(() => expect(api.updateSchedulePlan).toHaveBeenCalledWith({ ready_by_minute: 12 * 60 + 51 }));
  });

  it("a press without a drag opens the scan's numbers instead of moving it", async () => {
    render(<ScheduleSection />);
    const handle = await screen.findByRole("button", { name: /^Move quick scan/ });
    fireEvent.pointerDown(handle, { pointerId: 1, clientX: 0, clientY: -100 });
    fireEvent.pointerUp(handle, { pointerId: 1, clientX: 1, clientY: -100 });
    fireEvent.click(handle);
    await act(async () => {});
    expect(api.updateSchedulePlan).not.toHaveBeenCalled();
    const inspector = await screen.findByRole("dialog", { name: "Scan inspector" });
    expect(within(inspector).getByText("944")).toBeInTheDocument();
    expect(within(inspector).getByText("10 min")).toBeInTheDocument();
    expect(within(inspector).getByText("every 6h after the last scan")).toBeInTheDocument();
  });

  it("types an exact time for the quick scans and changes their repeat from the inspector", async () => {
    render(<ScheduleSection />);
    fireEvent.click(await screen.findByRole("button", { name: /^Move quick scan/ }));
    const inspector = await screen.findByRole("dialog", { name: "Scan inspector" });
    const field = within(inspector).getByLabelText("Quick scan time");
    fireEvent.change(field, { target: { value: "10:00" } });
    fireEvent.blur(field);
    await waitFor(() => expect(api.updateSchedulePlan).toHaveBeenCalledWith({ repeat_anchor_minute: 600 }));

    await waitFor(() => expect(within(inspector).getByRole("button", { name: "3h" })).toBeEnabled());
    fireEvent.click(within(inspector).getByRole("button", { name: "3h" }));
    await waitFor(() => expect(api.updateSchedulePlan).toHaveBeenLastCalledWith({ repeat_hours: 3 }));
  });

  it("offers counting from the last scan again once the quick scans have clock times", async () => {
    vi.mocked(api.schedule).mockResolvedValue(planned({ repeat_anchor_minute: 600 }));
    render(<ScheduleSection />);
    fireEvent.click(await screen.findByRole("button", { name: /^Move quick scan/ }));
    const inspector = await screen.findByRole("dialog", { name: "Scan inspector" });
    expect(within(inspector).getByText("every 6h at fixed times")).toBeInTheDocument();
    fireEvent.click(within(inspector).getByRole("button", { name: "Count from the last scan instead" }));
    await waitFor(() => expect(api.updateSchedulePlan).toHaveBeenCalledWith({ repeat_anchor_minute: null }));
  });

  it("types when the full scan should be done by", async () => {
    render(<ScheduleSection />);
    fireEvent.click(await screen.findByRole("button", { name: /^Move full scan/ }));
    const inspector = await screen.findByRole("dialog", { name: "Scan inspector" });
    const field = within(inspector).getByLabelText("Full scan done by");
    fireEvent.change(field, { target: { value: "09:00" } });
    fireEvent.blur(field);
    await waitFor(() => expect(api.updateSchedulePlan).toHaveBeenCalledWith({ ready_by_minute: 9 * 60 }));
  });

  it("follows the pointer smoothly, not in 10-minute steps, and says where it will land", async () => {
    render(<ScheduleSection />);
    const handle = await screen.findByRole("button", { name: /^Move quick scan/ });
    fireEvent.pointerDown(handle, { pointerId: 1, clientX: 0, clientY: -100 });
    fireEvent.pointerMove(handle, { pointerId: 1, clientX: 100, clientY: 0 }); // 06:00
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("Quick scan · 06:00"));
    const at0600 = handle.style.left + handle.style.top;
    // Two minutes on: snapped, the handle would not move at all.
    fireEvent.pointerMove(handle, { pointerId: 1, clientX: 100, clientY: 1 });
    await waitFor(() => expect(handle.style.left + handle.style.top).not.toBe(at0600));
    expect(screen.getByRole("status")).toHaveTextContent("Quick scan · 06:00");
    fireEvent.pointerCancel(handle, { pointerId: 1 });
  });

  it("stays under the pointer frame after frame instead of flicking back", async () => {
    // The dial hands the drag the run as drawn, already moved; measuring each
    // move from that would undo the previous frame, and the run would jump
    // between the pointer and its old place on every other move.
    render(<ScheduleSection />);
    const handle = await screen.findByRole("button", { name: /^Move quick scan/ });
    fireEvent.pointerDown(handle, { pointerId: 1, clientX: 0, clientY: -100 });
    fireEvent.pointerMove(handle, { pointerId: 1, clientX: 100, clientY: 0 });
    await waitFor(() => expect(handle.style.left).toMatch(/^76\./));
    const first = handle.style.left + handle.style.top;
    for (let frame = 0; frame < 3; frame += 1) {
      fireEvent.pointerMove(handle, { pointerId: 1, clientX: 100, clientY: 0 });
      await new Promise((resolve) => requestAnimationFrame(() => resolve(null)));
      await new Promise((resolve) => setTimeout(resolve, 0));
      expect(handle.style.left + handle.style.top, `frame ${frame} moved off the pointer`).toBe(first);
    }
    fireEvent.pointerCancel(handle, { pointerId: 1 });
  });

  it("keeps every label it is not dragging where it was", async () => {
    render(<ScheduleSection />);
    const handle = await screen.findByRole("button", { name: /^Move quick scan/ });
    const fullLabel = () => [...document.querySelectorAll(".dial-label")]
      .find((label) => label.textContent?.includes("Full scan")) as SVGTextElement;
    const before = `${fullLabel().getAttribute("x")},${fullLabel().getAttribute("y")}`;
    fireEvent.pointerDown(handle, { pointerId: 1, clientX: 0, clientY: -100 });
    fireEvent.pointerMove(handle, { pointerId: 1, clientX: 100, clientY: 0 });
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("Quick scan · 06:00"));
    expect(`${fullLabel().getAttribute("x")},${fullLabel().getAttribute("y")}`).toBe(before);
    fireEvent.pointerCancel(handle, { pointerId: 1 });
  });

  it("holds a dropped run where it was dropped while the save is in flight", async () => {
    let finish: (value: SyncSchedule) => void = () => undefined;
    vi.mocked(api.updateSchedulePlan).mockReturnValue(new Promise<SyncSchedule>((resolve) => { finish = resolve; }));
    render(<ScheduleSection />);
    const handle = await screen.findByRole("button", { name: /^Move quick scan/ });
    const resting = handle.style.left + handle.style.top;
    fireEvent.pointerDown(handle, { pointerId: 1, clientX: 0, clientY: -100 });
    fireEvent.pointerMove(handle, { pointerId: 1, clientX: 100, clientY: 0 });
    fireEvent.pointerUp(handle, { pointerId: 1, clientX: 100, clientY: 0 });
    await waitFor(() => expect(api.updateSchedulePlan).toHaveBeenCalledWith({ repeat_anchor_minute: 360 }));
    await new Promise((resolve) => setTimeout(resolve, 40));
    expect(handle.style.left + handle.style.top, "sprang back before the save").not.toBe(resting);
    finish(planned({ repeat_anchor_minute: 360 }));
  });

  it("shows a running scan's numbers but does not let it be moved", async () => {
    vi.mocked(api.schedule).mockResolvedValue(planned({
      upcoming: [
        { at: "2026-07-28T14:10:00Z", kind: "full", seconds: 2460, estimated: false, on_wake: false, running: true, ready_by: false },
      ],
    }));
    render(<ScheduleSection />);
    const handle = await screen.findByRole("button", { name: /^Full scan running since/ });
    drag(handle, 100, 0);
    await act(async () => {});
    expect(api.updateSchedulePlan).not.toHaveBeenCalled();
    fireEvent.click(handle);
    const inspector = await screen.findByRole("dialog", { name: "Scan inspector" });
    expect(within(inspector).getByText("Scanning now")).toBeInTheDocument();
    expect(within(inspector).getByLabelText("Full scan done by")).toBeDisabled();
  });
});

/* Every write answers with the whole schedule. So the screen sends one write
   at a time, in the order they were made, and holds every control that writes
   while one is out. */
describe("every schedule write in one order", () => {
  beforeAll(() => {
    Element.prototype.setPointerCapture = function setPointerCapture() {};
    Element.prototype.releasePointerCapture = function releasePointerCapture() {};
  });
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(api.schedule).mockResolvedValue(planned());
  });

  /* A server that answers each write from the plan it held when the request
     arrived, and only when the test lets it. Two requests in the air at once
     would each write back the other's old value, so only a client that sends
     one at a time keeps both edits. */
  const heldServer = () => {
    let stored = planned();
    const held: Array<() => void> = [];
    vi.mocked(api.updateSchedulePlan).mockImplementation((update) => {
      const read = stored;
      return new Promise<SyncSchedule>((resolve) => {
        held.push(() => {
          stored = { ...read, plan: { ...read.plan, ...update } as SyncSchedule["plan"] };
          resolve(stored);
        });
      });
    });
    vi.mocked(api.updateSchedule).mockImplementation(() => {
      const read = stored;
      return new Promise<SyncSchedule>((resolve) => {
        held.push(() => {
          stored = read;
          resolve(stored);
        });
      });
    });
    /** Answer every request in the air, the last one sent first, until no
     *  write is left to send. */
    const drain = async () => {
      for (let round = 0; round < 10; round += 1) {
        await act(async () => {});
        if (held.length === 0) return;
        while (held.length > 0) held.pop()?.();
        await act(async () => {});
      }
    };
    return { drain };
  };

  /** Every control on the screen that writes the schedule, open or not. */
  const writers = () => {
    const settings = screen.getByLabelText("Plan settings");
    return [
      ...within(within(settings).getByRole("group", { name: "Scan days" })).getAllByRole("button"),
      ...within(within(settings).getByRole("group", { name: "Quick scan every" })).getAllByRole("button"),
      ...within(within(settings).getByRole("group", { name: "Pause scans" })).getAllByRole("button"),
      within(settings).getByRole("checkbox", { name: /Only when plugged in/ }),
      screen.getByRole("button", { name: /^Move quick scan/ }),
      screen.getByRole("button", { name: /^Move full scan/ }),
      screen.getByRole("button", { name: /^Move OpenAI full scan/ }),
    ];
  };
  /** The exact-time fields stay focusable while a write is out, and read only. */
  const timeFields = () => [
    within(screen.getByLabelText("Plan settings")).getByLabelText("Full scan done by"),
    ...screen.queryAllByLabelText(/(Quick scan|OpenAI full scan) time$/),
  ];

  it("sends two quick edits one after the other, and both land", async () => {
    const server = heldServer();
    render(<ScheduleSection />);
    const settings = await screen.findByLabelText("Plan settings");
    const days = within(settings).getByRole("group", { name: "Scan days" });
    const repeat = within(settings).getByRole("group", { name: "Quick scan every" });

    // Two edits faster than a render: no control has been disabled yet.
    act(() => {
      fireEvent.click(within(days).getByRole("button", { name: "Sat" }));
      fireEvent.click(within(repeat).getByRole("button", { name: "3h" }));
    });
    await act(async () => {});
    // The second waits until the first is answered.
    expect(api.updateSchedulePlan).toHaveBeenCalledTimes(1);
    expect(api.updateSchedulePlan).toHaveBeenLastCalledWith({ days: [0, 1, 2, 3, 4, 6] });

    await server.drain();
    expect(vi.mocked(api.updateSchedulePlan).mock.calls.map(([update]) => update))
      .toEqual([{ days: [0, 1, 2, 3, 4, 6] }, { repeat_hours: 3 }]);
    expect(within(days).getByRole("button", { name: "Sat" })).toHaveAttribute("aria-pressed", "false");
    expect(within(repeat).getByRole("button", { name: "3h" })).toHaveAttribute("aria-pressed", "true");
  });

  it("orders a company's own time and a plan edit in the same queue", async () => {
    const server = heldServer();
    render(<ScheduleSection />);
    fireEvent.click(await screen.findByRole("button", { name: /^Move OpenAI full scan/ }));
    const field = await screen.findByLabelText("OpenAI full scan time");
    fireEvent.change(field, { target: { value: "21:00" } });
    const days = within(screen.getByLabelText("Plan settings")).getByRole("group", { name: "Scan days" });

    act(() => {
      fireEvent.blur(field);
      fireEvent.click(within(days).getByRole("button", { name: "Sat" }));
    });
    await act(async () => {});
    expect(api.updateSchedule).toHaveBeenCalledTimes(1);
    expect(api.updateSchedulePlan).not.toHaveBeenCalled();

    await server.drain();
    expect(api.updateSchedulePlan).toHaveBeenCalledWith({ days: [0, 1, 2, 3, 4, 6] });
    expect(within(days).getByRole("button", { name: "Sat" })).toHaveAttribute("aria-pressed", "false");
  });

  it("while a plan run's edit is out, every control that writes waits for it", async () => {
    const server = heldServer();
    render(<ScheduleSection />);
    await screen.findByRole("img", { name: /scan clock/i });
    for (const control of writers()) expect(control).toBeEnabled();

    fireEvent.click(screen.getByRole("button", { name: /^Move quick scan/ }));
    const inspector = await screen.findByRole("dialog", { name: "Scan inspector" });
    fireEvent.click(within(inspector).getByRole("button", { name: "3h" }));
    await act(async () => {});
    expect(api.updateSchedulePlan).toHaveBeenCalledTimes(1);

    const held = [...writers(), ...within(inspector).getAllByRole("button", { name: /^\d+h$/ })];
    for (const control of held) expect(control).toBeDisabled();
    for (const field of timeFields()) expect(field).toHaveAttribute("readonly");

    await server.drain();
    for (const control of writers()) expect(control).toBeEnabled();
    for (const field of timeFields()) expect(field).not.toHaveAttribute("readonly");
  });

  it("while a company's move is out, the plan's controls wait for it too", async () => {
    const server = heldServer();
    render(<ScheduleSection />);
    fireEvent.click(await screen.findByRole("button", { name: /^Move OpenAI full scan/ }));
    const field = await screen.findByLabelText("OpenAI full scan time");
    fireEvent.change(field, { target: { value: "21:00" } });
    fireEvent.blur(field);
    await act(async () => {});
    expect(api.updateSchedule).toHaveBeenCalledTimes(1);

    for (const control of writers()) expect(control).toBeDisabled();
    for (const time of timeFields()) expect(time).toHaveAttribute("readonly");

    await server.drain();
    for (const control of writers()) expect(control).toBeEnabled();
  });
});

describe("a full scan's start and done-by time", () => {
  it("round-trips to the minute, across midnight", () => {
    for (const readyBy of [0, 9 * 60, 13 * 60 + 33, 23 * 60 + 59]) {
      expect(readyByForStart(startForReadyBy(readyBy, 2460), 2460)).toBe(readyBy);
    }
    for (const start of [0, 7 * 60 + 50, 23 * 60 + 40]) {
      expect(startForReadyBy(readyByForStart(start, 1980), 1980)).toBe(start);
    }
    expect(readyByForStart(23 * 60 + 40, 2460)).toBe(31);
  });
});

/* Words the schedule says in place of a time, a length or an answer come from
   the catalog, so another language shows none of the English. */
describe("ScheduleSection in another language", () => {
  beforeEach(() => vi.clearAllMocks());
  afterEach(() => activate("en"));

  it("says a running scan and a guessed length in the reader's words", async () => {
    await activate("es");
    vi.mocked(api.schedule).mockResolvedValue(planned({
      upcoming: [
        { at: "2026-07-28T14:10:00Z", kind: "full", seconds: 2460, estimated: true, on_wake: false, running: true, ready_by: false },
      ],
    }));
    render(<ScheduleSection />);

    const next = await screen.findByRole("list", { name: msg("settings-schedule-section-next-scans-2") });
    const [row] = within(next).getAllByRole("listitem");
    expect(row.querySelector("time")).toHaveTextContent(msg("settings-schedule-section-now"));
    expect(row).toHaveTextContent(msg("settings-plan-about", { duration: msg("settings-plan-min", { minutes: 41 }) }));
    expect(row).not.toHaveTextContent(/\bnow\b|about/);
    // The dial's label beside the running scan says it too.
    const times = [...document.querySelectorAll(".dial-label-time")].map((node) => node.textContent);
    expect(times).toContain(msg("settings-schedule-section-now"));
    expect(times).not.toContain("now");
  });

  it("answers whether a company's site closes roles in the reader's words", async () => {
    await activate("zh-Hans");
    const reconcile = msg("settings-schedule-mode-name", { schedule: "timers", mode: "reconcile" });
    const closesRoles = async (closure: string) => {
      vi.mocked(api.schedule).mockResolvedValue({ ...fixture, bindings: [{ ...fixture.bindings[0], closure_capability: closure }] });
      const view = render(<ScheduleSection />);
      fireEvent.click(await screen.findByRole("button", { name: new RegExp(`OpenAI ${reconcile}`) }));
      const inspector = await screen.findByRole("dialog", { name: msg("settings-chronograph-inspector-scan-schedule-inspector") });
      const answer = within(inspector).getByText(msg("settings-chronograph-inspector-closes-roles")).nextElementSibling;
      const text = answer?.textContent;
      view.unmount();
      return text;
    };
    expect(await closesRoles("authoritative")).toBe(msg("settings-plan-run-inspector-yes"));
    expect(await closesRoles("none")).toBe(msg("settings-chronograph-inspector-no"));
  });
});
