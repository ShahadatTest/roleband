import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { useTabRoute } from "./useTabRoute";

const SLUGS = ["overview", "velocity", "demand"] as const;

function Probe() {
  const loc = useLocation();
  return <div data-testid="loc">{loc.pathname}</div>;
}

function Back() {
  const navigate = useNavigate();
  return <button onClick={() => navigate(-1)}>back</button>;
}

function Harness() {
  const { tab, setTab } = useTabRoute({ base: "/statistics", slugs: SLUGS, fallback: "overview" });
  return (
    <>
      <div data-testid="tab">{tab}</div>
      <button onClick={() => setTab("velocity")}>go-velocity</button>
    </>
  );
}

function renderAt(route: string) {
  return render(
    <MemoryRouter initialEntries={[route]}>
      <Routes>
        <Route path="/statistics/:tab" element={<Harness />} />
      </Routes>
      <Probe />
      <Back />
    </MemoryRouter>,
  );
}

describe("useTabRoute", () => {
  it("reads a valid sub-tab from the path", () => {
    renderAt("/statistics/velocity");
    expect(screen.getByTestId("tab")).toHaveTextContent("velocity");
  });

  it("redirects an unknown sub-tab to the fallback", async () => {
    renderAt("/statistics/bogus");
    expect(await screen.findByTestId("loc")).toHaveTextContent("/statistics/overview");
    expect(screen.getByTestId("tab")).toHaveTextContent("overview");
  });

  it("pushes on tab change so the back button returns to the prior tab", async () => {
    const user = userEvent.setup();
    renderAt("/statistics/overview");
    await user.click(screen.getByText("go-velocity"));
    expect(screen.getByTestId("loc")).toHaveTextContent("/statistics/velocity");
    await user.click(screen.getByText("back"));
    expect(screen.getByTestId("loc")).toHaveTextContent("/statistics/overview");
  });
});
