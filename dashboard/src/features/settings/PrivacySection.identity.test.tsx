import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import { api } from "../../api";
import { applySharing } from "../../diagnostics/sharing";
import { usageStateFixture } from "../../test/fixtures";
import { msg } from "../../test/msg";
import { PrivacySection } from "./PrivacySection";

const sdk = vi.hoisted(() => {
  const identity = { id: null as string | null, device: 0, links: [] as string[] };
  return { identity, client: {
    init: vi.fn((_key: string, config: { bootstrap: { distinctID: string } }) => {
      identity.id = config.bootstrap.distinctID;
    }),
    identify: vi.fn((id: string) => {
      if (identity.id && identity.id !== id) identity.links.push(`${identity.id}:${id}`);
      identity.id = id;
    }),
    get_distinct_id: vi.fn(() => identity.id),
    reset: vi.fn((options: { resetDeviceID: boolean; bootstrap: { distinctID: string } }) => {
      identity.id = options.bootstrap.distinctID;
      if (options.resetDeviceID) identity.device += 1;
    }),
    set_config: vi.fn(), opt_out_capturing: vi.fn(), opt_in_capturing: vi.fn(),
    has_opted_out_capturing: vi.fn(() => false),
  } };
});
vi.mock("posthog-js/dist/module.full.no-external", () => ({ default: sdk.client }));
vi.mock("../../api", () => ({ api: {
  usage: vi.fn(), saveUsageConsent: vi.fn(), resetUsageInstallId: vi.fn(), usagePreview: vi.fn(),
} }));

it("Reset ID rotates the active browser identity without linking IDs or changing consent", async () => {
  const old = usageStateFixture("shared");
  const next = { ...old, install_id: "0b5c1f7e-2d4a-4c8e-9f10-6a7b8c9d0e1f" };
  vi.mocked(api.usage).mockResolvedValue(old);
  vi.mocked(api.resetUsageInstallId).mockResolvedValue(next);
  await applySharing(old);
  expect(sdk.identity.id).toBe(old.install_id);
  const device = sdk.identity.device;
  render(<PrivacySection />);
  await screen.findByText(old.install_id!);
  await userEvent.click(screen.getByRole("button", { name: msg("privacy-reset-id") }));
  expect(await screen.findByText(next.install_id)).toBeVisible();
  expect(sdk.identity.id).toBe(next.install_id);
  expect(sdk.identity.device).toBe(device + 1);
  expect(sdk.identity.links).toEqual([]);
  for (const toggle of screen.getAllByRole("checkbox")) expect(toggle).toBeChecked();
  expect(api.saveUsageConsent).not.toHaveBeenCalled();
});
