import { BAND_LABEL, LOC_LABEL } from "../format";
import { byKey } from "./gen/vocab";
import { roleJobStatusClosed, roleJobStatusOpen } from "./gen/role";

/* Product vocabulary by slug (docs/copy.md).
 *
 * The backend sends slugs and keeps their meaning; this names them in the
 * reader's language from `copy/en/vocab.ftl`. `backend/tests/test_vocab_catalog.py`
 * fails when a slug the backend can send has no message, so the slug itself is
 * shown only for one a newer server added. Lazy screens only: the map holds
 * every name, so nothing in the shell imports this. */

/** The catalog key part for a slug: "ai_ml" -> "ai-ml", "sec_edgar" -> "sec-edgar". */
const part = (slug: string): string => slug.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");

function say(kind: string, slug: string): string {
  const message = byKey[`vocab-${kind}-${part(slug)}`];
  return message ? message() : slug;
}

/** A domain (world) by slug; null is the unclassified bucket. */
export const domainName = (slug: string | null | undefined): string => say("domain", slug ?? "unclassified");
/** The line under a domain's name. */
export const domainHint = (slug: string): string => say("domain-hint", slug);
/** A track by slug. */
export const trackName = (slug: string): string => say("track", slug);
/** A role group (family) by slug; null is a role in none. */
export const roleName = (slug: string | null | undefined): string => say("role", slug ?? "other");
/** A company sector by slug. */
export const sectorName = (slug: string): string => say("sector", slug);
/** Where a company fact came from, by source key. */
export const sourceName = (source: string): string => say("source", source);
/** A skill by its catalog slug (the API's `term`). */
export const skillName = (slug: string): string => say("skill", slug);
/** The pay a figure is stated on, by the API's `basis` ("base"). */
export const payBasisName = (basis: string): string => say("pay-basis", basis);

const STATUS: Record<string, () => string> = { open: roleJobStatusOpen, closed: roleJobStatusClosed };
/** A posting's status ("open"), said; null for one this build has no word for,
 *  which a screen shows as the code it is (`ui/Content`). */
export const statusName = (status: string): string | null => STATUS[status]?.() ?? null;

/** A level band by slug ("senior"), from the shell's band names. */
export const levelName = (slug: string | null | undefined): string => (slug ? BAND_LABEL[slug] ?? slug : "");

/** A place: RoleBand's own groupings (metros, regions) by the catalog; a
 *  country or a city by its own name as the server sends it,
 *  which is the place's name, not the product's words. */
export const placeName = (place: { slug: string; display: string; kind?: string }): string =>
  (place.kind === "metro" || place.kind === "region" ? LOC_LABEL[place.slug] : undefined) ?? place.display;

/* The two headings RoleBand writes itself, by the key and the stored English
 * the connectors write together (`clean_section("job_description", "Job
 * description", ...)`). A stored heading is matched exactly, so an employer's
 * own "Compensation" under another key stays theirs. */
const OWN_HEADINGS: Record<string, string> = {
  "job_description\nJob description": "job-description", /* not copy */
  "pay_and_benefits\nCompensation": "compensation", /* not copy */
};

/** RoleBand's own heading for a section, from the catalog; null for an
 *  employer's, which is shown as written (`ui/Content`). */
export function ownHeading(key: string | null | undefined, title: string): string | null {
  const own = OWN_HEADINGS[`${key ?? ""}\n${title}`];
  return own ? say("section", own) : null;
}

/** A description section's heading as text (an accessible name): RoleBand's
 *  own named from the catalog, an employer's as written. */
export const sectionTitle = (key: string | null | undefined, title: string): string => ownHeading(key, title) ?? title;
