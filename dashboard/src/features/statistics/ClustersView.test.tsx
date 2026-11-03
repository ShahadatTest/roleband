import { msg } from "../../test/msg";
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";
import type { ClusterDetail, ClusterSummary } from "../../api";
import { api } from "../../api";
import { jobFixture } from "../../test/fixtures";
import { ClustersView } from "./ClustersView";
import { clusterLabel } from "./names";

vi.mock("../../api", async () => {
  const actual = await vi.importActual<typeof import("../../api")>("../../api");
  return { ...actual, api: { ...actual.api, clusters: vi.fn(), cluster: vi.fn() } };
});

vi.mock("./charts/StatisticsCharts", () => ({
  ClusterLandscapeChart: ({ clusters, onSelect }: {
    clusters: ClusterSummary[];
    onSelect: (id: number) => void;
  }) => <>{clusters.map((cluster) => (
    <button key={cluster.id} onClick={() => onSelect(cluster.id)}>
      Select {clusterLabel(cluster)}
    </button>
  ))}</>,
}));

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((onResolve) => { resolve = onResolve; });
  return { promise, resolve };
}

/* A cluster is named by its strongest skills: "python" reads "Python". */
const summary = (
  id: number,
  term: string,
  companies: Record<string, number> = {},
): ClusterSummary => ({
  id, family_hint: null, size: 1,
  top_terms: [{ term, weight: 1 }], companies,
});

const detail = (id: number, term: string): ClusterDetail => ({
  id, family_hint: null, size: 0,
  top_terms: [{ term, weight: 1 }], items: [],
});

beforeEach(() => vi.clearAllMocks());

it("shows a retryable error instead of spinning forever when clusters fail", async () => {
  vi.mocked(api.clusters).mockRejectedValue(new Error("offline"));
  render(<ClustersView onOpen={vi.fn()} />);

  expect(await screen.findByRole("alert")).toHaveTextContent(msg("insights-clusters-view-load-failed"));
  expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();
});

it("ignores an older detail response after another cluster is selected", async () => {
  const alpha = deferred<ClusterDetail>();
  const beta = deferred<ClusterDetail>();
  vi.mocked(api.clusters).mockResolvedValue({
    items: [summary(1, "python"), summary(2, "rust")], model_version: "v1",
  });
  vi.mocked(api.cluster).mockImplementation((id: number) => id === 1 ? alpha.promise : beta.promise);
  render(<ClustersView onOpen={vi.fn()} />);

  fireEvent.click(await screen.findByRole("button", { name: "Select Python" }));
  fireEvent.click(screen.getByRole("button", { name: "Select Rust" }));
  await act(async () => beta.resolve(detail(2, "rust")));
  const panel = document.querySelector(".cluster-detail") as HTMLElement;
  expect(within(panel).getByRole("heading", { name: "Rust" })).toBeInTheDocument();

  await act(async () => alpha.resolve(detail(1, "python")));
  expect(within(panel).getByRole("heading", { name: "Rust" })).toBeInTheDocument();
  expect(within(panel).queryByRole("heading", { name: "Python" })).toBeNull();
});

/* A cluster card is a whole-card control that also carries company chips, and a
   CompanyChip is a real <button>: its keyboard path to the profile is the
   accessible half of a hover card that is otherwise pointer-only. So the card's
   own control and the chips have to be SIBLINGS. Nesting them is invalid HTML:
   the browser reparents it, the inner control is unreachable by keyboard in
   some engines, and assistive tech announces the pair inconsistently. React
   only warns in the console, so nothing else fails. */
it("never nests one interactive control inside another", async () => {
  vi.mocked(api.clusters).mockResolvedValue({
    items: [summary(1, "python", { anthropic: 3, openai: 1 })],
    model_version: "v1",
  });
  const { container } = render(
    <MemoryRouter>
      <ClustersView onOpen={vi.fn()} />
    </MemoryRouter>,
  );
  // The card's label and its skill chip both read "Python".
  await screen.findAllByText("Python");

  // Every pairing, not just button-in-button: an anchor inside a button is the
  // same defect and reads the same way to the platform.
  const nested = [...container.querySelectorAll("button button, button a, a button, a a")];
  expect(
    nested.map((el) => `${el.tagName.toLowerCase()}.${el.className}`),
    "an interactive control is inside another one. The card's control and its " +
      "chips must be siblings — see ClustersView's stretched card control.",
  ).toEqual([]);
});

it("selects a cluster from its card control, and leaves the chip a control of its own", async () => {
  vi.mocked(api.clusters).mockResolvedValue({
    items: [summary(1, "python", { anthropic: 3 })],
    model_version: "v1",
  });
  vi.mocked(api.cluster).mockResolvedValue(detail(1, "python"));
  render(
    <MemoryRouter>
      <ClustersView onOpen={vi.fn()} />
    </MemoryRouter>,
  );

  // The card is one control with an accessible name and a pressed state, so
  // the selection is announced, not only painted. Exact name:
  // the landscape chart's own select button is "Select Python", and a card whose
  // name merely CONTAINS the label would not distinguish them.
  const card = await screen.findByRole("button", { name: "Python" });
  expect(card).toHaveAttribute("aria-pressed", "false");
  fireEvent.click(card);
  expect(screen.getByRole("button", { name: "Python" })).toHaveAttribute("aria-pressed", "true");

  // The chip is still its own control with its own name. That it actually
  // REACHES the company is a browser fact (it depends on stacking, which jsdom
  // does not compute) and lives in tests/ux/statistics.spec.ts.
  expect(screen.getByRole("button", { name: /view company profile/i })).toBeInTheDocument();
});

/* A member's caption is its own listed age (`listed_days`), the age
   its Board row and Job detail show. `days_open` is our first-sighting clock:
   a posting its employer dated 170 days ago that we first saw 3 days ago is
   listed for 170 days, and never reads "3 days open". */
it("captions each member with its listed age, never our first-sighting clock", async () => {
  vi.mocked(api.clusters).mockResolvedValue({ items: [summary(1, "python")], model_version: "v1" });
  vi.mocked(api.cluster).mockResolvedValue({
    ...detail(1, "python"),
    size: 1,
    items: [{
      ...jobFixture, id: 7, company: "anthropic", title: "Staff Product Manager, Claude",
      days_open: 3, listed_days: 170,
    }],
  });
  render(
    <MemoryRouter>
      <ClustersView onOpen={vi.fn()} />
    </MemoryRouter>,
  );
  fireEvent.click(await screen.findByRole("button", { name: "Select Python" }));

  const row = await screen.findByRole("link", { name: /Staff Product Manager, Claude/ });
  expect(row).toHaveTextContent("Anthropic · Listed for 170 days");
  expect(row).not.toHaveTextContent(/\bopen\b/i);
});

it("names a group's eight leading companies and counts the rest in one line", async () => {
  // A card listing every company down to its one role runs to hundreds of chips.
  const companies = Object.fromEntries(Array.from({ length: 12 }, (_, i) => [`co-${i}`, 20 - i]));
  vi.mocked(api.clusters).mockResolvedValue({ items: [summary(1, "Platform PM", companies)], model_version: "t" });
  render(<MemoryRouter><ClustersView onOpen={vi.fn()} /></MemoryRouter>);
  const card = (await screen.findByRole("button", { name: "Platform PM" })).closest(".cluster-card") as HTMLElement;
  expect(card.querySelectorAll(".cluster-co")).toHaveLength(8);
  expect(within(card).getByText("and 4 more companies")).toBeInTheDocument();
  // The leaders, largest first: the four smallest are the ones folded.
  expect(within(card).queryByText("co-11")).toBeNull();
  expect(screen.getByRole("heading", { level: 2, name: "1 role group" })).toBeInTheDocument();
});

it("shows a member with only a base estimate as a base estimate", async () => {
  // Fail-first: the member printed fmtComp(comp_median), a bare dash.
  vi.mocked(api.clusters).mockResolvedValue({ items: [summary(1, "python")], model_version: "v1" });
  vi.mocked(api.cluster).mockResolvedValue({
    ...detail(1, "python"), size: 1,
    items: [{ ...jobFixture, id: 5, comp_low: null, comp_high: null, comp_median: null, comp_base_median: 180_000 }],
  });
  render(<ClustersView onOpen={vi.fn()} />);
  fireEvent.click(await screen.findByRole("button", { name: "Select Python" }));
  expect(await screen.findByText(msg("shared-pay-est-base", { range: "$180K" }))).toBeInTheDocument();
});
