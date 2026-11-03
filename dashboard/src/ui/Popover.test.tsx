import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useRef, useState } from "react";
import { MemoryRouter, Route, Routes, useLocation, useNavigate, type Location } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { ScreenProvider } from "../routing/screen";
import { Popover } from "./Popover";

function Harness() {
  const anchorRef = useRef<HTMLButtonElement | null>(null);
  const [open, setOpen] = useState(false);
  return (
    <div>
      <button ref={anchorRef} onClick={() => setOpen((v) => !v)}>
        Toggle menu
      </button>
      <Popover
        isOpen={open}
        onClose={() => setOpen(false)}
        anchor={anchorRef.current}
        label="test menu"
      >
        <button>Menu item</button>
      </Popover>
    </div>
  );
}

describe("Popover", () => {
  it("opens anchored, non-modal, and closes on outside click restoring anchor focus", async () => {
    render(<Harness />);
    const anchor = screen.getByRole("button", { name: "Toggle menu" });
    await userEvent.click(anchor);

    const pop = screen.getByRole("dialog", { name: "test menu" });
    expect(pop).not.toHaveAttribute("aria-modal");
    expect(screen.getByRole("button", { name: "Menu item" })).toBeInTheDocument();
    // Non-modal: the page keeps scrolling.
    expect(document.body.style.overflow).not.toBe("hidden");

    // Outside click lands on the clear click-catcher.
    await userEvent.click(screen.getByRole("button", { name: "Close test menu" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(anchor).toHaveFocus();
  });

  it("closes on Escape", async () => {
    render(<Harness />);
    await userEvent.click(screen.getByRole("button", { name: "Toggle menu" }));
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    fireEvent.keyDown(window, { key: "Escape" });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  /* A popover belongs to the SCREEN it was opened on — the toast's rule,
     for the same reason: the page underneath a cover stays mounted, so a
     popover opened on the list would outlive it, and since a cover ranks below
     a popover it would float over the comparison — the compare roster, whose
     own primary opens it. */
  describe("the screen it belongs to", () => {
    /* The list as App.tsx renders it under a cover: routed on the background
       location, so `useLocation()` inside it still says "/" while the reader
       is at the comparison. That is where the roster lives. */
    function Slots() {
      const location = useLocation();
      const background = (location.state as { backgroundLocation?: Location } | null)?.backgroundLocation;
      return (
        <Routes location={background ?? location}>
          <Route path="/" element={<List />} />
        </Routes>
      );
    }
    function List() {
      const anchorRef = useRef<HTMLButtonElement | null>(null);
      const [open, setOpen] = useState(true);
      const location = useLocation();
      const navigate = useNavigate();
      return (
        <div>
          <button ref={anchorRef}>Anchor</button>
          <button onClick={() => navigate("/compare", { state: { backgroundLocation: location } })}>
            Compare 3 roles
          </button>
          <button onClick={() => navigate("/?sort=comp")}>Re-sort</button>
          <Popover isOpen={open} onClose={() => setOpen(false)} anchor={anchorRef.current} label="roster"
            takeFocus={false} closeOnScrim={false}>
            <p>In compare</p>
          </Popover>
        </div>
      );
    }
    const mount = () =>
      render(
        <MemoryRouter initialEntries={["/"]}>
          <ScreenProvider>
            <Slots />
          </ScreenProvider>
        </MemoryRouter>,
      );

    it("closes when a cover opens over the list it was opened on", () => {
      mount();
      expect(screen.getByRole("dialog", { name: "roster" })).toBeInTheDocument();
      fireEvent.click(screen.getByRole("button", { name: "Compare 3 roles" }));
      expect(screen.queryByRole("dialog", { name: "roster" })).not.toBeInTheDocument();
    });

    it("stays open when only the query changes — that is the same screen", () => {
      mount();
      fireEvent.click(screen.getByRole("button", { name: "Re-sort" }));
      expect(screen.getByRole("dialog", { name: "roster" })).toBeInTheDocument();
    });
  });
});
