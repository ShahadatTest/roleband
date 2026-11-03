import { describe, expect, it } from "vitest";
import type { Job } from "../../api";
import { jobFixture } from "../../test/fixtures";
import { columnDescriptions, nothingShared, nothingToRead } from "./descriptions";

/* The three-column model. Two rules a reader relies on without
   seeing them: each column keeps its posting's own order — employers do not
   share section keys, so nothing is realigned — and "unique" means not in
   EVERY column, judged across the whole posting rather than section by
   section. At two columns that is Review's pairwise rule. */

const withSections = (id: number, sections: { key: string; title: string; content: string }[]): Job => ({
  ...jobFixture,
  id,
  description_sections: sections,
});
const plain = (id: number, text: string | null): Job => ({ ...jobFixture, id, description_sections: undefined, description_text: text });

describe("columnDescriptions", () => {
  it("keeps each posting's own sections in its own order", () => {
    const a = withSections(1, [{ key: "summary", title: "Summary", content: "x" }, { key: "quals", title: "Qualifications", content: "y" }]);
    const b = withSections(2, [{ key: "basic", title: "Basic Qualifications", content: "y" }, { key: "pay", title: "Pay", content: "z" }]);
    const [one, two] = columnDescriptions([a, b]);
    expect(one.sections.map((s) => s.title)).toEqual(["Summary", "Qualifications"]);
    expect(two.sections.map((s) => s.title)).toEqual(["Basic Qualifications", "Pay"]);
  });

  it("judges sharedness across the whole posting, not within a matching section", () => {
    const a = withSections(1, [{ key: "quals", title: "Qualifications", content: "Ten years." }]);
    const b = withSections(2, [{ key: "basic", title: "Basic Qualifications", content: "- ten years." }]);
    const [one, two] = columnDescriptions([a, b]);
    expect(one.sections[0].passages[0].unique).toBe(false);
    expect(two.sections[0].passages[0].unique).toBe(false);
    expect(one.sections[0].shared).toBe(1);
  });

  it("marks a passage unique when any column lacks it, shared only when every column has it", () => {
    const [one, two, three] = columnDescriptions([
      plain(1, "Shared line.\nIn one and two.\nOnly one."),
      plain(2, "Shared line.\nIn one and two."),
      plain(3, "- shared   line."),
    ]);
    expect(one.sections[0].passages.map((p) => p.unique)).toEqual([false, true, true]);
    expect(two.sections[0].passages.map((p) => p.unique)).toEqual([false, true]);
    // Case, a bullet and spacing do not make a different passage (blockKey).
    expect(three.sections[0].passages.map((p) => p.unique)).toEqual([false]);
    expect([one, two, three].map((c) => c.sections[0].shared)).toEqual([1, 1, 1]);
  });

  it("at two columns is the pairwise rule: unique means not in the other posting", () => {
    const [one, two] = columnDescriptions([plain(1, "A.\nB."), plain(2, "B.\nC.")]);
    expect(one.sections[0].passages.map((p) => [p.text, p.unique])).toEqual([["A.", true], ["B.", false]]);
    expect(two.sections[0].passages.map((p) => [p.text, p.unique])).toEqual([["B.", false], ["C.", true]]);
  });

  it("says when there is nothing to read at all, but not when one column is merely empty", () => {
    expect(nothingToRead(columnDescriptions([plain(1, null), plain(2, "")]))).toBe(true);
    expect(nothingToRead(columnDescriptions([plain(1, "Something."), plain(2, null)]))).toBe(false);
  });

  it("knows when nothing is shared at all, so marking everything can be declined", () => {
    expect(nothingShared(columnDescriptions([plain(1, "A."), plain(2, "B.")]))).toBe(true);
    expect(nothingShared(columnDescriptions([plain(1, "A.\nB."), plain(2, "B.")]))).toBe(false);
  });
});
