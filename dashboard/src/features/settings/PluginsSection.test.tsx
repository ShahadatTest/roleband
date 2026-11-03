import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { ApiError, api } from "../../api";
import { resetWriteQueues } from "../../hooks/useWriteQueue";
import {
  pluginAdoptingFixture, pluginDetailFixture, pluginFixture, pluginLapsedFixture, pluginRunContinuingFixture,
  pluginRunStoppedFixture, pluginsFixture, referenceFixture, pluginRobotsFixture,
} from "../../test/fixtures";
import { msg } from "../../test/msg";
import { PluginsSection } from "./PluginsSection";
import { duration, list } from "../../copy/format";
import { ago } from "./pluginWords";
import { START_WINDOW_MS } from "./usePluginActions";

/* Settings > Plugins: one kit row per
   plugin. The switch turns its data on and off (a plugin that needs approval is
   reviewed first, AS SHOWN); Start updates now, and when it cannot, says why
   beside it; Pause is not a row verb (it lives on the plugin's settings, with
   one meaning); the badge says only what the switch does not; the gear opens
   its settings; search filters the installed plugins; the summary under the
   intro says what estimates did. */

const epoch = vi.hoisted(() => ({ referenceVersion: 0, notificationVersion: 0 }));
// The status poll a plugin decision asks for at once.
const poll = vi.hoisted(() => vi.fn(async () => {}));

vi.mock("../../context/SyncState", () => ({ useSyncEpoch: () => epoch, useStatusPoll: () => poll }));
vi.mock("../../api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../api")>();
  return {
    ...actual,
    api: {
      plugins: vi.fn(),
      plugin: vi.fn(),
      approvePlugin: vi.fn(),
      pluginRobots: vi.fn(async () => ({ sites: [], consent: null, consent_at: null })),
      setPluginRobots: vi.fn(),
      enablePlugin: vi.fn(),
      disablePlugin: vi.fn(),
      refreshPlugin: vi.fn(),
      pausePlugin: vi.fn(),
    },
  };
});

const action = (plugin = pluginFixture()) => ({ plugin, reestimate_started: false, stopped: [] });
const reports = pluginFixture({
  id: "acme-reports", name: "Acme pay reports", slots: ["pay.observations"], active_slots: ["pay.observations"],
  attribution: "Data source: Acme",
});

function Where() {
  return <span data-testid="where">{useLocation().pathname}</span>;
}

function renderSection() {
  return render(
    <MemoryRouter initialEntries={["/settings/plugins"]}>
      <Routes>
        <Route path="/settings/plugins" element={<PluginsSection />} />
        <Route path="*" element={<Where />} />
      </Routes>
    </MemoryRouter>,
  );
}

const row = (id = "example-pay") => screen.findByTestId(`plugin-row-${id}`);
/** A failed write on one plugin: said directly under that plugin's row. */
async function rowAlert(id = "example-pay") {
  const r = await row(id);
  await waitFor(() => expect(r.nextElementSibling).toHaveAttribute("role", "alert"));
  return r.nextElementSibling as HTMLElement;
}
const useSwitch = (name = "Example pay data") =>
  screen.findByRole("checkbox", { name: msg("settings-plugins-section-use", { name }) });
/** A row's Start, named by its plugin: every row has one. */
const startName = (name = "Example pay data") => msg("settings-plugins-section-start-name", { name });

afterEach(() => {
  vi.useRealTimers();
});

beforeEach(() => {
  vi.clearAllMocks();
  resetWriteQueues();
  epoch.referenceVersion = 0;
  vi.mocked(api.plugins).mockResolvedValue(pluginsFixture());
});

it("a row says what the plugin answers, when it updated and updates next, and its state; the head counts what is on", async () => {
  renderSection();
  const r = await row();
  expect(within(r).getByText("Example pay data")).toBeVisible();
  expect(screen.getByTestId("plugin-answers-example-pay")).toHaveTextContent(
    msg("settings-plugins-section-answers", { slots: "benefits and comp bands" }),
  );
  const facts = screen.getByTestId("plugin-facts-example-pay");
  // One casing with the plugin's page: the line opens "Updated", as Last update does.
  expect(facts).toHaveTextContent(/^Updated /);
  expect(facts).toHaveTextContent(/next update (19 Jul|Jul 19)/);
  // "On" beside a switch that is on is the same fact twice: no badge says it.
  expect(within(r).queryByText(msg("settings-plugins-section-state", { state: "enabled" }))).toBeNull();
  expect(await useSwitch()).toBeChecked();
  expect(screen.getByText(msg("settings-plugins-section-on-count", { on: 1, total: 1 }))).toBeVisible();
  expect(screen.getByRole("note")).toHaveTextContent("Estimates changed for 44 roles at 6 companies");
});

it("while the list loads it says so in one whole sentence, never \"Loading Loading\"", async () => {
  vi.mocked(api.plugins).mockReturnValue(new Promise(() => {}));
  renderSection();
  const status = await screen.findByRole("status");
  expect(status).toHaveTextContent(msg("settings-plugins-section-loading"));
  expect(status).not.toHaveTextContent(/Loading Loading/);
});

it("with nothing installed it says so, offers no plugin control, and still shows where more plugins will come from", async () => {
  vi.mocked(api.plugins).mockResolvedValue(pluginsFixture({ plugins: [], reference: referenceFixture({
    last_change: null, last_change_id: null }) }));
  renderSection();
  const none = await screen.findByText(msg("settings-plugins-section-none"));
  expect(none).toBeVisible();
  // An empty list is an empty state, not a notice banner.
  expect(screen.queryByRole("note")).toBeNull();
  expect(none.closest(".settings-message")).toBeNull();
  expect(screen.getByText(msg("settings-plugins-section-more"))).toBeVisible();
  expect(screen.queryByRole("checkbox")).toBeNull();
  expect(screen.queryByRole("button")).toBeNull();
});

it("search filters by name and by what a plugin brings, and says when nothing matches", async () => {
  vi.mocked(api.plugins).mockResolvedValue(pluginsFixture({ plugins: [pluginFixture(), reports] }));
  renderSection();
  await row("acme-reports");
  const search = screen.getByRole("searchbox", { name: msg("settings-plugins-section-search") });
  await userEvent.type(search, "compensation estimates");
  expect(screen.queryByTestId("plugin-row-example-pay")).toBeNull();
  expect(screen.getByTestId("plugin-row-acme-reports")).toBeVisible();
  await userEvent.clear(search);
  await userEvent.type(search, "example");
  expect(screen.getByTestId("plugin-row-example-pay")).toBeVisible();
  expect(screen.queryByTestId("plugin-row-acme-reports")).toBeNull();
  await userEvent.clear(search);
  await userEvent.type(search, "glassdoor");
  expect(screen.getByText(msg("settings-plugins-section-no-match"))).toBeVisible();
  expect(screen.getByText(msg("settings-plugins-section-more"))).toBeVisible();
});

it("the switch turns a plugin off and on, at once when it has read every followed company", async () => {
  const whole = { coverage: { "pay.levels": 120, "company.benefits": 120 } };
  vi.mocked(api.plugins)
    .mockResolvedValueOnce(pluginsFixture({ plugins: [pluginFixture(whole)] }))
    .mockResolvedValue(pluginsFixture({ plugins: [pluginFixture({ ...whole, state: "disabled", active_slots: [] })] }));
  vi.mocked(api.disablePlugin).mockResolvedValue(action(pluginFixture({ state: "disabled" })));
  vi.mocked(api.enablePlugin).mockResolvedValue(action());
  renderSection();
  await userEvent.click(await useSwitch());
  expect(api.disablePlugin).toHaveBeenCalledWith("example-pay");
  await waitFor(async () => expect(await useSwitch()).not.toBeChecked());
  await userEvent.click(await useSwitch());
  expect(api.enablePlugin).toHaveBeenCalledWith("example-pay");
});

it("turning on a plugin that would leave companies empty asks first, saying what goes empty", async () => {
  const off = pluginFixture({ state: "disabled", active_slots: [] });
  vi.mocked(api.plugins).mockResolvedValue(pluginsFixture({ plugins: [off] }));
  vi.mocked(api.enablePlugin).mockResolvedValue(action());
  renderSection();
  await userEvent.click(await useSwitch());
  expect(api.enablePlugin).not.toHaveBeenCalled();
  const dialog = await screen.findByRole("dialog", { name: msg("settings-plugins-section-turn-on-title") });
  expect(dialog).toHaveTextContent(msg("settings-plugins-section-turn-on-lead"));
  const gap = within(dialog).getByTestId("plugin-approval-gap");
  expect(gap).toHaveTextContent(msg("settings-plugins-section-approve-gap"));
  expect(gap).toHaveTextContent(msg("shared-results-of-company", { n: 96, t: 120, total: 120 }));

  await userEvent.click(within(dialog).getByRole("button", { name: msg("settings-cancel") }));
  expect(screen.queryByRole("dialog")).toBeNull();
  expect(api.enablePlugin).not.toHaveBeenCalled();

  await userEvent.click(await useSwitch());
  const again = await screen.findByRole("dialog", { name: msg("settings-plugins-section-turn-on-title") });
  await userEvent.click(within(again).getByRole("button", { name: msg("settings-plugins-section-turn-on") }));
  await waitFor(() => expect(api.enablePlugin).toHaveBeenCalledWith("example-pay"));
});

it("a switch asks the status at once, so estimates read as updating from the click", async () => {
  vi.mocked(api.plugins).mockResolvedValue(pluginsFixture());
  vi.mocked(api.disablePlugin).mockResolvedValue(action(pluginFixture({ state: "disabled" })));
  renderSection();
  await useSwitch();
  expect(poll).not.toHaveBeenCalled();
  await userEvent.click(await useSwitch());
  await waitFor(() => expect(poll).toHaveBeenCalledTimes(1));
  // After the write and the list's refetch, never before the write lands.
  expect(vi.mocked(api.disablePlugin).mock.invocationCallOrder[0])
    .toBeLessThan(poll.mock.invocationCallOrder[0]);
});

it("turning on a plugin that needs approval reviews it first: approving names the fingerprint shown, then turns it on", async () => {
  vi.mocked(api.plugins).mockResolvedValue(pluginsFixture({
    plugins: [pluginFixture({ state: "needs_approval", active_slots: [], last_run: null })],
  }));
  vi.mocked(api.plugin).mockResolvedValue(pluginDetailFixture());
  vi.mocked(api.approvePlugin).mockResolvedValue(action(pluginFixture({ state: "disabled" })));
  vi.mocked(api.enablePlugin).mockResolvedValue(action());
  renderSection();
  expect(within(await row()).getByText(msg("settings-plugins-section-state", { state: "needs_approval" }))).toBeVisible();
  await userEvent.click(await useSwitch());
  expect(api.enablePlugin).not.toHaveBeenCalled();

  const dialog = await screen.findByRole("dialog", { name: msg("settings-plugins-section-approve-title") });
  expect(within(dialog).getByText("data.example.com")).toBeVisible();
  expect(dialog).toHaveTextContent(msg("settings-plugins-section-schedule", { schedule: "weekly" }));
  await userEvent.click(within(dialog).getByRole("button", { name: msg("settings-plugins-section-approve-and-turn-on") }));

  expect(api.approvePlugin).toHaveBeenCalledWith("example-pay", "f0".repeat(32), null);
  await waitFor(() => expect(api.enablePlugin).toHaveBeenCalledWith("example-pay"));
  expect(vi.mocked(api.approvePlugin).mock.invocationCallOrder[0])
    .toBeLessThan(vi.mocked(api.enablePlugin).mock.invocationCallOrder[0]);
});

it("approving says a company it has not read shows none of it, how far each kind has read, and how long the rest takes", async () => {
  vi.mocked(api.plugins).mockResolvedValue(pluginsFixture({
    plugins: [pluginFixture({ state: "needs_approval", active_slots: [], last_run: null })],
  }));
  vi.mocked(api.plugin).mockResolvedValue(pluginDetailFixture({
    slots: ["company.benefits", "pay.levels"], coverage: { "pay.levels": 7, "company.benefits": 21 }, companies: 1180,
    reading_left: { units: 1159, seconds_per_unit: 62, seconds: 76_000 },
  }));
  renderSection();
  await userEvent.click(await useSwitch());
  const gap = within(await screen.findByRole("dialog")).getByTestId("plugin-approval-gap");
  expect(gap).toHaveTextContent(msg("settings-plugins-section-approve-gap"));
  const slot = (word: string, n: number) => msg("settings-plugins-section-approve-slot", {
    slot: msg("settings-plugins-section-slot", { slot: word }),
    count: msg("shared-results-of-company", { n, t: 1180, total: 1180 }) });
  expect(gap).toHaveTextContent(msg("settings-plugins-section-approve-read", {
    slots: list([slot("company_benefits", 21), slot("pay_levels", 7)]) }));
  expect(gap).toHaveTextContent(msg("settings-plugins-section-approve-left", {
    duration: duration(21 * 3600), pace: duration(60) }));
});

it("a plugin that has read nothing and measured no pace says what it has read, and no time", async () => {
  vi.mocked(api.plugins).mockResolvedValue(pluginsFixture({
    plugins: [pluginFixture({ state: "needs_approval", active_slots: [], last_run: null })],
  }));
  vi.mocked(api.plugin).mockResolvedValue(pluginDetailFixture());
  renderSection();
  await userEvent.click(await useSwitch());
  const gap = within(await screen.findByRole("dialog")).getByTestId("plugin-approval-gap");
  expect(gap).toHaveTextContent(msg("shared-results-of-company", { n: 0, t: 120, total: 120 }));
  // The words before the time: absent, whatever the time would have been.
  const before = msg("settings-plugins-section-approve-left", { duration: "\u0000", pace: "\u0000" }).split("\u0000")[0];
  expect(gap).not.toHaveTextContent(before.replace(/[\u2068\u2069]/g, "").trim());
});

it("the approval quotes each site's rules and records the choice for those files", async () => {
  vi.mocked(api.plugins).mockResolvedValue(pluginsFixture({
    plugins: [pluginFixture({ state: "needs_approval", active_slots: [], last_run: null })],
  }));
  vi.mocked(api.plugin).mockResolvedValue(pluginDetailFixture());
  vi.mocked(api.pluginRobots).mockResolvedValue(pluginRobotsFixture());
  vi.mocked(api.approvePlugin).mockResolvedValue(action(pluginFixture({ state: "disabled" })));
  vi.mocked(api.enablePlugin).mockResolvedValue(action());
  renderSection();
  await userEvent.click(await useSwitch());
  const dialog = await screen.findByRole("dialog", { name: msg("settings-plugins-section-approve-title") });
  const site = await within(dialog).findByTestId("plugin-robots-site-data.example.com");
  expect(site).toHaveTextContent(msg("settings-plugins-section-robots-site", { state: "rules" }));
  expect(site).toHaveTextContent("/private/");
  expect(site).toHaveTextContent("/*?page=");
  const allow = within(dialog).getByRole("checkbox", { name: msg("settings-plugins-section-robots-allow") });
  expect(allow).not.toBeChecked();
  await userEvent.click(allow);
  await userEvent.click(within(dialog).getByRole("button", { name: msg("settings-plugins-section-approve-and-turn-on") }));
  expect(api.approvePlugin).toHaveBeenCalledWith("example-pay", "f0".repeat(32), { "data.example.com": "ab".repeat(32) });
});

it("cancelling the review approves and turns on nothing", async () => {
  vi.mocked(api.plugins).mockResolvedValue(pluginsFixture({
    plugins: [pluginFixture({ state: "needs_approval", active_slots: [], last_run: null })],
  }));
  vi.mocked(api.plugin).mockResolvedValue(pluginDetailFixture());
  renderSection();
  await userEvent.click(await useSwitch());
  const dialog = await screen.findByRole("dialog");
  await userEvent.click(within(dialog).getByRole("button", { name: msg("settings-cancel") }));
  expect(api.approvePlugin).not.toHaveBeenCalled();
  expect(api.enablePlugin).not.toHaveBeenCalled();
});

it("a stale approval says so in the reader's words and turns nothing on", async () => {
  vi.mocked(api.plugins).mockResolvedValue(pluginsFixture({
    plugins: [pluginFixture({ state: "needs_approval", active_slots: [], last_run: null })],
  }));
  vi.mocked(api.plugin).mockResolvedValue(pluginDetailFixture());
  vi.mocked(api.approvePlugin).mockRejectedValue(
    new ApiError("the plugin changed since it was shown", 409, "plugin-approval-stale", {}),
  );
  renderSection();
  await userEvent.click(await useSwitch());
  await userEvent.click(within(await screen.findByRole("dialog")).getByRole("button", {
    name: msg("settings-plugins-section-approve-and-turn-on") }));
  expect(await screen.findByRole("alert")).toHaveTextContent(msg("error-plugin-approval-stale"));
  expect(api.enablePlugin).not.toHaveBeenCalled();
});

it("Start that answers before its run exists shows the update at once, holds Start, and polls until the run shows", async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
  vi.mocked(api.refreshPlugin).mockResolvedValue({ started: true, job: "refresh", waiting: null });
  renderSection();
  const r = await row();
  await user.click(within(r).getByRole("button", { name: startName() }));
  expect(api.refreshPlugin).toHaveBeenCalledTimes(1);

  // The refetch right after still reads `running: false`: the row says it is updating anyway.
  await waitFor(() => expect(within(r).getByText(msg("settings-plugins-section-state", { state: "updating" }))).toBeVisible());
  expect(screen.getByTestId("plugin-facts-example-pay")).toHaveTextContent(
    msg("settings-plugin-settings-run", { outcome: "running", when: "" }),
  );
  const start = within(r).getByRole("button", { name: startName() });
  expect(start).toBeDisabled();
  await user.click(start);
  expect(api.refreshPlugin).toHaveBeenCalledTimes(1);

  // It polls meanwhile, so the run is seen when it appears.
  const before = vi.mocked(api.plugins).mock.calls.length;
  await act(async () => { await vi.advanceTimersByTimeAsync(3_100); });
  expect(vi.mocked(api.plugins).mock.calls.length).toBeGreaterThan(before);

  // A run that never shows up stops being claimed after the window.
  await act(async () => { await vi.advanceTimersByTimeAsync(START_WINDOW_MS); });
  await waitFor(() => expect(within(r).getByRole("button", { name: startName() })).toBeEnabled());
  expect(within(r).queryByText(msg("settings-plugins-section-state", { state: "updating" }))).toBeNull();
});

it("a Start ends its wait as soon as its run has come and gone", async () => {
  vi.mocked(api.refreshPlugin).mockResolvedValue({ started: true, job: "refresh", waiting: null });
  vi.mocked(api.plugins)
    .mockResolvedValueOnce(pluginsFixture())
    .mockResolvedValue(pluginsFixture({ plugins: [pluginFixture({
      last_run: { ...pluginFixture().last_run!, id: 13 } })] }));
  renderSection();
  const r = await row();
  await userEvent.click(within(r).getByRole("button", { name: startName() }));
  await waitFor(() => expect(within(r).getByRole("button", { name: startName() })).toBeEnabled());
  expect(within(r).queryByText(msg("settings-plugins-section-state", { state: "updating" }))).toBeNull();
});

it("Start updates now; on a maintenance wake it says when the update will start", async () => {
  vi.mocked(api.refreshPlugin).mockResolvedValue({ started: false, job: "refresh", waiting: "waiting_for_full_wake" });
  renderSection();
  await userEvent.click(within(await row()).getByRole("button", { name: startName() }));
  expect(api.refreshPlugin).toHaveBeenCalledWith("example-pay");
  expect(await screen.findByText(msg("settings-plugins-section-waiting-wake"))).toBeVisible();
});

it("Start waits for the plugin to be on, and says so on screen beside it, not in a tooltip", async () => {
  vi.mocked(api.plugins).mockResolvedValue(pluginsFixture({
    plugins: [pluginFixture({ state: "disabled", active_slots: [] })] }));
  renderSection();
  const r = await row();
  const start = within(r).getByRole("button", { name: startName() });
  expect(start).toBeDisabled();
  expect(within(r).getByText(msg("settings-plugins-section-turn-on-first"))).toBeVisible();
  expect(start).toHaveAccessibleDescription(msg("settings-plugins-section-turn-on-first"));
  expect(start).not.toHaveAttribute("title");
  // Off is what the switch says: no badge restates it.
  expect(within(r).queryByText(msg("settings-plugins-section-state", { state: "disabled" }))).toBeNull();
});

it("an update in flight shows its progress and holds Start; Pause is not a row verb", async () => {
  const running = pluginFixture({
    running: true,
    last_run: { ...pluginFixture().last_run!, outcome: "running", ended_at: null, progress_done: 12, progress_total: 96 },
  });
  vi.mocked(api.plugins).mockResolvedValue(pluginsFixture({ plugins: [running] }));
  renderSection();
  const r = await row();
  expect(screen.getByTestId("plugin-facts-example-pay")).toHaveTextContent(
    msg("settings-plugin-settings-run-progress", {
      outcome: "running", when: "", read: msg("shared-results-of-company", { n: 12, t: 96, total: 96 }) }),
  );
  expect(within(r).getByText(msg("settings-plugins-section-state", { state: "updating" }))).toBeVisible();
  // Start stays where it was, waiting; nothing takes its place.
  expect(within(r).getByRole("button", { name: startName() })).toBeDisabled();
  expect(within(r).queryByRole("button", { name: msg("settings-plugins-section-pause") })).toBeNull();
});

it("a paused plugin says so and plans no next update", async () => {
  vi.mocked(api.plugins).mockResolvedValue(pluginsFixture({
    plugins: [pluginFixture({ paused: true, paused_at: "2026-07-13T08:00:00Z", next_update_at: null })] }));
  renderSection();
  const r = await row();
  // Said once, in the update line; the badge does not repeat it.
  expect(within(r).queryByText(msg("settings-plugins-section-state", { state: "paused" }))).toBeNull();
  expect(screen.getByTestId("plugin-facts-example-pay")).toHaveTextContent(msg("settings-plugins-section-paused"));
  expect(screen.getByTestId("plugin-facts-example-pay")).not.toHaveTextContent("next update");
});

it("an uninstalled plugin keeps a row, its switch locked, and its settings open for removing its data", async () => {
  vi.mocked(api.plugins).mockResolvedValue(pluginsFixture({
    plugins: [pluginFixture({ state: "removed", active_slots: [], next_update_at: null })] }));
  renderSection();
  const r = await row();
  expect(await useSwitch()).toBeDisabled();
  expect(within(r).queryByRole("button", { name: startName() })).toBeNull();
  expect(within(r).getByText(msg("settings-plugins-section-state", { state: "removed" }))).toBeVisible();
  expect(screen.queryByText(msg("settings-plugins-section-on-count", { on: 0, total: 0 }))).toBeNull();
});

it("the gear opens that plugin's own settings", async () => {
  renderSection();
  await userEvent.click(await screen.findByRole("button", {
    name: msg("settings-plugins-section-open-settings", { name: "Example pay data" }) }));
  expect(await screen.findByTestId("where")).toHaveTextContent("/settings/plugins/example-pay");
});

it("estimates moving shows how many roles are still to go", async () => {
  vi.mocked(api.plugins).mockResolvedValue(pluginsFixture({
    reference: referenceFixture({ target_fp: "b2".repeat(32), pending_jobs: 380 }),
  }));
  renderSection();
  expect(await screen.findByText(msg("settings-plugins-section-pending", { pending: 380 }))).toBeVisible();
});

it("a reference change seen by the status poll refetches the list", async () => {
  const { rerender } = renderSection();
  await row();
  expect(api.plugins).toHaveBeenCalledTimes(1);
  epoch.referenceVersion = 1;
  rerender(
    <MemoryRouter initialEntries={["/settings/plugins"]}>
      <Routes><Route path="/settings/plugins" element={<PluginsSection />} /></Routes>
    </MemoryRouter>,
  );
  await waitFor(() => expect(api.plugins).toHaveBeenCalledTimes(2));
});

it("a mount after estimates already moved fetches once: only a change refetches", async () => {
  epoch.referenceVersion = 3;
  renderSection();
  await row();
  await new Promise((resolve) => setTimeout(resolve, 20));
  expect(api.plugins).toHaveBeenCalledTimes(1);
});

it("an update that lapsed the approval of a plugin left on: switch on, waiting, and off needs no approval", async () => {
  vi.mocked(api.plugins)
    .mockResolvedValueOnce(pluginsFixture({ plugins: [pluginLapsedFixture()] }))
    .mockResolvedValue(pluginsFixture({ plugins: [pluginLapsedFixture({ enabled: false })] }));
  vi.mocked(api.disablePlugin).mockResolvedValue(action(pluginLapsedFixture({ enabled: false })));
  renderSection();
  const r = await row();
  expect(await useSwitch()).toBeChecked();
  expect(within(r).getByText(msg("settings-plugins-section-state", { state: "needs_approval" }))).toBeVisible();
  const start = within(r).getByRole("button", { name: startName() });
  expect(start).toBeDisabled();
  // Why it waits is the badge beside it, read with the button.
  expect(start).toHaveAccessibleDescription(msg("settings-plugins-section-state", { state: "needs_approval" }));
  expect(start).not.toHaveAttribute("title");

  await userEvent.click(await useSwitch());
  expect(api.disablePlugin).toHaveBeenCalledWith("example-pay");
  expect(api.plugin).not.toHaveBeenCalled();
  expect(api.approvePlugin).not.toHaveBeenCalled();
  await waitFor(async () => expect(await useSwitch()).not.toBeChecked());
});

it("a write shows the row the server answered with before the refetch lands, and holds the row until it does", async () => {
  vi.mocked(api.plugins)
    .mockResolvedValueOnce(pluginsFixture())
    .mockReturnValue(new Promise(() => {}));
  vi.mocked(api.disablePlugin).mockResolvedValue(action(pluginFixture({ state: "disabled", active_slots: [] })));
  renderSection();
  await userEvent.click(await useSwitch());
  await waitFor(async () => expect(await useSwitch()).not.toBeChecked());
  // The refetch has not landed: the row is still busy.
  expect(await useSwitch()).toBeDisabled();
});

it("a failed write says which plugin and which step, in that plugin's row, and still refetches", async () => {
  vi.mocked(api.plugins).mockResolvedValue(pluginsFixture({ plugins: [pluginFixture(), reports] }));
  vi.mocked(api.disablePlugin).mockRejectedValue(new ApiError("boom", 500, undefined, {}));
  renderSection();
  await row("acme-reports");
  await userEvent.click(await useSwitch("Acme pay reports"));
  const alert = await rowAlert("acme-reports");
  expect(alert).toHaveTextContent(msg("settings-plugins-section-failed", { action: "off" }));
  expect(screen.getAllByRole("alert")).toHaveLength(1);
  expect(screen.getByTestId("plugin-row-example-pay").nextElementSibling)
    .toBe(screen.getByTestId("plugin-row-acme-reports"));
  await waitFor(() => expect(api.plugins).toHaveBeenCalledTimes(2));
});

it("reading what approval shows can fail, and says so as that, not as an approval", async () => {
  vi.mocked(api.plugins).mockResolvedValue(pluginsFixture({
    plugins: [pluginFixture({ state: "needs_approval", active_slots: [], last_run: null })],
  }));
  vi.mocked(api.plugin).mockRejectedValue(new ApiError("boom", 500, undefined, {}));
  renderSection();
  await userEvent.click(await useSwitch());
  const alert = await rowAlert();
  expect(alert).toHaveTextContent(msg("settings-plugins-section-failed", { action: "review" }));
  expect(alert).not.toHaveTextContent(msg("settings-plugins-section-failed", { action: "approve" }));
});

it("approved but not turned on says that the approval held and the turning on failed", async () => {
  vi.mocked(api.plugins).mockResolvedValue(pluginsFixture({
    plugins: [pluginFixture({ state: "needs_approval", active_slots: [], last_run: null })],
  }));
  vi.mocked(api.plugin).mockResolvedValue(pluginDetailFixture());
  vi.mocked(api.approvePlugin).mockResolvedValue(action(pluginFixture({ state: "disabled" })));
  vi.mocked(api.enablePlugin).mockRejectedValue(new ApiError("boom", 500, undefined, {}));
  renderSection();
  await userEvent.click(await useSwitch());
  await userEvent.click(within(await screen.findByRole("dialog")).getByRole("button", {
    name: msg("settings-plugins-section-approve-and-turn-on") }));
  expect(await rowAlert()).toHaveTextContent(
    msg("settings-plugins-section-failed", { action: "on_after_approve" }),
  );
});

it("the approval shows everything approving allows: version, code, facts and their trust, older rows, how it visits, what it receives", async () => {
  vi.mocked(api.plugins).mockResolvedValue(pluginsFixture({
    plugins: [pluginFixture({ state: "needs_approval", active_slots: [], last_run: null })],
  }));
  const detail = pluginDetailFixture();
  vi.mocked(api.plugin).mockResolvedValue({
    ...detail,
    approval: {
      ...detail.approval,
      slots: ["pay.levels", "company.facts"],
      fact_fields: ["headcount"],
      fact_rank: 40,
    },
  });
  renderSection();
  await userEvent.click(await useSwitch());
  const dialog = await screen.findByRole("dialog", { name: msg("settings-plugins-section-approve-title") });
  expect(within(dialog).getByTestId("plugin-approval-version")).toHaveTextContent("0.3.1");
  expect(within(dialog).getByText("https://github.com/example/example-pay")).toBeVisible();
  const facts = within(dialog).getByTestId("plugin-approval-facts");
  expect(facts).toHaveTextContent(msg("settings-plugins-section-fact-field", { field: "headcount" }));
  // Never mixed with ours: the dialog says they replace, never sit beside.
  expect(facts).toHaveTextContent(msg("settings-plugins-section-approve-fact-rank"));
  expect(within(dialog).queryByTestId("plugin-approval-legacy")).toBeNull();
  expect(dialog).toHaveTextContent(msg("settings-plugins-section-approve-identity", { identity: "identified" }));
  expect(within(dialog).getByTestId("plugin-approval-needs")).toHaveTextContent(
    msg("settings-plugins-section-approve-needs", { need: "followed_companies" }),
  );
});

it("an unknown identity or need is said neutrally, never as a known one", async () => {
  expect(msg("settings-plugins-section-approve-identity", { identity: "something_new" }))
    .not.toBe(msg("settings-plugins-section-approve-identity", { identity: "identified" }));
  expect(msg("settings-plugins-section-approve-needs", { need: "saved_roles" }))
    .not.toBe(msg("settings-plugins-section-approve-needs", { need: "followed_companies" }));
});

it("each row's Start is named by its plugin for a screen reader, and still reads Start", async () => {
  vi.mocked(api.plugins).mockResolvedValue(pluginsFixture({ plugins: [pluginFixture(), reports] }));
  renderSection();
  await row("acme-reports");
  const starts = screen.getAllByRole("button", { name: new RegExp(`^${msg("settings-plugins-section-start")}`) });
  expect(starts.map((b) => b.getAttribute("aria-label"))).toEqual([startName(), startName("Acme pay reports")]);
  for (const b of starts) expect(b).toHaveTextContent(new RegExp(`^${msg("settings-plugins-section-start")}$`));
  // The name leads with the word on screen (label in name), and no two are alike.
  expect(new Set(starts.map((b) => b.getAttribute("aria-label"))).size).toBe(2);
  expect(within(await row("acme-reports")).getByRole("button", { name: startName("Acme pay reports") })).toBeEnabled();
});

it("what estimates did is said under the intro, above the search and the list", async () => {
  renderSection();
  await row();
  const note = screen.getByRole("note");
  expect(note).toHaveTextContent("Estimates changed for 44 roles at 6 companies");
  const search = screen.getByRole("searchbox", { name: msg("settings-plugins-section-search") });
  // DOCUMENT_POSITION_FOLLOWING: the search, and the first row, come after it.
  expect(note.compareDocumentPosition(search) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  expect(note.compareDocumentPosition(screen.getByTestId("plugin-row-example-pay")) & Node.DOCUMENT_POSITION_FOLLOWING)
    .toBeTruthy();
  expect(note.compareDocumentPosition(screen.getByText(msg("settings-plugins-section-more"))) & Node.DOCUMENT_POSITION_FOLLOWING)
    .toBeTruthy();
});

it("a row says how many companies its own data answers for, and how far a short update got", async () => {
  vi.mocked(api.plugins).mockResolvedValue(pluginsFixture({ plugins: [pluginFixture(), pluginAdoptingFixture()] }));
  renderSection();
  await row("example-ladder");
  // Pay by level for 96 companies and benefits for 81: the row says 96, never 177.
  const facts = screen.getByTestId("plugin-facts-example-pay");
  expect(facts).toHaveTextContent(msg("settings-plugins-section-read", { read: 96, companies: 120 }));
  expect(facts).not.toHaveTextContent("177");
  // Stopped partway through a pass over 1,180 companies: when, and after how many.
  const ladder = screen.getByTestId("plugin-facts-example-ladder");
  const stopped = pluginAdoptingFixture().last_run!;
  expect(ladder).toHaveTextContent(msg("settings-plugin-settings-run-progress", {
    outcome: "stopped", when: ago(stopped.ended_at!), read: msg("shared-results-of-company", { n: 4, t: 1180, total: 1180 }),
  }));
  expect(ladder).toHaveTextContent(msg("settings-plugins-section-read", { read: 4, companies: 1180 }));
});

it("an update that continues says how far it got and that it carries on, with no next date beside it", async () => {
  const run = pluginRunContinuingFixture();
  vi.mocked(api.plugins).mockResolvedValue(pluginsFixture({ plugins: [pluginFixture({ last_run: run })] }));
  renderSection();
  await row();
  const facts = screen.getByTestId("plugin-facts-example-pay");
  expect(facts).toHaveTextContent(msg("settings-plugin-settings-run-progress", {
    outcome: "continues", when: ago(run.ended_at!), read: msg("shared-results-of-company", { n: 300, t: 1180, total: 1180 }),
  }));
  expect(facts).not.toHaveTextContent("next update");
});

it("More plugins says how to install one: the command as code to copy, and no install control", async () => {
  vi.mocked(api.plugins).mockResolvedValue(pluginsFixture({ plugins: [] }));
  renderSection();
  const command = await screen.findByText(/scripts\.plugin install/);
  expect(command.tagName).toBe("PRE");
  expect(command).toHaveAttribute("data-copy", "code");
  expect(command).toHaveTextContent(/^cd backend && \.venv\/bin\/python -m scripts\.plugin install <plugin-folder>$/);
  expect(screen.getByText(msg("settings-plugins-section-more-note"))).toBeVisible();
  expect(screen.queryByRole("button")).toBeNull();
});

it("with plugins not available yet a Coming soon sign stands for the list, and More plugins stays as it is", async () => {
  // The API lists none while the gate is off, even with plugins installed; a
  // listed plugin here would be a server that ignored its own gate.
  vi.mocked(api.plugins).mockResolvedValue(pluginsFixture({ available: false, plugins: [pluginLapsedFixture()] }));
  renderSection();
  const soon = await screen.findByTestId("plugins-coming-soon");
  expect(within(soon).getByText(msg("settings-plugins-section-coming-soon"))).toBeVisible();
  expect(within(soon).getByText(msg("settings-plugins-section-coming-soon-note"))).toBeVisible();
  // No plugin, its approval state, its controls, the search or the count.
  expect(screen.queryByTestId(/^plugin-row-/)).toBeNull();
  expect(screen.queryByText(msg("settings-plugins-section-state", { state: "needs_approval" }))).toBeNull();
  expect(screen.queryByText(msg("settings-plugins-section-none"))).toBeNull();
  expect(screen.queryByRole("searchbox")).toBeNull();
  expect(screen.queryByRole("checkbox")).toBeNull();
  expect(screen.queryByRole("button")).toBeNull();
  expect(screen.queryByText(/ of \d+ on$/)).toBeNull();
  expect(screen.queryByRole("note")).toBeNull();
  // More plugins and the command, unchanged and after the sign.
  const more = screen.getByText(msg("settings-plugins-section-more"));
  expect(soon.compareDocumentPosition(more) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  expect(screen.getByText(msg("settings-plugins-section-more-note"))).toBeVisible();
  expect(screen.getByText(/scripts\.plugin install/)).toHaveTextContent(
    /^cd backend && \.venv\/bin\/python -m scripts\.plugin install <plugin-folder>$/);
});

it("with plugins available there is no Coming soon sign", async () => {
  renderSection();
  await row();
  expect(screen.queryByTestId("plugins-coming-soon")).toBeNull();
  expect(screen.getByRole("searchbox")).toBeVisible();
});

it("a row shows what the plugin does and what its last update did in the plugin's own words", async () => {
  const run = pluginRunStoppedFixture({ summary: "Read pay for 56 of 1,180 companies" });
  vi.mocked(api.plugins).mockResolvedValue(pluginsFixture({ plugins: [pluginFixture({
    name: "Ladder pay", description: "Pay by level and benefits from ladder.example", last_run: run,
  })] }));
  renderSection();
  await row();
  const answers = screen.getByTestId("plugin-answers-example-pay");
  expect(answers).toHaveTextContent(/^Pay by level and benefits from ladder\.example$/);
  // Third-party text: shown as written, never translated.
  expect(within(answers).getByText("Pay by level and benefits from ladder.example")).toHaveAttribute("translate", "no");
  const facts = screen.getByTestId("plugin-facts-example-pay");
  const ended = msg("settings-plugin-settings-run", { outcome: "stopped", when: ago(run.ended_at!) });
  expect(facts).toHaveTextContent(`${ended}: Read pay for 56 of 1,180 companies`);
  expect(within(facts).getByText("Read pay for 56 of 1,180 companies")).toHaveAttribute("translate", "no");
  // The plugin's account replaces RoleBand's count of what the run read, never doubles it.
  expect(facts).not.toHaveTextContent(msg("shared-results-of-company", { n: 4, t: 1180, total: 1180 }));
  expect(screen.getByRole("checkbox", { name: msg("settings-plugins-section-use", { name: "Ladder pay" }) })).toBeVisible();
});

it("a plugin that says nothing of itself keeps RoleBand's words for what it brings and how far it got", async () => {
  const run = pluginRunStoppedFixture();
  vi.mocked(api.plugins).mockResolvedValue(pluginsFixture({ plugins: [pluginFixture({ last_run: run })] }));
  renderSection();
  await row();
  expect(screen.getByTestId("plugin-answers-example-pay")).toHaveTextContent(
    msg("settings-plugins-section-answers", { slots: "benefits and comp bands" }),
  );
  expect(screen.getByTestId("plugin-facts-example-pay")).toHaveTextContent(msg("settings-plugin-settings-run-progress", {
    outcome: "stopped", when: ago(run.ended_at!), read: msg("shared-results-of-company", { n: 4, t: 1180, total: 1180 }),
  }));
});
