import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { useRef } from "react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../../api";
import { COMPARE_CAP, JobWorkspaceProvider, useJobActions, useJobWorkspace } from "../../context/JobWorkspace";
import { jobDetailFixture, jobFixture } from "../../test/fixtures";
import { ToastProvider } from "../../ui/Toast";
import { CompareBeacon } from "./CompareBeacon";
import { JobCard } from "./JobCard";
import { msg } from "../../test/msg";

/* The compare beacon's contract: it exists from two selected roles, level with the row
 * selected LAST, carries the count, goes to Compare on click, and its reveal
 * is the roster — each role removable — with the same next step and Clear.
 * Driven through the real provider and real rows, because "level with the
 * last selected row" is a claim about which element it is anchored to. */

vi.mock("../../api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../../api")>()),
  api: {
    markJobViewed: vi.fn().mockResolvedValue(undefined),
    job: vi.fn(),
    compareSelection: vi.fn().mockResolvedValue({ job_ids: [] }),
    setCompareSelection: vi.fn((jobIds: number[]) => Promise.resolve({ job_ids: jobIds })),
  },
}));

/* The source switch the app has seen (`referenceVersion`): the
 * roster cache outlives the beacon, so a switch must drop its old figures. */
const source = vi.hoisted(() => ({ version: 0 }));
vi.mock("../../context/SyncState", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../../context/SyncState")>()),
  useReferenceVersion: () => source.version,
}));

const rows = [
  { ...jobFixture, id: 1, title: "Staff Product Manager, API" },
  { ...jobFixture, id: 2, title: "Principal Engineering Manager" },
  { ...jobFixture, id: 3, title: "Director, Platform Infrastructure" },
  { ...jobFixture, id: 4, title: "Head of Product, Payments" },
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

function Where() {
  return <span data-testid="where">{useLocation().pathname}</span>;
}

function mount() {
  return render(tree());
}

function tree() {
  return (
    <MemoryRouter initialEntries={["/"]}>
      <ToastProvider>
        <JobWorkspaceProvider>
          <Where />
          <Routes>
            <Route path="/" element={<List />} />
            <Route path="/compare" element={<h1>Compare</h1>} />
          </Routes>
        </JobWorkspaceProvider>
      </ToastProvider>
    </MemoryRouter>
  );
}

/* What the roster fetches for each role: a posting that DISCLOSES pay (it
 * prints a base band) whose comp columns are the app's estimate, a combination
 * the reveal must not label "disclosed". Every test in this
 * file gets the same detail per id, so the module-level roster cache holds
 * the same thing whichever test fetches first. */
const detail = (id: number) =>
  jobDetailFixture({
    ...rows.find((r) => r.id === id)!,
    discloses_pay: true,
    comp_low: 1098952,
    comp_high: 1486817,
    comp_median: 1292885,
    comp_provenance: "Openai L6 reported median (software_engineering)",
    disclosed_comp: {
      disclosed: true,
      base_min: 310000,
      base_max: 460000,
      currency: "USD",
      pay_basis: "base",
      pay_period: "year",
      bonus_pct: null,
      confidence: "high",
      snippet: "The base salary range for this role is $310,000 - $460,000.",
      checked_at: "2026-09-21T00:00:00Z",
      from_pay_field: false,
    },
  });

const row = (title: string) => screen.getByRole("heading", { name: title }).closest("article")!;
const select = (title: string) => fireEvent.click(within(row(title)).getByRole("button", { name: msg("jobs-compare") }));
const beacon = () => screen.queryByRole("button", { name: /in compare/ });

// The board is wide and the pointer hovers: the desktop branch, which is where
// the margin exists. matchMedia in jsdom answers every query with `false`.
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

describe("CompareBeacon", () => {
  beforeEach(() => {
    wideWithHover();
    vi.mocked(api.job).mockImplementation((id: number) => Promise.resolve(detail(id)));
  });
  afterEach(() => {
    vi.restoreAllMocks();
    source.version = 0;
  });

  it("exists from two selected roles, in the margin beside the row selected last, with the count", () => {
    mount();
    select("Staff Product Manager, API");
    expect(beacon()).toBeNull();

    select("Principal Engineering Manager");
    const pill = beacon()!;
    expect(pill).toHaveAccessibleName("2 in compare. Compare 2 roles");
    expect(pill).toHaveTextContent("2");
    // Anchored to the LAST selected row's element, not floating free: the
    // wrapper is positioned from that row, and it is not docked.
    const wrapper = pill.closest(".job-beacon")!;
    expect(wrapper).not.toHaveAttribute("data-docked");

    // Three is the cap (COMPARE_CAP), so the third selection is the
    // one that says so — and a fourth row cannot be added at all.
    select("Director, Platform Infrastructure");
    expect(beacon()).toHaveAccessibleName("3 in compare, full. Compare 3 roles");
    expect(beacon()).toHaveTextContent("full");
    select("Head of Product, Payments");
    expect(beacon()).toHaveAccessibleName("3 in compare, full. Compare 3 roles");
  });

  it("goes to Compare on click, and never opens the row it is beside", () => {
    mount();
    select("Staff Product Manager, API");
    select("Principal Engineering Manager");
    fireEvent.click(beacon()!);
    expect(screen.getByTestId("where")).toHaveTextContent("/compare");
  });

  it("reveals the roster on hover, where a role can be taken out; below two it is gone", async () => {
    mount();
    select("Staff Product Manager, API");
    select("Principal Engineering Manager");
    fireEvent.pointerEnter(beacon()!.closest(".job-beacon")!);
    const reveal = await screen.findByRole("dialog", { name: "In compare" });
    expect(reveal).toHaveTextContent(`In compare · 2 of ${COMPARE_CAP}`);
    await waitFor(() => expect(within(reveal).getByText("Principal Engineering Manager")).toBeInTheDocument());
    expect(within(reveal).getByText("Staff Product Manager, API")).toBeInTheDocument();
    expect(within(reveal).getByRole("button", { name: "Compare 2 roles" })).toBeInTheDocument();

    fireEvent.click(within(reveal).getByRole("button", { name: "Remove Principal Engineering Manager from compare" }));
    // One role is not a comparison: the beacon leaves, and the row's own
    // toggle reads unselected again.
    expect(beacon()).toBeNull();
    expect(within(row("Principal Engineering Manager")).getByRole("button", { name: msg("jobs-compare") })).toBeInTheDocument();
  });

  it("names each role's comp for what it is, the estimate, even when the posting discloses pay", async () => {
    // The reveal's qualifier describes the number beside it. comp_low/high is
    // the app's estimate; `discloses_pay` only says the posting states pay
    // somewhere, and the posted base band is not what the slot shows either.
    mount();
    select("Staff Product Manager, API");
    select("Principal Engineering Manager");
    fireEvent.pointerEnter(beacon()!.closest(".job-beacon")!);
    const reveal = await screen.findByRole("dialog", { name: "In compare" });
    await waitFor(() => expect(reveal.querySelectorAll(".job-reveal-comp")).toHaveLength(2));
    for (const comp of reveal.querySelectorAll(".job-reveal-comp")) {
      expect(comp).toHaveTextContent(/^est\. \$1\.10M–\$1\.49M$/);
    }
    expect(reveal).not.toHaveTextContent(/disclosed/i);
    expect(reveal).not.toHaveTextContent("$310K");
  });

  it("a source switch drops the roster's cached pay: it never shows the old source beside the board", async () => {
    const view = mount();
    select("Staff Product Manager, API");
    select("Principal Engineering Manager");
    const leaf = beacon()!.closest(".job-beacon")!;
    fireEvent.pointerEnter(leaf);
    const reveal = await screen.findByRole("dialog", { name: "In compare" });
    await waitFor(() => expect(reveal.querySelectorAll(".job-reveal-comp")).toHaveLength(2));
    expect(reveal.querySelector(".job-reveal-comp")).toHaveTextContent("$1.10M–$1.49M");

    // The plugin now answers pay; the poll has seen the switch land.
    vi.mocked(api.job).mockImplementation((id: number) => Promise.resolve(
      { ...detail(id), comp_low: 793050, comp_high: 1072950, comp_median: 933000 }));
    source.version = 1;
    view.rerender(tree()); // what the epoch's context change does in the app
    fireEvent.pointerLeave(leaf);
    fireEvent.pointerEnter(leaf);
    const after = await screen.findByRole("dialog", { name: "In compare" });
    await waitFor(() => {
      const comps = [...after.querySelectorAll(".job-reveal-comp")].map((c) => c.textContent);
      expect(comps).toEqual(["est. $793K–$1.07M", "est. $793K–$1.07M"]);
    });
  });

  it("Clear empties the selection with a way back", async () => {
    mount();
    select("Staff Product Manager, API");
    select("Principal Engineering Manager");
    fireEvent.pointerEnter(beacon()!.closest(".job-beacon")!);
    const reveal = await screen.findByRole("dialog", { name: "In compare" });
    fireEvent.click(within(reveal).getByRole("button", { name: "Clear" }));
    expect(beacon()).toBeNull();
    const toast = screen.getByRole("status");
    expect(toast).toHaveTextContent("Cleared 2 roles from compare");
    fireEvent.click(within(toast).getByRole("button", { name: "Undo" }));
    expect(beacon()).toHaveAccessibleName("2 in compare. Compare 2 roles");
  });

  it("docks when the row it belongs to is not on the page", () => {
    mount();
    select("Staff Product Manager, API");
    select("Principal Engineering Manager");
    expect(beacon()!.closest(".job-beacon")).not.toHaveAttribute("data-docked");
    // The anchored row leaves the page (a re-sort, another page): the beacon
    // stays, docked to the edge, because the selection did not change.
    act(() => {
      row("Principal Engineering Manager").remove();
      window.dispatchEvent(new Event("resize"));
    });
    expect(beacon()!.closest(".job-beacon")).toHaveAttribute("data-docked");
  });
});
