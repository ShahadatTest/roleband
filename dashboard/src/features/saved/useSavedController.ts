import { useCallback, useMemo } from "react";
import { DEFAULT_FILTERS, Job, JobList as JobListData, api } from "../../api";
import { useJobActions, useJobWorkspace } from "../../context/JobWorkspace";
import { useMissionActions } from "../../context/MissionState";
import { useAsyncResource, useRefetchOn } from "../../hooks/useAsyncResource";
import { useSourceSwitch } from "../../context/SyncState";
import { useRoleSaves } from "../../hooks/useRoleSaves";
import { useToast } from "../../ui";
import {
  savedUseSavedControllerCouldNotRemoveFromSaved,
  savedUseSavedControllerCouldNotRestore,
  savedUseSavedControllerRemovedFromSaved,
  savedUseSavedControllerUndo,
} from "../../copy/gen/saved";

/** status "" -> saved-but-closed roles are still saved roles (the empty status
 *  reaches the wire). One page of 200: a saved list is a
 *  hand-curated set, not a feed to paginate. */
const SAVED_QUERY = { ...DEFAULT_FILTERS, favorites_only: true, status: "", limit: 200 };

/**
 * Saved's state: the list, its failure, and the one mutation the screen has.
 *
 * A save anywhere (`favVersion`) re-reads the list and the stages in place:
 * the rows stay mounted with their scroll. The shared async resource orders
 * the responses, so a read still in flight when the next save lands never
 * overwrites the newer one.
 */
export function useSavedController() {
  const { viewedIds, compareIds, compareFull, compareCap, favVersion } = useJobWorkspace();
  const { openJob, toggleCompare } = useJobActions();
  const { refreshStats } = useMissionActions();
  const { toast } = useToast();
  const saveRole = useRoleSaves();

  // A failed fetch must not read as an empty one: the boundary's error state
  // is what says which happened.
  const list = useAsyncResource<JobListData>(
    (signal) => api.jobs(SAVED_QUERY, signal),
    [],
  );
  const { mutate, refresh } = list;
  useRefetchOn(favVersion, refresh);
  // Each tracked role's stage, shown on its row. Optional: a failed read
  // leaves the rows without a stage line, never with a wrong one.
  const pursuits = useAsyncResource(() => api.pursuits(), []);
  useRefetchOn(favVersion, pursuits.refresh);
  const stages = useMemo(
    () => new Map((pursuits.data?.pursuits ?? []).map((p) => [p.job_id, p.stage])),
    [pursuits.data],
  );
  // Saved rows show pay: a source switch re-reads them.
  useSourceSwitch(refresh);

  const unfavorite = useCallback(
    (job: Job) => {
      // Optimistic: the row leaves now, the server catches up. Rollback is a
      // re-read, not a remembered copy: another tab may have changed the set.
      const show = (on: boolean) => {
        if (on) void refresh({ preserveData: true });
        else mutate((prev) =>
          prev ? { ...prev, items: prev.items.filter((j) => j.id !== job.id), total: prev.total - 1 } : prev,
        );
      };
      // One writer per role across every surface, Undo included.
      saveRole({ jobId: job.id, was: true, next: false, show, send: () => api.setFavorite(job.id, false) })
        .then(() => {
          refreshStats();
          toast({
            key: "saved",
            text: savedUseSavedControllerRemovedFromSaved({ title: String(job.title) }),
            action: {
              label: savedUseSavedControllerUndo(),
              onClick: () => {
                void saveRole({
                  jobId: job.id, was: false, next: true,
                  // The row comes back with the re-read below, not before.
                  show: () => undefined,
                  send: () => api.setFavorite(job.id, true),
                })
                  .then(() => {
                    refreshStats();
                    return refresh({ preserveData: true });
                  })
                  .catch(() => {
                    // A failed undo is a user action that did not happen, and
                    // saying nothing would leave the row missing with no reason.
                    toast({ key: "saved", text: savedUseSavedControllerCouldNotRestore({ title: String(job.title) }) });
                    void refresh({ preserveData: true });
                  });
              },
            },
          });
        })
        .catch(() => {
          // The newest write failed: `show(true)` has already re-read the list.
          toast({ key: "saved", text: savedUseSavedControllerCouldNotRemoveFromSaved({ title: String(job.title) }) });
        });
    },
    [mutate, refresh, refreshStats, toast, saveRole],
  );

  return {
    items: list.data?.items ?? [],
    // The denominator the page cannot see. `SAVED_QUERY` asks for one page of
    // 200, so past that `items` IS the cap and printing its length alone would
    // state the cap as the truth. The server's `total` is the only thing that
    // knows otherwise; the optimistic unfavourite above decrements it.
    total: list.data?.total ?? 0,
    stages,
    loading: list.loading,
    failed: list.error,
    retry: list.retry,
    unfavorite,
    openJob, viewedIds, compareIds, toggleCompare, compareFull, compareCap,
  };
}
