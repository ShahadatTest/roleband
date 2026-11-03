import "../ScopeSection.css";
import "./walk.css";
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { Badge } from "../../../ui/Badge";
import { Button } from "../../../ui/Button";
import { TabBar, type TabBarItem } from "../../../ui/TabBar";
import { ResourceLoadState } from "../../../ui/ResourceLoadState";
import { api, type PayFloor } from "../../../api";
import { forgetSetupProbe, type SetupCompaniesProps } from "../../../routing/setupMode";
import { useScopeDraft } from "../useScopeDraft";
import { keepSetupStash, readSetupStash } from "../setupStash";
import { AccountableStep } from "./AccountableStep";
import { LevelStep } from "./LevelStep";
import { WhereStep } from "./WhereStep";
import { RolesStep } from "./RolesStep";
import { SubjectsStep } from "./SubjectsStep";
import { SummaryStep } from "./SummaryStep";
import { ProgressRail } from "./ProgressRail";
import { domainsOf, excludedOf, linesFrom, rolesNarrowed, type ModifierLine } from "./walkModel";
import { STEPS, type StepId, type WalkView } from "./walkSteps";
import {
  profilePayFloorRowCouldNotSaveThePay,
  profileWalkContinue,
  profileWalkContinueReasonAccountable,
  profileWalkContinueReasonLevel,
  profileWalkContinueReasonWhere,
  profileWalkLockedReason,
  profileWalkOptional,
  profileWalkSkip,
  profileWalkSteps,
  profileWalkSummary,
  profileWalkWhatYourRadarLooksFor,
  profileWelcomeWizardBack,
  profileSetupCompaniesNote,
  profileSetupCompaniesTab,
  profileSetupCompaniesTitle,
  profileSetupLater,
  profileSetupStep,
  profileSetupTitle,
} from "../../../copy/gen/profile";
import { number as copyNumber } from "../../../copy/format";
import { PageHeader } from "../../../patterns/PageHeader";
import { radarLoadFailed, radarLoading } from "../../../copy/gen/radar";

/* Profile › Looking for as a walk.
 *
 * A path of five screens, one question each: the kind of role, the level,
 * where — the three that decide what reaches the radar — then two optional
 * ones that sharpen it, which roles exactly and the interests. A sixth entry,
 * Summary, is the whole answer in one place and the place to judge it: the
 * choices, the funnel they produced, and the way back to any step. After the
 * third answer the walk lands there (the gate and the summary are one
 * screen).
 *
 * Above, the steps as the app's tab bar. Below it, the one question of the
 * current step, in a step card: a banded head, the question, the
 * note, and a body whose frame is the same size for the three answers that
 * decide, so Back and Continue never move. At the right, the rail: what the
 * radar keeps, and Save.
 *
 * Only the current step is rendered. The rail holds words and one Save,
 * never a question. That is the whole anti-wall rule.
 *
 * First-run setup (`setup`) is the same walk taken straight through: the three
 * answers that decide, the two that sharpen, the Summary of all five, and a
 * last step on which companies to scan, handed in by the route because it is
 * Companies' own. The draft starts blank, the rail offers no Save, and the
 * companies step's Start is the one commit: the scope, then the pay floor the
 * Summary holds. Setup has the window to itself,
 * so the walk draws its own header (the step it is on, and the way out) and
 * stands as one centred column a little below the top.
 *
 * Setup's step lives in the browser's history, one entry per step, so Back
 * (the browser's, or a phone's back gesture) steps back through setup rather
 * than out of RoleBand, and a reload opens the step it left. Its answers are
 * kept for the tab until Start (../setupStash).
 *
 * The two that sharpen say they are optional, and while one still keeps
 * everything a quieter Skip sits beside Continue. Continue stays where it is
 * on every step, so a reader who presses it from habit still moves on; both
 * keep everything, since a blank draft keeps every role of each kind and
 * every world. */

const ORDER: readonly WalkView[] = ["accountable", "level", "where", "summary", "roles", "subjects"];
const SETUP_ORDER: readonly WalkView[] = ["accountable", "level", "where", "roles", "subjects", "summary", "companies"];
const DECIDING: readonly WalkView[] = ["accountable", "level", "where"];

/** The setup step a history entry names, read as untrusted: an entry of
    another shape opens the first step. */
function setupStepOf(state: unknown): WalkView {
  const step = (state as { setupStep?: unknown } | null)?.setupStep;
  return typeof step === "string" && (SETUP_ORDER as readonly string[]).includes(step) ? step as WalkView : "accountable";
}

/** What a step still needs before Continue opens. The optional steps are
    always answered, so they need none. */
const CONTINUE_REASON: Partial<Record<StepId, () => string>> = {
  accountable: profileWalkContinueReasonAccountable,
  level: profileWalkContinueReasonLevel,
  where: profileWalkContinueReasonWhere,
};

export interface WalkSetup {
  companies?: (props: SetupCompaniesProps) => ReactNode;
  /** "Set up later": leaves without saving. */
  onLater?: () => void;
}

export function Walk({ setup }: { setup?: WalkSetup } = {}) {
  const draft = useScopeDraft();
  const navigate = useNavigate();
  const location = useLocation();
  const requestedSummary = useRef(location.hash === "#summary");
  const {
    catalog, error, selectedTracks, selectedLocations, selectedBands, selectedDomains, selectedExcluded,
    selectedAnswers, experienceStage, targetStage, replaceDomains, replaceExcluded, dirty, save,
  } = draft;
  const [walkView, setWalkView] = useState<WalkView>("accountable");
  const asked = setup ? setupStepOf(location.state) : walkView;
  const setView = (next: WalkView) => {
    if (!setup) { setWalkView(next); return; }
    if (next !== asked) navigate({ pathname: location.pathname, search: location.search }, { state: { setupStep: next } });
  };
  /* Setup's pay floor, held from the Summary until Start writes it:
     undefined while untouched, so Start writes nothing. */
  const [heldFloor, setHeldFloor] = useState<PayFloor | null | undefined>(() => (setup ? readSetupStash().floor : undefined));
  const holdFloor = (floor: PayFloor | null) => {
    setHeldFloor(floor);
    keepSetupStash({ floor });
  };
  const [floorSaving, setFloorSaving] = useState(false);
  const [floorError, setFloorError] = useState<string | null>(null);
  const headingRef = useRef<HTMLHeadingElement>(null);
  const firstRender = useRef(true);
  useEffect(() => {
    if (!catalog || !requestedSummary.current) return;
    requestedSummary.current = false;
    if (selectedTracks.size > 0 && selectedLocations.size > 0 && (selectedBands.size > 0 || (experienceStage && targetStage))) setWalkView("summary");
  }, [catalog, selectedTracks.size, selectedLocations.size, selectedBands.size, experienceStage, targetStage]);

  /* The interests list is the source of two saved sets while the user writes
     it: the worlds set ("interested in") and the excluded list ("not
     interested in", a veto). When either changes from outside (a suggestion
     accepted, the catalog loaded) the sets are the source of the list. They
     agree by construction: a list produces the two sets, and sets that are
     not the ones the list produces re-derive the list. A profile saved with
     no excluded list avoided nothing, so its worlds set reads back as
     interests. */
  const allDomains = useMemo(() => (catalog?.domains ?? []).map((domain) => domain.slug), [catalog]);
  const [lines, setLines] = useState<ModifierLine[]>([]);
  useEffect(() => {
    if (!catalog) return;
    const same = (a: Set<string>, b: Set<string>) => a.size === b.size && [...a].every((slug) => b.has(slug));
    const agrees = same(new Set(domainsOf(allDomains, lines)), selectedDomains)
      && (selectedExcluded.size === 0 || same(new Set(excludedOf(allDomains, lines)), selectedExcluded));
    if (agrees) return;
    const next = linesFrom(allDomains, selectedDomains, selectedExcluded);
    const key = (list: ModifierLine[]) => list.map((line) => `${line.verb}:${line.subject}`).join("|");
    if (key(next) !== key(lines)) setLines(next);
  }, [catalog, allDomains, lines, selectedDomains, selectedExcluded]);
  const setModifierLines = (next: ModifierLine[]) => {
    setLines(next);
    replaceDomains(domainsOf(allDomains, next));
    replaceExcluded(excludedOf(allDomains, next));
  };

  /* A step change moves the reader with it: the question takes focus, so a
     keyboard or screen-reader user lands on what changed rather than on the
     strip button they pressed. The page moves only when the card's top has
     scrolled out of sight, and then back to the page's own top, so every
     step opens in the same place under the Profile header. Not
     `scrollIntoView({ block: "nearest" })`: for a card taller than the
     screen, such as World, that means "align its top" and scrolls the
     header away on that step alone. */
  useEffect(() => {
    if (firstRender.current) { firstRender.current = false; return; }
    const heading = headingRef.current;
    if (!heading) return;
    heading.focus({ preventScroll: true });
    const card = heading.closest(".walk");
    let port = card?.parentElement ?? null;
    while (port && port.scrollHeight <= port.clientHeight) port = port.parentElement;
    const portTop = port && port !== document.documentElement ? port.getBoundingClientRect().top : 0;
    if (card && card.getBoundingClientRect().top < portTop) (port ?? window).scrollTo?.({ top: 0 });
  }, [asked]);

  // A failed read offers the draft's retry, as the Welcome wizard does, so a
  // page reload is never the only way out.
  if (!catalog) {
    return (
      <ResourceLoadState
        error={error ? new Error(error) : null}
        loading={radarLoading()}
        failed={radarLoadFailed()}
        onRetry={draft.reloadCatalog}
      />
    );
  }

  const levelAnswered = Boolean(experienceStage && targetStage) || selectedBands.size > 0;
  const answered: Record<StepId, boolean> = {
    accountable: selectedTracks.size > 0,
    level: levelAnswered,
    where: selectedLocations.size > 0,
    roles: true,
    subjects: true,
  };
  const stageOneComplete = answered.accountable && answered.level && answered.where;
  /* A history entry can name a step its answers no longer reach (they were
     not kept, or a deciding one was cleared): the walk opens the first
     deciding step still open instead. */
  const view = stageOneComplete || DECIDING.includes(asked)
    ? asked
    : (["accountable", "level", "where"] as const).find((step) => !answered[step]) ?? "accountable";

  const order = setup ? SETUP_ORDER : ORDER;
  const at = order.indexOf(view);
  const currentAnswered = view === "summary" || view === "companies" || answered[view];
  const next = () => {
    if (!currentAnswered) return;
    const following = order[at + 1];
    if (following === undefined) { setView("summary"); return; }
    /* Past the three that decide, every step waits for them: Continue goes
       back to the first one still open rather than doing nothing. */
    const open = (["accountable", "level", "where"] as const).find((step) => !answered[step]);
    if (open && !DECIDING.includes(following)) { setView(open); return; }
    setView(following);
  };
  const back = () => {
    const previous = order[at - 1];
    if (previous !== undefined) setView(previous);
  };
  const leave = async () => {
    if (dirty && !(await save())) return;
    navigate("/");
  };
  /* Setup ends on the board, and the replace keeps Back from returning into a
     walk whose install is now configured. */
  /* The pay floor is written after the scope: a scope that failed leaves
     nothing saved, and a floor that failed after it is retried by Start
     again, which saves the same scope once more. */
  const finishSetup = async () => {
    if (!(await save())) return;
    if (heldFloor !== undefined) {
      setFloorError(null);
      setFloorSaving(true);
      try {
        await (heldFloor ? api.savePayFloor(heldFloor) : api.clearPayFloor());
      } catch {
        setFloorSaving(false);
        setFloorError(profilePayFloorRowCouldNotSaveThePay());
        return;
      }
    }
    forgetSetupProbe();
    navigate("/", { replace: true });
  };

  const current = view === "summary" || view === "companies" ? null : STEPS.find((step) => step.id === view) ?? null;
  const stageOne = view === "accountable" || view === "level" || view === "where";
  const narrowed = view === "roles" ? rolesNarrowed(selectedAnswers) : view === "subjects" ? lines.length > 0 : true;
  const skippable = Boolean(current?.optional) && !narrowed;

  /* The steps as the app's tab bar, the one Settings and Insights use: three
     runs set apart by a rule, the three that decide, the two that sharpen,
     and Summary. No done marks: a check on every answered tab distracts more
     than it tells; the selected tab
     says where you are. Labels stay stable; selection state and its effect
     live in the answers and funnel. The tabs after the first three unlock
     once those are answered, and say so on screen beside the bar: a locked
     tab cannot be focused or hovered on a touch screen, so a tooltip would
     never reach most of the people who meet one. */
  const locked = stageOneComplete ? undefined : "walk-locked-reason";
  const tabs: TabBarItem<WalkView>[] = [
    ...STEPS.map((step): TabBarItem<WalkView> => {
      const unlocked = !step.optional || stageOneComplete;
      return {
        id: step.id,
        label: step.label,
        disabled: !unlocked,
        describedBy: unlocked ? undefined : locked,
        groupStart: step.id === "roles",
      };
    }),
    { id: "summary", label: profileWalkSummary(), disabled: !stageOneComplete, describedBy: locked, groupStart: true },
    ...(setup
      ? [{ id: "companies" as const, label: profileSetupCompaniesTab(), disabled: !stageOneComplete, describedBy: locked }]
      : []),
  ];

  return (
    <section className={setup ? "walk walk--setup" : "walk"} aria-label={profileWalkWhatYourRadarLooksFor()}>
      {setup && (
        <PageHeader
          eyebrow={profileSetupStep({ step: copyNumber(at + 1), count: copyNumber(order.length) })}
          title={profileSetupTitle()}
          actions={(
            <Button variant="link" className="ui-btn-quiet" onClick={setup.onLater}>
              {profileSetupLater()}
            </Button>
          )}
        />
      )}
      {(error ?? floorError) && <div className="scope-notice bad" role="alert">{error ?? floorError}</div>}

      <div className="walk-tabs-row">
        <TabBar
          label={profileWalkSteps()}
          className="walk-tabs"
          value={view}
          onChange={setView}
          tabs={tabs}
          idPrefix="walk"
          controls="walk-panel"
        />
        {locked && <p className="walk-note" id={locked}>{profileWalkLockedReason()}</p>}
      </div>
      {/* How far along setup is, as a line; the eyebrow says it in words. */}
      {setup && (
        <div className="walk-setup-progress" aria-hidden="true">
          <span style={{ width: `${((at + 1) / order.length) * 100}%` }} />
        </div>
      )}
      <div className="walk-body">
        <div className="walk-step" id="walk-panel" role="tabpanel" aria-labelledby={`walk-tab-${view}`} aria-live="polite">
          {view === "companies" ? (
            <section key="companies" className="settings-section scope-step walk-card walk-card--stage1" aria-labelledby="walk-step-companies">
              <header className="scope-step-head walk-card-head">
                <h2 className="scope-step-title" id="walk-step-companies" tabIndex={-1} ref={headingRef}>
                  {profileSetupCompaniesTitle()}
                </h2>
                <p className="scope-step-note">{profileSetupCompaniesNote()}</p>
              </header>
              <div className="scope-step-body walk-card-body">
                {setup?.companies?.({
                  footClassName: "walk-step-foot",
                  saving: draft.saving || floorSaving,
                  onBack: back,
                  onStart: finishSetup,
                  keptChoice: readSetupStash().companies,
                  onChoice: (companies) => keepSetupStash({ companies }),
                })}
              </div>
            </section>
          ) : view === "summary" || !current ? (
            <SummaryStep
              key="summary"
              headingRef={headingRef}
              lines={lines}
              onGo={setView}
              onLeave={leave}
              onContinue={setup ? () => setView("companies") : undefined}
              onBack={setup ? back : undefined}
              heldFloor={setup ? { floor: heldFloor, onChange: holdFloor } : undefined}
            />
          ) : (
            <section
              key={view}
              className={`settings-section scope-step walk-card${stageOne ? " walk-card--stage1" : ""}`}
              aria-labelledby={`walk-step-${view}`}
            >
              <header className="scope-step-head walk-card-head">
                <div className="walk-card-headrow">
                  <h2 className="scope-step-title" id={`walk-step-${view}`} tabIndex={-1} ref={headingRef}>
                    {current.title}
                  </h2>
                  {current.optional && <Badge tone="neutral" variant="outline" size="sm">{profileWalkOptional()}</Badge>}
                </div>
                <p className="scope-step-note">{current.note}</p>
              </header>
              <div className="scope-step-body walk-card-body">
                <div className="walk-question">
                  {view === "accountable" && <AccountableStep />}
                  {view === "level" && <LevelStep setup={Boolean(setup)} />}
                  {view === "where" && <WhereStep />}
                  {view === "roles" && <RolesStep />}
                  {view === "subjects" && <SubjectsStep lines={lines} onChange={setModifierLines} />}
                </div>
                <footer className="walk-step-foot">
                  {/* The first step has nowhere to go back to: Back holds its
                      place unseen, so Continue stands where it stands on
                      every step. */}
                  <Button
                    variant="ghost"
                    onClick={back}
                    disabled={at === 0}
                    style={at === 0 ? { visibility: "hidden" } : undefined}
                  >
                    {profileWelcomeWizardBack()}
                  </Button>
                  {/* Why Continue is shut, on screen rather than in a tooltip that
                      keyboard, touch and screen-reader users never reach. */}
                  {!currentAnswered && (
                    <p className="walk-note" id="walk-continue-reason">{CONTINUE_REASON[view]?.()}</p>
                  )}
                  {skippable && <Button variant="ghost" className="walk-step-skip" onClick={next}>{profileWalkSkip()}</Button>}
                  <Button
                    variant="ghost"
                    className="ui-btn-strong"
                    onClick={next}
                    disabled={!currentAnswered}
                    aria-describedby={currentAnswered ? undefined : "walk-continue-reason"}
                  >
                    {profileWalkContinue({ choice: (view === "subjects" && !setup) ? "yes" : "no" })}
                  </Button>
                </footer>
              </div>
            </section>
          )}
        </div>
        <ProgressRail view={view} answered={answered} lines={lines} onGo={setView} setup={Boolean(setup)} />
      </div>
    </section>
  );
}
