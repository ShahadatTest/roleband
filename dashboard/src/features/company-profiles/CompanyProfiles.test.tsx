import { msg } from "../../test/msg";
import { ApiError } from "../../api/transport";
import { act, cleanup, fireEvent, render as rtlRender, screen, waitFor, within } from "@testing-library/react";
import type { ReactElement } from "react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { CompanyPrices, CompanyProfileDetail, CompanyProfileSummary } from "../../api";
import { api } from "../../api";
import {
  PLUGIN_SOURCE,
  PLUGIN_ATTRIBUTION,
  PLUGIN_NAME,
  OUR_SECTION,
  PLUGIN_SECTION,
  companyProfileFieldWriteFixture,
  companyProfileFieldsFixture,
  levelGuideFixture,
  profileFieldFixture,
  profileSectorOrderFixture,
} from "../../test/fixtures";
import { CompanyProfilePanel } from "./CompanyProfilePanel";
import { CompanyProfilesView } from "./CompanyProfilesView";
import { levelName } from "../../copy/vocab";
import { calendarDay } from "../../copy/format";
import { activate } from "../../copy/activate";
import { ToastProvider } from "../../ui/Toast";

type BenefitRowFixture = CompanyProfileDetail["benefits"][number]["items"][number];
import { BRAND_ICONS } from "../../ui/brandIcons.gen";

vi.mock("../../api", () => ({
  PRICE_FEED_KEY_URL: "https://www.tiingo.com/account/api/token",
  api: {
    companyProfile: vi.fn(),
    companyProfiles: vi.fn(),
    companyPrices: vi.fn(),
    companyCard: vi.fn(),
    setCompanyField: vi.fn(),
    clearCompanyField: vi.fn(),
    // Pending unless a test answers it: the codes are not what most tests read.
    levelGuide: vi.fn(() => new Promise(() => {})),
  },
}));

const mocked = vi.mocked(api);

// Every render needs a router: the view/panel use useSearchParams + useNavigate.
function render(ui: ReactElement, { route = "/" }: { route?: string } = {}) {
  return rtlRender(<MemoryRouter initialEntries={[route]}>{ui}</MemoryRouter>);
}

// A probe that echoes the current URL so navigation assertions are user-visible.
function LocationProbe() {
  const loc = useLocation();
  return <div data-testid="location">{`${loc.pathname}${loc.search}`}</div>;
}

const emptyPrices = (over: Partial<CompanyPrices> = {}): CompanyPrices => ({
  slug: "google",
  range: "3m",
  currency: "USD",
  latest: null,
  bars: [],
  // Nothing shown: no credit, and no key set.
  attribution: null,
  feed_configured: false,
  ...over,
});

const mock = (d: CompanyProfileDetail) => {
  mocked.companyPrices.mockResolvedValue(emptyPrices());
  return mocked.companyProfile.mockResolvedValue(d);
};

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((onResolve) => { resolve = onResolve; });
  return { promise, resolve };
}

const field = profileFieldFixture;

const level = (
  band: string,
  level_label: string,
  tc: number,
  base: number,
  stock: number,
  bonus: number,
) => ({
  band,
  level_label,
  currency: "USD",
  tc_median: tc,
  base_amount: base,
  stock_amount: stock,
  bonus_amount: bonus,
  base_pct: base / tc,
  stock_pct: stock / tc,
  bonus_pct: bonus / tc,
  source: PLUGIN_SOURCE,
  source_url: "https://pay.example/x",
});

/** Every switching part of the profile answered by RoleBand's own data. */
const OURS = { pay: OUR_SECTION, benefits: OUR_SECTION, company_size: OUR_SECTION };

/** A test names only the fields it is about; the rest arrive unasserted, as the server sends them. */
type DetailOverrides = Omit<Partial<CompanyProfileDetail>, "fields"> & {
  fields?: Partial<CompanyProfileDetail["fields"]>;
};

const base = ({ fields, ...over }: DetailOverrides = {}): CompanyProfileDetail => ({
  slug: "google",
  display_name: "Google",
  logo_url: "https://static.pay.example/custom/google.webp",
  brand_color: "#33a852",
  data_health: "ok",
  needs_review: [],
  comp_levels: [level("principal", "L7", 907_556, 315_444, 499_333, 92_778)],
  benefits: [
    {
      category: "retirement_financial",
      items: [
        { name: "401k", benefit_type: "retirement_plan", value_usd: 9750, value_text: null, description: "50% match",
          source: PLUGIN_SOURCE, provider: PLUGIN_SOURCE, builtin: false, kind: "provider", country: null, reviewed: false, mentions: 0, wordings: [] },
        { name: "Free yacht", benefit_type: null, value_usd: null, value_text: "20 days", description: null,
          source: PLUGIN_SOURCE, provider: PLUGIN_SOURCE, builtin: false, kind: "provider", country: null, reviewed: false, mentions: 0, wordings: [] },
      ],
    },
  ],
  level_base: [],
  benefit_notes: [],
  offer_policy: {
    verified_on: "2026-10-09",
    facts: [
      { fact: "equity_rule", value: "dollar_grant_by_level", stated_by: "estimated" },
      { fact: "bonus_rule", value: "pct_of_base", stated_by: "employer" },
      { fact: "annual_refresh", value: null, stated_by: null },
    ],
    unknown_fields: [],
  },
  comp_notes: null,
  open_roles: 0,
  unfollowed: false,
  locations: [],
  attribution: PLUGIN_ATTRIBUTION,
  source_names: { [PLUGIN_SOURCE]: PLUGIN_NAME },
  // The plugin answers pay and benefits; company size and identity are ours.
  sources: { pay: PLUGIN_SECTION, benefits: PLUGIN_SECTION, company_size: OUR_SECTION },
  ...over,
  fields: companyProfileFieldsFixture(fields ?? {
    is_public: field(true),
    ticker: field("GOOG"),
    headcount: field(258750),
    equity_vehicle: field("rsu"),
  }),
});

describe("CompanyProfilePanel", () => {
  beforeEach(() => vi.clearAllMocks());

  it("names the source only when it is not one the footer already credits", async () => {
    // Every row carrying an identical plugin chip is decoration: the panel
    // footer already credits the plugin. A chip has to mean "this row is
    // different" — otherwise the rows that ARE different stop standing out.
    mock(
      base({
        fields: {
          ticker: field("GOOG"),
          equity_vehicle: field("rsu", { source: "heuristic" }),
        },
      }),
    );
    render(<CompanyProfilePanel slug="google" />);

    const ticker = (await screen.findByText("Ticker")).closest(".prof-field")!;
    expect(within(ticker as HTMLElement).getByText("GOOG")).toBeInTheDocument();
    expect(within(ticker as HTMLElement).queryByText(PLUGIN_NAME)).toBeNull();

    // ...but a value we inferred, rather than observed, still says so.
    const ev = screen.getByText("Equity vehicle").closest(".prof-field")!;
    expect(within(ev as HTMLElement).getByText("Inferred")).toBeInTheDocument();
  });

  it("shows a website as its bare domain, linking to the full URL", async () => {
    // "https://www.google.com" spent most of the row's width on a scheme and a
    // `www.` that name nothing. The link still goes to the untouched URL.
    mock(base({ fields: { website: field("https://www.google.com") } }));
    render(<CompanyProfilePanel slug="google" />);

    const link = await screen.findByRole("link", { name: "google.com" });
    expect(link).toHaveAttribute("href", "https://www.google.com");
    expect(link).toHaveAttribute("target", "_blank");
    expect(screen.queryByText("https://www.google.com")).toBeNull();
  });

  it("words a one-year grant on the vesting row and shows a schedule as sent", async () => {
    // Coinbase grants equity one year at a time: the atlas sends a code, never a fraction
    // a job package would read. A real schedule is data and shows unchanged.
    mock(base({ fields: { vesting_schedule: field("one_year_grants", { source: "employer" }) } }));
    const { unmount } = render(<CompanyProfilePanel slug="coinbase" />);
    const row = (await screen.findByText(msg("profiles-labels-vesting"))).closest(".prof-field")!;
    expect(within(row as HTMLElement).getByText(msg("profiles-labels-one-year-grants"))).toBeInTheDocument();
    expect(within(row as HTMLElement).queryByText("one_year_grants")).toBeNull();
    unmount();

    mock(base({ fields: { vesting_schedule: field("25/25/25/25") } }));
    render(<CompanyProfilePanel slug="meta" />);
    const plain = (await screen.findByText(msg("profiles-labels-vesting"))).closest(".prof-field")!;
    expect(within(plain as HTMLElement).getByText("25/25/25/25")).toBeInTheDocument();
  });

  it("gives a scheme-less website a real href instead of a relative one", async () => {
    // A source may omit the scheme; a bare domain in an href would
    // navigate inside the dashboard rather than out to the company.
    mock(base({ fields: { website: field("anthropic.com/") } }));
    render(<CompanyProfilePanel slug="anthropic" />);

    const link = await screen.findByRole("link", { name: "anthropic.com" });
    expect(link).toHaveAttribute("href", "https://anthropic.com/");
  });

  it("ignores an older company response after the selected slug changes", async () => {
    const google = deferred<CompanyProfileDetail>();
    const netflix = deferred<CompanyProfileDetail>();
    mocked.companyPrices.mockResolvedValue(emptyPrices());
    mocked.companyProfile.mockImplementation(
      (slug: string) => slug === "google" ? google.promise : netflix.promise,
    );
    const view = rtlRender(
      <MemoryRouter><CompanyProfilePanel slug="google" /></MemoryRouter>,
    );
    view.rerender(
      <MemoryRouter><CompanyProfilePanel slug="netflix" /></MemoryRouter>,
    );

    await act(async () => netflix.resolve(base({ slug: "netflix", display_name: "Netflix" })));
    expect(await screen.findByRole("heading", { name: "Netflix" })).toBeInTheDocument();
    await act(async () => google.resolve(base({ slug: "google", display_name: "Google" })));

    expect(screen.getByRole("heading", { name: "Netflix" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Google" })).toBeNull();
  });

  it("surfaces conflicting signals with the dissenting source and its claim", async () => {
    // A filing gives a ticker; another source still says the company is private.
    mock(
      base({
        slug: "reddit",
        display_name: "Reddit",
        data_health: "conflict",
        fields: {
          ticker: field("RDDT", {
            source: "sec_edgar",
            
            conflicts: [
              {
                source: "reported",
                source_label: "Estimated",
                value: null,
                observed_at: "2026-07-14T00:00:00Z",
              },
            ],
          }),
        },
      }),
    );
    render(<CompanyProfilePanel slug="reddit" enriching />);

    // Winner is shown, attributed to the higher-trust source...
    const ticker = (await screen.findByText("Ticker")).closest(".prof-field")!;
    expect(within(ticker as HTMLElement).getByText("RDDT")).toBeInTheDocument();
    expect(within(ticker as HTMLElement).getByText("SEC EDGAR")).toBeInTheDocument();
    // ...and the disagreement is explicit, not silently dropped.
    expect(within(ticker as HTMLElement).getByText(/Conflicting signal/i)).toBeInTheDocument();
    expect(within(ticker as HTMLElement).getByText(msg("profiles-labels-no-value"))).toBeInTheDocument();
    // The dissent is one of RoleBand's own sources, named from the catalog:
    // identity is never a plugin's.
    expect(ticker).toHaveTextContent(`${msg("vocab-source-reported")} says`);
    // The hero keeps the health signal as a compact dot (the badge slot holds
    // the open-roles pill), surfaced by its accessible title.
    expect(screen.getByTitle("Conflicting signals")).toBeInTheDocument();
  });

  it("marks a manually pinned value as user-sourced", async () => {
    mock(
      base({
        fields: {
          headcount: field(2000, {
            source: "manual",
            
            is_manual: true,
          }),
        },
      }),
    );
    render(<CompanyProfilePanel slug="anthropic" enriching />);
    const hc = (await screen.findByText("Headcount")).closest(".prof-field")!;
    expect(within(hc as HTMLElement).getByText("2,000")).toBeInTheDocument();
    expect(within(hc as HTMLElement).getByText("Manual (you)")).toBeInTheDocument();
  });

  it("flags a stale claim", async () => {
    mock(base({ fields: { headcount: field(45, { freshness: "stale" }) } }));
    render(<CompanyProfilePanel slug="anthropic" enriching />);
    expect(await screen.findByText("stale")).toBeInTheDocument();
  });

  it("renders the comp baseline with its stock share", async () => {
    mock(base());
    render(<CompanyProfilePanel slug="google" />);
    const row = (await screen.findByText("Principal")).closest("tr")!;
    expect(within(row).getByText("L7")).toBeInTheDocument();
    expect(within(row).getByText("$908K")).toBeInTheDocument();
    expect(within(row).getByText("55%")).toBeInTheDocument(); // stock share
  });

  const policy = (rule: string): CompanyProfileDetail["offer_policy"] => ({
    verified_on: "2026-10-09",
    facts: [{ fact: "equity_rule", value: rule, stated_by: "estimated" }],
    unknown_fields: [],
  });

  it("says a company pays no stock only when our equity policy says so, never from a level's 0", async () => {
    // 1Password grants options; the pay source writes 0 for stock it does not
    // value. A measured 0 is shown as the source's figure, and says nothing
    // about the company.
    mock(base({
      slug: "1password", display_name: "1Password",
      comp_levels: [level("senior", "Senior Developer", 182_880, 182_880, 0, 0)],
    }));
    const { unmount } = render(<CompanyProfilePanel slug="1password" />);
    const row = (await screen.findByText("Senior Developer")).closest("tr")!;
    expect(within(row).getByText("0%")).toBeInTheDocument();
    expect(screen.queryByTestId("equity-policy")).not.toBeInTheDocument();
    unmount();

    // Two Sigma: our data says it grants none.
    mock(base({ slug: "two-sigma", offer_policy: policy("none"), comp_levels: [level("staff", "L6", 500_000, 500_000, 0, 0)] }));
    render(<CompanyProfilePanel slug="two-sigma" />);
    expect(await screen.findByTestId("equity-policy")).toHaveTextContent(msg("profiles-equity-policy", { rule: "none" }));
  });

  it("says each employee chooses at a company whose policy is an election", async () => {
    mock(base({ slug: "netflix", offer_policy: policy("employee_election"), comp_levels: [level("staff", "L6", 756_250, 756_250, 0, 0)] }));
    render(<CompanyProfilePanel slug="netflix" />);
    expect(await screen.findByTestId("equity-policy")).toHaveTextContent(msg("profiles-equity-policy", { rule: "election" }));
  });

  it("states the policy on our own baseline too, not only a plugin's ladder", async () => {
    mock(base({ sources: OURS, comp_levels: [], offer_policy: policy("none") }));
    render(<CompanyProfilePanel slug="two-sigma" />);
    expect(await screen.findByTestId("equity-policy")).toHaveTextContent(msg("profiles-equity-policy", { rule: "none" }));
  });

  it("an empty chart without a key draws the chart's ghost, says prices come from Tiingo, links its key page and Settings, credits nobody", async () => {
    mock(base());
    render(<CompanyProfilePanel slug="google" />);
    const empty = await screen.findByTestId("price-empty");
    // The ghost holds the chart's place, as decoration only.
    expect(empty.querySelector(".ui-empty-ghost-chart")).toHaveAttribute("aria-hidden", "true");
    expect(empty).toHaveTextContent(/Tiingo integration/);
    const key = within(empty).getByRole("link", { name: msg("shared-price-feed-get-key") });
    expect(key).toHaveAttribute("href", "https://www.tiingo.com/account/api/token");
    expect(key).toHaveAttribute("target", "_blank");
    expect(within(empty).getByRole("link", { name: msg("profiles-stock-price-panel-add-key") }))
      .toHaveAttribute("href", "/settings/plugins");
    expect(screen.queryByText(/offline sample/)).not.toBeInTheDocument();
    expect(screen.queryByText(/python -m/)).not.toBeInTheDocument();
  });

  it("an empty chart with a key set waits for the next scan, with no instructions", async () => {
    mocked.companyProfile.mockResolvedValue(base());
    mocked.companyPrices.mockResolvedValue(emptyPrices({ feed_configured: true }));
    render(<CompanyProfilePanel slug="google" />);
    expect(await screen.findByTestId("price-empty")).toHaveTextContent(msg("profiles-stock-price-panel-waiting"));
    expect(screen.queryByRole("link", { name: msg("shared-price-feed-get-key") })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: msg("profiles-stock-price-panel-add-key") })).not.toBeInTheDocument();
  });

  it("shows an unknown stock share as not known, and keeps a level without a total", async () => {
    // The source published a total only, and another level with base only.
    mock(base({
      comp_levels: [
        { ...level("senior", "L5", 400_000, 200_000, 150_000, 50_000),
          base_amount: null, stock_amount: null, bonus_amount: null,
          base_pct: null, stock_pct: null, bonus_pct: null },
        { ...level("staff", "L6", 1, 300_000, 0, 0),
          tc_median: null, stock_amount: null, bonus_amount: null,
          base_pct: null, stock_pct: null, bonus_pct: null },
      ],
    }));
    render(<CompanyProfilePanel slug="google" />);
    const senior = (await screen.findByText("L5")).closest("tr")!;
    expect(senior).toHaveTextContent("$400K");
    expect(senior).toHaveTextContent(msg("profiles-level-base-unknown"));
    expect(senior).not.toHaveTextContent("0%");
    expect(senior.querySelector(".split-bar")).toBeNull();
    const staff = screen.getByText("L6").closest("tr")!;
    expect(staff).toHaveTextContent(msg("profiles-level-base-unknown"));
    expect(screen.queryByTestId("equity-policy")).not.toBeInTheDocument();
  });

  it("names each benefit by its type, keeps a provider's own label, never sums", async () => {
    mock(base());
    render(<CompanyProfilePanel slug="google" />);
    expect(await screen.findByText(msg("profiles-benefits-category", { category: "retirement_financial" })))
      .toBeInTheDocument();
    // An estimate is labelled as one; with no terms behind it, the row adds no filler line.
    const k = screen.getByText(msg("profiles-benefits-type", { type: "retirement_plan" })).closest("li")!;
    expect(within(k).getByText(msg("profiles-benefits-estimate", { value: "$10K" }))).toBeInTheDocument();
    expect(k.querySelector(".benefit-terms")).toBeNull();
    expect(screen.queryByText(/Details not captured/)).toBeNull();
    const own = screen.getByText("Free yacht").closest("li")!;  // no alias maps it: its own name
    expect(within(own).getByText("20 days")).toBeInTheDocument();
    expect(screen.queryByText(/estimated value/)).toBeNull();  // perks are never summed
  });

  const ours = (over: Partial<BenefitRowFixture>): BenefitRowFixture => ({
    name: null, benefit_type: "vacation", value_usd: null, value_text: null, description: null, source: "builtin",
    provider: "builtin", builtin: true, kind: "dataset", country: null, reviewed: false, mentions: 0, wordings: [],
    ...over,
  });

  it("shows each benefit once: its best wording, its mentions, the rest behind a toggle", async () => {
    mock(base({
      sources: OURS,
      benefits: [{ category: "retirement_financial", items: [ours({
        benefit_type: "retirement_plan", value_text: "Match vests only after 3 years.", mentions: 75,
        wordings: [{ text: "401(k) Plan", kind: "employer", country: null },
                   { text: "Roth option", kind: "dataset", country: "US" }],
      })] }],
    }));
    render(<CompanyProfilePanel slug="amazon" />);
    const row = (await screen.findByText("Match vests only after 3 years.")).closest("li")!;
    expect(screen.getAllByText(msg("profiles-benefits-type", { type: "retirement_plan" }))).toHaveLength(1);
    expect(row).toHaveTextContent(msg("profiles-benefits-mentions", { count: 75 }));
    expect(screen.queryByText("401(k) Plan")).toBeNull();  // folded until asked for
    const toggle = within(row).getByRole("button", { name: msg("profiles-benefits-other-wordings", { open: "no", count: 2 }) });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(toggle);
    expect(within(row).getByText("401(k) Plan").closest("li")).toHaveTextContent(msg("vocab-source-employer"));
    expect(within(row).getByText("Roth option")).toBeInTheDocument();
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(toggle).toHaveTextContent(msg("profiles-benefits-other-wordings", { open: "yes", count: 2 }));
  });

  it("lists benefits recorded by name alone on one line, not a row each", async () => {
    mock(base({
      sources: OURS,
      benefits: [{ category: "health_wellbeing", items: [
        ours({ benefit_type: "dental_insurance" }),
        ours({ benefit_type: "pet_insurance" }),
        ours({ benefit_type: "medical_insurance", mentions: 73, kind: "employer" }),
      ] }],
    }));
    render(<CompanyProfilePanel slug="amazon" />);
    const names = [msg("profiles-benefits-type", { type: "dental_insurance" }),
                   msg("profiles-benefits-type", { type: "pet_insurance" })];
    const line = await screen.findByText(msg("profiles-benefits-also-listed", { names: `${names[0]} and ${names[1]}` }));
    expect(line.closest("li")).toBeNull();
    // Named in its postings is something to say: that one keeps its row.
    const medical = screen.getByText(msg("profiles-benefits-type", { type: "medical_insurance" })).closest("li")!;
    expect(medical).toHaveTextContent(msg("profiles-benefits-mentions", { count: 73 }));
    expect(medical).not.toHaveTextContent(msg("vocab-source-employer"));  // no words of its own to attribute
  });

  it("says a sentence several benefits share once, under none of them", async () => {
    const said = "Medical, Dental, and Vision Coverage";
    mock(base({
      sources: OURS,
      benefits: [{ category: "health_wellbeing", items: [
        ours({ benefit_type: "dental_insurance", mentions: 27, kind: "employer" }),
        ours({ benefit_type: "vision_insurance", mentions: 27, kind: "employer" }),
      ] }],
      benefit_notes: [{ text: said, mentions: 27, benefit_types: ["dental_insurance", "vision_insurance"] }],
    }));
    render(<CompanyProfilePanel slug="amazon" />);
    expect(await screen.findAllByText(said)).toHaveLength(1);
    const notes = screen.getByTestId("benefit-notes");
    expect(within(notes).getByText(msg("profiles-benefits-shared"))).toBeInTheDocument();
    expect(within(notes).getByText(said).closest("li")).toHaveTextContent(msg("profiles-benefits-mentions", { count: 27 }));
  });

  const ourLevel = (over: Partial<CompanyProfileDetail["level_base"][number]>) => ({
    band: "senior", base_usd: 236000, bonus_ratio: null, bonus_usd: null,
    below_lower: false, stock_usd: null, total_usd: null,
    ...over,
  });

  it("adds stock and a total only for a company our data holds stock for, a total only when every part is known", async () => {
    mock(base({
      sources: OURS,
      comp_levels: [],
      level_base: [
        ourLevel({ band: "senior", base_usd: 196900, bonus_ratio: 0, bonus_usd: 0, stock_usd: 170160, total_usd: 367060 }),
        ourLevel({ band: "staff", base_usd: 230000, stock_usd: 250000 }),  // bonus unknown: no total
        ourLevel({ band: "principal", base_usd: 247100 }),  // no stock point
      ],
    }));
    render(<CompanyProfilePanel slug="amazon" />);
    const table = await screen.findByTestId("level-base");
    expect(within(table).getByRole("columnheader", { name: msg("profiles-company-profile-panel-stock") })).toBeInTheDocument();
    const row = (band: string) => within(table).getByText(levelName(band)).closest("tr")!;
    expect(row("senior")).toHaveTextContent("$170K");
    expect(row("senior")).toHaveTextContent("$367K");
    const cells = (band: string) => [...row(band).querySelectorAll("td")].map((td) => td.textContent);
    // Band | Base | Bonus | Stock | Total: an unknown bonus leaves the total unknown.
    expect(cells("staff").slice(1, 4)).toEqual([msg("profiles-level-base-bonus", { choice: "unknown", amount: "", pct: "" }),
      expect.stringContaining("$250K"), msg("profiles-level-base-unknown")]);
    expect(cells("principal").slice(2, 4)).toEqual([msg("profiles-level-base-unknown"), msg("profiles-level-base-unknown")]);
    expect(screen.getByText(msg("profiles-level-base-sub", { stock: "yes" }))).toBeInTheDocument();
  });

  describe("the company's own code for each level", () => {
    const codeColumn = () => msg("profiles-company-profile-panel-level");
    const renderBaseline = async (slug: string, bands: string[]) => {
      const guide = Promise.resolve(levelGuideFixture);
      mocked.levelGuide.mockReturnValue(guide);
      mock(base({ sources: OURS, comp_levels: [], level_base: bands.map((band) => ourLevel({ band })) }));
      render(<CompanyProfilePanel slug={slug} />);
      const table = await screen.findByTestId("level-base");
      await act(() => guide);
      return table;
    };
    const codeOf = (table: HTMLElement, band: string) =>
      within(table).getByText(levelName(band)).closest("tr")!.querySelector("td")!.textContent;

    it("shows the code beside the level, and says a level the ladder skips has none", async () => {
      const table = await renderBaseline("amazon", ["senior", "staff", "principal"]);
      expect(within(table).getByRole("columnheader", { name: codeColumn() })).toBeInTheDocument();
      expect(codeOf(table, "senior")).toBe("L6");
      // Amazon has no Staff rung: no code, and never L6 or L7 borrowed from a neighbour.
      expect(codeOf(table, "staff")).toBe(msg("profiles-level-base-no-code", { level: levelName("staff") }));
      expect(codeOf(table, "principal")).toBe("L7");
    });

    it("reads a level split by track on the engineering ladder the baseline prices", async () => {
      const table = await renderBaseline("google", ["staff", "principal", "director_plus"]);
      expect(codeOf(table, "staff")).toBe("L6");
      // Google's L8 is Principal for engineers; the management ladder would say L7 and L8–L10.
      expect(codeOf(table, "principal")).toBe("L7–L8");
      expect(codeOf(table, "director_plus")).toBe("L9–L10");
    });

    it("shows no code column for a flat ladder or a company without a guide", async () => {
      for (const slug of ["meta", "stripe"]) {
        const table = await renderBaseline(slug, ["entry", "mid"]);
        expect(within(table).queryByRole("columnheader", { name: codeColumn() })).not.toBeInTheDocument();
        expect(table).not.toHaveTextContent(/University Grad|Software Engineer/);
        cleanup();
      }
    });
  });

  it("says a company that grants no stock has none", async () => {
    mock(base({
      sources: OURS, comp_levels: [],
      level_base: [ourLevel({ band: "mid", base_usd: 172500, bonus_ratio: null, stock_usd: 0 })],
    }));
    render(<CompanyProfilePanel slug="two-sigma" />);
    const row = (await screen.findByTestId("level-base")).querySelector("tbody tr")!;
    expect(row).toHaveTextContent(msg("profiles-level-base-no-stock"));
    expect(row).not.toHaveTextContent("$0");
  });

  it("shows estimated base and bonus per level without traceability details", async () => {
    mock(base({
      sources: OURS,
      comp_levels: [],
      level_base: [
        ourLevel({ band: "entry", base_usd: 129000, bonus_ratio: 0, bonus_usd: 0 }),
        ourLevel({ band: "senior", base_usd: 236000, bonus_ratio: 0.175, bonus_usd: 41300 }),
        ourLevel({ band: "staff", base_usd: 224000, below_lower: true }),
        ourLevel({ band: "principal", base_usd: 307050, bonus_ratio: 0, bonus_usd: 0 }),
        ourLevel({ band: "director_plus", base_usd: 418500 }),
      ],
    }));
    render(<CompanyProfilePanel slug="google" />);
    const table = await screen.findByTestId("level-base");
    const row = (band: string) => within(table).getByText(levelName(band)).closest("tr")!;
    expect(row("senior")).toHaveTextContent("$236K");
    expect(within(table).queryByRole("columnheader", { name: "From" })).not.toBeInTheDocument();
    expect(table).not.toHaveTextContent(/reported|pay filings|posted ranges/i);
    expect(screen.getByRole("heading", { name: "Comp bands" })).toBeInTheDocument();
    expect(within(table).getByText(msg("taxonomy-band-entry"))).toBeInTheDocument();  // every band by its name
    expect(row("senior")).toHaveTextContent(/17\.5%/);
    expect(row("staff")).toHaveTextContent(msg("profiles-level-base-below-lower"));
    expect(row("staff")).toHaveTextContent(msg("profiles-level-base-bonus", { choice: "unknown", amount: "", pct: "" }));
    expect(row("senior")).not.toHaveTextContent(msg("profiles-level-base-below-lower"));
    expect(row("principal")).toHaveTextContent(msg("profiles-level-base-bonus", { choice: "none", amount: "", pct: "" }));
    expect(row("director_plus")).toHaveTextContent("$419K");
    // Our data holds no stock: no stock column, no total, no split legend.
    expect(within(table).queryByText(msg("profiles-company-profile-panel-stock"))).toBeNull();
    expect(within(table).queryByText(msg("profiles-company-profile-panel-total-comp"))).toBeNull();
    expect(screen.getByText(msg("profiles-level-base-sub", { stock: "no" }))).toBeInTheDocument();
  });


  it("says when we have no base for the company's levels, never a plugin's ladder in its place", async () => {
    mock(base({ sources: OURS, level_base: [] }));  // comp_levels still holds a plugin row: not shown
    render(<CompanyProfilePanel slug="acme" />);
    const body = await screen.findByText(msg("profiles-level-base-none"));
    expect(body).toBeInTheDocument();
    // The empty table draws its own ghost rows under the title.
    expect(screen.getByText(msg("profiles-company-profile-panel-no-comp-bands-yet"))).toBeInTheDocument();
    expect(body.closest(".ui-empty-preview")!.querySelector(".ui-empty-ghost-rows")).not.toBeNull();
    expect(screen.queryByText("L7")).toBeNull();
  });

  it("marks the employer's own words in RoleBand's dataset", async () => {
    mock(base({
      sources: OURS,
      benefits: [{
        category: "retirement_financial",
        items: [{ name: null, benefit_type: "employee_share_purchase", value_usd: null, value_text: "15% discount",
          description: null, source: "builtin", provider: "builtin", builtin: true, kind: "employer", country: "US",
          reviewed: false, mentions: 0, wordings: [] }],
      }],
    }));
    render(<CompanyProfilePanel slug="google" />);
    const employer = (await screen.findByText(msg("profiles-benefits-type", { type: "employee_share_purchase" }), {
      exact: false })).closest("li")!;
    expect(employer).toHaveTextContent(msg("vocab-source-employer"));
    expect(employer).toHaveTextContent("15% discount");
  });

  it("says a plugin has not read the company, and shows none of RoleBand's data in its place", async () => {
    const unread = { ...PLUGIN_SECTION, covered: false };
    mock(base({ comp_levels: [], benefits: [], sources: { pay: unread, benefits: unread, company_size: unread } }));
    render(<CompanyProfilePanel slug="anthropic" />);
    const said = msg("profiles-not-covered", { plugin: PLUGIN_NAME });
    expect(await screen.findAllByText((_, node) => node?.textContent === said && node.classList.contains("empty-hint")))
      .toHaveLength(2);  // the pay ladder and the benefits
    expect(screen.queryByText(msg("profiles-benefits-not-collected"))).toBeNull();
    expect(screen.queryByText(msg("profiles-company-profile-panel-no-level-in-this-company"))).toBeNull();
  });

  it("names the plugin on a company size it has not read, never a bare dash", async () => {
    const unread = { ...PLUGIN_SECTION, covered: false };
    mock(base({
      sources: { ...OURS, company_size: unread },
      fields: { headcount: field(null, { source: null, answered_by: PLUGIN_SOURCE, editable: false }) },
    }));
    render(<CompanyProfilePanel slug="anthropic" />);
    const row = (await screen.findByText(msg("profiles-labels-headcount"))).closest(".prof-field")!;
    expect(row).toHaveTextContent(msg("profiles-field-not-covered", { plugin: PLUGIN_NAME }));
    expect(row).not.toHaveTextContent("—");
  });

  it("an unknown company size of ours stays a dash: only a plugin's gap is named", async () => {
    mock(base({ sources: OURS, fields: { headcount: field(null, { source: null }) } }));
    render(<CompanyProfilePanel slug="anthropic" />);
    const row = (await screen.findByText(msg("profiles-labels-headcount"))).closest(".prof-field")!;
    expect(row).toHaveTextContent("—");
    expect(row).not.toHaveTextContent(msg("profiles-field-not-covered", { plugin: PLUGIN_NAME }));
  });

  it("shows a benefit's terms beside its estimate, never the estimate in their place", async () => {
    mock(base({
      sources: OURS,
      benefits: [{
        category: "retirement_financial",
        items: [{ name: null, benefit_type: "retirement_plan", value_usd: 9750, value_text: "3-6% of base by tenure",
          description: null, source: "builtin", provider: "builtin", builtin: true, kind: "dataset", country: null,
          reviewed: false, mentions: 0, wordings: [] }],
      }],
    }));
    render(<CompanyProfilePanel slug="apple" />);
    const row = (await screen.findByText(msg("profiles-benefits-type", { type: "retirement_plan" }))).closest("li")!;
    expect(within(row).getByText("3-6% of base by tenure")).toBeInTheDocument();
    expect(within(row).getByText(msg("profiles-benefits-estimate", { value: "$10K" }))).toBeInTheDocument();
  });

  it("shows the sentence that names an employer's benefit, with the full statement on hover", async () => {
    const full = "The base salary range is listed below. Starting Day 1, Acme offers EAP and Mental Health Support.";
    mock(base({
      sources: OURS,
      benefits: [{
        category: "health_wellbeing",
        items: [{ name: null, benefit_type: "mental_health_support", value_usd: null,
          value_text: "Starting Day 1, Acme offers EAP and Mental Health Support.", description: full,
          source: "builtin", provider: "builtin", builtin: true, kind: "employer", country: null, reviewed: false, mentions: 0, wordings: [] }],
      }],
    }));
    render(<CompanyProfilePanel slug="acme" />);
    const row = (await screen.findByText("Starting Day 1, Acme offers EAP and Mental Health Support.")).closest("li")!;
    expect(row).not.toHaveTextContent("salary");
    expect(row).toHaveAttribute("title", full);
  });

  it("says what nobody checked: unreviewed records and records with no country", async () => {
    mock(base());
    render(<CompanyProfilePanel slug="google" />);
    await screen.findByText("Free yacht");
    expect(screen.getByText(msg("profiles-benefits-unreviewed"), { exact: false })).toBeInTheDocument();
    expect(screen.getByText(msg("profiles-benefits-unscoped"), { exact: false })).toBeInTheDocument();
  });

  it("drops each caveat once it no longer holds", async () => {
    mock(base({
      sources: OURS,
      benefits: [{
        category: "time_off",
        items: [{ name: null, benefit_type: "vacation", value_usd: null, value_text: "25 days", description: null,
          source: "builtin", provider: "builtin", builtin: true, kind: "employer", country: "GB", reviewed: true, mentions: 0, wordings: [] }],
      }],
    }));
    render(<CompanyProfilePanel slug="acme" />);
    await screen.findByText("25 days");
    expect(screen.queryByText(msg("profiles-benefits-unreviewed"), { exact: false })).not.toBeInTheDocument();
    expect(screen.queryByText(msg("profiles-benefits-unscoped"), { exact: false })).not.toBeInTheDocument();
  });

  it("an empty benefits list says nothing was collected, never that there are none", async () => {
    mock(base({
      sources: OURS, benefits: [] }));
    render(<CompanyProfilePanel slug="openai" />);
    expect(await screen.findByText(msg("profiles-benefits-not-collected"))).toBeInTheDocument();
  });

  it("credits the plugins answering, as they write it", async () => {
    mock(base());
    render(<CompanyProfilePanel slug="google" />);
    expect(await screen.findByText(PLUGIN_ATTRIBUTION)).toBeInTheDocument();
    expect(screen.getByText(/named at the foot of this panel/)).toBeInTheDocument();
  });

  it("credits nothing when only RoleBand's own data answers", async () => {
    mock(base({ attribution: null, source_names: {} }));
    render(<CompanyProfilePanel slug="google" />);
    await screen.findByRole("heading", { name: "Google" });
    // (The price panel's own credit is a separate line, for its own source.)
    expect(screen.queryByText(/Data source/)).toBeNull();
    // Nor a sentence pointing at a credit that is not there.
    expect(screen.queryByText(/named at the foot of this panel/)).toBeNull();
  });
});

const candidate = (source: string, source_label: string, rank: number, value: unknown) => ({
  source,
  source_label,
  rank,
  value,
  observed_at: "2026-07-14T00:00:00Z",
});

const SEC = candidate("sec_edgar", "SEC EDGAR", 80, "RDDT");
const AGG = candidate("reported", "Estimated", 55, null);

const reviewable = () =>
  base({
    slug: "reddit",
    display_name: "Reddit",
    data_health: "conflict",
    needs_review: [
      {
        field: "ticker",
        reason: "conflict",
        current: "RDDT",
        suggestion: SEC,
        candidates: [SEC, AGG],
      },
    ],
  });

describe("CompanyProfilePanel — how offers are built", () => {
  beforeEach(() => vi.clearAllMocks());

  const card = async () =>
    (await screen.findByRole("heading", { name: msg("profiles-offer-heading") })).closest(".panel")! as HTMLElement;
  const row = (scope: HTMLElement, label: string) =>
    within(scope).getByText(label, { selector: ".prof-field-l" }).closest(".prof-field")! as HTMLElement;

  it("states each atlas fact with who states it, and a searched-for gap as one", async () => {
    mock(base());
    render(<CompanyProfilePanel slug="google" />);
    const offers = await card();
    const equity = row(offers, msg("profiles-offer-fact", { fact: "equity_rule" }));
    expect(equity).toHaveTextContent(msg("profiles-offer-equity-rule", { rule: "dollar_grant_by_level" }));
    expect(equity).toHaveTextContent(msg("vocab-source-reported"));
    const bonus = row(offers, msg("profiles-offer-fact", { fact: "bonus_rule" }));
    expect(bonus).toHaveTextContent(msg("profiles-offer-bonus-rule", { rule: "pct_of_base" }));
    expect(bonus).toHaveTextContent(msg("vocab-source-employer"));
    const refresh = row(offers, msg("profiles-offer-fact", { fact: "annual_refresh" }));
    expect(refresh).toHaveTextContent(msg("profiles-offer-searched-not-found"));
    expect(refresh).not.toHaveTextContent(msg("vocab-source-employer"));
    expect(within(offers).getByText(msg("profiles-offer-checked", { date: "Oct 9" }), { exact: false }))
      .toBeInTheDocument();
  });

  it("moves the equity vehicle and vesting out of the identity facts and into the card", async () => {
    mock(base());
    render(<CompanyProfilePanel slug="google" />);
    const offers = await card();
    const vehicle = msg("profiles-labels-equity-vehicle");
    expect(row(offers, vehicle)).toHaveTextContent("RSUs");
    // One row each, and only in the card.
    expect(screen.getAllByText(vehicle, { selector: ".prof-field-l" })).toHaveLength(1);
    expect(screen.getAllByText(msg("profiles-labels-vesting"), { selector: ".prof-field-l" })).toHaveLength(1);
  });

  it("says a field was searched for, not left blank, when the atlas found nothing", async () => {
    mock(base({ offer_policy: { verified_on: null, facts: [], unknown_fields: ["vesting_schedule"] } }));
    render(<CompanyProfilePanel slug="acme" />);
    const offers = await card();
    expect(row(offers, msg("profiles-labels-vesting"))).toHaveTextContent(msg("profiles-offer-searched-not-found"));
    // The vehicle was not searched for: a plain dash, not a claim of a search.
    expect(row(offers, msg("profiles-labels-equity-vehicle"))).not.toHaveTextContent(
      msg("profiles-offer-searched-not-found"));
  });

  it("a company never researched says so once, instead of a row of dashes", async () => {
    mock(base({ offer_policy: null }));
    render(<CompanyProfilePanel slug="10xteam" />);
    const offers = await card();
    expect(within(offers).getByText(msg("profiles-offer-not-researched"))).toBeInTheDocument();
    expect(within(offers).queryByText(msg("profiles-offer-searched-not-found"))).not.toBeInTheDocument();
    expect(within(offers).queryByText(msg("profiles-offer-fact", { fact: "equity_rule" }))).not.toBeInTheDocument();
  });
});

describe("manual-enrichment workflow", () => {
  beforeEach(() => vi.clearAllMocks());

  const setField = () =>
    mocked.setCompanyField;

  it("offers every source's claim on the flagged field, marking our suggestion", async () => {
    mock(reviewable());
    render(<CompanyProfilePanel slug="reddit" enriching />);

    // Resolution lives on the field it concerns, anchored by the reason the
    // row was flagged.
    const row = (await screen.findByText("Sources disagree")).closest(".prof-field")!;
    expect(within(row as HTMLElement).getByText("Ticker")).toBeInTheDocument();
    // Both candidates are offered: the user picks, rather than researching.
    expect(within(row as HTMLElement).getByText("RDDT")).toBeInTheDocument();
    expect(within(row as HTMLElement).getByText(msg("profiles-labels-no-value"))).toBeInTheDocument();
    // The higher-trust source is the one we recommend.
    expect(within(row as HTMLElement).getByText("Suggested")).toBeInTheDocument();
    // Each claim says whose it is, named from the catalog: every choice offered
    // here is one of RoleBand's own sources, since a pin is ours.
    expect(within(row as HTMLElement).getByRole("button", { name: /from SEC EDGAR/ })).toBeInTheDocument();
    expect(within(row as HTMLElement).getByRole("button", { name: new RegExp(`from ${msg("vocab-source-reported")}`) }))
      .toBeInTheDocument();
  });

  it("pins the chosen value and reloads the profile", async () => {
    mock(reviewable());
    setField().mockResolvedValue(companyProfileFieldWriteFixture);
    render(<CompanyProfilePanel slug="reddit" enriching />);

    const choice = await screen.findByRole("button", {
      name: /Set Ticker to RDDT from SEC EDGAR/i,
    });
    fireEvent.click(choice);

    await waitFor(() =>
      expect(setField()).toHaveBeenCalledWith("reddit", "ticker", "RDDT"),
    );
    // Re-fetches so the badge/queue reflect the new state.
    await waitFor(() => expect(api.companyProfile).toHaveBeenCalledTimes(2));
  });

  it("lets the user reject both sources and enter their own value", async () => {
    mock(reviewable());
    setField().mockResolvedValue(companyProfileFieldWriteFixture);
    render(<CompanyProfilePanel slug="reddit" enriching />);

    const input = await screen.findByLabelText(/Custom value for Ticker/i);
    fireEvent.change(input, { target: { value: "RDDT.X" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() =>
      expect(setField()).toHaveBeenCalledWith("reddit", "ticker", "RDDT.X"),
    );
  });

  it("coerces a numeric field instead of pinning a string", async () => {
    mock(
      base({
        slug: "anthropic",
        needs_review: [
          {
            field: "headcount",
            reason: "conflict",
            current: 45,
            suggestion: null,
            candidates: [candidate("reported", "Estimated", 55, 45)],
          },
        ],
      }),
    );
    setField().mockResolvedValue({ ...companyProfileFieldWriteFixture, slug: "anthropic", field: "headcount" });
    render(<CompanyProfilePanel slug="anthropic" enriching />);

    fireEvent.change(await screen.findByLabelText(/Custom value for Headcount/i), {
      target: { value: "2,000" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() =>
      expect(setField()).toHaveBeenCalledWith("anthropic", "headcount", 2000),
    );
  });

  it("surfaces a save failure instead of pretending it worked", async () => {
    mock(reviewable());
    setField().mockRejectedValue(new ApiError("unknown field: ticker", 400, "invalid-input"));
    render(<CompanyProfilePanel slug="reddit" enriching />);

    fireEvent.click(
      await screen.findByRole("button", { name: /Set Ticker to RDDT from SEC EDGAR/i }),
    );
    // A malformed request is a defect: the screen's own sentence, never the server's English.
    expect(await screen.findByText("Couldn't save it. Try again.")).toBeInTheDocument();
    expect(screen.queryByText(/unknown field/)).not.toBeInTheDocument();
  });

  it("keeps the controls behind the mode, but still says the field is flagged", async () => {
    // A dossier opens as something to READ. The row must still carry its
    // reason — hiding the controls must not hide the problem.
    mock(reviewable());
    render(<CompanyProfilePanel slug="reddit" />);

    const row = (await screen.findByText("Sources disagree")).closest(".prof-field")!;
    expect(within(row as HTMLElement).getByText("Ticker")).toBeInTheDocument();
    // No way to change the value until enrichment is asked for.
    expect(screen.queryByLabelText(/Custom value for Ticker/i)).toBeNull();
    expect(
      screen.queryByRole("button", { name: /Set Ticker to RDDT from SEC EDGAR/i }),
    ).toBeNull();
  });

  it("shows no review controls when nothing needs review", async () => {
    mock(base()); // needs_review: []
    render(<CompanyProfilePanel slug="google" />);
    await screen.findByRole("heading", { name: "Google" });
    expect(screen.queryByText("Sources disagree")).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/Custom value for/)).not.toBeInTheDocument();
  });

  it("reports a failed load instead of spinning forever", async () => {
    // A stale API (no /api/company-profiles route yet) 404s. The rejection must
    // reach the screen, or the spinner runs indefinitely.
    mocked.companyProfile.mockRejectedValue(
      new ApiError("company profile not found", 404, "company-profile-not-found"),
    );
    render(<CompanyProfilePanel slug="google" />);

    expect(await screen.findByText("Profile unavailable")).toBeInTheDocument();
    expect(screen.getByText(msg("error-company-profile-not-found"))).toBeInTheDocument();
    expect(screen.queryByText(/company profile not found/)).not.toBeInTheDocument();
    expect(screen.queryByText(msg("profiles-company-profile-panel-loading"))).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument();
  });

  it("retries a failed load on demand", async () => {
    const fetchProfile = mocked.companyProfile;
    fetchProfile.mockRejectedValueOnce(new Error("404 Not Found"));
    fetchProfile.mockResolvedValueOnce(base());
    render(<CompanyProfilePanel slug="google" />);

    fireEvent.click(await screen.findByRole("button", { name: "Retry" }));
    expect(await screen.findByRole("heading", { name: "Google" })).toBeInTheDocument();
  });

  it("notifies the parent so the company list's badge is not left stale", async () => {
    // Resolving a field changes the company's health. Without the callback the
    // list keeps claiming "N need review" and showing a conflict dot after the
    // user fixed it.
    mock(reviewable());
    setField().mockResolvedValue(companyProfileFieldWriteFixture);
    const onResolved = vi.fn();
    render(<CompanyProfilePanel slug="reddit" enriching onResolved={onResolved} />);

    fireEvent.click(
      await screen.findByRole("button", { name: /Set Ticker to RDDT from SEC EDGAR/i }),
    );
    await waitFor(() => expect(onResolved).toHaveBeenCalled());
  });

  it("keeps the profile when the re-read after a save fails, says so, and tries again in place", async () => {
    mocked.companyPrices.mockResolvedValue(emptyPrices());
    mocked.companyProfile
      .mockResolvedValueOnce(reviewable())
      .mockRejectedValueOnce(new Error("offline"))
      .mockResolvedValueOnce(base({ slug: "reddit", display_name: "Reddit" }));
    setField().mockResolvedValue(companyProfileFieldWriteFixture);
    render(<CompanyProfilePanel slug="reddit" enriching />);

    const heading = await screen.findByRole("heading", { name: "Reddit" });
    fireEvent.click(screen.getByRole("button", { name: /Set Ticker to RDDT from SEC EDGAR/i }));

    // The save landed and only the re-read failed: the profile stays, with
    // the failure said above it rather than in its place.
    expect(await screen.findByText(msg("shared-refresh-failed"))).toBeInTheDocument();
    expect(screen.queryByText(msg("profiles-company-profile-panel-profile-unavailable"))).not.toBeInTheDocument();
    expect(heading).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: msg("common-try-again") }));
    await waitFor(() => expect(screen.queryByText("Sources disagree")).not.toBeInTheDocument());
    expect(screen.queryByText(msg("shared-refresh-failed"))).not.toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Reddit" })).toBe(heading);
  });
});

describe("a value set by hand", () => {
  beforeEach(() => vi.clearAllMocks());
  afterEach(() => activate("en"));

  // A pin and its way back are confirmed by a toast: the provider renders it.
  const renderWithToasts = (ui: ReactElement) =>
    rtlRender(<MemoryRouter><ToastProvider>{ui}</ToastProvider></MemoryRouter>);

  const listedUnderReview = () =>
    base({
      slug: "reddit",
      display_name: "Reddit",
      data_health: "missing",
      needs_review: [{ field: "is_public", reason: "missing", current: null, suggestion: null, candidates: [] }],
    });

  const headcountUnderReview = () =>
    base({
      slug: "anthropic",
      display_name: "Anthropic",
      needs_review: [
        { field: "headcount", reason: "conflict", current: 45, suggestion: null, candidates: [candidate("reported", "Estimated", 55, 45)] },
      ],
    });

  const pinnedHeadcount = () =>
    base({ slug: "anthropic", display_name: "Anthropic", fields: { headcount: field(2000, { source: "manual", is_manual: true }) } });

  const toastSaying = async (text: string) => (await screen.findByText(text)).closest("[role='status'], [role='alert']") as HTMLElement;

  it("lets a Spanish reader answer Listed in their own words, and pins the answer they chose", async () => {
    await activate("es");
    mock(listedUnderReview());
    mocked.setCompanyField.mockResolvedValue({ ...companyProfileFieldWriteFixture, field: "is_public" });
    const user = userEvent.setup();
    renderWithToasts(<CompanyProfilePanel slug="reddit" enriching />);

    const answer = await screen.findByRole("combobox", {
      name: msg("profiles-field-review-custom-value-for", { label: msg("profiles-labels-listed") }),
    });
    // The answers are the reader's words, never English or a code to type.
    const offered = within(answer).getAllByRole("option").map((o) => o.textContent);
    expect(offered).toEqual(expect.arrayContaining([msg("profiles-yes-no", { answer: "yes" }), msg("profiles-yes-no", { answer: "no" })]));
    expect(offered).not.toContain("Yes");
    expect(screen.queryByRole("textbox", {
      name: msg("profiles-field-review-custom-value-for", { label: msg("profiles-labels-listed") }),
    })).toBeNull();

    await user.selectOptions(answer, msg("profiles-yes-no", { answer: "yes" }));
    await user.click(screen.getByRole("button", { name: msg("profiles-field-review-save") }));
    await waitFor(() => expect(mocked.setCompanyField).toHaveBeenCalledWith("reddit", "is_public", true));

    // "No" is a pin too, and pins false.
    await user.selectOptions(answer, msg("profiles-yes-no", { answer: "no" }));
    await user.click(screen.getByRole("button", { name: msg("profiles-field-review-save") }));
    await waitFor(() => expect(mocked.setCompanyField).toHaveBeenLastCalledWith("reddit", "is_public", false));
  });

  it("offers the equity vehicles by name and pins the code", async () => {
    mock(base({
      slug: "reddit",
      display_name: "Reddit",
      needs_review: [{ field: "equity_vehicle", reason: "missing", current: null, suggestion: null, candidates: [] }],
    }));
    mocked.setCompanyField.mockResolvedValue({ ...companyProfileFieldWriteFixture, field: "equity_vehicle" });
    const user = userEvent.setup();
    renderWithToasts(<CompanyProfilePanel slug="reddit" enriching />);

    const vehicle = await screen.findByRole("combobox", {
      name: msg("profiles-field-review-custom-value-for", { label: msg("profiles-labels-equity-vehicle") }),
    });
    await user.selectOptions(vehicle, msg("profiles-labels-cash-election"));
    await user.click(screen.getByRole("button", { name: msg("profiles-field-review-save") }));
    await waitFor(() => expect(mocked.setCompanyField).toHaveBeenCalledWith("reddit", "equity_vehicle", "cash_election"));
  });

  it("reads a count the way a Spanish reader writes it, and refuses one it cannot read whole", async () => {
    await activate("es", { region: "ES" });
    mock(headcountUnderReview());
    mocked.setCompanyField.mockResolvedValue({ ...companyProfileFieldWriteFixture, slug: "anthropic", field: "headcount" });
    renderWithToasts(<CompanyProfilePanel slug="anthropic" enriching />);

    const input = await screen.findByRole("textbox", {
      name: msg("profiles-field-review-custom-value-for", { label: msg("profiles-labels-headcount") }),
    });
    const save = () => fireEvent.click(screen.getByRole("button", { name: msg("profiles-field-review-save") }));
    const refusal = msg("profiles-field-review-not-a-whole-number", { example: 1200 });

    // "1,5" is one and a half in Spain: not a count, and never pinned as 15.
    fireEvent.change(input, { target: { value: "1,5" } });
    save();
    expect(await screen.findByRole("alert")).toHaveTextContent(refusal);
    expect(input).toHaveAttribute("aria-invalid", "true");
    // Words around a number are not a number either.
    fireEvent.change(input, { target: { value: "unos 300" } });
    save();
    expect(await screen.findByRole("alert")).toHaveTextContent(refusal);
    expect(mocked.setCompanyField).not.toHaveBeenCalled();

    // "1.000" is one thousand in Spain, not one.
    fireEvent.change(input, { target: { value: "1.000" } });
    expect(screen.queryByRole("alert")).toBeNull();
    save();
    await waitFor(() => expect(mocked.setCompanyField).toHaveBeenCalledWith("anthropic", "headcount", 1000));
    expect(mocked.setCompanyField).toHaveBeenCalledTimes(1);
  });

  it("confirms a pin with a toast whose Undo drops it and restores what the sources say", async () => {
    mock(reviewable());
    mocked.setCompanyField.mockResolvedValue(companyProfileFieldWriteFixture);
    mocked.clearCompanyField.mockResolvedValue(companyProfileFieldWriteFixture);
    const user = userEvent.setup();
    renderWithToasts(<CompanyProfilePanel slug="reddit" enriching />);

    await user.click(await screen.findByRole("button", { name: /Set Ticker to RDDT from SEC EDGAR/i }));
    await waitFor(() => expect(mocked.setCompanyField).toHaveBeenCalledWith("reddit", "ticker", "RDDT"));
    const ticker = msg("profiles-labels-ticker");
    const toast = await toastSaying(msg("profiles-field-review-pinned", { label: ticker, value: "RDDT" }));
    expect(toast).toHaveAttribute("role", "status");
    expect(mocked.clearCompanyField).not.toHaveBeenCalled();

    await user.click(within(toast).getByRole("button", { name: msg("common-undo") }));
    await waitFor(() => expect(mocked.clearCompanyField).toHaveBeenCalledWith("reddit", "ticker"));
    // The profile is read again after the pin and again after its Undo.
    await waitFor(() => expect(mocked.companyProfile).toHaveBeenCalledTimes(3));
    expect(await screen.findByText(msg("profiles-field-unpinned", { label: ticker }))).toBeInTheDocument();
  });

  it("says so when the Undo of a pin does not land", async () => {
    mock(reviewable());
    mocked.setCompanyField.mockResolvedValue(companyProfileFieldWriteFixture);
    mocked.clearCompanyField.mockRejectedValue(new Error("offline"));
    const user = userEvent.setup();
    renderWithToasts(<CompanyProfilePanel slug="reddit" enriching />);

    await user.click(await screen.findByRole("button", { name: /Set Ticker to RDDT from SEC EDGAR/i }));
    const toast = await toastSaying(msg("profiles-field-review-pinned", { label: msg("profiles-labels-ticker"), value: "RDDT" }));
    await user.click(within(toast).getByRole("button", { name: msg("common-undo") }));
    expect(await toastSaying(msg("profiles-field-could-not-undo"))).toHaveAttribute("role", "alert");
    expect(screen.queryByText(msg("profiles-field-unpinned", { label: msg("profiles-labels-ticker") }))).toBeNull();
  });

  it("gives a pinned field, and only in the enrich mode, the way back to its sources, with Undo", async () => {
    const headcount = msg("profiles-labels-headcount");
    const backToSources = () => screen.queryByRole("button", { name: msg("profiles-field-use-sources-for", { label: headcount }) });
    const row = () => screen.getByText(headcount, { selector: ".prof-field-l" }).closest(".prof-field") as HTMLElement;

    // Not on a field nobody pinned, and not while the profile is being read.
    mock(base({ slug: "anthropic", display_name: "Anthropic", fields: { headcount: field(45) } }));
    const first = renderWithToasts(<CompanyProfilePanel slug="anthropic" enriching />);
    await screen.findByRole("heading", { name: "Anthropic" });
    expect(backToSources()).toBeNull();
    first.unmount();
    mock(pinnedHeadcount());
    const reading = renderWithToasts(<CompanyProfilePanel slug="anthropic" />);
    await screen.findByRole("heading", { name: "Anthropic" });
    expect(backToSources()).toBeNull();
    reading.unmount();

    mocked.companyProfile.mockReset();
    mocked.companyProfile
      .mockResolvedValueOnce(pinnedHeadcount())
      .mockResolvedValueOnce(base({ slug: "anthropic", display_name: "Anthropic", fields: { headcount: field(45) } }))
      .mockResolvedValue(pinnedHeadcount());
    mocked.clearCompanyField.mockResolvedValue({ ...companyProfileFieldWriteFixture, slug: "anthropic", field: "headcount" });
    mocked.setCompanyField.mockResolvedValue({ ...companyProfileFieldWriteFixture, slug: "anthropic", field: "headcount" });
    const user = userEvent.setup();
    renderWithToasts(<CompanyProfilePanel slug="anthropic" enriching />);

    await screen.findByRole("heading", { name: "Anthropic" });
    expect(row()).toHaveTextContent(msg("vocab-source-manual"));
    await user.click(await screen.findByRole("button", { name: msg("profiles-field-use-sources-for", { label: headcount }) }));
    await waitFor(() => expect(mocked.clearCompanyField).toHaveBeenCalledWith("anthropic", "headcount"));

    // The source's value is back, and the hand-set one is gone.
    await waitFor(() => expect(row()).toHaveTextContent("45"));
    expect(row()).not.toHaveTextContent(msg("vocab-source-manual"));
    expect(backToSources()).toBeNull();

    // Undo sets the value the reader had pinned, exactly.
    const toast = await toastSaying(msg("profiles-field-unpinned", { label: headcount }));
    await user.click(within(toast).getByRole("button", { name: msg("common-undo") }));
    await waitFor(() => expect(mocked.setCompanyField).toHaveBeenCalledWith("anthropic", "headcount", 2000));
    expect(mocked.setCompanyField).toHaveBeenCalledTimes(1);
  });
});

const summary = (
  slug: string,
  display_name: string,
  over: Partial<CompanyProfileSummary> = {},
): CompanyProfileSummary => ({
  slug,
  display_name,
  logo_url: `https://static.pay.example/${slug}.webp`,
  brand_color: "#33a852",
  is_public: true,
  ticker: null,
  equity_vehicle: "rsu",
  headcount: 100,
  data_health: "ok",
  conflict_fields: [],
  mapped_levels: 3,
  // Outside the dataset by default: one group, so a test about search or
  // selection sees every row without unfolding anything.
  sectors: [],
  in_dataset: false,
  price: null,
  change_pct: null,
  currency: null,
  price_as_of: null,
  ...over,
});

describe("CompanyProfilesView — search + branding", () => {
  beforeEach(() => vi.clearAllMocks());

  const mockList = (items: CompanyProfileSummary[]) => {
    mocked.companyProfiles.mockResolvedValue({
      items,
      sectors: profileSectorOrderFixture,
      attribution: PLUGIN_ATTRIBUTION,
    });
    mocked.companyProfile.mockResolvedValue(base());
    mocked.companyPrices.mockResolvedValue(emptyPrices());
  };

  const LIST = [
    summary("google", "Google", { ticker: "GOOG" }),
    summary("netflix", "Netflix", { ticker: "NFLX" }),
    summary("openai", "OpenAI", { is_public: false, ticker: null }),
  ];

  /* The toolbar count describes the list underneath it, not the whole roster,
     on the Board's two shapes: a query NARROWS, so it earns a fraction; the
     lens is a different list, so it is named and takes no denominator. */
  const FLAGGED = [
    summary("google", "Google", { ticker: "GOOG" }),
    summary("netflix", "Netflix", { ticker: "NFLX", data_health: "stale" }),
    summary("openai", "OpenAI", { is_public: false, ticker: null, data_health: "stale" }),
  ];
  const count = () => document.querySelector(".prof-toolbar .results-count")!.textContent!;

  it("states the search narrowing as a fraction, not the roster's own total", async () => {
    mockList(FLAGGED);
    render(<CompanyProfilesView />);
    await screen.findByRole("button", { name: "Google" });
    expect(count()).toContain("3");
    expect(count()).not.toContain("of");

    fireEvent.change(screen.getByLabelText("Search companies"), { target: { value: "net" } });
    expect(count()).toMatch(/1\s*of\s*3\s*companies/);
  });

  it("counts what needs review among the roles SHOWN, not across the roster", async () => {
    mockList(FLAGGED);
    render(<CompanyProfilesView />);
    await screen.findByRole("button", { name: "Google" });
    expect(count()).toMatch(/2\s*need review/);

    // Narrow to the one healthy company: the roster still holds two flagged
    // profiles, but none of them is on screen to be reviewed.
    fireEvent.change(screen.getByLabelText("Search companies"), { target: { value: "goog" } });
    expect(count()).toContain("all profiles current");
    expect(count()).not.toContain("2");
  });

  /* A disabled review lens says why. The count beside it already does — "all
     profiles current" — so that sentence is the switch's description, and only
     while it holds. */
  it("a disabled review switch is described by the count that says why", async () => {
    mockList([
      summary("google", "Google", { ticker: "GOOG" }),
      summary("netflix", "Netflix", { ticker: "NFLX" }),
    ]);
    render(<CompanyProfilesView />);
    await screen.findByRole("button", { name: "Google" });
    const lens = screen.getByRole("checkbox", { name: "Needs review only" });
    expect(lens).toBeDisabled();
    expect(lens).toHaveAccessibleDescription("all profiles current");
  });

  it("an enabled review switch carries no reason", async () => {
    mockList(FLAGGED);
    render(<CompanyProfilesView />);
    await screen.findByRole("button", { name: "Google" });
    const lens = screen.getByRole("checkbox", { name: "Needs review only" });
    expect(lens).toBeEnabled();
    expect(lens).toHaveAccessibleDescription("");
  });

  it("names the review lens instead of pricing it as a fraction, and offers the way back", async () => {
    mockList(FLAGGED);
    render(<CompanyProfilesView />);
    await screen.findByRole("button", { name: "Google" });

    fireEvent.click(screen.getByLabelText("Needs review only"));
    // A lens is a different list, never "2 of 3".
    expect(count()).not.toContain("of");
    expect(count()).toMatch(/2\s*companies that need review/);

    fireEvent.click(screen.getByRole("button", { name: "Show all" }));
    expect(screen.getByRole("button", { name: "Google" })).toBeInTheDocument();
  });


  it("filters the company list by name as you type", async () => {
    mockList(LIST);
    render(<CompanyProfilesView />);

    await screen.findByRole("button", { name: "Netflix" });
    fireEvent.change(screen.getByLabelText("Search companies"), {
      target: { value: "net" },
    });

    expect(screen.getByRole("button", { name: "Netflix" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Google" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "OpenAI" })).not.toBeInTheDocument();
  });

  it("also matches on ticker — you may think 'NFLX', not 'Netflix'", async () => {
    mockList(LIST);
    render(<CompanyProfilesView />);

    await screen.findByRole("button", { name: "Netflix" });
    fireEvent.change(screen.getByLabelText("Search companies"), {
      target: { value: "nflx" },
    });
    expect(screen.getByRole("button", { name: "Netflix" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Google" })).not.toBeInTheDocument();
  });

  it("says so when nothing matches, rather than showing an empty list", async () => {
    mockList(LIST);
    render(<CompanyProfilesView />);

    await screen.findByRole("button", { name: "Google" });
    fireEvent.change(screen.getByLabelText("Search companies"), {
      target: { value: "zzzz" },
    });
    expect(screen.getByText(/No company matches/)).toBeInTheDocument();
  });

  /* The two empty states. The rail narrows on the query AND the review
   * switch, so a sentence chosen on the query alone (`q ? … : …`) fails both. */
  describe("empty states name the reason and offer the way out", () => {
    it("does not deny a company in the roster because Needs review only is on", async () => {
      mockList([
        summary("google", "Google", { ticker: "GOOG" }),
        summary("netflix", "Netflix", { ticker: "NFLX", data_health: "conflict" }),
      ]);
      render(<CompanyProfilesView />);

      await screen.findByRole("button", { name: "Google" });
      fireEvent.click(screen.getByRole("checkbox", { name: "Needs review only" }));
      fireEvent.change(screen.getByLabelText("Search companies"), {
        target: { value: "google" },
      });

      // Google is right there in the roster, healthy: the state must not
      // deny it.
      expect(screen.queryByText(/^No company matches/)).not.toBeInTheDocument();
      expect(screen.getByText("No flagged company matches “google”.")).toBeInTheDocument();

      fireEvent.click(screen.getByRole("button", { name: "Show all companies" }));
      expect(screen.getByRole("button", { name: "Google" })).toBeInTheDocument();
    });

    it("blames only the search when the review switch is off", async () => {
      mockList(LIST);
      render(<CompanyProfilesView />);

      await screen.findByRole("button", { name: "Google" });
      fireEvent.change(screen.getByLabelText("Search companies"), {
        target: { value: "zzzz" },
      });

      expect(screen.getByText("No company matches “zzzz”.")).toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "Show all companies" })).not.toBeInTheDocument();
      fireEvent.click(screen.getByRole("button", { name: "Clear the search" }));
      expect(screen.getByRole("button", { name: "Google" })).toBeInTheDocument();
    });

    it("says the one true thing when nothing is tracked, and points at the fix", async () => {
      // An empty roster means exactly one thing: `ensure_company_profiles`
      // materializes a profile per TRACKED company on API startup.
      mockList([]);
      render(
        <>
          <CompanyProfilesView />
          <LocationProbe />
        </>,
      );

      expect(
        await screen.findByText("You don't follow any company yet"),
      ).toBeInTheDocument();

      // One state, one claim: no rail sentence, no pane sentence, no toolbar.
      expect(screen.queryByText(/Nothing needs review/)).not.toBeInTheDocument();
      expect(screen.queryByText(/No company profiles yet/)).not.toBeInTheDocument();
      expect(screen.queryByLabelText("Search companies")).not.toBeInTheDocument();

      fireEvent.click(screen.getByRole("link", { name: "Settings › Companies" }));
      expect(screen.getByTestId("location")).toHaveTextContent("/settings/companies");
    });
  });

  it("shows the company mark in the profile hero", async () => {
    mockList(LIST);
    const { container } = render(<CompanyProfilesView />);

    await screen.findByRole("heading", { name: "Google" });
    // Decorative (aria-hidden), so query it structurally. Google ships in the
    // bundled set, so the hero must render that mark and NOT fetch the remote logo.
    const hero = container.querySelector(".prof-identity .company-logo .ui-company-icon svg path");
    expect(hero).toHaveAttribute("d", BRAND_ICONS.google.path);
    expect(container.querySelector(".prof-identity .company-logo img")).toBeNull();
  });
});

describe("CompanyProfilesView: a resolved field re-reads in place", () => {
  beforeEach(() => vi.clearAllMocks());

  const roster = (data_health: CompanyProfileSummary["data_health"]) => ({
    items: [summary("reddit", "Reddit", { data_health })],
    sectors: profileSectorOrderFixture,
    attribution: PLUGIN_ATTRIBUTION,
  });

  it("keeps the toolbar, the list and the profile heading mounted while both re-read", async () => {
    const profileAgain = deferred<CompanyProfileDetail>();
    const rosterAgain = deferred<ReturnType<typeof roster>>();
    mocked.companyPrices.mockResolvedValue(emptyPrices());
    mocked.companyProfile.mockResolvedValueOnce(reviewable()).mockReturnValueOnce(profileAgain.promise);
    mocked.companyProfiles.mockResolvedValueOnce(roster("conflict")).mockReturnValueOnce(rosterAgain.promise);
    mocked.setCompanyField.mockResolvedValue(companyProfileFieldWriteFixture);
    render(<CompanyProfilesView />);

    const heading = await screen.findByRole("heading", { name: "Reddit" });
    const search = screen.getByRole("searchbox", { name: msg("profiles-company-profiles-view-search-companies") });
    fireEvent.click(screen.getByRole("button", { name: msg("profiles-company-profiles-view-enrich-fields") }));
    fireEvent.click(await screen.findByRole("button", { name: /Set Ticker to RDDT from SEC EDGAR/i }));

    // Both re-reads are in flight and neither has answered.
    await waitFor(() => expect(mocked.companyProfile).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(mocked.companyProfiles).toHaveBeenCalledTimes(2));
    expect(heading).toBeInTheDocument();
    expect(search).toBeInTheDocument();
    expect(screen.queryByText(msg("profiles-company-profiles-view-loading-companies"))).not.toBeInTheDocument();
    expect(screen.queryByText(msg("profiles-company-profile-panel-loading"))).not.toBeInTheDocument();

    await act(async () => {
      profileAgain.resolve(base({ slug: "reddit", display_name: "Reddit" }));
      rosterAgain.resolve(roster("ok"));
    });

    // The answers land in the nodes already on screen: the field is settled,
    // the toolbar's count has moved, and the heading is the one from before.
    await waitFor(() => expect(screen.queryByText("Sources disagree")).not.toBeInTheDocument());
    expect(await screen.findByText(msg("profiles-company-profiles-view-all-profiles-current"))).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Reddit" })).toBe(heading);
    expect(screen.getByRole("searchbox", { name: msg("profiles-company-profiles-view-search-companies") })).toBe(search);
  });
});

describe("CompanyLogo fallback", () => {
  beforeEach(() => vi.clearAllMocks());

  // Mark -> remote logo -> monogram. The remote rung is only reachable for a
  // company the bundled set does not carry, which is why these use Citadel
  // (a quant firm, absent from the set) rather than a household tech brand.
  it("prefers the bundled mark over the remote logo, sparing the network hop", async () => {
    mock(base({ slug: "netflix", display_name: "Netflix", logo_url: "https://static.pay.example/x.png" }));
    const { container } = render(<CompanyProfilePanel slug="netflix" />);

    await screen.findByRole("heading", { name: "Netflix" });
    expect(container.querySelector(".company-logo svg path")).toHaveAttribute(
      "d",
      BRAND_ICONS.netflix.path,
    );
    expect(container.querySelector(".company-logo img")).toBeNull();
  });

  it("uses the remote logo for a company the bundled set does not carry", async () => {
    mock(base({ slug: "citadel", display_name: "Citadel", logo_url: "https://static.pay.example/c.png" }));
    const { container } = render(<CompanyProfilePanel slug="citadel" />);

    await screen.findByRole("heading", { name: "Citadel" });
    expect(container.querySelector(".company-logo img")).toHaveAttribute(
      "src",
      "https://static.pay.example/c.png",
    );
  });

  it("falls back to a brand-coloured monogram when the remote logo 404s", async () => {
    // These are third-party URLs; some will rot. A broken-image icon would be
    // worse than no image, so the profile must still read as the company.
    mock(base({ slug: "citadel", display_name: "Citadel", logo_url: "https://dead.example/x.png" }));
    const { container } = render(<CompanyProfilePanel slug="citadel" />);

    await screen.findByRole("heading", { name: "Citadel" });
    fireEvent.error(container.querySelector(".company-logo img")!);

    expect(container.querySelector(".ui-company-icon.is-monogram [data-letter]")).toHaveAttribute("data-letter", "C");
    expect(container.querySelector(".company-logo img")).toBeNull();
  });

  it("renders a monogram when there is no logo and no bundled mark", async () => {
    mock(base({ slug: "optiver", display_name: "Optiver", logo_url: null, brand_color: null }));
    const { container } = render(<CompanyProfilePanel slug="optiver" />);
    await screen.findByRole("heading", { name: "Optiver" });
    expect(container.querySelector(".ui-company-icon.is-monogram [data-letter]")).toHaveAttribute("data-letter", "O");
  });
});

describe("CompanyProfilesView — dataset sections and sector folds", () => {
  beforeEach(() => vi.clearAllMocks());

  const mockList = (items: CompanyProfileSummary[]) => {
    mocked.companyProfiles.mockResolvedValue({
      items,
      sectors: profileSectorOrderFixture,
      attribution: PLUGIN_ATTRIBUTION,
    });
    mocked.companyProfile.mockResolvedValue(base());
    mocked.companyPrices.mockResolvedValue(emptyPrices());
  };

  const inData = (slug: string, name: string, sectors: string[], over: Partial<CompanyProfileSummary> = {}) =>
    summary(slug, name, { in_dataset: true, sectors, ...over });

  // Sent in slug order, as the API does: the screen decides every order.
  const ROSTER = [
    summary("10xteam", "10xteam"),
    summary("acme-url", "Acme"),
    inData("amazon", "Amazon", ["faang"], { ticker: "AMZN" }),
    inData("anthropic", "Anthropic", ["ai"], { is_public: false }),
    inData("discord", "Discord", ["gaming", "consumer"], { is_public: false }),
    inData("flexport", "Flexport", [], { is_public: false }),
    inData("google", "Google", ["faang"], { ticker: "GOOG" }),
    inData("microsoft", "Microsoft", ["technology", "gaming"], { ticker: "MSFT" }),
    inData("openai", "OpenAI", ["ai"], { is_public: false, data_health: "stale" }),
  ];

  const disclosures = () =>
    screen.getAllByRole("button", { expanded: false }).concat(screen.getAllByRole("button", { expanded: true }));
  const fold = (name: string) => screen.getByRole("button", { name, expanded: false });
  const unfolded = (name: string) => screen.getByRole("button", { name, expanded: true });
  const group = (name: string) => screen.getByRole("region", { name });

  it("leads with the dataset, folded by sector in Settings' order, then other companies", async () => {
    mockList(ROSTER);
    render(<CompanyProfilesView />);
    await screen.findByRole("button", { name: "Amazon" });

    const dataset = screen.getByRole("region", { name: msg("profiles-roster-dataset") });
    // Distinct companies: Discord and Microsoft sit in two sectors and count once.
    // The section is the page's second level: the outline steps h1, h2, h3.
    expect(within(dataset).getByRole("heading", { level: 2 })).toHaveTextContent(/7$/);

    // Every fold in reading order: FAANG first, then Settings' sector order,
    // then the researched company in no sector, then everyone else.
    const heads = [...document.querySelectorAll(".prof-group-disclose")].map((el) => el.textContent);
    expect(heads).toEqual([
      msg("vocab-sector-faang"),
      msg("vocab-sector-ai"),
      msg("vocab-sector-technology"),
      msg("vocab-sector-gaming"),
      msg("vocab-sector-consumer"),
      msg("profiles-roster-no-sector"),
      msg("companies-model-other-companies"),
    ]);
    expect(disclosures()).toHaveLength(7);
    // A sector with no followed company draws no head.
    expect(screen.queryByRole("button", { name: msg("vocab-sector-quant") })).not.toBeInTheDocument();
    // Each fold counts its own rows.
    expect(within(group(msg("vocab-sector-gaming"))).getByText("2")).toBeInTheDocument();
    expect(within(group(msg("companies-model-other-companies"))).getByText("2")).toBeInTheDocument();
  });

  it("rests folded except the group of the company on screen, whose rows run A to Z", async () => {
    mockList(ROSTER);
    render(<CompanyProfilesView />);
    await waitFor(() => expect(api.companyProfile).toHaveBeenCalledWith("amazon"));

    // Amazon is the first row the list draws, so FAANG is open and nothing else is.
    expect(unfolded(msg("vocab-sector-faang"))).toBeInTheDocument();
    expect(screen.getAllByRole("button", { expanded: true })).toHaveLength(1);
    const faang = within(screen.getByRole("list", { name: msg("vocab-sector-faang") }));
    expect(faang.getAllByRole("button").map((b) => b.textContent)).toEqual(["AmazonAMZN", "GoogleGOOG"]);
    // A folded group renders no rows at all.
    expect(screen.queryByRole("button", { name: "Anthropic" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "10xteam" })).not.toBeInTheDocument();
  });

  it("unfolds and folds a group from its head, and a company in two sectors is a row in each", async () => {
    mockList(ROSTER);
    render(<CompanyProfilesView />);
    await screen.findByRole("button", { name: "Amazon" });

    fireEvent.click(fold(msg("vocab-sector-technology")));
    fireEvent.click(fold(msg("vocab-sector-gaming")));
    expect(within(group(msg("vocab-sector-technology"))).getByRole("button", { name: "Microsoft" })).toBeInTheDocument();
    expect(within(group(msg("vocab-sector-gaming"))).getByRole("button", { name: "Microsoft" })).toBeInTheDocument();

    fireEvent.click(unfolded(msg("vocab-sector-gaming")));
    expect(within(group(msg("vocab-sector-gaming"))).queryByRole("button", { name: "Discord" })).not.toBeInTheDocument();
    // Folding the group of the company on screen keeps it folded.
    fireEvent.click(unfolded(msg("vocab-sector-faang")));
    expect(screen.queryByRole("button", { name: "Amazon" })).not.toBeInTheDocument();
  });

  it("selecting a company keeps the reader's folds", async () => {
    mockList(ROSTER);
    rtlRender(
      <MemoryRouter initialEntries={["/company"]}>
        <Routes>
          <Route path="/company" element={<CompanyProfilesView />} />
          <Route path="/company/:slug" element={<CompanyProfilesView />} />
        </Routes>
      </MemoryRouter>,
    );
    await screen.findByRole("button", { name: "Amazon" });
    fireEvent.click(fold(msg("companies-model-other-companies")));
    fireEvent.click(screen.getByRole("button", { name: "10xteam" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "10xteam" })).toHaveAttribute("aria-current", "true"));
    expect(unfolded(msg("vocab-sector-faang"))).toBeInTheDocument();
    expect(unfolded(msg("companies-model-other-companies"))).toBeInTheDocument();
  });

  it("a search opens every group with a match and draws no head over nothing", async () => {
    mockList(ROSTER);
    render(<CompanyProfilesView />);
    await screen.findByRole("button", { name: "Amazon" });

    // Discord is in Gaming and Consumer, both folded at rest.
    fireEvent.change(screen.getByLabelText("Search companies"), { target: { value: "disc" } });
    expect(within(group(msg("vocab-sector-gaming"))).getByRole("button", { name: "Discord" })).toBeInTheDocument();
    expect(within(group(msg("vocab-sector-consumer"))).getByRole("button", { name: "Discord" })).toBeInTheDocument();
    // Gaming draws its one match, not Microsoft beside it.
    expect(within(group(msg("vocab-sector-gaming"))).queryByRole("button", { name: "Microsoft" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: msg("vocab-sector-faang") })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: msg("companies-model-other-companies") })).not.toBeInTheDocument();

    // A fold made during the search lasts as long as that search.
    fireEvent.click(unfolded(msg("vocab-sector-consumer")));
    expect(fold(msg("vocab-sector-consumer"))).toBeInTheDocument();

    // Clearing it returns the folds to where the reader left them.
    fireEvent.change(screen.getByLabelText("Search companies"), { target: { value: "" } });
    expect(screen.getAllByRole("button", { expanded: true }).map((b) => b.textContent)).toEqual([
      msg("vocab-sector-faang"),
    ]);
  });

  it("the review lens opens the groups holding a flagged company", async () => {
    mockList(ROSTER);
    render(<CompanyProfilesView />);
    await screen.findByRole("button", { name: "Amazon" });
    fireEvent.click(screen.getByRole("checkbox", { name: "Needs review only" }));
    expect(within(group(msg("vocab-sector-ai"))).getByRole("button", { name: /OpenAI/ })).toBeInTheDocument();
    expect(screen.getAllByRole("button", { expanded: true })).toHaveLength(1);
  });

  it("without the dataset, the list is the one group of other companies", async () => {
    mockList([summary("10xteam", "10xteam"), summary("acme-url", "Acme")]);
    render(<CompanyProfilesView />);
    await screen.findByRole("button", { name: "10xteam" });
    expect(screen.queryByRole("region", { name: msg("profiles-roster-dataset") })).not.toBeInTheDocument();
    expect(unfolded(msg("companies-model-other-companies"))).toBeInTheDocument();
  });
});

describe("CompanyProfilesView — URL-driven selection", () => {
  beforeEach(() => vi.clearAllMocks());

  const mockList = (items: CompanyProfileSummary[], detail?: CompanyProfileDetail) => {
    mocked.companyProfiles.mockResolvedValue({
      items,
      sectors: profileSectorOrderFixture,
      attribution: "x",
    });
    mocked.companyProfile.mockResolvedValue(
      detail ?? base(),
    );
    mocked.companyPrices.mockResolvedValue(emptyPrices());
  };

  // Selection is a path segment (`/company/:slug`), so the view must be mounted
  // under both the bare and the parametrized route.
  const renderRouted = (route: string) =>
    rtlRender(
      <MemoryRouter initialEntries={[route]}>
        <Routes>
          <Route path="/company" element={<CompanyProfilesView />} />
          <Route path="/company/:slug" element={<CompanyProfilesView />} />
        </Routes>
        <LocationProbe />
      </MemoryRouter>,
    );

  const LIST = [
    summary("google", "Google", { ticker: "GOOG" }),
    summary("netflix", "Netflix", { ticker: "NFLX" }),
  ];

  it("preselects the company named in /company/:slug (deep link from a job chip)", async () => {
    mockList(LIST, base({ slug: "netflix", display_name: "Netflix" }));
    renderRouted("/company/netflix");

    // The profile panel for the deep-linked company loads, not the first in the list.
    await waitFor(() =>
      expect(api.companyProfile).toHaveBeenCalledWith("netflix"),
    );
    const nav = screen.getByRole("button", { name: "Netflix" });
    expect(nav).toHaveAttribute("aria-current", "true");
  });

  it("a deep link unfolds the group holding the company, and only that one", async () => {
    mockList(
      [
        summary("amazon", "Amazon", { in_dataset: true, sectors: ["faang"] }),
        summary("stripe", "Stripe", { in_dataset: true, sectors: ["fintech"] }),
        summary("10xteam", "10xteam"),
      ],
      base({ slug: "stripe", display_name: "Stripe" }),
    );
    renderRouted("/company/stripe");
    const row = await screen.findByRole("button", { name: "Stripe" });
    expect(row).toHaveAttribute("aria-current", "true");
    expect(screen.getAllByRole("button", { expanded: true }).map((b) => b.textContent)).toEqual([
      msg("vocab-sector-fintech"),
    ]);
    expect(screen.queryByRole("button", { name: "Amazon" })).not.toBeInTheDocument();
  });

  it("falls back to the first company when the slug is unknown", async () => {
    mockList(LIST);
    renderRouted("/company/ghostco");
    await waitFor(() => expect(api.companyProfile).toHaveBeenCalledWith("google"));
  });

  it("opens on the first company the list DRAWS, not the first the API sent", async () => {
    // The API sends one alphabetical run; the list renders the dataset before
    // other companies. Sent Affirm first, landing must still select the
    // company sitting at the top of the rendered list.
    mockList([
      summary("affirm", "Affirm", { is_public: false, ticker: null }),
      summary("amazon", "Amazon", { ticker: "AMZN", in_dataset: true, sectors: ["faang"] }),
    ]);
    renderRouted("/company");
    await waitFor(() => expect(api.companyProfile).toHaveBeenCalledWith("amazon"));
    expect(api.companyProfile).not.toHaveBeenCalledWith("affirm");
  });

  it("writes the picked company into the URL path so the profile is shareable", async () => {
    mockList(LIST);
    renderRouted("/company");
    fireEvent.click(await screen.findByRole("button", { name: "Netflix" }));
    await waitFor(() =>
      expect(screen.getByTestId("location")).toHaveTextContent("/company/netflix"),
    );
  });

  it("redirects a ?slug= query link to the path form", async () => {
    mockList(LIST, base({ slug: "netflix", display_name: "Netflix" }));
    renderRouted("/company?slug=netflix");

    // A link in the query form still resolves: the query is rewritten to the path form...
    await waitFor(() =>
      expect(screen.getByTestId("location")).toHaveTextContent("/company/netflix"),
    );
    expect(screen.getByTestId("location")).not.toHaveTextContent("?slug=");
    // ...and the deep-linked company loads.
    await waitFor(() => expect(api.companyProfile).toHaveBeenCalledWith("netflix"));
  });
});

describe("CompanyProfilePanel — prices + jobs cross-link", () => {
  beforeEach(() => vi.clearAllMocks());

  const PRICED = () => emptyPrices({
        latest: {
          ticker: "GOOG",
          price: 213.95,
          currency: "USD",
          change_abs: -1.03,
          change_pct: -0.48,
          as_of: "2026-07-13",
        },
        bars: [
          { date: "2026-07-10", open: 210, high: 214, low: 209, close: 200, volume: 1 },
          { date: "2026-07-13", open: 212, high: 215, low: 211, close: 213.95, volume: 1 },
        ],
        attribution: "Price data: Tiingo",
        feed_configured: true,
      });

  it("reads as one instrument: ticker by the title, last close, the day's move, the day it closed, the range move", async () => {
    mock(base({ slug: "google", display_name: "Google" }));
    mocked.companyPrices.mockResolvedValue(PRICED());
    render(<CompanyProfilePanel slug="google" />);

    const panel = await screen.findByTestId("stock-panel");
    expect(within(panel).getByRole("heading", { name: "Stock price" })).toBeInTheDocument();
    expect(await within(panel).findByText("$213.95")).toBeInTheDocument();
    expect(within(panel).getByTestId("stock-ticker")).toHaveTextContent(/^GOOG$/);
    // The day's move in money and percent, coloured by its own sign.
    const day = within(panel).getByTestId("stock-day-move");
    expect(day).toHaveTextContent("-$1.03 (-0.48%)");
    expect(day).toHaveClass("co-change-down");
    expect(within(panel).getByText(msg("profiles-stock-price-panel-close", { date: calendarDay("2026-07-13") }))).toBeInTheDocument();
    // The window's move is what the line's colour says: up here, while the day was down.
    const window = within(panel).getByTestId("stock-range-move");
    expect(window).toHaveTextContent(msg("profiles-stock-price-panel-range-move", { move: "+7.0%", range: "m3" }));
    expect(window).toHaveClass("co-change-up");
    expect(within(panel).getByText("Price data: Tiingo")).toBeInTheDocument();
    await waitFor(() => expect(api.companyPrices).toHaveBeenCalledWith("google", "3m"));
  });

  it("hides the range control and the credit when there are no prices to choose between", async () => {
    mock(base());
    render(<CompanyProfilePanel slug="google" />);
    await screen.findByTestId("price-empty");
    expect(screen.queryByRole("button", { name: "3M" })).not.toBeInTheDocument();
    expect(screen.queryByText(/Price data/)).not.toBeInTheDocument();
    expect(screen.getByText(msg("profiles-stock-price-panel-empty-title"))).toBeInTheDocument();
  });

  it("does not show a stock panel for a private company", async () => {
    mock(
      base({
        slug: "openai",
        display_name: "OpenAI",
        fields: { is_public: field(false), equity_vehicle: field("options") },
      }),
    );
    render(<CompanyProfilePanel slug="openai" />);
    await screen.findByRole("heading", { name: "OpenAI" });
    expect(screen.queryByRole("heading", { name: "Stock price" })).not.toBeInTheDocument();
    expect(api.companyPrices).not.toHaveBeenCalled();
  });

  it("re-requests history when the range toggle changes, 6M included", async () => {
    mock(base());
    mocked.companyPrices.mockResolvedValue(PRICED());
    render(<CompanyProfilePanel slug="google" />);
    await screen.findByTestId("stock-quote");

    fireEvent.click(screen.getByRole("button", { name: "6M" }));
    await waitFor(() => expect(api.companyPrices).toHaveBeenCalledWith("google", "6m"));
    fireEvent.click(screen.getByRole("button", { name: "1Y" }));
    await waitFor(() => expect(api.companyPrices).toHaveBeenCalledWith("google", "1y"));
  });

  it("links to the board filtered to this company's open roles", async () => {
    mock(base({ slug: "google", display_name: "Google", open_roles: 7 }));
    render(
      <>
        <CompanyProfilePanel slug="google" />
        <LocationProbe />
      </>,
    );
    const pill = await screen.findByRole("button", { name: /See 7 open roles at Google/i });
    expect(pill).toHaveAttribute("title", "See open roles");
    fireEvent.click(pill);
    expect(screen.getByTestId("location")).toHaveTextContent("/?company=google");
  });

  it("shows a non-interactive empty pill when the company has no open roles", async () => {
    mock(base({ open_roles: 0 }));
    render(<CompanyProfilePanel slug="google" />);
    await screen.findByRole("heading", { name: "Google" });
    // No clickable jobs link when there are no positions to link to...
    expect(
      screen.queryByRole("button", { name: /open role/i }),
    ).not.toBeInTheDocument();
    // ...just an inert marker.
    expect(screen.getByText("0 open")).toBeInTheDocument();
  });

  it("says an unfollowed company's roles are not on the Board, instead of 0 open", async () => {
    // The Board shows only followed companies, so the jump would
    // open on nothing; the pill says why there is nothing to jump to.
    mock(base({ open_roles: 0, unfollowed: true }));
    render(<CompanyProfilePanel slug="google" />);
    await screen.findByRole("heading", { name: "Google" });
    const pill = screen.getByText("Not on your radar");
    expect(pill).toHaveAttribute("title", "Not on your radar. Follow Google to see its roles.");
    expect(screen.queryByText("0 open")).toBeNull();
    expect(screen.queryByRole("button", { name: /open role/i })).not.toBeInTheDocument();
  });

  it("lists offices under their country, with open-role counts and the HQ tag", async () => {
    mock(
      base({
        locations: [
          {
            city: "Mountain View, CA",
            open_count: 12,
            groups: ["silicon_valley", "united_states"],
            is_hq: true,
            country: "united_states",
          },
          {
            city: "London, UK",
            open_count: 3,
            groups: ["london", "uk"],
            is_hq: false,
            country: "uk",
          },
        ],
      }),
    );
    render(<CompanyProfilePanel slug="google" />);

    await screen.findByRole("heading", { name: "Offices & open roles" });
    // The panel counts countries; cities are what the sections hold.
    expect(screen.getByText("2 countries")).toBeInTheDocument();

    // Busiest country first, each office under its own flag heading.
    const us = screen.getByRole("list", { name: "Offices in United States" });
    const usRows = within(us).getAllByRole("listitem");
    expect(usRows).toHaveLength(1);
    expect(usRows[0]).toHaveTextContent("Mountain View, CA");
    expect(usRows[0]).toHaveTextContent("12 open");
    expect(within(usRows[0]).getByText("HQ")).toBeInTheDocument();

    const uk = screen.getByRole("list", { name: "Offices in UK" });
    const ukRows = within(uk).getAllByRole("listitem");
    expect(ukRows[0]).toHaveTextContent("London, UK");
    expect(within(ukRows[0]).queryByText("HQ")).not.toBeInTheDocument();
  });

  it("hides the offices panel when no postings carry a resolvable city", async () => {
    mock(base({ locations: [] }));
    render(<CompanyProfilePanel slug="google" />);
    await screen.findByRole("heading", { name: "Google" });
    expect(
      screen.queryByRole("heading", { name: "Offices & open roles" }),
    ).not.toBeInTheDocument();
  });
});

describe("CompanyProfilesView: the page heading and a worded error in every state", () => {
  it("leads a failed load with the page heading and the reader's sentence, never the transport text", async () => {
    mocked.companyProfiles.mockRejectedValue(new ApiError("connect ECONNREFUSED 127.0.0.1:8010", 0, "offline"));
    render(<CompanyProfilesView />);
    const alert = await screen.findByRole("alert");
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent(msg("profiles-company-profiles-view-companies"));
    expect(alert).toHaveTextContent(msg("error-offline"));
    expect(alert).not.toHaveTextContent("ECONNREFUSED");
    expect(within(alert).getByRole("heading", { level: 2 })).toBeInTheDocument();
  });

  it("leads the loading state with the page heading and a catalog line", () => {
    mocked.companyProfiles.mockReturnValue(new Promise(() => {}));
    render(<CompanyProfilesView />);
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent(msg("profiles-company-profiles-view-companies"));
    expect(screen.getByRole("status")).toHaveTextContent(msg("profiles-company-profiles-view-loading-companies"));
  });
});
