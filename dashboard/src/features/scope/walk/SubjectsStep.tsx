import { number as copyNumber } from "../../../copy/format";
import { useMemo, useState } from "react";
import { SearchField } from "../../../ui/SearchField";
import { useScopeDraft } from "../useScopeDraft";
import { matches } from "./RolesStep";
import { VERB_LABELS, withLine, withoutLine, type ModifierLine, type Verb } from "./walkModel";
import { untaggedUnder, vetoConflicts } from "./walkProgress";
import {
  profileScopeSectionBusinessFunctions,
  profileScopeSectionIndustries,
  profileSubjectsStepChooseAListThenTick,
  profileSubjectsStepFilterInterests,
  profileSubjectsStepFilterInterests2,
  profileSubjectsStepNothingCalled,
  profileSubjectsStepOfYourRolesArenT,
  profileSubjectsStepPicked,
  profileSubjectsStepRemovesOfTheRolesYou,
  profileSubjectsStepRolesAboutTheseDropOff,
  profileSubjectsStepSwitchToThis,
  profileSubjectsStepTechnologies,
  profileSubjectsStepYouLlSeeRolesAbout,
} from "../../../copy/gen/profile";
import { Msg } from "../../../ui/Msg";
import { domainHint, domainName } from "../../../copy/vocab";

/* Step 5: interests. Two lists, filled the same way: choose a list, then
   tick what goes in it. The list is the step's first decision and stays in
   sight the whole time: two large radio cards, "Interested in" and "Not
   interested in", each saying what it does and how many it holds, the chosen
   one filled and marked "Picking now", the other offering the switch. The
   pair sticks to the top of the scroll while the cards pass beneath it, and
   the chosen list's colour carries into the cards below (ink for interested,
   the danger hue for not interested), so a tick always shows which list it
   lands in. A segmented switch would demote the decision to chrome. Then the
   interests as
   the walk's one selection object, the select-card, grouped under
   Technologies, Industries and Business functions, with the same filter
   field as the roles step. A card already picked under the other list wears
   that list's name, in its colour, in place of its hint. The cards themselves
   show the picks; Summary reads them back across both lists.

   Below the cards, two notes about the draft, never the market: the roles
   it keeps that carry no subject, which no pick here removes, and a
   "not interested in" pick that takes out most of a row picked on Which
   roles, the one place the two steps contradict each other. */

const KINDS: readonly { kind: "technology" | "industry" | "function"; heading: string }[] = [
  { kind: "technology", get heading() { return profileSubjectsStepTechnologies(); } },
  { kind: "industry", get heading() { return profileScopeSectionIndustries(); } },
  { kind: "function", get heading() { return profileScopeSectionBusinessFunctions(); } },
];

const VERBS: readonly { value: Verb; effect: string }[] = [
  { value: "interested", get effect() { return profileSubjectsStepYouLlSeeRolesAbout(); } },
  { value: "avoid", get effect() { return profileSubjectsStepRolesAboutTheseDropOff(); } },
];

export function SubjectsStep({
  lines, onChange,
}: {
  lines: ModifierLine[];
  onChange: (lines: ModifierLine[]) => void;
}) {
  const { catalog, scopeIndex, scopeSelection, progress } = useScopeDraft();
  const [verb, setVerb] = useState<Verb>("interested");
  const [query, setQuery] = useState("");
  const untagged = useMemo(
    () => (catalog ? untaggedUnder(scopeIndex, catalog, scopeSelection, progress) : null),
    [catalog, scopeIndex, scopeSelection, progress],
  );
  const conflicts = useMemo(
    () => (catalog ? vetoConflicts(scopeIndex, catalog, scopeSelection) : []),
    [catalog, scopeIndex, scopeSelection],
  );
  if (!catalog) return null;

  const domains = catalog.domains ?? [];
  const displayOf = (slug: string) => domainName(slug);
  const lineFor = (slug: string) => lines.find((line) => line.subject === slug);
  // By name and hint, never the postings' department names, which match the
  // wrong world ("Finance" would find AI & Machine Learning).
  const shown = domains.filter((domain) => matches(query, domainName(domain.slug), domainHint(domain.slug)));

  const toggle = (slug: string) => {
    const line = lineFor(slug);
    if (line && line.verb === verb) onChange(withoutLine(lines, slug));
    else onChange(withLine(lines, { verb, subject: slug }));
  };

  return (
    <>
      <fieldset className="walk-mode" data-verb={verb}>
        <legend className="walk-mode-legend" data-selection="chrome">{profileSubjectsStepChooseAListThenTick()}</legend>
        <div className="walk-mode-options">
          {VERBS.map((option) => {
            const current = verb === option.value;
            const picked = lines.filter((line) => line.verb === option.value).length;
            return (
              <label
                className="select-card walk-mode-option"
                data-verb={option.value}
                key={option.value}
              >
                <input
                  type="radio"
                  name="walk-verb"
                  checked={current}
                  aria-label={VERB_LABELS[option.value]}
                  aria-describedby={`walk-mode-${option.value}`}
                  onChange={() => setVerb(option.value)}
                />
                <span className="walk-mode-title">{VERB_LABELS[option.value]}</span>
                <span className="walk-mode-state" data-selection="chrome">
                  {profileSubjectsStepSwitchToThis({ choice: (current) ? "yes" : "no" })}
                </span>
                <small id={`walk-mode-${option.value}`}>{option.effect}</small>
                <span className="walk-mode-count" data-selection="chrome">
                  {profileSubjectsStepPicked({ choice: (picked === 0) ? "yes" : "no", picked: (picked === 0) ? "" : picked })}
                </span>
              </label>
            );
          })}
        </div>
      </fieldset>

      <div className="walk-picker" role="group" aria-label={VERB_LABELS[verb]} data-verb={verb}>
        <SearchField
          size="md"
          className="walk-filter"
          label={profileSubjectsStepFilterInterests()}
          placeholder={profileSubjectsStepFilterInterests2()}
          value={query}
          onChange={setQuery}
        />
        {shown.length === 0 && <p className="walk-empty"><Msg of={profileSubjectsStepNothingCalled} elems={{ query: query.trim() }} /></p>}
        {KINDS.map(({ kind, heading }) => {
          const members = shown.filter((domain) => domain.kind === kind);
          if (members.length === 0) return null;
          return (
            <div className="walk-picker-kind" key={kind}>
              <span className="walk-head" data-selection="chrome">{VERB_LABELS[verb]} · {heading}</span>
              <div className="select-card-grid walk-cards">
                {members.map((domain) => {
                  const line = lineFor(domain.slug);
                  const on = line?.verb === verb;
                  const other = line && line.verb !== verb ? VERB_LABELS[line.verb] : null;
                  return (
                    <label className={`select-card${other ? " is-other" : ""}`} key={domain.slug}>
                      <input
                        type="checkbox"
                        checked={on}
                        aria-label={domainName(domain.slug)}
                        onChange={() => toggle(domain.slug)}
                      />
                      <span className="select-card-label">{domainName(domain.slug)}</span>
                      {/* A pick under the other verb takes the sub-line, as a partly-on
                          role card does on step 4, so the name keeps its two lines. */}
                      {other ? (
                        <small><span className="walk-card-tag" data-selection="chrome" data-verb={line!.verb}>{other}</span></small>
                      ) : (
                        /* What the world covers, one line (DomainGroup.hint). */
                        <small data-selection="content">{domainHint(domain.slug)}</small>
                      )}
                    </label>
                  );
                })}
              </div>
            </div>
          );
        })}
      </div>

      {conflicts.map((conflict) => (
        <p className="walk-note" role="note" key={`${conflict.subject}:${conflict.track}:${conflict.row.key}`}>
          <Msg of={profileSubjectsStepRemovesOfTheRolesYou} elems={{ avoid: VERB_LABELS.avoid, subject: displayOf(conflict.subject), dropped: copyNumber(conflict.dropped), of: copyNumber(conflict.of), label: conflict.row.label }} />
        </p>
      ))}
      {untagged && untagged.untagged > 0 && (
        <p className="walk-note" role="note">
          <Msg of={profileSubjectsStepOfYourRolesArenT} elems={{ untagged: copyNumber(untagged.untagged), of: copyNumber(untagged.of) }} />
        </p>
      )}
    </>
  );
}
