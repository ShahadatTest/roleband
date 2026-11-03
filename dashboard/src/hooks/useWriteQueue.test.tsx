import { act, renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { useWriteQueue } from "./useWriteQueue";

/* The ordering properties, on the primitive rather than through a provider.
 *
 * Every one of these is stated as "what may be in flight at once", which is the
 * only question a queue answers. A gate the test opens by index is what makes
 * that observable: a call list says which tasks were ASKED for, never which
 * ones were allowed to run.
 */

/* Enqueueing is always one microtask short of starting: both verbs hand the
   task to `.then`, so nothing runs in the caller's own tick. Every step here
   therefore ends on a macrotask, which drains whatever the step scheduled —
   asserting in the same tick would only ever measure that. */
const drain = (step: () => void) => act(async () => {
  step();
  await new Promise((resolve) => { setTimeout(resolve, 0); });
});

/** Tasks that record their own start order and block until released. */
function gatedTasks() {
  const started: string[] = [];
  const finished: string[] = [];
  const release: Record<string, (reason?: Error) => void> = {};
  const task = (name: string) => () => {
    started.push(name);
    return new Promise<string>((resolve, reject) => {
      release[name] = (reason) => {
        finished.push(name);
        if (reason) reject(reason);
        else resolve(name);
      };
    });
  };
  return {
    started,
    finished,
    task,
    /** Let a task settle, and drain everything its settling schedules. */
    open: (name: string, reason?: Error) => drain(() => release[name]?.(reason)),
  };
}

const mount = (subject = "test-subject") => renderHook(() => useWriteQueue(subject));

describe("a keyed write", () => {
  it("waits for an earlier write to the same key", async () => {
    const g = gatedTasks();
    const { result } = mount();

    await drain(() => { void result.current.keyed("google", g.task("g1")); });
    await drain(() => { void result.current.keyed("google", g.task("g2")); });

    expect(g.started).toEqual(["g1"]);
    await g.open("g1");
    expect(g.started).toEqual(["g1", "g2"]);
  });

  it("does not wait for another key", async () => {
    const g = gatedTasks();
    const { result } = mount();

    await drain(() => { void result.current.keyed("google", g.task("g1")); });
    await drain(() => { void result.current.keyed("apple", g.task("a1")); });

    // Both in the air: one slow row may not stall every other row.
    expect(g.started).toEqual(["g1", "a1"]);
  });
});

describe("an exclusive write", () => {
  it("waits for every outstanding keyed write, whatever key it holds", async () => {
    /* The direction a per-key queue cannot cover on its own. An exclusive
       write replaces the whole subject, so its response echoes rows a keyed
       write is still changing — start it early and it adopts a value that is
       about to be superseded, with nothing left to correct it. */
    const g = gatedTasks();
    const { result } = mount();

    await drain(() => { void result.current.keyed("google", g.task("g1")); });
    await drain(() => { void result.current.keyed("apple", g.task("a1")); });
    await drain(() => { void result.current.exclusive(["google", "apple"], g.task("roster")); });

    expect(g.started).toEqual(["g1", "a1"]);
    await g.open("g1");
    expect(g.started, "the roster write started with apple still in flight").toEqual(["g1", "a1"]);

    await g.open("a1");
    expect(g.started).toEqual(["g1", "a1", "roster"]);
  });

  it("holds back every later write, including one for a key it never named", async () => {
    const g = gatedTasks();
    const { result } = mount();

    await drain(() => { void result.current.exclusive(["google"], g.task("roster")); });
    await drain(() => { void result.current.keyed("apple", g.task("a1")); });

    expect(g.started, "a keyed write ran while the whole subject was being replaced")
      .toEqual(["roster"]);
    await g.open("roster");
    expect(g.started).toEqual(["roster", "a1"]);
  });

  it("holds back a key that was already writing before it, not just a fresh one", async () => {
    /* The half a fresh key cannot show. A key carries its own tail, and that
       tail is settled by the time an exclusive write runs — so a later write
       to THAT key chains off a resolved promise and starts immediately,
       straight through the barrier, while the roster PUT is still in the air.
       The exclusive write has to supersede every keyed tail, not merely wait
       on them. Register shape: hide Google, toggle tracking, hide Google. */
    const g = gatedTasks();
    const { result } = mount();

    await drain(() => { void result.current.keyed("google", g.task("g1")); });
    await drain(() => { void result.current.exclusive(["google"], g.task("roster")); });
    await g.open("g1");
    expect(g.started).toEqual(["g1", "roster"]);

    await drain(() => { void result.current.keyed("google", g.task("g2")); });
    expect(g.started, "a key with a settled tail walked through the barrier")
      .toEqual(["g1", "roster"]);

    await g.open("roster");
    expect(g.started).toEqual(["g1", "roster", "g2"]);
  });

  it("runs once however many keys it marks busy", async () => {
    /* Ordering key is not busy key. A roster write touches forty slugs and is
       still one request; joining forty per-key queues would send forty. */
    const g = gatedTasks();
    const { result } = mount();

    await drain(() => { void result.current.exclusive(["a", "b", "c", "d"], g.task("roster")); });

    expect(g.started).toEqual(["roster"]);
    expect(result.current.busy).toEqual(new Set(["a", "b", "c", "d"]));
  });

  it("serializes against another exclusive write", async () => {
    const g = gatedTasks();
    const { result } = mount();

    await drain(() => { void result.current.exclusive([], g.task("r1")); });
    await drain(() => { void result.current.exclusive([], g.task("r2")); });

    expect(g.started).toEqual(["r1"]);
    await g.open("r1");
    expect(g.started).toEqual(["r1", "r2"]);
  });
});

describe("busy", () => {
  it("counts across both verbs, so neither can re-arm a key the other holds", async () => {
    /* The defect this prevents: two writers, two counters, one shared set, and
       whichever finishes first clears the row — which then reads idle with a
       write still outstanding. */
    const g = gatedTasks();
    const { result } = mount();

    await drain(() => { void result.current.keyed("google", g.task("g1")); });
    await drain(() => { void result.current.exclusive(["google"], g.task("roster")); });
    expect(result.current.busy.has("google")).toBe(true);

    await g.open("g1");
    expect(
      result.current.busy.has("google"),
      "the keyed write finished and cleared a key the roster write still holds",
    ).toBe(true);

    await g.open("roster");
    await waitFor(() => expect(result.current.busy.has("google")).toBe(false));
  });

  it("holds its identity when a key that is already busy takes another write", async () => {
    const g = gatedTasks();
    const { result } = mount();

    await drain(() => { void result.current.keyed("google", g.task("g1")); });
    const first = result.current.busy;
    await drain(() => { void result.current.keyed("google", g.task("g2")); });

    expect(result.current.busy, "the busy set changed identity without changing").toBe(first);
  });

  it("reports writing until the last queued task has drained", async () => {
    const g = gatedTasks();
    const { result } = mount();

    await drain(() => { void result.current.keyed("google", g.task("g1")); });
    await drain(() => { void result.current.keyed("google", g.task("g2")); });
    expect(result.current.writing).toBe(true);

    await g.open("g1");
    expect(result.current.writing, "the queue re-armed over work still outstanding").toBe(true);

    await g.open("g2");
    await waitFor(() => expect(result.current.writing).toBe(false));
  });

  it("tracks a write that names no key", async () => {
    const g = gatedTasks();
    const { result } = mount();

    await drain(() => { void result.current.exclusive([], g.task("r1")); });
    expect(result.current.writing).toBe(true);
    expect(result.current.busy.size).toBe(0);

    await g.open("r1");
    await waitFor(() => expect(result.current.writing).toBe(false));
  });
});

describe("a task that rejects", () => {
  it("does not strand the write behind it", async () => {
    const g = gatedTasks();
    const { result } = mount();

    await drain(() => { void result.current.keyed("google", g.task("g1")).catch(() => {}); });
    await drain(() => { void result.current.keyed("google", g.task("g2")); });

    await g.open("g1", new Error("write exploded"));
    expect(g.started).toEqual(["g1", "g2"]);
  });

  it("does not poison the queue for every write that follows", async () => {
    /* A tail stored in its rejectable form skips every later `.then` forever:
       the queue stops writing and busy sticks, with no error anywhere. */
    const g = gatedTasks();
    const { result } = mount();

    await drain(() => { void result.current.exclusive([], g.task("r1")).catch(() => {}); });
    await g.open("r1", new Error("write exploded"));

    await drain(() => { void result.current.exclusive([], g.task("r2")); });
    expect(g.started, "a rejected write poisoned the exclusive tail").toEqual(["r1", "r2"]);

    // Drained first, because the barrier is the other reason a keyed write
    // waits — leave r2 open and this would measure that instead.
    await g.open("r2");
    await drain(() => { void result.current.keyed("google", g.task("g1")); });
    expect(g.started, "a rejected write poisoned the keyed path too")
      .toEqual(["r1", "r2", "g1"]);
  });

  it("still releases busy and writing", async () => {
    const g = gatedTasks();
    const { result } = mount();

    await drain(() => { void result.current.keyed("google", g.task("g1")).catch(() => {}); });
    await g.open("g1", new Error("write exploded"));

    await waitFor(() => expect(result.current.busy.has("google")).toBe(false));
    expect(result.current.writing).toBe(false);
  });

  it("surfaces the rejection to its own caller", async () => {
    const g = gatedTasks();
    const { result } = mount();

    let caught: unknown = null;
    await drain(() => {
      void result.current.keyed("google", g.task("g1")).catch((reason) => { caught = reason; });
    });
    await g.open("g1", new Error("write exploded"));

    expect((caught as Error)?.message).toBe("write exploded");
  });
});

describe("across a remount", () => {
  it("orders a write against one the previous mount left in flight", async () => {
    /* The guarantee has to outlive the component, because the subject does.
       Leave /profile with a scope save in flight and come back, and a queue
       held in refs starts EMPTY beside the draining one — two whole-subject
       PUTs unordered, which is the thing this file exists to prevent. */
    const g = gatedTasks();
    const first = mount("radar");
    await drain(() => { void first.result.current.exclusive([], g.task("r1")); });
    expect(g.started).toEqual(["r1"]);

    first.unmount();
    const second = mount("radar");
    await drain(() => { void second.result.current.exclusive([], g.task("r2")); });

    expect(g.started, "a remount started a whole-subject write beside one still in flight")
      .toEqual(["r1"]);
    await g.open("r1");
    expect(g.started).toEqual(["r1", "r2"]);
  });

  it("carries a key's order across the remount too", async () => {
    const g = gatedTasks();
    const first = mount("roster");
    await drain(() => { void first.result.current.keyed("google", g.task("g1")); });

    first.unmount();
    const second = mount("roster");
    await drain(() => { void second.result.current.keyed("google", g.task("g2")); });

    expect(g.started, "the row's order was lost with its provider").toEqual(["g1"]);
    await g.open("g1");
    expect(g.started).toEqual(["g1", "g2"]);
  });

  it("does not make the new mount busy for work it never asked for", async () => {
    /* The deliberate half that does NOT cross. `busy` counts what THIS mount
       asked for, so a screen does not open with rows marked busy for a write
       belonging to a screen the reader already left. */
    const g = gatedTasks();
    const first = mount("roster");
    await drain(() => { void first.result.current.keyed("google", g.task("g1")); });
    expect(first.result.current.busy.has("google")).toBe(true);

    first.unmount();
    const second = mount("roster");
    expect(second.result.current.busy.size).toBe(0);
    expect(second.result.current.writing).toBe(false);
  });

  it("keeps two subjects out of each other's way", async () => {
    const g = gatedTasks();
    const radar = mount("radar");
    const roster = mount("roster");

    await drain(() => { void radar.result.current.exclusive([], g.task("radar-write")); });
    await drain(() => { void roster.result.current.exclusive([], g.task("roster-write")); });

    // Different things; neither orders the other.
    expect(g.started).toEqual(["radar-write", "roster-write"]);
  });
});
