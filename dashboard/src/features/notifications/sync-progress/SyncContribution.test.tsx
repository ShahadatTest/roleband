import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { parseSyncProgress, type SyncCompany, type SyncProgress } from "./model";
import {
  SyncContributionBar,
  SyncFooterCounts,
  buildSegments,
  isEmptyButFine,
  isLanded,
} from "./SyncContribution";

const landed = (slug: string, detected: number, over: Partial<SyncCompany> = {}): SyncCompany => ({
  slug,
  state: "collected",
  outcome: "ok",
  sinceMs: null,
  detected,
  scanned: detected * 10,
  recorded: 0,
  ...over,
});

function progressOf(companies: Record<string, unknown>[]): SyncProgress {
  return parseSyncProgress({
    progress: {
      phase: "collecting",
      companies_total: companies.length,
      companies_scraping: companies.filter((c) => c.state === "scraping").length,
      concurrency_limit: 5,
      companies,
    },
  })!;
}

describe("buildSegments", () => {
  it("ranks sources by what they contributed", () => {
    const segments = buildSegments(
      [landed("apple", 12), landed("google", 64), landed("meta", 30)],
      null,
    );
    expect(segments.map((s) => s.key)).toEqual(["google", "meta", "apple"]);
    expect(segments[0].value).toBe(64);
  });

  it("breaks ties deterministically so the bar does not shuffle between polls", () => {
    const segments = buildSegments([landed("zebra", 10), landed("apple", 10)], null);
    expect(segments.map((s) => s.key)).toEqual(["apple", "zebra"]);
  });

  it("excludes sources that are still working", () => {
    const segments = buildSegments(
      [landed("google", 64), landed("meta", 30, { state: "scraping", outcome: null })],
      null,
    );
    expect(segments.map((s) => s.key)).toEqual(["google"]);
  });

  it("excludes finished sources that found nothing, since they have no volume", () => {
    expect(buildSegments([landed("google", 64), landed("empty", 0)], null).map((s) => s.key)).toEqual(
      ["google"],
    );
  });

  it("returns nothing at all before any source lands", () => {
    expect(buildSegments([landed("a", 0, { state: "scraping", outcome: null })], null)).toEqual([]);
  });

  it("merges slivers too thin to read into one trailing segment", () => {
    const segments = buildSegments(
      [landed("big", 500), landed("tiny1", 3), landed("tiny2", 4), landed("tiny3", 2)],
      null,
    );
    const merged = segments[segments.length - 1];
    expect(merged.merged).toBe(true);
    expect(merged.label).toBe("+3 more");
    expect(merged.value).toBe(9);
  });

  it("keeps a lone remainder named, because '+1 more' is worse than the name", () => {
    // 3/503 is far under the merge floor, so only the lone-remainder rule keeps it.
    const segments = buildSegments([landed("big", 500), landed("tiny", 3)], null);
    expect(segments.some((s) => s.merged)).toBe(false);
    expect(segments.map((s) => s.key)).toEqual(["big", "tiny"]);
    expect(segments[segments.length - 1].value).toBe(3);
  });

  it("caps how many sources it names before merging the rest", () => {
    const many = Array.from({ length: 12 }, (_, i) => landed(`c${i}`, 100 - i));
    const segments = buildSegments(many, null);
    expect(segments.filter((s) => !s.merged)).toHaveLength(8);
    expect(segments[segments.length - 1].merged).toBe(true);
  });

  it("keeps shares summing to the whole", () => {
    const segments = buildSegments([landed("a", 60), landed("b", 30), landed("c", 10)], null);
    const total = segments.reduce((sum, s) => sum + s.pct, 0);
    expect(total).toBeCloseTo(1, 10);
  });

  it("hides an inline label that would not fit the measured container", () => {
    const companies = [landed("big", 90), landed("small", 10)];
    const wide = buildSegments(companies, 1000);
    const narrow = buildSegments(companies, 120);
    expect(wide.find((s) => s.key === "big")!.showLabel).toBe(true);
    expect(narrow.find((s) => s.key === "small")!.showLabel).toBe(false);
  });

  it("falls back to the bare count when a name will not fit but a number will", () => {
    // 8% of 1000px = 80px: too narrow for "Name 80", wide enough for "80".
    const segment = buildSegments([landed("big", 920), landed("small", 80)], 1000).find(
      (s) => s.key === "small",
    )!;
    expect(segment.showLabel).toBe(false);
    expect(segment.showCount).toBe(true);
  });

  it("shows nothing inside a segment too narrow even for a number", () => {
    const segment = buildSegments([landed("big", 9990), landed("sliver", 10)], 1000).find(
      (s) => s.key === "sliver",
    )!;
    expect(segment.showCount).toBe(false);
  });

  it("carries the companies a merged segment stands for", () => {
    const merged = buildSegments(
      [landed("big", 500), landed("apple", 3), landed("google", 4), landed("meta", 2)],
      null,
    ).find((s) => s.merged)!;
    expect(merged.members).toEqual(["Google", "Apple", "Meta"]);
  });
});

describe("outcome predicates", () => {
  it("counts a capped source as landed, never as a failure", () => {
    expect(isLanded(landed("a", 12, { outcome: "capped" }))).toBe(true);
  });

  it("counts a degraded source as landed, because it returned usable data", () => {
    expect(isLanded(landed("a", 12, { outcome: "degraded" }))).toBe(true);
  });

  it("counts sources cut by our own time/page ceiling as landed", () => {
    // Backend `_USABLE` mirror: the pages collected before OUR bound fired are
    // real observations — styling them as failures misreports our threshold
    // as the source's fault.
    expect(isLanded(landed("a", 40, { outcome: "bounded" }))).toBe(true);
    expect(isLanded(landed("a", 90, { outcome: "truncated" }))).toBe(true);
  });

  it("counts a lossy source as landed — it enumerated all but a few rows", () => {
    // `lossy` is the most complete outcome short of `ok`: the board
    // was read minus a sub-1% handful of unreadable records.
    expect(isLanded(landed("a", 81, { outcome: "lossy", scanned: 1678 }))).toBe(true);
  });

  it("counts a board proven empty as landed, read through the parser", () => {
    // `empty` is a careers page that answered in full and listed
    // nothing: a scan with no postings, never a failure. Parsed from the wire
    // shape, because an outcome the parser does not know becomes null and
    // drops out of the sync view.
    const [source] = progressOf([
      { slug: "zingage", state: "collected", outcome: "empty", detected: 0, scanned: 0 },
    ]).companies;
    expect(source.outcome).toBe("empty");
    expect(isLanded(source)).toBe(true);
    expect(isEmptyButFine(source)).toBe(true);
  });

  it("counts a scan this computer cut by sleeping as landed, read through the parser", () => {
    // `suspended`: the pages read before the laptop slept or lost its network
    // landed; the source did nothing wrong.
    const [source] = progressOf([
      { slug: "google", state: "collected", outcome: "suspended", detected: 12, scanned: 300 },
    ]).companies;
    expect(source.outcome).toBe("suspended");
    expect(isLanded(source)).toBe(true);
  });

  it("does not count a failed source as landed", () => {
    expect(isLanded(landed("a", 0, { outcome: "failed" }))).toBe(false);
  });

  it("treats a full scan that kept nothing as a success, not an empty failure", () => {
    const source = landed("a", 0, { scanned: 812 });
    expect(isLanded(source)).toBe(true);
    expect(isEmptyButFine(source)).toBe(true);
  });
});

describe("SyncContributionBar", () => {
  it("labels each segment with its source and count for assistive tech", () => {
    render(<SyncContributionBar companies={[landed("google", 64), landed("apple", 12)]} />);
    expect(screen.getByRole("listitem", { name: "Google: 64 roles" })).toBeInTheDocument();
    expect(screen.getByRole("listitem", { name: "Apple: 12 roles" })).toBeInTheDocument();
  });

  it("heads the bar by the companies it counts, and counts one role as one", () => {
    render(<SyncContributionBar companies={[landed("google", 1)]} />);
    expect(screen.getByText("Finished companies")).toBeInTheDocument();
    expect(screen.getByText("1 role")).toBeInTheDocument();
    expect(screen.getByRole("listitem", { name: "Google: 1 role" })).toBeInTheDocument();
    expect(screen.queryByText(/landed|opportunit/i)).not.toBeInTheDocument();
  });

  it("names a segment on hover even when the bar had no room to print it", () => {
    render(<SyncContributionBar companies={[landed("google", 920), landed("apple", 80)]} />);
    // jsdom leaves the container unmeasured, so the 8% segment is count-only.
    const tip = screen.getByRole("tooltip", { name: /Apple/ });
    expect(tip).toHaveTextContent("Apple · 80 roles");
    const seg = screen.getByRole("listitem", { name: "Apple: 80 roles" });
    expect(seg).toHaveAttribute("aria-describedby", tip.getAttribute("id"));
  });

  it("makes only the unlabelled segments reachable by keyboard", () => {
    render(<SyncContributionBar companies={[landed("google", 920), landed("apple", 80)]} />);
    expect(screen.getByRole("listitem", { name: /Google/ })).not.toHaveAttribute("tabindex");
    expect(screen.getByRole("listitem", { name: /Apple/ })).toHaveAttribute("tabindex", "0");
  });

  it("reveals the merged companies by name on hover", () => {
    render(
      <SyncContributionBar
        companies={[landed("big", 500), landed("apple", 3), landed("google", 4), landed("meta", 2)]}
      />,
    );
    expect(screen.getByRole("tooltip", { name: /Google, Apple, Meta/ })).toBeInTheDocument();
  });

  it("renders nothing before any source has landed", () => {
    const { container } = render(
      <SyncContributionBar companies={[landed("a", 0, { state: "scraping", outcome: null })]} />,
    );
    expect(container).toBeEmptyDOMElement();
  });
});

describe("SyncFooterCounts", () => {
  const roster = [
    { slug: "google", state: "collected", outcome: "ok", detected: 64, scanned: 900 },
    { slug: "amazon", state: "scraping", outcome: null, detected: 0, scanned: 0 },
    { slug: "netflix", state: "queued", outcome: null, detected: 0, scanned: 0 },
    { slug: "apple", state: "queued", outcome: null, detected: 0, scanned: 0 },
    { slug: "meta", state: "collected", outcome: "failed", detected: 0, scanned: 0 },
    { slug: "nvidia", state: "collected", outcome: "ok", detected: 0, scanned: 812 },
  ];

  it("names the failed source instead of leaving it a number", () => {
    render(<SyncFooterCounts progress={progressOf(roster)} />);
    expect(screen.getByText("Failed: Meta")).toBeInTheDocument();
  });

  it("names an empty-but-successful source without calling it a failure", () => {
    render(<SyncFooterCounts progress={progressOf(roster)} />);
    const line = screen.getByText(/Scanned, no roles for you/);
    expect(line).toHaveTextContent("Nvidia");
    expect(line).not.toHaveTextContent(/[Ff]ailed/);
  });

  it("names a blocked source on its own line, distinct from failures", () => {
    // "The source is refusing us" and "the source errored" need different
    // operator responses; the backend breaker establishes the distinction and
    // this footer must not collapse it.
    render(
      <SyncFooterCounts
        progress={progressOf([
          { slug: "meta", state: "collected", outcome: "blocked", detected: 0, scanned: 0 },
        ])}
      />,
    );
    expect(screen.getByText(/Blocked by their careers page: Meta/)).toBeInTheDocument();
    expect(screen.queryByText(/Failed:/)).not.toBeInTheDocument();
  });

  it("names a scan this computer paused on its own line, never as failed", () => {
    render(
      <SyncFooterCounts
        progress={progressOf([
          { slug: "google", state: "collected", outcome: "suspended", detected: 12, scanned: 300 },
        ])}
      />,
    );
    expect(screen.getByText("Paused while this computer slept or was offline: Google")).toBeInTheDocument();
    expect(screen.queryByText(/Failed:/)).not.toBeInTheDocument();
  });

  it("names a degraded source as partial rather than failed", () => {
    render(
      <SyncFooterCounts
        progress={progressOf([
          { slug: "google", state: "collected", outcome: "degraded", detected: 5, scanned: 90 },
        ])}
      />,
    );
    expect(screen.getByText("Partly scanned: Google")).toBeInTheDocument();
    expect(screen.queryByText(/Failed:/)).not.toBeInTheDocument();
  });

  it("keeps queued sources as a count until asked", () => {
    render(<SyncFooterCounts progress={progressOf(roster)} />);
    const toggle = screen.getByRole("button", { name: /waiting/ });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByText(/Netflix/)).not.toBeInTheDocument();

    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText(/Netflix/)).toHaveTextContent("Apple");
  });

  it("offers no disclosure when the queue is empty", () => {
    render(
      <SyncFooterCounts
        progress={progressOf([
          { slug: "google", state: "collected", outcome: "ok", detected: 64, scanned: 900 },
        ])}
      />,
    );
    expect(screen.queryByRole("button", { name: /waiting/ })).not.toBeInTheDocument();
  });

  it("caps a long name list rather than printing the whole roster", () => {
    const failures = Array.from({ length: 7 }, (_, i) => ({
      slug: `dead${i}`,
      state: "collected",
      outcome: "failed",
      detected: 0,
      scanned: 0,
    }));
    render(<SyncFooterCounts progress={progressOf(failures)} />);
    expect(screen.getByText(/Failed:/)).toHaveTextContent("+3 more");
  });
});
