import type { readLocale } from "./copy/catalog.mjs";
// Types for the copy linter, for its test.
export const SRC: string;
export const COPY: string;
export const BASELINE: string;
export const AS_FOUND: string;
export function asFound(src?: string, backendRoot?: string): string[];
export function pythonStrings(root: string): string[];
export function area(file: string): string;
export function totals(byArea: Record<string, Record<string, number>>): Record<string, number>;
export function glossary(locale: string, root?: string): Record<string, unknown>;
export function textProblems(text: string, rules: Record<string, unknown>, options?: { withTerms?: boolean }): [string, string][];
export function sourceHash(msg: { src: string; pattern: { span: { start: number; end: number } } }): string;
export function recordTranslated(root: string, locale: string, ids?: string[]): { recorded: string[]; dropped: string[] };
export function checkCatalog(root?: string, asFoundPath?: string, catalogs?: Map<string, ReturnType<typeof readLocale>>): { blocking: string[]; reports: string[]; diagnostics: {locale:string|null;id:string|null;file:string|null;line:number|null;severity:string;rule:string;detail:string}[]; messages: number; asIs: number };
export function checkLiterals(src?: string): string[];
export function counts(src?: string): Record<string, Record<string, number>>;
export function checkSource(src?: string): { literals: string[]; counts: Record<string, Record<string, number>>; habits: import("./copy/extract.mjs").Habit[] };

export function ratchetProblems(now:Record<string,Record<string,number>>,literals:string[],base:{counts:Record<string,Record<string,number>>;literals:string[]}):string[];
export function migrateFingerprints(root:string,locale:string):void;
