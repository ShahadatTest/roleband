import { ResourceLoadState } from "../../ui/ResourceLoadState";
import { SearchField } from "../../ui/SearchField";
import { memo, useCallback, useDeferredValue, useEffect, useLayoutEffect, useRef, useState, type RefObject } from "react";
import { useAsyncResource } from "../../hooks/useAsyncResource";
import { useMeasuredCssSize } from "../../hooks/useMeasuredCssSize";
import { useBodyAttribute } from "../../hooks/useBodyAttribute";
import { PageHeader } from "../../patterns/PageHeader";
import { ResultsSummary } from "../../patterns/ResultsSummary";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { CompanyProfileSummary, api } from "../../api";
import { sectorName } from "../../copy/vocab";
import { companiesModelOtherCompanies } from "../../copy/gen/companies";
import { Button } from "../../ui/Button";
import { EmptyState } from "../../ui/EmptyState";
import { narrowedBy, type NarrowingFilter } from "../../ui/emptyFilters";
import { Icon } from "../../ui/Icon";
import { Switch } from "../../ui/Switch";
import { CompanyLogo } from "./CompanyLogo";
import { CompanyProfilePanel } from "./CompanyProfilePanel";
import { HEALTH_LABEL } from "./labels";
import { DATASET_SECTION, NO_SECTOR, groupOf, renderOrder, rosterSections, type RosterGroup } from "./roster";
// The register material is this screen's OWN dependency, not a loan: it
// supplies the token overrides `data-material="register"` switches on.
// Companies and Intelligence each import it for the same reason. Relying on
// tabs.tsx eagerly importing Companies would be an undeclared dependency that
// a code-split breaks into a screen with none of the material's paper. The
// toolbar's switch does not depend on it: ui/Switch carries its own CSS.
import "../../design/materials/register-material.css";
import "./company-profiles.css";
import {
  profilesCompanyProfilePanelRetry,
  profilesCompanyProfilesViewAll,
  profilesCompanyProfilesViewAllProfilesCurrent,
  profilesCompanyProfilesViewBackToEveryCompanyProfile,
  profilesCompanyProfilesViewClearTheSearch,
  profilesCompanyProfilesViewCompanies,
  profilesCompanyProfilesViewCompaniesUnavailable,
  profilesCompanyProfilesViewCouldNotLoadCompanies,
  profilesCompanyProfilesViewLoadingCompanies,
  profilesCompanyProfilesViewEnrichFields,
  profilesCompanyProfilesViewFindACompanyOrTicker,
  profilesCompanyProfilesViewMatch,
  profilesCompanyProfilesViewNeedReview,
  profilesCompanyProfilesViewNeedsReviewOnly,
  profilesCompanyProfilesViewNoCompaniesToShow,
  profilesCompanyProfilesViewSearchCompanies,
  profilesCompanyProfilesViewSettingsCompanies,
  profilesCompanyProfilesViewShowAll,
  profilesCompanyProfilesViewShowAllCompanies,
  profilesCompanyProfilesViewThatNeedReview,
  profilesCompanyProfilesViewToSee,
  profilesCompanyProfilesViewToStartOver,
  profilesCompanyProfilesViewTrackOneInAndIts,
  profilesCompanyProfilesViewYouAreNotTrackingAny,
  profilesRosterDataset,
  profilesRosterDatasetHint,
  profilesRosterNoSector,
  profilesRosterOtherHint,
} from "../../copy/gen/profiles";
import { Msg } from "../../ui/Msg";
import { errorText } from "../../api/errorText";
import { shellNavCompanies } from "../../copy/gen/shell";

// The material rides on `body` so anything portalled outside this tree is
// painted by the same register material as the screen (as on Companies and
// Settings > Intelligence; see design/materials/).
//
// The roster leads with the companies RoleBand researched, folded by the
// sectors Settings lists them under, then everyone else the user follows
// (`./roster.ts`). The ticker on a row says a company is listed.

const EMPTY: ReadonlySet<string> = new Set();

function toggled(set: ReadonlySet<string>, key: string): ReadonlySet<string> {
  const next = new Set(set);
  if (!next.delete(key)) next.add(key);
  return next;
}

function groupLabel(group: RosterGroup): string {
  if (group.sector) return sectorName(group.sector);
  return group.key === NO_SECTOR ? profilesRosterNoSector() : companiesModelOtherCompanies();
}

/* The company list scrolls on its own, so it must END inside the window: a
 * list taller than the room below it hides its last rows past the bottom edge,
 * where neither its own scroll nor the page's reaches them. That room is not a
 * constant. At rest the page title sits above the list; once the page scrolls
 * the title away the list sticks under the toolbar and the room grows. So it is
 * measured, from the list's top to the scrollport's bottom, on every scroll and
 * resize, and written as `--prof-list-room` for the stylesheet to subtract its
 * margin from. It is written only when it changes, which is during the first
 * stretch of a scroll; after the list sticks every read returns the same. */
function useListRoom(
  rootRef: RefObject<HTMLElement | null>,
  listRef: RefObject<HTMLDivElement | null>,
  ready: boolean,
) {
  useLayoutEffect(() => {
    const main = rootRef.current;
    const list = listRef.current;
    if (!ready || !main || !list) return;
    let written = "";
    const fit = () => {
      const room = main.getBoundingClientRect().bottom - list.getBoundingClientRect().top;
      const value = `${Math.max(0, Math.floor(room))}px`;
      if (value === written) return;
      list.style.setProperty("--prof-list-room", value);
      written = value;
    };
    fit();
    main.addEventListener("scroll", fit, { passive: true });
    window.addEventListener("resize", fit);
    const observer = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(fit);
    observer?.observe(main);
    return () => {
      main.removeEventListener("scroll", fit);
      window.removeEventListener("resize", fit);
      observer?.disconnect();
      list.style.removeProperty("--prof-list-room");
    };
  }, [rootRef, listRef, ready]);
}

function RosterRow({
  company: c,
  selected,
  onSelect,
}: {
  company: CompanyProfileSummary;
  selected: boolean;
  onSelect: (slug: string) => void;
}) {
  return (
    <li>
      <button
        aria-current={selected ? "true" : undefined}
        // Without this the button has no accessible name at all.
        aria-label={
          c.data_health === "ok"
            ? c.display_name
            : `${c.display_name} — ${HEALTH_LABEL[c.data_health]}`
        }
        onClick={() => onSelect(c.slug)}
      >
        <CompanyLogo
          slug={c.slug}
          name={c.display_name}
          logoUrl={c.logo_url}
          brandColor={c.brand_color}
          size={22}
        />
        <span className="prof-nav-name">{c.display_name}</span>
        {c.ticker && <span className="traj-ticker">{c.ticker}</span>}
        {c.data_health !== "ok" && (
          // Compact marker — the full story sits on the flagged
          // field, so the company name keeps its space.
          <span
            className={`health-dot health-${c.data_health}`}
            title={HEALTH_LABEL[c.data_health]}
          />
        )}
      </button>
    </li>
  );
}

/* One folding group. Folded, it is a head and a count, so the dataset reads as
 * sector names instead of a thousand rows; the rows are not rendered at all
 * until it opens, which also keeps the large Other companies group off the
 * first paint. The disclosure is the register's (`ledger-sector-disclose`):
 * a link-variant Button carrying `aria-expanded`. */
function RosterGroupView({
  group,
  label,
  hint,
  level,
  open,
  onToggle,
  selected,
  onSelect,
}: {
  group: RosterGroup;
  label: string;
  hint?: string;
  /** `section` when the group IS its section (Other companies has no sectors). */
  level: "group" | "section";
  open: boolean;
  onToggle: () => void;
  selected: string;
  onSelect: (slug: string) => void;
}) {
  const Head = level === "section" ? "h3" : "h4";
  return (
    <section className={level === "section" ? "prof-group prof-group-section" : "prof-group prof-group-fold"} aria-label={label}>
      <Head className="prof-group-head">
        <Button variant="link" className="prof-group-disclose" aria-expanded={open} onClick={onToggle}>
          <Icon name={open ? "chevronUp" : "chevronDown"} size={14} />
          {label}
        </Button>
        <span className="prof-group-count">{group.members.length}</span>
      </Head>
      {hint && <div className="prof-group-hint">{hint}</div>}
      {open && (
        <ul className="prof-nav" aria-label={label}>
          {group.members.map((c) => (
            <RosterRow key={c.slug} company={c} selected={selected === c.slug} onSelect={onSelect} />
          ))}
        </ul>
      )}
    </section>
  );
}

/* The selector rail's empty state, on the inline variant: it is a 260px column
 * beside the profile it drives, and the page variant's 88px radar and centred
 * heading are sized for a screen's whole content column.
 *
 * The list narrows on BOTH the query and the review switch, so a sentence
 * chosen on the query alone would answer "No company matches" about a healthy
 * company sitting in the roster while the switch is on. `reasons` is measured
 * by the caller (ui/emptyFilters), so this only reads it out.
 */
function RosterEmpty({
  query,
  reasons,
  onClearQuery,
  onShowAll,
}: {
  query: string;
  reasons: NarrowingFilter<"query" | "review">[];
  onClearQuery: () => void;
  onShowAll: () => void;
}) {
  const search = reasons.find((reason) => reason.key === "query");
  const review = reasons.find((reason) => reason.key === "review");
  const title = profilesCompanyProfilesViewNoCompaniesToShow({ choice: (search) ? (review) ? "v1" : "v2" : (review) ? "v3" : "v4", query: (search) ? (review) ? String(query.trim()) : "" : "", query2: (search) ? (review) ? "" : String(query.trim()) : "" });

  return (
    <EmptyState variant="inline" title={title}>
      {review && (
        <>
          <Button variant="link" onClick={onShowAll}>
            {profilesCompanyProfilesViewShowAllCompanies()}
          </Button>{" "}
          <Msg of={profilesCompanyProfilesViewToSee} elems={{ value: " " }} />
          {profilesCompanyProfilesViewAll({ choice: (search) ? "yes" : "no", released: (search) ? review.released : "", value: (search) ? profilesCompanyProfilesViewMatch({ count: review.released }) : "", released2: (search) ? "" : review.released })}
          .{" "}
        </>
      )}
      {search && (
        <>
          <Button variant="link" onClick={onClearQuery}>
            {profilesCompanyProfilesViewClearTheSearch()}
          </Button>{" "}
          {profilesCompanyProfilesViewToStartOver()}
        </>
      )}
    </EmptyState>
  );
}

/* The open dossier, drawn again only when its company, the mode or the
   refresh verb changes: never for a keystroke in the list beside it. */
const ShownProfile = memo(CompanyProfilePanel);

export function CompanyProfilesView() {
  const rootRef = useRef<HTMLElement>(null);
  const toolbarRef = useRef<HTMLDivElement>(null);
  useMeasuredCssSize({ rootRef, elementRef: toolbarRef, property: "--prof-toolbar-h", ignoreZero: true });
  useBodyAttribute("data-material", "register");
  const [query, setQuery] = useState("");
  // The list follows the box one render behind, so a keystroke paints the box
  // at once and the matching rows come in a render the next one can interrupt.
  const shownQuery = useDeferredValue(query);
  const [reviewOnly, setReviewOnly] = useState(false);
  // Enrichment is a mode, not the resting state — see the toolbar button. It
  // survives switching companies on purpose: correcting data is a pass across
  // the roster, not a per-dossier errand.
  const [enriching, setEnriching] = useState(false);
  // Which groups are open. At rest every group is folded except the one
  // holding the company on screen, unfolded once each time the selection
  // changes (`revealed`), so a deep link to /company/stripe lands with Fintech
  // open and a group the reader folds stays folded.
  const [open, setOpen] = useState<ReadonlySet<string>>(EMPTY);
  const [revealed, setRevealed] = useState<string | null>(null);
  // While a search or the review lens narrows the list, every group with a
  // match is open, so a result is never hidden inside a fold. What the reader
  // folds during that narrowing is kept apart and dropped when it changes.
  const [narrowFolded, setNarrowFolded] = useState<{ key: string; folded: ReadonlySet<string> }>({
    key: "",
    folded: EMPTY,
  });
  // Selection lives in the URL path (`/company/:slug`) so a company profile is
  // deep-linkable and consistent with the nested position URL — the job→company hover card
  // navigates straight here.
  const navigate = useNavigate();
  const { slug: slugParam } = useParams();
  const [searchParams] = useSearchParams();

  // A deep link in the query form (`?slug=`) is redirected to the path form
  // (replace, and strip the query), so a shared or bookmarked link in that
  // form keeps working.
  const legacySlug = searchParams.get("slug");
  useEffect(() => {
    if (legacySlug) navigate(`/company/${encodeURIComponent(legacySlug)}`, { replace: true });
  }, [legacySlug, navigate]);

  // Selection within the master-detail list is a slice, not a new destination,
  // so it replaces (no history entry per company clicked).
  const selectCompany = useCallback(
    (slug: string) => {
      navigate(`/company/${encodeURIComponent(slug)}`, { replace: true });
    },
    [navigate],
  );

  // A failed fetch must fail loudly and offer a retry rather than spinning
  // forever, which is what a stale API (one that does not serve
  // /api/company-profiles yet) would otherwise look like.
  const roster = useAsyncResource((signal) => api.companyProfiles(signal), [], { keep: "company-profiles" });
  const list = roster.data?.items ?? null;
  // A resolved field moves the company's health badge. The list re-reads in
  // place, so the toolbar, the list and the open profile stay mounted.
  const refreshRoster = roster.refresh;
  const onResolved = useCallback(() => void refreshRoster({ preserveData: true }), [refreshRoster]);
  const listRef = useRef<HTMLDivElement>(null);
  useListRoom(rootRef, listRef, list !== null && list.length > 0);
  // A company arriving by link may sit a thousand rows down: bring its row into
  // the list's own view. The list scrolls, never the page (`scrollIntoView`
  // would move the profile too), and a row already in view stays put.
  useEffect(() => {
    const box = listRef.current;
    const row = box?.querySelector<HTMLElement>('[aria-current="true"]');
    if (!box || !row) return;
    const top = row.getBoundingClientRect().top - box.getBoundingClientRect().top;
    if (top < 0 || top + row.offsetHeight > box.clientHeight) box.scrollTop += top - box.clientHeight / 3;
  }, [slugParam, list]);
  // Every state leads with the page's heading, so the outline never starts
  // below the screen it is on.
  if (roster.error) {
    return (
      <main className="main prof-main" data-design-system="app" ref={rootRef}>
        <PageHeader title={profilesCompanyProfilesViewCompanies()} />
        <div className="panel" role="alert">
          <h2>{profilesCompanyProfilesViewCompaniesUnavailable()}</h2>
          <div className="empty-hint">
            {errorText(roster.error, profilesCompanyProfilesViewCouldNotLoadCompanies())}
          </div>
          <Button variant="link" onClick={roster.retry}>
            {profilesCompanyProfilePanelRetry()}
          </Button>
        </div>
      </main>
    );
  }

  if (!list) {
    return (
      <main className="main prof-main" data-design-system="app" ref={rootRef}>
        <PageHeader title={profilesCompanyProfilesViewCompanies()} />
        <ResourceLoadState error={null} loading={profilesCompanyProfilesViewLoadingCompanies()} />
      </main>
    );
  }

  /* One screen, one empty voice.
   *
   * `ensure_company_profiles` materializes a profile for every TRACKED company
   * on API startup, so an empty roster means exactly one thing: nothing is
   * tracked. It is not a dead end and it does not need a generic link: the
   * cause is knowable, so the state says it and points at the one place that
   * fixes it.
   *
   * It returns before the toolbar and the shell because each would make its
   * own claim about this state: the selector rail's empty state, the profile
   * pane's, and a toolbar count over a search box with nothing to search.
   */
  if (list.length === 0) {
    return (
      <main className="main prof-main" data-design-system="app" ref={rootRef}>
        <PageHeader title={shellNavCompanies()} />
        <EmptyState title={profilesCompanyProfilesViewYouAreNotTrackingAny()}>
          <Msg of={profilesCompanyProfilesViewTrackOneInAndIts} elems={{ link: <Link to="/settings/companies">{profilesCompanyProfilesViewSettingsCompanies()}</Link> }} />
        </EmptyState>
      </main>
    );
  }

  const needsReview = list.filter((c) => c.data_health !== "ok");

  // The API sends one alphabetical run across every company, but the list
  // RENDERS in group order, so `list[0]` is not the first row on screen.
  // Landing must select the company the eye is pointed at: fall back along
  // the order that actually draws the list.
  const sectorOrder = roster.data?.sectors ?? [];
  const inRenderOrder = renderOrder(rosterSections(list, sectorOrder));

  // The URL is the source of truth; fall back to the first company when the param
  // is absent or points at an unknown slug (a stale deep link), without dirtying
  // the URL until the user actually picks something. The roster is non-empty by
  // here and the two groups partition it, so there is always one to fall back to.
  const selected =
    slugParam && list.some((c) => c.slug === slugParam) ? slugParam : inRenderOrder[0].slug;

  // Unfold the selected company's group when the selection changes. State
  // adjusted during render, React's pattern for state derived from a prop.
  if (selected !== revealed) {
    setRevealed(selected);
    const home = groupOf(rosterSections(list, sectorOrder), selected);
    if (home && !open.has(home)) setOpen(new Set(open).add(home));
  }

  // Match on name OR ticker — you are as likely to think "NFLX" as "Netflix".
  const q = shownQuery.trim().toLowerCase();
  const matches = q
    ? list.filter(
        (c) =>
          c.display_name.toLowerCase().includes(q) ||
          c.slug.toLowerCase().includes(q) ||
          (c.ticker ?? "").toLowerCase().includes(q),
      )
    : list;
  const shown = reviewOnly ? matches.filter((c) => c.data_health !== "ok") : matches;

  // What is narrowing the list RIGHT NOW, for the toolbar. The count must
  // describe the list below it, as the group heads do (they count `shown`),
  // never the whole roster. The Board's two shapes decide which reading
  // applies: the query NARROWS the roster, so it earns a fraction; the lens is
  // a different list, so it is named and takes no denominator.
  //
  // The EMPTY case is measured rather than guessed, by `ui/emptyFilters`:
  // `narrowedBy` re-runs this list's own predicate with one filter released,
  // which is strictly better than reading these two booleans in order and is
  // why the empty state does not share them.
  const searching = q !== "";
  const reviewShown = shown.filter((c) => c.data_health !== "ok").length;

  const sections = rosterSections(shown, sectorOrder);
  const narrowing = searching || reviewOnly;
  const narrowKey = `${q}\u0000${reviewOnly}`;
  const folded = narrowFolded.key === narrowKey ? narrowFolded.folded : EMPTY;
  const isOpen = (key: string) => (narrowing ? !folded.has(key) : open.has(key));
  const toggle = (key: string) =>
    narrowing ? setNarrowFolded({ key: narrowKey, folded: toggled(folded, key) }) : setOpen(toggled(open, key));

  return (
    <main className="main prof-main" data-design-system="app" ref={rootRef}>
      {/* The same page header every screen leads with (page-hero, surfaces.css)
          and, like the settings register, it is what SCROLLS AWAY while the
          toolbar below freezes. */}
      <PageHeader title={profilesCompanyProfilesViewCompanies()} />

      {/* Search and the roster's counts sit on top of everything, the same
          band the settings register leads with. */}
      <div className="prof-toolbar" ref={toolbarRef}>
        <SearchField
          className="prof-search-box"
          label={profilesCompanyProfilesViewSearchCompanies()}
          placeholder={profilesCompanyProfilesViewFindACompanyOrTicker()}
          value={query}
          onChange={setQuery}
        />
        {/* The shared count, on the Board's two shapes. Both halves describe
            the list underneath, not the whole roster: the fraction states the
            search narrowing, and the review clause counts what is SHOWN. No
            reset here for the query: Reset all has one scope app-wide and it
            is never the search. */}
        <ResultsSummary
          count={shown.length}
          total={searching && !reviewOnly ? list.length : null}
          noun="company"
          meta={reviewOnly ? (
            <>{" "}<span>{profilesCompanyProfilesViewThatNeedReview({ count: shown.length })}</span></>
          ) : (
            <>
              {" "}<span className="results-sep" aria-hidden="true">·</span>{" "}
              {reviewShown === 0 ? (
                <span id="prof-review-why">{profilesCompanyProfilesViewAllProfilesCurrent()}</span>
              ) : (
                <>
                  <b className="is-warn">{reviewShown}</b>{" "}
                  <span>{profilesCompanyProfilesViewNeedReview({ count: reviewShown })}</span>
                </>
              )}
            </>
          )}
          reset={reviewOnly && (
            <Button variant="link" className="ui-btn-quiet" onClick={() => setReviewOnly(false)}
              title={profilesCompanyProfilesViewBackToEveryCompanyProfile()}>
              {profilesCompanyProfilesViewShowAll()}
            </Button>
          )}
        />
        <div className="prof-toolbar-end">
          <Switch
            checked={reviewOnly}
            disabled={needsReview.length === 0 && !reviewOnly}
            describedBy={needsReview.length === 0 && !reviewOnly ? "prof-review-why" : undefined}
            onChange={setReviewOnly}
          >
            {profilesCompanyProfilesViewNeedsReviewOnly()}
          </Switch>
          {/* Correcting data is a decision, not something a dossier asks for
              the moment you open it. The flagged field still SAYS it is
              flagged; this is what hands you the controls to settle it. Same
              slot the register keeps for Follow all. */}
          <Button
            variant="ghost"
            className="ui-btn-strong"
            aria-pressed={enriching}
            onClick={() => setEnriching((on) => !on)}
          >
            <Icon name="edit" size={16} />
            {profilesCompanyProfilesViewEnrichFields()}
          </Button>
        </div>
      </div>

      {/* The selector and the profile it drives are ONE block. Without this
          wrapper each column is a direct child of `.main`, so the app-wide
          `.main > *` measure cap centres the profile inside its own track and
          strands it far from the list it belongs to on a wide screen. */}
      <div className="prof-shell">
        <div className="prof-list" ref={listRef}>
          {shown.length === 0 ? (
            <RosterEmpty
              query={shownQuery}
              // Each count is this list's own narrowing re-run with one filter
              // released, so the copy can never blame the wrong one.
              reasons={narrowedBy<"query" | "review">([
                {
                  key: "query",
                  active: q.length > 0,
                  released: reviewOnly ? needsReview.length : list.length,
                },
                { key: "review", active: reviewOnly, released: matches.length },
              ])}
              onClearQuery={() => setQuery("")}
              onShowAll={() => setReviewOnly(false)}
            />
          ) : (
            <>
              {sections.map((section) =>
                section.key === DATASET_SECTION ? (
                  <section className="prof-section" key={section.key} aria-label={profilesRosterDataset()}>
                    <h2 className="prof-section-head">
                      <span>{profilesRosterDataset()}</span>
                      <span className="prof-group-count">{section.count}</span>
                    </h2>
                    <div className="prof-group-hint">{profilesRosterDatasetHint()}</div>
                    {section.groups.map((group) => (
                      <RosterGroupView
                        key={group.key}
                        group={group}
                        label={groupLabel(group)}
                        level="group"
                        open={isOpen(group.key)}
                        onToggle={() => toggle(group.key)}
                        selected={selected}
                        onSelect={selectCompany}
                      />
                    ))}
                  </section>
                ) : (
                  <div className="prof-section" key={section.key}>
                    {section.groups.map((group) => (
                      <RosterGroupView
                        key={group.key}
                        group={group}
                        label={groupLabel(group)}
                        hint={profilesRosterOtherHint()}
                        level="section"
                        open={isOpen(group.key)}
                        onToggle={() => toggle(group.key)}
                        selected={selected}
                        onSelect={selectCompany}
                      />
                    ))}
                  </div>
                ),
              )}
            </>
          )}
        </div>
        <div className="prof-body">
          {/* `selected` falls back to the first company in render order, so a
              non-empty roster always has one — and an empty roster returned
              above. There is no third state for this pane to describe. */}
          <ShownProfile slug={selected} enriching={enriching} onResolved={onResolved} />
        </div>
      </div>
    </main>
  );
}
