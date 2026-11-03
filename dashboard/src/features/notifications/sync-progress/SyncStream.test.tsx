import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { isRunComplete, isSyncStale, parseSyncProgress, type SyncClock, type SyncProgress } from "./model";
import { SyncStream, inFlight } from "./SyncStream";

const NOW = 1_785_000_000_000;

const company = (over: Record<string, unknown> = {}) => ({
  slug: "google",
  state: "queued",
  outcome: null,
  since_ms: null,
  detected: 0,
  scanned: 0,
  recorded: 0,
  ...over,
});

function progressOf(
  companies: Record<string, unknown>[],
  over: Record<string, unknown> = {},
): SyncProgress {
  return parseSyncProgress({
    progress: {
      phase: "collecting",
      percent: 20,
      companies_total: companies.length,
      companies_queued: companies.filter((c) => c.state === "queued").length,
      opportunities_detected: 0,
      opportunities_recorded: 0,
      opportunities_pending: 0,
      concurrency_limit: 5,
      snapshot_at_ms: NOW,
      companies,
      ...over,
    },
  })!;
}

const clock = (over: Partial<SyncClock> = {}): SyncClock => ({
  nowMs: NOW,
  skewMs: 0,
  staleMs: 0,
  ...over,
});

/** jsdom has a matchMedia stub; point it at "reduce" for the motion tests. */
function preferReducedMotion(reduce: boolean) {
  vi.stubGlobal("matchMedia", (query: string) => ({
    matches: reduce && query.includes("prefers-reduced-motion"),
    media: query,
    addEventListener: () => {},
    removeEventListener: () => {},
    addListener: () => {},
    removeListener: () => {},
    onchange: null,
    dispatchEvent: () => false,
  }));
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("inFlight", () => {
  it("selects only sources with a clock running", () => {
    const rows = inFlight(
      progressOf([
        company({ slug: "a", state: "queued" }),
        company({ slug: "b", state: "scraping", since_ms: NOW - 1000 }),
        company({ slug: "c", state: "collected", outcome: "ok" }),
        company({ slug: "d", state: "persisting", outcome: "ok", since_ms: NOW - 500 }),
        company({ slug: "e", state: "recorded", outcome: "ok" }),
      ]).companies,
      5,
    );
    expect(rows.map((r) => r.slug)).toEqual(["b", "d"]);
  });

  it("puts the longest-running source first, where the risk is", () => {
    const rows = inFlight(
      progressOf([
        company({ slug: "young", state: "scraping", since_ms: NOW - 1_000 }),
        company({ slug: "old", state: "scraping", since_ms: NOW - 90_000 }),
        company({ slug: "middle", state: "scraping", since_ms: NOW - 30_000 }),
      ]).companies,
      5,
    );
    expect(rows.map((r) => r.slug)).toEqual(["old", "middle", "young"]);
  });

  it("never shows more channels than the collector can actually run", () => {
    const many = Array.from({ length: 9 }, (_, i) =>
      company({ slug: `c${i}`, state: "scraping", since_ms: NOW - i * 1000 }),
    );
    expect(inFlight(progressOf(many).companies, 3)).toHaveLength(3);
  });
});

describe("SyncStream", () => {
  it("names every source it draws and shows its elapsed clock", () => {
    render(
      <SyncStream
        progress={progressOf([
          company({ slug: "amazon", state: "scraping", since_ms: NOW - 184_000 }),
          company({ slug: "meta", state: "scraping", since_ms: NOW - 28_000 }),
        ])}
        clock={clock()}
      />,
    );
    expect(screen.getByText("Amazon")).toBeInTheDocument();
    expect(screen.getByText("3m 04s")).toBeInTheDocument();
    expect(screen.getByText("Meta")).toBeInTheDocument();
    expect(screen.getByText("28s")).toBeInTheDocument();
  });

  it("applies the estimated clock skew to elapsed time", () => {
    render(
      <SyncStream
        progress={progressOf([
          company({ slug: "amazon", state: "scraping", since_ms: NOW - 10_000 }),
        ])}
        clock={clock({ skewMs: 20_000 })}
      />,
    );
    expect(screen.getByText("30s")).toBeInTheDocument();
  });

  it("says what it is waiting for when nothing has started", () => {
    render(
      <SyncStream
        progress={progressOf([company({ slug: "a" }), company({ slug: "b" })])}
        clock={clock()}
      />,
    );
    expect(screen.getByText(/Waiting for the first company/)).toBeInTheDocument();
    expect(screen.getByText(/2 waiting/)).toBeInTheDocument();
  });

  it("switches its idle copy when collection is over", () => {
    render(
      <SyncStream
        progress={progressOf([company({ slug: "a", state: "collected", outcome: "ok" })], {
          phase: "persisting",
        })}
        clock={clock()}
      />,
    );
    expect(screen.getByText("Adding the last roles")).toBeInTheDocument();
  });

  it("reports both tank volumes, which is what replaces the old paragraph", () => {
    render(
      <SyncStream
        progress={progressOf([company({ slug: "a", state: "scraping", since_ms: NOW })], {
          opportunities_detected: 214,
          opportunities_pending: 214,
          opportunities_recorded: 0,
        })}
        clock={clock()}
      />,
    );
    expect(
      screen.getByRole("img", {
        name: /0 roles from finished companies, 214 from companies still scanning/,
      }),
    ).toBeInTheDocument();
  });

  it("splits the roles by whether their company's scan has ended, never by whether they are kept", () => {
    // Roles reach the radar seconds after a page is read, so a split worded as
    // recorded / not recorded tells the person found roles are not kept yet.
    render(
      <SyncStream
        progress={progressOf([company({ slug: "a", state: "scraping", since_ms: NOW })], {
          opportunities_detected: 4,
          opportunities_pending: 3,
          opportunities_recorded: 1,
        })}
        clock={clock()}
      />,
    );
    const box = screen.getByRole("img", { name: /1 role from finished companies, 3 from companies still scanning\./ });
    expect(box).toHaveTextContent("Still scanning");
    expect(box).toHaveTextContent("1 finished");
    expect(box).toHaveTextContent("Roles found");
    expect(box.textContent).not.toMatch(/record/i);
    expect(box.getAttribute("aria-label")).not.toMatch(/record/i);
  });

  it("never draws a negative band when closure commits more than this run found", () => {
    // The backend clamps `opportunities_pending`; the band must read from it
    // rather than recomputing detected - recorded.
    render(
      <SyncStream
        progress={progressOf([company({ slug: "a", state: "recorded", outcome: "ok" })], {
          phase: "persisting",
          opportunities_detected: 2,
          opportunities_recorded: 9,
          opportunities_pending: 0,
        })}
        clock={clock()}
      />,
    );
    expect(
      screen.getByRole("img", { name: /9 roles from finished companies, 0 from companies still scanning/ }),
    ).toBeInTheDocument();
  });

  it("flows while a source is running", () => {
    preferReducedMotion(false);
    render(
      <SyncStream
        progress={progressOf([company({ slug: "a", state: "scraping", since_ms: NOW })])}
        clock={clock()}
      />,
    );
    expect(screen.getByRole("img")).toHaveAttribute("data-flow", "on");
  });

  it("stops flowing when the reader asked for reduced motion", () => {
    preferReducedMotion(true);
    render(
      <SyncStream
        progress={progressOf([company({ slug: "a", state: "scraping", since_ms: NOW })])}
        clock={clock()}
      />,
    );
    expect(screen.getByRole("img")).toHaveAttribute("data-flow", "off");
  });

  it("stops flowing and says so when the run goes quiet", () => {
    preferReducedMotion(false);
    render(
      <SyncStream
        progress={progressOf([company({ slug: "a", state: "scraping", since_ms: NOW - 5_000 })])}
        clock={clock({ staleMs: 120_000 })}
      />,
    );
    expect(screen.getByRole("img")).toHaveAttribute("data-flow", "off");
    expect(screen.getByText(/No update for 2m 00s/)).toBeInTheDocument();
  });
});

describe("a finished run", () => {
  /* The `sync_started` row is never flipped out of `running` — a completed run
     gets a separate terminal notification — so the panel has to work out for
     itself that there is nothing left to wait for. */
  const done = () =>
    progressOf(
      [
        company({ slug: "google", state: "recorded", outcome: "ok", detected: 4, recorded: 4 }),
        company({ slug: "meta", state: "recorded", outcome: "capped", detected: 2, recorded: 2 }),
      ],
      {
        phase: "persisting",
        percent: 100,
        companies_total: 2,
        companies_recorded: 2,
        opportunities_detected: 6,
        opportunities_recorded: 6,
        opportunities_pending: 0,
      },
    );

  it("knows every source has been committed", () => {
    expect(isRunComplete(done())).toBe(true);
  });

  it("does not accuse a completed run of having stalled", () => {
    // Publishing stops when the run ends, so staleness is expected here.
    expect(isSyncStale(clock({ staleMs: 600_000 }), true)).toBe(false);
    render(<SyncStream progress={done()} clock={clock({ staleMs: 600_000 })} />);
    expect(screen.queryByText(/may have stopped/)).not.toBeInTheDocument();
    expect(screen.getByText("Scan finished")).toBeInTheDocument();
  });

  it("still warns when a run goes quiet with work outstanding", () => {
    const midRun = progressOf(
      [company({ slug: "meta", state: "scraping", since_ms: NOW - 5_000 })],
      { companies_total: 2, companies_recorded: 0 },
    );
    expect(isRunComplete(midRun)).toBe(false);
    render(<SyncStream progress={midRun} clock={clock({ staleMs: 600_000 })} />);
    expect(screen.getByText(/may have stopped/)).toBeInTheDocument();
  });
});

describe("tank readout legibility", () => {
  /* The on-disk band spans empty to full, so no fixed label position is reliably
     over one surface. Each readout must pick its fill from what is behind it. */
  const tank = (recorded: number, pending: number) =>
    progressOf([company({ slug: "a", state: "scraping", since_ms: NOW })], {
      opportunities_detected: recorded + pending,
      opportunities_recorded: recorded,
      opportunities_pending: pending,
    });

  const classesOf = (container: HTMLElement) =>
    [...container.querySelectorAll("text")].map(
      (t) => `${t.textContent}|${t.getAttribute("class")}`,
    );

  it("keeps the held readout light while the tank is empty", () => {
    const { container } = render(<SyncStream progress={tank(0, 214)} clock={clock()} />);
    const held = classesOf(container).find((c) => c.startsWith("214|"))!;
    expect(held).not.toContain("on-band");
  });

  it("flips every readout the band has risen behind to dark", () => {
    const { container } = render(<SyncStream progress={tank(214, 0)} clock={clock()} />);
    const classes = classesOf(container);
    expect(classes.find((c) => c.startsWith("0|"))).toContain("on-band");
    expect(classes.find((c) => c.startsWith("Still scanning|"))).toContain("on-band");
    expect(classes.find((c) => c.startsWith("214 finished|"))).toContain("on-band");
    // The caption below the tank is never behind the band.
    expect(classes.find((c) => c.startsWith("Roles found|"))).not.toContain("on-band");
  });

  it("does not stack the disk label on top of the held readout when the tank fills", () => {
    const { container } = render(<SyncStream progress={tank(214, 0)} clock={clock()} />);
    const y = (text: string) =>
      Number(
        [...container.querySelectorAll("text")]
          .find((t) => t.textContent === text)!
          .getAttribute("y"),
      );
    expect(y("214 finished") - y("Still scanning")).toBeGreaterThan(14);
  });
});
