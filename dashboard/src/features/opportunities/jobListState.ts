import type { Job, JobList } from "../../api";

/** Exact rows and related rows are distinct arrays in one response. */
export function patchJob(list: JobList, id: number, patch: Partial<Job>): JobList {
  return {
    ...list,
    items: list.items.map((job) => job.id === id ? { ...job, ...patch } : job),
    related_items: list.related_items?.map((job) => job.id === id ? { ...job, ...patch } : job),
  };
}

/** A level the Board places: anything but "none" (states no level) and
 * "unmapped" (states one we cannot place). A null basis is placed by its band. */
function isPlaced(job: Job): boolean {
  return job.level_basis !== "none" && job.level_basis !== "unmapped";
}

/** Only decrement the section that actually loses a row. A repeated/stale
 * removal must not consume another related role's count. Best fit's
 * `placed_total` is an index into the exact rows: a dismissed
 * placed row leaves that group too, or the "Level not placed" head draws one
 * row late and its count one short. */
export function removeJob(list: JobList, id: number): JobList {
  const removed = list.items.find((job) => job.id === id);
  const primary = removed != null;
  const related = list.related_items?.some((job) => job.id === id);
  return {
    ...list,
    items: list.items.filter((job) => job.id !== id),
    related_items: list.related_items?.filter((job) => job.id !== id),
    total: primary ? Math.max(0, list.total - 1) : list.total,
    placed_total: primary && list.placed_total != null && isPlaced(removed)
      ? Math.max(0, list.placed_total - 1) : list.placed_total,
    related_total: related && list.related_total != null
      ? Math.max(0, list.related_total - 1) : list.related_total,
  };
}
