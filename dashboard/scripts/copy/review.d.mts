// Types for the copy review deck's data, for its tests.
import type { Message } from "./catalog.mjs";

export function samples(msg: Message): Record<string, string | number>[];
export function usageIndex(messages: Message[], src?: string): Record<string, { file: string; line: number; mode: string }[]>;
export function changedMessages(ref: string, root?: string): { changed: { id: string; terms: string[] }[]; removed: string[] };
export function reviewData(root?: string, src?: string): any;
export function recordReview(root: string, code: string, ids: string[]): void;
