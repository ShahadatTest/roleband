import {
  jobsDismissedAria,
  jobsNotForMeJustNow,
} from "../../copy/gen/jobs";
import { commonUndo } from "../../copy/gen/common";
import { sharedNotForMe } from "../../copy/gen/shared";
import { RefObject } from "react";
import { Job } from "../../api";
import { Button } from "../../ui/Button";
import { Icon } from "../../ui/Icon";
import { MarginBeacon, RevealRole } from "./MarginBeacon";

/* The way-back beacon: level with the seam a dismissed row left (the list
 * renders a zero-height `.job-seam[data-seam-for]` where the row was), for
 * DISMISS_TTL_MS or until Undo. Undo is for an accident, and an accident is
 * singular, so the pill IS the undo — one click, no reveal to reach first. The
 * reveal names the role so the reader can confirm it was the wrong one, and
 * carries Undo for where there is no hover (tap opens the reveal; keyboard
 * reaches it with ArrowDown). It offers no employer-vocabulary exclusion: a
 * standing rule is a decision made on review, in the Not-for-me lens, not in
 * the seconds after a click.
 */
export interface Dismissal {
  job: Job;
}

export function DismissBeacon({
  host,
  anchorVersion,
  dismissal,
  onUndo,
  dockSlot,
}: {
  host: RefObject<HTMLElement | null>;
  anchorVersion?: unknown;
  dismissal: Dismissal;
  onUndo: (job: Job) => void;
  dockSlot?: number;
}) {
  const { job } = dismissal;
  return (
    <MarginBeacon
      host={host}
      anchorSelector={`.job-seam[data-seam-for="${job.id}"]`}
      anchorVersion={anchorVersion}
      dockSlot={dockSlot}
      variant="way-back"
      label={jobsDismissedAria({ title: job.title })}
      pill={<Icon name="undo" size={14} />}
      onActivate={() => onUndo(job)}
      revealLabel={sharedNotForMe()}
      reveal={
        <>
          <div className="job-reveal-kicker">{jobsNotForMeJustNow()}</div>
          <div className="job-reveal-row">
            <RevealRole job={job} struck />
          </div>
          <div className="job-reveal-foot">
            <Button className="ui-btn-strong" onClick={() => onUndo(job)}>
              {commonUndo()}
            </Button>
          </div>
        </>
      }
    />
  );
}
