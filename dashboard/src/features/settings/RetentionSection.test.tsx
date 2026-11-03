import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { api } from "../../api";
import { retentionStateFixture } from "../../test/fixtures";
import { RetentionSection } from "./RetentionSection";

vi.mock("../../api", () => ({
  api: {
    retention: vi.fn(),
    saveRetention: vi.fn(),
  },
}));

const select = () => screen.getByRole("combobox", { name: "Remove postings after" });

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(api.retention).mockResolvedValue(retentionStateFixture());
});

it("shows the saved window, what is kept, what is due and the last removal", async () => {
  render(<RetentionSection />);
  expect(await screen.findByRole("heading", { name: "Data retention" })).toBeVisible();
  expect(select()).toHaveValue("60");
  expect(screen.getByTestId("retention-counts")).toHaveTextContent(
    "1,240 kept · 210 no longer listed · 330 from companies you stopped following",
  );
  // What is due is a row of its own: the count is its fact, the prose its
  // description, never glued to the counts line.
  const due = screen.getByTestId("retention-due");
  expect(due).toHaveTextContent(/^94 postings$/);
  expect(due.closest(".settings-message")).toBeNull();
  const dueRow = due.closest(".settings-row") as HTMLElement;
  expect(dueRow).not.toContainElement(screen.getByTestId("retention-counts"));
  expect(within(dueRow).getByText("Due for removal")).toBeVisible();
  expect(within(dueRow).getByText("Due postings are removed during scans, never by saving."))
    .toHaveClass("settings-row-desc");
  expect(screen.getByTestId("retention-counts").closest(".settings-row-facts")).toHaveTextContent(
    /^1,240 kept · 210 no longer listed · 330 from companies you stopped following$/,
  );
  expect(screen.getByTestId("retention-last")).toHaveTextContent("57 removed");
  expect(screen.getByText(/never removed/)).toBeVisible();
});

it("labels each choice with what it would remove now, before anything is saved", async () => {
  render(<RetentionSection />);
  await screen.findByRole("heading", { name: "Data retention" });
  const labels = Array.from(select().querySelectorAll("option")).map((o) => o.textContent);
  expect(labels).toEqual([
    "7 days (402 due)", "14 days (310 due)", "30 days (188 due)", "60 days (94 due)",
    "90 days (40 due)", "180 days", "1 year", "Never",
  ]);
});

it("saves a longer window on change: it makes nothing newly due", async () => {
  vi.mocked(api.saveRetention).mockResolvedValue(retentionStateFixture({ days: 90, due: 40 }));
  render(<RetentionSection />);
  await screen.findByRole("heading", { name: "Data retention" });

  await userEvent.selectOptions(select(), "90");

  expect(api.saveRetention).toHaveBeenCalledWith({ days: 90 });
  expect(await screen.findByText("Saved.")).toBeVisible();
  expect(screen.getByTestId("retention-due")).toHaveTextContent(/^40 postings$/);
  expect(select()).toHaveValue("90");
  expect(screen.queryByRole("button", { name: /Remove after/ })).toBeNull();
});

it("asks before a shorter window, naming what it makes due, and saves only on confirm", async () => {
  // A pointer slip on the list must not commit "7 days (402 due)".
  vi.mocked(api.saveRetention).mockResolvedValue(retentionStateFixture({ days: 14, due: 310 }));
  render(<RetentionSection />);
  await screen.findByRole("heading", { name: "Data retention" });

  await userEvent.selectOptions(select(), "14");

  expect(api.saveRetention).not.toHaveBeenCalled();
  expect(select()).toHaveValue("14");
  expect(screen.getByTestId("retention-confirm")).toHaveTextContent(
    "With 14 days, 310 postings are due for removal. They're removed during the next scans.",
  );
  await userEvent.click(screen.getByRole("button", { name: "Remove after 14 days" }));

  expect(api.saveRetention).toHaveBeenCalledWith({ days: 14 });
  expect(await screen.findByText("Saved.")).toBeVisible();
  expect(screen.getByTestId("retention-due")).toHaveTextContent(/^310 postings$/);
  expect(screen.queryByTestId("retention-confirm")).toBeNull();
});

it("cancelling a shorter window sends nothing and returns to the saved one", async () => {
  render(<RetentionSection />);
  await screen.findByRole("heading", { name: "Data retention" });

  await userEvent.selectOptions(select(), "7");
  await userEvent.click(screen.getByRole("button", { name: "Cancel" }));

  expect(api.saveRetention).not.toHaveBeenCalled();
  expect(select()).toHaveValue("60");
  expect(screen.queryByTestId("retention-confirm")).toBeNull();
});

it("sends Never as null and says nothing is removed", async () => {
  vi.mocked(api.saveRetention).mockResolvedValue(retentionStateFixture({ days: null, due: 0 }));
  render(<RetentionSection />);
  await screen.findByRole("heading", { name: "Data retention" });

  await userEvent.selectOptions(select(), "never");

  expect(api.saveRetention).toHaveBeenCalledWith({ days: null });
  expect(await screen.findByText("Saved.")).toBeVisible();
  expect(screen.getByTestId("retention-due")).toHaveTextContent(/^0 postings$/);
  expect(screen.getByText("Nothing is removed while this is set to Never.")).toBeVisible();
  expect(select()).toHaveValue("never");
});

it("a failed save says so and the control returns to the saved window", async () => {
  vi.mocked(api.saveRetention).mockRejectedValue(new Error("Server unavailable"));
  render(<RetentionSection />);
  await screen.findByRole("heading", { name: "Data retention" });

  await userEvent.selectOptions(select(), "7");
  await userEvent.click(screen.getByRole("button", { name: "Remove after 7 days" }));

  expect(await screen.findByRole("alert")).toHaveTextContent("Couldn't save it. Try again.");
  expect(screen.getByRole("alert")).not.toHaveTextContent("Server unavailable");
  expect(select()).toHaveValue("60");
  expect(select()).toBeEnabled();
  expect(screen.queryByText("Saved.")).toBeNull();
});

it("says when nothing has been removed yet, and when a removal left more for the next scan", async () => {
  vi.mocked(api.retention).mockResolvedValueOnce(retentionStateFixture({ last_removed: null, due: 0 }));
  const { unmount } = render(<RetentionSection />);
  expect(await screen.findByTestId("retention-last")).toHaveTextContent("None yet");
  expect(screen.getByTestId("retention-due")).toHaveTextContent(/^0 postings$/);
  unmount();

  vi.mocked(api.retention).mockResolvedValueOnce(retentionStateFixture({ due: 1 }));
  const second = render(<RetentionSection />);
  expect(await screen.findByTestId("retention-due")).toHaveTextContent(/^1 posting$/);
  second.unmount();

  vi.mocked(api.retention).mockResolvedValueOnce(retentionStateFixture({
    last_removed: { at: "2026-09-21T06:10:00Z", removed: 100000, more: true },
  }));
  render(<RetentionSection />);
  expect(await screen.findByTestId("retention-last")).toHaveTextContent(
    "100,000 removed · more are removed at the next scan",
  );
});
