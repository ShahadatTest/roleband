import { afterEach, describe, expect, it, vi } from "vitest";
import { lineageApi } from "./lineage";

/* A verdict keeps a link's confidence, so a pair decided from "Matched
   automatically" is still `auto`. The routes default to `suspected`; a
   Decided list that left the filter on would never show that pair again.
   The list reads the summary form (`detail=false`): a closed row needs no
   description, and the full form would read and compare every pair's. */

afterEach(() => vi.restoreAllMocks());

describe("the Decided list", () => {
  it("asks both tables for every verdict, whatever its confidence, in the summary form", async () => {
    const fetched = vi.spyOn(globalThis, "fetch").mockImplementation(async () =>
      new Response(JSON.stringify({ total: 0, limit: 200, offset: 0, items: [] }), {
        status: 200, headers: { "content-type": "application/json" },
      }));
    await lineageApi.lineageReviewHistory(200);
    await lineageApi.twinReviewHistory(200);

    const asked = fetched.mock.calls.map(([input]) => new URL(String(input), "http://roleband.test"));
    expect(asked.map((url) => url.pathname)).toEqual(["/api/lineage/review", "/api/twins/review"]);
    for (const url of asked) {
      expect(url.searchParams.get("status")).toBe("reviewed");
      expect(url.searchParams.get("confidence")).toBe("");
      expect(url.searchParams.get("limit")).toBe("200");
      expect(url.searchParams.get("detail")).toBe("false");
    }
  });
});
