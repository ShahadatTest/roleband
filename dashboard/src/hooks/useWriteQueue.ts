import { useCallback, useMemo, useRef, useState } from "react";

/* Submission order as persistence order, for a surface with more than one
 * writer.
 *
 * The rule a queue exists for: when an endpoint replaces the WHOLE subject,
 * two requests in the air means the install keeps whichever row the server
 * wrote last, which is not necessarily the later write. A stale-response guard
 * cannot reach that — it decides what the screen adopts, never what the
 * database keeps. Make submission order total and the question stops existing,
 * which is also why there is no generation ref anywhere near this file.
 *
 * What this adds over a bare promise chain is that a surface usually has TWO
 * shapes of write, and one chain is wrong for both:
 *
 *  - `keyed`  — patches one row. Two different rows never need to wait on each
 *               other, and making them wait is a real cost: the Companies
 *               register hides a company per click, and one slow write would
 *               stall every other row's eye.
 *  - `exclusive` — replaces the whole subject (the roster PUT). It must order
 *               against EVERY outstanding write, both directions: it cannot
 *               start while a keyed write is in the air (its response would
 *               echo a row that is about to change), and nothing may start
 *               while it is (its response replaces every row).
 *
 * So: per-key tails, one exclusive tail, and an exclusive write that gates on
 * all of them and then supersedes them. That is a barrier, not a lock — there
 * is nothing to release and no way to deadlock, because a task never enqueues
 * onto the queue it is running under.
 *
 * ORDERING KEY IS NOT BUSY KEY, and conflating them is the trap this shape
 * invites. `exclusive` orders by nothing (it orders against all), but it still
 * has to say which rows it makes busy — a roster write touches forty slugs and
 * must run ONCE, not forty times. Hence `keys` on `exclusive` is a busy
 * argument only, and is never read for ordering.
 *
 * `busy` COUNTS rather than marking, and it counts across both verbs. A set
 * cleared by whoever finishes first lets a row re-arm over work that is still
 * outstanding — which is what happens when each writer keeps its own counter
 * and clears the shared set unconditionally.
 * One counter per key, fed by every verb, is the only arrangement where "is
 * this row still writing" has one answer.
 *
 * The SUBJECT is what the queue orders, and it is named rather than implied:
 * two screens editing the same server-side thing share one order even across a
 * navigation, and two different things never wait on each other.
 *
 * Nothing cancels on unmount, deliberately. The request has already left, so
 * the write should complete; and on React 18 every state call from a settled
 * promise is inert once the owner is gone, so a drained queue writes nothing
 * to a dead tree. What a caller must still not do is assume the queue survives
 * a remount is covered: the tails are keyed by subject at module scope, so a
 * provider that unmounts mid-write and remounts inherits the order it left.
 */

const EMPTY: ReadonlySet<string> = new Set();

/* The tails outlive the component, because the SUBJECT does.
 *
 * Held in refs they are per provider INSTANCE, so the guarantee ends at an
 * unmount: leave /profile with a scope save in flight, come back, and the new
 * provider starts an EMPTY queue beside the draining one — two whole-scope PUTs
 * unordered, which is the exact thing this file exists to prevent. The radar and
 * the roster are not per-instance, so neither is their order.
 *
 * Keyed by subject at module scope, and never dropped: the app names a handful
 * of subjects and an entry is a pair of promise tails. It holds no React state and
 * nothing reads it during render but get-or-create, so a later mount inherits
 * the ORDER without inheriting anyone else's `busy`.
 *
 * `busy` deliberately does NOT cross the remount. It counts what THIS mount
 * asked for, so a screen that inherits an in-flight write from a screen you
 * already left does not open with rows marked busy for work it never started.
 * The cost is the narrow window where such a write is outstanding and its row
 * reads idle — `aria-busy` only, and the ordering that protects the data is
 * unaffected. */
interface SubjectTails {
  exclusive: Promise<void>;
  keyed: Map<string, Promise<void>>;
}

const SUBJECTS = new Map<string, SubjectTails>();

function tailsFor(subject: string): SubjectTails {
  const found = SUBJECTS.get(subject);
  if (found) return found;
  const created: SubjectTails = { exclusive: Promise.resolve(), keyed: new Map() };
  SUBJECTS.set(subject, created);
  return created;
}

/** Drop every subject's tails. Module state outlives a component by design,
 *  which inside one test FILE means it outlives the test — a spec that leaves a
 *  write pending would otherwise hand the next one a tail that never settles.
 *  Called from `src/test/setup.ts`, beside Testing Library's `cleanup()`. */
export function resetWriteQueues() {
  SUBJECTS.clear();
}

/** The tail form: a promise that has SETTLED, never one that rejects.
 *  Storing a rejectable tail is how a chain poisons — one throw and every
 *  later `.then` is skipped forever, so the queue silently stops writing and
 *  `busy` sticks. Callers still see their own rejection through `run`. */
const settled = (promise: Promise<unknown>): Promise<void> =>
  promise.then(() => {}, () => {});

/** Does the published set already name exactly the keys still counted? */
const sameKeys = (published: ReadonlySet<string>, counted: ReadonlyMap<string, number>) =>
  published.size === counted.size && [...published].every((key) => counted.has(key));

export interface WriteQueue {
  /** A write that owns the whole subject. Runs after everything outstanding;
   *  everything queued afterwards runs after it. `keys` is what it marks busy
   *  — it is NOT what it orders by, and the task runs once however many keys
   *  it names. */
  exclusive: <T>(keys: readonly string[], task: () => Promise<T>) => Promise<T>;
  /** A write that owns one key. Runs after that key's own outstanding writes
   *  and after any exclusive write, and never waits on another key. */
  keyed: <T>(key: string, task: () => Promise<T>) => Promise<T>;
  /** Keys with a write outstanding — queued or in flight, whichever verb put
   *  it there. Identity holds while the set of keys has not moved, so a second
   *  write for a key already busy re-renders nobody. */
  busy: ReadonlySet<string>;
  /** Anything at all outstanding, including a write that named no key. */
  writing: boolean;
}

export function useWriteQueue(subject: string): WriteQueue {
  // Counted per MOUNT, unlike the tails: see the note on `SUBJECTS`.
  const counts = useRef(new Map<string, number>());
  const outstanding = useRef(0);
  const [busy, setBusy] = useState<ReadonlySet<string>>(EMPTY);
  const [writing, setWriting] = useState(false);

  const publish = useCallback(() => {
    setWriting(outstanding.current > 0);
    setBusy((current) => (sameKeys(current, counts.current)
      ? current
      : new Set(counts.current.keys())));
  }, []);

  const enter = useCallback((keys: readonly string[]) => {
    outstanding.current += 1;
    for (const key of keys) counts.current.set(key, (counts.current.get(key) ?? 0) + 1);
    publish();
  }, [publish]);

  const leave = useCallback((keys: readonly string[]) => {
    outstanding.current -= 1;
    for (const key of keys) {
      const left = (counts.current.get(key) ?? 1) - 1;
      if (left > 0) counts.current.set(key, left);
      else counts.current.delete(key);
    }
    publish();
  }, [publish]);

  const exclusive = useCallback(<T>(
    keys: readonly string[],
    task: () => Promise<T>,
  ): Promise<T> => {
    // Read, never captured: a mount that outlives a `resetWriteQueues()` must
    // not keep writing into tails nobody else can see.
    const tails = tailsFor(subject);
    // Every tail, not just the last exclusive one: a keyed write still in the
    // air would otherwise land on either side of a write that replaces its row.
    const gate = Promise.all([tails.exclusive, ...tails.keyed.values()]);
    enter(keys);
    const run = gate.then(() => task()).finally(() => leave(keys));
    // Each keyed tail is now inside `gate`, so `run` supersedes all of them:
    // the next write for any key chains off this one through the exclusive
    // tail, which is what makes the barrier hold in the other direction too.
    tails.keyed.clear();
    tails.exclusive = settled(run);
    return run;
  }, [subject, enter, leave]);

  const keyed = useCallback(<T>(key: string, task: () => Promise<T>): Promise<T> => {
    const tails = tailsFor(subject);
    // Falls back to the exclusive tail rather than to a resolved promise: a
    // FIRST write for this key must still wait for a whole-subject write.
    const previous = tails.keyed.get(key) ?? tails.exclusive;
    enter([key]);
    const run = previous.then(() => task()).finally(() => leave([key]));
    tails.keyed.set(key, settled(run));
    return run;
  }, [subject, enter, leave]);

  return useMemo(
    () => ({ exclusive, keyed, busy, writing }),
    [exclusive, keyed, busy, writing],
  );
}
