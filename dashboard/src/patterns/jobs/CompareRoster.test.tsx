import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { useRef } from "react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError, api } from "../../api";
import { JobWorkspaceProvider, useJobActions, useJobWorkspace } from "../../context/JobWorkspace";
import { jobDetailFixture, jobFixture } from "../../test/fixtures";
import { ToastProvider } from "../../ui/Toast";
import { CompareBeacon } from "./CompareBeacon";
import { JobCard } from "./JobCard";
import { msg } from "../../test/msg";

/* A role that is GONE.
 *
 * The pill's count comes from the selection; its roster comes from one fetch
 * per role. Two sources, so they can disagree: a role dropped silently leaves
 * "3 in compare" over a roster of two.
 *
 * Its own file, not a case in CompareBeacon.test: the roster cache is
 * module-level and never cleared, so a sibling test that already fetched these
 * ids would make the fetch under test never run at all — and the assertion
 * would pass for the wrong reason.
 */

vi.mock("../../api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../../api")>()),
  api: {
    markJobViewed: vi.fn().mockResolvedValue(undefined),
    job: vi.fn(),
    compareSelection: vi.fn().mockResolvedValue({ job_ids: [] }),
    setCompareSelection: vi.fn((jobIds: number[]) => Promise.resolve({ job_ids: jobIds })),
  },
}));

const rows = [
  { ...jobFixture, id: 11, title: "Staff Product Manager, API" },
  { ...jobFixture, id: 12, title: "Principal Engineering Manager" },
  { ...jobFixture, id: 13, title: "Director, Platform Infrastructure" },
];

function List() {
  const host = useRef<HTMLDivElement>(null);
  const { compareIds, compareFull } = useJobWorkspace();
  const { toggleCompare } = useJobActions();
  return (
    <div ref={host} className="job-margin-host">
      {rows.map((job) => (
        <JobCard
          key={job.id}
          job={job}
          onOpen={() => {}}
          onToggleFav={() => {}}
          compareOn={compareIds.has(job.id)}
          onToggleCompare={() => toggleCompare(job.id)}
          compareDisabled={compareFull}
        />
      ))}
      <CompareBeacon host={host} />
    </div>
  );
}

const row = (title: string) => screen.getByRole("heading", { name: title }).closest("article")!;
const select = (title: string) =>
  fireEvent.click(within(row(title)).getByRole("button", { name: msg("jobs-compare") }));
const beacon = () => screen.queryByRole("button", { name: /in compare/ });

function mount() {
  return render(
    <MemoryRouter initialEntries={["/"]}>
      <ToastProvider>
        <JobWorkspaceProvider>
          <List />
        </JobWorkspaceProvider>
      </ToastProvider>
    </MemoryRouter>,
  );
}

/** The desktop branch, where the margin exists. jsdom answers every query false. */
function wideWithHover() {
  vi.spyOn(window, "matchMedia").mockImplementation((query: string) => ({
    matches: /min-width: 1100px|hover: hover/.test(query),
    media: query,
    onchange: null,
    addEventListener: () => {},
    removeEventListener: () => {},
    addListener: () => {},
    removeListener: () => {},
    dispatchEvent: () => false,
  }));
}

const selectThree = () => {
  select("Staff Product Manager, API");
  select("Principal Engineering Manager");
  select("Director, Platform Infrastructure");
};

beforeEach(() => {
  vi.clearAllMocks();
  wideWithHover();
});

describe("the compare count cannot outlive the roles it counts", () => {
  it("stops counting a role the server says does not exist", async () => {
    vi.mocked(api.job).mockImplementation((id: number) =>
      id === 12
        ? Promise.reject(new ApiError("job not found", 404))
        : Promise.resolve(jobDetailFixture(rows.find((r) => r.id === id)!)),
    );
    mount();
    selectThree();
    expect(beacon()).toHaveAccessibleName(/^3 in compare/);

    await waitFor(() => expect(beacon()).toHaveAccessibleName(/^2 in compare/));
    // And the row itself agrees it is out of the comparison.
    expect(
      within(row("Principal Engineering Manager")).getByRole("button", { name: msg("jobs-compare") }),
    ).toHaveAttribute("aria-pressed", "false");
    // The eviction is durable too, or the reload would bring the ghost back.
    expect(vi.mocked(api.setCompareSelection)).toHaveBeenLastCalledWith([11, 13]);
  });

  it("keeps a role when the request merely failed", async () => {
    // A 500 or a dropped connection is not evidence the role is gone. Evicting
    // on one would silently delete the user's selection because the API
    // hiccuped.
    vi.mocked(api.job).mockImplementation((id: number) =>
      id === 12
        ? Promise.reject(new ApiError("boom", 500))
        : Promise.resolve(jobDetailFixture(rows.find((r) => r.id === id)!)),
    );
    mount();
    selectThree();

    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(beacon()).toHaveAccessibleName(/^3 in compare/);
  });
});
