import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { DEFAULT_FILTERS } from "../../api";
import { facetsFixture } from "../../test/fixtures";
import { BoardFilters } from "./BoardFilters";
import { BoardToolbar } from "./BoardToolbar";
import { boardMode } from "./filters";
import { msg } from "../../test/msg";

/* The docked toolbar: search + count + lens chips + sort, plus (below rail
 * widths) the "Filters · N" opener over the same register the rail shows. The search
 * input's STATE lives in AppState (the shell's "/" shortcut reaches it through
 * boardSearchRef), so the context is mocked to the two fields this component
 * reads. */

const setSearch = vi.fn();
const boardSearchRef = { current: null };
vi.mock("../../context/MissionState", () => ({
  useBoardQuery: () => ({ search: "" }),
  useMissionActions: () => ({ setSearch, boardSearchRef }),
}));

const renderToolbar = (overrides: Partial<Parameters<typeof BoardToolbar>[0]> = {}) => {
  const update = vi.fn();
  // The REAL register, built from the same filters the toolbar gets: the
  // screen owns this element and hands it to both homes (BoardScreen), so a
  // stub here would stop these tests seeing what the folded panel contains.
  const filters = overrides.filters ?? DEFAULT_FILTERS;
  const onModeChange = vi.fn();
  const mode = boardMode(filters);
  render(
    <BoardToolbar
      register={
        <BoardFilters
          facets={facetsFixture}
          filters={filters}
          update={update}
          mode={mode}
          onModeChange={onModeChange}
        />
      }
      filters={filters}
      update={update}
      onModeChange={onModeChange}
      total={215}
      railMode={true}
      newSignalsOnly={false}
      clearNewSignals={vi.fn()}
      repostsOnly={false}
      clearReposts={vi.fn()}
      {...overrides}
    />
  );
  return update;
};

beforeEach(() => {
  setSearch.mockClear();
  boardSearchRef.current = null;
});

describe("the board toolbar", () => {
  it("offers retry for an unknown baseline without inventing a denominator or resetting filters", async () => {
    const retry = vi.fn();
    const update = renderToolbar({
      filters: { ...DEFAULT_FILTERS, company: ["google"] }, total: 1, baseTotal: null,
      baselineError: new Error("Offline"), onRetryBaseline: retry,
    });
    expect(screen.getByRole("status")).toHaveTextContent(msg("radar-total-failed"));
    expect(document.querySelector(".results-count")).not.toHaveTextContent("of");
    await userEvent.click(screen.getByRole("button", { name: msg("radar-total-retry-aria") }));
    expect(retry).toHaveBeenCalledOnce();
    expect(update).not.toHaveBeenCalled();
  });

  it("leads with the search box, wired to the shared query and the '/' ref", async () => {
    const user = userEvent.setup();
    renderToolbar();
    const input = screen.getByLabelText("Search titles and descriptions");
    // The shell's "/" shortcut focuses whatever this ref holds.
    expect(boardSearchRef.current).toBe(input);
    await user.type(input, "d");
    expect(setSearch).toHaveBeenCalledWith("d");
  });

  it("states the result count as a fact beside the search, with no undo while nothing narrows", () => {
    renderToolbar();
    expect(screen.getByText("215")).toBeInTheDocument();
    expect(screen.getByText("roles")).toBeInTheDocument();
    expect(screen.queryByText("of")).toBeNull();
    expect(screen.queryByRole("button", { name: "Reset all" })).toBeNull();
  });

  /* The undo is not in the register (a head row there would shift every
   * group on the first click); it sits beside the count it undoes. While
   * anything narrows the list the count is a fraction of what the same
   * search would give unfiltered, and Reset all follows it on the same
   * line, a line that never changes height. */
  it("states the narrowed count as a fraction of the unfiltered one, with the undo beside it", () => {
    renderToolbar({ filters: { ...DEFAULT_FILTERS, company: ["amazon"] }, total: 197, baseTotal: 219 });
    const count = document.querySelector(".results-count")!;
    expect(count.textContent!.replace(/\s+/g, " ").trim()).toBe("197 of 219 roles · Reset all");
    expect(screen.getByRole("button", { name: "Reset all" })).toBeInTheDocument();
  });

  it("offers the undo as soon as a lens narrows, even before the baseline is measured", () => {
    renderToolbar({ newSignalsOnly: true, total: 3, baseTotal: null });
    const count = document.querySelector(".results-count")!;
    expect(count.textContent!.replace(/\s+/g, " ").trim()).toBe("3 roles · Reset all");
  });

  it("Reset all clears every filter AND both mission lenses from that one control", async () => {
    const user = userEvent.setup();
    const clearNewSignals = vi.fn();
    const clearReposts = vi.fn();
    const update = renderToolbar({
      filters: { ...DEFAULT_FILTERS, level_band: ["staff"], workplace_type: ["hybrid"], viewed: "unread" },
      total: 12, baseTotal: 215, newSignalsOnly: true, clearNewSignals, clearReposts,
    });
    await user.click(screen.getByRole("button", { name: "Reset all" }));
    expect(clearNewSignals).toHaveBeenCalled();
    expect(clearReposts).toHaveBeenCalled();
    expect(update).toHaveBeenCalledWith(
      expect.objectContaining({ level_band: [], workplace_type: [], company: [], viewed: "", offset: 0 })
    );
  });

  it("offers Best match without a query and sends the relevance sort", async () => {
    const user = userEvent.setup();
    const update = renderToolbar();
    await user.selectOptions(screen.getByLabelText("Sort by"), "relevance");
    expect(update).toHaveBeenCalledWith({ sort: "relevance", offset: 0 });
  });

  it("disables the order toggle on the relevance sort (backend ignores asc/desc)", () => {
    renderToolbar({ filters: { ...DEFAULT_FILTERS, sort: "relevance" } });
    expect(screen.getByRole("button", { name: msg("radar-order-reverse") })).toBeDisabled();
  });

  it("says Best fit is newest first when there is nothing to rank by, and why", () => {
    renderToolbar({ filters: { ...DEFAULT_FILTERS, sort: "relevance" }, bestFitUnranked: true });
    const sort = screen.getByLabelText("Sort by");
    expect(sort).toHaveDisplayValue(msg("radar-sort-best-fit-unranked"));
    expect(sort).toHaveAccessibleDescription(msg("radar-sort-best-fit-unranked-why"));
  });

  it("names Best fit plainly once it ranks", () => {
    renderToolbar({ filters: { ...DEFAULT_FILTERS, sort: "relevance" } });
    const sort = screen.getByLabelText("Sort by");
    expect(sort).toHaveDisplayValue(msg("radar-sort-best-fit"));
    expect(sort).not.toHaveAccessibleDescription();
  });

  it("spells out Base in the sort menu, where an option never shows a hover", () => {
    renderToolbar({ filters: { ...DEFAULT_FILTERS, sort: "base_pay" } });
    const sort = screen.getByLabelText("Sort by");
    expect(sort).toHaveDisplayValue("Base salary");
    expect(screen.queryByRole("option", { name: "Base" })).toBeNull();
    expect(screen.queryByRole("option", { name: "Estimated total compensation" })).toBeNull();
  });

  it("shows no Filters opener while the register renders as the rail", () => {
    renderToolbar({ railMode: true });
    expect(screen.queryByRole("button", { name: /Filters/ })).toBeNull();
  });

  it("below rail widths, counts active filters on the opener and opens the register", async () => {
    const user = userEvent.setup();
    renderToolbar({
      railMode: false,
      filters: { ...DEFAULT_FILTERS, company: ["amazon"], level_band: ["staff"] },
      newSignalsOnly: true,
    });
    const opener = screen.getByRole("button", { name: /Filters · 3/ });
    await user.click(opener);
    const panel = screen.getByRole("dialog", { name: "Filters" });
    expect(panel).toBeInTheDocument();
    expect(screen.getByLabelText("Amazon")).toBeChecked();
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog", { name: "Filters" })).toBeNull();
  });

  it("wears an active mission lens as a pressed chip that clears on click", async () => {
    const user = userEvent.setup();
    const clearNewSignals = vi.fn();
    renderToolbar({ newSignalsOnly: true, clearNewSignals });
    const chip = screen.getByRole("button", { name: msg("radar-new-today") });
    expect(chip).toHaveAttribute("aria-pressed", "true");
    await user.click(chip);
    expect(clearNewSignals).toHaveBeenCalled();
  });
});
