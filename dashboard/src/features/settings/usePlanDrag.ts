import { useRef, useState } from "react";
import type { PointerEvent as ReactPointerEvent, RefObject } from "react";
import type { SchedulePlanUpdate } from "../../api";
import { errorText } from "../../api/errorText";
import { DAY } from "./charts/dial";
import type { PlanSegment } from "./charts/plan";
import { kindLabel } from "./charts/plan";
import { formatMinute } from "./charts/schedule";
import { capture, minuteAtPointer, releaseCapture, snapMinute, useFrameThrottle } from "./useDialDrag";
import {
  settingsScheduleSectionCouldnTSaveThatChange,
  settingsUseDialDragCouldnTMoveThatScan,
  settingsUsePlanDragFullScanMovedToDone,
  settingsUsePlanDragQuickScansMovedOneAt,
} from "../../copy/gen/settings";

/* Dragging the plan's runs around the dial. The dial is a direct editor: the
   plan's runs are its marks, each one to drag or click for its exact time, and
   a drop means what it looks like:

     a quick scan  -> every quick scan moves with it: the repeats run at fixed
                      clock times from where it was dropped (`repeat_anchor_minute`);
     a full scan   -> the daily full scan starts where it was dropped, so it is
                      done by that start + its measured length + 10 minutes
                      (`ready_by_minute`, to the minute: rounding it to the grid
                      would move the scan minutes off the drop, a visible jump).

   The pointer mechanics are the company marks' (`useDialDrag`): capture, a
   4px threshold before a press becomes a drag, and the latch that stops the
   click a drag ends in from also opening the inspector. */

export interface PlanDraft {
  key: string;
  kind: PlanSegment["kind"];
  /** Minutes the dragged run has moved from where it was: fractional while
   *  dragging (the run follows the pointer), on the grid once dropped. */
  delta: number;
  moved: boolean;
  /** The time the run would land on now, on the grid, for its label. */
  minute: number;
}

interface ActivePointer {
  key: string;
  pointerId: number;
  startX: number;
  startY: number;
  moved: boolean;
  /** The run as it was when pressed. Every move is measured from here: the
   *  dial hands the handler the run as currently DRAWN, already shifted by the
   *  drag, and measuring from that would make each frame undo the last one, so
   *  the run would flicker between the pointer and its old place. */
  origin: PlanSegment;
}

export interface PlanDrag {
  draft: PlanDraft | null;
  /** A schedule write is out, from any control on the screen. */
  saving: boolean;
  notice: string | null;
  error: string | null;
  anchors: Map<string, HTMLButtonElement>;
  start: (pointer: ReactPointerEvent<HTMLButtonElement>, segment: PlanSegment) => void;
  move: (pointer: ReactPointerEvent<HTMLButtonElement>, segment: PlanSegment) => void;
  finish: (pointer: ReactPointerEvent<HTMLButtonElement>, segment: PlanSegment) => void;
  cancel: () => void;
  consumeClickAfterDrag: () => boolean;
  /** Save a run's new start minute, from a drop or the inspector's field. */
  place: (segment: PlanSegment, minute: number) => Promise<void>;
  save: (update: SchedulePlanUpdate, done: string) => Promise<void>;
}

/** The ready-by minute that has a full scan of `seconds` start at `minute`
 *  (the server starts it that long + 10 minutes before the ready-by time). */
export const readyByForStart = (minute: number, seconds: number) =>
  (Math.round(minute + seconds / 60 + 10) % DAY + DAY) % DAY;

/** Where a full scan done by `readyBy` starts, the inverse of the above. */
export const startForReadyBy = (readyBy: number, seconds: number) =>
  (Math.round(readyBy - seconds / 60 - 10) % DAY + DAY) % DAY;

const signedDelta = (from: number, to: number) => {
  const raw = ((to - from) % DAY + DAY) % DAY;
  return raw > DAY / 2 ? raw - DAY : raw;
};

/** Whether a run can be moved: one in progress cannot. */
export const movable = (segment: PlanSegment) => !segment.running;

export function usePlanDrag(
  stageRef: RefObject<HTMLDivElement | null>,
  onPlan: (update: SchedulePlanUpdate) => Promise<void>,
  /** The screen's one busy state: a schedule write is out. */
  busy: boolean,
): PlanDrag {
  const pointerRef = useRef<ActivePointer | null>(null);
  const suppressClickRef = useRef(false);
  const anchorsRef = useRef(new Map<string, HTMLButtonElement>());
  const [draft, setDraft] = useState<PlanDraft | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const frames = useFrameThrottle<{ segment: PlanSegment; minute: number }>(({ segment, minute }) => {
    // `segment` is the run as pressed (the pointer's `origin`).
    setDraft({
      key: segment.key,
      kind: segment.kind,
      delta: signedDelta(segment.startMinute, minute),
      moved: true,
      minute: snapMinute(minute),
    });
    setNotice(`${kindLabel(segment.kind)} · ${formatMinute(snapMinute(minute))}`);
  });

  /** One change to the plan. A failure names the server's reason, else
      `failed`, which says what this change was: a moved scan, or a setting. */
  const save = async (
    update: SchedulePlanUpdate,
    done: string,
    failed: string = settingsScheduleSectionCouldnTSaveThatChange(),
  ) => {
    setError(null);
    try {
      await onPlan(update);
      setNotice(done);
    } catch (caught) {
      setError(errorText(caught, failed));
    } finally {
      setDraft(null);
    }
  };

  const place = (segment: PlanSegment, minute: number) =>
    segment.kind === "quick"
      ? save(
        { repeat_anchor_minute: minute },
        settingsUsePlanDragQuickScansMovedOneAt({ time: formatMinute(minute) }),
        settingsUseDialDragCouldnTMoveThatScan(),
      )
      : save(
        { ready_by_minute: readyByForStart(minute, segment.seconds) },
        settingsUsePlanDragFullScanMovedToDone({ start: formatMinute(minute), doneBy: formatMinute(readyByForStart(minute, segment.seconds)) }),
        settingsUseDialDragCouldnTMoveThatScan(),
      );

  const start = (pointer: ReactPointerEvent<HTMLButtonElement>, segment: PlanSegment) => {
    suppressClickRef.current = false;
    if (!movable(segment)) return;
    pointerRef.current = {
      key: segment.key,
      pointerId: pointer.pointerId,
      startX: pointer.clientX,
      startY: pointer.clientY,
      moved: false,
      origin: segment,
    };
    capture(pointer.currentTarget, pointer.pointerId);
    setDraft({ key: segment.key, kind: segment.kind, delta: 0, moved: false, minute: segment.startMinute });
  };

  const move = (pointer: ReactPointerEvent<HTMLButtonElement>, segment: PlanSegment) => {
    const active = pointerRef.current;
    if (!active || active.pointerId !== pointer.pointerId || active.key !== segment.key) return;
    if (
      !active.moved
      && Math.hypot(pointer.clientX - active.startX, pointer.clientY - active.startY) < 4
    ) return;
    active.moved = true;
    frames.push({ segment: active.origin, minute: minuteAtPointer(stageRef.current, pointer, true) });
  };

  const finish = (pointer: ReactPointerEvent<HTMLButtonElement>, segment: PlanSegment) => {
    const active = pointerRef.current;
    if (!active || active.pointerId !== pointer.pointerId || active.key !== segment.key) return;
    pointerRef.current = null;
    releaseCapture(pointer.currentTarget, pointer.pointerId);
    frames.cancel();
    if (!active.moved) {
      setDraft(null);
      return;
    }
    suppressClickRef.current = true;
    const { origin } = active;
    const minute = minuteAtPointer(stageRef.current, pointer);
    // Hold the run where it was dropped, on the grid, until the saved plan
    // comes back, so it never springs back to its old place first.
    setDraft({
      key: origin.key, kind: origin.kind, delta: signedDelta(origin.startMinute, minute), moved: true, minute,
    });
    void place(origin, minute);
  };

  return {
    draft,
    saving: busy,
    notice,
    error,
    anchors: anchorsRef.current,
    start,
    move,
    finish,
    cancel: () => {
      pointerRef.current = null;
      frames.cancel();
      setDraft(null);
    },
    consumeClickAfterDrag: () => {
      if (!suppressClickRef.current) return false;
      suppressClickRef.current = false;
      return true;
    },
    place,
    save,
  };
}
