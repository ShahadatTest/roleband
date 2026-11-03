import { Fragment, useState } from "react";
import { JobQualification, JobRequirements, JobSkill, RequirementModality } from "../../api";
import { Badge } from "../../ui/Badge";
import { Button } from "../../ui/Button";
import { InfoTip } from "../../ui/InfoTip";
import {
  roleJobRequirementsPanelAboutImportance,
  roleJobRequirementsPanelCloud,
  roleJobRequirementsPanelCollaboration,
  roleJobRequirementsPanelCore,
  roleJobRequirementsPanelCoreSkills,
  roleJobRequirementsPanelData,
  roleJobRequirementsPanelEvidence,
  roleJobRequirementsPanelFramework,
  roleJobRequirementsPanelImportanceReflectsHowStronglyThis,
  roleJobRequirementsPanelImportant,
  roleJobRequirementsPanelImportanceInline,
  roleJobRequirementsPanelIndustry,
  roleJobRequirementsPanelInfra,
  roleJobRequirementsPanelLanguage,
  roleJobRequirementsPanelLeadership,
  roleJobRequirementsPanelMentioned,
  roleJobRequirementsPanelMlAi,
  roleJobRequirementsPanelModalityInline,
  roleJobRequirementsPanelNoExplicitSkillRequirementsFound,
  roleJobRequirementsPanelPreferred,
  roleJobRequirementsPanelPreferred2,
  roleJobRequirementsPanelProcess,
  roleJobRequirementsPanelQualifications,
  roleJobRequirementsPanelRequired,
  roleJobRequirementsPanelRequired2,
  roleJobRequirementsPanelRequirementSources,
  roleJobRequirementsPanelRoleRequirements,
  roleJobRequirementsPanelRoleRequirements2,
  roleJobRequirementsPanelSecurity,
  roleJobRequirementsPanelShowEvidence,
  roleJobRequirementsPanelShowInDescription,
  roleJobRequirementsPanelShowMore,
  roleJobRequirementsPanelSkill,
  roleJobRequirementsPanelSkillSourcesShowEvidence,
  roleJobRequirementsPanelSources,
  roleJobRequirementsPanelSupporting,
  roleJobRequirementsPanelSupporting2,
  roleJobRequirementsPanelTechnology,
  roleJobRequirementsPanelThisPostingHasNoStored,
  roleJobRequirementsPanelTitle,
  roleJobRequirementsPanelUsedInRole,
  roleJobRequirementsPanelWaysOfWorking,
  roleJobRequirementsPanelWaysOfWorkingEvidence,
  roleJobRequirementsPanelWhatThisRoleAsksFor,
  roleJobRequirementsPanelYears,
} from "../../copy/gen/role";
import { Msg } from "../../ui/Msg";
import { ownHeading, skillName } from "../../copy/vocab";
import { Content } from "../../ui/Content";

/* Role requirements panel.

   User truth contract: everything shown is an EXPLICIT catalogued requirement
   found in this posting, grounded in an employer quote the user can open.
   Importance = employer emphasis in this posting; never candidate match or
   selection probability. No evidence -> no displayed skill (the API already
   enforces it; this component renders nothing without evidence). */

const MODALITY_LABEL: Record<RequirementModality, string> = {
  get required() { return roleJobRequirementsPanelRequired2(); },
  get preferred() { return roleJobRequirementsPanelPreferred(); },
  get used_in_role() { return roleJobRequirementsPanelUsedInRole(); },
  get context() { return roleJobRequirementsPanelMentioned(); },
};

/** The server sends modality as a plain string — no database constraint backs it —
 *  so a value outside the known four renders as itself rather than as `undefined`. */
function modalityLabel(modality: string): string {
  return MODALITY_LABEL[modality as RequirementModality] ?? modality;
}

/** The same modality as a word inside a sentence, in the form the catalog
 *  writes for that place. */
function modalityInline(modality: string): string {
  return Object.keys(MODALITY_LABEL).includes(modality) ? roleJobRequirementsPanelModalityInline({ modality }) : modality;
}

const FACET_LABEL: Record<string, string> = {
  get technology() { return roleJobRequirementsPanelTechnology(); },
  get professional_skill() { return roleJobRequirementsPanelSkill(); },
  get industry() { return roleJobRequirementsPanelIndustry(); },
  get behavioral_competency() { return roleJobRequirementsPanelWaysOfWorking(); },
  get language() { return roleJobRequirementsPanelLanguage(); },
};

const CATEGORY_LABEL: Record<string, string> = {
  get language() { return roleJobRequirementsPanelLanguage(); },
  get framework() { return roleJobRequirementsPanelFramework(); },
  get ml_ai() { return roleJobRequirementsPanelMlAi(); },
  get cloud() { return roleJobRequirementsPanelCloud(); },
  get data() { return roleJobRequirementsPanelData(); },
  get infra() { return roleJobRequirementsPanelInfra(); },
  get security() { return roleJobRequirementsPanelSecurity(); },
  get industry() { return roleJobRequirementsPanelIndustry(); },
  get process() { return roleJobRequirementsPanelProcess(); },
  get leadership() { return roleJobRequirementsPanelLeadership(); },
  get collaboration() { return roleJobRequirementsPanelCollaboration(); },
};

const SUPPORTING_COLLAPSE = 6;

/** A years statement is a floor ("8+ years", "at least 8 years", "8-10 years"
 *  all read 8), so it prints as one. The parser reads whole years. */
function yearsFloor(n: number): string {
  return `${Number.isInteger(n) ? n : n.toFixed(1)}+`;
}

function yearsUnit(n: number): string {
  return roleJobRequirementsPanelYears({ count: n });
}

/** Every years number an experience line states, in the order written, each
 *  once: "10+ years, including 5+ leading teams" is 10 and 5. A row
 *  that kept only its headline still shows it. */
function linesYears(q: JobQualification): number[] {
  const stated = q.years_stated.length > 0 ? q.years_stated : q.years != null ? [q.years] : [];
  return [...new Set(stated)];
}

/** One row per line the posting prints. The extractor writes a row per KIND a
 *  line matches ("Bachelor's degree or equivalent practical
 *  experience.10 years of experience in ..." is education AND experience), and
 *  kind is never shown, so without merging such a line would be listed twice.
 * The merged line keeps its first place and its experience years. */
function qualificationLines(quals: JobQualification[]): JobQualification[] {
  const byLine = new Map<string, JobQualification>();
  for (const q of quals) {
    const key = `${q.modality}\n${q.display}`;
    const seen = byLine.get(key);
    if (!seen) byLine.set(key, q);
    else if (seen.years == null && q.years != null) byLine.set(key, { ...q, id: seen.id });
  }
  return [...byLine.values()];
}

/** `onShowSection` brings a quoted section of this role's own description into
    view: the detail owns where its description is, and a document-wide lookup
    would find the page behind an overlay first. Without it no quote offers
    the jump. */
export function JobRequirementsPanel({
  requirements,
  onShowSection,
}: {
  requirements?: JobRequirements;
  onShowSection?: (sectionKey: string) => void;
}) {
  const [openEvidence, setOpenEvidence] = useState<number | null>(null);
  const [showAllSupporting, setShowAllSupporting] = useState(false);
  const [showWaysEvidence, setShowWaysEvidence] = useState(false);

  if (!requirements) return null;

  if (requirements.state !== "ready") {
    return (
      <section className="req-panel" aria-label={roleJobRequirementsPanelRoleRequirements2()}>
        <PanelHead skills={[]} />
        <p className="req-empty">
          {roleJobRequirementsPanelThisPostingHasNoStored({ choice: (requirements.state === "pending") ? "yes" : "no" })}
        </p>
      </section>
    );
  }

  const skills = requirements.skills;
  const quals = qualificationLines(requirements.qualifications);

  // Grouping: hard skills (technology / professional_skill / language) rank in
  // the ledger; behavioural competencies live in their own group and never mix
  // into the technology ranking; industries are a separate substrate, never skills.
  const hard = skills.filter((s) =>
    ["technology", "professional_skill", "language"].includes(s.facet),
  );
  const ledger = hard.filter((s) => s.importance_band === "core" || s.importance_band === "important");
  const supporting = hard.filter((s) => s.importance_band === "supporting");
  const industry = skills.filter((s) => s.facet === "industry");
  const ways = skills.filter((s) => s.facet === "behavioral_competency");

  const empty = skills.length === 0 && quals.length === 0;

  return (
    <section className="req-panel" aria-label={roleJobRequirementsPanelRoleRequirements2()}>
      <PanelHead skills={hard} requiredYears={requirements.required_years} />

      {empty && (
        <p className="req-empty">
          {roleJobRequirementsPanelNoExplicitSkillRequirementsFound()}
        </p>
      )}

      {ledger.length > 0 && (
        <div className="req-group">
          <div data-selection="chrome" className="req-group-label">{roleJobRequirementsPanelCoreSkills()}</div>
          <ul className="req-ledger">
            {ledger.map((s) => (
              <SkillRow
                key={s.concept_id}
                skill={s}
                open={openEvidence === s.concept_id}
                onShowSection={onShowSection}
                onToggle={() =>
                  setOpenEvidence(openEvidence === s.concept_id ? null : s.concept_id)
                }
              />
            ))}
          </ul>
        </div>
      )}

      {supporting.length > 0 && (
        <div className="req-group">
          <div data-selection="chrome" className="req-group-label">{roleJobRequirementsPanelSupporting()}</div>
          <div className="req-chips">
            {(showAllSupporting ? supporting : supporting.slice(0, SUPPORTING_COLLAPSE)).map(
              (s) => (
                <Badge variant="outline" key={s.concept_id} title={s.evidence[0]?.quote}>
                  {skillName(s.slug)}
                  <span data-selection="chrome" className="req-mod"> · {modalityLabel(s.modality)}</span>
                </Badge>
              ),
            )}
            {supporting.length > SUPPORTING_COLLAPSE && !showAllSupporting && (
              <Button variant="link" className="ui-btn-quiet" onClick={() => setShowAllSupporting(true)}>
                <Msg of={roleJobRequirementsPanelShowMore} elems={{ value: supporting.length - SUPPORTING_COLLAPSE }} />
              </Button>
            )}
          </div>
        </div>
      )}

      {industry.length > 0 && (
        <div className="req-group">
          <div data-selection="chrome" className="req-group-label">{roleJobRequirementsPanelIndustry()}</div>
          <div className="req-chips">
            {industry.map((s) => (
              <Badge variant="outline" key={s.concept_id} title={s.evidence[0]?.quote}>
                {skillName(s.slug)}
                <span data-selection="chrome" className="req-mod"> · {modalityLabel(s.modality)}</span>
              </Badge>
            ))}
          </div>
        </div>
      )}

      {quals.length > 0 && (
        <div className="req-group">
          <div data-selection="chrome" className="req-group-label">{roleJobRequirementsPanelQualifications()}</div>
          <dl className="req-quals">
            {quals.map((q) => {
              const years = linesYears(q);
              return (
                <div className="req-qual-row" key={q.id}>
                  <dt className={q.modality === "required" ? "req-mod-required" : "req-mod-preferred"}>
                    {roleJobRequirementsPanelPreferred2({ choice: (q.modality === "required") ? "yes" : "no" })}
                  </dt>
                  <dd>{q.display}</dd>
                  {/* The line's own numbers, its headline strong. A long line's
                      display is cut at 160 characters, so this can be the only
                      place a late "5+ years" still shows. */}
                  {years.length > 0 && (
                    <dd className="req-qual-years">
                      {years.map((y, i) => (
                        <Fragment key={y}>
                          {i > 0 && " · "}
                          {y === q.years ? <strong>{yearsFloor(y)}</strong> : yearsFloor(y)}
                        </Fragment>
                      ))}{" "}
                      {yearsUnit(Math.max(...years))}
                    </dd>
                  )}
                </div>
              );
            })}
          </dl>
        </div>
      )}

      {ways.length > 0 && (
        <div className="req-group">
          <div data-selection="chrome" className="req-group-label">{roleJobRequirementsPanelWaysOfWorking()}</div>
          <div className="req-ways">
            <span>{ways.map((s) => skillName(s.slug)).join(" · ")}</span>
            <Button
              variant="link"
              className="ui-btn-quiet"
              aria-expanded={showWaysEvidence}
              onClick={() => setShowWaysEvidence(!showWaysEvidence)}
            >
              {roleJobRequirementsPanelShowEvidence({ choice: (showWaysEvidence) ? "yes" : "no" })}
            </Button>
          </div>
          {showWaysEvidence && (
            <div className="req-evidence" role="region" aria-label={roleJobRequirementsPanelWaysOfWorkingEvidence()}>
              {ways.map((s) =>
                s.evidence.slice(0, 1).map((e, i) => (
                  <EvidenceQuote key={`${s.concept_id}-${i}`} label={skillName(s.slug)} evidence={e} onShowSection={onShowSection} />
                )),
              )}
            </div>
          )}
        </div>
      )}
    </section>
  );
}

function PanelHead({
  skills,
  requiredYears = null,
}: {
  skills: JobSkill[];
  requiredYears?: number | null;
}) {
  const core = skills.filter((s) => s.importance_band === "core").length;
  const supporting = skills.filter((s) => s.importance_band === "supporting").length;
  const counted = core > 0 || supporting > 0;
  return (
    <header className="req-head">
      <div>
        <div className="eyebrow req-eyebrow">{roleJobRequirementsPanelRoleRequirements()}</div>
        <h2 className="req-title">
          {roleJobRequirementsPanelWhatThisRoleAsksFor()}
          <InfoTip label={roleJobRequirementsPanelAboutImportance()}>
            {roleJobRequirementsPanelImportanceReflectsHowStronglyThis()}
          </InfoTip>
        </h2>
      </div>
      {(requiredYears != null || counted) && (
        <div className="req-head-facts">
          {/* The posting's headline: the most years a REQUIRED line states.
              Preferred years never set it (`skills.extract.required_years`). */}
          {requiredYears != null && (
            <p className="req-years">
              <Msg of={roleJobRequirementsPanelRequired} elems={{ requiredYears: yearsFloor(requiredYears), requiredYears2: yearsUnit(requiredYears) }} />
            </p>
          )}
          {counted && (
            <div className="req-counts">
              {core > 0 && <span><Msg of={roleJobRequirementsPanelCore} elems={{ core: core }} /></span>}
              {core > 0 && supporting > 0 && <span className="req-counts-sep"> · </span>}
              {supporting > 0 && <span><Msg of={roleJobRequirementsPanelSupporting2} elems={{ supporting: supporting }} /></span>}
            </div>
          )}
        </div>
      )}
    </header>
  );
}

function SkillRow({
  skill,
  open,
  onToggle,
  onShowSection,
}: {
  skill: JobSkill;
  open: boolean;
  onToggle: () => void;
  onShowSection?: (sectionKey: string) => void;
}) {
  const sources = skill.evidence.length;
  const bandLabel = roleJobRequirementsPanelImportant({ choice: (skill.importance_band === "core") ? "yes" : "no" });
  const spoken = {
    count: sources,
    display: skillName(skill.slug),
    bandLabel: roleJobRequirementsPanelImportanceInline({ band: skill.importance_band }),
    modality: modalityInline(skill.modality),
    sources,
  };
  return (
    <li className="req-row-item">
      <button
        type="button"
        className={`req-row ${open ? "open" : ""}`}
        aria-expanded={open}
        aria-label={roleJobRequirementsPanelSkillSourcesShowEvidence(spoken)}
        onClick={onToggle}
      >
        <span className="req-cat">{CATEGORY_LABEL[skill.category] ?? FACET_LABEL[skill.facet]}</span>
        <span className="req-name">{skillName(skill.slug)}</span>
        <span className={`req-band req-band-${skill.importance_band}`}>{bandLabel}</span>
        <span
          className="req-meter"
          role="img"
          aria-label={roleJobRequirementsPanelRequirementSources(spoken)}
        >
          <span className="req-meter-fill" style={{ width: `${skill.importance_score}%` }} />
        </span>
        <span className="req-sources">
          <Msg of={roleJobRequirementsPanelSources} args={{ count: sources }} elems={{ sources: sources }} />
        </span>
      </button>
      {open && (
        <div className="req-evidence" role="region" aria-label={roleJobRequirementsPanelEvidence({ display: String(skillName(skill.slug)) })}>
          {skill.evidence.map((e, i) => (
            <EvidenceQuote key={i} evidence={e} onShowSection={onShowSection} />
          ))}
        </div>
      )}
    </li>
  );
}

function EvidenceQuote({
  evidence,
  label,
  onShowSection,
}: {
  evidence: JobSkill["evidence"][number];
  label?: string;
  onShowSection?: (sectionKey: string) => void;
}) {
  const sectionKey = evidence.section_key;
  return (
    <figure className="req-quote">
      <blockquote>“{evidence.quote}”</blockquote>
      <figcaption>
        {label && <span className="req-quote-skill">{label} · </span>}
        <span className="req-quote-src">
          {evidence.section_title ? (ownHeading(evidence.section_key, evidence.section_title) ?? <Content text={evidence.section_title} />) : (evidence.section_key ? evidence.section_key : roleJobRequirementsPanelTitle())}
        </span>
        <span className="req-quote-mod"> · {modalityLabel(evidence.modality)}</span>
        {sectionKey && onShowSection && (
          <Button variant="link" className="req-jump" onClick={() => onShowSection(sectionKey)}>
            {roleJobRequirementsPanelShowInDescription()}
          </Button>
        )}
      </figcaption>
    </figure>
  );
}
