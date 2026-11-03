import type { ScopeSelection } from "./scopeDraftModel";

/* Profile's unsaved draft, kept across a navigation. The scope draft's
   provider lives inside the route, so leaving Profile unmounts it and would
   silently drop every unsaved pick. `useScopeDraft` stashes a dirty draft here on unmount and seeds the next
   mount from it. In memory on purpose: nothing is written until Save, and a
   full reload starts from the saved scope.

   Its own module, with no imports but a type, so the test setup can clear it
   between tests without loading the provider and its context ahead of each
   test file's mocks. */
let stashed: ScopeSelection | null = null;

export const readProfileDraft = (): ScopeSelection | null => stashed;
export const keepProfileDraft = (draft: ScopeSelection | null) => { stashed = draft; };
/** Drops a kept draft; each test starts from the server's scope, as a page load does. */
export const forgetProfileDraft = () => { stashed = null; };
