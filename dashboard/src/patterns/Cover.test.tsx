import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Button } from "../ui";
import { ToastProvider, useToast } from "../ui/Toast";
import { Cover } from "./Cover";

/* The way back raised INSIDE a cover is reachable from inside it. Opened over a
 * list the cover is a modal dialog, so its Tab ring is the whole of what a
 * keyboard can reach — and the toast host is app chrome, outside the dialog.
 * Wired through the real three pieces (Cover's shell, Toast's host, Overlay's
 * ring), because each alone passes its own test while the seam between them is
 * where an Undo gets lost. Paint is proven in the browser
 * (tests/ux/compare.spec.ts); jsdom cannot tell what is on top. */
function Remove() {
  const { toast } = useToast();
  return (
    <Button onClick={() => toast({ text: "Removed a role from compare", action: { label: "Undo", onClick: () => {} } })}>
      Remove
    </Button>
  );
}

function renderCover(asOverlay: boolean) {
  render(
    <ToastProvider>
      <button type="button">Row underneath</button>
      <Cover label="Comparison" asOverlay={asOverlay} onBack={() => {}} bar={<Button>Back</Button>}>
        <Remove />
      </Cover>
    </ToastProvider>,
  );
}

describe("Cover", () => {
  it("opened over a list, lets Tab reach the Undo it raised and come back round", () => {
    renderCover(true);
    const remove = screen.getByRole("button", { name: "Remove" });
    fireEvent.click(remove);
    const undo = screen.getByRole("button", { name: "Undo" });

    remove.focus();
    fireEvent.keyDown(remove, { key: "Tab" });
    expect(undo).toHaveFocus();

    const dismiss = screen.getByRole("button", { name: "Dismiss" });
    dismiss.focus();
    fireEvent.keyDown(dismiss, { key: "Tab" });
    expect(screen.getByRole("button", { name: "Back" })).toHaveFocus();
  });
});
