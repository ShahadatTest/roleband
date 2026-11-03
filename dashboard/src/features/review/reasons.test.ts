import { describe, expect, it } from "vitest";
import { msg } from "../../test/msg";
import { reasonsText } from "./reasons";

/* The detector's reasons reach the reader as catalog words, never its English
 * or its method names (`title+embedding`, `title_jaccard`). */
describe("why two postings were paired", () => {
  it("says each code in the reader's words, with its figures", () => {
    expect(reasonsText([
      { code: "same_title", params: {} },
      { code: "descriptions_alike", params: { pct: 93 } },
      { code: "passages_differ", params: { earlier: 2, later: 3 } },
    ])).toEqual([
      msg("duplicates-reason-same-title"),
      msg("duplicates-reason-descriptions-alike", { pct: 93 }),
      msg("duplicates-reason-passages-differ", { earlier: 2, later: 3 }),
    ]);
    expect(msg("duplicates-reason-descriptions-alike", { pct: 93 })).toBe("Descriptions 93% alike");
  });

  it("leaves a code this build does not know, or one missing its figure, unsaid", () => {
    expect(reasonsText([{ code: "cosine_above_floor", params: {} }, { code: "titles_alike", params: {} }])).toEqual([]);
  });
});
