import { errorText } from "../../api/errorText";
import { number as copyNumber } from "../../copy/format";
// The aim sentence, owned by Settings > Intelligence > Fit ranking.
//
// It never decides which roles reach the radar, it only orders them when the
// board is sorted by Best fit. That makes it a ranking preference, and the ranking card is where a
// person can see what it does: the field and the preview re-rank on save.
import { FormEvent, useEffect, useRef, useState } from "react";
import { IntelligenceFit, api } from "../../api";
import { Button, useEscapeLayer } from "../../ui";
import {
  aiAimLineAddYourAim,
  aiAimLineCancel,
  aiAimLineCouldnTSaveYourAim,
  aiAimLineExample,
  aiAimLineOpenRolesRankedByHow,
  aiAimLineOpenRolesRankedByWhat,
  aiAimLineOpenRolesSortedByDate,
  aiAimLineOpenRolesSortedByDate2,
  aiAimLineRolesClosestToItCome,
  aiAimLineSave,
  aiAimLineYourAim,
  aiAimLineYourAimInOneSentence,
} from "../../copy/gen/ai";
import { Content } from "../../ui/Content";
import { Msg } from "../../ui/Msg";

const MAX_LENGTH = 200;

export function AimLine({
  fit,
  onSaved,
}: {
  fit: IntelligenceFit;
  /** Called with the saved sentence; the card re-reads its ranking. */
  onSaved: (statement: string) => void;
}) {
  const statement = fit.intent_statement ?? "";
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState(statement);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const openRef = useRef<HTMLButtonElement>(null);
  const returnFocus = useRef(false);

  useEffect(() => {
    if (editing) inputRef.current?.focus();
    else if (returnFocus.current) {
      returnFocus.current = false;
      openRef.current?.focus();
    }
  }, [editing]);

  const open = () => {
    setValue(statement);
    setError(null);
    setEditing(true);
  };
  const close = () => {
    returnFocus.current = true;
    setEditing(false);
  };

  // Escape leaves the editor without saving. A layer, not a key handler of its
  // own: a dialog opened over the page still takes the press first.
  useEscapeLayer(editing, busy ? undefined : close, "page");

  const trimmed = value.trim();
  const unchanged = trimmed === statement.trim();

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (unchanged) return close();
    setBusy(true);
    setError(null);
    try {
      const saved = await api.saveIntentStatement(trimmed);
      onSaved(saved.intent_statement);
      close();
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  };

  if (editing) {
    return (
      <form
        className="ledger-form intel-aim"
        aria-label={aiAimLineYourAim()}
        onSubmit={submit}
      >
        <div>
          <label htmlFor="intel-aim-input">{aiAimLineYourAimInOneSentence()}</label>
          <input
            ref={inputRef}
            id="intel-aim-input"
            type="text"
            maxLength={MAX_LENGTH}
            placeholder={aiAimLineExample()}
            value={value}
            onChange={(event) => setValue(event.target.value)}
            aria-describedby="intel-aim-hint"
          />
          <small id="intel-aim-hint" className="intel-aim-hint">
            {aiAimLineRolesClosestToItCome()}
          </small>
        </div>
        {error && (
          <p className="intel-aim-error" role="alert">
            <Msg of={aiAimLineCouldnTSaveYourAim} elems={{ error: error }} />
          </p>
        )}
        <div className="ledger-form-actions">
          <Button variant="ghost" size="sm" onClick={close} disabled={busy}>
            {aiAimLineCancel()}
          </Button>
          <Button variant="primary" size="sm" type="submit" disabled={busy || unchanged}>
            {aiAimLineSave()}
          </Button>
        </div>
      </form>
    );
  }

  const total = copyNumber(fit.total);
  return (
    <div className="intel-intent">
      {fit.ranked && statement ? (
        <span>
          <Msg of={aiAimLineOpenRolesRankedByHow} elems={{ total: total }} /> <q><Content text={statement} /></q>
        </span>
      ) : fit.ranked ? (
        <span><Msg of={aiAimLineOpenRolesRankedByWhat} elems={{ total: total }} /></span>
      ) : statement ? (
        <span>
          <Msg of={aiAimLineOpenRolesSortedByDate} elems={{ total: total, q: <q><Content text={statement} /></q> }} />
        </span>
      ) : (
        <span><Msg of={aiAimLineOpenRolesSortedByDate2} elems={{ total: total }} /></span>
      )}
      <Button ref={openRef} variant="link" className="ui-btn-quiet" onClick={open}>
        {aiAimLineAddYourAim({ choice: (statement) ? "yes" : "no" })}
      </Button>
    </div>
  );
}
