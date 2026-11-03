import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation, type Location } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { ScreenProvider, useScreenKey } from "./screen";

function Probe({ id }: { id: string }) {
  return <span data-testid={id}>{useScreenKey()}</span>;
}

/* The two slots as App.tsx renders them: the list under a cover is routed with
   `<Routes location={background}>`, which is what `useLocation()` returns to
   everything inside it; the cover renders in a second slot on the real
   location. */
function Slots() {
  const location = useLocation();
  const background = (location.state as { backgroundLocation?: Location } | null)?.backgroundLocation;
  return (
    <>
      <Routes location={background ?? location}>
        <Route path="/" element={<Probe id="on-the-list" />} />
      </Routes>
      {background && (
        <Routes>
          <Route path="/compare" element={<Probe id="in-the-cover" />} />
        </Routes>
      )}
    </>
  );
}

const OVER_THE_LIST = { pathname: "/compare", state: { backgroundLocation: { pathname: "/" } } };

describe("useScreenKey", () => {
  it("answers the reader's screen wherever it is asked — on the list under a cover included", () => {
    render(
      <MemoryRouter initialEntries={[OVER_THE_LIST]}>
        <ScreenProvider>
          <Slots />
        </ScreenProvider>
      </MemoryRouter>,
    );
    expect(screen.getByTestId("in-the-cover")).toHaveTextContent("/compare");
    // The list is mounted and routed as "/", but the reader is at the comparison.
    expect(screen.getByTestId("on-the-list")).toHaveTextContent("/compare");
  });

  it("falls back to the nearest location with no provider, where the two agree", () => {
    render(
      <MemoryRouter initialEntries={["/saved"]}>
        <Probe id="alone" />
      </MemoryRouter>,
    );
    expect(screen.getByTestId("alone")).toHaveTextContent("/saved");
  });
});
