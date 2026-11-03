import { number as copyNumber } from "../../copy/format";
import type { SchedulePlan } from "../../api";
import { Badge, Button, Popover, Segmented } from "../../ui";
import { durationText, kindLabel } from "./charts/plan";
import type { PlanSegment } from "./charts/plan";
import { formatMinute } from "./charts/schedule";
import { InspectorTime } from "./InspectorTime";
import { movable, readyByForStart, startForReadyBy } from "./usePlanDrag";
import type { PlanDrag } from "./usePlanDrag";
import {
  settingsChronographInspectorClosesRoles,
  settingsPlanRunInspectorAQuickScanEveryHours,
  settingsPlanRunInspectorCompanies,
  settingsPlanRunInspectorCountFromTheLastScan,
  settingsPlanRunInspectorEvery,
  settingsPlanRunInspectorFullScanBackToYour,
  settingsPlanRunInspectorFullScanDoneBy,
  settingsPlanRunInspectorFullTime,
  settingsPlanRunInspectorItAlsoRunsWhenYou,
  settingsPlanRunInspectorPlanned,
  settingsPlanRunInspectorQuickScanEvery,
  settingsPlanRunInspectorQuickScanTime,
  settingsPlanRunInspectorQuickScansEveryHoursAfter,
  settingsPlanRunInspectorQuickTime,
  settingsPlanRunInspectorRepeats,
  settingsPlanRunInspectorRepeatsEvery,
  settingsPlanRunInspectorScanInspector,
  settingsPlanRunInspectorScanningNow,
  settingsPlanRunInspectorStarts,
  settingsPlanRunInspectorTakes,
  settingsPlanRunInspectorUseMyUsualStart,
  settingsPlanRunInspectorWhenYouTurnItOn,
  settingsPlanRunInspectorYes,
  settingsScheduleHours,
} from "../../copy/gen/settings";

/* What a click on one of the plan's runs opens: the run in numbers,
   and its time to read or type, as a company mark's inspector does. A quick scan's field moves every quick scan (they keep their
   spacing); a full scan's sets when the daily full scan is done by. */

type RepeatHours = 2 | 3 | 6 | 12;

interface Props {
  segment: PlanSegment | null;
  plan: SchedulePlan;
  drag: PlanDrag;
  onClose: () => void;
}

export function PlanRunInspector({ segment, plan, drag, onClose }: Props) {
  const companies = segment?.kind === "full" ? plan.roster : plan.quick_roster;
  const choices = plan.repeat_choices.filter(
    (hours): hours is RepeatHours => [2, 3, 6, 12].includes(hours),
  );
  const readyBy = segment ? readyByForStart(segment.startMinute, segment.seconds) : 0;
  return (
    <Popover
      isOpen={segment !== null}
      onClose={onClose}
      anchor={segment ? drag.anchors.get(segment.key) ?? null : null}
      label={settingsPlanRunInspectorScanInspector()}
      className="schedule-inspector app-overlay"
    >
      {segment && (
        <article className="schedule-inspector-row">
          <header>
            <strong>{kindLabel(segment.kind)}</strong>
            {segment.running ? (
              <Badge tone="accent" variant="soft" size="sm">{settingsPlanRunInspectorScanningNow()}</Badge>
            ) : segment.onWake ? (
              <Badge tone="neutral" variant="soft" size="sm">{settingsPlanRunInspectorWhenYouTurnItOn()}</Badge>
            ) : (
              <Badge tone="success" variant="soft" size="sm">{settingsPlanRunInspectorPlanned()}</Badge>
            )}
          </header>
          <dl>
            <dt>{settingsPlanRunInspectorCompanies()}</dt>
            <dd>{copyNumber(companies)}</dd>
            <dt>{settingsPlanRunInspectorTakes()}</dt>
            <dd>{durationText(segment)}</dd>
            {segment.kind === "full" ? (
              <>
                <dt>{settingsPlanRunInspectorStarts()}</dt>
                <dd>{formatMinute(segment.startMinute)}</dd>
                <dt>{settingsChronographInspectorClosesRoles()}</dt>
                <dd>{settingsPlanRunInspectorYes()}</dd>
              </>
            ) : (
              <>
                <dt>{settingsPlanRunInspectorRepeats()}</dt>
                <dd>
                  {settingsPlanRunInspectorRepeatsEvery({
                    anchor: plan.repeat_anchor_minute !== null ? "fixed" : "last",
                    hours: plan.repeat_hours,
                  })}
                </dd>
              </>
            )}
          </dl>

          {segment.kind === "quick" ? (
            <>
              <label className="schedule-inspector-time">
                <span>{settingsPlanRunInspectorQuickTime({ state: movable(segment) ? "planned" : "running" })}</span>
                <InspectorTime
                  label={settingsPlanRunInspectorQuickScanTime()}
                  minute={segment.startMinute}
                  step={600}
                  locked={!movable(segment)}
                  saving={drag.saving}
                  onCommit={(minute) => void drag.place(segment, minute)}
                />
              </label>
              <div className="schedule-inspector-repeat">
                <span>{settingsPlanRunInspectorEvery()}</span>
                <Segmented
                  label={settingsPlanRunInspectorQuickScanEvery()}
                  value={String(plan.repeat_hours)}
                  options={choices.map((hours) => ({
                    value: String(hours), label: settingsScheduleHours({ hours }), disabled: drag.saving,
                  }))}
                  onChange={(value) => void drag.save(
                    { repeat_hours: Number(value) as RepeatHours },
                    settingsPlanRunInspectorAQuickScanEveryHours({ hours: Number(value) }),
                  )}
                />
              </div>
              {plan.repeat_anchor_minute !== null && (
                <Button
                  variant="link"
                  disabled={drag.saving}
                  onClick={() => void drag.save(
                    { repeat_anchor_minute: null },
                    settingsPlanRunInspectorQuickScansEveryHoursAfter({ repeat_hours: plan.repeat_hours }),
                  )}
                >
                  {settingsPlanRunInspectorCountFromTheLastScan()}
                </Button>
              )}
            </>
          ) : (
            <>
              <label className="schedule-inspector-time">
                <span>{settingsPlanRunInspectorFullTime({ state: movable(segment) ? "planned" : "running" })}</span>
                <InspectorTime
                  label={settingsPlanRunInspectorFullScanDoneBy()}
                  minute={movable(segment) ? readyBy : segment.startMinute}
                  step={600}
                  locked={!movable(segment)}
                  saving={drag.saving}
                  onCommit={(minute) => void drag.place(segment, startForReadyBy(minute, segment.seconds))}
                />
              </label>
              {plan.ready_by_minute !== null && movable(segment) && (
                <Button
                  variant="link"
                  disabled={drag.saving}
                  onClick={() => void drag.save({ ready_by_minute: null }, settingsPlanRunInspectorFullScanBackToYour())}
                >
                  {settingsPlanRunInspectorUseMyUsualStart()}
                </Button>
              )}
              <p className="schedule-inspector-note">
                {settingsPlanRunInspectorItAlsoRunsWhenYou()}
              </p>
            </>
          )}
          {drag.error && <p className="schedule-plan-error" role="alert">{drag.error}</p>}
        </article>
      )}
    </Popover>
  );
}
