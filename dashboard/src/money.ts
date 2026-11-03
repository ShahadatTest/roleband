/* Money in its stated currency; comp precision remains the existing contract. */
import { compactMoney, money, number } from "./copy/format";
export function fmtComp(n: number | null | undefined): string { return n == null ? "—" : compactMoney(n); }
export function fmtRange(low: number | null, high: number | null, median: number | null): string {
  if (low != null && high != null) return `${fmtComp(low)}–${fmtComp(high)}`;
  if (median != null) return fmtComp(median);
  return "—";
}
export const fmtCompIn = (amount: number, currency: string): string => compactMoney(amount, currency);
export function fmtMoney(amount: number, currency: string): string {
  try { return money(amount,currency); }
  catch { return `${number(amount)} ${currency}`; }
}
