import { useCallback } from "react";
import { type RoleSave, type SaveOutcome, useRoleSaves } from "../hooks/useRoleSaves";
import { useJobActions } from "./JobWorkspace";
import { useMissionActions } from "./MissionState";

/* The save command: one write to whether a role is saved, and what that write
 * makes stale.
 *
 * `useRoleSaves` orders the writes and decides what the screen shows if one
 * fails; it knows nothing of the rest of the app. Callers adding the
 * consequences by hand each add a different set, and a screen drawing the role
 * is never told it changed: a save made in a role opened from a Compare column
 * would leave that column's star as it was drawn.
 *
 * Here the obligation is stated once. A write the server confirmed
 * (`outcome: "saved"`) makes two things stale: the header's counts
 * (`refreshStats`) and every reader of the saved state (`savedChanged`, which
 * bumps the version the lists re-read on and names the role for screens that
 * patch it in place). A superseded write announces nothing: the newer write
 * decides, and announces itself when it lands. A failed one rejects, after
 * `useRoleSaves` has repainted the star, and announces nothing either.
 *
 * Three states stay apart: what the screen shows now (`show`, optimistic),
 * what the server confirmed (the ledger in `useRoleSaves`) and what the rest
 * of the app is told (this, only once confirmed). */

export interface SaveResult {
  /** The posting the write was for: the id every surface keys a role by. */
  jobId: number;
  /** Whether that posting is saved once the write landed. */
  saved: boolean;
  outcome: SaveOutcome;
}

export function useSaveCommand() {
  const saveRole = useRoleSaves();
  const { refreshStats } = useMissionActions();
  const { savedChanged } = useJobActions();

  return useCallback(
    <T>(write: RoleSave<T>): Promise<SaveResult> =>
      saveRole(write).then((outcome) => {
        if (outcome === "saved") {
          refreshStats();
          savedChanged({ jobId: write.jobId, saved: write.next });
        }
        return { jobId: write.jobId, saved: write.next, outcome };
      }),
    [saveRole, refreshStats, savedChanged],
  );
}
