import { number as copyNumber } from "../../../copy/format";
import { companyName } from "../../../format";
import { useMediaQuery } from "../../../hooks/useMediaQuery";
import { fmtElapsed, isRunComplete, isSyncStale, type SyncClock, type SyncCompany, type SyncProgress } from "./model";
import {
  notificationsSyncStreamEverySourceRecorded,
  notificationsSyncStreamHeld,
  notificationsSyncStreamInMemory,
  notificationsSyncStreamNoUpdateForThisRun,
  notificationsSyncStreamOnDisk,
  notificationsSyncStreamOpportunitiesHeldInMemoryWritten,
  notificationsSyncStreamPath,
  notificationsSyncStreamRunningPostPasses,
  notificationsSyncStreamScrapingNow,
  notificationsSyncStreamWaitingOnTheFirstSource,
  notificationsSyncStreamWritingCollectedSourcesToThe,
} from "../../../copy/gen/notifications";
import { Msg } from "../../../ui/Msg";

/**
 * The live panel's first block: only the sources genuinely in flight.
 *
 * The collector semaphore is held per *backend*, and a backend drains its own
 * companies serially, so the in-flight set is bounded by
 * `min(concurrency_limit, backends with work left)`: a handful, permanently,
 * however many companies are tracked. That bound is what lets this block name
 * every source it shows and stay the same size on a 2-company account and a
 * 100-company one.
 *
 * The tank is the point of the whole component. Collection writes nothing to the
 * database, so "recorded 0" is correct and alarming for most of a run; showing
 * the two volumes side by side says why better than a sentence could.
 */

const WIDTH = 1200;
const ROW_GAP = 50;
/** Where each source's channel begins. */
const SPOUT_X = 222;
/** Right edge of the label column; names and clocks are right-aligned to it. */
const LABEL_X = 210;
/** Every channel converges here, at the tank mouth. */
const CONVERGE_X = 975;
const TANK_X = 990;
const TANK_W = 130;
const TANK_PAD = 40;
const MIN_HEIGHT = 200;

/** Sources with a clock running. Persist is serial, so it contributes at most one. */
export function inFlight(companies: SyncCompany[], limit: number): SyncCompany[] {
  return companies
    .filter((c) => c.state === "scraping" || c.state === "persisting")
    .sort((a, b) => (a.sinceMs ?? 0) - (b.sinceMs ?? 0))
    .slice(0, Math.max(1, limit));
}

function elapsedFor(company: SyncCompany, clock: SyncClock): number | null {
  if (company.sinceMs == null) return null;
  return Math.max(0, clock.nowMs + clock.skewMs - company.sinceMs);
}

function idleLabel(progress: SyncProgress, complete: boolean): string {
  if (complete) return notificationsSyncStreamEverySourceRecorded();
  if (progress.phase === "persisting") return notificationsSyncStreamWritingCollectedSourcesToThe();
  if (progress.phase === "finishing") return notificationsSyncStreamRunningPostPasses();
  return notificationsSyncStreamWaitingOnTheFirstSource({ choice: (progress.companiesQueued > 0) ? "yes" : "no", companiesQueued: (progress.companiesQueued > 0) ? progress.companiesQueued : "" });
}

/** Channel from one source into the tank mouth: flat at the source, then bending in. */
function channelPath(y: number, centerY: number): string {
  return `M ${SPOUT_X},${y} C ${SPOUT_X + 230},${y} ${CONVERGE_X - 260},${centerY} ${CONVERGE_X},${centerY}`;
}

export function SyncStream({ progress, clock }: { progress: SyncProgress; clock: SyncClock }) {
  const reduced = useMediaQuery("(prefers-reduced-motion: reduce)");
  const rows = inFlight(progress.companies, progress.concurrencyLimit);
  const complete = isRunComplete(progress);
  const stale = isSyncStale(clock, complete);
  const flowing = !reduced && !stale && rows.length > 0;

  // Size to the sources actually running. A fixed five-row box would sit mostly
  // empty for most of a run, since backends drain and the in-flight set shrinks.
  const height = Math.max(rows.length * ROW_GAP + 70, MIN_HEIGHT);
  const centerY = height / 2;
  const rowY = (index: number) => centerY + (index - (rows.length - 1) / 2) * ROW_GAP;

  const tankY = TANK_PAD;
  const tankH = height - TANK_PAD * 2;

  // Both volumes come from clamped aggregates: closure reconciliation can commit
  // more rows than this run detected, and `detected - recorded` would then draw
  // a negative band.
  const held = progress.opportunitiesPending;
  const written = progress.opportunitiesRecorded;
  const scale = Math.max(1, held + written);
  const bandH = Math.round((tankH - 2) * (written / scale));
  // The band grows from empty to the full tank, so no fixed label position is
  // safely on one surface or the other. Every readout inside the tank picks its
  // fill from what is actually behind it rather than assuming.
  const bandTop = tankY + tankH - 1 - bandH;
  const onBand = (y: number) => (bandH > 0 && y - 4 >= bandTop ? " on-band" : "");
  // Pinned to the tank floor rather than centred in the band: a band tall enough
  // to centre in is also tall enough to reach the held readout and collide with it.
  const diskLabelY = tankY + tankH - 14;

  const summary = notificationsSyncStreamOpportunitiesHeldInMemoryWritten({ choice: (rows.length) ? "yes" : "no", join: (rows.length) ? String(rows
        .map((c) => {
          const ms = elapsedFor(c, clock);
          return ms == null ? companyName(c.slug) : `${companyName(c.slug)} ${fmtElapsed(ms)}`;
        })
        .join(", ")) : "", held, written, progress: (rows.length) ? "" : String(idleLabel(progress, complete)) });

  return (
    <div className="sync-stream">
      <svg
        className="sync-stream-svg"
        viewBox={`0 0 ${WIDTH} ${height}`}
        width="100%"
        role="img"
        aria-label={summary}
        data-flow={flowing ? "on" : "off"}
        data-rows={rows.length}
      >
        <text className="sync-stream-eyebrow" x="0" y="16">
          {notificationsSyncStreamScrapingNow()}
        </text>

        {rows.length === 0 && (
          <text className="sync-stream-idle" x="0" y={centerY + 4}>
            {idleLabel(progress, complete)}
          </text>
        )}

        {rows.map((company, index) => {
          const y = rowY(index);
          const ms = elapsedFor(company, clock);
          const path = channelPath(y, centerY);
          return (
            <g key={company.slug}>
              <text className="sync-stream-name" x={LABEL_X} y={y + 4} textAnchor="end">
                {companyName(company.slug)}
              </text>
              <text className="sync-stream-clock" x={LABEL_X} y={y + 19} textAnchor="end">
                {ms == null ? "—" : fmtElapsed(ms)}
              </text>
              <path className="sync-stream-channel" d={path} />
              <circle className="sync-stream-spout" cx={SPOUT_X} cy={y} r="3.5" />
              {flowing &&
                [0, 1, 2].map((slot) => (
                  <circle
                    key={slot}
                    className="sync-stream-dot"
                    r="3.5"
                    style={{
                      offsetPath: notificationsSyncStreamPath({ path: String(path) }),
                      animationDelay: `${slot * 1.15 + index * 0.4}s`,
                    }}
                  />
                ))}
            </g>
          );
        })}

        <rect
          className="sync-stream-tank"
          x={TANK_X}
          y={tankY}
          width={TANK_W}
          height={tankH}
          rx="10"
        />
        {bandH > 0 && (
          <rect
            className="sync-stream-written"
            x={TANK_X + 1}
            y={tankY + tankH - 1 - bandH}
            width={TANK_W - 2}
            height={bandH}
            rx="9"
          />
        )}
        <text
          className={`sync-stream-total${onBand(tankY + tankH * 0.4)}`}
          x={TANK_X + TANK_W / 2}
          y={tankY + tankH * 0.4}
          textAnchor="middle"
        >
          {copyNumber(held)}
        </text>
        <text
          className={`sync-stream-caption${onBand(tankY + tankH * 0.4 + 17)}`}
          x={TANK_X + TANK_W / 2}
          y={tankY + tankH * 0.4 + 17}
          textAnchor="middle"
        >
          {notificationsSyncStreamHeld()}
        </text>
        <text
          className={`sync-stream-caption${onBand(diskLabelY)}`}
          x={TANK_X + TANK_W / 2}
          y={diskLabelY}
          textAnchor="middle"
        >
          <Msg of={notificationsSyncStreamOnDisk} elems={{ written: copyNumber(written) }} />
        </text>
        <text
          className="sync-stream-caption"
          x={TANK_X + TANK_W / 2}
          y={height - 12}
          textAnchor="middle"
        >
          {notificationsSyncStreamInMemory()}
        </text>
      </svg>

      {stale && (
        <p className="sync-progress-note warn">
          <Msg of={notificationsSyncStreamNoUpdateForThisRun} elems={{ staleMs: fmtElapsed(clock.staleMs) }} />
        </p>
      )}
    </div>
  );
}
