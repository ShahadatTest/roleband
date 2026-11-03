import { wordsLanguage } from "../../copy/runtime";
import type { CompanyConsent, CompanyDiscoveryCompany } from "../../api";
import { CURATED_LIST } from "../../copy/vocabulary";
import { aboutCount, type FollowEstimate, type SectorGroup } from "./companiesModel";
import {
  companiesFollowCopyByFollowingYouChooseTo,
  companiesFollowCopyChangeItAnyTimeIn,
  companiesFollowCopyCancel,
  companiesFollowCopyFollow,
  companiesFollowCopyFollowCompany,
  companiesFollowCopyFollowEveryCompany,
  companiesFollowCopyFollowEveryCompanyQuestion,
  companiesFollowCopyFollowAll,
  companiesFollowCopyFollowAllIn,
  companiesFollowCopyFollowMore,
  companiesFollowCopyFollowingAllWillLikelyBring,
  companiesFollowCopyHundredsOfRoles,
  companiesFollowCopyKeep,
  companiesFollowCopyKeepFollowing,
  companiesFollowCopyMoreRoles,
  companiesFollowCopyRolebandScansTheBestKnown,
  companiesFollowCopyRolebandStartsYouWithA,
  companiesFollowCopyRolebandStopsScanningThemYour,
  companiesFollowCopyOnlyCompaniesHiringForRoles,
  companiesFollowCopySJobListingsStopBeing,
  companiesFollowCopyScanAboutMoreCompanies,
  companiesFollowCopySomeOfTheseCompaniesCareers,
  companiesFollowCopySomeOfTheseCompaniesLimit,
  companiesFollowCopyStartScanning,
  companiesFollowCopyThisWillLikelyAddTo,
  companiesFollowCopyThousandsOfRoles,
  companiesFollowCopyUnfollow,
  companiesFollowCopyUnfollowCompanyQuestion,
  companiesFollowCopyUnfollowCompany,
  companiesFollowCopyUnfollowOutsideYour,
  companiesFollowCopyWithMoreCompaniesScansTake,
  companiesFollowCopyYouCanStopAtAny,
  companiesFollowCopyYouCanUnfollowAnyCompany,
  companiesFollowCopyYourRadarCoversTheWhole,
} from "../../copy/gen/companies";

/* What the follow confirmations SAY, as data.
 *
 * One function builds every dialog's words, and the dialog renders exactly
 * what it returns. That is not tidiness: for a walled company the
 * words ARE the consent — the server stores the text the user confirmed — so
 * the text shown and the text recorded must be the same string by
 * construction, never two renderings that happen to agree.
 *
 * The wording is pinned (`copy/pinned.en.json`): one sentence for every wall,
 * naming no company, no reason and not the product, so a change here is a
 * change to what was agreed.
 */

/** A follow or unfollow waiting on the reader's answer. `companies` is exactly
 *  what the write would change, fixed when it was asked, so the dialog and the
 *  write cannot disagree about the count. */
export type FollowConfirmation =
  | { kind: "include"; companies: CompanyDiscoveryCompany[]; estimate: FollowEstimate }
  | { kind: "exclude"; companies: CompanyDiscoveryCompany[] }
  | {
      kind: "sector";
      group: SectorGroup;
      companies: CompanyDiscoveryCompany[];
      estimate: FollowEstimate;
    }
  /** Follow one walled company — or consent for one already followed with no
   *  stored consent, which is not scanned until the user answers. */
  | { kind: "walled-follow"; company: CompanyDiscoveryCompany }
  | { kind: "walled-unfollow"; company: CompanyDiscoveryCompany }
  /** Follow every other company RoleBand can scan, as one decision. */
  | { kind: "directory"; size: number }
  /** Setup's "Plus other companies": every listed company still unfollowed
   *  (`companies`, possibly none) and the set of other companies, in one
   *  answer. */
  | { kind: "everything"; companies: CompanyDiscoveryCompany[] };

export interface FollowCopy {
  title: string;
  paragraphs: string[];
  /** The safe answer. It takes focus. */
  safe: string;
  act: string;
}

/** A walled company this write would start collecting without the user's
 *  consent — the ones a bulk dialog must name and record. */
export function awaitingConsent(companies: readonly CompanyDiscoveryCompany[]): CompanyDiscoveryCompany[] {
  return companies.filter((company) => company.wall !== null && !company.consented);
}


function volume(estimate: FollowEstimate): string {
  if (estimate.volume === "thousands") return companiesFollowCopyThousandsOfRoles();
  if (estimate.volume === "hundreds") return companiesFollowCopyHundredsOfRoles();
  return companiesFollowCopyMoreRoles();
}

/** Why a company waits for the user. Every wall is the SITE's — a company the
 *  product itself leaves to the user is not walled at all and never reaches a
 *  dialog. Names no company: the dialog's title does. */
export const SITE_WALL_SENTENCE = "Its careers site limits automated collection.";

export function wallSentence(company: CompanyDiscoveryCompany): string | null {
  return company.wall === null ? null : SITE_WALL_SENTENCE;
}

/** The line that makes a bulk follow an informed choice about its walled
 *  companies: Follow all includes them. Absent when none. Every bulk follow
 *  records the same pinned consent sentence. */
function walledLine(companies: readonly CompanyDiscoveryCompany[]): string | null {
  return awaitingConsent(companies).length > 0 ? companiesFollowCopySomeOfTheseCompaniesLimit() : null;
}

export function followCopy(pending: FollowConfirmation): FollowCopy {
  switch (pending.kind) {
    case "include": {
      const n = pending.companies.length;
      return {
        title: companiesFollowCopyFollowMore(),
        paragraphs: [
          companiesFollowCopyRolebandStartsYouWithA({ curatedList: CURATED_LIST() }),
          companiesFollowCopyFollowingAllWillLikelyBring(),
          walledLine(pending.companies),
          companiesFollowCopyYouCanUnfollowAnyCompany(),
        ].filter((line): line is string => line !== null),
        safe: companiesFollowCopyKeep({ curatedList: CURATED_LIST() }),
        act: companiesFollowCopyFollowAll({ count: n }),
      };
    }
    case "exclude": {
      const n = pending.companies.length;
      return {
        title: companiesFollowCopyUnfollowOutsideYour({ count: n, curatedList: CURATED_LIST() }),
        paragraphs: [
          companiesFollowCopyRolebandStopsScanningThemYour({ count: n, curatedList: CURATED_LIST() }),
        ],
        safe: companiesFollowCopyKeepFollowing(),
        act: companiesFollowCopyUnfollow({ count: n }),
      };
    }
    case "sector": {
      const n = pending.group.bulk.length;
      return {
        title: companiesFollowCopyFollowAllIn({ count: n, sector: pending.group.display }),
        paragraphs: [
          companiesFollowCopyThisWillLikelyAddTo({ estimate: String(volume(pending.estimate)) }),
          walledLine(pending.companies),
        ].filter((line): line is string => line !== null),
        safe: companiesFollowCopyCancel(),
        act: companiesFollowCopyFollowAll({ count: n }),
      };
    }
    case "walled-follow": {
      const { display } = pending.company;
      return {
        title: companiesFollowCopyFollow({ display: String(display) }),
        paragraphs: [
          SITE_WALL_SENTENCE,
          companiesFollowCopyByFollowingYouChooseTo({ display: String(display) }),
        ],
        safe: companiesFollowCopyCancel(),
        act: companiesFollowCopyFollowCompany({ display: String(display) }),
      };
    }
    case "directory": {
      const about = aboutCount(pending.size);
      return {
        title: companiesFollowCopyScanAboutMoreCompanies({ about: String(about) }),
        paragraphs: [
          companiesFollowCopyOnlyCompaniesHiringForRoles(),
          companiesFollowCopyRolebandScansTheBestKnown(),
          companiesFollowCopyYouCanStopAtAny(),
        ],
        safe: companiesFollowCopyCancel(),
        act: companiesFollowCopyStartScanning(),
      };
    }
    case "everything": {
      // Says that some sites limit collection, never how many: the choice is
      // the list and the other companies, and the consent is the same for one company or ten.
      const walled = awaitingConsent(pending.companies).length > 0;
      return {
        title: companiesFollowCopyFollowEveryCompanyQuestion(),
        paragraphs: [
          companiesFollowCopyYourRadarCoversTheWhole(),
          walled ? companiesFollowCopySomeOfTheseCompaniesCareers() : null,
          companiesFollowCopyWithMoreCompaniesScansTake(),
          companiesFollowCopyChangeItAnyTimeIn(),
        ].filter((line): line is string => line !== null),
        safe: companiesFollowCopyCancel(),
        act: companiesFollowCopyFollowEveryCompany(),
      };
    }
    case "walled-unfollow": {
      const { display } = pending.company;
      return {
        title: companiesFollowCopyUnfollowCompanyQuestion({ display: String(display) }),
        paragraphs: [
          companiesFollowCopySJobListingsStopBeing({ display: String(display) }),
        ],
        safe: companiesFollowCopyCancel(),
        act: companiesFollowCopyUnfollowCompany({ display: String(display) }),
      };
    }
  }
}

/** The consents this answer records: one per walled company it starts to
 *  collect, each carrying the whole dialog text the user confirmed. */
export function consentsFor(pending: FollowConfirmation, shown: { copy: FollowCopy; locale: string } = { copy: followCopy(pending), locale: wordsLanguage() }): CompanyConsent[] {
  const copy = shown.copy;
  const text = [copy.title, ...copy.paragraphs].join("\n\n");
  const walled =
    pending.kind === "walled-follow"
      ? [pending.company]
      : pending.kind === "include" || pending.kind === "sector" || pending.kind === "everything"
        ? awaitingConsent(pending.companies)
        : [];
  return walled.map((company) => ({ slug: company.slug, text, locale: shown.locale }));
}
