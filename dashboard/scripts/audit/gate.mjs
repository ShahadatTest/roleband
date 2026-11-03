// The decisions of the dependency audit gate (scripts/audit-gate.mjs), apart
// from running npm so a test can feed them a report.

const RANK = { info: 0, low: 1, moderate: 2, high: 3, critical: 4 };
/** The lowest severity that fails the gate. */
export const FLOOR = "high";
const FIELDS = ["id", "package", "reason", "expires"];

function advisoryId(via) {
  const ghsa = /GHSA(?:-[0-9a-z]{4}){3}/i.exec(via.url ?? "");
  return ghsa ? ghsa[0] : String(via.source);
}

/**
 * Every advisory at or above FLOOR in an `npm audit --json` report, once per
 * package and advisory. A package's `via` lists its own advisories as objects
 * and, as plain names, the packages it inherits one from; each inherited
 * advisory is listed again under the package it belongs to, so the names are
 * skipped here.
 */
export function findingsOf(report) {
  const out = new Map();
  for (const entry of Object.values(report.vulnerabilities ?? {})) {
    for (const via of entry.via ?? []) {
      if (typeof via !== "object" || (RANK[via.severity] ?? 0) < RANK[FLOOR]) continue;
      const id = advisoryId(via);
      out.set(`${via.name}\u0000${id}`, { package: via.name, id, severity: via.severity, title: via.title ?? "" });
    }
  }
  return [...out.values()];
}

/**
 * What fails the gate, one line each; empty when it passes. `today` and every
 * `expires` are YYYY-MM-DD, so they compare as strings.
 */
export function auditProblems(found, exceptions, today) {
  const out = [];
  const valid = [];
  exceptions.forEach((entry, i) => {
    const missing = FIELDS.filter((f) => !entry[f]);
    if (missing.length) out.push(`exception #${i + 1} (${entry.id ?? "?"}): missing ${missing.join(", ")}`);
    else if (!/^\d{4}-\d{2}-\d{2}$/.test(entry.expires)) out.push(`exception ${entry.id}: expires must be YYYY-MM-DD`);
    else valid.push(entry);
  });
  const used = new Set();
  for (const f of found) {
    const match = valid.findIndex((e) => e.id === f.id && e.package === f.package);
    if (match < 0) {
      out.push(`${f.package}: ${f.id} (${f.severity}) ${f.title}; upgrade it, or add a reviewed exception`);
      continue;
    }
    used.add(match);
    if (valid[match].expires < today) out.push(`${f.package}: exception ${f.id} expired on ${valid[match].expires}`);
  }
  valid.forEach((e, i) => {
    if (!used.has(i)) out.push(`exception ${e.id} (${e.package}) matches no finding; remove it`);
  });
  return out;
}
