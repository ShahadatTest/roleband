import { useCallback } from "react";
import { useWriteQueue } from "./useWriteQueue";

/* One writer for whether a role is saved, shared by every surface that can
 * change it: the Radar's star, Compare's, the role's own, its stage (pursuing
 * saves it) and Saved's Remove and Undo.
 *
 * Writes sent the moment each is clicked race: Save then Unsave while the first
 * request waits sends PUT and DELETE together; the DELETE can land first, and
 * the PUT then leaves the role saved on the server while the screen shows it
 * unsaved. So writes for one role go one at a time in the order they were
 * asked for (`useWriteQueue`, keyed by role, its order
 * held at module scope so it crosses a navigation from one surface to another).
 *
 * Ordering fixes what the server keeps. What the SCREEN shows after a failure
 * is the second half: flipping the star back to the opposite of the click is
 * right only for the newest write. With Save, Unsave, Save queued, the first
 * failing must not unlight a star the third is about to confirm, and an older
 * failure must never undo a newer success. So a failure repaints only when no
 * newer write for the role was asked for since, and then to what the server
 * last confirmed. The ledger holding that lives only while a role has writes
 * outstanding: once they settle, the next write starts from what the screen
 * shows, which a reload has made the server's truth. */

interface Ledger {
  /** The saved state the server holds as far as this app knows. */
  confirmed: boolean;
  /** The sequence number of the newest write asked for. */
  latest: number;
  outstanding: number;
}

const LEDGERS = new Map<number, Ledger>();

/** Called from `src/test/setup.ts` beside `resetWriteQueues()`: the ledger is
 *  module state for the same reason the queue's tails are. */
export function resetRoleSaves() {
  LEDGERS.clear();
}

/** What a write came to for its caller: it landed, or it failed while a newer
 *  write for the same role was already asked for (that one decides). A failure
 *  of the newest write rejects, after the star is repainted. */
export type SaveOutcome = "saved" | "superseded";

export interface RoleSave<T> {
  jobId: number;
  /** Whether the screen shows the role saved before this write. */
  was: boolean;
  /** Whether the role is saved once this write lands. */
  next: boolean;
  /** Paint the role saved or not: with `next` at once, and with the server's
   *  state if this write fails while it is still the newest. */
  show: (saved: boolean) => void;
  send: () => Promise<T>;
}

export function useRoleSaves() {
  const { keyed } = useWriteQueue("role-saves");

  return useCallback(
    <T>({ jobId, was, next, show, send }: RoleSave<T>): Promise<SaveOutcome> => {
      let ledger = LEDGERS.get(jobId);
      if (!ledger) {
        ledger = { confirmed: was, latest: 0, outstanding: 0 };
        LEDGERS.set(jobId, ledger);
      }
      const entry = ledger;
      const own = ++entry.latest;
      entry.outstanding += 1;
      show(next);
      const settle = () => {
        entry.outstanding -= 1;
        if (entry.outstanding === 0 && LEDGERS.get(jobId) === entry) LEDGERS.delete(jobId);
      };
      return keyed(String(jobId), send).then(
        (): SaveOutcome => {
          entry.confirmed = next;
          settle();
          return "saved";
        },
        (error: unknown): SaveOutcome => {
          const newest = entry.latest === own;
          if (newest) show(entry.confirmed);
          settle();
          if (newest) throw error;
          return "superseded";
        },
      );
    },
    [keyed],
  );
}
