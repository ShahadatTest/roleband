// Generates the dashboard's Simple Icons artifacts. Three outputs, because a
// company can arrive two ways and only one of them is known at build time:
//
//   brandIcons.gen.ts          eager  the catalog's own marks
//   brandIconManifest.gen.ts   eager  every slug upstream carries, no paths
//   brandIconShards/<c>.gen.ts lazy   one chunk per first character, fetched on demand
//
// A company added through Settings -> "Add a company by URL" is a database row,
// not a catalog entry, so no build-time generation can ever see it. Shipping
// every mark eagerly would load megabytes that are almost all unused.
//
// The manifest is what makes the lazy path cheap: it answers "does a mark exist
// at all?" offline, so Amazon — absent upstream, and in the default catalog —
// falls straight to a monogram instead of pulling a shard to discover nothing.
// Only a slug the manifest confirms triggers a fetch.
//
// `simple-icons` therefore stays a devDependency: everything ships pre-generated
// and the app makes no network call to a third party.
//
// The emitted file is keyed by SIMPLE ICONS SLUG, never by a RoleBand company
// slug, and carries no company facts. That is deliberate — `src/companies.json`
// stays the dashboard's only per-company literal, and this
// file stays what it is: a vendored slice of a third-party icon set. Company ->
// mark resolution happens at runtime in `brandIcons.ts` against the catalog the
// API already serves.
//
// Run: npm run gen:brand-icons
import { mkdirSync, readFileSync, readdirSync, rmSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import * as simpleIcons from "simple-icons";

const HERE = dirname(fileURLToPath(import.meta.url));
const REPO = resolve(HERE, "../..");
const OUT = resolve(HERE, "../src/ui/brandIcons.gen.ts");

const SOURCES = [
  resolve(REPO, "backend/tracker/company_discovery.py"),
  resolve(REPO, "backend/tracker/company_catalog.py"),
  resolve(REPO, "backend/tracker/blueprint.py"),
];

// Shared with the runtime resolver (src/ui/brandIcons.ts) so build-time matching
// and runtime lookup cannot disagree.
const { _comment, ...ALIASES } = JSON.parse(
  readFileSync(resolve(HERE, "../src/ui/brandAliases.json"), "utf8"),
);

const norm = (s) => s.toLowerCase().replace(/&/g, "and").replace(/[^a-z0-9]/g, "");

// Index every icon by slug, normalized title, and normalized aliases.
const index = new Map();
// Marks the app never shows and must not carry: outside pay sources, which only
// plugins reach. A plugin's own name is its text, not a mark.
// Spelled from parts, as `backend/tests/vendor_names.py` does: the release gate
// fails a tracked file that names an outside source, and a slug is a name.
const EXCLUDED = new Set([["levels", "dot", "fyi"].join("")]);
const icons = Object.values(simpleIcons).filter((i) => i && i.slug && i.path && !EXCLUDED.has(i.slug));
for (const icon of icons) {
  const keys = new Set([icon.slug, norm(icon.title)]);
  for (const alt of icon.aliases?.aka ?? []) keys.add(norm(alt));
  for (const key of keys) if (!index.has(key)) index.set(key, icon);
}

// An alias pointing at a mark upstream does not have is silent data rot: the
// company just falls back to a monogram and nothing says why. Fail loudly.
const deadAliases = Object.entries(ALIASES).filter(([, icon]) => !index.has(icon));
if (deadAliases.length) {
  throw new Error(
    `brandAliases.json points at ${deadAliases.length} Simple Icons slug(s) that do not exist: ` +
      deadAliases.map(([co, icon]) => `${co} -> ${icon}`).join(", "),
  );
}

// Pull (slug, display) pairs out of the backend catalogs. Three shapes:
//   _c("slug", "Display", ...)              company_discovery.py
//   "slug": {"display": "Display", ...}     company_catalog.py
//   "slug": CompanyBlueprint("slug", "Display", ...)   blueprint.py
const companies = new Map();
for (const file of SOURCES) {
  const src = readFileSync(file, "utf8");
  const patterns = [
    /_c\(\s*"([a-z0-9_-]+)"\s*,\s*"([^"]+)"/g,
    /"([a-z0-9_-]+)":\s*\{\s*"display":\s*"([^"]+)"/g,
    /"([a-z0-9_-]+)":\s*CompanyBlueprint\(\s*"[a-z0-9_-]+"\s*,\s*"([^"]+)"/g,
  ];
  for (const re of patterns) {
    for (const [, slug, display] of src.matchAll(re)) {
      if (!companies.has(slug)) companies.set(slug, display);
    }
  }
}

if (companies.size === 0) {
  throw new Error("no companies parsed from backend catalogs — refusing to emit an empty icon set");
}

const matched = new Map();
const missing = [];
for (const [slug, display] of [...companies].sort()) {
  const candidates = [ALIASES[slug], slug, norm(slug), norm(display)].filter(Boolean);
  const icon = candidates.map((c) => index.get(c)).find(Boolean);
  if (icon) matched.set(icon.slug, icon);
  else missing.push(`${slug} (${display})`);
}

const rows = [...matched.values()]
  .sort((a, b) => a.slug.localeCompare(b.slug))
  .map((i) => `  ${JSON.stringify(i.slug)}: { title: ${JSON.stringify(i.title)}, hex: "#${i.hex}", path: ${JSON.stringify(i.path)} },`)
  .join("\n");

const pkg = JSON.parse(readFileSync(resolve(HERE, "../package.json"), "utf8"));
const version = pkg.devDependencies["simple-icons"].replace(/^[^\d]*/, "");

writeFileSync(
  OUT,
  `// GENERATED by scripts/gen-brand-icons.mjs — do not edit by hand.
// Run \`npm run gen:brand-icons\` to refresh.
//
// Source: Simple Icons v${version} (https://simpleicons.org), SVG paths CC0-1.0.
// The marks themselves remain trademarks of their respective owners; they are
// used here only to identify the employer a posting belongs to.
//
// Coverage: ${matched.size} of ${companies.size} catalog companies. The rest fall
// back to a brand-coloured monogram — see CompanyIcon.tsx. A company absent here
// is usually absent upstream too (Simple Icons honours brand takedown requests,
// which is why Amazon, Microsoft and Adobe are not present).

export interface BrandIcon {
  /** Official brand name as Simple Icons records it. */
  title: string;
  /** Official brand colour, '#rrggbb'. Run through brandInk() before painting. */
  hex: string;
  /** Single SVG path, 24x24 viewBox. */
  path: string;
}

export const BRAND_ICONS: Record<string, BrandIcon> = {
${rows}
};
`,
  "utf8",
);

console.log(`[brand-icons] ${matched.size}/${companies.size} matched -> ${OUT}`);
console.log(`[brand-icons] no mark for ${missing.length}: ${missing.slice(0, 12).join(", ")}${missing.length > 12 ? ", ..." : ""}`);

// ---------------------------------------------------------------------------
// Manifest + lazy shards, for companies added at runtime by careers URL.
// ---------------------------------------------------------------------------

/** Shard key: first character, or `_` for the digit-leading slugs (1password). */
const shardOf = (slug) => (/[a-z]/.test(slug[0]) ? slug[0] : "_");

const MANIFEST_OUT = resolve(HERE, "../src/ui/brandIconManifest.gen.ts");
const SHARD_DIR = resolve(HERE, "../src/ui/brandIconShards");

const allSlugs = [...new Set(icons.map((i) => i.slug))].sort();

writeFileSync(
  MANIFEST_OUT,
  `// GENERATED by scripts/gen-brand-icons.mjs — do not edit by hand.
//
// Every slug Simple Icons v${version} carries, with NO path data — ~30KB so it can
// ship eagerly. This is the offline "does a mark exist?" oracle: a slug missing
// here can never resolve, so it renders a monogram without fetching a shard.
// Without it, every uncovered company (Amazon, McKinsey, every quant firm) would
// pull a shard just to learn there was nothing in it.
//
// Space-delimited rather than an array literal: same data, a fraction of the
// parse cost and none of the per-element quoting.
const SLUGS =
  ${JSON.stringify(allSlugs.join(" "))};

export const BRAND_ICON_SLUGS: ReadonlySet<string> = new Set(SLUGS.split(" "));

/** Shard key for a slug; mirrors the generator's bucketing. */
export function brandIconShard(slug: string): string {
  return /[a-z]/.test(slug[0]) ? slug[0] : "_";
}
`,
  "utf8",
);

mkdirSync(SHARD_DIR, { recursive: true });
const shards = new Map();
for (const icon of icons) {
  const key = shardOf(icon.slug);
  if (!shards.has(key)) shards.set(key, []);
  shards.get(key).push(icon);
}

// Stale shards would keep resolving slugs upstream has since dropped.
for (const stale of readdirSync(SHARD_DIR).filter((f) => f.endsWith(".gen.ts"))) {
  if (!shards.has(stale.replace(".gen.ts", ""))) rmSync(resolve(SHARD_DIR, stale));
}

for (const [key, list] of [...shards].sort()) {
  const body = list
    .sort((a, b) => a.slug.localeCompare(b.slug))
    .map((i) => `  ${JSON.stringify(i.slug)}: { title: ${JSON.stringify(i.title)}, hex: "#${i.hex}", path: ${JSON.stringify(i.path)} },`)
    .join("\n");
  writeFileSync(
    resolve(SHARD_DIR, `${key}.gen.ts`),
    `// GENERATED by scripts/gen-brand-icons.mjs — do not edit by hand.
// Lazy shard "${key}": ${list.length} marks, loaded only when a company's slug is
// in the manifest but not in the eager set. Source: Simple Icons v${version}, CC0-1.0.
import type { BrandIcon } from "../brandIcons.gen";

export const SHARD: Record<string, BrandIcon> = {
${body}
};
`,
    "utf8",
  );
}

const shardSummary = [...shards].map(([k, v]) => `${k}:${v.length}`).sort().join(" ");
console.log(`[brand-icons] manifest ${allSlugs.length} slugs -> ${MANIFEST_OUT}`);
console.log(`[brand-icons] ${shards.size} lazy shards -> ${SHARD_DIR}`);
console.log(`[brand-icons] shard sizes ${shardSummary}`);
