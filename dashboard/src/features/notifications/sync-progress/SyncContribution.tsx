import { compare as copyCompare, number as copyNumber } from "../../../copy/format";
import { Button } from "../../../ui/Button";
import { useCallback, useEffect, useId, useRef, useState } from "react";
import { companyName } from "../../../format";
import { FINISHED_STATES, LANDED, type SyncCompany, type SyncProgress } from "./model";
import {
  notificationsSyncContributionBlocked,
  notificationsSyncContributionBlockedTheSourceIsRefusing,
  notificationsSyncContributionFailed,
  notificationsSyncContributionFailed2,
  notificationsSyncContributionLanded,
  notificationsSyncContributionMore,
  notificationsSyncContributionMore2,
  notificationsSyncContributionOpportunities,
  notificationsSyncContributionOpportunities2,
  notificationsSyncContributionOpportunities3,
  notificationsSyncContributionPartial,
  notificationsSyncContributionPausedWhileThisComputer,
  notificationsSyncContributionQueued,
  notificationsSyncContributionRolesFoundPerCompany,
  notificationsSyncContributionScannedNothingInScope,
  notificationsSyncContributionScraping,
  notificationsSyncContributionWhatHasLanded,
} from "../../../copy/gen/notifications";
import { Msg } from "../../../ui/Msg";

/**
 * The live panel's second block, under the stream: what the finished sources
 * actually contributed.
 *
 * Segments are sized by opportunities found, not by company count: the question
 * is which sources are carrying this run, and an equal slice per company would
 * answer a different one. Failures and empty-but-successful sources are named in
 * the footer rather than drawn, because neither has a volume to draw.
 */

/** Below this share of the total a segment is too thin to read; it merges. */
const MERGE_FLOOR = 0.04;
/** Past this many named segments the bar stops being scannable. */
const MAX_SEGMENTS = 8;
/** A name plus its count needs about this much room to sit inside a segment. */
const LABEL_MIN_PX = 88;
/** A bare count needs far less, and beats an anonymous block of colour. */
const COUNT_MIN_PX = 34;
/** Fallback share tests when the container has not been measured (jsdom, first paint). */
const LABEL_MIN_PCT = 0.12;
const COUNT_MIN_PCT = 0.05;
/** Named lists stay readable; the rest becomes a count. */
const MAX_NAMED = 4;

export interface ContributionSegment {
  key: string;
  label: string;
  value: number;
  pct: number;
  merged: boolean;
  /** Room for the name and its count. */
  showLabel: boolean;
  /** Room for the count alone — a narrow segment still says something. */
  showCount: boolean;
  /** Display names this segment stands for; more than one only when merged. */
  members: string[];
}

const isFinished = (c: SyncCompany) => FINISHED_STATES.includes(c.state);

/** Collection finished and produced usable observations (`LANDED`), whatever the volume. */
export const isLanded = (c: SyncCompany) =>
  isFinished(c) && c.outcome != null && LANDED[c.outcome];

/**
 * Sources that scanned a board and legitimately kept nothing. A success under
 * `classify_source_outcome`, and it must never be styled as a failure.
 */
export const isEmptyButFine = (c: SyncCompany) => isLanded(c) && c.detected === 0;

export function buildSegments(
  companies: SyncCompany[],
  containerWidth: number | null,
): ContributionSegment[] {
  const eligible = companies
    .filter((c) => isFinished(c) && c.detected > 0)
    .sort((a, b) => b.detected - a.detected || copyCompare(a.slug, b.slug));
  const total = eligible.reduce((sum, c) => sum + c.detected, 0);
  if (total <= 0) return [];

  const named: SyncCompany[] = [];
  const rest: SyncCompany[] = [];
  for (const company of eligible) {
    const belowFloor = company.detected / total < MERGE_FLOOR;
    if (rest.length > 0 || belowFloor || named.length >= MAX_SEGMENTS) rest.push(company);
    else named.push(company);
  }

  // "+1 more" is strictly worse than the company's own name, so a remainder of
  // one is always kept whole.
  if (rest.length === 1) {
    named.push(rest.pop() as SyncCompany);
  }

  const fits = (pct: number, px: number, fallbackPct: number) =>
    containerWidth == null ? pct >= fallbackPct : pct * containerWidth >= px;
  const showLabel = (pct: number) => fits(pct, LABEL_MIN_PX, LABEL_MIN_PCT);
  const showCount = (pct: number) => fits(pct, COUNT_MIN_PX, COUNT_MIN_PCT);

  const segments = named.map((company) => {
    const pct = company.detected / total;
    return {
      key: company.slug,
      label: companyName(company.slug),
      value: company.detected,
      pct,
      merged: false,
      showLabel: showLabel(pct),
      showCount: showCount(pct),
      members: [companyName(company.slug)],
    };
  });

  if (rest.length > 0) {
    const value = rest.reduce((sum, c) => sum + c.detected, 0);
    const pct = value / total;
    segments.push({
      key: "__rest__",
      label: notificationsSyncContributionMore({ length: rest.length }),
      value,
      pct,
      merged: true,
      showLabel: showLabel(pct),
      showCount: showCount(pct),
      members: rest.map((c) => companyName(c.slug)),
    });
  }
  return segments;
}

/**
 * Rendered width of the bar, or null before it can be measured (jsdom).
 *
 * Deliberately a callback ref plus a resize listener rather than a
 * `ResizeObserver`. Two reasons:
 *
 * 1. This bar renders nothing until the first source lands, so an effect with an
 *    empty dep list runs once while the node is still absent and never fires
 *    again once it appears: the width would stay null for the whole run.
 * 2. ResizeObserver notifications are not delivered in every host that renders
 *    this app, and a silent fallback to the coarse percentage rule is indistinguishable from
 *    working. `getBoundingClientRect` in the ref callback is available at commit
 *    and works everywhere.
 */
function useMeasuredWidth<T extends HTMLElement>() {
  const [width, setWidth] = useState<number | null>(null);
  const node = useRef<T | null>(null);

  const measure = useCallback(() => {
    const measured = node.current?.getBoundingClientRect().width ?? 0;
    setWidth(measured > 0 ? measured : null);
  }, []);

  const ref = useCallback(
    (next: T | null) => {
      node.current = next;
      measure();
    },
    [measure],
  );

  useEffect(() => {
    window.addEventListener("resize", measure);
    return () => window.removeEventListener("resize", measure);
  }, [measure]);

  return [ref, width] as const;
}

/** What hovering a segment reveals: whatever the bar itself had no room to say. */
function tipText(segment: ContributionSegment): string {
  if (segment.merged) return segment.members.join(", ");
  return notificationsSyncContributionOpportunities2({ label: String(segment.label), count: segment.value, value: String(copyNumber(segment.value)) });
}

export function SyncContributionBar({ companies }: { companies: SyncCompany[] }) {
  const [ref, width] = useMeasuredWidth<HTMLDivElement>();
  const tipId = useId();
  const segments = buildSegments(companies, width);
  if (segments.length === 0) return null;

  const total = segments.reduce((sum, s) => sum + s.value, 0);
  return (
    <div className="sync-contrib" ref={ref}>
      <div className="sync-contrib-head">
        <span className="eyebrow">{notificationsSyncContributionWhatHasLanded()}</span>
        <span className="sync-contrib-total"><Msg of={notificationsSyncContributionOpportunities} args={{ count: total }} elems={{ total: copyNumber(total) }} /></span>
      </div>
      <div className="sync-contrib-bar" role="list" aria-label={notificationsSyncContributionRolesFoundPerCompany()}>
        {segments.map((segment) => {
          const id = `${tipId}-${segment.key}`;
          return (
            <div
              key={segment.key}
              className="sync-contrib-seg"
              data-merged={segment.merged ? "yes" : "no"}
              style={{ flexGrow: segment.value }}
              role="listitem"
              aria-label={notificationsSyncContributionOpportunities3({ label: String(segment.label), value: segment.value })}
              aria-describedby={id}
              // Focusable only where the name is hidden, so revealing it does not
              // cost a tab stop on segments that already say who they are.
              tabIndex={segment.showLabel ? undefined : 0}
            >
              {segment.showLabel ? (
                <span className="sync-contrib-seg-label">
                  {segment.label} {copyNumber(segment.value)}
                </span>
              ) : (
                segment.showCount && (
                  <span className="sync-contrib-seg-label">
                    {copyNumber(segment.value)}
                  </span>
                )
              )}
              <span className="sync-contrib-tip" id={id} role="tooltip">
                {tipText(segment)}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function nameList(companies: SyncCompany[]): string {
  const names = companies.map((c) => companyName(c.slug));
  if (names.length <= MAX_NAMED) return names.join(", ");
  return notificationsSyncContributionMore2({ join: String(names.slice(0, MAX_NAMED).join(", ")), value: names.length - MAX_NAMED });
}

export function SyncFooterCounts({ progress: p }: { progress: SyncProgress }) {
  const [queuedOpen, setQueuedOpen] = useState(false);
  const failed = p.companies.filter((c) => c.outcome === "failed");
  // A blocked source gets its own line, not a seat among the failures: "the
  // source is refusing us" needs the operator's attention, and folding it into
  // "failed" hides exactly the distinction the backend breaker establishes.
  const blocked = p.companies.filter((c) => c.outcome === "blocked");
  const degraded = p.companies.filter((c) => c.outcome === "degraded");
  // Landed, but cut by this computer sleeping or going offline: the next scan
  // reads the rest, and nothing about the source is wrong.
  const suspended = p.companies.filter((c) => c.outcome === "suspended");
  const emptyButFine = p.companies.filter(isEmptyButFine);
  const queued = p.companies.filter((c) => c.state === "queued");
  const landed = p.companies.filter(isLanded).length;

  return (
    <div className="sync-contrib-foot">
      <p className="sync-contrib-counts">
        <span>
          <b>{landed}</b> {notificationsSyncContributionLanded()}
        </span>
        <span>
          <b>{p.companiesScraping}</b> {notificationsSyncContributionScraping()}
        </span>
        {queued.length > 0 && (
          <Button
            variant="link"
            className="ui-btn-quiet sync-contrib-queued"
            aria-expanded={queuedOpen}
            aria-controls="sync-queued-names"
            onClick={() => setQueuedOpen((open) => !open)}
          >
            <b>{queued.length}</b> {notificationsSyncContributionQueued()}
          </Button>
        )}
        {failed.length > 0 && (
          <span className="sync-contrib-bad">
            <b>{failed.length}</b> {notificationsSyncContributionFailed()}
          </span>
        )}
        {blocked.length > 0 && (
          <span className="sync-contrib-bad">
            <b>{blocked.length}</b> {notificationsSyncContributionBlocked()}
          </span>
        )}
      </p>

      {queuedOpen && queued.length > 0 && (
        <p className="sync-contrib-names" id="sync-queued-names">
          {queued.map((c) => companyName(c.slug)).join(" · ")}
        </p>
      )}

      {failed.length > 0 && (
        <p className="sync-contrib-names bad"><Msg of={notificationsSyncContributionFailed2} elems={{ failed: nameList(failed) }} /></p>
      )}
      {blocked.length > 0 && (
        <p className="sync-contrib-names bad">
          <Msg of={notificationsSyncContributionBlockedTheSourceIsRefusing} elems={{ blocked: nameList(blocked) }} />
        </p>
      )}
      {degraded.length > 0 && (
        <p className="sync-contrib-names warn"><Msg of={notificationsSyncContributionPartial} elems={{ degraded: nameList(degraded) }} /></p>
      )}
      {suspended.length > 0 && (
        <p className="sync-contrib-names">
          <Msg of={notificationsSyncContributionPausedWhileThisComputer} elems={{ suspended: nameList(suspended) }} />
        </p>
      )}
      {emptyButFine.length > 0 && (
        <p className="sync-contrib-names">
          <Msg of={notificationsSyncContributionScannedNothingInScope} elems={{ emptyButFine: nameList(emptyButFine) }} />
        </p>
      )}
    </div>
  );
}
