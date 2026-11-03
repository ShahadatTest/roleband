import { number as copyNumber } from "../../../copy/format";
import { useEffect, useState } from "react";
import type { ScopePreview } from "../../../api";
import { Button } from "../../../ui/Button";
import { useSavePreview, useScopeDraft } from "../useScopeDraft";
import { joinAnd, tunedFor, type ModifierLine } from "./walkModel";
import { domainName } from "../../../copy/vocab";
import { isPending, removes, share } from "./walkProgress";
import type { StepId, WalkView } from "./walkSteps";
import { RadarPyramid, pyramidLayers } from "./RadarPyramid";
import {
  profileProgressRailAScanIsRunningFrom,
  profileProgressRailAllRoles,
  profileProgressRailAt,
  profileProgressRailChooseYourRoleLevelAnd,
  profileProgressRailCountNow,
  profileProgressRailFocusYourRadar,
  profileProgressRailMoreAreAddedWhenThe,
  profileProgressRailMoreJoinAsEachCompany,
  profileProgressRailNoCountYet,
  profileProgressRailOfAllRoles,
  profileProgressRailOfThemFromEarlierScans,
  profileProgressRailReviewChanges,
  profileProgressRailRoles,
  profileProgressRailRolesAre,
  profileProgressRailRolesMatch,
  profileProgressRailRolesWhenYouSave,
  profileProgressRailSave,
  profileProgressRailSaveToCountTheRoles,
  profileProgressRailSavedOnYourBoardNow,
  profileProgressRailText,
  profileProgressRailText2,
  profileProgressRailText3,
  profileProgressRailWeLlKnowAfterThe,
  profileProgressRailYourBoardGoesFromTo,
  profileProgressRailYourProgress,
  profileScopeSectionRoles,
} from "../../../copy/gen/profile";

/* Followed-company pool -> five cumulative filters -> roles fitting the draft.
   Real counts; schematic geometry. Review changes owns the one Save except
   on Summary, whose primary saves and leaves. No writes from the diagram. */

/** What is still to reach the Board after a save. A save made while a scan
    runs promotes nothing yet: that scan adds the rest at its end. */
function arrivingClause(arriving: number, pending: boolean): string {
  if (pending) {
    return (" " + profileProgressRailMoreAreAddedWhenThe({ choice: (arriving > 0) ? "yes" : "no", arriving: (arriving > 0) ? String(copyNumber(arriving)) : "" }));
  }
  return profileProgressRailText({ choice: (arriving > 0) ? "yes" : "no", arriving: (arriving > 0) ? String(copyNumber(arriving)) : "" });
}

const roles = (count: number) => profileScopeSectionRoles({ count: count, count2: String(copyNumber(count)) });

/** What a save would do to the Board, in the review card before Save.
    The server ran the save's own writes and rolled
    them back, so a narrowing says the Board shrinks as plainly as a widening
    says it grows. */
export function previewSentences(preview: ScopePreview): string[] {
  // The additions the Board shows: a hidden company's are added, not shown.
  const { on_board_now: now, on_board_after: after, adds_on_board: adds, adds_later: later } = preview;
  const like = profileProgressRailText2({ choice: (preview.examples.length > 0) ? "yes" : "no", joinAnd: (preview.examples.length > 0) ? String(joinAnd(preview.examples.map((example) => profileProgressRailAt({ title: String(example.title), company_display: String(example.company_display) })))) : "" });
  const out = [profileProgressRailYourBoardGoesFromTo({ choice: (after === now) ? "yes" : "no", now: (after === now) ? String(roles(now)) : "", now2: (after === now) ? "" : String(copyNumber(now)), after: (after === now) ? "" : String(roles(after)) })];
  if (adds > 0) out.push(profileProgressRailOfThemFromEarlierScans({ adds: String(copyNumber(adds)), like: String(like) }));
  if (preview.scan_running && later > 0) {
    out.push(profileProgressRailAScanIsRunningFrom({ later: String(roles(later)), like: String(like) }));
  } else if (later > 0) {
    out.push(profileProgressRailMoreJoinAsEachCompany());
  }
  return out;
}

export function ProgressRail({
  view, answered, lines, onGo, setup = false,
}: {
  view: WalkView;
  answered: Record<StepId, boolean>;
  lines: ModifierLine[];
  onGo: (view: WalkView) => void;
  /** First-run setup: no Save here, because the setup's last step is its
   *  one commit. */
  setup?: boolean;
}) {
  const {
    catalog, progress, selectedAnswers, selectedLocations, selectedExcepted, selectedBands, experienceStage, targetStage,
    dirty, saving, save, impact, saveDelta, locationsDirty, domainsDirty, estimableDirty, lastInScopeChanged, lastOnBoard, lastPromotion,
    refreshing, refreshMessage, refreshInventory, countsShown,
  } = useScopeDraft();
  const savePreview = useSavePreview();
  const [savedConfirmation, setSavedConfirmation] = useState<{
    changed: number; onBoard: number | null; promoted: number; pending: boolean;
  } | null>(null);
  useEffect(() => {
    if (lastInScopeChanged === null) return;
    setSavedConfirmation({
      changed: lastInScopeChanged, onBoard: lastOnBoard,
      promoted: lastPromotion?.promoted ?? 0, pending: lastPromotion?.pending ?? false,
    });
    const timeout = window.setTimeout(() => setSavedConfirmation(null), 8_000);
    return () => window.clearTimeout(timeout);
  }, [lastInScopeChanged, lastOnBoard, lastPromotion]);

  if (!catalog) return null;

  const stageOneComplete = answered.accountable && answered.level && answered.where;
  const unpricedOnly = (locationsDirty || domainsDirty) && !estimableDirty;
  /* A layer is in use when the person picked something there (a ticked
     Discipline card, a World interest) or the save narrows it anyway. Nothing
     ticked keeps every role, so it stays open until a card is ticked. */
  const rolesNarrowed = [...(selectedAnswers?.values() ?? [])].some((roles) => roles !== "any");
  const used = {
    roles: rolesNarrowed || removes(progress, "roles"),
    subjects: lines.length > 0 || removes(progress, "subjects"),
  };

  /* The headline is the whole gate, the number the save keeps. The deepest
     layer the person touched would count every family whenever step 4 reads
     "any" and overstate the save. */
  const last = !stageOneComplete ? null : "subjects";

  /* The card is the funnel and its result, nothing else: which companies
     are not counted and what the catalog could not place belong to the
     company register; a place a scan never asked about is said on the Where
     step, where the place is chosen. */
  /* After a save, what the Board holds now, how many of those the save added
     from postings earlier scans read, and how many of the roles
     that fit are still to arrive: those no scan has read yet (a place not
     asked for, a company not scanned since) land on its next scan. */
  /* Without counts (setup, or nothing read yet) the funnel names the answers
     instead, and nothing offers to count. */
  const unread = !countsShown;
  const said = unread
    ? tunedFor({
      answers: selectedAnswers ?? new Map(), experience: experienceStage, target: targetStage, bands: selectedBands,
      levels: catalog.levels, locations: catalog.locations ?? [], places: selectedLocations, excepted: selectedExcepted,
    }, lines, domainName)
    : null;
  const fit = progress.ready && stageOneComplete ? progress.kept.subjects : null;
  const arriving = savedConfirmation?.onBoard != null && fit !== null ? Math.max(0, fit - savedConfirmation.onBoard) : 0;

  return (
    <aside className="persona-rail walk-rail" aria-label={profileProgressRailYourProgress()}>
      <section className="scope-rail-card walk-progress" aria-labelledby="walk-progress-title">
        <header className="walk-progress-head">
          <h2 id="walk-progress-title">{profileProgressRailFocusYourRadar()}</h2>
        </header>
        <div className="walk-progress-body">
          <div className="walk-progress-source" data-selection="chrome">
            <span>{profileProgressRailAllRoles()}</span>
            {progress.ready && progress.total > 0 && <span className="walk-progress-source-share">100%</span>}
          </div>
          <RadarPyramid
            layers={pyramidLayers(progress, answered, used, stageOneComplete, said && { ...said, subjects: said.subjects.join(", ") })}
            named={Boolean(said)}
            view={view}
            onGo={onGo}
          />
          <div className="walk-progress-result" aria-live="polite">
            {unread ? null : !progress.ready ? (
              <p className="walk-progress-line">
                {profileProgressRailNoCountYet()}{" "}
                <Button variant="link" className="ui-btn-quiet" onClick={refreshInventory} disabled={refreshing}>
                  {profileProgressRailCountNow({ choice: (refreshing) ? "yes" : "no" })}
                </Button>
              </p>
            ) : last && isPending(progress, last) ? (
              <p className="walk-progress-line">
                {profileProgressRailSaveToCountTheRoles({ choice: (progress.counting) ? "yes" : "no", pendingPlaces: (progress.counting) ? String(joinAnd(progress.pendingPlaces)) : "", pendingPlaces2: (progress.counting) ? "" : String(joinAnd(progress.pendingPlaces)) })}
              </p>
            ) : last ? (
              <>
                <div className="walk-progress-outcome" data-selection="chrome">
                  <strong>{copyNumber(progress.kept[last])}</strong>
                  <span>{profileProgressRailRolesMatch({ count: progress.kept[last] })}</span>
                </div>
                <p className="walk-progress-line"><span className="num">{share(progress.kept[last], progress.total)}</span> {profileProgressRailOfAllRoles()}</p>
              </>
            ) : (
              <p className="walk-progress-line">{profileProgressRailChooseYourRoleLevelAnd()}</p>
            )}
          </div>
          {refreshMessage && <p className="walk-progress-note" role="status">{refreshMessage}</p>}
        </div>
      </section>

      {dirty && !setup && view !== "summary" && (
        <section className="scope-rail-card scope-action-card" aria-labelledby="walk-review-title">
          <div data-selection="chrome" className="persona-rail-title" id="walk-review-title">{profileProgressRailReviewChanges()}</div>
          {/* The joint prices every axis, places and interests included, so it
              answers whenever it is ready; the marginal estimate is the
              fallback for an install whose joint is not counted yet. */}
          {saveDelta !== null ? (
            <div className="scope-impact" aria-live="polite">
              <span className={`scope-impact-value ${saveDelta > 0 ? "positive" : saveDelta < 0 ? "negative" : ""}`}>
                {saveDelta === 0 ? "·" : `${saveDelta > 0 ? "+" : ""}${copyNumber(saveDelta)}`}
              </span>
              <span>{profileProgressRailRolesWhenYouSave({ choice: (saveDelta === 0) ? "yes" : "no" })}</span>
            </div>
          ) : (
            <div className="scope-impact" aria-live="polite">
              <span className={`scope-impact-value ${!unpricedOnly && impact.complete && impact.total > 0 ? "positive" : !unpricedOnly && impact.complete && impact.total < 0 ? "negative" : ""}`}>
                {unpricedOnly || !impact.complete ? "·" : `${impact.total > 0 ? "+" : ""}${copyNumber(impact.total)}`}
              </span>
              <span>
                {profileProgressRailWeLlKnowAfterThe({ choice: (unpricedOnly) ? "v1" : (impact.complete) ? (impact.total === 0) ? "v2" : "v3" : "v4" })}
              </span>
            </div>
          )}
          <Button variant="primary" onClick={save} disabled={saving}>
            {profileProgressRailSave({ choice: (saving) ? "yes" : "no" })}
          </Button>
          {/* Below Save, never above it: the preview answers after the change
              that asked for it, often mid-tap, and text landing above would
              push the button out from under the finger. */}
          {savePreview && (
            <p className="walk-progress-note walk-review-preview" aria-live="polite">
              {previewSentences(savePreview).join(" ")}
            </p>
          )}
        </section>
      )}
      {!dirty && savedConfirmation !== null && (
        <div className="scope-save-confirmation" role="status">
          {profileProgressRailSavedOnYourBoardNow({ choice: (savedConfirmation.onBoard === null) ? "yes" : "no", changed: (savedConfirmation.onBoard === null) ? String(copyNumber(savedConfirmation.changed)) : "", value: (savedConfirmation.onBoard === null) ? profileProgressRailRoles({ count: savedConfirmation.changed }) : "", onBoard: (savedConfirmation.onBoard === null) ? "" : String(copyNumber(savedConfirmation.onBoard)), value2: (savedConfirmation.onBoard === null) ? "" : profileProgressRailRolesAre({ count: savedConfirmation.onBoard }), value3: (savedConfirmation.onBoard === null) ? "" : profileProgressRailText3({ choice: (savedConfirmation.promoted > 0) ? "yes" : "no", promoted: (savedConfirmation.promoted > 0) ? String(copyNumber(savedConfirmation.promoted)) : "" }), arriving: (savedConfirmation.onBoard === null) ? "" : String(arrivingClause(arriving, savedConfirmation.pending)) })}
        </div>
      )}
    </aside>
  );
}
