import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";
import { api } from "../api";
import { JobWorkspaceProvider, useJobActions } from "../context/JobWorkspace";
import { ToastProvider } from "../ui";
import { CompareSaveAlert } from "./CompareSaveAlert";

/* A compare selection that did not save, said wherever the reader is. The
   context records the failure, and the margin beacon's reveal stands only
   from two roles, so a failed first pick, a removal down to one, or Clear
   would otherwise say nothing, and a reload would bring back what the reader
   had removed. */

vi.mock("../api", () => ({
  api: { markJobViewed: vi.fn().mockResolvedValue({}), compareSelection: vi.fn(), setCompareSelection: vi.fn() },
}));

const store = { setCompareSelection: () => vi.mocked(api.setCompareSelection) };
let verbs: ReturnType<typeof useJobActions>;

function Verbs() {
  verbs = useJobActions();
  return null;
}

async function mount(stored: number[]) {
  vi.mocked(api.compareSelection).mockResolvedValue({ job_ids: stored });
  render(
    <MemoryRouter>
      <ToastProvider>
        <JobWorkspaceProvider>
          <Verbs />
          <CompareSaveAlert />
        </JobWorkspaceProvider>
      </ToastProvider>
    </MemoryRouter>,
  );
  await waitFor(() => expect(api.compareSelection).toHaveBeenCalled());
  await act(async () => {});
}

const ALERT = /Couldn't save what you're comparing/;

beforeEach(() => {
  vi.clearAllMocks();
  store.setCompareSelection().mockImplementation((ids: number[]) => Promise.resolve({ job_ids: ids }));
});

it.each([
  ["a first pick", [] as number[], () => verbs.toggleCompare(1)],
  ["a removal down to one", [1, 2], () => verbs.toggleCompare(2)],
  ["Clear", [1, 2], () => verbs.clearCompare()],
])("says when %s did not save, at any selection size, and Try again saves it", async (_case, stored, act_) => {
  await mount(stored);
  store.setCompareSelection().mockRejectedValueOnce(new Error("offline"));

  await act(async () => act_());

  expect(await screen.findByText(ALERT)).toBeVisible();
  await userEvent.click(screen.getByRole("button", { name: "Try again" }));
  await waitFor(() => expect(screen.queryByText(ALERT)).toBeNull());
  const sent = store.setCompareSelection().mock.calls.map(([ids]) => ids);
  expect(sent[sent.length - 1]).toEqual(sent[sent.length - 2]); // the same selection, sent again
});

it("says nothing when the selection saved", async () => {
  await mount([1, 2]);
  await act(async () => verbs.clearCompare());
  await act(async () => {});
  expect(screen.queryByText(ALERT)).toBeNull();
});
