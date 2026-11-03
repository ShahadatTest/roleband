import { number as copyNumber } from "../../copy/format";
import "./ScopeSection.css";
import { Button } from "../../ui/Button";
import { Icon } from "../../ui/Icon";
import { Pager } from "../../patterns/Pager";
import { ResourceLoadState } from "../../ui/ResourceLoadState";
import { useAsyncResource } from "../../hooks/useAsyncResource";
import { useToast } from "../../ui/Toast";
import { useId, useState } from "react";
import type { ScopeRule, ScopeRulePayload } from "../../api";
import { api } from "../../api";
import { companyName } from "../../format";
import {
  profileScopeSectionCompanyExclusions,
  profileScopeSectionCompanyExclusions2,
  profileScopeSectionCouldNotRemoveThatExclusion,
  profileScopeSectionCouldNotRestoreThatExclusion,
  profileScopeSectionExclusionRemovedBackOnYour,
  profileScopeSectionExclusionRestoredLeftYourRadar,
  profileScopeSectionMatchingTeamsAndDepartmentsStay,
  profileScopeSectionRemove,
  profileScopeSectionRemoveExclusionAt,
  profileScopeSectionRoles,
  profileScopeSectionUndo,
  profileScopeSectionRulesLoadFailed,
} from "../../copy/gen/profile";

/* The company exclusions list the walk's Summary shows. */

/* Learned employer-vocabulary exclusions. Written only by
   the board's dismiss flow with explicit confirmation; this is where they are
   reviewed and revoked. Removing one recomputes scope immediately, so the rows
   it excluded come straight back. */
export function ScopeRulesList() {
  // The server's list, and the edits made since it was read (a revoke, a
  // restore): the edits stand over the read until the next one.
  const loaded = useAsyncResource(() => api.scopeRules().then((result) => result.rules), []);
  const [edited, setEdited] = useState<ScopeRule[] | null>(null);
  const rules = edited ?? loaded.data;
  const setRules = (next: (prev: ScopeRule[]) => ScopeRule[]) =>
    setEdited((prev) => next(prev ?? loaded.data ?? []));
  const [expanded, setExpanded] = useState(false);
  const [requestedOffset, setOffset] = useState(0);
  const listId = useId();
  const { toast } = useToast();

  const load = () => api.scopeRules().then((result) => result.rules);

  // The section may draw nothing and still have work to do: the toast lives in
  // the app's toast layer, so revoking the LAST rule reports its count from
  // out of flow and this returns null without cutting the sentence short. The
  // component stays MOUNTED while it returns null, which is what lets Undo put
  // the list back.
  // A failed read is said where the list would be, never taken for "no
  // exclusions": the rules are still excluding roles.
  if (!rules && loaded.error) {
    return (
      <section className="worlds-rules" aria-label={profileScopeSectionCompanyExclusions2()}>
        <ResourceLoadState error={loaded.error} failed={profileScopeSectionRulesLoadFailed()} onRetry={loaded.retry} />
      </section>
    );
  }
  if (!rules || rules.length === 0) return null;
  const pageSize = 5;
  const offset = Math.min(requestedOffset, Math.floor((rules.length - 1) / pageSize) * pageSize);

  /* A stored rule's kind is a plain string on the wire (no database constraint
     backs it), while the create endpoint accepts only the kinds it knows. A kind
     outside them could never be written back, so Undo reports it the way it
     reports any refused restore, without sending the request. */
  const isRuleKind = (kind: string): kind is ScopeRulePayload["kind"] =>
    kind === "team" || kind === "department";

  const rowsReturned = (count: number) =>
    profileScopeSectionRoles({ count: count, count2: String(copyNumber(count)) });

  /* Undo writes the rule back by VALUE — a deleted row's id is gone, and the
     create endpoint is the same explicitly-confirmed path the dismiss flow
     uses. Re-read afterwards rather than splicing: the new rule has a new id
     and the list is server-ordered. */
  const restore = (rule: ScopeRule) => {
    const { kind } = rule;
    if (!isRuleKind(kind)) {
      toast({ key: "scope-rules", tone: "error", text: profileScopeSectionCouldNotRestoreThatExclusion() });
      return;
    }
    api.createScopeRule({ company: rule.company, kind, value: rule.value }).then(
      async (result) => {
        // A failed re-read must not shrink the list to the one rule we just
        // wrote — that would report a state the server is not in. Fall back to
        // adding it to what is already on screen.
        const reloaded = await load().catch(() => null);
        setRules((prev) => reloaded ?? [...prev, result.rule]);
        toast({
          key: "scope-rules",
          text: profileScopeSectionExclusionRestoredLeftYourRadar({ in_scope_changed: String(rowsReturned(result.in_scope_changed)) }),
        });
      },
      () => {
        toast({ key: "scope-rules", tone: "error", text: profileScopeSectionCouldNotRestoreThatExclusion() });
      },
    );
  };

  /* Revoking is never a silent final act: a failed DELETE says so, and a
     successful one can be undone without dismissing a matching role again.
     Both halves go through the toast. */
  const remove = (rule: ScopeRule) => {
    api.deleteScopeRule(rule.id).then(
      (result) => {
        setRules((prev) => prev.filter((r) => r.id !== rule.id));
        toast({
          key: "scope-rules",
          text: profileScopeSectionExclusionRemovedBackOnYour({ in_scope_changed: String(rowsReturned(result.in_scope_changed)) }),
          action: { label: profileScopeSectionUndo(), onClick: () => restore(rule) },
        });
      },
      () => {
        // The row is still there and still excluding: say so rather than let the
        // click read as done.
        toast({ key: "scope-rules", tone: "error", text: profileScopeSectionCouldNotRemoveThatExclusion() });
      },
    );
  };

  return (
    <section className="worlds-rules" aria-label={profileScopeSectionCompanyExclusions2()}>
      <h4>
        <Button size="lg" className="ui-btn-strong worlds-rules-toggle" aria-expanded={expanded} aria-controls={listId} onClick={() => setExpanded(!expanded)}>
          <span>{profileScopeSectionCompanyExclusions()} <span className="worlds-rules-count">{rules.length}</span></span>
          <Icon name={expanded ? "chevronUp" : "chevronDown"} />
        </Button>
      </h4>
      <div id={listId} hidden={!expanded}>
        <p className="worlds-rules-note">{profileScopeSectionMatchingTeamsAndDepartmentsStay()}</p>
        {rules.slice(offset, offset + pageSize).map((rule) => (
          <div className="worlds-rule" key={rule.id}>
            <span className="worlds-rule-text">
              {companyName(rule.company)} · {rule.kind} “{rule.value}”
            </span>
            <Button
              variant="link"
              className="ui-btn-quiet"
              aria-label={profileScopeSectionRemoveExclusionAt({ value: String(rule.value), company: String(companyName(rule.company)) })}
              onClick={() => remove(rule)}
            >
              {profileScopeSectionRemove()}
            </Button>
          </div>
        ))}
        <Pager total={rules.length} pageSize={pageSize} offset={offset} onOffsetChange={setOffset} />
      </div>
    </section>
  );
}
