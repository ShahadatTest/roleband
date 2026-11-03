import { errorText } from "../../api/errorText";
import { useState } from "react";
import {
  api,
  type CompanyList,
  type RecipeCheck,
  type RecipeDetail,
  type RecipeList,
  type RecipeRevision,
} from "../../api";
import { list } from "../../copy/format";
import { companyName, formatWhen } from "../../format";
import { useAsyncResource } from "../../hooks/useAsyncResource";
import { useWriteQueue } from "../../hooks/useWriteQueue";
import { AsyncBoundary, EmptyState } from "../../ui";
import { Button } from "../../ui/Button";
import { Card, CardMessage, CardRow } from "../../ui/Card";
import { Select } from "../../ui/Select";
import "./RecipesSection.css";
import {
  settingsRecipesSectionARecipeIsOneJson,
  settingsRecipesSectionARecipeTellsRolebandHow,
  settingsRecipesSectionCheckTheWholePage,
  settingsRecipesSectionChooseACompany,
  settingsCompany,
  settingsRecipesSectionCouldNotReadIt,
  settingsRecipesSectionCouldnTCheckTheWhole,
  settingsRecipesSectionCouldnTPreviewTheRecipe,
  settingsRecipesSectionCouldnTSaveTheRecipe,
  settingsRecipesSectionCouldnTScanThatCompany,
  settingsRecipesSectionCouldnTSwitchVersions,
  settingsRecipesSectionDraftOnly,
  settingsRecipesSectionEdit,
  settingsRecipesSectionInUse,
  settingsRecipesSectionIsNowScannedWithIts,
  settingsRecipesSectionLoadFailed,
  settingsLoading,
  settingsRecipesSectionNewRecipe,
  settingsRecipesSectionNoCompanyIsScannedWith,
  settingsRecipesSectionNoPlaceStated,
  settingsRecipesSectionNoRecipesYetWriteOne,
  settingsRecipesSectionNoRolesFoundOnThe,
  settingsRecipesSectionNotChecked,
  settingsRecipesSectionNotChecked2,
  settingsRecipesSectionNotCheckedTheWholePage,
  settingsRecipesSectionNotValidJson,
  settingsRecipesSectionOpen,
  settingsRecipesSectionPreview,
  settingsRecipesSectionRecipeJson,
  settingsRecipesSectionRecipes,
  settingsRecipesSectionRefreshFailed,
  settingsRecipesSectionSaveDraft,
  settingsRecipesSectionSaved,
  settingsRecipesSectionSavedVersionOf,
  settingsRecipesSectionScanACompanyWithIt,
  settingsRecipesSectionScanWithIt,
  settingsRecipesSectionScansNoCompany,
  settingsRecipesSectionTheRecipeHasProblems,
  settingsRecipesSectionThisCareersPageAsksNot,
  settingsRecipesSectionUseThisVersion,
  settingsRecipesSectionVersion,
  settingsRecipesSectionVersionIsNowTheOne,
  settingsRecipesSectionVersions,
  settingsRecipesSectionVersions2,
  settingsRecipesSectionVersionsLoadFailed,
  settingsRecipesSectionVersionsRefreshFailed,
  settingsRecipesSectionWholePageCheckResult,
} from "../../copy/gen/settings";
import { Content } from "../../ui/Content";

/* Settings › Recipes.

   A recipe tells RoleBand how to read a careers page no built-in reader covers.
   The screen walks the same path the backend enforces, one step at a time:
   preview (two pages, five postings, nothing saved) -> save a draft version ->
   use that version -> check the whole page -> scan a company with it. It never
   offers what the backend decides: whether a company's missing roles close is
   earned by a checked version and a clean scan, never by a button. */

const STARTER = JSON.stringify(
  {
    format_version: 1,
    kind: "job_listing",
    id: "example-careers",
    match: { domains: ["careers.example.com"] },
    transport: { mode: "static_http" },
    listing: {
      start_url: "https://careers.example.com/jobs",
      response: "html",
      item: "article.job",
      fields: {
        req_id: { attr: "data-id", required: true },
        title: { css: "h2", text: true, required: true },
        url: { css: "a", attr: "href", absolute: true, required: true },
      },
    },
  },
  null,
  2,
);

const EDITOR = "editor";

const message = (caught: unknown, fallback: string) => errorText(caught, fallback);

function parse(text: string): Record<string, unknown> | string {
  try {
    const value: unknown = JSON.parse(text);
    return value && typeof value === "object" && !Array.isArray(value)
      ? (value as Record<string, unknown>)
      : settingsRecipesSectionARecipeIsOneJson();
  } catch (caught) {
    return settingsRecipesSectionNotValidJson({ caught: String(message(caught, settingsRecipesSectionCouldNotReadIt())) });
  }
}

function CheckResult({ check, kind }: { check: RecipeCheck; kind: "preview" | "whole" }) {
  const robots = check.robots as { allowed?: boolean | null; detail?: string };
  return (
    <div className="recipe-check" role="group" aria-label={settingsRecipesSectionWholePageCheckResult({ choice: (kind === "preview") ? "yes" : "no" })}>
      {check.problems.length > 0 && (
        <CardMessage role="alert">
          {settingsRecipesSectionTheRecipeHasProblems({ count: check.problems.length, length: (check.problems.length === 1) ? "" : check.problems.length })}
          <ul className="recipe-list">{check.problems.map((p) => <li key={p}>{p}</li>)}</ul>
        </CardMessage>
      )}
      {check.errors.length > 0 && (
        <CardMessage tone="danger" role="status">
          <ul className="recipe-list">{check.errors.map((e) => <li key={e}>{e}</li>)}</ul>
        </CardMessage>
      )}
      {robots.allowed === false && (
        <CardMessage role="alert">{settingsRecipesSectionThisCareersPageAsksNot()}</CardMessage>
      )}
      {kind === "whole" && check.problems.length === 0 && (
        <CardMessage tone={check.passed ? "positive" : "info"} role="status">
          {settingsRecipesSectionNotCheckedTheWholePage({ choice: (check.passed) ? "yes" : "no", found: (check.passed) ? check.found : "", pages: (check.passed) ? check.pages : "" })}
        </CardMessage>
      )}
      {check.jobs.map((job) => (
        <CardRow
          key={job.req_id}
          title={job.title}
          facts={[job.locations.join(" · ") || settingsRecipesSectionNoPlaceStated(), job.req_id].join(" · ")}
        />
      ))}
      {kind === "preview" && check.problems.length === 0 && check.errors.length === 0 && check.found === 0 && (
        <CardMessage tone="info" role="status">{settingsRecipesSectionNoRolesFoundOnThe()}</CardMessage>
      )}
    </div>
  );
}

function versionFacts(revision: RecipeRevision, inUse: boolean) {
  return [
    inUse ? settingsRecipesSectionInUse() : null,
    settingsRecipesSectionNotChecked({ choice: (revision.validated_at) ? "yes" : "no", validated_at: (revision.validated_at) ? String(formatWhen(revision.validated_at, { weekday: false })) : "" }),
    settingsRecipesSectionSaved({ created_at: String(formatWhen(revision.created_at, { weekday: false })) }),
  ].filter(Boolean).join(" · ");
}

export function RecipesSection() {
  const recipes = useAsyncResource<RecipeList>(() => api.recipes(), []);
  const companies = useAsyncResource<CompanyList>(() => api.companies(), []);
  const [open, setOpen] = useState<string | null>(null);
  const detail = useAsyncResource<RecipeDetail | null>(
    () => (open ? api.recipe(open) : Promise.resolve(null)),
    [open],
  );
  const queue = useWriteQueue("recipes");
  const [text, setText] = useState(STARTER);
  const [check, setCheck] = useState<{ result: RecipeCheck; kind: "preview" | "whole" } | null>(null);
  const [previewing, setPreviewing] = useState(false);
  const [failures, setFailures] = useState<Record<string, string>>({});
  const [company, setCompany] = useState("");
  const [notice, setNotice] = useState<string | null>(null);

  const fail = (key: string, why: string | null) =>
    setFailures((current) => {
      const next = { ...current };
      if (why) next[key] = why;
      else delete next[key];
      return next;
    });

  const reload = async () => {
    await Promise.all([recipes.refresh({ preserveData: true }), detail.refresh({ preserveData: true })]);
  };

  const preview = async () => {
    const document = parse(text);
    if (typeof document === "string") return fail(EDITOR, document);
    fail(EDITOR, null);
    setPreviewing(true);
    try {
      setCheck({ result: await api.previewRecipe(document), kind: "preview" });
    } catch (caught) {
      fail(EDITOR, message(caught, settingsRecipesSectionCouldnTPreviewTheRecipe()));
    } finally {
      setPreviewing(false);
    }
  };

  const save = async () => {
    const document = parse(text);
    if (typeof document === "string") return fail(EDITOR, document);
    const slug = typeof document.id === "string" ? document.id : EDITOR;
    fail(EDITOR, null);
    try {
      const saved = await queue.keyed(slug, () => api.saveRecipeDraft(document));
      setNotice(settingsRecipesSectionSavedVersionOf({ version: saved.version, slug: String(saved.slug) }));
      setOpen(saved.slug);
      await reload();
    } catch (caught) {
      fail(EDITOR, message(caught, settingsRecipesSectionCouldnTSaveTheRecipe()));
    }
  };

  const openRecipe = (slug: string) => {
    setOpen(slug);
    setCheck(null);
    setNotice(null);
  };

  const edit = (revision: RecipeRevision) => setText(JSON.stringify(revision.document, null, 2));

  const checkWhole = async (slug: string, revision: RecipeRevision) => {
    const key = `check:${revision.id}`;
    fail(key, null);
    try {
      const result = await queue.keyed(slug, () => api.checkRecipeVersion(slug, revision.id));
      setCheck({ result, kind: "whole" });
      await reload();
    } catch (caught) {
      fail(key, message(caught, settingsRecipesSectionCouldnTCheckTheWhole()));
    }
  };

  const use = async (slug: string, revision: RecipeRevision) => {
    const key = `use:${revision.id}`;
    fail(key, null);
    try {
      await queue.keyed(slug, () => api.useRecipeVersion(slug, revision.id));
      setNotice(settingsRecipesSectionVersionIsNowTheOne({ version: revision.version }));
      await reload();
    } catch (caught) {
      fail(key, message(caught, settingsRecipesSectionCouldnTSwitchVersions()));
    }
  };

  const scan = async (slug: string) => {
    const key = `scan:${slug}`;
    fail(key, null);
    try {
      const bound = await queue.keyed(slug, () => api.scanCompanyWithRecipe(company, slug));
      setNotice(settingsRecipesSectionIsNowScannedWithIts({ company: String(companyName(bound.company)), slug: String(slug) }));
      setCompany("");
      await Promise.all([reload(), companies.refresh({ preserveData: true })]);
    } catch (caught) {
      fail(key, message(caught, settingsRecipesSectionCouldnTScanThatCompany()));
    }
  };

  // A company RoleBand already scans with a built-in reader is never offered:
  // moving its roles to another reader is not this screen's job.
  const scannable = (companies.data?.companies ?? []).filter(
    (row) => row.adapter == null || row.adapter === "recipe",
  );

  return (
    <>
      <Card
        title={settingsRecipesSectionRecipes()}
        intro={settingsRecipesSectionARecipeTellsRolebandHow()}
      >
        <AsyncBoundary resource={recipes} failed={settingsRecipesSectionLoadFailed()} refreshFailed={settingsRecipesSectionRefreshFailed()} skeleton={<CardRow title={settingsRecipesSectionRecipes()} facts={settingsLoading()} />}>
          {(rows) =>
            rows.length === 0 ? (
              <EmptyState variant="inline" title={settingsRecipesSectionNoRecipesYetWriteOne()} />
            ) : (
              <>
                {rows.map((row) => (
                  <CardRow
                    key={row.slug}
                    title={<Content text={row.slug} />}
                    description={<Content text={list(row.domains)} />}
                    facts={[
                      settingsRecipesSectionDraftOnly({ choice: (row.active_version) ? "yes" : "no", active_version: (row.active_version) ? row.active_version : "" }),
                      row.active_version ? settingsRecipesSectionNotChecked2({ choice: (row.active_validated) ? "yes" : "no" }) : null,
                      settingsRecipesSectionScansNoCompany({ choice: (row.companies.length) ? "yes" : "no", join: (row.companies.length) ? list(row.companies.map((slug) => companyName(slug))) : "" }),
                    ].filter(Boolean).join(" · ")}
                    trailing={
                      <Button variant="link" onClick={() => openRecipe(row.slug)} aria-pressed={open === row.slug}>
                        {settingsRecipesSectionOpen()}
                      </Button>
                    }
                  />
                ))}
              </>
            )
          }
        </AsyncBoundary>
      </Card>

      <Card title={open ? open : settingsRecipesSectionNewRecipe()}>
        <label className="recipe-editor-label" htmlFor="recipe-document">{settingsRecipesSectionRecipeJson()}</label>
        <textarea
          id="recipe-document"
          className="recipe-editor"
          // A recipe is code the person writes, not copy (`data-copy`).
          data-copy="code"
          spellCheck={false}
          value={text}
          onChange={(event) => setText(event.target.value)}
        />
        <div className="recipe-actions">
          <Button onClick={preview} disabled={previewing} aria-busy={previewing}>
            {settingsRecipesSectionPreview({ choice: (previewing) ? "yes" : "no" })}
          </Button>
          <Button variant="primary" onClick={save} disabled={queue.writing}>{settingsRecipesSectionSaveDraft()}</Button>
        </div>
        {failures[EDITOR] && <CardMessage role="alert">{failures[EDITOR]}</CardMessage>}
        {notice && <CardMessage tone="info" role="status">{notice}</CardMessage>}
        {check && <CheckResult check={check.result} kind={check.kind} />}

        {open && (
          <AsyncBoundary resource={detail} failed={settingsRecipesSectionVersionsLoadFailed()} refreshFailed={settingsRecipesSectionVersionsRefreshFailed()} skeleton={<CardRow title={settingsRecipesSectionVersions()} facts={settingsLoading()} />}>
            {(recipe) =>
              recipe && (
                <div className="recipe-versions" role="group" aria-label={settingsRecipesSectionVersions2()}>
                  {recipe.revisions.map((revision) => {
                    const inUse = recipe.active_revision_id === revision.id;
                    return (
                      <div key={revision.id}>
                        <CardRow
                          title={settingsRecipesSectionVersion({ version: revision.version })}
                          facts={versionFacts(revision, inUse)}
                          trailing={
                            <span className="recipe-actions">
                              <Button variant="link" onClick={() => edit(revision)}>{settingsRecipesSectionEdit()}</Button>
                              <Button
                                size="sm"
                                onClick={() => checkWhole(recipe.slug, revision)}
                                disabled={queue.busy.has(recipe.slug)}
                              >
                                {settingsRecipesSectionCheckTheWholePage()}
                              </Button>
                              {!inUse && (
                                <Button size="sm" onClick={() => use(recipe.slug, revision)} disabled={queue.busy.has(recipe.slug)}>
                                  {settingsRecipesSectionUseThisVersion()}
                                </Button>
                              )}
                            </span>
                          }
                        />
                        {failures[`check:${revision.id}`] && <CardMessage role="alert">{failures[`check:${revision.id}`]}</CardMessage>}
                        {failures[`use:${revision.id}`] && <CardMessage role="alert">{failures[`use:${revision.id}`]}</CardMessage>}
                      </div>
                    );
                  })}
                  {recipe.active_revision_id != null && (
                    <CardRow
                      title={settingsRecipesSectionScanACompanyWithIt()}
                      description={settingsRecipesSectionNoCompanyIsScannedWith({ choice: (recipe.companies.length) ? "yes" : "no", join: (recipe.companies.length) ? list(recipe.companies.map((slug) => companyName(slug))) : "" })}
                      trailing={
                        <span className="recipe-actions">
                          <Select
                            label={settingsCompany()}
                            value={company}
                            onChange={setCompany}
                            options={[
                              { value: "", label: settingsRecipesSectionChooseACompany() },
                              ...scannable.map((row) => ({ value: row.slug, label: row.display })),
                            ]}
                          />
                          <Button
                            size="sm"
                            onClick={() => scan(recipe.slug)}
                            disabled={!company || queue.busy.has(recipe.slug)}
                          >
                            {settingsRecipesSectionScanWithIt()}
                          </Button>
                        </span>
                      }
                    />
                  )}
                  {failures[`scan:${recipe.slug}`] && <CardMessage role="alert">{failures[`scan:${recipe.slug}`]}</CardMessage>}
                </div>
              )
            }
          </AsyncBoundary>
        )}
      </Card>
    </>
  );
}
