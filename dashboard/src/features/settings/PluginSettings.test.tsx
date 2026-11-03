import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";
import { ApiError, PluginDetail, api } from "../../api";
import { resetWriteQueues } from "../../hooks/useWriteQueue";
import {
  pluginAdoptingFixture, pluginDetailFixture, pluginFixture, pluginLapsedFixture, pluginRobotsFixture,
  pluginRunContinuingFixture, pluginRunErroredFixture, pluginRunFixture, pluginRunStoppedFixture,
} from "../../test/fixtures";
import { msg } from "../../test/msg";
import { PluginSettings } from "./PluginSettings";
import { duration } from "../../copy/format";
import { ago } from "./pluginWords";

/* One plugin's settings: its own card first (named by the
   plugin, its switch left of "Use {plugin}", approval asked for there), how
   often it updates and when next, Start with Pause / Resume beside it (one
   meaning: hold updates), what it brings and for how many companies, its
   recent updates, Remove data (only while off, typed) and Uninstall (keeps its
   data). */

const epoch = vi.hoisted(() => ({ referenceVersion: 0, notificationVersion: 0 }));
// The status poll a plugin decision asks for at once.
const poll = vi.hoisted(() => vi.fn(async () => {}));

vi.mock("../../context/SyncState", () => ({ useSyncEpoch: () => epoch, useStatusPoll: () => poll }));
vi.mock("../../api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../api")>();
  return {
    ...actual,
    api: {
      plugin: vi.fn(),
      approvePlugin: vi.fn(),
      pluginRobots: vi.fn(async () => ({ sites: [], consent: null, consent_at: null })),
      setPluginRobots: vi.fn(),
      enablePlugin: vi.fn(),
      disablePlugin: vi.fn(),
      refreshPlugin: vi.fn(),
      pausePlugin: vi.fn(),
      resumePlugin: vi.fn(),
      setPluginSchedule: vi.fn(),
      uninstallPlugin: vi.fn(),
      removePluginData: vi.fn(),
    },
  };
});

/** The installed, approved, enabled plugin with two updates behind it; its
 *  switch follows an overridden `state`, as `pluginFixture` does. */
function enabled(overrides: Partial<PluginDetail> = {}): PluginDetail {
  const view = pluginFixture(overrides.state ? { state: overrides.state } : {});
  return pluginDetailFixture({
    ...view,
    runs: [
      view.last_run!,
      { ...view.last_run!, id: 11, outcome: "partial", published: { "pay.levels": 40 } },
    ],
    ...overrides,
  });
}

const action = () => ({ plugin: pluginFixture(), reestimate_started: false, stopped: [] });

function Where() {
  return <span data-testid="where">{useLocation().pathname}</span>;
}

function renderScreen(id = "example-pay") {
  return render(
    <MemoryRouter initialEntries={[`/settings/plugins/${id}`]}>
      <Routes>
        <Route path="/settings/plugins/:pluginId" element={<PluginSettings pluginId={id} />} />
        <Route path="*" element={<Where />} />
      </Routes>
    </MemoryRouter>,
  );
}

const heading = () => screen.findByRole("heading", { name: "Example pay data" });

beforeEach(() => {
  vi.clearAllMocks();
  resetWriteQueues();
  vi.mocked(api.plugin).mockResolvedValue(enabled());
});

it("while the plugin loads it says so in one whole sentence, never \"Loading Loading\"", async () => {
  vi.mocked(api.plugin).mockReturnValue(new Promise(() => {}));
  renderScreen();
  const status = await screen.findByRole("status");
  expect(status).toHaveTextContent(msg("settings-plugin-settings-loading"));
  expect(status).not.toHaveTextContent(/Loading Loading/);
});

it("Updates: on the plugin's own schedule it says what the plugin suggests, when it updates next and last", async () => {
  renderScreen();
  await heading();
  const group = screen.getByRole("group", { name: msg("settings-plugin-settings-how-often") });
  expect(within(group).getByRole("button", { name: msg("settings-plugin-settings-option", { schedule: "weekly" }) }))
    .toHaveAttribute("aria-pressed", "true");
  expect(screen.getByText(msg("settings-plugin-settings-suggests", { schedule: "weekly" }))).toBeVisible();
  expect(screen.getByTestId("plugin-next-update")).toHaveTextContent(/19 Jul|Jul 19/);
});

it("choosing how often writes the plugin's schedule", async () => {
  vi.mocked(api.setPluginSchedule).mockResolvedValue(action());
  renderScreen();
  await heading();
  await userEvent.click(screen.getByRole("button", { name: msg("settings-plugin-settings-option", { schedule: "daily" }) }));
  expect(api.setPluginSchedule).toHaveBeenCalledWith("example-pay", "daily");
  await waitFor(() => expect(api.plugin).toHaveBeenCalledTimes(2));
});

it("the person's schedule replaces the plugin's; when you ask means no update is planned", async () => {
  vi.mocked(api.plugin).mockResolvedValue(enabled({
    schedule: "manual", next_update_at: null,
    jobs: [{ name: "refresh", schedule: "manual", manifest_schedule: "weekly", budget_seconds: 1800 }],
  }));
  renderScreen();
  await heading();
  expect(screen.getByRole("button", { name: msg("settings-plugin-settings-option", { schedule: "manual" }) }))
    .toHaveAttribute("aria-pressed", "true");
  expect(screen.getByTestId("plugin-next-update")).toHaveTextContent(
    msg("settings-plugin-settings-next-value", { state: "manual", when: "" }),
  );
  // Nothing starts on its own, so there is nothing to pause; Start still works.
  expect(screen.queryByRole("button", { name: msg("settings-plugins-section-pause") })).toBeNull();
  expect(screen.getByRole("button", { name: msg("settings-plugins-section-start") })).toBeEnabled();
});

it("when you ask: Pause comes back while an update runs, because it stops that update", async () => {
  vi.mocked(api.pausePlugin).mockResolvedValue(action());
  vi.mocked(api.plugin).mockResolvedValue(enabled({
    schedule: "manual", next_update_at: null, running: true,
    jobs: [{ name: "refresh", schedule: "manual", manifest_schedule: "weekly", budget_seconds: 1800 }],
    last_run: { ...pluginFixture().last_run!, outcome: "running", ended_at: null, progress_done: 3, progress_total: 96 },
  }));
  renderScreen();
  await heading();
  await userEvent.click(within(screen.getByTestId("plugin-next-update")).getByRole("button", { name: msg("settings-plugins-section-pause") }));
  expect(api.pausePlugin).toHaveBeenCalledWith("example-pay");
});

it("Pause holds updates; a paused plugin says so and Resume releases it", async () => {
  vi.mocked(api.pausePlugin).mockResolvedValue(action());
  vi.mocked(api.resumePlugin).mockResolvedValue(action());
  const { unmount } = renderScreen();
  await heading();
  await userEvent.click(screen.getByRole("button", { name: msg("settings-plugins-section-pause") }));
  expect(api.pausePlugin).toHaveBeenCalledWith("example-pay");
  unmount();

  vi.mocked(api.plugin).mockResolvedValue(enabled({ paused: true, paused_at: "2026-07-13T08:00:00Z", next_update_at: null }));
  renderScreen();
  await heading();
  expect(screen.getByTestId("plugin-next-update")).toHaveTextContent(
    msg("settings-plugin-settings-next-value", { state: "paused", when: "" }),
  );
  expect(screen.queryByRole("button", { name: msg("settings-plugins-section-pause") })).toBeNull();
  await userEvent.click(screen.getByRole("button", { name: msg("settings-plugins-section-resume") }));
  expect(api.resumePlugin).toHaveBeenCalledWith("example-pay");
});

it("the plugin's own card names it, with its switch left of the words it governs and no badge restating it", async () => {
  renderScreen();
  const card = await screen.findByRole("region", { name: "Example pay data" });
  const toggle = within(card).getByRole("checkbox", { name: msg("settings-plugins-section-use", { name: "Example pay data" }) });
  expect(toggle).toBeChecked();
  // The switch's words are on screen beside it, not only in its accessible name.
  const label = toggle.closest("label") as HTMLElement;
  expect(label).toHaveTextContent(msg("settings-plugins-section-use", { name: "Example pay data" }));
  expect(within(card).queryByText(msg("settings-plugins-section-state", { state: "enabled" }))).toBeNull();
});

it("Pause means one thing: while an update runs, Start waits and Pause stops it and holds the rest", async () => {
  vi.mocked(api.plugin).mockResolvedValue(enabled({
    running: true,
    last_run: { ...pluginFixture().last_run!, outcome: "running", ended_at: null, progress_done: 3, progress_total: 96 },
  }));
  vi.mocked(api.pausePlugin).mockResolvedValue(action());
  renderScreen();
  await heading();
  expect(screen.getByRole("button", { name: msg("settings-plugins-section-start") })).toBeDisabled();
  expect(screen.getAllByRole("button", { name: msg("settings-plugins-section-pause") })).toHaveLength(1);
  await userEvent.click(screen.getByRole("button", { name: msg("settings-plugins-section-pause") }));
  expect(api.pausePlugin).toHaveBeenCalledWith("example-pay");
});

it("Start that cannot run says why on screen beside it", async () => {
  vi.mocked(api.plugin).mockResolvedValue(enabled({ state: "disabled", active_slots: [] }));
  renderScreen();
  await heading();
  const start = screen.getByRole("button", { name: msg("settings-plugins-section-start") });
  expect(start).toBeDisabled();
  expect(start).toHaveAccessibleDescription(msg("settings-plugins-section-turn-on-first"));
  expect(screen.getByText(msg("settings-plugins-section-turn-on-first"))).toBeVisible();
  expect(start).not.toHaveAttribute("title");
});

it("the two irreversible acts wear the same rank: neither carries an icon the other lacks", async () => {
  renderScreen();
  await heading();
  const remove = screen.getByRole("button", { name: msg("settings-plugins-section-remove") });
  const uninstall = screen.getByRole("button", { name: msg("settings-plugin-settings-uninstall") });
  expect(remove.querySelectorAll("svg")).toHaveLength(uninstall.querySelectorAll("svg").length);
  expect(remove.className).toBe(uninstall.className);
});

it("Start updates now", async () => {
  vi.mocked(api.refreshPlugin).mockResolvedValue({ started: true, job: "refresh", waiting: null });
  renderScreen();
  await heading();
  await userEvent.click(screen.getByRole("button", { name: msg("settings-plugins-section-start") }));
  expect(api.refreshPlugin).toHaveBeenCalledWith("example-pay");
});

it("What it brings counts the followed companies each kind has read, says what the rest show, and names the sites it reads and its credit", async () => {
  renderScreen();
  await heading();
  const pay = screen.getByTestId("plugin-slot-pay.levels");
  expect(pay).toHaveTextContent(msg("settings-plugins-section-read", { read: 96, companies: 120 }));
  // It answers app-wide, so a company it has not read shows no estimate, not ours.
  expect(pay).toHaveTextContent(msg("settings-plugin-settings-slot-gap", {
    read: 96, left: 24, none: msg("settings-plugin-settings-slot-none", { slot: "pay_levels" }) }));
  expect(screen.getByTestId("plugin-slot-company.benefits")).toHaveTextContent(
    msg("settings-plugins-section-read", { read: 81, companies: 120 }),
  );
  // No pass under way: nothing to say about time.
  expect(screen.queryByTestId("plugin-left")).toBeNull();
  // Nothing about rows RoleBand read before plugins: a plugin answers from its own.
  expect(screen.getByTestId("plugin-slot-pay.levels")).not.toHaveTextContent("before it was a plugin");
  expect(screen.getByText("Pay data courtesy of Example")).toBeVisible();
  expect(screen.getByText("data.example.com")).toBeVisible();
});

it("a kind no update has read a company of yet answers nothing yet, even beside a kind that has", async () => {
  vi.mocked(api.plugin).mockResolvedValue(pluginDetailFixture({ ...pluginAdoptingFixture(), runs: [] }));
  renderScreen("example-ladder");
  await screen.findByRole("heading", { name: "Example ladder data" });
  expect(screen.getByTestId("plugin-slot-pay.levels")).toHaveTextContent(
    msg("settings-plugins-section-read", { read: 4, companies: 1180 }));
  const benefits = screen.getByTestId("plugin-slot-company.benefits");
  expect(benefits).toHaveTextContent(msg("settings-plugins-section-read", { read: 0, companies: 1180 }));
  // 76,000s left at 62s a company: whole hours and minutes, as a person says them.
  expect(screen.getByTestId("plugin-left")).toHaveTextContent(
    msg("settings-plugin-settings-left-value", { duration: duration(21 * 3600), pace: duration(60) }));
});

it("a kind it answers before reading any company says every company shows none of it until read", async () => {
  vi.mocked(api.plugin).mockResolvedValue(enabled({ coverage: {} }));
  renderScreen();
  await heading();
  const benefits = screen.getByTestId("plugin-slot-company.benefits");
  expect(benefits).toHaveTextContent(msg("settings-plugins-section-read", { read: 0, companies: 120 }));
  expect(benefits).toHaveTextContent(msg("settings-plugin-settings-slot-gap", {
    read: 0, left: 120, none: msg("settings-plugin-settings-slot-none", { slot: "company_benefits" }) }));
});

it("a plugin that is off or waits for approval says its data is not used, whatever it published", async () => {
  vi.mocked(api.plugin).mockResolvedValue(enabled({ state: "disabled", active_slots: [] }));
  const { unmount } = renderScreen();
  await heading();
  const pay = screen.getByTestId("plugin-slot-pay.levels");
  expect(pay).toHaveTextContent(msg("settings-plugin-settings-slot-state", { state: "off" }));
  // What it would answer with once on, never what a company shows now: ours answers.
  expect(pay).toHaveTextContent(msg("settings-plugins-section-read", { read: 96, companies: 120 }));
  expect(pay).not.toHaveTextContent(msg("settings-plugin-settings-slot-none", { slot: "pay_levels" }));
  unmount();
  vi.mocked(api.plugin).mockResolvedValue(pluginDetailFixture({ ...pluginLapsedFixture(), runs: [] }));
  renderScreen();
  await heading();
  expect(screen.getByTestId("plugin-slot-pay.levels")).toHaveTextContent(
    msg("settings-plugin-settings-slot-state", { state: "approval" }));
});

it("the credit is labelled Credit, so a credit that begins with its own label never reads as one word twice", async () => {
  vi.mocked(api.plugin).mockResolvedValue(pluginDetailFixture({ ...pluginAdoptingFixture(), runs: [] }));
  renderScreen("example-ladder");
  await screen.findByRole("heading", { name: "Example ladder data" });
  const credit = screen.getByText("Data source: Example ladder (https://ladder.example)");
  const label = credit.closest("div")!.querySelector("dt")!;
  expect(label).toHaveTextContent(msg("settings-plugins-section-credit"));
  expect(label.textContent).not.toMatch(/data/i);
});

it("Recent updates: each update at its own time, how it ended and how many companies it read, rows beside it", async () => {
  // Three updates one afternoon: "3 hours ago" three times would tell them apart by nothing.
  const runs = [pluginRunStoppedFixture(), pluginRunErroredFixture(), pluginRunContinuingFixture({
    started_at: "2026-07-12T15:05:00Z", ended_at: "2026-07-12T15:09:00Z" })];
  vi.mocked(api.plugin).mockResolvedValue(enabled({ last_run: runs[0], runs }));
  renderScreen();
  await heading();
  const items = within(history()).getAllByRole("listitem");
  expect(items).toHaveLength(3);
  const times = items.map((item) => item.querySelector("time")!);
  expect(times.map((t) => t.getAttribute("datetime"))).toEqual(runs.map((run) => run.started_at));
  for (const t of times) expect(t.textContent).toMatch(/\d{1,2}[:.]\d{2}/);
  expect(new Set(times.map((t) => t.textContent)).size).toBe(3);

  const [stopped, errored, continuing] = items;
  expect(stopped).toHaveTextContent(msg("settings-plugin-settings-outcome", { outcome: "stopped" }));
  expect(stopped).toHaveTextContent(msg("shared-results-of-company", { n: 4, t: 1180, total: 1180 }));
  expect(stopped).toHaveTextContent(msg("settings-plugin-settings-published", { rows: 32 }));
  expect(errored).toHaveTextContent(msg("settings-plugin-settings-outcome", { outcome: "error" }));
  expect(continuing).toHaveTextContent(msg("settings-plugin-settings-outcome", { outcome: "continues" }));
  expect(continuing).toHaveTextContent(msg("shared-results-of-company", { n: 300, t: 1180, total: 1180 }));
  // Each says its time, never "x hours ago".
  for (const item of items) expect(item).not.toHaveTextContent(ago(runs[0].ended_at!));
});

it("two updates in one minute (a Pause, then Start at once) are told apart by their seconds; others keep the minute", async () => {
  const runs = [
    pluginRunFixture({ id: 31, started_at: "2026-07-12T15:28:41Z", ended_at: "2026-07-12T15:28:59Z" }),
    pluginRunStoppedFixture({ id: 30, started_at: "2026-07-12T15:28:03Z", ended_at: "2026-07-12T15:28:20Z" }),
    pluginRunStoppedFixture({ id: 29, started_at: "2026-07-12T15:05:00Z", ended_at: "2026-07-12T15:09:00Z" }),
  ];
  vi.mocked(api.plugin).mockResolvedValue(enabled({ last_run: runs[0], runs }));
  renderScreen();
  await heading();
  const times = within(history()).getAllByRole("listitem").map((item) => item.querySelector("time")!.textContent!);
  expect(new Set(times).size).toBe(3);
  // The two in one minute carry their seconds; a minute no other update shares does not.
  expect(times[0].length).toBeGreaterThan(times[2].length);
  expect(times[1].length).toBeGreaterThan(times[2].length);
});

it("an errored update shows its own words, as written; a stopped one's words, which restate it, are not repeated", async () => {
  const runs = [pluginRunErroredFixture(), pluginRunStoppedFixture(), pluginRunContinuingFixture({
    outcome: "partial", continues: false, message: "2 companies answered nothing readable" })];
  vi.mocked(api.plugin).mockResolvedValue(enabled({ last_run: runs[0], runs }));
  renderScreen();
  await heading();
  const [errored, stopped, partial] = within(history()).getAllByRole("listitem");
  const words = within(errored).getByText(runs[0].message!);
  expect(words).toHaveAttribute("data-copy", "diagnostic");
  expect(words).toHaveAttribute("translate", "no");
  expect(within(partial).getByText("2 companies answered nothing readable")).toBeVisible();
  expect(within(stopped).queryByText("the run is stopped")).toBeNull();
});

it("Remove data waits until the plugin is off, then removes only after its id is typed", async () => {
  renderScreen();
  await heading();
  expect(screen.getByRole("button", { name: msg("settings-plugins-section-remove") })).toBeDisabled();
});

it("an off plugin's data is removed after its id is typed, and the rows it added are reported", async () => {
  vi.mocked(api.plugin).mockResolvedValue(enabled({ state: "disabled", active_slots: [] }));
  vi.mocked(api.removePluginData).mockResolvedValue({
    deleted: { company_comp_level: 2804, company_benefit: 1120, plugin_coverage: 96 }, reestimate_started: true,
  });
  renderScreen();
  await heading();
  await userEvent.click(screen.getByRole("button", { name: msg("settings-plugins-section-remove") }));
  const dialog = await screen.findByRole("dialog", { name: msg("settings-plugins-section-remove-title") });
  const confirm = within(dialog).getByRole("button", { name: msg("settings-plugins-section-remove") });
  expect(confirm).toBeDisabled();
  await userEvent.type(within(dialog).getByLabelText(/example-pay/), "example-pay");
  await userEvent.click(confirm);
  expect(api.removePluginData).toHaveBeenCalledWith("example-pay", "example-pay");
  // 2804 + 1120: the coverage bookkeeping cleared beside them is not data it added.
  expect(await screen.findByText(msg("settings-plugins-section-removed", { rows: 3924 }))).toBeVisible();
});

it("Remove data waits, saying why, while the estimates still read the plugin's data", async () => {
  vi.mocked(api.plugin).mockResolvedValue(enabled({ state: "disabled", active_slots: [], estimates_read: true }));
  renderScreen();
  await heading();
  const remove = screen.getByRole("button", { name: msg("settings-plugins-section-remove") });
  expect(remove).toBeDisabled();
  expect(remove).toHaveAccessibleDescription(msg("settings-plugin-settings-remove-waiting"));
});

it("a plugin whose data stays as history says Remove data keeps it", async () => {
  vi.mocked(api.plugin).mockResolvedValue(enabled({
    state: "disabled", active_slots: [], slots: ["pay.observations"], removable_slots: [] }));
  renderScreen();
  await heading();
  expect(screen.getByText(msg("settings-plugin-settings-remove-note", {
    what: "history", kinds: msg("settings-plugins-section-slot", { slot: "pay_observations" }) }))).toBeVisible();
});

it("Remove data asks for the id exactly as shown: a value in another case keeps Remove off", async () => {
  vi.mocked(api.plugin).mockResolvedValue(enabled({ state: "disabled", active_slots: [] }));
  renderScreen();
  await heading();
  await userEvent.click(screen.getByRole("button", { name: msg("settings-plugins-section-remove") }));
  const dialog = await screen.findByRole("dialog", { name: msg("settings-plugins-section-remove-title") });
  // The id renders as its own text, outside the label's upper-casing.
  const id = within(dialog).getByText("example-pay");
  expect(id).toHaveAttribute("data-copy", "content");
  expect(id).toHaveClass("plugin-remove-id");
  const field = within(dialog).getByRole("textbox", { name: msg("settings-plugins-section-remove-confirm", { name: "example-pay" }) });
  await userEvent.type(field, "EXAMPLE-PAY");
  const confirm = within(dialog).getByRole("button", { name: msg("settings-plugins-section-remove") });
  expect(confirm).toBeDisabled();
  await userEvent.type(field, "{Enter}");
  expect(api.removePluginData).not.toHaveBeenCalled();
});

it.each([
  ["plugin-confirm-mismatch", () => msg("error-plugin-confirm-mismatch")],
  ["plugin-estimates-moving", () => msg("error-plugin-estimates-moving")],
] as const)("Remove data refused with %s says why", async (code, said) => {
  vi.mocked(api.plugin).mockResolvedValue(enabled({ state: "disabled", active_slots: [] }));
  vi.mocked(api.removePluginData).mockRejectedValue(new ApiError("refused", 409, code, {}));
  renderScreen();
  await heading();
  await userEvent.click(screen.getByRole("button", { name: msg("settings-plugins-section-remove") }));
  const dialog = await screen.findByRole("dialog", { name: msg("settings-plugins-section-remove-title") });
  await userEvent.type(within(dialog).getByRole("textbox"), "example-pay");
  await userEvent.click(within(dialog).getByRole("button", { name: msg("settings-plugins-section-remove") }));
  expect(await screen.findByRole("alert")).toHaveTextContent(said());
});

it("an update that lapsed the approval while on: switch on, Remove data held, off without approving, and approving says it resumes", async () => {
  vi.mocked(api.plugin).mockResolvedValue(pluginDetailFixture({ ...pluginLapsedFixture(), runs: [] }));
  vi.mocked(api.disablePlugin).mockResolvedValue({
    plugin: pluginLapsedFixture({ enabled: false }), reestimate_started: false, stopped: [] });
  renderScreen();
  await heading();
  const toggle = screen.getByRole("checkbox", { name: msg("settings-plugins-section-use", { name: "Example pay data" }) });
  expect(toggle).toBeChecked();
  expect(screen.getByRole("button", { name: msg("settings-plugins-section-remove") })).toBeDisabled();
  const start = screen.getByRole("button", { name: msg("settings-plugins-section-start") });
  expect(start).toBeDisabled();
  expect(start).toHaveAccessibleDescription(msg("settings-plugins-section-approve-first"));
  expect(screen.getByTestId("plugin-next-update")).toHaveTextContent(
    msg("settings-plugin-settings-next-value", { state: "approval", when: "" }),
  );

  await userEvent.click(screen.getByRole("button", { name: msg("settings-plugins-section-review") }));
  const dialog = await screen.findByRole("dialog", { name: msg("settings-plugins-section-approve-title") });
  expect(dialog).toHaveTextContent(msg("settings-plugins-section-approve-still-on"));
  expect(within(dialog).getByRole("button", { name: msg("settings-plugins-section-approve-and-use") })).toBeVisible();
  expect(within(dialog).queryByRole("button", { name: msg("settings-plugins-section-approve") })).toBeNull();
  await userEvent.click(within(dialog).getByRole("button", { name: msg("settings-cancel") }));

  await userEvent.click(toggle);
  expect(api.disablePlugin).toHaveBeenCalledWith("example-pay");
  expect(api.approvePlugin).not.toHaveBeenCalled();
});

it("an update that ended partway reads as one in progress, and the next update continues it", async () => {
  const view = pluginFixture();
  // An update that never counted its companies: the sentence without a count.
  const partway = { ...view.last_run!, continues: true, progress_done: null, progress_total: null };
  vi.mocked(api.plugin).mockResolvedValue(enabled({ last_run: partway, runs: [partway] }));
  renderScreen();
  await heading();
  const when = ago(partway.ended_at!);
  expect(screen.getByTestId("plugin-last-update")).toHaveTextContent(
    msg("settings-plugin-settings-run", { outcome: "continues", when }),
  );
  expect(screen.getByTestId("plugin-next-update")).toHaveTextContent(
    msg("settings-plugin-settings-next-value", { state: "continues", when: "" }),
  );
  expect(screen.getByRole("listitem")).toHaveTextContent(msg("settings-plugin-settings-outcome", { outcome: "continues" }));
});

it("the last update says how far a short one got: stopped after 4 of 1,180 companies; continuing after 300", async () => {
  const stopped = pluginRunStoppedFixture();
  vi.mocked(api.plugin).mockResolvedValue(enabled({ last_run: stopped, runs: [stopped] }));
  const { unmount } = renderScreen();
  await heading();
  expect(screen.getByTestId("plugin-last-update")).toHaveTextContent(msg("settings-plugin-settings-run-progress", {
    outcome: "stopped", when: ago(stopped.ended_at!), read: msg("shared-results-of-company", { n: 4, t: 1180, total: 1180 }),
  }));
  unmount();

  const continuing = pluginRunContinuingFixture();
  vi.mocked(api.plugin).mockResolvedValue(enabled({ last_run: continuing, runs: [continuing] }));
  renderScreen();
  await heading();
  expect(screen.getByTestId("plugin-last-update")).toHaveTextContent(msg("settings-plugin-settings-run-progress", {
    outcome: "continues", when: ago(continuing.ended_at!),
    read: msg("shared-results-of-company", { n: 300, t: 1180, total: 1180 }),
  }));
});

/** Recent updates, the card. */
const history = () => screen.getByRole("region", { name: msg("settings-plugin-settings-history") });

/** One fact line of the Updates card, found by its label. */
const factLine = (label: string) => screen.getByText(label, { selector: "dt" }).closest("div") as HTMLElement;

it("Pause and Resume sit on the Next update line, which they govern; Start sits on the Last update line", async () => {
  const { unmount } = renderScreen();
  await heading();
  const next = factLine(msg("settings-plugin-settings-next"));
  const last = factLine(msg("settings-plugin-settings-last"));
  expect(within(next).getByRole("button", { name: msg("settings-plugins-section-pause") })).toBeEnabled();
  expect(within(next).queryByRole("button", { name: msg("settings-plugins-section-start") })).toBeNull();
  expect(within(last).getByRole("button", { name: msg("settings-plugins-section-start") })).toBeEnabled();
  expect(within(last).queryByRole("button", { name: msg("settings-plugins-section-pause") })).toBeNull();
  unmount();

  vi.mocked(api.plugin).mockResolvedValue(enabled({ paused: true, paused_at: "2026-07-13T08:00:00Z", next_update_at: null }));
  renderScreen();
  await heading();
  const paused = factLine(msg("settings-plugin-settings-next"));
  // Resume beside the sentence that says nothing updates until you resume.
  expect(paused).toHaveTextContent(msg("settings-plugin-settings-next-value", { state: "paused", when: "" }));
  expect(within(paused).getByRole("button", { name: msg("settings-plugins-section-resume") })).toBeEnabled();
  expect(within(factLine(msg("settings-plugin-settings-last"))).getByRole("button", {
    name: msg("settings-plugins-section-start") })).toBeEnabled();
});

it("Start that cannot run says why on its own line, beside it", async () => {
  vi.mocked(api.plugin).mockResolvedValue(enabled({ state: "disabled", active_slots: [] }));
  renderScreen();
  await heading();
  const last = factLine(msg("settings-plugin-settings-last"));
  const start = within(last).getByRole("button", { name: msg("settings-plugins-section-start") });
  expect(within(last).getByText(msg("settings-plugins-section-turn-on-first"))).toBeVisible();
  expect(start).toHaveAccessibleDescription(msg("settings-plugins-section-turn-on-first"));
  // Off: nothing to pause or resume, so the Next update line has no control.
  expect(within(factLine(msg("settings-plugin-settings-next"))).queryByRole("button")).toBeNull();
});

it("the last update stands as its own sentence, not a lower-case fragment", async () => {
  renderScreen();
  await heading();
  const when = ago(pluginFixture().last_run!.ended_at!);
  expect(screen.getByTestId("plugin-last-update")).toHaveTextContent(
    msg("settings-plugin-settings-run", { outcome: "clean", when }),
  );
});

it("Start shows the update at once and holds Start until its run shows up", async () => {
  vi.mocked(api.refreshPlugin).mockResolvedValue({ started: true, job: "refresh", waiting: null });
  renderScreen();
  await heading();
  await userEvent.click(screen.getByRole("button", { name: msg("settings-plugins-section-start") }));
  await waitFor(() => expect(screen.getByRole("button", { name: msg("settings-plugins-section-start") })).toBeDisabled());
  expect(screen.getByText(msg("settings-plugins-section-state", { state: "updating" }))).toBeVisible();
  expect(screen.getByTestId("plugin-last-update")).toHaveTextContent(
    msg("settings-plugin-settings-run", { outcome: "running", when: "" }),
  );
});

it("Uninstall says the data stays, and uninstalls only when confirmed", async () => {
  vi.mocked(api.uninstallPlugin).mockResolvedValue(action());
  renderScreen();
  await heading();
  await userEvent.click(screen.getByRole("button", { name: msg("settings-plugin-settings-uninstall") }));
  const dialog = await screen.findByRole("dialog", { name: msg("settings-plugin-settings-uninstall-title") });
  expect(dialog).toHaveTextContent(msg("settings-plugin-settings-uninstall-lead"));
  await userEvent.click(within(dialog).getByRole("button", { name: msg("settings-cancel") }));
  expect(api.uninstallPlugin).not.toHaveBeenCalled();
  await userEvent.click(screen.getByRole("button", { name: msg("settings-plugin-settings-uninstall") }));
  await userEvent.click(within(await screen.findByRole("dialog")).getByRole("button", {
    name: msg("settings-plugin-settings-uninstall") }));
  expect(api.uninstallPlugin).toHaveBeenCalledWith("example-pay");
});

it("an uninstalled plugin shows no schedule and no Uninstall, and its data can be removed", async () => {
  vi.mocked(api.plugin).mockResolvedValue(enabled({ state: "removed", active_slots: [], next_update_at: null }));
  renderScreen();
  await heading();
  expect(screen.queryByRole("group", { name: msg("settings-plugin-settings-how-often") })).toBeNull();
  expect(screen.queryByRole("button", { name: msg("settings-plugin-settings-uninstall") })).toBeNull();
  expect(screen.getByRole("button", { name: msg("settings-plugins-section-remove") })).toBeEnabled();
  expect(screen.getByRole("checkbox", { name: msg("settings-plugins-section-use", { name: "Example pay data" }) }))
    .toBeDisabled();
});

it("a plugin waiting for approval says why, and Review approves it without turning it on", async () => {
  vi.mocked(api.plugin).mockResolvedValue(pluginDetailFixture());
  vi.mocked(api.approvePlugin).mockResolvedValue(action());
  renderScreen();
  await heading();
  expect(screen.getByText(msg("settings-plugin-settings-needs-approval"))).toBeVisible();
  await userEvent.click(screen.getByRole("button", { name: msg("settings-plugins-section-review") }));
  const dialog = await screen.findByRole("dialog", { name: msg("settings-plugins-section-approve-title") });
  await userEvent.click(within(dialog).getByRole("button", { name: msg("settings-plugins-section-approve") }));
  expect(api.approvePlugin).toHaveBeenCalledWith("example-pay", "f0".repeat(32), null);
  expect(api.enablePlugin).not.toHaveBeenCalled();
});

it("Site rules: a plugin that follows them offers Review, and allowing records the files shown", async () => {
  vi.mocked(api.pluginRobots).mockResolvedValue(pluginRobotsFixture());
  vi.mocked(api.setPluginRobots).mockResolvedValue({ plugin: pluginFixture(), reestimate_started: false, stopped: [] });
  renderScreen();
  await heading();
  const row = screen.getByTestId("plugin-robots-state");
  expect(row).toHaveTextContent(msg("settings-plugin-settings-robots-state", { state: "follows", hosts: "", when: "" }));
  await userEvent.click(within(row).getByRole("button", { name: msg("settings-plugin-settings-robots-review") }));
  const dialog = await screen.findByRole("dialog", { name: msg("settings-plugins-section-robots-title") });
  const allowButton = within(dialog).getByRole("button", { name: msg("settings-plugins-section-robots-allow-button") });
  expect(allowButton).toBeDisabled();
  await userEvent.click(await within(dialog).findByRole("checkbox", { name: msg("settings-plugins-section-robots-allow") }));
  await userEvent.click(allowButton);
  expect(api.setPluginRobots).toHaveBeenCalledWith("example-pay", { "data.example.com": "ab".repeat(32) });
});

it("Site rules: an allowed plugin can follow them again, and a site that changed its rules is named", async () => {
  vi.mocked(api.setPluginRobots).mockResolvedValue({ plugin: pluginFixture(), reestimate_started: false, stopped: [] });
  vi.mocked(api.plugin).mockResolvedValue(enabled({ robots_consent_at: "2026-10-12T09:00:00Z" }));
  const { unmount } = renderScreen();
  await heading();
  const row = screen.getByTestId("plugin-robots-state");
  await userEvent.click(within(row).getByRole("button", { name: msg("settings-plugin-settings-robots-stop") }));
  expect(api.setPluginRobots).toHaveBeenCalledWith("example-pay", null);
  unmount();

  vi.mocked(api.plugin).mockResolvedValue(enabled({
    robots_consent_at: "2026-10-12T09:00:00Z", robots_lapsed: ["data.example.com"] }));
  renderScreen();
  await heading();
  const lapsed = screen.getByTestId("plugin-robots-state");
  expect(lapsed).toHaveTextContent(msg("settings-plugin-settings-robots-state", {
    state: "lapsed", hosts: "data.example.com", when: "" }));
  expect(within(lapsed).getByRole("button", { name: msg("settings-plugin-settings-robots-review") })).toBeEnabled();
});

it("a plugin that is not installed says so, and All plugins goes back", async () => {
  vi.mocked(api.plugin).mockRejectedValue(new ApiError("no plugin", 404, "plugin-not-found", {}));
  renderScreen("gone");
  expect(await screen.findByText(msg("settings-plugin-settings-not-found"))).toBeVisible();
  await userEvent.click(screen.getByRole("button", { name: msg("settings-plugin-settings-back") }));
  expect(await screen.findByTestId("where")).toHaveTextContent("/settings/plugins");
});


it("the plugin's own words say what it does, what its last update did and what each recent update did", async () => {
  const stopped = pluginRunStoppedFixture({ summary: "Read pay for 56 of 1,180 companies" });
  const earlier = pluginRunFixture({ id: 9, summary: "Read pay for 96 companies" });
  vi.mocked(api.plugin).mockResolvedValue(enabled({
    description: "Pay by level and benefits from ladder.example", last_run: stopped, runs: [stopped, earlier],
  }));
  renderScreen();
  await heading();
  const what = screen.getByText("Pay by level and benefits from ladder.example");
  expect(what).toHaveAttribute("translate", "no");
  expect(screen.queryByText(msg("settings-plugins-section-answers", { slots: "benefits and pay by level" }))).toBeNull();
  const ended = msg("settings-plugin-settings-run", { outcome: "stopped", when: ago(stopped.ended_at!) });
  expect(screen.getByTestId("plugin-last-update")).toHaveTextContent(`${ended}: Read pay for 56 of 1,180 companies`);
  const history = screen.getAllByRole("listitem").filter((li) => li.closest(".plugin-settings-runs"));
  expect(history[0]).toHaveTextContent("Read pay for 56 of 1,180 companies");
  expect(history[0]).not.toHaveTextContent(msg("shared-results-of-company", { n: 4, t: 1180, total: 1180 }));
  expect(history[1]).toHaveTextContent("Read pay for 96 companies");
});
