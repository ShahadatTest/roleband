import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { act, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, useLocation, useNavigate } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ToastProvider, useToast, type ToastOptions } from "./Toast";

const css = readFileSync(
  join(dirname(fileURLToPath(import.meta.url)), "Toast.css"),
  "utf8",
).replace(/\/\*[\s\S]*?\*\//g, "");

function Trigger({ options, label = "Do it" }: { options: ToastOptions; label?: string }) {
  const { toast } = useToast();
  return (
    <button type="button" onClick={() => toast(options)}>
      {label}
    </button>
  );
}

describe("Toast", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it("announces a confirmation as a status and lets it go on its own", () => {
    render(
      <ToastProvider>
        <Trigger options={{ text: "Removed from compare" }} />
      </ToastProvider>,
    );
    fireEvent.click(screen.getByRole("button", { name: "Do it" }));
    expect(screen.getByRole("status")).toHaveTextContent("Removed from compare");
    act(() => vi.advanceTimersByTime(6000));
    expect(screen.queryByRole("status")).toBeNull();
  });

  it("carries the way back: the action runs once and the toast leaves", () => {
    const undo = vi.fn();
    render(
      <ToastProvider>
        <Trigger options={{ text: "Removed", action: { label: "Undo", onClick: undo } }} />
      </ToastProvider>,
    );
    fireEvent.click(screen.getByRole("button", { name: "Do it" }));
    fireEvent.click(screen.getByRole("button", { name: "Undo" }));
    expect(undo).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("status")).toBeNull();
  });

  it("gives a toast with an action longer to be noticed than one without", () => {
    render(
      <ToastProvider>
        <Trigger options={{ text: "Removed", action: { label: "Undo", onClick: () => {} } }} />
      </ToastProvider>,
    );
    fireEvent.click(screen.getByRole("button", { name: "Do it" }));
    act(() => vi.advanceTimersByTime(6000));
    expect(screen.getByRole("status")).toBeInTheDocument();
    act(() => vi.advanceTimersByTime(2000));
    expect(screen.queryByRole("status")).toBeNull();
  });

  it("keeps an error until it is dismissed, and says so as an alert", () => {
    render(
      <ToastProvider>
        <Trigger options={{ text: "Could not save", tone: "error" }} />
      </ToastProvider>,
    );
    fireEvent.click(screen.getByRole("button", { name: "Do it" }));
    act(() => vi.advanceTimersByTime(60000));
    expect(screen.getByRole("alert")).toHaveTextContent("Could not save");
    fireEvent.click(screen.getByRole("button", { name: "Dismiss" }));
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("replaces a toast about the same subject instead of stacking it", () => {
    render(
      <ToastProvider>
        <Trigger options={{ text: "First", key: "same" }} label="One" />
        <Trigger options={{ text: "Second", key: "same" }} label="Two" />
      </ToastProvider>,
    );
    fireEvent.click(screen.getByRole("button", { name: "One" }));
    fireEvent.click(screen.getByRole("button", { name: "Two" }));
    expect(screen.getAllByRole("status")).toHaveLength(1);
    expect(screen.getByRole("status")).toHaveTextContent("Second");
  });

  it("is inert without a provider, so a screen that toasts still renders", () => {
    render(<Trigger options={{ text: "Nothing" }} />);
    fireEvent.click(screen.getByRole("button", { name: "Do it" }));
    expect(screen.queryByRole("status")).toBeNull();
  });

  /* A toast belongs to the screen that raised it. The way back acts
     on that page's state, so carrying it to the next screen offers to undo an
     edit to a list that is not there. */
  describe("the screen it belongs to", () => {
    const UNDO: ToastOptions = {
      text: "Removed Staff Product Manager from compare",
      action: { label: "Undo", onClick: () => {} },
    };

    // The two moves that are NOT leaving: a query change is the same screen
    // asking a different question, and a position floats over the page that
    // opened it, which stays mounted underneath (App.tsx / routing/screen).
    function Elsewhere() {
      const location = useLocation();
      const navigate = useNavigate();
      return (
        <>
          <button type="button" onClick={() => navigate("/")}>
            Radar
          </button>
          <button type="button" onClick={() => navigate("/compare?sort=comp")}>
            Sort
          </button>
          <button
            type="button"
            onClick={() => navigate("/company/openai/job/1", { state: { backgroundLocation: location } })}
          >
            Open a role
          </button>
        </>
      );
    }

    /* Two ways to be at the comparison, and the rule is the same for both: as
       the page (a direct link or a refresh), and as a COVER over the list the
       roles were picked on, which stays mounted underneath with its scroll and
       filters. */
    const AS_PAGE = "/compare";
    const AS_COVER = { pathname: "/compare", state: { backgroundLocation: { pathname: "/" } } };

    const mount = (options: ToastOptions = UNDO, entry: string | object = AS_PAGE) =>
      render(
        <MemoryRouter initialEntries={[entry as string]}>
          <ToastProvider>
            <Trigger options={options} />
            <Elsewhere />
          </ToastProvider>
        </MemoryRouter>,
      );

    const raise = () => fireEvent.click(screen.getByRole("button", { name: "Do it" }));
    const go = (name: string) => fireEvent.click(screen.getByRole("button", { name }));

    it("does not follow the reader to the next screen", () => {
      mount();
      raise();
      expect(screen.getByRole("status")).toBeInTheDocument();
      go("Radar");
      expect(screen.queryByRole("status")).toBeNull();
      expect(screen.queryByRole("button", { name: "Undo" })).toBeNull();
    });

    it("takes an error with it too, sticky as it is", () => {
      mount({ text: "Could not remove that exclusion", tone: "error" });
      raise();
      expect(screen.getByRole("alert")).toBeInTheDocument();
      go("Radar");
      expect(screen.queryByRole("alert")).toBeNull();
    });

    it("stays while the same screen asks a different question", () => {
      mount();
      raise();
      go("Sort");
      expect(screen.getByRole("status")).toHaveTextContent("Removed Staff Product Manager from compare");
    });

    /* The sharp one. The comparison is a cover over the list, so the list is
       still mounted and history still names it — and if the screen were read
       THROUGH to that background, a toast raised in the cover would already be
       assigned to the board and clicking Radar would keep it. */
    it("does not hand a cover's toast to the list mounted underneath it", () => {
      mount(UNDO, AS_COVER);
      raise();
      expect(screen.getByRole("status")).toBeInTheDocument();
      go("Radar");
      expect(screen.queryByRole("status")).toBeNull();
    });

    it("counts a cover opening over this page as leaving it", () => {
      mount();
      raise();
      go("Open a role");
      expect(screen.queryByRole("status")).toBeNull();
    });

    it("keeps a toast raised after the move, on the screen it was raised on", () => {
      mount();
      go("Radar");
      raise();
      expect(screen.getByRole("status")).toBeInTheDocument();
      act(() => vi.advanceTimersByTime(8000));
      expect(screen.queryByRole("status")).toBeNull();
    });
  });

  describe("stylesheet contracts", () => {
    it("is out of flow, ignores the pointer as a layer, and takes it back per toast", () => {
      const host = css.slice(css.indexOf(".ui-toast-host {"), css.indexOf("}", css.indexOf(".ui-toast-host {")));
      expect(host).toMatch(/position:\s*fixed/);
      expect(host).toMatch(/pointer-events:\s*none/);
      const toast = css.slice(css.indexOf(".ui-toast {"), css.indexOf("}", css.indexOf(".ui-toast {")));
      expect(toast).toMatch(/pointer-events:\s*auto/);
    });

    it("paints --app-* only", () => {
      const consumed = [...css.matchAll(/var\((--[a-z0-9-]+)/g)].map((m) => m[1]);
      expect(consumed.filter((t) => !t.startsWith("--app-"))).toEqual([]);
    });
  });
});
