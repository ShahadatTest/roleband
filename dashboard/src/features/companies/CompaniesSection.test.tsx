import { msg } from "../../test/msg";
import { ApiError } from "../../api/transport";
import { ToastProvider } from "../../ui/Toast";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type {
  CompanyDirectoryStatus,
  CompanyDiscoveryCompany,
  CompanyDiscoveryState,
  SyncTarget,
  TrackedCompany,
} from "../../api";
import { api } from "../../api";
import { activate } from "../../copy/activate";
import { statsFixture, statusFixture } from "../../test/fixtures";
import { AppProviders } from "../../context/AppProviders";
import { CompaniesDataProvider } from "./CompaniesData";
import { CompaniesSection } from "./CompaniesSection";

vi.mock("../../api", () => ({
  api: {
    companyDiscovery: vi.fn(),
    companyOpenCounts: vi.fn(),
    searchCompanyDirectory: vi.fn(),
    companyDirectoryStatus: vi.fn(),
    followCompanyDirectory: vi.fn(),
    setCompanySelection: vi.fn(),
    addCompany: vi.fn(),
    updateCompany: vi.fn(),
    // The register reads run state: which companies are syncable, which failed
    // last run, whether one is in flight, and how each source's binding is
    // doing — the connector column reports health over declared state.
    syncTargets: vi.fn(),
    sync: vi.fn(),
    cancelSync: vi.fn(),
    status: vi.fn(),
    stats: vi.fn(),
    compareSelection: vi.fn().mockResolvedValue({ job_ids: [] }),
    setCompareSelection: vi.fn((jobIds: number[]) => Promise.resolve({ job_ids: jobIds })),
  },
}));


const company = (over: Partial<CompanyDiscoveryCompany>): CompanyDiscoveryCompany => ({
  slug: "acme",
  display: "Acme",
  careers_url: "https://example.com/careers",
  sectors: ["technology"],
  aliases: [],
  connector_state: "planned",
  parked_reason: null,
  selectable: true,
  tracked: false,
  enabled: false,
  visible: true,
  builtin: false,
  curated: false, directory: false,
  wall: null,
  consented: false,
  status: null,
  ...over,
});

/* A sector by slug; the register names it from the catalog. */
const sector = (slug: string) => ({
  slug,
  company_count: 1,
  ready_count: 0,
  selected_count: 0,
});

/* Meta sits in two sectors on purpose: real companies do, and a
   row is drawn in each. That is the arithmetic most likely to break — totals
   must come from the flat company array, never from summing sections. */
const state: CompanyDiscoveryState = {
  sectors: [
    sector("faang"),
    sector("ai"),
    sector("robotics"),
    sector("consulting"),
    sector("consumer"),
  ],
  companies: [
    company({
      slug: "google",
      display: "Google",
      sectors: ["faang"],
      connector_state: "live",
      parked_reason: null,
      tracked: true,
      enabled: true,
      builtin: true,
      curated: true, directory: false,
      status: "active",
    }),
    company({
      slug: "meta",
      display: "Meta",
      sectors: ["faang", "consumer"],
      connector_state: "live",
      parked_reason: null,
      tracked: true,
      enabled: true,
      builtin: true,
      curated: true, directory: false,
      status: "active",
    }),
    company({
      slug: "apple",
      display: "Apple",
      sectors: ["faang"],
      connector_state: "ready",
      parked_reason: null,
    }),
    company({
      slug: "openai",
      display: "OpenAI",
      sectors: ["ai"],
      connector_state: "ready",
      parked_reason: null,
    }),
    company({ slug: "snowflake", display: "Snowflake", sectors: ["ai"] }),
    company({
      slug: "tesla",
      display: "Tesla",
      sectors: ["robotics"],
      connector_state: "parked",
      parked_reason: "bot_protected",
      selectable: false,
    }),
    // Matches a search for "sec" only through its alias — the row has to say so.
    company({
      slug: "pwc",
      display: "PwC",
      sectors: ["consulting"],
      aliases: ["PricewaterhouseCoopers"],
    }),
  ],
};

const trackedCompany: TrackedCompany = {
  slug: "obscureco",
  display: "ObscureCo",
  adapter: null,
  board_token: null,
  careers_url: "https://jobs.lever.co/obscureco",
  status: "pending",
  enabled: true,
  visible: true,
  source: "url",
  builtin: false,
  job_count: 0,
  role_catalog_status: "pending",
  role_catalog_scanned_at: null,
  role_catalog_error: null,
  detected_family: null,
  pending_reason: null,
};

/** A Coverage notice's words as the server sends them. */
const said = (title: string, p: Record<string, string | number>, cause: string) => ({
  title: { k: title, p },
  body: [{ k: cause, p: {} }],
});

const target = (over: Partial<SyncTarget> & { slug: string }): SyncTarget => ({
  display: over.slug,
  adapter: "greenhouse",
  last_sync_at: "2026-07-13T04:00:00Z",
  age_hours: 2,
  stale: false,
  last_full_scan_at: "2026-07-13T04:00:00Z",
  automatic: true,
  last_outcome: "ok",
  retryable: false,
  coverage: null,
  ...over,
});

function renderSection(entry = "/settings/companies") {
  return render(
    <MemoryRouter initialEntries={[entry]}>
      <AppProviders>
        <ToastProvider>
        <CompaniesDataProvider>
          <CompaniesSection />
        </CompaniesDataProvider>
        </ToastProvider>
      </AppProviders>
    </MemoryRouter>,
  );
}

const openCounts = { counts: { google: 12, meta: 40 }, not_counted: {}, unplaced: {}, unsorted: {}, last_read: {} };

/** The directory's status: no set at all by default, so the register's own
 *  contracts run without the set of other companies. */
const noSet: CompanyDirectoryStatus = {
  size: 0, following: false, since: null, checked: 0, to_check: 0, with_roles: 0, waiting_for_power: false,
};
const setStatus = (over: Partial<CompanyDirectoryStatus> = {}): CompanyDirectoryStatus => ({
  ...noSet, size: 10214, to_check: 10214, ...over,
});

/** A request that never settles — stands in for the slow half of the screen. */
const pending = <T,>() => new Promise<T>(() => {});

/** A roster where exactly `slugs` are followed. */
const followed = (slugs: string[]): CompanyDiscoveryState => ({
  ...state,
  companies: state.companies.map((entry) => ({
    ...entry,
    enabled: slugs.includes(entry.slug),
    tracked: slugs.includes(entry.slug) || entry.tracked,
  })),
});

type SelectionChange = Parameters<typeof api.setCompanySelection>[0];
/** What the server holds; every selection write changes it. */
let server: CompanyDiscoveryState = state;
/** A starting roster where exactly `slugs` are followed, on the server too. */
const seed = (slugs: string[]): CompanyDiscoveryState => (server = followed(slugs));
const change = (follow: string[], unfollow: string[] = []): SelectionChange => ({ follow, unfollow });

/** The selection PUT applies one change and returns the whole roster; mirror
 *  that so the component's post-write state is the server's, not its guess. */
const applySelection = async (write: SelectionChange): Promise<CompanyDiscoveryState> => {
  const on = new Set(server.companies.filter((entry) => entry.enabled).map((entry) => entry.slug));
  for (const slug of write.follow) on.add(slug);
  for (const slug of write.unfollow) on.delete(slug);
  return seed([...on]);
};

// A two-sector company means duplicate accessible names in the register, so
// every row lookup is scoped to its section.
const sectorPanel = (name: string) => screen.getByRole("region", { name });
const row = (sectorName: string, companyName: string) =>
  within(sectorPanel(sectorName)).getByRole("checkbox", { name: companyName });
const index = () => screen.getByRole("navigation", { name: "Sectors" });

beforeEach(() => {
  vi.clearAllMocks();
  server = state;
  vi.mocked(api.companyDiscovery).mockResolvedValue(state);
  vi.mocked(api.companyOpenCounts).mockResolvedValue(openCounts);
  vi.mocked(api.searchCompanyDirectory).mockResolvedValue({ size: 0, match_count: 0, matches: [] });
  vi.mocked(api.companyDirectoryStatus).mockResolvedValue(noSet);
  vi.mocked(api.setCompanySelection).mockImplementation(applySelection);
  vi.mocked(api.addCompany).mockResolvedValue(trackedCompany);
  vi.mocked(api.updateCompany).mockResolvedValue(trackedCompany);
  vi.mocked(api.syncTargets).mockResolvedValue({ companies: [], freshness_max_hours: 26 });
  vi.mocked(api.status).mockResolvedValue(statusFixture);
  vi.mocked(api.stats).mockResolvedValue(statsFixture);
});

/* --- The ledger's own contracts -------------------------------------------
 *
 * Every company on screen at rest, sectors as places to scroll to, and an
 * index that navigates rather than collapses. */
describe("CompaniesSection — the ledger", () => {
  it("puts every company in the register at rest, with nothing behind a disclosure", async () => {
    renderSection();

    // No sector is collapsed and no connectorless company hides behind a
    // per-sector "Show N more".
    await waitFor(() => expect(row("FAANG", "Google")).toBeInTheDocument());
    expect(row("AI", "Snowflake")).toBeInTheDocument();
    expect(row("Robotics, autonomy & defense", "Tesla")).toBeInTheDocument();
    expect(row("Consulting", "PwC")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Show \d+ more/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Toggle .* companies/ })).not.toBeInTheDocument();
  });

  it("navigates by sector index instead of collapsing sections", async () => {
    renderSection();
    await waitFor(() => expect(row("FAANG", "Google")).toBeInTheDocument());

    const nav = index();
    // Every sector is listed with how much of it you track, attached to the
    // thing it navigates to.
    expect(within(nav).getByRole("button", { name: /FAANG/ })).toHaveTextContent("2/3");
    expect(within(nav).getByRole("button", { name: /AI/ })).toHaveTextContent("0/2");

    fireEvent.click(within(nav).getByRole("button", { name: /Robotics/ }));

    // Focus, not filter: the rest of the register is untouched.
    expect(within(nav).getByRole("button", { name: /Robotics/ })).toHaveAttribute(
      "aria-current",
      "true",
    );
    expect(sectorPanel("FAANG")).toBeInTheDocument();
    expect(row("AI", "Snowflake")).toBeInTheDocument();
  });

  it("hides the planned tail on request, and a search overrides that", async () => {
    renderSection();
    await waitFor(() => expect(row("AI", "Snowflake")).toBeInTheDocument());

    fireEvent.click(screen.getByRole("checkbox", { name: "Show planned" }));
    expect(screen.queryByRole("checkbox", { name: "Snowflake" })).not.toBeInTheDocument();
    // The sector says what it is withholding rather than silently shrinking.
    expect(sectorPanel("AI")).toHaveTextContent("1 planned hidden");
    // A sector left with nothing leaves the register but stays on the map, so
    // the catalog never appears smaller than it is.
    expect(screen.queryByRole("region", { name: "Consulting" })).not.toBeInTheDocument();
    expect(within(index()).getByRole("button", { name: /Consulting/ })).toBeDisabled();

    // A sector cannot advertise a match count and then not draw the row.
    fireEvent.change(screen.getByRole("searchbox", { name: "Search companies" }), {
      target: { value: "snow" },
    });
    expect(screen.getByRole("checkbox", { name: "Snowflake" })).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: "Show planned" })).toBeDisabled();
  });

  it("explains a search hit that landed on an alias", async () => {
    renderSection();
    await waitFor(() => expect(row("FAANG", "Google")).toBeInTheDocument());

    // "sec" is inside "pricewaterhou-sec-oopers" and nowhere in "PwC": without
    // the alias on the row, the hit reads as a false positive.
    fireEvent.change(screen.getByRole("searchbox", { name: "Search companies" }), {
      target: { value: "sec" },
    });

    const consulting = sectorPanel("Consulting");
    expect(within(consulting).getByRole("checkbox", { name: "PwC" })).toBeInTheDocument();
    expect(consulting).toHaveTextContent("aka PricewaterhouseCoopers");
    // The index counts matches, and says so rather than reusing "tracked/total".
    expect(within(index()).getByRole("button", { name: /Consulting/ })).toHaveTextContent(
      "1 match",
    );
  });

  it("reports what the scans did, not what the catalog claims", async () => {
    // Google's catalog entry says `live`. No scan has read its board in full
    // for 5 days and the bell rings for it. Printing "Live" here is the most
    // expensive lie the screen can tell. Meta, scanned 3 hours ago, is Live
    // with its clock on hover.
    const threeHoursAgo = new Date(Date.now() - 3 * 3_600_000).toISOString();
    vi.mocked(api.syncTargets).mockResolvedValue({
      freshness_max_hours: 26,
      companies: [
        target({
          slug: "google", display: "Google", last_full_scan_at: new Date(Date.now() - 5.2 * 86_400_000).toISOString(),
          coverage: {
            cause: "unreachable", held_open: 4, days_since_full_scan: 5.2, rings: true,
            title: "Couldn't scan Google · 5 days", body: "Its careers page isn't answering.",
            say: said("notif-coverage-scan-title", { company: "Google", days: 5 }, "notif-coverage-unreachable"),
          },
        }),
        target({ slug: "meta", display: "Meta", last_full_scan_at: threeHoursAgo }),
      ],
    });
    renderSection();

    const faang = await screen.findByRole("region", { name: "FAANG" });
    await waitFor(() => expect(row("FAANG", "Google")).toHaveAccessibleDescription(/^Couldn't scan · 5d/));
    expect(within(faang).getByTitle("Scanned 3h ago.")).toHaveTextContent(/^Live$/);
    expect(faang).not.toHaveTextContent(/Quarantined|scan cleanly|Scan problems/);
    // Why, on hover: the Coverage notice's own words.
    expect(within(faang).getByTitle("Couldn't scan Google · 5 days. Its careers page isn't answering.")).toBeInTheDocument();
  });

  it("says the Coverage notice's words in the reader's language", async () => {
    await activate("en-XA");
    try {
      vi.mocked(api.syncTargets).mockResolvedValue({
        freshness_max_hours: 26,
        companies: [
          target({
            slug: "google", display: "Google", last_full_scan_at: new Date(Date.now() - 5.2 * 86_400_000).toISOString(),
            coverage: {
              cause: "unreachable", held_open: 4, days_since_full_scan: 5.2, rings: true,
              title: "Couldn't scan Google · 5 days", body: "Its careers page isn't answering.",
              say: said("notif-coverage-scan-title", { company: "Google", days: 5 }, "notif-coverage-unreachable"),
            },
          }),
        ],
      });
      renderSection();
      const why = await waitFor(() => {
        const el = document.querySelector('[title^="⟦Çöûļðñ\'ţ šçàñ Google"]');
        expect(el).not.toBeNull();
        return el!;
      });
      expect(why.getAttribute("title")).not.toContain("Couldn't scan Google");
    } finally {
      await activate("en");
    }
  });

  it("shows a company awaiting its first scan without treating its age as a failure", async () => {
    vi.mocked(api.syncTargets).mockResolvedValue({
      freshness_max_hours: 26,
      companies: [target({
        slug: "google", display: "Google", last_sync_at: null, last_full_scan_at: null,
        coverage: {
          cause: "unknown", held_open: 0, days_since_full_scan: 81.4, rings: true,
          title: "Waiting to scan Google", body: "No scan has reached its careers page.",
          say: said("notif-coverage-waiting-title", { company: "Google" }, "notif-coverage-unknown"),
        },
      })],
    });
    renderSection();
    await waitFor(() => expect(row("FAANG", "Google")).toHaveAccessibleDescription(
      new RegExp(`^${msg("companies-company-register-rows-following-not-scanned-yet")}`),
    ));
    expect(sectorPanel("FAANG")).not.toHaveTextContent(/81d|Couldn't scan/);
  });

  it("reports a first scan failure without an age from before any full scan", async () => {
    vi.mocked(api.syncTargets).mockResolvedValue({
      freshness_max_hours: 26,
      companies: [target({
        slug: "google", display: "Google", last_sync_at: new Date().toISOString(), last_full_scan_at: null,
        coverage: {
          cause: "unreachable", held_open: 0, days_since_full_scan: 81.4, rings: true,
          title: "Couldn't scan Google", body: "Its careers page isn't answering.",
          say: said("notif-coverage-scan-title", { company: "Google", days: 0 }, "notif-coverage-unreachable"),
        },
      })],
    });
    renderSection();
    await waitFor(() => expect(row("FAANG", "Google")).toHaveAccessibleDescription(
      new RegExp(`^${msg("companies-company-register-rows-coverage-problem", { cause: "unreachable" })}`),
    ));
    expect(sectorPanel("FAANG")).not.toHaveTextContent("81d");
    expect(within(sectorPanel("FAANG")).getByTitle("Couldn't scan Google. Its careers page isn't answering."))
      .toHaveClass("is-warn");
  });

  it("gives a company scanned only on request its clock, never an alert", async () => {
    // Scanned only when the user presses Scan now, 5 days ago. Stale by
    // the clock, and still not broken: the bell never rings for it.
    const fiveDaysAgo = new Date(Date.now() - 5 * 86_400_000).toISOString();
    vi.mocked(api.syncTargets).mockResolvedValue({
      freshness_max_hours: 26,
      companies: [
        target({ slug: "google", display: "Google", automatic: false, stale: true, age_hours: 120, last_full_scan_at: fiveDaysAgo }),
      ],
    });
    renderSection();

    await waitFor(() => expect(row("FAANG", "Google")).toHaveAccessibleDescription(/^Live · scanned 5d ago/));
    const faang = screen.getByRole("region", { name: "FAANG" });
    expect(within(faang).getByTitle("Scanned 5d ago. Google is scanned when you choose Scan now."))
      .not.toHaveClass("is-warn");
  });

  it("names a followed company counted only from partial scans, apart from one not counted at all", async () => {
    vi.mocked(api.companyOpenCounts).mockResolvedValue({
      ...openCounts, not_counted: { meta: "partial", google: "missing" },
    });
    renderSection();

    await waitFor(() => expect(row("FAANG", "Meta")).toHaveAccessibleDescription(/^Live · partly counted/));
    const faang = screen.getByRole("region", { name: "FAANG" });
    expect(within(faang).getByTitle(
      "Meta's scans have not read its whole careers page yet, so some roles aren't counted. Its next full scan adds them.",
    )).toHaveTextContent("Live · partly counted");
    expect(row("FAANG", "Google")).toHaveAccessibleDescription(/^Live · not counted yet/);
  });

  it("says when a followed company whose reads stopped was last read (walk-counts B2)", async () => {
    // Read three days ago and not since: its roles left the count, and the row
    // says why and since when. A "stale" with no read time (the catalog's own
    // meaning) keeps its old words.
    const threeDaysAgo = new Date(Date.now() - 72 * 3_600_000).toISOString();
    vi.mocked(api.companyOpenCounts).mockResolvedValue({
      ...openCounts, not_counted: { meta: "stale", google: "stale" }, last_read: { meta: threeDaysAgo },
    });
    renderSection();

    await waitFor(() => expect(row("FAANG", "Meta")).toHaveAccessibleDescription(/^Live · not counted, last scanned 3d ago/));
    const faang = screen.getByRole("region", { name: "FAANG" });
    expect(within(faang).getByTitle(
      "Meta was last scanned 3d ago, too long ago for your radar's count. Its next scan adds its roles back.",
    )).toHaveTextContent("Live · not counted, last scanned 3d ago");
    expect(row("FAANG", "Google")).toHaveAccessibleDescription(/^Live · not counted yet/);
  });

  it("names a followed company the radar's count leaves out, and roles whose place it can't read", async () => {
    vi.mocked(api.companyOpenCounts).mockResolvedValue({
      ...openCounts, not_counted: { meta: "missing" }, unplaced: { google: 3 },
    });
    renderSection();

    await waitFor(() => expect(row("FAANG", "Meta")).toHaveAccessibleDescription(/^Live · not counted yet/));
    const faang = screen.getByRole("region", { name: "FAANG" });
    expect(within(faang).getByTitle("Meta's roles aren't in your radar's count yet. Its next scan adds them."))
      .toHaveTextContent("Live · not counted yet");
    // Counted, so its state is plain; its number carries the unplaced mark.
    expect(row("FAANG", "Google")).toHaveAccessibleDescription(/^Live(?! · not counted)/);
    expect(within(faang).getByTitle("3 of Google's roles name a place that isn't recognized, so they don't show for any place you choose."))
      .toHaveTextContent("12 open ·");
    expect(within(faang).getByText("40 open")).not.toHaveAttribute("title");
  });

  it("says a role with no role type is kept by no answer, never that its place is unreadable", async () => {
    /* Google's 432: every one has a place, none a role type, so the mark
       must not say "a place we can't read" about them. */
    vi.mocked(api.companyOpenCounts).mockResolvedValue({ ...openCounts, unsorted: { google: 432 } });
    renderSection();

    const faang = await screen.findByRole("region", { name: "FAANG" });
    const count = await within(faang).findByTitle("432 of Google's roles fit no known discipline, so they don't show for any discipline you choose.");
    expect(count).toHaveTextContent("12 open ·");
    expect(count.title).not.toMatch(/place/);
  });

  it("shows a broken company in the bell's own words, and breaks every row the bell rings for", async () => {
    vi.mocked(api.syncTargets).mockResolvedValue({
      freshness_max_hours: 26,
      companies: [
        target({
          slug: "google", display: "Google",
          coverage: {
            cause: "empty_listing", held_open: 12, days_since_full_scan: 0.4, rings: true,
            title: "Google lists no roles · 2 days", body: "Its careers page answered with an empty list.",
            say: said("notif-coverage-empty-title", { company: "Google", days: 2 }, "notif-coverage-empty-listing"),
          },
        }),
        // Attempted 3 hours ago, read in part: the bell rings, so the row must not say Live.
        target({
          slug: "meta", display: "Meta", age_hours: 3,
          coverage: {
            cause: "partial", held_open: 0, days_since_full_scan: 4.3, rings: true,
            title: "Couldn't scan Meta · 4 days", body: "Scans read only part of its careers page.",
            say: said("notif-coverage-scan-title", { company: "Meta", days: 4 }, "notif-coverage-partial"),
          },
        }),
        // Gone from its address: the company moved it, so never "Couldn't scan".
        target({
          slug: "apple", display: "Apple",
          coverage: {
            cause: "board_missing", held_open: 3, days_since_full_scan: 2.2, rings: true,
            title: "Apple's careers page is gone · 2 days",
            body: "Its careers page is no longer at its last address.",
            say: said("notif-coverage-gone-title", { company: "Apple", days: 2 }, "notif-coverage-board-missing"),
          },
        }),
      ],
    });
    renderSection();

    const faang = await screen.findByRole("region", { name: "FAANG" });
    expect(await within(faang).findByTitle(
      "Apple's careers page is gone · 2 days. Its careers page is no longer at its last address.",
    )).toHaveTextContent("Careers page gone · 2d");
    const why = await within(faang).findByTitle("Google lists no roles · 2 days. Its careers page answered with an empty list.");
    expect(why).toHaveTextContent("Lists no roles · 10h");
    expect(why).toHaveClass("is-warn");
    expect(within(faang).getByTitle("Couldn't scan Meta · 4 days. Scans read only part of its careers page."))
      .toHaveTextContent("Couldn't scan · 4d");
  });

  it("keeps a company the bell is quiet about Live, with no coverage words", async () => {
    vi.mocked(api.syncTargets).mockResolvedValue({
      freshness_max_hours: 26,
      companies: [
        target({
          slug: "google", display: "Google",
          coverage: {
            cause: "unreachable", held_open: 0, days_since_full_scan: 3.5, rings: true,
            title: "Couldn't scan Google · 3 days", body: "Its careers page isn't answering.",
            say: said("notif-coverage-scan-title", { company: "Google", days: 3 }, "notif-coverage-unreachable"),
          },
        }),
        // Served words but no ring: the row decides nothing itself.
        target({
          slug: "meta", display: "Meta",
          coverage: {
            cause: "partial", held_open: 0, days_since_full_scan: 3.1, rings: false,
            title: "Couldn't scan Meta · 3 days", body: "Scans read only part of its careers page.",
            say: said("notif-coverage-scan-title", { company: "Meta", days: 3 }, "notif-coverage-partial"),
          },
        }),
      ],
    });
    renderSection();

    await waitFor(() => expect(row("FAANG", "Google")).toHaveAccessibleDescription(/^Couldn't scan/));
    expect(row("FAANG", "Meta")).toHaveAccessibleDescription(/^Live/);
    expect(screen.queryByTitle(/Couldn't scan Meta/)).not.toBeInTheDocument();
  });

  it("counts live and ready connectors over the companies you track, not the catalog", async () => {
    renderSection();

    // Tracked: Google (live) + Meta (live). Apple and OpenAI are ready but
    // untracked, so they belong to neither figure — the toolbar's subject is
    // your radar, not the catalog.
    const search = await screen.findByRole("searchbox", { name: "Search companies" });
    const toolbar = search.closest(".ledger-toolbar") as HTMLElement;
    await waitFor(() => expect(toolbar).toHaveTextContent("2 of 7 followed"));
    expect(toolbar).toHaveTextContent("52 open roles");
    expect(toolbar).toHaveTextContent("2 live");
    expect(toolbar).toHaveTextContent("0 ready");
  });

  it("says nothing about open roles for a company it has never collected", async () => {
    renderSection();

    // Apple is connectable but untracked, so it has never been scraped. A "—"
    // would report our own inaction as a fact about the employer, and beside a
    // working connector it reads as a broken feed.
    await waitFor(() => expect(row("FAANG", "Google")).toBeInTheDocument());
    const faang = sectorPanel("FAANG");
    expect(within(faang).getByText("12 open")).toBeInTheDocument();
    expect(within(faang).queryByText("—")).not.toBeInTheDocument();
  });

  it("offers select-all as one labelled action per sector", async () => {
    renderSection();

    await waitFor(() => expect(row("FAANG", "Google")).toBeInTheDocument());
    // Adds one company (Apple): that is what its own row does, so no question.
    fireEvent.click(screen.getByRole("button", { name: "Follow all FAANG companies" }));

    await waitFor(() => expect(api.setCompanySelection).toHaveBeenCalledTimes(1));
    expect(api.setCompanySelection).toHaveBeenCalledWith(change(["apple", "google", "meta"]), []);
    // Once everything connectable is on, the same control reverses.
    expect(
      await screen.findByRole("button", { name: "Unfollow all FAANG companies" }),
    ).toBeInTheDocument();
  });

  it("states that a sector no connector reaches is a different fact from an unpicked one", async () => {
    renderSection();

    // The fact is carried by the sector's own stats. It is NOT carried by
    // disabling select-all: a sector no connector reaches still has rows the
    // roster accepts, and tracking one records intent (it stays paused until a
    // connector exists) exactly as clicking that row on its own does.
    await screen.findByRole("button", { name: "Follow all Consulting companies" });
    expect(sectorPanel("Consulting")).toHaveTextContent("none covered");
    expect(sectorPanel("FAANG")).toHaveTextContent("3 covered");
  });

  it("select-all takes every row the sector shows, and says which will stay paused", async () => {
    renderSection();

    // PwC is `planned`: visible and individually trackable, so select-all
    // must take it too, or the button would claim the sector fully tracked
    // while skipping it.
    const consulting = await screen.findByRole("button", { name: "Follow all Consulting companies" });
    expect(consulting).toBeEnabled();
    fireEvent.click(consulting);

    // The write names the sector's rows, so PwC is followed and nothing else moves.
    await waitFor(() => expect(api.setCompanySelection).toHaveBeenCalledTimes(1));
    expect(api.setCompanySelection).toHaveBeenCalledWith(change(["pwc"]), []);
    // ...and the notice does not call a paused entry "tracking" without saying so.
    expect(
      await screen.findByText(/1 isn't scanned yet/),
    ).toBeInTheDocument();
  });

  it("select-all follows the search: it never reaches a row the sector is not showing", async () => {
    renderSection();
    await waitFor(() => expect(row("FAANG", "Google")).toBeInTheDocument());

    // One FAANG row left on screen, and it is already tracked. So the sector,
    // as shown, is fully tracked and the control must read as the reverse.
    fireEvent.change(screen.getByRole("searchbox"), { target: { value: "google" } });
    const faang = sectorPanel("FAANG");
    expect(within(faang).getAllByRole("checkbox")).toHaveLength(1);
    const act = await screen.findByRole("button", { name: "Unfollow all FAANG companies" });

    // Never "Follow all" here: that would enroll Meta and Apple, two rows the
    // search has removed from the screen.
    fireEvent.click(act);
    await waitFor(() => expect(api.setCompanySelection).toHaveBeenCalledTimes(1));
    expect(api.setCompanySelection).toHaveBeenCalledWith(change([], ["google"]), []);
  });
});

/* --- Tracking ------------------------------------------------------------- */
describe("CompaniesSection — tracking", () => {
  it("tracks a company immediately, with no save step", async () => {
    renderSection();

    fireEvent.click(await screen.findByRole("checkbox", { name: "Apple" }));

    await waitFor(() =>
      expect(api.setCompanySelection).toHaveBeenCalledWith(change(["apple"]), []),
    );
    expect(screen.queryByRole("button", { name: /save/i })).not.toBeInTheDocument();
    await waitFor(() => expect(row("FAANG", "Apple")).toBeChecked());
    expect(screen.getByText("Following Apple.")).toBeInTheDocument();
  });

  it("undoes a track with the inverse write", async () => {
    renderSection();

    fireEvent.click(await screen.findByRole("checkbox", { name: "Apple" }));
    fireEvent.click(await screen.findByRole("button", { name: "Undo" }));

    await waitFor(() => expect(api.setCompanySelection).toHaveBeenCalledTimes(2));
    expect(vi.mocked(api.setCompanySelection).mock.calls[1][0]).toEqual(change([], ["apple"]));
    await waitFor(() => expect(row("FAANG", "Apple")).not.toBeChecked());
  });

  it("untracks by toggling a tracked row again", async () => {
    renderSection();

    fireEvent.click(await screen.findByRole("checkbox", { name: "Google" }));

    await waitFor(() => expect(api.setCompanySelection).toHaveBeenCalledWith(change([], ["google"]), []));
    expect(screen.getByText("Stopped following Google.")).toBeInTheDocument();
  });

  it("reverts the row and reports the error when the write fails", async () => {
    vi.mocked(api.setCompanySelection).mockRejectedValue(new ApiError("Failed to fetch", 0, "offline"));
    renderSection();

    fireEvent.click(await screen.findByRole("checkbox", { name: "Apple" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(msg("error-offline"));
    expect(screen.getByRole("alert")).not.toHaveTextContent("Failed to fetch");
    expect(row("FAANG", "Apple")).not.toBeChecked();
  });

  it("says a company followed without a connector is waiting, not scanned", async () => {
    renderSection();

    const snowflake = await screen.findByRole("checkbox", { name: "Snowflake" });
    // Unfollowed, a planned row only states its coverage.
    expect(snowflake).toHaveAccessibleDescription(/^Planned/);
    fireEvent.click(snowflake);

    expect(
      await screen.findByText(
        "Following Snowflake. Scanning starts as soon as its careers page can be read.",
      ),
    ).toBeInTheDocument();
    // The row must not read like an idle catalog entry beside a switch that is on.
    await waitFor(() =>
      expect(row("AI", "Snowflake")).toHaveAccessibleDescription(/^Following · not scanned yet/),
    );
    // A covered followed company keeps its coverage label: the new wording is
    // for the switch that bought nothing yet, not for every followed row.
    expect(row("FAANG", "Google")).not.toHaveAccessibleDescription(/not scanned yet/);
    const strip = await screen.findByRole("region", { name: "Companies needing attention" });
    await waitFor(() => expect(strip).toHaveTextContent("1 followed company is not scanned yet"));
    expect(strip).toHaveTextContent("Snowflake");
  });

  it("names the board a pending company's page pointed at, and why it waits", async () => {
    const pendingCompany = (slug: string, display: string, over: Partial<CompanyDiscoveryCompany>) =>
      company({ slug, display, sectors: ["faang"], tracked: true, enabled: true, status: "pending", ...over });
    vi.mocked(api.companyDiscovery).mockResolvedValue({
      ...state,
      companies: [
        ...state.companies,
        pendingCompany("silentco", "SilentCo", { detected_family: "jibe", pending_reason: "board_silent" }),
        pendingCompany("refusedco", "RefusedCo", { detected_family: "radancy", pending_reason: "policy_refused" }),
        pendingCompany("plainco", "PlainCo", {}),
      ],
    });
    renderSection();

    await screen.findByRole("checkbox", { name: "SilentCo" });
    expect(row("FAANG", "SilentCo")).toHaveAccessibleDescription(
      /^Uses \W?Jibe\W?, which didn't answer/,
    );
    expect(row("FAANG", "RefusedCo")).toHaveAccessibleDescription(
      /^Uses \W?Radancy TalentBrew\W?; collecting from it is off/,
    );
    // A page that named no known board keeps the plain waiting words.
    expect(row("FAANG", "PlainCo")).toHaveAccessibleDescription(/^Following · not scanned yet/);
    expect(row("FAANG", "PlainCo")).not.toHaveAccessibleDescription(/Found a/);
  });

  it("keeps a parked source visible but impossible to track", async () => {
    renderSection();

    const tesla = await screen.findByRole("checkbox", { name: "Tesla" });
    expect(tesla).toBeDisabled();
    expect(sectorPanel("Robotics, autonomy & defense")).toHaveTextContent("Blocked");
  });

  it("counts a two-sector company once in the total and shows it in both", async () => {
    renderSection();

    // Membership sums to 7 across the 5 sectors, but there are only 6 companies.
    await waitFor(() => expect(row("FAANG", "Meta")).toBeChecked());
    expect(row("Consumer platforms", "Meta")).toBeChecked();

    // Either row writes the same single-slug delta.
    fireEvent.click(row("Consumer platforms", "Meta"));
    await waitFor(() => expect(api.setCompanySelection).toHaveBeenCalledWith(change([], ["meta"]), []));
  });

  it("sorts tracked first, then by open roles, within a sector", async () => {
    renderSection();

    await waitFor(() => expect(within(sectorPanel("FAANG")).getByText("40 open")).toBeInTheDocument());
    const names = within(sectorPanel("FAANG"))
      .getAllByRole("checkbox")
      .map((box) => box.getAttribute("aria-label"));
    expect(names).toEqual(["Meta", "Google", "Apple"]);
  });

  it("hides everything you do not track behind the Tracked only filter", async () => {
    renderSection();

    fireEvent.click(await screen.findByRole("checkbox", { name: "Following only" }));

    expect(screen.getByRole("checkbox", { name: "Google" })).toBeInTheDocument();
    expect(screen.queryByRole("checkbox", { name: "Apple" })).not.toBeInTheDocument();
  });

  /* The register's empty state.
   *
   * These fail against a sentence chosen by `query ? … : trackedOnly ? …`
   * while the list ANDs the filters together. */
  describe("says WHY it is empty, and offers the filter back", () => {
    it("does not deny a catalog company because Tracked only is on", async () => {
      renderSection();

      fireEvent.click(await screen.findByRole("checkbox", { name: "Following only" }));
      fireEvent.change(screen.getByLabelText("Search companies"), {
        target: { value: "apple" },
      });

      // Not "no companies match": Apple is IN the catalog, and the reasonable
      // next move from that sentence is Add by link, which duplicates it.
      expect(screen.queryByText(/^No companies match/)).not.toBeInTheDocument();
      expect(screen.getByText("No company you follow matches “apple”.")).toBeInTheDocument();
      expect(screen.getByText(/1 match you don't follow/)).toBeInTheDocument();
    });

    it("hands back the filter that emptied the list, not a suggestion to widen", async () => {
      renderSection();

      fireEvent.click(await screen.findByRole("checkbox", { name: "Following only" }));
      fireEvent.change(screen.getByLabelText("Search companies"), {
        target: { value: "apple" },
      });

      fireEvent.click(screen.getByRole("button", { name: "Show all companies" }));

      // The recovery has to actually recover: the row it promised is there,
      // and the search the user typed survives.
      expect(screen.getByRole("checkbox", { name: "Apple" })).toBeInTheDocument();
      expect(screen.getByLabelText("Search companies")).toHaveValue("apple");
    });

    it("blames only the search when the search is the only thing narrowing", async () => {
      renderSection();

      await screen.findByRole("checkbox", { name: "Google" });
      fireEvent.change(screen.getByLabelText("Search companies"), {
        target: { value: "zzzz" },
      });

      expect(screen.getByText("No company matches “zzzz”.")).toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "Show all companies" })).not.toBeInTheDocument();
      fireEvent.click(screen.getByRole("button", { name: "Clear the search" }));
      expect(screen.getByRole("checkbox", { name: "Google" })).toBeInTheDocument();
    });

    it("never blames Show planned, which a search has already overridden", async () => {
      renderSection();

      // Planned rows are forced visible while searching, so releasing that
      // switch would reveal nothing and it must not be named.
      fireEvent.click(await screen.findByRole("checkbox", { name: "Show planned" }));
      fireEvent.change(screen.getByLabelText("Search companies"), {
        target: { value: "zzzz" },
      });

      expect(screen.queryByRole("button", { name: "Show planned" })).not.toBeInTheDocument();
    });
  });

  it("keeps opportunity visibility independent from tracking, and offers it only when tracked", async () => {
    renderSection();

    fireEvent.click(await screen.findByRole("button", { name: "Hide Google on your radar" }));
    await waitFor(() =>
      expect(api.updateCompany).toHaveBeenCalledWith("google", { visible: false }),
    );
    expect(api.setCompanySelection).not.toHaveBeenCalled();

    // An untracked company has no visibility to control.
    expect(
      screen.queryByRole("button", { name: /Apple in opportunities/ }),
    ).not.toBeInTheDocument();
  });

  it("names where a hidden company went, and takes it back", async () => {
    /* The eye's whole effect is on ANOTHER screen: nothing here changes but one
       icon, while the Board loses every role of that company. So it says so,
       with Undo, like its row-neighbour. */
    renderSection();

    fireEvent.click(await screen.findByRole("button", { name: "Hide Google on your radar" }));
    expect(
      await screen.findByText("Google hidden from your radar."),
    ).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Undo" }));
    await waitFor(() =>
      expect(api.updateCompany).toHaveBeenLastCalledWith("google", { visible: true }),
    );
    // The row reads the write back, so the eye offers to hide it again.
    expect(
      await screen.findByRole("button", { name: "Hide Google on your radar" }),
    ).toBeInTheDocument();
  });

  it("says nothing landed when the visibility write fails", async () => {
    vi.mocked(api.updateCompany).mockRejectedValueOnce(
      new ApiError("Failed to fetch", 0, "offline"),
    );
    renderSection();

    fireEvent.click(await screen.findByRole("button", { name: "Hide Google on your radar" }));

    // The row is named, then why, from the failure's code: a bare detail says
    // nothing about WHICH row just failed.
    expect(await screen.findByText(/Couldn't hide Google from your radar\./)).toBeInTheDocument();
    expect(screen.getByText(new RegExp(msg("error-offline").replace(/[.*+?^${}()|[\]\\]/g, "\\$&")))).toBeInTheDocument();
    expect(screen.queryByText(/Failed to fetch/)).not.toBeInTheDocument();
    // Still shown: a failed write must not leave the row claiming it is hidden.
    expect(
      screen.getByRole("button", { name: "Hide Google on your radar" }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Undo" })).not.toBeInTheDocument();
  });

  it("preserves the manual careers-URL path for a company outside the catalog", async () => {
    renderSection();

    const addMore = await screen.findByRole("region", { name: "Add more companies" });
    fireEvent.click(within(addMore).getByRole("button", { name: "Add by link" }));
    fireEvent.change(screen.getByLabelText("Company name"), {
      target: { value: "ObscureCo" },
    });
    fireEvent.change(screen.getByLabelText("Careers page link"), {
      target: { value: "https://jobs.lever.co/obscureco" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Add company" }));

    await waitFor(() =>
      expect(api.addCompany).toHaveBeenCalledWith({
        name: "ObscureCo",
        careers_url: "https://jobs.lever.co/obscureco",
      }),
    );
    expect(api.companyDiscovery).toHaveBeenCalledTimes(2);
  });

  it("keeps the register on screen while the roster re-reads after an add", async () => {
    renderSection();
    await waitFor(() => expect(row("FAANG", "Google")).toBeChecked());
    const google = row("FAANG", "Google");
    // The re-read the add starts never answers, so the test sees the screen
    // exactly as it stands while that read is in flight.
    vi.mocked(api.companyDiscovery).mockImplementation(pending);

    fireEvent.click(within(screen.getByRole("region", { name: "Add more companies" }))
      .getByRole("button", { name: "Add by link" }));
    fireEvent.change(screen.getByLabelText("Careers page link"), {
      target: { value: "https://jobs.lever.co/obscureco" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Add company" }));

    await waitFor(() => expect(api.companyDiscovery).toHaveBeenCalledTimes(2));
    expect(screen.queryByText("Loading companies…")).not.toBeInTheDocument();
    // The same node: the row was never unmounted behind the skeleton.
    expect(row("FAANG", "Google")).toBe(google);
  });

  /* A dialog owns its failure feedback: an app-wide toast would paint UNDER
     its scrim, unreadable. The reason shows inside it, what was typed stays,
     and trying again works without reopening anything. */
  it("says why an add failed inside the dialog, keeps the typed values, and can retry", async () => {
    vi.mocked(api.addCompany).mockRejectedValueOnce(new ApiError("the board did not answer", 409, "careers-page-unreachable"));
    renderSection();

    const addMore = await screen.findByRole("region", { name: "Add more companies" });
    fireEvent.click(within(addMore).getByRole("button", { name: "Add by link" }));
    const dialog = screen.getByRole("dialog", { name: "Add a company by link" });
    fireEvent.change(within(dialog).getByLabelText("Company name"), { target: { value: "ObscureCo" } });
    fireEvent.change(within(dialog).getByLabelText("Careers page link"), {
      target: { value: "https://jobs.lever.co/obscureco" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Add company" }));

    const alert = await within(dialog).findByRole("alert");
    expect(alert).toHaveTextContent(`Couldn't add that company. ${msg("error-careers-page-unreachable")}`);
    expect(alert).not.toHaveTextContent("did not answer");
    expect(within(dialog).getByLabelText("Company name")).toHaveValue("ObscureCo");
    expect(within(dialog).getByLabelText("Careers page link")).toHaveValue("https://jobs.lever.co/obscureco");
    // Said once, where the user is looking: not also as a toast behind the dialog.
    expect(screen.getAllByText(/Couldn't add that company/)).toHaveLength(1);

    fireEvent.click(within(dialog).getByRole("button", { name: "Add company" }));
    await waitFor(() =>
      expect(screen.queryByRole("dialog", { name: "Add a company by link" })).not.toBeInTheDocument(),
    );
    expect(api.addCompany).toHaveBeenCalledTimes(2);
  });
});

describe("CompaniesSection — loading", () => {
  it("renders the register while open-role counts are still loading", async () => {
    vi.mocked(api.companyOpenCounts).mockImplementation(pending);
    renderSection();

    expect(await screen.findByRole("checkbox", { name: "Google" })).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: "Apple" })).toBeEnabled();
    expect(screen.queryByText("Loading companies…")).not.toBeInTheDocument();
    // Only tracked rows carry a count, so only they say they are busy: Google,
    // and Meta twice — it is in two sectors.
    expect(screen.getAllByRole("status", { name: "Open roles loading" })).toHaveLength(3);
  });

  it("keeps the register usable when only the counts request fails", async () => {
    vi.mocked(api.companyOpenCounts).mockRejectedValue(new Error("counts unavailable"));
    renderSection();

    await waitFor(() => expect(within(sectorPanel("FAANG")).getAllByText("—")).toHaveLength(2));
    expect(screen.getByRole("checkbox", { name: "Apple" })).toBeEnabled();
  });

  it("still gates the screen on the roster itself, the only hard dependency", async () => {
    vi.mocked(api.companyDiscovery).mockImplementation(pending);
    renderSection();

    expect(await screen.findByText("Loading companies…")).toBeInTheDocument();
    expect(screen.queryByRole("checkbox", { name: "Google" })).not.toBeInTheDocument();
  });
});

describe("CompaniesSection — sync", () => {
  const syncable = {
    freshness_max_hours: 26,
    companies: [target({ slug: "google", display: "Google", adapter: "google" })],
  };

  it("syncs one company from its row", async () => {
    vi.mocked(api.syncTargets).mockResolvedValue(syncable);
    vi.mocked(api.sync).mockResolvedValue({ status: "started", companies: ["google"], queued: ["google"] });
    renderSection();

    await waitFor(() => expect(row("FAANG", "Google")).toBeChecked());
    fireEvent.click(within(sectorPanel("FAANG")).getByRole("button", { name: "Scan Google now" }));

    await waitFor(() => expect(vi.mocked(api.sync)).toHaveBeenCalledWith(["google"]));
  });

  it("keeps each row's scan action while the targets re-read after a scan", async () => {
    vi.mocked(api.syncTargets).mockResolvedValue(syncable);
    vi.mocked(api.sync).mockResolvedValue({ status: "started", companies: ["google"], queued: ["google"] });
    renderSection();

    await waitFor(() => expect(row("FAANG", "Google")).toBeChecked());
    const scan = within(sectorPanel("FAANG")).getByRole("button", { name: "Scan Google now" });
    // The re-read a landed scan starts never answers.
    vi.mocked(api.syncTargets).mockImplementation(pending);
    fireEvent.click(scan);

    await waitFor(() => expect(vi.mocked(api.syncTargets)).toHaveBeenCalledTimes(2));
    // The targets the row was drawn from stay until the next answer replaces
    // them, so the action does not vanish for the length of a read.
    expect(within(sectorPanel("FAANG")).getByRole("button", { name: "Scan Google now" })).toBe(scan);
  });

  it("offers no sync action for a company the pipeline would not accept", async () => {
    vi.mocked(api.syncTargets).mockResolvedValue(syncable);
    renderSection();

    await waitFor(() => expect(row("FAANG", "Google")).toBeChecked());
    expect(screen.queryByRole("button", { name: "Scan Meta now" })).toBeNull();
  });

  const liveRun = {
    ...statusFixture,
    db: "ok" as const, last_success_at: null, last_success_age_hours: null, last_run_status: "running",
    last_run_started_at: "2026-07-13T04:00:00Z", last_run_finished_at: null, last_run_new: 0,
    last_run_seen: 0, running: true, manual_sync_running: false, manual_queued: [], stuck_running: 0,
    stale: false, freshness_max_hours: 26,
  };

  it("adds a company to the run that is live, and says it is read next", async () => {
    vi.mocked(api.syncTargets).mockResolvedValue(syncable);
    vi.mocked(api.status).mockResolvedValue(liveRun);
    vi.mocked(api.sync).mockResolvedValue({
      status: "already_running", run_id: 9, started_at: "2026-07-13T04:00:00Z", companies: [], queued: ["google"],
    });
    renderSection();

    await waitFor(() => expect(row("FAANG", "Google")).toBeChecked());
    const button = within(sectorPanel("FAANG")).getByRole("button", { name: "Scan Google now" });
    await waitFor(() => expect(button).toHaveAttribute("title", msg("companies-company-register-rows-scan-now-hint", { scan: "running" })));
    expect(button).toBeEnabled();
    fireEvent.click(button);

    await waitFor(() => expect(vi.mocked(api.sync)).toHaveBeenCalledWith(["google"]));
    expect(await screen.findByText(msg("companies-company-register-rows-scan-joined", { display: "Google" }))).toBeInTheDocument();
    expect(screen.queryByText(msg("companies-company-register-rows-scanning", { display: "Google" }))).toBeNull();
  });

  it("disables the row action while a requested scan waits for its turn", async () => {
    vi.mocked(api.syncTargets).mockResolvedValue(syncable);
    vi.mocked(api.status).mockResolvedValue({ ...liveRun, running: false, last_run_status: "ok", manual_queued: ["meta"] });
    renderSection();

    await waitFor(() => expect(row("FAANG", "Google")).toBeChecked());
    const button = within(sectorPanel("FAANG")).getByRole("button", { name: "Scan Google now" });
    await waitFor(() => expect(button).toBeDisabled());
    expect(button).toHaveAttribute("title", msg("companies-company-register-rows-scan-now-hint", { scan: "waiting" }));
    fireEvent.click(button);
    expect(vi.mocked(api.sync)).not.toHaveBeenCalled();
  });

  it("surfaces failed sources above the register, with the re-run beside them", async () => {
    // An actionable warning sits above the register, where it is read first.
    vi.mocked(api.syncTargets).mockResolvedValue({
      freshness_max_hours: 26,
      companies: [
        target({ slug: "google", display: "Google", retryable: true, last_outcome: "failed" }),
      ],
    });
    vi.mocked(api.sync).mockResolvedValue({ status: "started", companies: ["google"], queued: ["google"] });
    renderSection();

    const strip = await screen.findByRole("region", { name: "Companies needing attention" });
    expect(strip).toHaveTextContent("1 company failed the last scan");
    fireEvent.click(within(strip).getByRole("button", { name: /Rescan 1/ }));

    await waitFor(() => expect(vi.mocked(api.sync)).toHaveBeenCalledWith(["google"]));
  });
});

/* --- The curated list ------------------------------------------------------ */
describe("CompaniesSection — curated list", () => {
  // Google and Meta are curated. Apple and OpenAI can be scanned and are not:
  // they are the "other companies". Snowflake and PwC are planned and Tesla is
  // parked, so the toolbar's Follow all never counts or follows them.
  const toolbarAct = (name: string) => screen.findByRole("button", { name });

  it("has no switch any more: the list action sits in the toolbar", async () => {
    renderSection();
    expect(await toolbarAct("Follow all")).toBeInTheDocument();
    expect(screen.queryByRole("checkbox", { name: /Include other companies/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Curated list" })).not.toBeInTheDocument();
  });

  it("asks before following them, with the safe answer focused, and Keep changes nothing", async () => {
    renderSection();
    fireEvent.click(await toolbarAct("Follow all"));

    const ask = await screen.findByRole("dialog", { name: "Follow the whole list?" });
    const keep = within(ask).getByRole("button", { name: "Keep curated list" });
    await waitFor(() => expect(keep).toHaveFocus());
    expect(within(ask).getByRole("button", { name: "Follow all 2" })).toBeInTheDocument();

    fireEvent.click(keep);
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(api.setCompanySelection).not.toHaveBeenCalled();
  });

  it("follows every listed company on yes, never the planned or parked ones, then offers the way back", async () => {
    renderSection();
    fireEvent.click(await toolbarAct("Follow all"));
    const ask = await screen.findByRole("dialog", { name: "Follow the whole list?" });
    fireEvent.click(within(ask).getByRole("button", { name: "Follow all 2" }));

    await waitFor(() => expect(api.setCompanySelection).toHaveBeenCalledTimes(1));
    const sent = vi.mocked(api.setCompanySelection).mock.calls[0][0] as SelectionChange;
    expect(sent).toEqual(change(["apple", "openai"]));
    expect(await toolbarAct("Curated list only")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Follow all" })).not.toBeInTheDocument();
  });

  it("follows a curated company the user had unfollowed too: all means all", async () => {
    vi.mocked(api.companyDiscovery).mockResolvedValue(seed(["google"]));
    renderSection();
    fireEvent.click(await toolbarAct("Follow all"));
    const ask = await screen.findByRole("dialog", { name: "Follow the whole list?" });
    fireEvent.click(within(ask).getByRole("button", { name: "Follow all 3" }));
    await waitFor(() => expect(api.setCompanySelection).toHaveBeenCalledTimes(1));
    const sent = vi.mocked(api.setCompanySelection).mock.calls[0][0] as SelectionChange;
    expect(sent).toEqual(change(["apple", "meta", "openai"]));
  });

  it("Curated list only unfollows only the other companies, after asking", async () => {
    vi.mocked(api.companyDiscovery).mockResolvedValue(
      seed(["google", "meta", "apple", "openai"]),
    );
    renderSection();
    fireEvent.click(await toolbarAct("Curated list only"));

    const ask = await screen.findByRole("dialog", {
      name: "Unfollow 2 companies outside your curated list?",
    });
    expect(within(ask).getByRole("button", { name: "Keep following" })).toBeInTheDocument();
    fireEvent.click(within(ask).getByRole("button", { name: "Unfollow 2" }));

    await waitFor(() => expect(api.setCompanySelection).toHaveBeenCalledTimes(1));
    const sent = vi.mocked(api.setCompanySelection).mock.calls[0][0] as SelectionChange;
    expect(sent).toEqual(change([], ["apple", "openai"]));
  });

  it("while some are followed, Follow all asks only about the rest", async () => {
    vi.mocked(api.companyDiscovery).mockResolvedValue(seed(["google", "meta", "apple"]));
    renderSection();
    fireEvent.click(await toolbarAct("Follow all"));
    const ask = await screen.findByRole("dialog", { name: "Follow the whole list?" });
    expect(within(ask).getByRole("button", { name: "Follow all 1" })).toBeInTheDocument();
  });

  it("says the cost in words, names no figure, and reads no scan times", async () => {
    vi.mocked(api.companyOpenCounts).mockResolvedValue({ ...openCounts, counts: { ...openCounts.counts, apple: 900, openai: 300 } });
    const first = renderSection();
    await toolbarAct("Follow all");
    // The counts arrive on their own; wait for them before asking.
    await waitFor(() => expect(api.companyOpenCounts).toHaveBeenCalled());
    await new Promise((resolve) => setTimeout(resolve, 0));
    fireEvent.click(await toolbarAct("Follow all"));
    const ask = await screen.findByRole("dialog", { name: "Follow the whole list?" });
    // Thousands of roles are counted, and the dialog still names no figure.
    expect(ask).toHaveTextContent("More companies bring more roles, and each scan takes longer.");
    expect(ask).not.toHaveTextContent(/about \d|thousands|minutes/);
    fireEvent.click(within(ask).getByRole("button", { name: "Keep curated list" }));
    first.unmount();
  });

  it("a sector's Follow all asks when it adds several companies, and Cancel changes nothing", async () => {
    renderSection();
    const act = await screen.findByRole("button", { name: "Follow all AI companies" });
    fireEvent.click(act);

    const ask = await screen.findByRole("dialog", { name: "Follow all 2 companies in AI?" });
    const cancel = within(ask).getByRole("button", { name: "Cancel" });
    await waitFor(() => expect(cancel).toHaveFocus());
    fireEvent.click(cancel);
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(api.setCompanySelection).not.toHaveBeenCalled();

    fireEvent.click(act);
    const yes = await screen.findByRole("dialog", { name: "Follow all 2 companies in AI?" });
    fireEvent.click(within(yes).getByRole("button", { name: "Follow all 2" }));
    await waitFor(() => expect(api.setCompanySelection).toHaveBeenCalledTimes(1));
    const sent = vi.mocked(api.setCompanySelection).mock.calls[0][0] as SelectionChange;
    expect(sent).toEqual(change(["openai", "snowflake"]));
  });
});

/* --- Walled companies ----------------------------------------- */
describe("CompaniesSection — walled companies follow only through their dialog", () => {
  // DeepMind rides a walled source: its robots.txt disallows the route we request.
  const deepmind = company({
    slug: "deepmind", display: "DeepMind", sectors: ["ai"], connector_state: "family",
    parked_reason: null, wall: "robots",
  });
  const withDeepmind = (over: Partial<CompanyDiscoveryCompany> = {}): CompanyDiscoveryState => ({
    ...state,
    companies: [...state.companies, { ...deepmind, ...over }],
  });
  const dialogText = (dialog: HTMLElement) =>
    [within(dialog).getByRole("heading").textContent, ...within(dialog).getAllByText(/./, { selector: "p" })
      .map((p) => p.textContent)].join("\n\n");

  it("the switch asks first, states the wall, and Cancel writes nothing", async () => {
    vi.mocked(api.companyDiscovery).mockResolvedValue(withDeepmind());
    renderSection();
    fireEvent.click(await within(await screen.findByRole("region", { name: "AI" })).findByRole("checkbox", { name: "DeepMind" }));

    const ask = await screen.findByRole("dialog", { name: "Follow DeepMind?" });
    // One universal sentence for every wall, naming no company; the
    // company's name is on the dialog's own title.
    expect(ask).toHaveTextContent("Its careers site limits automated collection.");
    const cancel = within(ask).getByRole("button", { name: "Cancel" });
    await waitFor(() => expect(cancel).toHaveFocus());
    fireEvent.click(cancel);
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(api.setCompanySelection).not.toHaveBeenCalled();
  });

  it("following through the dialog sends the consent as the words the user saw", async () => {
    vi.mocked(api.companyDiscovery).mockResolvedValue(withDeepmind());
    renderSection();
    fireEvent.click(await within(await screen.findByRole("region", { name: "AI" })).findByRole("checkbox", { name: "DeepMind" }));
    const ask = await screen.findByRole("dialog", { name: "Follow DeepMind?" });
    const shown = dialogText(ask);
    fireEvent.click(within(ask).getByRole("button", { name: "Follow DeepMind" }));

    await waitFor(() => expect(api.setCompanySelection).toHaveBeenCalledTimes(1));
    const [sent, consents] = vi.mocked(api.setCompanySelection).mock.calls[0];
    expect(sent).toEqual(change(["deepmind"]));
    expect(consents).toEqual([{ slug: "deepmind", text: shown, locale: "en" }]);
  });

  it("a company the user already consented to follows again from its switch without asking", async () => {
    vi.mocked(api.companyDiscovery).mockResolvedValue(withDeepmind({ tracked: true, enabled: false, consented: true }));
    renderSection();
    fireEvent.click(await within(await screen.findByRole("region", { name: "AI" })).findByRole("checkbox", { name: "DeepMind" }));

    await waitFor(() => expect(api.setCompanySelection).toHaveBeenCalledTimes(1));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    const [sent, consents] = vi.mocked(api.setCompanySelection).mock.calls[0];
    expect(sent).toEqual(change(["deepmind"]));
    expect(consents ?? []).toEqual([]);
  });

  it("a walled company followed before consent existed says so, and Review asks the same question", async () => {
    vi.mocked(api.companyDiscovery).mockResolvedValue(withDeepmind({ tracked: true, enabled: true }));
    renderSection();
    const strip = await screen.findByRole("region", { name: "Companies needing attention" });
    expect(strip).toHaveTextContent("1 followed company waits for your consent");
    expect(within(screen.getByRole("region", { name: "AI" })).getByText("Needs consent")).toBeInTheDocument();

    fireEvent.click(within(strip).getByRole("button", { name: "Review DeepMind" }));
    const ask = await screen.findByRole("dialog", { name: "Follow DeepMind?" });
    fireEvent.click(within(ask).getByRole("button", { name: "Follow DeepMind" }));
    await waitFor(() => expect(api.setCompanySelection).toHaveBeenCalledTimes(1));
    const [sent, consents] = vi.mocked(api.setCompanySelection).mock.calls[0];
    expect(sent).toEqual(change(["deepmind"]));
    expect(consents?.map((entry) => entry.slug)).toEqual(["deepmind"]);
  });

  it("Follow all names the walled ones and records consent only for them", async () => {
    vi.mocked(api.companyDiscovery).mockResolvedValue(withDeepmind());
    renderSection();
    fireEvent.click(await screen.findByRole("button", { name: "Follow all" }));
    const ask = await screen.findByRole("dialog", { name: "Follow the whole list?" });
    expect(ask).toHaveTextContent(
      "Some of these companies limit automated collection on their careers sites. By following them, you choose to collect their public postings.",
    );
    // A settings path, a hyphenated word and a short sentence opener each keep to one line.
    for (const run of ["Settings › Followed companies", "well-known", "By following"]) {
      expect(within(ask).getByText(run, { exact: true })).toHaveClass("ledger-confirm-unbroken");
    }
    fireEvent.click(within(ask).getByRole("button", { name: "Follow all 3" }));
    await waitFor(() => expect(api.setCompanySelection).toHaveBeenCalledTimes(1));
    const [, consents] = vi.mocked(api.setCompanySelection).mock.calls[0];
    expect(consents?.map((entry) => entry.slug)).toEqual(["deepmind"]);
  });

  it("unfollowing a walled company shows its message and records no consent", async () => {
    vi.mocked(api.companyDiscovery).mockResolvedValue(withDeepmind({ tracked: true, enabled: true, consented: true }));
    renderSection();
    fireEvent.click(await within(await screen.findByRole("region", { name: "AI" })).findByRole("checkbox", { name: "DeepMind" }));
    const ask = await screen.findByRole("dialog", { name: "Unfollow DeepMind?" });
    fireEvent.click(within(ask).getByRole("button", { name: "Unfollow DeepMind" }));
    await waitFor(() => expect(api.setCompanySelection).toHaveBeenCalledTimes(1));
    const [sent, consents] = vi.mocked(api.setCompanySelection).mock.calls[0];
    expect(sent).toEqual(change([], ["deepmind"]));
    expect(consents).toEqual([]);
  });
});

/* --- Every other company RoleBand can scan ----------------------
 *
 * Far too many for the register to hold, so a search
 * asks the server for the few that match, draws them under "Other companies",
 * and following one is the same roster write as any other row. */
describe("CompaniesSection — every other company, found by name", () => {
  const search = (value: string) =>
    fireEvent.change(screen.getByRole("searchbox", { name: "Search companies" }), {
      target: { value },
    });
  const spacex = { slug: "spacex", display: "SpaceX", named_by: "board" as const, tracked: false, enabled: false };

  it("a search reaches companies outside every sector, in their own group", async () => {
    vi.mocked(api.searchCompanyDirectory).mockResolvedValue({ size: 10214, match_count: 1, matches: [spacex] });
    renderSection();
    await waitFor(() => expect(row("FAANG", "Google")).toBeInTheDocument());

    search("space");
    const hit = await waitFor(() => row("Other companies", "SpaceX"));
    expect(hit).not.toBeChecked();
    expect(vi.mocked(api.searchCompanyDirectory)).toHaveBeenLastCalledWith("space", expect.anything());
    // Every match is on screen, so there is nothing to say about the rest.
    expect(sectorPanel("Other companies")).not.toHaveTextContent("Showing");
  });

  it("drops the last word's rows as soon as a new word is typed, before its answer", async () => {
    vi.mocked(api.searchCompanyDirectory)
      .mockResolvedValueOnce({ size: 10214, match_count: 1, matches: [spacex] })
      .mockImplementation(pending);
    renderSection();
    await waitFor(() => expect(row("FAANG", "Google")).toBeInTheDocument());
    search("space");
    await waitFor(() => row("Other companies", "SpaceX"));
    search("zzzz");
    expect(screen.queryByRole("checkbox", { name: "SpaceX" })).not.toBeInTheDocument();
  });

  it("asks nothing for a single letter, which would match most of the set", async () => {
    renderSection();
    await waitFor(() => expect(row("FAANG", "Google")).toBeInTheDocument());
    search("s");
    await new Promise((resolve) => setTimeout(resolve, 300));
    expect(vi.mocked(api.searchCompanyDirectory)).not.toHaveBeenCalled();
  });

  it("following a hit is one roster write that includes it", async () => {
    vi.mocked(api.searchCompanyDirectory).mockResolvedValue({ size: 10214, match_count: 1, matches: [spacex] });
    vi.mocked(api.setCompanySelection).mockImplementation(async (write: SelectionChange) => {
      const roster = await applySelection(write);
      return {
        ...roster,
        companies: [
          ...roster.companies,
          company({ slug: "spacex", display: "SpaceX", sectors: [], connector_state: "active",
                    parked_reason: null, tracked: true, enabled: true,
                    directory: true, careers_url: null, status: "active" }),
        ],
      };
    });
    renderSection();
    await waitFor(() => expect(row("FAANG", "Google")).toBeInTheDocument());
    search("space");
    fireEvent.click(await waitFor(() => row("Other companies", "SpaceX")));

    await waitFor(() => expect(vi.mocked(api.setCompanySelection)).toHaveBeenCalled());
    const [sent] = vi.mocked(api.setCompanySelection).mock.calls[0];
    expect(sent).toEqual(change(["spacex"])); // and nothing else: the roster is not restated
    await waitFor(() => expect(row("Other companies", "SpaceX")).toBeChecked());
  });

  it("says when the list is the best matches rather than all of them", async () => {
    vi.mocked(api.searchCompanyDirectory).mockResolvedValue({ size: 10214, match_count: 57, matches: [spacex] });
    renderSection();
    await waitFor(() => expect(row("FAANG", "Google")).toBeInTheDocument());
    search("sp");
    await waitFor(() =>
      expect(sectorPanel("Other companies")).toHaveTextContent(
        "Showing 1 of 57 matches. Keep typing to narrow the list.",
      ),
    );
  });

  it("draws nothing from an answer to a word the reader has since deleted", async () => {
    vi.mocked(api.searchCompanyDirectory).mockResolvedValue({ size: 10214, match_count: 1, matches: [spacex] });
    renderSection();
    await waitFor(() => expect(row("FAANG", "Google")).toBeInTheDocument());
    search("space");
    await waitFor(() => row("Other companies", "SpaceX"));
    search("");
    expect(screen.queryByRole("region", { name: "Other companies" })).not.toBeInTheDocument();
  });

  it("an empty answer leaves the empty state to say so", async () => {
    renderSection();
    await waitFor(() => expect(row("FAANG", "Google")).toBeInTheDocument());
    search("zzzz");
    await waitFor(() => expect(vi.mocked(api.searchCompanyDirectory)).toHaveBeenCalledWith("zzzz", expect.anything()));
    expect(await screen.findByText("No company matches “zzzz”.")).toBeInTheDocument();
  });
});

/* --- The whole set, followed as one thing ----------------------- */
describe("CompaniesSection — every other company, followed as one", () => {
  const addMore = () => screen.getByRole("region", { name: "Add more companies" });
  const setCard = () => within(addMore()).getByRole("group", { name: "The wider market" });

  it("with no set to scan, the end of the list offers only a company by its link", async () => {
    renderSection();
    await waitFor(() => expect(row("FAANG", "Google")).toBeInTheDocument());
    expect(within(addMore()).getByRole("button", { name: "Add by link" })).toBeInTheDocument();
    expect(within(addMore()).queryByRole("group")).not.toBeInTheDocument();
    // The group of other companies is drawn only when it has rows.
    expect(screen.queryByRole("region", { name: "Other companies" })).not.toBeInTheDocument();
  });

  it("offers the set beside the link, as a rounded count, and asks before scanning", async () => {
    vi.mocked(api.companyDirectoryStatus).mockResolvedValue(setStatus());
    vi.mocked(api.followCompanyDirectory).mockResolvedValue(setStatus({ following: true, since: "2026-09-24T12:00:00Z" }));
    renderSection();

    await waitFor(() => expect(setCard()).toHaveTextContent("About 10,000 companies on the same job sites"));
    expect(setCard()).toHaveTextContent("only the ones hiring for roles on your radar join your list");
    expect(within(addMore()).getByRole("button", { name: "Add by link" })).toBeInTheDocument();
    // No row for any of them: the set is not a list, and not a group.
    expect(screen.queryByRole("region", { name: "Other companies" })).not.toBeInTheDocument();
    // The index leads to the end of the list.
    expect(within(index()).getByRole("button", { name: "Add more companies" })).toBeEnabled();

    fireEvent.click(within(setCard()).getByRole("button", { name: "Find the ones hiring for you" }));
    const dialog = await screen.findByRole("dialog", { name: "Scan about 10,000 more companies?" });
    // Enter on a dialog that just opened must never start scanning the whole set.
    expect(within(dialog).getByRole("button", { name: "Cancel" })).toHaveFocus();
    fireEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));
    expect(vi.mocked(api.followCompanyDirectory)).not.toHaveBeenCalled();

    fireEvent.click(within(setCard()).getByRole("button", { name: "Find the ones hiring for you" }));
    fireEvent.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Start scanning" }));
    await waitFor(() => expect(vi.mocked(api.followCompanyDirectory)).toHaveBeenCalledWith(true));
    expect(await screen.findByText(
      "Scanning about 10,000 more companies, best-known first.",
    )).toBeInTheDocument();
  });

  it("shows the first pass in the card as it runs: how many are read, and how many are hiring", async () => {
    vi.mocked(api.companyDirectoryStatus).mockResolvedValue(
      setStatus({ following: true, since: "2026-09-24T12:00:00Z", checked: 3200, with_roles: 4 }),
    );
    renderSection();
    const bar = await within(await waitFor(setCard)).findByRole("progressbar", { name: "Companies scanned" });
    expect(bar).toHaveAttribute("aria-valuenow", "3200");
    expect(bar).toHaveAttribute("aria-valuemax", "10214");
    expect(setCard()).toHaveTextContent("3,200 scanned of about 10,000");
    expect(setCard()).toHaveTextContent("4 hiring for you so far");
    expect(setCard()).toHaveTextContent("The scan continues if you leave this page.");
    // Two cards side by side: neither spends a sentence on the app's own name.
    expect(addMore()).not.toHaveTextContent("RoleBand");
    // The sectors are our curation, not the reader's choice: never "your sectors".
    expect(addMore()).not.toHaveTextContent(/sectors/i);
    expect(within(addMore()).getByRole("heading", { name: "The wider market" })).toBeInTheDocument();
    expect(within(addMore()).getByRole("heading", { name: "A specific company" })).toBeInTheDocument();
    expect(within(setCard()).queryByRole("button", { name: "Find the ones hiring for you" })).not.toBeInTheDocument();
  });

  it("after the first pass, says how many are hiring and how many are quiet, and has no bar", async () => {
    vi.mocked(api.companyDirectoryStatus).mockResolvedValue(
      setStatus({ following: true, since: "2026-09-24T12:00:00Z", checked: 10214, with_roles: 5 }),
    );
    renderSection();
    await waitFor(() => expect(setCard()).toHaveTextContent("5 hiring for you"));
    expect(setCard()).toHaveTextContent("10,209 quiet today");
    expect(setCard()).toHaveTextContent("scanned daily");
    expect(setCard()).toHaveTextContent(
      "Quiet ones are scanned again tomorrow.",
    );
    expect(screen.queryByRole("progressbar")).not.toBeInTheDocument();
  });

  // On battery the scan waits for mains power. A line that stopped
  // moving with no word said reads as a broken scan.
  it("on battery, the first scan says it is paused and picks up when plugged in", async () => {
    vi.mocked(api.companyDirectoryStatus).mockResolvedValue(setStatus({
      following: true, since: "2026-09-24T12:00:00Z", checked: 3200, with_roles: 4, waiting_for_power: true,
    }));
    renderSection();
    await waitFor(() => expect(setCard()).toHaveTextContent("first scan paused on battery"));
    expect(setCard()).toHaveTextContent("It picks up where it stopped when you plug in.");
    expect(setCard()).not.toHaveTextContent("first scan running");
    expect(setCard()).not.toHaveTextContent("The scan continues if you leave this page.");
    // What it read so far still counts.
    expect(setCard()).toHaveTextContent("3,200 scanned of about 10,000");
  });

  it("on battery, after the first pass, says the daily checks wait for power", async () => {
    vi.mocked(api.companyDirectoryStatus).mockResolvedValue(setStatus({
      following: true, since: "2026-09-24T12:00:00Z", checked: 10214, with_roles: 5, waiting_for_power: true,
    }));
    renderSection();
    await waitFor(() => expect(setCard()).toHaveTextContent("Paused on battery. Daily scans resume when you plug in."));
    expect(setCard()).not.toHaveTextContent("Quiet ones are scanned again tomorrow.");
    expect(setCard()).toHaveTextContent("5 hiring for you");
  });

  it("started on battery, the scan says it begins when plugged in, not that it is scanning", async () => {
    vi.mocked(api.companyDirectoryStatus).mockResolvedValue(setStatus());
    vi.mocked(api.followCompanyDirectory).mockResolvedValue(
      setStatus({ following: true, since: "2026-09-24T12:00:00Z", waiting_for_power: true }),
    );
    renderSection();
    fireEvent.click(within(await waitFor(setCard)).getByRole("button", { name: "Find the ones hiring for you" }));
    fireEvent.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Start scanning" }));
    expect(await screen.findByText(
      "On battery: the scan of about 10,000 more companies starts when you plug in.",
    )).toBeInTheDocument();
    expect(screen.queryByText(/best-known first/)).not.toBeInTheDocument();
  });

  it("stops scanning without asking, names what it unfollowed, and Undo starts again", async () => {
    vi.mocked(api.companyDirectoryStatus).mockResolvedValue(
      setStatus({ following: true, since: "2026-09-24T12:00:00Z", checked: 10214, with_roles: 31 }),
    );
    vi.mocked(api.followCompanyDirectory).mockImplementation(async (following: boolean) =>
      setStatus({ following, checked: 0 }));
    renderSection();
    fireEvent.click(await within(await waitFor(setCard)).findByRole("button", {
      name: "Stop scanning the wider market",
    }));
    await waitFor(() => expect(vi.mocked(api.followCompanyDirectory)).toHaveBeenCalledWith(false));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    // The count is the one before stopping: the answer to stopping is always 0.
    expect(await screen.findByText("Stopped scanning. The 31 companies it added are no longer followed.")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Undo" }));
    await waitFor(() => expect(vi.mocked(api.followCompanyDirectory)).toHaveBeenLastCalledWith(true));
  });

  it("while searching, the set's card waits and the link stays", async () => {
    vi.mocked(api.companyDirectoryStatus).mockResolvedValue(setStatus());
    renderSection();
    await waitFor(() => expect(setCard()).toBeInTheDocument());
    fireEvent.change(screen.getByRole("searchbox", { name: "Search companies" }), {
      target: { value: "zzzz" },
    });
    await waitFor(() => expect(within(addMore()).queryByRole("group")).not.toBeInTheDocument());
    expect(within(addMore()).getByRole("button", { name: "Add by link" })).toBeInTheDocument();
  });

  it("draws the companies the set found roles at, as ordinary rows", async () => {
    vi.mocked(api.companyDirectoryStatus).mockResolvedValue(
      setStatus({ following: true, since: "2026-09-24T12:00:00Z", checked: 10214, with_roles: 1 }),
    );
    vi.mocked(api.companyDiscovery).mockResolvedValue({
      ...state,
      companies: [
        ...state.companies,
        company({ slug: "esri", display: "Esri", sectors: [], connector_state: "active",
                  parked_reason: null, tracked: true, enabled: true,
                  directory: true, careers_url: null, status: "active" }),
      ],
    });
    renderSection();
    fireEvent.click(await within(await waitFor(() => sectorPanel("Other companies")))
      .findByRole("button", { name: "Other companies", expanded: false }));
    await waitFor(() => expect(row("Other companies", "Esri")).toBeChecked());
    // Never among the user's own URL additions.
    expect(screen.queryByRole("region", { name: "Your additions" })).not.toBeInTheDocument();
  });
});

/* The group of other companies is the one whose size the user does not pick:
 * hundreds of rows once the wider market is followed. It folds to its heading. */
describe("CompaniesSection — the group of other companies folds", () => {
  const directoryState = (): CompanyDiscoveryState => ({
    ...state,
    companies: [
      ...state.companies,
      company({ slug: "esri", display: "Esri", sectors: [], connector_state: "active",
                parked_reason: null, tracked: true, enabled: true,
                directory: true, careers_url: null, status: "active" }),
      company({ slug: "klaviyo", display: "Klaviyo", sectors: [], connector_state: "active",
                parked_reason: null, directory: true, careers_url: null }),
    ],
  });
  const toggle = () => within(sectorPanel("Other companies")).getByRole("button", { name: "Other companies" });
  const rowIn = (name: string) =>
    within(sectorPanel("Other companies")).queryByRole("checkbox", { name });

  beforeEach(() => {
    vi.mocked(api.companyDirectoryStatus).mockResolvedValue(
      setStatus({ following: true, since: "2026-09-24T12:00:00Z", checked: 10214, with_roles: 2 }),
    );
    vi.mocked(api.companyDiscovery).mockResolvedValue(directoryState());
  });

  it("starts folded to its heading, with its counts and its Follow all still there", async () => {
    renderSection();
    await waitFor(() => expect(toggle()).toHaveAttribute("aria-expanded", "false"));
    expect(rowIn("Esri")).not.toBeInTheDocument();
    expect(rowIn("Klaviyo")).not.toBeInTheDocument();
    expect(sectorPanel("Other companies")).toHaveTextContent("1/2 followed");
    expect(within(sectorPanel("Other companies")).getByRole("button", {
      name: "Follow all Other companies companies",
    })).toBeEnabled();
    // Only this group folds: a sector keeps its rows and has no disclosure.
    expect(row("FAANG", "Google")).toBeInTheDocument();
    expect(within(sectorPanel("FAANG")).queryByRole("button", { name: "FAANG" })).not.toBeInTheDocument();
  });

  it("opens and closes from its heading, and remembers which across a remount", async () => {
    const first = renderSection();
    fireEvent.click(await waitFor(toggle));
    expect(toggle()).toHaveAttribute("aria-expanded", "true");
    expect(rowIn("Esri")).toBeChecked();
    expect(rowIn("Klaviyo")).not.toBeChecked();
    first.unmount();

    const second = renderSection();
    await waitFor(() => expect(rowIn("Esri")).toBeChecked());
    fireEvent.click(toggle());
    expect(rowIn("Esri")).not.toBeInTheDocument();
    second.unmount();

    renderSection();
    await waitFor(() => expect(toggle()).toHaveAttribute("aria-expanded", "false"));
    expect(rowIn("Esri")).not.toBeInTheDocument();
  });

  it("a search draws its matches even when the group is folded, and folds back after", async () => {
    renderSection();
    await waitFor(() => expect(toggle()).toHaveAttribute("aria-expanded", "false"));
    const search = screen.getByRole("searchbox", { name: "Search companies" });
    fireEvent.change(search, { target: { value: "esri" } });
    await waitFor(() => expect(rowIn("Esri")).toBeInTheDocument());
    // Nothing to fold while a search is drawn here.
    expect(within(sectorPanel("Other companies")).queryByRole("button", { name: "Other companies" }))
      .not.toBeInTheDocument();

    fireEvent.change(search, { target: { value: "" } });
    await waitFor(() => expect(toggle()).toHaveAttribute("aria-expanded", "false"));
    expect(rowIn("Esri")).not.toBeInTheDocument();
  });

  it("the index link to it opens it", async () => {
    renderSection();
    await waitFor(() => expect(toggle()).toHaveAttribute("aria-expanded", "false"));
    fireEvent.click(within(index()).getByRole("button", { name: /Other companies/ }));
    await waitFor(() => expect(rowIn("Esri")).toBeInTheDocument());
    expect(toggle()).toHaveAttribute("aria-expanded", "true");
  });
});
