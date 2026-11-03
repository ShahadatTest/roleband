import { LOC_LABEL, isMetro } from "../../format";

/** The taxonomy places a job falls in (metro, country, region), without the
    GeoNames city slugs stored after them (`city_<geonameid>`): the
    city is already the job's own location text, and a badge would repeat it
    by a code. */
export function placeGroups(slugs: readonly string[]): string[] {
  return slugs.filter((slug) => !slug.startsWith("city_"));
}

/** The place groups worth a tag beside a posting's own place text: only what
    that text does not already say. A country or region is read from the text,
    so its tag would repeat it; a metro area is not ("Sunnyvale" lies in
    Silicon Valley), unless the text names it too ("London, UK"). */
export function placeGroupsBeyond(slugs: readonly string[], places: readonly string[]): string[] {
  const text = places.join(" ").toLowerCase();
  return slugs.filter((slug) => isMetro(slug) && !text.includes(LOC_LABEL[slug].toLowerCase()));
}
