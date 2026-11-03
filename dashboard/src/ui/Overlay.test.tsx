import { act, fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import { Dialog } from "./Dialog";
import { ABOVE_COVER, Overlay } from "./Overlay";
import { Popover } from "./Popover";

function Harness(props: { modal?: boolean; closeOnScrim?: boolean; closeOnEscape?: boolean }) {
  const [open, setOpen] = useState(false);
  return (
    <div>
      <button onClick={() => setOpen(true)}>Open it</button>
      <Overlay isOpen={open} onClose={() => setOpen(false)} label="test overlay" {...props}>
        <button>First action</button>
        <button>Last action</button>
      </Overlay>
    </div>
  );
}

describe("Overlay", () => {
  it("renders nothing while closed and portals content to body when open", async () => {
    render(<Harness />);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Open it" }));
    const dialog = screen.getByRole("dialog", { name: "test overlay" });
    expect(dialog).toHaveAttribute("aria-modal", "true");
    // Portalled out of the harness subtree, directly under <body>.
    expect(dialog.closest("body")).toBe(document.body);
    expect(dialog.parentElement?.parentElement).toBe(document.body);
  });

  it("closes on Escape and restores focus to the opener", async () => {
    render(<Harness />);
    const opener = screen.getByRole("button", { name: "Open it" });
    await userEvent.click(opener);
    expect(screen.getByRole("dialog")).toBeInTheDocument();

    fireEvent.keyDown(window, { key: "Escape" });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(opener).toHaveFocus();
  });

  it("does not close on Escape when closeOnEscape is false", async () => {
    render(<Harness closeOnEscape={false} />);
    await userEvent.click(screen.getByRole("button", { name: "Open it" }));
    fireEvent.keyDown(window, { key: "Escape" });
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });

  it("closes when the scrim is clicked", async () => {
    render(<Harness />);
    await userEvent.click(screen.getByRole("button", { name: "Open it" }));
    await userEvent.click(screen.getByRole("button", { name: "Close test overlay" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("offers no scrim close control when closeOnScrim is false", async () => {
    render(<Harness closeOnScrim={false} />);
    await userEvent.click(screen.getByRole("button", { name: "Open it" }));
    expect(screen.queryByRole("button", { name: "Close test overlay" })).not.toBeInTheDocument();
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });

  it("moves focus into the overlay on open", async () => {
    render(<Harness />);
    await userEvent.click(screen.getByRole("button", { name: "Open it" }));
    const dialog = screen.getByRole("dialog");
    expect(dialog.contains(document.activeElement)).toBe(true);
  });

  it("traps Tab inside modal content, wrapping last -> first and first -> last", async () => {
    render(<Harness />);
    await userEvent.click(screen.getByRole("button", { name: "Open it" }));
    const first = screen.getByRole("button", { name: "First action" });
    const last = screen.getByRole("button", { name: "Last action" });

    last.focus();
    fireEvent.keyDown(last, { key: "Tab" });
    expect(first).toHaveFocus();

    first.focus();
    fireEvent.keyDown(first, { key: "Tab", shiftKey: true });
    expect(last).toHaveFocus();
  });

  it("locks body scroll while a modal overlay is open and releases it on close", async () => {
    render(<Harness />);
    expect(document.body.style.overflow).not.toBe("hidden");
    await userEvent.click(screen.getByRole("button", { name: "Open it" }));
    expect(document.body.style.overflow).toBe("hidden");
    fireEvent.keyDown(window, { key: "Escape" });
    expect(document.body.style.overflow).not.toBe("hidden");
  });

  it("non-modal overlays skip aria-modal, focus trap, and scroll lock", async () => {
    const onClose = vi.fn();
    render(
      <Overlay isOpen onClose={onClose} label="quiet overlay" modal={false}>
        <button>Only action</button>
      </Overlay>,
    );
    const dialog = screen.getByRole("dialog", { name: "quiet overlay" });
    expect(dialog).not.toHaveAttribute("aria-modal");
    expect(document.body.style.overflow).not.toBe("hidden");
    // Tab is not intercepted for non-modal overlays.
    const only = screen.getByRole("button", { name: "Only action" });
    only.focus();
    fireEvent.keyDown(only, { key: "Tab" });
    expect(only).toHaveFocus();
  });
});

/* The cover layer. A cover is a SCREEN, not
 * a dialog: it sits on the cover layer, and a layer that paints above it — the
 * toast host, carrying the only way back — joins its Tab ring. A dialog
 * outranks that layer, so a dialog's ring must never reach into it. */
describe("Overlay — the cover layer", () => {
  function CoverHarness({ layer, above = true }: { layer?: "cover" | "dialog"; above?: boolean }) {
    return (
      <div>
        <button>Row underneath</button>
        <div {...{ [ABOVE_COVER]: "" }}>
          {above && (
            <>
              <button>Undo</button>
              <button>Dismiss</button>
            </>
          )}
        </div>
        <Overlay isOpen onClose={() => {}} label="the cover" layer={layer} scrim={false} closeOnScrim={false}>
          <button>Back</button>
          <button>Remove</button>
        </Overlay>
      </div>
    );
  }

  it("runs a cover's Tab ring on into the layer above it, and back round", () => {
    render(<CoverHarness layer="cover" />);
    const back = screen.getByRole("button", { name: "Back" });
    const remove = screen.getByRole("button", { name: "Remove" });
    const undo = screen.getByRole("button", { name: "Undo" });
    const dismiss = screen.getByRole("button", { name: "Dismiss" });

    remove.focus();
    fireEvent.keyDown(remove, { key: "Tab" });
    expect(undo).toHaveFocus();

    // Leaving the layer's last control closes the ring at the cover's first,
    // never at the row underneath, which is where DOM order would go next.
    dismiss.focus();
    fireEvent.keyDown(dismiss, { key: "Tab" });
    expect(back).toHaveFocus();

    fireEvent.keyDown(back, { key: "Tab", shiftKey: true });
    expect(dismiss).toHaveFocus();

    undo.focus();
    fireEvent.keyDown(undo, { key: "Tab", shiftKey: true });
    expect(remove).toHaveFocus();
  });

  it("brings focus back when WebKit walks a cover's Tab out past a button", () => {
    // WebKit's Tab skips buttons, so from a cover's control that is not its
    // last it can leave the cover altogether (the listing history's
    // button after Job detail's last field). The ring takes it back.
    vi.useFakeTimers();
    try {
      render(<CoverHarness layer="cover" above={false} />);
      const back = screen.getByRole("button", { name: "Back" });
      back.focus();
      fireEvent.keyDown(back, { key: "Tab" });
      // What WebKit does next: focus lands on the page under the cover.
      screen.getByRole("button", { name: "Row underneath" }).focus();
      act(() => {
        vi.runAllTimers();
      });
      expect(screen.getByRole("button", { name: "Remove" })).toHaveFocus();
    } finally {
      vi.useRealTimers();
    }
  });

  it("keeps the old ring while nothing is showing above the cover", () => {
    render(<CoverHarness layer="cover" above={false} />);
    const remove = screen.getByRole("button", { name: "Remove" });
    remove.focus();
    fireEvent.keyDown(remove, { key: "Tab" });
    expect(screen.getByRole("button", { name: "Back" })).toHaveFocus();
  });

  it("takes a stray Tab back into a cover's ring — focus dropped on the page by a removed control", () => {
    render(<CoverHarness layer="cover" />);
    // Pressing Undo removes it, and focus falls to the page.
    (document.activeElement as HTMLElement | null)?.blur();
    expect(document.activeElement).toBe(document.body);
    fireEvent.keyDown(document.body, { key: "Tab", shiftKey: true });
    expect(screen.getByRole("button", { name: "Dismiss" })).toHaveFocus();

    screen.getByRole("button", { name: "Row underneath" }).focus();
    fireEvent.keyDown(screen.getByRole("button", { name: "Row underneath" }), { key: "Tab" });
    expect(screen.getByRole("button", { name: "Back" })).toHaveFocus();
  });

  it("leaves focus alone inside another modal surface over the cover — the palette keeps its input", () => {
    render(
      <>
        <CoverHarness layer="cover" />
        <div role="dialog" aria-modal="true" aria-label="Command palette">
          <input aria-label="Search commands" />
        </div>
      </>,
    );
    const input = screen.getByRole("textbox", { name: "Search commands" });
    input.focus();
    fireEvent.keyDown(input, { key: "Tab" });
    expect(input).toHaveFocus();
  });

  it("gives a dialog no route into that layer — a dialog paints over it", () => {
    render(<CoverHarness />);
    const remove = screen.getByRole("button", { name: "Remove" });
    remove.focus();
    fireEvent.keyDown(remove, { key: "Tab" });
    expect(screen.getByRole("button", { name: "Back" })).toHaveFocus();

    // And Tab from inside that layer is not the dialog's to steer.
    const dismiss = screen.getByRole("button", { name: "Dismiss" });
    dismiss.focus();
    fireEvent.keyDown(dismiss, { key: "Tab" });
    expect(dismiss).toHaveFocus();

    // Nor from the page: the stray-Tab rule belongs to the cover layer only.
    const row = screen.getByRole("button", { name: "Row underneath" });
    row.focus();
    fireEvent.keyDown(row, { key: "Tab" });
    expect(row).toHaveFocus();
  });
});

/* One press of Escape is one surface: the one on top, never every surface
 * open at once (the palette and the cover under it, a popover and the dialog
 * it was opened from). The primitive is where that contract lives, so it is
 * pinned here. */
describe("Overlay — Escape belongs to the topmost layer", () => {
  /** `revision` only forces a re-render: both shells get a fresh inline onClose. */
  function PopoverInDialog({ revision = 0 }: { revision?: number }) {
    const [dialog, setDialog] = useState(true);
    const [popover, setPopover] = useState(false);
    const [anchor, setAnchor] = useState<HTMLButtonElement | null>(null);
    return (
      <Dialog isOpen={dialog} onClose={() => setDialog(false)} label="Edit schedule">
        <p>Revision {revision}</p>
        <button ref={setAnchor} onClick={() => setPopover(true)}>
          Options
        </button>
        <Popover isOpen={popover} onClose={() => setPopover(false)} anchor={anchor} label="Schedule options">
          <button>Pause</button>
        </Popover>
      </Dialog>
    );
  }

  it("closes a popover opened in a dialog and only the popover; the next Escape is the dialog's", async () => {
    render(<PopoverInDialog />);
    const options = screen.getByRole("button", { name: "Options" });
    await userEvent.click(options);
    expect(screen.getByRole("dialog", { name: "Schedule options" })).toBeInTheDocument();

    await userEvent.keyboard("{Escape}");
    expect(screen.queryByRole("dialog", { name: "Schedule options" })).not.toBeInTheDocument();
    expect(screen.getByRole("dialog", { name: "Edit schedule" })).toBeInTheDocument();
    // Focus goes back to the popover's opener, which is still there to take it.
    expect(options).toHaveFocus();

    await userEvent.keyboard("{Escape}");
    expect(screen.queryByRole("dialog", { name: "Edit schedule" })).not.toBeInTheDocument();
  });

  it("keeps the popover on top when the dialog beneath it re-renders", async () => {
    const { rerender } = render(<PopoverInDialog revision={0} />);
    await userEvent.click(screen.getByRole("button", { name: "Options" }));
    // A re-render is not a re-open: a layer keyed on its handler's identity
    // would re-register on every render and lift the dialog over its popover.
    rerender(<PopoverInDialog revision={1} />);

    await userEvent.keyboard("{Escape}");
    expect(screen.queryByRole("dialog", { name: "Schedule options" })).not.toBeInTheDocument();
    expect(screen.getByRole("dialog", { name: "Edit schedule" })).toBeInTheDocument();
  });

  it("holds Escape for a layer that declines it: the layer beneath never hears the press", async () => {
    const beneath = vi.fn();
    render(
      <>
        <Overlay isOpen onClose={beneath} label="the cover" layer="cover" scrim={false} closeOnScrim={false}>
          <button>Back</button>
        </Overlay>
        <Overlay isOpen onClose={() => {}} label="must be answered" closeOnEscape={false}>
          <button>Answer</button>
        </Overlay>
      </>,
    );
    await userEvent.keyboard("{Escape}");
    expect(beneath).not.toHaveBeenCalled();
    expect(screen.getByRole("dialog", { name: "must be answered" })).toBeInTheDocument();
  });

  it("ranks by the layer scale, not by arrival: a cover opened under a dialog does not take its Escape", async () => {
    const question = vi.fn();
    const screenBeneath = vi.fn();
    function DialogThenCover({ cover }: { cover: boolean }) {
      return (
        <>
          <Overlay isOpen onClose={question} label="a question">
            <button>Yes</button>
          </Overlay>
          {cover && (
            <Overlay isOpen onClose={screenBeneath} label="a screen" layer="cover" scrim={false} closeOnScrim={false}>
              <button>Back</button>
            </Overlay>
          )}
        </>
      );
    }
    const { rerender } = render(<DialogThenCover cover={false} />);
    rerender(<DialogThenCover cover />);

    await userEvent.keyboard("{Escape}");
    // The dialog paints over the cover (Overlay.css), so it is the one on top.
    expect(question).toHaveBeenCalledTimes(1);
    expect(screenBeneath).not.toHaveBeenCalled();
  });

  it("leaves an Escape that a control inside the layer has already handled", async () => {
    const onClose = vi.fn();
    render(
      <Overlay isOpen onClose={onClose} label="with an editor">
        <input
          aria-label="Time"
          onKeyDown={(e) => {
            // An in-place editor abandoning its edit consumes the press.
            if (e.key === "Escape") e.preventDefault();
          }}
        />
      </Overlay>,
    );
    screen.getByRole("textbox", { name: "Time" }).focus();
    await userEvent.keyboard("{Escape}");
    expect(onClose).not.toHaveBeenCalled();
  });
});
