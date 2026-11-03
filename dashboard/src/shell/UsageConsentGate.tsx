import type { UsageState } from "../api";
import { UsageConsentDialog } from "../patterns/privacy/UsageConsentDialog";
import { groupsToAsk } from "../patterns/privacy/consentCopy";

/* Asks a configured install about usage sharing once (docs/architecture.md).
   App mounts this only after its first-run check found a configured install
   (a fresh one is asked inside the welcome walk) and never on /welcome, with
   the state it read at startup. It asks about the groups never answered or
   widened since; nothing when an environment switch has turned sharing off on
   this computer. Lazy: the question's words stay out of the startup chunk.
   */

export default function UsageConsentGate({
  state,
  onAnswered,
}: {
  state: UsageState;
  onAnswered: (next: UsageState) => void;
}) {
  if (state.blocked_by) return null;
  const groups = groupsToAsk(state);
  if (groups.length === 0) return null;
  return <UsageConsentDialog state={state} groups={groups} onAnswered={onAnswered} />;
}
