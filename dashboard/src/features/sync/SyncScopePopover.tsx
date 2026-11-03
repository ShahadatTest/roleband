import { SearchField } from "../../ui/SearchField";
import { useMemo, useState } from "react";
import type { SourceOutcome, SyncTarget, SyncTargets } from "../../api";
import { api } from "../../api";
import { useSyncActions } from "../../context/SyncState";
import { ageLabel } from "../../format";
import { useAsyncResource } from "../../hooks/useAsyncResource";
import { AsyncBoundary, Badge, Button, Popover, useToast } from "../../ui";
import type { BadgeTone } from "../../ui";
import "./SyncScope.css";
import {
  scanSyncScopePopoverAFewRowsUnread,
  scanSyncScopePopoverATargetedSyncRefreshesOnly,
  scanSyncScopePopoverAllShown,
  scanSyncScopePopoverBlocked,
  scanSyncScopePopoverCapped,
  scanSyncScopePopoverChooseCompaniesToScan,
  scanSyncScopePopoverCompanies,
  scanSyncScopePopoverCompaniesToScan2,
  scanSyncScopePopoverCutShort,
  scanSyncScopePopoverFailed,
  scanSyncScopePopoverFailedLastRun,
  scanSyncScopePopoverFilterCompanies,
  scanSyncScopePopoverFilterCompaniesToScan,
  scanSyncScopePopoverJoined,
  scanSyncScopePopoverJoinsRunning,
  scanSyncScopePopoverListsNoRoles,
  scanSyncScopePopoverLoadFailed,
  scanSyncScopePopoverLoading,
  scanSyncScopePopoverRolebandCanTScanAny,
  scanSyncScopePopoverNoCompanyMatchesThatFilter,
  scanSyncScopePopoverNotReached,
  scanSyncScopePopoverPartial,
  scanSyncScopePopoverPaused,
  scanSyncScopePopoverScan,
  scanSyncScopePopoverSelectAllShownCompanies,
  scanSyncScopePopoverSelectCompanies,
  scanSyncScopePopoverStale,
} from "../../copy/gen/scan";
import { Msg } from "../../ui/Msg";

/* Choosing which companies a sync covers.
 *
 * The pipeline takes a company subset (`tracker.daily --company`, and the
 * automated retry runs on one); this is that capability with a handle on it.
 * It lives beside the header Sync button rather than on the Companies board
 * because a run has exactly one live state (running, elapsed, stop) and that
 * state lives here. Two surfaces triggering one run would disagree about it.
 *
 * Selection grammar is deliberately the Companies board's: search, a tri-state
 * select-all, rows with a state. A third way to pick many from a set would make
 * the screens read as different products.
 *
 * The roster comes from `/api/sync/targets`, which is `get_active_targets` and
 * nothing else, so the picker can never offer a company the run would drop. */

/** How an outcome from the last full run reads on a row. `ok` says nothing.
 *  A Record, so an outcome the backend adds fails `tsc` until it has words. */
const OUTCOME_PRESENTATION: Record<SourceOutcome, { label: string; tone: BadgeTone } | null> = {
  ok: null,
  failed: { get label() { return scanSyncScopePopoverFailed(); }, tone: "danger" },
  blocked: { get label() { return scanSyncScopePopoverBlocked(); }, tone: "danger" },
  degraded: { get label() { return scanSyncScopePopoverPartial(); }, tone: "warning" },
  bounded: { get label() { return scanSyncScopePopoverCutShort(); }, tone: "warning" },
  truncated: { get label() { return scanSyncScopePopoverCutShort(); }, tone: "warning" },
  unattempted: { get label() { return scanSyncScopePopoverNotReached(); }, tone: "warning" },
  suspended: { get label() { return scanSyncScopePopoverPaused(); }, tone: "info" },
  lossy: { get label() { return scanSyncScopePopoverAFewRowsUnread(); }, tone: "info" },
  empty: { get label() { return scanSyncScopePopoverListsNoRoles(); }, tone: "info" },
  capped: { get label() { return scanSyncScopePopoverCapped(); }, tone: "info" },
};

function matches(target: SyncTarget, query: string): boolean {
  const q = query.trim().toLowerCase();
  if (!q) return true;
  return target.display.toLowerCase().includes(q) || target.slug.includes(q);
}

function SyncScopeRow({
  target,
  checked,
  onToggle,
}: {
  target: SyncTarget;
  checked: boolean;
  onToggle: () => void;
}) {
  const outcome = target.last_outcome ? OUTCOME_PRESENTATION[target.last_outcome] : null;
  return (
    <label className="sync-scope-row">
      <input type="checkbox" aria-label={target.display} checked={checked} onChange={onToggle} />
      <span className="sync-scope-name">{target.display}</span>
      {outcome && (
        <Badge tone={outcome.tone} size="sm">
          {outcome.label}
        </Badge>
      )}
      {/* Last *attempted*, not last succeeded: a source we tried and failed is
          not fresh, and the badge beside it is what says which happened. */}
      <span className={`sync-scope-age${target.stale ? " is-stale" : ""}`}>
        {ageLabel(target.age_hours)}
      </span>
    </label>
  );
}

function SyncScopePanel({ joining, onClose, onFailed }: { joining: boolean; onClose: () => void; onFailed: () => void }) {
  const { triggerSync } = useSyncActions();
  const { toast } = useToast();
  const resource = useAsyncResource<SyncTargets>(api.syncTargets, []);
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState<Set<string>>(new Set());

  const all = useMemo(() => resource.data?.companies ?? [], [resource.data]);
  const visible = useMemo(() => all.filter((t) => matches(t, query)), [all, query]);
  const staleSlugs = useMemo(() => all.filter((t) => t.stale).map((t) => t.slug), [all]);
  const failedSlugs = useMemo(() => all.filter((t) => t.retryable).map((t) => t.slug), [all]);

  const toggle = (slug: string) =>
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(slug)) next.delete(slug);
      else next.add(slug);
      return next;
    });

  // Select-all acts on what the filter is showing, like the board's sector
  // checkbox acts on its group — a hidden row must never be swept in silently.
  const visibleSelected = visible.filter((t) => selected.has(t.slug)).length;
  const allVisibleSelected = visible.length > 0 && visibleSelected === visible.length;
  const someVisibleSelected = visibleSelected > 0 && !allVisibleSelected;
  const toggleVisible = () =>
    setSelected((prev) => {
      const next = new Set(prev);
      for (const target of visible) {
        if (allVisibleSelected) next.delete(target.slug);
        else next.add(target.slug);
      }
      return next;
    });

  const count = selected.size;
  // Joining a live run, every company is still a list: the run reads them all
  // already, and only named companies move to the front.
  const everything = !joining && count > 0 && count === all.length;
  const label = scanSyncScopePopoverScan({ choice: (everything) ? "yes" : "no", count: (everything) ? "" : count, value: (everything) ? "" : scanSyncScopePopoverCompanies({ count: count }) });

  const start = () => {
    // Everything selected is a genuinely full run, so send no subset at all:
    // the backend records `scope=full` and the radar's freshness clock resets,
    // which a targeted run must never do.
    void triggerSync(everything ? [] : [...selected]).then((started) => {
      if (!started) onFailed();
      else if (started === "joined") toast({ key: "sync-joined", text: scanSyncScopePopoverJoined({ count }) });
    });
    onClose();
  };

  return (
    <div className="sync-scope">
      <AsyncBoundary
        resource={resource}
        loading={scanSyncScopePopoverLoading()}
        failed={scanSyncScopePopoverLoadFailed()}
        isEmpty={(data) => data.companies.length === 0}
        empty={
          <p className="sync-scope-note">
            {scanSyncScopePopoverRolebandCanTScanAny()}
          </p>
        }
      >
        {() => (
          <>
            <SearchField
              size="sm"
              className="sync-scope-search"
              label={scanSyncScopePopoverFilterCompaniesToScan()}
              placeholder={scanSyncScopePopoverFilterCompanies()}
              value={query}
              onChange={setQuery}
            />

            <label className="sync-scope-all">
              <input
                type="checkbox"
                aria-label={scanSyncScopePopoverSelectAllShownCompanies()}
                checked={allVisibleSelected}
                ref={(node) => {
                  if (node) node.indeterminate = someVisibleSelected;
                }}
                disabled={visible.length === 0}
                onChange={toggleVisible}
              />
              <span>
                {scanSyncScopePopoverAllShown({
                  choice: visible.length < all.length ? "yes" : "no",
                  shown: visible.length,
                  total: all.length,
                })}
              </span>
            </label>

            <div className="sync-scope-rows" role="group" aria-label={scanSyncScopePopoverCompaniesToScan2()}>
              {visible.length === 0 ? (
                <p className="sync-scope-note">{scanSyncScopePopoverNoCompanyMatchesThatFilter()}</p>
              ) : (
                visible.map((target) => (
                  <SyncScopeRow
                    key={target.slug}
                    target={target}
                    checked={selected.has(target.slug)}
                    onToggle={() => toggle(target.slug)}
                  />
                ))
              )}
            </div>

            {(staleSlugs.length > 0 || failedSlugs.length > 0) && (
              <div className="sync-scope-presets">
                {staleSlugs.length > 0 && (
                  <Button size="sm" onClick={() => setSelected(new Set(staleSlugs))}>
                    <Msg of={scanSyncScopePopoverStale} elems={{ length: staleSlugs.length }} />
                  </Button>
                )}
                {failedSlugs.length > 0 && (
                  <Button size="sm" onClick={() => setSelected(new Set(failedSlugs))}>
                    <Msg of={scanSyncScopePopoverFailedLastRun} elems={{ length: failedSlugs.length }} />
                  </Button>
                )}
              </div>
            )}

            <div className="sync-scope-actions">
              <Button
                variant="primary"
                disabled={count === 0}
                onClick={start}
              >
                {count === 0 ? scanSyncScopePopoverSelectCompanies() : label}
              </Button>
            </div>

            {/* The one thing a user cannot infer from the control itself. */}
            <p className="sync-scope-note">
              {joining ? scanSyncScopePopoverJoinsRunning() : scanSyncScopePopoverATargetedSyncRefreshesOnly()}
            </p>
          </>
        )}
      </AsyncBoundary>
    </div>
  );
}

export function SyncScopePopover({
  isOpen,
  joining = false,
  anchor,
  onClose,
  onFailed,
}: {
  isOpen: boolean;
  /** A run is live: the companies picked join it and are read next. */
  joining?: boolean;
  anchor: HTMLElement | null;
  onClose: () => void;
  /** The trigger did not land. Reported by the caller, which owns the run's
   *  state — this panel has closed by then. */
  onFailed: () => void;
}) {
  return (
    <Popover
      isOpen={isOpen}
      anchor={anchor}
      onClose={onClose}
      label={scanSyncScopePopoverChooseCompaniesToScan()}
      align="end"
      className="sync-scope-popover app-overlay"
    >
      {/* Mounted only while open, so every open re-reads freshness rather than
          showing what was true the first time the panel was built. */}
      <SyncScopePanel joining={joining} onClose={onClose} onFailed={onFailed} />
    </Popover>
  );
}
