import { describe, expect, it } from "vitest";
import { type LedgerRow, MIN_RUN, groupLedger, rowDiffers } from "./ledger";

type Item = Record<string, string>;
const row = (key: string, collapsible = true): LedgerRow<Item> => ({ key, label: key, diff: (item) => item[key], collapsible });
const shape = (groups: ReturnType<typeof groupLedger<Item, LedgerRow<Item>>>) =>
  groups.map((g) => (g.kind === "row" ? g.row.key : `[${g.rows.map((r) => r.key).join(",")}]`));

const a = { title: "A", level: "staff", place: "SF", team: "x", pay: "1", link: "u1" };
const b = { title: "B", level: "staff", place: "SF", team: "x", pay: "2", link: "u2" };

describe("the ledger's one folding rule", () => {
  it("folds a run of agreeing rows and leaves what differs at full size", () => {
    const rows = [row("title"), row("level"), row("place"), row("team"), row("pay")];
    expect(shape(groupLedger(rows, [a, b]))).toEqual(["title", "[level,place,team]", "pay"]);
  });

  it("folds from MIN_RUN on, and a lone agreeing row stays a row", () => {
    expect(MIN_RUN).toBe(2);
    expect(shape(groupLedger([row("level"), row("place"), row("pay")], [a, b]))).toEqual(["[level,place]", "pay"]);
    expect(shape(groupLedger([row("level"), row("pay"), row("place")], [a, b]))).toEqual(["level", "pay", "place"]);
  });

  it("never folds a row marked not collapsible, and it breaks the run around it", () => {
    const rows = [row("level"), row("team", false), row("place")];
    expect(shape(groupLedger(rows, [a, b]))).toEqual(["level", "team", "place"]);
  });

  it("reads agreement across every column, not just the first two", () => {
    const c = { ...b, place: "NYC" };
    expect(rowDiffers(row("place"), [a, b])).toBe(false);
    expect(rowDiffers(row("place"), [a, b, c])).toBe(true);
    expect(shape(groupLedger([row("level"), row("place"), row("team")], [a, b, c]))).toEqual(["level", "place", "team"]);
  });
});
