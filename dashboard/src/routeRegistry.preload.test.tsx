import { render, screen } from "@testing-library/react";
import { Suspense } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ErrorBoundary } from "./ui/ErrorBoundary";
import { CompareRoute, PositionRoute, ROUTE_COMPONENTS, preloadRoute, preloadScreens, preloadable } from "./routeRegistry";

/* A screen fetched ahead of its route opens on itself, not on a load state:
   React.lazy alone would suspend once on the first render, and React holds a
   fallback it has shown for a moment. */

const settle = () => new Promise((done) => setTimeout(done, 0));

it("a screen fetched ahead renders at once, with no load state", async () => {
  const Screen = preloadable(async () => ({ default: () => <p>the screen</p> }));
  Screen.preload();
  await settle();
  render(<Suspense fallback={<p>loading</p>}><Screen /></Suspense>);
  expect(screen.getByText("the screen")).toBeInTheDocument();
  expect(screen.queryByText("loading")).toBeNull();
});

it("a screen not fetched yet waits on the load state until it arrives, and is fetched once", async () => {
  let calls = 0;
  const Screen = preloadable(async () => { calls += 1; return { default: () => <p>later</p> }; });
  render(<Suspense fallback={<p>loading</p>}><Screen /></Suspense>);
  expect(screen.getByText("loading")).toBeInTheDocument();
  expect(await screen.findByText("later")).toBeInTheDocument();
  Screen.preload();
  expect(calls).toBe(1);
});

it("a screen passes its props through, fetched ahead or not", async () => {
  const Ahead = preloadable(async () => ({ default: ({ label }: { label: string }) => <p>{label}</p> }));
  Ahead.preload();
  await settle();
  const OnRender = preloadable(async () => ({ default: ({ label }: { label: string }) => <p>{label}</p> }));
  render(
    <Suspense fallback={<p>loading</p>}>
      <Ahead label="over the list" />
      <OnRender label="standalone" />
    </Suspense>,
  );
  expect(await screen.findByText("over the list")).toBeInTheDocument();
  expect(await screen.findByText("standalone")).toBeInTheDocument();
});

it("a screen that cannot be fetched ahead fails when its route renders", async () => {
  const Screen = preloadable(() => Promise.reject(new Error("chunk gone")));
  Screen.preload();
  await settle();
  vi.spyOn(console, "error").mockImplementation(() => {});
  render(
    <ErrorBoundary fallback={(error) => <p role="alert">{error.message}</p>}>
      <Suspense fallback={<p>loading</p>}><Screen /></Suspense>
    </ErrorBoundary>,
  );
  expect(await screen.findByRole("alert")).toHaveTextContent("chunk gone");
  vi.restoreAllMocks();
});

describe("which screen a launch fetches first", () => {
  afterEach(() => vi.restoreAllMocks());

  const fetched = (pathname: string) => {
    const screens = { ...ROUTE_COMPONENTS, position: PositionRoute, compare: CompareRoute };
    const spies = Object.entries(screens).map(([name, s]) => [name, vi.spyOn(s, "preload").mockImplementation(() => {})] as const);
    preloadRoute(pathname);
    return spies.filter(([, spy]) => spy.mock.calls.length > 0).map(([name]) => name);
  };

  it.each([
    ["/", ["/"]],
    ["/statistics/pay", ["/statistics"]],
    ["/settings/plugins/levels", ["/settings"]],
    ["/company", ["/company"]],
    ["/company/acme", ["/company"]],
    ["/company/acme/job/12", ["position"]],
    ["/job/12", ["position"]],
    ["/compare", ["compare"]],
    ["/welcome", []],
    ["/favoritesx", []],
  ])("%s fetches %j", (pathname, expected) => {
    expect(fetched(pathname)).toEqual(expected);
  });
});

describe("the screens fetched after the first has drawn", () => {
  afterEach(() => vi.restoreAllMocks());

  it("are every tab and both covers, each fetched after the one before has arrived", async () => {
    const screens = [...Object.values(ROUTE_COMPONENTS), PositionRoute, CompareRoute];
    const arrivals = screens.map(() => {
      let arrive!: () => void;
      const arrived = new Promise<{ default: () => null }>((done) => { arrive = () => done({ default: () => null }); });
      return { arrive, arrived };
    });
    const loads = screens.map((s, i) => vi.spyOn(s, "load").mockImplementation(() => arrivals[i].arrived));

    const done = preloadScreens();
    for (let i = 0; i < screens.length; i++) {
      await settle();
      expect(loads.map((spy) => spy.mock.calls.length)).toEqual(screens.map((_, j) => (j <= i ? 1 : 0)));
      arrivals[i].arrive();
    }
    await done;
  });

  it("go on past a screen that cannot be fetched", async () => {
    const screens = [...Object.values(ROUTE_COMPONENTS), PositionRoute, CompareRoute];
    const loads = screens.map((s, i) =>
      vi.spyOn(s, "load").mockImplementation(() =>
        i === 0 ? Promise.reject(new Error("chunk gone")) : Promise.resolve({ default: () => null }),
      ),
    );
    await preloadScreens();
    expect(loads.every((spy) => spy.mock.calls.length === 1)).toBe(true);
  });
});
