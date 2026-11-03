import {
  radarEmptyFirstScanFinish,
  radarEmptyFilteredClear,
  radarEmptyFilteredTitle,
  radarEmptyChangeLookingFor,
  radarEmptyFew,
  radarEmptyFewTitle,
  radarEmptyFit,
  radarEmptyFitTitle,
  radarEmptyFollowMore,
  radarEndChangeLookingFor,
  radarEndFew,
  radarEndFiltered,
  radarEndFit,
  radarEndScanning,
  radarFirstScanBack,
  radarFirstScanBackMinutes,
  radarFirstScanFiltered,
  radarFirstScanFollow,
  radarFirstScanHeld,
  radarFirstScanHeldCount,
  radarFirstScanHeldTitle,
  radarFirstScanHeldUntil,
  radarFirstScanLine,
  radarFirstScanLookingFor,
  radarFirstScanNone,
  radarFirstScanNoneTitle,
  radarFirstScanNothingYet,
  radarFirstScanProgress,
  radarFirstScanProgressUnknown,
  radarFirstScanRunningTitle,
  radarFirstScanScanNow,
  radarFirstScanStarting,
  radarFirstScanStartingTitle,
  radarFirstScanStopped,
  radarFirstScanStoppedTitle,
} from "../../copy/gen/radar";
import { useEffect, useRef } from "react";
import { api, type CompanyDirectoryStatus } from "../../api";
import { roundCount } from "../../counts";
import { useAsyncResource } from "../../hooks/useAsyncResource";
import { Link } from "react-router-dom";
import { useSyncActions, useSyncStatus } from "../../context/SyncState";
import { number as copyNumber, time } from "../../copy/format";
import { useInstallSetUp } from "../../routing/installSetUp";
import { SETUP_PATH } from "../../routing/setupMode";
import { Button, EmptyState, Msg } from "../../ui";
import { firstScan, nothingFitsYet, type FirstScan, type FirstScanWhen } from "./firstScan";

/* The board's words for the first scan: the empty board, the line over a
   list while the scan reads, and the note under the last page. Each reads the
   scan status itself, so a poll re-renders these and never the board. */

const LOOKING_FOR_PATH = "/profile/direction";
const COMPANIES_PATH = "/settings/companies";
/** The list is read again at most this often while the first scan finds roles:
    the scan publishes new roles every few minutes, not per company. */
const REREAD_MS = 60_000;

function useFirstScan(): FirstScan | null {
  const { status, syncing } = useSyncStatus();
  return status ? firstScan(status, syncing, Date.now()) : null;
}

/** Three dots that fade in turn while work is moving. Hidden from screen
    readers, so the title is read once; still under reduced motion. */
function ScanDots() {
  return (
    <span className="scan-dots" aria-hidden="true">
      <span>.</span><span>.</span><span>.</span>
    </span>
  );
}

function backLine(back: FirstScanWhen) {
  return back.when === "minutes" ? radarFirstScanBackMinutes({ minutes: back.minutes }) : radarFirstScanBack({ when: back.when });
}

/** The open board with nothing on it. `narrowed`: a board filter or lens is
    on, and `onClear` clears them all, as the toolbar's Reset all does. */
export function OpenBoardEmpty({ narrowed, onClear }: { narrowed: boolean; onClear: () => void }) {
  const scan = useFirstScan();
  const setUp = useInstallSetUp();
  const { triggerSync } = useSyncActions();
  // Until the status answers there is nothing true to say about why the
  // board is empty; a sentence about filters would be a guess.
  if (!scan) return null;

  if (scan.phase === "done") {
    if (narrowed) {
      return (
        <EmptyState title={radarEmptyFilteredTitle()}>
          <Button variant="link" onClick={onClear}>{radarEmptyFilteredClear()}</Button>
        </EmptyState>
      );
    }
    return <FitEmpty />;
  }

  const filtered = narrowed && (
    <p className="board-first-scan-filtered">
      {radarFirstScanFiltered()}{" "}
      <Button variant="link" onClick={onClear}>{radarEmptyFilteredClear()}</Button>
    </p>
  );
  const finish = setUp === false && (
    <Link className="ui-btn ui-btn-link board-first-scan-finish" to={SETUP_PATH}>{radarEmptyFirstScanFinish()}</Link>
  );
  const lookingFor = <Link className="ui-btn ui-btn-link" to={LOOKING_FOR_PATH}>{radarFirstScanLookingFor()}</Link>;

  let title: React.ReactNode;
  let body: React.ReactNode;
  switch (scan.phase) {
    case "none":
      title = radarFirstScanNoneTitle();
      body = (
        <>
          <p>{radarFirstScanNone()}</p>
          <Link className="ui-btn ui-btn-link board-first-scan-finish" to={COMPANIES_PATH}>{radarFirstScanFollow()}</Link>
        </>
      );
      break;
    case "starting":
      title = <>{radarFirstScanStartingTitle()}<ScanDots /></>;
      body = <p>{radarFirstScanStarting()}</p>;
      break;
    case "running": {
      const count = scan.count;
      title = <>{radarFirstScanRunningTitle()}<ScanDots /></>;
      body = (
        <>
          <p>
            {count === null ? radarFirstScanProgressUnknown()
              : nothingFitsYet(count) && !narrowed
                ? <Msg of={radarFirstScanNothingYet} args={{ read: copyNumber(count.read), total: copyNumber(count.total) }} elems={{ link: lookingFor }} />
                : radarFirstScanProgress({ read: copyNumber(count.read), total: copyNumber(count.total) })}
          </p>
          <p>{backLine(scan.back)}</p>
        </>
      );
      break;
    }
    case "held": {
      const { read, total } = scan.count;
      const { reason, until } = scan.hold;
      title = radarFirstScanHeldTitle();
      body = (
        <p>
          {radarFirstScanHeldCount({ read: copyNumber(read), total: copyNumber(total) })}{" "}
          {reason === "backoff" && until ? radarFirstScanHeldUntil({ time: time(until) }) : radarFirstScanHeld({ reason })}
        </p>
      );
      break;
    }
    case "stopped": {
      const { read, total } = scan.count;
      title = radarFirstScanStoppedTitle();
      body = (
        <>
          <p>{radarFirstScanStopped({ read: copyNumber(read), total: copyNumber(total) })}</p>
          <Button className="board-first-scan-finish" onClick={() => void triggerSync()}>{radarFirstScanScanNow()}</Button>
        </>
      );
      break;
    }
  }
  return (
    <div className="board-first-scan" data-phase={scan.phase}>
      <EmptyState title={title}>
        {body}
        {filtered}
        {finish}
      </EmptyState>
    </div>
  );
}

/* Whether the person follows every company decides what to suggest when
   nothing fits. Following some, more companies is the likelier answer than a
   narrower Profile, so it comes first; following all of them, the Profile is
   what is left. Read only where one of these lines shows. Null while it loads
   or when it fails, read as following some. */
function useDirectory(): CompanyDirectoryStatus | null {
  return useAsyncResource(api.companyDirectoryStatus, [], { keep: "companies/directory-status" }).data ?? null;
}

const changeLink = () => <Link className="ui-btn ui-btn-link" to={LOOKING_FOR_PATH}>{radarEmptyChangeLookingFor()}</Link>;

function FitEmpty() {
  const { status } = useSyncStatus();
  const directory = useDirectory();
  if (directory?.following) {
    const checking = directory.checked < directory.to_check;
    return (
      <EmptyState title={radarEmptyFitTitle()}>
        <p>{radarEmptyFit({
          choice: checking ? "checking" : "done",
          checked: copyNumber(directory.checked),
          total: copyNumber(directory.to_check),
        })}</p>
        <p className="board-empty-actions">{changeLink()}</p>
      </EmptyState>
    );
  }
  const followed = status?.bindings_attention.followed ?? 0;
  const more = directory ? directory.to_check : 0;
  return (
    <EmptyState title={radarEmptyFewTitle({ count: followed })}>
      <p>{radarEmptyFew({ choice: more > 0 ? "counted" : "other", more: more > 0 ? copyNumber(roundCount(more)) : "" })}</p>
      <p className="board-empty-actions">
        <Link className="ui-btn ui-btn-link" to={COMPANIES_PATH}>{radarEmptyFollowMore()}</Link>
        {changeLink()}
      </p>
    </EmptyState>
  );
}

/** The end of a list once every company is read, with no board filter on. */
function ReachNote() {
  const directory = useDirectory();
  if (directory?.following) return <Msg of={radarEndFit} elems={{ change: changeLink() }} />;
  return (
    <Msg of={radarEndFew} elems={{
      follow: <Link className="ui-btn ui-btn-link" to={COMPANIES_PATH}>{radarEmptyFollowMore()}</Link>,
      change: <Link className="ui-btn ui-btn-link" to={LOOKING_FOR_PATH}>{radarEndChangeLookingFor()}</Link>,
    }} />
  );
}

/** Over a list while the first scan is reading: how far it has got. */
export function FirstScanLine() {
  const scan = useFirstScan();
  if (scan?.phase !== "running" || scan.count === null) return null;
  return (
    <div className="board-first-scan-line" role="status">
      <Msg of={radarFirstScanLine} args={{ read: copyNumber(scan.count.read), total: copyNumber(scan.count.total) }}
        elems={{ dots: <ScanDots /> }} />
    </div>
  );
}

/** Under the last page of a list that ends: still reading, or that this is
    every role the followed companies, the person's Profile or the board's
    filters let through. */
export function ListEndNote({ narrowed, onClear }: { narrowed: boolean; onClear: () => void }) {
  const scan = useFirstScan();
  if (!scan || scan.phase === "none") return null;
  let note: React.ReactNode;
  if (scan.phase !== "done") {
    if (!("count" in scan) || scan.count === null) return null;
    note = radarEndScanning({ count: scan.count.total - scan.count.read });
  } else if (narrowed) {
    note = <Msg of={radarEndFiltered} elems={{ clear: <Button variant="link" onClick={onClear}>{radarEmptyFilteredClear()}</Button> }} />;
  } else {
    note = <ReachNote />;
  }
  return <p className="board-list-end" role="note">{note}</p>;
}

/** While the first scan reads, the list is read again as companies are
    read: the scan has no end to wait for, and its first roles must not wait
    for the last company. `onReread` decides how the new list arrives. */
export function FirstScanReread({ onReread }: { onReread: () => void }) {
  const { status } = useSyncStatus();
  const scheduler = status?.scheduler;
  const read = status?.running && scheduler?.seeded && scheduler.ever_read < scheduler.required ? scheduler.ever_read : null;
  const last = useRef<{ read: number; at: number } | null>(null);
  const latest = useRef(onReread);
  useEffect(() => {
    latest.current = onReread;
  }, [onReread]);
  useEffect(() => {
    if (read === null) {
      last.current = null;
      return;
    }
    const now = Date.now();
    if (last.current === null) {
      last.current = { read, at: now };
    } else if (read > last.current.read && now - last.current.at >= REREAD_MS) {
      last.current = { read, at: now };
      latest.current();
    }
  }, [read]);
  return null;
}
