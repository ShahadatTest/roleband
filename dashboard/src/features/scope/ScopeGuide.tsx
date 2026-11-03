import { useState } from "react";
import { Button } from "../../ui/Button";
import { Icon } from "../../ui/Icon";
import { Sheet } from "../../ui/Sheet";
import { STEPS } from "./walk/walkSteps";
import type { CSSProperties } from "react";
import {
  profilePersonaRailLevel,
  profileScopeGuideARoleWeHavenT,
  profileScopeGuideAboutTheCounts,
  profileScopeGuideCareerTrack,
  profileScopeGuideCareerTrackLevelDisciplineAnd,
  profileScopeGuideCloseGuide,
  profileScopeGuideDecide,
  profileScopeGuideDiscipline,
  profileScopeGuideFiveAnswersDecideWhatReaches,
  profileScopeGuideHowYouContribute,
  profileScopeGuideHowYourRadarWorks,
  profileScopeGuideHowYourRadarWorks2,
  profileScopeGuideHowYourRadarWorks3,
  profileScopeGuideLocation,
  profileScopeGuideNothingHiddenByAGuess,
  profileScopeGuideOpportunityRadar,
  profileScopeGuideProgressShowsHowManyOf,
  profileScopeGuideRadarGuide,
  profileScopeGuideSaveAppliesYourAnswersTo,
  profileScopeGuideSavingAppliesToRolesAlready,
  profileScopeGuideSharpenOptional,
  profileScopeGuideTheWorkYouWant,
  profileScopeGuideWhenChangesApply,
  profileScopeGuideWhereItCanBeBased,
  profileScopeGuideWhereYouAreAndAim,
  profileScopeGuideYourRadar,
} from "../../copy/gen/profile";

/* Long-form scope help lives in one deliberate overlay. Step headings keep only
   compact InfoTips; this panel owns the system model and guided-setup escape.
   It is `ui/Sheet` right-docked, so the scroll lock, Escape from anywhere and
   a reachable backdrop button come with the primitive. */
/* What the guide explains. `walk` is Profile's five answers: the
   first three decide what reaches the radar, the last two sharpen it. `setup`
   is the first-run wizard's model (career track, discipline, location);
   Profile never shows it. */
// One line per step, from the walk's own table (the radar pyramid says it too).
const WALK_DECIDE: readonly [string, string][] = STEPS.filter((step) => !step.optional).map((step) => [step.label, step.gist]);
const WALK_SHARPEN: readonly [string, string][] = STEPS.filter((step) => step.optional).map((step) => [step.label, step.gist]);

/* `compact` is the walk's trigger: an icon in the Profile header, at the
   right end of the title's row, the side the sheet opens from. */
export function ScopeGuideButton({ className = "", variant = "setup", compact = false }: {
  className?: string;
  variant?: "walk" | "setup";
  compact?: boolean;
}) {
  const [open, setOpen] = useState(false);

  return (
    <>
      {/* Focus the trigger before opening, because a TAP does not.
          `Overlay` restores focus to whatever was active when it opened, which
          is the right contract and silently wrong on touch: a tap moves
          focus nowhere, so closing the panel would send focus to whatever the
          user last focused. Naming the opener is what makes the primitive's
          restore correct. */}
      {compact ? (
        <Button
          variant="icon"
          size="sm"
          className={className || undefined}
          aria-label={profileScopeGuideHowYourRadarWorks3()}
          title={profileScopeGuideHowYourRadarWorks2()}
          onClick={(event) => {
            event.currentTarget.focus();
            setOpen(true);
          }}
        >
          <Icon name="info" size={16} />
        </Button>
      ) : (
        <button
          type="button"
          className={`scope-guide-trigger ${className}`.trim()}
          onClick={(event) => {
            event.currentTarget.focus();
            setOpen(true);
          }}
        >
          <Icon name="info" size={15} />
          <span>{profileScopeGuideHowYourRadarWorks()}</span>
        </button>
      )}

      <Sheet
        isOpen={open}
        onClose={() => setOpen(false)}
        label={profileScopeGuideHowYourRadarWorks()}
        className="scope-guide-sheet app-overlay"
      >
        <div className="scope-guide-head">
          <div>
            <div className="scope-guide-eyebrow">{profileScopeGuideRadarGuide()}</div>
            <h2>{profileScopeGuideHowYourRadarWorks2()}</h2>
          </div>
          <Button variant="icon" aria-label={profileScopeGuideCloseGuide()} onClick={() => setOpen(false)}>
            <Icon name="close" size={17} />
          </Button>
        </div>

        {variant === "walk" ? (
          <>
          <p className="scope-guide-intro">
            {profileScopeGuideFiveAnswersDecideWhatReaches()}
          </p>

          <div className="scope-guide-flow">
            <span className="scope-guide-group" data-selection="chrome">{profileScopeGuideDecide()}</span>
            {WALK_DECIDE.map(([title, copy], index) => (
              <div className="scope-guide-gate" key={title} style={{ "--gate-delay": `${index * 110}ms` } as CSSProperties}>
                <span>{String(index + 1).padStart(2, "0")}</span>
                <strong>{title}</strong>
                <small>{copy}</small>
              </div>
            ))}
            <span className="scope-guide-group" data-selection="chrome">{profileScopeGuideSharpenOptional()}</span>
            {WALK_SHARPEN.map(([title, copy], index) => (
              <div className="scope-guide-gate" key={title} style={{ "--gate-delay": `${(index + 3) * 110}ms` } as CSSProperties}>
                <span>{String(index + 4).padStart(2, "0")}</span>
                <strong>{title}</strong>
                <small>{copy}</small>
              </div>
            ))}
            <div className="scope-guide-result">
              <span className="scope-guide-pulse" />
              {profileScopeGuideYourRadar()}
            </div>
          </div>

          <section className="scope-guide-note">
            <h3>{profileScopeGuideWhenChangesApply()}</h3>
            <p>
              {profileScopeGuideSaveAppliesYourAnswersTo()}
            </p>
          </section>

          <section className="scope-guide-note">
            <h3>{profileScopeGuideAboutTheCounts()}</h3>
            <p>
              {profileScopeGuideProgressShowsHowManyOf()}
            </p>
          </section>

          <section className="scope-guide-note">
            <h3>{profileScopeGuideNothingHiddenByAGuess()}</h3>
            <p>{profileScopeGuideARoleWeHavenT()}</p>
          </section>
          </>
        ) : (
          <>
          <p className="scope-guide-intro">
            {profileScopeGuideCareerTrackLevelDisciplineAnd()}
          </p>

          <div className="scope-guide-flow" aria-hidden="true">
            {[
              ["01", profileScopeGuideCareerTrack(), profileScopeGuideHowYouContribute()],
              ["02", profilePersonaRailLevel(), profileScopeGuideWhereYouAreAndAim()],
              ["03", profileScopeGuideDiscipline(), profileScopeGuideTheWorkYouWant()],
              ["04", profileScopeGuideLocation(), profileScopeGuideWhereItCanBeBased()],
            ].map(([number, title, copy], index) => (
              <div className="scope-guide-gate" key={number} style={{ "--gate-delay": `${index * 110}ms` } as CSSProperties}>
                <span>{number}</span>
                <strong>{title}</strong>
                <small>{copy}</small>
              </div>
            ))}
            <div className="scope-guide-result">
              <span className="scope-guide-pulse" />
              {profileScopeGuideOpportunityRadar()}
            </div>
          </div>

          <section className="scope-guide-note">
            <h3>{profileScopeGuideWhenChangesApply()}</h3>
            <p>{profileScopeGuideSavingAppliesToRolesAlready()}</p>
          </section>

          </>
        )}
      </Sheet>
    </>
  );
}
