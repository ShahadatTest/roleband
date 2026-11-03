import { act, render, screen } from "@testing-library/react";
import { useState } from "react";
import { flushSync } from "react-dom";
import { describe, expect, it } from "vitest";
import { PhaseFade } from "./primitives";

/* The crossfade primitives present REACT STATE, not the children they were last
   handed: AnimatePresence keeps a `renderedChildren` array and, when the last
   exiting layer finishes, restores a SNAPSHOT of the children taken in a layout
   effect. The restore never touches its `diffedChildren` bookkeeping, and the
   diff that would repair it runs only when the `children` prop changes identity
   — so a snapshot that goes stale wins for as long as nothing re-renders the
   primitive.

   That is reachable in the real app because the snapshot is restored from an
   animation callback (default priority) while a click renders at discrete
   priority: the click's children replace the snapshot's, then the queued
   restore lands and puts the dead ones back: the screen shows the previous
   step's markup and stays there while the wizard's own state says otherwise.

   Both tests below reproduce that ordering deterministically rather than
   waiting for the race: `act` holds the queued restore, and `flushSync` renders
   new children ahead of it at discrete priority. Remove the primitives'
   `onExitComplete` re-arm and both fail with the stale content on screen. */

function useProbe(initial: string) {
  const [value, setValue] = useState(initial);
  return [value, setValue] as const;
}

describe("PhaseFade", () => {
  it("shows the live children when a late exit restores a stale snapshot", async () => {
    let setPhase!: (value: string) => void;
    let setContent!: (value: string) => void;

    function Harness() {
      const [phase, phaseSetter] = useProbe("intro");
      const [content, contentSetter] = useProbe("first");
      setPhase = phaseSetter;
      setContent = contentSetter;
      return (
        <PhaseFade phaseKey={phase}>
          <p data-testid="content">{content}</p>
        </PhaseFade>
      );
    }

    render(<Harness />);
    await act(async () => { setPhase("walk"); });
    // The outgoing phase is still on screen, animating out.
    expect(document.querySelectorAll(".phase-layer")).toHaveLength(2);

    await act(async () => {
      // Let the outgoing layer finish. Its restore is queued at default
      // priority, and `act` holds it rather than flushing it.
      await new Promise((resolve) => setTimeout(resolve, 400));
      // A discrete render replaces the children ahead of that queued restore.
      flushSync(() => setContent("second"));
    });

    expect(document.querySelectorAll(".phase-layer")).toHaveLength(1);
    expect(screen.getByTestId("content").textContent).toBe("second");
  });
});
