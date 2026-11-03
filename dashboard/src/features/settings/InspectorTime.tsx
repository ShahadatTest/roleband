import { useState } from "react";
import { formatMinute } from "./charts/schedule";

/* The exact-time field commits on blur or Enter — never on `change`.
 *
 * A time input fires `change` for every segment edit that leaves the value
 * complete, so committing there would persist the first keystroke of an edit:
 * in a 12-hour locale a single "1" typed into the hour of "10:00 PM" is
 * already a complete "01:00 PM". Held by tests/ux/schedule.spec.ts, which
 * types rather than filling: `fill()` never passes through a partial value.
 *
 * `readOnly` rather than `disabled` while the save is in flight: a disabled
 * field drops focus, and Enter commits with the caret still in the field.
 * `disabled` stays for the locked case, where the field is genuinely not an
 * editable control.
 */
export function InspectorTime({
  label,
  minute,
  step,
  locked,
  saving,
  onCommit,
}: {
  label: string;
  /** The persisted time, or the live drag position while one is in progress;
   *  null shows an empty field (nothing set yet), and any time typed commits. */
  minute: number | null;
  step: number;
  locked: boolean;
  saving: boolean;
  onCommit: (minute: number) => void;
}) {
  const [typed, setTyped] = useState<string | null>(null);

  const commit = () => {
    if (typed === null) return;
    setTyped(null);
    const [hour, minutePart] = typed.split(":").map(Number);
    if (Number.isNaN(hour) || Number.isNaN(minutePart)) return;
    const next = hour * 60 + minutePart;
    // Tabbing out of a field nobody changed is not a reschedule.
    if (next === minute) return;
    onCommit(next);
  };

  return (
    <input
      type="time"
      step={step}
      aria-label={label}
      value={typed ?? (minute === null ? "" : formatMinute(minute))}
      disabled={locked}
      readOnly={saving}
      aria-busy={saving || undefined}
      onChange={(change) => setTyped(change.target.value)}
      onBlur={commit}
      // Enter commits; abandoning an edit needs no key of its own, because
      // Overlay's own Escape closes the inspector and React fires no blur on
      // unmount — the pending value goes with it.
      onKeyDown={(key) => {
        if (key.key !== "Enter") return;
        key.preventDefault();
        commit();
      }}
    />
  );
}
