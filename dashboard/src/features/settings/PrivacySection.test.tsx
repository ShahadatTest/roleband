import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { api } from "../../api";
import { usageStateFixture } from "../../test/fixtures";
import { msg } from "../../test/msg";
import { PrivacySection } from "./PrivacySection";

/* Settings > Privacy (docs/architecture.md): one switch per kind of
   sharing, committed at once with the words beside it; a machine-wide switch
   says why everything is off and disables the switches; Reset and the next
   batch are one click each. */

vi.mock("../../api", () => ({
  api: {
    usage: vi.fn(),
    saveUsageConsent: vi.fn(),
    resetUsageInstallId: vi.fn(),
    usagePreview: vi.fn(),
    usageSent: vi.fn(),
  },
}));
vi.mock("posthog-js/dist/module.full.no-external", () => ({ default: {
  init: vi.fn(), set_config: vi.fn(), identify: vi.fn(), reset: vi.fn(),
  get_distinct_id: vi.fn(() => "8f14e45f-ceea-4e7a-9b3a-1f2d3c4b5a69"),
  opt_out_capturing: vi.fn(), opt_in_capturing: vi.fn(), has_opted_out_capturing: vi.fn(() => false),
} }));

const usageSwitch = () => screen.getByRole("checkbox", { name: "Anonymous usage data" });

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(api.usage).mockResolvedValue(usageStateFixture("declined"));
});

it("the card is named by its tab, and the consent question's title heads the switches it records", async () => {
  render(<PrivacySection />);
  expect(await screen.findByRole("region", { name: msg("privacy-settings-title") })).toBeVisible();
  expect(screen.getByRole("heading", { level: 2, name: msg("privacy-settings-title") })).toBeVisible();
  expect(await screen.findByRole("heading", { level: 3, name: msg("privacy-consent-title") })).toBeVisible();
  // What is never sent is standing copy in the intro, not a boxed note between rows.
  expect(screen.getByText(new RegExp(msg("privacy-never")))).toBeVisible();
  expect(screen.queryByRole("note")).toBeNull();
});

it("while it loads, the row it becomes stands in, not the card's own title again", async () => {
  vi.mocked(api.usage).mockReturnValue(new Promise(() => {}));
  render(<PrivacySection />);
  expect(screen.getByText(msg("privacy-group-usage"))).toBeVisible();
  expect(screen.getAllByText(msg("privacy-settings-title"))).toHaveLength(1);
  expect(screen.queryByText(msg("privacy-consent-title"))).toBeNull();
});

it("each switch is its row's own label: the row's words turn it, and no label sits inside another", async () => {
  vi.mocked(api.saveUsageConsent).mockResolvedValue(usageStateFixture("declined"));
  render(<PrivacySection />);
  const toggle = await screen.findByRole("checkbox", { name: "Crash reports" });
  const label = toggle.closest("label") as HTMLElement;
  expect(label.parentElement?.closest("label")).toBeNull();
  expect(toggle).toHaveAccessibleDescription(msg("privacy-group-crashes-detail"));
  await userEvent.click(screen.getByText(msg("privacy-group-crashes-detail")));
  await waitFor(() => expect(api.saveUsageConsent).toHaveBeenCalledTimes(1));
  expect(vi.mocked(api.saveUsageConsent).mock.calls[0][0].answers).toEqual({ crashes: true });
});

it("shows one switch per kind of sharing, each off until turned on", async () => {
  render(<PrivacySection />);
  expect(await screen.findByRole("heading", { name: "Help us improve" })).toBeVisible();
  for (const name of ["Anonymous usage data", "Crash reports", "Feedback surveys"]) {
    expect(screen.getByRole("checkbox", { name })).not.toBeChecked();
  }
  // RoleBand records no sessions: there is nothing to switch on.
  expect(screen.getAllByRole("checkbox")).toHaveLength(3);
  expect(screen.queryByText(/Session recordings/)).toBeNull();
  expect(screen.getByText("None yet")).toBeVisible();
});

it("turning one on records only it, with the words beside it", async () => {
  vi.mocked(api.saveUsageConsent).mockResolvedValue(
    usageStateFixture("declined", {
      groups: usageStateFixture("declined").groups.map((g) => (g.group === "usage" ? { ...g, status: "shared" } : g)),
    }),
  );
  render(<PrivacySection />);
  await userEvent.click(await screen.findByRole("checkbox", { name: "Anonymous usage data" }));
  await waitFor(() => expect(api.saveUsageConsent).toHaveBeenCalledTimes(1));
  const payload = vi.mocked(api.saveUsageConsent).mock.calls[0][0];
  expect(payload.answers).toEqual({ usage: true });
  expect(payload.fingerprints).toEqual({ usage: "usage-fingerprint" });
  expect(payload.text).toBe(
    [
      "Help us improve",
      "Anonymous usage data: Which screens and features you use, and how scans go.",
      "Never sent: company names, role titles, compensation, your CV or anything you type.",
    ].join("\n\n"),
  );
  await waitFor(() => expect(usageSwitch()).toBeChecked());
});

it("turning one off stops it", async () => {
  vi.mocked(api.usage).mockResolvedValue(usageStateFixture("shared"));
  vi.mocked(api.saveUsageConsent).mockResolvedValue(usageStateFixture("declined"));
  render(<PrivacySection />);
  await userEvent.click(await screen.findByRole("checkbox", { name: "Crash reports" }));
  await waitFor(() => expect(api.saveUsageConsent).toHaveBeenCalled());
  expect(vi.mocked(api.saveUsageConsent).mock.calls[0][0].answers).toEqual({ crashes: false });
});

it("a machine-wide switch says why and disables every switch", async () => {
  vi.mocked(api.usage).mockResolvedValue(usageStateFixture("shared", { blocked_by: "DO_NOT_TRACK" }));
  render(<PrivacySection />);
  expect(await screen.findByText("Sharing is off on this computer: DO_NOT_TRACK is set.")).toBeVisible();
  expect(usageSwitch()).toBeDisabled();
});

it("a widened kind says so instead of its sentence", async () => {
  const state = usageStateFixture("shared");
  state.groups[0].status = "stale";
  vi.mocked(api.usage).mockResolvedValue(state);
  render(<PrivacySection />);
  expect(await screen.findByText(/has grown since you chose/)).toBeVisible();
  expect(usageSwitch()).not.toBeChecked();
});

it("resets the install ID and shows the next batch on request", async () => {
  const shared = usageStateFixture("shared", { pending_events: 2 });
  vi.mocked(api.usage).mockResolvedValue(shared);
  vi.mocked(api.resetUsageInstallId).mockResolvedValue({ ...shared, install_id: "0b5c1f7e-2d4a-4c8e-9f10-6a7b8c9d0e1f" });
  vi.mocked(api.usagePreview).mockResolvedValue({
    body: { api_key: "phc_test", batch: [{ event: "daily_action", properties: { action: "save_job", count: 3 } }] },
    left_out: 0,
  });
  render(<PrivacySection />);
  expect(await screen.findByText(shared.install_id as string)).toBeVisible();
  await userEvent.click(screen.getByRole("button", { name: "Reset ID" }));
  expect(await screen.findByText("0b5c1f7e-2d4a-4c8e-9f10-6a7b8c9d0e1f")).toBeVisible();
  // The count is the fact (data voice); when it leaves is the description (body voice).
  expect(screen.getByTestId("privacy-next-count")).toHaveTextContent(/^2 events$/);
  expect(screen.getByText("Waits for the daily send.")).toHaveClass("settings-row-desc");
  await userEvent.click(screen.getByRole("button", { name: "Show what's sent" }));
  expect(await screen.findByLabelText("Next send")).toHaveTextContent('"action": "save_job"');
});

/* The list's own load lines are whole messages. Handed the row's title as a
   noun, the line would read "Loading Sent recently…". */
it("says the sent list's loading and failure in its own words, never around the row's title", async () => {
  vi.mocked(api.usageSent).mockReturnValue(new Promise(() => {}));
  const first = render(<PrivacySection />);
  await userEvent.click(await screen.findByRole("button", { name: msg("privacy-show-sent") }));
  const loading = await screen.findByText(msg("privacy-sent-loading"));
  expect(loading).not.toHaveTextContent(msg("privacy-sent-recently"));
  first.unmount();

  vi.mocked(api.usageSent).mockRejectedValue(new Error("offline"));
  render(<PrivacySection />);
  await userEvent.click(await screen.findByRole("button", { name: msg("privacy-show-sent") }));
  const failed = await screen.findByRole("alert");
  expect(within(failed).getByRole("heading")).toHaveTextContent(msg("privacy-sent-load-failed"));
  expect(failed).not.toHaveTextContent(msg("privacy-sent-recently"));
});
