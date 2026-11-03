import {
  radarFieldCareerTrack,
  radarFieldCompany,
  radarFieldDiscipline,
  radarFieldLevel,
  radarFieldLocation,
  radarFieldWorkplace,
  radarFieldWorld,
  radarFilterAny,
  radarFilterCompanyAria,
  radarFilterDays,
  radarFilterDisclosesPay,
  radarFilterDisciplineAria,
  radarFilterLevelAria,
  radarFilterListedWithin,
  radarFilterLocationAria,
  radarFilterMax,
  radarFilterMin,
  radarFilterMore,
  radarFilterNoCompanies,
  radarFilterNoLocations,
  radarFilterPayFrom,
  radarFilterPayFromFull,
  radarFilterPayMaxAria,
  radarFilterPayMinAria,
  radarFilterPayUpTo,
  radarFilterPayUpToFull,
  radarFilterShowing,
  radarFiltersLoadFailed,
  radarFilterTrackAria,
  radarFilterUnreadOnly,
  radarFilterWorkplaceAria,
  radarFilterWorldAria,
  radarInterpPayMax,
  radarInterpPayMin,
} from "../../copy/gen/radar";
import { Facets, Filters } from "../../api";
import { Abbr } from "../../ui/Abbr";
import { LEVEL_NOT_PLACED_OPTION, UNSTATED_LEVEL } from "../../copy/vocabulary";
import { BAND_LABEL, BAND_ORDER, LOC_LABEL, WORKPLACE_LABEL, fmtComp, ownValue } from "../../format";
import {
  FacetGroup, FilterDrawer, FilterGroup, FilterRegister, ResourceLoadState, Segmented, Switch, bySelection,
} from "../../ui";
import {
  BOARD_MEMORY_SCOPE, BOARD_MODES, MODE_LABEL, countSituationalFilters, type BoardMode,
} from "./filters";
import { domainName, roleName, trackName } from "../../copy/vocab";
import { useEffect, useRef, useState } from "react";

/** How long a typed pay bound settles before it is asked for: the header
 *  search box's pause, so "250000" is one request, not six. */
export const PAY_SETTLE_MS = 250;

/** A pay bound the reader types digit by digit. Its draft is committed once
 *  typing settles, or at once on Enter or on leaving the field; an edit from
 *  elsewhere (the toolbar's reset, a remembered filter) replaces the draft. */
function PayBound({ value, onCommit, placeholder, label }: {
  value: number | null;
  onCommit: (next: number | null) => void;
  placeholder: string;
  label: string;
}) {
  const shown = value == null ? "" : String(value);
  const [draft, setDraft] = useState(shown);
  useEffect(() => setDraft(shown), [shown]);
  const commitRef = useRef(onCommit);
  commitRef.current = onCommit;
  const commit = (text: string) => {
    if (text !== shown) commitRef.current(text ? Number(text) : null);
  };
  useEffect(() => {
    if (draft === shown) return;
    const timer = window.setTimeout(() => commitRef.current(draft ? Number(draft) : null), PAY_SETTLE_MS);
    return () => window.clearTimeout(timer);
  }, [draft, shown]);
  return (
    <input
      type="number"
      placeholder={placeholder}
      aria-label={label}
      value={draft}
      onChange={(e) => setDraft(e.target.value)}
      onBlur={() => commit(draft)}
      onKeyDown={(e) => { if (e.key === "Enter") commit(draft); }}
    />
  );
}

/* The board's filter register: every way to narrow the list, in one column,
 * with its state worn on its sleeve. This is the register/settings idiom
 * (the sector index, the /company selector) applied to filtering: a column
 * has room to show WHICH values are on, where a button in a horizontal bar
 * could only say "Location · 2".
 *
 * One component, two homes: the Board renders it as the left rail at rail
 * widths and inside the toolbar's Filters panel below them (useMediaQuery
 * decides, never both, so labels and checkboxes exist once). Selection
 * grammar is the app's: checkbox rows with counts, seg for one-of lenses,
 * `aria-pressed`/checked as the single source of "currently on".
 *
 * The MODE (which population the board shows) is a different kind of
 * question from the narrowing groups, so it sits last, at the foot of
 * `More filters`, as one exclusive control.
 */

export function BoardFilters({
  facets,
  facetsError,
  onRetryFacets,
  filters,
  update,
  mode,
  onModeChange,
}: {
  facets: Facets | null;
  /** Why the register has no vocabulary. Without it a failed facets fetch is
   *  indistinguishable from loading, and the whole register would vanish with
   *  nothing to click and no way back. */
  facetsError?: Error | null;
  onRetryFacets?: () => void;
  filters: Filters;
  update: (patch: Partial<Filters>) => void;
  /** The mode is URL state, so the register ASKS for it rather than patching
   *  `filters`: one writer, no loop. */
  mode: BoardMode;
  onModeChange: (mode: BoardMode) => void;
}) {
  if (facetsError) {
    return (
      <div className="board-filters">
        <ResourceLoadState error={facetsError} failed={radarFiltersLoadFailed()} onRetry={onRetryFacets} />
      </div>
    );
  }
  if (!facets) return null;

  const companyEntries = Object.entries(facets.companies)
    .map(([slug, meta]) => ({
      slug,
      display: meta.display,
      count: ownValue(facets.counts.company, slug) ?? 0,
    }))
    .sort(bySelection(filters.company));

  /* Locations nest, so the register renders them nested, and drops the ones
     that cannot narrow: a value whose count equals the board's total (a
     country every role is in) changes nothing when chosen, and a facet that
     visibly does nothing teaches the reader that facets do not work. A group
     whose parent was dropped rises to the top level, which is why depth is
     computed against what SURVIVES rather than against the taxonomy. */
  // No total, no claim: "this value matches the WHOLE board" is a statement
  // about a number, and an API that has not sent one (an older backend, a
  // partial response) leaves every option offered rather than none. Without
  // the guard, `count < undefined` is false for every group and the entire
  // Location facet would vanish from the rail.
  const boardTotal = typeof facets.total === "number" && facets.total > 0 ? facets.total : null;
  const offeredLocations = Object.keys(facets.location_groups).filter(
    (slug) => boardTotal == null || (facets.counts.location_group[slug] ?? 0) < boardTotal,
  );
  const locDepth = (slug: string): number => {
    let depth = 0;
    let parent = facets.location_groups[slug]?.parent;
    // The taxonomy is a tree, but this walks data from the wire: bound the
    // climb rather than trusting it, or one bad `parent` hangs the register.
    while (parent && offeredLocations.includes(parent) && depth < 4) {
      depth += 1;
      parent = facets.location_groups[parent]?.parent;
    }
    return depth;
  };
  const locEntries = offeredLocations
    .map((s) => ({
      slug: s,
      display: LOC_LABEL[s] ?? facets.location_groups[s]?.display ?? s,
      count: facets.counts.location_group[s] ?? 0,
      depth: locDepth(s),
    }))
    // Parents before their children, then the register's own scan order.
    .sort((a, b) => a.depth - b.depth || bySelection(filters.location_group)(a, b));

  // Worlds (domain axis). "Unclassified" sorts last — the fail-open bucket is
  // not a world, but it must stay findable.
  const domainEntries = Object.keys(facets.domains ?? {})
    .map((s) => ({
      slug: s,
      display: domainName(s),
      count: facets.counts.domain?.[s] ?? 0,
    }))
    .sort((a, b) => {
      if (a.slug === "unclassified") return 1;
      if (b.slug === "unclassified") return -1;
      return bySelection(filters.domain)(a, b);
    });

  // Bands keep their ladder order — seniority is a scale, not a ranking by count.
  // Roles whose posting names no level come last, under their own key: the
  // server stores them at Mid for sorting only and never counts them as Mid.
  const bandEntries = [...BAND_ORDER, UNSTATED_LEVEL]
    .filter((b) => facets.counts.level_band[b] != null)
    .map((b) => ({
      slug: b,
      display: b === UNSTATED_LEVEL ? LEVEL_NOT_PLACED_OPTION() : BAND_LABEL[b] ?? b,
      count: facets.counts.level_band[b] ?? 0,
    }));

  const wpEntries = Object.keys(facets.counts.workplace_type)
    .filter((w) => w !== "unknown")
    .map((w) => ({
      slug: w,
      display: WORKPLACE_LABEL[w] ?? w,
      count: facets.counts.workplace_type[w] ?? 0,
    }));

  const trackEntries = Object.keys(facets.tracks ?? {}).map((slug) => ({
    slug,
    display: trackName(slug),
    count: facets.counts.track?.[slug] ?? 0,
  }));

  const familyEntries = Object.keys(facets.families).map((slug) => ({
    slug,
    display: roleName(slug),
    count: facets.counts.family[slug] ?? 0,
  }));

  return (
    <FilterRegister scope={BOARD_MEMORY_SCOPE} className="board-filters">
      {/* No headline and no head row: the column explains itself, and the
          undo lives beside the count in the toolbar. */}
      {/* The reader's OWN mark leads the register: the first thing someone
          hunting for the role they have not opened yet wants gone is every
          role they have. A SWITCH: this is one boolean, and a four-way
          All / Unread / Read / Not for me would ask the reader to decide a
          non-choice in the loudest control the column has, resting on its
          default. "Read only" is history rather than a hunt (the API keeps
          `viewed=read`), and "Not for me" is a POPULATION rather than a
          lens. */}
      <div className="board-unread">
        <Switch
          checked={filters.viewed === "unread"}
          onChange={(on) => update({ viewed: on ? "unread" : "", offset: 0 })}
        >
          <span>{radarFilterUnreadOnly()}</span>
        </Switch>
      </div>

      {/* The three facets a reader narrows by every session, first, and
          CLOSED, like every other group. Resting them open would save clicks
          on a facet in constant use and cost three open lists above the fold
          for every reader, including the ones who never touch Company. The
          ranking is the ORDER; whether a group is open is the reader's own
          answer and is remembered (ui/FilterRegister).

          Company folds at five once opened: the head of a list sorted
          selected-first, then by count. A chosen row is never folded away, so
          a remembered selection is visible with the group shut. */}
      <FacetGroup
        title={radarFieldCompany()}
        ariaLabel={radarFilterCompanyAria()}
        entries={companyEntries}
        selected={filters.company}
        onChange={(next) => update({ company: next, offset: 0 })}
        searchable
        foldAfter={5}
        emptyText={radarFilterNoCompanies()}
      />
      {locEntries.length > 0 && (
        <FacetGroup
          title={radarFieldLocation()}
          ariaLabel={radarFilterLocationAria()}
          entries={locEntries}
          selected={filters.location_group}
          onChange={(next) => update({ location_group: next, offset: 0 })}
          searchable
          foldAfter={6}
          emptyText={radarFilterNoLocations()}
        />
      )}
      {bandEntries.length > 0 && (
        <FacetGroup
          title={radarFieldLevel()}
          ariaLabel={radarFilterLevelAria()}
          entries={bandEntries}
          selected={filters.level_band}
          onChange={(next) => update({ level_band: next, offset: 0 })}
        />
      )}

      {/* Everything a reader opens to answer ONE question and then closes.
          Ordered by how often that question is asked, and the two
          facets whose data is mostly unknown come last saying so — a facet
          that answers "unclassified" half the time has to admit it, or the
          reader learns that facets do not work. */}
      <FilterDrawer title={radarFilterMore()} count={countSituationalFilters(filters)}>
        {familyEntries.length > 0 && (
          <FacetGroup
            title={radarFieldDiscipline()}
            ariaLabel={radarFilterDisciplineAria()}
            entries={familyEntries}
            selected={filters.family}
            onChange={(next) => update({ family: next, offset: 0 })}
          />
        )}
        {trackEntries.length > 0 && (
          <FacetGroup
            title={radarFieldCareerTrack()}
            ariaLabel={radarFilterTrackAria()}
            entries={trackEntries}
            selected={filters.track}
            onChange={(next) => update({ track: next, offset: 0 })}
          />
        )}

        <FilterGroup title={radarFilterListedWithin()}>
          {/* A genuine one-of, so a segmented control: four values,
              exclusive, all four worth a click. A boolean takes a Switch,
              never a pill pair. The primitive is already the scale's `sm`
              rank, so there is no size to pass. */}
          <Segmented
            label={radarFilterListedWithin()}
            value={filters.posted_within_days == null ? "" : String(filters.posted_within_days)}
            onChange={(v) => update({ posted_within_days: v === "" ? null : Number(v), offset: 0 })}
            options={[
              { value: "", label: radarFilterAny() },
              { value: "7", label: radarFilterDays({ count: 7 }) },
              { value: "30", label: radarFilterDays({ count: 30 }) },
              { value: "90", label: radarFilterDays({ count: 90 }) },
            ]}
          />
        </FilterGroup>

        <div className="filter-group">
          {/* One boolean, on the app's one boolean control, never an
              "Any / Discloses pay" pair wearing a 36px segmented control. */}
          <Switch
            checked={filters.discloses_pay}
            onChange={(on) => update({ discloses_pay: on, offset: 0 })}
          >
            <span>{radarFilterDisclosesPay()}</span>
          </Switch>
        </div>

        {/* The comp pair, kept together. "At least this much" is asked far
            more often than "at most", but one half of one filter on screen
            and the other behind a door would make a reader setting a range
            meet the same control in two places. Both are situational and
            both count on the door; they are ONE filter in `Filters · N`
            (`group: "comp"`). */}
        <FilterGroup title={<Abbr short={radarFilterPayFrom()} full={radarFilterPayFromFull()} />}>
          <div className="range-row">
            <PayBound
              placeholder={radarFilterMin()}
              label={radarFilterPayMinAria()}
              value={filters.base_min}
              onCommit={(next) => update({ base_min: next, offset: 0 })}
            />
          </div>
          {filters.base_min != null && (
            <div className="filter-hint">{radarInterpPayMin({ min: fmtComp(filters.base_min) })}</div>
          )}
        </FilterGroup>

        <FilterGroup title={<Abbr short={radarFilterPayUpTo()} full={radarFilterPayUpToFull()} />}>
          <div className="range-row">
            <PayBound
              placeholder={radarFilterMax()}
              label={radarFilterPayMaxAria()}
              value={filters.base_max}
              onCommit={(next) => update({ base_max: next, offset: 0 })}
            />
          </div>
          {filters.base_max != null && (
            <div className="filter-hint">{radarInterpPayMax({ max: fmtComp(filters.base_max) })}</div>
          )}
        </FilterGroup>

        {wpEntries.length > 0 && (
          <FacetGroup
            title={radarFieldWorkplace()}
            ariaLabel={radarFilterWorkplaceAria()}
            entries={wpEntries}
            selected={filters.workplace_type}
            onChange={(next) => update({ workplace_type: next, offset: 0 })}
          />
        )}
        {domainEntries.length > 0 && (
          <FacetGroup
            title={radarFieldWorld()}
            ariaLabel={radarFilterWorldAria()}
            entries={domainEntries}
            selected={filters.domain}
            onChange={(next) => update({ domain: next, offset: 0 })}
          />
        )}

        {/* Which POPULATION, last and lowest. Open roles is the board: its
            count is the top bar's own, and that count is the link back.
            Closed and Not-for-me are somewhere a reader goes on purpose,
            rarely, so a strip above every list would be three permanent
            controls for a decision almost nobody is making.
            Exclusive by construction: one segmented control, three positions,
            and the modes are a partition rather than three flags that can
            disagree. */}
        <FilterGroup title={radarFilterShowing()}>
          <Segmented
            label={radarFilterShowing()}
            value={mode}
            onChange={(next) => onModeChange(next as BoardMode)}
            options={BOARD_MODES.map((m) => ({ value: m, label: MODE_LABEL[m] }))}
          />
        </FilterGroup>
      </FilterDrawer>
    </FilterRegister>
  );
}
