import { useEffect, useState } from "react";
import { onSetupProbeForgotten, readUnconfigured } from "./setupMode";

/** Whether this install has been set up (a profile or a saved scope), from
 *  setup's own probe: null until it answers. A saved scope forgets the probe,
 *  and a screen showing the answer reads it again. Its own module, not
 *  setupMode.ts: the shell loads that one, and only screens ask this. */
export function useInstallSetUp(): boolean | null {
  const [unconfigured, setUnconfigured] = useState<boolean | null>(null);
  useEffect(() => {
    let live = true;
    const read = () => {
      void readUnconfigured().then((answer) => {
        if (live) setUnconfigured(answer);
      });
    };
    read();
    const stop = onSetupProbeForgotten(read);
    return () => {
      live = false;
      stop();
    };
  }, []);
  return unconfigured === null ? null : !unconfigured;
}
