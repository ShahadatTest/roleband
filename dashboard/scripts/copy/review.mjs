// The copy review deck's data (docs/copy.md, section 7).
// Dev-only: the deck page reads it through the Vite plugin's worker, and
// `npm run copy:deck` exports it.
//
//   npm run copy:deck                         write the catalog export
//   npm run copy:deck -- --since <ref>        also the messages changed since a ref
//   npm run copy:deck -- --reviewed es <id>   record an editorial review
//
// The official Fluent runtime renders the samples, so the deck shows what a
// reader sees independently of our compiler; the canonical AST supplies the
// contracts, dependencies and source fingerprints.
import { FluentBundle, FluentResource } from "@fluent/bundle";
import ts from "typescript";
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { dirname, join, relative } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { tmpdir } from "node:os";
import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import yaml from "js-yaml";
import { camel, combinations, contract, dependencies, manifestAt, readLocale } from "./catalog.mjs";
import { sourceFiles } from "./extract.mjs";
import { checkCatalog, sourceHash } from "../copy-check.mjs";

const HERE = dirname(fileURLToPath(import.meta.url));
export const ROOT = join(HERE, "../../src/copy");
const SRC = join(ROOT, "..");

const readJSON = (path) => (existsSync(path) ? JSON.parse(readFileSync(path, "utf8")) : {});
/** The text of a message's own pattern, as written in its file. */
const patternSource = (msg) => msg.src.slice(msg.pattern.span.start, msg.pattern.span.end);
/** Group `items` by `key`, keeping their order. */
const groupBy = (items, key) => {
  const groups = new Map();
  for (const item of items) groups.set(key(item), [...(groups.get(key(item)) ?? []), item]);
  return groups;
};

/** One sample argument set per selector branch: a placeholder for each plain
    variable, every key of each selector plus its default, and representative
    numbers for a numeric selector (plural categories, a fraction, grouping). */
export function samples(msg) {
  const { variables, selectors } = contract(msg.pattern);
  const base = Object.fromEntries([...variables].map((name) => [name, `‹${name}›`]));
  let cases = [base];
  for (const [name, selector] of selectors) {
    const values = selector.numeric ? [0, 1, 2, 1.5, 1000, 1000000] : [...selector.keys, "__default__"];
    cases = combinations(cases, values).map(([args, value]) => ({ ...args, [name]: value }));
  }
  return cases.length ? cases : [base];
}

/** Where each message is used: dashboard imports of the generated modules
    (named, aliased, namespace and keyed lookups) and backend producers of
    notification and banner keys. A lookup whose key the data decides marks
    every message of its file `dynamic`: a use the index cannot pin, so the
    index never claims a message is unused. */
export function usageIndex(messages, src = SRC) {
  const index = Object.fromEntries(messages.map((m) => [m.id, []]));
  const idByExport = new Map(messages.map((m) => [camel(m.id), m.id]));

  for (const file of sourceFiles(src)) {
    if (relative(src, file).startsWith("copy/gen/")) continue;
    const text = readFileSync(file, "utf8");
    const sf = ts.createSourceFile(file, text, ts.ScriptTarget.Latest, true);
    const bindings = new Map(); // local name -> message id
    const namespaces = new Map(); // local name -> generated module ("surface")
    const add = (id, node, mode = "direct") => {
      const line = sf.getLineAndCharacterOfPosition(node.getStart(sf)).line + 1;
      const use = { file: relative(src, file), line, mode };
      if (!index[id].some((u) => u.file === use.file && u.line === line)) index[id].push(use);
    };

    for (const statement of sf.statements) {
      if (!ts.isImportDeclaration(statement) || !/copy\/gen\/|\.\/gen\//.test(statement.moduleSpecifier.text)) continue;
      const bind = statement.importClause?.namedBindings;
      const surface = statement.moduleSpecifier.text.split("/").at(-1);
      if (bind && ts.isNamedImports(bind)) {
        for (const element of bind.elements) {
          const name = element.propertyName?.text ?? element.name.text;
          if (idByExport.has(name)) bindings.set(element.name.text, idByExport.get(name));
          if (name === "byKey") namespaces.set(element.name.text, surface);
        }
      }
      if (bind && ts.isNamespaceImport(bind)) namespaces.set(bind.name.text, surface);
    }

    const visit = (node) => {
      if (ts.isImportDeclaration(node)) return;
      if (ts.isIdentifier(node) && bindings.has(node.text)) add(bindings.get(node.text), node);
      const onNamespace = (x) => ts.isIdentifier(x.expression) && namespaces.has(x.expression.text);
      // `M.reviewTitle`: a namespace member.
      if (ts.isPropertyAccessExpression(node) && onNamespace(node) && idByExport.has(node.name.text)) {
        add(idByExport.get(node.name.text), node);
      }
      // `byKey["vocab-domain-ai-ml"]` names its message; `byKey[slug]` could be any in the file.
      if (ts.isElementAccessExpression(node) && onNamespace(node)) {
        const surface = namespaces.get(node.expression.text);
        if (ts.isStringLiteral(node.argumentExpression) && index[node.argumentExpression.text]) {
          add(node.argumentExpression.text, node);
        } else {
          for (const m of messages.filter((m) => m.file === `en/${surface}.ftl`)) add(m.id, node, "dynamic");
        }
      }
      ts.forEachChild(node, visit);
    };
    visit(sf);
  }

  // Backend producers name `notif-` and `banner-` keys as string literals; a
  // literal that is only a prefix is a key built at run time. git lists the
  // files, so the scan sees what the repository does (ignored files excluded).
  const backend = join(src, "../../backend/tracker");
  if (existsSync(backend)) {
    const listed = execFileSync("git", ["ls-files", "--cached", "--others", "--exclude-standard", "--full-name", "--", "."], {
      cwd: backend,
      encoding: "utf8",
    });
    const files = listed
      .trim()
      .split("\n")
      .filter((f) => f.endsWith(".py") && !f.endsWith("catalog_gen.py"))
      .map((f) => join(backend, "../..", f));
    for (const file of files) {
      const text = readFileSync(file, "utf8");
      for (const hit of text.matchAll(/["']((?:notif|banner)-[a-z0-9-]+)["']/g)) {
        const line = text.slice(0, hit.index).split("\n").length;
        const use = { file: relative(src, file), line };
        if (index[hit[1]]) {
          index[hit[1]].push({ ...use, mode: "server" });
        } else {
          for (const id of Object.keys(index).filter((id) => id.startsWith(hit[1]))) index[id].push({ ...use, mode: "dynamic-server" });
        }
      }
    }
  }
  return index;
}

/** The English messages whose source changed since `ref` (a git ref), with the
    terms each depends on, and the ids removed since. */
export function changedMessages(ref, root = ROOT) {
  const scratch = mkdtempSync(join(tmpdir(), "copy-before-"));
  try {
    const repo = join(root, "../../..");
    const git = (args) => execFileSync("git", args, { cwd: repo, encoding: "utf8" });
    const paths = git(["ls-tree", "-r", "--name-only", ref, "--", "dashboard/src/copy/en"])
      .trim()
      .split("\n")
      .filter((p) => p.endsWith(".ftl"));
    mkdirSync(join(scratch, "en"));
    for (const path of paths) writeFileSync(join(scratch, "en", path.split("/").at(-1)), git(["show", `${ref}:${path}`]));

    const before = new Map(readLocale(scratch, "en").messages.map((m) => [m.id, sourceHash(m)]));
    const now = readLocale(root, "en").messages;
    return {
      changed: now.filter((m) => before.get(m.id) !== sourceHash(m)).map((m) => ({ id: m.id, terms: Object.keys(dependencies(m)) })),
      removed: [...before.keys()].filter((id) => !now.some((m) => m.id === id)),
    };
  } finally {
    rmSync(scratch, { recursive: true, force: true });
  }
}

/** Everything the deck shows: per English message its source, contract, uses
    and diagnostics, and per language its state and rendered samples. */
export function reviewData(root = ROOT, src = SRC) {
  const manifest = manifestAt(root);
  const locales = manifest.locales.filter((l) => l.status !== "pseudo");
  const cats = new Map();
  const bundles = new Map();
  for (const locale of locales) {
    const cat = readLocale(root, locale.code);
    const bundle = new FluentBundle(locale.code, { useIsolating: false });
    cats.set(locale.code, cat);
    bundles.set(locale.code, bundle);
    for (const file of cat.files) {
      const [error] = bundle.addResource(new FluentResource(readFileSync(join(root, locale.code, file), "utf8")));
      if (error) throw error;
    }
  }

  const en = cats.get("en");
  const usages = usageIndex(en.messages, src);
  const diagnostics = checkCatalog(root, undefined, cats);
  const diagnosticsById = groupBy(diagnostics.diagnostics, (d) => d.id);
  const quarantine = readJSON(join(root, "translation-quarantine.json"));
  const englishOnly = manifest.englishOnly ?? [];

  /** One message (or `id.attribute`) by the official runtime; null on any error. */
  const render = (code, id, args) => {
    const bundle = bundles.get(code);
    const [key, attribute] = id.split(".");
    const message = bundle.getMessage(key);
    const pattern = attribute ? message?.attributes[attribute] : message?.value;
    if (!pattern) return null;
    const errors = [];
    const text = bundle.formatPattern(pattern, args, errors);
    return errors.length ? null : text;
  };

  const ledgers = new Map(
    [...cats.keys()].map((code) => [
      code,
      { translated: readJSON(join(root, code, "translated-from.json")), reviewed: readJSON(join(root, code, "reviewed-from.json")) },
    ]),
  );

  // An editorial review holds while the checker and the glossaries it read are
  // unchanged: their fingerprint is part of what a review records.
  const engine = readFileSync(join(HERE, "../copy-check.mjs"), "utf8") + readFileSync(join(HERE, "catalog.mjs"), "utf8");
  const glossary = (code) => {
    const path = join(root, code, "glossary.yaml");
    return existsSync(path) ? yaml.load(readFileSync(path, "utf8")) : {};
  };
  const rules = Object.fromEntries(
    [...cats.keys()].map((code) => [code, createHash("sha256").update(engine + JSON.stringify([glossary("en"), glossary(code)])).digest("hex")]),
  );

  // The language a reader of `code` sees `id` in: the first along its fallback
  // chain that has it, English last, and English for a quarantined translation.
  const fallbackOrder = (code) => [code, ...(manifest.locales.find((l) => l.code === code)?.fallback ?? []).flatMap(fallbackOrder)];
  const resolve = (code, id) => {
    const chain = [...fallbackOrder(code).filter((c) => c !== "en"), "en"];
    const origin = chain.find((c) => cats.get(c)?.messages.some((m) => m.id === id));
    return quarantine[origin]?.[id] ? "en" : origin;
  };

  const status = (code, m, own, hash) => {
    if (code === "en") return "source";
    if (quarantine[code]?.[m.id]) return "quarantined";
    if (!own) return englishOnly.includes(m.id) ? "english-only" : "missing";
    return ledgers.get(code).translated[m.id] !== hash ? "stale" : "current";
  };
  const editorial = (code, m, ownHash, hash) => {
    const record = ledgers.get(code).reviewed[m.id];
    if (record === `${hash}|${ownHash}|${rules[code]}`) return "reviewed";
    return record ? "review-stale" : "unreviewed";
  };

  const messages = en.messages.map((m) => {
    const { selectors, variables } = contract(m.pattern);
    const hash = sourceHash(m);
    const cases = samples(m);
    const found = diagnosticsById.get(m.id) ?? [];
    const perLocale = [...cats].map(([code, cat]) => {
      const own = cat.messages.find((x) => x.id === m.id);
      const ownHash = own ? sourceHash(own) : null;
      const origin = resolve(code, m.id) ?? "en";
      return [
        code,
        {
          status: status(code, m, own, hash),
          editorial: editorial(code, m, ownHash, hash),
          hash: ownHash,
          rulesHash: rules[code],
          origin,
          source: own ? patternSource(own) : null,
          variants: cases.map((args) => ({ args, english: render("en", m.id, args), text: render(origin, m.id, args) })),
        },
      ];
    });
    return {
      id: m.id,
      kind: m.meta.kind ?? "",
      file: m.file,
      line: m.src.slice(0, m.node.span.start).split("\n").length,
      source: patternSource(m),
      selectors: Object.fromEntries(selectors),
      rules: found.map((d) => d.rule),
      parameters: [...variables],
      terms: Object.keys(dependencies(m)),
      meta: m.meta,
      hash,
      uses: usages[m.id],
      locales: Object.fromEntries(perLocale),
      diagnostics: found.map((d) => `${d.locale}: ${d.rule}: ${d.detail}`),
    };
  });

  // Equal English text is a merge candidate only: the same words can carry
  // different intent, so the deck lists them and merges nothing.
  const equalTextGroups = [...groupBy(messages, (m) => m.source).values()].filter((group) => group.length > 1).map((group) => group.map((m) => m.id));
  return {
    locales,
    messages,
    equalTextGroups,
    blocking: diagnostics.blocking,
    reports: diagnostics.reports,
    diagnostics: diagnostics.diagnostics,
  };
}

/** Record an editorial review of `ids` in `code`: the English, the translation
    and the rules it was reviewed against. Any of them changing makes it stale.
    Separate from translation tracking (`copy:check -- --translated`). */
export function recordReview(root, code, ids) {
  const data = reviewData(root);
  const path = join(root, code, "reviewed-from.json");
  const ledger = readJSON(path);
  for (const id of ids) {
    const m = data.messages.find((m) => m.id === id);
    const words = m?.locales[code];
    if (!words) throw new Error(`unknown review ${code} ${id}`);
    ledger[id] = `${m.hash}|${words.hash}|${words.rulesHash}`;
  }
  writeFileSync(path, JSON.stringify(Object.fromEntries(Object.entries(ledger).sort()), null, 2) + "\n");
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  const reviewed = process.argv.indexOf("--reviewed");
  if (reviewed !== -1) {
    const [code, ...ids] = process.argv.slice(reviewed + 1);
    if (!ids.length) throw new Error("explicit message ids required");
    recordReview(ROOT, code, ids);
  }
  const output = join(ROOT, "../../node_modules/.cache/copy-review");
  mkdirSync(output, { recursive: true });
  writeFileSync(join(output, "catalog.json"), JSON.stringify(reviewData(), null, 2) + "\n");
  const since = process.argv.indexOf("--since");
  if (since !== -1) writeFileSync(join(output, "changed.json"), JSON.stringify(changedMessages(process.argv[since + 1]), null, 2) + "\n");
  console.log(`Copy review: ${output}/catalog.json; dev page http://127.0.0.1:5173/__copy-review/`);
}
