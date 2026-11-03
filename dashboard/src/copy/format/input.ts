/* Formatting implementation. Public API: ../format.ts. */
import {regionTag} from "../runtime";
import {intl} from "./core";



/** Read a number typed the way the region writes it ("250,000", "250 000",
 *  "1.234,5"). NaN when it is not one. */
export function parseNumber(text: string): number {
  const nf = intl(Intl.NumberFormat, regionTag());
  const parts = nf.formatToParts(123456789.5);
  const group = parts.find(p => p.type === "group")?.value;
  const decimal = parts.find(p => p.type === "decimal")?.value ?? ".";
  const integers = parts.filter(p => p.type === "integer").map(p => [...p.value].length);
  const primary = integers[integers.length-1] ?? 3, secondary = integers[integers.length-2] ?? primary;
  let input = text.trim().replace(/[\u061c\u200e\u200f]/g, "");
  for (let n = 0; n <= 9; n++) input = input.split(nf.format(n)).join(String(n));
  const minus = nf.formatToParts(-1).find(p => p.type === "minusSign")?.value ?? "-";
  const negative = input.startsWith(minus);
  if (negative) input = input.slice(minus.length);
  const fractions = input.split(decimal);
  if (fractions.length > 2 || (fractions.length === 2 && !/^\d+$/.test(fractions[1]))) return Number.NaN;
  const groups = group ? fractions[0].split(group) : [fractions[0]];
  if (groups.length > 1 && (groups[groups.length-1].length !== primary || groups[0].length < 1 || groups[0].length > secondary || groups.slice(1,-1).some(g => g.length !== secondary))) return Number.NaN;
  if (!groups.every(g => /^\d+$/.test(g)) && !(groups.length === 1 && groups[0] === "" && fractions.length === 2)) return Number.NaN;
  const value = Number(`${negative ? "-" : ""}${groups.join("") || "0"}${fractions.length === 2 ? `.${fractions[1]}` : ""}`);
  return Number.isFinite(value) ? value : Number.NaN;
}
