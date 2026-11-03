export interface ModuleInfo { bytes: number; exports: string[]; lazyImporters?: string[] }
export interface Pair { module: string; export?: string; lazyImporters: string[] }
export interface Confined { dir: string; allow: string[]; why: string }
export interface Boundary { confined?: Confined[]; infrastructure: { module: string; exports?: string[]; why: string }[]; debt: { module: string; export?: string }[] }
export function driftProblems(measured: { js: number; css: number }, recorded: { js: number; css: number; slack: number; cap: number }): string[];
export function moduleDelta(now: Record<string, { bytes: number }>, recorded: Record<string, { bytes: number }>): { module: string; before: number; after: number; delta: number }[];
export function lazyOnly(full: Record<string, ModuleInfo>, stubbed: Record<string, ModuleInfo>): Pair[];
export interface Snapshot { [module: string]: { bytes: number; exports: string[]; shell: string[] | null } }
export function snapshotOf(full: Record<string, ModuleInfo>, stubbed: Record<string, ModuleInfo>): Snapshot;
export function boundaryProblems(found: Pair[], boundary: Boundary, recorded: Partial<Snapshot>): { failures: string[]; warnings: string[]; stale: string[]; shed: { module: string; export?: string }[] };
export function confinementProblems(full: Record<string, ModuleInfo>, confined?: Confined[]): string[];
