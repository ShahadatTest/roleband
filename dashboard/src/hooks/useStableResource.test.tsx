import { act, render } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it } from "vitest";
import { useAsyncResource } from "./useAsyncResource";
import { useStableResource } from "./useStableResource";

/* The identity claim, measured on the real hook rather than on a hand-made
 * object: `useAsyncResource` is the thing whose literal churns, and a test
 * against a fake resource would pass while the assumption about the real one
 * rotted. */

function harness(load: () => Promise<number>) {
  const seen: unknown[] = [];
  let bump: (() => void) | null = null;
  function Probe() {
    const [, setTick] = useState(0);
    bump = () => setTick((n) => n + 1);
    const stable = useStableResource(useAsyncResource(load, []));
    seen.push(stable);
    return <span>{stable.data ?? "none"}</span>;
  }
  const view = render(<Probe />);
  return { seen, rerender: () => act(() => { bump?.(); }), view };
}

describe("useStableResource", () => {
  it("hands back the same object across a render that moved nothing", async () => {
    const h = harness(() => Promise.resolve(7));
    await act(async () => { await Promise.resolve(); });
    const before = h.seen.length;

    await h.rerender();

    expect(h.seen.length).toBeGreaterThan(before);
    expect(h.seen[h.seen.length - 1]).toBe(h.seen[before - 1]);
  });

  it("hands back a new object when the data lands", async () => {
    const h = harness(() => Promise.resolve(7));
    const first = h.seen[0];
    await act(async () => { await Promise.resolve(); });

    const latest = h.seen[h.seen.length - 1] as { data: number | null; loading: boolean };
    expect(latest).not.toBe(first);
    expect(latest.data).toBe(7);
    expect(latest.loading).toBe(false);
  });

  it("carries the error through rather than swallowing it", async () => {
    const boom = new Error("resource exploded");
    const h = harness(() => Promise.reject(boom));
    await act(async () => { await Promise.resolve(); await Promise.resolve(); });

    const latest = h.seen[h.seen.length - 1] as { error: Error | null };
    expect(latest.error).toBe(boom);
  });
});
