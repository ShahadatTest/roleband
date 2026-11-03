import { useEffect, useRef, useState } from "react";
import { api } from "../../api";
import type { UsageGroup, UsageState } from "../../api";
import { Dialog } from "../../ui";
import { privacyConsentTitle } from "../../copy/gen/privacy";
import { ConsentPane } from "./ConsentPane";
import { consentPayload, consentWords } from "./consentCopy";

/* Asks an existing install once (docs/architecture.md): an install set
   up before usage sharing existed never sees the welcome walk again, and a
   group widened since the user shared it asks again. Must be answered: the
   scrim does not close it, and Escape is "No thanks" for the groups asked,
   recorded like the button, so the question is not asked again. */

export function UsageConsentDialog({
  state,
  groups,
  onAnswered,
}: {
  state: UsageState;
  groups: UsageGroup[];
  onAnswered: (next: UsageState) => void;
}) {
  const safeRef = useRef<HTMLButtonElement>(null);
  const [open, setOpen] = useState(true);

  // A child's effect runs before the Overlay's, which keeps focus it finds
  // already inside (the FollowConfirmDialog pattern).
  useEffect(() => {
    if (open) safeRef.current?.focus();
  }, [open]);

  const done = (next: UsageState) => {
    setOpen(false);
    onAnswered(next);
  };

  const decline = () => {
    setOpen(false);
    const answers = Object.fromEntries(groups.map((group) => [group, false]));
    api
      .saveUsageConsent(consentPayload(state, answers, consentWords(groups)))
      .then(onAnswered)
      .catch(() => {
        /* Asked again next launch: a failed decline shares nothing. */
      });
  };

  return (
    <Dialog
      isOpen={open}
      onClose={decline}
      label={privacyConsentTitle()}
      width={540}
      closeOnScrim={false}
      className="app-overlay privacy-consent-dialog"
    >
      <ConsentPane state={state} groups={groups} onAnswered={done} safeRef={safeRef} />
    </Dialog>
  );
}
