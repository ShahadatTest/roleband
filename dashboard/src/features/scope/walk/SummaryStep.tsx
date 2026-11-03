import { number as copyNumber } from "../../../copy/format";
import type { RefObject } from "react";
import { Link } from "react-router-dom";
import { api, type PayFloor } from "../../../api";
import { useAsyncResource } from "../../../hooks/useAsyncResource";
import { Badge } from "../../../ui/Badge";
import { Button } from "../../../ui/Button";
import { Icon } from "../../../ui/Icon";
import { useScopeDraft } from "../useScopeDraft";
import { SuggestionInbox } from "../ProfileSuggestions";
import { ScopeRulesList } from "../ScopeSection";
import { PayFloorRow, currencyForPlaces } from "./PayFloorRow";
import { joinAnd, rolesNarrowed, tunedFor, type ModifierLine } from "./walkModel";
import { FUNNEL_ORDER, isPending, removes, share } from "./walkProgress";
import type { StepId } from "./walkSteps";
import {
  profileExperiencePageComingSoon,
  profileExperiencePageYourExperience,
  profilePersonaRailLevel,
  profilePersonaRailTunedFor,
  profileProgressRailAllRoles,
  profileSummaryStepAddYourCv,
  profileSummaryStepAdjust,
  profileSummaryStepAdjust2,
  profileSummaryStepAfterYouSave,
  profileSummaryStepCountingTheRolesIn,
  profileSummaryStepInterests,
  profileSummaryStepNoCountYetOnceA,
  profileSummaryStepRole,
  profileSummaryStepSaveToCountTheRoles,
  profileSummaryStepSeeYourRadar,
  profileSummaryStepSummary,
  profileSummaryStepWhatItKeeps,
  profileSummaryStepWhere,
  profileSummaryStepWhichRoles,
  profileSetupSummaryLater,
  profileWelcomeWizardBack,
  profileWalkContinue,
} from "../../../copy/gen/profile";
import { Msg } from "../../../ui/Msg";
import { domainName } from "../../../copy/vocab";

/* The sixth entry: the whole answer in one place and the place to judge it.
   Reached after the third answer (it is the gate) and any time from the
   strip. Three parts: the choices as a "Tuned for" table, each
   with its way back; the funnel those choices produced once the scan ran,
   from every role at the person's companies to the ones kept; and leaving
   as the primary. Below a hairline, what else shapes the feed — proposals
   from the inference pass, learned exclusions, the aim line — so a person
   deciding whether to change something sees everything that decides.

   Every row is at most two lines, named then counted, whoever's answers they
   are, so no one's answers can overflow the Summary. The pay floor is the
   one OPTIONAL answer, and Your experience links to the CV placeholder; intake is not built.

   In first-run setup (`onContinue`) the Summary is a waypoint, not the exit:
   it leads on to the companies step and offers nothing that leaves the walk
   or saves on its own. Its pay floor is held by the walk and written by
   Start; Your experience links out of the walk, so it is left out. */

const FUNNEL_LABELS: Record<StepId, string> = {
  get accountable() { return profileSummaryStepRole(); }, get level() { return profilePersonaRailLevel(); }, get where() { return profileSummaryStepWhere(); }, get roles() { return profileSummaryStepWhichRoles(); }, get subjects() { return profileSummaryStepInterests(); },
};

export function SummaryStep({
  headingRef, lines, onGo, onLeave, onContinue, onBack, heldFloor,
}: {
  headingRef: RefObject<HTMLHeadingElement | null>;
  lines: ModifierLine[];
  onGo: (step: StepId) => void;
  onLeave: () => void;
  onContinue?: () => void;
  /** Setup only: the step before the Summary. */
  onBack?: () => void;
  /** Setup's pay floor, held by the walk until Start: `floor` undefined while
      the person has not touched it, so the row shows the stored one. */
  heldFloor?: { floor: PayFloor | null | undefined; onChange: (floor: PayFloor | null) => void };
}) {
  const {
    catalog, progress, selectedAnswers, selectedLocations, selectedExcepted, selectedBands,
    experienceStage, targetStage, saving, dirty, countsShown,
  } = useScopeDraft();
  // The optional pay floor lives apart from the Walk's draft: it is not scope.
  const payFloor = useAsyncResource(() => api.payFloor().then((r) => r.pay_floor), []);
  const floor = payFloor.data ?? null;
  if (!catalog) return null;

  const chosen = selectedAnswers ?? new Map();
  const said = tunedFor({
    answers: chosen, experience: experienceStage, target: targetStage, bands: selectedBands,
    levels: catalog.levels, locations: catalog.locations ?? [], places: selectedLocations, excepted: selectedExcepted,
  }, lines, domainName);
  // Without counts (setup, or nothing read yet) the choices stand alone.
  const unread = !countsShown;

  const facts: { id: StepId; label: string; value: string | string[] }[] = [
    { id: "accountable", label: profileSummaryStepRole(), value: said.accountable },
    { id: "level", label: profilePersonaRailLevel(), value: said.level },
    { id: "where", label: profileSummaryStepWhere(), value: said.where },
    { id: "roles", label: profileSummaryStepWhichRoles(), value: said.roles },
    { id: "subjects", label: profileSummaryStepInterests(), value: said.subjects },
  ];

  /* The funnel stops at the last step that narrows: an untouched optional
     step keeps the count of the step before it, and saying so twice would
     read as a step that did nothing. */
  /* A step the save narrows is shown even when it reads "any", so the last
     number is always what the save keeps. */
  const shown = FUNNEL_ORDER.filter((step) =>
    step === "accountable" || step === "level" || step === "where"
    || (step === "roles" && (rolesNarrowed(chosen) || removes(progress, "roles")))
    || (step === "subjects" && (lines.length > 0 || removes(progress, "subjects"))));

  return (
    <section className="settings-section scope-step walk-card walk-card--stage1 walk-summary" aria-labelledby="walk-step-summary">
      <header className="scope-step-head walk-card-head">
        <div className="walk-card-headrow">
          <h2 className="scope-step-title" id="walk-step-summary" tabIndex={-1} ref={headingRef}>{profileSummaryStepSummary()}</h2>
        </div>
      </header>
      <div className="scope-step-body walk-card-body">
        <div className={onContinue ? "walk-summary-grid walk-summary-grid--setup" : "walk-summary-grid"}>
          <section className="walk-summary-block walk-summary-choices" aria-labelledby="walk-summary-choices">
            <div data-selection="chrome" className="persona-rail-title" id="walk-summary-choices">{profilePersonaRailTunedFor()}</div>
            <div className="persona-summary walk-summary-facts">
              {facts.map((fact) => (
                <div className="persona-fact" key={fact.id}>
                  <span data-selection="chrome" className="persona-fact-label">{fact.label}</span>
                  <span className="persona-fact-value walk-fact-value">
                    <span className="walk-fact-text">
                      {(Array.isArray(fact.value) ? fact.value : [fact.value]).map((line) => (
                        // The title is the whole line: the clamp may cut it.
                        <span className="walk-fact-line" key={line} title={line}>{line}</span>
                      ))}
                    </span>
                    <Button variant="link" className="ui-btn-quiet walk-summary-adjust" aria-label={profileSummaryStepAdjust2({ label: String(fact.label.toLowerCase()) })} onClick={() => onGo(fact.id)}>
                      {profileSummaryStepAdjust()}
                    </Button>
                  </span>
                </div>
              ))}
            </div>
          </section>

          {!unread && <section className="walk-summary-block walk-summary-funnel" aria-labelledby="walk-summary-funnel">
            <div data-selection="chrome" className="persona-rail-title" id="walk-summary-funnel">{profileSummaryStepWhatItKeeps()}</div>
            {!progress.ready ? (
              <p className="walk-summary-empty">{profileSummaryStepNoCountYetOnceA()}</p>
            ) : (
              <>
                <ol className="walk-funnel">
                  <li className="walk-funnel-row">
                    <span className="walk-funnel-label">{profileProgressRailAllRoles()}</span>
                    <span className="walk-funnel-bar"><span className="walk-funnel-fill" style={{ width: "100%" }} /></span>
                    <span className="walk-funnel-value"><span className="num">{copyNumber(progress.total)}</span></span>
                  </li>
                  {shown.map((step) => isPending(progress, step) ? (
                    <li className="walk-funnel-row" key={step}>
                      <span className="walk-funnel-label">{FUNNEL_LABELS[step]}</span>
                      <span className="walk-funnel-bar" />
                      <span className="walk-funnel-value walk-funnel-pending">{profileSummaryStepAfterYouSave({ choice: (progress.counting) ? "yes" : "no" })}</span>
                    </li>
                  ) : (
                    <li className="walk-funnel-row" key={step}>
                      <span className="walk-funnel-label">{FUNNEL_LABELS[step]}</span>
                      <span className="walk-funnel-bar">
                        <span className="walk-funnel-fill" style={{ width: progress.total > 0 ? `${Math.max(1, (progress.kept[step] / progress.total) * 100)}%` : "0%" }} />
                      </span>
                      <span className="walk-funnel-value">
                        <span className="num">{copyNumber(progress.kept[step])}</span>
                        <span className="walk-funnel-share">{share(progress.kept[step], progress.total)}</span>
                      </span>
                    </li>
                  ))}
                </ol>
                {progress.pendingFrom && <p className="walk-summary-line">
                  {progress.counting
                      ? <><Msg of={profileSummaryStepCountingTheRolesIn} elems={{ pendingPlaces: joinAnd(progress.pendingPlaces) }} /></>
                      : <><Msg of={profileSummaryStepSaveToCountTheRoles} elems={{ pendingPlaces: joinAnd(progress.pendingPlaces) }} /></>}
                </p>}
              </>
            )}
          </section>}
          {/* A floor setup holds is known here, so it never waits on the read. */}
          <PayFloorRow
            floor={heldFloor && heldFloor.floor !== undefined ? heldFloor.floor : floor}
            status={heldFloor && heldFloor.floor !== undefined ? "ready" : payFloor.loading ? "loading" : payFloor.error ? "error" : "ready"}
            onRetry={payFloor.retry}
            onChange={heldFloor ? heldFloor.onChange : (next) => payFloor.mutate(() => next)}
            held={Boolean(heldFloor)}
            startCurrency={currencyForPlaces(selectedLocations, catalog.locations ?? [])}
          />
          {!onContinue && (
          <section className="walk-summary-block walk-summary-cv" aria-labelledby="walk-summary-cv">
            <div className="walk-summary-section-head">
              <h3 className="walk-summary-section-title" id="walk-summary-cv">{profileExperiencePageYourExperience()}</h3>
              <Badge tone="neutral" variant="outline" size="sm">{profileExperiencePageComingSoon()}</Badge>
            </div>
            <Link to="/profile/experience" className="ui-btn ui-btn-ghost ui-btn-lg ui-btn-strong ui-btn-tile">
              <Icon name="person" size={20} />
              <span className="ui-btn-tile-copy"><span className="ui-btn-tile-title">{profileSummaryStepAddYourCv()}</span></span>
              <Icon name="arrowRight" />
            </Link>
          </section>
          )}
        </div>

        {onContinue ? (
          <footer className="walk-step-foot">
            <Button variant="ghost" onClick={onBack}>{profileWelcomeWizardBack()}</Button>
            <p className="walk-note">{profileSetupSummaryLater()}</p>
            <Button variant="ghost" className="ui-btn-strong" onClick={onContinue}>
              {profileWalkContinue({ choice: "no" })}
            </Button>
          </footer>
        ) : (
          <>
            <div className="walk-summary-more">
              <SuggestionInbox compact />
              <ScopeRulesList />
            </div>
            <div className="walk-summary-foot">
              <Button variant="primary" onClick={onLeave} disabled={saving}>
                {profileSummaryStepSeeYourRadar({ choice: (saving) ? "v1" : (dirty) ? "v2" : "v3" })}
              </Button>
            </div>
          </>
        )}
      </div>
    </section>
  );
}
