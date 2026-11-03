import { activate } from "./copy/activate";
import { afterEach, describe, expect, it } from "vitest";
import { fmtComp } from "./format";
import { fmtCompIn, fmtMoney } from "./money";

afterEach(() => activate("en"));

describe("money in its own currency", () => {
  it("writes a stated band compact, with the sign of the currency it was stated in", () => {
    expect(fmtCompIn(120000, "GBP")).toBe("£120K");
    expect(fmtCompIn(104800, "EUR")).toBe("€105K");
    expect(fmtCompIn(250000, "CHF")).toBe("CHF\u00a0250K");
    expect(fmtCompIn(1250000, "GBP")).toBe("£1.25M");
    // Dollars read exactly as our own estimates do, so one panel has one format.
    for (const n of [950, 650000, 1250000, 1000000]) expect(fmtCompIn(n, "USD")).toBe(fmtComp(n));
  });

  it("says back a typed amount in full, in its currency", () => {
    expect(fmtMoney(250000, "USD")).toBe("$250,000");
    expect(fmtMoney(180000, "GBP")).toBe("£180,000");
  });
});

it("currency and K/M precision survive a region switch", async () => {
  await activate("es", { region: "es-ES" });
  expect(fmtMoney(250000,"USD")).toBe("250.000 US$");
  expect(fmtCompIn(1250000,"EUR")).toBe("1,25M €");
  expect(fmtCompIn(1000000,"EUR")).toBe("1M €");
  await activate("en", { region: "en-GB" });
  expect(fmtCompIn(1250000,"GBP")).toBe("£1.25M");
});
