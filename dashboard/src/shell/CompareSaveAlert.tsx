import { commonTryAgain } from "../copy/gen/common";
import { shellCompareSaveFailed } from "../copy/gen/shell";
import { useEffect } from "react";
import { useJobActions, useJobWorkspace } from "../context/JobWorkspace";
import { useToast } from "../ui";

/* A compare selection that did not save, said on whatever screen the reader is
 * on. The workspace records the failure but is F2 and cannot raise a toast;
 * the margin beacon stands only from two roles, and says it only inside its
 * reveal, so a failed first pick, a removal down to one or Clear would say
 * nothing and a reload would undo them. An error toast stays until
 * it is answered; it leaves on its own once a write lands. Its own component,
 * so a compare change re-renders this and nothing else in the shell. */
export function CompareSaveAlert() {
  const { compareSyncFailed } = useJobWorkspace();
  const { retryCompare } = useJobActions();
  const { toast, dismiss } = useToast();

  useEffect(() => {
    if (!compareSyncFailed) return;
    const id = toast({
      key: "compare-save",
      text: shellCompareSaveFailed(),
      tone: "error",
      action: { label: commonTryAgain(), onClick: retryCompare },
    });
    return () => dismiss(id);
  }, [compareSyncFailed, retryCompare, toast, dismiss]);

  return null;
}
