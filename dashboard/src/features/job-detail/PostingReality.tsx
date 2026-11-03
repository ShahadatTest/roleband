import type { JobDetail } from "../../api";
import { STANDING_HEDGE, STANDING_TITLE, isStanding, standingSigns } from "../../patterns/jobs/JobBadges";
import {
  rolePostingRealityOfSigns,
} from "../../copy/gen/role";
import { Msg } from "../../ui/Msg";

/** "May be an always-open posting": shown only when the server's verdict is
 *  `possible` (two of three signs). A posting with fewer signs, or a closed
 *  one, shows nothing: there is nothing worth saying about it. `undefined`
 *  too: the screen renders a list row before its detail arrives. */
export function PostingReality({ reality }: { reality: JobDetail["posting_reality"] | undefined }) {
  if (!isStanding(reality)) return null;
  return (
    <section aria-label={STANDING_TITLE()}>
      <div className="section-title">{STANDING_TITLE()}</div>
      <ul className="jd-advisory-rationale">
        {standingSigns(reality).map((line) => (
          <li key={line}>{line}</li>
        ))}
      </ul>
      <div className="jd-advisory-meta">
        <Msg of={rolePostingRealityOfSigns} elems={{ length: reality.met.length, criteria_total: reality.criteria_total, sTANDING_HEDGE: STANDING_HEDGE() }} />
      </div>
    </section>
  );
}
