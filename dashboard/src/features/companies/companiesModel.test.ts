import { describe, expect, it } from "vitest";
import type { CompanyDiscoveryCompany, CompanyDiscoveryState, SyncTarget } from "../../api";
import {
  buildAlerts,
  buildOrderIndex,
  aboutCount,
  hoursSince,
  shortAge,
  buildSectorGroups,
  DIRECTORY_SLUG,
  directoryHitCompany,
  enabledSet,
  failedSources,
  followEstimate,
  isConnectable,
  openRolesLookup,
  selectionChange,
  otherCompanies,
  registerEmptyReasons,
  registerVisibility,
  sectorNameMap,
  trackedSummary,
  UNSORTED_SLUG,
  type RegisterFilters,
} from "./companiesModel";

/* The register's arithmetic, without a provider.
 *
 * Every question below is asked of pure functions, with no rendered screen.
 * The one that matters most is the first: a company may sit in several
 * sectors, so it draws a row in each — and every TOTAL must still come from the
 * flat company array. Summing sections double-counts exactly those companies,
 * which is invisible on a screenshot and wrong on a ledger.
 */

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

const sector = (slug: string, display: string) => ({
  slug,
  display,
  description: `${display} companies`,
  company_count: 1,
  ready_count: 0,
  selected_count: 0,
});

/** Meta sits in two sectors; Stripe belongs to none and lands in "Your additions". */
const STATE: CompanyDiscoveryState = {
  sectors: [sector("ai", "AI"), sector("technology", "Technology")],
  companies: [
    company({ slug: "meta", display: "Meta", sectors: ["ai", "technology"], connector_state: "live", enabled: true }),
    company({ slug: "openai", display: "OpenAI", sectors: ["ai"], connector_state: "live", enabled: true }),
    company({ slug: "planned-co", display: "Planned Co", sectors: ["ai"], connector_state: "planned" }),
    company({ slug: "stripe", display: "Stripe", sectors: [], connector_state: "ready", enabled: true }),
  ],
};

const FILTERS: RegisterFilters = { query: "", trackedOnly: false, showPlanned: true };
const NAMES = sectorNameMap(STATE);
const CHOSEN = enabledSet(STATE);

const groups = (over: Partial<RegisterFilters> = {}, chosen: ReadonlySet<string> = CHOSEN) => {
  const filters = { ...FILTERS, ...over };
  return buildSectorGroups({
    state: STATE,
    chosen,
    filters,
    sectorNames: NAMES,
    orderIndex: buildOrderIndex(STATE, chosen, null),
    // planned-co carries a count on purpose: if a sector folded in members
    // it does not track, this 5 would show up in the total below.
    openRoles: openRolesLookup({ counts: { meta: 4, openai: 6, stripe: 1, "planned-co": 5 } }),
    countsReady: true,
  });
};

const bySlug = (over: Partial<RegisterFilters> = {}) =>
  Object.fromEntries(groups(over).map((group) => [group.slug, group]));

// --------------------------------------------------------------------------- //
// A company in two sectors
// --------------------------------------------------------------------------- //

describe("a company in more than one sector", () => {
  it("draws a row in each of them", () => {
    const sectors = bySlug();
    expect(sectors.ai.rows.map((c) => c.slug)).toContain("meta");
    expect(sectors.technology.rows.map((c) => c.slug)).toContain("meta");
  });

  it("is counted once by every total, which is why totals read the flat array", () => {
    const sectors = bySlug();
    const summed = Object.values(sectors).reduce((total, group) => total + group.trackedCount, 0);
    const tracked = STATE.companies.filter((c) => CHOSEN.has(c.slug));

    expect(summed).toBe(4); // meta twice, openai, stripe — the wrong answer
    expect(trackedSummary({ tracked, openRoles: openRolesLookup(null), countsReady: false })
      .trackedTotal).toBe(3);
  });

  it("lands in 'Your additions' when it belongs to no sector at all", () => {
    const sectors = bySlug();
    expect(sectors[UNSORTED_SLUG].rows.map((c) => c.slug)).toEqual(["stripe"]);
    expect(sectors.ai.rows.map((c) => c.slug)).not.toContain("stripe");
  });
});

// --------------------------------------------------------------------------- //
// The filters
// --------------------------------------------------------------------------- //

describe("the register's three filters", () => {
  it("withholds planned rows and says how many it is withholding", () => {
    const ai = bySlug({ showPlanned: false }).ai;
    expect(ai.rows.map((c) => c.slug)).toEqual(["meta", "openai"]);
    expect(ai.hiddenPlanned).toBe(1);
  });

  it("lets a search override the planned switch, or a sector would miscount itself", () => {
    // "3 match" over two drawn rows is the defect this rule exists to prevent.
    const ai = bySlug({ showPlanned: false, query: "planned" }).ai;
    expect(ai.rows.map((c) => c.slug)).toEqual(["planned-co"]);
    expect(ai.hiddenPlanned).toBe(0);
  });

  it("matches a search against display name, aliases and sector names", () => {
    const withAlias = {
      ...STATE,
      companies: [company({ slug: "acme", display: "Acme", aliases: ["Initech"], connector_state: "live" })],
    };
    const visible = (query: string) =>
      withAlias.companies.filter(
        registerVisibility({ ...FILTERS, query }, new Set(), sectorNameMap(withAlias)).visible,
      ).length;

    expect(visible("initech")).toBe(1);
    expect(visible("Technology")).toBe(1);
    expect(visible("nothing")).toBe(0);
  });

  it("narrows to tracked companies without hiding their sectors", () => {
    const sectors = bySlug({ trackedOnly: true });
    expect(sectors.ai.rows.map((c) => c.slug)).toEqual(["meta", "openai"]);
    expect(sectors.ai.members).toHaveLength(3);
  });

  it("counts open roles for tracked members only, and not at all before the counts land", () => {
    const sectors = bySlug();
    expect(sectors.ai.openRoles).toBe(10); // meta 4 + openai 6; planned-co's 5 is not ours to count

    const pending = buildSectorGroups({
      state: STATE,
      chosen: CHOSEN,
      filters: FILTERS,
      sectorNames: NAMES,
      orderIndex: new Map(),
      openRoles: openRolesLookup(null),
      countsReady: false,
    });
    expect(pending[0].openRoles).toBeNull();
  });

  it("offers select-all over the rows on screen, never the whole sector", () => {
    const parked = {
      ...STATE,
      companies: [
        ...STATE.companies,
        company({ slug: "parked-co", display: "Parked Co", sectors: ["ai"], connector_state: "parked", selectable: false }),
      ],
    };
    const [ai] = buildSectorGroups({
      state: parked,
      chosen: CHOSEN,
      filters: { ...FILTERS, query: "planned" },
      sectorNames: NAMES,
      orderIndex: new Map(),
      openRoles: openRolesLookup(null),
      countsReady: false,
    });

    expect(ai.bulk.map((c) => c.slug)).toEqual(["planned-co"]);
  });

  it("calls a sector dormant when no connector reaches any member", () => {
    const sectors = bySlug();
    expect(sectors.technology.dormant).toBe(false);
    const [only] = buildSectorGroups({
      state: { sectors: [sector("ai", "AI")], companies: [company({ slug: "x", sectors: ["ai"] })] },
      chosen: new Set(),
      filters: FILTERS,
      sectorNames: { ai: "AI" },
      orderIndex: new Map(),
      openRoles: openRolesLookup(null),
      countsReady: false,
    });
    expect(only.dormant).toBe(true);
  });
});

// --------------------------------------------------------------------------- //
// Why it is empty
// --------------------------------------------------------------------------- //

describe("the empty state", () => {
  const reasons = (over: Partial<RegisterFilters>, chosen: ReadonlySet<string> = CHOSEN) =>
    registerEmptyReasons({ state: STATE, chosen, filters: { ...FILTERS, ...over }, sectorNames: NAMES });

  it("says nothing while any row is drawn", () => {
    expect(reasons({})).toBeNull();
  });

  it("names the filter that is holding rows back and what releasing it reveals", () => {
    expect(reasons({ query: "zzz" })).toEqual([
      { key: "query", active: true, released: 4 },
    ]);
  });

  it("counts a release with the OTHER filters still applied", () => {
    // The whole point of measuring: the number in "1 in the catalog matches"
    // must come from this exact predicate, with the other filters left on —
    // not from a second condition written for the message. Tracked-only over an
    // empty selection empties the list; releasing it reveals the ONE company
    // the search still admits, not all four.
    expect(reasons({ query: "meta", trackedOnly: true }, new Set())).toEqual([
      { key: "tracked", active: true, released: 1 },
    ]);
  });

  it("never blames a filter that is releasing nothing", () => {
    // `showPlanned` is off here and is NOT blamed: releasing it alone reveals
    // nothing, because the search still excludes everything. And releasing the
    // query reveals 3 rather than 4 — the planned switch is still applied,
    // which is what "with the other filters left on" means.
    expect(reasons({ query: "zzz", showPlanned: false })).toEqual([
      { key: "query", active: true, released: 3 },
    ]);
  });

  it("blames no filter when the catalog itself came back empty", () => {
    expect(
      registerEmptyReasons({
        state: { sectors: [], companies: [] },
        chosen: new Set(),
        filters: FILTERS,
        sectorNames: {},
      }),
    ).toEqual([]);
  });
});

// --------------------------------------------------------------------------- //
// Order, alerts, selection, sync targets
// --------------------------------------------------------------------------- //

describe("the rest of the register's arithmetic", () => {
  it("orders tracked first, then by volume, then catalog order", () => {
    const order = buildOrderIndex(STATE, CHOSEN, { counts: { meta: 4, openai: 6, stripe: 1 } });
    const ranked = [...order.entries()].sort((a, b) => a[1] - b[1]).map(([slug]) => slug);

    expect(ranked).toEqual(["openai", "meta", "stripe", "planned-co"]);
  });

  it("falls back to catalog order before the counts land", () => {
    const order = buildOrderIndex(STATE, CHOSEN, null);
    const ranked = [...order.entries()].sort((a, b) => a[1] - b[1]).map(([slug]) => slug);

    expect(ranked).toEqual(["meta", "openai", "stripe", "planned-co"]);
  });

  it("raises one alert per reason a tracked company cannot be collected", () => {
    const tracked = [
      company({ slug: "parked-co", display: "Parked Co", connector_state: "parked" }),
      company({ slug: "planned-co", display: "Planned Co", connector_state: "planned" }),
      company({ slug: "hidden-co", display: "Hidden Co", connector_state: "live", visible: false }),
      company({ slug: "fine", display: "Fine", connector_state: "live" }),
    ];

    expect(buildAlerts(tracked)).toEqual([
      { kind: "blocked", companies: ["Parked Co"] },
      { kind: "paused", companies: ["Planned Co"] },
      { kind: "hidden", companies: ["Hidden Co"] },
    ]);
    expect(buildAlerts([company({ connector_state: "live" })])).toEqual([]);
  });

  it("sends only the companies a write names, split by whether it follows them", () => {
    // `pwc` is followed in the roster but not named: a write never restates it.
    const next = new Set(["meta", "pwc"]);
    expect(selectionChange(next, ["stripe", "meta", "meta"])).toEqual({ follow: ["meta"], unfollow: ["stripe"] });
  });

  it("reads a company's roles as null until the counts arrive, never as zero", () => {
    expect(openRolesLookup(null)("meta")).toBeNull();
    expect(openRolesLookup({ counts: {} })("meta")).toBe(0);
  });

  it("reads a company named like an Object builtin as its count, never the prototype's member", () => {
    // A slug is user data: `counts["constructor"]` on a plain object answers
    // `Object`, and a sum over it turns into a string of function source.
    const counts = { counts: { meta: 4, openai: 6 } };
    const lookup = openRolesLookup(counts);
    for (const slug of ["constructor", "toString", "valueOf", "hasOwnProperty", "__proto__"]) {
      expect(lookup(slug)).toBe(0);
    }
    const tracked = ["meta", "constructor", "openai", "valueOf"].map((slug) =>
      company({ slug, connector_state: "live" }),
    );
    const summary = trackedSummary({ tracked, openRoles: lookup, countsReady: true });
    expect(summary.trackedOpenRoles).toBe(10);
    expect(summary.maxOpenRoles).toBe(6);
    const order = buildOrderIndex(
      { ...STATE, companies: [...STATE.companies, company({ slug: "constructor" })] },
      CHOSEN,
      counts,
    );
    expect([...order.values()].every(Number.isInteger)).toBe(true);
    expect(followEstimate(tracked, { counts: { constructor: 700, meta: 400 } }).volume)
      .toBe("thousands");
  });

  it("projects the sync targets it is allowed to ask for and the ones worth retrying", () => {
    const targets = [
      { slug: "meta", display: "Meta", retryable: true },
      { slug: "openai", display: "OpenAI", retryable: false },
    ] as SyncTarget[];

    expect([...failedSources(targets)]).toEqual([{ slug: "meta", display: "Meta" }]);
  });

  it("only calls a connector-bearing company connectable", () => {
    expect(isConnectable(company({ connector_state: "live" }))).toBe(true);
    expect(isConnectable(company({ connector_state: "planned" }))).toBe(false);
    expect(isConnectable(company({ connector_state: "parked" }))).toBe(false);
  });
});

describe("the curated list: which companies are the others, and what following them costs", () => {
  const others = otherCompanies({
    sectors: [],
    companies: [
      company({ slug: "google", curated: true, directory: false, connector_state: "live" }),
      company({ slug: "stripe", connector_state: "ready" }),
      company({ slug: "deepmind", connector_state: "family" }),
      company({ slug: "pwc", connector_state: "planned" }),
      company({ slug: "tesla", connector_state: "parked", selectable: false }),
      // Added by URL: the user's own follow, never a list RoleBand ships.
      company({ slug: "acme", connector_state: "active", sectors: [] }),
    ],
  });

  it("counts only what RoleBand can scan and is not curated", () => {
    expect(others.map((entry) => entry.slug)).toEqual(["stripe", "deepmind"]);
    expect(otherCompanies(null)).toEqual([]);
  });

  it("names thousands or hundreds only from stored counts, and more roles otherwise", () => {
    expect(followEstimate(others, { counts: { stripe: 700, deepmind: 300 } }).volume).toBe("thousands");
    expect(followEstimate(others, { counts: { stripe: 150 } }).volume).toBe("hundreds");
    expect(followEstimate(others, { counts: { stripe: 99 } }).volume).toBeNull();
    expect(followEstimate(others, null).volume).toBeNull();
    // A planned company is never scanned, so its roles never reach the radar.
    const withPlanned = [...others, company({ slug: "pwc", connector_state: "planned" })];
    expect(followEstimate(withPlanned, { counts: { pwc: 5000 } })).toEqual({ volume: null });
  });
});

// --------------------------------------------------------------------------- //
// Every other company RoleBand can scan
// --------------------------------------------------------------------------- //

describe("the directory: every other company, found by name", () => {
  const DIR_STATE: CompanyDiscoveryState = {
    ...STATE,
    companies: [
      ...STATE.companies,
      company({ slug: "crusoe", display: "Crusoe", sectors: [], connector_state: "active",
                enabled: true, tracked: true, directory: true }),
    ],
  };
  const hit = (slug: string, display: string) =>
    directoryHitCompany({ slug, display, named_by: "board", tracked: false, enabled: false });

  const dirGroups = (over: Partial<RegisterFilters> = {}, hits = [hit("spacex", "SpaceX")]) =>
    Object.fromEntries(
      buildSectorGroups({
        state: DIR_STATE,
        chosen: enabledSet(DIR_STATE),
        filters: { ...FILTERS, ...over },
        sectorNames: NAMES,
        orderIndex: buildOrderIndex(DIR_STATE, enabledSet(DIR_STATE), null),
        openRoles: openRolesLookup(null),
        countsReady: false,
        directoryHits: hits,
      }).map((group) => [group.slug, group]),
    );

  it("keeps a followed directory company apart from the user's own URL additions", () => {
    const groups = dirGroups({}, []);
    expect(groups[DIRECTORY_SLUG].rows.map((c) => c.slug)).toEqual(["crusoe"]);
    expect(groups[UNSORTED_SLUG].rows.map((c) => c.slug)).toEqual(["stripe"]);
    expect(groups[DIRECTORY_SLUG].display).toBe("Other companies");
  });

  it("draws a search hit even when only its board address matched", () => {
    // The server matched "pantheonpub" on the address; the name does not contain it.
    const groups = dirGroups({ query: "pantheonpub" }, [hit("pantheon", "Pantheon Ventures")]);
    expect(groups[DIRECTORY_SLUG].rows.map((c) => c.slug)).toEqual(["pantheon"]);
  });

  it("never draws a hit twice once the roster holds it", () => {
    const groups = dirGroups({ query: "cru" }, [hit("crusoe", "Crusoe")]);
    expect(groups[DIRECTORY_SLUG].rows.map((c) => c.slug)).toEqual(["crusoe"]);
    expect(groups[DIRECTORY_SLUG].rows[0].enabled).toBe(true);
  });

  it("hides unfollowed hits under Following only, and keeps followed ones", () => {
    const groups = dirGroups({ query: "c", trackedOnly: true }, [hit("spacex", "SpaceX")]);
    expect(groups[DIRECTORY_SLUG].rows.map((c) => c.slug)).toEqual(["crusoe"]);
  });

  it("has no group at all when nothing from the directory is followed or found", () => {
    const groups = Object.fromEntries(
      buildSectorGroups({
        state: STATE, chosen: CHOSEN, filters: FILTERS, sectorNames: NAMES,
        orderIndex: buildOrderIndex(STATE, CHOSEN, null), openRoles: openRolesLookup(null),
        countsReady: false,
      }).map((group) => [group.slug, group]),
    );
    expect(groups[DIRECTORY_SLUG]).toBeUndefined();
  });

  it("sends a hit followed from a search, which the roster does not hold yet", () => {
    const next = new Set([...enabledSet(STATE), "spacex"]);
    expect(selectionChange(next, ["spacex"])).toEqual({ follow: ["spacex"], unfollow: [] });
  });

  it("marks a hit ready and followable: a board RoleBand can read that nobody follows yet", () => {
    const row = hit("spacex", "SpaceX");
    expect([row.connector_state, row.selectable, row.directory, row.sectors]).toEqual([
      "ready", true, true, []]);
    expect(isConnectable(row)).toBe(true);
  });
});

describe("a large count said plainly", () => {
  it.each([
    [57, "57"],
    [999, "999"],
    [1234, "1,200"],
    [9960, "9,900"],
    [10214, "10,000"],
    [16361, "16,000"],
  ])("%i reads as about %s", (n, text) => {
    expect(aboutCount(n)).toBe(text);
  });
});

describe("the register's age cells (R14)", () => {
  it("counts hours since a moment, and never invents one", () => {
    const now = Date.parse("2026-10-04T12:00:00Z");
    expect(hoursSince("2026-10-04T10:30:00Z", now)).toBe(1.5);
    expect(hoursSince(null, now)).toBeNull();
    expect(hoursSince(undefined, now)).toBeNull();
    expect(hoursSince("not a date", now)).toBeNull();
    // A clock skewed ahead of ours is no negative age.
    expect(hoursSince("2026-10-04T13:00:00Z", now)).toBe(0);
  });

  it("says hours below two days and days from there, with no 'ago'", () => {
    expect(shortAge(null)).toBeNull();
    expect(shortAge(0.4)).toBe("0h");
    expect(shortAge(47.4)).toBe("47h");
    // The cut is 48 h, not the freshness wording's 24 h.
    expect(shortAge(30)).toBe("30h");
    expect(shortAge(48)).toBe("2d");
    expect(shortAge(24 * 9 + 5)).toBe("9d");
  });
});
