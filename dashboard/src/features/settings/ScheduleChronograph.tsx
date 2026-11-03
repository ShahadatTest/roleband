import { useCallback, useMemo, useState } from "react";
import type { SchedulePlanUpdate, SyncSchedule } from "../../api";
import { companyName } from "../../format";
import { DAY, R_DISC, R_REC, minuteOf, placeLabels } from "./charts/dial";
import type { DialMark } from "./charts/dial";
import { kindLabel, offHours, planSegments, runSubject } from "./charts/plan";
import type { PlanSegment } from "./charts/plan";
import { formatMinute, leadIndexOf } from "./charts/schedule";
import type { ReconciliationWindow, ScheduleCluster } from "./charts/schedule";
import { ChronographDial } from "./ChronographDial";
import type { DialPlan, HubReadout } from "./ChronographDial";
import { ChronographInspector } from "./ChronographInspector";
import { PlanRunInspector } from "./PlanRunInspector";
import { snapMinute, useDialDrag } from "./useDialDrag";
import type { ScheduleMove } from "./useDialDrag";
import { usePlanDrag } from "./usePlanDrag";
import {
  settingsScheduleChronographCompanies,
  settingsScheduleChronographDragAScanToMove,
  settingsScheduleChronographDue,
  settingsScheduleChronographDueNow,
  settingsScheduleChronographHubCompany,
  settingsScheduleChronographHubStack,
  settingsScheduleChronographHubTitle,
  settingsScheduleChronographInHoursMinutes,
  settingsScheduleChronographInMinutes,
  settingsScheduleChronographNextDispatch,
  settingsScheduleChronographNextScan,
  settingsScheduleChronographOnWake,
  settingsScheduleChronographOnWake2,
  settingsScheduleChronographProjectedThrough,
  settingsScheduleChronographSavingSchedule,
  settingsScheduleChronographSince,
  settingsScheduleChronographStackLocked,
  settingsScheduleChronographStackMovable,
  settingsScheduleChronographTheNextScanRunsOnce,
  settingsScheduleChronographWaiting,
  settingsScheduleChronographWaitingStatus,
  settingsScheduleChronographWhenYouTurnItOn,
  settingsScheduleSectionNow,
} from "../../copy/gen/settings";

/* The chronograph: two orbits (outer amber = reconciliation, inner cyan =
   discovery), every mark labeled in place, the authoritative cycle drawn as a
   glowing arc, and a marker inspector for exact edits.

   This file is the composition and nothing else. The four pieces it puts
   together, and why each is its own:
     charts/dial.ts         where a mark and its label GO (pure)
     useDialDrag.ts         what a drag DOES (three refs and one write)
     ChronographDial.tsx    the face and the grabbable marks
     ChronographInspector   one mark's schedule, with an editable time
   What is left here is the bridge: the bindings index, the marks the clusters
   project into, which mark is open, and the readout. */

/* One label for a planned run (its landing time while dragged) and one for a
   company mark, as the dial writes them beside their marks. */
const runLabel = (segment: PlanSegment) => {
  const time = segment.running ? settingsScheduleSectionNow() : formatMinute(segment.landing ?? segment.startMinute);
  const who = segment.onWake ? settingsScheduleChronographOnWake({ kind: segment.kind }) : kindLabel(segment.kind);
  return {
    key: segment.key,
    minute: segment.startMinute,
    ring: segment.kind === "full" ? "outer" as const : "inner" as const,
    time,
    who,
    text: `${time} ${who}`,
    tone: segment.kind === "full" ? "muted" as const : "cyan" as const,
  };
};
const markLabel = (mark: DialMark, minute: number) => {
  const time = formatMinute(minute);
  const name = mark.events.length > 1
    ? settingsScheduleChronographCompanies({ count: mark.events.length })
    : companyName(mark.events[0].company);
  const who = mark.overdue ? settingsScheduleChronographDue({ name: String(name) }) : name;
  return {
    key: mark.key,
    minute,
    ring: mark.mode === "reconcile" ? "outer" as const : "inner" as const,
    time,
    who,
    text: `${time} ${who}`,
    tone: mark.overdue
      ? "warn" as const
      : mark.mode === "reconcile" ? "muted" as const : "cyan" as const,
  };
};

interface Props {
  schedule: SyncSchedule;
  clusters: ScheduleCluster[];
  window: ReconciliationWindow | null;
  summary: string;
  /** A schedule write is out, from any control on the screen: every mark,
      run and inspector field waits for it. */
  busy: boolean;
  onMove: (move: ScheduleMove) => Promise<void>;
  /** Save a change to the schedule plan (a dragged or typed run). */
  onPlan: (update: SchedulePlanUpdate) => Promise<void>;
}

export function ScheduleChronograph({ schedule, clusters, window: cycle, summary, busy, onMove, onPlan }: Props) {
  const [inspectedRun, setInspectedRun] = useState<string | null>(null);
  const [inspected, setInspected] = useState<string | null>(null);

  const bindings = useMemo(
    () => new Map(schedule.bindings.map((binding) => [binding.binding_id, binding])),
    [schedule.bindings],
  );

  const nowMinute = minuteOf(schedule.generated_at);

  const drag = useDialDrag(bindings, onMove, schedule.plan.enabled, busy);
  const planDrag = usePlanDrag(drag.stageRef, onPlan, busy);
  const { draft } = drag;

  const marks = useMemo<DialMark[]>(() => clusters.flatMap((cluster): DialMark[] => {
    const collapsed: DialMark = {
      key: cluster.id,
      clusterId: cluster.id,
      mode: cluster.mode,
      at: cluster.at,
      overdue: cluster.overdue,
      events: cluster.events,
      radius: cluster.mode === "reconcile" ? R_REC : R_DISC,
    };
    const lead = leadIndexOf(cluster.events, bindings);
    const dragging = draft?.key === cluster.id && draft.moved;
    if (!dragging || cluster.events.length < 2 || lead < 0) return [collapsed];
    // Mid-drag the stack splits, so the dial never implies all of it is
    // moving. The lead keeps the cluster's own key — that is the button the
    // pointer is captured on — and the rest stay parked at the shared time.
    return [
      { ...collapsed, events: [cluster.events[lead]] },
      {
        ...collapsed,
        key: `${cluster.id}~parked`,
        events: cluster.events.filter((_, index) => index !== lead),
        parked: true,
      },
    ];
  }), [clusters, bindings, draft]);

  const markMinute = useCallback(
    (mark: DialMark) => (draft?.key === mark.key ? draft.minute : minuteOf(mark.at)),
    [draft],
  );

  // No "+1" here. The dial covers one 24-hour turn, so in steady state almost
  // every deadline falls on the next calendar day — a marker that shows on
  // nearly every label distinguishes nothing, and it reads as a timezone
  // offset next to a clock time. The header already names the zone and date.
  // The schedule plan's runs: a full scan on the outer orbit, a
  // quick scan on the inner, each as long as it takes. Under the per-company
  // timers there is no plan layer.
  const plan = schedule.plan.enabled ? schedule.plan : null;
  // While a run is dragged the dial previews the drop: a quick scan carries
  // every quick scan with it (they keep their spacing), a full scan moves alone.
  const { draft: planDraft } = planDrag;
  const baseSegments = useMemo(
    () => (plan ? planSegments(plan, schedule.generated_at) : []),
    [plan, schedule.generated_at],
  );
  // Which runs a drag carries: a quick scan carries every quick scan (they
  // keep their spacing), a full scan moves alone. A running scan never moves.
  const carried = useMemo(() => {
    if (!planDraft?.moved) return new Set<string>();
    return new Set(baseSegments
      .filter((segment) => (planDraft.kind === "quick"
        ? segment.kind === "quick" && !segment.running
        : segment.key === planDraft.key))
      .map((segment) => segment.key));
  }, [baseSegments, planDraft]);

  // While a run is dragged the dial previews the drop: the arcs follow the
  // pointer exactly (fractional minutes), and each label says the grid time it
  // would land on.
  const dialPlan = useMemo<DialPlan | null>(() => {
    if (!plan) return null;
    const dragged = baseSegments.find((segment) => segment.key === planDraft?.key);
    const landingDelta = planDraft && dragged
      ? ((planDraft.minute - dragged.startMinute) % DAY + DAY) % DAY
      : 0;
    const segments = baseSegments.map((segment) => {
      if (!planDraft || !carried.has(segment.key)) return segment;
      const shift = (minute: number, delta: number) => ((minute + delta) % DAY + DAY) % DAY;
      return {
        ...segment,
        startMinute: shift(segment.startMinute, planDraft.delta),
        endMinute: shift(segment.endMinute, planDraft.delta),
        landing: shift(segment.startMinute, landingDelta),
      };
    });
    return { segments, off: offHours(plan.usual.today) };
  }, [plan, baseSegments, carried, planDraft]);

  // Labels that are not moving keep their places for the whole drag: placing
  // every label again each frame lets the collision pass push them around as
  // the dragged one passes, which reads as the whole dial twitching. Only the
  // moving labels are placed per frame, among themselves.
  const draggingMark = draft?.moved ? draft.key : null;
  const stillLabels = useMemo(() => placeLabels([
    ...baseSegments.filter((segment) => !carried.has(segment.key)).map(runLabel),
    ...marks.filter((mark) => mark.key !== draggingMark && !mark.parked)
      .map((mark) => markLabel(mark, minuteOf(mark.at))),
    ...marks.filter((mark) => mark.parked).map((mark) => markLabel(mark, minuteOf(mark.at))),
  ]), [baseSegments, carried, marks, draggingMark]);
  const movingLabels = placeLabels([
    ...(dialPlan?.segments ?? []).filter((segment) => carried.has(segment.key)).map(runLabel),
    ...marks.filter((mark) => mark.key === draggingMark).map((mark) => {
      const label = markLabel(mark, markMinute(mark));
      const time = formatMinute(snapMinute(markMinute(mark)));
      return { ...label, time, text: `${time} ${label.who}` };
    }),
  ]);
  const labels = [...stillLabels, ...movingLabels];


  const hub = useMemo<HubReadout | null>(() => {
    const relativeText = (at: string) => {
      const minutes = Math.round((Date.parse(at) - Date.parse(schedule.generated_at)) / 60_000);
      if (minutes <= 0) return null;
      return minutes >= 60
        ? settingsScheduleChronographInHoursMinutes({ hours: Math.floor(minutes / 60), minutes: minutes % 60 })
        : settingsScheduleChronographInMinutes({ minutes });
    };
    if (plan) {
      const run = plan.upcoming[0];
      // Why nothing planned runs now, said before what runs next.
      if (plan.waiting) {
        const resumes = plan.paused_until ?? run?.at ?? null;
        return {
          title: settingsScheduleChronographWaiting({ waiting: plan.waiting }),
          time: null,
          status: settingsScheduleChronographWaitingStatus({ waiting: plan.waiting }),
          subject: run ? runSubject(run, plan) : "",
          relative: plan.waiting === "mains"
            ? settingsScheduleChronographTheNextScanRunsOnce()
            : resumes ? settingsScheduleChronographNextScan({ time: formatMinute(minuteOf(resumes)) }) : null,
        };
      }
      if (!run) return null;
      const due = !run.running && Date.parse(run.at) <= Date.parse(schedule.generated_at);
      return {
        title: settingsScheduleChronographHubTitle({ state: run.running ? "running" : "next" }),
        time: run.running || due || run.on_wake ? null : formatMinute(minuteOf(run.at)),
        status: run.running
          ? settingsScheduleChronographSince({ time: formatMinute(minuteOf(run.at)) })
          : due ? settingsScheduleChronographDueNow() : run.on_wake ? settingsScheduleChronographOnWake2() : null,
        subject: runSubject(run, plan),
        relative: run.on_wake
          ? settingsScheduleChronographWhenYouTurnItOn({ time: formatMinute(minuteOf(run.at)) })
          : run.running || due ? null : relativeText(run.at),
      };
    }
    const first = clusters[0] ?? null;
    if (!first) return null;
    const relative = relativeText(first.at);
    const count = first.events.length;
    return {
      title: settingsScheduleChronographNextDispatch(),
      time: relative ? formatMinute(minuteOf(first.at)) : null,
      status: relative ? null : settingsScheduleChronographDueNow(),
      subject: count > 1
        ? settingsScheduleChronographHubStack({ mode: first.mode, count })
        : settingsScheduleChronographHubCompany({ mode: first.mode, company: companyName(first.events[0].company) }),
      relative: relative ?? (cycle ? settingsScheduleChronographProjectedThrough({ time: formatMinute(minuteOf(cycle.end)) }) : null),
    };
  }, [plan, clusters, cycle, schedule.generated_at]);


  // Every mark opens the same inspector. For a stack that means the combined
  // view of all its companies — each with its own editable time — rather than
  // scattering them onto the dial and losing the fact that they shared one.
  const openMark = (mark: DialMark) => {
    if (mark.parked) return;
    setInspected(mark.key);
    if (mark.events.length < 2) return;
    const lead = leadIndexOf(mark.events, bindings);
    const count = mark.events.length;
    const time = formatMinute(markMinute(mark));
    drag.setNotice(lead >= 0
      ? settingsScheduleChronographStackMovable({ count, time, company: companyName(mark.events[lead].company) })
      : settingsScheduleChronographStackLocked({ count, time }));
  };

  const inspectedMark = marks.find((mark) => mark.key === inspected) ?? null;

  return (
    <div className="schedule-clock-main" data-selection="chrome">
      <ChronographDial
        marks={marks}
        labels={labels}
        cycle={cycle}
        summary={summary}
        bindings={bindings}
        markMinute={markMinute}
        hub={hub}
        plan={dialPlan}
        planDrag={planDrag}
        inspectedRun={inspectedRun}
        onOpenRun={(segment) => setInspectedRun(segment.key)}
        nowMinute={nowMinute}
        inspected={inspected}
        drag={drag}
        onOpen={openMark}
      />

      <div className="schedule-clock-readout" role="status" aria-live="polite">
        {/* The drag hint is about company marks; under the plan a dial with
            no pinned company has none to drag, so it says nothing. */}
        {busy
          ? settingsScheduleChronographSavingSchedule()
          : planDrag.notice
            ?? (marks.length > 0
              ? drag.notice
              : (dialPlan?.segments.length ?? 0) > 0
                ? settingsScheduleChronographDragAScanToMove()
                : null)}
      </div>
      {drag.error && <div className="schedule-clock-error" role="alert">{drag.error}</div>}
      {planDrag.error && inspectedRun === null && (
        <div className="schedule-clock-error" role="alert">{planDrag.error}</div>
      )}

      {plan && (
        <PlanRunInspector
          segment={dialPlan?.segments.find((segment) => segment.key === inspectedRun) ?? null}
          plan={plan}
          drag={planDrag}
          onClose={() => setInspectedRun(null)}
        />
      )}

      <ChronographInspector
        mark={inspectedMark}
        schedule={schedule}
        bindings={bindings}
        markMinute={markMinute}
        drag={drag}
        // The ring is the dial's statement that this mark is the one in hand,
        // so it has to end when the inspector does.
        onClose={() => {
          setInspected(null);
        }}
      />
    </div>
  );
}
