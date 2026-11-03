import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { useSearchParam } from "./useSearchParam";

const OPTIONS = ["7", "30", "90"] as const;

function Probe() {
  const loc = useLocation();
  return <div data-testid="loc">{`${loc.pathname}${loc.search}`}</div>;
}

function Back() {
  const navigate = useNavigate();
  return <button onClick={() => navigate(-1)}>back</button>;
}

function Harness() {
  const [win, setWin] = useSearchParam("window", { options: OPTIONS, fallback: "30" });
  return (
    <>
      <div data-testid="val">{win}</div>
      <button onClick={() => setWin("90")}>set90</button>
      <button onClick={() => setWin("30")}>setdefault</button>
    </>
  );
}

function renderAt(entries: string[], initialIndex = entries.length - 1) {
  return render(
    <MemoryRouter initialEntries={entries} initialIndex={initialIndex}>
      <Harness />
      <Probe />
      <Back />
    </MemoryRouter>,
  );
}

describe("useSearchParam", () => {
  it("returns the fallback when the param is absent", () => {
    renderAt(["/"]);
    expect(screen.getByTestId("val")).toHaveTextContent("30");
  });

  it("reads a valid value from the query string", () => {
    renderAt(["/?window=90"]);
    expect(screen.getByTestId("val")).toHaveTextContent("90");
  });

  it("falls back for an out-of-whitelist value without rewriting the URL", () => {
    renderAt(["/?window=bogus"]);
    expect(screen.getByTestId("val")).toHaveTextContent("30");
    // Tolerant read: the invalid param is ignored, not redirected away.
    expect(screen.getByTestId("loc")).toHaveTextContent("window=bogus");
  });

  it("writes a non-default value into the query", async () => {
    const user = userEvent.setup();
    renderAt(["/"]);
    await user.click(screen.getByText("set90"));
    expect(screen.getByTestId("loc")).toHaveTextContent("/?window=90");
    expect(screen.getByTestId("val")).toHaveTextContent("90");
  });

  it("deletes the key when set back to the fallback, preserving other params", async () => {
    const user = userEvent.setup();
    renderAt(["/?window=90&x=1"]);
    await user.click(screen.getByText("setdefault"));
    const loc = screen.getByTestId("loc");
    expect(loc).not.toHaveTextContent("window");
    expect(loc).toHaveTextContent("x=1");
  });

  it("replaces rather than pushes, so the lens does not pollute history", async () => {
    const user = userEvent.setup();
    renderAt(["/first", "/?window=30"], 1);
    await user.click(screen.getByText("set90"));
    expect(screen.getByTestId("loc")).toHaveTextContent("/?window=90");
    // The set replaced the current entry, so Back lands on the prior page.
    await user.click(screen.getByText("back"));
    expect(screen.getByTestId("loc")).toHaveTextContent("/first");
  });

  it("does not navigate when the value is not changing", async () => {
    // `setSearchParams` always navigates, resolving against the location its
    // closure was built in — so a mirror that re-fires as the reader leaves
    // lands a replace on the OLD route and undoes the departure. Writing the
    // value it already holds must be a no-op, not a navigation.
    const seen: string[] = [];
    function Probe() {
      const [value, setValue] = useSearchParam("show", { options: ["open", "closed"] as const, fallback: "open" });
      const location = useLocation();
      seen.push(location.pathname + location.search);
      return <button onClick={() => setValue(value)}>rewrite</button>;
    }
    render(
      <MemoryRouter initialEntries={["/board?show=closed"]}>
        <Routes><Route path="/board" element={<Probe />} /></Routes>
      </MemoryRouter>,
    );
    const before = seen.length;
    fireEvent.click(screen.getByRole("button", { name: "rewrite" }));
    fireEvent.click(screen.getByRole("button", { name: "rewrite" }));
    expect(seen.length).toBe(before);
    expect(seen[seen.length - 1]).toBe("/board?show=closed");
  });
});
