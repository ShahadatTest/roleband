import { useMemo } from "react";
import type { ScheduleBinding } from "../../api";
import { companyName } from "../../format";
import { dragSurface } from "../../ui";
import {
  CENTER,
  DAY,
  R_DISC,
  R_HUB,
  R_NUMERAL,
  R_REC,
  R_TICKS,
  SIZE,
  WINDOW_BAND,
  WINDOW_HALO,
  annulusPath,
  arcPath,
  cappedArcPath,
  dialPoint,
  minuteOf,
} from "./charts/dial";
import type { DialMark, PlacedLabel } from "./charts/dial";
import type { PlanSegment } from "./charts/plan";
import { editableReason, formatMinute, leadEvent, modeLabel, stackText } from "./charts/schedule";
import type { ReconciliationWindow } from "./charts/schedule";
import type { DialDrag } from "./useDialDrag";
import { movable } from "./usePlanDrag";
import type { PlanDrag } from "./usePlanDrag";
import {
  settingsChronographDialATimeYouSet,
  settingsChronographDialAuthoritativeCycle,
  settingsChronographDialDiscoveryOrbit,
  settingsChronographDialDraggableScheduleMarks,
  settingsChronographDialFullScan,
  settingsChronographDialMoveCompany,
  settingsChronographDialMovePlannedScan,
  settingsChronographDialNight,
  settingsChronographDialQuickScan,
  settingsChronographDialReconciliationOrbit,
  settingsChronographDialScanClock,
  settingsChronographDialScanRunning,
  settingsChronographDialScheduleClockLegend,
  settingsChronographDialStackLocked,
  settingsChronographDialStackMovable,
  settingsChronographDialStillAt,
  settingsChronographDialUsuallyOff,
} from "../../copy/gen/settings";

/** The centre readout: what runs next, said the same way in both modes. */
export interface HubReadout {
  title: string;
  /** The clock time, or null when the next thing is not at a time ("due now",
   *  "when you turn it on" sit in `status` instead). */
  time: string | null;
  status: string | null;
  subject: string;
  relative: string | null;
}

/** The schedule plan's layer of the dial. */
export interface DialPlan {
  segments: PlanSegment[];
  /** Minutes outside the usual on-hours, or null while still learning. */
  off: Array<[number, number]> | null;
}

/** Half-thickness of a planned run's arc: a run is a stretch of the orbit the
 *  marks ride on, heavier than the cycle's lit thread. */
const RUN_BAND = 4.5;

/* The dial itself: the stage, the engraved face, and the marks you can grab.

   Everything here is drawing plus one gesture. What a mark MEANS lives in
   charts/, where it is measured; what a drag DOES lives in useDialDrag, where
   it is stateful. This file is what is left, and it is the one that carries
   the a11y allowance — see the stage's mousedown below and its entry in
   eslint.config.js. */

interface Props {
  marks: DialMark[];
  labels: PlacedLabel[];
  cycle: ReconciliationWindow | null;
  summary: string;
  bindings: Map<number, ScheduleBinding>;
  markMinute: (mark: DialMark) => number;
  /** The centre readout. Null when nothing is due. */
  hub: HubReadout | null;
  /** The schedule plan's runs and usual hours; null under the per-company timers. */
  plan: DialPlan | null;
  /** Dragging and clicking the plan's runs. */
  planDrag: PlanDrag;
  inspectedRun: string | null;
  onOpenRun: (segment: PlanSegment) => void;
  /** Where the schedule was generated, which is where "now" is drawn. */
  nowMinute: number;
  inspected: string | null;
  drag: DialDrag;
  onOpen: (mark: DialMark) => void;
}

export function ChronographDial({
  marks,
  labels,
  cycle,
  summary,
  bindings,
  markMinute,
  hub,
  plan,
  planDrag,
  inspectedRun,
  onOpenRun,
  nowMinute,
  inspected,
  drag,
  onOpen,
}: Props) {
  // The window is drawn only when it says something the marks cannot. A
  // one-binding cycle IS its mark: same instant, same connector, and one
  // scheduler tick long, so an arc for it would have to invent a duration.
  // With two or more the marks all sit on one instant while the work
  // serializes across the window, and only the band shows that stretch. Then
  // it is long enough to read as an arc on its own, so nothing needs padding:
  // the span drawn is the span projected.
  //
  // Two concentric arcs, closed at each end by a half-round rather than a
  // radial cut. Kept thin and paired with a blurred halo, it reads as a lit
  // stretch of the orbit the marks ride on rather than a plank laid over it,
  // and a lit thread ends by tapering out, not by being sawn off. Rounding
  // costs the track 2.75 units of overshoot per end (~12 minutes at this
  // radius) and buys the one thing a segment of orbit needs to look like
  // light rather than a slab.
  const windowArc = useMemo(() => {
    if (plan || !cycle || cycle.count < 2) return null;
    const [start, end] = [minuteOf(cycle.start), minuteOf(cycle.end)];
    return {
      track: cappedArcPath(start, end, R_REC - WINDOW_BAND, R_REC + WINDOW_BAND),
      halo: cappedArcPath(start, end, R_REC - WINDOW_HALO, R_REC + WINDOW_HALO),
    };
  }, [cycle, plan]);

  // The band is a projection, so it is brightest where the cycle is certain —
  // its start — and fades out toward an end nobody has run yet. Track and halo
  // share the axis so they die together: a halo at flat opacity would outlive
  // the track and its own end would become the edge of the shape.
  const windowFade = useMemo(() => {
    if (!cycle) return null;
    const [x1, y1] = dialPoint(minuteOf(cycle.start), R_REC);
    const [x2, y2] = dialPoint(minuteOf(cycle.end), R_REC);
    return { x1, y1, x2, y2 };
  }, [cycle]);

  const nightPath = useMemo(() => annulusPath(22 * 60, 6 * 60, R_HUB + 8, R_TICKS - 2), []);
  // Once the plan has learned when the computer is usually on, the tint marks
  // the hours it is usually OFF instead of a night everyone was assumed to have.
  const offPaths = useMemo(() => plan?.off?.map(([start, end]) => (
    end - start === DAY || (start === 0 && end === DAY)
      ? annulusPath(0, DAY - 0.01, R_HUB + 8, R_TICKS - 2)
      : annulusPath(start, end, R_HUB + 8, R_TICKS - 2)
  )) ?? null, [plan]);
  const runArcs = useMemo(() => (plan?.segments ?? []).map((segment) => {
    const radius = segment.kind === "full" ? R_REC : R_DISC;
    return {
      segment,
      d: cappedArcPath(segment.startMinute, segment.endMinute, radius - RUN_BAND, radius + RUN_BAND),
    };
  }), [plan]);

  const ticks = useMemo(() => {
    const rows = [];
    for (let i = 0; i < 48; i++) {
      const minute = i * 30;
      const major = minute % 360 === 0;
      const hour = i % 2 === 0;
      const [x1, y1] = dialPoint(minute, major ? 250 : 254);
      const [x2, y2] = dialPoint(minute, R_TICKS);
      rows.push({ key: i, x1, y1, x2, y2, major, hour });
    }
    return rows;
  }, []);
  /* The dial is a drag surface; `dragSurface` carries why (src/ui/dragSurface.ts). */
  return (
    <>
      <div
        className={`schedule-clock-stage${drag.draft?.moved || planDrag.draft?.moved ? " is-dragging" : ""}`}
        ref={drag.stageRef}
        {...dragSurface}
      >
        <figure
          role="img"
          aria-label={settingsChronographDialScanClock()}
          className="schedule-dial-figure"
        >
          <svg viewBox={`0 0 ${SIZE} ${SIZE}`} className="schedule-dial" aria-hidden="true">
            <defs>
              {windowFade && (
                <linearGradient
                  id="schedule-cycle-fade"
                  gradientUnits="userSpaceOnUse"
                  x1={windowFade.x1}
                  y1={windowFade.y1}
                  x2={windowFade.x2}
                  y2={windowFade.y2}
                >
                  <stop className="dial-window-from" offset="0" />
                  <stop className="dial-window-mid" offset=".7" />
                  <stop className="dial-window-to" offset="1" />
                </linearGradient>
              )}
              {windowFade && (
                <linearGradient
                  id="schedule-cycle-halo-fade"
                  gradientUnits="userSpaceOnUse"
                  x1={windowFade.x1}
                  y1={windowFade.y1}
                  x2={windowFade.x2}
                  y2={windowFade.y2}
                >
                  <stop className="dial-window-glow-from" offset="0" />
                  <stop className="dial-window-glow-mid" offset=".7" />
                  <stop className="dial-window-glow-to" offset="1" />
                </linearGradient>
              )}
              <filter id="schedule-glow" x="-60%" y="-60%" width="220%" height="220%">
                <feGaussianBlur stdDeviation="6" result="blur" />
                <feMerge>
                  <feMergeNode in="blur" />
                  <feMergeNode in="SourceGraphic" />
                </feMerge>
              </filter>
              {/* Blur alone, no merge back to source. #schedule-glow keeps the
                  crisp shape on top of its blur: right for the hand's dot,
                  wrong for a halo, whose hard-edged annulus would show under
                  the glow meant to soften the band's ends. */}
              <filter id="schedule-cycle-halo" x="-60%" y="-60%" width="220%" height="220%">
                <feGaussianBlur stdDeviation="5" />
              </filter>
            </defs>

            {offPaths ? (
              offPaths.map((d, index) => (
                <path key={index} className="dial-night" data-testid="usually-off" d={d} />
              ))
            ) : (
              <>
                <path className="dial-night" d={nightPath} />
                <path className="dial-night-edge" d={arcPath(22 * 60, 6 * 60, R_TICKS - 2)} />
                <text className="dial-night-text" x={dialPoint(2 * 60, 274)[0]} y={dialPoint(2 * 60, 274)[1]} textAnchor="middle">
                  {settingsChronographDialNight()}
                </text>
              </>
            )}

            {ticks.map((tick) => (
              <line
                key={tick.key}
                x1={tick.x1}
                y1={tick.y1}
                x2={tick.x2}
                y2={tick.y2}
                className={tick.major ? "dial-tick major" : tick.hour ? "dial-tick hour" : "dial-tick"}
              />
            ))}
            {[0, 6, 12, 18].map((hour) => {
              const [x, y] = dialPoint(hour * 60, R_NUMERAL);
              return (
                <text key={hour} className="dial-numeral" x={x} y={y} dy={4} textAnchor="middle">
                  {String(hour).padStart(2, "0")}
                </text>
              );
            })}

            <circle className="dial-orbit" cx={CENTER} cy={CENTER} r={R_REC} />
            <circle className="dial-orbit" cx={CENTER} cy={CENTER} r={R_DISC} />
            {(() => {
              const [hx, hy] = dialPoint(nowMinute, R_REC);
              const [tx, ty] = dialPoint((nowMinute + DAY / 2) % DAY, 24);
              return (
                <g className="dial-hand">
                  <line x1={tx} y1={ty} x2={hx} y2={hy} />
                  <circle cx={hx} cy={hy} r={3.4} filter="url(#schedule-glow)" />
                </g>
              );
            })()}
            <circle className="dial-hub" cx={CENTER} cy={CENTER} r={R_HUB} />

            {windowArc && (
              <g data-testid="reconciliation-window">
                <path
                  className="dial-window-glow"
                  d={windowArc.halo}
                  fill="url(#schedule-cycle-halo-fade)"
                  filter="url(#schedule-cycle-halo)"
                />
                <path
                  className="dial-window"
                  d={windowArc.track}
                  fill="url(#schedule-cycle-fade)"
                />
                {/* No radial lead tick: a bright bar square across the band
                    reads as a hard cut. The gradient marks the certain start
                    instead: full weight at the start, gone by the end. */}
              </g>
            )}

            {runArcs.map(({ segment, d }) => (
              <path
                key={segment.key}
                data-testid="plan-run"
                data-kind={segment.kind}
                className={[
                  "dial-run",
                  segment.kind,
                  segment.running ? "running" : "",
                  segment.onWake ? "wake" : "",
                ].filter(Boolean).join(" ")}
                d={d}
              />
            ))}

            {labels.map((label) => (
              <text
                key={label.key}
                className={`dial-label ${label.tone}`}
                x={label.x}
                y={label.y}
                textAnchor={label.anchor}
              >
                <tspan className="dial-label-time">{label.time}</tspan>
                <tspan className="dial-label-who" dx="5">{label.who}</tspan>
              </text>
            ))}

          </svg>
          <figcaption className="schedule-visually-hidden">{summary}</figcaption>
        </figure>

        {hub && (
          <div className="schedule-clock-center" aria-hidden="true">
            <span>{hub.title}</span>
            {hub.time ? (
              <strong>{hub.time}</strong>
            ) : (
              <strong className="due">{hub.status}</strong>
            )}
            <small>{hub.subject}</small>
            {hub.relative && <small className="relative">{hub.relative}</small>}
          </div>
        )}

        <div className="schedule-drag-layer" role="group" aria-label={settingsChronographDialDraggableScheduleMarks()}>
          {/* The plan's runs are the marks under the plan: drag one
              to move it, click it for its numbers and exact time. */}
          {(plan?.segments ?? []).map((segment) => {
            const radius = segment.kind === "full" ? R_REC : R_DISC;
            const [x, y] = dialPoint(segment.startMinute, radius);
            const time = formatMinute(segment.startMinute);
            const name = segment.running
              ? settingsChronographDialScanRunning({ kind: segment.kind, time })
              : settingsChronographDialMovePlannedScan({ kind: segment.kind, start: segment.onWake ? "wake" : "clock", time });
            return (
              <button
                key={segment.key}
                type="button"
                ref={(node) => {
                  if (node) planDrag.anchors.set(segment.key, node);
                  else planDrag.anchors.delete(segment.key);
                }}
                className={[
                  "schedule-drag-handle plan-handle",
                  segment.kind === "full" ? "reconcile" : "discovery",
                  segment.running ? "running" : "",
                ].filter(Boolean).join(" ")}
                style={{ left: `${(x / SIZE) * 100}%`, top: `${(y / SIZE) * 100}%` }}
                aria-label={name}
                aria-expanded={inspectedRun === segment.key}
                title={name}
                disabled={planDrag.saving}
                onPointerDown={(pointer) => planDrag.start(pointer, segment)}
                onPointerMove={(pointer) => planDrag.move(pointer, segment)}
                onPointerUp={(pointer) => planDrag.finish(pointer, segment)}
                onPointerCancel={planDrag.cancel}
                onClick={() => {
                  if (planDrag.consumeClickAfterDrag()) return;
                  onOpenRun(segment);
                }}
                data-movable={movable(segment) || undefined}
              />
            );
          })}
          {marks.map((mark) => {
            const lead = leadEvent(mark.events, bindings);
            const event = lead ?? mark.events[0];
            const binding = bindings.get(event.bindingId);
            if (!binding) return null;
            const minute = markMinute(mark);
            const [x, y] = dialPoint(minute, mark.radius);
            const stacked = mark.events.length > 1;
            // A stack is locked only when nothing in it can move.
            const reason = lead ? null : editableReason(event, binding);
            const time = formatMinute(minute);
            const stack = stackText(mark.events.length, mark.mode, plan !== null);
            const state = mark.overdue ? "overdue" : "scheduled";
            const name = !stacked
              ? settingsChronographDialMoveCompany({ company: companyName(event.company), scan: modeLabel(event.mode, plan !== null), time })
              : lead
                ? settingsChronographDialStackMovable({ stack, state, time, company: companyName(lead.company) })
                : settingsChronographDialStackLocked({ stack, state, time });
            return (
              <button
                key={mark.key}
                type="button"
                ref={(node) => {
                  if (node) drag.anchors.set(mark.key, node);
                  else drag.anchors.delete(mark.key);
                }}
                className={[
                  "schedule-drag-handle",
                  mark.mode,
                  stacked ? "cluster" : "",
                  mark.parked ? "parked" : "",
                  mark.overdue ? "overdue" : "",
                  reason ? "locked" : "",
                ].filter(Boolean).join(" ")}
                style={{ left: `${(x / SIZE) * 100}%`, top: `${(y / SIZE) * 100}%` }}
                aria-label={mark.parked
                  ? settingsChronographDialStillAt({ stack, time })
                  : name}
                // Every mark opens the inspector, so every mark says whether it
                // is open; the dial's "in hand" ring is keyed on this.
                aria-expanded={inspected === mark.key}
                title={reason ?? name}
                disabled={drag.saving || mark.parked}
                onPointerDown={(pointer) => drag.start(pointer, mark)}
                onPointerMove={(pointer) => drag.move(pointer, mark)}
                onPointerUp={(pointer) => drag.finish(pointer, mark)}
                onPointerCancel={drag.cancel}
                onClick={() => {
                  // A drag ends in a click. One of them is the gesture; the
                  // other must not also open the inspector.
                  if (drag.consumeClickAfterDrag()) return;
                  onOpen(mark);
                }}
              >
                {stacked && <b>{mark.events.length}</b>}
              </button>
            );
          })}
        </div>
      </div>

      <div className="schedule-clock-legend" role="group" aria-label={settingsChronographDialScheduleClockLegend()}>
        {plan ? (
          <>
            <span><i className="reconcile" />{settingsChronographDialFullScan()}</span>
            <span><i className="discovery" />{settingsChronographDialQuickScan()}</span>
            {/* A machine that is on all day has no off hours to key. */}
            {plan.off && plan.off.length > 0 && <span><i className="off" />{settingsChronographDialUsuallyOff()}</span>}
            {marks.length > 0 && <span><i className="pinned" />{settingsChronographDialATimeYouSet()}</span>}
          </>
        ) : (
          <>
            <span><i className="reconcile" />{settingsChronographDialReconciliationOrbit()}</span>
            <span><i className="discovery" />{settingsChronographDialDiscoveryOrbit()}</span>
            {/* No key for a band that is not on the dial. */}
            {windowArc && <span><i className="window" />{settingsChronographDialAuthoritativeCycle()}</span>}
          </>
        )}
      </div>
    </>
  );
}
