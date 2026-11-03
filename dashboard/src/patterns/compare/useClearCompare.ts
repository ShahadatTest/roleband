import { commonUndo } from "../../copy/gen/common";
import { shellCompareCleared } from "../../copy/gen/shell";
import { useCallback } from "react";
import { useJobActions, useJobWorkspace } from "../../context/JobWorkspace";
import { useToast } from "../../ui";

/**
 * Empty the comparison, with a way back.
 *
 * The one recipe for clearing the selection: the comparison's own Clear and
 * the command palette both run it. A palette calling the bare `clearCompare`
 * would make one act undoable in one place and final in the other — and the
 * palette runs from any screen, where nothing visible changes to say it
 * happened. It lives in `patterns/` because both callers can reach it there: a
 * palette in `shell/` may not import the comparison's feature controller.
 *
 * The set is captured BEFORE clearing, so Undo restores what was cleared rather
 * than whatever the selection holds by the time the toast is pressed.
 */
export function useClearCompare(): () => void {
  const { compareIds } = useJobWorkspace();
  const { clearCompare, setCompare } = useJobActions();
  const { toast } = useToast();
  return useCallback(() => {
    const kept = [...compareIds];
    clearCompare();
    toast({
      key: "compare",
      text: shellCompareCleared({ count: kept.length }),
      action: { label: commonUndo(), onClick: () => setCompare(kept) },
    });
  }, [compareIds, clearCompare, setCompare, toast]);
}
