/* The row's city line. A posting's `locations` is what the source
 * published, and sources publish a run of cities in ONE string ("San
 * Francisco, CA | New York City, NY"; "A; B") and then the same cities again
 * as entries of their own. A column cannot hold that, and truncating it
 * throws away the one fact the cell exists for. The row shows
 * the FIRST city and how many others there are; the caller puts the whole
 * list where a reader can reach it (the cell's tooltip, and text for
 * assistive tech). Order is the source's, so the first city is the one the
 * posting led with; a city named twice counts once.
 *
 * Here and not in `format.ts`: that module is in the app shell's chunk, and
 * a helper only the row reads would be paid for on every route (the shell's
 * bundle gate holds its ceiling to the byte). */
export function primaryLocation(locations: readonly string[]): { city: string | null; others: string[] } {
  const [city = null, ...others] = postingPlaces(locations);
  return { city, others };
}

/* Every place a posting names, once each, in the source's order and wording:
 * the joined strings split, the repeats dropped. Every surface that lists a
 * posting's places reads this, never `locations` itself, which can name the
 * same city twice. */
export function postingPlaces(locations: readonly string[]): string[] {
  const seen: string[] = [];
  for (const raw of locations) {
    for (const part of raw.split(/\s*[|;]\s*/)) {
      const place = part.trim();
      if (place && !seen.includes(place)) seen.push(place);
    }
  }
  return seen;
}
