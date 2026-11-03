import { describe, expect, it } from "vitest";
import { jobFixture, jobListFixture } from "../../test/fixtures";
import { patchJob, removeJob } from "./jobListState";

const direct = { ...jobListFixture, total: 1, items: [{ ...jobFixture, id: 101 }],
  related_total: 41, related_items: [{ ...jobFixture, id: 202 }], query_kind: "identifier" as const };

describe("Board optimistic list state", () => {
  it("patches favorites in both sections without changing counts or unrelated rows", () => {
    for (const id of [101, 202]) {
      const patched = patchJob(direct, id, { is_favorite: true });
      expect([...patched.items, ...patched.related_items!].find((job) => job.id === id)?.is_favorite).toBe(true);
      expect(patched.total).toBe(1);
      expect(patched.related_total).toBe(41);
    }
    expect(direct.items[0].is_favorite).toBe(jobFixture.is_favorite);
  });

  it("removing the last exact row preserves related rows and their count", () => {
    const removed = removeJob(direct, 101);
    expect(removed.items).toEqual([]);
    expect(removed.total).toBe(0);
    expect(removed.related_items).toEqual(direct.related_items);
    expect(removed.related_total).toBe(41);
  });

  it("removing a related row never decrements the exact count, even if repeated", () => {
    const removed = removeJob(direct, 202);
    expect(removed.total).toBe(1);
    expect(removed.items).toEqual(direct.items);
    expect(removed.related_total).toBe(40);
    expect(removed.related_items).toEqual([]);
    expect(removeJob(removed, 202).related_total).toBe(40);
    expect(removeJob(direct, 999)).toEqual(direct);
  });

  /* Best fit heads the roles at a level we cannot place with "Level not
     placed" at index placed_total. The list closes up locally on a
     dismissal, so the index must follow the row that left. */
  it("a dismissed placed row leaves the placed group; an unplaced one does not", () => {
    const placed = { ...jobFixture, id: 1, level_basis: "company" };
    const legacy = { ...jobFixture, id: 2, level_basis: null };
    const unplaced = { ...jobFixture, id: 3, level_basis: "unmapped" };
    const bestFit = { ...jobListFixture, total: 3, placed_total: 2, items: [placed, legacy, unplaced] };

    expect(removeJob(bestFit, 1).placed_total).toBe(1);
    expect(removeJob(bestFit, 2).placed_total).toBe(1);
    expect(removeJob(bestFit, 3).placed_total).toBe(2);
    expect(removeJob(bestFit, 3).total).toBe(2);
    expect(removeJob({ ...bestFit, placed_total: undefined }, 1).placed_total).toBeUndefined();
  });
});
