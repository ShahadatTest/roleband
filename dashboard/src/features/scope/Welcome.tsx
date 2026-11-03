import "./welcome/welcome.css";
import { lazy, Suspense, useEffect, useLayoutEffect, useRef, useState, type RefObject } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../../api";
import { useAsyncResource } from "../../hooks/useAsyncResource";
import { SETUP_PATH } from "../../routing/setupMode";
import { ConsentPane } from "../../patterns/privacy/ConsentPane";
import { groupsToAsk } from "../../patterns/privacy/consentCopy";
import { applySharing } from "../../diagnostics/sharing";
import { MotionStage } from "./motion/primitives";

/* The front door of first-run setup: the radar intro (the product narrative
   as a scene, not a form), then the usage-sharing question, then Profile's
   own walk in setup mode (routing/setupMode.ts). Setup is the walk every
   configured install edits later, so there is no second copy of its steps
   here to drift from it.

   The sharing question (docs/architecture.md) is asked BEFORE the walk, so a
   person who shares has the walk itself counted; nothing is counted before
   the answer. It is asked inside the intro's scene: the planet dims and the
   question takes the place of the intro's words. Skipped when nothing is left to ask, when an environment switch
   has turned sharing off, or when the state cannot be read (a failed read
   never blocks setup).

   The intro's planet is lazy: d3 and the world atlas load only when it shows. */

const RadarIntro = lazy(() => import("./welcome/RadarIntro"));

function WelcomeBody({ page }: { page: RefObject<HTMLElement | null> }) {
  const navigate = useNavigate();
  const sharing = useAsyncResource((signal) => api.usage(signal), []);
  const toAsk = sharing.data && !sharing.data.blocked_by ? groupsToAsk(sharing.data) : [];
  const [asking, setAsking] = useState(false);
  // The question opens at the top: on a short screen the intro is scrolled to
  // reach its button, and the question would otherwise open part-way down.
  useLayoutEffect(() => {
    page.current?.scrollTo?.({ top: 0 });
  }, [page, asking]);
  // The question takes the keyboard to its safe answer, as the dialog that
  // asks an existing install does: Enter on a question that just opened
  // never shares. The page stays at its top.
  const safe = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    if (asking) safe.current?.focus({ preventScroll: true });
  }, [asking]);
  // Pushed, not replaced: Back from setup's first step comes back here
  // rather than leaving RoleBand.
  const toWalk = () => navigate(SETUP_PATH);
  // The walk comes next: its catalog is asked while the welcome is read, once
  // the welcome is on screen. Loaded apart, so the welcome does not carry the
  // draft's code.
  useEffect(() => {
    const later = window.setTimeout(() => {
      void import("./useScopeDraft").then((draft) => draft.primeScopeCatalog());
    }, 1000);
    return () => window.clearTimeout(later);
  }, []);

  return (
    <Suspense fallback={<div className="welcome-intro-fallback" aria-hidden="true" />}>
      <RadarIntro
        onBegin={() => (toAsk.length > 0 ? setAsking(true) : toWalk())}
        question={asking && sharing.data ? (
          <ConsentPane
            look="scene"
            state={sharing.data}
            groups={toAsk}
            safeRef={safe}
            onAnswered={(next) => {
              void applySharing(next);
              toWalk();
            }}
          />
        ) : null}
      />
    </Suspense>
  );
}

export function Welcome() {
  const page = useRef<HTMLElement>(null);
  return (
    <main ref={page} className="main settings-view welcome-main">
      <MotionStage>
        <WelcomeBody page={page} />
      </MotionStage>
    </main>
  );
}
