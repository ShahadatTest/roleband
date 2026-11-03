import { AnimatePresence, MotionConfig, motion } from "motion/react";
import { useReducer, type CSSProperties, type ReactNode } from "react";
import "./primitives.css";

/* RoleBand motion primitives: the shared animation vocabulary, built on
   motion/react. These own *travel and
   reveal* (mount, step, cascade); hover/pop stay CSS-owned on the base --ease
   tokens. Register: docs/ui.md, "Motion".
   Reduced motion: wrap a screen in <MotionStage> once — every primitive under
   it then collapses to instant cuts when the OS asks for reduced motion. */

/** Silk deceleration — the JS mirror of --ease-silk in styles.css. */
const SILK = [0.22, 1, 0.36, 1] as const;
/** Travel duration (seconds) for a glide. */
const GLIDE = 0.34;

/** Screen-level wrapper: honors prefers-reduced-motion for everything below. */
export function MotionStage({ children }: { children: ReactNode }) {
  return <MotionConfig reducedMotion="user">{children}</MotionConfig>;
}

/** Fade-and-rise mount reveal for a block of content. */
export function Reveal({
  children,
  delay = 0,
  y = 12,
  className,
  style,
}: {
  children: ReactNode;
  delay?: number;
  y?: number;
  className?: string;
  style?: CSSProperties;
}) {
  return (
    <motion.div
      className={className}
      style={style}
      initial={{ opacity: 0, y }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: GLIDE, delay, ease: SILK }}
    >
      {children}
    </motion.div>
  );
}

/* Pane transitions use a sync crossfade on a grid stack (.phase-stack in
   styles.css): outgoing and incoming layers briefly share one grid cell, so
   there is no layout jump and — unlike AnimatePresence's "wait" mode — the
   incoming layer starts animating immediately and can never be deadlocked by
   an exit that fails to complete. The exiting layer loses pointer events via
   CSS (`:not(:last-child)`). */

/* Re-render on every completed exit, so AnimatePresence re-diffs its children.

   AnimatePresence renders `renderedChildren` — REACT STATE, not the children it
   was just handed — and when the last exiting child finishes it restores a
   SNAPSHOT of them (`setRenderedChildren(pendingPresentChildren.current)`).
   That restore never touches `diffedChildren`, and the diff that would repair
   it only runs when the `children` prop changes identity. The two together are
   not concurrent-safe: the snapshot is taken in an animation callback at
   default priority, so a DISCRETE render (a click) can replace the children
   between the snapshot and its flush — and the stale snapshot then wins for as
   long as nothing re-renders this component: the screen shows a dead render
   of an earlier step while the live state has moved on.

   Bumping our own state in `onExitComplete` hands AnimatePresence a fresh
   `children` identity to diff against, and lands in the SAME batch as the stale
   restore, so the repair happens before paint rather than a frame later. In the
   ordinary case the fresh element wraps the same child object React already
   rendered, so the extra pass bails out one level down and costs nothing. */
function useExitRearm() {
  const [, rearm] = useReducer((generation: number) => generation + 1, 0);
  return rearm;
}

/** Crossfade between whole phases of a screen (e.g. intro → walk). */
export function PhaseFade({
  phaseKey,
  children,
  className,
}: {
  phaseKey: string;
  children: ReactNode;
  className?: string;
}) {
  const rearm = useExitRearm();
  return (
    <div className={`phase-stack${className ? ` ${className}` : ""}`}>
      <AnimatePresence initial={false} onExitComplete={rearm}>
        <motion.div
          key={phaseKey}
          className="phase-layer"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: GLIDE * 0.6, ease: SILK }}
        >
          {children}
        </motion.div>
      </AnimatePresence>
    </div>
  );
}
