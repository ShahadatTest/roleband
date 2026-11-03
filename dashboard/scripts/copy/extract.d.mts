// Types for the copy extractor, for the tests that drive it.
export interface Extracted { file: string; line: number; kind: string; text: string; parts: number; moduleScope: boolean }
export function sourceFiles(src: string): string[];
export interface Habit { file: string; line: number; habit: string; text: string }
export function extractStrings(src: string): Extracted[];
export function extractSource(src: string): { strings: Extracted[]; habits: Habit[] };
export function extractFile(rel: string, text: string): { sf: unknown; strings: (Extracted & { node: unknown })[]; habits: Habit[] };
export function fileHabits(src: string): [string, Record<string, number>][];
