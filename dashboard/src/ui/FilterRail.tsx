import { compare as copyCompare } from "../copy/format";
import { ReactNode, createContext, useCallback, useContext, useState } from "react";
import { useDisclosureMemory, type DisclosureMemory } from "../hooks/useFilterMemory";
import { Button } from "./Button";
import { Icon } from "./Icon";
import {
  sharedFilterRailClear,
  sharedFilterRailMore,
  sharedFilterRailNoOptionsMatch,
  sharedFilterRailSearch,
  sharedFilterRailSearch2,
  sharedFilterRailSelectAll,
  sharedFilterRailSelectAll2,
  sharedFilterRailShowAll,
  sharedFilters,
} from "../copy/gen/shared";
import "./FilterRail.css";
import { Msg } from "./Msg";

/* The filter register — every way to narrow a list, in one column, with its
 * state worn on its sleeve. The Board and Notifications both render it, so
 * the pieces live here.
 *
 * One register, two homes: a screen renders it as the left rail at rail widths
 * and inside its toolbar's Filters panel below them (`useMediaQuery(RAIL_QUERY)`
 * decides — never both, so every checkbox and label exists once). Selection
 * grammar is the app's: checkbox rows with counts, Segmented for one-of lenses,
 * `aria-pressed`/checked as the single source of "currently on".
 *
 * What is here: the group anatomy (a KICKER over a control, a GROUP HEAD you
 * open over rows), the reset row, and the narrow home's scrim + panel. What is
 * NOT here: the shell that places the rail beside the list (patterns/
 * RailShell), whose sticky offset is keyed to each screen's own measured
 * toolbar height.
 */

/** Rail widths: the register stands beside the list. Below, it folds into the
 * toolbar's Filters panel. patterns/rail-shell.css names the same boundary in
 * its shell guard (patterns/rail-shell.test.ts fails if the two drift). */
export const RAIL_QUERY = "(min-width: 1360px)";

/** Above this an expanded facet also grows a search row. */
const SEARCH_THRESHOLD = 7;

/* ---- the register itself: one scope, and what it remembers ---------------- */

/* `/*#__PURE__*\/` is load-bearing, not decoration. A bare module-level call
 * is a side effect as far as the bundler can prove, so this one line pinned the
 * whole of FilterRail — and, through it, `hooks/filterMemory` — into the app
 * shell's eager chunk, for a register no shell module renders. */
const RegisterMemory = /*#__PURE__*/ createContext<DisclosureMemory | null>(null);

/** THE register. Wrap a screen's groups in one of these and every disclosure
 *  inside remembers whether this reader opened it (`hooks/useFilterMemory`).
 *
 *  Every group rests CLOSED. Company, Location and Level open by default would
 *  be the right default for a reader who filters by company every session and
 *  the wrong one for everybody else: three open lists above the fold, most of
 *  them scrolled past. A default is a guess about a reader; memory is that
 *  reader's own answer, and it outlives the guess. So the ranking is an ORDER
 *  — always-tier groups first, situational ones behind `More filters` — and
 *  not a claim about what is worth opening.
 *
 *  Without a register around them the groups still work; they just forget
 *  between mounts, which is what a one-off filter surface wants. */
export function FilterRegister({
  scope,
  className,
  children,
}: {
  /** Storage key for this screen's disclosures: "board", "notifications". */
  scope: string;
  className?: string;
  children: ReactNode;
}) {
  const memory = useDisclosureMemory(scope);
  return (
    <RegisterMemory.Provider value={memory}>
      {/* The register's own heading, for the outline only: the
          screen's h1 is above it and its groups are h3, so without this the
          outline would jump h1 -> h3 (axe `heading-order`). The aside that carries the rail is already
          labelled "Filters"; this is the same word inside the outline, where
          a reader stepping through headings meets it. */}
      <div className={className}>
        <h2 className="sr-only">{sharedFilters()}</h2>
        {children}
      </div>
    </RegisterMemory.Provider>
  );
}

/** Open state for one group: the register's memory when there is one, this
 *  component's own state when there is not. Both hooks run unconditionally —
 *  only which answer is returned depends on the context. */
function useGroupDisclosure(id: string, fallback: boolean): [boolean, (open: boolean) => void] {
  const memory = useContext(RegisterMemory);
  const [local, setLocal] = useState(fallback);
  const setOpen = useCallback(
    (next: boolean) => (memory ? memory.setOpen(id, next) : setLocal(next)),
    [memory, id],
  );
  return [memory ? memory.isOpen(id, fallback) : local, setOpen];
}

export interface FacetEntry {
  slug: string;
  display: string;
  count: number;
  /** Nesting depth, for a facet the taxonomy nests (a metro under its
   *  country). The caller flattens its own tree — the register only indents
   *  what it is handed, so one facet cannot invent a second tree grammar. */
  depth?: number;
}

/** Selected first, then by count, then name — the scan order for a list whose
 * top rows are the only ones visible while collapsed. */
export function bySelection(selected: string[]) {
  return (a: FacetEntry, b: FacetEntry) => {
    const sa = selected.includes(a.slug) ? 1 : 0;
    const sb = selected.includes(b.slug) ? 1 : 0;
    if (sa !== sb) return sb - sa;
    if (a.count !== b.count) return b.count - a.count;
    return copyCompare(a.display, b.display);
  };
}

/** A KICKER names a control block (whisper, muted, never a button) — the home
 * of a Segmented lens or a range row. */
export function FilterGroup({ title, children }: { title: ReactNode; children: ReactNode }) {
  return (
    <div className="filter-group">
      {/* A heading INSIDE a control surface is a field label, not a section
          title — "Comp from", "Posted within", "Status". The element rule in
          shell.css leaves headings selectable because a section title is
          content a reader may quote; a register's group name is the name of
          the control under it. */}
      <h3 data-selection="chrome">{title}</h3>
      {children}
    </div>
  );
}

/* One facet as a DISCLOSURE: a group whose
   filter is not in use offers nothing worth a list, so at rest it is one
   headline. What the register still refuses to hide is STATE: an active group
   wears its count on the headline and its chosen rows stay visible (and
   un-checkable) while collapsed; expanding shows the full option list, with a
   search row on the long facets.

   Every facet rests CLOSED and remembers being opened — see `FilterRegister`.
   `foldAfter` still ranks the OPEN state: a long facet shows the head of its
   list with a "+ N more" rather than all forty rows at once. */
export function FacetGroup({
  id,
  title,
  ariaLabel,
  entries,
  selected,
  onChange,
  searchable = false,
  emptyText = sharedFilterRailNoOptionsMatch(),
  foldAfter,
}: {
  /** Stable key for this group's remembered open state. Defaults to the
   *  title, which is unique within a register; pass one when the title is
   *  data-driven or two registers in a scope share a word. */
  id?: string;
  title: string;
  ariaLabel: string;
  entries: FacetEntry[];
  selected: string[];
  onChange: (next: string[]) => void;
  searchable?: boolean;
  emptyText?: string;
  /** Show this many rows of an open facet, then "+ N more". A chosen row is
   *  never folded away — the fold grows to the selection instead, because a
   *  register that hides what it is doing is the one thing this column may not
   *  do. */
  foldAfter?: number;
}) {
  const [expanded, setExpanded] = useGroupDisclosure(id ?? title, false);
  const [unfolded, setUnfolded] = useState(false);
  const [query, setQuery] = useState("");

  const q = query.trim().toLowerCase();
  const matched = q
    ? entries.filter((e) => e.display.toLowerCase().includes(q) || e.slug.includes(q))
    : entries;
  // A search is already a fold, and a stricter one: never fold its results.
  const limit = foldAfter == null || unfolded || q ? null : Math.max(foldAfter, selected.length);
  const open = expanded ? (limit == null ? matched : matched.slice(0, limit)) : [];
  // Only an OPEN group folds. A collapsed one is already showing nothing but
  // its state, and offering "+ 8 more" under a headline you have not opened
  // would be a second, quieter disclosure for the same list.
  const hidden = expanded && limit != null ? matched.length - open.length : 0;
  const rows = expanded ? open : entries.filter((e) => selected.includes(e.slug));
  const allSelected = entries.length > 0 && entries.every((e) => selected.includes(e.slug));

  const toggle = (slug: string) =>
    onChange(selected.includes(slug) ? selected.filter((s) => s !== slug) : [...selected, slug]);

  return (
    <div className="filter-group" role="group" aria-label={ariaLabel}>
      {/* The GROUP HEAD: a row you open, not a kicker. */}
      <h3 className="filter-head">
        <button
          type="button"
          className="filter-title"
          onClick={() => {
            // Closing puts the group back to how it opens: no search, folded.
            // Read from the rendered value rather than from a state updater:
            // an updater that also calls two other setters is not pure, and
            // StrictMode runs it twice (it also cannot see the register's
            // memory, which is not this component's state).
            if (expanded) {
              setQuery("");
              setUnfolded(false);
            }
            setExpanded(!expanded);
          }}
          aria-expanded={expanded}
          // Flex children concatenate without spaces in name computation, so
          // the counted name is stated whole ("Company · 1", never "Company·1").
          aria-label={selected.length > 0 ? `${title} · ${selected.length}` : undefined}
        >
          <Icon name={expanded ? "chevronUp" : "chevronDown"} size={14} />
          {title}
          {selected.length > 0 && <span className="filter-title-count">· {selected.length}</span>}
        </button>
        {selected.length > 0 && (
          <Button variant="link" className="ui-btn-quiet" onClick={() => onChange([])}>
            {sharedFilterRailClear()}
          </Button>
        )}
      </h3>
      {expanded && searchable && entries.length > SEARCH_THRESHOLD && (
        <div className="filter-search-row">
          <Icon name="search" size={14} />
          <input
            type="search"
            aria-label={sharedFilterRailSearch({ title: String(title.toLowerCase()) })}
            placeholder={sharedFilterRailSearch2({ title: String(title.toLowerCase()) })}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </div>
      )}
      {rows.map((r) => (
        <label className={`check-row${r.depth ? " is-child" : ""}`} key={r.slug}>
          <input
            type="checkbox"
            aria-label={r.display}
            checked={selected.includes(r.slug)}
            onChange={() => toggle(r.slug)}
          />
          <span>{r.display}</span>
          <span className="cnt">{r.count}</span>
        </label>
      ))}
      {expanded && matched.length === 0 && <div className="filter-hint">{emptyText}</div>}
      {hidden > 0 && (
        <Button
          variant="link"
          className="ui-btn-quiet filter-more"
          aria-label={sharedFilterRailShowAll({ title: String(title.toLowerCase()) })}
          onClick={() => setUnfolded(true)}
        >
          <Msg of={sharedFilterRailMore} elems={{ hidden: hidden }} />
        </Button>
      )}
      {expanded && !allSelected && entries.length > 1 && (
        <Button
          variant="link"
          className="ui-btn-quiet filter-more"
          aria-label={sharedFilterRailSelectAll2({ title: String(title) })}
          onClick={() => onChange(entries.map((e) => e.slug))}
        >
          {sharedFilterRailSelectAll()}
        </Button>
      )}
    </div>
  );
}

/* A door over a set of GROUPS. Same head as a facet — chevron,
 * name, live count, the 32px row — so a register has one disclosure grammar
 * and not two; what it opens is other groups rather than checkbox rows.
 *
 * It refuses to hide STATE for the same reason a facet does: if anything
 * inside is on, it opens itself. A count on a closed door tells the reader
 * that something is narrowing their list without telling them what, which is
 * the failure this whole column exists to avoid.
 */
export function FilterDrawer({ id, title, count, children }: {
  /** Stable key for the remembered open state; defaults to the title. */
  id?: string;
  title: string;
  /** Active filters inside. Non-zero forces the drawer open. */
  count: number;
  children: ReactNode;
}) {
  const [opened, setOpened] = useGroupDisclosure(id ?? title, false);
  const expanded = opened || count > 0;
  return (
    <div className="filter-group filter-drawer">
      <h3 className="filter-head">
        <button
          type="button"
          className="filter-title"
          onClick={() => setOpened(!opened)}
          aria-expanded={expanded}
          aria-label={count > 0 ? `${title} · ${count}` : undefined}
        >
          <Icon name={expanded ? "chevronUp" : "chevronDown"} size={14} />
          {title}
          {count > 0 && <span className="filter-title-count">· {count}</span>}
        </button>
      </h3>
      {expanded && <div className="filter-drawer-body">{children}</div>}
    </div>
  );
}
