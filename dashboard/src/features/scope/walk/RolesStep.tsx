import { number as copyNumber } from "../../../copy/format";
import { useMemo, useState } from "react";
import { SearchField } from "../../../ui/SearchField";
import { Segmented } from "../../../ui/Segmented";
import { NewMark } from "../NewMark";
import { countByOption, type ScopeAxesSelection, type ScopeIndex } from "../scopeCells";
import { useScopeDraft } from "../useScopeDraft";
import {
  ACCOUNTABLE, ROLE_QUESTIONS, accountableFor, rowOn, withRow,
  type AnswerRoles, type Answers, type TrackSlug,
} from "./walkModel";
import {
  profileRolesStepCraftFor,
  profileRolesStepFilterRoles,
  profileRolesStepFilterRoles2,
  profileRolesStepNothingCalledUnder,
  profileRolesStepPickAKindOfRole,
  profileRolesStepRoles,
} from "../../../copy/gen/profile";
import { Msg } from "../../../ui/Msg";

/* Step 4: which roles of each kind. One block per answer from step 1, its
   cards unticked until the person picks: nothing ticked is every role of that
   kind (including ones no card names), as an empty World keeps every world,
   and ticked cards are the only roles kept. A click in one block never
   moves another: each answer keeps its own roles. The cards are
   the select-card step 1 uses, each saying how many roles it holds under the
   other answers (outside setup, which counts nothing), and above them the filter field, so the list can grow
   without the person scrolling for a name. A specialist picks a craft first
   and sees that craft's cards; a search looks across every craft. */
export function RolesStep() {
  const { catalog, selectedAnswers, replaceAnswers, scopeIndex, scopeSelection, countsShown } = useScopeDraft();
  // Role families added since the last save: a row naming one says New.
  const fresh = new Set((catalog?.categories ?? []).flatMap((category) => category.groups).filter((group) => group.new).map((group) => group.slug));
  const answers = selectedAnswers ?? new Map<string, AnswerRoles>();
  const picked = ACCOUNTABLE.filter((answer) => answers.has(answer.slug));
  const [query, setQuery] = useState("");

  if (picked.length === 0) return <p className="walk-note">{profileRolesStepPickAKindOfRole()}</p>;
  return (
    <>
      <SearchField
        size="md"
        className="walk-filter"
        label={profileRolesStepFilterRoles()}
        placeholder={profileRolesStepFilterRoles2()}
        value={query}
        onChange={setQuery}
      />
      {picked.map((answer) => (
        <RoleQuestionBlock
          key={answer.slug}
          track={answer.slug}
          answers={answers}
          query={query}
          fresh={fresh}
          index={countsShown ? scopeIndex : null}
          selection={scopeSelection}
          onChange={replaceAnswers}
        />
      ))}
    </>
  );
}

export function matches(query: string, ...texts: (string | undefined)[]): boolean {
  const needle = query.trim().toLowerCase();
  if (!needle) return true;
  return texts.some((text) => text?.toLowerCase().includes(needle));
}

function RoleQuestionBlock({
  track, answers, query, fresh, index, selection, onChange,
}: {
  track: TrackSlug;
  answers: Answers;
  query: string;
  fresh: Set<string>;
  /** Null when the walk shows no counts: each card says its examples alone. */
  index: ScopeIndex | null;
  selection: ScopeAxesSelection;
  onChange: (answers: Answers) => void;
}) {
  const question = ROLE_QUESTIONS[track];
  const answer = accountableFor(track)!;
  const roles = answers.get(track) ?? "any";
  const crafts = question.crafts;
  const firstOnCraft = question.rows.find((row) => rowOn(roles, row))?.craft;
  const [craft, setCraft] = useState<string>(firstOnCraft ?? crafts?.[0] ?? "");
  const searching = query.trim().length > 0;
  const rows = question.rows
    .filter((row) => searching || !crafts || row.craft === craft)
    .filter((row) => matches(query, row.label, row.examples, row.craft));
  /* What a card holds: roles of this kind in its families, under every other
     answer. One scan of the joint per kind, by family, kept until the draft
     moves, so a keystroke in the filter counts nothing again. A cell carries
     one family, so a card's count is the sum over its own families. */
  const byFamily = useMemo(
    () => (index?.ready
      ? countByOption(index, { ...selection, answers: new Map<string, "any">([[track, "any"]]) }, "roles")
      : null),
    [index, selection, track],
  );
  const holds = (families: readonly string[]) => byFamily
    ? [...new Set(families)].reduce((sum, family) => sum + (byFamily.get(family) ?? 0), 0)
    : null;

  return (
    <section className="walk-roles" aria-label={answer.label}>
      <div className="walk-register-head">
        <h3 className="walk-register-title">{answer.label}</h3>
      </div>
      {crafts && !searching && (
        <Segmented
          label={profileRolesStepCraftFor({ label: String(answer.label) })}
          value={craft}
          onChange={setCraft}
          options={crafts.map((name) => ({ value: name, label: name }))}
          className="walk-crafts"
        />
      )}
      {rows.length === 0 ? (
        <p className="walk-empty"><Msg of={profileRolesStepNothingCalledUnder} elems={{ query: query.trim(), label: answer.label.toLowerCase() }} /></p>
      ) : (
        <div className="select-card-grid walk-cards">
          {rows.map((row) => {
            const on = rowOn(roles, row);
            const count = holds(row.families);
            return (
              <label className="select-card" key={row.key}>
                <input
                  type="checkbox"
                  checked={on}
                  aria-label={`${row.label} (${answer.label})`}
                  onChange={(event) => onChange(withRow(answers, track, row.key, event.target.checked))}
                />
                <span className="select-card-label">{row.label} <NewMark on={row.families.some((family) => fresh.has(family))} /></span>
                {/* The count leads, so a long line of examples can never clip it. */}
                <small>{count === null ? row.examples : profileRolesStepRoles({ count: count, count2: String(copyNumber(count)), examples: String(row.examples) })}</small>
              </label>
            );
          })}
        </div>
      )}
    </section>
  );
}
