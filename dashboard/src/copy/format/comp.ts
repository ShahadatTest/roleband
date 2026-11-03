/* Formatting implementation. Public API: ../format.ts. */
import {regionTag} from "../runtime";
import {number} from "./basic";
import {intl, mark} from "./core";



/** Compact comp keeps its existing K/M units and precision; digits and
 * currency placement follow the region. No conversion or annualization. */
export function compactMoney(amount: number, currency = "USD"): string {
  const divisor = amount >= 1_000_000 ? 1_000_000 : amount >= 1000 ? 1000 : 1;
  const value = divisor === 1000 ? Math.round(amount / divisor) : divisor === 1_000_000 ? Number((amount / divisor).toFixed(2)) : amount;
  const digits = divisor === 1_000_000 ? (Number.isInteger(value) ? 0 : 2) : 0;
  const suffix = divisor === 1_000_000 ? "M" : divisor === 1000 ? "K" : "";
  try {
    const parts = intl(Intl.NumberFormat, regionTag(), { style: "currency", currency, minimumFractionDigits: digits, maximumFractionDigits: divisor === 1 ? 20 : digits }).formatToParts(value);
    let lastNumber = -1;
    parts.forEach((p,i) => { if (["integer","group","decimal","fraction"].includes(p.type)) lastNumber=i; });
    return mark(parts.map((p,i) => p.value + (i === lastNumber ? suffix : "")).join(""));
  } catch { return mark(`${number(value,{maximumFractionDigits:digits})}${suffix} ${currency}`); }
}
