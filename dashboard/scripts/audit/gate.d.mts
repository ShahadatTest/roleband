export interface Finding { package: string; id: string; severity: string; title: string }
export interface AuditException { id?: string; package?: string; reason?: string; expires?: string }
export const FLOOR: string;
export function findingsOf(report: { vulnerabilities?: Record<string, { via?: unknown[] }> }): Finding[];
export function auditProblems(found: Finding[], exceptions: AuditException[], today: string): string[];
