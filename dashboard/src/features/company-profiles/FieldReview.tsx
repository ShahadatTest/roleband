import { errorText } from "../../api/errorText";
import { useState } from "react";
import { FieldCandidate, ReviewItem, api } from "../../api";
import { parseNumber } from "../../copy/format";
import { commonUndo } from "../../copy/gen/common";
import { Button } from "../../ui/Button";
import { Select } from "../../ui/Select";
import { useToast } from "../../ui/Toast";
import { FIELD_LABEL, REASON_TEXT, VEHICLE_LABEL, displayValue, yesNo } from "./labels";
import {
  profilesFieldCouldNotUndo,
  profilesFieldCouldNotUseSources,
  profilesFieldReviewCouldnTSaveItTry,
  profilesFieldReviewCustomValueFor,
  profilesFieldReviewNotAWholeNumber,
  profilesFieldReviewOrChooseAValue,
  profilesFieldReviewOrEnterAValue,
  profilesFieldReviewPinned,
  profilesFieldReviewSave,
  profilesFieldReviewSetToFrom,
  profilesFieldReviewSuggested,
  profilesFieldUnpinned,
  profilesFieldUseSources,
  profilesFieldUseSourcesFor,
} from "../../copy/gen/profiles";
import { SourceLabel, type SourceNames, sourceText } from "./SourceLabel";

/** The fields whose value is a count or a year: a whole number. */
const WHOLE_NUMBER_FIELDS: ReadonlySet<string> = new Set(["headcount", "year_founded"]);

/** A whole number written the way the reader's region writes it ("1.000" is
 *  one thousand in Spain, "1,000" in the US); null for anything else, so a value
 *  the reader did not write is never pinned. */
function readWholeNumber(raw: string): number | null {
  const value = parseNumber(raw);
  return Number.isSafeInteger(value) && value >= 0 ? value : null;
}

/* A field with a closed set of answers is chosen, never typed: the stored
 * value is the code, and the reader sees each code's name in their language. */
function choicesFor(field: string): { value: string; label: string }[] | null {
  if (field === "is_public") return [{ value: "yes", label: yesNo(true) }, { value: "no", label: yesNo(false) }];
  if (field === "equity_vehicle") return Object.keys(VEHICLE_LABEL).map((code) => ({ value: code, label: VEHICLE_LABEL[code] }));
  return null;
}

/* A pin and an unpin each confirm with a toast whose Undo is the other write
 * (ui/Toast): a pin outranks every source, so it is never final on one click.
 * A write that fails throws to the caller, which says so where it was made;
 * an Undo that fails says so in the toast that replaces it. */
function usePinWrites(slug: string, field: string, onResolved: () => void) {
  const { toast } = useToast();
  const key = ["profile-pin", slug, field].join(":");
  const label = () => FIELD_LABEL[field] ?? field;
  const pinnedText = (value: unknown) => profilesFieldReviewPinned({ label: label(), value: displayValue(field, value) });
  const unpinnedText = () => profilesFieldUnpinned({ label: label() });
  const undo = (write: () => Promise<unknown>, done: () => string) => {
    write().then(
      () => {
        onResolved();
        toast({ key, text: done() });
      },
      (e) => toast({ key, text: errorText(e, profilesFieldCouldNotUndo()), tone: "error" }),
    );
  };
  const pin = async (value: unknown) => {
    await api.setCompanyField(slug, field, value);
    onResolved();
    toast({
      key,
      text: pinnedText(value),
      action: { label: commonUndo(), onClick: () => undo(() => api.clearCompanyField(slug, field), unpinnedText) },
    });
  };
  const unpin = async (pinned: unknown) => {
    await api.clearCompanyField(slug, field);
    onResolved();
    toast({
      key,
      text: unpinnedText(),
      action: { label: commonUndo(), onClick: () => undo(() => api.setCompanyField(slug, field, pinned), () => pinnedText(pinned)) },
    });
  };
  return { pin, unpin };
}

// The manual-enrichment workflow, dissolved into the field it concerns: the
// flagged row itself offers every source's claim so the user CONFIRMS or
// CORRECTS where they read the value, rather than in a separate queue panel.
export function FieldReview({
  slug,
  item,
  sourceNames,
  onResolved,
}: {
  slug: string;
  item: ReviewItem;
  sourceNames: SourceNames;
  onResolved: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [custom, setCustom] = useState("");
  const [error, setError] = useState<string | null>(null);
  const { pin } = usePinWrites(slug, item.field, onResolved);

  const commit = async (value: unknown) => {
    setBusy(true);
    setError(null);
    try {
      await pin(value);
    } catch (e) {
      setError(errorText(e, profilesFieldReviewCouldnTSaveItTry()));
    } finally {
      setBusy(false);
    }
  };

  const label = FIELD_LABEL[item.field] ?? item.field;
  const choices = choicesFor(item.field);
  const whole = WHOLE_NUMBER_FIELDS.has(item.field);

  /* The entry as the field stores it, or null when it is not one: an entry
     that does not read as a whole number is refused, never coerced. */
  const entered = (raw: string): { value: unknown } | null => {
    if (item.field === "is_public") return { value: raw === "yes" };
    if (!whole) return { value: raw };
    const value = readWholeNumber(raw);
    return value === null ? null : { value };
  };

  const submit = () => {
    const raw = custom.trim();
    if (!raw) return;
    const read = entered(raw);
    if (read === null) setError(profilesFieldReviewNotAWholeNumber({ example: 1200 }));
    else void commit(read.value);
  };

  return (
    <div className="prof-field-review">
      <span className={`prof-review-reason is-${item.reason}`}>
        {REASON_TEXT[item.reason]}
      </span>

      {item.candidates.map((c: FieldCandidate) => {
        const suggested = item.suggestion?.source === c.source;
        return (
          <Button
            key={c.source}
            variant="ghost"
            size="sm"
            className={`ui-btn-strong prof-review-choice${suggested ? " suggested" : ""}`}
            disabled={busy}
            onClick={() => commit(c.value)}
            aria-label={profilesFieldReviewSetToFrom({ label: String(label), field: String(displayValue(item.field, c.value)), source_label: sourceText(c.source, sourceNames) })}
          >
            <span className="prof-review-choice-v">{displayValue(item.field, c.value)}</span>
            <span className="prof-review-choice-s"><SourceLabel source={c.source} names={sourceNames} /></span>
            {suggested && <span className="prof-review-suggested">{profilesFieldReviewSuggested()}</span>}
          </Button>
        );
      })}

      <form
        className="prof-review-custom"
        onSubmit={(e) => {
          e.preventDefault();
          submit();
        }}
      >
        {choices ? (
          <Select
            label={profilesFieldReviewCustomValueFor({ label: String(label) })}
            value={custom}
            onChange={setCustom}
            options={[{ value: "", label: profilesFieldReviewOrChooseAValue(), disabled: true }, ...choices]}
          />
        ) : (
          <input
            type="text"
            inputMode={whole ? "numeric" : undefined}
            placeholder={profilesFieldReviewOrEnterAValue()}
            aria-label={profilesFieldReviewCustomValueFor({ label: String(label) })}
            aria-invalid={error !== null && whole ? true : undefined}
            value={custom}
            onChange={(e) => {
              setCustom(e.target.value);
              setError(null);
            }}
          />
        )}
        <Button type="submit" variant="ghost" size="sm" disabled={busy || !custom}>
          {profilesFieldReviewSave()}
        </Button>
      </form>

      {error && (
        <span className="prof-review-error" role="alert">
          {error}
        </span>
      )}
    </div>
  );
}

/* A pinned field, in the enrich mode: the way back to what its sources say.
 * The pin is the only claim that outranks every source, so nothing else on
 * the screen can undo it. */
export function PinnedField({
  slug,
  field,
  value,
  onResolved,
}: {
  slug: string;
  field: string;
  value: unknown;
  onResolved: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const { unpin } = usePinWrites(slug, field, onResolved);
  const label = FIELD_LABEL[field] ?? field;

  const backToSources = async () => {
    setBusy(true);
    setError(null);
    try {
      await unpin(value);
    } catch (e) {
      setError(errorText(e, profilesFieldCouldNotUseSources()));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="prof-field-review">
      <Button
        variant="ghost"
        size="sm"
        className="ui-btn-strong"
        disabled={busy}
        aria-label={profilesFieldUseSourcesFor({ label: String(label) })}
        onClick={() => void backToSources()}
      >
        {profilesFieldUseSources()}
      </Button>
      {error && (
        <span className="prof-review-error" role="alert">
          {error}
        </span>
      )}
    </div>
  );
}
