import {
  jobsClear,
  jobsCompareBeaconAria,
  jobsCompareBeaconAriaFull,
  jobsCompareFullPill,
  jobsCompareNotSaved,
  jobsCompareRemove,
  jobsInCompare,
  jobsInCompareCount,
} from "../../copy/gen/jobs";
import {
  commonUndo,
} from "../../copy/gen/common";
import {
  shellCompareCleared,
  shellPaletteCompare,
} from "../../copy/gen/shell";
import { RefObject, useEffect, useState } from "react";
import { Job, api, isNotFound } from "../../api";
import { useJobActions, useJobWorkspace } from "../../context/JobWorkspace";
import { useReferenceVersion } from "../../context/SyncState";
import { Button } from "../../ui/Button";
import { Icon } from "../../ui/Icon";
import { useToast } from "../../ui/Toast";
import { MarginBeacon, RevealRole } from "./MarginBeacon";

/* The standing beacon: from two selected roles until Compare or Clear. It
 * is level with the row selected LAST (the selection is a Set, which keeps
 * insertion order) and moves with each new one; when that row is not on the
 * page it docks. The pill carries the count; at the cap it says "full",
 * which is the reason every other row's compare toggle is disabled. Click
 * goes to Compare. The reveal is the roster — each role can be taken out —
 * with the same one next step as its primary, and Clear with its way back.
 */

const cache = new Map<number, Job>();
/** The source switch the cached roles were read under (`referenceVersion`): a
 *  switch since means their pay is the old source's, so they are read again.
 * Module-level like the cache, since the cache outlives the
 *  beacon: a switch made in Settings must not leave the old figures here. */
let cachedUnder = 0;

/** The selected roles, fetched once each and cached.
 *
 * `onGone` carries the ids the server says do not exist. The pill's count comes
 * from the selection and its rows come from this roster, so an id that outlives
 * its job would make the two disagree ("3 in compare" over two rows). Only a
 * 404 counts: a failed request is not evidence a role is gone, and evicting on
 * one would delete the user's selection because the API hiccuped.
 */
function useRoster(ids: number[], onGone: (ids: number[]) => void): Job[] {
  // Keyed on the ids' VALUE: a fresh array each render must not refetch.
  const key = ids.join(",");
  const [, bump] = useState(0);
  const version = useReferenceVersion();
  useEffect(() => {
    let live = true;
    if (version !== cachedUnder) {
      cache.clear();
      cachedUnder = version;
    }
    const wanted = key ? key.split(",").map(Number) : [];
    const missing = wanted.filter((id) => !cache.has(id));
    if (missing.length === 0) return;
    Promise.all(
      missing.map((id) =>
        api
          .job(id)
          .then((job) => {
            cache.set(id, job);
            return null;
          })
          .catch((error: unknown) => (isNotFound(error) ? id : null)),
      ),
    ).then((results) => {
      if (!live) return;
      const gone = results.filter((id): id is number => id !== null);
      if (gone.length > 0) onGone(gone);
      bump((n) => n + 1);
    });
    return () => {
      live = false;
    };
  }, [key, onGone, version]);
  return ids.map((id) => cache.get(id)).filter((job): job is Job => job !== undefined);
}

export function CompareBeacon({
  host,
  anchorVersion,
}: {
  host: RefObject<HTMLElement | null>;
  anchorVersion?: unknown;
}) {
  const { compareIds, compareSyncFailed, compareCap } = useJobWorkspace();
  const { toggleCompare, clearCompare, setCompare, dropCompare, openCompare } = useJobActions();
  const { toast } = useToast();
  const ids = [...compareIds];
  const count = ids.length;
  const last = ids[ids.length - 1];
  const roster = useRoster(count >= 2 ? ids : [], dropCompare);
  const full = count >= compareCap;

  const clear = () => {
    const kept = [...ids];
    clearCompare();
    toast({
      key: "compare",
      text: shellCompareCleared({ count: kept.length }),
      action: { label: commonUndo(), onClick: () => setCompare(kept) },
    });
  };

  return (
    <MarginBeacon
      present={count >= 2}
      host={host}
      anchorSelector={`[data-job-id="${last}"]`}
      anchorVersion={anchorVersion}
      variant="standing"
      label={(full ? jobsCompareBeaconAriaFull : jobsCompareBeaconAria)({ count })}
      pill={
        <>
          <Icon name="columns" size={14} />
          <span className="ui-beacon-count">{count}</span>
          {full && <span>{jobsCompareFullPill()}</span>}
        </>
      }
      onActivate={openCompare}
      revealLabel={jobsInCompare()}
      reveal={
        <>
          <div className="job-reveal-kicker">
            {jobsInCompareCount({ count, cap: compareCap })}
          </div>
          {/* The selection is durable, so when a write did not land the roster
              on screen is not what a reload would bring back. Said here rather
              than in a toast: this panel IS the account of the selection. */}
          {compareSyncFailed && (
            <div className="job-reveal-kicker" role="status">
              {jobsCompareNotSaved()}
            </div>
          )}
          <ul className="job-reveal-list">
            {roster.map((job) => (
              <li className="job-reveal-row" key={job.id}>
                <RevealRole
                  job={job}
                  control={
                    <Button
                      variant="icon"
                      size="sm"
                      aria-label={jobsCompareRemove({ title: job.title })}
                      onClick={() => toggleCompare(job.id)}
                    >
                      <Icon name="close" size={14} />
                    </Button>
                  }
                />
              </li>
            ))}
          </ul>
          <div className="job-reveal-foot">
            <Button variant="primary" onClick={openCompare}>
              {shellPaletteCompare({ count })} <Icon name="arrowRight" size={13} />
            </Button>
            <span className="job-reveal-spacer" />
            <Button variant="link" onClick={clear}>
              {jobsClear()}
            </Button>
          </div>
        </>
      }
    />
  );
}
