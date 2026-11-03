import { wordsLanguage } from "../../copy/runtime";
import { useEffect, useRef, type ReactNode } from "react";
import { Button, Dialog } from "../../ui";
import { useCompanies } from "./CompaniesData";
import { followCopy } from "./followCopy";
// The dialog form these confirmations wear (`.ledger-form`, `.ledger-confirm`)
// belongs to the register material; setup asks them without Settings' chunk.
import "../../design/materials/register-material.css";
import {
  companiesCuratedListConfirm,
} from "../../copy/gen/companies";

/* The follow confirmations.
 *
 * Every bulk follow asks first (the toolbar's Follow all, a sector's Follow
 * all, the set of other companies), because it changes what the radar holds
 * and how long each scan takes. There is no follow switch under the sector
 * index: it would read as a promise of companies not on screen, while the
 * toolbar action says plainly that it follows the ones that are.
 */

/** A settings path ("Settings › Followed companies"), a hyphenated word, or a
 *  short word that opens a sentence with the word after it ("By following"). */
const UNBROKEN = /[^\s›]+ › [^.,;。，]+|\p{L}+(?:-\p{L}+)+|(?<=[.?!] )\p{L}{1,3} \p{L}+/gu;

/** The paragraph's own text, with each UNBROKEN run kept on one line. The words
 *  are unchanged: they are the consent the server stores. */
function keepTogether(line: string): ReactNode[] {
  const parts: ReactNode[] = [];
  let at = 0;
  for (const match of line.matchAll(UNBROKEN)) {
    if (match.index > at) parts.push(line.slice(at, match.index));
    parts.push(<span key={match.index} className="ledger-confirm-unbroken">{match[0]}</span>);
    at = match.index + match[0].length;
  }
  if (at < line.length) parts.push(line.slice(at));
  return parts;
}

export function FollowConfirmDialog({
  onAnswered,
}: {
  /** Told which way the reader answered, after the write is asked for: first-run
   *  setup goes on only once a follow it asked for is confirmed. */
  onAnswered?: (followed: boolean) => void;
} = {}) {
  const { confirmation, confirmFollow, dismissFollow } = useCompanies();
  const dismiss = () => {
    dismissFollow();
    onAnswered?.(false);
  };
  const pending = confirmation;
  const safeRef = useRef<HTMLButtonElement>(null);

  // The safe answer takes focus: Enter on a dialog that just opened must never
  // follow seventy companies — or consent to a wall. A child's effect runs
  // before the Overlay's, which keeps focus it finds already inside.
  useEffect(() => {
    if (pending) safeRef.current?.focus();
  }, [pending]);

  // Rendered from the same words the consent records (followCopy.ts).
  const copy = pending ? followCopy(pending) : null;
  const shownLocale = wordsLanguage();

  return (
    <Dialog
      isOpen={pending !== null}
      onClose={dismiss}
      label={copy?.title ?? companiesCuratedListConfirm()}
      width={440}
      closeOnScrim={false}
      className="app-overlay"
    >
      <div className="ledger-form ledger-confirm">
        <h3>{copy?.title}</h3>
        {copy?.paragraphs.map((line) => <p key={line}>{keepTogether(line)}</p>)}
        <div className="ledger-form-actions">
          <Button ref={safeRef} onClick={dismiss}>
            {copy?.safe}
          </Button>
          <Button
            variant="primary"
            onClick={() => {
              if (!copy) return;
              confirmFollow({ copy, locale: shownLocale });
              onAnswered?.(true);
            }}
          >
            {copy?.act}
          </Button>
        </div>
      </div>
    </Dialog>
  );
}
