import { fireEvent, render, screen } from "@testing-library/react";
import { StrictMode, useState } from "react";
import { MemoryRouter, useLocation } from "react-router-dom";
import { beforeAll, describe, expect, it, vi } from "vitest";
import { Overlay } from "../ui/Overlay";
import { ToastProvider } from "../ui/Toast";
import { CommandPalette } from "./CommandPalette";

const mocks = vi.hoisted(() => ({
  setSearch: vi.fn(),
  clearCompare: vi.fn(),
  setCompare: vi.fn(),
  openCompare: vi.fn(),
  compareIds: new Set<number>(),
}));

vi.mock("../context/MissionState", () => ({
  useMissionActions: () => ({ setSearch: mocks.setSearch }),
}));
vi.mock("../context/JobWorkspace", () => ({
  useJobWorkspace: () => ({ compareIds: mocks.compareIds }),
  useJobActions: () => ({
    clearCompare: mocks.clearCompare,
    setCompare: mocks.setCompare,
    openCompare: mocks.openCompare,
  }),
}));

function Location() {
  const { pathname } = useLocation();
  return <div data-testid="pathname">{pathname}</div>;
}

function renderPalette({ compareIds = [] as number[] } = {}) {
  mocks.setSearch.mockClear();
  mocks.clearCompare.mockClear();
  mocks.setCompare.mockClear();
  mocks.compareIds = new Set(compareIds);
  const onClose = vi.fn();
  const onShowShortcuts = vi.fn();
  const tree = (open: boolean) => (
    <MemoryRouter initialEntries={["/"]}>
      <ToastProvider>
        <CommandPalette
          open={open}
          onClose={onClose}
          theme="dark"
          onToggleTheme={vi.fn()}
          onShowShortcuts={onShowShortcuts}
        />
      </ToastProvider>
      <Location />
    </MemoryRouter>
  );
  const { rerender } = render(tree(true));
  return {
    onClose,
    onShowShortcuts,
    input: () => screen.getByLabelText("Command query"),
    type: (value: string) => fireEvent.change(screen.getByLabelText("Command query"), { target: { value } }),
    pathname: () => screen.getByTestId("pathname").textContent,
    selected: () => screen.getByRole("option", { selected: true }).textContent,
    reopen: () => {
      rerender(tree(false));
      rerender(tree(true));
    },
  };
}

// jsdom implements no layout, so the list's keep-the-row-visible effect has no
// scrollIntoView to call.
beforeAll(() => {
  Element.prototype.scrollIntoView = vi.fn();
});

// Keys are handled on the window (the palette is modal, not focus-dependent).
const press = (key: string) => fireEvent.keyDown(window, { key });

describe("CommandPalette", () => {
  it("returns focus to the opener across repeated development ref mounts", () => {
    function Harness() {
      const [open, setOpen] = useState(false);
      return <>
        <button onClick={() => setOpen(true)}>Open commands</button>
        <CommandPalette open={open} onClose={() => setOpen(false)} theme="dark" onToggleTheme={() => {}} />
      </>;
    }
    render(<StrictMode><MemoryRouter><ToastProvider><Harness /></ToastProvider></MemoryRouter></StrictMode>);
    const opener = screen.getByRole("button", { name: "Open commands" });
    for (let count = 0; count < 2; count++) {
      opener.focus();
      fireEvent.click(opener);
      expect(screen.getByRole("combobox", { name: "Command query" })).toHaveFocus();
      press("Escape");
      expect(opener).toHaveFocus();
    }
  });

  it("arrow-down then enter runs the highlighted destination", () => {
    const p = renderPalette();

    p.type("Pace");
    // Index 0 is always the free-text role search; the destination is next.
    press("ArrowDown");
    press("Enter");

    expect(p.pathname()).toBe("/statistics/velocity");
    expect(mocks.setSearch).not.toHaveBeenCalled();
    expect(p.onClose).toHaveBeenCalledTimes(1);
  });

  // A keystroke whose state commit lands AFTER the arrow key must not move the
  // selection: an INDEX into a re-derived list would snap back to 0, and Enter
  // would run the search command -- navigating to "/" instead of the row the
  // user can see highlighted.
  it("keeps the highlighted command when a keystroke commits after the arrow key", () => {
    const p = renderPalette();

    p.type("Pac");
    press("ArrowDown");
    expect(p.selected()).toContain("Insights: Pace");

    // The last character's commit arrives late, re-deriving the list under the
    // existing selection.
    p.type("Pace");
    expect(p.selected()).toContain("Insights: Pace");

    press("Enter");
    expect(p.pathname()).toBe("/statistics/velocity");
    expect(mocks.setSearch).not.toHaveBeenCalled();
  });

  it("keeps arrowing from the visible highlight after a late commit", () => {
    const p = renderPalette();

    p.type("Insight");
    press("ArrowDown");
    expect(p.selected()).toContain("Insights");

    p.type("Insights");
    press("ArrowDown");
    expect(p.selected()).toContain("Insights: Overview");

    press("Enter");
    expect(p.pathname()).toBe("/statistics/overview");
  });

  it("falls back to the first result when the newest query drops the selection", () => {
    const p = renderPalette();

    p.type("Pac");
    press("ArrowDown");
    expect(p.selected()).toContain("Insights: Pace");

    // A query that stops matching the selected command: the highlight moves
    // to the top result, and Enter still runs what is highlighted.
    p.type("Overlap");
    expect(p.selected()).toContain("Search roles for");

    press("Enter");
    expect(mocks.setSearch).toHaveBeenCalledWith("Overlap");
    expect(p.pathname()).toBe("/");
  });

  it("reopening resets the query and the selection", () => {
    const p = renderPalette();

    p.type("Pace");
    press("ArrowDown");
    expect(p.selected()).toContain("Insights: Pace");

    p.reopen();
    expect(p.input()).toHaveValue("");
    expect(p.selected()).toContain("Radar");
  });

  /* Arrowing scrolls the list under a pointer that rests on it. The browser
     reports each row arriving under it as the pointer entering that row, at
     the same coordinates: only a pointer that actually moved may take the
     highlight, or Enter runs the row under the mouse instead of the one the
     keyboard reached. */
  it("a row scrolled under a resting pointer does not take the highlight", () => {
    const p = renderPalette();
    const row = (name: string) => screen.getByRole("option", { name });

    // Opened under a resting pointer: the first report only places it.
    fireEvent.mouseEnter(row("Saved"));
    fireEvent.mouseMove(row("Saved"), { clientX: 300, clientY: 200 });
    expect(p.selected()).toBe("Radar");

    // A real move takes the highlight.
    fireEvent.mouseMove(row("Profile"), { clientX: 300, clientY: 240 });
    expect(p.selected()).toBe("Profile");

    press("ArrowDown");
    press("ArrowDown");
    expect(p.selected()).toBe("Profile: Your experience");

    // The list scrolls; another row arrives under the still pointer.
    fireEvent.mouseEnter(row("Insights"));
    fireEvent.mouseMove(row("Insights"), { clientX: 300, clientY: 240 });
    expect(p.selected()).toBe("Profile: Your experience");

    press("Enter");
    expect(p.pathname()).toBe("/profile/experience");
  });

  /* The palette opens over a cover, whose own Escape steps back. The press is
     the palette's alone: both listen at the window, and one press must not
     close the palette AND step the screen under it back. */
  it("takes Escape from the cover it was opened over, and leaves the next press to the cover", () => {
    const stepBack = vi.fn();
    const onClose = vi.fn();
    const tree = (open: boolean) => (
      <MemoryRouter initialEntries={["/compare"]}>
        <ToastProvider>
          <Overlay isOpen onClose={stepBack} label="Comparison" layer="cover" scrim={false} closeOnScrim={false}>
            <button>Back</button>
          </Overlay>
          <CommandPalette open={open} onClose={onClose} theme="dark" onToggleTheme={vi.fn()} />
        </ToastProvider>
      </MemoryRouter>
    );
    const { rerender } = render(tree(false));
    rerender(tree(true)); // opened over the cover, as Cmd-K does

    press("Escape");
    expect(onClose).toHaveBeenCalledTimes(1);
    expect(stepBack).not.toHaveBeenCalled();

    rerender(tree(false)); // the shell closes it on that call
    press("Escape");
    expect(stepBack).toHaveBeenCalledTimes(1);
  });

  /* This command runs the comparison's own Clear, which captures the set and
     offers Undo, never the bare clear. Undo must restore
     the set that was CLEARED — captured at the moment of clearing — not
     whatever the selection holds when the toast is pressed. */
  it("clears the comparison with a way back, and Undo restores exactly what it cleared", () => {
    const p = renderPalette({ compareIds: [701, 702] });

    p.type("clear");
    press("ArrowDown");
    expect(p.selected()).toContain("Clear compare selection (2)");
    press("Enter");

    expect(mocks.clearCompare).toHaveBeenCalledTimes(1);
    expect(screen.getByText("Cleared 2 roles from compare")).toBeInTheDocument();
    mocks.compareIds = new Set([999]); // the selection moves on before Undo
    fireEvent.click(screen.getByRole("button", { name: "Undo" }));
    expect(mocks.setCompare).toHaveBeenCalledWith([701, 702]);
  });

  it("says one cleared role in the singular", () => {
    const p = renderPalette({ compareIds: [701] });
    p.type("clear");
    press("ArrowDown");
    press("Enter");
    // The count picks the plural form: never "1 roles".
    expect(screen.getByText("Cleared 1 role from compare")).toBeInTheDocument();
  });

  it("offers the keyboard shortcuts by name, and hands the sheet to the shell", () => {
    const p = renderPalette();

    p.type("keyboard");
    press("ArrowDown");
    expect(p.selected()).toContain("Keyboard shortcuts");
    press("Enter");

    expect(p.onShowShortcuts).toHaveBeenCalledTimes(1);
    expect(p.onClose).toHaveBeenCalledTimes(1);
  });
});
