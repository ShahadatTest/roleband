import { errorText } from "../../api/errorText";
import { useCallback, useRef, useState } from "react";
import type { PointerEvent as ReactPointerEvent, RefObject } from "react";
import type { ScheduleBinding } from "../../api";
import { companyName } from "../../format";
import { DAY, minuteOf } from "./charts/dial";
import type { DialMark } from "./charts/dial";
import { formatMinute, leadEvent, modeLabel } from "./charts/schedule";
import type { ScheduleEvent, ScheduleMode } from "./charts/schedule";
import {
  settingsUseDialDragCouldnTMoveThatScan,
  settingsUseDialDragDragAMarkToReschedule,
  settingsUseDialDragMovedTo,
} from "../../copy/gen/settings";

/* The dial's drag machine: pointer capture, the click latch, the live draft,
   and the one write the whole surface makes.

   It is a hook rather than a module of functions because every part of it is
   state the dial renders from — and because the three refs are the whole
   correctness story. `pointerRef` is what makes a second pointer on a second
   mark a no-op; `suppressClickRef` is what stops the click that follows a
   drag from also opening the inspector; `stageRef` is what turns a client
   coordinate into a minute. None of them can live in the component that draws
   the marks, because that component is re-created by every state change the
   drag causes. */

/* Pointer capture is what keeps a drag alive once the pointer leaves the 24px
   mark: without it the browser stops delivering moves and ups to the handle
   and the gesture dies where the cursor crosses the edge. That is held, in a
   real browser, by the two mouse drags in `tests/ux/schedule.spec.ts`. It is
   NOT held by any component test, and cannot be: jsdom implements neither
   method, so `ScheduleChronograph.test.tsx` stubs them and dispatches every
   pointer event at the mark directly.

   Both are guarded because both can throw on a pointer the browser does not
   count as active: `releasePointerCapture` is specified to raise
   NotFoundError for a pointerId that matches no active pointer, and it runs
   in the pointerup handler, before the persist call. Unguarded, one throw
   would drop the write the drag exists to make, silently. */
export const capture = (target: Element, pointerId: number) => {
  try {
    target.setPointerCapture(pointerId);
  } catch {
    // An uncaptured drag still tracks while the pointer stays on the mark.
  }
};

export const releaseCapture = (target: Element, pointerId: number) => {
  try {
    target.releasePointerCapture(pointerId);
  } catch {
    // Already released — the browser drops capture at pointerup on its own.
  }
};

/** Times on the dial land on a 10-minute grid. */
const SNAP_MINUTES = 10;

export const snapMinute = (minute: number) =>
  (Math.round(minute / SNAP_MINUTES) * SNAP_MINUTES) % DAY;

/** The dial minute under a pointer: its angle around the stage's centre.
 *  Snapped to the 10-minute grid unless `continuous`: a drag follows the
 *  pointer exactly and snaps only where it is dropped, because snapping every
 *  move makes the mark jump 2.5 degrees at a time.
 *  Shared by the company marks and the plan's runs. */
export const minuteAtPointer = (
  stage: HTMLElement | null,
  event: { clientX: number; clientY: number },
  continuous = false,
) => {
  const rect = stage?.getBoundingClientRect();
  if (!rect) return 0;
  const x = event.clientX - (rect.left + rect.width / 2);
  const y = event.clientY - (rect.top + rect.height / 2);
  const angle = (Math.atan2(x, -y) + Math.PI * 2) % (Math.PI * 2);
  const rawMinute = (angle / (Math.PI * 2)) * DAY;
  return continuous ? rawMinute : snapMinute(rawMinute);
};

/** One state update per animation frame, however fast pointer moves arrive:
 *  a mouse reports at 125-1000 Hz, and re-rendering the dial for each report
 *  queues renders behind the pointer, which reads as the mark lagging and then
 *  jumping. The latest value wins; `flush` runs a pending one at once (a drop),
 *  `cancel` drops it (a cancelled drag). */
export function useFrameThrottle<T>(apply: (value: T) => void) {
  const frame = useRef<number | null>(null);
  const latest = useRef<{ value: T } | null>(null);
  const applyRef = useRef(apply);
  applyRef.current = apply;
  // One object for the hook's life, so it can sit in a dependency list.
  const [throttle] = useState(() => {
    const run = () => {
      frame.current = null;
      const pending = latest.current;
      latest.current = null;
      if (pending) applyRef.current(pending.value);
    };
    return {
      push: (value: T) => {
        latest.current = { value };
        if (frame.current === null) frame.current = requestAnimationFrame(run);
      },
      flush: () => {
        if (frame.current !== null) cancelAnimationFrame(frame.current);
        run();
      },
      cancel: () => {
        if (frame.current !== null) cancelAnimationFrame(frame.current);
        frame.current = null;
        latest.current = null;
      },
    };
  });
  return throttle;
}

export interface ScheduleMove {
  bindingId: number;
  mode: ScheduleMode;
  localMinute: number;
  timezone: string;
}

export interface DragState {
  key: string;
  minute: number;
  /** False until the pointer has travelled far enough to be a drag rather
   *  than a click, so a stack does not split the instant it is pressed. */
  moved: boolean;
}

/** The pointer currently captured on a mark, if any. Identity by pointerId as
 *  well as by key: a second finger on a second mark is a no-op, not a race. */
interface ActivePointer {
  key: string;
  pointerId: number;
  startX: number;
  startY: number;
  moved: boolean;
}

export interface DialDrag {
  stageRef: RefObject<HTMLDivElement | null>;
  /** Each mark's button, so the inspector's popover can anchor to the one
      that opened it. A plain Map, not a ref cell that can be null: it is
      created once and only ever mutated. */
  anchors: Map<string, HTMLButtonElement>;
  /** The live drag, or null. The dial reads a mark's minute from here. */
  draft: DragState | null;
  /** A schedule write is out, from any control on the screen. Every mark
   *  waits for it, not only the one being moved. */
  saving: boolean;
  notice: string;
  setNotice: (notice: string) => void;
  error: string | null;
  persist: (event: ScheduleEvent, minute: number) => void;
  start: (pointer: ReactPointerEvent<HTMLButtonElement>, mark: DialMark) => void;
  move: (pointer: ReactPointerEvent<HTMLButtonElement>, mark: DialMark) => void;
  finish: (pointer: ReactPointerEvent<HTMLButtonElement>, mark: DialMark) => void;
  cancel: () => void;
  /** True when this click is the tail of a drag; consumes the latch. */
  consumeClickAfterDrag: () => boolean;
}

export function useDialDrag(
  bindings: Map<number, ScheduleBinding>,
  onMove: (move: ScheduleMove) => Promise<void>,
  /** Under the schedule plan the notices name a full or quick scan. */
  planned: boolean,
  /** The screen's one busy state: a schedule write is out. */
  busy: boolean,
): DialDrag {
  const stageRef = useRef<HTMLDivElement>(null);
  const pointerRef = useRef<ActivePointer | null>(null);
  const suppressClickRef = useRef(false);
  const anchorsRef = useRef(new Map<string, HTMLButtonElement>());
  const [draft, setDraft] = useState<DragState | null>(null);
  const [notice, setNotice] = useState(settingsUseDialDragDragAMarkToReschedule());
  const [error, setError] = useState<string | null>(null);

  const pointerMinute = (event: ReactPointerEvent<HTMLButtonElement>) =>
    minuteAtPointer(stageRef.current, event);
  const frames = useFrameThrottle<{ key: string; minute: number; event: ScheduleEvent | null }>(
    ({ key, minute, event }) => {
      setDraft({ key, minute, moved: true });
      if (event) {
        setNotice(`${companyName(event.company)} · ${modeLabel(event.mode, planned)} · ${
          formatMinute(snapMinute(minute))}`);
      }
    },
  );

  const persist = async (event: ScheduleEvent, minute: number) => {
    setError(null);
    try {
      await onMove({
        bindingId: event.bindingId,
        mode: event.mode,
        localMinute: minute,
        timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC",
      });
      setNotice(
        settingsUseDialDragMovedTo({ company: companyName(event.company), scan: modeLabel(event.mode, planned), time: formatMinute(minute) }),
      );
    } catch (caught) {
      setError(errorText(caught, settingsUseDialDragCouldnTMoveThatScan()));
    } finally {
      setDraft(null);
    }
  };

  const draggedEvent = (mark: DialMark) => leadEvent(mark.events, bindings);

  /* A cancelled drag is not a reschedule: the draft goes and the marker reads
     from the schedule again. Nothing else releases it — the pointer is gone,
     so there is no up event coming. */
  const cancel = useCallback(() => {
    pointerRef.current = null;
    frames.cancel();
    setDraft(null);
  }, [frames]);


  const startDrag = (
    pointer: ReactPointerEvent<HTMLButtonElement>,
    mark: DialMark,
  ) => {
    // A drag that ended without a click (released off the handle, say) leaves
    // this latched, and the latch would eat the next click on any mark. It
    // belongs to one interaction, so clear it as the next one starts.
    suppressClickRef.current = false;
    if (mark.parked) return;
    const event = draggedEvent(mark);
    if (!event) return;
    pointerRef.current = {
      key: mark.key,
      pointerId: pointer.pointerId,
      startX: pointer.clientX,
      startY: pointer.clientY,
      moved: false,
    };
    capture(pointer.currentTarget, pointer.pointerId);
    setDraft({ key: mark.key, minute: minuteOf(event.at), moved: false });
    // No preventDefault here: cancelling pointerdown suppresses the
    // compatibility mouse events, and with them the click that opens the
    // inspector. Selection is handled by the stage's mousedown instead.
  };

  const moveDrag = (
    pointer: ReactPointerEvent<HTMLButtonElement>,
    mark: DialMark,
  ) => {
    const active = pointerRef.current;
    if (!active || active.pointerId !== pointer.pointerId || active.key !== mark.key) return;
    if (
      !active.moved &&
      Math.hypot(pointer.clientX - active.startX, pointer.clientY - active.startY) < 4
    ) return;
    active.moved = true;
    frames.push({
      key: mark.key,
      minute: minuteAtPointer(stageRef.current, pointer, true),
      event: draggedEvent(mark),
    });
  };

  const finishDrag = (
    pointer: ReactPointerEvent<HTMLButtonElement>,
    mark: DialMark,
  ) => {
    const active = pointerRef.current;
    if (!active || active.pointerId !== pointer.pointerId || active.key !== mark.key) return;
    pointerRef.current = null;
    releaseCapture(pointer.currentTarget, pointer.pointerId);
    frames.cancel();
    if (!active.moved) {
      setDraft(null);
      return;
    }
    suppressClickRef.current = true;
    // Hold the mark where it was dropped, on the grid, while the write is in
    // flight, so it does not spring back to its old time and then jump.
    setDraft({ key: mark.key, minute: pointerMinute(pointer), moved: true });
    const event = draggedEvent(mark);
    if (!event) {
      setDraft(null);
      return;
    }
    void persist(event, pointerMinute(pointer));
  };

  return {
    stageRef,
    anchors: anchorsRef.current,
    draft,
    saving: busy,
    notice,
    setNotice,
    error,
    persist: (event, minute) => void persist(event, minute),
    start: startDrag,
    move: moveDrag,
    finish: finishDrag,
    cancel,
    consumeClickAfterDrag: () => {
      if (!suppressClickRef.current) return false;
      suppressClickRef.current = false;
      return true;
    },
  };
}
