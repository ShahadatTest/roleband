import type { DuplicateLLMAssessment } from "../../api";
import { DECISION_COPY, RelationshipDecision } from "./decision";
import {
  duplicatesDecisionConsoleAi,
  duplicatesDecisionConsoleAiJudgment,
  duplicatesDecisionConsoleAiJudgmentUnavailable,
  duplicatesDecisionConsoleAskAi,
  duplicatesDecisionConsoleAskTheModel,
  duplicatesDecisionConsoleCurrent,
  duplicatesDecisionConsoleGetAnOptionalIndependentAssessment,
  duplicatesDecisionConsoleLocalModelAssessment,
  duplicatesDecisionConsoleMakeADecision,
  duplicatesDecisionConsoleMakeADecision2,
  duplicatesDecisionConsoleTokensMs,
  duplicatesDecisionConsoleUncertain,
  duplicatesDecisionConsoleWhatIsTheRelationship,
  duplicatesDecisionConsoleYourJudgment,
} from "../../copy/gen/duplicates";
import { Msg } from "../../ui/Msg";

/* The two decision surfaces: the queue's fixed console (with the optional AI
 * advisory) and the history editor's inline bar. Both present the same three
 * verdicts; only the queue offers the model's opinion, and the advice never
 * writes a verdict itself: that separation is a pinned behavior
 * (tests/ux/review.spec.ts). */

export function QueueDecisionConsole({
  busy,
  aiBusy,
  aiError,
  assessment,
  onAnalyze,
  onDecide,
}: {
  busy: boolean;
  aiBusy: boolean;
  aiError: string | null;
  assessment: DuplicateLLMAssessment | null;
  onAnalyze: () => void;
  onDecide: (decision: RelationshipDecision) => void;
}) {
  const options: Array<{ decision: RelationshipDecision; key: string }> = [
    { decision: "different", key: "N" },
    { decision: "twin", key: "T" },
    { decision: "duplicate", key: "D" },
  ];
  return (
    <section className={`review-decision-console${assessment ? " has-ai-response" : ""}`} aria-label={duplicatesDecisionConsoleMakeADecision()}>
      {aiError ? (
        <div className="review-console-ai-error" role="alert"><strong>{duplicatesDecisionConsoleAiJudgmentUnavailable()}</strong><span>{aiError}</span></div>
      ) : assessment ? (
        <ConsoleAssessment result={assessment} />
      ) : null}

      <div className="review-console-options">
        {options.map(({ decision, key }) => (
          <button
            key={decision}
            type="button"
            className={`review-console-option decision-${decision}`}
            disabled={busy || aiBusy}
            onClick={() => onDecide(decision)}
            title={DECISION_COPY[decision].note}
          >
            <span className="review-decision-radio" aria-hidden="true" />
            <strong>{DECISION_COPY[decision].label}</strong>
            <kbd>{key}</kbd>
          </button>
        ))}
        <button
          aria-label={duplicatesDecisionConsoleAskTheModel()}
          className="review-console-option review-console-ai"
          type="button"
          onClick={onAnalyze}
          disabled={aiBusy || busy}
          title={duplicatesDecisionConsoleGetAnOptionalIndependentAssessment()}
        >
          <span className="review-console-option-mark" aria-hidden="true">{duplicatesDecisionConsoleAi()}</span>
          <strong>{duplicatesDecisionConsoleAskAi({ choice: (aiBusy) ? "v1" : (assessment) ? "v2" : "v3" })}</strong>
        </button>
      </div>
    </section>
  );
}

function ConsoleAssessment({ result }: { result: DuplicateLLMAssessment }) {
  const answer = result.assessment;
  const confidence = `${Math.round(answer.confidence * 100)}%`;
  const recommendation = duplicatesDecisionConsoleUncertain({ choice: (answer.recommendation === "confirmed") ? "v1" : (answer.recommendation === "rejected") ? "v2" : "v3" });
  return (
    <section className={`review-console-assessment assessment-${answer.recommendation}`} aria-label={duplicatesDecisionConsoleLocalModelAssessment()}>
      <div>
        <span>{duplicatesDecisionConsoleAiJudgment()}</span>
        <strong>{recommendation}</strong>
        <b>{confidence}</b>
      </div>
      <p>{answer.summary}</p>
      <small><Msg of={duplicatesDecisionConsoleTokensMs} elems={{ model: result.model, value: result.metrics.total_tokens ?? "—", wall_time_ms: result.metrics.wall_time_ms }} /></small>
    </section>
  );
}

export function DecisionBar({
  busy,
  current,
  onDecide,
}: {
  busy: boolean;
  current?: RelationshipDecision;
  onDecide: (decision: RelationshipDecision) => void;
}) {
  const options: Array<{ decision: RelationshipDecision; key: string }> = [
    { decision: "different", key: "N" },
    { decision: "twin", key: "T" },
    { decision: "duplicate", key: "D" },
  ];
  return (
    <section className="review-decision-bar" aria-label={duplicatesDecisionConsoleMakeADecision2({ choice: (current) ? "yes" : "no" })}>
      <div className="review-decision-intro">
        <span>{duplicatesDecisionConsoleYourJudgment({ choice: (current) ? "yes" : "no" })}</span>
        <strong>{duplicatesDecisionConsoleWhatIsTheRelationship({ choice: (current) ? "yes" : "no" })}</strong>
      </div>
      <div className="review-decision-options">
        {options.map(({ decision, key }) => (
          <button
            key={decision}
            type="button"
            className={`review-decision-option decision-${decision}`}
            aria-pressed={current === decision}
            disabled={busy || current === decision}
            onClick={() => onDecide(decision)}
          >
            <span className="review-decision-radio" aria-hidden="true" />
            <span><strong>{DECISION_COPY[decision].label}</strong><small>{DECISION_COPY[decision].note}</small></span>
            {!current && <kbd>{key}</kbd>}
            {current === decision && <em>{duplicatesDecisionConsoleCurrent()}</em>}
          </button>
        ))}
      </div>
    </section>
  );
}
