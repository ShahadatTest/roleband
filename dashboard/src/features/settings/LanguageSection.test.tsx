import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { api } from "../../api";
import { ApiError } from "../../api/transport";
import { msg } from "../../test/msg";
import { LanguageSection } from "./LanguageSection";

vi.mock("../../api", () => ({ api: { saveLocale: vi.fn() } }));

describe("LanguageSection", () => {
  it("names the reason a choice could not be saved", async () => {
    // RoleBand down is a reason the reader can act on; a bare "try again"
    // beside the dial that names it would leave them guessing.
    vi.mocked(api.saveLocale).mockRejectedValue(new ApiError("down", 0, "offline"));
    const user = userEvent.setup();
    render(<LanguageSection />);
    const region = screen.getByRole<HTMLSelectElement>("combobox", { name: msg("settings-region-label") });
    const other = Array.from(region.querySelectorAll("option")).find((option) => option.value !== region.value)!;
    await user.selectOptions(region, other.value);
    expect(await screen.findByRole("alert")).toHaveTextContent(msg("error-offline"));
  });

  it("says its own words when the failure explains nothing", async () => {
    vi.mocked(api.saveLocale).mockRejectedValue(new Error("boom"));
    const user = userEvent.setup();
    render(<LanguageSection />);
    const region = screen.getByRole<HTMLSelectElement>("combobox", { name: msg("settings-region-label") });
    const other = Array.from(region.querySelectorAll("option")).find((option) => option.value !== region.value)!;
    await user.selectOptions(region, other.value);
    expect(await screen.findByRole("alert")).toHaveTextContent(msg("settings-save-failed"));
  });
});
