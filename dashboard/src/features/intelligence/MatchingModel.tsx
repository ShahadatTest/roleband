import { errorText } from "../../api/errorText";
import { number as copyNumber } from "../../copy/format";
// The model line, and every state it can be in.
//
// Switching models is a minutes-long job, so the line always shows an
// estimate, a way to stop, and a state for "it stopped halfway" (never
// settled while part of the corpus is still on the other model).
//
// Five states, one line:
//   settled      big model · Current                   → "Switch to the small model"
//   downloading  the model is still arriving; no choice is offered yet
//   converting   progress, time left, and one action: stop AND go back
//   interrupted  paused; finishes tonight, or finish/revert now
//   blocked      the download failed, the one state that is a fault
//
// The line's own action is a button, not an underlined phrase: it sits at the
// end of a row of plain facts and would otherwise read as one more of them.
// Both states that carry an action use the same rank in the same position, so
// the affordance does not change shape as the line changes state. That rank is
// `ghost` + `ui-btn-strong`, the app's toolbar rank, NOT a screen-local
// shape: emphasis inside one screen is not worth a shape no other screen
// speaks. See docs/ui.md
//
// Copy rules: the models are the big model and the small
// model; the limit is RAM, never disk; we never talk down our own product;
// exact measured numbers only, never vague quantities; the product never names
// itself; and the first sentence of a confirm describes the thing the user
// clicked, not our recommendation.
import { useState } from "react";
import { IntelligenceStatus, MatchingTier, api } from "../../api";
import { Dialog, Icon } from "../../ui";
import { Button } from "../../ui/Button";
import {
  aiAimLineCancel,
  aiMatchingModelAboutHr,
  aiMatchingModelAboutMin,
  aiMatchingModelBigModel,
  aiMatchingModelBigModel2,
  aiMatchingModelCheckYourInternetConnectionAnd,
  aiMatchingModelChooseAutomatically,
  aiMatchingModelCouldNotBeDownloaded,
  aiMatchingModelCurrent,
  aiMatchingModelDownloadProgress,
  aiMatchingModelDownloadingOfMb,
  aiMatchingModelFinishNow,
  aiMatchingModelGb,
  aiMatchingModelGb2,
  aiMatchingModelGoBackToThe,
  aiMatchingModelItIsTheRightFit,
  aiMatchingModelKeepTheComputerAwakeUntil,
  aiMatchingModelKeepWorkingWhileItRuns,
  aiMatchingModelLocalAiModel,
  aiMatchingModelLocalAiModelSwitch,
  aiMatchingModelMatchingModel,
  aiMatchingModelNotDownloaded,
  aiMatchingModelOfRolesUpdated,
  aiMatchingModelOtherModel,
  aiMatchingModelReRanked,
  aiMatchingModelRoles,
  aiMatchingModelRolesAreListedNewestFirst,
  aiMatchingModelRolesRanked,
  aiMatchingModelRolesReRanked,
  aiMatchingModelSmallModel,
  aiMatchingModelSmallModel2,
  aiMatchingModelSmallModelIsBuiltFor,
  aiMatchingModelStartTheSwitch,
  aiMatchingModelStopAndGoBackTo,
  aiMatchingModelStopAndGoBackTo2,
  aiMatchingModelStopAnytimeRestartAnytimeNothing,
  aiMatchingModelSwitchOnlyIfYouWant,
  aiMatchingModelSwitchToThe,
  aiMatchingModelSwitchingProgress,
  aiMatchingModelSwitchingToThe,
  aiMatchingModelText,
  aiMatchingModelTheBigModelProducesBetter,
  aiMatchingModelTheCouldNotBeDownloaded,
  aiMatchingModelTheRestFinishesTonightOn,
  aiMatchingModelTheSmallModelIsBuilt,
  aiMatchingModelTheSwitchToTheIs,
  aiMatchingModelUnderAMinute,
  aiMatchingModelUseThe,
  aiMatchingModelYouCanKeepWorkingMeanwhile,
  aiMatchingModelYourComputerHas,
} from "../../copy/gen/ai";
import { Msg } from "../../ui/Msg";

const OTHER: Record<MatchingTier, MatchingTier> = { fp32: "int8", int8: "fp32" };

/** What each artifact is called for a person. Never Exact/Compact, never the
 *  quantization — those name the file, not the thing the user gets. */
const NAME: Record<MatchingTier, string> = { get fp32() { return aiMatchingModelBigModel(); }, get int8() { return aiMatchingModelSmallModel(); } };
const NAME_LOWER: Record<MatchingTier, string> = { get fp32() { return aiMatchingModelBigModel2(); }, get int8() { return aiMatchingModelSmallModel2(); } };

const gb = (bytes: number) => Math.round(bytes / 1024 ** 3);

/** Rounded hard, and only ever from a measured rate. "About 18 minutes",
 *  never "17 m 43 s" — precision we cannot honour reads as a promise. */
function durationLabel(seconds: number | null | undefined): string | null {
  if (seconds == null || seconds <= 0) return null;
  const minutes = Math.round(seconds / 60);
  if (minutes < 1) return aiMatchingModelUnderAMinute();
  if (minutes < 90) return aiMatchingModelAboutMin({ minutes: minutes });
  return aiMatchingModelAboutHr({ round: Math.round(minutes / 60) });
}

export function MatchingModel({
  status,
  setStatus,
  onMutationChange,
}: {
  status: IntelligenceStatus;
  setStatus: (s: IntelligenceStatus) => void;
  /** Marks only the request edge; background work is derived from status. */
  onMutationChange?: (inFlight: boolean) => void;
}) {
  const [confirming, setConfirming] = useState<MatchingTier | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const m = status.matching;
  const active = (m.tier ?? null) as MatchingTier | null;
  const other = active ? OTHER[active] : null;
  const phase = m.job_phase;
  const stale = m.stale_count ?? 0;
  const otherTier = m.other_tier_count ?? 0;
  const ram = m.detected_ram_bytes;
  // A configured model with no pinned manifest answers without an estimate.
  const estimate = "estimate_seconds" in m ? m.estimate_seconds : null;

  const run = async (fn: () => Promise<IntelligenceStatus>) => {
    setSaving(true);
    setError(null);
    onMutationChange?.(true);
    try {
      setStatus(await fn());
    } catch (e) {
      setError(errorText(e));
    } finally {
      setSaving(false);
      onMutationChange?.(false);
    }
  };

  const switchTo = (tier: MatchingTier) => {
    setConfirming(null);
    return run(() => api.setMatchingTier(tier));
  };

  const stop = () => run(() => api.stopMatchingSwitch());

  // ---- downloading: no rows moved yet, so this is the cheapest way out ----
  if (m.status === "downloading" || phase === "downloading") {
    const done = m.downloaded_bytes;
    const totalBytes = Math.max(1, m.total_bytes);
    return (
      <>
        <div className="intel-model">
          <span className="intel-model-k">{aiMatchingModelLocalAiModel()}</span>
          <span>
            <b>{active ? NAME[active] : aiMatchingModelMatchingModel()}</b>{" "}
            <span data-selection="chrome" className="intel-model-note">
              <Msg of={aiMatchingModelDownloadingOfMb} elems={{ round: Math.round(done / 1024 ** 2), round2: Math.round(totalBytes / 1024 ** 2) }} />
            </span>
          </span>
          <span className="intel-bar" role="progressbar" aria-valuemin={0} aria-valuemax={totalBytes}
            aria-valuenow={done} aria-label={aiMatchingModelDownloadProgress()}>
            <i style={{ width: `${Math.round((done / totalBytes) * 100)}%` }} />
          </span>
          <span className="intel-model-end">
            <span data-selection="chrome" className="intel-model-note">{aiMatchingModelRolesAreListedNewestFirst()}</span>
            {other && (
              <Button className="ui-btn-strong" onClick={stop} disabled={saving}>
                {aiMatchingModelStopAndGoBackTo({ choice: (saving) ? "yes" : "no", nAME_LOWER: (saving) ? "" : String(NAME_LOWER[other]) })}
              </Button>
            )}
          </span>
        </div>
        {error && <div className="intel-error" role="alert">{error}</div>}
      </>
    );
  }

  // ---- converting: progress, time left, and one way out -------------------
  if (phase === "converting" && active) {
    const total = Math.max(1, m.corpus_total);
    const done = m.corpus_embedded;
    const left = durationLabel(estimate);
    return (
      <>
        <div className="intel-model">
          <span className="intel-model-k">{aiMatchingModelLocalAiModel()}</span>
          <span>
            <b><Msg of={aiMatchingModelSwitchingToThe} elems={{ nAME_LOWER: NAME_LOWER[active] }} /></b>
          </span>
          <span className="intel-bar" role="progressbar" aria-valuemin={0} aria-valuemax={total}
            aria-valuenow={done} aria-label={aiMatchingModelSwitchingProgress()}>
            <i style={{ width: `${Math.round((done / total) * 100)}%` }} />
          </span>
          <span data-selection="chrome" className="intel-model-note intel-mono">
            <Msg of={aiMatchingModelOfRolesUpdated} elems={{ done: copyNumber(done), total: copyNumber(total) }} />
            {aiMatchingModelText({ choice: (left) ? "yes" : "no", left: (left) ? String(left) : "" })}
          </span>
          <span className="intel-model-end">
            <Button className="ui-btn-strong" onClick={stop} disabled={saving}>
              {aiMatchingModelStopAndGoBackTo2({ choice: (saving) ? "yes" : "no", value: (saving) ? "" : String(other ? NAME_LOWER[other] : aiMatchingModelOtherModel()) })}
            </Button>
          </span>
        </div>
        <div className="intel-model-sub">{aiMatchingModelYouCanKeepWorkingMeanwhile()}</div>
        {error && <div className="intel-error" role="alert">{error}</div>}
      </>
    );
  }

  // ---- blocked: the model could not be fetched. The one fault state. ------
  if (m.status === "missing") {
    return (
      <>
        <div className="intel-model">
          <span className="intel-model-k">{aiMatchingModelLocalAiModel()}</span>
          <span>
            <b>{active ? NAME[active] : aiMatchingModelMatchingModel()}</b>{" "}
            <span data-selection="chrome" className="intel-model-note">{aiMatchingModelNotDownloaded()}</span>
          </span>
        </div>
        <div className="intel-notice is-warn" role="alert">
          <b>
            {active
              ? <Msg of={aiMatchingModelTheCouldNotBeDownloaded} elems={{ value: NAME_LOWER[active] }} />
              : aiMatchingModelCouldNotBeDownloaded()}
          </b>
          <span>{aiMatchingModelCheckYourInternetConnectionAnd()}</span>
          <span className="intel-notice-acts">
            {other && (
              <Button variant="primary" onClick={() => switchTo(other)} disabled={saving}>
                <Msg of={aiMatchingModelUseThe} elems={{ nAME_LOWER: NAME_LOWER[other] }} />
              </Button>
            )}
          </span>
        </div>
        {error && <div className="intel-error" role="alert">{error}</div>}
      </>
    );
  }

  // ---- interrupted: a switch that stopped partway ------------------------
  // `reembedding: false` alone would render as settled while a chunk of the
  // corpus is still on the other model; rows on the other model are what mark
  // it. Rows never ranked are a scan's backlog, not a switch.
  const interrupted = otherTier > 0 && phase === "none" && active;

  return (
    <>
      <div className="intel-model">
        <span className="intel-model-k">{aiMatchingModelLocalAiModel()}</span>
        <span>
          <b>{active ? NAME[active] : "—"}</b>{" "}
          <span data-selection="chrome" className="intel-model-note">
            {aiMatchingModelCurrent()}
          </span>
        </span>
        <span className="intel-model-end">
          <span data-selection="chrome" className="intel-model-note intel-mono">
            {aiMatchingModelRolesRanked({ choice: (interrupted) ? "yes" : "no", value: (interrupted) ? String(copyNumber((m.corpus_total - stale))) : "", corpus_total: (interrupted) ? String(copyNumber(m.corpus_total)) : "", corpus_embedded: (interrupted) ? "" : String(copyNumber(m.corpus_embedded)) })}
          </span>
          {/* The only signal that the user pinned this rather than letting
              the computer decide: the status word is "Current" either way,
              because which one is RUNNING is the fact the line is about. */}
          {m.chosen_by === "user" && !interrupted && (
            <Button variant="link" className="ui-btn-quiet" onClick={() => run(() => api.setMatchingTier(null))} disabled={saving}>
              {aiMatchingModelChooseAutomatically()}
            </Button>
          )}
          {other && !interrupted && (
            <Button className="ui-btn-strong" onClick={() => setConfirming(other)} disabled={saving}>
              <Msg of={aiMatchingModelSwitchToThe} elems={{ nAME_LOWER: NAME_LOWER[other] }} />
            </Button>
          )}
        </span>
      </div>

      {interrupted && active && (
        <div className="intel-notice" role="status">
          <b><Msg of={aiMatchingModelTheSwitchToTheIs} elems={{ nAME_LOWER: NAME_LOWER[active] }} /></b>
          <span>{aiMatchingModelTheRestFinishesTonightOn()}</span>
          <span className="intel-notice-acts">
            {/* Its own call, not a re-selection of the current tier: the
                choice is not changing, only the work owed under it. */}
            <Button
              className="ui-btn-strong"
              onClick={() => {
                return run(() => api.resumeMatchingSwitch());
              }}
              disabled={saving}
            >
              {aiMatchingModelFinishNow({ choice: (durationLabel(estimate)) ? "yes" : "no", estimate: (durationLabel(estimate)) ? String(durationLabel(estimate)) : "" })}
            </Button>
            {other && (
              <Button variant="link" className="ui-btn-quiet" onClick={() => switchTo(other)} disabled={saving}>
                <Msg of={aiMatchingModelGoBackToThe} elems={{ nAME_LOWER: NAME_LOWER[other] }} />
              </Button>
            )}
          </span>
        </div>
      )}

      {error && <div className="intel-error" role="alert">{error}</div>}

      {confirming && active && (
        <SwitchDialog
          target={confirming}
          current={active}
          ramBytes={ram}
          ramThresholdBytes={m.ram_threshold_bytes}
          corpusTotal={m.corpus_total}
          estimateSeconds={
            m.tiers?.find((t) => t.tier === confirming)?.switch_seconds ?? null
          }
          onClose={() => setConfirming(null)}
          onConfirm={() => switchTo(confirming)}
        />
      )}
    </>
  );
}

/** The confirm, shaped as a work order rather than a questionnaire: the user
 *  is scheduling a measured job, not answering a quiz. The header is the
 *  routing slip (from -> to), the hero is the honest cost (the measured
 *  duration, or the exact role count when no rate has been measured yet), the
 *  guarantees are a checklist, and the recommendation is a quiet aside at the
 *  bottom: result quality first, then the RAM facts, both numbers from real
 *  readings and never invented. */
function SwitchDialog({
  target,
  current,
  ramBytes,
  ramThresholdBytes,
  corpusTotal,
  estimateSeconds,
  onClose,
  onConfirm,
}: {
  target: MatchingTier;
  current: MatchingTier;
  ramBytes: number | null;
  /** The RAM below which the automatic choice takes the small model, as the
   *  server decides it; stated to the user because it is their actual
   *  decision criterion. */
  ramThresholdBytes: number;
  corpusTotal: number;
  estimateSeconds: number | null;
  onClose: () => void;
  onConfirm: () => void;
}) {
  const toSmall = target === "int8";
  const duration = durationLabel(estimateSeconds);

  // Only stated when detection actually succeeded: a fabricated capacity
  // would read "suits 0 GB of RAM".
  const ramGb = ramBytes != null ? gb(ramBytes) : null;
  const ramThresholdGb = gb(ramThresholdBytes);

  // Two tiers, not one paragraph: the lead is the decision ("which, and when
  // would you switch"), the annotation is the evidence behind it. The RAM
  // numbers stay VISIBLE rather than hiding behind a hover — they are the fact
  // that decides the question, and a touch device has no hover to give.
  // Two lines, not one wrapped sentence: the verdict and the condition under
  // which you would switch anyway are separate thoughts, and breaking them
  // keeps the second from being read as a tail of the first.
  const leadLines = toSmall
    ? [aiMatchingModelTheBigModelProducesBetter(), aiMatchingModelSwitchOnlyIfYouWant()]
    : [aiMatchingModelTheBigModelProducesBetter()];

  // The evidence is two numbers whose GAP is the whole argument, so when both
  // are known it is drawn as a comparison rather than written as a sentence —
  // 16 beside 48 is read at a glance, where the prose had to be parsed. Prose
  // remains for the cases with nothing to compare: RAM undetected, or the
  // reverse switch, where the machine's capacity is the only figure.
  const spec =
    toSmall && ramGb != null
      ? [
          { k: aiMatchingModelSmallModelIsBuiltFor(), v: String(ramThresholdGb), unit: "GB" },
          { k: aiMatchingModelYourComputerHas(), v: String(ramGb), unit: "GB" },
        ]
      : null;

  const evidence = spec
    ? null
    : toSmall ? (
        <>
          <Msg of={aiMatchingModelTheSmallModelIsBuilt} elems={{ b: <b><Msg of={aiMatchingModelGb} elems={{ ramThresholdGb }} /></b> }} />
        </>
      ) : ramGb != null ? (
        <>
          <Msg of={aiMatchingModelItIsTheRightFit} elems={{ b: <b><Msg of={aiMatchingModelGb2} elems={{ ramGb: ramGb }} /></b> }} />
        </>
      ) : null;

  // The dialog's accessible name IS its visible heading, not a second string
  // only a screen reader hears (`Dialog` takes an aria-label, so the only way
  // to keep them identical is to pass the heading's own text).
  const label = aiMatchingModelLocalAiModelSwitch();

  return (
    <Dialog isOpen onClose={onClose} label={label} width={520} className="app-overlay">
      <div className="ledger-form intel-order">
        <div className="intel-order-head">
          {/* The heading is real, and carries the dialog's accessible name, so
              the screen and assistive tech are told the same title. */}
          <h2 className="intel-order-k">{label}</h2>
          <span className="intel-order-route">
            <span>{NAME[current]}</span>
            <Icon name="arrowRight" size={16} />
            <span>{NAME[target]}</span>
          </span>
        </div>
        <div className="intel-order-hero">
          {duration ? (
            <>
              <b>{duration}</b>
              <span><Msg of={aiMatchingModelRolesReRanked} elems={{ corpusTotal: copyNumber(corpusTotal) }} /></span>
            </>
          ) : (
            // No measured rate yet, so no duration may be stated — the exact
            // role count is still true, so the count becomes the hero.
            <>
              <b><Msg of={aiMatchingModelRoles} elems={{ corpusTotal: copyNumber(corpusTotal) }} /></b>
              <span>{aiMatchingModelReRanked()}</span>
            </>
          )}
        </div>
        <ul className="intel-order-checks">
          <li>
            <Icon name="check" size={14} />
            {aiMatchingModelKeepWorkingWhileItRuns()}
          </li>
          <li>
            <Icon name="check" size={14} />
            {aiMatchingModelStopAnytimeRestartAnytimeNothing()}
          </li>
          <li className="is-await">
            <Icon name="clock" size={14} />
            {aiMatchingModelKeepTheComputerAwakeUntil()}
          </li>
        </ul>
        <div className={`intel-order-note${spec ? " is-split" : ""}`}>
          <p className="intel-order-lead">
            {leadLines.map((line) => (
              <span key={line}>{line}</span>
            ))}
          </p>
          {spec && (
            <dl className="intel-order-spec">
              {spec.map((row) => (
                <div key={row.k}>
                  <dt>{row.k}</dt>
                  {/* The unit is subordinate to the figure, not its equal: at
                      one mono size "16 GB" reads as two words with a gap. */}
                  <dd>
                    {row.v} <span>{row.unit}</span>
                  </dd>
                </div>
              ))}
            </dl>
          )}
          {evidence && (
            <p className="intel-order-evidence">
              <Icon name="info" size={14} />
              <span>{evidence}</span>
            </p>
          )}
        </div>
        <div className="ledger-form-actions">
          <Button className="ui-btn-strong" onClick={onClose}>
            {aiAimLineCancel()}
          </Button>
          <Button variant="primary" onClick={onConfirm}>
            {aiMatchingModelStartTheSwitch()}
          </Button>
        </div>
      </div>
    </Dialog>
  );
}
