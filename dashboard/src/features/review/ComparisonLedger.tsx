import { Button } from "../../ui/Button";
import { Fragment, useEffect, useState } from "react";
import type { Job } from "../../api";
import { BAND_LABEL, WORKPLACE_LABEL, fmtCompIn, fmtDate, relDays } from "../../format";
import { number } from "../../copy/format";
import { roleName, statusName } from "../../copy/vocab";
import { postingPlaces } from "../../patterns/jobs/location";
import { useJobActions } from "../../context/JobWorkspace";
import { JobLinkRow } from "../../patterns/jobs/JobLinkRow";
import { Icon } from "../../ui";
import { ExternalLink } from "../../ui/ExternalLink";
import { type PayCover, usePayCoverage } from "../../payCoverage";
import { payShown } from "../../payShown";
import { Abbr } from "../../ui/Abbr";
import { sharedEstTcFull } from "../../copy/gen/shared";
import { type LedgerRow, groupLedger, rowDiffers } from "../../patterns/ledger";
import {
  duplicatesComparisonLedgerAge,
  duplicatesComparisonLedgerCareersPage,
  duplicatesComparisonLedgerCareersPageOf,
  duplicatesComparisonLedgerCompEst,
  duplicatesComparisonLedgerDepartment,
  duplicatesComparisonLedgerDifferent,
  duplicatesComparisonLedgerDisclosedBand,
  duplicatesComparisonLedgerEarlierPosting,
  duplicatesComparisonLedgerFamily,
  duplicatesComparisonLedgerField,
  duplicatesComparisonLedgerFields,
  duplicatesComparisonLedgerFirstSeen,
  duplicatesComparisonLedgerLastObserved,
  duplicatesComparisonLedgerLevel,
  duplicatesComparisonLedgerLinks,
  duplicatesComparisonLedgerLocations,
  duplicatesComparisonLedgerNewerPosting,
  duplicatesComparisonLedgerNotDisclosed,
  duplicatesComparisonLedgerRoleDetails,
  duplicatesComparisonLedgerRoleDetailsOf,
  duplicatesComparisonLedgerSame,
  duplicatesComparisonLedgerShow,
  duplicatesComparisonLedgerShowMatchingFields,
  duplicatesComparisonLedgerSideBySide,
  duplicatesComparisonLedgerStatus,
  duplicatesComparisonLedgerTeam,
  duplicatesComparisonLedgerTitle,
  duplicatesComparisonLedgerWorkplace,
} from "../../copy/gen/duplicates";

/* The structured field-by-field comparison of a candidate pair, on the
 * shared ledger model (patterns/ledger): runs of agreeing secondary fields
 * fold into one counted row, so the eye lands on what differs. The title
 * never folds. The requisition ID is not a row: identity is `company:req_id`,
 * so the two postings of a pair always differ on it, and a row that always
 * says Different is no evidence. The Decided list still shows and searches it.
 * Each column's links follow the fields, outside the comparison. */

type ComparisonRow = LedgerRow<Job> & { value: (job: Job) => string };

export function ComparisonLedger({ prior, job }: { prior: Job; job: Job }) {
  const rows = comparisonRows(usePayCoverage());
  const pair = [prior, job] as const;
  const groups = groupLedger(rows, pair);
  const [expandedRuns, setExpandedRuns] = useState<Set<string>>(new Set());

  useEffect(() => setExpandedRuns(new Set()), [prior.id, job.id]);

  const toggleRun = (key: string) => {
    setExpandedRuns((current) => {
      const next = new Set(current);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

  return (
    <section className="review-ledger-wrap" aria-label={duplicatesComparisonLedgerSideBySide()}>
      {/* The roles are stated, not left to the elements: review.css lays the
          rows out as grids, and an engine that sees a display change on a
          table part (WebKit) drops its table semantics. */}
      <table className="review-ledger" role="table">
        <thead role="rowgroup">
          <tr role="row">
            <th scope="col" role="columnheader">{duplicatesComparisonLedgerField()}</th>
            <th scope="col" role="columnheader"><span>{duplicatesComparisonLedgerEarlierPosting()}</span></th>
            <th scope="col" role="columnheader"><span>{duplicatesComparisonLedgerNewerPosting()}</span></th>
          </tr>
        </thead>
        <tbody role="rowgroup">
          {groups.map((group) => {
            if (group.kind === "row") return <ComparisonLedgerRow key={group.row.key} row={group.row} pair={pair} />;
            const runKey = `${group.rows[0].key}-${group.rows[group.rows.length - 1].key}`;
            const open = expandedRuns.has(runKey);
            return (
              <Fragment key={runKey}>
                <tr className={`is-same review-ledger-run${open ? " is-expanded" : ""}`} role="row">
                  <th scope="row" role="rowheader"><strong>{group.rows.length}</strong><span>{duplicatesComparisonLedgerFields()}</span></th>
                  <td colSpan={2} className="review-ledger-shared" role="cell">
                    <span className="review-ledger-same">{duplicatesComparisonLedgerSame()}</span>
                    <span className="review-ledger-run-range">{group.rows[0].label}–{group.rows[group.rows.length - 1].label}</span>
                    <Button
                      variant="link"
                      className="review-ledger-run-toggle"
                      aria-expanded={open}
                      aria-label={duplicatesComparisonLedgerShowMatchingFields({ choice: (open) ? "yes" : "no", length: group.rows.length })}
                      onClick={() => toggleRun(runKey)}
                    >
                      {duplicatesComparisonLedgerShow({ choice: (open) ? "yes" : "no" })}
                      <Icon name={open ? "chevronUp" : "chevronDown"} size={14} />
                    </Button>
                  </td>
                </tr>
                {open && group.rows.map((row) => <ComparisonLedgerRow key={row.key} row={row} pair={pair} runDetail />)}
              </Fragment>
            );
          })}
          <ComparisonLedgerLinks pair={pair} />
        </tbody>
      </table>
    </section>
  );
}

function ComparisonLedgerRow(
  { row, pair, runDetail = false }: { row: ComparisonRow; pair: readonly [Job, Job]; runDetail?: boolean },
) {
  const same = !rowDiffers(row, pair);
  const cell = (side: 0 | 1) => row.value(pair[side]);
  return (
    <tr className={`${same ? "is-same" : "is-different"}${row.key === "title" ? " is-title" : ""}${runDetail ? " is-run-detail" : ""} row-${row.key}`} role="row">
      <th scope="row" role="rowheader">
        <span>{row.fullLabel ? <Abbr short={row.label} full={row.fullLabel} /> : row.label}</span>
        {!same && <small>{duplicatesComparisonLedgerDifferent()}</small>}
      </th>
      {same ? (
        <td colSpan={2} className="review-ledger-shared" role="cell">
          <span className="review-ledger-same">{duplicatesComparisonLedgerSame()}</span>
          {cell(0)}
        </td>
      ) : (
        <>
          <td role="cell">{cell(0)}</td>
          <td role="cell">{cell(1)}</td>
        </>
      )}
    </tr>
  );
}

/* Where each posting can be read in full. Two destinations that must not be
   mistaken for each other: the role in the app opens over the queue, so Back
   returns to this pair; the employer's careers page leaves the app in a new
   tab, wearing the external glyph. Their addresses always differ, so the row
   is never compared. */
function ComparisonLedgerLinks({ pair }: { pair: readonly [Job, Job] }) {
  const { openJob } = useJobActions();
  const sides = ["earlier", "newer"] as const;
  return (
    <tr className="row-links" role="row">
      <th scope="row" role="rowheader"><span>{duplicatesComparisonLedgerLinks()}</span></th>
      {pair.map((job, i) => (
        <td key={job.id} role="cell">
          <JobLinkRow
            className="ui-btn ui-btn-ghost ui-btn-sm"
            jobId={job.id}
            company={job.company}
            onOpen={openJob}
            aria-label={duplicatesComparisonLedgerRoleDetailsOf({ side: sides[i] })}
          >
            {duplicatesComparisonLedgerRoleDetails()}
          </JobLinkRow>
          {job.url && (
            <ExternalLink href={job.url} label={duplicatesComparisonLedgerCareersPageOf({ side: sides[i] })}>
              {duplicatesComparisonLedgerCareersPage()}
            </ExternalLink>
          )}
        </td>
      ))}
    </tr>
  );
}

/** A row compared by what it shows. */
function row(key: string, label: string, show: (job: Job) => string, collapsible = true): ComparisonRow {
  return { key, label, value: show, diff: show, collapsible };
}

function comparisonRows(cover: PayCover | null): ComparisonRow[] {
  const observed = (value: Job) => fmtDate(value.status === "closed" ? value.closed_at : value.last_seen);
  return [
    row("title", duplicatesComparisonLedgerTitle(), (j) => j.title, false),
    row("status", duplicatesComparisonLedgerStatus(), (j) => statusName(j.status) ?? j.status),
    row("level", duplicatesComparisonLedgerLevel(), (j) => BAND_LABEL[j.level_band] ?? j.level_band),
    row("family", duplicatesComparisonLedgerFamily(), (j) => roleName(j.family)),
    row("locations", duplicatesComparisonLedgerLocations(), (j) => postingPlaces(j.locations).join(" · ") || "—"),
    row("workplace", duplicatesComparisonLedgerWorkplace(), (j) => WORKPLACE_LABEL[j.workplace_type] ?? j.workplace_type),
    row("department", duplicatesComparisonLedgerDepartment(), (j) => j.department ?? "—"),
    row("team", duplicatesComparisonLedgerTeam(), (j) => j.team ?? "—"),
    { ...row("estimated-comp", duplicatesComparisonLedgerCompEst(), (j) => payShown(j, cover).text), fullLabel: sharedEstTcFull() },
    row("disclosed-comp", duplicatesComparisonLedgerDisclosedBand(), disclosedBand),
    row("first-seen", duplicatesComparisonLedgerFirstSeen(), (j) => fmtDate(j.first_seen)),
    row("last-observed", duplicatesComparisonLedgerLastObserved(), observed),
    row("age", duplicatesComparisonLedgerAge(), (j) => relDays(j.listed_days)),
  ];
}

/* The employer's band in the currency it was posted in. A band that names no
 * currency shows its figures alone: a symbol would claim a currency the
 * posting never stated. */
function disclosedBand(job: Job): string {
  const band = job.disclosed_comp;
  if (!band?.disclosed) return duplicatesComparisonLedgerNotDisclosed();
  const amount = (n: number) =>
    band.currency ? fmtCompIn(n, band.currency) : number(n, { notation: "compact", maximumFractionDigits: 2 });
  const figures = [band.base_min, band.base_max].filter((n): n is number => n != null).map(amount);
  return figures.length > 0 ? figures.join("–") : duplicatesComparisonLedgerNotDisclosed();
}
