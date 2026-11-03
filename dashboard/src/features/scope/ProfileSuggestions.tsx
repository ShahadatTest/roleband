import { Button } from "../../ui/Button";
import { useState } from "react";
import { ProfileSuggestion, api } from "../../api";
import { errorText } from "../../api/errorText";
import { commonTryAgain } from "../../copy/gen/common";
import { sharedCountRole } from "../../copy/gen/shared";
import { useAsyncResource } from "../../hooks/useAsyncResource";
import { useScopeDraft } from "./useScopeDraft";
import {
  profileSuggestionsAcceptTurnOn,
  profileSuggestionsCouldNotApplyTheSuggestion,
  profileSuggestionsCouldNotDismissTheSuggestion,
  profileSuggestionsCouldNotLoad,
  profileSuggestionsDismissSuggestionAbout,
  profileSuggestionsFollowedCompanySectorPoints,
  profileSuggestionsFollowedCompanySectorsPoint,
  profileSuggestionsInProgress,
  profileSuggestionsInferredFromYourRecentActivity,
  profileSuggestionsMoreNotForMeWith,
  profileSuggestionsNoThanks,
  profileSuggestionsRoleThereIs,
  profileSuggestionsRolesThereAre,
  profileSuggestionsSuggestedAdjustments,
  profileSuggestionsThere,
  profileSuggestionsTurnItOn,
  profileSuggestionsTurnOn,
  profileSuggestionsTurnedOnOnYourRadar,
  profileSuggestionsYouMarkedThereNotFor,
  profileSuggestionsYouSavedThere,
  profileSuggestionsYourAimNamesIt,
} from "../../copy/gen/profile";
import { domainName } from "../../copy/vocab";

/* Inferred profile adjustments: the system proposes,
   the user disposes. Every card says WHY in the user's own history — counts of
   saves/passes, tracked-company sectors, the intent statement — because an
   unexplained suggestion earns no trust. Accepting writes through the same
   stores a manual worlds edit uses; the response's authoritative domain list
   is adopted into the scope draft so the walk never shows a stale axis.
   Dismissing is permanent for that suggestion (the pass never re-raises a
   resolved key). Rendered on the walk's Summary. */

/** A count and its words, both forms spelled out: appending "s" would print
    "2 more passs". */
function counted(n: number, one: string, many: string): string {
  return `${n} ${n === 1 ? one : many}`;
}

/* In the glossary's words (docs/copy.md): a role sent away is
   marked not for me, never passed on; one being chased is in progress, never
   pursued. Settings › AI calls the intent statement "Your aim". */
export function basisClauses(suggestion: ProfileSuggestion): string[] {
  const basis = suggestion.basis;
  const clauses: string[] = [];
  if (suggestion.kind === "world_off") {
    if (basis.dismissed_wrong_domain > 0) {
      clauses.push(profileSuggestionsYouMarkedThereNotFor({ dismissed_wrong_domain: sharedCountRole({ count: basis.dismissed_wrong_domain }) }));
    }
    if (basis.dismissed_other > 0) clauses.push(profileSuggestionsMoreNotForMeWith({ dismissed_other: basis.dismissed_other }));
  } else {
    if (basis.pursued > 0) clauses.push(profileSuggestionsInProgress({ pursued: String(counted(basis.pursued, profileSuggestionsRoleThereIs(), profileSuggestionsRolesThereAre())) }));
    if (basis.favorited > 0) clauses.push(profileSuggestionsYouSavedThere({ favorited: sharedCountRole({ count: basis.favorited }) }));
    if (basis.sectors.length > 0) {
      clauses.push(profileSuggestionsThere({ length: String(counted(basis.sectors.length, profileSuggestionsFollowedCompanySectorPoints(), profileSuggestionsFollowedCompanySectorsPoint())) }));
    }
    if (basis.intent_matched) clauses.push(profileSuggestionsYourAimNamesIt());
  }
  return clauses;
}

export function SuggestionInbox({ compact = false }: { compact?: boolean }) {
  const { applyServerDomains } = useScopeDraft();
  const loaded = useAsyncResource(() => api.profileSuggestions(), []);
  const [busy, setBusy] = useState<number | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const suggestions: ProfileSuggestion[] | null = loaded.data?.suggestions ?? null;

  // A load that failed is said, with a way to try again: an empty inbox would
  // read as "nothing to confirm" when nothing was read at all.
  if (loaded.error) {
    return (
      <div className={`profile-suggestions${compact ? " compact" : ""}`} role="alert">
        <span>{errorText(loaded.error, profileSuggestionsCouldNotLoad())}</span>{" "}
        <Button variant="link" className="ui-btn-quiet" onClick={loaded.retry}>{commonTryAgain()}</Button>
      </div>
    );
  }
  // Keep the section mounted while a notice is up: accepting the LAST
  // suggestion must still report its scope effect, not vanish mid-sentence.
  if (!suggestions || (suggestions.length === 0 && !notice)) return null;

  const remove = (id: number) =>
    loaded.mutate((prev) => prev && { ...prev, suggestions: prev.suggestions.filter((item) => item.id !== id) });

  const accept = (suggestion: ProfileSuggestion) => {
    setBusy(suggestion.id);
    api.acceptProfileSuggestion(suggestion.id)
      .then((result) => {
        applyServerDomains(result.enabled_domain_groups, result.excluded_domain_groups);
        remove(suggestion.id);
        setNotice(
          profileSuggestionsTurnedOnOnYourRadar({ choice: (suggestion.kind === "world_off") ? "yes" : "no", display: String(domainName(suggestion.world)), in_scope_changed: sharedCountRole({ count: result.in_scope_changed }) }),
        );
      })
      .catch(() => setNotice(profileSuggestionsCouldNotApplyTheSuggestion()))
      .finally(() => setBusy(null));
  };

  const dismiss = (suggestion: ProfileSuggestion) => {
    setBusy(suggestion.id);
    api.dismissProfileSuggestion(suggestion.id)
      .then(() => remove(suggestion.id))
      .catch(() => setNotice(profileSuggestionsCouldNotDismissTheSuggestion()))
      .finally(() => setBusy(null));
  };

  return (
    <section
      className={`profile-suggestions${compact ? " compact" : ""}`}
      aria-label={profileSuggestionsSuggestedAdjustments()}
    >
      {suggestions.map((suggestion) => (
        <div className="profile-suggestion" key={suggestion.id}>
          <div className="profile-suggestion-title">
            {profileSuggestionsTurnOn({ choice: (suggestion.kind === "world_off") ? "yes" : "no", display: (suggestion.kind === "world_off") ? String(domainName(suggestion.world)) : "", display2: (suggestion.kind === "world_off") ? "" : String(domainName(suggestion.world)) })}
          </div>
          <div className="profile-suggestion-basis">
            {(() => {
              const clauses = basisClauses(suggestion);
              return profileSuggestionsInferredFromYourRecentActivity({ choice: (clauses.length > 0) ? "yes" : "no", join: (clauses.length > 0) ? String(clauses.join(", and ")) : "" });
            })()}
          </div>
          <div className="profile-suggestion-actions">
            <Button
              variant="primary"
              disabled={busy === suggestion.id}
              aria-label={profileSuggestionsAcceptTurnOn({ choice: (suggestion.kind === "world_off") ? "yes" : "no", display: String(domainName(suggestion.world)) })}
              onClick={() => accept(suggestion)}
            >
              {profileSuggestionsTurnItOn({ choice: (suggestion.kind === "world_off") ? "yes" : "no" })}
            </Button>
            <Button
              variant="link"
              className="ui-btn-quiet"
              disabled={busy === suggestion.id}
              aria-label={profileSuggestionsDismissSuggestionAbout({ display: String(domainName(suggestion.world)) })}
              onClick={() => dismiss(suggestion)}
            >
              {profileSuggestionsNoThanks({ choice: (suggestion.kind === "world_off") ? "yes" : "no" })}
            </Button>
          </div>
        </div>
      ))}
      {notice && <div className="profile-suggestion-notice" role="status">{notice}</div>}
    </section>
  );
}
