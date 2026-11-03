import type { ModuleInfo } from "./gate.mjs";
export function startupOf(chunks: unknown[], root?: string, importersOf?: (id: string) => readonly string[] | undefined): { entry: string; js: string[]; css: string[]; modules: Record<string, ModuleInfo> };
