// Types for the copy compiler, for the tests that drive it.
import type { readLocale } from "./copy/catalog.mjs";
export class CopyError extends Error {}
export function metadata(comment: string | null | undefined): Record<string, string>;
export function build(options?: { root?: string; gen?: string; runtime?: string; twin?: boolean; catalogs?: Map<string, ReturnType<typeof readLocale>> }): {
  files: Map<string, string>;
  report: string[];
  ids: string[];
};
export function write(files: Map<string, string>, options?: { check?: boolean; gen?: string | null }): string[];
export function flatten(pattern: unknown, terms: Map<string, unknown>): string;
