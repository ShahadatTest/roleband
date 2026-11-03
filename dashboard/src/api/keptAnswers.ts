/* The last answer of each read a screen keeps (`useAsyncResource`'s `keep`),
   so a screen opened again paints at once and then refreshes quietly. Any write
   forgets them all: `transport.ts` counts every write that settles, and answers
   kept under an older count are gone. The one write it does not count is a mark
   no kept read shows (`postMarkJSON`). An answer from before a write may no
   longer be true, and which reads a write touches is the server's to know.
   The count lives in the transport so the shell carries only a number; this
   module loads with the screens that keep answers. */
import { writesSettled } from "./transport";

export { writesSettled };

/** Answers kept at most; the oldest is dropped first. */
const LIMIT = 40;

const kept = new Map<string, unknown>();
let keptUnder = 0;

/** The kept answers, emptied first if a write settled since they were kept. */
function answers(): Map<string, unknown> {
  const writes = writesSettled();
  if (keptUnder !== writes) {
    kept.clear();
    keptUnder = writes;
  }
  return kept;
}

export function keptAnswer(key: string): { value: unknown } | undefined {
  const current = answers();
  return current.has(key) ? { value: current.get(key) } : undefined;
}

/** Keep `value` as the answer for `key`, unless a write settled after the read
 *  that produced it started (`startedAfter`, from `writesSettled`): that read
 *  may have answered from before the write. */
export function keepAnswer(key: string, value: unknown, startedAfter: number): void {
  const current = answers();
  if (startedAfter !== keptUnder) return;
  current.delete(key);
  current.set(key, value);
  if (current.size > LIMIT) current.delete(current.keys().next().value as string);
}

/** Forget every kept answer; tests start each case from none. */
export function forgetKeptAnswers(): void {
  kept.clear();
}
