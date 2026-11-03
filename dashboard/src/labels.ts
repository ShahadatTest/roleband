// Display labels for levels, places and workplaces, and the day count, as the
// screens print them. Not in format.ts because the shell loads that file and
// uses none of these: there, every one would ride in the startup chunk, with
// all of locations.gen.ts behind LOC_LABEL.
// Import them from `./format`, which re-exports them.
import {
  taxonomyBandDirectorPlus,
  taxonomyBandEntry,
  taxonomyBandIntern,
  taxonomyBandMid,
  taxonomyBandPrincipal,
  taxonomyBandSenior,
  taxonomyBandStaff,
  taxonomyPlaceAfrica,
  taxonomyPlaceAustin,
  taxonomyPlaceCentralAsia,
  taxonomyPlaceDcMetro,
  taxonomyPlaceEastAsia,
  taxonomyPlaceEurope,
  taxonomyPlaceGulf,
  taxonomyPlaceLatinAmerica,
  taxonomyPlaceLondon,
  taxonomyPlaceMiddleEast,
  taxonomyPlaceNewYork,
  taxonomyPlaceNorthAmerica,
  taxonomyPlaceOceania,
  taxonomyPlacePacificNorthwest,
  taxonomyPlaceSiliconValley,
  taxonomyPlaceSouthAsia,
  taxonomyPlaceSoutheastAsia,
  taxonomyPlaceUk,
  taxonomyWorkplaceHybrid,
  taxonomyWorkplaceOnsite,
  taxonomyWorkplaceRemote,
} from "./copy/gen/taxonomy";
import { formatDays, formatDaysToday } from "./copy/gen/format";
import { COUNTRY_ALPHA2, COUNTRY_LABEL } from "./locations.gen";

export function relDays(days: number | null | undefined): string {
  if (days == null) return "—";
  if (days === 0) return formatDaysToday();
  return formatDays({ count: days });
}

// Display order for level bands: most senior first. The full-market ladder —
// every career stage is present and first-class. Intern is its own rung below
// Entry / Junior.
export const BAND_ORDER = ["director_plus", "principal", "staff", "senior", "mid", "entry", "intern"];

export const BAND_LABEL: Record<string, string> = {
  get intern() { return taxonomyBandIntern(); },
  get entry() { return taxonomyBandEntry(); },
  get mid() { return taxonomyBandMid(); },
  get senior() { return taxonomyBandSenior(); },
  get staff() { return taxonomyBandStaff(); },
  get principal() { return taxonomyBandPrincipal(); },
  get director_plus() { return taxonomyBandDirectorPlus(); },
};

/* Every country label comes from the generated mirror; metros and regions are
   named here because they are RoleBand's own groupings, not ISO countries.
   `uk` overrides the generated "United Kingdom" — the short form is what fits a
   badge. Countries never get a hand-written entry: a hand-copied map falls
   behind the taxonomy and renders the missing groups as raw slugs. */
const METRO_LABEL: Record<string, string> = {
  get silicon_valley() { return taxonomyPlaceSiliconValley(); },
  get pacific_northwest() { return taxonomyPlacePacificNorthwest(); },
  get new_york() { return taxonomyPlaceNewYork(); },
  get austin() { return taxonomyPlaceAustin(); },
  get dc_metro() { return taxonomyPlaceDcMetro(); },
  get london() { return taxonomyPlaceLondon(); },
};

const GROUP_LABEL: Record<string, string> = {
  get north_america() { return taxonomyPlaceNorthAmerica(); },
  get latin_america() { return taxonomyPlaceLatinAmerica(); },
  get europe() { return taxonomyPlaceEurope(); },
  get middle_east() { return taxonomyPlaceMiddleEast(); },
  get gulf() { return taxonomyPlaceGulf(); },
  get africa() { return taxonomyPlaceAfrica(); },
  get central_asia() { return taxonomyPlaceCentralAsia(); },
  get south_asia() { return taxonomyPlaceSouthAsia(); },
  get east_asia() { return taxonomyPlaceEastAsia(); },
  get southeast_asia() { return taxonomyPlaceSoutheastAsia(); },
  get oceania() { return taxonomyPlaceOceania(); },
  get uk() { return taxonomyPlaceUk(); },
};

/* Copied as DESCRIPTORS, not spread: a spread reads each getter once, at
   import, and would freeze the group names in the language the app booted in. */
export const LOC_LABEL: Record<string, string> = Object.defineProperties(
  { ...COUNTRY_LABEL },
  { ...Object.getOwnPropertyDescriptors(METRO_LABEL), ...Object.getOwnPropertyDescriptors(GROUP_LABEL) },
);

/* A metro area: the one kind of place group a posting's own place text does
   not already state, since its country and region are read from that text. */
export function isMetro(slug: string): boolean {
  return Object.prototype.hasOwnProperty.call(METRO_LABEL, slug);
}

/* A country slug as a flag glyph. The two regional-indicator codepoints ARE the
   flag, so all 196 countries cost no image assets and no icon dependency.
   Returns "" for a slug with no alpha-2 (an unmapped city, a metro, a region) —
   callers render nothing rather than a placeholder box.

   Fonts that ship no flag glyphs (Windows Chrome) fall back to the two letters,
   which still names the country. Never let this be the only label: pair it with
   the display name, or an `aria-label` where space forbids one. */
export function flagEmoji(countrySlug: string | null | undefined): string {
  const a2 = countrySlug ? COUNTRY_ALPHA2[countrySlug] : undefined;
  if (!a2) return "";
  return String.fromCodePoint(
    ...[...a2.toUpperCase()].map((c) => c.charCodeAt(0) + 0x1f1a5),
  );
}

export const WORKPLACE_LABEL: Record<string, string> = {
  get onsite() { return taxonomyWorkplaceOnsite(); },
  get remote() { return taxonomyWorkplaceRemote(); },
  get hybrid() { return taxonomyWorkplaceHybrid(); },
  unknown: "—",
};
