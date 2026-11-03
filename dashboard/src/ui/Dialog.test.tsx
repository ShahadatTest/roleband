import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { Dialog } from "./Dialog";
import { Sheet } from "./Sheet";

describe("Dialog", () => {
  it("renders a centered modal dialog that closes on Escape and scrim", async () => {
    const onClose = vi.fn();
    render(
      <Dialog isOpen onClose={onClose} label="confirm delete" width={420}>
        <p>Are you sure?</p>
      </Dialog>,
    );
    const dialog = screen.getByRole("dialog", { name: "confirm delete" });
    expect(dialog).toHaveAttribute("aria-modal", "true");
    expect(dialog).toHaveClass("ui-dialog");
    expect(dialog).toHaveStyle({ width: "420px" });
    expect(screen.getByText("Are you sure?")).toBeInTheDocument();

    fireEvent.keyDown(window, { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(1);
    await userEvent.click(screen.getByRole("button", { name: "Close confirm delete" }));
    expect(onClose).toHaveBeenCalledTimes(2);
  });

  it("keeps must-answer dialogs open on scrim interaction when closeOnScrim is false", () => {
    const onClose = vi.fn();
    render(
      <Dialog isOpen onClose={onClose} label="required choice" closeOnScrim={false}>
        <button>Choose</button>
      </Dialog>,
    );
    expect(screen.queryByRole("button", { name: "Close required choice" })).not.toBeInTheDocument();
    expect(onClose).not.toHaveBeenCalled();
  });
});

describe("Sheet", () => {
  it("renders a modal edge-docked sheet with the requested side", () => {
    const onClose = vi.fn();
    render(
      <Sheet isOpen onClose={onClose} label="job drawer" side="bottom">
        <p>Drawer content</p>
      </Sheet>,
    );
    const sheet = screen.getByRole("dialog", { name: "job drawer" });
    expect(sheet).toHaveAttribute("aria-modal", "true");
    expect(sheet).toHaveClass("ui-sheet", "ui-sheet-bottom");
    expect(document.body.style.overflow).toBe("hidden");
  });

  it("docks right by default and closes on Escape", () => {
    const onClose = vi.fn();
    render(
      <Sheet isOpen onClose={onClose} label="job drawer">
        <p>Drawer content</p>
      </Sheet>,
    );
    expect(screen.getByRole("dialog", { name: "job drawer" })).toHaveClass("ui-sheet-right");
    fireEvent.keyDown(window, { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
