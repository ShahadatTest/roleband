// The formatting module: region decides numbers and dates, language decides
// words. Literal expectations, so a broken Intl wiring cannot pass by agreeing
// with itself.
import { afterEach, describe, expect, it } from "vitest";
import { activate } from "./activate";
import { compare, country, date, duration, list, money, number, parseNumber, percent } from "./format";

const APRIL_12 = "2026-04-12T15:00:00Z";
afterEach(() => activate("en"));

describe("numbers follow the region", () => {
  it("rejects misplaced separators and reads regional numerals and grouping", async () => {
    await activate("en", { region: "en-US" });
    for (const bad of ["2,50,000", "1,,000", "1 2", "1.2.3", "1,000,", ""]) expect(parseNumber(bad)).toBeNaN();
    await activate("en", { region: "en-IN" });
    expect(parseNumber("12,34,567.5")).toBe(1234567.5);
    expect(parseNumber("1,234,567.5")).toBeNaN();
    await activate("en", { region: "ar-EG" });
    expect(parseNumber(number(-1234.5))).toBe(-1234.5);
    await activate("en", { region: "fr-FR" });
    expect(parseNumber(number(1234.5))).toBe(1234.5);
    expect(parseNumber("1.234,5")).toBeNaN();
  });
  it("writes and reads them the region's way", async () => {
    await activate("en", { region: "en-US" });
    expect(number(1234.5)).toBe("1,234.5");
    expect(parseNumber("250,000")).toBe(250000);
    // English words, Spanish digits: the region decides, not the language.
    await activate("en", { region: "es-ES" });
    expect(number(1234567.5)).toBe("1.234.567,5");
    expect(parseNumber("1.234,5")).toBe(1234.5);
    await activate("es", { region: "es-ES" });
    expect(number(1234567.5)).toBe("1.234.567,5");
    expect(parseNumber("250.000")).toBe(250000);
    await activate("zh-Hans", { region: "zh-CN" });
    expect(number(1234567.5)).toBe("1,234,567.5");
    expect(parseNumber("about 3")).toBeNaN();
  });

  it("money keeps its currency and shortens on request", async () => {
    await activate("en", { region: "en-US" });
    expect(money(250000)).toBe("$250,000");
    expect(money(132000, "USD", { compact: true })).toBe("$132K");
    expect(percent(0.48)).toBe("48%");
  });
});

describe("dates take the language's words in the region's order", () => {
  it("12 Apr or Apr 12 is the region, not the language", async () => {
    await activate("en", { region: "en-US" });
    expect(date(APRIL_12, "day")).toBe("Apr 12");
    await activate("en", { region: "en-GB" });
    expect(date(APRIL_12, "day")).toBe("12 Apr");
    await activate("es", { region: "es-ES" });
    expect(date(APRIL_12, "day")).toBe("12 abr");
    await activate("zh-Hans", { region: "zh-CN" });
    expect(date(APRIL_12, "day")).toBe("4月12日");
  });
});

describe("words follow the language", () => {
  it("joins, names and sorts in the screen's language", async () => {
    await activate("en", { region: "en-GB" });
    expect(list(["Apple", "Stripe", "Meta"])).toBe("Apple, Stripe and Meta");
    expect(list(["Apple", "Stripe"], "or")).toBe("Apple or Stripe");
    await activate("en", { region: "en-US" });
    expect(list(["Apple", "Stripe", "Meta"])).toBe("Apple, Stripe, and Meta");
    await activate("en", { region: "en-GB" });
    expect(country("de")).toBe("Germany");
    expect(duration(3 * 60 + 12)).toBe("3 min, 12 sec");
    await activate("es", { region: "en-GB" });
    expect(list(["Apple", "Stripe", "Meta"])).toBe("Apple, Stripe y Meta");
    expect(country("de")).toBe("Alemania");
    expect(["oso", "ñu", "nube"].sort(compare)).toEqual(["nube", "ñu", "oso"]);
    await activate("zh-Hans", { region: "en-GB" });
    expect(list(["Apple", "Stripe", "Meta"])).toBe("Apple、Stripe和Meta");
    expect(country("de")).toBe("德国");
    // Chinese sorts by pinyin: li, wang, zhang.
    expect(["张", "李", "王"].sort(compare)).toEqual(["李", "王", "张"]);
  });
});

describe("the pseudo locale marks every formatted value", () => {
  it("brackets output so a value formatted elsewhere shows", async () => {
    await activate("en-XA");
    expect(number(3)).toBe("⟦3⟧");
    expect(date(APRIL_12, "full")).toMatch(/^⟦.+⟧$/);
  });
});
