import { useCallback, useEffect } from "react";
import { Job, api } from "../../api";
import { useJobActions, useJobWorkspace } from "../../context/JobWorkspace";
import { useSaveCommand } from "../../context/useSaveCommand";
import { useSourceSwitch } from "../../context/SyncState";
import { useAsyncResource } from "../../hooks/useAsyncResource";
import { usePayCoverage } from "../../payCoverage";
import { useClearCompare } from "../../patterns/compare/useClearCompare";
import { useToast } from "../../ui";
import {
  compareUseCompareControllerCouldNotHide,
  compareUseCompareControllerCouldNotUnsave,
  compareUseCompareControllerCouldnTRestore,
  compareUseCompareControllerNotForMe,
  compareUseCompareControllerRemovedFromCompare,
  compareUseCompareControllerUndo,
} from "../../copy/gen/compare";

/**
 * Compare's state: the selection turned into loaded roles, the two ways a
 * role leaves the comparison, and the two verbs a column head carries (Save,
 * Not for me). Every removal is undoable from its
 * toast — the selection is the user's work, so nothing here discards it
 * silently — and "Not for me" is undoable as a whole: the role comes back to
 * the radar AND to the comparison.
 */
export function useCompareController() {
  const { compareIds, compareHydrated, compareFull, lastSaved } = useJobWorkspace();
  const { toggleCompare, openJob } = useJobActions();
  const { toast } = useToast();
  const saveRole = useSaveCommand();
  const ids = [...compareIds];

  // Below two roles there is no comparison to fetch. `useAsyncResource` keys on
  // the Set identity, so a newer selection supersedes an in-flight older one
  // and the stale response cannot paint (pinned by CompareScreen.test).
  const comparison = useAsyncResource<Job[]>(
    () => (ids.length < 2 ? Promise.resolve([]) : Promise.all(ids.map((id) => api.job(id)))),
    [compareIds],
  );
  // It stays mounted under a job's cover, so a source switch landing there
  // must re-read its columns' pay, as the board beneath does.
  useSourceSwitch(comparison.refresh);

  // A save confirmed anywhere reaches the columns. A role opened from a
  // column is a cover over this screen, which stays mounted under it, so a
  // star set there must show here without reopening the comparison. Patched,
  // not re-read: the comparison is one detail read per role, and the
  // confirmed write is the fact. Its own Save lands here too, already
  // painted, and changes nothing.
  const { mutate: patchComparison } = comparison;
  useEffect(() => {
    if (!lastSaved) return;
    patchComparison((prev) =>
      prev?.some((j) => j.id === lastSaved.jobId && j.is_favorite !== lastSaved.saved)
        ? prev.map((j) => (j.id === lastSaved.jobId ? { ...j, is_favorite: lastSaved.saved } : j))
        : prev,
    );
  }, [lastSaved, patchComparison]);

  const removeOne = useCallback(
    (job: Job) => {
      toggleCompare(job.id);
      toast({
        key: "compare",
        text: compareUseCompareControllerRemovedFromCompare({ title: String(job.title) }),
        action: { label: compareUseCompareControllerUndo(), onClick: () => toggleCompare(job.id) },
      });
    },
    [toggleCompare, toast],
  );

  /** The star, as the row has it: optimistic, and it springs back with a
   *  word when the write misses. */
  const save = useCallback(
    (job: Job) => {
      const next = !job.is_favorite;
      const patch = (on: boolean) => (prev: Job[] | null) =>
        prev ? prev.map((j) => (j.id === job.id ? { ...j, is_favorite: on } : j)) : prev;
      // One writer per role across every surface: writes go in
      // click order, and only the newest one's failure repaints the star.
      saveRole({
        jobId: job.id, was: job.is_favorite, next,
        show: (on) => comparison.mutate(patch(on)),
        send: () => api.setFavorite(job.id, next),
      })
        .catch(() => {
          toast({ key: "compare", text: compareUseCompareControllerCouldNotUnsave({ direction: next ? "save" : "unsave", title: job.title }) });
        });
    },
    [comparison, toast, saveRole],
  );

  /** Not for me: the role leaves the radar and the comparison together, and
   *  Undo brings it back to both. Two writes, one gesture, one way back. */
  const dismiss = useCallback(
    (job: Job) => {
      toggleCompare(job.id);
      // Both halves of Undo move together: the role
      // comes back into the comparison at once, and if the radar refuses it
      // leaves again, with Undo offered once more.
      const undo = () => {
        toggleCompare(job.id);
        api.undismissJob(job.id).catch(() => {
          toggleCompare(job.id);
          toast({
            key: "compare",
            text: compareUseCompareControllerCouldnTRestore({ title: String(job.title) }),
            tone: "error",
            action: { label: compareUseCompareControllerUndo(), onClick: undo },
          });
        });
      };
      api
        .dismissJob(job.id)
        .then(() => {
          toast({
            key: "compare",
            text: compareUseCompareControllerNotForMe({ title: String(job.title) }),
            action: { label: compareUseCompareControllerUndo(), onClick: undo },
          });
        })
        .catch(() => {
          toggleCompare(job.id);
          toast({ key: "compare", text: compareUseCompareControllerCouldNotHide({ title: String(job.title) }), tone: "error" });
        });
    },
    [toggleCompare, toast],
  );

  // Shared with the command palette, so the two cannot drift.
  const clearAll = useClearCompare();
  const payCover = usePayCoverage();

  return {
    ids,
    /** False until the stored selection has been read. Arriving here by URL or
     *  reload, the selection is briefly empty for a reason that is not "nothing
     *  is selected", and the two must not render the same. */
    hydrated: compareHydrated,
    /** The selection is at the cap: the frame line says so, because that is
     *  the reason every other row's toggle is disabled. */
    full: compareFull,
    jobs: comparison.data ?? [],
    /** The plugin answering pay and what it has read. */
    payCover,
    loading: comparison.loading,
    error: comparison.error,
    retry: comparison.retry,
    removeOne,
    clearAll,
    save,
    dismiss,
    openJob,
  };
}
