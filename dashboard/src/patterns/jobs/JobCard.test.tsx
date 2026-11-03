import { cleanup, render as rtlRender, screen } from "@testing-library/react";
import type { ReactElement, ReactNode } from "react";
import { MemoryRouter } from "react-router-dom";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { jobFixture } from "../../test/fixtures";
import { JobCard } from "./JobCard";
import { isStanding } from "./JobBadges";
import { msg } from "../../test/msg";

// JobCard renders CompanyChip, which navigates via react-router — needs a Router.
const Wrap = ({ children }: { children: ReactNode }) => <MemoryRouter>{children}</MemoryRouter>;
const render = (ui: ReactElement) => rtlRender(ui, { wrapper: Wrap });

describe("JobCard", () => {
  /* A posting that names no level is stored at Mid for sorting
     only; the row says so instead of claiming Mid-level. */
  it("marks a role whose posting names no level, and never calls it Mid-level", () => {
    const card = (job: typeof jobFixture) => (
      <JobCard job={job} onOpen={vi.fn()} onToggleFav={vi.fn()} compareOn={false} onToggleCompare={vi.fn()} />
    );
    const { rerender, container } = render(card({
      ...jobFixture, level_band: "mid", level_confidence: "unconfirmed", level_basis: "none",
    }));
    const fact = container.querySelector(".job-band");
    expect(fact).toHaveTextContent(/^level not stated$/);
    expect(fact).toHaveAttribute("title", "The posting names no level");

    // "Senior Manager" names a level in the company's own terms we cannot
    // place: the row says so, never "not stated", never the guess.
    rerender(card({ ...jobFixture, title: "Senior Manager, Data Science", level_band: "staff",
      level_confidence: "confirmed", level_basis: "unmapped" }));
    expect(container.querySelector(".job-band")).toHaveTextContent(/^level not mapped$/);

    // Control: a stated Mid keeps its band word.
    rerender(card({ ...jobFixture, level_band: "mid", level_confidence: "confirmed", level_basis: "generic" }));
    expect(container.querySelector(".job-band")).toHaveTextContent(/^Mid-level$/);
  });

  /* The city line. Sources publish several cities in one string
     and again as separate entries; the cell shows the first, counts the
     rest, and keeps the whole list reachable — as the cell's tooltip for a
     pointer, as text after the count for a reader. */
  it("shows the posting's first city and counts the others, with the full list reachable", () => {
    const { rerender } = render(
      <JobCard
        job={{ ...jobFixture, locations: ["San Francisco, CA | New York City, NY", "Seattle, WA", "New York City, NY"] }}
        onOpen={vi.fn()} onToggleFav={vi.fn()} compareOn={false} onToggleCompare={vi.fn()}
      />
    );
    const cell = screen.getByRole("article").querySelector(".jr-loc")!;
    expect(cell.querySelector(".job-location")).toHaveTextContent(/^San Francisco, CA \+2/);
    expect(cell).toHaveAttribute("title", "San Francisco, CA · New York City, NY · Seattle, WA");
    expect(cell.querySelector(".job-loc-more .sr-only")).toHaveTextContent(msg("jobs-loc-more", { places: "New York City, NY and Seattle, WA" }));
    // The region sits in the same cell, under the city, not beside it as a fact.
    expect(cell.querySelector(".job-loc-group")).toHaveTextContent("Silicon Valley");

    rerender(
      <JobCard job={jobFixture} onOpen={vi.fn()} onToggleFav={vi.fn()} compareOn={false} onToggleCompare={vi.fn()} />
    );
    expect(cell.querySelector(".job-loc-more")).toBeNull();
    expect(cell).not.toHaveAttribute("title");
  });

  /* s and c are the row's own keys, a bare letter each. Held with Cmd or Ctrl
     they are the browser's: Cmd+C copies, Cmd+S saves the page. The row must
     neither toggle Compare or Save, nor swallow the shortcut. */
  it("answers s and c bare, and leaves them to the browser when a modifier is held", async () => {
    const onToggleFav = vi.fn();
    const onToggleCompare = vi.fn();
    render(
      <JobCard job={jobFixture} onOpen={vi.fn()} onToggleFav={onToggleFav} compareOn={false} onToggleCompare={onToggleCompare} />
    );
    const user = userEvent.setup();
    screen.getByRole("article").focus();

    await user.keyboard("{Meta>}c{/Meta}{Control>}c{/Control}{Meta>}s{/Meta}{Control>}s{/Control}{Alt>}s{/Alt}");
    expect(onToggleCompare).not.toHaveBeenCalled();
    expect(onToggleFav).not.toHaveBeenCalled();

    await user.keyboard("cs");
    expect(onToggleCompare).toHaveBeenCalledTimes(1);
    expect(onToggleFav).toHaveBeenCalledTimes(1);
  });

  it("puts the age under the numeral, in the comp cell", () => {
    render(
      <JobCard job={jobFixture} onOpen={vi.fn()} onToggleFav={vi.fn()} compareOn={false} onToggleCompare={vi.fn()} />
    );
    const row = screen.getByRole("article");
    expect(row.querySelector(".jr-comp .comp")).toHaveTextContent("$400K");
    expect(row.querySelector(".jr-comp .jr-age")).toHaveTextContent("1 day");
    expect(row.querySelector(".jr-meta-row")).toBeNull();
  });

  it("says a role is new through its row state and its age, not a chip on the facts", () => {
    render(
      <JobCard job={{ ...jobFixture, days_open: 0, listed_days: 0, new_listing: true }} onOpen={vi.fn()} onToggleFav={vi.fn()} compareOn={false} onToggleCompare={vi.fn()} />
    );
    const row = screen.getByRole("article");
    expect(row.className).toContain("is-new");
    expect(row.querySelector(".jr-comp .jr-age")).toHaveTextContent("today");
    expect(row.querySelector(".job-meta .badge-new")).toBeNull();
    expect(screen.queryByText(/^new( today)?$/i)).toBeNull();
  });

  it("lights only what the server calls new, so the row and the header's New count agree", () => {
    // A company followed today: its first read finds a role we saw this
    // morning that was already up. Its age reads "today" and it is not new.
    render(
      <JobCard job={{ ...jobFixture, days_open: 0, listed_days: 0, new_listing: false }} onOpen={vi.fn()} onToggleFav={vi.fn()} compareOn={false} onToggleCompare={vi.fn()} />
    );
    const row = screen.getByRole("article");
    expect(row.querySelector(".jr-comp .jr-age")).toHaveTextContent("today");
    expect(row.className).not.toContain("is-new");
  });

  it("shows how long the posting has been listed, not how long we have watched it", () => {
    // A board we started reading 62 days ago holds a posting its
    // employer dated 164 days ago. The row says 164, and a posting we first
    // saw today is not fresh when its employer dated it months ago.
    render(
      <JobCard
        job={{ ...jobFixture, days_open: 0, listed_days: 164, listed_since: "2026-04-16T00:00:00Z", listed_basis: "employer" }}
        onOpen={vi.fn()}
        onToggleFav={vi.fn()}
        compareOn={false}
        onToggleCompare={vi.fn()}
      />
    );
    const row = screen.getByRole("article");
    const age = row.querySelector(".jr-comp .jr-age");
    expect(age).toHaveTextContent("164 days");
    // The tooltip names where the age counts from.
    expect(age).toHaveAttribute("title", expect.stringMatching(/^Listed since Apr 1[56], 2026, the employer's date$/));
    expect(row.className).not.toContain("is-new");
  });

  it("renders a lens's foot line under the facts, and only when given one", () => {
    const { rerender } = render(
      <JobCard job={jobFixture} onOpen={vi.fn()} onToggleFav={vi.fn()} compareOn={false} onToggleCompare={vi.fn()} />
    );
    expect(screen.queryByText("Always exclude team “API”")).toBeNull();
    rerender(
      <JobCard job={jobFixture} onOpen={vi.fn()} onToggleFav={vi.fn()} compareOn={false} onToggleCompare={vi.fn()}
        foot={<button type="button">Always exclude team “API”</button>} />
    );
    const foot = screen.getByRole("button", { name: "Always exclude team “API”" });
    // Under the role cell, after the facts — never in the actions column.
    expect(foot.closest(".jr-role")).not.toBeNull();
    expect(foot.closest(".jr-actions")).toBeNull();
  });

  /* One role its employer lists once per place says so on the row,
     with its own words, never the repost chip's "N postings". */
  it("says how many places a role is listed in, and only for a place set", () => {
    const card = (job: typeof jobFixture) => (
      <JobCard job={job} onOpen={vi.fn()} onToggleFav={vi.fn()} compareOn={false} onToggleCompare={vi.fn()} />
    );
    const { rerender } = render(card({ ...jobFixture, place_count: 10 }));
    expect(screen.getByText("Listed in 10 places")).toBeInTheDocument();
    expect(screen.queryByText(/postings/)).not.toBeInTheDocument();
    rerender(card({ ...jobFixture, place_count: null }));
    expect(screen.queryByText(/Listed in/)).not.toBeInTheDocument();
    rerender(card({ ...jobFixture, place_count: 1 }));
    expect(screen.queryByText(/Listed in/)).not.toBeInTheDocument();
  });

  /* A role listed again at its one place says how many times; a
     role at several places keeps the places chip, which Job detail expands. */
  it("says how many times a role is listed at its one place", () => {
    const card = (job: typeof jobFixture) => (
      <JobCard job={job} onOpen={vi.fn()} onToggleFav={vi.fn()} compareOn={false} onToggleCompare={vi.fn()} />
    );
    const { rerender } = render(card({ ...jobFixture, place_count: 1, place_set_size: 3 }));
    expect(screen.getByText("Listed 3 times")).toBeInTheDocument();
    rerender(card({ ...jobFixture, place_count: 2, place_set_size: 4 }));
    expect(screen.getByText("Listed in 2 places")).toBeInTheDocument();
    expect(screen.queryByText(/times/)).not.toBeInTheDocument();
    rerender(card({ ...jobFixture, place_count: null, place_set_size: null }));
    expect(screen.queryByText(/Listed/)).not.toBeInTheDocument();
  });

  it("renders role evidence and its base salary, never the total", () => {
    render(
      <JobCard
        job={jobFixture}
        onOpen={vi.fn()}
        onToggleFav={vi.fn()}
        compareOn={false}
        onToggleCompare={vi.fn()}
      />
    );

    expect(screen.getByText("Staff Product Manager, API")).toBeInTheDocument();
    expect(screen.getByText("OpenAI")).toBeInTheDocument();
    expect(screen.getByText("Staff")).toBeInTheDocument();
    expect(screen.getByText("Product & Program")).toBeInTheDocument();
    expect(screen.getByText("Silicon Valley")).toBeInTheDocument();
    expect(screen.getByText("$400K")).toBeInTheDocument();
    expect(screen.queryByText(/\$650K|\$735K|\$820K/)).toBeNull();
    expect(screen.getByText("1 day")).toBeInTheDocument();
  });

  describe("the Base cell", () => {
    const cell = (job: Partial<typeof jobFixture>) => {
      render(<JobCard job={{ ...jobFixture, ...job }} onOpen={vi.fn()} onToggleFav={vi.fn()} compareOn={false} onToggleCompare={vi.fn()} />);
      return screen.getByRole("article").querySelector(".jr-comp .comp") as HTMLElement;
    };
    // What a sighted reader sees, and what assistive tech alone hears.
    const seen = (comp: HTMLElement) => [...comp.childNodes]
      .filter((n) => !(n instanceof HTMLElement && n.classList.contains("sr-only")))
      .map((n) => n.textContent).join("");
    const spoken = (comp: HTMLElement) => [...comp.querySelectorAll(".sr-only")].map((n) => n.textContent?.trim());
    const posted = (min: number | null, max: number | null, currency = "USD", period: "year" | "hour" | "month" = "year") =>
      ({ posted_base: { min, max, currency, period } });

    it("shows a posted range from its low end, over the estimate, and says its source on hover and to a screen reader", () => {
      const comp = cell(posted(150_000, 200_000));
      expect(seen(comp)).toBe("$150K+");
      expect(comp).toHaveAttribute("title", "Posted range: $150K to $200K");
      expect(spoken(comp)).toEqual(["Posted range: $150K to $200K"]);
    });

    it("shows a posted single figure without a plus", () => {
      const comp = cell(posted(150_000, 150_000));
      expect(seen(comp)).toBe("$150K");
      expect(comp).toHaveAttribute("title", "Posted base salary: $150K");
    });

    it("keeps a posted hourly or foreign range in its own unit and currency, never converted", () => {
      expect(seen(cell(posted(45, 60, "USD", "hour")))).toBe("$45+ / hr");
      cleanup();
      expect(seen(cell(posted(60_000, 80_000, "GBP")))).toBe("£60K+");
    });

    it("shows the estimated base as one figure and says it is ours", () => {
      const comp = cell({ posted_base: null });
      expect(seen(comp)).toBe("$400K");
      expect(comp).toHaveAttribute("title", "Our estimate for this level");
      expect(spoken(comp)).toEqual(["Our estimate for this level"]);
    });

    it("leaves the cell empty when no base is known, even with a total, and the age stays on line two", () => {
      const comp = cell({ posted_base: null, comp_base_low: null, comp_base_median: null, comp_base_high: null });
      expect(seen(comp)).toBe("");
      expect(spoken(comp)).toEqual(["Base salary not known"]);
      expect(comp).not.toHaveAttribute("title");
      expect(screen.getByRole("article").querySelector(".jr-comp .jr-age")).toHaveTextContent("1 day");
    });
  });

  it("puts the position first and states its facts as text, never as pills or plates", () => {
    render(
      <JobCard
        job={{ ...jobFixture, why_world: "ai_ml" }}
        onOpen={vi.fn()}
        onToggleFav={vi.fn()}
        compareOn={false}
        onToggleCompare={vi.fn()}
      />
    );
    const row = screen.getByRole("article");
    const title = screen.getByRole("heading", { name: "Staff Product Manager, API" });
    const meta = row.querySelector(".job-meta")!;
    // Reading order: the title is above the meta line in the DOM.
    expect(title.compareDocumentPosition(meta) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    // The four facts are plain text on one line (the company's mark is
    // aria-hidden decoration — a monogram letter is not part of the name)...
    const visible = (el: Element) => {
      const clone = el.cloneNode(true) as Element;
      clone.querySelectorAll("[aria-hidden]").forEach((n) => n.remove());
      return clone.textContent?.trim();
    };
    const facts = [...meta.querySelectorAll(".job-fact")].map(visible);
    expect(facts).toEqual(["OpenAI", "Staff", "Product & Program", "AI & Machine Learning"]);
    // ...and none of them wears a category chip; location has no plate either.
    expect(row.querySelector(".ui-badge-tag")).toBeNull();
    expect(row.querySelector(".ui-badge-accent")).toBeNull();
    expect(row.querySelector(".comp-bar")).toBeNull();
    expect(row.querySelector(".jr-loc")).toHaveTextContent("San Francisco");
    expect(screen.getByText("Silicon Valley")).toHaveClass("job-loc-group");
  });

  it("keeps card open, favorite, and compare actions independent", async () => {
    const user = userEvent.setup();
    const onOpen = vi.fn();
    const onToggleFav = vi.fn();
    const onToggleCompare = vi.fn();

    render(
      <JobCard
        job={jobFixture}
        onOpen={onOpen}
        onToggleFav={onToggleFav}
        compareOn={false}
        onToggleCompare={onToggleCompare}
      />
    );

    await user.click(screen.getByLabelText(msg("jobs-compare")));
    expect(onToggleCompare).toHaveBeenCalledTimes(1);
    expect(onOpen).not.toHaveBeenCalled();

    await user.click(screen.getByLabelText("Save"));
    expect(onToggleFav).toHaveBeenCalledTimes(1);
    expect(onOpen).not.toHaveBeenCalled();

    await user.click(screen.getByText("Staff Product Manager, API"));
    expect(onOpen).toHaveBeenCalledTimes(1);
  });

  /* The row's keys are advertised: the row declares them, and each action's
     tooltip names its own. */
  it("names the row's keys: on the row itself, and in each action's tooltip", () => {
    render(
      <JobCard job={jobFixture} onOpen={vi.fn()} onToggleFav={vi.fn()} compareOn={false} onToggleCompare={vi.fn()} />
    );
    expect(screen.getByRole("article")).toHaveAttribute("aria-keyshortcuts", "Enter s c");
    expect(screen.getByLabelText(msg("jobs-compare"))).toHaveAttribute("title", msg("jobs-compare-title", { key: "c" }));
    expect(screen.getByLabelText("Save")).toHaveAttribute("title", "Save (s)");
  });

  it("supports keyboard control on the focused row: enter opens, s saves, c compares", async () => {
    const user = userEvent.setup();
    const onOpen = vi.fn();
    const onToggleFav = vi.fn();
    const onToggleCompare = vi.fn();

    render(
      <JobCard
        job={jobFixture}
        onOpen={onOpen}
        onToggleFav={onToggleFav}
        compareOn={false}
        onToggleCompare={onToggleCompare}
      />
    );

    const row = screen.getByRole("article");
    row.focus();
    await user.keyboard("{Enter}");
    expect(onOpen).toHaveBeenCalledTimes(1);
    await user.keyboard("s");
    expect(onToggleFav).toHaveBeenCalledTimes(1);
    await user.keyboard("c");
    expect(onToggleCompare).toHaveBeenCalledTimes(1);
  });

  it("shows a match badge naming the retrieval sources only on the Best-match path", () => {
    const { rerender } = render(
      <JobCard
        job={{ ...jobFixture, relevance: 0.031, matched_via: ["keyword", "fuzzy"] }}
        onOpen={vi.fn()}
        onToggleFav={vi.fn()}
        compareOn={false}
        onToggleCompare={vi.fn()}
      />
    );
    // Names the sources (bucketed), never the raw fusion score.
    expect(screen.getByText("Keyword · Fuzzy")).toBeInTheDocument();
    expect(screen.queryByText(/0\.031/)).not.toBeInTheDocument();

    // Legacy path: no matched_via → no badge.
    rerender(
      <JobCard
        job={jobFixture}
        onOpen={vi.fn()}
        onToggleFav={vi.fn()}
        compareOn={false}
        onToggleCompare={vi.fn()}
      />
    );
    expect(screen.queryByTitle(/matched via/i)).not.toBeInTheDocument();
  });

  it("labels the match class qualitatively and never promotes a related row", () => {
    // A family-conflict candidate (Product Manager against
    // an Applied Science Manager query) arrives as match_class="related" and
    // must render "Related" — never "Exact title" or "Close title".
    const { rerender } = render(
      <JobCard
        job={{ ...jobFixture, match_class: "related", matched_via: ["keyword"] }}
        onOpen={vi.fn()}
        onToggleFav={vi.fn()}
        compareOn={false}
        onToggleCompare={vi.fn()}
      />
    );
    expect(screen.getByText(msg("jobs-match-partial"))).toBeInTheDocument();
    expect(screen.queryByText("Exact match")).not.toBeInTheDocument();
    expect(screen.queryByText("Close title")).not.toBeInTheDocument();

    // The identity claim is the CLASS chip; "exact" is not a retrieval source,
    // so the via badge shows only the textual sources beside it.
    rerender(
      <JobCard
        job={{ ...jobFixture, match_class: "exact", matched_via: ["exact", "keyword"] }}
        onOpen={vi.fn()}
        onToggleFav={vi.fn()}
        compareOn={false}
        onToggleCompare={vi.fn()}
      />
    );
    expect(screen.getByText("Exact match")).toBeInTheDocument();
    expect(screen.getByText("Keyword")).toBeInTheDocument();

    rerender(
      <JobCard
        job={{ ...jobFixture, match_class: "close", matched_via: ["keyword"] }}
        onOpen={vi.fn()}
        onToggleFav={vi.fn()}
        compareOn={false}
        onToggleCompare={vi.fn()}
      />
    );
    expect(screen.getByText(msg("jobs-match-close"))).toBeInTheDocument();

    // No class (legacy / queryless path) → no class chip at all.
    rerender(
      <JobCard job={jobFixture} onOpen={vi.fn()} onToggleFav={vi.fn()} compareOn={false} onToggleCompare={vi.fn()} />
    );
    expect(screen.queryByText(/Exact match|Close title|^Related$/)).not.toBeInTheDocument();
  });

  it("shows a stacked 'N postings' badge and lineage age when the role is a lineage", () => {
    render(
      <JobCard
        job={{ ...jobFixture, lineage_id: 3, lineage_size: 3, lineage_role: "repost", listed_days: 118, days_open: 1 }}
        onOpen={vi.fn()}
        onToggleFav={vi.fn()}
        compareOn={false}
        onToggleCompare={vi.fn()}
      />
    );
    expect(screen.getByText("3 postings")).toBeInTheDocument();
    expect(screen.getByRole("article").className).toContain("is-stacked");
    // Age is the listing age (118d, from the lineage), not this posting's 1 day.
    expect(screen.getByText("118 days")).toBeInTheDocument();
  });

  it("shows neither the stacked badge nor is-stacked for a standalone job", () => {
    render(
      <JobCard
        job={jobFixture}
        onOpen={vi.fn()}
        onToggleFav={vi.fn()}
        compareOn={false}
        onToggleCompare={vi.fn()}
      />
    );
    expect(screen.queryByText(/postings/)).not.toBeInTheDocument();
    expect(screen.getByRole("article").className).not.toContain("is-stacked");
  });

  /* The Board shows Job detail's standing-posting verdict, only at
     `possible`, with each sign named in the title in Job detail's words. */
  it("marks a possible standing posting and names its signs, and nothing below that", () => {
    const row = (reality: Parameters<typeof isStanding>[0]) => (
      <JobCard
        job={{ ...jobFixture, posting_reality: reality }}
        onOpen={vi.fn()} onToggleFav={vi.fn()} compareOn={false} onToggleCompare={vi.fn()}
      />
    );
    const possible = { level: "possible" as const, met: ["long_open" as const, "relisted" as const], criteria_total: 3, listings: 4 };
    const { rerender } = render(row(possible));
    const badge = screen.getByText("May be always open");
    expect(badge).toHaveAttribute(
      "title",
      "May be an always-open posting: listed for a long time and listed 4 times. " +
        "Patterns in how it is listed, not a verdict on the company. It may still be hiring.",
    );

    for (const quiet of [
      { ...possible, level: "none" as const, met: ["long_open" as const] },
      null,
      undefined,
    ]) {
      rerender(row(quiet));
      expect(screen.queryByText("May be always open")).toBeNull();
    }
  });

  it("exposes compare-full state without disabling removal", () => {
    const { rerender } = render(
      <JobCard
        job={jobFixture}
        onOpen={vi.fn()}
        onToggleFav={vi.fn()}
        compareOn={false}
        compareDisabled
        onToggleCompare={vi.fn()}
      />
    );

    // Full, it cannot add this role, but it stays focusable and carries why
    // as its description: a disabled button takes no focus, so its reason in
    // a tooltip reached nobody without a pointer.
    const full = screen.getByLabelText(msg("jobs-compare"));
    expect(full).not.toBeDisabled();
    expect(full).toHaveAttribute("aria-disabled", "true");
    expect(full).toHaveAccessibleDescription(msg("jobs-compare-full"));
    full.focus();
    expect(full).toHaveFocus();

    rerender(
      <JobCard
        job={jobFixture}
        onOpen={vi.fn()}
        onToggleFav={vi.fn()}
        compareOn
        compareDisabled
        onToggleCompare={vi.fn()}
      />
    );

    expect(screen.getByLabelText(msg("jobs-compare"))).not.toBeDisabled();
    expect(screen.getByLabelText(msg("jobs-compare"))).not.toHaveAttribute("aria-disabled");
  });

  it("a full Compare ignores a press: it adds nothing", async () => {
    const onToggleCompare = vi.fn();
    render(
      <JobCard job={jobFixture} onOpen={vi.fn()} onToggleFav={vi.fn()} compareOn={false} compareDisabled
        onToggleCompare={onToggleCompare} />,
    );
    await userEvent.click(screen.getByLabelText(msg("jobs-compare")));
    expect(onToggleCompare).not.toHaveBeenCalled();
  });

  // Density: pay disclosure is not a row-scanning signal — it says nothing
  // about THIS role's comp, and it would spend an eyebrow slot on every
  // disclosing row. It stays reachable as a
  // filter (FilterBar's "Discloses pay" pill), which is where a reader who
  // cares about it actually starts. The row must stay silent either way.
  it("keeps pay disclosure off the row — it is a filter, not an eyebrow chip", () => {
    const { rerender } = render(
      <JobCard
        job={jobFixture}
        onOpen={vi.fn()}
        onToggleFav={vi.fn()}
        compareOn={false}
        onToggleCompare={vi.fn()}
      />
    );
    expect(screen.queryByText("discloses pay")).not.toBeInTheDocument();

    rerender(
      <JobCard
        job={{ ...jobFixture, discloses_pay: true }}
        onOpen={vi.fn()}
        onToggleFav={vi.fn()}
        compareOn={false}
        onToggleCompare={vi.fn()}
      />
    );
    expect(screen.queryByText("discloses pay")).not.toBeInTheDocument();
  });

  // No visible "viewed" chip in the eyebrow (density): the receded row
  // carries the state for sighted readers. The
  // word itself must survive for assistive tech — a tint alone would make
  // this a colour-only state — so this asserts BOTH halves: the row class,
  // and the text present but visually hidden.
  it("distinguishes a viewed opportunity by row state, keeping the word for assistive tech", () => {
    render(
      <JobCard
        job={{ ...jobFixture, viewed_at: "2026-07-15T18:30:00Z" }}
        viewed
        onOpen={vi.fn()}
        onToggleFav={vi.fn()}
        compareOn={false}
        onToggleCompare={vi.fn()}
      />
    );

    expect(screen.getByRole("article")).toHaveClass("is-viewed");
    expect(screen.getByText("viewed")).toHaveClass("sr-only");
  });
});

describe("JobCard dismiss action", () => {
  it("offers Not-for-me without triggering open, and restore when dismissed", async () => {
    const user = userEvent.setup();
    const onOpen = vi.fn();
    const onDismiss = vi.fn();

    const { rerender } = render(
      <JobCard
        job={jobFixture}
        onOpen={onOpen}
        onToggleFav={vi.fn()}
        onDismiss={onDismiss}
        compareOn={false}
        onToggleCompare={vi.fn()}
      />
    );

    await user.click(screen.getByRole("button", { name: "Not for me" }));
    expect(onDismiss).toHaveBeenCalledTimes(1);
    expect(onOpen).not.toHaveBeenCalled();

    // The same slot restores on the Dismissed lens.
    rerender(
      <JobCard
        job={{ ...jobFixture, is_dismissed: true }}
        onOpen={onOpen}
        onToggleFav={vi.fn()}
        onDismiss={onDismiss}
        compareOn={false}
        onToggleCompare={vi.fn()}
      />
    );
    expect(screen.getByRole("button", { name: "Restore" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Not for me" })).not.toBeInTheDocument();
  });

  it("renders no dismiss control on surfaces without the concept", () => {
    render(
      <JobCard
        job={jobFixture}
        onOpen={vi.fn()}
        onToggleFav={vi.fn()}
        compareOn={false}
        onToggleCompare={vi.fn()}
      />
    );
    expect(screen.queryByRole("button", { name: "Not for me" })).not.toBeInTheDocument();
  });
});


it("names the world the server sends as a slug, and renders nothing when it sends none", () => {
  const props = {
    onOpen: vi.fn(),
    onToggleFav: vi.fn(),
    compareOn: false,
    onToggleCompare: vi.fn(),
  };
  const { rerender } = render(
    <JobCard {...props} job={{ ...jobFixture, why_world: "ai_ml", relevance: 0.83 }} />,
  );
  // The catalog's name, never the slug (the chip speaks the reader's language).
  expect(screen.getByText("AI & Machine Learning")).toBeInTheDocument();
  expect(screen.queryByText("ai_ml")).not.toBeInTheDocument();
  // The score never renders — qualitative chips only.
  expect(screen.queryByText(/0\.83|83%/)).not.toBeInTheDocument();

  rerender(<JobCard {...props} job={{ ...jobFixture, why_world: null }} />);
  expect(screen.queryByText("AI & Machine Learning")).not.toBeInTheDocument();
});

/* The Board shows only companies the user follows, so only a
   Saved or Compare row can be at one the user stopped following. It stays
   theirs, and says nothing checks it any more, with the last time a scan
   did. A followed company's row says nothing. */
it("says a saved role at a company the user stopped following is no longer checked", () => {
  const props = { onOpen: vi.fn(), onToggleFav: vi.fn(), compareOn: false, onToggleCompare: vi.fn() };
  const { rerender } = render(
    <JobCard job={{ ...jobFixture, company_unfollowed: true, last_seen: "2026-09-25T12:00:00Z" }} {...props} />
  );
  expect(screen.getByText("No longer scanned")).toHaveAttribute(
    "title",
    "You don't follow OpenAI, so this role is no longer scanned. Last seen Sep 25, 2026.",
  );
  rerender(<JobCard job={jobFixture} {...props} />);
  expect(screen.queryByText("No longer scanned")).toBeNull();
});
