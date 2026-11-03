import { NewMark } from "../NewMark";
import { useScopeDraft } from "../useScopeDraft";
import { ACCOUNTABLE, withAnswer } from "./walkModel";

/* Step 1: what you want to be accountable for. The four career tracks, worded
   forward and without the field split, on the existing select-card pattern.
   Picking an answer adds it as "any": every role of that kind. Dropping one
   forgets its narrowing. Nothing else moves: answers never share a role, so
   one cannot change another. */
export function AccountableStep() {
  const { catalog, selectedAnswers, replaceAnswers } = useScopeDraft();
  // A career track added since the last save arrives off and says so.
  const fresh = new Set((catalog?.tracks ?? []).filter((track) => track.new).map((track) => track.slug));
  const answers = selectedAnswers ?? new Map();

  return (
    <div className="select-card-grid walk-cards">
      {ACCOUNTABLE.map((answer) => (
        <label className="select-card" key={answer.slug}>
          <input
            aria-label={answer.label}
            type="checkbox"
            checked={answers.has(answer.slug)}
            onChange={() => replaceAnswers(withAnswer(answers, answer.slug, !answers.has(answer.slug)))}
          />
          <span className="select-card-label">{answer.label} <NewMark on={fresh.has(answer.slug)} /></span>
          <small>{answer.examples}</small>
        </label>
      ))}
    </div>
  );
}
