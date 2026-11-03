// Canonical URL for an individual position (job). A position is a sub-resource
// of its company, so it nests under the company path — every position is tied to
// its company through the link (`/company/google/job/123`). Singular segments:
// each names one entity (the company, the job).
export const POSITION_ROUTE = "/company/:slug/job/:id";

export function positionPath(companySlug: string, id: number | string): string {
  return `/company/${encodeURIComponent(companySlug)}/job/${id}`;
}

/** One key per position, whichever URL names it, or null for any other path.
 *  A short /job/:id, or a position under the wrong company, rewrites itself
 *  to `positionPath` once the job loads; a key that changed with that rewrite
 *  would remount the detail and fetch all of it again. */
export function positionKey(pathname: string): string | null {
  const id = /^(?:\/company\/[^/]+)?\/job\/([^/]+)\/?$/.exec(pathname)?.[1];
  return id ? `position:${id}` : null;
}

/** The page a cover opens OVER. A cover never stacks on a role: opened from a
 *  role cover it reuses that cover's background, so Back lands on the list.
 *  A comparison is the one exception a role may stack on (`openJob`), because
 *  a reader who opens a column expects Back to return to the comparison. */
export function coverBackground(location: { pathname: string; state: unknown }): unknown {
  const behind = (location.state as { backgroundLocation?: unknown } | null)?.backgroundLocation;
  return behind ?? location;
}

export const COMPARE_ROUTE = "/compare";
