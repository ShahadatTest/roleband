import { mkdtempSync, mkdirSync, writeFileSync, rmSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { expect, it } from "vitest";
import { build } from "../../scripts/gen-copy.mjs";
import { readLocale, branches, semantic } from "../../scripts/copy/catalog.mjs";
import { sourceHash, textProblems, checkCatalog, ratchetProblems } from "../../scripts/copy-check.mjs";
import { usageIndex, recordReview, reviewData } from "../../scripts/copy/review.mjs";
import ts from "typescript";
import * as runtime from "./runtime";
import {budgetProblems} from "../../scripts/copy/budgets.mjs";
function scratch(en: string, target = "") {
  const root=mkdtempSync(join(tmpdir(),"copy-contract-"));
  mkdirSync(join(root,"en"));mkdirSync(join(root,"es"));
  writeFileSync(join(root,"locales.json"),JSON.stringify({locales:[{code:"en",status:"complete",fallback:[]},{code:"es",status:"beta",fallback:["en"]}]}));
  writeFileSync(join(root,"en/a.ftl"),en);writeFileSync(join(root,"es/a.ftl"),target);
  return root;
}
const compile=(root:string)=>build({root,gen:join(root,"gen")});
it.each([
  ["m = { $title } { $link }\n", "m = { $title }\n", /omits displayed \$link/],
  ["m = { $choice ->\n [yes] { $link }\n*[no] No\n}\n", "m = { $choice ->\n [yes] Sí\n*[no] { $link }\n}\n", /omits displayed \$link in/],
  ["m = { $stage ->\n [applied] Sent\n*[other] Considering\n}\n", "m = { $stage ->\n [waiting] Esperando\n*[other] Otro\n}\n", /semantic branches/],
  ["m = Hi\n", "m = Uno\nm = Dos\n", /defined twice/],
  ["m = Hi\n", "m = { $extra }\n", /English does not pass/],
  ["-a = { -b }\n-b = { -a }\nm = { -a }\n", "", /term cycle/],
  ["a-b = One\naB = Two\n", "", /export collision/],
])("refuses a broken catalog contract (%s)",(en,target,error)=>{
  const root=scratch(en,target);try{expect(()=>compile(root)).toThrow(error);}finally{rmSync(root,{recursive:true,force:true});}
});
it("permits grammatical plural collapse, while a displayed number remains required",()=>{
  const root=scratch("m = { $count ->\n [one] One role\n*[other] Many roles\n}\n","m = Roles\n");
  try{expect(()=>compile(root)).not.toThrow();}finally{rmSync(root,{recursive:true,force:true});}
});
it("the checker alone blocks an unquarantined omitted action",()=>{
  const root=scratch("m = { $title } { $link }\n","m = { $title }\n");
  try {expect(checkCatalog(root).blocking.join("\n")).toMatch(/omits displayed \$link/);}finally{rmSync(root,{recursive:true,force:true});}
});
it.each([
  [{code:"es",status:"beta",fallback:["missing"]}, /unknown fallback/],
  [{code:"es",status:"beta",fallback:["es"]}, /fallback cycle/],
  [{code:"en",status:"beta",fallback:[]}, /duplicate locale/],
  [{code:"es",status:"hidden",fallback:[]}, /invalid locale/],
  [{code:"ES",status:"beta",fallback:[]}, /noncanonical/],
])("refuses invalid locale declarations", (locale,error)=>{
  const root=scratch("m = One\n");
  try {
    writeFileSync(join(root,"locales.json"),JSON.stringify({locales:[{code:"en",status:"complete",fallback:[]},locale]}));
    expect(()=>compile(root)).toThrow(error);
  }finally{rmSync(root,{recursive:true,force:true});}
});
it("a non-English fallback retains its own plural grammar",()=>{
  const root=scratch("m = { $n ->\n [one] { $n } role\n*[other] { $n } roles\n}\n");
  try {
    mkdirSync(join(root,"fr"));writeFileSync(join(root,"fr/a.ftl"),"m = { $n ->\n [one] { $n } rôle\n*[other] { $n } rôles\n}\n");
    writeFileSync(join(root,"locales.json"),JSON.stringify({locales:[{code:"en",status:"complete",fallback:[]},{code:"fr",status:"beta",fallback:["en"]},{code:"es",status:"beta",fallback:["fr","en"]}]}));
    const built=compile(root), source=built.files.get(join(root,"gen/locales/es.ts"))!;
    const exports: {default?: runtime.Table}={};
    const js=ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.CommonJS}}).outputText;
    new Function("exports","require",js)(exports,()=>runtime);
    runtime.setActive({table:exports.default!,language:"es",tableLanguage:"es",region:"en-US"});
    expect(exports.default![0]!({n:0})).toBe("0 rôle");
    expect(exports.default![0]!({n:2})).toBe("2 rôles");
  }finally{runtime.setActive({table:null,language:"en",tableLanguage:"en",region:null});rmSync(root,{recursive:true,force:true});}
});
it("fingerprints transitive term values, attributes and contract metadata",()=>{
  const root=scratch('-a = { -b }\n-b = role\n    .gender = male\n# kind=label\nm = { -a }\n');
  try {
    const first=sourceHash(readLocale(root,"en").messages[0]);
    const p=join(root,"en/a.ftl"), original=readFileSync(p,"utf8");
    for(const edit of [original.replace("role","posting"),original.replace("male","female"),original.replace("kind=label","kind=heading")]) {
      writeFileSync(p,edit);expect(sourceHash(readLocale(root,"en").messages[0])).not.toBe(first);
    }
  }finally{rmSync(root,{recursive:true,force:true});}
});
it("checks every rendered term branch with scoped literal arguments",()=>{
  const root=scratch('-term = { $num ->\n [one] role\n*[other] roles\n}\nm = { $n ->\n [one] A { -term(num: "one") }\n*[other] { $n } { -term(num: "other") }\n}\n');
  try{const c=readLocale(root,"en");expect(branches(c.messages[0].pattern,c.terms)).toEqual(["A role","{$n} roles"]);}finally{rmSync(root,{recursive:true,force:true});}
});
it("an allowed phrase exempts only its own vocabulary, never surrounding text or punctuation",()=>{
  expect(textProblems("Apple Intelligence scraping —", {allowed:{phrases:["Apple Intelligence"]},banned:["intelligence","scrape"],mechanics:{forbid:["—"]}}).map(p=>p[0])).toEqual(["vocabulary","mechanics"]);
  expect(textProblems("您的连接器",{matching:"substring",banned:["连接器"],register:{forbidden:["您"]}}).map(p=>p[0])).toEqual(["vocabulary","register"]);
});
it("a freeze cannot conceal rising counts or new literal violations",()=>{
  expect(ratchetProblems({a:{"locale-call":2}},["new"],{counts:{a:{"locale-call":1}},literals:[]})).toHaveLength(2);
});
it("a lazy-language budget catches growth and refuses an undocumented new language",()=>{
  const text="translated message ".repeat(50);
  expect(budgetProblems("es",text,{bytes:1000,gzip:100,why:"fixture"})).toEqual([]);
  expect(budgetProblems("es",text,{bytes:100,gzip:1,why:"fixture"})).toHaveLength(2);
  expect(budgetProblems("new",text,undefined)).toEqual(["new: declare bytes, gzip and why"]);
});
it("review usage resolves aliases, getters, namespace calls and dynamic keyed lookups",()=>{
  const root=scratch("m-one = One\nm-two = Two\n");const src=join(root,"src");mkdirSync(src);
  try {
    writeFileSync(join(src,"use.ts"),'import { mOne as alias, byKey } from "./copy/gen/a";\nimport * as words from "./copy/gen/a";\nconst model = {get label() { return alias(); }};\nwords.mTwo();\nbyKey[slug]();\n');
    const uses=usageIndex(readLocale(root,"en").messages,src);
    expect(uses["m-one"].map(u=>u.mode)).toEqual(["direct","dynamic"]);
    expect(uses["m-two"].map(u=>u.mode)).toEqual(["direct","dynamic"]);
  }finally{rmSync(root,{recursive:true,force:true});}
});
// The quarantine holds a broken translation's exact pattern: the
// reader sees the English until it is repaired, and any other text blocks.
it("a quarantined translation says its English until repaired, and only its frozen text is excused",()=>{
  const root=scratch("# kind=label\nm = { $title } { $link }\n","m = { $title }\n");
  const src=join(root,"src");mkdirSync(src);
  try {
    const frozen=JSON.stringify(semantic(readLocale(root,"es").messages[0].pattern));
    writeFileSync(join(root,"translation-quarantine.json"),JSON.stringify({es:{m:frozen}}));
    const {blocking,reports}=checkCatalog(root);
    expect(blocking.join("\n")).not.toMatch(/omits displayed/);
    expect(reports.join("\n")).toMatch(/m: contract: omits displayed \$link; English fallback until repaired/);
    const table=[...compile(root).files].find(([path])=>path.endsWith(join("locales","es.ts")))![1];
    expect(table).toMatch(/export const filled = 0;/);
    const words=reviewData(root,src).messages[0].locales.es;
    expect([words.status,words.origin]).toEqual(["quarantined","en"]);
    expect(words.variants[0].text).toBe(words.variants[0].english);
    // Edited without repair: not the frozen text, so it blocks again.
    writeFileSync(join(root,"es/a.ftl"),"m = Hola { $title }\n");
    expect(()=>compile(root)).toThrow(/omits displayed \$link/);
    expect(checkCatalog(root).blocking.join("\n")).toMatch(/omits displayed \$link/);
  }finally{rmSync(root,{recursive:true,force:true});}
});
it("editorial review is separate from translation tracking and becomes stale on source changes",()=>{
  const root=scratch("# kind=label\nm = One\n","m = Uno\n");
  const src=join(root,"src");mkdirSync(src);
  try {
    recordReview(root,"es",["m"]);
    expect(reviewData(root,src).messages[0].locales.es.editorial).toBe("reviewed");
    expect(reviewData(root,src).messages[0].locales.es.status).toBe("stale");
    writeFileSync(join(root,"es/a.ftl"),"m = Dos\n");
    expect(reviewData(root,src).messages[0].locales.es.editorial).toBe("review-stale");
    recordReview(root,"es",["m"]);
    writeFileSync(join(root,"es/glossary.yaml"),"register:\n  forbidden: [usted]\n");
    expect(reviewData(root,src).messages[0].locales.es.editorial).toBe("review-stale");
    recordReview(root,"es",["m"]);
    writeFileSync(join(root,"en/a.ftl"),"# kind=label\nm = Two\n");
    expect(reviewData(root,src).messages[0].locales.es.editorial).toBe("review-stale");
    expect(checkCatalog(root).reports.some(r=>r.includes("untracked"))).toBe(true);
  }finally{rmSync(root,{recursive:true,force:true});}
});
it("reports branch explosion instead of silently skipping variants",()=>{
  const root=scratch("m = "+Array.from({length:9},(_,i)=>`{ $s${i} ->\n [a] A\n [b] B\n*[c] C\n}`).join("\n    ")+"\n");
  try{const m=readLocale(root,"en").messages[0];expect(()=>branches(m.pattern,m.terms)).toThrow(/branch combinations exceed/);}finally{rmSync(root,{recursive:true,force:true});}
});
