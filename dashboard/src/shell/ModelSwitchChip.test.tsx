import { act, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ModelSwitchChip } from "./ModelSwitchChip";
import { AppProviders } from "../context/AppProviders";
import { api, type SystemStatus } from "../api";
import { statusFixture } from "../test/fixtures";
import { msg } from "../test/msg";

const status = (matching_switch: SystemStatus["matching_switch"]): SystemStatus => ({ ...statusFixture, matching_switch });

function renderChip() {
  vi.spyOn(api, "stats").mockResolvedValue({
    open_total: 0, new_today: 0, reposted_today: 0, closed_today: 0, saved_total: 0, review_pending: 0, notif_unread: 0, notif_high_unread: 0, by_company: {},
  });
  return render(
    <MemoryRouter>
      <AppProviders>
        <ModelSwitchChip />
      </AppProviders>
    </MemoryRouter>,
  );
}

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe("ModelSwitchChip", () => {
  it.each([
    ["converting", "switching model"],
    ["downloading", "getting model"],
  ] as const)("while the model is %s, says so and leads to Settings > AI", async (phase, words) => {
    vi.spyOn(api, "status").mockResolvedValue(status(phase));
    renderChip();
    const chip = await screen.findByRole("link", { name: msg("shell-model-switch-aria", { phase }) });
    expect(chip).toHaveAttribute("href", "/settings/intelligence");
    expect(chip).toHaveTextContent(words);
  });

  it("says nothing while no model job runs", async () => {
    const read = vi.spyOn(api, "status").mockResolvedValue(status("none"));
    renderChip();
    await vi.waitFor(() => expect(read).toHaveBeenCalled());
    await act(async () => {});
    expect(screen.queryByRole("link")).toBeNull();
  });

  it("leaves when the job ends", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const read = vi.spyOn(api, "status").mockResolvedValue(status("converting"));
    renderChip();
    expect(await screen.findByRole("link")).toBeInTheDocument();
    read.mockResolvedValue(status("none"));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(61_000);
    });
    expect(screen.queryByRole("link")).toBeNull();
  });
});
