import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { DEFAULT_FILTERS, Facets } from "../../api";
import { facetsFixture } from "../../test/fixtures";
import { BoardFilters, PAY_SETTLE_MS } from "./BoardFilters";
import { RESET_FILTERS, boardMode, countActiveFilters } from "./filters";
import { msg } from "../../test/msg";

/* The filter register's behavior contracts: every facet emits its patch,
 * select-all/clear-all exist, reset (from the toolbar) clears lenses along
 * with filters, and active state is VISIBLE: checked rows on screen, a count
 * on the group title, and no selection ever folded out of sight.
 */

const renderFilters = (overrides: Partial<Parameters<typeof BoardFilters>[0]> = {}) => {
  const update = vi.fn();
  const onModeChange = vi.fn();
  render(
    <BoardFilters
      facets={facetsFixture}
      filters={DEFAULT_FILTERS}
      update={update}
      mode={boardMode(overrides.filters ?? DEFAULT_FILTERS)}
      onModeChange={onModeChange}
      {...overrides}
    />,
  );
  return { update, onModeChange };
};

/** Every group of the register rests CLOSED, so a test that reaches for a
 *  row opens its group first: the two clicks a reader makes. `name` is the head's accessible name, counted when active. */
const openGroup = (user: ReturnType<typeof userEvent.setup>, name: string) =>
  user.click(screen.getByRole("button", { name }));

/** A facets fixture with `extra` synthetic companies beyond the two real ones. */
const manyCompanies = (extra: number): Facets => {
  const companies = { ...facetsFixture.companies } as Facets["companies"];
  const counts = { ...facetsFixture.counts.company } as Record<string, number>;
  for (let i = 0; i < extra; i++) {
    companies[`co_${i}`] = { display: `Synth Co ${i}` };
    counts[`co_${i}`] = 10 + i;
  }
  return { ...facetsFixture, companies, counts: { ...facetsFixture.counts, company: counts } };
};

describe("the board filter register", () => {
  /* The register in two tiers. What a reader narrows by every
     session is on screen; what answers one question waits behind one door
     that still says how many of its filters are on. Twelve groups at one
     weight would make this column read as a wall. */
  it("puts the always-tier on screen and everything situational behind one door", async () => {
    const user = userEvent.setup();
    renderFilters();
    for (const name of ["Filter by company", "Filter by location", "Filter by level"]) {
      expect(screen.getByRole("group", { name })).toBeInTheDocument();
    }

    const door = screen.getByRole("button", { name: "More filters" });
    expect(door).toHaveAttribute("aria-expanded", "false");
    for (const name of ["Filter by world", "Filter by workplace", "Filter by career track",
      "Filter by discipline", msg("radar-filter-listed-within")]) {
      expect(screen.queryByRole("group", { name })).toBeNull();
    }
    // The comp pair sits behind the door TOGETHER: half a filter on screen and
    // half behind a door would make a reader setting a range meet the same
    // control in two places.
    expect(screen.queryByLabelText("Minimum comp")).toBeNull();
    expect(screen.queryByLabelText("Maximum comp")).toBeNull();
    expect(screen.queryByLabelText("Discloses pay")).toBeNull();

    // Opened, every one of them is there: the tiers rank groups, never drop them.
    await user.click(door);
    for (const name of ["Filter by world", "Filter by workplace", "Filter by career track",
      "Filter by discipline", msg("radar-filter-listed-within")]) {
      expect(screen.getByRole("group", { name })).toBeInTheDocument();
    }
    for (const label of [msg("radar-filter-discloses-pay"), msg("radar-filter-pay-min-aria"), msg("radar-filter-pay-max-aria")]) {
      expect(screen.getByLabelText(label)).toBeInTheDocument();
    }
  });

  it("opens the door on its own when something inside is narrowing the list", () => {
    // A register may fold OPTIONS away and may never fold STATE away: a count
    // on a closed door says something is filtering without saying what.
    renderFilters({ filters: { ...DEFAULT_FILTERS, posted_within_days: 7, domain: ["ai_ml"] } });
    const door = screen.getByRole("button", { name: "More filters · 2" });
    expect(door).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("group", { name: msg("radar-filter-listed-within") })).toBeInTheDocument();
    expect(screen.getByLabelText("AI & Machine Learning")).toBeChecked();
  });

  it("asks for a typed pay floor once the typing settles, not once per digit", () => {
    vi.useFakeTimers();
    try {
      // A ceiling already set opens the door the floor sits behind.
      const { update } = renderFilters({ filters: { ...DEFAULT_FILTERS, base_max: 900000 } });
      const floor = screen.getByLabelText(msg("radar-filter-pay-min-aria"));
      for (const typed of ["2", "25", "250", "2500", "25000", "250000"]) {
        fireEvent.change(floor, { target: { value: typed } });
        act(() => { vi.advanceTimersByTime(100); });
      }
      expect(update).not.toHaveBeenCalled();
      act(() => { vi.advanceTimersByTime(PAY_SETTLE_MS); });
      expect(update.mock.calls).toEqual([[{ base_min: 250000, offset: 0 }]]);
    } finally {
      vi.useRealTimers();
    }
  });

  it("titles the pay pair Base, the column it bounds, and spells it out on hover", () => {
    renderFilters({ filters: { ...DEFAULT_FILTERS, base_max: 900000 } });
    expect(screen.getByText("Base from").closest("abbr")).toHaveAttribute("title", "Base salary from");
    expect(screen.getByText("Base up to").closest("abbr")).toHaveAttribute("title", "Base salary up to");
    expect(screen.queryByText(/Est\. TC/)).toBeNull();
  });

  it("asks for a typed pay ceiling at once on Enter, and clears it when emptied", () => {
    const { update } = renderFilters({ filters: { ...DEFAULT_FILTERS, base_max: 900000 } });
    const ceiling = screen.getByLabelText(msg("radar-filter-pay-max-aria"));
    fireEvent.change(ceiling, { target: { value: "300000" } });
    fireEvent.keyDown(ceiling, { key: "Enter" });
    expect(update).toHaveBeenLastCalledWith({ base_max: 300000, offset: 0 });
    fireEvent.change(ceiling, { target: { value: "" } });
    fireEvent.blur(ceiling);
    expect(update).toHaveBeenLastCalledWith({ base_max: null, offset: 0 });
  });

  it("counts the comp pair once on the door, floor or ceiling or both", () => {
    /* Both halves are behind the door, and they are ONE filter
       (`group: "comp"`). A floor alone has to COUNT: the drawer may fold
       options away and may never fold state away. And a floor AND a ceiling
       must still say one, or the door reads "· 2" under a summary reading
       "Filters · 1" and two numbers describe one filter. */
    renderFilters({ filters: { ...DEFAULT_FILTERS, base_min: 500000 } });
    expect(screen.getAllByRole("button", { name: "More filters · 1" }).length).toBeGreaterThan(0);
    cleanup();
    renderFilters({ filters: { ...DEFAULT_FILTERS, base_max: 900000 } });
    expect(screen.getAllByRole("button", { name: "More filters · 1" }).length).toBeGreaterThan(0);
    cleanup();
    renderFilters({ filters: { ...DEFAULT_FILTERS, base_min: 500000, base_max: 900000 } });
    expect(screen.getAllByRole("button", { name: "More filters · 1" }).length).toBeGreaterThan(0);
  });

  it("keeps segmented controls for genuine one-ofs only, and none at the head of the column", async () => {
    // A boolean or a mode wearing a 36px bordered track is not a segmented
    // control. The register keeps two, both real exclusive choices, and both
    // behind the door.
    const user = userEvent.setup();
    renderFilters();
    expect(screen.queryByRole("group", { name: msg("radar-filter-listed-within") })).toBeNull();
    expect(document.querySelectorAll(".ui-seg")).toHaveLength(0);

    await user.click(screen.getByRole("button", { name: "More filters" }));
    const tracks = screen.getAllByRole("group").filter((g) => g.classList.contains("ui-seg"));
    expect(tracks.map((g) => g.getAttribute("aria-label"))).toEqual([msg("radar-filter-listed-within"), "Showing"]);
  });

  /* The MODE, last and lowest. Open roles IS the board — its count is the top
     bar's, and that count is the link back — so Closed and Not-for-me belong
     at the foot of the drawer a reader opens on purpose, never in a strip
     above every list. No segmented lens sits at the TOP of the column
     ("Status", "Visibility"). */
  it("holds the mode at the foot of the drawer, and never at the head of the column", async () => {
    const user = userEvent.setup();
    renderFilters();
    for (const name of ["Status", "Visibility", "Show"]) {
      expect(screen.queryByRole("group", { name })).toBeNull();
    }
    expect(screen.queryByRole("group", { name: "Showing" })).toBeNull();

    await user.click(screen.getByRole("button", { name: "More filters" }));
    const showing = screen.getByRole("group", { name: "Showing" });
    // Last in the drawer: everything that narrows the open board comes first.
    const groups = screen.getAllByRole("group");
    expect(groups[groups.length - 1]).toBe(showing);
  });

  it("makes the three populations exclusive by construction, and names the default first", async () => {
    const user = userEvent.setup();
    const { update, onModeChange } = renderFilters();
    await user.click(screen.getByRole("button", { name: "More filters" }));
    const showing = screen.getByRole("group", { name: "Showing" });
    expect(within(showing).getAllByRole("button").map((b) => b.textContent))
      .toEqual(["Open", "Closed", "Not for me"]);
    expect(within(showing).getByRole("button", { name: "Open" })).toHaveAttribute("aria-pressed", "true");

    // One control, one value: picking Closed cannot leave the bin on, which
    // two independent switches would have allowed.
    await user.click(within(showing).getByRole("button", { name: "Not for me" }));
    // Through the ROUTE, never `update`: the mode is URL state and has exactly
    // one writer, so it cannot oscillate.
    expect(onModeChange).toHaveBeenCalledWith("dismissed");
    expect(update).not.toHaveBeenCalled();
  });

  it("opens the drawer on its own when the reader is not on the open board", () => {
    // The state-never-hides rule, applied to the mode: a closed door reading
    // "More filters · 1" over a list of closed roles explains nothing.
    renderFilters({ filters: { ...DEFAULT_FILTERS, ...{ status: "closed", dismissed_only: false } } });
    expect(screen.getByRole("button", { name: "More filters · 1" })).toHaveAttribute("aria-expanded", "true");
    expect(within(screen.getByRole("group", { name: "Showing" })).getByRole("button", { name: "Closed" }))
      .toHaveAttribute("aria-pressed", "true");
  });

  /* Rank is an ORDER, not an open state. Resting Company, Location and Level
     open would save clicks for a facet in constant use, and cost every reader
     who does not filter by company three open lists above the fold. A default is a
     guess about a reader — so the register guesses nothing, and remembers
     each reader's own answer instead. */
  it("rests every group closed, whichever tier it is in", async () => {
    const user = userEvent.setup();
    const { update } = renderFilters();
    for (const name of ["Company", "Location", "Level", "More filters"]) {
      expect(screen.getByRole("button", { name })).toHaveAttribute("aria-expanded", "false");
    }
    // Nothing chosen, so a closed group offers nothing — not one row.
    for (const label of ["Silicon Valley", "Staff", "OpenAI", "Management / Leadership"]) {
      expect(screen.queryByLabelText(label)).toBeNull();
    }

    // The rows are one click away, and the ORDER is untouched: the facets a
    // reader narrows by every session still lead the column.
    await openGroup(user, "Location");
    expect(screen.getByRole("button", { name: "Location" })).toHaveAttribute("aria-expanded", "true");
    await user.click(screen.getByLabelText("Silicon Valley"));
    expect(update).toHaveBeenCalledWith({ location_group: ["silicon_valley"], offset: 0 });
  });

  /* The other half of "collapsed by default": a reader who opens Company does
     not open it again tomorrow. The default is a guess; this is their answer,
     and it outlives the mount (hooks/useFilterMemory). */
  it("remembers which groups this reader opened, across a remount", async () => {
    const user = userEvent.setup();
    const { unmount } = render(
      <BoardFilters
        facets={facetsFixture}
        filters={DEFAULT_FILTERS}
        update={vi.fn()}
        mode="open"
        onModeChange={vi.fn()}
      />,
    );
    await openGroup(user, "Company");
    expect(screen.getByLabelText("OpenAI")).toBeInTheDocument();
    unmount();

    renderFilters();
    expect(screen.getByRole("button", { name: "Company" })).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByLabelText("OpenAI")).toBeInTheDocument();
    // And only that one: closing is remembered as such, never as "untouched",
    // so the rest of the column is still at its default.
    expect(screen.getByRole("button", { name: "Location" })).toHaveAttribute("aria-expanded", "false");
  });

  it("emits the level filter with human band labels", async () => {
    const user = userEvent.setup();
    const { update } = renderFilters();
    await openGroup(user, "Level");
    await user.click(screen.getByLabelText("Staff"));
    expect(update).toHaveBeenCalledWith({ level_band: ["staff"], offset: 0 });
  });

  it("offers roles whose level isn't stated as their own option, after the rungs, never as Mid-level", async () => {
    // The server counts them under "unstated"; their stored band is Mid for
    // sorting only, so they must never show as Mid-level.
    const user = userEvent.setup();
    const facets = {
      ...facetsFixture,
      counts: { ...facetsFixture.counts, level_band: { principal: 4, mid: 2, unstated: 7 } },
    };
    const { update } = renderFilters({ facets });
    await openGroup(user, "Level");
    const group = screen.getByRole("group", { name: "Filter by level" });
    const labels = within(group).getAllByRole("checkbox").map((box) => box.closest("label")?.textContent ?? "");
    expect(labels).toEqual([
      expect.stringContaining("Principal"),
      expect.stringContaining("Mid-level"),
      expect.stringContaining("Level not placed"),
    ]);
    expect(labels[2]).toContain("7");
    expect(labels[1]).toContain("2");
    await user.click(screen.getByLabelText("Level not placed"));
    expect(update).toHaveBeenCalledWith({ level_band: ["unstated"], offset: 0 });
  });

  it("renders companies from the tracked list, never from the counts map", async () => {
    // `counts.company` carries `hidden_co` (a hidden company's open jobs are
    // still grouped), so rendering from counts would list it.
    const user = userEvent.setup();
    renderFilters();
    await openGroup(user, "Company");
    expect(screen.queryByLabelText("hidden_co")).toBeNull();
    expect(screen.getByLabelText("OpenAI")).toBeInTheDocument();
    expect(screen.getByLabelText("Amazon")).toBeInTheDocument();
  });

  /* An option that cannot narrow is noise in a column whose whole job is
     narrowing. In the fixture `united_states` counts every role on the board,
     so choosing it would change nothing, and a facet that visibly does nothing
     teaches the reader to stop using facets. */
  it("drops a location that matches the whole board, and raises its orphans", async () => {
    const user = userEvent.setup();
    renderFilters();
    await openGroup(user, "Location");
    expect(screen.queryByLabelText("United States")).toBeNull();
    // Its two metros survive at the TOP level, since the parent they nest
    // under is not offered.
    for (const metro of ["Silicon Valley", "New York"]) {
      expect(screen.getByLabelText(metro)).toBeInTheDocument();
      expect(screen.getByLabelText(metro).closest(".check-row")).not.toHaveClass("is-child");
    }
  });

  it("offers every location when no total was sent: no number, no claim", async () => {
    // An older backend, or a partial response. `count < undefined` is false for
    // every group, so comparing against a missing total would drop the entire
    // facet.
    const user = userEvent.setup();
    const { total: _dropped, ...withoutTotal } = facetsFixture;
    renderFilters({ facets: withoutTotal as Facets });
    await openGroup(user, "Location");
    expect(screen.getByLabelText("United States")).toBeInTheDocument();
    expect(screen.getByLabelText("Silicon Valley")).toBeInTheDocument();
  });

  it("nests a metro under the country it belongs to, by position and nothing else", async () => {
    const user = userEvent.setup();
    const facets: Facets = {
      ...facetsFixture,
      total: 9,
      counts: { ...facetsFixture.counts, location_group: { silicon_valley: 1, new_york: 2, united_states: 4 } },
    };
    renderFilters({ facets });
    await openGroup(user, "Location");
    // Here `united_states` (4) narrows a 9-role board, so it is offered, and
    // its metros indent under it.
    expect(screen.getByLabelText("United States").closest(".check-row")).not.toHaveClass("is-child");
    expect(screen.getByLabelText("Silicon Valley").closest(".check-row")).toHaveClass("is-child");
  });

  it("selects a whole group from the expanded Select all, sorted selected-first then by count", async () => {
    const user = userEvent.setup();
    const facets: Facets = {
      ...facetsFixture,
      total: 9,
      location_groups: { silicon_valley: { display: "Silicon Valley", parent: null }, uk: { display: "UK", parent: null } },
      counts: { ...facetsFixture.counts, location_group: { silicon_valley: 1, uk: 2 } },
    };
    const { update } = renderFilters({ facets });
    await openGroup(user, "Location");
    await user.click(screen.getByRole("button", { name: "Select all Location" }));
    expect(update).toHaveBeenCalledWith({ location_group: ["uk", "silicon_valley"], offset: 0 });
  });

  it("wears active state while collapsed: checked row, counted headline, per-group clear", async () => {
    const user = userEvent.setup();
    const { update } = renderFilters({
      filters: { ...DEFAULT_FILTERS, family: ["product_management"] },
    });
    // The register's non-negotiable, asserted on a facet that still RESTS
    // collapsed: the chosen row is visible and checked with nothing expanded
    // by hand, and the unchosen types are not. The door above it opened
    // itself, which is the same rule one level up.
    expect(screen.getByLabelText("Product Management")).toBeChecked();
    expect(screen.queryByLabelText("Program Management")).toBeNull();
    const group = screen.getByRole("group", { name: "Filter by discipline" });
    expect(within(group).getByRole("button", { name: "Discipline · 1" })).toHaveAttribute(
      "aria-expanded",
      "false"
    );
    await user.click(within(group).getByRole("button", { name: "clear" }));
    expect(update).toHaveBeenCalledWith({ family: [], offset: 0 });
  });

  it("expands to the full list with a search row on the long facets", async () => {
    const user = userEvent.setup();
    renderFilters({
      facets: manyCompanies(9),
      filters: { ...DEFAULT_FILTERS, company: ["openai"] },
    });
    // Opened, it folds to five: the selection first, then by count.
    await openGroup(user, "Company · 1");
    const group = screen.getByRole("group", { name: "Filter by company" });
    expect(screen.getByLabelText("OpenAI")).toBeChecked();
    expect(within(group).getAllByRole("checkbox")).toHaveLength(5);
    expect(screen.queryByLabelText("Synth Co 3")).toBeNull();

    // Long facets grow a search row that narrows the WHOLE list, past the fold.
    await user.type(screen.getByLabelText("Search company"), "Synth Co 3");
    expect(screen.getByLabelText("Synth Co 3")).toBeInTheDocument();
    expect(screen.queryByLabelText("Amazon")).toBeNull();

    // Collapsing folds it back to the selection and forgets the query.
    await user.click(screen.getByRole("button", { name: "Company · 1" }));
    expect(screen.queryByLabelText("Synth Co 3")).toBeNull();
    expect(screen.getByLabelText("OpenAI")).toBeChecked();
  });

  /* The fold: a facet in constant use shows the head of its list, not all of
     it — and never hides what the reader has already chosen. */
  it("folds a long open facet, names how many are left, and unfolds to all of them", async () => {
    const user = userEvent.setup();
    renderFilters({ facets: manyCompanies(9) });
    await openGroup(user, "Company");
    const more = screen.getByRole("button", { name: "Show all company" });
    expect(more).toHaveTextContent("+ 6 more");
    await user.click(more);
    expect(screen.getByLabelText("Synth Co 8")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Show all company" })).toBeNull();
  });

  it("grows the fold rather than hiding a chosen row", () => {
    // Seven chosen out of eleven, with a fold of five: a register that folds
    // away its own state is the one thing this column may not do.
    const chosen = ["co_0", "co_1", "co_2", "co_3", "co_4", "co_5", "co_6"];
    renderFilters({ facets: manyCompanies(9), filters: { ...DEFAULT_FILTERS, company: chosen } });
    for (const slug of chosen) {
      expect(screen.getByLabelText(`Synth Co ${slug.slice(3)}`)).toBeChecked();
    }
  });

  it("emits the role-kind (track) refinement from behind the door", async () => {
    const user = userEvent.setup();
    const { update } = renderFilters();
    await user.click(screen.getByRole("button", { name: "More filters" }));
    await openGroup(user, "Career track");
    await user.click(screen.getByLabelText("Management / Leadership"));
    expect(update).toHaveBeenCalledWith({ track: ["management"], offset: 0 });
  });

  it("carries no head row: the undo lives in the toolbar, so nothing here ever shifts", () => {
    renderFilters({ filters: { ...DEFAULT_FILTERS, level_band: ["staff"] } });
    expect(screen.queryByRole("button", { name: "Reset all" })).toBeNull();
  });
});

/* The reader's own mark: one boolean,
 * first in the register, on the app's one boolean control. A lens is one
 * active filter, and Reset all takes it back with the rest — the register's
 * contract that no selection hides. */
describe("the Unread lens", () => {
  it("leads the register as one switch, and emits the viewed patch both ways", async () => {
    const { update } = renderFilters();
    const unread = screen.getByRole("checkbox", { name: "Unread only" });
    expect(unread).not.toBeChecked();
    // First in the column, above every facet: the reader's own mark leads.
    const firstGroupHead = screen.getAllByRole("group")[0];
    expect(unread.compareDocumentPosition(firstGroupHead) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();

    await userEvent.click(unread);
    expect(update).toHaveBeenCalledWith({ viewed: "unread", offset: 0 });
  });

  it("switches back off to the empty lens, never to read", () => {
    // Both positions are things a reader asked for; "read" is neither of them.
    const { update } = renderFilters({ filters: { ...DEFAULT_FILTERS, viewed: "unread" } });
    const on = screen.getByRole("checkbox", { name: "Unread only" });
    expect(on).toBeChecked();
    fireEvent.click(on);
    expect(update).toHaveBeenCalledWith({ viewed: "", offset: 0 });
  });

  it("offers no read-only position: a non-choice in the loudest control is not a lens", () => {
    // A three-way All / Unread / Read control would rest on its default, and
    // "Read" answers a question nobody asks while hunting. The API keeps
    // `viewed=read`; the register does not offer it.
    renderFilters({ filters: { ...DEFAULT_FILTERS, viewed: "read" } });
    expect(screen.queryByRole("group", { name: "Show" })).toBeNull();
    for (const label of ["All", "Read"]) {
      expect(screen.queryByRole("button", { name: label })).toBeNull();
    }
    // A `read` lens set from elsewhere leaves the switch honestly OFF rather
    // than claiming the list is showing unread roles.
    expect(screen.getByRole("checkbox", { name: "Unread only" })).not.toBeChecked();
  });

  it("counts as one filter, and the reset patch takes it back", () => {
    const filters = { ...DEFAULT_FILTERS, viewed: "unread" as const };
    expect(countActiveFilters(filters, { newSignalsOnly: false, repostsOnly: false })).toBe(1);
    renderFilters({ filters });
    expect(screen.getByRole("checkbox", { name: "Unread only" })).toBeChecked();
    expect(RESET_FILTERS).toEqual(expect.objectContaining({ viewed: "" }));
  });

  /* "Not for me" is the reader's strongest mark, and it is a different LIST,
   * so it is not a lens on this one; and it is a list a reader visits rarely,
   * so it is not a permanent strip either. It is the last choice in the
   * drawer. */
  it("does not force the reader's own mark off when they step into another population", () => {
    // The two request keys are separate controls, so neither clears the other:
    // you can ask for the unread roles inside your own bin.
    renderFilters({ filters: { ...DEFAULT_FILTERS, dismissed_only: true, status: "", viewed: "unread" } });
    expect(screen.queryByRole("group", { name: "Show" })).toBeNull();
    expect(screen.getByRole("checkbox", { name: "Unread only" })).toBeChecked();
  });

  it("a mode IS a filter again: counted once, and Reset all takes it back to open", () => {
    // A tab would be uncounted and survive Reset all. In the register the
    // mode is neither.
    const lenses = { newSignalsOnly: false, repostsOnly: false };
    expect(countActiveFilters({ ...DEFAULT_FILTERS, status: "closed" }, lenses)).toBe(1);
    expect(countActiveFilters({ ...DEFAULT_FILTERS, status: "", dismissed_only: true }, lenses)).toBe(1);
    // Reset all clears it through the route, not through this patch: the mode
    // is URL state with exactly one writer.
    expect(RESET_FILTERS).not.toHaveProperty("status");
  });
});

/* This component renders nothing without `facets`, so a failed fetch has to
 * surface as a message with a retry, or the entire register vanishes with no
 * way to get it back. */
describe("the register when its vocabulary will not load", () => {
  it("says so and offers a retry instead of disappearing", async () => {
    const onRetryFacets = vi.fn();
    render(
      <BoardFilters
        facets={null}
        facetsError={new Error("offline")}
        onRetryFacets={onRetryFacets}
        filters={DEFAULT_FILTERS}
        update={vi.fn()}
        mode="open"
        onModeChange={vi.fn()}
      />,
    );
    expect(screen.getByRole("alert")).toHaveTextContent(msg("radar-filters-load-failed"));
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(onRetryFacets).toHaveBeenCalledTimes(1);
  });

  it("still renders nothing while the vocabulary is merely on its way", () => {
    const { container } = render(
      <BoardFilters facets={null} filters={DEFAULT_FILTERS} update={vi.fn()} mode="open" onModeChange={vi.fn()} />,
    );
    // Loading is not failure: no alert, and no half-built register either.
    expect(container).toBeEmptyDOMElement();
  });
});
