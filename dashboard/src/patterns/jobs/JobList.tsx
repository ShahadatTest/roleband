import {
  jobsHeadLocation,
  jobsHeadPay,
  jobsHeadRole,
  jobsSortBy,
  jobsSortByAscending,
  jobsSortByDescending,
  jobsSortLabelAbbr,
} from "../../copy/gen/jobs";
import { sharedBaseSalaryFull } from "../../copy/gen/shared";
import { useRef } from "react";
import type { JobSort, SortOrder } from "../../api";
import { Icon } from "../../ui";
import { Abbr } from "../../ui/Abbr";
import "./job-row.css";

// Sortable columns exposed as clickable headers, in render order. A key is a
// `JobSort`, the set `/api/jobs` publishes from the backend's SORT_COLUMNS
// registry, so one the route does not accept fails `tsc`; it also needs a
// label in the BoardToolbar SORTS list. Adding a sortable column is one entry
// here (plus its header cell). Age has no column (it sits under the numeral),
// so its sort lives in the toolbar's Sort select alone.
const SORTABLE_HEADERS: { key: JobSort; className: string }[] = [
  { key: "location", className: "col-loc" },
  { key: "base_pay", className: "col-comp" },
];

export interface SortControl {
  sort: JobSort;
  order: SortOrder;
  onSort: (key: JobSort) => void;
}

function HeaderCell({
  label,
  full,
  sortKey,
  className,
  control,
}: {
  label: string;
  /** The full words behind a short label, for hover and the accessible name. */
  full?: string;
  sortKey: JobSort;
  className: string;
  control?: SortControl;
}) {
  const shown = full ? <Abbr short={label} full={full} /> : label;
  if (!control) return <span className={className}>{shown}</span>;
  // The name keeps the visible short form so a voice user can say what they
  // see (WCAG 2.5.3), and adds the full words a screen reader needs.
  const spoken = full ? jobsSortLabelAbbr({ short: label, full }) : label;
  const active = control.sort === sortKey;
  const arrow = active ? (control.order === "asc" ? "arrowUp" : "arrowDown") : null;
  // `aria-sort` is legal only on a real column-header role, and this head is a
  // div grid — on a button element it is invalid ARIA that tooling flags and
  // readers may drop. The state rides the app's own "currently on" convention
  // instead (aria-pressed, docs/ui.md), with the direction in the NAME,
  // which every reader announces.
  return (
    <span className={className}>
      <button
        type="button"
        className="col-sort"
        aria-pressed={active}
        aria-label={active ? (control.order === "asc" ? jobsSortByAscending : jobsSortByDescending)({ label: spoken }) : jobsSortBy({ label: spoken })}
        onClick={() => control.onSort(sortKey)}
      >
        {shown}
        <span className="col-sort-arrow" aria-hidden="true">
          {arrow && <Icon name={arrow} size={11} />}
        </span>
      </button>
    </span>
  );
}

/* The signal list: one bordered surface, a sticky column-header strip, and
   hairline-divided rows. Owns column geometry (--row-cols) and arrow-key /
   j-k focus movement across rows. When `sortControl` is supplied the Location
   and comp headers become clickable sort toggles with an active arrow. */
export function JobList({
  children,
  sortControl,
}: {
  children: React.ReactNode;
  sortControl?: SortControl;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const labels: Record<string, string> = {
    location: jobsHeadLocation(),
    base_pay: jobsHeadPay(),
  };
  const fullLabels: Record<string, string> = { base_pay: sharedBaseSalaryFull() };

  const onKeyDown = (e: React.KeyboardEvent) => {
    // With a modifier the key is someone else's: Cmd+K opens the palette and
    // must not also move focus a row.
    if (e.metaKey || e.ctrlKey || e.altKey) return;
    const key = e.key.toLowerCase();
    const down = e.key === "ArrowDown" || key === "j";
    const up = e.key === "ArrowUp" || key === "k";
    if (!down && !up) return;
    const target = e.target as HTMLElement;
    if (target.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName)) return;
    const rows = Array.from(ref.current?.querySelectorAll<HTMLElement>(".job-row") ?? []);
    if (rows.length === 0) return;
    e.preventDefault();
    const active = document.activeElement as HTMLElement | null;
    const current = rows.findIndex((r) => r === active || r.contains(active));
    const next = current === -1 ? 0 : Math.min(Math.max(current + (down ? 1 : -1), 0), rows.length - 1);
    rows[next].focus();
  };

  return (
    <div className="job-list" ref={ref} onKeyDown={onKeyDown}>
      <div className="list-head" data-selection="chrome" aria-hidden={sortControl ? undefined : true}>
        <span>{jobsHeadRole()}</span>
        {SORTABLE_HEADERS.map((h) => (
          <HeaderCell
            key={h.key}
            label={labels[h.key]}
            full={fullLabels[h.key]}
            sortKey={h.key}
            className={h.className}
            control={sortControl}
          />
        ))}
        <span />
      </div>
      {children}
    </div>
  );
}
