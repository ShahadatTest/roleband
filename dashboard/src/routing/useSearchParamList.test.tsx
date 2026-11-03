import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useEffect } from "react";
import { MemoryRouter, Outlet, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { useSearchParamList } from "./useSearchParamList";

function Probe() {
  const loc = useLocation();
  return (
    <>
      <div data-testid="loc">{`${loc.pathname}${loc.search}`}</div>
      {/* A new key on every navigation, replace included -- so a test can tell
          "wrote nothing" from "wrote the same thing again". */}
      <div data-testid="key">{loc.key}</div>
    </>
  );
}

function Harness() {
  const [companies, setCompanies] = useSearchParamList("company");
  return (
    <>
      <div data-testid="val">{companies.join(",")}</div>
      <button onClick={() => setCompanies(["google", "netflix"])}>settwo</button>
      <button onClick={() => setCompanies([])}>clear</button>
      <button onClick={() => setCompanies(["google"])}>resetgoogle</button>
    </>
  );
}

function renderAt(route: string) {
  return render(
    <MemoryRouter initialEntries={[route]}>
      <Harness />
      <Probe />
    </MemoryRouter>,
  );
}

describe("useSearchParamList", () => {
  it("reads every value of a repeated param", () => {
    renderAt("/?company=google&company=netflix");
    expect(screen.getByTestId("val")).toHaveTextContent("google,netflix");
  });

  it("is empty when the param is absent", () => {
    renderAt("/");
    expect(screen.getByTestId("val")).toHaveTextContent("");
  });

  it("writes each value and preserves other params", async () => {
    const user = userEvent.setup();
    renderAt("/?q=eng");
    await user.click(screen.getByText("settwo"));
    const loc = screen.getByTestId("loc");
    expect(loc).toHaveTextContent("company=google");
    expect(loc).toHaveTextContent("company=netflix");
    expect(loc).toHaveTextContent("q=eng");
  });

  it("clears the key when set to an empty list, leaving others intact", async () => {
    const user = userEvent.setup();
    renderAt("/?company=google&q=eng");
    await user.click(screen.getByText("clear"));
    const loc = screen.getByTestId("loc");
    expect(loc).not.toHaveTextContent("company");
    expect(loc).toHaveTextContent("q=eng");
  });

  // A no-op write still NAVIGATES, and that is how a mirror stomps a
  // destination: `setSearchParams` resolves "?" against the mirror's own route,
  // so a write issued after the user has left replaces the new URL with the old
  // one. The board mirrors `filters.company` here on every setter identity
  // change -- and the setter's identity changes with the location, so leaving
  // the board re-fires it.
  it("does not navigate when the values are already in the URL", async () => {
    const user = userEvent.setup();
    renderAt("/?company=google");
    const before = screen.getByTestId("key").textContent;

    await user.click(screen.getByText("resetgoogle"));

    expect(screen.getByTestId("loc")).toHaveTextContent("company=google");
    expect(screen.getByTestId("key")).toHaveTextContent(before!);
  });

  it("still navigates when the values differ only in order", async () => {
    const user = userEvent.setup();
    renderAt("/?company=netflix&company=google");
    await user.click(screen.getByText("settwo"));
    expect(screen.getByTestId("loc")).toHaveTextContent("company=google&company=netflix");
  });

  // The shape of the board stomping the palette: the board
  // mirrors `filters.company` into `?company=` from an effect, and that effect
  // re-fires as the user leaves -- with a setter closure built while the board
  // was still the current route, so its write resolves to "/" and REPLACES the
  // destination the palette had just pushed. The write had nothing to change.
  it("a stale setter with nothing to change does not undo a navigation", async () => {
    const user = userEvent.setup();
    let stale: ((vals: string[]) => void) | null = null;
    render(
      <MemoryRouter initialEntries={["/"]}>
        <Routes>
          <Route path="/" element={<Mirror onSetter={(fn) => { stale ??= fn; }} />}>
            <Route index element={<Leave />} />
            <Route path="statistics/velocity" element={<div>velocity</div>} />
          </Route>
        </Routes>
        <Probe />
      </MemoryRouter>,
    );

    await user.click(screen.getByText("leave"));
    expect(screen.getByTestId("loc")).toHaveTextContent("/statistics/velocity");

    await act(async () => stale!([]));
    expect(screen.getByTestId("loc")).toHaveTextContent("/statistics/velocity");
    expect(screen.getByText("velocity")).toBeInTheDocument();
  });
});

// The board's URL mirror, reduced to its mechanism: a route based at "/" that
// hands out the setter it built while it was the current route.
function Mirror({ onSetter }: { onSetter: (fn: (vals: string[]) => void) => void }) {
  const [, setCompanies] = useSearchParamList("company");
  useEffect(() => onSetter(setCompanies), [onSetter, setCompanies]);
  return <Outlet />;
}

function Leave() {
  const navigate = useNavigate();
  return <button onClick={() => navigate("/statistics/velocity")}>leave</button>;
}
