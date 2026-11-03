import { number as copyNumber } from "../../copy/format";
import { ReactNode, memo, useCallback, useEffect, useLayoutEffect, useRef } from "react";
import type { CompanyDiscoveryCompany } from "../../api";
import { notificationText } from "../../api/notificationText";
import { useDisclosureMemory } from "../../hooks/useFilterMemory";
import { CompanyIcon, Icon, Spinner, Switch } from "../../ui";
import { Button } from "../../ui/Button";
import type { CompaniesContextValue, CompaniesSyncValue, SectorGroup } from "./CompaniesData";
import { isConnectable, useCompanies, useCompaniesSync } from "./CompaniesData";
import { hoursSince, shortAge } from "./companiesModel";
import { wallSentence } from "./followCopy";
import {
  companiesCompanyRegisterRowsAka,
  companiesCompanyRegisterRowsAlso,
  companiesCompanyRegisterRowsBlocked,
  companiesCompanyRegisterRowsCareersPage,
  companiesCompanyRegisterRowsCoverageProblem,
  companiesCompanyRegisterRowsCouldnTStartAScan,
  companiesCompanyRegisterRowsCoveredCount,
  companiesCompanyRegisterRowsSectorAction,
  companiesCompanyRegisterRowsSectorFollowAll,
  companiesCompanyRegisterRowsFollowed,
  companiesCompanyRegisterRowsFollowingNotScannedYet,
  companiesCompanyRegisterRowsRadarVisibility,
  companiesCompanyRegisterRowsLimitsCollection,
  companiesCompanyRegisterRowsNeedsConsent,
  companiesCompanyRegisterRowsRolebandLastReadSRoles,
  companiesCompanyRegisterRowsRolebandStartsScanningAsSoon,
  companiesCompanyRegisterRowsNothingToFollowWhy,
  companiesCompanyRegisterRowsNotCountedLastReadAgo,
  companiesCompanyRegisterRowsNotCountedYet,
  companiesCompanyRegisterRowsOfSRolesFitNo,
  companiesCompanyRegisterRowsOfSRolesNameA,
  companiesCompanyRegisterRowsOpenCount,
  companiesCompanyRegisterRowsSectorOpen,
  companiesCompanyRegisterRowsOpenCareersPage,
  companiesCompanyRegisterRowsOpenRoleCountsAreUnavailable,
  companiesCompanyRegisterRowsOpenRolesLoading,
  companiesCompanyRegisterRowsPartlyCounted,
  companiesCompanyRegisterRowsPlanned,
  companiesCompanyRegisterRowsPlannedHidden,
  companiesCompanyRegisterRowsLiveOrReady,
  companiesCompanyRegisterRowsNotCountedWhy,
  companiesCompanyRegisterRowsSScansHaveNotRead,
  companiesCompanyRegisterRowsScanNow,
  companiesCompanyRegisterRowsScanNowHint,
  companiesCompanyRegisterRowsScanJoined,
  companiesCompanyRegisterRowsScannedAgo,
  companiesCompanyRegisterRowsLabelScannedAgo,
  companiesCompanyRegisterRowsScannedAgoRolebandScansWhen,
  companiesCompanyRegisterRowsScanning,
  companiesCompanyRegisterRowsShowOrHideOnRadar,
  companiesCompanyRegisterRowsWaitingToScan,
  companiesCompanyRegisterRowsShowingOfMatchesKeepTyping,
  companiesCompanyRegisterRowsBoardFamily,
  companiesCompanyRegisterRowsBoardFound,
} from "../../copy/gen/companies";
import { Content } from "../../ui/Content";
import { Msg } from "../../ui/Msg";
import { connectorText } from "./connectorText";

/* The register's body: a sector heading over one row per company. A row
 * reads the Companies context and hands its own slice of it to a memoized
 * view, so a change to one row (a switch, a write settling) draws that row,
 * not the register. The count request is a prop like any other, so a row is
 * interactive while it is still out. */

type Counts = CompaniesContextValue["counts"];

/** The connector column: what can actually read this company's board.
 *
 *  What the scans did beats declared state. A followed company no scan has
 *  read in full for days still says `live` in the catalog, and reporting that
 *  would be the screen's most expensive lie: it is exactly the case a user
 *  needs to see without opening anything. */
function ConnectorCell({
  company,
  on,
  id,
  status,
  counts,
}: {
  company: CompanyDiscoveryCompany;
  on: boolean;
  id: string;
  status: ReturnType<CompaniesContextValue["sourceStatus"]>;
  counts: Counts;
}) {
  const coverage = status?.coverage ?? null;
  const needsAttention = !!coverage?.rings;
  // The coverage clock: when a scan last read the whole board.
  const scanned = on ? shortAge(hoursSince(status?.last_full_scan_at)) : null;

  let dot = "is-planned";
  let label = companiesCompanyRegisterRowsPlanned();
  let warn = false;
  let title = connectorText(company);

  if (needsAttention && coverage) {
    dot = "is-warn";
    warn = true;
    const days = coverage.days_since_full_scan;
    const age = status?.last_full_scan_at ? shortAge(days === null ? null : days * 24) : null;
    if (coverage.cause === "unknown") {
      label = status?.last_full_scan_at
        ? companiesCompanyRegisterRowsWaitingToScan()
        : companiesCompanyRegisterRowsFollowingNotScannedYet();
      if (!status?.last_full_scan_at) {
        dot = "is-ready";
        warn = false;
      }
    } else {
      const what = companiesCompanyRegisterRowsCoverageProblem({ cause: coverage.cause });
      label = age ? `${what} · ${age}` : what;
    }
    // Why, and what ends it: the Coverage notification's own words, served
    // with the row and said in the reader's language. The catalog's
    // "Scanned automatically" label is exactly the wrong thing to show on hover
    // of a broken row.
    const said = notificationText({ title: coverage.title, body: coverage.body, meta: { say: coverage.say } });
    title = `${said.title}. ${said.body}`;
  } else if (company.connector_state === "parked") {
    dot = "is-warn";
    label = companiesCompanyRegisterRowsBlocked();
    warn = true;
  } else if (company.wall !== null && company.enabled && !company.consented) {
    // Followed, walled, never consented to: kept, and not scanned.
    dot = "is-warn";
    label = companiesCompanyRegisterRowsNeedsConsent();
    warn = true;
  } else if (isConnectable(company)) {
    dot = company.connector_state !== "ready" ? "is-live" : "is-ready";
    label = companiesCompanyRegisterRowsLiveOrReady({ connector: company.connector_state });
    if (scanned) title = companiesCompanyRegisterRowsScannedAgo({ scanned: String(scanned) });
    if (scanned && status && !status.automatic) {
      // Scanned only when the user asks: never an alert,
      // the clock and how to move it.
      label = companiesCompanyRegisterRowsLabelScannedAgo({ label: String(label), scanned: String(scanned) });
      title = companiesCompanyRegisterRowsScannedAgoRolebandScansWhen({ scanned: String(scanned), display: String(company.display) });
    }
    // Scanned, and still left out of the count on Profile: no
    // catalog yet, or one from before the count could place its roles.
    const why = on ? counts.data?.not_counted[company.slug] : undefined;
    // Read before, and not lately enough to count:
    // the server says when; a catalog-sourced "stale" carries no time.
    const lastRead = why === "stale" ? shortAge(hoursSince(counts.data?.last_read?.[company.slug])) : null;
    if (lastRead) {
      label = companiesCompanyRegisterRowsNotCountedLastReadAgo({ label: String(label), lastRead: String(lastRead) });
      title = companiesCompanyRegisterRowsRolebandLastReadSRoles({ display: String(company.display), lastRead: String(lastRead) });
    } else if (why === "partial") {
      // Counted from scans that have not read its whole board.
      label = companiesCompanyRegisterRowsPartlyCounted({ label: String(label) });
      title = companiesCompanyRegisterRowsSScansHaveNotRead({ display: String(company.display) });
    } else if (why) {
      label = companiesCompanyRegisterRowsNotCountedYet({ label: String(label) });
      title = companiesCompanyRegisterRowsNotCountedWhy({ reason: why, company: company.display });
    }
  } else if (company.detected_family && company.pending_reason) {
    // Its careers page named a known board that did not become one: say which,
    // and why it waits, rather than the blank "planned" of a page nobody knew.
    dot = "is-warn";
    warn = true;
    label = companiesCompanyRegisterRowsBoardFound({
      reason: company.pending_reason,
      family: companiesCompanyRegisterRowsBoardFamily({ family: company.detected_family }),
    });
  } else if (on) {
    // Followed before RoleBand can read it: the follow is kept and
    // becomes collection the day a scanner lands. "Planned" beside a switch
    // that is on would read as if the switch did nothing.
    label = companiesCompanyRegisterRowsFollowingNotScannedYet();
    title = companiesCompanyRegisterRowsRolebandStartsScanningAsSoon({ display: String(company.display) });
  }

  return (
    <span className={`ledger-state${warn ? " is-warn" : ""}`} id={id} title={title}>
      <span className={`ledger-dot ${dot}`} />
      <span>{label}</span>
    </span>
  );
}

/** The count cell. Only the aggregate request is allowed to be late here; the
 *  row around it is interactive the whole time. */
function OpenRolesCell({
  company,
  id,
  counts,
  value,
}: {
  company: CompanyDiscoveryCompany;
  id: string;
  counts: Counts;
  /** `openRoles(company.slug)`. */
  value: number | null;
}) {
  // An untracked company has never been collected, so a number — or a dash
  // standing in for one — would report our own inaction as a fact about the
  // employer. Say nothing at all.
  if (!company.enabled || !isConnectable(company)) return <span id={id} />;
  if (counts.error) {
    return (
      <span data-selection="chrome" className="ledger-count is-empty" id={id} title={companiesCompanyRegisterRowsOpenRoleCountsAreUnavailable()}>
        —
      </span>
    );
  }
  if (value === null) {
    return (
      <span id={id}>
        <Spinner label={companiesCompanyRegisterRowsOpenRolesLoading()} size="sm" />
      </span>
    );
  }
  // Roles no answer can keep, by reason: a place we
  // could not read, or a place and no role type. The number carries a mark
  // and says which on hover.
  const unplaced = counts.data?.unplaced[company.slug] ?? 0;
  const unsorted = counts.data?.unsorted[company.slug] ?? 0;
  const why = [
    unplaced > 0 ? companiesCompanyRegisterRowsOfSRolesNameA({ unplaced: String(copyNumber(unplaced)), display: String(company.display) }) : null,
    unsorted > 0 ? companiesCompanyRegisterRowsOfSRolesFitNo({ unsorted: String(copyNumber(unsorted)), display: String(company.display) }) : null,
  ].filter(Boolean).join(" ");
  return (
    <span data-selection="chrome" className="ledger-count" id={id} title={why || undefined}>
      <Msg of={companiesCompanyRegisterRowsOpenCount} elems={{ count: copyNumber(value), mark: why && <span aria-hidden="true"> ·</span> }} />
    </span>
  );
}

/** The newest `verb` behind one identity for the row's life. The register's
 *  verbs close over the selection, so a memoized row holding them directly
 *  would be drawn again on every switch anywhere in the register. */
function useLatestVerb<A extends unknown[]>(verb: (...args: A) => unknown): (...args: A) => void {
  const latest = useRef(verb);
  useLayoutEffect(() => {
    latest.current = verb;
  });
  return useCallback((...args: A) => void latest.current(...args), []);
}

function CompanyRow({
  company,
  sectorSlug,
}: {
  company: CompanyDiscoveryCompany;
  sectorSlug: string;
}) {
  const {
    chosen,
    busy,
    query,
    maxOpenRoles,
    openRoles,
    sectorNames,
    sourceStatus,
    counts,
    toggleCompany,
    toggleVisible,
    syncable,
  } = useCompanies();
  const { syncRunning, scanLive, syncCompanies } = useCompaniesSync();
  const toggle = useLatestVerb(toggleCompany);
  const toggleShown = useLatestVerb(toggleVisible);
  const scan = useLatestVerb(syncCompanies);
  return (
    <CompanyRowView
      company={company}
      sectorSlug={sectorSlug}
      on={chosen.has(company.slug)}
      busy={busy.has(company.slug)}
      needle={query.trim()}
      maxOpenRoles={maxOpenRoles}
      openCount={openRoles(company.slug)}
      sectorNames={sectorNames}
      status={sourceStatus(company.slug)}
      counts={counts}
      syncable={syncable.has(company.slug)}
      scanState={scanLive ? "running" : syncRunning ? "waiting" : "idle"}
      toggleCompany={toggle}
      toggleVisible={toggleShown}
      syncCompanies={scan}
    />
  );
}

const CompanyRowView = memo(function CompanyRowView({
  company,
  sectorSlug,
  on,
  busy,
  needle,
  maxOpenRoles,
  openCount,
  sectorNames,
  status,
  counts,
  syncable,
  scanState,
  toggleCompany,
  toggleVisible,
  syncCompanies,
}: {
  company: CompanyDiscoveryCompany;
  sectorSlug: string;
  on: boolean;
  busy: boolean;
  needle: string;
  maxOpenRoles: number;
  openCount: number | null;
  sectorNames: Record<string, string>;
  status: ReturnType<CompaniesContextValue["sourceStatus"]>;
  counts: Counts;
  syncable: boolean;
  /** `running`: a click joins the live run. `waiting`: queued work owns the
   *  next run, so there is nothing to ask for yet. */
  scanState: "idle" | "running" | "waiting";
  toggleCompany: (company: CompanyDiscoveryCompany) => void;
  toggleVisible: (company: CompanyDiscoveryCompany) => void;
  syncCompanies: CompaniesSyncValue["syncCompanies"];
}) {
  const stateId = /* not copy: an element id */ `ledger-state-${sectorSlug}-${company.slug}`;
  const countId = /* not copy: an element id */ `ledger-count-${sectorSlug}-${company.slug}`;

  // A company in two sectors draws a row in each. Say so, so toggling one
  // and watching the other follow reads as identity, not a glitch.
  const alsoIn = company.sectors
    .filter((slug) => slug !== sectorSlug)
    .map((slug) => sectorNames[slug])
    .filter(Boolean);

  // A search can match on an alias the row never shows ("sec" finds PwC through
  // "PricewaterhouseCoopers"). An unexplained hit reads as a false positive.
  const aliasHit =
    needle && !company.display.toLocaleLowerCase().includes(needle.toLocaleLowerCase())
      ? company.aliases.find((alias) =>
          alias.toLocaleLowerCase().includes(needle.toLocaleLowerCase()),
        )
      : undefined;

  const roles = on && isConnectable(company) ? openCount : null;
  const barWidth =
    roles && maxOpenRoles > 0 ? Math.max(4, Math.round(100 * Math.sqrt(roles / maxOpenRoles))) : 0;

  return (
    <div
      className={`ledger-row${company.selectable ? "" : " is-blocked"}`}
      aria-busy={busy || undefined}
    >
      {/* The switch keeps its own small size; its TARGET is this wrapper,
          which stretches the full height of the row — bigger than the 24px
          minimum, and reached without distorting the control itself. */}
      <Switch
        label={company.display}
        labelIsContent
        describedBy={`${stateId} ${countId}`}
        checked={on}
        disabled={!company.selectable}
        title={company.selectable ? undefined : connectorText(company)}
        onChange={() => toggleCompany(company)}
      />

      <CompanyIcon
        slug={company.slug}
        display={company.display}
        size={22}
        brand={on}
        className="ledger-mark"
      />

      <span className="ledger-name">
        <Content text={company.display} highlight={needle} />
        {aliasHit && <span className="ledger-tag"><Msg of={companiesCompanyRegisterRowsAka} elems={{ aliasHit: <Content text={aliasHit} highlight={needle} /> }} /></span>}
        {/* Quiet, like the other tags: a walled company is followed only
            through its own dialog, and the tag says why before it opens. */}
        {company.wall !== null && (
          <span className="ledger-tag" title={wallSentence(company) ?? undefined}>
            {companiesCompanyRegisterRowsLimitsCollection()}
          </span>
        )}
        {alsoIn.map((name) => (
          <span className="ledger-tag" key={name}>
            <Msg of={companiesCompanyRegisterRowsAlso} elems={{ name: name }} />
          </span>
        ))}
      </span>

      <span className="ledger-state-cell">
        <ConnectorCell company={company} on={on} id={stateId} status={status} counts={counts} />
      </span>

      <span className="ledger-num">
        <OpenRolesCell company={company} id={countId} counts={counts} value={openCount} />
      </span>

      <span className="ledger-bar-cell" aria-hidden="true">
        {barWidth > 0 && <span className="ledger-bar" style={{ width: `${barWidth}%` }} />}
      </span>

      <span className="ledger-actions">
        {company.careers_url && (
          <a
            href={company.careers_url}
            target="_blank"
            rel="noreferrer"
            className="ui-btn ui-btn-icon ui-btn-sm"
            aria-label={companiesCompanyRegisterRowsOpenCareersPage({ display: String(company.display) })}
            title={companiesCompanyRegisterRowsCareersPage()}
          >
            <Icon name="external" size={16} />
          </a>
        )}
        {on && (
          <Button
            variant="icon"
            size="sm"
            aria-label={companiesCompanyRegisterRowsShowOrHideOnRadar({ visibility: company.visible ? "shown" : "hidden", company: company.display })}
            aria-pressed={company.visible}
            title={companiesCompanyRegisterRowsRadarVisibility({ visibility: company.visible ? "shown" : "hidden" })}
            onClick={() => toggleVisible(company)}
          >
            <Icon name={company.visible ? "eye" : "eyeOff"} size={16} />
          </Button>
        )}
        {/* Offered only for a company the pipeline would really accept. While
            a run is live the company joins it and is read next. */}
        {syncable && (
          <Button
            variant="icon"
            size="sm"
            aria-label={companiesCompanyRegisterRowsScanNow({ display: String(company.display) })}
            disabled={scanState === "waiting"}
            title={companiesCompanyRegisterRowsScanNowHint({ scan: scanState })}
            onClick={() => syncCompanies([company.slug], {
              confirm: companiesCompanyRegisterRowsScanning({ display: String(company.display) }),
              joined: companiesCompanyRegisterRowsScanJoined({ display: String(company.display) }),
              failure: companiesCompanyRegisterRowsCouldnTStartAScan({ display: String(company.display) }),
            })}
          >
            <Icon name="refresh" size={16} />
          </Button>
        )}
      </span>
    </div>
  );
});

function sectorStats(group: SectorGroup): string {
  const parts = [companiesCompanyRegisterRowsFollowed({ followed: group.trackedCount, total: group.members.length })];
  // Withhold a total we do not have rather than printing a placeholder 0.
  if (group.openRoles !== null && group.openRoles > 0) {
    parts.push(companiesCompanyRegisterRowsSectorOpen({ openRoles: copyNumber(group.openRoles) }));
  }
  parts.push(companiesCompanyRegisterRowsCoveredCount({ coverage: group.dormant ? "none" : "some", covered: group.connectable.length }));
  if (group.hiddenPlanned > 0) parts.push(companiesCompanyRegisterRowsPlannedHidden({ hiddenPlanned: group.hiddenPlanned }));
  return parts.join(" · ");
}

/** Under the directory group while a search is capped: the rows are the best
 *  matches, not all of them, and the count says how many more there are. */
export function DirectoryNote() {
  const { directorySearch } = useCompanies();
  if (!directorySearch || directorySearch.matchCount <= directorySearch.shown) return null;
  return (
    <p className="ledger-sector-note">
      <Msg of={companiesCompanyRegisterRowsShowingOfMatchesKeepTyping} elems={{ shown: directorySearch.shown, matchCount: copyNumber(directorySearch.matchCount) }} />
    </p>
  );
}

/* A group that can fold to its heading. Only "Other companies" does: it is the
 * one group whose size is not ours to choose (hundreds of rows once the wider
 * market is followed), and it sits last, so folded it costs one line.
 * Folded by default and remembered per browser. A search unfolds it without
 * touching that memory, because a search's matches are drawn in it; so does an
 * index link to it, because following one is asking to see it. */
export function SectorSection({
  group,
  before,
  collapsible = false,
}: {
  group: SectorGroup;
  /** Drawn above the rows. */
  before?: ReactNode;
  collapsible?: boolean;
}) {
  const { chosen, toggleSector, scrollTarget, clearScrollTarget, searching } = useCompanies();
  const memory = useDisclosureMemory("companies");
  const folds = collapsible && !searching;
  const open = !folds || memory.isOpen(group.slug, false);
  const { setOpen } = memory;
  // Two refs on purpose: the sticky HEAD is what gets scrolled into view (it
  // carries the scroll margin that clears the column header), while the
  // heading itself is what takes focus, so a keyboard user lands on something
  // that announces the sector rather than on an unnamed container.
  const headRef = useRef<HTMLDivElement>(null);
  const headingRef = useRef<HTMLHeadingElement>(null);

  // An index link must land the keyboard too, not just the viewport.
  useEffect(() => {
    if (scrollTarget !== group.slug) return;
    const head = headRef.current;
    clearScrollTarget();
    if (collapsible) setOpen(group.slug, true);
    if (!head) return;
    const reduced = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    head.scrollIntoView?.({ block: "start", behavior: reduced ? "auto" : "smooth" });
    headingRef.current?.focus();
  }, [scrollTarget, group.slug, clearScrollTarget, collapsible, setOpen]);

  /* Folding from deep in the list removes the rows under the reader, and the
     page can clamp the heading out of view; bring it back into view. */
  const fold = () => {
    setOpen(group.slug, !open);
    if (open) requestAnimationFrame(() => headRef.current?.scrollIntoView?.({ block: "nearest" }));
  };

  const selected = group.bulk.filter((company) => chosen.has(company.slug)).length;
  const all = group.bulk.length > 0 && selected === group.bulk.length;

  return (
    // Named by the sector: the same company can appear in two sections, and the
    // region is what disambiguates the two rows that carry its name.
    <section className="ledger-sector" aria-label={group.display}>
      <div className="ledger-sector-head" ref={headRef}>
        <h2 className="ledger-sector-title" ref={headingRef} tabIndex={-1}>
          {folds ? (
            <Button variant="link" className="ledger-sector-disclose" aria-expanded={open} onClick={fold}>
              <Icon name={open ? "chevronUp" : "chevronDown"} size={16} />
              {group.display}
            </Button>
          ) : (
            group.display
          )}
        </h2>
        <span className="ledger-sector-stats">{sectorStats(group)}</span>
        {/* Empty `bulk` does not mean "no connector": a sector with only
            planned companies still has rows the roster accepts. It means
            there is nothing on screen to act on, and the title says which of
            the two reasons applies. */}
        <Button
          variant="link"
          className="ui-btn-quiet ledger-sector-act"
          disabled={group.bulk.length === 0}
          // Disabled, it says "Nothing to follow", and that is its name: a
          // label promising "Follow all" would name an action it cannot take.
          aria-label={
            group.bulk.length === 0
              ? undefined
              : companiesCompanyRegisterRowsSectorFollowAll({ direction: all ? "unfollow" : "follow", sector: group.display })
          }
          title={
            group.bulk.length > 0
              ? undefined
              : companiesCompanyRegisterRowsNothingToFollowWhy({ coverage: group.dormant ? "none" : "some" })
          }
          onClick={() => toggleSector(group)}
        >
          {companiesCompanyRegisterRowsSectorAction({ action: group.bulk.length === 0 ? "none" : all ? "unfollow" : "follow" })}
        </Button>
      </div>

      {open && before}

      {open &&
        group.rows.map((company) => (
          <CompanyRow key={`${group.slug}:${company.slug}`} company={company} sectorSlug={group.slug} />
        ))}
    </section>
  );
}
