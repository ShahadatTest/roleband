import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { api } from "../../api";
import { ApiError } from "../../api/transport";
import { priceFeedStateFixture } from "../../test/fixtures";
import { msg } from "../../test/msg";
import { PriceFeedSection } from "./PriceFeedSection";

vi.mock("../../api", () => ({
  PRICE_FEED_KEY_URL: "https://www.tiingo.com/account/api/token",
  api: {
    priceFeed: vi.fn(),
    savePriceFeedKey: vi.fn(),
    removePriceFeedKey: vi.fn(),
    refreshPriceFeed: vi.fn(),
  },
}));

const row = () => screen.getByTestId("price-feed-row");
const button = (name: string) => screen.queryByRole("button", { name });
const dialog = () => screen.getByTestId("price-feed-dialog");
const SAVED = priceFeedStateFixture({
  configured: true, origin: "settings", priced: 58, as_of: "2026-10-09",
  last_run_at: new Date(Date.now() - 2 * 3600_000).toISOString(),
});

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(api.priceFeed).mockResolvedValue(priceFeedStateFixture());
});

it("is one kit row: the service by name, its terms and where to get a key, no bare field", async () => {
  render(<PriceFeedSection />);
  expect(await screen.findByRole("heading", { name: msg("settings-price-feed-title") })).toBeVisible();
  expect(within(row()).getByText(msg("settings-price-feed-source"))).toBeVisible();
  const key = within(row()).getByRole("link", { name: msg("shared-price-feed-get-key") });
  expect(key).toHaveAttribute("href", "https://www.tiingo.com/account/api/token");
  expect(key).toHaveAttribute("target", "_blank");
  expect(screen.getByTestId("price-feed-facts")).toHaveTextContent(
    new RegExp(`^${msg("settings-price-feed-key-state", { origin: "none" })}$`),
  );
  // A write-only key: no input on the card, nothing to remove.
  expect(row().querySelector("input")).toBeNull();
  expect(button(msg("settings-price-feed-add"))).toBeEnabled();
  expect(button(msg("settings-price-feed-remove"))).toBeNull();
});

it("states a saved key, the priced companies, the newest close and the last update as facts", async () => {
  vi.mocked(api.priceFeed).mockResolvedValue(SAVED);
  render(<PriceFeedSection />);
  const facts = await screen.findByTestId("price-feed-facts");
  expect(facts).toHaveTextContent(/^Key saved · 58 companies · latest close .+ · updated .+ago$/);
  expect(button(msg("settings-price-feed-replace"))).toBeEnabled();
  expect(button(msg("settings-price-feed-remove"))).toBeEnabled();
});

it("adds a key in a dialog: a labelled password field, saved trimmed, never shown again", async () => {
  vi.mocked(api.savePriceFeedKey).mockResolvedValue({ ...SAVED, key_check: "ok" });
  render(<PriceFeedSection />);
  await userEvent.click(await screen.findByRole("button", { name: msg("settings-price-feed-add") }));
  const field = within(dialog()).getByLabelText(msg("settings-price-feed-dialog-field"));
  expect(field).toHaveAttribute("type", "password");
  expect(field).toHaveFocus();
  const save = within(dialog()).getByRole("button", { name: msg("settings-price-feed-dialog-save", { choice: "no" }) });
  expect(save).toBeDisabled();
  await userEvent.type(field, "  tk_secret  ");
  await userEvent.click(save);
  expect(api.savePriceFeedKey).toHaveBeenCalledWith("tk_secret");
  expect(await screen.findByText(msg("settings-price-feed-saved", { check: "ok" }))).toBeVisible();
  expect(screen.queryByTestId("price-feed-dialog")).not.toBeInTheDocument();
  expect(screen.getByTestId("price-feed-facts")).toHaveTextContent(/^Key saved/);
  expect(document.body).not.toHaveTextContent("tk_secret");
});

it("keeps the dialog open with what was typed when the save fails", async () => {
  vi.mocked(api.savePriceFeedKey).mockRejectedValue(new Error("boom"));
  render(<PriceFeedSection />);
  await userEvent.click(await screen.findByRole("button", { name: msg("settings-price-feed-add") }));
  const field = within(dialog()).getByLabelText(msg("settings-price-feed-dialog-field"));
  await userEvent.type(field, "tk_secret");
  await userEvent.click(within(dialog()).getByRole("button", { name: msg("settings-price-feed-dialog-save", { choice: "no" }) }));
  expect(await within(dialog()).findByRole("alert")).toHaveTextContent(msg("settings-save-failed"));
  expect(field).toHaveValue("tk_secret");
});

it("offers Remove only for a key saved here, never for one set outside the app", async () => {
  vi.mocked(api.priceFeed).mockResolvedValue(priceFeedStateFixture({ configured: true, origin: "environment" }));
  const { unmount } = render(<PriceFeedSection />);
  expect(await screen.findByTestId("price-feed-facts")).toHaveTextContent(/^Key set outside the app/);
  expect(button(msg("settings-price-feed-remove"))).toBeNull();
  expect(button(msg("settings-price-feed-add"))).toBeEnabled();
  unmount();

  vi.mocked(api.priceFeed).mockResolvedValue(SAVED);
  vi.mocked(api.removePriceFeedKey).mockResolvedValue(priceFeedStateFixture());
  render(<PriceFeedSection />);
  await userEvent.click(await screen.findByRole("button", { name: msg("settings-price-feed-remove") }));
  expect(api.removePriceFeedKey).toHaveBeenCalledOnce();
  expect(await screen.findByText(msg("settings-price-feed-removed"))).toBeVisible();
  expect(screen.getByTestId("price-feed-facts")).toHaveTextContent(/^No key yet$/);
});

it("says when the price service refused the key, and only while a key is set", async () => {
  vi.mocked(api.priceFeed).mockResolvedValue({ ...SAVED, refused: "unauthorized" });
  const { unmount } = render(<PriceFeedSection />);
  expect(await screen.findByRole("alert")).toHaveTextContent(msg("settings-price-feed-unauthorized"));
  unmount();

  vi.mocked(api.priceFeed).mockResolvedValue(priceFeedStateFixture({ refused: "unauthorized" }));
  render(<PriceFeedSection />);
  await screen.findByTestId("price-feed-facts");
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
});


it("says when a saved key could not be checked yet, and does not claim Tiingo answered", async () => {
  vi.mocked(api.savePriceFeedKey).mockResolvedValue({ ...SAVED, key_check: "offline" });
  render(<PriceFeedSection />);
  await userEvent.click(await screen.findByRole("button", { name: msg("settings-price-feed-add") }));
  await userEvent.type(within(dialog()).getByLabelText(msg("settings-price-feed-dialog-field")), "tk_secret");
  await userEvent.click(within(dialog()).getByRole("button", { name: msg("settings-price-feed-dialog-save", { choice: "no" }) }));
  expect(await screen.findByText(msg("settings-price-feed-saved", { check: "other" }))).toBeVisible();
  expect(screen.queryByText(msg("settings-price-feed-saved", { check: "ok" }))).not.toBeInTheDocument();
});

it("keeps the dialog open and says why when Tiingo refuses the key", async () => {
  const refused = new ApiError("refused", 409, "price-key-refused");
  vi.mocked(api.savePriceFeedKey).mockRejectedValue(refused);
  render(<PriceFeedSection />);
  await userEvent.click(await screen.findByRole("button", { name: msg("settings-price-feed-add") }));
  await userEvent.type(within(dialog()).getByLabelText(msg("settings-price-feed-dialog-field")), "tk_wrong");
  await userEvent.click(within(dialog()).getByRole("button", { name: msg("settings-price-feed-dialog-save", { choice: "no" }) }));
  expect(await within(dialog()).findByRole("alert")).toHaveTextContent(msg("error-price-key-refused"));
});

it("says how many prices wait for Tiingo's limits and when, and asks for an update on request", async () => {
  const later = new Date(Date.now() + 40 * 60_000).toISOString();
  vi.mocked(api.priceFeed).mockResolvedValue({ ...SAVED, waiting: 12, next_at: later });
  vi.mocked(api.refreshPriceFeed).mockResolvedValue({ ...SAVED, waiting: 12, next_at: later });
  render(<PriceFeedSection />);
  expect(await screen.findByTestId("price-feed-facts")).toHaveTextContent(/· 12 more in 40 minutes$/);
  await userEvent.click(screen.getByRole("button", { name: msg("settings-price-feed-update-now") }));
  expect(api.refreshPriceFeed).toHaveBeenCalledOnce();
});

it("offers Update now only while a key is set", async () => {
  render(<PriceFeedSection />);
  await screen.findByTestId("price-feed-facts");
  expect(button(msg("settings-price-feed-update-now"))).toBeNull();
});
