import type { ScheduleBinding, SyncSchedule } from "../../api";
import { companyName } from "../../format";
import { Badge, Popover } from "../../ui";
import { minuteOf } from "./charts/dial";
import type { DialMark } from "./charts/dial";
import { editableReason, formatMinute, leadEvent, modeLabel } from "./charts/schedule";
import { InspectorTime } from "./InspectorTime";
import type { DialDrag } from "./useDialDrag";
import {
  settingsChronographInspectorClosesRoles,
  settingsChronographInspectorDueNow,
  settingsChronographInspectorEvery,
  settingsChronographInspectorHeldUntil,
  settingsChronographInspectorLocked,
  settingsChronographInspectorNo,
  settingsChronographInspectorNoCadence,
  settingsChronographInspectorPass,
  settingsChronographInspectorRunsAt,
  settingsChronographInspectorScanScheduleInspector,
  settingsChronographInspectorScheduled,
  settingsChronographInspectorShare,
  settingsChronographInspectorStackLocked,
  settingsChronographInspectorStackMovable,
  settingsChronographInspectorTime,
  settingsPlanRunInspectorYes,
} from "../../copy/gen/settings";

/* The mark inspector: one mark's worth of schedule, with an editable time per
   connector.

   Every mark opens this same panel. For a stack that means the combined view
   of all its companies rather than scattering them onto the dial and losing
   the fact that they shared one tick — which is why it takes a DialMark and
   not an event. */

interface Props {
  /** The mark being inspected, or null when the panel is closed. */
  mark: DialMark | null;
  schedule: SyncSchedule;
  bindings: Map<number, ScheduleBinding>;
  markMinute: (mark: DialMark) => number;
  drag: DialDrag;
  onClose: () => void;
}

export function ChronographInspector({ mark, schedule, bindings, markMinute, drag, onClose }: Props) {
  const lead = mark ? leadEvent(mark.events, bindings) : null;
  return (
      <Popover
        isOpen={mark !== null}
        // The ring is the dial's statement that this mark is the one in hand,
        // so it has to end when the inspector does.
        onClose={onClose}
        anchor={mark ? drag.anchors.get(mark.key) ?? null : null}
        label={settingsChronographInspectorScanScheduleInspector()}
        className="schedule-inspector app-overlay"
      >
        {mark && mark.events.length > 1 && (
          <header className="schedule-inspector-stack">
            <strong>
              {settingsChronographInspectorShare({ count: mark.events.length, time: formatMinute(markMinute(mark)) })}
            </strong>
            <span>
              {lead
                ? settingsChronographInspectorStackMovable({ company: companyName(lead.company) })
                : settingsChronographInspectorStackLocked()}
            </span>
          </header>
        )}
        {mark?.events.map((event) => {
          const open = mark;
          const binding = bindings.get(event.bindingId);
          if (!binding) return null;
          const reason = editableReason(event, binding);
          const otherMode = event.mode === "discovery" ? "reconcile" : "discovery";
          const other = event.mode === "discovery"
            ? binding.next_reconcile_at
            : binding.discovery_enabled ? binding.next_discovery_at : null;
          const cadence = event.mode === "discovery"
            ? binding.discovery_cadence_seconds
            : binding.reconcile_cadence_seconds;
          return (
            <article key={event.id} className="schedule-inspector-row">
              <header>
                <strong>{companyName(event.company)}</strong>
                {event.overdue ? (
                  <Badge tone="warning" variant="soft" size="sm">{settingsChronographInspectorDueNow()}</Badge>
                ) : (
                  <Badge tone="success" variant="soft" size="sm">{settingsChronographInspectorScheduled()}</Badge>
                )}
              </header>
              <dl>
                <dt>{settingsChronographInspectorPass({ mode: event.mode })}</dt>
                <dd>
                  {!cadence
                    ? settingsChronographInspectorNoCadence()
                    : cadence % 86_400 === 0
                      ? settingsChronographInspectorEvery({ unit: "day", count: cadence / 86_400 })
                      : settingsChronographInspectorEvery({ unit: "hour", count: cadence / 3_600 })}
                </dd>
                {event.mode === "reconcile" && (
                  <>
                    <dt>{settingsChronographInspectorClosesRoles()}</dt>
                    <dd>{binding.closure_capability === "authoritative" ? settingsPlanRunInspectorYes() : settingsChronographInspectorNo()}</dd>
                  </>
                )}
                {other && (
                  <>
                    <dt>{settingsChronographInspectorPass({ mode: otherMode })}</dt>
                    <dd>{formatMinute(minuteOf(other))}</dd>
                  </>
                )}
                {event.effectiveAt && event.effectiveAt !== event.at && (
                  <>
                    <dt>{settingsChronographInspectorHeldUntil()}</dt>
                    <dd className="warn">{formatMinute(minuteOf(event.effectiveAt))}</dd>
                  </>
                )}
              </dl>
              <label className="schedule-inspector-time">
                <span>{reason ?? settingsChronographInspectorRunsAt()}</span>
                <InspectorTime
                  label={settingsChronographInspectorTime({ company: companyName(event.company), scan: modeLabel(event.mode, schedule.plan.enabled) })}
                  step={schedule.tick_seconds}
                  minute={drag.draft?.key === open.key && open.events.length === 1
                    ? drag.draft.minute
                    : minuteOf(event.at)}
                  locked={Boolean(reason)}
                  saving={drag.saving}
                  onCommit={(minute) => drag.persist(event, minute)}
                />
                {reason && <Badge tone="warning" variant="soft" size="sm">{settingsChronographInspectorLocked()}</Badge>}
              </label>
            </article>
          );
        })}
      </Popover>
  );
}
