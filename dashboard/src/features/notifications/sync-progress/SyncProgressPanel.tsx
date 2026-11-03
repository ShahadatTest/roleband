import { number as copyNumber } from "../../../copy/format";
import { SyncStream } from "./SyncStream";
import { SyncContributionBar, SyncFooterCounts } from "./SyncContribution";
import { PHASE_LABEL, type SyncProgress, isRunComplete, useSyncClock } from "./model";
import "./sync-progress.css";
import {
  notificationsSyncProgressPanelCompaniesScanned,
  notificationsSyncProgressPanelNothingIsWrittenToThe,
  notificationsSyncProgressPanelOf,
  notificationsSyncProgressPanelPending,
  notificationsSyncProgressPanelRecorded,
  notificationsSyncProgressPanelRolesFound,
  notificationsSyncProgressPanelScanProgress,
  notificationsSyncProgressPanelSourcesFailedSeeTheRun,
  notificationsSyncProgressPanelStillScraping,
} from "../../../copy/gen/notifications";
import { Msg } from "../../../ui/Msg";

/**
 * Live sync progress: the expanded panel for a running scrape.
 *
 * The composition root for the roster views. Everything it renders with — the
 * parsed snapshot, the clock, the completion predicates — is `./model`.
 */
function Stat({ label, value, hint }: { label: string; value: number; hint?: string }) {
  return (
    <div className="sync-stat">
      <span className="sync-stat-value">{copyNumber(value)}</span>
      <span className="sync-stat-label">{label}</span>
      {hint && <span className="sync-stat-hint">{hint}</span>}
    </div>
  );
}

export function SyncProgressPanel({ progress: p }: { progress: SyncProgress }) {
  // Stop the clock once nothing is outstanding: a completed run keeps its row in
  // `running`, and ticking on forever would be a lie about work in progress.
  const live = p.phase !== "finishing" && !isRunComplete(p);
  const clock = useSyncClock(p.snapshotAtMs, live);
  const hasRoster = p.companies.length > 0;

  return (
    <div className="sync-progress" data-phase={p.phase}>
      <div className="sync-progress-head">
        <span className="sync-phase">{PHASE_LABEL[p.phase]}</span>
        <span className="sync-percent">{p.percent}%</span>
      </div>

      <div
        className="sync-bar"
        role="progressbar"
        aria-valuenow={p.percent}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label={notificationsSyncProgressPanelScanProgress({ pHASE_LABEL: String(PHASE_LABEL[p.phase]) })}
      >
        <div className="sync-bar-fill" style={{ width: `${p.percent}%` }} />
      </div>

      {hasRoster ? (
        // No aggregate tiles here: the roster states every one of them a second
        // time. Sources scanned and found are already in the row summary directly
        // above; scraping is the stream, which also names the sources; recorded
        // and pending are the two volumes in the tank.
        <>
          <SyncStream progress={p} clock={clock} />
          <SyncContributionBar companies={p.companies} />
          <SyncFooterCounts progress={p} />
        </>
      ) : (
        <>
          <div className="sync-stats">
            <Stat
              label={notificationsSyncProgressPanelCompaniesScanned()}
              value={p.companiesCollected}
              hint={notificationsSyncProgressPanelOf({ companiesTotal: p.companiesTotal })}
            />
            <Stat label={notificationsSyncProgressPanelStillScraping()} value={p.companiesScraping} />
            <Stat label={notificationsSyncProgressPanelRolesFound()} value={p.opportunitiesDetected} />
            <Stat
              label={notificationsSyncProgressPanelRecorded()}
              value={p.opportunitiesRecorded}
              hint={p.opportunitiesPending > 0 ? notificationsSyncProgressPanelPending({ opportunitiesPending: p.opportunitiesPending }) : undefined}
            />
          </div>
          {p.companiesFailed > 0 && (
            <p className="sync-progress-note warn">
              <Msg of={notificationsSyncProgressPanelSourcesFailedSeeTheRun} args={{ count: p.companiesFailed }} elems={{ companiesFailed: p.companiesFailed }} />
            </p>
          )}
          {p.phase === "collecting" && (
            <p className="sync-progress-note">
              {notificationsSyncProgressPanelNothingIsWrittenToThe()}
            </p>
          )}
        </>
      )}
    </div>
  );
}
