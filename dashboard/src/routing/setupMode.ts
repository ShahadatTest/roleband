import { useEffect, useState } from "react";
import { useLocation } from "react-router-dom";
import { shellApi } from "../api/shell";

/* First-run setup: the welcome screen, then Profile's walk, with the window to
   itself: the rest of the app is not drawn.

   In Profile it is a query flag on the Direction tab, so a reload in the
   middle keeps it. The flag alone never turns it on: only an install with
   no profile and no saved scope is in setup, so a configured install that
   follows an old link or types the flag gets the ordinary Profile. A failed
   read is "not in setup": hiding the app is the one thing that must never
   happen by mistake. */

const SETUP_PARAM = "setup";
export const SETUP_PATH = `/profile/direction?${SETUP_PARAM}=1`;

export type SetupMode = "off" | "pending" | "on";

/** The install's answer, read once per page load and shared by the shell and
 *  Profile, so the shell and the walk never disagree about setup. */
let probe: Promise<boolean> | null = null;
/** The answer once it has come back, so a screen mounted after it reads it at
    once instead of showing a load state for a frame. */
let answered: boolean | null = null;

export function readUnconfigured(): Promise<boolean> {
  if (!probe) {
    const request = shellApi.profile?.();
    probe = (request
      ? request.then((state) => !state.profile && !state.scope_configured, () => false)
      : Promise.resolve(false)
    ).then((answer) => {
      answered = answer;
      return answer;
    });
  }
  return probe;
}

/** Who to tell when the answer is forgotten, so a screen already showing it
    reads it again. */
const forgotten = new Set<() => void>();

/** Forget the answer: finishing setup, or any saved scope, configures the
 *  install. */
export function forgetSetupProbe(): void {
  probe = null;
  answered = null;
  for (const listener of forgotten) listener();
}

/** Calls `listener` whenever the answer is forgotten; returns the way to stop. */
export function onSetupProbeForgotten(listener: () => void): () => void {
  forgotten.add(listener);
  return () => { forgotten.delete(listener); };
}

export function useSetupMode(): SetupMode {
  const { pathname, search } = useLocation();
  /* The welcome screen is setup's front door, so it has the window too, from
     a fresh install's first screen. */
  const flagged = pathname === "/welcome"
    || (pathname.startsWith("/profile") && new URLSearchParams(search).has(SETUP_PARAM));
  const [unconfigured, setUnconfigured] = useState<boolean | null>(answered);

  useEffect(() => {
    if (!flagged) return;
    let live = true;
    void readUnconfigured().then((answer) => {
      if (live) setUnconfigured(answer);
    });
    return () => { live = false; };
  }, [flagged]);

  if (!flagged) return "off";
  if (unconfigured === null) return "pending";
  return unconfigured ? "on" : "off";
}

/** What the walk hands the companies step it does not own: the step body
 *  comes from the Companies feature, composed in by the Profile route. */
export interface SetupCompaniesProps {
  /** The walk's step-foot class, so the step's Back and Start sit where every
   *  other step's buttons do. */
  footClassName: string;
  saving: boolean;
  onBack: () => void;
  /** Saves the profile and lands on the board. */
  onStart: () => Promise<void>;
  /** The choice kept for the tab from before a reload, and where a new one is
   *  kept (features/scope/setupStash). */
  keptChoice?: string;
  onChoice?: (choice: string) => void;
}
