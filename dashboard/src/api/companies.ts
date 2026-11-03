/* Companies: profiles, prices, the chip's card and the tracked roster.
   One domain of the typed client; `index.ts` composes `api`. */

import type { Schemas } from "./schemas";
import { qs, getJSON, putJSON, postJSON, patchJSON, deleteJSON } from "./transport";

// --- Company Profiles -------------------------------------------------------
// Values are RESOLVED from competing source claims, so each field carries its
// provenance: which source won, how stale it is, and who disagrees.

export type Freshness = NonNullable<ProfileField["freshness"]>;
export type DataHealth = CompanyProfileSummary["data_health"];

/** Another source asserting a different value, as resolution stored it. */
export type FieldConflict = Schemas["ProfileFieldConflict"];

/** One source's latest claim about a field, most-trusted first: the choices we
 *  offer so the user picks rather than retypes. */
export type FieldCandidate = Schemas["ProfileFieldCandidate"];

/** A resolved field: its value, which source won, how fresh it is, who disagrees. */
export type ProfileField = Schemas["ProfileFieldDetail"];

export type ReviewReason = ReviewItem["reason"];
export type ReviewItem = Schemas["ProfileReviewItem"];
export type CompanyCompLevel = Schemas["CompanyCompRung"];
export type CompanyBenefitItem = Schemas["CompanyBenefitItem"];
export type CompanyBenefitGroup = Schemas["CompanyBenefitGroup"];

/** A profile list row; the latest cached quote is null for a private or unpriced company. */
export type CompanyProfileSummary = Schemas["CompanyProfileSummary"];

/** One daily OHLC bar for the profile price sparkline. */
export type PriceBar = Schemas["PriceBarRow"];
export type CompanyPrices = Schemas["CompanyPricesResponse"];

/** Settings > Plugins > Stock prices: whether a key is set and where
 *  from, and what the price pass last did. The key itself is write-only. */
export type PriceFeedState = Schemas["PriceFeedState"];

/** Where a user gets a free price-feed key: its account page shows the key after
 *  sign-up. The profile's empty price chart and the Stock prices
 *  card both link here. */
export const PRICE_FEED_KEY_URL = "https://www.tiingo.com/account/api/token";

/** Compact payload behind a company chip's hover card on a job row. */
export type CompanyCard = Schemas["CompanyCardResponse"];
export type CompanyProfileList = Schemas["CompanyProfileListResponse"];

/** One company. `fields` always carries all eight shown fields. */
export type CompanyProfileDetail = Schemas["CompanyProfileDetailResponse"];

/** An office observed from open in-scope postings, busiest first. `country` is the
 *  country-kind slug out of `groups`, named by the backend so the dashboard never
 *  guesses; `null` is a real answer ("Wilmington, DE"), and the city is still shown. */
export type CompanyLocation = Schemas["CompanyLocationRow"];

/** A pin or an unpin: the company's health after re-resolving. */
export type CompanyProfileFieldWrite = Schemas["CompanyProfileFieldWrite"];

/* Tracked-company wire types are aliases of the generated schemas
   (`tracker/api/schemas/companies.py`). */

/** One tracked company, as the roster and every company write answer with it.
 *  `status`, `source` and `role_catalog_status` are plain strings on the wire:
 *  no database constraint backs them. */
export type TrackedCompany = Schemas["TrackedCompanyRow"];

export type CompanyList = Schemas["CompanyListResponse"];

export type CompanyDiscoverySector = Schemas["DiscoverySector"];

/** A company in the explorer: a catalog entry merged with its tracked row, if any. */
export type CompanyDiscoveryCompany = Schemas["DiscoveryCompany"];
/** A search over every other company RoleBand can scan. */
export type CompanyDirectorySearch = Schemas["CompanyDirectorySearchResponse"];
export type CompanyDirectoryMatch = Schemas["DirectoryMatch"];
/** The whole set as one followable thing, and the background scan's progress. */
export type CompanyDirectoryStatus = Schemas["CompanyDirectoryStatus"];

export type CompanyConnectorState = CompanyDiscoveryCompany["connector_state"];

export type CompanyDiscoveryState = Schemas["CompanyDiscoveryResponse"];

// Open in-scope roles per company slug, served apart from the roster so the
// Company Explorer paints before this aggregate lands. A slug absent from the
// map has no open in-scope role — read it as 0, never as "still loading".
export type CompanyOpenCounts = Schemas["CompanyOpenCountsResponse"];

// Median seconds one whole scan of a company takes, from recent runs. A slug
// absent from the map has never been measured — never read it as fast.
export type CompanyNames = Schemas["CompanyNamesResponse"];

/** One walled company's consent, as the dialog the user confirmed. */
export type CompanyConsent = Schemas["CompanyConsent"];

/** A careers page a company's roles moved to, verified to answer. */
export type MovedBoard = Schemas["MovedBoard"];
export type BoardSearch = Schemas["BoardSearchResponse"];

/** `POST /api/companies`: a catalog slug, or a name and a careers URL. */
export type AddCompanyPayload = Schemas["AddCompanyPayload"];

export const companiesApi = {
  companyProfiles: (signal?: AbortSignal) =>
    getJSON<CompanyProfileList>("/api/company-profiles", signal),
  companyProfile: (slug: string, signal?: AbortSignal) =>
    getJSON<CompanyProfileDetail>(`/api/company-profiles/${encodeURIComponent(slug)}`, signal),
  companyPrices: (slug: string, range = "3m") =>
    getJSON<CompanyPrices>(
      `/api/company-profiles/${encodeURIComponent(slug)}/prices?range=${encodeURIComponent(range)}`,
    ),
  priceFeed: () => getJSON<PriceFeedState>("/api/settings/price-feed"),
  savePriceFeedKey: (apiKey: string) =>
    putJSON<PriceFeedState>("/api/settings/price-feed", { api_key: apiKey } satisfies Schemas["PriceFeedKey"]),
  removePriceFeedKey: () => deleteJSON<PriceFeedState>("/api/settings/price-feed"),
  refreshPriceFeed: () => postJSON<PriceFeedState>("/api/settings/price-feed/refresh", {}),
  companyCard: (slug: string) =>
    getJSON<CompanyCard>(`/api/companies/${encodeURIComponent(slug)}/card`),
  setCompanyField: (slug: string, field: string, value: unknown) =>
    patchJSON<CompanyProfileFieldWrite>(
      `/api/company-profiles/${encodeURIComponent(slug)}`,
      { field, value },
    ),
  clearCompanyField: (slug: string, field: string) =>
    deleteJSON<CompanyProfileFieldWrite>(
      `/api/company-profiles/${encodeURIComponent(slug)}/manual/${encodeURIComponent(field)}`,
    ),
  companies: () => getJSON<CompanyList>("/api/companies"),
  companyDiscovery: () => getJSON<CompanyDiscoveryState>("/api/companies/discovery"),
  companyOpenCounts: () => getJSON<CompanyOpenCounts>("/api/companies/open-counts"),
  /** One write's change, and only it: the companies to follow and to unfollow.
   *  A company it does not name keeps whatever the server holds. `consents`
   *  carries the dialog text the user confirmed for each walled company it
   *  starts to follow; the server refuses a walled follow without one. */
  setCompanySelection: (change: { follow: string[]; unfollow: string[] }, consents: CompanyConsent[] = []) =>
    putJSON<CompanyDiscoveryState>("/api/companies/selection", {
      follow: change.follow,
      unfollow: change.unfollow,
      consents,
    } satisfies Schemas["CompanySelectionPayload"]),
  /** The few directory companies matching a typed name; never the whole set. */
  searchCompanyDirectory: (q: string, signal?: AbortSignal) =>
    getJSON<CompanyDirectorySearch>(`/api/companies/directory?${qs({ q })}`, signal),
  companyDirectoryStatus: () => getJSON<CompanyDirectoryStatus>("/api/companies/directory/status"),
  followCompanyDirectory: (following: boolean) =>
    putJSON<CompanyDirectoryStatus>("/api/companies/directory/follow", {
      following,
    } satisfies Schemas["DirectoryFollowPayload"]),
  addCompany: (payload: AddCompanyPayload) => postJSON<TrackedCompany>("/api/companies", payload),
  updateCompany: (slug: string, patch: Schemas["EnabledPayload"]) =>
    patchJSON<TrackedCompany>(`/api/companies/${encodeURIComponent(slug)}`, patch),
  /** Where a company's careers page moved, or null. With `careersUrl`, the
   *  page behind the address the person gave. Reads only. */
  findCompanyBoard: (slug: string, careersUrl?: string) =>
    postJSON<BoardSearch>(`/api/companies/${encodeURIComponent(slug)}/board/find`, {
      careers_url: careersUrl ?? null,
    } satisfies Schemas["FindBoardPayload"]),
  /** Point the company at a page `findCompanyBoard` answered; the server
   *  verifies it again before it moves anything. */
  moveCompanyBoard: (slug: string, board: MovedBoard) =>
    putJSON<TrackedCompany>(`/api/companies/${encodeURIComponent(slug)}/board`, {
      adapter: board.adapter,
      board_token: board.board_token,
      board_region: board.board_region,
    } satisfies Schemas["MoveBoardPayload"]),
};
