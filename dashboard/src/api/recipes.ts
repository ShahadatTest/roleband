/* Recipes: how RoleBand reads a careers page no built-in reader covers.
   One domain of the typed client; `index.ts` composes
   `api`. Every wire type is an alias of the generated schema
   (`tracker/api/schemas/recipes.py`). */

import type { Schemas } from "./schemas";
import { getJSON, postJSON } from "./transport";

/** `GET /api/connector-recipes`: every recipe, its version in use, whether
 *  RoleBand checked that version, and the companies it scans. */
export type RecipeList = Schemas["RecipeList"];
export type RecipeSummary = Schemas["RecipeSummary"];
/** `GET /api/connector-recipes/{slug}`: newest version first. */
export type RecipeDetail = Schemas["RecipeDetail"];
export type RecipeRevision = Schemas["RecipeRevisionRow"];
/** A draft save: the new version's id and number. */
export type SavedRecipeVersion = Schemas["SavedRevision"];
/** A preview (two pages, five postings, nothing saved) or a whole-page check. */
export type RecipeCheck = Schemas["RecipeCheckResult"];
export type RecipePreviewJob = Schemas["PreviewJob"];
/** A company now scanned with a recipe. */
export type RecipeBinding = Schemas["RecipeBindingRow"];

const slugPath = (slug: string) => `/api/connector-recipes/${encodeURIComponent(slug)}`;

export const recipesApi = {
  recipes: () => getJSON<RecipeList>("/api/connector-recipes"),
  recipe: (slug: string) => getJSON<RecipeDetail>(slugPath(slug)),
  saveRecipeDraft: (document: Record<string, unknown>) =>
    postJSON<SavedRecipeVersion>("/api/connector-recipes", { document }),
  previewRecipe: (document: Record<string, unknown>) =>
    postJSON<RecipeCheck>("/api/connectors/preview", { document }),
  checkRecipeVersion: (slug: string, revisionId: number) =>
    postJSON<RecipeCheck>(`${slugPath(slug)}/revisions/${revisionId}/validate`),
  useRecipeVersion: (slug: string, revisionId: number) =>
    postJSON<RecipeSummary>(`${slugPath(slug)}/activate`, { revision_id: revisionId }),
  scanCompanyWithRecipe: (company: string, recipe: string) =>
    postJSON<RecipeBinding>(`/api/companies/${encodeURIComponent(company)}/recipe`, { recipe }),
};
